"""Simplification-stage helpers for incremental thesis-system testing."""

from .stages import SIMPLIFICATION_STAGE_ORDER, SimplificationStage, get_stage, iter_stages

__all__ = [
    "SIMPLIFICATION_STAGE_ORDER",
    "SimplificationStage",
    "get_stage",
    "iter_stages",
]
