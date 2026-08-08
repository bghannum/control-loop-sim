"""Known-outcome scenarios for ControlLoop.tick: confirms the record schema
end-to-end, plus (Phase 3) that sensor faults enabled via the loop reach
the record, and (Phase 4) that a clean run shows no flags. Interlock/
detector are exercised thoroughly in their own dedicated test files
(test_interlock.py, test_detector.py) with realistic bounds; the shared
CONFIG here keeps the interlock deliberately wide-open so these tests
isolate PID/manual/sensor behavior rather than getting entangled with
bounds/slew clamping. See docs/control-loop-architecture.md §4.
"""

from pathlib import Path

import pytest
import yaml

from engine.loop import ControlLoop

REAL_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

CONFIG = {
    "simulation": {"dt_seconds": 0.5, "model_type": "first_order"},
    "model_params": {
        "first_order": {
            "thermal_mass": 5.0,
            "loss_coeff": 0.3,
            "k_heat": 1.0,
            "t_ambient": 293.15,
            "t_initial": 293.15,
        }
    },
    "setpoint": {"default_k": 323.15},
    "pid": {"kp": 2.0, "ki": 0.5, "kd": 0.1},
    # noise_sigma_k=0.0 keeps t_sensed exactly predictable in tests that
    # don't care about the sensor -- reproducibility is covered separately.
    "sensor": {
        "noise_sigma_k": 0.0,
        "drift_rate_k_per_s": 0.05,
        "spike_offset_k": 5.0,
        "spike_duration_ticks": 2,
    },
    "detector": {
        "window_ticks": 30,
        "z_score_threshold": 6.0,
        "cusum_slack_k": 1.0,
        "cusum_threshold_h": 9.0,
        "stuck_variance_ratio": 0.1,
        "boot_grace_ticks": 0,  # these tests are short (1-3 ticks); no grace period needed
    },
    # ai.max_response_wait_s + fallback_after_s = 1000s -- these tests
    # never construct a real client, so nothing should ever "fail" fast
    # enough to trip the fallback; see test_ai_controller.py for that.
    "ai": {
        "model": "claude-sonnet-5",
        "history_window_ticks": 20,
        "max_response_wait_s": 500.0,
        "fallback_after_s": 500.0,
        "safe_output_pct": 0.0,
    },
    # Deliberately wide-open bounds/slew so these tests never trip the
    # interlock incidentally -- see test_interlock.py for its own checks.
    "interlock": {
        "t_min_k": 0.0,
        "t_max_k": 1000.0,
        "bound_margin_k": 5.0,
        "max_delta_per_tick_pct": 1000.0,
        "trip_safe_output_pct": 0.0,
        "untrusted_auto_safe_after_s": 500.0,
        "trip_lockout_threshold": 2,
        "trip_correction_tolerance_pct": 1.0,
    },
}


def make_loop(seed=None):
    return ControlLoop(CONFIG, seed=seed)


def test_first_tick_matches_single_model_step():
    loop = make_loop()
    record = loop.tick(manual_input_pct=10.0)

    assert record["tick"] == 1
    assert record["t_true"] == pytest.approx(293.15)  # reading taken before this tick's step
    assert record["t_sensed"] == record["t_true"]  # no sensor fault model until Phase 3
    assert record["actuator_output"] == 10.0
    assert record["controller_source"] == "manual"
    assert loop.state["temperature"] == pytest.approx(294.15)  # state advances past the reading


def test_clean_run_has_no_detector_flags_and_interlock_allows():
    loop = make_loop()
    record = loop.tick(manual_input_pct=5.0)

    assert record["active_faults"] == []
    assert record["detector_flags"] == {"spike": False, "drift": False, "stuck": False}
    assert record["interlock_result"] == "allow"
    assert record["override_active"] is False


def test_tick_count_increments_and_state_persists_across_ticks():
    loop = make_loop()
    loop.tick(manual_input_pct=10.0)
    second_record = loop.tick(manual_input_pct=10.0)

    assert second_record["tick"] == 2
    assert second_record["t_true"] == pytest.approx(294.15)  # carried over from tick 1's result


