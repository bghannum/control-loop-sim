# Safety-Constrained AI Control Loop with Statistical Fault Detection

A testbed for evaluating how a generative AI controller (Claude) performs against classical control (PID) on a simple thermal system — and, more importantly, a working example of how to put a generative model anywhere near a control loop safely.

**The core idea: the AI proposes, a deterministic interlock disposes.** Every actuator command — whether it comes from a human, a classical PID controller, or Claude — passes through a hard-coded, non-negotiable safety layer before it ever reaches the simulated plant. That interlock never calls an LLM. A safety layer that itself depends on a probabilistic model isn't a safety layer.

Full design rationale, trade-offs, and known limitations are in [`docs/control-loop-architecture.md`](docs/control-loop-architecture.md) — this README covers what you need to get it running.

## What it does

- Simulates a first-order thermal system (heater, sensor, ambient loss) in Kelvin, driven by a pluggable differential-equation model so more complex physics can be swapped in without touching the rest of the codebase.
- Lets you control it three ways — manual override, classical PID, or an AI controller backed by the Claude API — and compare how each tracks a setpoint and responds to disturbance.
- Injects sensor faults on demand (noise, drift, stuck-at-value, spike/dropout) and catches them with classical statistical detection (rolling z-score, CUSUM for drift, variance checks for stuck sensors) — the detection itself is deliberately *not* AI-driven; Claude is only used afterward, on request, to explain a flagged fault in plain language (Tier-2 triage).
- Enforces hard safety bounds and rate limits on every proposed action. Manual mode can override the interlock (with a persistent warning); PID and AI can never bypass it, under any circumstance.
- Logs every interlock decision — allowed, clamped, rejected, or overridden — so you can watch exactly why the system did what it did.
- Ships **two interchangeable frontends** against the same simulation engine: a Streamlit app (single process, simplest to run) and a FastAPI backend + React frontend (a real service split, streaming live ticks over a WebSocket). Same engine, same safety guarantees, two different UI architectures — see "Two ways to run it" below.

## Prerequisites

