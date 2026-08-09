"""SimulationService, no HTTP: the background tick loop, control
pass-throughs, and broadcast to fake WebSocket-like clients.
"""

import asyncio

import pytest

from backend.service import SimulationService
from config_schema import load_config


def make_service(**overrides) -> SimulationService:
    config = load_config("config.yaml")
    config["simulation"]["dt_seconds"] = 0.01  # fast ticks for tests
    config.update(overrides)
    return SimulationService(config, seed=42)


class FakeWebSocket:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.received: list[str] = []

    async def send_text(self, payload: str) -> None:
        if self.fail:
            raise RuntimeError("connection reset")
        self.received.append(payload)


def test_start_ticks_in_background_and_grows_history():
    async def run():
        service = make_service()
        await service.start()
        await asyncio.sleep(0.05)
        service.stop()
        await service.shutdown()
        assert len(service.history) >= 2

    asyncio.run(run())


def test_stop_halts_ticking():
    async def run():
        service = make_service()
        await service.start()
        await asyncio.sleep(0.03)
        service.stop()
        await asyncio.sleep(0.02)
        count_after_stop = len(service.history)
        await asyncio.sleep(0.03)
        assert len(service.history) == count_after_stop
        await service.shutdown()

    asyncio.run(run())


def test_broadcast_reaches_connected_clients_and_drops_dead_ones():
    async def run():
        service = make_service()
        good = FakeWebSocket()
        bad = FakeWebSocket(fail=True)
        service._clients = {good, bad}
        await service.start()
        await asyncio.sleep(0.03)
        service.stop()
        await service.shutdown()
        assert len(good.received) >= 1
        assert bad not in service._clients
        assert good in service._clients

    asyncio.run(run())


def test_tick_loop_survives_unhandled_exception():
    async def run():
        service = make_service()

        real_tick = service.loop.tick
        calls = {"n": 0}

        def flaky_tick(manual_input_pct=0.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated failure")
            return real_tick(manual_input_pct)

        service.loop.tick = flaky_tick
        await service.start()
        await asyncio.sleep(0.05)
        service.stop()
        await service.shutdown()
        assert calls["n"] >= 2
        assert len(service.history) >= 1  # ticks after the failure still recorded

    asyncio.run(run())


def test_reset_rebuilds_loop_and_clears_history():
    async def run():
        service = make_service()
        await service.start()
        await asyncio.sleep(0.03)
        service.stop()
        await service.shutdown()
        assert len(service.history) > 0

        old_loop = service.loop
        service.reset(seed=7)
        assert service.loop is not old_loop
        assert service.history == []

    asyncio.run(run())


def test_reset_interlock_delegates():
    service = make_service()
    service.loop.interlock.locked_out = True
    service.reset_interlock()
    assert service.loop.interlock.locked_out is False


def test_control_passthroughs():
    service = make_service()

    service.set_mode("pid")
    assert service.loop.mode == "pid"

    service.set_setpoint_c(60.0)
    assert service.loop.setpoint == pytest.approx(333.15)

    service.set_manual(42.0, override_requested=True)
    assert service._manual_heater_pct == 42.0
    assert service.loop.manual_override_requested is True

    service.set_pid_gains(1.0, 2.0, 3.0)
    assert (service.loop.pid.kp, service.loop.pid.ki, service.loop.pid.kd) == (1.0, 2.0, 3.0)

    service.set_drift(True)
    assert "drift" in service.loop.sensor.active_faults()

    service.set_stuck(True)
    assert "stuck" in service.loop.sensor.active_faults()
