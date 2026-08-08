"""Streamlit entrypoint. Grows one build-order stage at a time —
see docs/control-loop-architecture.md §5. Phase 5 completes the three-way
controller comparison: manual, PID, and now AI (Claude), all proposing
through the same interface, all subject to the same interlock. The AI
call runs in a background thread (see engine/controllers/ai.py) so the
0.5s tick loop never blocks on a 1-3s+ API call -- it holds the last
committed value until a fresh one arrives, exactly like §3.3.1 describes.

The "scenario" picker seeds the sensor's RNG for reproducible baseline
noise (applied on Reset) -- it does NOT auto-script when faults fire.
Fault timing stays operator-driven via the toggles/button below, since
this is meant to be a live, presenter-driven demo, not a scripted replay.

Streamlit has no native background loop: each rerun executes the whole
script top to bottom. The live-plot effect here comes from a "Run" toggle
whose state persists in st.session_state — while it's on, each rerun
advances one tick, redraws, sleeps dt_seconds, then calls st.rerun() to
trigger the next rerun. Turning "Run" off just lets the script finish
without re-triggering itself.

Phase 7 adds Tier-2 LLM triage (see engine/triage.py) -- a plain-language,
advisory-only explanation of whatever the detector currently flags.
Deliberately manual/on-demand only (a button, never auto-triggered) to keep
API cost bounded, and a plain blocking call rather than AIController's
background-thread pattern, since it's a rare one-shot action, not a
per-tick decision with a deadline to protect.

Phase 8 is a layout/visual redesign only -- no control or safety logic
changes. Translates docs/design-prompts/Phase 8 Streamlit Thermal Control
UI.dc.html's 8-zone information architecture (status strip / chart /
controller / fault injection / session / telemetry tiles / AI reasoning /
decision log) into real Streamlit primitives: st.container(border=True)
cards for grouping, st.tabs to promote the decision log next to the chart
instead of it sitting below everything, st.container(height=...) to keep
the controller card's height stable across mode switches, and a small
green/amber/red/gray severity palette (module-level constants below) used
consistently across the status strip, telemetry tiles, and decision-log
row coloring -- not just the two st.error/st.warning calls used before.
The tick() call moved earlier in the script (right after the control
setters, before any rendering) so every zone in a given rerun reflects the
exact same tick -- previously the left-column metrics rendered from the
*previous* rerun's data while the chart/banner used the freshly-ticked
one, a one-rerun-stale mismatch that's easy to introduce when adding new
telemetry surfaces and easy to just not have at all.
"""

import html
import os
import time

import anthropic
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from config_schema import load_config
from engine.loop import ControlLoop
from engine.triage import Triage
from storage.historian import Historian

load_dotenv()

K_OFFSET_C = 273.15  # Kelvin<->Celsius offset -- Celsius is display-only, never internal (doc §3.1)

# Severity palette -- single source of truth for the status strip, telemetry
# tile dots, and decision-log row coloring. Values taken directly from
# docs/design-prompts/Phase 8 Streamlit Thermal Control UI.dc.html so the
# real app matches the reviewed mockup, not just its intent.
GREEN, GREEN_BG = "oklch(0.72 0.17 145)", "oklch(0.72 0.17 145 / 0.14)"
AMBER, AMBER_BG = "oklch(0.78 0.15 70)", "oklch(0.78 0.15 70 / 0.14)"
RED, RED_BG = "oklch(0.65 0.19 25)", "oklch(0.65 0.19 25 / 0.14)"
GRAY, GRAY_BG = "oklch(0.55 0.01 240)", "oklch(0.55 0.01 240 / 0.12)"


def k_to_c(kelvin: float) -> float:
    return kelvin - K_OFFSET_C


def c_to_k(celsius: float) -> float:
    return celsius + K_OFFSET_C


def format_active_flags(flags: dict, empty_label: str = "none") -> str:
    active = [name for name, is_active in flags.items() if is_active]
    return ", ".join(active) or empty_label


def status_strip_html(code: str, msg: str, color: str, bg: str) -> str:
    return (
        f'<div style="display:flex;align-items:center;gap:12px;padding:12px 20px;'
        f'border-radius:8px;background:{bg};margin-bottom:14px;">'
        f'<span style="font-family:monospace;font-size:11px;font-weight:700;'
        f'letter-spacing:.02em;color:{color};border:1px solid {color};'
        f'border-radius:4px;padding:4px 8px;">{code}</span>'
        f'<span style="font-weight:600;font-size:14.5px;color:{color};">{msg}</span>'
        f"</div>"
    )


