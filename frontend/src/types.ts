// Mirrors backend/schemas.py -- kept in sync by hand for now (no codegen
// step in 9b's minimal scope).

export interface ProposedAction {
  proposed_output_pct: number;
  source: string;
  confidence: string | null;
  rationale: string | null;
  flagged_sensor_concern: boolean;
  metadata: Record<string, unknown>;
}

export interface TickRecord {
  tick: number;
  t_true: number;
  t_sensed: number;
  setpoint: number;
  active_faults: string[];
  detector_flags: Record<string, boolean>;
  controller_source: string;
  proposed_action: ProposedAction;
  interlock_result: string;
  interlock_reason: string;
  override_active: boolean;
  ai_fallback_active: boolean;
  interlock_locked_out: boolean;
  trip_strikes: number;
  trip_lockout_threshold: number;
  actuator_output: number;
}

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "lost";

export type ControllerMode = "manual" | "pid" | "ai";

export interface Controls {
  mode: ControllerMode;
  setpoint_c: number;
  kp: number;
  ki: number;
  kd: number;
  manual_heater_pct: number;
  manual_override_requested: boolean;
  drift_enabled: boolean;
  stuck_enabled: boolean;
}

export interface Scenario {
  name: string;
  seed: number;
}

export interface TriageResponse {
  success: boolean;
  fault_type: string | null;
  severity: string | null;
  explanation: string | null;
  error: string | null;
}

export interface StateResponse {
  history: TickRecord[];
  running: boolean;
  mode: ControllerMode;
  controls: Controls;
}
