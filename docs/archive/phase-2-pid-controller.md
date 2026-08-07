# Phase 2: PID controller + mode toggle

Archived detailed build write-up — moved out of `CLAUDE.md` on 2026-08-07 to keep that file focused on current status. See `../../CLAUDE.md` for where the project stands now.

---

- `engine/controllers/pid.py` — `PIDController`: textbook `output = Kp*e + Ki*∫e + Kd*(de/dt)`, stateful (`_integral`, `_prev_error`), dt fixed at construction (matches the sim's fixed timestep). **Output is not clamped to [0, 100]** — that's the interlock's job (Phase 4), and letting PID (or later, AI) propose something out of range and watching it pass straight through unmodified is exactly the "propose vs. dispose" separation the whole project demonstrates. Don't add clamping here when it's tempting to do so — it belongs in the interlock, not the controller, or the Phase 4 story gets weaker.
- `engine/loop.py` — `ControlLoop.set_mode("manual"|"pid")`, `set_setpoint(k)`, `set_pid_gains(kp, ki, kd)`. Switching *into* PID mode calls `pid.reset()` (clears integral/prev_error) so state from a stale/inactive period doesn't cause an output jump the instant PID resumes control — this is tested directly (`test_switching_back_to_pid_resets_integral_and_derivative_state`).
- **Schema change:** added a `setpoint` field to the per-tick record (not in the architecture doc's example schema in §4). Needed because the setpoint is now a live UI slider, not a fixed constant — the chart needs the setpoint that was actually active at each historical tick, not just "whatever it is right now" retroactively applied. Backward compatible (additive).
- `app.py` — mode radio (Manual/PID), setpoint slider (°C), Kp/Ki/Kd sliders shown only in PID mode. All setters are called unconditionally every rerun (idempotent unless something actually changed), matching the pattern already established for the heater slider in Phase 1.
- Tests: `tests/test_pid_controller.py` (5 known-outcome scenarios — P/I/D terms isolated with synthetic reading sequences, reset behavior, exact 2-tick trace using the real config.yaml gains) + 4 new `ControlLoop` mode-switch integration tests. 20/20 total passing.
- **Verified visually via Playwright:** PID mode screenshot after ~15s simulated shows classic step-response behavior — rise, slight overshoot past the 50°C setpoint line, settle back down. Confirms the controller is actually doing PID, not just producing plausible-looking numbers.
