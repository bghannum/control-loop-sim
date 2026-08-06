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
    def propose(
        self, reading: float, setpoint: float, history: list[dict], detector_flags: dict
    ) -> ProposedAction:
        """Given the latest (possibly faulted) sensor reading, the current
        setpoint, recent tick history, and the Tier-1 detector's current
        flag state, propose a next actuator command. Does not know about
        interlock bounds — that's the interlock's job.

        detector_flags is passed to every controller for interface
        uniformity (Manual/PID ignore it, same as they already ignore
        history) but exists specifically for the AI controller (Phase 5),
        per docs/control-loop-architecture.md §3.3: the AI sees the
        detector's flag directly rather than inferring anomalies itself
        from raw history -- keeping "control decision" and "anomaly
        detection" as separate jobs.
        """
