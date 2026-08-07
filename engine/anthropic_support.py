"""Small pieces shared by every Claude API integration in this project
(AIController in Phase 5, Triage in Phase 7): a structurally-typed client
Protocol and a UI-safe error summarizer. Extracted here once a second
caller needed the exact same logic, not duplicated a second time.
"""

from typing import Any, Protocol


class AnthropicMessagesLike(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class AnthropicClientLike(Protocol):
    """Structural shape of the only part of the Anthropic client actually
    used here: `.messages.create(...)`. Lets `client` be meaningfully typed
    (IDE/mypy support) without hard-depending on the real `anthropic`
    package's concrete class -- the fake client used in tests satisfies
    this structurally, no inheritance needed, since Protocol matching is
    duck-typed."""

    messages: AnthropicMessagesLike


def summarize_error(exc: Exception) -> str:
    """A short, UI-safe summary. Our own raised RuntimeError/ValueError
    messages are already descriptive and contain nothing sensitive, so
    those are shown in full; anything else (network/API client errors,
    whose text we don't control) is reduced to just its type name --
    the full exception is always logged separately, with a traceback."""
    if isinstance(exc, (RuntimeError, ValueError)):
        return str(exc)
    return f"{type(exc).__name__} (see server log for details)"
