# Control Loop Simulation — project status

Read `README.md` and `docs/control-loop-architecture.md` first — they're the source of truth for design decisions. This file is just a pointer to where things stand.

## Status: Phase 8 (Streamlit UI/UX overhaul) implemented and verified, plus backlog items 7 and 8 shipped on top of it. Phase 9 (React/FastAPI frontend split) UI design is done, and it's now split into 9a/9b/9c — **9a (FastAPI backend) is implemented and verified**, live and via tests. 9b (minimal frontend) and 9c (full UI) are not started. Docs polish stays last at Phase 10.

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

**2026-08-08: Phase 9 split into 9a/9b/9c.** Scoped and walked through with the user before any code — same "small, demoable increments" instinct as the original build order, applied to a phase big enough to need it (a real backend/frontend split, not a reflow like Phase 8 was). Three confirmed decisions, all recorded here since they shape every sub-phase:
- **Streamlit stays.** The new stack is a second interface sharing `engine`/`storage`, not a replacement for `app.py` — keeps the Phase 8 investment and the "same system, two ways" comparison.
- **Local-only, like the rest of the project.** No hosting story, no Dockerfile, no auth stubs for this phase — `uvicorn` + `npm run dev` side by side locally is the whole deployment story for now.
- **Vite + React + TypeScript, not Next.js**, for 9b/9c. Next's two headline features (file-based routing, SSR) have no use here — this is one page, and nothing benefits from server-rendering a value that changes twice a second. Next would functionally become a client-only SPA anyway, which reads worse in a portfolio piece than picking the tool that actually fits.

