"""
habituation_stl -- reusable components for the habituation-aware STL task-value
direction of the vineyard multi-robot deterrence thesis.

Modules
-------
stl            : STL robustness monitor (classical + smooth), future & past ops
habituation    : per-(cell, mode) effectiveness dynamics (recovery + habituation)
mission_spec   : the four mission clauses (exposure, react, coverage, anti-hab)
task_value     : counterfactual robustness task value U(a,r) + forward predictor
signals        : decentralized online robustness monitor (Algorithm 1)
dispatch       : reserved-capacity dispatch with robustness value (Algorithm 3)
metrics        : run-level metrics (J_exp, robustness, variety, eta_bar, ...)
reference_sim  : compact runnable smoke-test simulator
experiment     : baseline-ladder driver (B0..B4) with habituation on/off control

See README_INTEGRATION.md for wiring into the existing DeterrentSystem codebase.
"""
import os as _os
import sys as _sys

# Allow both usage modes:
#   (a) run scripts from inside this directory  (python run_demo.py)
#   (b) import the package from a parent dir     (import habituation_stl)
# The submodules use flat absolute imports (e.g. `from stl import ...`), so we
# put this directory on sys.path before importing them.
_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

from . import stl, habituation, mission_spec, task_value, signals, dispatch, metrics  # noqa: E402,F401

__all__ = ["stl", "habituation", "mission_spec", "task_value", "signals",
           "dispatch", "metrics"]
