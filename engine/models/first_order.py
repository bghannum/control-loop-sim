"""First-order lumped thermal model.

dT/dt = (heater_output_pct * k_heat - loss_coeff * (T - T_ambient)) / thermal_mass

Integrated with explicit Euler: T_next = T + dT/dt * dt. See
docs/control-loop-architecture.md §3.1 for why Euler over solve_ivp at this
phase, and the units of each param (documented alongside config.yaml).
"""

from engine.models.base import PlantModel, register_model


@register_model("first_order")
class FirstOrderThermal(PlantModel):
    def initial_state(self) -> dict:
        return {"temperature": self.params["t_initial"]}

    def step(self, state: dict, control_input: float, dt: float) -> dict:
        t = state["temperature"]
        t_ambient = self.params["t_ambient"]
        k_heat = self.params["k_heat"]
        loss_coeff = self.params["loss_coeff"]
        thermal_mass = self.params["thermal_mass"]

        dT_dt = (control_input * k_heat - loss_coeff * (t - t_ambient)) / thermal_mass
        return {"temperature": t + dT_dt * dt}
