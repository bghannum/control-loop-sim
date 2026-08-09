# Safety-Constrained AI Control Loop with Statistical Fault Detection
## Technical Design Document

**Author:** Brian Hannum
**Status:** Draft v2
**Purpose:** A testbed for evaluating how a generative AI controller (Claude) performs against classical control (PID) on simple physical models — how well it tracks a setpoint, how it behaves under sensor faults, and what constraints are actually needed to trust it in a control role. The project is built around a safety-constrained architecture (AI proposes, a deterministic interlock disposes) with classical statistical fault detection as supporting infrastructure, not as a separate headline capability.

---

## 1. Problem Statement & Goals

Build a simulated thermal control loop where a setpoint is maintained by one of three interchangeable controllers (manual, classical PID, AI-assisted), with sensor fault injection and a hard-coded safety interlock that mediates every proposed actuator command regardless of its source.

**Primary goals**
- Test how a generative AI controller actually performs at a control task — setpoint tracking, response to disturbance, behavior under sensor faults — compared directly against classical PID on the same simple physical model. This comparison is the core question the project exists to answer, not a side benefit.
- Demonstrate a defensible architecture pattern for AI-in-the-loop control: the AI *proposes*, a deterministic layer *disposes*. This is what makes it safe to let a generative model anywhere near a control loop in the first place.
- Produce a legible, demoable artifact — a reviewer should be able to watch a fault happen, watch the AI and PID controllers respond differently, and watch the interlock intervene when needed, all in one session.
- Ground the project in real control-systems vocabulary (setpoint tracking, overshoot, slew rate, sensor trust) so it holds up under technical questioning from people who actually know this domain.

**Explicit non-goals**
- Physical realism beyond a first/second-order thermal model — this is not a high-fidelity plant simulation, and shouldn't try to be.
- Production-grade security, auth, or multi-user support.
- Real-time performance guarantees (soft real-time in a Streamlit loop is fine).

---

## 2. System Overview

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Controller  │────▶│  Interlock Layer  │────▶│    Plant     │
│ (Manual/PID/ │     │  (deterministic,  │     │ (thermal sim)│
│     AI)      │     │   no LLM in path) │     │              │
└─────────────┘     └──────────────────┘     └──────┬──────┘
       ▲                      │                       │
       │                 decision log                 ▼
       │                      │                ┌─────────────┐
       │                      │                ┌▶│  Sensor     │
       │                      │                │ │ (+ faults)  │
       └──────────────────────┴────────────────┘ └──────┬──────┘
                     current state                       │
                                                           ▼
                                                  ┌─────────────────┐
                                                  │ Anomaly Detector │
                                                  │ (statistical +   │
                                                  │  LLM triage)     │
                                                  └─────────────────┘
