"""Deterministic safety interlock — no LLM calls in this path, ever.

Checks applied in order, first failure wins: sensor-trust gate, absolute
bounds (present-state only, no lookahead), slew-rate limit, pass-through.
Sensor-trust gate implemented in Phase 4; bounds/rate-limit checks against
AI proposals in Phase 6.
See docs/control-loop-architecture.md §3.4.
"""
