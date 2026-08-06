"""Deterministic safety interlock — no LLM calls in this path, ever.

Checks applied in order, first failure wins:
0. Lockout gate -- ABSOLUTE. If a prior escalation latched the interlock
   (see check 2), every proposal is refused until an explicit operator
   reset (`reset_lockout()`) clears it. Nothing below this point runs.
1. Sensor-trust gate -- ABSOLUTE, never overridable by anyone. If the
   detector currently flags anything, hold at the last-known-good actuator
   output -- UNLESS the sensed temperature is simultaneously past a hard
   bound, or the untrusted period has gone on too long, in which case it
   forces a safe output instead (see "Why the sensor-trust gate can force
   safe output" below). The doc's "regardless of source" phrasing is
   specific to this check's basic hold behavior.
2. Hard over/under-temperature trip -- ABSOLUTE, never overridable, bypasses
   the slew limit (an emergency trip must reach the safe value immediately,
   not be rate-limited like routine control). This is the "high-high"
   counterpart to check 3: once t_sensed is actually AT OR PAST t_max_k/
   t_min_k -- not just near it -- force a safe output regardless of what's
   proposed or which direction. Added after live testing showed the softer
   margin check (3) alone let a real overshoot run well past the hard
   ceiling: that check only blocks proposals pushing further TOWARD a
   bound, so once a controller was already proposing decreases (but not
   fast enough to beat thermal lag), there was nothing left to block.
   Repeated trips without the controller ever proposing a genuine
   correction escalate to a LATCHING lockout (check 0) rather than
   self-clearing forever -- see "Escalation to lockout" below.
3. Absolute bounds / margin (present-state only, no lookahead) -- the ONE
   check a manual override can bypass, with a persistent warning. PID/AI
   can never override it, under any circumstance. Only ever reachable
   below check 2's hard limits now, so it functions as the "high" alarm to
   check 2's "high-high" trip.
4. Rate-of-change (slew) limit -- ABSOLUTE, never overridable, any source.
   The doc's own example ("catches ... a fat-fingered manual override")
   only makes sense if manual can't bypass this one either.
5. Pass-through -- proposal (or its [0,100] clamp) executes unmodified.

Operates on t_sensed only, never t_true -- matching "controllers and
detectors always operate on reading, never ground truth" (doc §3.2), and
explicitly stated for the bounds check too (doc §3.4). This is deliberate:
a corrupted sensor could in principle fool the bounds check, which is
exactly why the sensor-trust gate runs FIRST -- it's the safety net for
that scenario, not a redundant check.

**Why the sensor-trust gate can force safe output, not just hold:**
"Hold at last-known-good" isn't the same as "safe" -- if the controller was
heating hard the instant the detector flagged something, freezing there
just keeps applying that same heat for the entire untrusted period, and
temperature keeps climbing the whole time. Two situations override the
plain hold:
  - The sensed temperature is *simultaneously* past a hard bound. Reasoning:
    forcing a safe output is one-directional (can only make things safer),
    so acting on an untrusted reading for this specific purpose can't
    produce a worse outcome than not acting -- unlike a routine control
    decision, where trusting a bad reading could easily make things worse.
  - The untrusted period has lasted longer than untrusted_auto_safe_after_s.
    Same dead-man-timer shape as the AI controller's failure handling
    (doc §3.6): don't hold an unverified value forever, fall back to safe
    after a bounded wait.

**Escalation to lockout:** a hard trip (check 2) is self-clearing by design
-- it fires fresh off t_sensed every tick. But if the same excursion keeps
recurring (temperature drops back under the limit, then crosses again)
without the controller ever proposing something that would actually
correct it, self-clearing just means silently repeating the same failure
forever with no one told. After `trip_lockout_threshold` such episodes
(separate excursions, not consecutive ticks -- this is about the
controller failing to learn across excursions, not one long excursion),
the interlock latches: every proposal is refused and the safe output is
forced until `reset_lockout()` is called. A "correction" is judged
against the controller's own proposals in the calm gap between episodes,
not against what the interlock actually applied (which was clamped to the
trip's safe value regardless) -- specifically, proposing something at or
near the safe value again, within trip_correction_tolerance_pct.

See docs/control-loop-architecture.md §3.4.
"""

import logging
import math
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class InterlockDecision:
    actuator_output: float
    result: str  # "allow" | "clamp" | "reject"
    reason: str
    override_active: bool


