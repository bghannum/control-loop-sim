"""Sensor model: wraps true plant temperature, applies active fault modes.

The only place faults are injected — controllers and detectors always see
"reading," never ground truth. Baseline Gaussian noise is always present
(matches doc §3.2's table: "N/A -- always present"); drift, stuck-at-value,
and spike/dropout are independently toggleable/triggerable faults layered
on top, in an order chosen to match how a real sensor would actually fail:
stuck-at overrides everything else -- a frozen sensor doesn't also show
fresh noise, and that near-zero variance is exactly what Phase 4's
detector will use to catch it. Otherwise drift and spike bias the true
value, and baseline noise is layered on last.

Seeded scenarios (config.yaml sensor.seeded_scenarios) reseed the RNG for
reproducible noise; which faults fire and when is still operator-driven
via the UI toggles, not scripted -- this is a live demo, not a replay.
See docs/control-loop-architecture.md §3.2.
"""

import numpy as np


class Sensor:
    def __init__(
        self,
        noise_sigma_k: float,
        drift_rate_k_per_s: float,
        spike_offset_k: float,
        spike_duration_ticks: int,
        dt: float,
        seed: int | None = None,
    ):
        self.noise_sigma_k = noise_sigma_k
        self.drift_rate_k_per_s = drift_rate_k_per_s
        self.spike_offset_k = spike_offset_k
        self.spike_duration_ticks = spike_duration_ticks
        self.dt = dt
        self._rng = np.random.default_rng(seed)

        self._drift_active = False
        self._drift_elapsed_s = 0.0

        self._stuck_active = False
        self._stuck_value: float | None = None

        self._spike_remaining_ticks = 0

    def reseed(self, seed: int | None) -> None:
        self._rng = np.random.default_rng(seed)

    @property
    def drift_enabled(self) -> bool:
        return self._drift_active

    @property
    def stuck_enabled(self) -> bool:
        return self._stuck_active

    def set_drift(self, enabled: bool) -> None:
        # UI setters are called unconditionally every rerun (same pattern as
        # ControlLoop.set_mode), so only reset the ramp on an actual
        # OFF->ON transition -- resetting on every call would mean the
        # drift offset never grows past a fraction of a tick.
        if enabled and not self._drift_active:
            self._drift_elapsed_s = 0.0
        self._drift_active = enabled

    def set_stuck(self, enabled: bool) -> None:
        # Same idempotent-call concern: only clear the frozen value on an
        # actual transition, so a future re-activation freezes at a fresh
        # reading instead of silently reusing a stale one.
        if enabled != self._stuck_active:
            self._stuck_value = None
        self._stuck_active = enabled

    def trigger_spike(self) -> None:
        self._spike_remaining_ticks = self.spike_duration_ticks

    def active_faults(self) -> list[str]:
        faults = []
        if self._drift_active:
            faults.append("drift")
        if self._stuck_active:
            faults.append("stuck")
        if self._spike_remaining_ticks > 0:
            faults.append("spike")
        return faults

    def read(self, t_true: float) -> float:
        if self._stuck_active:
            if self._stuck_value is None:
                self._stuck_value = t_true
            return self._stuck_value

        reading = t_true

        if self._drift_active:
            self._drift_elapsed_s += self.dt
            reading += self.drift_rate_k_per_s * self._drift_elapsed_s

        if self._spike_remaining_ticks > 0:
            reading += self.spike_offset_k
            self._spike_remaining_ticks -= 1

        reading += self._rng.normal(0.0, self.noise_sigma_k)
        return reading
