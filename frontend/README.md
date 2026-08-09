# frontend

React + TypeScript + Vite client for the control loop simulation's FastAPI backend (`../backend`). See the [repo root README](../README.md) for the full project, prerequisites, and how to run the backend this talks to.

## Dev commands

```bash
npm install
npm run dev      # http://localhost:5173, expects the backend at localhost:8000
npm run build    # tsc -b && vite build -- type-checks and produces dist/
npm run lint      # oxlint
```

## Structure

- `src/hooks/useSimulationState.ts` — the app's one state store: WebSocket connection, tick buffer, control values, and the actions that mutate them.
- `src/hooks/useEventToasts.ts` — fires a toast on a live state transition (lockout, hard trip, override, fault injected).
- `src/lib/severity.ts` — shared color/status derivation, the TS mirror of `app.py`'s (the Streamlit UI's) severity logic, so both frontends read as the same system.
- `src/components/` — UI components; `components/ui/` holds shadcn/ui primitives (installed via its CLI, not hand-written — see `components.json`).

Styling is Tailwind v4 + shadcn/ui, fixed to a dark control-room theme (no light mode). Charting is Recharts.