```

**Control loop cycle (one tick):**
1. Sensor reads true plant state, applies active fault model(s), returns a (possibly corrupted) reading.
2. Anomaly detector evaluates the reading against recent history; flags if suspicious.
3. Active controller (manual override, PID, or AI) receives the reading + detector flag, proposes a next actuator command.
4. Interlock layer validates the proposed command against hard bounds, rate limits, and sensor-trust state. Allows, clamps, or rejects.
5. Plant model integrates the (possibly modified) actuator command forward one timestep.
6. Everything — proposal, interlock decision, reason, resulting state — gets logged for the UI feed.

---

## 3. Component Design

### 3.1 Plant Model

**Decision: first-order lumped thermal model**, not a full PDE heat-transfer simulation.

**Units: Kelvin.** All temperature state, setpoints, and bounds are in Kelvin throughout the system — plant model, sensor, detector, interlock, and UI. Using an absolute temperature scale avoids sign-convention ambiguity in the loss term and matches how a real instrumentation/controls engineer would specify a thermal system. The UI may *display* Celsius as a convenience conversion at the presentation layer only — never internally.

```
dT/dt = (heater_output * k_heat - loss_coeff * (T - T_ambient)) / thermal_mass
```
(`T`, `T_ambient` in Kelvin; `heater_output` as a 0–100 percent actuator command; `k_heat`, `loss_coeff`, `thermal_mass` as tunable model parameters with defined units documented alongside `config.yaml`.)

**Trade-off considered:** a second-order model (adding actuator lag/dynamics) would be more realistic and would produce overshoot/oscillation that's more interesting to watch — but adds a state variable and tuning complexity for marginal storytelling gain. **Decision: start first-order, add second-order lag as a stretch goal** if the first-order loop feels too clean to be interesting once built.

Integration: simple explicit Euler at a fixed timestep (e.g., 0.5s simulated, decoupled from wall-clock refresh rate in the UI). `scipy.integrate.odeint` is more "correct" but explicit Euler is transparent enough that you can explain every line in an interview — that transparency is worth more here than numerical elegance.

### 3.2 Sensor Model

Wraps the true plant temperature and applies zero or more active fault modes before the value ever reaches a controller or detector. This is the *only* place faults are injected — controllers and detectors always operate on "reading," never on ground truth, which is the honest way to simulate a real instrumentation boundary.

| Fault mode | Model | Detection difficulty |
|---|---|---|
| Gaussian noise (baseline) | `reading = T_true + N(0, σ)` | N/A — always present |
| Drift | `reading = T_true + drift_rate × t_since_fault` | Hard — looks like slow real change |
| Stuck-at-value | `reading = T_frozen` (constant from fault onset) | Medium — easy to catch with variance check, easy to miss with naive threshold |
| Spike/dropout | `reading = T_true + large_offset` for 1–3 samples, then reverts | Medium — must distinguish from real transients |

Faults are independently toggleable and stackable (e.g., drift + noise concurrently), since compounding failures are the realistic case and a good stress test for the detector.

**Reproducibility: seeded scenarios.** All randomness (sensor noise, fault timing/magnitude) is driven by a single seeded RNG per session, and the project ships **three named preset seeds** representing distinct, reliably-reproducible demo scenarios (e.g., "clean run with late-onset drift," "early stuck-at-value with compounding noise," "spike burst during a setpoint change"). This exists specifically so a live demo or interview walkthrough behaves identically every time — without seeding, "watch this fault get caught" is a gamble on a live run, which is not a risk worth taking in front of an interviewer. Users can still run in true-random mode for open-ended exploration; presets are the reliable path for demonstration.

### 3.3 Controllers

All three implement the same interface — `propose(reading, setpoint, history) -> ProposedAction` — so the interlock and logging layer don't need to know which controller is active. This is the key architectural decision that makes the three-way comparison demo possible without duplicated plumbing.

- **Manual** — passthrough of a user-set slider value. No logic.
- **PID (classical)** — standard `output = Kp*e + Ki*∫e + Kd*(de/dt)`, gains exposed as UI sliders.
- **AI-assisted** — Claude API call with the current reading, setpoint, recent history window, and detector flag in the prompt. Returns a **structured JSON proposal**, never a free-text command:

```json
{
  "proposed_output_pct": 42.0,
  "confidence": "high",
  "rationale": "Reading trending toward setpoint, minor correction only.",
  "flagged_sensor_concern": false
}
```

**Trade-off:** letting the AI see the detector's flag (vs. having it infer anomalies itself from raw history) is a deliberate simplification — it keeps the AI's job scoped to "control decision," not "anomaly detection," which are different competencies and shouldn't be conflated in one prompt. This separation of concerns is worth stating explicitly in the README, since it mirrors a real design principle: don't ask one model to do two jobs it wasn't evaluated for.

#### 3.3.1 A known risk: AI latency vs. control loop timing

**This is a real limitation, not a detail to gloss over.** A Claude API call takes on the order of 1–3 seconds of wall-clock time. A control loop tick, by contrast, should be fast and regular. Running the AI as a synchronous, every-tick controller means "AI mode" runs at a fundamentally different — and much slower, and much less regular — cadence than PID or manual mode. That's not a bug to hide; it's a real characteristic of using a general-purpose LLM as a control-loop component, and it's worth stating plainly in the README as a known limitation of this architecture, not something the project pretends isn't true.

**How this project handles it:** while an AI proposal is in flight, the loop **holds the last commanded actuator value** rather than blocking the whole simulation or feeding stale data into a new decision. The AI effectively runs on a slower, asynchronous cadence layered on top of a faster loop that's otherwise idling on "hold."

**How production systems actually get around this** (worth including in the doc, since it's a fair question to get asked: "so is this how you'd really do it?"):
- **Tiered control, not single-loop control.** Real systems that use ML/AI for control decisions almost never put the model directly in a tight real-time loop. A fast, deterministic inner loop (a PID or similar) handles moment-to-moment regulation; a slower outer loop (which can absolutely be AI-driven) adjusts *setpoints, gains, or operating strategy* on a much longer cadence — seconds to minutes, not milliseconds. This project's "AI proposes an actuator value directly" approach is a simplification for demo legibility; a production version would more likely have the AI adjust the PID's setpoint or tuning, not bypass PID entirely.
- **Async inference with a bounded staleness budget.** Kick off the AI call without blocking the loop, and accept its answer only if it arrives within some max staleness window relevant to the process's time constant — otherwise discard it as stale and keep holding.
- **Smaller, faster, purpose-built models for anything in a tight loop.** A general-purpose LLM API call is the wrong tool for millisecond-scale control; if AI-in-the-loop control is genuinely required at that speed, that's a distilled/local model problem, not an API-call problem.

### 3.4 Interlock Layer

**Deterministic, rule-based, zero LLM calls in this path** — this is non-negotiable and is the central thesis of the whole project. A safety layer that itself depends on a probabilistic model isn't a safety layer.

**Revision from v1: the bounds check must not depend on the plant model.** The original draft's "one-step lookahead" check would have required the interlock to call into the plant's physics to project a future temperature — which quietly couples the "dumb" safety layer to the same simulation logic it's meant to be independent of, undermining the whole point of keeping it separate. **Fixed to a genuinely dumb check:** the interlock only ever looks at the *current* sensed temperature and the *proposed* actuator command, with no forward projection. E.g., "if current temperature is within a defined margin of `T_max`, reject any command that increases heater output; if within a margin of `T_min`, reject any command that decreases it." This is exactly how a real hardwired interlock works — it trips on a present measured condition, not a model-predicted future one. Prediction-based protection is a legitimate real-world technique, but it belongs in a separate, explicitly-labeled predictive-safety layer — never silently folded into the "dumb" interlock.

Checks applied in order, first failure wins:
1. **Sensor-trust gate** — if the detector's current flag state is "untrusted," reject any proposal that isn't "hold at last-known-good," regardless of source.
2. **Absolute bounds (present-state only, no lookahead)** — clamp actuator output to `[0, 100]`; reject any command that pushes further toward a temperature bound the system is already near, per the margin rule above.
3. **Rate-of-change (slew) limit** — reject/clamp any proposed change exceeding `max_delta_per_tick`, regardless of who proposed it — this catches both a runaway AI and a fat-fingered manual override.
4. **Pass-through** — if all checks clear, the proposal executes unmodified.

**Manual override policy (a real design decision, not an oversight):** only the **manual** controller may explicitly override an interlock rejection — and only with a visible, persistent warning in the UI while the override is active (e.g., a red banner: "Interlock override active — operating outside validated safety bounds"). **PID and AI proposals can never bypass the interlock, under any circumstance.** This mirrors real operational doctrine: a human operator can be granted authority to accept risk with eyes open; an automated controller — classical or AI — is never granted that authority, because it can't be held accountable for the decision the way a person can. This is worth stating explicitly in the README, since it's a genuinely defensible position on human-AI authority that's directly relevant to your background.

Every evaluation — allowed, clamped, rejected, or manually overridden — writes a log entry: `{tick, source, proposed, result, reason, override_active}`. This log is the most important UI element in the whole project; it's what turns "I built an AI control system" into "I built a *safety-constrained* AI control system," which is the actual claim you want to be able to defend in an interview.

**Trade-off considered:** should the interlock be allowed to learn/adapt its thresholds over time? **Decision: no.** Keeping it static and dumb is the point — adaptive safety logic reintroduces the exact trust problem the interlock exists to solve. This is worth stating explicitly as a design decision, not an omission.

### 3.5 Fault Detection (Statistical) + AI Triage (Explanatory Only)

Two tiers with clearly different jobs — worth naming precisely, since blending them under one "AI anomaly detection" label overstates what the AI actually does here:

**Tier 1 — statistical (fast, deterministic, runs every tick)**
- Rolling z-score or EWMA control-chart bounds for spike/dropout detection.
- CUSUM (cumulative sum) for drift detection — chosen specifically because a static threshold *cannot* catch slow drift, and being able to explain why CUSUM handles it and a threshold doesn't is a strong interview moment.
- Variance-over-window check for stuck-at-value (near-zero rolling variance where noise should exist).

This tier alone drives the interlock's sensor-trust gate — **the safety-critical path never depends on the LLM tier**, only on cheap, fast, explainable statistics.

**Tier 2 — LLM triage (slower, runs on flag or on-demand)**
- When Tier 1 flags an anomaly, pass a windowed summary of readings + which statistical test fired to Claude, asking for a plain-language characterization: likely fault type, suggested severity, human-readable explanation.
- This tier is explicitly advisory/explanatory only — it never feeds back into the interlock decision. Its job is making the *dashboard* legible to a non-engineer, not making the *system* safe.

### 3.6 AI Controller Failure Handling

**A safety-oriented design that doesn't specify what happens when its own AI component fails isn't finished.** The AI controller path must handle three failure cases explicitly, not implicitly:

1. **API call fails, times out, or returns malformed JSON.** The system **holds the last commanded actuator value** — same as the latency-handling behavior in 3.3.1 — and does not treat this as a control decision of any kind.
2. **Failure persists.** If the AI controller cannot get a valid response for a defined period (proposed: **10 seconds**), the UI surfaces a visible, unmissable countdown warning telling the operator to switch to manual or PID control.
3. **Operator doesn't respond in time.** If the warning window elapses with no mode change, the system **automatically sets a manual override to a predefined safe value** (e.g., a conservative mid-range actuator output known to hold temperature roughly flat) rather than continuing to sit in a failed AI-controller state indefinitely. This is logged as a system-initiated safety action, distinct from a human-initiated override, so the decision log always shows *why* control changed hands.

This same 10-second-warning-then-safe-default pattern is a legitimate, common real-world design for automation failure handling (it's structurally similar to a "dead-man" timer) — worth naming as such in the README, since it's a recognizable pattern rather than something invented for this project.

---

## 4. Data Flow & State Management

Given this runs in Streamlit, state lives in `st.session_state` as a rolling buffer (e.g., last 500 ticks) of a single structured record per tick:

```python
{
  "tick": int, "t_true": float, "t_sensed": float,
  "active_faults": [...], "detector_flags": {...},
  "controller_source": "manual"|"pid"|"ai",
  "proposed_action": {...}, "interlock_result": "allow"|"clamp"|"reject",
  "interlock_reason": str, "override_active": bool, "ai_fallback_active": bool,
  "interlock_locked_out": bool, "trip_strikes": int, "trip_lockout_threshold": int,
  "actuator_output": float
}
```

**Trade-off:** a real system would separate this into a time-series store (even SQLite) from the UI layer. For a portfolio project scoped to a single demo session, an in-memory buffer is the right call — but the record schema above is deliberately designed so it *could* be dropped into Delta Lake with no changes, which is a nice callback to the Databricks project if you want to mention it's the same data-modeling instinct.

---

## 5. Implementation Strategy & Build Order

Sequenced so that every stage produces something demoable — never a long stretch with nothing to show.

1. **Plant + manual control only.** Slider drives heater, temperature responds, plotted live. Proves the physics loop works.
2. **Add PID controller + mode toggle.** Now you can show classical control tracking a setpoint.
3. **Add sensor model with fault toggles, no detection yet.** Inject drift/noise/stuck/spike, watch the (now visibly wrong) reading feed the PID astray. This alone is a good "why we need a safety layer" demo moment.
4. **Add Tier 1 statistical detector + interlock sensor-trust gate.** Now faults get caught and the interlock freezes control — the core safety story is functional at this point, before any AI is involved at all. Worth pausing here and confirming the story holds.
5. **Add AI controller + structured proposal schema.** Wire Claude API into the same `propose()` interface the PID uses.
6. **Add interlock bounds/rate-limit checks against AI proposals specifically**, and build the decision log UI. This is where you can force a demo moment: crank AI aggressiveness or inject a fault, watch the interlock override it, and point at the log line as the payoff.
7. **Add Tier 2 LLM triage layer** for plain-language fault explanation — polish pass, not core functionality.
8. **README + architecture diagram + short walkthrough.** Budget real time for this — it's the artifact most reviewers will actually read.

---

## 6. Key Design Decisions (Summary for README)

| Decision | Alternative considered | Why this choice |
|---|---|---|
| AI proposes, interlock disposes | Let AI write directly to actuator with post-hoc monitoring | Propose/execute separation is the entire safety argument; monitoring after the fact doesn't prevent harm, it just documents it |
| Interlock is static, rule-based, non-adaptive | Learned/adaptive safety thresholds | An adaptive safety layer has the same trust problem it's meant to solve |
| Statistical detector gates the interlock; LLM tier is advisory-only | Let LLM triage feed the interlock decision | Keeps the safety-critical path fast, deterministic, and explainable without a model in the loop |
| First-order plant model | Second-order with actuator lag | Faster to build and fully explainable; upgrade only if the demo needs more visual drama |
| Faults injected only at the sensor boundary | Faults injectable anywhere in the pipeline | Mirrors a real instrumentation boundary; keeps the mental model honest |
| AI failure → hold last command → 10s warning → auto safe-default | Fail silently, or block indefinitely on retry | Dead-man-timer pattern: bounded time in a degraded state, then a defined safe outcome, always logged |
| Manual can override interlock (with warning); PID/AI never can | Allow any controller to override with sufficient confidence | Only a human operator can be held accountable for accepting risk; automated controllers are never granted that authority |
| Interlock bounds check uses present state only, no lookahead | Predictive lookahead using the plant model | Keeps the safety layer fully decoupled from simulation physics — a dumb interlock stays dumb |
| Kelvin throughout, Celsius display-only | Celsius or Fahrenheit internally | Absolute scale avoids sign-convention bugs in the loss term; matches real controls-engineering convention |
| Seeded scenario presets (3 named seeds) | Pure random every run | Reproducible demos — a live interview walkthrough shouldn't depend on random luck |
| Concurrency: last command wins | Locking/queue-based arbitration | Reasonable simplification at demo scale; explicitly not claimed as production-grade |

---

## 7. Data Storage Architecture (Productionization)

*This section explains how to store the simulation's data the way a real production system would, instead of just keeping everything in memory. Read this if you're unfamiliar with the terms — each concept is explained before it's used.*

### 7.1 The core idea: "hot path" vs. "historian"

Real industrial control systems (the SCADA/DCS systems you worked with in the Navy and at Govini) never store live control data and historical data in the same place. There are two very different jobs happening:

- **Hot path** — data the control loop needs *right now*, this millisecond, to make a decision. Needs to be extremely fast to read and write. Doesn't need to be kept forever.
- **Historian** — a durable, searchable record of everything that happened, used later for analysis, dashboards, and audits. Can be slower, because nothing time-critical is waiting on it.

Mixing these two jobs into one database is a common beginner mistake — you end up with something that's too slow for real-time control and too limited for good historical analysis. Splitting them is one of the most "production-minded" decisions you can make in this project, and it's an easy thing to explain in an interview.

### 7.2 Hot path: what it is and what to use

**What "hot path" means here:** the current tick's readings, the last ~50-100 ticks of history (enough for the anomaly detector's rolling calculations), and the current interlock state. This is the data your control loop touches every single cycle.

**Options:**
- **Plain in-memory Python (a list or dict in your program)** — the simplest option. No new technology to learn. Fine for a single-process demo, but data disappears if the program restarts, and it can't be shared between separate processes (like a separate engine and UI, discussed in Section 9).
- **Redis** — a database that keeps everything in RAM (memory) instead of on disk, which makes it extremely fast. Think of it as a shared, structured "scratchpad" that multiple programs can read and write to at the same time. This is the standard real-world tool for exactly this kind of "hot," short-lived, shared state. It also has a feature called **pub/sub** (publish/subscribe) — one program can "publish" a message (like "new tick available") and any number of other programs can "subscribe" to get notified instantly. That becomes useful once you split the simulation engine from the UI (Section 9).

**Recommendation:** start with plain in-memory. Add Redis only once you actually split the engine and UI into separate processes — at that point Redis stops being "extra complexity" and starts being "the thing that makes two processes able to talk to each other," which is a much easier thing to justify than adding it upfront.

### 7.3 Historian: what it is and what to use

**What "historian" means here:** a permanent, queryable log of every tick that ever happened — useful for things like "show me every time the interlock rejected an AI proposal in the last hour" or "plot temperature drift over the whole session." This is analytical, not time-critical.

**Options, from simplest to most "production":**

- **SQLite** — a full relational (SQL) database that lives in a single file on your disk, no server required. Good learning step if you've never written to a real database before, since the SQL you write is the same SQL you'd use anywhere.
- **TimescaleDB** — this is regular PostgreSQL (a very widely-used SQL database) with an add-on specifically designed for time-series data (data that's naturally ordered by time, like sensor readings). It automatically organizes your data into time-based chunks behind the scenes ("hypertables"), which makes queries like "show me the last hour" much faster without you having to manage that yourself. **This is my top recommendation** — Postgres is one of the most common databases in the industry, so this teaches you something broadly useful, not just something specific to this toy project.
- **Delta Lake / Parquet files in cloud storage (S3, or Azure Blob)** — this is the same pattern you're already using in your Whoop/Databricks project. Instead of a database server, you write data as files (Parquet is a compact, column-organized file format built for analytics) into a folder structure, and Delta Lake adds transaction safety and versioning on top. **Recommendation if you want this project to visibly reuse the same architecture as your Databricks project** — a reviewer or interviewer will notice if you use the same storage pattern across two portfolio pieces, and it's a legitimate, reusable skill rather than a one-off choice.

**Recommendation:** TimescaleDB if you want to learn something new and broadly transferable (SQL/Postgres skills apply almost everywhere). Delta Lake/Parquet if you'd rather deepen the exact skill set you're already building for the Databricks role. Either is a defensible choice — pick based on which skill gap you'd rather close.

### 7.4 Don't let storage slow down the control loop

**The problem:** if your control loop tries to write every single tick directly to a database (especially a networked one like TimescaleDB), the loop now has to wait for that write to finish before it can continue. In a real control system, this kind of delay is exactly the sort of thing that causes real problems — the historian should never be able to slow down or block control decisions.

**The fix — a pattern called "batching with a background writer":**
1. The control loop keeps writing ticks to the fast, in-memory hot path only — it never talks to the historian directly.
2. A separate, independent piece of code (a "background writer") wakes up periodically (say, every 5 seconds, or every 50 ticks) and copies whatever's accumulated in the hot path into the historian, all at once ("batching," which is much more efficient than writing one row at a time).
3. If the historian is slow or briefly unavailable, the control loop doesn't notice or care — it just keeps running against the hot path.

This is a genuinely important production pattern (not just something we're inventing for this project), and being able to explain *why* you separated these — "so storage latency can never affect control loop timing" — is a strong, specific answer to have ready in an interview.

---

## 8. Pluggable Simulation Models

*This section explains how to structure the code so you can swap in a more complex physics model later (like the second-order model with actuator lag) without rewriting the rest of the program.*

### 8.1 The problem this solves

Right now, the plan is to build one specific equation (the first-order thermal model) directly into the simulation loop. If you later want to try a more complex model, you'd have to go find every place in the code that assumes "the state is just one temperature number" and change it. That's fragile and it's exactly the kind of thing that makes code hard to extend later.

### 8.2 The fix: a common "interface" all models follow

**What "interface" means here:** a contract that says "any plant model must provide these specific functions, no matter how it works internally." The rest of the program (the control loop, the logger, the UI) only ever talks to "a model" through that contract — it never needs to know whether it's talking to the simple model or a complex one.

In Python, this is typically done with an **abstract base class** — basically a template that says "every real model must implement these methods, or Python will refuse to let you use it":

```python
class PlantModel(ABC):
    @abstractmethod
    def step(self, state: dict, control_input: float, dt: float) -> dict:
        """Given current state and a control input, return the new state after one timestep."""

    @abstractmethod
    def initial_state(self) -> dict:
        """Return the starting state for this model."""
