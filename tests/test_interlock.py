"""Known-outcome scenarios for Interlock, using the real config.yaml
bounds. Covers all six checks in order, and specifically the
override-eligibility distinction that's central to the safety story:
- Check 0 (lockout), check 1 (sensor-trust), check 2 (hard over/under-temp
  trip), and check 4 (slew-rate): ABSOLUTE, never overridable by anyone --
  the doc's "regardless of source"/"regardless of who proposed it"
  phrasing, and check 4's own "fat-fingered manual override" example, only
  make sense under this reading.
- Check 3 (bounds/margin): the one check manual can override, with a
  persistent warning (override_active=True).

Also covers backlog items 2-5 (2026-08-05): the sensor-trust gate forcing
safe output instead of a plain hold (past a hard bound, or after too long
untrusted), and the hard trip escalating to a latching lockout after
repeated uncorrected excursions.
See docs/control-loop-architecture.md §3.4.
"""

import pytest

from engine.interlock import Interlock
from tests.conftest import FakeClock

# Real config.yaml values.
T_MIN_K = 273.15
T_MAX_K = 373.15
BOUND_MARGIN_K = 5.0
MAX_DELTA_PCT = 10.0
TRIP_SAFE_OUTPUT_PCT = 0.0
UNTRUSTED_AUTO_SAFE_AFTER_S = 20.0
TRIP_LOCKOUT_THRESHOLD = 2
TRIP_CORRECTION_TOLERANCE_PCT = 1.0


def make_interlock(initial_output=50.0, clock=None):
    return Interlock(
        t_min_k=T_MIN_K, t_max_k=T_MAX_K, bound_margin_k=BOUND_MARGIN_K,
        max_delta_per_tick_pct=MAX_DELTA_PCT, trip_safe_output_pct=TRIP_SAFE_OUTPUT_PCT,
        untrusted_auto_safe_after_s=UNTRUSTED_AUTO_SAFE_AFTER_S,
        trip_lockout_threshold=TRIP_LOCKOUT_THRESHOLD,
        trip_correction_tolerance_pct=TRIP_CORRECTION_TOLERANCE_PCT,
        initial_output=initial_output, clock=clock or FakeClock(),
    )


# --- Check 1: sensor-trust gate -- absolute ---


def test_untrusted_holds_at_last_known_good_for_pid():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=80.0, source="pid", t_sensed=320.0,
        sensor_trusted=False, override_requested=False,
    )
    assert decision.actuator_output == 50.0
    assert decision.result == "reject"
    assert decision.override_active is False
    assert "untrusted" in decision.reason


def test_untrusted_cannot_be_overridden_by_manual():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=80.0, source="manual", t_sensed=320.0,
        sensor_trusted=False, override_requested=True,  # override requested -- still ignored
    )
    assert decision.actuator_output == 50.0
    assert decision.result == "reject"
    assert decision.override_active is False


def test_untrusted_proposal_matching_last_output_is_allow_not_reject():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=50.0, source="manual", t_sensed=320.0,
        sensor_trusted=False, override_requested=False,
    )
    assert decision.result == "allow"  # already holding, nothing to reject


# --- Item 3: sensor-untrusted duration auto-safe-default ---


def test_untrusted_duration_under_threshold_still_holds_at_last_known_good():
    clock = FakeClock(start=1000.0)
    interlock = make_interlock(initial_output=50.0, clock=clock)
    interlock.evaluate(proposed_output_pct=80.0, source="pid", t_sensed=320.0, sensor_trusted=False, override_requested=False)

    clock.advance(UNTRUSTED_AUTO_SAFE_AFTER_S - 1.0)  # still under threshold
    decision = interlock.evaluate(proposed_output_pct=80.0, source="pid", t_sensed=320.0, sensor_trusted=False, override_requested=False)

    assert decision.actuator_output == pytest.approx(50.0)  # still just holding
    assert "holding at last-known-good" in decision.reason


