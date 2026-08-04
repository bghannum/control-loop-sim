"""Streamlit entrypoint. Grows one build-order stage at a time —
see docs/control-loop-architecture.md §5. Phase 1 adds the first
real content: a manual-control slider driving the plant model.
"""

import streamlit as st

st.set_page_config(page_title="Control Loop Simulation", layout="wide")
st.title("Safety-Constrained AI Control Loop")
st.caption("Scaffolding only — Phase 1 (plant + manual control) not yet implemented.")
