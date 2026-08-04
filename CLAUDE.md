# Control Loop Simulation — project status

Read `README.md` and `docs/control-loop-architecture.md` first — they're the source of truth for design decisions. This file is just a pointer to where things stand.

## Status: Phase 0 (scaffolding) complete, not yet verified

Repo structure, `PlantModel`/`Controller` interfaces + registry pattern, `config.yaml`, `docker-compose.yml`, and a pytest scaffold are committed (`git log` shows the one commit so far). **None of it has been run yet** — this machine is missing the README's own prerequisites:

- Python 3.12 (`python3 --version` here is 3.9.6)
- Docker (needed for the TimescaleDB container)
- `gh`

The user is installing these themselves, then coming back to this session.

## Next steps once prerequisites are installed

1. `python3.12 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
2. `docker compose up -d` and confirm `docker ps` shows `timescaledb` (container isn't written to yet — see decision below)
3. Copy `.env.example` to `.env`, fill in `ANTHROPIC_API_KEY`
4. Run `pytest` to sanity-check the scaffold — note `engine/controllers/base.py` uses `str | None` union syntax (PEP 604), which requires Python 3.10+ and will fail to import on anything older
5. Start Phase 1 (see task list / build order below)

## Build order (tracked as tasks #1-#9, #1 done)

Follows architecture doc §5, with two adjustments the user explicitly approved:
- **Historian writes deferred to Phase 4**, not wired early — `docker-compose.yml` stands up TimescaleDB as infra now, but the batched async writer (`storage/historian.py`) doesn't get implemented until Phase 4, alongside the interlock's sensor-trust gate. Keeps Phases 1-3 focused on physics/control logic.
- **Tests embedded per phase**, not a separate testing pass at the end — each phase that introduces new logic ships with a small pytest suite of known-outcome scenarios as part of its definition of done (this directly addresses a gap the architecture doc calls out in §10).

Phases: (1) plant + manual control, (2) PID + mode toggle, (3) sensor fault injection, (4) Tier-1 statistical detector + interlock sensor-trust gate + historian wiring, (5) AI controller, (6) interlock bounds/rate-limit checks vs. AI + decision log UI, (7) Tier-2 LLM triage, (8) README/docs/walkthrough polish.

Deferred to stretch goals (per doc §9, §11 — not in the numbered build order): FastAPI/WebSocket service split, second-order plant model, Redis hot path, Delta Lake alternative, multi-loop interlock demo.
