// Thin wrappers over backend/routers/control.py's REST surface -- one
// function per endpoint, all sharing the same fetch/JSON boilerplate 9b's
// App.tsx had inline for a single endpoint. Centralized now that every
// control (not just Run/Stop) goes through here.

import { API_BASE_URL } from "@/config";
import type { Scenario, StateResponse, TriageResponse } from "@/types";

async function post(path: string, body?: unknown): Promise<void> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
}

export async function fetchState(): Promise<StateResponse> {
  const res = await fetch(`${API_BASE_URL}/state`);
  if (!res.ok) throw new Error(`/state -> ${res.status}`);
  return res.json();
}

export async function fetchScenarios(): Promise<Scenario[]> {
  const res = await fetch(`${API_BASE_URL}/config/scenarios`);
  if (!res.ok) throw new Error(`/config/scenarios -> ${res.status}`);
  return res.json();
}

export const api = {
  setMode: (mode: string) => post("/control/mode", { mode }),
  setSetpoint: (setpoint_c: number) => post("/control/setpoint", { setpoint_c }),
  setManual: (heater_pct: number, override_requested: boolean) =>
    post("/control/manual", { heater_pct, override_requested }),
  setPidGains: (kp: number, ki: number, kd: number) => post("/control/pid-gains", { kp, ki, kd }),
  setDrift: (enabled: boolean) => post("/control/faults/drift", { enabled }),
  setStuck: (enabled: boolean) => post("/control/faults/stuck", { enabled }),
  triggerSpike: () => post("/control/faults/spike"),
  setRunning: (running: boolean) => post("/session/run", { running }),
  resetSession: (seed?: number | null) => post("/session/reset", { seed: seed ?? null }),
  resetInterlock: () => post("/session/reset-interlock"),
  async requestTriage(): Promise<TriageResponse> {
    const res = await fetch(`${API_BASE_URL}/triage`, { method: "POST" });
    if (!res.ok) throw new Error(`/triage -> ${res.status}`);
    return res.json();
  },
};
