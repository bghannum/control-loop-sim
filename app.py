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
"""

import os
import time

import anthropic
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from config_schema import load_config
from engine.loop import ControlLoop
from storage.historian import Historian

load_dotenv()

K_OFFSET_C = 273.15  # Kelvin<->Celsius offset -- Celsius is display-only, never internal (doc §3.1)


def k_to_c(kelvin: float) -> float:
    return kelvin - K_OFFSET_C


def c_to_k(celsius: float) -> float:
    return celsius + K_OFFSET_C


def format_active_flags(flags: dict, empty_label: str = "none") -> str:
    active = [name for name, is_active in flags.items() if is_active]
    return ", ".join(active) or empty_label


st.set_page_config(page_title="Control Loop Simulation", layout="wide")
st.title("Safety-Constrained AI Control Loop")
st.caption("Phase 5: manual / PID / AI (Claude), all through the same interlock. Full control-source comparison.")
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


if "ai_client" not in st.session_state:
    # None is fine -- AIController treats a missing client as an immediate,
    # well-labeled failure rather than crashing, same resilience posture as
    # the historian tolerating a missing DSN.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    st.session_state.ai_client = anthropic.Anthropic(api_key=api_key) if api_key else None
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

col_controls, col_plot = st.columns([1, 3])

with col_controls:
    st.subheader("Control")
    mode_label = st.radio("Control mode", ["Manual", "PID", "AI"], horizontal=True)
    mode = mode_label.lower()

    setpoint_c = st.slider("Setpoint (°C)", min_value=0.0, max_value=100.0, value=50.0, step=1.0)
    setpoint_k = c_to_k(setpoint_c)

    override_requested = False
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

    st.subheader("Sensor")
    scenario_label = st.selectbox("Scenario (seeds noise, applied on Reset)", list(SCENARIOS.keys()))
    drift_on = st.toggle("Drift fault")
    stuck_on = st.toggle("Stuck-at fault")
    spike_clicked = st.button("Trigger spike burst")

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

    current_temp_k = loop.state["temperature"]
    st.metric("True temperature", f"{k_to_c(current_temp_k):.1f} °C", help=f"{current_temp_k:.2f} K")
    if st.session_state.history:
        latest = st.session_state.history[-1]
        st.metric("Sensed temperature", f"{k_to_c(latest['t_sensed']):.1f} °C")
        st.metric("Actuator output", f"{latest['actuator_output']:.1f} %")
        st.caption(f"Active faults (ground truth): {', '.join(latest['active_faults']) or 'none'}")
        st.caption(f"Detector flags (Tier-1 belief): {format_active_flags(latest['detector_flags'])}")
        st.caption(
            f"Historian: {'connected' if st.session_state.historian and st.session_state.historian.ready else 'unavailable (not blocking)'}"
        )
        if loop.interlock.trip_strikes > 0:
            status = " — LOCKED OUT, awaiting reset" if loop.interlock.locked_out else ""
            st.caption(
                f"Interlock trip strikes: {loop.interlock.trip_strikes}/{loop.interlock.trip_lockout_threshold}{status}"
            )

        if mode == "ai":
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

            if proposed.confidence:
                st.caption(f"AI confidence: {proposed.confidence}")
            if proposed.rationale:
                st.caption(f"AI rationale: {proposed.rationale}")
            if proposed.flagged_sensor_concern:
                st.caption("AI independently flagged a sensor concern.")
            if proposed.metadata.get("last_error"):
                st.caption(f"Last AI error: {proposed.metadata['last_error']}")

if st.session_state.running:
    record = st.session_state.loop.tick(heater_pct)
    st.session_state.history.append(record)
    st.session_state.history = st.session_state.history[-HISTORY_LIMIT:]
    if st.session_state.historian is not None:
        st.session_state.historian.record(record)

latest = st.session_state.history[-1] if st.session_state.history else None
if latest and latest["interlock_locked_out"]:
    banner_placeholder.error(
        "INTERLOCK LOCKED OUT — repeated over-temperature trips without correction. Heater forced to "
        'safe output. Press "Reset Interlock" once conditions are confirmed safe.'
    )
elif latest and latest["override_active"]:
    banner_placeholder.error("Interlock override active — operating outside validated safety bounds")
elif latest and latest["ai_fallback_active"]:
    banner_placeholder.error("AI controller unresponsive — automatic safe fallback active")

with col_plot:
    if st.session_state.history:
        df = pd.DataFrame(st.session_state.history)
        # Vectorized subtraction (not .apply(k_to_c)) -- idiomatic pandas,
        # avoids a slow per-row Python call over a column of floats.
        df["true_c"] = df["t_true"] - K_OFFSET_C
        df["sensed_c"] = df["t_sensed"] - K_OFFSET_C
        df["setpoint_c"] = df["setpoint"] - K_OFFSET_C
        st.line_chart(df.set_index("tick")[["true_c", "sensed_c", "setpoint_c"]])
    else:
        st.info("Press Run to start the simulation.")

st.subheader("Interlock decision log")
st.caption("Every evaluation — allowed, clamped, rejected, or manually overridden — logged with its reason.")
show_full_history = st.checkbox(f"Show full history (up to {HISTORY_LIMIT} ticks)", value=False)
if st.session_state.history:
    rows = st.session_state.history if show_full_history else st.session_state.history[-DECISION_LOG_ROWS_DEFAULT:]
    log_df = pd.DataFrame(rows[::-1])
    log_df["detector_flags"] = log_df["detector_flags"].apply(lambda flags: format_active_flags(flags, empty_label="-"))
    st.dataframe(
        log_df[
            [
                "tick", "controller_source", "actuator_output", "interlock_result",
                "interlock_reason", "override_active", "interlock_locked_out", "detector_flags",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )
else:
    st.caption("No ticks yet.")

if st.session_state.running:
    time.sleep(CONFIG["simulation"]["dt_seconds"])
    st.rerun()
