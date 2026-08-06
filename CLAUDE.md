# Control Loop Simulation — project status

Read `README.md` and `docs/control-loop-architecture.md` first — they're the source of truth for design decisions. This file is just a pointer to where things stand.

## Status: Phase 5.5 (interlock lockout mechanism, backlog items 1-5) complete and verified

Phase 0 scaffolding + prerequisites verified previously (Python 3.12.13, Docker/`timescaledb`, `.env`, `gh`, pytest scaffold).

Phase 1 adds:
- `engine/models/first_order.py` — `FirstOrderThermal`, explicit-Euler integration of the doc's §3.1 ODE, registered as `"first_order"`. `engine/models/__init__.py` now imports it so the registry populates on package import.
- `engine/controllers/manual.py` — `ManualController`: holds a mutable `value` set via `set_value()`, `propose()` just echoes it. (The shared `Controller.propose(reading, setpoint, history)` signature has no slot for "current slider position" by design — every controller looks identical to the loop/interlock — so Manual gets its input through a setter instead.)
- `engine/loop.py` — `ControlLoop` class. `tick()` implements the full §4 record schema now, not just the fields Phase 1 needs: sensor/detector/interlock stages are honest passthroughs (`t_sensed == t_true`, `interlock_result == "allow"` with a reason string saying why) rather than omitted fields, so later phases fill a stage in without reshaping the schema.
- `app.py` — Streamlit UI: heater slider + live-updating chart (Celsius display-only, Kelvin internal per doc). Live-update mechanism: a `key="running"` toggle: while on, each script run advances one tick, redraws, sleeps `dt_seconds`, then calls `st.rerun()` to trigger the next run.
- Tests: `tests/test_first_order_model.py`, `tests/test_manual_controller.py`, `tests/test_control_loop.py` — 10 new known-outcome scenarios (exact single-Euler-step values, decay-to-ambient, analytical steady-state, passthrough behavior, record-schema stability). 11/11 total passing.

**Verified:** full pytest suite (11/11), Streamlit `AppTest` static render + widget interaction (no exceptions), a `ControlLoop` smoke test against the real `config.yaml`, and — after adding Playwright (below) — an actual headless-browser screenshot confirming the "Run" toggle drives the live chart.

