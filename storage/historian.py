"""Batched, async writes to TimescaleDB — never blocks the control loop.

The control loop only ever writes to the in-memory hot path (ControlLoop's
returned tick records); it never talks to the historian directly (see
docs/control-loop-architecture.md §7.4). It's the UI layer's job to fan
each tick out to both the hot-path list and this historian.

A background daemon thread drains a queue on its own schedule and
bulk-inserts into TimescaleDB. Every DB operation is wrapped so a failure
logs a warning and is retried next cycle -- it never raises into the
caller's thread, and `record()` never blocks (a bounded queue drops and
logs rather than backing up if the DB is down for a long stretch).

If TimescaleDB isn't reachable yet at construction (e.g. `docker compose
up` hasn't finished by the time Streamlit starts), schema creation is
retried on every flush cycle until it succeeds, rather than only once at
startup -- otherwise a DB that comes up seconds later would leave the
historian permanently broken for the rest of the session (inserts into a
table that was never created).

Threading, not a separate process or task queue, is the pragmatic choice
at this project's scale (a single-user Streamlit demo) -- see the
architecture doc's explicit non-goal of production-grade multi-user
support. A fresh connection is opened per flush rather than pooled, which
is fine at a 5-second batch interval but wouldn't scale past demo size.
"""

import json
import logging
import queue
import threading

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

CREATE_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS ticks (
    id BIGSERIAL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    tick INTEGER NOT NULL,
    t_true DOUBLE PRECISION,
    t_sensed DOUBLE PRECISION,
    setpoint DOUBLE PRECISION,
    controller_source TEXT,
    actuator_output DOUBLE PRECISION,
    interlock_result TEXT,
    interlock_reason TEXT,
    override_active BOOLEAN,
    active_faults TEXT[],
    detector_flags JSONB
);

SELECT create_hypertable('ticks', 'ts', if_not_exists => TRUE);
"""

INSERT_SQL = """
INSERT INTO ticks (
    tick, t_true, t_sensed, setpoint, controller_source, actuator_output,
    interlock_result, interlock_reason, override_active, active_faults, detector_flags
) VALUES %s
"""


class Historian:
    def __init__(
        self,
        dsn: str,
        batch_interval_s: float = 5.0,
        max_batch_size: int = 500,
        max_queue_size: int = 5000,
    ):
        self.dsn = dsn
        self.batch_interval_s = batch_interval_s
        self.max_batch_size = max_batch_size
        self.ready = False
        self._schema_failure_logged = False

        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        if psycopg2 is None:
            logger.warning("historian: psycopg2 not installed -- running as a no-op")
            return

        self._ensure_schema()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def record(self, tick_record: dict) -> None:
        if psycopg2 is None:
            return
        try:
            self._queue.put_nowait(tick_record)
        except queue.Full:
            logger.warning("historian: queue full (DB unavailable?) -- dropping tick %s", tick_record.get("tick"))

    def close(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._flush()  # best-effort final flush

    def _connect(self):
        return psycopg2.connect(self.dsn)

    def _ensure_schema(self) -> None:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(CREATE_SCHEMA_SQL)
            self.ready = True
            self._schema_failure_logged = False
        except Exception:
            # Full traceback only on the first failure -- this gets retried
            # every flush cycle while down (see _flush), and a fresh stack
            # trace every batch_interval_s for a long outage would just be
            # log noise once the cause is already known.
            if not self._schema_failure_logged:
                logger.warning("historian: could not reach TimescaleDB", exc_info=True)
                self._schema_failure_logged = True
            else:
                logger.warning("historian: still unable to reach TimescaleDB")
            self.ready = False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self.batch_interval_s)
            self._flush()

    def _flush(self) -> None:
        if not self.ready:
            # Schema creation failed at startup (or a prior flush) -- retry
            # it before touching the queue, so if TimescaleDB was simply
            # not up yet, writes recover on their own once it is. Checked
            # BEFORE draining the queue so a still-down DB doesn't lose
            # whatever's already waiting.
            self._ensure_schema()
            if not self.ready:
                return

        batch = []
        while len(batch) < self.max_batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not batch:
            return

        try:
            rows = [
                (
                    r["tick"], r["t_true"], r["t_sensed"], r["setpoint"],
                    r["controller_source"], r["actuator_output"],
                    r["interlock_result"], r["interlock_reason"], r["override_active"],
                    r["active_faults"], json.dumps(r["detector_flags"]),
                )
                for r in batch
            ]
            with self._connect() as conn, conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, INSERT_SQL, rows)
            self.ready = True
        except Exception:
            logger.warning("historian: batch write of %d records failed", len(batch), exc_info=True)
            self.ready = False