def test_switching_to_pid_mode_uses_pid_controller():
    loop = make_loop()
    loop.set_mode("pid")
    record = loop.tick()

    # reading=293.15, setpoint=323.15 (config default) -> error=30.0
    # integral = 30*0.5=15.0, derivative=0 (first PID call ever)
    # output = 2.0*30 + 0.5*15.0 + 0.1*0 = 67.5
    assert record["controller_source"] == "pid"
    assert record["actuator_output"] == pytest.approx(67.5)


def test_manual_input_is_ignored_while_in_pid_mode():
    loop = make_loop()
    loop.set_mode("pid")
    record = loop.tick(manual_input_pct=99.0)  # should have no effect on actuator_output

    assert record["actuator_output"] == pytest.approx(67.5)


def test_switching_back_to_pid_resets_integral_and_derivative_state():
    loop = make_loop()
    loop.set_mode("pid")
    loop.tick()
    loop.tick()  # accumulate real integral/derivative state

    loop.set_mode("manual")
    loop.tick(manual_input_pct=5.0)  # a tick spent inactive shouldn't matter either way

    loop.set_mode("pid")  # transition back in -> should reset

    assert loop.pid._integral == 0.0
    assert loop.pid._prev_error is None


def test_set_pid_gains_takes_effect_on_next_tick():
    loop = make_loop()
    loop.set_mode("pid")
    loop.set_pid_gains(kp=10.0, ki=0.0, kd=0.0)
    record = loop.tick()

    # reading=293.15, setpoint=323.15 -> error=30.0, raw PID output = 10.0*30.0 = 300.0.
    # The gain change reached PID correctly; the interlock's unconditional
    # [0,100] range clamp (not one of the configurable bounds -- there's no
    # such thing as a 300% heater) is what brings it down to 100.0.
    assert record["actuator_output"] == pytest.approx(100.0)
    assert record["interlock_result"] == "clamp"


def test_enabling_drift_makes_sensed_reading_diverge_from_true():
    loop = make_loop()
    loop.set_drift(True)
    record = loop.tick()

    # drift_rate=0.05, dt=0.5 -> offset after 1 tick = 0.025K
    assert record["t_sensed"] == pytest.approx(record["t_true"] + 0.025)
    assert record["active_faults"] == ["drift"]


def test_stuck_fault_freezes_sensed_reading_while_true_temperature_moves():
    loop = make_loop()
    loop.set_stuck(True)
    first = loop.tick(manual_input_pct=100.0)  # heater on, true temp will rise
    second = loop.tick(manual_input_pct=100.0)

    assert first["t_sensed"] == pytest.approx(second["t_sensed"])  # frozen
    assert second["t_true"] > first["t_true"]  # ground truth kept moving underneath it
    assert second["active_faults"] == ["stuck"]


def test_spike_trigger_reverts_after_configured_duration():
    loop = make_loop()
    loop.trigger_spike()  # spike_duration_ticks=2

    first = loop.tick()
    second = loop.tick()
    third = loop.tick()

    assert first["t_sensed"] == pytest.approx(first["t_true"] + 5.0)
    assert second["t_sensed"] == pytest.approx(second["t_true"] + 5.0)
    assert third["t_sensed"] == pytest.approx(third["t_true"])  # reverted
    assert third["active_faults"] == []


def test_seeded_loops_produce_reproducible_sensed_readings():
    noisy_config = {**CONFIG, "sensor": {**CONFIG["sensor"], "noise_sigma_k": 0.5}}
    loop_a = ControlLoop(noisy_config, seed=99)
    loop_b = ControlLoop(noisy_config, seed=99)

    readings_a = [loop_a.tick()["t_sensed"] for _ in range(5)]
    readings_b = [loop_b.tick()["t_sensed"] for _ in range(5)]

    assert readings_a == readings_b


