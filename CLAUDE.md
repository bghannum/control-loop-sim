# Control Loop Simulation — project status

Read `README.md` and `docs/control-loop-architecture.md` first — they're the source of truth for design decisions. This file is just a pointer to where things stand.

## Status: Phase 7 (Tier-2 LLM triage) complete and verified — this closes out the doc's original MVP scope. Design work for Phase 8 (Streamlit UI/UX overhaul) and Phase 9 (React/FastAPI frontend split) is done — full mockups exist in `docs/design-prompts/`; implementation for both hasn't started. Docs polish stays last at Phase 10.

Phase 0 scaffolding + prerequisites verified previously (Python 3.12.13, Docker/`timescaledb`, `.env`, `gh`, pytest scaffold).

**Detailed build history for Phases 1-5.5 has moved to `docs/archive/`** — one file per phase, same content as before, just out of this file's default context so `CLAUDE.md` stays focused on current status rather than accumulating an ever-growing changelog (same reasoning that moved the backlog out to `BACKLOG.md` on 2026-08-05). Check there for the full story behind any given phase — implementation details, verification steps, gotchas hit along the way (e.g. the Phase 4 runaway-bug root cause, Phase 5.5's three confirmed design forks):
- `docs/archive/phase-1-plant-and-manual-control.md`
- `docs/archive/phase-2-pid-controller.md`
- `docs/archive/phase-3-sensor-fault-injection.md`
- `docs/archive/phase-4-detector-interlock-historian.md`
- `docs/archive/phase-5-ai-controller.md` (includes the post-Phase-5 hard-trip fix)
- `docs/archive/phase-5.5-interlock-lockout.md`

## Build order (tracked as tasks #1-#10, #1-#7 done)

Follows architecture doc §5, with two adjustments the user explicitly approved:
- **Historian writes deferred to Phase 4**, not wired early — `docker-compose.yml` stands up TimescaleDB as infra now, but the batched async writer (`storage/historian.py`) doesn't get implemented until Phase 4, alongside the interlock's sensor-trust gate. Keeps Phases 1-3 focused on physics/control logic.
- **Tests embedded per phase**, not a separate testing pass at the end — each phase that introduces new logic ships with a small pytest suite of known-outcome scenarios as part of its definition of done (this directly addresses a gap the architecture doc calls out in §10).

Phases: (1) plant + manual control, (2) PID + mode toggle, (3) sensor fault injection, (4) Tier-1 statistical detector + interlock sensor-trust gate + historian wiring, (5) AI controller, (6) interlock bounds/rate-limit checks vs. AI + decision log UI, (7) Tier-2 LLM triage — **this completes the doc's original MVP scope.** Then: (8) Streamlit UI/UX overhaul, (9) FastAPI + React frontend split, (10) README/docs/walkthrough polish.

**2026-08-07 renumbering:** the doc's original §5 numbered (8) as README/docs/walkthrough polish; that's now (10) so it stays last — polishing the walkthrough before the UI it's walking through has changed twice more would just mean rewriting it twice. (8) and (9) are new, user-requested phases, not in the original architecture doc — see `docs/design-prompts/` for the UX briefs written for each before implementation starts. (9) promotes the FastAPI/WebSocket service split from "deferred stretch goal" (doc §9) to a scheduled phase; still deferred/unscheduled: second-order plant model, Redis hot path, Delta Lake alternative, multi-loop interlock demo (doc §9, §11).

## Phase 8 & 9 design (mockups complete, implementation not started)

Both are user-requested phases beyond the original architecture doc's scope. **Design work is genuinely done for both** — reviewed directly, not taken on faith: `docs/design-prompts/` holds a self-contained brief per phase (`.md`) plus the actual output of running that brief through Claude Design — a full interactive HTML mockup (`.dc.html`, ~44KB each), not a stub or a written description. Both mockups render every state the brief asked for, with real (not placeholder) data per state, and share one severity color system (green=nominal/allowed, amber=degraded, red=critical, gray=inactive) applied consistently across the status strip, decision log rows, and telemetry.

**Phase 8 — Streamlit UI/UX overhaul** (`phase-8-streamlit-ui-prompt.md` / `Phase 8 Streamlit Thermal Control UI.dc.html`). Layout-only redesign, no functional change. Problem being solved: today's UI is one narrow column — 20+ stacked controls/metrics/captions of near-identical visual weight — with the decision log (the single most important element per the architecture doc) buried at the very bottom, below the chart. Proposed IA: eight zones (A status strip · B chart · C controller · D fault injection · E session controls · F telemetry tiles · G AI reasoning · H decision log, promoted to a top-level tab beside the chart), a status strip with fixed height so "nominal" is an actual rendered state rather than collapsing to empty space, and mode-switching that doesn't reflow the page. Scoped hard to what Streamlit's real layout primitives can produce (`st.columns`/`st.tabs`/`st.container(border=True)`/`st.metric`/`st.dataframe` + light CSS) — no custom JS, modals, or animated transitions. **Delivered: all 11 requested states**, dark control-room theme, each zone-labeled inline in the mockup.

