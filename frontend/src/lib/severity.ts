// Single source of truth for severity classification -- the TS mirror of
// app.py's Phase 8 module-level GREEN/AMBER/RED/GRAY logic (render_status_strip,
// render_tile_row, decision_log_row_bg). Every component reads colors through
// here rather than re-deriving them, so the two frontends (Streamlit and this
// one) never drift apart on what counts as "critical."

import type { ConnectionStatus, TickRecord } from "@/types";

export type Severity = "green" | "amber" | "red" | "gray";

// Connection state deliberately lives outside the Severity type -- the
// mockup's own script constants color a live feed green but a dropped one
// violet, not red/amber, specifically so "the WebSocket hiccuped" can never
// read as "the plant tripped." Keeping it a separate type/map (rather than
// smuggling "violet" into Severity) makes that separation a compile-time
// guarantee, not just a convention.
export const CONNECTION_LABEL: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  open: "Live",
  reconnecting: "Reconnecting…",
  lost: "Connection lost",
};

export const CONNECTION_PILL_CLASS: Record<ConnectionStatus, string> = {
  connecting: "text-severity-gray bg-severity-gray-bg",
  open: "text-severity-green bg-severity-green-bg",
  reconnecting: "text-severity-violet bg-severity-violet-bg",
  lost: "text-severity-violet bg-severity-violet-bg",
};

export const CONNECTION_DOT_CLASS: Record<ConnectionStatus, string> = {
  connecting: "bg-severity-gray",
  open: "bg-severity-green",
  reconnecting: "bg-severity-violet",
  lost: "bg-severity-violet",
};

export const CONNECTION_PULSE: Record<ConnectionStatus, boolean> = {
  connecting: false,
  open: false,
  reconnecting: true,
  lost: false,
};

export const SEVERITY_DOT_CLASS: Record<Severity, string> = {
  green: "bg-severity-green",
  amber: "bg-severity-amber",
  red: "bg-severity-red",
  gray: "bg-severity-gray",
};

export const SEVERITY_TEXT_CLASS: Record<Severity, string> = {
  green: "text-severity-green",
  amber: "text-severity-amber",
  red: "text-severity-red",
  gray: "text-severity-gray",
};

export const SEVERITY_PILL_CLASS: Record<Severity, string> = {
  green: "text-severity-green bg-severity-green-bg",
  amber: "text-severity-amber bg-severity-amber-bg",
  red: "text-severity-red bg-severity-red-bg",
  gray: "text-severity-gray bg-severity-gray-bg",
};

export interface GlobalStatus {
  code: string;
  message: string;
  severity: Severity;
  // "square" marks the one operator-chosen critical state (manual override)
  // as visually distinct from system-imposed ones (lockout/hard-trip/AI
  // fallback) at the same severity tier -- the operator caused this one on
  // purpose. Mirrors the mockup's legend note on shape.
  shape: "circle" | "square";
}

// Mirrors app.py's render_status_strip(): priority locked out > hard trip
// firing > override active > AI fallback active > nominal. Hard-trip is
// detected from interlock_reason text (interlock.py already writes
// "...hard trip, forcing safe output..." for exactly this case) rather than
// a dedicated schema field -- same trick app.py uses, kept consistent here.
export function globalStatus(latest: TickRecord | null): GlobalStatus {
  if (latest === null) {
    return { code: "NOMINAL", message: "System nominal", severity: "green", shape: "circle" };
  }
  if (latest.interlock_locked_out) {
    return {
      code: "LOCKED OUT",
      message:
        'Repeated over-temperature trips without correction — heater forced to safe output. Press "Reset Interlock" once conditions are confirmed safe.',
      severity: "red",
      shape: "circle",
    };
  }
  if (latest.interlock_reason.toLowerCase().includes("hard trip")) {
    return {
      code: "HARD TRIP",
      message: "Sensed temperature at or past a hard bound — actuator forced to a safe output regardless of source.",
      severity: "red",
      shape: "circle",
    };
  }
  if (latest.override_active) {
    return {
      code: "OVERRIDE ACTIVE",
      message: "Interlock override active — operating outside validated safety bounds.",
      severity: "red",
      shape: "square",
    };
  }
  if (latest.ai_fallback_active) {
    return {
      code: "AI FALLBACK",
      message: "AI controller unresponsive — automatic safe fallback active.",
      severity: "red",
      shape: "circle",
    };
  }
  return {
    code: "NOMINAL",
    message: "System nominal — all proposals within validated bounds.",
    severity: "green",
    shape: "circle",
  };
}

// Mirrors app.py's decision_log_row_bg(): "none" (no tint) for a plain
// allow, distinct from a tile's plain "green" -- the decision log only
// tints rows that need attention.
export function decisionLogRowSeverity(record: TickRecord): "red" | "amber" | "none" {
  const reason = record.interlock_reason.toLowerCase();
  if (record.interlock_locked_out || record.override_active || reason.includes("hard trip") || reason.includes("lockout")) {
    return "red";
  }
  if (record.interlock_result === "clamp" || record.interlock_result === "reject" || reason.includes("untrusted")) {
    return "amber";
  }
  return "none";
}

export function anyDetectorFlag(record: TickRecord): boolean {
  return Object.values(record.detector_flags).some(Boolean);
}

export function sensedTempSeverity(record: TickRecord): Severity {
  return anyDetectorFlag(record) ? "red" : "green";
}

export function faultSeverity(record: TickRecord): Severity {
  return record.active_faults.length > 0 ? "red" : "green";
}

export function historianSeverity(connected: boolean): Severity {
  // Never red -- a missing historian is "not blocking," not a safety concern.
  return connected ? "green" : "gray";
}

export function tripStrikeSeverity(record: TickRecord): Severity {
  if (record.interlock_locked_out) return "red";
  if (record.trip_strikes > 0) return "amber";
  return "green";
}
