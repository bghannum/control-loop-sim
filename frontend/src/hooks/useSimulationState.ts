// The app's one state store: WebSocket connection + tick buffer + current
// control-surface values + the actions that mutate them. A plain hook is
// enough at this project's scope (single operator, single client, no
// concurrent writers to reconcile against) -- no need for a state library.
import { useCallback, useEffect, useRef, useState } from "react";

import { WS_URL } from "@/config";
import { api, fetchScenarios, fetchState } from "@/lib/api";
import type { ConnectionStatus, ControllerMode, Controls, Scenario, TickRecord, TriageResponse } from "@/types";

const MAX_TICKS = 200; // mirrors backend's own HISTORY_LIMIT-bounded rolling window
const BASE_DELAY_MS = 500;
const MAX_DELAY_MS = 8000;
const LOST_AFTER_ATTEMPTS = 5;

const DEFAULT_CONTROLS: Controls = {
  mode: "manual",
  setpoint_c: 50,
  kp: 2,
  ki: 0.5,
  kd: 0.1,
  manual_heater_pct: 0,
  manual_override_requested: false,
  drift_enabled: false,
  stuck_enabled: false,
};

export function useSimulationState() {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [ticks, setTicks] = useState<TickRecord[]>([]);
  const [running, setRunning] = useState(false);
  const [controls, setControls] = useState<Controls>(DEFAULT_CONTROLS);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [lastMessageAt, setLastMessageAt] = useState<number | null>(null);
  const [lastTriage, setLastTriage] = useState<TriageResponse | null>(null);
  const [triageLoading, setTriageLoading] = useState(false);

  const attemptsRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const unmountedRef = useRef(false);

  const appendTick = useCallback((record: TickRecord) => {
    setTicks((prev) => {
      // Guards against a live tick racing ahead of resyncFromServer's fetch
      // resolving, or a duplicate delivered right at reconnect -- ticks are
      // strictly increasing, so anything not newer than what's already
      // buffered is dropped rather than concatenated.
      if (prev.length > 0 && record.tick <= prev[prev.length - 1].tick) return prev;
      return [...prev.slice(-(MAX_TICKS - 1)), record];
    });
    setLastMessageAt(Date.now());
  }, []);

  // Refetches the server's own history on every connect *and* reconnect --
  // fixes 9b's known rough edge where a reconnect only ever appended new
  // ticks onto the old buffer, leaving stale and fresh tick numbers
  // concatenated (non-monotonic) until the stale ones aged out of the
  // rolling window. GET /state (added in 9a specifically for backlog catch-
  // up) is the fix; WS stays new-ticks-only.
  const resyncFromServer = useCallback(async () => {
    try {
      const state = await fetchState();
      if (unmountedRef.current) return;
      setTicks(state.history.slice(-MAX_TICKS));
      setRunning(state.running);
      setControls(state.controls);
    } catch (err) {
      console.error("failed to resync from GET /state", err);
    }
  }, []);

  useEffect(() => {
    unmountedRef.current = false;

    const connect = () => {
      const ws = new WebSocket(WS_URL);
      socketRef.current = ws;

      ws.onopen = () => {
        attemptsRef.current = 0;
        setStatus("open");
        resyncFromServer();
      };

      ws.onmessage = (event) => {
        appendTick(JSON.parse(event.data) as TickRecord);
      };

      ws.onclose = () => {
        if (unmountedRef.current) return;
        attemptsRef.current += 1;
        setStatus(attemptsRef.current >= LOST_AFTER_ATTEMPTS ? "lost" : "reconnecting");
        const delay = Math.min(BASE_DELAY_MS * 2 ** (attemptsRef.current - 1), MAX_DELAY_MS);
        timerRef.current = setTimeout(connect, delay);
      };

      ws.onerror = (event) => {
        // React StrictMode's dev-only double-mount aborts a phantom first
        // connection while it's still CONNECTING -- expected noise. onclose
        // (fires right after, either way) owns all reconnect logic.
        if (!unmountedRef.current) console.error("tick stream websocket error", event);
      };
    };

    connect();
    fetchScenarios()
      .then(setScenarios)
      .catch((err) => console.error("failed to fetch /config/scenarios", err));

    return () => {
      unmountedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, [appendTick, resyncFromServer]);

  // -- actions: optimistic local update + fire-and-forget API call. Safe to
  // stay optimistic at this project's scope -- one operator, one client, no
  // other writer that could disagree with this one's assumption.

  const setMode = useCallback((mode: ControllerMode) => {
    setControls((c) => ({ ...c, mode }));
    api.setMode(mode).catch((err) => console.error("setMode failed", err));
  }, []);

  const setSetpoint = useCallback((setpoint_c: number) => {
    setControls((c) => ({ ...c, setpoint_c }));
    api.setSetpoint(setpoint_c).catch((err) => console.error("setSetpoint failed", err));
  }, []);

  const setManual = useCallback((heaterPct: number, overrideRequested: boolean) => {
    setControls((c) => ({ ...c, manual_heater_pct: heaterPct, manual_override_requested: overrideRequested }));
    api.setManual(heaterPct, overrideRequested).catch((err) => console.error("setManual failed", err));
  }, []);

  const setPidGains = useCallback((kp: number, ki: number, kd: number) => {
    setControls((c) => ({ ...c, kp, ki, kd }));
    api.setPidGains(kp, ki, kd).catch((err) => console.error("setPidGains failed", err));
  }, []);

  const setDrift = useCallback((enabled: boolean) => {
    setControls((c) => ({ ...c, drift_enabled: enabled }));
    api.setDrift(enabled).catch((err) => console.error("setDrift failed", err));
  }, []);

  const setStuck = useCallback((enabled: boolean) => {
    setControls((c) => ({ ...c, stuck_enabled: enabled }));
    api.setStuck(enabled).catch((err) => console.error("setStuck failed", err));
  }, []);

  const triggerSpike = useCallback(() => {
    api.triggerSpike().catch((err) => console.error("triggerSpike failed", err));
  }, []);

  const toggleRunning = useCallback(() => {
    const next = !running;
    setRunning(next);
    api.setRunning(next).catch((err) => console.error("setRunning failed", err));
  }, [running]);

  const resetSession = useCallback(
    (seed?: number | null) => {
      setTicks([]); // instant feedback; resyncFromServer below fills in authoritative post-reset controls
      setLastTriage(null); // a fresh run shouldn't show a stale explanation from before -- mirrors app.py's Reset
      api
        .resetSession(seed)
        .then(resyncFromServer)
        .catch((err) => console.error("resetSession failed", err));
    },
    [resyncFromServer],
  );

  const resetInterlock = useCallback(() => {
    api.resetInterlock().catch((err) => console.error("resetInterlock failed", err));
  }, []);

  const requestTriage = useCallback(async () => {
    setTriageLoading(true);
    try {
      setLastTriage(await api.requestTriage());
    } catch (err) {
      console.error("requestTriage failed", err);
    } finally {
      setTriageLoading(false);
    }
  }, []);

  return {
    status,
    ticks,
    latest: ticks.length > 0 ? ticks[ticks.length - 1] : null,
    lastMessageAt,
    running,
    controls,
    scenarios,
    setMode,
    setSetpoint,
    setManual,
    setPidGains,
    setDrift,
    setStuck,
    triggerSpike,
    toggleRunning,
    resetSession,
    resetInterlock,
    lastTriage,
    triageLoading,
    requestTriage,
  };
}
