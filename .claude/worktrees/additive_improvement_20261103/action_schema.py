from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Literal, Mapping


ActionKind = Literal["deterring", "patrolling"]


@dataclass(frozen=True)
class ActionSpec:
    kind: ActionKind
    name: str
    params: dict[str, Any]
    service_time_s: float

    def to_public_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable action payload for telemetry and structured exports."""
        return {
            "kind": str(self.kind),
            "name": str(self.name),
            "params": dict(self.params),
            "service_time_s": float(self.service_time_s),
        }


def _coerce_action(action_value: Any) -> ActionSpec | None:
    """Normalize an existing action-like object into an ActionSpec when possible."""
    if action_value is None:
        return None
    if isinstance(action_value, ActionSpec):
        return action_value
    if is_dataclass(action_value):
        payload = asdict(action_value)
    elif isinstance(action_value, Mapping):
        payload = dict(action_value)
    else:
        return None
    kind = str(payload.get("kind", "patrolling")).strip().lower()
    if kind not in {"deterring", "patrolling"}:
        kind = "patrolling"
    return ActionSpec(
        kind=kind,  # type: ignore[arg-type]
        name=str(payload.get("name", "unknown")),
        params=dict(payload.get("params", {}) or {}),
        service_time_s=max(float(payload.get("service_time_s", 0.0)), 0.0),
    )


def make_detection_action(service_time_s: float) -> ActionSpec:
    """Create the canonical reactive direct-detection deterrence action."""
    return ActionSpec(
        kind="deterring",
        name="direct_detection",
        params={},
        service_time_s=max(float(service_time_s), 0.0),
    )


def make_deterring_mode_action(
    mode: str,
    deterring_modes: Mapping[str, Mapping[str, Any]] | None,
    service_time_s: float,
) -> ActionSpec:
    """Create a predictive deterrence action for a named cue mode."""
    mode_name = str(mode or "unknown").strip()
    params = dict((deterring_modes or {}).get(mode_name, {}) or {})
    return ActionSpec(
        kind="deterring",
        name=mode_name or "unknown",
        params=params,
        service_time_s=max(float(service_time_s), 0.0),
    )


def make_patrol_action(origin: str | None) -> ActionSpec:
    """Create the canonical patrol action used by predictive patrol tasks."""
    origin_key = str(origin or "").strip().lower()
    if origin_key == "fallback":
        name = "fallback_patrol"
    else:
        name = "hotspot_patrol"
    return ActionSpec(
        kind="patrolling",
        name=name,
        params={},
        service_time_s=0.0,
    )


def task_action(
    task_row: Mapping[str, Any],
    deterring_modes: Mapping[str, Mapping[str, Any]] | None = None,
    default_service_time_s: float = 0.0,
) -> ActionSpec:
    """Resolve the canonical ActionSpec for a task row, preserving explicit action metadata when present."""
    existing = _coerce_action(task_row.get("action"))
    if existing is not None:
        return existing

    task_type = str(task_row.get("type", "")).strip().lower()
    if task_type == "patrolling":
        return make_patrol_action(task_row.get("origin"))

    if task_type == "deterring":
        mode = task_row.get("mode")
        if mode in (None, "", "none"):
            return make_detection_action(default_service_time_s)
        return make_deterring_mode_action(
            str(mode),
            deterring_modes=deterring_modes,
            service_time_s=default_service_time_s,
        )

    return ActionSpec(
        kind="patrolling",
        name="unknown",
        params={},
        service_time_s=0.0,
    )


def task_action_kind(
    task_row: Mapping[str, Any],
    deterring_modes: Mapping[str, Mapping[str, Any]] | None = None,
    default_service_time_s: float = 0.0,
) -> str:
    """Return the normalized action kind for dispatch and metrics code."""
    return str(task_action(task_row, deterring_modes, default_service_time_s).kind)


def task_action_name(
    task_row: Mapping[str, Any],
    deterring_modes: Mapping[str, Mapping[str, Any]] | None = None,
    default_service_time_s: float = 0.0,
) -> str:
    """Return the normalized action name used for mode identity and routing decisions."""
    return str(task_action(task_row, deterring_modes, default_service_time_s).name)


def task_action_service_time_s(
    task_row: Mapping[str, Any],
    deterring_modes: Mapping[str, Mapping[str, Any]] | None = None,
    default_service_time_s: float = 0.0,
) -> float:
    """Return the normalized service time required by the task action."""
    return float(task_action(task_row, deterring_modes, default_service_time_s).service_time_s)


def task_action_public_dict(
    task_row: Mapping[str, Any],
    deterring_modes: Mapping[str, Mapping[str, Any]] | None = None,
    default_service_time_s: float = 0.0,
) -> dict[str, Any]:
    """Return the public action payload for a task row."""
    return task_action(task_row, deterring_modes, default_service_time_s).to_public_dict()
