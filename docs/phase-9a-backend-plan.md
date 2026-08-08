# Phase 9a implementation plan: FastAPI backend

Written 2026-08-08, scoped and walked through with the user before any code exists. Not started — this is the reference to build from when 9a is picked up, so the design decisions don't need to be re-derived. See `CLAUDE.md`'s "Phase 9 split into 9a/9b/9c" note for the three decisions this plan assumes: Streamlit stays (this is a second interface, not a replacement), local-only (no deployment scope), Vite/React/TypeScript for 9b/9c (not this doc's concern, but shapes the API contract below).

## The one idea this phase is actually about

Today, `app.py` *is* the simulation's heartbeat — Streamlit re-runs the whole script on a timer, and each rerun calls `loop.tick()` once. There is no simulation running independently of a browser tab.

A backend can't work that way. It needs a tick loop that runs on its own, in the background, whether or not any client is connected — an `asyncio.Task` started once when the server boots, not driven by any request. Everything else in this plan exists to support that one idea: something has to own the `ControlLoop`, run it continuously, and hand its output to whoever's listening.

## Directory layout

```
backend/
  __init__.py
  main.py            # FastAPI() app, CORS, lifespan startup/shutdown, router mounting
  service.py          # SimulationService -- owns ControlLoop + the background tick loop
  schemas.py           # Pydantic request/response models (API boundary, same role as config_schema.py)
  routers/
    __init__.py
    control.py          # REST control endpoints
    stream.py            # WebSocket endpoint
requirements-backend.txt  # fastapi, uvicorn[standard], httpx (test client) -- separate from
                           # requirements.txt, same reasoning as requirements-dev.txt: Streamlit
                           # users shouldn't need to install a web framework they're not using
```

`engine/`, `storage/`, `config_schema.py` are imported, not touched or duplicated.

Tests go in the existing flat `tests/` directory, prefixed rather than nested (matches the project's existing one-file-per-module convention): `tests/test_backend_service.py`, `tests/test_backend_control_api.py`, `tests/test_backend_stream_api.py`.

## `SimulationService` (`backend/service.py`)

The class that replaces "the implicit loop inside `app.py`'s script reruns" with something explicit and independent.

```python
class SimulationService:
    def __init__(self, config: dict, ai_client: AnthropicClientLike | None = None):
        self._config = config
        self._ai_client = ai_client
        self.loop = ControlLoop(config, ai_client=ai_client)
        self.triage = Triage(
            client=ai_client, model=config["triage"]["model"], max_wait_s=config["triage"]["max_wait_s"]
        )
        self.history: list[dict] = []
        self._history_limit = 500
        self._manual_heater_pct = 0.0        # tick() takes this as a param, not a setter --
                                               # has to be buffered as service state now that
                                               # nothing calls tick() per-request anymore
        self._clients: set[WebSocket] = set()
        self._tick_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        if self._tick_task is None or self._tick_task.done():
            self._tick_task = asyncio.create_task(self._tick_loop())

    def stop(self) -> None:
        self._running = False  # _tick_loop checks this each cycle and exits cleanly

    async def _tick_loop(self) -> None:
        while self._running:
            record = self.loop.tick(self._manual_heater_pct)
            self.history.append(record)
            self.history = self.history[-self._history_limit:]
            await self._broadcast(record)
            await asyncio.sleep(self._config["simulation"]["dt_seconds"])

    async def _broadcast(self, record: dict) -> None:
        payload = TickRecord.from_domain(record).model_dump_json()
        dead = set()
        for ws in self._clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead
```

Everything else (mode, setpoint, PID gains, drift/stuck toggles, spike trigger, manual override) is a thin, synchronous pass-through to `self.loop`'s existing setters — called directly from REST handlers, not buffered. Only the manual heater percentage needs buffering, because `ControlLoop.tick()` takes it as a direct argument rather than something set ahead of time via a setter.

**Why no locks are needed here (worth stating explicitly, since it looks scarier than it is):** FastAPI's concurrency is cooperative `async`/`await`, not real multi-threading. A REST handler and `_tick_loop` only ever hand off control to each other at an `await` point. `loop.tick()`, `loop.set_mode()`, etc. are all plain synchronous Python — they run to completion without yielding, so there's no window where two code paths mutate `ControlLoop` at once. (`AIController` already runs its own genuine background *thread* internally — unrelated and unaffected; `tick()` only ever polls whether that thread is done, never blocks on it.)

`reset()` and `reset_interlock()` on the service just delegate to constructing a fresh `ControlLoop` / calling `self.loop.reset_interlock()`, same as `app.py`'s `reset_simulation()` today.

**Historian wiring is optional for 9a**, not required for its definition of done — `self.history` (in-memory) is sufficient, same as it is for `app.py` today; Historian is a nice-to-have if there's time, not a blocker.

## API schemas (`backend/schemas.py`)

The one real wrinkle: a tick record's `proposed_action` field is a `ProposedAction` dataclass, not JSON-serializable as-is (`storage/historian.py` already hit this exact problem and solved it by excluding the field — here we actually want it, since the AI reasoning panel needs `confidence`/`rationale`). Same boundary-validation pattern `config_schema.py` already established: a Pydantic model at the edge, nothing downstream has to change.

```python
class ProposedActionOut(BaseModel):
    proposed_output_pct: float
    source: str
    confidence: str | None
    rationale: str | None
    flagged_sensor_concern: bool
    metadata: dict

class TickRecord(BaseModel):
    tick: int
    t_true: float
    t_sensed: float
    setpoint: float
    active_faults: list[str]
    detector_flags: dict[str, bool]
    controller_source: str
    proposed_action: ProposedActionOut
    interlock_result: str
    interlock_reason: str
    override_active: bool
    ai_fallback_active: bool
    interlock_locked_out: bool
    actuator_output: float

    @classmethod
    def from_domain(cls, record: dict) -> "TickRecord": ...  # unpacks record["proposed_action"] into ProposedActionOut
```

Plus one small request model per control action (`ModeRequest{mode}`, `SetpointRequest{setpoint_c}`, `ManualRequest{heater_pct, override_requested}`, `PidGainsRequest{kp,ki,kd}`, `FaultToggleRequest{enabled}`, `RunRequest{running}`, `ResetRequest{seed}`), and a `TriageResponse` mirroring `engine/triage.py`'s `TriageResult`.

## REST surface (`backend/routers/control.py`)

One-for-one with today's Streamlit controls:

| Endpoint | Body | Effect |
|---|---|---|
| `POST /control/mode` | `ModeRequest` | `loop.set_mode(...)` |
| `POST /control/setpoint` | `SetpointRequest` | `loop.set_setpoint(c_to_k(...))` |
| `POST /control/manual` | `ManualRequest` | sets `_manual_heater_pct` + `loop.set_manual_override_requested(...)` |
| `POST /control/pid-gains` | `PidGainsRequest` | `loop.set_pid_gains(...)` |
| `POST /control/faults/drift` | `FaultToggleRequest` | `loop.set_drift(...)` |
| `POST /control/faults/stuck` | `FaultToggleRequest` | `loop.set_stuck(...)` |
| `POST /control/faults/spike` | — | `loop.trigger_spike()` |
| `POST /session/run` | `RunRequest` | `service.start()` / `service.stop()` |
| `POST /session/reset` | `ResetRequest` | rebuild `ControlLoop` |
| `POST /session/reset-interlock` | — | `loop.reset_interlock()` |
| `POST /triage` | — | `triage.request(history=service.history[-window:], detector_flags=...)` -> `TriageResponse` |
| `GET /state` | — | `{history: list[TickRecord], running: bool, mode: str}` -- lets a client that just (re)connected catch up on backlog |

## WebSocket (`backend/routers/stream.py`)

`WS /ws/ticks` — on connect, add the socket to `service._clients`; on `WebSocketDisconnect`, remove it. Deliberately **only** streams new ticks going forward — a client wanting the backlog calls `GET /state` first. Keeping "catch me up" (REST) and "keep me updated" (WebSocket) separate is simpler than making the socket do both.

## `backend/main.py`

`FastAPI()` app with `CORSMiddleware` allowing the Vite dev server's origin (`http://localhost:5173` by default — the gotcha flagged in the walkthrough: this bites on the first cross-origin request if it's not configured up front). A `lifespan` context manager constructs one `SimulationService` on startup (config via the existing `config_schema.load_config()`, `ai_client` via the same `ANTHROPIC_API_KEY`-or-`None` pattern `app.py` already uses) and cancels the tick task on shutdown.

## Testing

- `tests/test_backend_service.py` — unit tests on `SimulationService` directly, no HTTP: start the loop with a short `dt_seconds` override, await a couple of cycles, assert `history` grows; `reset()`/`reset_interlock()` delegate correctly; a fake `WebSocket`-like object in `_clients` receives broadcasts.
- `tests/test_backend_control_api.py` — FastAPI's `TestClient`, POST each control endpoint, assert both the HTTP response and that `service.loop`'s actual state changed (whitebox check, same style already used elsewhere in this suite, e.g. `loop.interlock.locked_out = True`).
- `tests/test_backend_stream_api.py` — `TestClient`'s `websocket_connect()`, start the service ticking with a short `dt`, `receive_json()` a couple of times, assert the shape matches `TickRecord`.

## Explicitly out of scope for 9a

- No React/frontend code (that's 9b).
- No Docker or deployment config (the "local-only" decision).
- No auth/session management (the "single operator" scope, same as the architecture doc's own stated scope).
- Historian wiring is optional, not required.

## Verification, once built

1. `pytest -q` — new backend tests green alongside the existing 113.
2. Manual live check, no UI needed: `uvicorn backend.main:app --reload`, `GET /state`, POST a few control changes and re-`GET` to confirm they landed, connect a raw Python `websockets` client script and print incoming ticks for ~10s, confirm `POST /session/run {"running": true}` starts ticking and `{"running": false}` stops it.
3. This phase's bar is "the API works when driven by scripts/tests" — not "looks good in a browser." That's 9b's job.
