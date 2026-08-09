"""FastAPI TestClient: POST each control endpoint, assert both the HTTP
response and that service.loop's actual state changed (whitebox, same
style already used elsewhere in this suite).
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def service(client):
    return client.app.state.service


def test_set_mode(client):
    resp = client.post("/control/mode", json={"mode": "pid"})
    assert resp.status_code == 200
    assert service(client).loop.mode == "pid"


def test_set_setpoint(client):
    resp = client.post("/control/setpoint", json={"setpoint_c": 75.0})
    assert resp.status_code == 200
    assert service(client).loop.setpoint == pytest.approx(348.15)


def test_set_manual(client):
    resp = client.post("/control/manual", json={"heater_pct": 33.0, "override_requested": True})
    assert resp.status_code == 200
    svc = service(client)
    assert svc._manual_heater_pct == 33.0
    assert svc.loop.manual_override_requested is True


def test_set_pid_gains(client):
    resp = client.post("/control/pid-gains", json={"kp": 5.0, "ki": 0.2, "kd": 0.05})
    assert resp.status_code == 200
    pid = service(client).loop.pid
    assert (pid.kp, pid.ki, pid.kd) == (5.0, 0.2, 0.05)


def test_toggle_drift(client):
    resp = client.post("/control/faults/drift", json={"enabled": True})
    assert resp.status_code == 200
    assert "drift" in service(client).loop.sensor.active_faults()


def test_toggle_stuck(client):
    resp = client.post("/control/faults/stuck", json={"enabled": True})
    assert resp.status_code == 200
    assert "stuck" in service(client).loop.sensor.active_faults()


def test_trigger_spike(client):
    resp = client.post("/control/faults/spike")
    assert resp.status_code == 200
    assert resp.json() == {"triggered": True}


def test_run_toggle_starts_and_stops_ticking(client):
    resp = client.post("/session/run", json={"running": True})
    assert resp.status_code == 200
    assert service(client).running is True

    resp = client.post("/session/run", json={"running": False})
    assert resp.status_code == 200
    assert service(client).running is False


def test_reset_session(client):
    svc = service(client)
    old_loop = svc.loop
    resp = client.post("/session/reset", json={"seed": 3})
    assert resp.status_code == 200
    assert service(client).loop is not old_loop


def test_reset_interlock(client):
    svc = service(client)
    svc.loop.interlock.locked_out = True
    resp = client.post("/session/reset-interlock")
    assert resp.status_code == 200
    assert svc.loop.interlock.locked_out is False


def test_triage_endpoint_no_client_configured(client):
    resp = client.post("/triage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["error"] is not None


def test_get_state(client):
    resp = client.get("/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"history": [], "running": False, "mode": "manual"}