def test_untrusted_duration_exceeding_threshold_forces_safe_output():
    clock = FakeClock(start=1000.0)
    interlock = make_interlock(initial_output=50.0, clock=clock)
    interlock.evaluate(proposed_output_pct=80.0, source="pid", t_sensed=320.0, sensor_trusted=False, override_requested=False)

    clock.advance(UNTRUSTED_AUTO_SAFE_AFTER_S + 1.0)
    decision = interlock.evaluate(proposed_output_pct=80.0, source="pid", t_sensed=320.0, sensor_trusted=False, override_requested=False)

    assert decision.actuator_output == pytest.approx(TRIP_SAFE_OUTPUT_PCT)
    assert decision.result == "reject"
    assert "auto safe default" in decision.reason


def test_untrusted_timer_resets_once_trusted_again():
    clock = FakeClock(start=1000.0)
    interlock = make_interlock(initial_output=50.0, clock=clock)
    interlock.evaluate(proposed_output_pct=80.0, source="pid", t_sensed=320.0, sensor_trusted=False, override_requested=False)
    clock.advance(UNTRUSTED_AUTO_SAFE_AFTER_S + 1.0)

    # Briefly trusted again -- should clear the staleness timer.
    interlock.evaluate(proposed_output_pct=55.0, source="pid", t_sensed=320.0, sensor_trusted=True, override_requested=False)

    # Untrusted again immediately after -- should NOT auto-safe-default yet,
    # the timer restarted from this moment.
    decision = interlock.evaluate(proposed_output_pct=80.0, source="pid", t_sensed=320.0, sensor_trusted=False, override_requested=False)
    assert "holding at last-known-good" in decision.reason


# --- Check 2: hard over/under-temperature trip -- absolute, bypasses slew ---


def test_hard_trip_at_ceiling_forces_safe_output_even_on_a_decrease_proposal():
    # The whole point: unlike the margin check, this fires even when the
    # proposal is a DECREASE (or anything else) -- once actually past the
    # hard limit, nothing gets through except the safe value.
    interlock = make_interlock(initial_output=80.0)
    decision = interlock.evaluate(
        proposed_output_pct=30.0, source="pid", t_sensed=373.15,  # exactly at t_max, proposing less heat
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == pytest.approx(TRIP_SAFE_OUTPUT_PCT)
    assert decision.result == "reject"
    assert "T_max" in decision.reason


def test_hard_trip_past_ceiling_cannot_be_overridden_by_manual():
    interlock = make_interlock(initial_output=80.0)
    decision = interlock.evaluate(
        proposed_output_pct=80.0, source="manual", t_sensed=400.0,  # well past t_max
        sensor_trusted=True, override_requested=True,
    )
    assert decision.actuator_output == pytest.approx(TRIP_SAFE_OUTPUT_PCT)
    assert decision.result == "reject"
    assert decision.override_active is False


def test_hard_trip_bypasses_the_slew_limit():
    interlock = make_interlock(initial_output=100.0)
    decision = interlock.evaluate(
        proposed_output_pct=100.0, source="pid", t_sensed=373.15,
        sensor_trusted=True, override_requested=False,
    )
    # 100 -> 0 is a 100% jump, far past the 10%/tick slew limit -- the trip
    # must not be rate-limited like routine control.
    assert decision.actuator_output == pytest.approx(TRIP_SAFE_OUTPUT_PCT)


def test_hard_trip_at_floor_forces_max_heat():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=50.0, source="pid", t_sensed=273.15,  # exactly at t_min
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == pytest.approx(100.0)
    assert decision.result == "reject"
    assert "T_min" in decision.reason


def test_just_below_hard_trip_threshold_still_uses_the_softer_margin_check():
    # 0.01K under t_max -- should NOT trip; falls through to the ordinary
    # near-ceiling margin rule instead (which itself may still reject an
    # increase, but via the overridable path, not the hard trip).
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=40.0, source="pid", t_sensed=373.14,  # decreasing -- margin check allows this
        sensor_trusted=True, override_requested=False,
    )
    assert decision.result == "allow"
    assert decision.actuator_output == pytest.approx(40.0)


def test_hard_bound_wins_over_sensor_untrusted_not_last_known_good():
    # Reversed from the original Phase-4-era design (backlog item 5): a
    # forced safe output is one-directional and can't make things worse,
    # even acting on a reading already flagged untrusted -- so it takes
    # priority over the plain "hold at last-known-good" the sensor-trust
    # gate would otherwise do.
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=80.0, source="pid", t_sensed=400.0,  # past t_max AND untrusted
        sensor_trusted=False, override_requested=False,
    )
    assert decision.actuator_output == pytest.approx(TRIP_SAFE_OUTPUT_PCT)
    assert decision.result == "reject"
    assert "untrusted AND at/past T_max" in decision.reason


