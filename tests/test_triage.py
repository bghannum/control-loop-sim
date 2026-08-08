"""Known-outcome scenarios for Triage (Phase 7), against a fake, injectable
Anthropic client -- no network calls, no cost, fully deterministic. Mirrors
test_ai_controller.py's coverage of the same failure modes (bad/missing
client, exception, malformed response), minus any threading concerns --
Triage.request() is a single synchronous call, not a background thread with
a polled pending-result slot. See docs/control-loop-architecture.md §3.5.
"""

from engine.triage import Triage
from tests.conftest import FakeClient, FakeResponse, FakeTextBlock, FakeToolUseBlock


def valid_response(**overrides):
    payload = {
        "likely_fault_type": "drift",
        "severity": "medium",
        "explanation": "The reading has been trending steadily away from setpoint.",
    }
    payload.update(overrides)
    return lambda: FakeResponse([FakeToolUseBlock(payload)])


def make_triage(client):
    return Triage(client=client, model="claude-sonnet-5", max_wait_s=15.0)


def test_successful_triage_returns_structured_result():
    client = FakeClient([valid_response()])
    triage = make_triage(client)

    result = triage.request(history=[], detector_flags={"drift": True})

    assert result.success is True
    assert result.fault_type == "drift"
    assert result.severity == "medium"
    assert result.explanation == "The reading has been trending steadily away from setpoint."
    assert result.error is None


def test_missing_tool_call_is_a_failure():
    client = FakeClient([lambda: FakeResponse([FakeTextBlock("I decline to use the tool.")])])
    triage = make_triage(client)

    result = triage.request(history=[], detector_flags={"spike": True})

    assert result.success is False
    assert "did not include a tool call" in result.error
    assert result.fault_type is None


def test_schema_validation_failure_is_a_failure():
    bad_payload = {"likely_fault_type": "not-a-real-type", "severity": "medium", "explanation": "x"}
    client = FakeClient([lambda: FakeResponse([FakeToolUseBlock(bad_payload)])])
    triage = make_triage(client)

    result = triage.request(history=[], detector_flags={"stuck": True})

    assert result.success is False
    assert "did not match expected schema" in result.error


def test_client_exception_is_sanitized_but_logged(caplog):
    def raise_with_sensitive_detail():
        raise ConnectionError("failed to connect to https://internal-service.example/secret-path?token=abc123")

    client = FakeClient([raise_with_sensitive_detail])
    triage = make_triage(client)

    with caplog.at_level("WARNING"):
        result = triage.request(history=[], detector_flags={"spike": True})

    assert result.success is False
    assert result.error == "ConnectionError (see server log for details)"
    assert "token=abc123" not in result.error
    assert "token=abc123" in caplog.text  # full detail still recoverable from the log


def test_no_client_configured_is_an_immediate_failure():
    triage = make_triage(client=None)

    result = triage.request(history=[], detector_flags={"drift": True})

    assert result.success is False
    assert "no Anthropic client" in result.error


def test_prompt_includes_history_and_detector_flags_but_not_ground_truth():
    client = FakeClient([valid_response()])
    triage = make_triage(client)

    history = [{
        "tick": 5, "t_sensed": 301.2, "setpoint": 310.0, "actuator_output": 40.0,
        "active_faults": ["drift"], "interlock_result": "allow", "interlock_reason": "within bounds",
    }]
    triage.request(history=history, detector_flags={"spike": False, "drift": True, "stuck": False})

    call_kwargs = client.calls[0]
    prompt = call_kwargs["messages"][0]["content"]
    assert "tick=5" in prompt
    assert "301.20" in prompt
    assert "'drift': True" in prompt
    # Ground truth (active_faults) must never reach the prompt -- the model
    # should reason from what a real operator would see, not the answer key.
    assert "active_faults" not in prompt
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "provide_fault_triage"}
    assert call_kwargs["timeout"] == 15.0


def test_prompt_includes_interlock_result_and_reason_from_history():
    # backlog item 7: triage is interlock-aware now, not just detector-flag-
    # aware -- confirms the interlock's own decision (not just readings)
    # actually reaches the prompt text.
    client = FakeClient([valid_response()])
    triage = make_triage(client)

    history = [{
        "tick": 42, "t_sensed": 374.0, "setpoint": 323.15, "actuator_output": 0.0,
        "active_faults": [], "interlock_result": "reject",
        "interlock_reason": "sensed temperature at or past T_max -- hard trip, forcing safe output (0.0%) [strike 1/2]",
    }]
    triage.request(history=history, detector_flags={"spike": False, "drift": False, "stuck": False})

    prompt = client.calls[0]["messages"][0]["content"]
    assert "interlock=reject" in prompt
    assert "hard trip" in prompt


def test_triage_schema_accepts_interlock_as_a_fault_type():
    # backlog item 7: likely_fault_type's enum widened to include "interlock"
    # for when the headline story is interlock behavior, not a sensor fault.
    client = FakeClient([valid_response(likely_fault_type="interlock", explanation="Interlock rejected a proposal near the ceiling.")])
    triage = make_triage(client)

    result = triage.request(history=[], detector_flags={"spike": False, "drift": False, "stuck": False})

    assert result.success is True
    assert result.fault_type == "interlock"
