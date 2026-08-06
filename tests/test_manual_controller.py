"""Known-outcome scenarios for ManualController (Phase 1): pure passthrough,
no logic, ignores reading/setpoint/history. See docs/control-loop-architecture.md §3.3.
"""

from engine.controllers.manual import ManualController


def test_propose_returns_last_set_value_regardless_of_inputs():
    controller = ManualController(initial_value=0.0)
    controller.set_value(42.0)

    action = controller.propose(reading=999.0, setpoint=-1.0, history=[{"anything": True}], detector_flags={})

    assert action.proposed_output_pct == 42.0
    assert action.source == "manual"


def test_propose_reflects_updated_value_after_multiple_sets():
    controller = ManualController()
    controller.set_value(10.0)
    controller.set_value(75.0)

    action = controller.propose(reading=0.0, setpoint=0.0, history=[], detector_flags={})

    assert action.proposed_output_pct == 75.0
