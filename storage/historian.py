"""Batched, async writes to TimescaleDB — never blocks the control loop.

The control loop only ever writes to the in-memory hot path; a separate
background writer periodically flushes accumulated ticks to the historian.
Wiring deferred to Phase 4 so early phases aren't coupled to persistence.
See docs/control-loop-architecture.md §7.4.
"""