class Interlock:
    def __init__(
        self,
        t_min_k: float,
        t_max_k: float,
        bound_margin_k: float,
        max_delta_per_tick_pct: float,
        trip_safe_output_pct: float = 0.0,
        untrusted_auto_safe_after_s: float = 20.0,
        trip_lockout_threshold: int = 2,
        trip_correction_tolerance_pct: float = 1.0,
        initial_output: float = 0.0,
        clock=time.time,
    ):
        self.t_min_k = t_min_k
        self.t_max_k = t_max_k
        self.bound_margin_k = bound_margin_k
        self.max_delta_per_tick_pct = max_delta_per_tick_pct
        self.trip_safe_output_pct = trip_safe_output_pct
        self.untrusted_auto_safe_after_s = untrusted_auto_safe_after_s
        self.trip_lockout_threshold = trip_lockout_threshold
        self.trip_correction_tolerance_pct = trip_correction_tolerance_pct
        self.last_output = initial_output
        self._clock = clock

        self._untrusted_since: float | None = None
        self._auto_safe_logged = False

        self.locked_out = False
        self.trip_strikes = 0
        self._was_tripped = False
        self._last_trip_was_ceiling: bool | None = None
        self._corrected_since_last_episode = True  # no episode yet -- nothing to correct

    def reset_lockout(self) -> None:
        """Operator-acknowledged reset: clears a latched lockout and every
        piece of state that feeds it, plus the sensor-untrusted timer. Does
        NOT touch last_output -- the actuator stays wherever it was until a
        controller proposes something new next tick."""
        if self.locked_out or self.trip_strikes:
            logger.info("interlock: operator reset (was %d strike(s), locked_out=%s)", self.trip_strikes, self.locked_out)
        self.locked_out = False
        self.trip_strikes = 0
        self._was_tripped = False
        self._last_trip_was_ceiling = None
        self._corrected_since_last_episode = True
        self._untrusted_since = None
        self._auto_safe_logged = False

    def _trip_target_and_bound_name(self, past_ceiling: bool) -> tuple[float, str]:
        if past_ceiling:
            return self.trip_safe_output_pct, "T_max"
        # Opposite extreme from the ceiling trip: the correct response to
        # dangerously cold is max heat, not less. In practice unreachable
        # with this system's physics (no active cooling, ambient sits well
        # above t_min_k) -- included so the interlock is honestly symmetric.
        return 100.0, "T_min"

    def _finalize(self, decision: InterlockDecision) -> InterlockDecision:
        """Every branch below ends by remembering what actually got
        applied (used as the reference point for next tick's hold/margin/
        slew checks) and returning it -- pulled into one place instead of
        repeating both lines at every one of evaluate()'s seven exit points."""
        self.last_output = decision.actuator_output
        return decision

    def evaluate(
        self,
        proposed_output_pct: float,
        source: str,
        t_sensed: float,
        sensor_trusted: bool,
        override_requested: bool,
    ) -> InterlockDecision:
        # 0. Lockout gate -- absolute, checked before anything else.
        if self.locked_out:
            decision = InterlockDecision(
                actuator_output=self.trip_safe_output_pct,
                result="reject",
                reason=(
                    f"LOCKED OUT: {self.trip_strikes} over-temperature trips without correction -- "
                    "awaiting manual reset"
                ),
                override_active=False,
            )
            return self._finalize(decision)

        past_ceiling = t_sensed >= self.t_max_k
        past_floor = t_sensed <= self.t_min_k

        # 1. Sensor-trust gate -- absolute, no override.
        if not sensor_trusted:
            if self._untrusted_since is None:
                self._untrusted_since = self._clock()
                logger.info("interlock: sensor became untrusted (t_sensed=%.2f)", t_sensed)
            untrusted_duration = self._clock() - self._untrusted_since

            if past_ceiling or past_floor:
                target, bound_name = self._trip_target_and_bound_name(past_ceiling)
                reason = (
                    f"sensor untrusted AND at/past {bound_name} -- forcing safe output ({target}%) "
                    "despite distrust (this specific action is one-directional and cannot worsen the outcome)"
                )
            elif untrusted_duration > self.untrusted_auto_safe_after_s:
                target = self.trip_safe_output_pct
                reason = (
                    f"sensor untrusted for over {self.untrusted_auto_safe_after_s:.0f}s -- "
                    f"auto safe default ({target}%) rather than holding indefinitely"
                )
                if not self._auto_safe_logged:
                    logger.warning("interlock: sensor untrusted past %.0fs -- auto safe default engaged", self.untrusted_auto_safe_after_s)
                    self._auto_safe_logged = True
            else:
                target = self.last_output
                reason = "sensor untrusted (Tier-1 detector flag active) -- holding at last-known-good output"

            decision = InterlockDecision(
                actuator_output=target,
                result="allow" if proposed_output_pct == target else "reject",
                reason=reason,
                override_active=False,
            )
            return self._finalize(decision)
        self._untrusted_since = None  # trusted again -- clear the staleness timer
        self._auto_safe_logged = False

        # 2. Hard over/under-temperature trip -- absolute, no override,
        # bypasses the slew limit.
        if past_ceiling or past_floor:
            if not self._was_tripped:
                # A new excursion is starting -- count it, unless the
                # controller genuinely corrected during the calm gap since
                # the last one, in which case this is a fresh start.
                self.trip_strikes = 1 if self._corrected_since_last_episode else self.trip_strikes + 1
                self._corrected_since_last_episode = False
                self._last_trip_was_ceiling = past_ceiling
                logger.warning(
                    "interlock: hard trip engaged (t_sensed=%.2f, strike %d/%d)",
                    t_sensed, self.trip_strikes, self.trip_lockout_threshold,
                )
                if self.trip_strikes >= self.trip_lockout_threshold:
                    self.locked_out = True
                    logger.error("interlock: LOCKOUT engaged after %d uncorrected trips", self.trip_strikes)
                    decision = InterlockDecision(
                        actuator_output=self.trip_safe_output_pct,
                        result="reject",
                        reason=(
                            f"LOCKOUT ENGAGED: {self.trip_strikes} over-temperature trips without "
                            "correction -- forcing safe output, awaiting manual reset"
                        ),
                        override_active=False,
                    )
                    self._was_tripped = True
                    return self._finalize(decision)
            self._was_tripped = True

            target, bound_name = self._trip_target_and_bound_name(past_ceiling)
            decision = InterlockDecision(
                actuator_output=target,
                result="reject",
                reason=(
                    f"sensed temperature at or past {bound_name} -- hard trip, forcing safe output "
                    f"({target}%) [strike {self.trip_strikes}/{self.trip_lockout_threshold}]"
                ),
                override_active=False,
            )
            return self._finalize(decision)

        self._was_tripped = False
        if self._last_trip_was_ceiling is not None and not self._corrected_since_last_episode:
            floor_safe_output, _ = self._trip_target_and_bound_name(past_ceiling=False)
            corrected = (
                proposed_output_pct <= self.trip_safe_output_pct + self.trip_correction_tolerance_pct
                if self._last_trip_was_ceiling
                else proposed_output_pct >= floor_safe_output - self.trip_correction_tolerance_pct
            )
            if corrected:
                self._corrected_since_last_episode = True

        # Unconditional numeric clamp to the physically valid range -- not
        # something an override should bypass, there's no such thing as a
        # 120% or -10% heater command.
        raw = max(0.0, min(100.0, proposed_output_pct))
        manual_override_eligible = source == "manual" and override_requested

        # 3. Absolute bounds (margin rule) -- the one overridable check.
        # near_ceiling/near_floor can only be true here for the band below
        # the hard trip thresholds above (t_sensed < t_max_k / > t_min_k).
        near_ceiling = t_sensed >= self.t_max_k - self.bound_margin_k
        near_floor = t_sensed <= self.t_min_k + self.bound_margin_k
        pushing_further_toward_bound = (near_ceiling and raw > self.last_output) or (
            near_floor and raw < self.last_output
        )

        if pushing_further_toward_bound and not manual_override_eligible:
            bound_name = "T_max" if near_ceiling else "T_min"
            direction = "increase" if near_ceiling else "decrease"
            decision = InterlockDecision(
                actuator_output=self.last_output,
                result="reject",
                reason=f"sensed temperature within {self.bound_margin_k}K of {bound_name} -- rejecting further {direction}",
                override_active=False,
            )
            return self._finalize(decision)

        # 4. Slew-rate limit -- absolute, no override, any source.
        delta = raw - self.last_output
        if abs(delta) > self.max_delta_per_tick_pct:
            clamped = self.last_output + math.copysign(self.max_delta_per_tick_pct, delta)
            decision = InterlockDecision(
                actuator_output=clamped,
                result="clamp",
                reason=f"proposed change {delta:+.1f}%/tick exceeds slew limit {self.max_delta_per_tick_pct}%/tick",
                override_active=False,
            )
            return self._finalize(decision)

        # 5. Pass-through (possibly via an active manual override of check 3).
        overriding = pushing_further_toward_bound and manual_override_eligible
        if overriding:
            reason = "manual override active -- operating outside validated safety bounds"
        elif raw != proposed_output_pct:
            reason = "clamped to valid actuator range [0, 100]"
        else:
            reason = "within bounds"
        decision = InterlockDecision(
            actuator_output=raw,
            result="clamp" if (raw != proposed_output_pct and not overriding) else "allow",
            reason=reason,
            override_active=overriding,
        )
        return self._finalize(decision)
