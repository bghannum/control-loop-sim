"""AI-assisted controller: a Claude API call proposes the next heater
output, returned as a structured proposal via tool-use (never free text) —
see docs/control-loop-architecture.md §3.3.

**Async, not blocking (§3.3.1):** a real API call takes 1-3s, far slower
than one 0.5s control tick. propose() must never block the loop, so each
call runs in a background thread; propose() always returns immediately —
either a freshly-arrived decision, or the last committed value ("hold")
while a call is still in flight. Only one call is ever in flight at a
time. This mirrors the historian's background-thread pattern.

**Failure handling (§3.6), tracked here, acted on by ControlLoop:** three
things count as failure -- the client is unavailable, the call raises
(network error, timeout, rate limit, ...), or the model doesn't return a
valid tool call (doc's "malformed JSON" case; tool-use makes syntactically
invalid JSON structurally impossible, so this really means "no tool call"
or a response that fails pydantic validation). On any failure, the held
value is left unchanged and seconds_since_last_success keeps growing.
ControlLoop watches that value to decide when to show a warning and when
to fall back to a safe default -- this controller only reports the timer,
it doesn't act on it, keeping "propose" and "enforce" separate the same
way the interlock is kept separate from every other controller.

**Testability:** both the Anthropic client and the clock are injectable,
so tests run against a fake client (no network, no cost, deterministic)
and can simulate elapsed time without real sleeping.

**Error messages shown to the UI are sanitized, not raw exception text.**
A third-party exception's `str()` (network/API client errors) can carry
more detail than should be echoed to a screen someone might be sharing --
the full exception always goes to the log via `logging`; only our own
raised messages (already-safe, already-descriptive) or a bare exception
type name reach `ProposedAction.metadata["last_error"]`.
"""

import logging
import threading
import time
from typing import Literal

from pydantic import BaseModel, ValidationError

from engine.anthropic_support import AnthropicClientLike, summarize_error
from engine.controllers.base import Controller, ProposedAction

logger = logging.getLogger(__name__)


TOOL_NAME = "propose_heater_output"

TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "Propose the next heater actuator output for one control tick.",
    "input_schema": {
        "type": "object",
        "properties": {
            "proposed_output_pct": {
                "type": "number",
                "description": "Heater output, nominally 0-100 percent. A deterministic safety "
                "interlock enforces hard bounds/rate limits after you propose -- you don't need "
                "to self-clamp, just propose what you believe is the right control action.",
            },
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "rationale": {"type": "string", "description": "One or two sentences explaining the proposal."},
            "flagged_sensor_concern": {
                "type": "boolean",
                "description": "True if you suspect the reading may be unreliable, independent of "
                "the Tier-1 detector's own flag state given to you above.",
            },
        },
        "required": ["proposed_output_pct", "confidence", "rationale", "flagged_sensor_concern"],
    },
}


class AIProposalSchema(BaseModel):
    proposed_output_pct: float
    confidence: Literal["low", "medium", "high"]
    rationale: str
    flagged_sensor_concern: bool


def _build_prompt(reading: float, setpoint: float, history: list[dict], detector_flags: dict) -> str:
    history_lines = "\n".join(
        f"tick={h['tick']} sensed={h['t_sensed']:.2f}K setpoint={h['setpoint']:.2f}K actuator={h['actuator_output']:.1f}%"
        for h in history
    ) or "(no history yet)"

    return f"""You are the control-decision component of a thermal control loop (temperatures in Kelvin). You propose a heater output percentage each tick; a separate, deterministic safety interlock has final say and may clamp or reject your proposal, so you don't need to self-enforce hard safety bounds -- just propose the control action you believe is correct.

Current sensed temperature: {reading:.2f} K
Setpoint: {setpoint:.2f} K
Tier-1 statistical fault detector flags (not your own judgment -- a separate, fast, deterministic layer): {detector_flags}

Recent history (oldest first):
{history_lines}

Propose the next heater output using the {TOOL_NAME} tool."""


