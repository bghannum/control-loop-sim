# Phase 5: AI controller (Claude)

Archived detailed build write-up — moved out of `CLAUDE.md` on 2026-08-07 to keep that file focused on current status. See `../../CLAUDE.md` for where the project stands now. Includes the post-Phase-5 hard-trip fix (a follow-on bug found via live testing right after this phase shipped).

---

Full pytest suite: **82/82 passing** (10 new `test_ai_controller.py`, 4 new `ControlLoop` integration tests in `test_control_loop.py`). Plus a live, real-API integration check (below) and a live Playwright run that made genuine Claude API calls end to end.

## Structured output: tool-use, not prompt-and-parse

Doc §3.6 lists "malformed JSON" as a failure mode to handle, which suggests asking the model for JSON in free text and parsing the result — fragile by construction. Used Anthropic's tool-use API instead (`tool_choice={"type": "tool", "name": "propose_heater_output"}`), which makes syntactically-invalid JSON structurally impossible, plus a pydantic model (`AIProposalSchema`) validating the *semantic* shape on top (right types, right enum values). "Malformed response" as a failure case still fully exists and is still explicitly tested — it just means "no tool call" or "failed validation" now, never a JSON parse error. Same doc-specified behavior, more robust implementation.

## Real async execution, not a blocking call (§3.3.1)

A synchronous API call (confirmed live: ~4s) would freeze the whole Streamlit script for several seconds every tick, directly violating "hold last value while a call is in flight, don't block." `AIController` runs each call in a background daemon thread (same pattern as the historian's writer thread) — `propose()` always returns immediately: either a freshly-arrived decision, or the last-committed value while a call is still in flight. Only one call is ever in flight at a time (guarded by checking `thread.is_alive()` before starting a new one). Thread-safe handoff via a lock-guarded "pending result" slot, not a full queue, since there's only ever one producer and one consumer.

## Interface change: `Controller.propose()` gains `detector_flags`

Doc §3.3 explicitly wants the AI's prompt to include "the current reading, setpoint, recent history window, and detector flag." There was no clean channel for the detector flag under the old 3-arg signature, so the shared interface grew a 4th parameter. Manual/PID ignore it (same as they already ignore `history`) — this is why every existing direct `.propose(...)` call in the test suite needed updating (mechanical, not a design change to those controllers).

## `ControlLoop` now keeps its own history

It didn't before — only the UI's `st.session_state.history` existed. Added a bounded `deque` (sized from `ai.history_window_ticks`) so the AI controller has something to look at; Manual/PID still ignore it.

## Failure handling (§3.6) — three stages, split across two objects

`AIController` tracks `seconds_since_last_success()` (via an **injectable clock**, so tests never need to actually sleep) but doesn't act on it — it only reports. `ControlLoop.tick()` does the acting: past `max_response_wait_s` (10s), the UI shows a countdown warning; past `max_response_wait_s + fallback_after_s` (10s more, total 20s — the doc doesn't give an exact number for the second stage, this is a documented interpretation), `ControlLoop` substitutes `ai.safe_output_pct` (0.0 — no active cooling in this system, off is safe) for that tick's proposal, still passed through the interlock like any other proposal, logged via a new `ai_fallback_active` record field (additive, same pattern as `override_active`/`setpoint`). **Kept `controller_source="ai"` during fallback** rather than silently relabeling it "manual" — it's still nominally AI mode, the system is substituting a value on AI's behalf, not secretly changing modes out from under the UI's own mode selector (which keeps re-asserting whatever the radio button says on every rerun — a genuine mode *switch* here would just get immediately overwritten by that, so the fallback is computed fresh each tick from elapsed time instead of being a persistent state flip).

## Testability

Both the Anthropic client and the clock are constructor-injectable. Tests use a small fake client (`FakeClient`/`FakeMessages`/`FakeToolUseBlock`) returning canned responses — success, no tool call, failed validation, a raised exception — plus a `threading.Event`-gated fake response to deterministically test the "hold while pending" behavior without real timing races. No test hits the real network.

## Verified against the real API

A scratch script constructed a real `anthropic.Anthropic` client (key already in `.env`) and called `AIController.propose()` directly: returned in 0.001s (non-blocking confirmed), the real call took 4.10s, and Claude's actual response was well-formed and sensibly reasoned ("Temperature is rising steadily... avoiding overshoot").

## Verified visually via Playwright (real API calls, not mocked)

AI mode screenshot after ~25s shows genuinely intelligent reasoning in the rationale field: the plant overshot to ~140°C (more than PID's tuned response), and the AI correctly diagnosed *why* ("still near peak despite actuator already being ramped down... system overshot significantly due to thermal lag; heater should be fully off... only reintroduced once temperature trends back down") and proposed heater=0% accordingly. Decision log confirms `controller_source=ai` flowing correctly through the interlock (`allow`/"within bounds"). The AI-vs-PID overshoot difference is itself a legitimate, interesting finding — exactly the comparison this whole project exists to enable, per doc §1's primary goal.

## Post-Phase-5: interlock hard over/under-temperature trip

User watched the AI-mode overshoot above happen live and asked why the interlock didn't stop it. Root cause: the existing margin check (§3.4's `bound_margin_k` rule) only blocks a proposal that pushes *further toward* a bound — it has no mechanism to force a decrease. Once the AI itself started reducing output, every subsequent proposal was a decrease, which that rule never touches, so the interlock had nothing left to block while the plant coasted (via thermal lag) well past `t_max_k` (373.15K/100°C) up to ~413K.

**Fix:** a new check 2 in `engine/interlock.py` (renumbering the rest), inserted between the sensor-trust gate and the margin check — a genuine "high-high" trip to the margin check's "high" alarm. Once `t_sensed` is actually at or past `t_max_k`/`t_min_k` (not just within margin), force `interlock.trip_safe_output_pct` (0.0 — no active cooling, off is safe) regardless of what's proposed or which direction, **absolute, no override** (user explicitly confirmed this choice over manual-overridable), and **bypasses the slew limit** — an emergency trip has to reach the safe value immediately, not get rate-limited like routine control. Symmetric floor-side trip forces 100% instead (correct direction for "too cold"), though it's practically unreachable given this system's physics (no active cooling, ambient sits well above `t_min_k`) — included so the interlock is honestly symmetric rather than silently one-sided.

22 known-outcome tests in `test_interlock.py` now (6 new), including: fires on a decrease proposal (the whole point — margin check wouldn't), can't be overridden even with override requested, bypasses slew, floor case forces max heat, boundary case just below the threshold still uses the softer margin path, and sensor-untrusted still takes priority when both conditions are true simultaneously. 88/88 total passing.

**Verified live:** re-ran the exact same AI-mode scenario that originally overshot to ~140°C. This time it capped at ~103°C (376K peak per the AI's own rationale, one tick of thermal lag past the 373.15K trip point) and cleanly declined back toward setpoint — the fix visibly working, not just passing in tests.

**Note:** this is a different mechanism from Phase 5.5 backlog item 3 (auto-safe-default after *sustained interlock rejection*, regardless of cause) — this new trip fires on the sensed *temperature value* itself, independent of how long anything's been rejecting. They're complementary, not overlapping.
