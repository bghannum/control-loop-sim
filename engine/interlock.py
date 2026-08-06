"""Deterministic safety interlock — no LLM calls in this path, ever.

Checks applied in order, first failure wins:
1. Sensor-trust gate -- ABSOLUTE, never overridable by anyone. If the
   detector currently flags anything, hold at the last-known-good actuator
   output regardless of what any controller (including manual) proposed.
   The doc's "regardless of source" phrasing is specific to this check.
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

See docs/control-loop-architecture.md §3.4.
"""

import math
from dataclasses import dataclass


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
        initial_output: float = 0.0,
    ):
        self.t_min_k = t_min_k
        self.t_max_k = t_max_k
        self.bound_margin_k = bound_margin_k
        self.max_delta_per_tick_pct = max_delta_per_tick_pct
        self.trip_safe_output_pct = trip_safe_output_pct
        self.last_output = initial_output

    def evaluate(
        self,
        proposed_output_pct: float,
        source: str,
        t_sensed: float,
        sensor_trusted: bool,
        override_requested: bool,
    ) -> InterlockDecision:
        # 1. Sensor-trust gate -- absolute, checked first, no override.
        if not sensor_trusted:
            decision = InterlockDecision(
                actuator_output=self.last_output,
                result="allow" if proposed_output_pct == self.last_output else "reject",
                reason="sensor untrusted (Tier-1 detector flag active) -- holding at last-known-good output",
                override_active=False,
            )
            self.last_output = decision.actuator_output
            return decision

        # 2. Hard over/under-temperature trip -- absolute, no override,
        # bypasses the slew limit. Forces a safe output the instant t_sensed
        # is actually at or past a hard bound, regardless of what's proposed
        # or which direction -- unlike check 3 below, which only blocks
        # proposals pushing further TOWARD a bound that hasn't been reached
        # yet.
        if t_sensed >= self.t_max_k:
            decision = InterlockDecision(
                actuator_output=self.trip_safe_output_pct,
                result="reject",
                reason=(
                    f"sensed temperature at or past T_max ({self.t_max_k}K) -- hard trip, "
                    f"forcing safe output ({self.trip_safe_output_pct}%)"
                ),
                override_active=False,
            )
            self.last_output = decision.actuator_output
            return decision
        if t_sensed <= self.t_min_k:
            # Opposite extreme from the ceiling trip: the correct response
            # to dangerously cold is max heat, not less. In practice
            # unreachable with this system's physics (no active cooling,
            # ambient sits well above t_min_k) -- included so the interlock
            # is honestly symmetric rather than silently one-sided.
            safe_low_output = 100.0
            decision = InterlockDecision(
                actuator_output=safe_low_output,
                result="reject",
                reason=(
                    f"sensed temperature at or past T_min ({self.t_min_k}K) -- hard trip, "
                    f"forcing safe output ({safe_low_output}%)"
                ),
                override_active=False,
            )
            self.last_output = decision.actuator_output
            return decision

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
            self.last_output = decision.actuator_output
            return decision

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
            self.last_output = decision.actuator_output
            return decision

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
        self.last_output = decision.actuator_output
        return decision
