"""Fault detection: Tier 1 statistical (fast, deterministic, gates the
interlock) + Tier 2 LLM triage (advisory-only, never feeds the interlock).

Tier 1 implemented in Phase 4, Tier 2 in Phase 7.
See docs/control-loop-architecture.md §3.5.
"""