def render_status_strip(latest: dict | None) -> str:
    """Zone A. Always returns a real rendered state -- "nominal" included --
    never empty space, unlike the st.empty()-collapses-to-nothing banner
    this replaces. Priority: locked out > hard trip firing > override
    active > AI fallback active > nominal. Hard-trip-firing is detected
    from the existing interlock_reason text (interlock.py already writes
    "...hard trip, forcing safe output..." for exactly this case) rather
    than a new schema field -- surfaces a state the old banner silently
    dropped: a single hard-trip tick that hasn't yet escalated to a
    lockout previously showed nothing at all. Hard-trip and override never
    coincide (interlock.py's check ordering returns from the hard-trip
    check before the override-eligible check runs), so this doesn't
    conflict with the other tiers.
    """
    if latest is None:
        return status_strip_html("NOMINAL", "System nominal", GREEN, GREEN_BG)
    if latest["interlock_locked_out"]:
        return status_strip_html(
            "LOCKED OUT",
            'Repeated over-temperature trips without correction — heater forced to safe output. '
            'Press "Reset Interlock" once conditions are confirmed safe.',
            RED,
            RED_BG,
        )
    if "hard trip" in latest["interlock_reason"].lower():
        return status_strip_html(
            "HARD TRIP",
            "Sensed temperature at or past a hard bound — actuator forced to a safe output regardless of source.",
            RED,
            RED_BG,
        )
    if latest["override_active"]:
        return status_strip_html(
            "OVERRIDE ACTIVE", "Interlock override active — operating outside validated safety bounds.", RED, RED_BG
        )
    if latest["ai_fallback_active"]:
        return status_strip_html(
            "AI FALLBACK", "AI controller unresponsive — automatic safe fallback active.", RED, RED_BG
        )
    return status_strip_html("NOMINAL", "System nominal — all proposals within validated bounds.", GREEN, GREEN_BG)


def render_tile(label: str, value: str, sub: str, dot: str) -> None:
    with st.container(border=True):
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:6px;font-size:10.5px;'
            f'text-transform:uppercase;letter-spacing:.03em;opacity:.65;margin-bottom:4px;">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{dot};flex:none;"></span>{label}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(f'<div style="font-size:19px;font-weight:600;">{value}</div>', unsafe_allow_html=True)
        st.caption(sub)


def render_tile_row(latest: dict, loop: ControlLoop) -> None:
    """Zone F. Replaces the old vertical st.metric + loose-caption stack
    with a row of compact tiles, each carrying a severity dot derived from
    existing fields -- no new schema, just a UI-layer classification."""
    any_fault = bool(latest["active_faults"])
    any_flag = any(latest["detector_flags"].values())
    historian_connected = bool(st.session_state.historian and st.session_state.historian.ready)
    trip_strikes = loop.interlock.trip_strikes
    trip_threshold = loop.interlock.trip_lockout_threshold
    locked_out = loop.interlock.locked_out

    tiles = [
        ("True temp", f"{k_to_c(latest['t_true']):.1f}°C", "ground truth", GRAY),
        ("Sensed temp", f"{k_to_c(latest['t_sensed']):.1f}°C", "reported", RED if any_flag else GREEN),
        ("Actuator", f"{latest['actuator_output']:.0f}%", "heater output", GRAY),
        ("Active faults", ", ".join(latest["active_faults"]) or "none", "ground truth", RED if any_fault else GREEN),
        (
            "Detector flags",
            format_active_flags(latest["detector_flags"]),
            "Tier-1 belief",
            RED if any_flag else GREEN,
        ),
        (
            "Historian",
            "connected" if historian_connected else "unavailable",
            "logging status",
            GREEN if historian_connected else GRAY,
        ),
        (
            "Trip strikes",
            f"{trip_strikes}/{trip_threshold}" + (" (locked)" if locked_out else ""),
            "before lockout",
            RED if locked_out else (AMBER if trip_strikes > 0 else GREEN),
        ),
    ]
    for col, (label, value, sub, dot) in zip(st.columns(7), tiles):
        with col:
            render_tile(label, value, sub, dot)


