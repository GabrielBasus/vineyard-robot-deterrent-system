from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping


PREASSIGNMENT_SELECTION_POLICIES = (
    "pass_through",
    "priority_top_k",
    "capacity_aware_greedy",
)

# Stable reason-code namespace for the selection stage. Only a subset is used
# today, but the contract is intentionally broader so later policies can grow
# without changing downstream diagnostics or report columns.
PREASSIGNMENT_SELECTION_REJECTION_CODES = (
    "selection_limit",
    "duplicate_candidate",
    "invalid_candidate",
    "stale_candidate",
    "eta_limit",
    "direct_detection_reserved",
    "capacity_exhausted",
    "patrol_capacity_exhausted",
    "model_det_capacity_exhausted",
    "redundant_overlap",
    "utility_below_threshold",
)

_DEFAULT_SELECTION_REDUNDANCY_RADIUS_M = 25.0
_MIN_SELECTION_SCORE = 1.0e-9


@dataclass(frozen=True)
class PreassignmentSelectionContext:
    """Contract for the pre-assignment task-selection stage.

    This stage sits strictly between:
    1. task extraction from SESTPP / recent detections
    2. robot-task assignment / dispatch

    The stage decides which extracted task rows are admitted into assignment,
    but it does not choose which robot receives each admitted task.
    """

    now_t: float
    candidate_tasks: tuple[dict, ...]
    selection_policy: str
    selection_limit: int
    active_load_by_robot: Mapping[str, int]
    active_patrol_load_by_robot: Mapping[str, int]
    active_model_det_load_by_robot: Mapping[str, int]
    max_active_tasks_per_robot: int
    max_active_patrolling_per_robot: int
    max_active_model_deterring_per_robot: int
    preserve_direct_detection_priority: bool

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "now_t": float(self.now_t),
            "selection_policy": str(self.selection_policy),
            "selection_limit": int(self.selection_limit),
            "candidate_count": int(len(self.candidate_tasks)),
            "active_load_by_robot": {str(k): int(v) for k, v in self.active_load_by_robot.items()},
            "active_patrol_load_by_robot": {str(k): int(v) for k, v in self.active_patrol_load_by_robot.items()},
            "active_model_det_load_by_robot": {
                str(k): int(v) for k, v in self.active_model_det_load_by_robot.items()
            },
            "max_active_tasks_per_robot": int(self.max_active_tasks_per_robot),
            "max_active_patrolling_per_robot": int(self.max_active_patrolling_per_robot),
            "max_active_model_deterring_per_robot": int(self.max_active_model_deterring_per_robot),
            "preserve_direct_detection_priority": bool(self.preserve_direct_detection_priority),
        }


@dataclass(frozen=True)
class PreassignmentSelectionResult:
    selection_policy: str
    selected_candidate_tasks: tuple[dict, ...]
    rejected_candidate_tasks: tuple[dict, ...]
    rejected_counts: Mapping[str, int]
    extracted_candidate_count: int
    selected_candidate_count: int

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "selection_policy": str(self.selection_policy),
            "selected_candidate_tasks": [dict(task) for task in self.selected_candidate_tasks],
            "rejected_candidate_tasks": [dict(task) for task in self.rejected_candidate_tasks],
            "rejected_counts": {str(k): int(v) for k, v in self.rejected_counts.items()},
            "extracted_candidate_count": int(self.extracted_candidate_count),
            "selected_candidate_count": int(self.selected_candidate_count),
        }


def build_preassignment_selection_context(
    *,
    now_t: float,
    candidate_tasks: list[dict],
    selection_policy: str,
    selection_limit: int,
    active_load_by_robot: Mapping[str, int] | None = None,
    active_patrol_load_by_robot: Mapping[str, int] | None = None,
    active_model_det_load_by_robot: Mapping[str, int] | None = None,
    max_active_tasks_per_robot: int = 0,
    max_active_patrolling_per_robot: int = 0,
    max_active_model_deterring_per_robot: int = 0,
    preserve_direct_detection_priority: bool = True,
) -> PreassignmentSelectionContext:
    policy_key = str(selection_policy).strip().lower()
    if policy_key not in PREASSIGNMENT_SELECTION_POLICIES:
        raise ValueError(
            "selection_policy must be one of "
            f"{list(PREASSIGNMENT_SELECTION_POLICIES)!r}, got: {selection_policy!r}"
        )
    return PreassignmentSelectionContext(
        now_t=float(now_t),
        candidate_tasks=tuple(dict(task) for task in candidate_tasks),
        selection_policy=str(policy_key),
        selection_limit=max(0, int(selection_limit)),
        active_load_by_robot={str(k): int(v) for k, v in (active_load_by_robot or {}).items()},
        active_patrol_load_by_robot={str(k): int(v) for k, v in (active_patrol_load_by_robot or {}).items()},
        active_model_det_load_by_robot={
            str(k): int(v) for k, v in (active_model_det_load_by_robot or {}).items()
        },
        max_active_tasks_per_robot=max(0, int(max_active_tasks_per_robot)),
        max_active_patrolling_per_robot=max(0, int(max_active_patrolling_per_robot)),
        max_active_model_deterring_per_robot=max(0, int(max_active_model_deterring_per_robot)),
        preserve_direct_detection_priority=bool(preserve_direct_detection_priority),
    )


