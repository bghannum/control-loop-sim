"""Known-outcome scenarios for Sensor (Phase 3): drift/stuck/spike faults
isolated with noise_sigma_k=0.0 for exact-value assertions, plus seeded
reproducibility and the stuck-overrides-everything precedence rule.
See docs/control-loop-architecture.md §3.2.
"""

import pytest

from engine.sensor import Sensor


def make_sensor(seed=None, noise_sigma_k=0.0):
    return Sensor(
        noise_sigma_k=noise_sigma_k,
        drift_rate_k_per_s=0.05,
        spike_offset_k=5.0,
        spike_duration_ticks=2,
        dt=0.5,
        seed=seed,
    )


def test_no_faults_and_zero_noise_reading_equals_true_temperature():
    sensor = make_sensor()
    assert sensor.read(300.0) == pytest.approx(300.0)
    assert sensor.active_faults() == []


def test_drift_accumulates_exact_value_per_tick():
    sensor = make_sensor()
    sensor.set_drift(True)

    # elapsed after tick N = N*dt = N*0.5s; drift = 0.05 * elapsed
    assert sensor.read(300.0) == pytest.approx(300.0 + 0.05 * 0.5)
    assert sensor.read(300.0) == pytest.approx(300.0 + 0.05 * 1.0)
    assert sensor.read(300.0) == pytest.approx(300.0 + 0.05 * 1.5)
    assert sensor.active_faults() == ["drift"]


def test_calling_set_drift_true_repeatedly_does_not_reset_ramp():
    # Regression test: the UI calls set_drift(True) unconditionally every
    # rerun while the toggle is on (same pattern as ControlLoop.set_mode).
    # Resetting elapsed time on every call would mean drift never grows
    # past a fraction of a tick.
    sensor = make_sensor()
    sensor.set_drift(True)
    sensor.read(300.0)  # elapsed = 0.5s
    sensor.set_drift(True)  # redundant call, as the UI would make every rerun
    reading = sensor.read(300.0)  # elapsed should now be 1.0s, not reset to 0.5s

    assert reading == pytest.approx(300.0 + 0.05 * 1.0)


def test_drift_ramp_restarts_on_actual_off_to_on_transition():
    sensor = make_sensor()
    sensor.set_drift(True)
    sensor.read(300.0)  # elapsed = 0.5s
    sensor.read(300.0)  # elapsed = 1.0s

    sensor.set_drift(False)
    sensor.set_drift(True)  # real transition -- should restart the ramp
    reading = sensor.read(300.0)

    assert reading == pytest.approx(300.0 + 0.05 * 0.5)  # back to a single tick's worth


def test_stuck_freezes_at_first_reading_after_activation():
    sensor = make_sensor()
    sensor.set_stuck(True)

    first = sensor.read(300.0)
    second = sensor.read(310.0)  # true temperature changed, reading should not
    third = sensor.read(250.0)

    assert first == pytest.approx(300.0)
    assert second == pytest.approx(300.0)
    assert third == pytest.approx(300.0)
    assert sensor.active_faults() == ["stuck"]


def test_stuck_value_resets_on_reactivation():
    sensor = make_sensor()
    sensor.set_stuck(True)
    sensor.read(300.0)  # freezes at 300.0

    sensor.set_stuck(False)
    sensor.set_stuck(True)  # a fresh activation should freeze at a new value
    reading = sensor.read(320.0)

    assert reading == pytest.approx(320.0)


def test_spike_adds_offset_for_configured_duration_then_reverts():
    sensor = make_sensor()  # spike_duration_ticks=2
    sensor.trigger_spike()

    assert sensor.read(300.0) == pytest.approx(305.0)
    assert sensor.active_faults() == ["spike"]
    assert sensor.read(300.0) == pytest.approx(305.0)
    assert sensor.read(300.0) == pytest.approx(300.0)  # reverted after 2 ticks
    assert sensor.active_faults() == []


def test_stuck_overrides_drift_and_spike_and_noise():
    sensor = make_sensor(noise_sigma_k=1.0)  # noise on, to prove stuck suppresses it too
    sensor.set_drift(True)
    sensor.trigger_spike()
    sensor.set_stuck(True)

    reading = sensor.read(300.0)
    assert reading == pytest.approx(300.0)  # frozen, ignoring drift/spike/noise entirely
    assert sensor.active_faults() == ["drift", "stuck", "spike"]


def test_reseed_produces_reproducible_noise_sequence():
    sensor_a = make_sensor(seed=42, noise_sigma_k=0.5)
    sensor_b = make_sensor(seed=42, noise_sigma_k=0.5)

    readings_a = [sensor_a.read(300.0) for _ in range(10)]
    readings_b = [sensor_b.read(300.0) for _ in range(10)]

    assert readings_a == readings_b


def test_reseed_changes_subsequent_noise_sequence():
    sensor = make_sensor(seed=1, noise_sigma_k=0.5)
    before = [sensor.read(300.0) for _ in range(5)]

    sensor.reseed(2)
    after = [sensor.read(300.0) for _ in range(5)]

    assert before != after
