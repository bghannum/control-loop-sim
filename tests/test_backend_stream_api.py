"""TestClient's websocket_connect(): start the service ticking with a
short dt, receive_json() a couple of times, assert the shape matches
TickRecord.
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_ws_streams_ticks(client):
    client.app.state.service._config["simulation"]["dt_seconds"] = 0.01
    client.post("/session/run", json={"running": True})

    with client.websocket_connect("/ws/ticks") as ws:
        first = ws.receive_json()
        second = ws.receive_json()

    client.post("/session/run", json={"running": False})

    for record in (first, second):
        assert set(record.keys()) == {
            "tick",
            "t_true",
            "t_sensed",
            "setpoint",
            "active_faults",
            "detector_flags",
            "controller_source",
            "proposed_action",
            "interlock_result",
            "interlock_reason",
            "override_active",
            "ai_fallback_active",
            "interlock_locked_out",
            "trip_strikes",
            "trip_lockout_threshold",
            "actuator_output",
        }
        assert record["proposed_action"]["source"] == "manual"

    assert second["tick"] > first["tick"]


def test_ws_disconnect_removes_client(client):
    with client.websocket_connect("/ws/ticks"):
        assert len(client.app.state.service._clients) == 1

    assert len(client.app.state.service._clients) == 0