**Tooling added: Playwright**, for headless-browser verification of UI phases. Dev-only, so it's in `requirements-dev.txt`, not `requirements.txt`:
```
source venv/bin/activate && pip install -r requirements-dev.txt && playwright install chromium
```
Chromium itself is cached under `~/Library/Caches/ms-playwright/`, not in the repo. Use it any time a phase touches `app.py` — launch `streamlit run app.py`, drive it with `playwright.sync_api.sync_playwright()`, screenshot before/after an interaction. Gotchas hit so far:
- Streamlit's checkbox/toggle widgets render their label text twice in the DOM in some cases (once in the widget, once in nearby help/info text) — `get_by_text("Run")` was ambiguous; scope to `get_by_test_id("stCheckbox").get_by_text(...)`. With multiple toggles on the page (Phase 3 added two more), disambiguate further with `.filter(has_text="...")`.
- **Streamlit's scrollable container is `section[data-testid="stMain"]`, not `window`/`body`.** Clicking a control lower on the page auto-scrolls that inner container, and neither `page.evaluate("window.scrollTo(0,0)")` nor `page.screenshot(full_page=True)` fixes it (both operate on the outer document, which never actually scrolls). Reset it explicitly before screenshotting: `page.evaluate('document.querySelector(\'[data-testid="stMain"]\').scrollTop = 0')`. Cost real time to diagnose (had to bounding-box the chart element and walk its ancestor chain to find which element actually had `scrollTop > 0`) — worth remembering directly rather than rediscovering.

**Noted for later, not a blocker:** at steady state, `T_ss = T_ambient + heater_pct * k_heat / loss_coeff`. With the current config constants that's ~373.15K (the `interlock.t_max_k` ceiling) at only ~24% heater — so once the interlock lands in Phase 4, most of the slider's/PID's range will get clamped at steady state. This is actually a good demo moment for the interlock, not a tuning bug.

## Phase 2: PID controller + mode toggle

- `engine/controllers/pid.py` — `PIDController`: textbook `output = Kp*e + Ki*∫e + Kd*(de/dt)`, stateful (`_integral`, `_prev_error`), dt fixed at construction (matches the sim's fixed timestep). **Output is not clamped to [0, 100]** — that's the interlock's job (Phase 4), and letting PID (or later, AI) propose something out of range and watching it pass straight through unmodified is exactly the "propose vs. dispose" separation the whole project demonstrates. Don't add clamping here when it's tempting to do so — it belongs in the interlock, not the controller, or the Phase 4 story gets weaker.
- `engine/loop.py` — `ControlLoop.set_mode("manual"|"pid")`, `set_setpoint(k)`, `set_pid_gains(kp, ki, kd)`. Switching *into* PID mode calls `pid.reset()` (clears integral/prev_error) so state from a stale/inactive period doesn't cause an output jump the instant PID resumes control — this is tested directly (`test_switching_back_to_pid_resets_integral_and_derivative_state`).
- **Schema change:** added a `setpoint` field to the per-tick record (not in the architecture doc's example schema in §4). Needed because the setpoint is now a live UI slider, not a fixed constant — the chart needs the setpoint that was actually active at each historical tick, not just "whatever it is right now" retroactively applied. Backward compatible (additive).
- `app.py` — mode radio (Manual/PID), setpoint slider (°C), Kp/Ki/Kd sliders shown only in PID mode. All setters are called unconditionally every rerun (idempotent unless something actually changed), matching the pattern already established for the heater slider in Phase 1.
- Tests: `tests/test_pid_controller.py` (5 known-outcome scenarios — P/I/D terms isolated with synthetic reading sequences, reset behavior, exact 2-tick trace using the real config.yaml gains) + 4 new `ControlLoop` mode-switch integration tests. 20/20 total passing.
- **Verified visually via Playwright:** PID mode screenshot after ~15s simulated shows classic step-response behavior — rise, slight overshoot past the 50°C setpoint line, settle back down. Confirms the controller is actually doing PID, not just producing plausible-looking numbers.

## Phase 3: sensor fault injection

- `engine/sensor.py` — `Sensor`: baseline Gaussian noise always applied; drift/stuck/spike are independent fault modes. **Ordering decision:** stuck-at overrides drift/spike/noise entirely (frozen, no noise layered on) rather than stacking — a real stuck sensor shows suspiciously flat readings, and that near-zero variance is exactly what Phase 4's detector will use to catch it, so faking noise on top of a frozen value would work against that story later.
- **Same idempotent-setter bug class as Phase 2's `pid.reset()`, caught before it shipped:** `app.py` calls `set_drift(enabled)`/`set_stuck(enabled)` unconditionally every rerun (same pattern as `set_mode`/`set_pid_gains`). A naive implementation that reset internal state (elapsed drift time, frozen stuck value) on every call rather than only on an actual OFF→ON transition would have meant drift never accumulates past a fraction of a tick. `Sensor.set_drift`/`set_stuck` guard on `enabled != self._currently_active` before resetting. Directly regression-tested (`test_calling_set_drift_true_repeatedly_does_not_reset_ramp`). **Worth remembering as a general rule for this codebase: any `ControlLoop`/`Sensor` setter called unconditionally from the UI every rerun must be transition-guarded if it has a reset side effect.**
- `engine/loop.py` — `set_drift()`, `set_stuck()`, `trigger_spike()` passthroughs to the sensor; `ControlLoop.__init__` now takes an optional `seed` param. `tick()`'s sensor stage is real now (`t_sensed = self.sensor.read(t_true)`) and `record["active_faults"]` is populated from `self.sensor.active_faults()` instead of being a hardcoded `[]`.
- **Scoping decision on "seeded scenarios":** the doc names three presets (§3.2) for reproducible demos but doesn't specify scripted fault timelines. Implemented as: scenario choice seeds the RNG (reproducible baseline noise), applied on Reset — but *when* faults fire is still operator-driven via the UI toggles/button, not auto-scripted. This is a live demo, not a replay. Full scripted timelines (e.g., "auto-trigger stuck-at at tick 200") weren't built; would be a reasonable Phase 8 polish addition if wanted, not a rearchitecture.
- `config.yaml` — added `drift_rate_k_per_s` (0.05), `spike_offset_k` (5.0), `spike_duration_ticks` (2) alongside existing `noise_sigma_k`/`seeded_scenarios`.
- `app.py` — Drift/Stuck-at toggles, "Trigger spike burst" button (one-shot, not a toggle — spikes are transient per doc §3.2), scenario `selectbox` feeding the seed into `reset_simulation()`. Chart now plots **true vs. sensed vs. setpoint** (was just true vs. setpoint) — essential once the two can diverge, otherwise there's nothing to see.
- Tests: `tests/test_sensor.py` (10 known-outcome scenarios: exact drift values with noise zeroed out, stuck freeze/reset-on-reactivation, spike duration/revert, stuck's override precedence, seeded reproducibility) + 4 new `ControlLoop` integration tests. 34/34 total passing.
- **Verified visually via Playwright:** screenshot sequence shows PID settling near the 50°C setpoint, then — after enabling the stuck-at fault — the sensed line (blue) frozen flat at 50°C while the true temperature (red) visibly drifts down underneath it, undetected by the controller. This is the exact "why we need a safety layer" moment the architecture doc calls for building before Phase 4's detector exists to catch it.

## Phase 4: Tier-1 statistical detector + interlock + historian

The biggest phase so far — three real subsystems, plus one genuine closed-loop bug found and fixed during live verification (below). Full pytest suite: **68/68 passing.**

### Detector (`engine/detector.py`)

Rolling z-score (spike), CUSUM (drift), rolling variance (stuck), tuned empirically against synthetic fault sequences rather than hand-derived (CUSUM by hand is error-prone) — same approach as validating the plant constants in Phase 1. Standardization uses the *configured* `noise_sigma_k`, not an empirically re-estimated rolling std (a small window's std estimate is itself noisy). Final tuned values in `config.yaml`: `window_ticks=30, z_score_threshold=6.0, cusum_slack_k=1.0, cusum_threshold_h=9.0, stuck_variance_ratio=0.1`. Verified: zero false positives across 5000+ clean-noise ticks, real drift/spike/stuck all caught within a reasonable tick window.

**CUSUM accumulators are capped** at `2× cusum_threshold_h` — without this, an extreme residual can push the accumulator so high that unwinding it afterward (bounded by `slack_k` per tick) takes an unreasonably long time even once the signal is actually calm again.

### The runaway bug (the important part)

Every individual piece (detector, interlock) passed its own thorough unit tests. Only when I ran the *full closed loop* live (PID mode, default gains, fresh start) did a real bug show up: the chart showed sensed temperature climbing linearly through 100°C+ with no sign of curving back toward the 50°C setpoint.

Root cause, confirmed via tick-by-tick tracing: a normal PID startup ramp (cold plant chasing a setpoint tens of Kelvin away) is statistically indistinguishable from the drift *fault* to simple rolling statistics — both are "sustained directional deviation from recent history." At tick 6, the detector false-flagged spike+drift during the ordinary startup ramp. The interlock did exactly what it's designed to do: froze the actuator at "last-known-good" (50%, whatever PID happened to be commanding mid-ramp). But 50% heater is nowhere near equilibrium for the temperature at that moment, so the plant kept heating — which kept looking like ongoing drift to the detector, since the window mean chased the ever-rising signal — so the flag never cleared. **A false alarm that caused the very condition that sustained it, forever.** The CUSUM cap (above) didn't help, because it only bounds recovery time *once the signal stabilizes* — here the frozen-but-wrong actuator meant the signal never stabilized on its own.

**Fix:** `Detector.boot_grace_ticks` (config: `50`) — the detector accepts no readings at all (doesn't touch window/CUSUM state) until that many ticks have passed, so when it does start, it starts genuinely fresh, after a normal startup transient has already had time to settle, rather than reacting to the transient itself. `Detector.reset()` also restarts this grace period, and `ControlLoop.set_setpoint()` calls `reset()` on any live setpoint change bigger than 1K (guarded so a jittering slider doesn't reset constantly) — a big live setpoint change is the same kind of event as a cold boot. Empirically validated: grace=40 already fully prevented the runaway across 5 seeds; grace=50 ships with margin. Confirmed a *real* fault introduced well after the grace period (e.g. stuck-at 30+ ticks after settling) still gets caught normally — the fix silences startup noise, not real faults.

**Two regression tests lock this in permanently**, using the actual shipped `config.yaml` (not a hand-rolled test config) so a future retune that reintroduces the bug gets caught: `test_pid_startup_settles_without_false_interlock_freeze_using_real_config`, `test_real_stuck_fault_after_settling_is_still_caught_using_real_config` (both in `test_control_loop.py`).

**Lesson for later phases:** unit tests on each component in isolation are necessary but not sufficient for a *closed loop* — component interactions (detector's output feeding the interlock's input feeding the plant's input feeding back into what the detector sees next) can create emergent behavior no single component's tests would catch. Worth deliberately running the full loop live before considering a phase done, not just the embedded pytest suite.

### Interlock (`engine/interlock.py`)

Implements all 4 checks from doc §3.4, operating on `t_sensed` only (never `t_true`) — a corrupted sensor could in principle fool the bounds check, which is exactly why the sensor-trust gate runs first. **Override-eligibility interpretation** (the doc is slightly ambiguous here, so recording the reasoning): checks 1 (sensor-trust) and 3 (slew-rate) are **absolute, never overridable by anyone** — the doc's "regardless of source"/"regardless of who proposed it" phrasing is specific to these two, and check 3's own example ("catches ... a fat-fingered manual override") only makes sense if manual can't bypass it. **Only check 2 (bounds/margin) is manual-overridable**, with `override_active=True` logged. All 16 known-outcome tests in `test_interlock.py` passed on the first run, which is a decent signal the interpretation is internally consistent.

**Schema addition:** `override_active: bool` on the per-tick record (additive, backward compatible — same pattern as Phase 2's `setpoint` field).

**Not live-Playwright-tested:** the manual-override-near-ceiling scenario. Structural reason, not a shortcut: the actuator saturates at 100% in ~2.5s (slew-limited ramp), which happens *before or concurrently with* the thermal ceiling margin being reached at the current tuning — so "propose an increase while already pinned near the ceiling" can't arise through a live ramp with default config. Thoroughly covered instead by direct-state-manipulation pytest tests (`test_manual_override_flows_through_to_interlock_end_to_end`, plus `test_interlock.py`'s dedicated bounds tests).

### Historian (`storage/historian.py`)

Per doc §7.4: `ControlLoop` has **zero knowledge of the historian** — the UI layer owns both the in-memory hot-path list and the historian, and fans each tick out to both. A background daemon thread drains a `queue.Queue` on a timer (5s default) and bulk-inserts into TimescaleDB; every DB call is wrapped so a failure logs and retries, never raises into the caller. `record()` uses `put_nowait` on a bounded queue (drops+logs if full) — genuinely never blocks, verified by timing it against an unreachable DB (<0.1ms). Schema: a `ticks` hypertable, columns matching the tick record (minus `proposed_action`, which isn't JSON-serializable as-is). `TIMESCALE_DSN` added to `.env`/`.env.example`. Historian's lifecycle is independent of `ControlLoop`'s — constructed once per Streamlit session, keeps running across Resets, matching how a real historian doesn't restart with the process it's observing.

### `app.py`

Detector flags (Tier-1 belief) shown alongside `active_faults` (ground truth) side by side — deliberately, since the gap between what's really happening and what the detector believes is the whole point. A real **decision log** table (doc: "the most important UI element in the whole project") — last 15 ticks, tick/source/output/result/reason/override/flags. Manual-only "Override interlock" toggle; a persistent red banner (via an `st.empty()` placeholder created early in the script and filled in after that rerun's tick, so it reflects the freshest decision) appears specifically when `override_active` is true that tick, not just when the toggle is armed.

### Verified visually via Playwright

PID settles cleanly near the 50°C setpoint (confirms the runaway is actually fixed, not just passing in tests). Then enabling the stuck-at fault: sensed line freezes flat, true temperature visibly diverges underneath it, and the decision log shows `reject` / "sensor untrusted ... holding at last-known-good" with `detector_flags=stuck` — the exact story doc §5 phase 4 asks for: "faults get caught and the interlock freezes control ... before any AI is involved at all."

## Phase 5: AI controller (Claude)

Full pytest suite: **82/82 passing** (10 new `test_ai_controller.py`, 4 new `ControlLoop` integration tests in `test_control_loop.py`). Plus a live, real-API integration check (below) and a live Playwright run that made genuine Claude API calls end to end.

### Structured output: tool-use, not prompt-and-parse

Doc §3.6 lists "malformed JSON" as a failure mode to handle, which suggests asking the model for JSON in free text and parsing the result — fragile by construction. Used Anthropic's tool-use API instead (`tool_choice={"type": "tool", "name": "propose_heater_output"}`), which makes syntactically-invalid JSON structurally impossible, plus a pydantic model (`AIProposalSchema`) validating the *semantic* shape on top (right types, right enum values). "Malformed response" as a failure case still fully exists and is still explicitly tested — it just means "no tool call" or "failed validation" now, never a JSON parse error. Same doc-specified behavior, more robust implementation.

### Real async execution, not a blocking call (§3.3.1)

A synchronous API call (confirmed live: ~4s) would freeze the whole Streamlit script for several seconds every tick, directly violating "hold last value while a call is in flight, don't block." `AIController` runs each call in a background daemon thread (same pattern as the historian's writer thread) — `propose()` always returns immediately: either a freshly-arrived decision, or the last-committed value while a call is still in flight. Only one call is ever in flight at a time (guarded by checking `thread.is_alive()` before starting a new one). Thread-safe handoff via a lock-guarded "pending result" slot, not a full queue, since there's only ever one producer and one consumer.

### Interface change: `Controller.propose()` gains `detector_flags`

Doc §3.3 explicitly wants the AI's prompt to include "the current reading, setpoint, recent history window, and detector flag." There was no clean channel for the detector flag under the old 3-arg signature, so the shared interface grew a 4th parameter. Manual/PID ignore it (same as they already ignore `history`) — this is why every existing direct `.propose(...)` call in the test suite needed updating (mechanical, not a design change to those controllers).

### `ControlLoop` now keeps its own history

It didn't before — only the UI's `st.session_state.history` existed. Added a bounded `deque` (sized from `ai.history_window_ticks`) so the AI controller has something to look at; Manual/PID still ignore it.

### Failure handling (§3.6) — three stages, split across two objects

`AIController` tracks `seconds_since_last_success()` (via an **injectable clock**, so tests never need to actually sleep) but doesn't act on it — it only reports. `ControlLoop.tick()` does the acting: past `max_response_wait_s` (10s), the UI shows a countdown warning; past `max_response_wait_s + fallback_after_s` (10s more, total 20s — the doc doesn't give an exact number for the second stage, this is a documented interpretation), `ControlLoop` substitutes `ai.safe_output_pct` (0.0 — no active cooling in this system, off is safe) for that tick's proposal, still passed through the interlock like any other proposal, logged via a new `ai_fallback_active` record field (additive, same pattern as `override_active`/`setpoint`). **Kept `controller_source="ai"` during fallback** rather than silently relabeling it "manual" — it's still nominally AI mode, the system is substituting a value on AI's behalf, not secretly changing modes out from under the UI's own mode selector (which keeps re-asserting whatever the radio button says on every rerun — a genuine mode *switch* here would just get immediately overwritten by that, so the fallback is computed fresh each tick from elapsed time instead of being a persistent state flip).

### Testability

Both the Anthropic client and the clock are constructor-injectable. Tests use a small fake client (`FakeClient`/`FakeMessages`/`FakeToolUseBlock`) returning canned responses — success, no tool call, failed validation, a raised exception — plus a `threading.Event`-gated fake response to deterministically test the "hold while pending" behavior without real timing races. No test hits the real network.

### Verified against the real API

A scratch script constructed a real `anthropic.Anthropic` client (key already in `.env`) and called `AIController.propose()` directly: returned in 0.001s (non-blocking confirmed), the real call took 4.10s, and Claude's actual response was well-formed and sensibly reasoned ("Temperature is rising steadily... avoiding overshoot").

### Verified visually via Playwright (real API calls, not mocked)

AI mode screenshot after ~25s shows genuinely intelligent reasoning in the rationale field: the plant overshot to ~140°C (more than PID's tuned response), and the AI correctly diagnosed *why* ("still near peak despite actuator already being ramped down... system overshot significantly due to thermal lag; heater should be fully off... only reintroduced once temperature trends back down") and proposed heater=0% accordingly. Decision log confirms `controller_source=ai` flowing correctly through the interlock (`allow`/"within bounds"). The AI-vs-PID overshoot difference is itself a legitimate, interesting finding — exactly the comparison this whole project exists to enable, per doc §1's primary goal.

## Post-Phase-5: interlock hard over/under-temperature trip

User watched the AI-mode overshoot above happen live and asked why the interlock didn't stop it. Root cause: the existing margin check (§3.4's `bound_margin_k` rule) only blocks a proposal that pushes *further toward* a bound — it has no mechanism to force a decrease. Once the AI itself started reducing output, every subsequent proposal was a decrease, which that rule never touches, so the interlock had nothing left to block while the plant coasted (via thermal lag) well past `t_max_k` (373.15K/100°C) up to ~413K.

**Fix:** a new check 2 in `engine/interlock.py` (renumbering the rest), inserted between the sensor-trust gate and the margin check — a genuine "high-high" trip to the margin check's "high" alarm. Once `t_sensed` is actually at or past `t_max_k`/`t_min_k` (not just within margin), force `interlock.trip_safe_output_pct` (0.0 — no active cooling, off is safe) regardless of what's proposed or which direction, **absolute, no override** (user explicitly confirmed this choice over manual-overridable), and **bypasses the slew limit** — an emergency trip has to reach the safe value immediately, not get rate-limited like routine control. Symmetric floor-side trip forces 100% instead (correct direction for "too cold"), though it's practically unreachable given this system's physics (no active cooling, ambient sits well above `t_min_k`) — included so the interlock is honestly symmetric rather than silently one-sided.

22 known-outcome tests in `test_interlock.py` now (6 new), including: fires on a decrease proposal (the whole point — margin check wouldn't), can't be overridden even with override requested, bypasses slew, floor case forces max heat, boundary case just below the threshold still uses the softer margin path, and sensor-untrusted still takes priority when both conditions are true simultaneously. 88/88 total passing.

**Verified live:** re-ran the exact same AI-mode scenario that originally overshot to ~140°C. This time it capped at ~103°C (376K peak per the AI's own rationale, one tick of thermal lag past the 373.15K trip point) and cleanly declined back toward setpoint — the fix visibly working, not just passing in tests.

**Note:** this is a different mechanism from backlog item 3 below (auto-safe-default after *sustained interlock rejection*, regardless of cause) — this new trip fires on the sensed *temperature value* itself, independent of how long anything's been rejecting. They're complementary, not overlapping.

## Build order (tracked as tasks #1-#9, #1-#6 done)

Follows architecture doc §5, with two adjustments the user explicitly approved:
- **Historian writes deferred to Phase 4**, not wired early — `docker-compose.yml` stands up TimescaleDB as infra now, but the batched async writer (`storage/historian.py`) doesn't get implemented until Phase 4, alongside the interlock's sensor-trust gate. Keeps Phases 1-3 focused on physics/control logic.
- **Tests embedded per phase**, not a separate testing pass at the end — each phase that introduces new logic ships with a small pytest suite of known-outcome scenarios as part of its definition of done (this directly addresses a gap the architecture doc calls out in §10).

Phases: (1) plant + manual control, (2) PID + mode toggle, (3) sensor fault injection, (4) Tier-1 statistical detector + interlock sensor-trust gate + historian wiring, (5) AI controller, (6) interlock bounds/rate-limit checks vs. AI + decision log UI, (7) Tier-2 LLM triage, (8) README/docs/walkthrough polish.

Deferred to stretch goals (per doc §9, §11 — not in the numbered build order): FastAPI/WebSocket service split, second-order plant model, Redis hot path, Delta Lake alternative, multi-loop interlock demo.

## Phase 5.5: interlock lockout mechanism (backlog items 1-5)

Not part of the original architecture doc's build order — five user-requested refinements to the Phase 4 interlock, all built together as one coherent mechanism since they share the same underlying state. Full pytest suite: **100/100 passing** (32 in `test_interlock.py` alone, up from 22). Three design forks were confirmed with the user via explicit questions before building, rather than guessed — all three confirmed-recommended options, and all 32 interlock tests passed on the first run afterward, a decent signal the interpretation was internally consistent.

### The three confirmed design decisions

1. **"Fires N times" = separate trip episodes**, not consecutive ticks — temperature must drop back under the threshold between counted trips. This measures the controller repeatedly failing to learn across distinct excursions, not how long one excursion lasts.
2. **"Correction" = the controller proposing something at/near the trip's safe value** (within `trip_correction_tolerance_pct`, default 1.0) during the calm gap between episodes — judged against what the controller *proposed*, not what the interlock actually *applied* (which was clamped regardless).
3. **The hard trip wins over a plain sensor-distrust hold** when both are true simultaneously (temperature past a hard bound AND sensor untrusted) — reasoning: forcing a safe output is one-directional and can't make the outcome worse, even when acting on an already-untrusted reading, unlike a routine control decision which could easily be made worse by trusting bad data.

### What actually changed (`engine/interlock.py`)

- **New check 0 (lockout gate)**, ahead of everything else: if `locked_out`, every proposal is refused and `trip_safe_output_pct` forced, until `reset_lockout()` is called. Absolute, no override, any source.
- **Check 1 (sensor-trust gate) now has three behaviors instead of one**: plain hold (unchanged default), forced safe output if simultaneously past a hard bound (item 5), or forced safe output if untrusted longer than `untrusted_auto_safe_after_s` (item 3, default 20s) — this one is self-clearing, not a lockout, matching the AI controller's dead-man-timer shape from §3.6.
- **Check 2 (hard trip) now tracks episodes and escalates**: a `trip_strikes` counter increments on each new episode (transition from not-tripped to tripped) unless the controller corrected during the prior gap, in which case it resets to 1. At `trip_lockout_threshold` (default 2), `locked_out` engages.
- **New `Interlock.reset_lockout()`** — clears lockout/strikes/correction-tracking state. Does NOT touch `last_output`.
- **Injectable `clock` param** (default `time.time`), same testability pattern as `AIController` — tests use a `FakeClock` to simulate elapsed untrusted-duration without real sleeping.

### `ControlLoop`

- **New `reset_interlock()`** — calls `interlock.reset_lockout()` **and** `detector.reset()`. Deliberate: "I've confirmed it's safe, resume normal control" should mean the whole safety pipeline gets a clean slate, not just the interlock's own escalation counter clearing while the detector's window/CUSUM state carries over stale.
- **New `interlock_locked_out` record field** (additive, same pattern as `override_active`/`ai_fallback_active`).

### `app.py`

- **"Reset Interlock" button** next to "Reset", wired to `loop.reset_interlock()`. Harmless to press when there's nothing to reset.
- **Lockout banner takes priority over the override/AI-fallback banners** — it's the most severe state, checked first in the same `st.empty()` placeholder pattern.
- **Trip-strike count shown** whenever `trip_strikes > 0`, even at strike 1 (before lockout), so an operator can see it escalating.
- **Decision log**: `DECISION_LOG_ROWS_DEFAULT` raised to 50 (from 15), plus a "Show full history" checkbox for the complete rolling buffer, and a new `interlock_locked_out` column (item 1).

### Fixed a test that encoded the old, now-intentionally-reversed behavior

`test_sensor_untrusted_takes_priority_over_hard_trip` asserted the *old* Phase-4-era behavior (hold at last-known-good even past a hard bound). Item 5 deliberately reverses this, so the test's assertion was now wrong on purpose — replaced with `test_hard_bound_wins_over_sensor_untrusted_not_last_known_good` (new behavior) plus `test_sensor_untrusted_below_hard_bound_still_holds_at_last_known_good` (confirms the plain-hold path still works when no hard bound is involved). Worth remembering as a general pattern: when a backlog item explicitly reverses previously-locked-in behavior, grep for the test that encoded the old behavior before assuming the new implementation is broken just because an old test fails.

### Verified two ways

1. **Scripted trace against the real `config.yaml`**, manual mode, heater pinned at 50% (never corrected): episode 1 tripped at tick 25 (~12.5s simulated), episode 2 at tick 35 (~17.5s), lockout engaged exactly as designed, stayed locked despite a new 100% proposal, and `reset_interlock()` cleared it fully back to normal evaluation.
2. **Live in the browser via Playwright**, same scenario: banner text matches exactly, chart shows the two trip episodes as visible bumps near the 100°C ceiling, and after clicking "Reset Interlock" the banner disappears and the actuator resumes its normal slew-limited ramp. Real Playwright gotcha hit here: Streamlit's slider is a visually-hidden `<input type="range">` (clip-path trick behind a styled thumb, no `role="slider"`) — `.click()` fails since Playwright's visibility check rejects it; use `.focus()` + keyboard (`Home` then repeated `ArrowRight`) instead. Locate it via `input[type="range"][aria-label="<slider label>"]`.

## Backlog

Planned enhancements not yet scheduled into a build-order phase now live in `BACKLOG.md`, not here — check there before starting new interlock/UI work. Moved out of this file 2026-08-05 so `CLAUDE.md` stays focused on current status rather than accumulating an ever-growing list.
