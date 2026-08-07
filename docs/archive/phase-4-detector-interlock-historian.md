# Phase 4: Tier-1 statistical detector + interlock + historian

Archived detailed build write-up — moved out of `CLAUDE.md` on 2026-08-07 to keep that file focused on current status. See `../../CLAUDE.md` for where the project stands now.

---

The biggest phase so far — three real subsystems, plus one genuine closed-loop bug found and fixed during live verification (below). Full pytest suite: **68/68 passing.**

## Detector (`engine/detector.py`)

Rolling z-score (spike), CUSUM (drift), rolling variance (stuck), tuned empirically against synthetic fault sequences rather than hand-derived (CUSUM by hand is error-prone) — same approach as validating the plant constants in Phase 1. Standardization uses the *configured* `noise_sigma_k`, not an empirically re-estimated rolling std (a small window's std estimate is itself noisy). Final tuned values in `config.yaml`: `window_ticks=30, z_score_threshold=6.0, cusum_slack_k=1.0, cusum_threshold_h=9.0, stuck_variance_ratio=0.1`. Verified: zero false positives across 5000+ clean-noise ticks, real drift/spike/stuck all caught within a reasonable tick window.

**CUSUM accumulators are capped** at `2× cusum_threshold_h` — without this, an extreme residual can push the accumulator so high that unwinding it afterward (bounded by `slack_k` per tick) takes an unreasonably long time even once the signal is actually calm again.

## The runaway bug (the important part)

Every individual piece (detector, interlock) passed its own thorough unit tests. Only when I ran the *full closed loop* live (PID mode, default gains, fresh start) did a real bug show up: the chart showed sensed temperature climbing linearly through 100°C+ with no sign of curving back toward the 50°C setpoint.

Root cause, confirmed via tick-by-tick tracing: a normal PID startup ramp (cold plant chasing a setpoint tens of Kelvin away) is statistically indistinguishable from the drift *fault* to simple rolling statistics — both are "sustained directional deviation from recent history." At tick 6, the detector false-flagged spike+drift during the ordinary startup ramp. The interlock did exactly what it's designed to do: froze the actuator at "last-known-good" (50%, whatever PID happened to be commanding mid-ramp). But 50% heater is nowhere near equilibrium for the temperature at that moment, so the plant kept heating — which kept looking like ongoing drift to the detector, since the window mean chased the ever-rising signal — so the flag never cleared. **A false alarm that caused the very condition that sustained it, forever.** The CUSUM cap (above) didn't help, because it only bounds recovery time *once the signal stabilizes* — here the frozen-but-wrong actuator meant the signal never stabilized on its own.

**Fix:** `Detector.boot_grace_ticks` (config: `50`) — the detector accepts no readings at all (doesn't touch window/CUSUM state) until that many ticks have passed, so when it does start, it starts genuinely fresh, after a normal startup transient has already had time to settle, rather than reacting to the transient itself. `Detector.reset()` also restarts this grace period, and `ControlLoop.set_setpoint()` calls `reset()` on any live setpoint change bigger than 1K (guarded so a jittering slider doesn't reset constantly) — a big live setpoint change is the same kind of event as a cold boot. Empirically validated: grace=40 already fully prevented the runaway across 5 seeds; grace=50 ships with margin. Confirmed a *real* fault introduced well after the grace period (e.g. stuck-at 30+ ticks after settling) still gets caught normally — the fix silences startup noise, not real faults.

**Two regression tests lock this in permanently**, using the actual shipped `config.yaml` (not a hand-rolled test config) so a future retune that reintroduces the bug gets caught: `test_pid_startup_settles_without_false_interlock_freeze_using_real_config`, `test_real_stuck_fault_after_settling_is_still_caught_using_real_config` (both in `test_control_loop.py`).

**Lesson for later phases:** unit tests on each component in isolation are necessary but not sufficient for a *closed loop* — component interactions (detector's output feeding the interlock's input feeding the plant's input feeding back into what the detector sees next) can create emergent behavior no single component's tests would catch. Worth deliberately running the full loop live before considering a phase done, not just the embedded pytest suite.

(This exact lesson repeated on 2026-08-07: a Gemini code review pass found a second instance of the same emergent-gap pattern in `reset_interlock()`'s interaction with the detector's boot-grace period — see `CODE_REVIEW.md` finding H.1 and `BACKLOG.md` item 8.)

## Interlock (`engine/interlock.py`)

Implements all 4 checks from doc §3.4, operating on `t_sensed` only (never `t_true`) — a corrupted sensor could in principle fool the bounds check, which is exactly why the sensor-trust gate runs first. **Override-eligibility interpretation** (the doc is slightly ambiguous here, so recording the reasoning): checks 1 (sensor-trust) and 3 (slew-rate) are **absolute, never overridable by anyone** — the doc's "regardless of source"/"regardless of who proposed it" phrasing is specific to these two, and check 3's own example ("catches ... a fat-fingered manual override") only makes sense if manual can't bypass it. **Only check 2 (bounds/margin) is manual-overridable**, with `override_active=True` logged. All 16 known-outcome tests in `test_interlock.py` passed on the first run, which is a decent signal the interpretation is internally consistent.

**Schema addition:** `override_active: bool` on the per-tick record (additive, backward compatible — same pattern as Phase 2's `setpoint` field).

**Not live-Playwright-tested:** the manual-override-near-ceiling scenario. Structural reason, not a shortcut: the actuator saturates at 100% in ~2.5s (slew-limited ramp), which happens *before or concurrently with* the thermal ceiling margin being reached at the current tuning — so "propose an increase while already pinned near the ceiling" can't arise through a live ramp with default config. Thoroughly covered instead by direct-state-manipulation pytest tests (`test_manual_override_flows_through_to_interlock_end_to_end`, plus `test_interlock.py`'s dedicated bounds tests).

## Historian (`storage/historian.py`)

Per doc §7.4: `ControlLoop` has **zero knowledge of the historian** — the UI layer owns both the in-memory hot-path list and the historian, and fans each tick out to both. A background daemon thread drains a `queue.Queue` on a timer (5s default) and bulk-inserts into TimescaleDB; every DB call is wrapped so a failure logs and retries, never raises into the caller. `record()` uses `put_nowait` on a bounded queue (drops+logs if full) — genuinely never blocks, verified by timing it against an unreachable DB (<0.1ms). Schema: a `ticks` hypertable, columns matching the tick record (minus `proposed_action`, which isn't JSON-serializable as-is). `TIMESCALE_DSN` added to `.env`/`.env.example`. Historian's lifecycle is independent of `ControlLoop`'s — constructed once per Streamlit session, keeps running across Resets, matching how a real historian doesn't restart with the process it's observing.

## `app.py`

Detector flags (Tier-1 belief) shown alongside `active_faults` (ground truth) side by side — deliberately, since the gap between what's really happening and what the detector believes is the whole point. A real **decision log** table (doc: "the most important UI element in the whole project") — last 15 ticks, tick/source/output/result/reason/override/flags. Manual-only "Override interlock" toggle; a persistent red banner (via an `st.empty()` placeholder created early in the script and filled in after that rerun's tick, so it reflects the freshest decision) appears specifically when `override_active` is true that tick, not just when the toggle is armed.

## Verified visually via Playwright

PID settles cleanly near the 50°C setpoint (confirms the runaway is actually fixed, not just passing in tests). Then enabling the stuck-at fault: sensed line freezes flat, true temperature visibly diverges underneath it, and the decision log shows `reject` / "sensor untrusted ... holding at last-known-good" with `detector_flags=stuck` — the exact story doc §5 phase 4 asks for: "faults get caught and the interlock freezes control ... before any AI is involved at all."
