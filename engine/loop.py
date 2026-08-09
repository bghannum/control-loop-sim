"""Ties one control-loop tick together: sensor read -> detector eval ->
controller propose -> interlock decide -> plant step -> log.

Implemented incrementally starting Phase 1 (plant + manual only) and grew
a stage at a time per docs/control-loop-architecture.md §5. As of Phase 5,
manual/PID/AI all propose through the same `Controller` interface, every
stage of the cycle is real, and the full "AI proposes, interlock disposes"
loop is complete. Phase 5.5 extended the interlock itself with a latching
lockout after repeated uncorrected trips (see engine/interlock.py).
"""

from collections import deque

from engine.anthropic_support import AnthropicClientLike
from engine.controllers.ai import AIController
from engine.controllers.base import ProposedAction
from engine.controllers.manual import ManualController
from engine.controllers.pid import PIDController
from engine.detector import Detector
from engine.interlock import Interlock
from engine.models import MODEL_REGISTRY
from engine.sensor import Sensor

MODES = ("manual", "pid", "ai")
SETPOINT_CHANGE_RESET_THRESHOLD_K = 1.0  # avoid resetting the detector on slider jitter


class ControlLoop:
    def __init__(self, config: dict, seed: int | None = None, ai_client: AnthropicClientLike | None = None):
        self.dt = config["simulation"]["dt_seconds"]
        model_type = config["simulation"]["model_type"]
        model_params = config["model_params"][model_type]
        self.plant = MODEL_REGISTRY[model_type](model_params)
        self.state = self.plant.initial_state()
        self.setpoint = config["setpoint"]["default_k"]

        self.manual = ManualController()
        self.pid = PIDController(
            kp=config["pid"]["kp"], ki=config["pid"]["ki"], kd=config["pid"]["kd"], dt=self.dt
        )
        ai_cfg = config["ai"]
        self.ai = AIController(
            client=ai_client,  # None is fine -- AIController treats it as an immediate failure (held/no proposal)
            model=ai_cfg["model"],
            max_response_wait_s=ai_cfg["max_response_wait_s"],
        )
        self.ai_fallback_threshold_s = ai_cfg["max_response_wait_s"] + ai_cfg["fallback_after_s"]
        self.ai_safe_output_pct = ai_cfg["safe_output_pct"]

        self._controllers = {"manual": self.manual, "pid": self.pid, "ai": self.ai}
        self.mode = "manual"

        self._history: deque = deque(maxlen=ai_cfg["history_window_ticks"])

        sensor_cfg = config["sensor"]
        self.sensor = Sensor(
            noise_sigma_k=sensor_cfg["noise_sigma_k"],
            drift_rate_k_per_s=sensor_cfg["drift_rate_k_per_s"],
            spike_offset_k=sensor_cfg["spike_offset_k"],
            spike_duration_ticks=sensor_cfg["spike_duration_ticks"],
            dt=self.dt,
            seed=seed,
        )

        detector_cfg = config["detector"]
        self.detector = Detector(
            window_ticks=detector_cfg["window_ticks"],
            noise_sigma_k=sensor_cfg["noise_sigma_k"],
            z_score_threshold=detector_cfg["z_score_threshold"],
            cusum_slack_k=detector_cfg["cusum_slack_k"],
            cusum_threshold_h=detector_cfg["cusum_threshold_h"],
            stuck_variance_ratio=detector_cfg["stuck_variance_ratio"],
            boot_grace_ticks=detector_cfg["boot_grace_ticks"],
        )
        self.detector_reset_grace_ticks = detector_cfg["reset_grace_ticks"]

        interlock_cfg = config["interlock"]
        self.interlock = Interlock(
            t_min_k=interlock_cfg["t_min_k"],
            t_max_k=interlock_cfg["t_max_k"],
            bound_margin_k=interlock_cfg["bound_margin_k"],
            max_delta_per_tick_pct=interlock_cfg["max_delta_per_tick_pct"],
            trip_safe_output_pct=interlock_cfg["trip_safe_output_pct"],
            untrusted_auto_safe_after_s=interlock_cfg["untrusted_auto_safe_after_s"],
            trip_lockout_threshold=interlock_cfg["trip_lockout_threshold"],
            trip_correction_tolerance_pct=interlock_cfg["trip_correction_tolerance_pct"],
        )
        self.manual_override_requested = False

        self.tick_count = 0

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}, expected one of {MODES}")
        if mode == "pid" and self.mode != "pid":
            # Reset integral/derivative state so error accumulated (or time
            # passed) while PID was inactive doesn't cause a jump in output
            # the instant it resumes control.
            self.pid.reset()
        if mode == "ai" and self.mode != "ai":
            # Restart the failure-tracking clock so a stale failure window
            # from a prior stint doesn't immediately read as "already
            # failing" the instant AI mode resumes.
            self.ai.reset()
        self.mode = mode

    def set_setpoint(self, setpoint_k: float) -> None:
        # A big legitimate setpoint change produces a real, fast temperature
        # ramp that can otherwise look like drift to the Tier-1 detector
        # (see engine/detector.py's named limitation) -- resetting here
        # gives it a clean slate rather than waiting on the CUSUM cap to
        # unwind a false accumulation. Guarded so a jittering slider
        # calling this every rerun with the same value doesn't reset
        # constantly.
        if abs(setpoint_k - self.setpoint) > SETPOINT_CHANGE_RESET_THRESHOLD_K:
            self.detector.reset()
        self.setpoint = setpoint_k

    def set_manual_override_requested(self, requested: bool) -> None:
        self.manual_override_requested = requested

    def reset_interlock(self) -> None:
        """Operator-acknowledged reset (backlog item 2): clears a latched
        lockout and gives the detector a fresh start too, since "I've
        confirmed it's safe, resume normal control" should mean the whole
        safety pipeline gets a clean slate, not just the interlock's own
        escalation counter. Uses detector_reset_grace_ticks, not the full
        boot grace (backlog item 8: this reset isn't a cold start, so it
        shouldn't buy a still-active fault 25s of silence) -- but not zero
        grace either, since a reset commonly happens right after a trip,
        exactly when the plant is likely mid a fast real recovery transient
        that a completely ungraced detector can mistake for sustained drift
        (see Detector.reset()'s docstring)."""
        self.interlock.reset_lockout()
        self.detector.reset(grace_ticks=self.detector_reset_grace_ticks)

    def set_pid_gains(self, kp: float, ki: float, kd: float) -> None:
        self.pid.kp, self.pid.ki, self.pid.kd = kp, ki, kd

    def set_drift(self, enabled: bool) -> None:
        self.sensor.set_drift(enabled)

    def set_stuck(self, enabled: bool) -> None:
        self.sensor.set_stuck(enabled)

    def trigger_spike(self) -> None:
        self.sensor.trigger_spike()

    def tick(self, manual_input_pct: float = 0.0) -> dict:
        self.manual.set_value(manual_input_pct)

        # 1. Sensor read — applies active fault modes; controllers only ever see this.
        t_true = self.state["temperature"]
        t_sensed = self.sensor.read(t_true)

        # 2. Detector eval — Tier 1 statistical, drives the interlock's sensor-trust gate.
        detector_flags = self.detector.evaluate(t_sensed)
        sensor_trusted = not any(detector_flags.values())

        # 3. Controller proposes.
        active_controller = self._controllers[self.mode]
        action = active_controller.propose(t_sensed, self.setpoint, list(self._history), detector_flags)

        # 3b. AI dead-man timer (§3.6): if AI has gone this long without a
        # single valid response, stop trusting whatever it last committed
        # to and substitute a safe default -- this is a system-initiated
        # safety action, distinct from a human overriding anything, and
        # still passes through the interlock like any other proposal.
        ai_fallback_active = False
        if self.mode == "ai" and self.ai.seconds_since_last_success() > self.ai_fallback_threshold_s:
            action = ProposedAction(
                proposed_output_pct=self.ai_safe_output_pct,
                source="ai",
                rationale="AI unresponsive past the failure-handling grace period -- automatic safe fallback.",
                metadata=action.metadata,
            )
            ai_fallback_active = True

        # 4. Interlock decides.
        decision = self.interlock.evaluate(
            proposed_output_pct=action.proposed_output_pct,
            source=action.source,
            t_sensed=t_sensed,
            sensor_trusted=sensor_trusted,
            override_requested=self.manual_override_requested,
        )
        actuator_output = decision.actuator_output

        # 5. Plant integrates forward one timestep.
        self.state = self.plant.step(self.state, actuator_output, self.dt)
        self.tick_count += 1

        self._history.append(
            {"tick": self.tick_count, "t_sensed": t_sensed, "setpoint": self.setpoint, "actuator_output": actuator_output}
        )

        # 6. Log record — schema per docs/control-loop-architecture.md §4.
        return {
            "tick": self.tick_count,
            "t_true": t_true,
            "t_sensed": t_sensed,
            "setpoint": self.setpoint,
            "active_faults": self.sensor.active_faults(),
            "detector_flags": detector_flags,
            "controller_source": action.source,
            "proposed_action": action,
            "interlock_result": decision.result,
            "interlock_reason": decision.reason,
            "override_active": decision.override_active,
            "ai_fallback_active": ai_fallback_active,
            "interlock_locked_out": self.interlock.locked_out,
            "trip_strikes": self.interlock.trip_strikes,
            "trip_lockout_threshold": self.interlock.trip_lockout_threshold,
            "actuator_output": actuator_output,
        }
