# Antigravity (AGY) Project Instructions & Repo Context

**Repository:** `control-loop-sim`  
**Purpose:** Safety-Constrained AI Control Loop simulation demonstrating deterministic safety interlocks ("AI proposes, interlock disposes") operating over thermal plant dynamics with sensor fault injection and TimescaleDB telemetry.

---

## 1. Executive Context & Architecture Overview

The system models a thermal control loop with three control modes (Manual, PID, AI via Claude) passing proposals through a multi-tier safety interlock:

```
[ Sensor ] ──> [ Tier-1 Detector ] ──> [ Interlock Gate ] ──> [ Plant Model ]
    │                                          ▲
    └──> [ Active Controller ] ────────────────┘
         (Manual / PID / AI)
```

### Primary Principles
1. **Separation of Control & Safety:** Controllers (including AI) only *propose* action. The deterministic `Interlock` (`engine/interlock.py`) has final authority to clamp, hold, or trip commands based on safety rules.
2. **Non-Blocking Asynchronous Operations:**
   - **AI Controller:** `engine/controllers/ai.py` calls the Anthropic API asynchronously in a daemon thread so the 0.5s Streamlit tick loop is never blocked.
   - **Historian:** `storage/historian.py` flushes telemetry batches asynchronously to TimescaleDB.
3. **Fault Injection & Sensor-Trust:**
   - `engine/sensor.py` injects baseline noise, drift, stuck-at, and spike faults.
   - `engine/detector.py` uses rolling z-scores, CUSUM, and rolling variance to untrust corrupted sensors and freeze actuators at last-known-good values.

---

## 2. Key Commands & Execution Workflows

### Run the Application
```bash
streamlit run app.py
```

### Execute Test Suite
```bash
pytest
```

### Headless Verification with Playwright
```bash
source venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium
```
*Note on Streamlit Playwright Testing:* Streamlit's main scrollable container is `section[data-testid="stMain"]`. To reset scroll position before screenshotting:
```python
page.evaluate('document.querySelector(\'[data-testid="stMain"]\').scrollTop = 0')
```

---

## 3. Important Design Contracts & Constraints

- **No Self-Clamping in Controllers:** Controllers (PID / AI) must NOT clamp their outputs to `[0, 100]` internally; enforcing valid ranges and slew limits is strictly the `Interlock`'s responsibility.
- **Idempotent UI Setters:** Streamlit re-runs the entire script on every user interaction. Any setter in `ControlLoop` or `Sensor` that resets state (e.g., CUSUM or drift timers) **must be transition-guarded** to prevent resetting on unchanged re-renders.
- **Error Boundaries:** Raw API exception strings must never be passed directly to UI components without sanitization (`AIController._call_api`).

---

## 4. Current Status & Active Handoff Files

- **Architecture Spec:** `docs/control-loop-architecture.md`
- **Claude Guidelines:** `CLAUDE.md`
- **Code Review & Refactoring Roadmap:** [`CODE_REVIEW.md`](file:///Users/bghannum/Code/bghannum/control-loop-sim/CODE_REVIEW.md) (contains prioritized P0–P2 security, resilience, type-safety, and logging tasks).

---

## 5. Instructions & Role Directives for Antigravity Sessions

**Role Constraint:** Antigravity functions **exclusively as a Code Reviewer**, not an active code editor or implementer.

When assisting on this codebase:
1. **Code Reviewer Only:** Antigravity must evaluate the code for security issues, unhandled errors, architectural patterns, logging, type safety, and error boundary handling. Do not directly edit implementation files unless explicitly requested.
2. **Review Git Diff:** To maximize efficiency, always check and review `git status` and `git diff` (staged/unstaged changes) to focus feedback on recent code modifications alongside the broader codebase.
3. **Review Output File:** All findings, feedback, and recommendations for code improvements **must always be written to [`CODE_REVIEW.md`](file:///Users/bghannum/Code/bghannum/control-loop-sim/CODE_REVIEW.md)** for handover to Claude.
4. **Preserve Design Contracts:** Ensure all recommendations maintain the strict separation between controller proposals and safety interlock decisions.
5. **Referential Handoff:** Keep recommendations concise, actionable, and structured with precise file and line references.


