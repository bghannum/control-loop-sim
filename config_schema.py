"""Validates config.yaml's shape once, at the boundary where it enters the
system -- not a refactor of how engine/ classes consume config. ControlLoop,
Detector, Interlock, etc. all still take plain nested dicts and already
fail fast (a missing key raises immediately in __init__, not "deep inside
a tick" -- construction happens once, at Reset). What this adds: a single,
complete error listing every missing/invalid field at once instead of
whichever KeyError happens to hit first, and basic type coercion (e.g. a
YAML value accidentally quoted as a string).

load_config() returns a plain dict (via model_dump()), not the Pydantic
model itself, specifically so nothing downstream has to change -- this is
purely an added checkpoint, not a new access pattern to adopt everywhere.
"""

from pydantic import BaseModel


class SimulationConfig(BaseModel):
    dt_seconds: float
    model_type: str


class FirstOrderModelParams(BaseModel):
    thermal_mass: float
    loss_coeff: float
    k_heat: float
    t_ambient: float
    t_initial: float


class ModelParamsConfig(BaseModel):
    first_order: FirstOrderModelParams


class SetpointConfig(BaseModel):
    default_k: float


class DetectorConfig(BaseModel):
    window_ticks: int
    z_score_threshold: float
    cusum_slack_k: float
    cusum_threshold_h: float
    stuck_variance_ratio: float
    boot_grace_ticks: int


class InterlockConfig(BaseModel):
    t_min_k: float
    t_max_k: float
    bound_margin_k: float
    max_delta_per_tick_pct: float
    trip_safe_output_pct: float
    untrusted_auto_safe_after_s: float
    trip_lockout_threshold: int
    trip_correction_tolerance_pct: float


class PIDConfig(BaseModel):
    kp: float
    ki: float
    kd: float


class AIConfig(BaseModel):
    model: str
    history_window_ticks: int
    max_response_wait_s: float
    fallback_after_s: float
    safe_output_pct: float


class SeededScenario(BaseModel):
    name: str
    seed: int


class SensorConfig(BaseModel):
    noise_sigma_k: float
    drift_rate_k_per_s: float
    spike_offset_k: float
    spike_duration_ticks: int
    seeded_scenarios: list[SeededScenario]


class AppConfig(BaseModel):
    simulation: SimulationConfig
    model_params: ModelParamsConfig
    setpoint: SetpointConfig
    detector: DetectorConfig
    interlock: InterlockConfig
    pid: PIDConfig
    ai: AIConfig
    sensor: SensorConfig


def load_config(path: str = "config.yaml") -> dict:
    """Read and validate path, returning a plain dict. Raises
    pydantic.ValidationError (one error listing every problem found, not
    just the first) if the file doesn't match the expected shape."""
    import yaml

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return AppConfig(**raw).model_dump()
