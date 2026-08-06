"""Known-outcome scenarios for AIController (Phase 5), against a fake,
injectable Anthropic client -- no network calls, no cost, fully
deterministic. Covers the three failure modes from doc §3.6 (bad/missing
client, exception, malformed response), the non-blocking hold-while-
pending behavior from §3.3.1, and the single-flight threading guarantee.
See docs/control-loop-architecture.md §3.3, §3.6.
"""

import threading

import pytest

from engine.controllers.ai import AIController


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_dict):
        self.input = input_dict


class FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeMessages:
    def __init__(self, client):
        self._client = client

    def create(self, **kwargs):
        return self._client._create(**kwargs)


class FakeClient:
    """behaviors: list of callables (return a FakeResponse or raise) consumed
    one per call, in order."""

    def __init__(self, behaviors):
        self.messages = FakeMessages(self)
        self._behaviors = list(behaviors)
        self.calls: list[dict] = []

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        behavior = self._behaviors.pop(0)
        return behavior()


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def valid_response(**overrides):
    payload = {
        "proposed_output_pct": 42.0,
        "confidence": "high",
        "rationale": "Reading trending toward setpoint.",
        "flagged_sensor_concern": False,
    }
    payload.update(overrides)
    return lambda: FakeResponse([FakeToolUseBlock(payload)])


def make_controller(client, clock=None):
    return AIController(
        client=client,
        model="claude-sonnet-5",
        history_window_ticks=20,
        max_response_wait_s=10.0,
        clock=clock or FakeClock(),
    )


def wait_for_idle(controller: AIController, timeout: float = 2.0) -> None:
    if controller._thread is not None:
        controller._thread.join(timeout=timeout)


def test_successful_proposal_is_committed_on_next_propose():
    client = FakeClient([valid_response()])
    controller = make_controller(client)

    controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})
    wait_for_idle(controller)
    action = controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})

    assert action.source == "ai"
    assert action.proposed_output_pct == pytest.approx(42.0)
    assert action.confidence == "high"
    assert action.rationale == "Reading trending toward setpoint."
    assert action.flagged_sensor_concern is False
    assert action.metadata["waiting"] is False
    assert action.metadata["last_error"] is None


def test_holds_last_value_while_a_call_is_pending():
    release = threading.Event()

    def blocking_response():
        release.wait(timeout=2.0)
        return FakeResponse([FakeToolUseBlock({
            "proposed_output_pct": 77.0, "confidence": "low", "rationale": "x", "flagged_sensor_concern": False,
        })])

    client = FakeClient([blocking_response])
    controller = make_controller(client)

    first = controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})
    assert first.proposed_output_pct == 0.0  # initial held value
    assert first.metadata["waiting"] is True

    second = controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})
    assert second.proposed_output_pct == 0.0  # still held -- call not resolved yet
    assert second.metadata["waiting"] is True

    release.set()
    wait_for_idle(controller)
    third = controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})
    assert third.proposed_output_pct == pytest.approx(77.0)
    assert third.metadata["waiting"] is False


def test_missing_tool_call_is_a_failure_and_does_not_commit():
    client = FakeClient([lambda: FakeResponse([FakeTextBlock("I decline to use the tool.")])])
    controller = make_controller(client)

    controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})
    wait_for_idle(controller)
    action = controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})

    assert action.proposed_output_pct == 0.0  # unchanged
    assert "did not include a tool call" in action.metadata["last_error"]


def test_schema_validation_failure_is_a_failure_and_does_not_commit():
    bad_payload = {"proposed_output_pct": "not-a-number", "confidence": "high", "rationale": "x", "flagged_sensor_concern": False}
    client = FakeClient([lambda: FakeResponse([FakeToolUseBlock(bad_payload)])])
    controller = make_controller(client)

    controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})
    wait_for_idle(controller)
    action = controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})

    assert action.proposed_output_pct == 0.0
    assert "did not match expected schema" in action.metadata["last_error"]


def test_client_exception_is_a_failure_and_does_not_commit():
    def raise_network_error():
        raise ConnectionError("connection reset")

    client = FakeClient([raise_network_error])
    controller = make_controller(client)

    controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})
    wait_for_idle(controller)
    action = controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})

    assert action.proposed_output_pct == 0.0
    assert "connection reset" in action.metadata["last_error"]


def test_no_client_configured_is_an_immediate_failure():
    controller = make_controller(client=None)

    controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})
    wait_for_idle(controller)
    action = controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})

    assert action.proposed_output_pct == 0.0
    assert "no Anthropic client" in action.metadata["last_error"]


def test_only_one_call_in_flight_at_a_time():
    release = threading.Event()

    def blocking_response():
        release.wait(timeout=2.0)
        return FakeResponse([FakeToolUseBlock({
            "proposed_output_pct": 1.0, "confidence": "low", "rationale": "x", "flagged_sensor_concern": False,
        })])

    client = FakeClient([blocking_response])
    controller = make_controller(client)

    for _ in range(5):  # several propose() calls while the first is still pending
        controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})

    assert len(client.calls) == 1  # only the first one actually started a call
    release.set()
    wait_for_idle(controller)


def test_seconds_since_last_success_uses_injected_clock_not_real_time():
    clock = FakeClock(start=1000.0)
    client = FakeClient([valid_response()])
    controller = make_controller(client, clock=clock)

    controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})
    wait_for_idle(controller)
    controller.propose(reading=300.0, setpoint=310.0, history=[], detector_flags={})  # consumes success, resets timer

    clock.advance(37.5)
    assert controller.seconds_since_last_success() == pytest.approx(37.5)


def test_reset_restarts_clock_and_clears_pending_result():
    clock = FakeClock(start=1000.0)
    client = FakeClient([valid_response()])
    controller = make_controller(client, clock=clock)

    clock.advance(500.0)
    controller.reset()

    assert controller.seconds_since_last_success() == pytest.approx(0.0)


def test_prompt_includes_reading_setpoint_history_and_detector_flags():
    client = FakeClient([valid_response()])
    controller = make_controller(client)

    history = [{"tick": 5, "t_sensed": 301.2, "setpoint": 310.0, "actuator_output": 40.0}]
    controller.propose(
        reading=305.5, setpoint=310.0, history=history, detector_flags={"spike": False, "drift": True, "stuck": False}
    )
    wait_for_idle(controller)

    call_kwargs = client.calls[0]
    prompt = call_kwargs["messages"][0]["content"]
    assert "305.50" in prompt
    assert "310.00" in prompt
    assert "'drift': True" in prompt
    assert "tick=5" in prompt
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "propose_heater_output"}
