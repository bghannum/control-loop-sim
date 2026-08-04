"""Shared controller interface.

Manual, PID, and AI controllers all implement `propose`, so the interlock
and logging layer never need to know which one is active. See
docs/control-loop-architecture.md §3.3.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProposedAction:
    proposed_output_pct: float
    source: str  # "manual" | "pid" | "ai"
    confidence: str | None = None       # AI only
    rationale: str | None = None         # AI only
    flagged_sensor_concern: bool = False  # AI only
    metadata: dict = field(default_factory=dict)


class Controller(ABC):
    @abstractmethod
    def propose(self, reading: float, setpoint: float, history: list[dict]) -> ProposedAction:
        """Given the latest (possibly faulted) sensor reading, the current
        setpoint, and recent tick history, propose a next actuator command.
        Does not know about interlock bounds — that's the interlock's job.
        """
