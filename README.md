# Safety-Constrained AI Control Loop with Statistical Fault Detection

A testbed for evaluating how a generative AI controller (Claude) performs against classical control (PID) on a simple thermal system — and, more importantly, a working example of how to put a generative model anywhere near a control loop safely.

**The core idea: the AI proposes, a deterministic interlock disposes.** Every actuator command — whether it comes from a human, a classical PID controller, or Claude — passes through a hard-coded, non-negotiable safety layer before it ever reaches the simulated plant. That interlock never calls an LLM. A safety layer that itself depends on a probabilistic model isn't a safety layer.

Full design rationale, trade-offs, and known limitations are in [`docs/control-loop-architecture.md`](docs/control-loop-architecture.md) — this README covers what you need to get it running.

## What it does

- Simulates a first-order thermal system (heater, sensor, ambient loss) in Kelvin, driven by a pluggable differential-equation model so more complex physics can be swapped in without touching the rest of the codebase.
- Lets you control it three ways — manual override, classical PID, or an AI controller backed by the Claude API — and compare how each tracks a setpoint and responds to disturbance.
- Injects sensor faults on demand (noise, drift, stuck-at-value, spike/dropout) and catches them with classical statistical detection (rolling z-score, CUSUM for drift, variance checks for stuck sensors) — the detection itself is deliberately *not* AI-driven; Claude is only used afterward to explain a flagged fault in plain language.
- Enforces hard safety bounds and rate limits on every proposed action. Manual mode can override the interlock (with a persistent warning); PID and AI can never bypass it, under any circumstance.
- Logs every interlock decision — allowed, clamped, rejected, or overridden — so you can watch exactly why the system did what it did.

## Setup (macOS)

**1. Core tools** (skip anything you already have installed):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12 git gh
brew install --cask docker visual-studio-code
gh auth login
```
Open Docker Desktop once from Applications and let it fully start before continuing.

**2. Clone and set up the environment**
```bash
git clone https://github.com/<your-username>/control-loop-sim.git
cd control-loop-sim
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**3. Start TimescaleDB** (local, free — self-hosted, not the paid cloud tier)
```bash
docker compose up -d
```
Confirm it's running: `docker ps` should show a `timescaledb` container.

**4. Set your API key**

Create a `.env` file in the project root (never committed — see `.gitignore`):
```
ANTHROPIC_API_KEY=your-key-here
```
A `.env.example` is included as a template.

**5. Run it**
```bash
streamlit run app.py
```

## Repository structure

```
engine/
├── models/          # PlantModel base class + physics implementations (first-order, second-order...)
├── controllers/      # manual, pid, ai — all implement the same propose() interface
├── sensor.py          # fault injection, seeded for reproducible demo scenarios
├── detector.py        # statistical fault detection (Tier 1) + Claude-based triage (Tier 2)
├── interlock.py       # deterministic safety layer — no LLM calls, ever
└── loop.py             # ties one tick together
storage/
└── historian.py       # batched, async writes to TimescaleDB — never blocks the control loop
docs/
└── control-loop-architecture.md   # full design doc: trade-offs, decisions, known limitations
```

## Known limitations

This is a portfolio project, not a production control system — a few things are intentionally simplified rather than hidden:

- The AI controller's latency (a Claude API call, typically 1–3s) is fundamentally slower than a real control tick. While a response is pending, the loop holds the last commanded value rather than blocking. See the design doc's discussion of tiered control (AI adjusting setpoints on a slow outer loop, not raw actuator output on a fast inner loop) for how a production system would actually handle this.
- The interlock's bounds check uses present-state-only logic, deliberately avoiding any dependency on the plant model's physics — this keeps the safety layer genuinely independent, at the cost of not catching an overshoot before it's already close.
- Concurrency between simultaneous control sources resolves as "last command wins" — a reasonable simplification at this scale, not a production-grade arbitration scheme.

Three seeded demo scenarios are included specifically so a live walkthrough doesn't depend on random luck — see the design doc, §3.2.
