"""REST control surface -- one endpoint per app.py control, each a thin
pass-through to SimulationService (which itself passes through to
ControlLoop). See docs/phase-9a-backend-plan.md for the full endpoint table.
"""

from fastapi import APIRouter, Request

from backend.schemas import (
    ControlsOut,
    FaultToggleRequest,
    ManualRequest,
    ModeRequest,
    PidGainsRequest,
    ResetRequest,
    RunRequest,
    ScenarioOut,
    SetpointRequest,
    TickRecord,
    TriageResponse,
)

router = APIRouter()


def _service(request: Request):
    return request.app.state.service


@router.post("/control/mode")
def set_mode(body: ModeRequest, request: Request):
    _service(request).set_mode(body.mode)
    return {"mode": body.mode}


@router.post("/control/setpoint")
def set_setpoint(body: SetpointRequest, request: Request):
    _service(request).set_setpoint_c(body.setpoint_c)
    return {"setpoint_c": body.setpoint_c}


@router.post("/control/manual")
def set_manual(body: ManualRequest, request: Request):
    _service(request).set_manual(body.heater_pct, body.override_requested)
    return {"heater_pct": body.heater_pct, "override_requested": body.override_requested}


@router.post("/control/pid-gains")
def set_pid_gains(body: PidGainsRequest, request: Request):
    _service(request).set_pid_gains(body.kp, body.ki, body.kd)
    return {"kp": body.kp, "ki": body.ki, "kd": body.kd}


@router.post("/control/faults/drift")
def set_drift(body: FaultToggleRequest, request: Request):
    _service(request).set_drift(body.enabled)
    return {"enabled": body.enabled}


@router.post("/control/faults/stuck")
def set_stuck(body: FaultToggleRequest, request: Request):
    _service(request).set_stuck(body.enabled)
    return {"enabled": body.enabled}


@router.post("/control/faults/spike")
def trigger_spike(request: Request):
    _service(request).trigger_spike()
    return {"triggered": True}


@router.post("/session/run")
async def set_running(body: RunRequest, request: Request):
    service = _service(request)
    if body.running:
        await service.start()
    else:
        service.stop()
    return {"running": body.running}


@router.post("/session/reset")
def reset_session(body: ResetRequest, request: Request):
    _service(request).reset(seed=body.seed)
    return {"reset": True}


@router.post("/session/reset-interlock")
def reset_interlock(request: Request):
    _service(request).reset_interlock()
    return {"reset": True}


@router.post("/triage", response_model=TriageResponse)
def request_triage(request: Request):
    result = _service(request).request_triage()
    return TriageResponse(
        success=result.success,
        fault_type=result.fault_type,
        severity=result.severity,
        explanation=result.explanation,
        error=result.error,
    )


@router.get("/config/scenarios", response_model=list[ScenarioOut])
def get_scenarios(request: Request):
    return _service(request).get_scenarios()


@router.get("/state")
def get_state(request: Request):
    service = _service(request)
    return {
        "history": [TickRecord.from_domain(r) for r in service.history],
        "running": service.running,
        "mode": service.loop.mode,
        "controls": ControlsOut(**service.get_controls()),
    }