class AIController(Controller):
    def __init__(
        self,
        client: AnthropicClientLike | None,
        model: str,
        max_response_wait_s: float,
        clock=time.time,
    ):
        self.client = client
        self.model = model
        self.max_response_wait_s = max_response_wait_s
        self._clock = clock

        self._thread: threading.Thread | None = None
        self._result_lock = threading.Lock()
        self._pending_result: dict | None = None

        self._last_committed_output = 0.0
        self._last_confidence: str | None = None
        self._last_rationale: str | None = None
        self._last_flagged_concern = False
        self._last_success_time = self._clock()
        self._last_error: str | None = None

    def reset(self) -> None:
        """Restart the failure-tracking clock and drop any in-flight
        result. Called by ControlLoop when switching into AI mode, so a
        stale failure window from a prior stint doesn't immediately read
        as "already failing" the instant AI mode resumes."""
        self._last_success_time = self._clock()
        self._last_error = None
        with self._result_lock:
            self._pending_result = None

    def seconds_since_last_success(self) -> float:
        return self._clock() - self._last_success_time

    def propose(
        self, reading: float, setpoint: float, history: list[dict], detector_flags: dict
    ) -> ProposedAction:
        self._consume_pending_result()
        self._maybe_start_call(reading, setpoint, history, detector_flags)

        waiting = self._thread is not None and self._thread.is_alive()
        return ProposedAction(
            proposed_output_pct=self._last_committed_output,
            source="ai",
            confidence=self._last_confidence,
            rationale=self._last_rationale,
            flagged_sensor_concern=self._last_flagged_concern,
            metadata={
                "waiting": waiting,
                "seconds_since_last_success": self.seconds_since_last_success(),
                "last_error": self._last_error,
            },
        )

    def _maybe_start_call(self, reading: float, setpoint: float, history: list[dict], detector_flags: dict) -> None:
        if self._thread is not None and self._thread.is_alive():
            return  # a call is already in flight -- never run two at once
        self._thread = threading.Thread(
            target=self._call_api,
            args=(reading, setpoint, list(history), dict(detector_flags)),
            daemon=True,
        )
        self._thread.start()

    def _consume_pending_result(self) -> None:
        with self._result_lock:
            result = self._pending_result
            self._pending_result = None
        if result is None:
            return
        if result["success"]:
            self._last_committed_output = result["proposed_output_pct"]
            self._last_confidence = result["confidence"]
            self._last_rationale = result["rationale"]
            self._last_flagged_concern = result["flagged_sensor_concern"]
            self._last_success_time = self._clock()
            self._last_error = None
        else:
            # Failure: leave the committed output alone (hold) and let the
            # elapsed-since-success timer keep growing. ControlLoop decides
            # what to do about sustained failure -- this just reports it.
            self._last_error = result["error"]

    def _call_api(self, reading: float, setpoint: float, history: list[dict], detector_flags: dict) -> None:
        try:
            parsed = self._request_decision(reading, setpoint, history, detector_flags)
            with self._result_lock:
                self._pending_result = {"success": True, **parsed}
        except Exception as exc:
            logger.warning("AI controller call failed", exc_info=True)
            with self._result_lock:
                self._pending_result = {"success": False, "error": summarize_error(exc)}

    def _request_decision(
        self, reading: float, setpoint: float, history: list[dict], detector_flags: dict
    ) -> dict:
        if self.client is None:
            raise RuntimeError("no Anthropic client configured (missing API key?)")

        prompt = _build_prompt(reading, setpoint, history, detector_flags)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
            timeout=self.max_response_wait_s,
        )

        tool_use_blocks = [block for block in response.content if block.type == "tool_use"]
        if not tool_use_blocks:
            raise ValueError("response did not include a tool call")

        try:
            validated = AIProposalSchema(**tool_use_blocks[0].input)
        except ValidationError as exc:
            raise ValueError(f"tool call did not match expected schema: {exc}") from exc

        return {
            "proposed_output_pct": float(validated.proposed_output_pct),
            "confidence": validated.confidence,
            "rationale": validated.rationale,
            "flagged_sensor_concern": validated.flagged_sensor_concern,
        }
