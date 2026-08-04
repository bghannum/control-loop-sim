"""Sensor model: wraps true plant temperature, applies active fault modes.

The only place faults are injected — controllers and detectors always see
"reading," never ground truth. Implemented in Phase 3.
See docs/control-loop-architecture.md §3.2.
"""
