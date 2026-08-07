"""Tier-2 LLM triage: a plain-language, advisory-only explanation of
whatever the Tier-1 statistical detector (engine/detector.py) currently
flags -- see docs/control-loop-architecture.md §3.5.

**Advisory only, never feeds back into the interlock.** This module has no
path into control at all: it doesn't propose actuator values (that's
AIController's job) and nothing here is consulted by Interlock.evaluate().
Its only output is text for a human to read.

**Manual/on-demand only, by design.** Unlike AIController (which runs every
0.5s tick), triage is deliberately never auto-triggered -- see CLAUDE.md's
Phase 7 section for the cost-control reasoning. Because it's a rare,
explicit, one-shot action rather than a per-tick decision, `request()` is a
plain synchronous call (with the caller expected to show a spinner) rather
than reusing AIController's background-thread/polling pattern, which exists
specifically to protect the per-tick control loop from a multi-second API
call -- a problem that doesn't apply to an on-demand button.

**Structured output via tool-use**, same reasoning as AIController: a
pydantic model validates the *semantic* shape (right types, right enum
values) on top of what tool-use already makes structurally guaranteed
(syntactically valid JSON).

Ground truth (`active_faults`) is deliberately excluded from the prompt --
same reasoning as the AI controller: the model should reason from what a
real operator would see (readings + the Tier-1 flag), not be handed the
answer key.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError

from engine.anthropic_support import AnthropicClientLike, summarize_error

logger = logging.getLogger(__name__)

TOOL_NAME = "provide_fault_triage"

TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "Provide a plain-language triage of a flagged sensor anomaly for a non-engineer operator.",
    "input_schema": {
        "type": "object",
        "properties": {
            "likely_fault_type": {
                "type": "string",
                "enum": ["spike", "drift", "stuck", "other"],
                "description": "Best guess at which fault mode is occurring, based on the flags and readings given.",
            },
            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            "explanation": {
                "type": "string",
                "description": "One or two plain-language sentences a non-engineer operator could understand.",
            },
        },
        "required": ["likely_fault_type", "severity", "explanation"],
    },
}


class TriageSchema(BaseModel):
    likely_fault_type: Literal["spike", "drift", "stuck", "other"]
    severity: Literal["low", "medium", "high"]
    explanation: str


@dataclass
class TriageResult:
    success: bool
    fault_type: str | None = None
    severity: str | None = None
    explanation: str | None = None
    error: str | None = None


def _build_prompt(history: list[dict], detector_flags: dict) -> str:
    history_lines = "\n".join(
        f"tick={h['tick']} sensed={h['t_sensed']:.2f}K setpoint={h['setpoint']:.2f}K actuator={h['actuator_output']:.1f}%"
        for h in history
    ) or "(no history yet)"

    return f"""You are the Tier-2 explanatory layer of a thermal control loop's fault-detection system (temperatures in Kelvin). A fast, deterministic Tier-1 statistical detector has already flagged an anomaly -- your job is only to characterize it in plain language for a non-engineer operator. You have no control authority and your output is never used to make any control decision.

Currently active Tier-1 detector flags: {detector_flags}

Recent history (oldest first):
{history_lines}

Provide your triage using the {TOOL_NAME} tool."""


class Triage:
    def __init__(self, client: AnthropicClientLike | None, model: str, max_wait_s: float):
        self.client = client
        self.model = model
        self.max_wait_s = max_wait_s

    def request(self, history: list[dict], detector_flags: dict) -> TriageResult:
        try:
            if self.client is None:
                raise RuntimeError("no Anthropic client configured (missing API key?)")

            prompt = _build_prompt(history, detector_flags)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                tools=[TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": prompt}],
                timeout=self.max_wait_s,
            )

            tool_use_blocks = [block for block in response.content if block.type == "tool_use"]
            if not tool_use_blocks:
                raise ValueError("response did not include a tool call")

            try:
                validated = TriageSchema(**tool_use_blocks[0].input)
            except ValidationError as exc:
                raise ValueError(f"tool call did not match expected schema: {exc}") from exc

            return TriageResult(
                success=True,
                fault_type=validated.likely_fault_type,
                severity=validated.severity,
                explanation=validated.explanation,
            )
        except Exception as exc:
            logger.warning("triage call failed", exc_info=True)
            return TriageResult(success=False, error=summarize_error(exc))
