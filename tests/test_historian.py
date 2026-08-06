"""Integration tests for Historian (Phase 4) against a real local
TimescaleDB (see docker-compose.yml). Skipped if the DB isn't reachable --
deliberately a real integration test, not mocked, since the point is
verifying the schema/hypertable/batching actually works against Postgres,
not just that our own code calls psycopg2 correctly.
See docs/control-loop-architecture.md §7.4.
"""

import time

import psycopg2
import pytest

from storage.historian import Historian

DSN = "postgresql://postgres:postgres@localhost:5432/control_loop_sim"


def _db_available() -> bool:
    try:
        psycopg2.connect(DSN, connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432")


def make_record(tick: int) -> dict:
    return {
        "tick": tick, "t_true": 300.0, "t_sensed": 300.1, "setpoint": 323.15,
        "controller_source": "manual", "actuator_output": 10.0 * tick,
        "interlock_result": "allow", "interlock_reason": "within bounds",
        "override_active": False, "active_faults": [],
        "detector_flags": {"spike": False, "drift": False, "stuck": False},
    }


@pytest.fixture
def clean_table():
    def truncate():
        conn = psycopg2.connect(DSN)
        conn.cursor().execute("TRUNCATE ticks")
        conn.commit()
        conn.close()

    truncate()
    yield
    truncate()


def test_construction_creates_hypertable_and_is_ready(clean_table):
    historian = Historian(DSN, batch_interval_s=0.5)
    assert historian.ready is True
    historian.close()


def test_record_does_not_block_and_flush_lands_rows(clean_table):
    historian = Historian(DSN, batch_interval_s=0.5)
    for i in range(1, 4):
        historian.record(make_record(i))
    assert historian._queue.qsize() == 3  # not yet flushed

    time.sleep(1.0)
    assert historian._queue.qsize() == 0

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT tick, actuator_output FROM ticks ORDER BY tick")
    rows = cur.fetchall()
    conn.close()
    historian.close()

    assert rows == [(1, 10.0), (2, 20.0), (3, 30.0)]


def test_close_performs_final_flush(clean_table):
    historian = Historian(DSN, batch_interval_s=100.0)  # long interval -- close() must flush explicitly
    historian.record(make_record(1))
    historian.close()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM ticks")
    count = cur.fetchone()[0]
    conn.close()

    assert count == 1


def test_flush_retries_schema_creation_and_recovers_once_db_available(clean_table):
    # Regression test: schema creation used to only be attempted once, at
    # construction -- a DB that was simply not up yet left the historian
    # permanently broken (inserting into a table that was never created)
    # for the rest of the session, even once the DB came online.
    bad_dsn = "postgresql://postgres:postgres@localhost:59999/nonexistent"
    historian = Historian(bad_dsn, batch_interval_s=100.0)  # long interval -- flush manually below
    assert historian.ready is False

    historian.record(make_record(1))
    historian.record(make_record(2))
    assert historian._queue.qsize() == 2

    historian._flush()  # DB still down -- retry fails, queued records must not be lost
    assert historian.ready is False
    assert historian._queue.qsize() == 2

    historian.dsn = DSN  # "the DB comes online" -- point at the real one and retry
    historian._flush()
    assert historian.ready is True
    assert historian._queue.qsize() == 0

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT tick FROM ticks ORDER BY tick")
    rows = cur.fetchall()
    conn.close()
    historian.close()

    assert rows == [(1,), (2,)]


def test_unreachable_db_does_not_raise_or_block():
    bad_dsn = "postgresql://postgres:postgres@localhost:59999/nonexistent"
    historian = Historian(bad_dsn, batch_interval_s=0.5)
    assert historian.ready is False

    start = time.time()
    historian.record(make_record(1))
    elapsed = time.time() - start
    assert elapsed < 0.1  # record() must never block

    historian.close()  # must not raise
