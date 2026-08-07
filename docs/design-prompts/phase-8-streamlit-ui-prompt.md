# Design prompt — Phase 8: Streamlit UI/UX overhaul

Paste this whole document to Claude Design. It's a self-contained brief — you don't need the rest of the repo to act on it, though the repo is available if you want to check specifics.

## What you're designing

A redesign of the *layout and visual system* of an existing single-page Streamlit app, not a new product. The underlying functionality does not change in this phase — every control, metric, and log entry described below already exists and works; the problem is purely how it's arranged on screen. Produce mockups (static images or HTML) for the states listed below, plus a short component/color legend.

## Project context

This is a portfolio project: a simulated thermal control loop (a heater keeping a temperature at a setpoint) that can be driven by a human, a classical PID controller, or an AI controller (Claude), all mediated by a hard-coded safety interlock that can reject, clamp, or force-override any proposed actuator command regardless of its source. The whole point of the project is **"AI proposes, a deterministic interlock disposes"** — the interlock is never AI-driven and can override the AI (or a human) at any time. The UI's job is to make that safety story *visible*: an operator (or an interviewer watching a demo) should be able to look at the screen and immediately understand what's controlling the plant, whether a fault is active, and whether the safety layer has intervened, without hunting for it.

The single most important element in the whole UI, per the project's own design doc, is the **decision log** — a running record of every interlock evaluation (allowed / clamped / rejected / overridden, with a reason). Today it's the least visible thing on the page.

## Who uses this, and when

One operator, one browser tab, one session at a time — no auth, no multi-tenancy, nothing concurrent to design for. Two real contexts of use:

1. **Live, presenter-driven demo** (e.g., in a job interview): the operator narrates while toggling modes, injecting faults, and pointing at what the interlock does about it. Screen is likely shared/projected, so glanceability at a distance matters more than density.
2. **Solo exploration**: same person, sitting at a laptop, actually watching values move tick to tick.

Design for a widescreen desktop browser. Mobile/responsive is explicitly out of scope — don't spend effort on it.

## What's wrong with the current UI (be concrete about this)

The app is currently one narrow left-hand column (roughly 1/4 page width) containing, stacked vertically with no grouping beyond a plain section header: a mode selector, a setpoint slider, 1–3 mode-specific inputs, a fault-injection section (scenario picker, two toggles, a button), three session buttons, then eight-plus separate metric/caption lines (true temp, sensed temp, actuator output, active faults, detector flags, historian status, trip-strike count), and — only in AI mode — five *more* stacked caption lines (confidence, rationale, sensor-concern flag, error text, a countdown warning). That's 20+ stacked elements of near-identical visual weight in one column. Specific consequences:

- **The decision log — the most important element — sits at the very bottom of the page**, below the chart, reachable only after scrolling past everything else. In a live demo this is easy to lose track of.
- **The safety banner (lockout / override / AI-fallback) sits at the top in an `st.empty()` slot that collapses to zero height when there's nothing to show.** This causes the whole page to jump vertically the instant an alert fires or clears — distracting during a live demo, and it means "nothing is wrong" has no visual presence at all (silence, not a calm state).
- **Controls, live telemetry, and AI reasoning are not visually separated** — a slider the operator can change, a read-only number they're observing, and a safety-critical status all look the same (plain text/widgets in a vertical stack).
- **Switching modes changes the panel's length unpredictably** (AI mode adds ~5 extra lines Manual/PID don't have), so the page reflows and scroll position shifts every time the operator changes mode.
- **The chart — the primary "what's happening" visualization — is cramped relative to how much of the page is spent on stacked text**, when it should be the dominant visual element.
- Color is barely used. `st.error`/`st.warning` give banners some color, but everything else (trip strikes escalating, a rejected proposal in the log, which fault is active) is plain text — nothing is glanceable by color/shape the way a real control-room display would be.

## Design goals

1. Get the decision log onto the same screen as the chart, or one click away — never a full scroll below everything else.
2. A persistent status strip that always occupies the same height, whether it's showing "nominal" or a critical alert — no layout jump.
3. Group elements by *role*, not just by proximity: things the operator sets, things the operator observes, and system safety state should be visually distinct zones, not one undifferentiated stack.
4. The chart should read as the dominant visual element of the page.
5. A consistent severity color system applied everywhere a status can vary (banner, decision log rows, trip-strike counter, telemetry), not just the two `st.error`/`st.warning` calls that happen to use it today.
6. Switching control mode should not change the height/scroll position of the rest of the page.

## Hard constraint: this has to actually be Streamlit

