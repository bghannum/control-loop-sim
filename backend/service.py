"""SimulationService: owns one ControlLoop and ticks it on a background
asyncio.Task, independent of any request or browser connection -- the one
idea Phase 9a is about (see docs/phase-9a-backend-plan.md). Everything else
here is a thin pass-through to ControlLoop's existing setters.
"""

import asyncio
import logging

from fastapi import WebSocket

from engine.anthropic_support import AnthropicClientLike
from engine.loop import ControlLoop
from engine.triage import Triage, TriageResult

from backend.schemas import TickRecord

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 500
K_OFFSET_C = 273.15  # Kelvin<->Celsius offset -- same constant app.py uses (doc §3.1: Celsius is display-only)


class SimulationService:
    def __init__(
        self, config: dict, seed: int | None = None, ai_client: AnthropicClientLike | None = None
    ):
        self._config = config
        self._ai_client = ai_client
        self.loop = ControlLoop(config, seed=seed, ai_client=ai_client)
        self.triage = Triage(
            client=ai_client,
            model=config["triage"]["model"],
            max_wait_s=config["triage"]["max_wait_s"],
        )
        self._triage_window = config["triage"]["history_window_ticks"]

        self.history: list[dict] = []
        self._manual_heater_pct = 0.0

        self._clients: set[WebSocket] = set()
        self._tick_task: asyncio.Task | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._running = True
        if self._tick_task is None or self._tick_task.done():
            self._tick_task = asyncio.create_task(self._tick_loop())

    def stop(self) -> None:
        self._running = False  # _tick_loop checks this each cycle and exits cleanly

    async def shutdown(self) -> None:
        self.stop()
        if self._tick_task is not None:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                record = self.loop.tick(self._manual_heater_pct)
                self.history.append(record)
                self.history = self.history[-HISTORY_LIMIT:]
                await self._broadcast(record)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("unhandled error in simulation tick loop -- continuing")
            await asyncio.sleep(self._config["simulation"]["dt_seconds"])

    async def _broadcast(self, record: dict) -> None:
        payload = TickRecord.from_domain(record).model_dump_json()
        dead = set()
        for ws in self._clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # -- control pass-throughs, one per REST endpoint --

    def set_mode(self, mode: str) -> None:
        self.loop.set_mode(mode)

    def set_setpoint_c(self, setpoint_c: float) -> None:
        self.loop.set_setpoint(setpoint_c + K_OFFSET_C)

    def set_manual(self, heater_pct: float, override_requested: bool) -> None:
        self._manual_heater_pct = heater_pct
        self.loop.set_manual_override_requested(override_requested)

    def set_pid_gains(self, kp: float, ki: float, kd: float) -> None:
        self.loop.set_pid_gains(kp, ki, kd)

    def set_drift(self, enabled: bool) -> None:
        self.loop.set_drift(enabled)

    def set_stuck(self, enabled: bool) -> None:
        self.loop.set_stuck(enabled)

    def trigger_spike(self) -> None:
        self.loop.trigger_spike()

    def reset(self, seed: int | None = None) -> None:
        self.loop = ControlLoop(self._config, seed=seed, ai_client=self._ai_client)
        self._manual_heater_pct = 0.0
        self.history = []

    def reset_interlock(self) -> None:
        self.loop.reset_interlock()

    def request_triage(self) -> TriageResult:
        window = self.history[-self._triage_window :]
        detector_flags = window[-1]["detector_flags"] if window else {}
        return self.triage.request(history=window, detector_flags=detector_flags)