- **Python 3.12** (verified against 3.12.13; other 3.12.x should work)
- **git**
- **Node.js 20.19+ or 22.12+** — only needed if you want to run the React frontend (Vite 8's minimum). The Streamlit app doesn't need Node at all.
- **Docker** — optional, only for persistent history storage (TimescaleDB). Everything runs without it; see "Optional: persistent history" below.
- An **Anthropic API key** — optional. Without one, AI mode and the "Triage with Claude" button are still fully present in the UI, they just show an explicit "no client configured" state instead of crashing. Manual and PID control, fault injection, and the interlock/detector all work with zero API access.

macOS install commands below use Homebrew; substitute your platform's usual installers (`python.org`, `nodejs.org`, Docker Desktop) if you're not on macOS — nothing in this project is macOS-specific.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12 node git
brew install --cask docker   # optional, only for TimescaleDB
```

## Setup

```bash
git clone https://github.com/bghannum/control-loop-sim.git
cd control-loop-sim
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

This gets you everything the Streamlit app needs. Both run options below share this same Python environment.

## Two ways to run it

### Option A: Streamlit (single process, simplest)

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. The simulation and the UI run in the same process — this is the fastest way to see the project working, and the UI it was originally built with.

### Option B: FastAPI backend + React frontend

The same simulation engine, split into a backend service (the actual control loop, running independently of any browser connection) and a separate React frontend that talks to it over REST + WebSocket — a real backend/frontend split, not a reflow of the Streamlit layout. See [`docs/control-loop-architecture.md` §9](docs/control-loop-architecture.md) for why this split is worth doing.

**Terminal 1 — backend:**
```bash
source venv/bin/activate
pip install -r requirements-backend.txt
uvicorn backend.main:app --reload
```
Runs on `http://localhost:8000`.

**Terminal 2 — frontend:**
```bash
cd frontend
npm install
npm run dev
```
Opens at `http://localhost:5173`. The two dev servers talk to each other over CORS-enabled localhost requests — no proxy config needed.

Both options are the same underlying safety system; pick whichever you want to poke at. The Streamlit app is the more mature/battle-tested UI; the React app is the newer, more polished one (control-room-style dark theme, live connection status, toast notifications, animated decision log).

## Optional: Claude API key

Create a `.env` file in the project root (never committed — see `.gitignore`):
```
ANTHROPIC_API_KEY=your-key-here
```
A `.env.example` is included as a template. Both the Streamlit app and the FastAPI backend read this the same way (via `python-dotenv`). Without it, AI mode and Tier-2 triage clearly report that no client is configured rather than failing silently or crashing — everything else in the project works identically either way.

## Optional: persistent history (TimescaleDB)

```bash
docker compose up -d
```
Confirm it's running: `docker ps` should show a `timescaledb` container. Then add to `.env`:
```
TIMESCALE_DSN=postgresql://postgres:postgres@localhost:5432/control_loop_sim
```

This only matters for the **Streamlit app** — it writes tick history to TimescaleDB in the background (batched, never blocking the control loop) if `TIMESCALE_DSN` is set, and simply doesn't if it isn't (the "Historian" tile shows "unavailable," not an error). **The FastAPI backend doesn't wire up a historian at all yet** — its own "Historian" tile always shows "not wired," honestly, rather than faking connectivity; this is a known, tracked gap (see `BACKLOG.md`), not an oversight you need to work around.

## Running tests

```bash
pytest -q
```
Runs the full suite — physics/plant model, PID, sensor fault injection, the Tier-1 statistical detector, the interlock (bounds, rate limits, trip/lockout escalation), the AI controller and Tier-2 triage (against fakes, no network calls), and the FastAPI backend's REST/WebSocket surface. No API key, database, or running frontend required — this suite is fully self-contained.

## Repository structure

```
engine/
├── models/            # PlantModel base class + physics implementations (first-order, second-order...)
├── controllers/       # manual, pid, ai — all implement the same propose() interface
├── sensor.py          # fault injection, seeded for reproducible demo scenarios
├── detector.py        # statistical fault detection (Tier 1)
├── interlock.py       # deterministic safety layer — no LLM calls, ever
├── triage.py           # Tier-2 LLM triage — advisory-only, never feeds back into the interlock
└── loop.py             # ties one tick together: sensor -> detector -> controller -> interlock -> plant
storage/
└── historian.py       # batched, async writes to TimescaleDB — never blocks the control loop (Streamlit only, see above)
backend/                # FastAPI service: wraps ControlLoop in a background tick task, REST control
├── service.py          # SimulationService — owns one ControlLoop, runs independently of any browser
├── routers/            # REST control endpoints + the /ws/ticks WebSocket stream
└── schemas.py          # Pydantic boundary models
frontend/               # React + TypeScript + Vite client for the FastAPI backend
└── src/
    ├── hooks/          # useSimulationState (WebSocket + control actions), useEventToasts
    ├── components/     # UI, incl. shadcn/ui primitives under components/ui/
    └── lib/            # severity.ts (shared color/status logic), api.ts
app.py                  # Streamlit entrypoint — the original, single-process UI
config.yaml             # every tunable parameter (plant physics, detector thresholds, interlock bounds, etc.)
docs/
├── control-loop-architecture.md   # full design doc: trade-offs, decisions, known limitations
├── archive/                        # phase-by-phase build history (Phases 1-5.5)
├── design-prompts/                 # UI design briefs + reviewed HTML mockups (Phase 8, Phase 9c)
└── phase-9a-backend-plan.md        # detailed plan behind the FastAPI backend split
```

## Known limitations

This is a portfolio project, not a production control system — a few things are intentionally simplified rather than hidden:

- The AI controller's latency (a Claude API call, typically 1–3s) is fundamentally slower than a real control tick. While a response is pending, the loop holds the last commanded value rather than blocking. See the design doc's discussion of tiered control (AI adjusting setpoints on a slow outer loop, not raw actuator output on a fast inner loop) for how a production system would actually handle this.
- The interlock's bounds check uses present-state-only logic, deliberately avoiding any dependency on the plant model's physics — this keeps the safety layer genuinely independent, at the cost of not catching an overshoot before it's already close.
- The Tier-1 statistical detector can mistake a real, fast, legitimate transient (e.g. the plant cooling rapidly right after a safety trip forced the heater off) for sustained sensor drift, since both look statistically similar to a rolling CUSUM check. Mitigated in a couple of specific spots (see `config.yaml`'s `boot_grace_ticks` and `reset_grace_ticks`), but not eliminated for large excursions — a broader empirical tuning pass is tracked in `POST_MVP_BACKLOG.md`.
- Concurrency between simultaneous control sources resolves as "last command wins" — a reasonable simplification at this scale, not a production-grade arbitration scheme.
- The FastAPI backend doesn't persist history to TimescaleDB (Streamlit does) — see "Optional: persistent history" above.

Three seeded demo scenarios are included specifically so a live walkthrough doesn't depend on random luck — see the design doc, §3.2.

## More docs

- [`docs/control-loop-architecture.md`](docs/control-loop-architecture.md) — the original technical design doc: problem statement, component-by-component design, trade-offs considered, and a productionization discussion (hot path vs. historian, pluggable simulation models, splitting engine from UI). Written before/during the build, not after — read it for the *reasoning* behind what's here.
- [`BACKLOG.md`](BACKLOG.md) — known, scoped gaps not yet built (e.g. wiring a historian into the FastAPI backend).
- [`POST_MVP_BACKLOG.md`](POST_MVP_BACKLOG.md) — bigger-picture ideas that would only matter if this grew beyond a local, single-operator demo tool. Not scheduled.
- [`docs/archive/`](docs/archive) — detailed build history for Phases 1–5.5 (plant model through the AI controller and interlock lockout logic).
- [`docs/design-prompts/`](docs/design-prompts) — the UI design briefs and reviewed HTML mockups behind the Streamlit and React UIs.