def render_ai_panel(latest: dict) -> None:
    """Zone G. Own dedicated card, only rendered in AI mode -- replaces the
    old five stacked captions (confidence/rationale/sensor-concern/error/
    countdown). Lives in the right column, so its appearance/disappearance
    across mode switches never affects the left rail (Zones C/D/E)."""
    with st.container(border=True):
        st.markdown("**AI reasoning**")
        proposed = latest["proposed_action"]
        elapsed = proposed.metadata.get("seconds_since_last_success", 0.0)
        max_wait = CONFIG["ai"]["max_response_wait_s"]
        fallback_threshold = max_wait + CONFIG["ai"]["fallback_after_s"]

        if latest["ai_fallback_active"]:
            st.error(
                f"AI unresponsive for {elapsed:.0f}s — automatic safe fallback active "
                f"({CONFIG['ai']['safe_output_pct']:.0f}% heater)."
            )
        elif elapsed > max_wait:
            st.warning(
                f"AI hasn't produced a valid response in {elapsed:.0f}s. Switch to Manual or PID, "
                f"or it will auto-fallback to a safe default in {fallback_threshold - elapsed:.0f}s."
            )
        elif proposed.metadata.get("waiting"):
            st.caption("Waiting on AI response...")

        col_conf, col_concern = st.columns(2)
        with col_conf:
            st.caption("Confidence")
            st.markdown(f"**{proposed.confidence or '—'}**")
        with col_concern:
            st.caption("Sensor concern")
            st.markdown("**Flagged**" if proposed.flagged_sensor_concern else "None")
        if proposed.rationale:
            st.markdown(f'*"{proposed.rationale}"*')
        if proposed.metadata.get("last_error"):
            st.caption(f"Last AI error: {proposed.metadata['last_error']}")


def decision_log_row_bg(record: dict) -> str:
    """Row-severity color for Zone H, mirroring the mockup's rowBg logic:
    red for anything absolute (lockout/override/hard trip), amber for a
    routine clamp/reject or a sensor-untrusted hold, transparent (no tint)
    for a plain allow. Derived entirely from fields already on the record
    -- no schema change."""
    reason = record["interlock_reason"].lower()
    if record["interlock_locked_out"] or record["override_active"] or "hard trip" in reason or "lockout" in reason:
        return RED_BG
    if record["interlock_result"] in ("clamp", "reject") or "untrusted" in reason:
        return AMBER_BG
    return "transparent"