def _count_rejections(tasks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        reason = str(task.get("selection_rejection_reason", "")).strip().lower()
        if not reason:
            continue
        counts[reason] = int(counts.get(reason, 0) + 1)
    return counts


def _with_rejection_reason(tasks: list[dict], reason: str) -> list[dict]:
    out = []
    for task in tasks:
        row = dict(task)
        row["selection_rejection_reason"] = str(reason)
        out.append(row)
    return out


def _candidate_type(task: dict) -> str:
    return str(task.get("type", "")).strip().lower()


def _candidate_owner(task: dict) -> str | None:
    for key in ("robot_id", "assigned_primary"):
        raw = task.get(key)
        if raw is None:
            continue
        rid = str(raw).strip()
        if rid:
            return rid
    return None


def _candidate_xy(task: dict) -> tuple[float, float] | None:
    try:
        x = float(task.get("x", float("nan")))
        y = float(task.get("y", float("nan")))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return x, y


def _candidate_cost(task: dict) -> float:
    for key in ("cost_eta", "eta_s"):
        try:
            value = float(task.get(key, float("nan")))
        except (TypeError, ValueError):
            value = float("nan")
        if math.isfinite(value) and value > 0.0:
            return value
    return 1.0


def _candidate_benefit(task: dict) -> float:
    cost = _candidate_cost(task)
    predicted_delta_j = float(task.get("predicted_deltaJ", 0.0) or 0.0)
    utility = float(task.get("utility", task.get("score", 0.0)) or 0.0)
    score = float(task.get("score", utility) or 0.0)
    selection_weight = task.get("selection_weight", 1.0)
    try:
        quality = float(selection_weight)
    except (TypeError, ValueError):
        quality = 1.0
    if not math.isfinite(quality) or quality <= 0.0:
        quality = 1.0
    raw_benefit = max(predicted_delta_j, utility + cost, score + cost, 0.0)
    return float(max(raw_benefit, 0.0) * quality)


def _overlap_fraction(task: dict, selected_tasks: list[dict], radius_m: float) -> float:
    task_xy = _candidate_xy(task)
    if task_xy is None or radius_m <= 0.0:
        return 0.0
    tx, ty = task_xy
    radius2 = float(radius_m) ** 2
    overlap = 0.0
    task_type = _candidate_type(task)
    for chosen in selected_tasks:
        chosen_xy = _candidate_xy(chosen)
        if chosen_xy is None:
            continue
        chosen_type = _candidate_type(chosen)
        if chosen_type != task_type:
            continue
        dx = tx - chosen_xy[0]
        dy = ty - chosen_xy[1]
        d2 = dx * dx + dy * dy
        if d2 > radius2:
            continue
        dist = math.sqrt(max(d2, 0.0))
        overlap += max(0.0, 1.0 - dist / max(float(radius_m), 1.0e-9))
    return float(overlap)


def _marginal_selection_score(task: dict, selected_tasks: list[dict], radius_m: float) -> float:
    benefit = _candidate_benefit(task)
    if benefit <= 0.0:
        return 0.0
    cost = _candidate_cost(task)
    novelty = 1.0 / (1.0 + _overlap_fraction(task, selected_tasks, radius_m))
    return float((benefit * novelty) / max(cost, 1.0e-6))


def _initial_capacity_maps(context: PreassignmentSelectionContext) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    robot_ids = set(context.active_load_by_robot) | set(context.active_patrol_load_by_robot) | set(context.active_model_det_load_by_robot)
    total_remaining: dict[str, int] = {}
    patrol_remaining: dict[str, int] = {}
    model_det_remaining: dict[str, int] = {}
    for rid in robot_ids:
        total_cap = max(0, int(context.max_active_tasks_per_robot))
        patrol_cap = max(0, int(context.max_active_patrolling_per_robot))
        model_det_cap = max(0, int(context.max_active_model_deterring_per_robot))
        total_remaining[rid] = max(0, total_cap - int(context.active_load_by_robot.get(rid, 0)))
        patrol_remaining[rid] = max(0, patrol_cap - int(context.active_patrol_load_by_robot.get(rid, 0)))
        model_det_remaining[rid] = max(0, model_det_cap - int(context.active_model_det_load_by_robot.get(rid, 0)))
    return total_remaining, patrol_remaining, model_det_remaining


def _feasibility_rejection_reason(
    task: dict,
    *,
    total_remaining: Mapping[str, int],
    patrol_remaining: Mapping[str, int],
    model_det_remaining: Mapping[str, int],
) -> str | None:
    task_type = _candidate_type(task)
    owner = _candidate_owner(task)
    if task_type not in {"patrolling", "deterring"}:
        return "invalid_candidate"
    if owner is None:
        return "invalid_candidate"
    if int(total_remaining.get(owner, 0)) <= 0:
        return "capacity_exhausted"
    if task_type == "patrolling" and int(patrol_remaining.get(owner, 0)) <= 0:
        return "patrol_capacity_exhausted"
    is_model_det = bool(task.get("mode") not in (None, "", "none")) and task_type == "deterring"
    if is_model_det and int(model_det_remaining.get(owner, 0)) <= 0:
        return "model_det_capacity_exhausted"
    return None


def _reserve_capacity_for_task(
    task: dict,
    *,
    total_remaining: dict[str, int],
    patrol_remaining: dict[str, int],
    model_det_remaining: dict[str, int],
) -> None:
    owner = _candidate_owner(task)
    if owner is None:
        return
    if owner in total_remaining:
        total_remaining[owner] = int(total_remaining.get(owner, 0)) - 1
    task_type = _candidate_type(task)
    if task_type == "patrolling" and owner in patrol_remaining:
        patrol_remaining[owner] = int(patrol_remaining.get(owner, 0)) - 1
    is_model_det = bool(task.get("mode") not in (None, "", "none")) and task_type == "deterring"
    if is_model_det and owner in model_det_remaining:
        model_det_remaining[owner] = int(model_det_remaining.get(owner, 0)) - 1


def _select_capacity_aware_greedy(
    *,
    context: PreassignmentSelectionContext,
    copied: list[dict],
    is_direct_detection_task_fn: Callable[[dict], bool],
    priority_sort_key_fn: Callable[[dict], Any] | None,
) -> PreassignmentSelectionResult:
    total_remaining, patrol_remaining, model_det_remaining = _initial_capacity_maps(context)
    selected: list[dict] = []
    rejected: list[dict] = []

    direct_candidates = [task for task in copied if bool(is_direct_detection_task_fn(task))]
    regular_candidates = [task for task in copied if not bool(is_direct_detection_task_fn(task))]

    if priority_sort_key_fn is not None:
        direct_candidates.sort(key=priority_sort_key_fn, reverse=True)
        regular_candidates.sort(key=priority_sort_key_fn, reverse=True)
    else:
        direct_candidates.sort(key=lambda task: float(task.get("score", 0.0)), reverse=True)
        regular_candidates.sort(key=lambda task: float(task.get("score", 0.0)), reverse=True)

    if bool(context.preserve_direct_detection_priority):
        for task in direct_candidates:
            selected.append(dict(task))
            _reserve_capacity_for_task(
                task,
                total_remaining=total_remaining,
                patrol_remaining=patrol_remaining,
                model_det_remaining=model_det_remaining,
            )
    else:
        regular_candidates = direct_candidates + regular_candidates

    remaining = [dict(task) for task in regular_candidates]
    global_limit = int(context.selection_limit)
    while remaining:
        if global_limit > 0 and len(selected) >= global_limit:
            rejected.extend(_with_rejection_reason(remaining, "selection_limit"))
            break

        best_idx = None
        best_score = float("-inf")
        best_priority = None
        best_reason = None
        for idx, task in enumerate(remaining):
            reason = _feasibility_rejection_reason(
                task,
                total_remaining=total_remaining,
                patrol_remaining=patrol_remaining,
                model_det_remaining=model_det_remaining,
            )
            if reason is not None:
                continue
            score = _marginal_selection_score(task, selected, _DEFAULT_SELECTION_REDUNDANCY_RADIUS_M)
            if score <= _MIN_SELECTION_SCORE:
                continue
            priority = priority_sort_key_fn(task) if priority_sort_key_fn is not None else float(task.get("score", 0.0))
            if (score > best_score) or (score == best_score and best_priority is not None and priority > best_priority) or (
                score == best_score and best_priority is None
            ):
                best_idx = idx
                best_score = float(score)
                best_priority = priority
                best_reason = None

        if best_idx is None:
            for task in remaining:
                reason = _feasibility_rejection_reason(
                    task,
                    total_remaining=total_remaining,
                    patrol_remaining=patrol_remaining,
                    model_det_remaining=model_det_remaining,
                )
                if reason is None:
                    overlap = _overlap_fraction(task, selected, _DEFAULT_SELECTION_REDUNDANCY_RADIUS_M)
                    if overlap > 0.0:
                        reason = "redundant_overlap"
                    else:
                        reason = "utility_below_threshold"
                rejected.extend(_with_rejection_reason([task], reason))
            break

        chosen = remaining.pop(best_idx)
        selected.append(dict(chosen))
        _reserve_capacity_for_task(
            chosen,
            total_remaining=total_remaining,
            patrol_remaining=patrol_remaining,
            model_det_remaining=model_det_remaining,
        )

    return PreassignmentSelectionResult(
        selection_policy=str(context.selection_policy),
        selected_candidate_tasks=tuple(selected),
        rejected_candidate_tasks=tuple(rejected),
        rejected_counts=_count_rejections(rejected),
        extracted_candidate_count=int(len(context.candidate_tasks)),
        selected_candidate_count=int(len(selected)),
    )


def select_preassignment_task_candidates(
    *,
    candidate_tasks: list[dict],
    selection_policy: str,
    selection_limit: int,
    is_direct_detection_task_fn: Callable[[dict], bool],
    priority_sort_key_fn: Callable[[dict], Any] | None = None,
    now_t: float = 0.0,
    active_load_by_robot: Mapping[str, int] | None = None,
    active_patrol_load_by_robot: Mapping[str, int] | None = None,
    active_model_det_load_by_robot: Mapping[str, int] | None = None,
    max_active_tasks_per_robot: int = 0,
    max_active_patrolling_per_robot: int = 0,
    max_active_model_deterring_per_robot: int = 0,
    preserve_direct_detection_priority: bool = True,
) -> dict:
    """Select which extracted tasks are admitted into assignment.

    Contract:
    - input: extracted task rows plus current queue/load context
    - output: admitted task rows plus rejected task rows with reason codes
    - non-goals: robot pairing, Hungarian/greedy assignment, or SESTPP updates

    The current implementation keeps behavior simple on purpose:
    - `pass_through`: admit every extracted task
    - `priority_top_k`: reserve direct detections, then keep the highest-priority
      remaining tasks under a flat global limit
    - `capacity_aware_greedy`: reserve direct detections, then greedily admit
      the best marginal-gain-per-service-cost tasks subject to per-robot queue
      capacity and a spatial redundancy penalty
    """

    context = build_preassignment_selection_context(
        now_t=now_t,
        candidate_tasks=candidate_tasks,
        selection_policy=selection_policy,
        selection_limit=selection_limit,
        active_load_by_robot=active_load_by_robot,
        active_patrol_load_by_robot=active_patrol_load_by_robot,
        active_model_det_load_by_robot=active_model_det_load_by_robot,
        max_active_tasks_per_robot=max_active_tasks_per_robot,
        max_active_patrolling_per_robot=max_active_patrolling_per_robot,
        max_active_model_deterring_per_robot=max_active_model_deterring_per_robot,
        preserve_direct_detection_priority=preserve_direct_detection_priority,
    )

    copied = [dict(task) for task in context.candidate_tasks]
    if context.selection_policy == "pass_through":
        result = PreassignmentSelectionResult(
            selection_policy=str(context.selection_policy),
            selected_candidate_tasks=tuple(copied),
            rejected_candidate_tasks=tuple(),
            rejected_counts={},
            extracted_candidate_count=int(len(context.candidate_tasks)),
            selected_candidate_count=int(len(copied)),
        )
        return result.to_public_dict()

    if context.selection_policy == "capacity_aware_greedy":
        result = _select_capacity_aware_greedy(
            context=context,
            copied=copied,
            is_direct_detection_task_fn=is_direct_detection_task_fn,
            priority_sort_key_fn=priority_sort_key_fn,
        )
        return result.to_public_dict()

    direct_candidates = [task for task in copied if bool(is_direct_detection_task_fn(task))]
    regular_candidates = [task for task in copied if not bool(is_direct_detection_task_fn(task))]
    if priority_sort_key_fn is not None:
        regular_candidates.sort(key=priority_sort_key_fn, reverse=True)
    else:
        regular_candidates.sort(key=lambda task: float(task.get("score", 0.0)), reverse=True)

    if int(context.selection_limit) > 0:
        keep_regular = max(0, int(context.selection_limit) - len(direct_candidates))
        selected_regular = regular_candidates[:keep_regular]
        rejected_regular = _with_rejection_reason(regular_candidates[keep_regular:], "selection_limit")
    else:
        selected_regular = regular_candidates
        rejected_regular = []

    selected = direct_candidates + selected_regular
    result = PreassignmentSelectionResult(
        selection_policy=str(context.selection_policy),
        selected_candidate_tasks=tuple(selected),
        rejected_candidate_tasks=tuple(rejected_regular),
        rejected_counts=_count_rejections(rejected_regular),
        extracted_candidate_count=int(len(context.candidate_tasks)),
        selected_candidate_count=int(len(selected)),
    )
    return result.to_public_dict()
