"""Shared test helpers. Not a pytest fixture module in the usual sense --
these are plain classes imported directly (e.g. `from tests.conftest import
FakeClock`) by test files that need them.

FakeClock simulates elapsed time without real sleeping (Interlock and
AIController both take an injectable `clock` callable for exactly this
reason). FakeToolUseBlock/FakeTextBlock/FakeResponse/FakeMessages/FakeClient
are a fake Anthropic client (no network, no cost, deterministic) shared by
every Claude-API-calling module's tests -- AIController (test_ai_controller.py)
and Triage (test_triage.py) both use the exact same shape.
"""


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


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
    one per call, in order. Once exhausted, the last one repeats -- useful
    for AIController, whose propose() eagerly starts a new background call
    right after consuming any result (so the AI is always working on the
    next decision, by design); a test that only cares about a single
    specific result would otherwise see that eager follow-up call hit an
    empty queue and raise IndexError. Triage's request() is a single
    synchronous call, so this repeat-last behavior is simply unused there."""

    def __init__(self, behaviors):
        self.messages = FakeMessages(self)
        self._behaviors = list(behaviors)
        self.calls: list[dict] = []

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        behavior = self._behaviors.pop(0) if len(self._behaviors) > 1 else self._behaviors[0]
        return behavior()
