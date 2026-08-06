"""Shared test helpers. Not a pytest fixture module in the usual sense --
FakeClock is a plain class imported directly (`from tests.conftest import
FakeClock`) by test files that need to simulate elapsed time without real
sleeping (Interlock and AIController both take an injectable `clock`
callable for exactly this reason).
"""


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
