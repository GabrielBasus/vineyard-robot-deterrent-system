from __future__ import annotations

from collections import deque
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import numpy as np


_MAX_TRACKING_DEPTH = 6


def summarize_ndarray(array: np.ndarray) -> dict[str, Any]:
    arr = np.asarray(array)
    summary: dict[str, Any] = {
        "kind": "ndarray",
        "shape": [int(v) for v in arr.shape],
        "dtype": str(arr.dtype),
        "size": int(arr.size),
    }
    if arr.size <= 0:
        summary.update({"min": None, "max": None, "mean": None, "sum": 0.0})
        return summary
    if np.issubdtype(arr.dtype, np.number):
        flat = arr.astype(float, copy=False).ravel()
        finite = flat[np.isfinite(flat)]
        if finite.size > 0:
            summary.update(
                {
                    "min": float(np.min(finite)),
                    "max": float(np.max(finite)),
                    "mean": float(np.mean(finite)),
                    "sum": float(np.sum(finite)),
                }
            )
        else:
            summary.update({"min": None, "max": None, "mean": None, "sum": 0.0})
    return summary


def export_tracking_value(
    value: Any,
    *,
    include_arrays: bool = False,
    max_items: int = 50,
    _depth: int = 0,
    _seen: set[int] | None = None,
) -> Any:
    if _seen is None:
        _seen = set()

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, ModuleType):
        return {"kind": "module", "name": str(getattr(value, "__name__", repr(value)))}
    if callable(value):
        return {"kind": "callable", "repr": repr(value)}

    object_id = id(value)
    if object_id in _seen:
        return {"kind": "reference", "repr": repr(value)}
    if _depth >= _MAX_TRACKING_DEPTH:
        return {"kind": "max_depth", "repr": repr(value)}

    if isinstance(value, np.ndarray):
        return np.array(value, copy=True) if include_arrays else summarize_ndarray(value)

    if hasattr(value, "to_tracking_dict") and callable(getattr(value, "to_tracking_dict")):
        _seen.add(object_id)
        try:
            return value.to_tracking_dict(include_arrays=include_arrays, max_items=max_items)
        finally:
            _seen.discard(object_id)

    if is_dataclass(value):
        _seen.add(object_id)
        try:
            return export_tracking_value(
                asdict(value),
                include_arrays=include_arrays,
                max_items=max_items,
                _depth=_depth + 1,
                _seen=_seen,
            )
        finally:
            _seen.discard(object_id)

    if isinstance(value, Mapping):
        _seen.add(object_id)
        try:
            return {
                str(key): export_tracking_value(
                    inner_value,
                    include_arrays=include_arrays,
                    max_items=max_items,
                    _depth=_depth + 1,
                    _seen=_seen,
                )
                for key, inner_value in value.items()
            }
        finally:
            _seen.discard(object_id)

    if isinstance(value, deque):
        value = list(value)

    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        preview = [
            export_tracking_value(
                item,
                include_arrays=include_arrays,
                max_items=max_items,
                _depth=_depth + 1,
                _seen=_seen,
            )
            for item in seq[: max(int(max_items), 0)]
        ]
        if len(seq) <= max_items:
            return preview
        return {
            "items": preview,
            "preview_count": int(len(preview)),
            "total_count": int(len(seq)),
            "truncated_count": int(len(seq) - len(preview)),
        }

    if hasattr(value, "__dict__") and value.__class__.__module__ != "builtins":
        _seen.add(object_id)
        try:
            payload = {"__class__": value.__class__.__name__}
            for key, inner_value in vars(value).items():
                if callable(inner_value):
                    continue
                payload[str(key)] = export_tracking_value(
                    inner_value,
                    include_arrays=include_arrays,
                    max_items=max_items,
                    _depth=_depth + 1,
                    _seen=_seen,
                )
            return payload
        finally:
            _seen.discard(object_id)

    return repr(value)


def export_named_tracking_state(
    values: Mapping[str, Any],
    *,
    include_arrays: bool = False,
    max_items: int = 50,
    skip_names: set[str] | None = None,
) -> dict[str, Any]:
    skip = set(skip_names or set())
    payload: dict[str, Any] = {}
    for name, value in values.items():
        name_str = str(name)
        if name_str in skip or name_str.startswith("__"):
            continue
        if isinstance(value, ModuleType) or callable(value):
            continue
        payload[name_str] = export_tracking_value(
            value,
            include_arrays=include_arrays,
            max_items=max_items,
        )
    return payload
