"""Known-outcome scenarios for Detector (Phase 4): exact hand-computed
single-tick cases (isolating z-score/CUSUM/variance formulas with simple
numbers), plus behavioral scenarios against the actual tuned config.yaml
parameters -- synthetic fault sequences flagging within an expected tick
window, and zero false positives on a long clean-noise run, matching the
empirical tuning approach recorded in CLAUDE.md.
See docs/control-loop-architecture.md §3.5.
"""

import pytest

from engine.detector import Detector
from engine.sensor import Sensor

# Matches config.yaml's tuned detector + sensor.noise_sigma_k values.
TUNED_KWARGS = dict(
    window_ticks=30,
    noise_sigma_k=0.15,
    z_score_threshold=6.0,
    cusum_slack_k=1.0,
    cusum_threshold_h=9.0,
    stuck_variance_ratio=0.1,
)


def make_tuned_sensor(seed):
    return Sensor(
        noise_sigma_k=0.15,
        drift_rate_k_per_s=0.05,
        spike_offset_k=5.0,
        spike_duration_ticks=2,
        dt=0.5,
        seed=seed,
    )


# --- Exact, hand-computed single-tick cases (simple numbers, isolate one formula) ---


def test_warm_up_never_flags_regardless_of_input_magnitude():
    detector = Detector(**TUNED_KWARGS)  # min_samples defaults to 5
    wild_values = [0.0, 1000.0, -500.0, 300.0]
    for value in wild_values:
        flags = detector.evaluate(value)
        assert flags == {"spike": False, "drift": False, "stuck": False}


def test_zscore_spike_exact_hand_computed_case():
    detector = Detector(
        window_ticks=30, noise_sigma_k=1.0, z_score_threshold=2.0, cusum_slack_k=0.5,
        cusum_threshold_h=100.0, stuck_variance_ratio=0.1, min_samples=3,
    )
    for _ in range(3):
        detector.evaluate(10.0)  # window = [10, 10, 10]

    # baseline_mean=10.0, z = (13-10)/1.0 = 3.0 > threshold 2.0
    flags = detector.evaluate(13.0)
    assert flags["spike"] is True
    assert flags["drift"] is False  # cusum_threshold_h=100 -- deliberately unreachable here


def test_cusum_drift_exact_hand_computed_single_tick_trip():
    detector = Detector(
        window_ticks=30, noise_sigma_k=1.0, z_score_threshold=100.0, cusum_slack_k=0.5,
        cusum_threshold_h=3.0, stuck_variance_ratio=0.1, min_samples=3,
    )
    for _ in range(3):
        detector.evaluate(10.0)  # window = [10, 10, 10]

    # baseline_mean=10.0, z=(100-10)/1.0=90; cusum_pos = max(0, 0+90-0.5) = 89.5 > 3.0
    flags = detector.evaluate(100.0)
    assert flags["drift"] is True
    assert flags["spike"] is False  # z_score_threshold=100 -- deliberately unreachable here


def test_stuck_variance_exact_hand_computed_case():
    detector = Detector(
        window_ticks=30, noise_sigma_k=1.0, z_score_threshold=100.0, cusum_slack_k=0.5,
        cusum_threshold_h=100.0, stuck_variance_ratio=0.1, min_samples=3,
    )
    detector.evaluate(10.0)
    detector.evaluate(10.0)
    # window (post-append) = [10, 10, 10] on the 3rd call -> variance=0.0 < 0.1*1^2
    flags = detector.evaluate(10.0)
    assert flags["stuck"] is True


def test_reset_clears_window_and_cusum_state():
    detector = Detector(
        window_ticks=30, noise_sigma_k=1.0, z_score_threshold=100.0, cusum_slack_k=0.5,
        cusum_threshold_h=3.0, stuck_variance_ratio=0.1, min_samples=3,
    )
    for _ in range(3):
        detector.evaluate(10.0)
    detector.evaluate(100.0)  # trips drift, accumulates real CUSUM state

    detector.reset()

    # Fresh state: even feeding the same jump sequence again needs to
    # rebuild a baseline first -- the first 2 calls can't flag (warm-up).
    assert detector.evaluate(10.0) == {"spike": False, "drift": False, "stuck": False}
    assert detector.evaluate(10.0) == {"spike": False, "drift": False, "stuck": False}


# --- Behavioral scenarios against the real tuned config.yaml parameters ---


def test_clean_noise_produces_no_false_positives_across_multiple_seeds():
    for seed in range(1, 6):
        sensor = make_tuned_sensor(seed)
        detector = Detector(**TUNED_KWARGS)
        for _ in range(1000):
            flags = detector.evaluate(sensor.read(300.0))
            assert not any(flags.values()), f"false positive at seed={seed}: {flags}"


def test_drift_flags_within_expected_tick_window():
    sensor = make_tuned_sensor(seed=1)
    sensor.set_drift(True)
    detector = Detector(**TUNED_KWARGS)

    first_flag_tick = None
    for t in range(1, 301):
        flags = detector.evaluate(sensor.read(300.0))
        if flags["drift"]:
            first_flag_tick = t
            break

    assert first_flag_tick is not None, "drift was never flagged"
    assert 10 <= first_flag_tick <= 100  # not implausibly instant, not implausibly slow


def test_spike_flags_during_active_ticks_only():
    sensor = make_tuned_sensor(seed=1)
    detector = Detector(**TUNED_KWARGS)
    for _ in range(20):  # warm up on clean data first
        detector.evaluate(sensor.read(300.0))

    sensor.trigger_spike()  # spike_duration_ticks=2
    results = [detector.evaluate(sensor.read(300.0))["spike"] for _ in range(10)]

    assert results == [True, True, False, False, False, False, False, False, False, False]


def test_stuck_flags_within_window_and_stays_flagged():
    sensor = make_tuned_sensor(seed=1)
    detector = Detector(**TUNED_KWARGS)
    for _ in range(20):
        detector.evaluate(sensor.read(300.0))

    sensor.set_stuck(True)
    first_flag_tick = None
    for t in range(1, 51):
        flags = detector.evaluate(sensor.read(300.0))
        if flags["stuck"]:
            first_flag_tick = t
            break

    assert first_flag_tick is not None
    assert first_flag_tick <= TUNED_KWARGS["window_ticks"]

    # Should stay flagged afterward -- it really is frozen.
    for _ in range(10):
        assert detector.evaluate(sensor.read(300.0))["stuck"] is True


def test_legitimate_fast_transient_recovers_within_bounded_window():
    # A big, fast, real change (not a fault) may cause false flags during
    # the transient itself -- a named, documented limitation of simple
    # rolling statistics (see engine/detector.py). What matters is that it
    # RECOVERS rather than latching forever, thanks to the CUSUM cap.
    detector = Detector(**TUNED_KWARGS)
    for _ in range(20):
        detector.evaluate(300.0)  # settled baseline

    for _ in range(40):  # a sharp, sustained ramp -- like an aggressive PID step
        detector.evaluate_result = detector.evaluate(300.0 + _ * 0.75)

    # Now hold steady at the new level and confirm drift eventually clears.
    settled_level = 300.0 + 39 * 0.75
    cleared = False
    for _ in range(100):
        flags = detector.evaluate(settled_level)
        if not flags["drift"]:
            cleared = True
            break
    assert cleared, "drift flag never recovered after the transient settled"