def test_sensor_untrusted_below_hard_bound_still_holds_at_last_known_good():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=80.0, source="pid", t_sensed=320.0,  # untrusted but nowhere near a bound
        sensor_trusted=False, override_requested=False,
    )
    assert decision.actuator_output == pytest.approx(50.0)
    assert decision.reason == "sensor untrusted (Tier-1 detector flag active) -- holding at last-known-good output"


# --- Item 4: hard trip escalates to a latching lockout (check 0) ---


def trip(interlock, t_sensed=380.0, proposed=80.0):
    return interlock.evaluate(proposed_output_pct=proposed, source="pid", t_sensed=t_sensed, sensor_trusted=True, override_requested=False)


def calm(interlock, proposed, t_sensed=350.0):
    return interlock.evaluate(proposed_output_pct=proposed, source="pid", t_sensed=t_sensed, sensor_trusted=True, override_requested=False)


def test_single_trip_does_not_lock_out():
    interlock = make_interlock(initial_output=50.0)
    decision = trip(interlock)
    assert decision.result == "reject"
    assert interlock.trip_strikes == 1
    assert interlock.locked_out is False


def test_two_uncorrected_trip_episodes_engage_lockout():
    interlock = make_interlock(initial_output=50.0)
    trip(interlock)
    calm(interlock, proposed=80.0)  # gap tick: controller never proposes anything near safe
    decision = trip(interlock)

    assert interlock.trip_strikes == 2  # == TRIP_LOCKOUT_THRESHOLD
    assert interlock.locked_out is True
    assert decision.actuator_output == pytest.approx(TRIP_SAFE_OUTPUT_PCT)
    assert "LOCKOUT" in decision.reason


def test_correction_during_the_gap_resets_strikes_and_avoids_lockout():
    interlock = make_interlock(initial_output=50.0)
    trip(interlock)
    assert interlock.trip_strikes == 1

    calm(interlock, proposed=0.5)  # genuine correction: at/near the trip's safe value
    trip(interlock)

    assert interlock.trip_strikes == 1  # reset, not incremented to 2
    assert interlock.locked_out is False


def test_locked_out_forces_safe_output_regardless_of_proposal():
    interlock = make_interlock(initial_output=50.0)
    trip(interlock)
    calm(interlock, proposed=80.0)
    trip(interlock)
    assert interlock.locked_out is True

    decision = interlock.evaluate(proposed_output_pct=0.0, source="pid", t_sensed=290.0, sensor_trusted=True, override_requested=False)
    assert decision.actuator_output == pytest.approx(TRIP_SAFE_OUTPUT_PCT)
    assert decision.result == "reject"


def test_locked_out_cannot_be_overridden_by_manual():
    interlock = make_interlock(initial_output=50.0)
    trip(interlock)
    calm(interlock, proposed=80.0)
    trip(interlock)

    decision = interlock.evaluate(proposed_output_pct=50.0, source="manual", t_sensed=290.0, sensor_trusted=True, override_requested=True)
    assert decision.actuator_output == pytest.approx(TRIP_SAFE_OUTPUT_PCT)
    assert decision.result == "reject"


def test_reset_lockout_clears_state_and_resumes_normal_evaluation():
    interlock = make_interlock(initial_output=50.0)
    trip(interlock)
    calm(interlock, proposed=80.0)
    trip(interlock)
    assert interlock.locked_out is True

    interlock.reset_lockout()
    assert interlock.locked_out is False
    assert interlock.trip_strikes == 0

    decision = interlock.evaluate(proposed_output_pct=5.0, source="pid", t_sensed=320.0, sensor_trusted=True, override_requested=False)
    assert decision.result == "allow"
    assert decision.actuator_output == pytest.approx(5.0)
    assert interlock.locked_out is False


# --- Check 3: bounds/margin -- the one overridable check ---