def test_stuck_fault_freezes_actuator_once_detector_flags_it():
    # Needs a real (nonzero) noise_sigma_k -- the detector's z-score divides
    # by it, and CONFIG's noise_sigma_k=0.0 is only safe for tests that
    # don't exercise the detector.
    config = {**CONFIG, "sensor": {**CONFIG["sensor"], "noise_sigma_k": 0.15}}
    loop = ControlLoop(config)
    loop.set_stuck(True)
    records = [loop.tick(manual_input_pct=80.0) for _ in range(15)]
    assert records[-1]["detector_flags"]["stuck"] is True
    frozen_value = records[-1]["actuator_output"]

    # A new, very different manual command should now be held, not applied.
    next_record = loop.tick(manual_input_pct=0.0)
    assert next_record["actuator_output"] == pytest.approx(frozen_value)
    assert "untrusted" in next_record["interlock_reason"]


def test_manual_override_flows_through_to_interlock_end_to_end():
    # Real bounds, but a huge slew limit -- isolates the bounds/margin
    # check specifically, matching test_interlock.py's approach.
    config = {
        **CONFIG,
        "interlock": {
            "t_min_k": 273.15, "t_max_k": 373.15, "bound_margin_k": 5.0,
            "max_delta_per_tick_pct": 1000.0, "trip_safe_output_pct": 0.0,
            "untrusted_auto_safe_after_s": 500.0, "trip_lockout_threshold": 2,
            "trip_correction_tolerance_pct": 1.0,
        },
    }
    loop = ControlLoop(config)
    loop.state["temperature"] = 370.0  # within the 5K margin of t_max=373.15

    blocked = loop.tick(manual_input_pct=90.0)
    assert blocked["interlock_result"] == "reject"
    assert blocked["actuator_output"] == pytest.approx(0.0)  # held at initial last_output

    loop.set_manual_override_requested(True)
    loop.state["temperature"] = 370.0  # put it back after tick()'s plant step moved it
    allowed = loop.tick(manual_input_pct=90.0)
    assert allowed["interlock_result"] == "allow"
    assert allowed["override_active"] is True
    assert allowed["actuator_output"] == pytest.approx(90.0)


def test_pid_startup_settles_without_false_interlock_freeze_using_real_config():
    # Regression test for a real closed-loop bug found in Phase 4: without
    # a detector boot grace period, a normal PID startup ramp (or any
    # legitimate fast transient) false-flags as drift. The interlock then
    # (correctly, per its own design) freezes the actuator at whatever was
    # being commanded mid-ramp -- a non-equilibrium value -- so the plant
    # keeps heating, which keeps looking like drift, so the flag never
    # clears. A self-sustaining false alarm that never lets PID settle.
    # Uses the actual shipped config.yaml so it catches a regression if
    # someone retunes these values later without re-validating.
    with open(REAL_CONFIG_PATH) as f:
        real_config = yaml.safe_load(f)
    grace = real_config["detector"]["boot_grace_ticks"]

    for seed in [1, 2, 3]:
        loop = ControlLoop(real_config, seed=seed)
        loop.set_mode("pid")

        froze_after_grace = False
        for t in range(1, 301):
            record = loop.tick()
            if t > grace and record["interlock_result"] == "reject":
                froze_after_grace = True

        assert not froze_after_grace, f"seed={seed}: interlock falsely latched a freeze after the boot grace period"
        settled_near_setpoint = abs(loop.state["temperature"] - real_config["setpoint"]["default_k"]) < 5.0
        assert settled_near_setpoint, f"seed={seed}: PID never settled near setpoint (got {loop.state['temperature']:.2f}K)"


def test_real_stuck_fault_after_settling_is_still_caught_using_real_config():
    # Companion to the regression test above: confirms the grace period
    # doesn't just silence the detector permanently -- a genuine fault
    # introduced after the system has settled still gets caught.
    with open(REAL_CONFIG_PATH) as f:
        real_config = yaml.safe_load(f)
    grace = real_config["detector"]["boot_grace_ticks"]

    loop = ControlLoop(real_config, seed=1)
    loop.set_mode("pid")
    for _ in range(grace + 30):  # let it settle well past the grace period
        loop.tick()

    loop.set_stuck(True)
    first_flag_tick = None
    for t in range(1, 51):
        record = loop.tick()
        if record["detector_flags"]["stuck"]:
            first_flag_tick = t
            break

    assert first_flag_tick is not None, "a real stuck fault was never flagged after settling"


