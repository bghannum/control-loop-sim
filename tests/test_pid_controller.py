"""Known-outcome scenarios for PIDController (Phase 2): each gain term
isolated with synthetic reading/setpoint sequences (not run through the
plant), plus the config.yaml default gains exercised together. See
docs/control-loop-architecture.md §3.3.
"""

import pytest

from engine.controllers.pid import PIDController


def test_proportional_only_output_is_exact():
    pid = PIDController(kp=2.0, ki=0.0, kd=0.0, dt=0.5)
    action = pid.propose(reading=290.0, setpoint=300.0, history=[], detector_flags={})
    assert action.proposed_output_pct == pytest.approx(20.0)  # 2.0 * (300-290)
    assert action.source == "pid"


def test_integral_accumulates_linearly_under_constant_error():
    pid = PIDController(kp=0.0, ki=0.5, kd=0.0, dt=0.5)
    outputs = [
        pid.propose(reading=290.0, setpoint=300.0, history=[], detector_flags={}).proposed_output_pct
        for _ in range(3)
    ]
    # integral after tick N = N * error * dt = N * 10 * 0.5 = N * 5.0
    # output = ki * integral = 0.5 * N * 5.0
    assert outputs == [pytest.approx(2.5), pytest.approx(5.0), pytest.approx(7.5)]


def test_derivative_reacts_to_changing_error():
    pid = PIDController(kp=0.0, ki=0.0, kd=0.2, dt=0.5)

    first = pid.propose(reading=290.0, setpoint=300.0, history=[], detector_flags={})  # error=10, no prior error
    assert first.proposed_output_pct == pytest.approx(0.0)

    second = pid.propose(reading=285.0, setpoint=300.0, history=[], detector_flags={})  # error=15
    assert second.proposed_output_pct == pytest.approx(2.0)  # 0.2 * (15-10)/0.5

    third = pid.propose(reading=300.0, setpoint=300.0, history=[], detector_flags={})  # error=0
    assert third.proposed_output_pct == pytest.approx(-6.0)  # 0.2 * (0-15)/0.5


def test_reset_clears_integral_and_derivative_state():
    pid = PIDController(kp=1.0, ki=1.0, kd=1.0, dt=0.5)
    pid.propose(reading=290.0, setpoint=300.0, history=[], detector_flags={})  # accumulates integral, sets prev_error

    pid.reset()
    action = pid.propose(reading=295.0, setpoint=300.0, history=[], detector_flags={})  # error=5, fresh integral+derivative

    # integral = 5*0.5 = 2.5 (not carrying the prior 5.0), derivative = 0 (prev_error was cleared)
    assert action.proposed_output_pct == pytest.approx(1.0 * 5.0 + 1.0 * 2.5 + 1.0 * 0.0)


def test_default_config_gains_across_two_ticks_exact_value():
    # kp=2.0, ki=0.5, kd=0.1 -- the actual config.yaml defaults.
    pid = PIDController(kp=2.0, ki=0.5, kd=0.1, dt=0.5)

    first = pid.propose(reading=293.15, setpoint=323.15, history=[], detector_flags={})  # error=30.0
    assert first.proposed_output_pct == pytest.approx(67.5)  # 2*30 + 0.5*15.0 + 0.1*0

    second = pid.propose(reading=294.15, setpoint=323.15, history=[], detector_flags={})  # error=29.0
    # integral = 15.0 + 29*0.5 = 29.5; derivative = (29-30)/0.5 = -2.0
    assert second.proposed_output_pct == pytest.approx(72.55)  # 2*29 + 0.5*29.5 + 0.1*-2.0