```

Then each specific physics model is just a class that fills in those two methods:

```python
class FirstOrderThermal(PlantModel):
    # state = {"temperature": ...}
    ...

class SecondOrderThermal(PlantModel):
    # state = {"temperature": ..., "actuator_lag_state": ...}
    # adds a second variable to model the actuator responding gradually, not instantly
    ...
```

Because the rest of your program only ever calls `model.step(...)`, it doesn't matter whether `state` has one number in it or five — nothing outside the model itself needs to change when you add a new one.

### 8.3 Choosing a model at runtime with a "registry"

**What a "registry" is:** a lookup table (just a Python dictionary, really) that maps a name (like `"first_order"`) to the actual class that implements it. Combined with a simple decorator (a small piece of code you put above a class definition), new models can register themselves automatically just by existing in the codebase:

```python
MODEL_REGISTRY = {}

def register_model(name):
    def wrapper(cls):
        MODEL_REGISTRY[name] = cls
        return cls
    return wrapper

@register_model("first_order")
class FirstOrderThermal(PlantModel):
    ...
```

Then, instead of hardcoding which model to use, you pick it from a config file:

```yaml
# config.yaml
model_type: first_order
model_params:
  thermal_mass: 5.0
  loss_coeff: 0.3
```

Your program reads this file at startup, looks up `"first_order"` in the registry, and creates that model with those parameters. **Why this matters:** adding a third model later means adding one new file — you never touch the simulation loop, the logger, or the UI code again. This "add new capability without modifying existing code" property has a name in software design — the **open/closed principle** (open to extension, closed to modification) — and it's worth knowing that term, because it's exactly what you're demonstrating here.

### 8.4 A better math tool for multiple models

The current plan uses a simple, hand-written stepping method (explicit Euler — basically, "take a small step forward using the current rate of change"). That's fine and easy to explain for one simple model. But once different models have different numbers of state variables (temperature only, vs. temperature + actuator lag), it's worth switching to `scipy.integrate.solve_ivp` — a well-tested, general-purpose function from the SciPy library that can integrate *any* system of equations you hand it, regardless of how many variables it has. This means your `PlantModel` classes just need to describe the math; they don't need to also handle the numerical mechanics of stepping it forward, which SciPy already does correctly.

---

## 9. Splitting Simulation Engine from UI (Service Architecture)

*This section covers restructuring the project from "one program that does everything" into "a backend service plus a separate frontend that talks to it" — a very common real-world pattern, and one of the most valuable things to practice here.*

### 9.1 Why split it at all?

The simplest version of this project is a single Streamlit app: the simulation runs and the UI displays it in the same process, at the same time. That's fine to start, but it has real limits: only one UI can ever exist, everything freezes if you refactor the display code, and — most importantly for learning purposes — it doesn't teach you the pattern that almost all real production systems actually use, which is a **backend** (does the work) separated from a **frontend** (shows the work to a person).

### 9.2 The recommended split

- **Backend: a FastAPI service.** FastAPI is a Python framework for building web APIs (a program that other programs can talk to over the network, usually by sending it requests and getting back data). Your simulation engine — the control loop, the plant model, the interlock, the detector — runs continuously inside this service, completely independent of any UI. It exposes a small set of operations other programs can call, for example:
  - `POST /control/setpoint` — change the target temperature
  - `POST /faults/inject` — turn on a sensor fault
  - `GET /state/current` — ask "what's happening right now"
  - A **WebSocket** connection (a persistent, two-way connection, as opposed to a normal request-then-response) that streams live ticks out to anything listening, so a UI doesn't have to keep re-asking "anything new?" — the server just pushes updates as they happen.

- **Frontend: a thin client.** This could still be Streamlit (simplest — keep using what you already know, just make it talk to the FastAPI service over the network instead of running the simulation itself), or a proper web frontend (React or Next.js) if you want more UI design practice. Either way, its only job becomes: display data it receives, and send user actions (button clicks, slider moves) to the backend as API calls. It has no simulation logic of its own.

**Why this is worth doing:** this is the actual architectural pattern behind almost every real product you've worked around — a backend service doing the real work, and one or more frontends consuming it. Being able to say "I built this as a service with a client, not a monolith" is a meaningfully stronger architecture story than the simulation itself, and it directly practices the kind of system design that Solutions Architect interviews probe for.

**Concurrency policy: last command wins.** Once engine and UI are split, it's possible for a manual override to arrive over the API while an AI proposal from a prior tick is still in flight. Rather than building a locking/queuing scheme for a portfolio demo, the resolution rule is simple and explicit: **whichever command the interlock evaluates last in a given tick is the one that's applied.** A stale AI proposal that resolves after a more recent manual command is discarded, not applied retroactively. This is a reasonable, statable simplification for a project at this scale — a real production system handling genuinely concurrent control sources would need a more rigorous arbitration scheme (e.g., command sequence numbers, a single-writer queue), and it's worth naming that distinction explicitly rather than implying "last command wins" is production-grade as-is.

### 9.3 What this unlocks later (optional, good to know about)

Once the engine is its own service, you can add more clients without touching the engine at all — for example, a Slack bot that posts an alert whenever the interlock rejects a command, or a second read-only dashboard. This is the practical payoff of the split, and it's a good one-sentence answer if someone asks "why did you bother separating these?"

---

## 10. Assumptions & Known Limitations

Stated explicitly, rather than left implicit — a design doc that names its own edges is more credible than one that pretends it doesn't have any.

- **AI control latency means "AI mode" and "PID mode" are not directly comparable on identical timing.** This is a real, acknowledged limitation of putting a general-purpose LLM API call in a control role, not a project bug. See §3.3.1 for the production-pattern alternative (tiered control with AI adjusting setpoints/gains on a slow outer loop, not raw actuator output on a fast inner loop).
- **"Last command wins" concurrency (§9.2) is a demo-scale simplification**, not a production-grade arbitration scheme. A real multi-source control system would need sequence numbers or a single-writer queue.
- **No automated test suite is specified in this v1 doc.** Before calling any tier "done," each should have at least a small set of scripted scenarios with known expected outcomes — e.g., feed the CUSUM detector a synthetic drift signal at a known rate and confirm it flags within an expected tick window, rather than relying on "it looked right in the demo." Worth adding as an explicit build step, not an afterthought.
- **No schema versioning strategy for the historian table.** If a new fault type or controller is added later, existing rows won't have that field. Acceptable for a portfolio project's lifespan; would need an explicit migration strategy (e.g., a `schema_version` column) in anything longer-lived.
- **Hot-path concurrency (Redis, §7.2) is not addressed for simultaneous writers.** At this project's scale it's very unlikely to matter, but it's called out here rather than silently assumed away.
- **The interlock's present-state-only bounds check (§3.4) is intentionally less sophisticated than a predictive/lookahead protection scheme** a real industrial system might use. That's a deliberate trade for architectural cleanliness (no coupling to the plant model), not an oversight — but it does mean the interlock can't prevent an overshoot it hasn't reached yet, only react once it's close. Worth being upfront about this trade-off if asked.

---

## 11. Open Questions / Stretch Goals

- Second-order plant dynamics (actuator lag) for more visually interesting overshoot behavior.
- Persist tick history to Delta Lake / SQLite instead of in-memory buffer, as a Databricks-project crossover.
- Multi-loop version (two coupled thermal zones) to demonstrate more complex interlock interactions.
- Replace CUSUM with a proper changepoint detection library and compare — good if you want a deeper "why I chose this algorithm" story.