This is not a custom frontend (that's Phase 9, a separate brief). Design only with what Streamlit's layout primitives can actually produce: `st.columns`, `st.tabs`, `st.expander`, `st.container(border=True)`, `st.metric`, `st.dataframe`, `st.empty` placeholders, and CSS reachable via `st.markdown(unsafe_allow_html=True)` for things like color chips or a status pill (light custom CSS is fine; a custom JS framework is not). No sticky/fixed-position panels, no modals, no drag-to-resize, no toast notifications, no animated transitions beyond what Streamlit's own rerun cycle gives you for free — Streamlit re-renders the whole script top to bottom on every tick, so any mockup should look correct as a single static frame, not rely on a transition between frames. If a mockup element isn't achievable this way, don't include it — flag it instead for the Phase 9 brief.

## Information architecture — proposed zones

This is a starting structure, not a rigid spec — push back on it if a better arrangement still respects the Streamlit constraint above.

**Zone A — Status strip** (full width, top, fixed height always). Shows exactly one state at a time, in priority order: locked out → override active → AI fallback active → nominal. "Nominal" must be an actual rendered state (e.g. a quiet green pill reading "System nominal"), not empty space.

**Zone B — Primary chart** (largest single element on the page). True temperature, sensed temperature, and setpoint over time. Preserve the color convention already validated in this project: true = red/orange, sensed = blue, setpoint = dashed neutral line.

**Zone C — Controller panel** (what the operator sets). Mode selector (Manual/PID/AI), setpoint slider, then mode-specific inputs — heater slider + override toggle (Manual), Kp/Ki/Kd (PID), a compact AI-status line (AI). Reserve consistent height across all three modes (e.g., a fixed-height container, or `st.tabs` per mode) so switching modes doesn't resize the panel.

**Zone D — Fault injection panel** (separate card from Zone C — currently merged into the same column despite being conceptually a different subsystem — sensor faults, not control). Scenario picker, drift toggle, stuck-at toggle, spike button.

**Zone E — Session controls** (separate small strip, not interleaved with Zone C's sliders). Run/pause toggle, Reset, Reset Interlock.

**Zone F — Telemetry readout** (what the operator observes, read-only). True temp, sensed temp, actuator output, active faults (ground truth), detector flags (Tier-1 belief — shown side by side with active faults since the *gap* between them is the point), historian connection status, trip-strike count. Render as a row/grid of compact metric tiles with consistent styling, not a vertical stack of `st.metric` + loose captions.

**Zone G — AI reasoning panel** (own dedicated card, only present in AI mode, in a fixed slot so its appearance/disappearance doesn't push Zones C–F around). Confidence, rationale, sensor-concern flag, waiting/error/fallback messaging.

**Zone H — Decision log** (promoted, not buried). Full table: tick, source, output, result, reason, override active, locked out, detector flags. Include the existing "show full history" checkbox. This needs to be reachable without scrolling past the chart and every telemetry element first — consider a top-level `st.tabs(["Live", "Decision Log"])` split, or placing it directly beside/below the chart in the main column rather than at the very end of the page.

A rough starting wireframe (not final — reflow as needed):

```
┌─────────────────────────────────────────────────────────────┐
│ Zone A — status strip (full width, fixed height)              │
├───────────────────┬─────────────────────────────────────────┤
│ Zone C Controller  │ Zone F — telemetry tile row               │
│ Zone D Faults      │ Zone B — chart (dominant)                 │
│ Zone E Session     │ Zone G — AI panel (AI mode only)          │
│  (left rail)       │ Zone H — decision log                     │
└───────────────────┴─────────────────────────────────────────┘
```

## Visual system

- **Severity colors, applied consistently everywhere status varies** (banner, decision log row highlighting, trip-strike counter, telemetry flags): nominal/allowed = green, degraded/warning (AI waiting, override armed, trip strike 1 of N) = amber, critical (locked out, hard trip firing, AI fallback active, override active, rejected proposal) = red, inactive/no data = neutral gray.
- **Chart colors are already validated by prior live testing — keep them**: true temperature = red/orange, sensed temperature = blue, setpoint = dashed neutral/gray line.
- **Overall tone: control-room / SCADA, not consumer-app playful.** This is a safety system; the visual language should read as trustworthy and legible at a glance, not decorative.
- Suggest small icons for: lockout (padlock), rejected (X), allowed (check), override armed (shield/warning), AI (a distinct badge from PID/Manual so the source is always identifiable at a glance in the decision log).

## States to design

Produce one mockup per state (all at the full-page layout, not isolated components):

1. **Idle** — before "Run" is ever pressed, no data yet.
2. **Manual mode, nominal** — heater slider mid-range, temperature tracking toward it, no faults.
3. **PID mode, nominal** — settled near setpoint, classic small-oscillation steady state.
4. **AI mode, nominal** — Zone G populated with a real rationale string, confidence shown.
5. **AI mode, degraded** — countdown warning visible (no valid response in >10s), Zone A still nominal (this hasn't triggered fallback yet).
6. **AI mode, fallback active** — Zone A shows the AI-fallback critical state.
7. **Sensor fault active (stuck-at)** — sensed line frozen flat in the chart while true temperature visibly diverges underneath; Zone F shows the ground-truth/detector-flag gap.
8. **Interlock reject/clamp** — a proposal rejected by the margin check; Zone H's newest row shows it, Zone A stays nominal (a single rejection isn't itself an alert state).
9. **Hard trip firing** — sensed temperature at/past the ceiling, actuator forced to 0% regardless of source; Zone A shows critical.
10. **Locked out** — repeated trip episodes without correction; Zone A shows the lockout state, "Reset Interlock" is the obviously-relevant action.
11. **Manual override active** — operator has armed and triggered an override past a bounds rejection; Zone A shows the override-active critical state (visually distinguishable from a lockout/hard-trip, since this one was operator-chosen, not system-imposed).

## Deliverables

- One high-fidelity mockup per state above (11 total), same base layout, differing only in the data/state shown.
- A short component/color legend: what each severity color, icon, and zone border style means.
- For every element you design, a one-line note confirming it's achievable with the Streamlit constraint above (or flag it as "needs Phase 9" if it secretly isn't).
