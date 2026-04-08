from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AssignmentSelection:
    task_type: str
    is_model_det: bool
    assigned_primary: str | None
    assigned_secondary: str | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "task_type": str(self.task_type),
            "is_model_det": bool(self.is_model_det),
            "assigned_primary": (None if self.assigned_primary is None else str(self.assigned_primary)),
            "assigned_secondary": (None if self.assigned_secondary is None else str(self.assigned_secondary)),
        }


@dataclass(frozen=True)
class ModelDeterringDispatchGateResult:
    reason: str | None
    task_utility: float
    budget_mode: str
    budget_queue: deque | None

    def to_public_dict(self) -> dict[str, Any]:
        queue_len = 0 if self.budget_queue is None else len(self.budget_queue)
        return {
            "reason": (None if self.reason is None else str(self.reason)),
            "task_utility": float(self.task_utility),
            "budget_mode": str(self.budget_mode),
            "budget_queue_length": int(queue_len),
            "budget_queue": (None if self.budget_queue is None else list(self.budget_queue)),
        }


def select_assignment(
    *,
    task_row: dict,
    active_load: dict,
    assigner: Any,
    prefer_idle_for_model_deterring: bool,
    is_model_deterring_candidate_fn: Callable[[dict], bool],
) -> AssignmentSelection:
    assigner.set_load(active_load)
    is_model_det = bool(is_model_deterring_candidate_fn(task_row))
    task_type = str(task_row.get("type", "")).strip().lower()
    res = None
    if is_model_det and bool(prefer_idle_for_model_deterring):
        idle_robot_ids = [
            str(rid)
            for rid, load in active_load.items()
            if int(load) <= 0
        ]
        if idle_robot_ids:
            res = assigner.assign_task(task_row, eligible_ids=idle_robot_ids)
    if res is None:
        res = assigner.assign_task(task_row)
    return AssignmentSelection(
        task_type=str(task_type),
        is_model_det=bool(is_model_det),
        assigned_primary=(None if res is None else res["primary"]),
        assigned_secondary=(None if res is None else res["secondary"]),
    )


def passes_busy_fallback_quality(
    *,
    task_row: dict,
    p_event_min: float,
    deltaJ_per_cost_min: float,
    eta_s_max: float,
) -> bool:
    p_event = float(task_row.get("p_event", 0.0))
    deltaJ_per_cost = float(task_row.get("deltaJ_per_cost", 0.0))
    eta_s = float(task_row.get("eta_s", float("inf")))
    return (
        p_event >= float(p_event_min)
        and deltaJ_per_cost >= float(deltaJ_per_cost_min)
        and eta_s <= float(eta_s_max)
    )


def has_direct_detection_conflict(
    *,
    task_row: dict,
    assigned_primary: str,
    active_tasks: list[dict],
    completed_tasks: list[dict],
    now_t: float,
    protect_direct_detection_from_model_deterring: bool,
    direct_conflict_radius_m: float,
    direct_conflict_window_s: float,
    deterring_source_fn: Callable[[dict], str],
) -> bool:
    if not bool(protect_direct_detection_from_model_deterring):
        return False
    tx = float(task_row.get("x", 0.0))
    ty = float(task_row.get("y", 0.0))
    direct_r2 = float(direct_conflict_radius_m) ** 2
    direct_window = float(direct_conflict_window_s)
    for tr in active_tasks:
        if str(tr.get("state", "")).strip().lower() != "active":
            continue
        if str(tr.get("type", "")).strip().lower() != "deterring":
            continue
        if deterring_source_fn(tr) != "direct_detection":
            continue
        if str(tr.get("assigned_primary")) == str(assigned_primary):
            return True
        dx = tx - float(tr.get("x", 0.0))
        dy = ty - float(tr.get("y", 0.0))
        if (dx * dx + dy * dy) <= direct_r2:
            return True
    if direct_window <= 0.0:
        return False
    for tr in reversed(completed_tasks):
        if str(tr.get("type", "")).strip().lower() != "deterring":
            continue
        if deterring_source_fn(tr) != "direct_detection":
            continue
        t_done = float(tr.get("t_done", -1e18))
        if (float(now_t) - t_done) > direct_window:
            break
        dx = tx - float(tr.get("x", 0.0))
        dy = ty - float(tr.get("y", 0.0))
        if (dx * dx + dy * dy) <= direct_r2:
            return True
    return False


