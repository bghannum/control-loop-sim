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

- [x] **6. `st.dataframe`'s `use_container_width` is deprecated.** Shipped Phase 8. Moot in the end: the decision log's `st.dataframe` call was replaced entirely by a hand-built HTML table during Phase 8 (a real `st.dataframe` + pandas `Styler` rendering bug, unrelated to this deprecation, forced that change — see `CLAUDE.md`'s Phase 8 section) so `use_container_width` doesn't appear anywhere in `app.py` anymore rather than being swapped for `width="stretch"`.

- [x] **7. Extend Tier-2 triage to explain interlock activity, not just detector flags.** Shipped. One combined button/prompt, confirmed with the user before building (not two separate asks). `engine/triage.py`'s prompt now includes each history row's `interlock_result`/`interlock_reason`; `likely_fault_type`'s enum widened to add `interlock`; `app.py`'s trigger broadened to any non-`allow` interlock result in the same window, not just a live detector flag. See `CLAUDE.md`'s "Backlog items 7 & 8" section for the live verification (correctly explained both a genuine hard-trip-to-lockout sequence and routine slew-limiting with zero faults present).

---

## Safety / interlock fixes

Requested 2026-08-07, from a Gemini code-review pass (see `CODE_REVIEW.md` finding H.1) — independently verified as a genuine bug, not just a review suggestion.

- [x] **8. `reset_interlock()` re-arms the detector's 25s boot-grace period, masking a still-active fault.** Shipped, exactly as designed: `Detector.reset(skip_boot_grace=True)`, called only by `reset_interlock()`; `set_setpoint()`'s reset and a fresh instance both keep full grace. Regression tests added at both the `Detector` level and the `ControlLoop` level (real `config.yaml`, mirroring the Phase 4 runaway-bug regression tests). Verified live: heater pinned at 100% until a real lockout, stuck-at fault enabled while locked out, "Reset Interlock" pressed without disabling it — the `stuck` flag reappeared in 0.5s, not 25s. See `CLAUDE.md`'s "Backlog items 7 & 8" section.
