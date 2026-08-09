"""Pydantic models at the API boundary -- same role config_schema.py plays
for config.yaml. Nothing downstream of this module deals with raw domain
dicts/dataclasses; everything crossing into JSON goes through here first.
"""

from pydantic import BaseModel


class ProposedActionOut(BaseModel):
    proposed_output_pct: float
    source: str
    confidence: str | None
    rationale: str | None
    flagged_sensor_concern: bool
    metadata: dict


class TickRecord(BaseModel):
    tick: int
    t_true: float
    t_sensed: float
    setpoint: float
    active_faults: list[str]
    detector_flags: dict[str, bool]
    controller_source: str
    proposed_action: ProposedActionOut
    interlock_result: str
    interlock_reason: str
    override_active: bool
    ai_fallback_active: bool
    interlock_locked_out: bool
    trip_strikes: int
    trip_lockout_threshold: int
    actuator_output: float

    @classmethod
    def from_domain(cls, record: dict) -> "TickRecord":
        action = record["proposed_action"]
        return cls(
            **{k: v for k, v in record.items() if k != "proposed_action"},
            proposed_action=ProposedActionOut(
                proposed_output_pct=action.proposed_output_pct,
                source=action.source,
                confidence=action.confidence,
                rationale=action.rationale,
                flagged_sensor_concern=action.flagged_sensor_concern,
                metadata=action.metadata,
            ),
        )


class ModeRequest(BaseModel):
    mode: str


class SetpointRequest(BaseModel):
    setpoint_c: float


class ManualRequest(BaseModel):
    heater_pct: float
    override_requested: bool


class PidGainsRequest(BaseModel):
    kp: float
    ki: float
    kd: float


class FaultToggleRequest(BaseModel):
    enabled: bool


class RunRequest(BaseModel):
    running: bool


class ResetRequest(BaseModel):
    seed: int | None = None


class ControlsOut(BaseModel):
    """Current control-surface state, independent of tick history -- lets a
    freshly-loaded or reconnected frontend render accurate values (setpoint,
    gains, fault toggles) even before the first tick lands, rather than
    guessing at config defaults client-side."""

    mode: str
    setpoint_c: float
    kp: float
    ki: float
    kd: float
    manual_heater_pct: float
    manual_override_requested: bool
    drift_enabled: bool
    stuck_enabled: bool


class ScenarioOut(BaseModel):
    name: str
    seed: int


class TriageResponse(BaseModel):
    success: bool
    fault_type: str | None = None
    severity: str | None = None
    explanation: str | None = None
    error: str | None = None
