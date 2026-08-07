# Phase 1: plant + manual control

Archived detailed build write-up — moved out of `CLAUDE.md` on 2026-08-07 to keep that file focused on current status. See `../../CLAUDE.md` for where the project stands now.

---

Phase 1 adds:
- `engine/models/first_order.py` — `FirstOrderThermal`, explicit-Euler integration of the doc's §3.1 ODE, registered as `"first_order"`. `engine/models/__init__.py` now imports it so the registry populates on package import.
- `engine/controllers/manual.py` — `ManualController`: holds a mutable `value` set via `set_value()`, `propose()` just echoes it. (The shared `Controller.propose(reading, setpoint, history)` signature has no slot for "current slider position" by design — every controller looks identical to the loop/interlock — so Manual gets its input through a setter instead.)
- `engine/loop.py` — `ControlLoop` class. `tick()` implements the full §4 record schema now, not just the fields Phase 1 needs: sensor/detector/interlock stages are honest passthroughs (`t_sensed == t_true`, `interlock_result == "allow"` with a reason string saying why) rather than omitted fields, so later phases fill a stage in without reshaping the schema.
- `app.py` — Streamlit UI: heater slider + live-updating chart (Celsius display-only, Kelvin internal per doc). Live-update mechanism: a `key="running"` toggle: while on, each script run advances one tick, redraws, sleeps `dt_seconds`, then calls `st.rerun()` to trigger the next run.
- Tests: `tests/test_first_order_model.py`, `tests/test_manual_controller.py`, `tests/test_control_loop.py` — 10 new known-outcome scenarios (exact single-Euler-step values, decay-to-ambient, analytical steady-state, passthrough behavior, record-schema stability). 11/11 total passing.

**Verified:** full pytest suite (11/11), Streamlit `AppTest` static render + widget interaction (no exceptions), a `ControlLoop` smoke test against the real `config.yaml`, and — after adding Playwright (below) — an actual headless-browser screenshot confirming the "Run" toggle drives the live chart.

**Tooling added: Playwright**, for headless-browser verification of UI phases. Dev-only, so it's in `requirements-dev.txt`, not `requirements.txt`:
```
source venv/bin/activate && pip install -r requirements-dev.txt && playwright install chromium
```
Chromium itself is cached under `~/Library/Caches/ms-playwright/`, not in the repo. Use it any time a phase touches `app.py` — launch `streamlit run app.py`, drive it with `playwright.sync_api.sync_playwright()`, screenshot before/after an interaction. Gotchas hit so far:
- Streamlit's checkbox/toggle widgets render their label text twice in the DOM in some cases (once in the widget, once in nearby help/info text) — `get_by_text("Run")` was ambiguous; scope to `get_by_test_id("stCheckbox").get_by_text(...)`. With multiple toggles on the page (Phase 3 added two more), disambiguate further with `.filter(has_text="...")`.
- **Streamlit's scrollable container is `section[data-testid="stMain"]`, not `window`/`body`.** Clicking a control lower on the page auto-scrolls that inner container, and neither `page.evaluate("window.scrollTo(0,0)")` nor `page.screenshot(full_page=True)` fixes it (both operate on the outer document, which never actually scrolls). Reset it explicitly before screenshotting: `page.evaluate('document.querySelector(\'[data-testid="stMain"]\').scrollTop = 0')`. Cost real time to diagnose (had to bounding-box the chart element and walk its ancestor chain to find which element actually had `scrollTop > 0`) — worth remembering directly rather than rediscovering.

**Noted for later, not a blocker:** at steady state, `T_ss = T_ambient + heater_pct * k_heat / loss_coeff`. With the current config constants that's ~373.15K (the `interlock.t_max_k` ceiling) at only ~24% heater — so once the interlock lands in Phase 4, most of the slider's/PID's range will get clamped at steady state. This is actually a good demo moment for the interlock, not a tuning bug.
