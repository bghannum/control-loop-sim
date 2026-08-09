"""Tier-1 statistical fault detector: rolling z-score for spikes, CUSUM for
drift, rolling variance for stuck-at-value. Fast, deterministic, runs every
tick -- this tier alone drives the interlock's sensor-trust gate; Tier-2
LLM triage (Phase 7) is advisory-only and never feeds back into it.

Standardization for both the z-score and CUSUM checks uses the sensor's
*configured* noise_sigma_k (a known, pre-calibrated instrument property),
not an empirically re-estimated rolling std -- a small rolling window's std
estimate is itself noisy, which would make thresholds flaky. Rolling
variance IS empirically measured for the stuck-at-value check specifically,
since "suspiciously low variance" is exactly what that check needs to
observe directly, not assume.

The baseline mean for z-score/CUSUM is computed from the window BEFORE the
current reading is appended (comparing the new point against recent
history, not against itself); the stuck-at-value variance check uses the
window AFTER appending (it's asking "how flat has the sensor been
recently," which should include the newest point).

**Named limitation, and why there's a boot grace period:** simple rolling
statistics on the reading alone can't perfectly distinguish a sensor fault
from a legitimate fast real change -- e.g. a normal PID startup ramp (cold
plant chasing a setpoint tens of Kelvin away) looks statistically
identical to sustained drift. Closed-loop testing surfaced a genuinely
broken interaction from this: the detector false-flags a few ticks into a
normal startup ramp, the interlock (correctly, per its own design) freezes
the actuator at "last-known-good" -- which, mid-ramp, is an actively-
heating value nowhere near equilibrium for the current temperature -- so
the plant keeps heating, which keeps looking like ongoing drift, so the
flag never clears. A self-sustaining false alarm, not a bounded one.

The CUSUM cap below (CUSUM_CAP_MULTIPLIER * cusum_threshold_h) is still
useful defense-in-depth for large transients mid-session, but it only
bounds *recovery time once the signal actually stabilizes* -- it can't
help here, because a frozen-but-wrong actuator output means the signal
never stabilizes on its own. The real fix is `boot_grace_ticks`: the
detector accepts no readings at all (doesn't touch window/CUSUM state)
until that many ticks have passed, so it starts truly fresh once a normal
startup transient has already had time to settle, rather than watching --
and reacting to -- the transient itself. Reset() restarts this grace
period too, since a live setpoint change is the same kind of event.

A model-aware detector could avoid the false flag without needing a grace
period at all, but that would couple this "dumb" statistical tier to
plant physics -- the same coupling the interlock's design doc explicitly
rejects for the same reason (§3.4).

See docs/control-loop-architecture.md §3.5.
"""

import logging
from collections import deque

logger = logging.getLogger(__name__)

CUSUM_CAP_MULTIPLIER = 2.0


class Detector:
    def __init__(
        self,
        window_ticks: int,
        noise_sigma_k: float,
        z_score_threshold: float,
        cusum_slack_k: float,
        cusum_threshold_h: float,
        stuck_variance_ratio: float,
        boot_grace_ticks: int = 0,
        min_samples: int = 5,
    ):
        self.noise_sigma_k = noise_sigma_k
        self.z_score_threshold = z_score_threshold
        self.cusum_slack_k = cusum_slack_k
        self.cusum_threshold_h = cusum_threshold_h
        self.stuck_variance_threshold = stuck_variance_ratio * noise_sigma_k**2
        self.boot_grace_ticks = boot_grace_ticks
        self.min_samples = min_samples
        self._cusum_cap = CUSUM_CAP_MULTIPLIER * cusum_threshold_h

        self._window: deque[float] = deque(maxlen=window_ticks)
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        self._ticks_seen = 0
        self._prev_flags = {"spike": False, "drift": False, "stuck": False}

    def reset(self, grace_ticks: int | None = None) -> None:
        """Clear window and CUSUM state. grace_ticks=None (default) uses the
        full boot_grace_ticks -- correct for a fresh instance or a live
        setpoint change, both of which produce a real transient that grace
        exists to mask.

        A short, explicit grace_ticks is for ControlLoop.reset_interlock()
        specifically. Originally this passed 0 (backlog item 8): an operator
        manually confirming "conditions are safe, resume normal control" is
        not a cold start, so re-arming the full 25s countdown just gives a
        still-active fault 25s to hide in if the operator reset without also
        clearing it. But 0 grace turned out to have the opposite problem: a
        reset commonly happens right after a trip, i.e. exactly when the
        plant is most likely mid a fast, real, physical recovery (e.g.
        cooling back down after the heater was forced to 0%) -- and with no
        grace at all, the detector starts building CUSUM state from the
        sharpest part of that transient, which can false-flag as sustained
        drift and never clear (same self-sustaining-false-alarm mechanism
        the module docstring describes for a startup ramp, just triggered by
        a reset instead). A short grace_ticks blunts the sharpest part of a
        post-trip transient without reopening much of the original 25s
        hiding window -- see reset_grace_ticks in config.yaml, used by
        ControlLoop.reset_interlock()."""
        self._window.clear()
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        grace = self.boot_grace_ticks if grace_ticks is None else grace_ticks
        self._ticks_seen = max(0, self.boot_grace_ticks - grace)
        self._prev_flags = {"spike": False, "drift": False, "stuck": False}

    def evaluate(self, reading: float) -> dict:
        self._ticks_seen += 1
        if self._ticks_seen <= self.boot_grace_ticks:
            return {"spike": False, "drift": False, "stuck": False}

        spike = False
        drift = False

        if len(self._window) >= self.min_samples:
            baseline_mean = sum(self._window) / len(self._window)
            z = (reading - baseline_mean) / self.noise_sigma_k

            spike = abs(z) > self.z_score_threshold

            self._cusum_pos = min(self._cusum_cap, max(0.0, self._cusum_pos + z - self.cusum_slack_k))
            self._cusum_neg = max(-self._cusum_cap, min(0.0, self._cusum_neg + z + self.cusum_slack_k))
            drift = self._cusum_pos > self.cusum_threshold_h or self._cusum_neg < -self.cusum_threshold_h

        self._window.append(reading)

        stuck = False
        if len(self._window) >= self.min_samples:
            mean = sum(self._window) / len(self._window)
            variance = sum((x - mean) ** 2 for x in self._window) / len(self._window)
            stuck = variance < self.stuck_variance_threshold

        flags = {"spike": spike, "drift": drift, "stuck": stuck}
        for name, active in flags.items():
            if active and not self._prev_flags[name]:
                logger.warning("detector: %s flag raised (reading=%.2f)", name, reading)
            elif self._prev_flags[name] and not active:
                logger.info("detector: %s flag cleared", name)
        self._prev_flags = flags

        return flags
