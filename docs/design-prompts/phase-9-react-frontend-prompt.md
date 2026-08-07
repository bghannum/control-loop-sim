# Design prompt — Phase 9: React/FastAPI frontend

Paste this whole document to Claude Design. It's a self-contained brief. It shares its project context and content inventory with the Phase 8 Streamlit brief (`phase-8-streamlit-ui-prompt.md`) — this one is the *unconstrained* version: same problem, no Streamlit ceiling.

## What you're designing

A ground-up frontend for the same app, once the backend is split out into a FastAPI service (streaming live ticks over a WebSocket) with a custom frontend as its only client. Unlike Phase 8, this is not a reflow of existing widgets — every visual element is being built from scratch, so use real interaction design: modals, toasts, live-connection state, animated transitions, whatever earns its place. Don't reuse Phase 8's mockups as a starting point beyond the shared content — this should feel like what the UI *should* be if nothing about Streamlit constrained it, not a themed version of the same layout.

## Project context

Same project as the Phase 8 brief: a simulated thermal control loop drivable by a human, PID, or an AI controller (Claude), all mediated by a hard-coded safety interlock that can reject, clamp, or force-override any proposed command from any source. The core story the UI exists to tell: **"AI proposes, a deterministic interlock disposes"** — the interlock is never AI-driven and can override the AI (or a human) at any time. An operator should be able to look at the screen and immediately know what's controlling the plant, whether a fault is active, and whether the safety layer has intervened.

The single most important element, per the project's own design doc, is the **decision log** — a running record of every interlock evaluation (allowed / clamped / rejected / overridden, with a reason).

## Who uses this, and when

Still one operator, one session — no auth, no multi-tenancy, no concurrent users to design for; don't build account/permissions UI. Two contexts:

1. **Live, presenter-driven demo** (e.g., a job interview): narrated while toggling modes, injecting faults, and pointing at the interlock's response. Likely shared/projected.
2. **Solo exploration** at a laptop, watching values move tick to tick.

Primary target: widescreen desktop browser. Reasonable to design gracefully down to a laptop screen; true mobile/responsive is still out of scope — don't spend effort on phone layouts.

## What's wrong with the current (Streamlit) UI

Everything is currently crammed into one narrow column — 20+ stacked controls, metrics, and status lines with near-identical visual weight — while the decision log (the most important element) sits at the very bottom of the page below the chart, reachable only by scrolling past everything else. The safety banner collapses to zero height when inactive, causing the page to jump every time an alert fires or clears. Switching control mode changes how many lines are stacked in the column, which reflows the whole page and loses scroll position. The chart, which should be the dominant visual, is squeezed by comparison. See the Phase 8 brief for the full list if useful context — but don't treat Phase 8's *layout* as a target to hit; treat its *problems* as the ones to solve, with more freedom to solve them.

## Design goals

1. Chart and decision log visible **simultaneously**, without a tab switch or scroll — you have the screen real estate now; use it.
2. A persistent status region that communicates "nominal" as a real, calm visual state, not silence — and that transitions between states smoothly rather than jumping.
3. Clear zones for *what the operator sets* vs. *what the operator observes* vs. *system safety state* — distinct enough that a glance sorts them without reading labels.
4. Live data should feel live: a connection-state indicator (connected / reconnecting / lost) for the WebSocket feed, since "is this actually updating or did it silently die" is a real failure mode worth surfacing.
5. Consistent severity color system, applied everywhere status varies, not just in one or two banners.
6. This is a safety system's control surface — the visual language should read as trustworthy and precise, not as a decorative consumer dashboard. Err toward a control-room/mission-control aesthetic.

## Freedoms available here that Phase 8 didn't have