def test_ai_mode_uses_ai_controller():
    loop = make_loop()  # no ai_client -> AIController always fails/holds, which is fine here
    loop.set_mode("ai")
    record = loop.tick()

    assert record["controller_source"] == "ai"
    assert record["actuator_output"] == pytest.approx(0.0)  # initial held value, never got a real proposal
    assert record["ai_fallback_active"] is False  # not yet past the fallback threshold


def test_ai_fallback_not_triggered_immediately_after_switching_to_ai_mode():
    loop = make_loop()
    loop.set_mode("ai")  # resets the AI failure clock
    record = loop.tick()

    assert record["ai_fallback_active"] is False


def test_ai_fallback_triggers_after_sustained_failure_and_stays_source_ai():
    config = {**CONFIG, "ai": {**CONFIG["ai"], "safe_output_pct": 25.0}}
    loop = ControlLoop(config)
    loop.set_mode("ai")

    # Whitebox: simulate a long stretch with no valid AI response, without
    # a real multi-second wait. Matches the pattern already used for
    # inspecting loop.pid's internal state directly.
    loop.ai._last_success_time -= config["ai"]["max_response_wait_s"] + config["ai"]["fallback_after_s"] + 1.0

    record = loop.tick()
    assert record["ai_fallback_active"] is True
    assert record["controller_source"] == "ai"  # still AI's own mode, just system-substituted a safe value
    assert record["actuator_output"] == pytest.approx(25.0)


def test_switching_into_ai_mode_resets_the_failure_clock():
    loop = make_loop()
    loop.set_mode("ai")
    loop.ai._last_success_time -= 9999  # make it look like it's been failing forever
    assert loop.ai.seconds_since_last_success() > 1000

    loop.set_mode("pid")
    loop.set_mode("ai")  # a fresh transition back into ai -> should reset

    assert loop.ai.seconds_since_last_success() < 1.0


def test_interlock_locked_out_appears_in_record():
    loop = make_loop()
    loop.interlock.locked_out = True  # whitebox, same pattern as loop.ai/loop.pid above
    record = loop.tick()
    assert record["interlock_locked_out"] is True


def test_reset_interlock_clears_lockout_and_detector_state():
    # Needs a real (nonzero) noise_sigma_k -- the detector's z-score divides
    # by it, same reason as test_stuck_fault_freezes_actuator_once_detector_flags_it.
    config = {**CONFIG, "sensor": {**CONFIG["sensor"], "noise_sigma_k": 0.15}}
    loop = ControlLoop(config)
    loop.interlock.locked_out = True
    loop.interlock.trip_strikes = 5
    for _ in range(10):  # build up real detector window/CUSUM state
        loop.detector.evaluate(300.0)
    assert len(loop.detector._window) == 10

    loop.reset_interlock()

    assert loop.interlock.locked_out is False
    assert loop.interlock.trip_strikes == 0
    assert len(loop.detector._window) == 0


def test_reset_interlock_does_not_reintroduce_boot_grace_silence_using_real_config():
    # backlog item 8: reset_interlock() used to call detector.reset() with
    # its full boot-grace period re-armed, so an operator who presses the
    # button without also disabling a still-active fault toggle got a false
    # 25s "all clear" -- the detector went silent even though the fault
    # never actually went away. skip_boot_grace=True fixes this; this test
    # locks the fix in against the real shipped config, same pattern as the
    # Phase 4 runaway-bug regression tests above.
    with open(REAL_CONFIG_PATH) as f:
        real_config = yaml.safe_load(f)
    grace = real_config["detector"]["boot_grace_ticks"]

    loop = ControlLoop(real_config, seed=1)
    loop.set_mode("pid")
    for _ in range(grace + 30):  # settle well past the initial grace period
        loop.tick()

    loop.set_stuck(True)  # fault genuinely active, and the operator forgets to clear it
    loop.interlock.locked_out = True  # whitebox: the state a "Reset Interlock" click responds to

    loop.reset_interlock()

    first_flag_tick = None
    for t in range(1, grace):  # well under the old 25s/50-tick grace window
        record = loop.tick()
        if record["detector_flags"]["stuck"]:
            first_flag_tick = t
            break

    assert first_flag_tick is not None, "stuck fault was not re-flagged before the old boot-grace window would have elapsed"
