"""Known-outcome scenarios for FirstOrderThermal (Phase 1).

Params match config.yaml's first_order block so these numbers stay
meaningful as documentation of the tuned system, not just arbitrary test
fixtures. See docs/control-loop-architecture.md §3.1.
"""

import pytest

from engine.models.first_order import FirstOrderThermal

PARAMS = {
    "thermal_mass": 5.0,
    "loss_coeff": 0.3,
    "k_heat": 1.0,
    "t_ambient": 293.15,
    "t_initial": 293.15,
}


def make_model():
    return FirstOrderThermal(PARAMS)


def test_initial_state_matches_config():
    model = make_model()
    assert model.initial_state() == {"temperature": 293.15}


def test_single_step_exact_value_heater_on_at_ambient():
    # At T == T_ambient the loss term is zero, so dT/dt = heater*k_heat/thermal_mass
    # = 10*1.0/5.0 = 2.0 K/s. Over dt=0.5s that's a clean +1.0K step.
    model = make_model()
    next_state = model.step({"temperature": 293.15}, control_input=10.0, dt=0.5)
    assert next_state["temperature"] == pytest.approx(294.15)


def test_single_step_exact_value_heater_off_above_ambient():
    # heater=0, so dT/dt = -loss_coeff*(T-T_ambient)/thermal_mass
    # = -0.3*6.85/5.0 = -0.411 K/s. Over dt=0.5s: -0.2055K.
    model = make_model()
    next_state = model.step({"temperature": 300.0}, control_input=0.0, dt=0.5)
    assert next_state["temperature"] == pytest.approx(299.7945)


def test_heater_off_decays_monotonically_toward_ambient():
    model = make_model()
    state = {"temperature": 310.0}
    prev_temp = state["temperature"]
    for _ in range(500):
        state = model.step(state, control_input=0.0, dt=0.5)
        assert state["temperature"] <= prev_temp  # pure decay, never overshoots ambient
        prev_temp = state["temperature"]
    assert state["temperature"] == pytest.approx(293.15, abs=0.01)


def test_heater_on_converges_to_analytical_steady_state():
    # At equilibrium dT/dt = 0, so T_ss = T_ambient + heater*k_heat/loss_coeff.
    # heater=9%: 293.15 + 9*1.0/0.3 = 323.15K -- exactly the config default setpoint.
    model = make_model()
    state = model.initial_state()
    for _ in range(2000):  # 1000s simulated, ~60x the 16.7s thermal time constant
        state = model.step(state, control_input=9.0, dt=0.5)
    assert state["temperature"] == pytest.approx(323.15, abs=0.01)