- **Sticky/fixed panels** — e.g., a persistent status bar or decision-log rail that stays in view while other content scrolls.
- **Modals or confirm affordances** for consequential actions — e.g., Reset and Reset Interlock could get a brief inline confirm (not necessarily a heavy modal — a two-stage button or a small popover is probably enough for a single-operator demo tool; don't over-design friction into a live-demo tool that needs to move fast).
- **Toasts/transient notifications** for discrete events — e.g., "spike burst triggered," "interlock locked out," "AI fallback engaged" — separate from the persistent status region, for things that happened rather than states that persist.
- **Animated state transitions** — a banner sliding/fading in rather than popping, a trip-strike counter incrementing with a visible tick, a decision-log row highlighting briefly when it lands.
- **A live connection badge** reflecting actual WebSocket state, not just data freshness.
- **Layout that adapts by mode** without reflowing everything else — e.g., the AI reasoning panel can occupy a reserved region that's empty (not absent) in Manual/PID mode, rather than appearing/disappearing and shifting neighbors.
- Real component library territory (shadcn/ui, Tailwind, Radix, etc.) — feel free to note which components a design implies, since that'll inform the eventual build.

## Content inventory (same underlying data as Phase 8 — organize it however serves the goals above, not into Phase 8's zones)

- **Global safety state**: nominal / override active / AI fallback active / locked out (mutually exclusive priority: locked out > override active > AI fallback active > nominal).
- **Controller settings**: mode (Manual/PID/AI), setpoint, and mode-specific inputs — heater % + override arm toggle (Manual), Kp/Ki/Kd (PID), nothing extra to set (AI, it's autonomous within the interlock).
- **Fault injection**: scenario/seed picker, drift toggle, stuck-at toggle, spike trigger (one-shot).
- **Session controls**: run/pause, reset simulation, reset interlock.
- **Live telemetry**: true temperature, sensed temperature, actuator output, active faults (ground truth), detector flags (Tier-1 statistical belief — shown alongside ground truth deliberately, since the *gap* between them is the point), historian connection status, interlock trip-strike count (of a configured lockout threshold).
- **AI reasoning** (AI mode only): confidence, rationale text, an independent sensor-concern flag the AI can raise, a response-pending/waiting state, elapsed-time-since-last-success, last error text.
- **Primary chart**: true vs. sensed vs. setpoint over time. Preserve the established color convention: true = red/orange, sensed = blue, setpoint = dashed neutral line.
- **Decision log**: per-tick record of every interlock evaluation — tick, controller source, proposed/actual output, result (allow/clamp/reject), reason string, override-active flag, locked-out flag, detector flags. This is explicitly the single most important element in the UI per the project's design doc — give it real, persistent screen presence, not a corner.

## Visual system

- **Severity colors, applied everywhere status varies**: nominal/allowed = green, degraded/warning (AI waiting, override armed but not yet triggered, trip strike short of lockout) = amber, critical (locked out, hard trip firing, AI fallback active, override active, rejected proposal) = red, inactive/no data = neutral gray.
- **Chart colors, already validated by prior testing — keep them**: true = red/orange, sensed = blue, setpoint = dashed neutral/gray.
- Distinguish *system-imposed* critical states (lockout, hard trip, AI fallback) from the *operator-chosen* one (manual override active) — same severity tier, but they should not be visually identical; the operator made one of these happen on purpose.
- Small persistent iconography for source identity (Manual/PID/AI) so the decision log's source column is scannable by shape/color, not just text, and for result (allow/clamp/reject/lockout).
- Dark, high-contrast control-room theme is a reasonable default direction for this content, but propose whichever theme (dark or light) actually serves legibility and "trustworthy safety system" best — justify the choice rather than defaulting for its own sake.

## States to design

Same set as the Phase 8 brief, for direct comparability — but solved with this brief's freedoms, not reflowed from Phase 8's layout:

1. **Idle** — before the simulation starts, no data yet, WebSocket connected but nothing streaming.
2. **Manual mode, nominal.**
3. **PID mode, nominal** — settled near setpoint.
4. **AI mode, nominal** — reasoning panel populated with a real rationale and confidence.
5. **AI mode, degraded** — response-pending countdown visible, global state still nominal.
6. **AI mode, fallback active** — global critical state, distinguishable from override/lockout.
7. **Sensor fault active (stuck-at)** — sensed line frozen in the chart, true temperature visibly diverging; ground-truth vs. detector-flag gap visible in telemetry.
8. **Interlock reject/clamp** — a single rejected proposal lands in the decision log; global state stays nominal (one rejection isn't itself an alert).
9. **Hard trip firing** — sensed temperature at/past a hard bound, actuator forced to the safe value regardless of source; global critical state.
10. **Locked out** — repeated trip episodes without correction; global critical state, with the reset-interlock action clearly the relevant next step.
11. **Manual override active** — operator armed and triggered an override past a rejection; global critical state, visually distinct from lockout/hard-trip per the "system-imposed vs. operator-chosen" distinction above.
12. **Connection lost** (new in this brief — not meaningful in Phase 8's synchronous rerun model): the WebSocket drops mid-session; show how the UI communicates "you're looking at stale data" without it being mistaken for any of the other alert states.

## Deliverables

- One high-fidelity mockup per state above (12 total), consistent base layout, differing in the data/state shown.
- A component/color/iconography legend.
- A brief note on which UI library/primitives each nonstandard interaction (toasts, connection badge, animated transitions) implies, since that will inform the actual FastAPI+React build in this phase.