**(9a) FastAPI backend — implemented and verified.** Wraps the existing `ControlLoop` in `SimulationService` (`backend/service.py`) with its own background tick loop (an `asyncio.Task` started via `POST /session/run`, running independently of any browser connection, unlike today's Streamlit-rerun-driven ticking — starts paused, matching `app.py`'s own default) plus a WebSocket stream and REST control endpoints. Built from the detailed plan at `docs/phase-9a-backend-plan.md`, which was reviewed before implementation and trimmed from three proposed resilience additions to two (see that doc's "Resilience notes for `_tick_loop`" section) — a third, concurrent WebSocket broadcast via `asyncio.gather`, was cut as solving for a multi-client scenario outside this project's single-operator scope.

- `backend/schemas.py` — Pydantic boundary models (`TickRecord`/`ProposedActionOut` plus one request model per control action), same role `config_schema.py` plays for `config.yaml`.
- `backend/service.py` — `SimulationService`: owns one `ControlLoop` + `Triage`, buffers the manual heater percentage (the one piece of state `ControlLoop.tick()` takes as a direct arg rather than a setter), and runs `_tick_loop`. The two kept resilience additions are both in `_tick_loop`/`shutdown`: an unhandled exception is logged and the loop continues rather than silently dying (this loop running independently is the entire point of 9a — a serialization glitch permanently halting it with no signal would defeat that), and `asyncio.CancelledError` is caught cleanly on shutdown rather than surfacing a stack trace on every `uvicorn --reload`.
- `backend/routers/control.py` / `backend/routers/stream.py` — REST control surface (one endpoint per `app.py` control, thin pass-throughs) and `WS /ws/ticks` (new-ticks-only; a reconnecting client calls `GET /state` for backlog first).
- `backend/main.py` — `FastAPI()` app, CORS for the Vite dev origin (`localhost:5173`), `lifespan` constructs one `SimulationService` on boot and calls `shutdown()` on exit.
- `requirements-backend.txt` — fastapi, uvicorn[standard], websockets, httpx — separate from `requirements.txt` so Streamlit-only use doesn't pull in a web framework.

**Verified two ways:**
1. `pytest -q`: **134/134** (21 new — `tests/test_backend_service.py` unit-tests `SimulationService` directly including the exception-shielding and clean-cancellation behavior with a flaky fake `tick()`; `tests/test_backend_control_api.py` POSTs every control endpoint via `TestClient` and asserts `service.loop`'s actual state changed; `tests/test_backend_stream_api.py` uses `TestClient`'s `websocket_connect()`).
2. Live: `uvicorn backend.main:app`, `GET /state` confirmed empty/paused at boot, `POST /control/mode` + `/control/setpoint` + `/session/run {"running": true}` confirmed via a follow-up `GET /state` (mode/setpoint changed, tick count growing, a real PID proposal correctly slew-clamped by the interlock), a raw Python `websockets` client received live ticks matching the same shape, `/session/run {"running": false}` stopped it — clean startup/shutdown log, no tracebacks.

**(9b) Minimal frontend** — Vite/React scaffold: connect to the tick WebSocket (with real reconnect handling — natively `WebSocket` doesn't auto-reconnect), a connection badge, one basic chart, one control action wired end-to-end. Proves the plumbing before investing in the full UI. Not started.
**(9c) Full UI build** — the reviewed 12-state mockup, for real: shadcn/ui components (its CLI copies component source into the repo — not a typical npm install), toasts derived by diffing consecutive tick records for discrete events (no new backend channel needed, same "derive from existing data" instinct as Phase 8's decision-log coloring), sticky panels, animated transitions. Not started.

## Phase 9c's UI design (mockup complete, implementation not started)

Covers 9c specifically (see the sub-phase breakdown above for 9a/9b). User-requested phase beyond the original architecture doc's scope, same status as Phase 8's design was before it got built. `docs/design-prompts/phase-9-react-frontend-prompt.md` / `Phase 9 React Frontend UI.dc.html`. **Design work is genuinely done** — reviewed directly, not taken on faith: a full interactive HTML mockup (~44KB), not a stub. The unconstrained version of Phase 8's problem, once the backend splits into a FastAPI service streaming ticks over a WebSocket. Shares Phase 8's content inventory and severity color system (green=nominal/allowed, amber=degraded, red=critical, gray=inactive), but uses freedoms Streamlit doesn't have: sticky panels, toasts for one-shot events (spike fired, lockout engaged), animated state transitions, and a live WebSocket connection badge (connected/reconnecting/lost), since silently-stale data is a real failure mode worth surfacing on its own. Deliberately distinguishes *system-imposed* critical states (lockout, hard trip, AI fallback) from the *operator-chosen* one (manual override) — same severity tier, visually distinct, since the operator caused one of these on purpose. **Delivered: all 12 requested states** (Idle, Manual/PID/AI nominal, AI degraded, AI fallback, sensor fault, reject/clamp, hard trip, locked out, manual override, plus "connection lost"), plus a written implied-primitives legend citing shadcn/ui + Tailwind + Radix for each nonstandard interaction (e.g. toasts via shadcn Sonner, Reset/Reset Interlock as a two-stage button rather than a modal). Implementation not started — ready to hand to a build pass when 9c is picked up.

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

## Phase 8: Streamlit UI/UX overhaul

Layout/visual redesign only — no change to `engine/`'s control or safety logic. Translates the reviewed mockup (`docs/design-prompts/Phase 8 Streamlit Thermal Control UI.dc.html`, all 11 states delivered) into real Streamlit code: `app.py`'s single narrow column of 20+ stacked controls/metrics/captions is now three bordered cards (Controller / Fault injection / Session) in a left rail, plus a right-side `st.tabs(["Live", "Decision Log"])` split that promotes the decision log — "the single most important element in the whole UI" per the architecture doc — off the very bottom of the page and onto a tab beside the chart. A `Detector.reset(skip_boot_grace=True)`-shaped decision wasn't needed here (that's backlog item 8, a separate fix); this phase touched only presentation.

### Zone A — status strip, now never empty

The old banner was an `st.empty()` placeholder that collapsed to zero height with nothing to show — the page visibly jumped every time an alert fired or cleared, and "nominal" had no visual presence at all. Replaced with an always-rendered colored strip (`render_status_strip()`); nominal is now a real green "SYSTEM NOMINAL" state.

**New severity tier, faithful to the mockup's state 9 ("hard trip firing"), not in the original banner logic:** the old banner only checked `interlock_locked_out` / `override_active` / `ai_fallback_active` — a single hard-trip tick that hadn't yet escalated to a lockout showed *nothing*, exactly the "silence isn't a calm state" problem the design brief calls out. Detected from the existing `interlock_reason` text (`"...hard trip, forcing safe output..."`, already written by `engine/interlock.py` — no new schema field). Priority order: locked out > hard trip firing > override active > AI fallback active > nominal. Hard-trip and override never coincide (interlock.py's check ordering returns from the hard-trip check before the override-eligible check runs), so no ambiguity with the existing tiers.

### Zones C/D/E — left rail, grouped by role instead of one undifferentiated stack

Three `st.container(border=True)` cards. **Design goal ("mode switch shouldn't resize the panel"):** the mode-specific input block (heater+override slider / Kp-Ki-Kd / AI status line — different lengths per mode) is wrapped in `st.container(height=170)`, a real fixed-height Streamlit primitive, not a CSS hack. Verified directly, not assumed: tracked the Y position of the "Fault injection" heading across Manual → PID → AI switches via Playwright — identical pixel position (734.375) in all three modes.

### Zone F — telemetry tiles

Replaced the vertical `st.metric` + loose-caption stack with a 7-tile row (`render_tile_row()`), each with a severity dot derived from existing fields (no new schema): sensed temp / active faults / detector flags red when a fault or flag is present; historian green when connected, gray (not red) when unavailable, matching its existing "not blocking" framing; trip strikes green at 0, amber above 0, red at/past the lockout threshold. The old "Historian: connected" and "Interlock trip strikes: N/M" captions are gone — folded into their tiles instead.

### Zone G — AI reasoning panel

Own `st.container(border=True)` (`render_ai_panel()`), replacing five stacked captions (confidence/rationale/sensor-concern/error/countdown). Lives in the right column's Live tab, so its appearance/disappearance across mode switches never touches the left rail — the two-column split protects that independently of Zone C's fixed-height container.

### Zone H — decision log, promoted, and a real bug caught during verification

Moved into the `st.tabs(["Live", "Decision Log"])` split per the mockup's own suggested resolution. First implementation used a pandas `Styler` (`.apply(axis=1)`) passed into `st.dataframe` for row-severity coloring — **this rendered as a corrupted solid-color block for most rows**, confirmed via Playwright screenshot across repeated runs, not a one-off screenshot-timing artifact. Root cause not fully diagnosed (a Glide-Data-Grid/canvas incompatibility with per-row custom CSS backgrounds in the installed Streamlit version, 1.61.0, is the leading theory) — rather than debug further, replaced it with a hand-built HTML table via `st.markdown(unsafe_allow_html=True)` (`render_decision_log_table()`), which is arguably more faithful anyway: the reviewed mockup itself is hand-built HTML/CSS, not a real grid widget. Re-verified clean after the fix. **Worth remembering as a general pattern for this codebase: `st.dataframe` + a pandas `Styler` for row-level background coloring is not reliable here — use a hand-built HTML table via `st.markdown` instead.**

Also caught and fixed during the same pass: the initial severity heuristic (red for lockout/override/hard-trip, amber for clamp/reject, else transparent) left "sensor untrusted, holding at last-known-good" rows uncolored, because that state's `interlock_result` is `allow` (the proposal matched the held value) even though it's a genuinely degraded state — added `"untrusted" in reason` as a second amber trigger.

Also folded in `BACKLOG.md` item 6 here, since this call site was being rewritten anyway: `use_container_width=True` → `width="stretch"`.

### A second correctness fix, found while restructuring, not in the original design brief

The old script order rendered the left-column metrics *before* that rerun's `tick()` call (at the very end of the script) — so on any given rerun, the chart/banner reflected the freshly-ticked data while the left-column metrics were one rerun (0.5s) stale. Harmless at that cadence, but a real inconsistency, and the Phase 8 rewrite touches exactly this code. Moved `tick()` to run immediately after the control setters, before any zone renders — every zone in a given rerun now reflects the exact same tick.

### Verified live via Playwright (four passes: initial build, the dataframe-corruption catch, the fix, and a final confirmation)

- Idle state: status strip shows real "SYSTEM NOMINAL" content, not blank space.
- Manual → PID → AI switching: left rail height provably stable (see Zone C above).
- Stuck-at fault (Manual mode): tiles turn red, status strip correctly stays nominal (a single hold isn't itself an alert, matching mockup state 8), decision log shows the "sensor untrusted" rows amber-tinted.
- AI mode, default setpoint, left to overshoot (the same scenario from Phase 6's verification): caught the hard-trip banner tier live (red "HARD TRIP" chip, `102.8°C` true / `103.1°C` sensed / `0%` actuator, `1/2` trip strikes) — a genuinely narrow window since the trip self-clears within a tick or two, needed 800ms polling to catch cleanly. Decision log for that run shows the exact expected color sequence: amber clamp rows (slew-limited ramp-up) → red hard-trip rows (strike 1/2) → amber reject rows (margin check on the way back down) → amber clamp (recovery ramp).
- Zero browser console errors across all passes.
- `pytest -q`: 108/108 (untouched — nothing in `engine`/`storage` changed).

## Backlog items 7 & 8: interlock-aware triage + boot-grace fix

Both closed together right after Phase 8. Full pytest suite: **113/113 passing** (5 new). No new subsystems, no tick-record schema changes — both are fixes to existing mechanisms.

### Item 8: `reset_interlock()` no longer buys a still-active fault 25s of silence

The real bug from the Gemini review (`CODE_REVIEW.md` finding H.1): `Detector.reset()` always re-armed the full `boot_grace_ticks` (50 ticks / 25s) countdown, during which the detector reports no flags at all *regardless of what's actually happening* — correct after a genuine cold start (masks a legitimate startup transient), wrong after an operator manually clicks "Reset Interlock," since that isn't a cold start and there's no legitimate transient to mask. If the operator reset without also disabling an active fault toggle, the detector would silently sit out the next 25 seconds.

**Fix:** `Detector.reset(skip_boot_grace: bool = False)` — when `True`, `_ticks_seen` is set to `boot_grace_ticks` (grace counted as already elapsed) instead of `0`, while still clearing the window/CUSUM state for a genuinely fresh statistical baseline. `ControlLoop.reset_interlock()` is the only caller that passes `skip_boot_grace=True`; `set_setpoint()`'s reset (a real setpoint jump) and a fresh `ControlLoop` instance both keep full grace, since those are exactly the transient-masking scenarios grace exists for.

**Verified live:** heater pinned at 100% (Manual mode) until the interlock genuinely locked out from repeated hard trips, enabled the stuck-at fault *while locked out*, then pressed "Reset Interlock" without disabling it — the `stuck` flag reappeared in the Detector flags tile in **0.5 seconds** (one tick), not the old 25-second silence.

### Item 7: triage is interlock-aware now, one combined button

Phase 7's "Triage with Claude" only ever saw sensor readings + the current detector flags — no visibility into what the interlock itself had been doing. Confirmed with the user before building: **one combined button**, not two — a sensor fault and the interlock's reaction to it are usually the same incident, so one narration beats forcing the operator to piece two together.

- `engine/triage.py`'s `_build_prompt()` now includes each history row's `interlock_result`/`interlock_reason` — these were already present on every record `app.py` passes in (the UI's full per-tick history, not the stripped-down shape `AIController`'s own prompt uses), just not previously read here. No new data plumbing, just reading what was already there.
- `TOOL_SCHEMA`/`TriageSchema`'s `likely_fault_type` enum widened from `[spike, drift, stuck, other]` to add `interlock` — deliberately *not* one enum value per interlock reason (hard-trip vs. lockout vs. margin-reject vs. override); a single tick can involve more than one, and the free-text `explanation` field is where that specific narrative belongs. The enum only answers "sensor fault or interlock event."
- `app.py`'s trigger condition broadened: the button now lights up on a live detector flag *or* any non-`allow` interlock result in the same history window sent to the prompt (previously detector-flag-only).

**Verified live with the real API, two ways:**
1. A synthetic-history scratch check (zero detector flags, pure margin-reject → hard-trip sequence) returned `fault_type="interlock", severity="high"`, correctly narrating it as "a genuine overheat trip (not a sensor glitch)... close to a full lockout."
2. Live in the running app: pinned heater at 100% with **no fault toggled at all** — the button lit up purely from routine slew-rate clamping (no detector flag, no hard trip, just the interlock pacing a fast ramp-up) and Claude correctly characterized it as `severity="low"`, explicitly normal behavior, not a fault — a good sign the combined prompt isn't crying wolf on routine interlock activity.

## Code review

A Gemini-authored code review lives in `CODE_REVIEW.md` (untracked, updated in place across passes rather than replaced — see its own disposition key). Both of its remaining open findings (H.1 the boot-grace gap, G.1 the `CLAUDE.md` archive) are now closed — see Phase 8 and "Backlog items 7 & 8" above. Everything else from that pass was either already fixed in an earlier round or reviewed and found not applicable (with rationale recorded inline in `CODE_REVIEW.md`) — several performance-related findings were checked empirically (measured, not assumed) before being dismissed.

## Backlog

Planned enhancements not yet scheduled into a build-order phase live in `BACKLOG.md`, not here — check there before starting new interlock/UI work. Moved out of this file 2026-08-05 so `CLAUDE.md` stays focused on current status rather than accumulating an ever-growing list.