def render_decision_log_table(rows: list[dict]) -> str:
    """Zone H, as a hand-built HTML table rather than st.dataframe: a
    pandas Styler passed into st.dataframe renders as a corrupted solid
    block for most rows in the installed Streamlit version (confirmed via
    Playwright screenshot, not just a screenshot-timing artifact -- the
    same corruption showed up across repeated runs). An HTML table is also
    arguably more faithful here anyway -- the reviewed mockup itself is
    hand-built HTML/CSS, not a real grid widget."""
    headers = ["Tick", "Source", "Output", "Result", "Reason", "Override", "Locked", "Flags"]
    header_html = "".join(
        f'<th style="text-align:left;padding:6px 10px;font-size:11px;text-transform:uppercase;'
        f'letter-spacing:.03em;opacity:.6;border-bottom:1px solid rgba(128,128,128,.3);">{h}</th>'
        for h in headers
    )
    body_rows = []
    for record in rows:
        bg = decision_log_row_bg(record)
        cells = [
            record["tick"],
            record["controller_source"],
            f"{record['actuator_output']:.1f}%",
            record["interlock_result"],
            html.escape(record["interlock_reason"]),
            "Y" if record["override_active"] else "N",
            "Y" if record["interlock_locked_out"] else "N",
            html.escape(format_active_flags(record["detector_flags"], empty_label="-")),
        ]
        cell_html = "".join(f'<td style="padding:5px 10px;font-size:12.5px;">{c}</td>' for c in cells)
        body_rows.append(f'<tr style="background:{bg};">{cell_html}</tr>')
    return (
        '<div style="max-height:600px;overflow-y:auto;border:1px solid rgba(128,128,128,.2);border-radius:6px;">'
        '<table style="width:100%;border-collapse:collapse;">'
        f"<thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )


st.set_page_config(page_title="Control Loop Simulation", layout="wide")
st.title("Safety-Constrained AI Control Loop")
st.caption("Manual / PID / AI (Claude), all proposing through the same interlock — AI proposes, the interlock disposes.")
banner_placeholder = st.empty()  # filled in after this rerun's tick, so it reflects the freshest decision

try:
    CONFIG = load_config("config.yaml")
except ValidationError as exc:
    st.error(f"config.yaml is invalid:\n\n{exc}")
    st.stop()

HISTORY_LIMIT = 500  # rolling buffer, per docs/control-loop-architecture.md §4
DECISION_LOG_ROWS_DEFAULT = 50

SCENARIOS = {"Random (no fixed seed)": None}
for scenario in CONFIG["sensor"]["seeded_scenarios"]:
    SCENARIOS[scenario["name"].replace("_", " ").title()] = scenario["seed"]


def reset_simulation(seed: int | None = None) -> None:
    st.session_state.loop = ControlLoop(CONFIG, seed=seed, ai_client=st.session_state.ai_client)
    st.session_state.history = []
    st.session_state.last_triage = None


if "ai_client" not in st.session_state:
    # None is fine -- AIController treats a missing client as an immediate,
    # well-labeled failure rather than crashing, same resilience posture as
    # the historian tolerating a missing DSN.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    st.session_state.ai_client = anthropic.Anthropic(api_key=api_key) if api_key else None
if "triage" not in st.session_state:
    st.session_state.triage = Triage(
        client=st.session_state.ai_client,
        model=CONFIG["triage"]["model"],
        max_wait_s=CONFIG["triage"]["max_wait_s"],
    )
if "loop" not in st.session_state:
    reset_simulation()
if "running" not in st.session_state:
    st.session_state.running = False
if "historian" not in st.session_state:
    # Historian's lifecycle is independent of the control loop's -- a real
    # historian keeps recording across resets, it doesn't restart with the
    # process it's observing. Tolerates a missing/unreachable DB on its own.
    dsn = os.environ.get("TIMESCALE_DSN")
    st.session_state.historian = Historian(dsn) if dsn else None

col_controls, col_main = st.columns([1, 3])

with col_controls:
    with st.container(border=True):  # Zone C -- controller
        st.markdown("**Controller**")
        mode_label = st.radio("Control mode", ["Manual", "PID", "AI"], horizontal=True)
        mode = mode_label.lower()

        setpoint_c = st.slider("Setpoint (°C)", min_value=0.0, max_value=100.0, value=50.0, step=1.0)
        setpoint_k = c_to_k(setpoint_c)

        override_requested = False
        # Fixed-height container (design goal 6): mode-specific inputs differ
        # in length (Manual: 2 rows, PID: 1 row of 3, AI: 2 caption lines),
        # so without this the card itself would resize on every mode switch.
        with st.container(height=170):
            if mode == "manual":
                heater_pct = st.slider("Heater output (%)", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
                override_requested = st.toggle("Override interlock (manual only)")
                if override_requested:
                    st.caption("Armed -- a bounds rejection will be let through, with a warning, while this is on.")
            elif mode == "pid":
                heater_pct = 0.0  # ignored by the loop while in PID mode
                kp = st.slider("Kp", min_value=0.0, max_value=10.0, value=CONFIG["pid"]["kp"], step=0.1)
                ki = st.slider("Ki", min_value=0.0, max_value=5.0, value=CONFIG["pid"]["ki"], step=0.05)
                kd = st.slider("Kd", min_value=0.0, max_value=5.0, value=CONFIG["pid"]["kd"], step=0.05)
                st.caption("PID can never override the interlock, under any circumstance.")
            else:  # ai
                heater_pct = 0.0  # ignored by the loop while in AI mode
                st.caption("AI can never override the interlock, under any circumstance.")
                if st.session_state.ai_client is None:
                    st.caption("No ANTHROPIC_API_KEY configured -- AI mode will always show as unresponsive.")
                else:
                    st.caption("Proposing actuator commands -- see AI reasoning panel →")

    with st.container(border=True):  # Zone D -- fault injection
        st.markdown("**Fault injection**")
        scenario_label = st.selectbox("Scenario (seeds noise, applied on Reset)", list(SCENARIOS.keys()))
        drift_on = st.toggle("Drift fault")
        stuck_on = st.toggle("Stuck-at fault")
        spike_clicked = st.button("Trigger spike burst")

    with st.container(border=True):  # Zone E -- session controls
        st.markdown("**Session**")
        st.toggle("Run", key="running")
        col_reset, col_reset_interlock = st.columns(2)
        with col_reset:
            if st.button("Reset"):
                reset_simulation(seed=SCENARIOS[scenario_label])
                st.rerun()
        with col_reset_interlock:
            # Operator-acknowledged reset (backlog item 2): clears a latched
            # lockout and gives the detector a fresh start too. Harmless to
            # press when there's nothing to reset.
            if st.button("Reset Interlock"):
                st.session_state.loop.reset_interlock()

loop = st.session_state.loop
loop.set_mode(mode)
loop.set_setpoint(setpoint_k)
if mode == "pid":
    loop.set_pid_gains(kp, ki, kd)
loop.set_drift(drift_on)
loop.set_stuck(stuck_on)
loop.set_manual_override_requested(override_requested)
if spike_clicked:
    loop.trigger_spike()

# Tick before any rendering (moved from the end of the script) so every
# zone below reflects this exact tick, not a mix of "this rerun's fresh
# data" (previously only the banner/chart) and "last rerun's data"
# (previously the left-column metrics).
if st.session_state.running:
    record = loop.tick(heater_pct)
    st.session_state.history.append(record)
    st.session_state.history = st.session_state.history[-HISTORY_LIMIT:]
    if st.session_state.historian is not None:
        st.session_state.historian.record(record)

latest = st.session_state.history[-1] if st.session_state.history else None
banner_placeholder.markdown(render_status_strip(latest), unsafe_allow_html=True)

with col_main:
    tab_live, tab_log = st.tabs(["Live", "Decision Log"])

    with tab_live:
        current_temp_k = loop.state["temperature"]
        st.metric("True temperature", f"{k_to_c(current_temp_k):.1f} °C", help=f"{current_temp_k:.2f} K")

        if latest is not None:
            render_tile_row(latest, loop)  # Zone F

            # Backlog item 7: one combined trigger, not two separate buttons --
            # a sensor fault and the interlock's reaction to it are usually
            # the same underlying incident. Lights up on either a live
            # detector flag or any non-"allow" interlock result in the same
            # window that gets sent to the prompt, so what enables the
            # button matches what it will actually reason about.
            window = CONFIG["triage"]["history_window_ticks"]
            recent = st.session_state.history[-window:]
            any_flag_active = any(latest["detector_flags"].values())
            any_interlock_activity = any(r["interlock_result"] != "allow" for r in recent)
            triage_available = any_flag_active or any_interlock_activity
            if st.button("Triage with Claude", disabled=not triage_available):
                with st.spinner("Asking Claude to triage the flagged anomaly or interlock activity..."):
                    st.session_state.last_triage = st.session_state.triage.request(
                        history=recent,
                        detector_flags=latest["detector_flags"],
                    )
            if not triage_available:
                st.caption(
                    "Triage enabled once a detector flag is active or the interlock has rejected/clamped/tripped "
                    "recently. Manual/on-demand only, to keep API cost bounded."
                )
            if st.session_state.last_triage is not None:
                result = st.session_state.last_triage
                if result.success:
                    st.info(f"**Triage:** likely {result.fault_type} (severity: {result.severity}) — {result.explanation}")
                else:
                    st.caption(f"Triage failed: {result.error}")

            df = pd.DataFrame(st.session_state.history)  # Zone B
            # Vectorized subtraction (not .apply(k_to_c)) -- idiomatic pandas,
            # avoids a slow per-row Python call over a column of floats.
            df["true_c"] = df["t_true"] - K_OFFSET_C
            df["sensed_c"] = df["t_sensed"] - K_OFFSET_C
            df["setpoint_c"] = df["setpoint"] - K_OFFSET_C
            st.line_chart(df.set_index("tick")[["true_c", "sensed_c", "setpoint_c"]])

            if mode == "ai":
                render_ai_panel(latest)  # Zone G
        else:
            st.info("Press Run to start the simulation.")

    with tab_log:
        st.caption("Every evaluation — allowed, clamped, rejected, or manually overridden — logged with its reason.")
        show_full_history = st.checkbox(f"Show full history (up to {HISTORY_LIMIT} ticks)", value=False)
        if st.session_state.history:
            rows = st.session_state.history if show_full_history else st.session_state.history[-DECISION_LOG_ROWS_DEFAULT:]
            st.markdown(render_decision_log_table(rows[::-1]), unsafe_allow_html=True)
        else:
            st.caption("No ticks yet.")

if st.session_state.running:
    time.sleep(CONFIG["simulation"]["dt_seconds"])
    st.rerun()
