"""Ties one control-loop tick together: sensor read -> detector eval ->
controller propose -> interlock decide -> plant step -> log.

Implemented incrementally starting Phase 1 (plant + manual only) and grows
a stage at a time per docs/control-loop-architecture.md §5.
"""
