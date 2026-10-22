"""
planner_committed_schedule.py -- a robot's committed schedule for the planner's forecast.

Plan Section 2 (variant B, user decision 5): the pending-intervention timeline
used for q_hat must contain every committed application known to the planner,
timed by the robot's committed schedule, and a candidate's lead delta_a must
include the robot's remaining time on its current task and committed queue.

In the B4 ("res") pipeline the order in which a robot serves its assigned tasks
is not stored: the simulator re-applies the dispatch rule
(_select_dispatch_policy_task) every step.  This module therefore EMULATES the
simulator's per-step dispatch loop for one robot (DeterrentSystem Stage 4,
non-"unc" branch with preempt_deterring_goals=True, no hysteresis margin,
no preempt_predictive_with_reactive) on the robot's committed tasks only:

  each step t (simulator dt), starting at the decision time:
    if not holding: (task, urgent) = dispatch rule at t from the emulated pose
        with the robot's predictive-time tracker advanced by the emulation;
        urgent and different from the current goal -> switch goal;
        no goal -> take the rule's task;
        move toward the goal by speed * dt;
    goal reached (within arrival_radius_m) -> deterring task: start the hold,
        complete when t >= hold start + service time; patrol: complete;
        goal without a task (an idle-roam leg): drop the goal;
    record [t, t + dt] in the tracker under the goal task's stream (or idle).

Stated modelling conditions of the emulation (see the report / open questions):
  * only the committed tasks (no new arrivals, prunings, expiries or reassignments);
  * motion and the rule's travel estimates use the planner's travel model
    (straight line at the profile speed plus spin-up), the same model used for a
    candidate's travel time in TaskGenerator;
  * a robot left without a task by the rule (e.g. the ceiling) stays in place;
  * emulation stops at decision time + horizon; a robot not free by then has
    free_t = inf.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional


def emulate_robot_schedule(
    *,
    now_t: float,
    dt: float,
    horizon_s: float,
    pose: tuple[float, float],
    speed_mps: float,
    spin_s: float,
    arrival_radius_m: float,
    loiter_until: float,
    goal_xy: Optional[tuple[float, float]],
    tasks: list[dict],
    service_s_fn: Callable[[dict], float],
    is_deterring_fn: Callable[[dict], bool],
    stream_fn: Callable[[dict], str],
    select_fn: Callable[..., tuple[Optional[dict], bool]],
    tracker: Any = None,
) -> dict:
    """Emulate one robot's dispatch loop on its committed tasks.

    tasks       : the robot's committed task rows (never mutated), in active_tasks order.
    select_fn   : select_fn(tasks, t, eta_seconds_fn, predictive_share, robot_is_idle)
                  -> (task | None, urgent), the simulator's dispatch rule.
    tracker     : a COPY of the robot's SlidingWindowTimeTracker (advanced here) or None.
    Returns {"completions": [(task, t_complete)], "free_t": float, "free_xy": (x, y)}.
    free_t is the first step at which the robot is free of every committed task
    (completion step + dt), now_t if it has none, inf if not free within the horizon.
    """
    dt = float(dt)
    speed = max(float(speed_mps), 1e-6)
    spin = float(spin_s)
    radius = float(arrival_radius_m)
    pos = [float(pose[0]), float(pose[1])]
    remaining = list(tasks)
    started = {id(tr): tr.get("started_hold") for tr in remaining}
    completions: list[tuple[dict, float]] = []
    if not remaining:
        return {"completions": completions, "free_t": float(now_t), "free_xy": (pos[0], pos[1])}

    goal = None if goal_xy is None else (float(goal_xy[0]), float(goal_xy[1]))
    loiter = float(loiter_until)

    def _eta(task_row):
        return math.hypot(float(task_row.get("x", 0.0)) - pos[0], float(task_row.get("y", 0.0)) - pos[1]) / speed + spin

    def _goal_task():
        if goal is None:
            return None
        for tr in remaining:
            if math.hypot(float(tr["x"]) - goal[0], float(tr["y"]) - goal[1]) <= radius:
                return tr
        return None

    t = float(now_t)
    t_stop = float(now_t) + float(horizon_s)
    while remaining and t < t_stop - 1e-9:
        if not (loiter > t):
            share = 0.0 if tracker is None else float(tracker.predictive_share(t))
            idle = goal is None and loiter <= t
            policy_task, urgent = select_fn(remaining, t, _eta, share, idle)
            cur = _goal_task()
            if urgent and policy_task is not None:
                if cur is None or id(cur) != id(policy_task):
                    goal = (float(policy_task["x"]), float(policy_task["y"]))
            elif goal is None and policy_task is not None:
                goal = (float(policy_task["x"]), float(policy_task["y"]))
            if goal is not None:
                dx, dy = goal[0] - pos[0], goal[1] - pos[1]
                dist = math.hypot(dx, dy)
                step = speed * dt
                if dist > 1e-6:
                    if step >= dist:
                        pos = [goal[0], goal[1]]
                    else:
                        pos = [pos[0] + dx * step / dist, pos[1] + dy * step / dist]
        cur = _goal_task()
        stream = "idle" if cur is None else str(stream_fn(cur))
        if goal is not None and math.hypot(pos[0] - goal[0], pos[1] - goal[1]) <= radius:
            matched = None
            for tr in remaining:
                if math.hypot(pos[0] - float(tr["x"]), pos[1] - float(tr["y"])) <= radius:
                    matched = tr
                    break
            if matched is None:
                goal = None
            elif is_deterring_fn(matched):
                if started[id(matched)] is None:
                    started[id(matched)] = t
                    loiter = t + float(service_s_fn(matched))
                elif t >= float(started[id(matched)]) + float(service_s_fn(matched)):
                    completions.append((matched, t))
                    remaining = [tr for tr in remaining if tr is not matched]
                    goal = None
            else:
                completions.append((matched, t))
                remaining = [tr for tr in remaining if tr is not matched]
                goal = None
        if tracker is not None:
            tracker.record(t, t + dt, stream)
        t += dt
    free_t = (completions[-1][1] + dt) if not remaining else math.inf
    return {"completions": completions, "free_t": float(free_t), "free_xy": (pos[0], pos[1])}