**Phase 9 — React/FastAPI frontend** (`phase-9-react-frontend-prompt.md` / `Phase 9 React Frontend UI.dc.html`). The unconstrained version of the same problem, once the backend splits into a FastAPI service streaming ticks over a WebSocket. Shares Phase 8's content inventory and color system, but uses freedoms Streamlit doesn't have: sticky panels, toasts for one-shot events (spike fired, lockout engaged), animated state transitions, and — new in this brief — a live WebSocket connection badge (connected/reconnecting/lost), since silently-stale data is a real failure mode worth surfacing on its own. Deliberately distinguishes *system-imposed* critical states (lockout, hard trip, AI fallback) from the *operator-chosen* one (manual override) — same severity tier, visually distinct, since the operator caused one of these on purpose. **Delivered: all 12 requested states** (Phase 8's 11 plus "connection lost"), plus a written implied-primitives legend citing shadcn/ui + Tailwind + Radix for each nonstandard interaction (e.g. toasts via shadcn Sonner, Reset/Reset Interlock as a two-stage button rather than a modal — "fast enough for a live demo, still has a confirm step").

Neither phase's actual implementation has started — these are design deliverables only, ready to hand to a build pass when picked up.

## Phase 6: interlock bounds/rate-limit checks vs. AI + decision log UI

Per the doc's build order (§5, item 6): "add interlock bounds/rate-limit checks against AI proposals specifically, and build the decision log UI... crank AI aggressiveness or inject a fault, watch the interlock override it, and point at the log line as the payoff."

**Nothing new to build.** Both pieces were already fully in place, just not formally closed out under a "Phase 6" label:
- The bounds/margin, hard-trip, and slew-rate checks in `engine/interlock.py` are source-agnostic by construction — `evaluate()`'s `source` param is only ever consulted for manual-override eligibility on the one overridable check. AI proposals already go through the identical gauntlet PID and manual do. This landed in Phase 4 (bounds/slew) and was hardened by the post-Phase-5 hard-trip fix (the ~140°C runaway bug).
- The decision log UI (`app.py`) landed in Phase 4 and was substantially extended in Phase 5.5 (50-row default, full-history toggle, lockout column, severity-ordered banners) — already beyond what the doc's Phase 6 originally asked for.

**Verified live via Playwright** (real API calls, AI mode, default 50°C setpoint, no faults injected) rather than just asserting the above from reading code, since the doc explicitly frames this as a demo moment worth confirming, not just a code property:
- Tick 22-23: AI proposed continued heating while sensed temperature was already at/past `t_max_k` (373.15K/100°C, true temp had overshot to ~103°C via thermal lag, matching the post-Phase-5 fix's documented behavior) — the hard-trip check forced `actuator_output=0.0` regardless of the proposal, logged with reason `"sensed temperature at or past T_max -- hard trip, forcing safe output (0.0%) [strike 1/2]"`.
- Tick 25 (a separate near-boundary moment): the softer margin check independently caught and rejected an AI proposal pushing further toward the ceiling — `"sensed temperature within 5.0K of T_max -- rejecting further increase"`.
- 30 simulated seconds later: actuator held at 0%, sensed/true temperature cleanly declined from the ~103°C peak back down through the 50°C setpoint to ~36°C — confirms the override isn't just a one-tick clamp, the system actually recovers and the AI resumes normal control once back in bounds.

This is the same overshoot-then-correct story documented in `docs/archive/phase-5-ai-controller.md`'s "Post-Phase-5" section, reproduced fresh specifically to confirm it still holds with AI proposals after Phase 5.5's lockout mechanism was layered on top (a new escalation path that could in principle have interfered with the trip's self-clearing behavior — confirmed it didn't: `trip_strikes` sat at 1/2, no lockout, exactly as expected for a single isolated excursion with the AI correcting on its own once the trip forced output down).

No code or test changes from this pass — pure verification of already-shipped behavior. Suite remains at 102/102.

## Phase 7: Tier-2 LLM triage (manual/on-demand)

Per doc §3.5 and §5 item 7: a plain-language, advisory-only explanation of whatever the Tier-1 statistical detector (`engine/detector.py`) currently flags. Genuinely separate from Phase 5's `AIController` — triage never proposes an actuator value and has no path into the interlock at all; its only output is text for a human to read. This closes out the doc's originally-scoped MVP (phases 1-7); phases 8-10 are user-requested additions beyond that scope (see "Build order" above). Full pytest suite: **108/108 passing** (6 new in `tests/test_triage.py`).

### Confirmed decision: manual/on-demand only, for cost control

User's explicit goal was to "show the art of the possible" without uncontrolled API spend. Considered and rejected: auto-triggering once per detector-flag *episode* (an idea directly available from the interlock's existing trip-episode/strike concept) — still an automatic spend the user doesn't directly control. Went with a plain button instead: cost is bounded by how many times it's actually clicked, zero surprise spend from just letting the sim run. This mirrors a precedent already set in Phase 3 — fault *timing* is operator-driven via toggles/a button, not auto-scripted, specifically to keep this a live, presenter-driven demo rather than something that runs itself.

Also confirmed: `Triage.request()` is a **plain synchronous/blocking call** (`st.spinner()` while it runs), not `AIController`'s background-thread/polling pattern. That pattern exists specifically to protect the 0.5s per-tick control loop from a multi-second API call — a problem that doesn't apply to a rare, deliberate, one-shot button click. A several-second pause on click (visibly pausing the live chart if "Run" happens to be on, then resuming) is simpler, standard Streamlit UX with no per-tick deadline to protect.

### `engine/anthropic_support.py` (new)

Extracted from `engine/controllers/ai.py` once a second caller needed the exact same logic: `AnthropicClientLike`/`AnthropicMessagesLike` (`Protocol`s, previously private to `ai.py`) and `summarize_error()` (previously `_summarize_error`) — our own `RuntimeError`/`ValueError` text passes through verbatim to the UI, anything else collapses to just its type name, full exception always still reaches the log. `engine/controllers/ai.py` and `engine/loop.py` now import from here; purely mechanical, no behavior change (existing AI controller tests assert on behavior, not the old private names).

### `engine/triage.py` (new)

`Triage` class: same tool-use pattern as `AIController` (structured output, never free-text-parsed — a pydantic `TriageSchema` validates `likely_fault_type` (enum: spike/drift/stuck/other), `severity` (low/medium/high), `explanation` (plain language)), but `request(history, detector_flags) -> TriageResult` is called directly, synchronously — no thread, no pending-result slot, no dead-man timer. A failed call just returns `TriageResult(success=False, error=...)`; there's no actuator value at stake, so there's nothing to hold or fall back to. The prompt deliberately **excludes `active_faults`** (ground truth) — same reasoning as the AI controller's prompt: the model should reason from what a real operator would see (readings + the Tier-1 flag), not be handed the answer key.

### Config

New `triage:` section in `config.yaml` (`model`, `history_window_ticks`, `max_wait_s`) validated by a new `TriageConfig` in `config_schema.py`.

### `app.py`

`st.session_state.triage` constructed once (reuses the same `ai_client` `AIController` already uses), `st.session_state.last_triage` cleared on Reset (a fresh run shouldn't show a stale explanation from before). A "Triage with Claude" button appears next to the "Detector flags (Tier-1 belief)" caption, **disabled until at least one flag is active** — the button only exists at all once there's at least one tick of history, so it's invisible before the first tick, then disabled-but-visible until a flag fires. On click: `st.spinner`, synchronous `Triage.request()`, result rendered via `st.info` (fault type/severity/explanation) or `st.caption` (sanitized error).

### Tests

Moved `FakeToolUseBlock`/`FakeTextBlock`/`FakeResponse`/`FakeMessages`/`FakeClient` out of `test_ai_controller.py` into `tests/conftest.py` (which already held `FakeClock` for the identical "shared fake, no network, deterministic" reason) — both `test_ai_controller.py` and the new `tests/test_triage.py` now import the same fakes. `tests/test_triage.py`: 6 known-outcome scenarios mirroring `test_ai_controller.py`'s failure-mode coverage (missing tool call, schema validation failure, client exception sanitized-but-logged, no client configured) minus threading concerns, plus a test confirming the prompt carries history/flags but never `active_faults`.

### Verified two ways

1. **Live against the real API** (scratch script, synthetic stuck-sensor history, no faults toggled in the running app): returned in 4.79s, correctly identified `fault_type="stuck"` with a sensible plain-language explanation referencing the exact frozen value.
2. **Live in the browser via Playwright**, real API calls: confirmed the button is genuinely absent before the first tick, present-but-disabled with no flag active, and enabled once Manual mode + the stuck-at fault produced a real detector flag (~30s in, past `boot_grace_ticks`) — then clicking it returned `"likely stuck (severity: high) — The temperature reading has stayed frozen at exactly 293.15K for 20 straight readings..."`, correctly reasoning from the sensed-value plateau visible in the chart.

## Code review

A Gemini-authored code review lives in `CODE_REVIEW.md` (untracked, updated in place across passes rather than replaced — see its own disposition key). As of the 2026-08-07 pass: two real, independently-verified findings are queued in `BACKLOG.md` (item 8: a genuine boot-grace/reset_interlock() safety gap; and G.1's `CLAUDE.md` archiving, which this restructuring itself just addressed). Everything else from that pass was either already fixed in an earlier round or reviewed and found not applicable (with rationale recorded inline in `CODE_REVIEW.md`) — several performance-related findings were checked empirically (measured, not assumed) before being dismissed.

## Backlog

Planned enhancements not yet scheduled into a build-order phase live in `BACKLOG.md`, not here — check there before starting new interlock/UI work. Moved out of this file 2026-08-05 so `CLAUDE.md` stays focused on current status rather than accumulating an ever-growing list.