def test_near_ceiling_rejects_further_increase_from_pid():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=60.0, source="pid", t_sensed=370.0,  # within 5K of 373.15
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == 50.0
    assert decision.result == "reject"
    assert decision.override_active is False


def test_near_ceiling_rejects_manual_increase_without_override_requested():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=60.0, source="manual", t_sensed=370.0,
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == 50.0
    assert decision.result == "reject"


def test_near_ceiling_manual_override_allows_the_increase_with_warning():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=60.0, source="manual", t_sensed=370.0,
        sensor_trusted=True, override_requested=True,
    )
    assert decision.actuator_output == 60.0
    assert decision.result == "allow"
    assert decision.override_active is True
    assert "override" in decision.reason


def test_near_ceiling_allows_a_decrease_without_needing_override():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=40.0, source="pid", t_sensed=370.0,  # decreasing, not pushing toward T_max
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == 40.0
    assert decision.result == "allow"


def test_near_floor_rejects_further_decrease_from_pid():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=40.0, source="pid", t_sensed=275.0,  # within 5K of 273.15
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == 50.0
    assert decision.result == "reject"


def test_near_floor_manual_override_allows_the_decrease():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=40.0, source="manual", t_sensed=275.0,
        sensor_trusted=True, override_requested=True,
    )
    assert decision.actuator_output == 40.0
    assert decision.result == "allow"
    assert decision.override_active is True


# --- Check 4: slew-rate limit -- absolute, no override, any source ---


def test_slew_limit_clamps_pid_proposal():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=70.0, source="pid", t_sensed=320.0,  # delta=+20, mid-range temp
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == pytest.approx(60.0)  # 50 + max 10
    assert decision.result == "clamp"


def test_slew_limit_clamps_manual_even_with_override_requested():
    # This is the doc's own "fat-fingered manual override" scenario.
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=70.0, source="manual", t_sensed=320.0,
        sensor_trusted=True, override_requested=True,
    )
    assert decision.actuator_output == pytest.approx(60.0)
    assert decision.result == "clamp"
    assert decision.override_active is False  # slew limit is never overridable


def test_slew_limit_clamps_a_large_decrease_too():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=30.0, source="pid", t_sensed=320.0,  # delta=-20
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == pytest.approx(40.0)  # 50 - max 10
    assert decision.result == "clamp"


def test_delta_exactly_at_slew_limit_is_allowed():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=60.0, source="pid", t_sensed=320.0,  # delta=+10, exactly the limit
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == pytest.approx(60.0)
    assert decision.result == "allow"


# --- Check 5: pass-through, and the unconditional [0,100] clamp ---


def test_clean_proposal_within_all_limits_passes_through():
    interlock = make_interlock(initial_output=50.0)
    decision = interlock.evaluate(
        proposed_output_pct=55.0, source="pid", t_sensed=320.0,
        sensor_trusted=True, override_requested=False,
    )
    assert decision.actuator_output == pytest.approx(55.0)
    assert decision.result == "allow"
    assert decision.override_active is False


def test_range_clamp_to_100_applies_even_with_override_requested():
    interlock = make_interlock(initial_output=90.0)
    decision = interlock.evaluate(
        proposed_output_pct=150.0, source="manual", t_sensed=320.0,  # far from any bound
        sensor_trusted=True, override_requested=True,
    )
    assert decision.actuator_output == pytest.approx(100.0)  # raw-clamped, delta=10 clears slew
    assert decision.result == "clamp"
    assert decision.override_active is False  # no bound violation occurred -- nothing to override


def test_last_output_persists_and_reflects_actual_applied_value_not_proposal():
    interlock = make_interlock(initial_output=50.0)
    first = interlock.evaluate(
        proposed_output_pct=70.0, source="pid", t_sensed=320.0,  # gets slew-clamped to 60
        sensor_trusted=True, override_requested=False,
    )
    assert first.actuator_output == pytest.approx(60.0)

    # Next tick's slew check should reference 60.0 (what was actually
    # applied), not 70.0 (what was proposed but rejected).
    second = interlock.evaluate(
        proposed_output_pct=75.0, source="pid", t_sensed=320.0,  # delta from 60 = +15
        sensor_trusted=True, override_requested=False,
    )
    assert second.actuator_output == pytest.approx(70.0)  # 60 + max 10
