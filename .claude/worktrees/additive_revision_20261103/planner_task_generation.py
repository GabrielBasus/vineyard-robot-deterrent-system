from __future__ import annotations

from collections import deque
from typing import Iterable

import numpy as np

from planner_task_extraction import build_task_dispatch_candidate_buffer, run_task_location_estimation


def prune_preventive_histories(
    *,
    now_t: float,
    robot_ids: Iterable[str],
    history_window_s: float,
    model_deterring_by_robot: dict,
    service_history_by_robot: dict,
    direct_deterring_arrivals_by_robot: dict,
    model_deterring_admissions_by_robot: dict,
) -> None:
    cutoff = float(now_t) - max(float(history_window_s), 1.0)
    for rid in robot_ids:
        q_budget = model_deterring_by_robot.get(rid, deque())
        while q_budget and float(q_budget[0][0]) < (float(now_t) - 3600.0):
            q_budget.popleft()
        model_deterring_by_robot[rid] = q_budget

        q_service = service_history_by_robot.get(rid, deque())
        while q_service and float(q_service[0][0]) < cutoff:
            q_service.popleft()
        service_history_by_robot[rid] = q_service

        q_direct = direct_deterring_arrivals_by_robot.get(rid, deque())
        while q_direct and float(q_direct[0]) < cutoff:
            q_direct.popleft()
        direct_deterring_arrivals_by_robot[rid] = q_direct

        q_model = model_deterring_admissions_by_robot.get(rid, deque())
        while q_model and float(q_model[0]) < cutoff:
            q_model.popleft()
        model_deterring_admissions_by_robot[rid] = q_model


def compute_preventive_capacity_state(
    *,
    now_t: float,
    robot_ids: Iterable[str],
    history_window_s: float,
    rho_max: float,
    min_completed: int,
    budget_mode: str,
    fallback_budget_per_hr: float,
    model_deterring_by_robot: dict,
    service_history_by_robot: dict,
    direct_deterring_arrivals_by_robot: dict,
    model_deterring_admissions_by_robot: dict,
    preventive_service_rate_snapshot: dict,
    preventive_direct_arrival_rate_snapshot: dict,
    preventive_capacity_remaining_snapshot: dict,
    preventive_capacity_ready_snapshot: dict,
) -> dict:
    prune_preventive_histories(
        now_t=now_t,
        robot_ids=robot_ids,
        history_window_s=history_window_s,
        model_deterring_by_robot=model_deterring_by_robot,
        service_history_by_robot=service_history_by_robot,
        direct_deterring_arrivals_by_robot=direct_deterring_arrivals_by_robot,
        model_deterring_admissions_by_robot=model_deterring_admissions_by_robot,
    )

    hist_window = max(float(history_window_s), 1.0)
    rho_cap = max(0.0, float(rho_max))
    min_completed_tasks = max(1, int(min_completed))
    budget_mode_key = str(budget_mode).strip().lower()
    remaining = {}
    ready = {}
    remain_vals = []
    service_vals = []
    direct_vals = []

    for rid in robot_ids:
        q_service = service_history_by_robot.get(rid, deque())
        service_times = [float(st) for (_td, st) in q_service if float(st) > 1e-9]
        if len(service_times) >= min_completed_tasks:
            mean_service = float(np.mean(service_times))
            mu_r = 3600.0 / max(mean_service, 1e-9)
            lam_direct = 3600.0 * float(len(direct_deterring_arrivals_by_robot.get(rid, deque()))) / hist_window
            lam_model = 3600.0 * float(len(model_deterring_admissions_by_robot.get(rid, deque()))) / hist_window
            lam_prev_max = max(0.0, rho_cap * mu_r - lam_direct)
            rem = max(0.0, lam_prev_max - lam_model)
            ready[rid] = True
            remaining[rid] = float(rem)
            preventive_service_rate_snapshot[rid] = float(mu_r)
            preventive_direct_arrival_rate_snapshot[rid] = float(lam_direct)
            preventive_capacity_remaining_snapshot[rid] = float(rem)
            preventive_capacity_ready_snapshot[rid] = True
            remain_vals.append(float(rem))
            service_vals.append(float(mu_r))
            direct_vals.append(float(lam_direct))
            continue

        ready[rid] = False
        preventive_service_rate_snapshot[rid] = float("nan")
        preventive_direct_arrival_rate_snapshot[rid] = float("nan")
        if budget_mode_key == "count_per_hour":
            q_budget = model_deterring_by_robot.get(rid, deque())
            rem = max(0.0, float(fallback_budget_per_hr) - float(len(q_budget)))
        else:
            rem = float("nan")
        remaining[rid] = float(rem)
        preventive_capacity_remaining_snapshot[rid] = float(rem)
        preventive_capacity_ready_snapshot[rid] = False
        if np.isfinite(rem):
            remain_vals.append(float(rem))

    return {
        "remaining": remaining,
        "ready": ready,
        "remain_vals": remain_vals,
        "service_vals": service_vals,
        "direct_vals": direct_vals,
    }


def current_busy_deterring_robots(active_tasks: list[dict]) -> set[str]:
    return {
        str(tr.get("assigned_primary"))
        for tr in active_tasks
        if (
            str(tr.get("state", "")).strip().lower() == "active"
            and str(tr.get("type", "")).strip().lower() == "deterring"
            and tr.get("assigned_primary") is not None
        )
    }