def evaluate_model_deterring_dispatch_gating(
    *,
    task_row: dict,
    assigned_primary: str,
    assigned_primary_busy: bool,
    accepted_this_cycle: int,
    active_model_det_load_map: dict,
    now_t: float,
    model_deterring_global_admission_cap_per_cycle: int,
    model_deterring_require_idle_robot_for_admission: bool,
    model_deterring_budget_mode: str,
    model_deterring_budget_per_robot_per_hr: int,
    model_deterring_budget_utility_per_robot_per_hr: float,
    max_active_model_deterring_per_robot: int,
    model_deterring_by_robot: dict,
    dispatch_task_value_fn: Callable[[dict], float],
    is_model_deterring_candidate_fn: Callable[[dict], bool],
    direct_conflict_fn: Callable[[dict, str], bool],
    busy_fallback_quality_fn: Callable[[dict], bool],
) -> ModelDeterringDispatchGateResult:
    task_utility = max(0.0, float(dispatch_task_value_fn(task_row)))
    budget_mode_local = "count_per_hour"
    if not bool(is_model_deterring_candidate_fn(task_row)):
        return ModelDeterringDispatchGateResult(
            reason=None,
            task_utility=float(task_utility),
            budget_mode=str(budget_mode_local),
            budget_queue=None,
        )
    if (
        int(model_deterring_global_admission_cap_per_cycle) > 0
        and int(accepted_this_cycle) >= int(model_deterring_global_admission_cap_per_cycle)
    ):
        return ModelDeterringDispatchGateResult("cycle_cap", float(task_utility), str(budget_mode_local), None)
    if bool(model_deterring_require_idle_robot_for_admission) and bool(assigned_primary_busy):
        return ModelDeterringDispatchGateResult("busy_primary", float(task_utility), str(budget_mode_local), None)
    if bool(assigned_primary_busy) and (not bool(model_deterring_require_idle_robot_for_admission)):
        if not bool(busy_fallback_quality_fn(task_row)):
            return ModelDeterringDispatchGateResult(
                "busy_fallback_quality",
                float(task_utility),
                str(budget_mode_local),
                None,
            )
    if bool(direct_conflict_fn(task_row, assigned_primary)):
        return ModelDeterringDispatchGateResult("direct_conflict", float(task_utility), str(budget_mode_local), None)
    if int(active_model_det_load_map.get(assigned_primary, 0)) >= int(max_active_model_deterring_per_robot):
        return ModelDeterringDispatchGateResult("model_det_cap", float(task_utility), str(budget_mode_local), None)

    q = deque(model_deterring_by_robot.get(assigned_primary, deque()))
    while q and float(q[0][0]) < (float(now_t) - 3600.0):
        q.popleft()
    budget_mode_local = str(model_deterring_budget_mode).strip().lower()
    if budget_mode_local not in ("count_per_hour", "utility_per_hour"):
        budget_mode_local = "count_per_hour"
    over_budget = False
    if budget_mode_local == "utility_per_hour":
        util_budget = max(0.0, float(model_deterring_budget_utility_per_robot_per_hr))
        spent_utility = float(sum(float(u) for (_ts, u) in q))
        over_budget = (spent_utility + float(task_utility)) > util_budget
    else:
        over_budget = len(q) >= int(model_deterring_budget_per_robot_per_hr)
    if over_budget:
        return ModelDeterringDispatchGateResult("budget", float(task_utility), str(budget_mode_local), None)
    return ModelDeterringDispatchGateResult(None, float(task_utility), str(budget_mode_local), q)
