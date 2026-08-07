# Phase 5.5: interlock lockout mechanism (backlog items 1-5)

Archived detailed build write-up — moved out of `CLAUDE.md` on 2026-08-07 to keep that file focused on current status. See `../../CLAUDE.md` for where the project stands now.

---

Not part of the original architecture doc's build order — five user-requested refinements to the Phase 4 interlock, all built together as one coherent mechanism since they share the same underlying state. Full pytest suite: **100/100 passing** (32 in `test_interlock.py` alone, up from 22). Three design forks were confirmed with the user via explicit questions before building, rather than guessed — all three confirmed-recommended options, and all 32 interlock tests passed on the first run afterward, a decent signal the interpretation was internally consistent.

## The three confirmed design decisions

1. **"Fires N times" = separate trip episodes**, not consecutive ticks — temperature must drop back under the threshold between counted trips. This measures the controller repeatedly failing to learn across distinct excursions, not how long one excursion lasts.
2. **"Correction" = the controller proposing something at/near the trip's safe value** (within `trip_correction_tolerance_pct`, default 1.0) during the calm gap between episodes — judged against what the controller *proposed*, not what the interlock actually *applied* (which was clamped regardless).
3. **The hard trip wins over a plain sensor-distrust hold** when both are true simultaneously (temperature past a hard bound AND sensor untrusted) — reasoning: forcing a safe output is one-directional and can't make the outcome worse, even when acting on an already-untrusted reading, unlike a routine control decision which could easily be made worse by trusting bad data.

## What actually changed (`engine/interlock.py`)

- **New check 0 (lockout gate)**, ahead of everything else: if `locked_out`, every proposal is refused and `trip_safe_output_pct` forced, until `reset_lockout()` is called. Absolute, no override, any source.
- **Check 1 (sensor-trust gate) now has three behaviors instead of one**: plain hold (unchanged default), forced safe output if simultaneously past a hard bound (item 5), or forced safe output if untrusted longer than `untrusted_auto_safe_after_s` (item 3, default 20s) — this one is self-clearing, not a lockout, matching the AI controller's dead-man-timer shape from §3.6.
- **Check 2 (hard trip) now tracks episodes and escalates**: a `trip_strikes` counter increments on each new episode (transition from not-tripped to tripped) unless the controller corrected during the prior gap, in which case it resets to 1. At `trip_lockout_threshold` (default 2), `locked_out` engages.
- **New `Interlock.reset_lockout()`** — clears lockout/strikes/correction-tracking state. Does NOT touch `last_output`.
- **Injectable `clock` param** (default `time.time`), same testability pattern as `AIController` — tests use a `FakeClock` to simulate elapsed untrusted-duration without real sleeping.

## `ControlLoop`

- **New `reset_interlock()`** — calls `interlock.reset_lockout()` **and** `detector.reset()`. Deliberate: "I've confirmed it's safe, resume normal control" should mean the whole safety pipeline gets a clean slate, not just the interlock's own escalation counter clearing while the detector's window/CUSUM state carries over stale.
  - **2026-08-07 follow-up:** a Gemini code review pass found a real edge case in this exact design — `detector.reset()` also re-arms the detector's 25s boot-grace period, which can mask a fault that's still genuinely active if the operator resets without also clearing the fault toggle. See `CODE_REVIEW.md` finding H.1 and `BACKLOG.md` item 8 for the confirmed bug and designed fix (not yet built).
- **New `interlock_locked_out` record field** (additive, same pattern as `override_active`/`ai_fallback_active`).

## `app.py`

- **"Reset Interlock" button** next to "Reset", wired to `loop.reset_interlock()`. Harmless to press when there's nothing to reset.
- **Lockout banner takes priority over the override/AI-fallback banners** — it's the most severe state, checked first in the same `st.empty()` placeholder pattern.
- **Trip-strike count shown** whenever `trip_strikes > 0`, even at strike 1 (before lockout), so an operator can see it escalating.
- **Decision log**: `DECISION_LOG_ROWS_DEFAULT` raised to 50 (from 15), plus a "Show full history" checkbox for the complete rolling buffer, and a new `interlock_locked_out` column (item 1).

## Fixed a test that encoded the old, now-intentionally-reversed behavior

`test_sensor_untrusted_takes_priority_over_hard_trip` asserted the *old* Phase-4-era behavior (hold at last-known-good even past a hard bound). Item 5 deliberately reverses this, so the test's assertion was now wrong on purpose — replaced with `test_hard_bound_wins_over_sensor_untrusted_not_last_known_good` (new behavior) plus `test_sensor_untrusted_below_hard_bound_still_holds_at_last_known_good` (confirms the plain-hold path still works when no hard bound is involved). Worth remembering as a general pattern: when a backlog item explicitly reverses previously-locked-in behavior, grep for the test that encoded the old behavior before assuming the new implementation is broken just because an old test fails.

## Verified two ways

1. **Scripted trace against the real `config.yaml`**, manual mode, heater pinned at 50% (never corrected): episode 1 tripped at tick 25 (~12.5s simulated), episode 2 at tick 35 (~17.5s), lockout engaged exactly as designed, stayed locked despite a new 100% proposal, and `reset_interlock()` cleared it fully back to normal evaluation.
2. **Live in the browser via Playwright**, same scenario: banner text matches exactly, chart shows the two trip episodes as visible bumps near the 100°C ceiling, and after clicking "Reset Interlock" the banner disappears and the actuator resumes its normal slew-limited ramp. Real Playwright gotcha hit here: Streamlit's slider is a visually-hidden `<input type="range">` (clip-path trick behind a styled thumb, no `role="slider"`) — `.click()` fails since Playwright's visibility check rejects it; use `.focus()` + keyboard (`Home` then repeated `ArrowRight`) instead. Locate it via `input[type="range"][aria-label="<slider label>"]`.
