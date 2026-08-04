"""PlantModel interface and registry.

Any physics model implements `step` and `initial_state`; nothing outside a
model needs to know how many state variables it carries. See
docs/control-loop-architecture.md §8 for the design rationale.
"""

from abc import ABC, abstractmethod
from typing import Callable, TypeVar

MODEL_REGISTRY: dict[str, type["PlantModel"]] = {}

T = TypeVar("T", bound=type["PlantModel"])


def register_model(name: str) -> Callable[[T], T]:
    def wrapper(cls: T) -> T:
        MODEL_REGISTRY[name] = cls
        return cls

    return wrapper


class PlantModel(ABC):
    """A pluggable physics model. State is a dict so models can carry
    however many variables they need (e.g. temperature only, or
    temperature + actuator lag) without changing this interface.
    """

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def step(self, state: dict, control_input: float, dt: float) -> dict:
        """Given current state and a control input (0-100 heater %),
        return the new state after one timestep of length `dt` seconds."""

    @abstractmethod
    def initial_state(self) -> dict:
        """Return the starting state for this model."""
