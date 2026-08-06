"""Classical PID controller: output = Kp*e + Ki*∫e + Kd*(de/dt), gains
exposed as UI sliders. See docs/control-loop-architecture.md §3.3.

Output is NOT clamped to [0, 100] here -- that's the interlock's job
(arrives Phase 4), and this controller proposing an out-of-range value is
exactly the "AI/PID proposes, interlock disposes" separation the whole
project is built around. Until Phase 4 lands, an out-of-range proposal
just passes straight through to the plant.
"""

from engine.controllers.base import Controller, ProposedAction


class PIDController(Controller):
    def __init__(self, kp: float, ki: float, kd: float, dt: float):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.dt = dt
        self._integral = 0.0
        self._prev_error: float | None = None

    def reset(self) -> None:
        """Clear accumulated integral/derivative state. Call whenever this
        controller transitions from inactive to active, so error that
        accumulated (or time that passed) while another controller was
        driving doesn't cause a sudden jump in output the moment PID
        resumes control."""
        self._integral = 0.0
        self._prev_error = None

    def propose(
        self, reading: float, setpoint: float, history: list[dict], detector_flags: dict
    ) -> ProposedAction:
        error = setpoint - reading
        self._integral += error * self.dt
        derivative = 0.0 if self._prev_error is None else (error - self._prev_error) / self.dt
        self._prev_error = error

        output = self.kp * error + self.ki * self._integral + self.kd * derivative
        return ProposedAction(proposed_output_pct=output, source="pid")
