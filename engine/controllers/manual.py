"""Manual controller: passthrough of a user-set slider value, no control
logic. Ignores reading/setpoint/history — it exists only to satisfy the
shared Controller interface so the loop and interlock don't special-case it.
See docs/control-loop-architecture.md §3.3.
"""

from engine.controllers.base import Controller, ProposedAction


class ManualController(Controller):
    def __init__(self, initial_value: float = 0.0):
        self.value = initial_value

    def set_value(self, value: float) -> None:
        self.value = value

    def propose(
        self, reading: float, setpoint: float, history: list[dict], detector_flags: dict
    ) -> ProposedAction:
        return ProposedAction(proposed_output_pct=self.value, source="manual")
