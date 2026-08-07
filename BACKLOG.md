# Backlog

Planned enhancements not yet scheduled into a build-order phase. Not part of `docs/control-loop-architecture.md`'s original design — these are refinements identified during/after Phase 4-5 development. See `CLAUDE.md` for current build status.

Check an item off (`- [x]`) when it ships, and note which commit/phase closed it.

---

## Interlock / UI enhancements

Requested 2026-08-05, while starting Phase 5. All five items below shipped together as "Phase 5.5" — see `CLAUDE.md`'s Phase 5.5 section for the full design writeup.

- [x] **1. Decision log: show more history.** Shipped Phase 5.5. `DECISION_LOG_ROWS_DEFAULT` raised to 50, plus a "Show full history" checkbox that displays the entire rolling buffer (up to `HISTORY_LIMIT`=500 ticks).

- [x] **2. Manual "reset interlock" action.** Shipped Phase 5.5. `ControlLoop.reset_interlock()` (wired to a "Reset Interlock" button in `app.py`) clears a latched lockout **and** resets the detector's window/CUSUM state — a full fresh start for the whole safety pipeline, not just the interlock's own escalation counter. Logged distinctly (the next tick's `interlock_result` simply reads "allow" again, and the persistent lockout banner disappears).

- [x] **3. Auto-safe-default after sustained interlock activation.** Shipped Phase 5.5, as `Interlock.untrusted_auto_safe_after_s` (config default 20.0s). While the sensor-trust gate is active, once the untrusted period exceeds this threshold, the interlock forces `trip_safe_output_pct` instead of continuing to hold at whatever was last-known-good. Self-clearing (not a lockout) — resumes normal hold behavior the moment the sensor is trusted again, and the timer restarts from zero if it goes untrusted again later.

- [x] **4. Escalate the hard over/under-temperature trip to a latching lockout after repeated firings without correction.** Shipped Phase 5.5. Design questions resolved (user-confirmed, see CLAUDE.md): "fires N times" means separate trip *episodes* (temperature must drop back under the threshold between counted trips), "correction" means the controller proposing something at/near the trip's safe value (within `trip_correction_tolerance_pct`) during the calm gap between episodes, and "before it allows a new control" means a full lockout that force-holds the safe output and refuses every proposal from any controller until item 2's manual reset clears it. `trip_lockout_threshold` (config default 2) controls the strike count. Verified live: real config timing produced lockout at ~17.5 simulated seconds with default manual heater=50%.

- [x] **5. Sensor-trust "hold at last-known-good" can itself hold at an unsafe value.** Shipped Phase 5.5, resolved per user's confirmed direction: the hard trip now wins over a plain sensor-distrust hold whenever the sensed temperature is simultaneously past a hard bound (reasoning: forcing a safe output is one-directional and can't make the outcome worse, even acting on an already-untrusted reading, unlike a routine control decision). `test_hard_bound_wins_over_sensor_untrusted_not_last_known_good` locks this in, replacing the old (intentionally reversed) `test_sensor_untrusted_takes_priority_over_hard_trip`.

---

## Streamlit / triage follow-ups

Requested 2026-08-07, after Phase 7 shipped.

- [ ] **6. `st.dataframe`'s `use_container_width` is deprecated.** `app.py:275` (the decision log table) passes `use_container_width=True`; Streamlit warns to replace it with `width="stretch"` (the `use_container_width` param is slated for removal, and per the warning text the removal date of 2025-12-31 has already passed as of today — worth checking which installed Streamlit version we're actually on, since it may already be silently ignoring the old param rather than just warning). Low-risk one-line fix; not done opportunistically because it's unrelated to Phase 7's actual scope.

- [ ] **7. Extend Tier-2 triage to explain interlock activity, not just detector flags.** Currently `Triage` (see `engine/triage.py`, Phase 7) only triggers off Tier-1 detector flags (spike/drift/stuck) and only sees sensor readings in its prompt. User wants to also be able to ask Claude to explain interlock behavior — e.g. "why did the interlock reject/clamp/trip/lock out just now" — narrating the safety-layer story (margin rejections, hard trips, lockouts, overrides), not just sensor-fault diagnosis. **Resolved (2026-08-07): the trigger can broaden freely to "any non-`allow` interlock result in recent history"** — user confirmed cost control comes from the button being manual-click-only, not from how rarely it's *enabled*; a button that's enabled more often still spends nothing until clicked. Remaining open design questions before building: (a) does the prompt need windowed *decision log* entries (result/reason/override_active/interlock_locked_out) in addition to the raw readings it already gets — almost certainly yes, that's the whole point; (b) one triage button/prompt that covers both detector and interlock context together, or two separate asks — leaning toward one combined button/prompt, since the two stories (sensor fault vs. interlock response to it) are usually the same underlying incident and a single narration is more useful than forcing the operator to piece two explanations together themselves, but worth confirming before building.

---

## Safety / interlock fixes

Requested 2026-08-07, from a Gemini code-review pass (see `CODE_REVIEW.md` finding H.1) — independently verified as a genuine bug, not just a review suggestion.

- [ ] **8. `reset_interlock()` re-arms the detector's 25s boot-grace period, masking a still-active fault.** `ControlLoop.reset_interlock()` (`engine/loop.py:121`) calls `self.detector.reset()` unconditionally, which restarts `Detector.boot_grace_ticks` (config: 50 ticks = 25 simulated seconds) — during that window `Detector.evaluate()` returns all-`False` flags regardless of the sensor's actual state (`engine/detector.py:98-99`). If an operator presses "Reset Interlock" while a fault toggle (e.g. stuck-at, drift) is still enabled in the UI, the sensor-trust gate treats the still-genuinely-faulted sensor as trusted for 25 real seconds, allowing un-gated control. Same bug *class* as the Phase 4 runaway (individually-correct components, emergent closed-loop gap) — confirmed by tracing `Detector.evaluate()` and `reset_interlock()` directly, not just taking the review's word for it. **Designed fix, not yet built:** add `Detector.reset(skip_boot_grace: bool = False)`; `reset_interlock()` calls it with `skip_boot_grace=True` (still clears window/CUSUM state for a fresh statistical baseline, just doesn't re-arm the 25s countdown) since `boot_grace_ticks` exists specifically to mask a *legitimate* transient (cold start, big setpoint change) — a justification that doesn't apply to a manual mid-session interlock reset. Regular `reset_simulation()` (fresh instance) and `set_setpoint()`'s reset (a real setpoint change producing a real ramp) should keep full grace, since those are exactly the scenarios the grace period is for. Shrinks the blind window from 25s down to ~2.5s (5 ticks — the same unavoidable minimum needed to rebuild any statistical baseline after any reset). Needs a regression test at the `ControlLoop` level (mirroring the Phase 4 runaway regression tests): stuck-at fault active, trip lockout, `reset_interlock()`, confirm the detector re-flags `stuck` within a few ticks rather than staying silent for 25s.
