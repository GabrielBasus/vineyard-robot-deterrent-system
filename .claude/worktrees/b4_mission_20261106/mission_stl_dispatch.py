"""Four-clause, all-stream dispatch from planner-only immutable inputs.

This module has no simulator dependency and cannot read truth state. It uses
the explicit pending-queue and forecast approximations in MISSION_SPECIFICATION.md.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from habituation_stl.stl import Aggregator


@dataclass(frozen=True)
class MissionTask:
    task_id: int
    robot_id: str
    created_t: float
    target_xy: tuple[float, float]
    cell_id: int | None
    service_s: float
    reactive: bool
    deterring: bool
    beta: float = 0.0
    omega_s: float = 1.0
    eta: float = 1.0


@dataclass(frozen=True)
class MissionRobot:
    robot_id: str
    position: tuple[float, float]
    speed_mps: float
    current_task_id: int | None = None
    hold_until_t: float = 0.0


@dataclass(frozen=True)
class MissionSpec:
    E_star: float
    T_cov_s: float
    eta_min: float
    horizon_s: float
    monitor_dt_s: float
    theta: float
    omega_e_s: float
    reactive_deadline_s: float = 90.0
    step_s: float = 1.0
    kernel_self: float = 1.0
    smooth: bool = True
    include_habituation: bool = True

    def __post_init__(self):
        for name in ('E_star', 'T_cov_s', 'horizon_s', 'monitor_dt_s', 'theta',
                     'omega_e_s', 'reactive_deadline_s', 'step_s'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if not 0 <= self.eta_min < 1 or not math.isfinite(self.kernel_self) or self.kernel_self < 0:
            raise ValueError('Invalid effectiveness threshold or suppression kernel')


@dataclass(frozen=True)
class MissionContext:
    now_t: float
    exposure: tuple[float, ...]
    coverage_age: tuple[float, ...]
    robots: tuple[MissionRobot, ...]
    tasks: tuple[MissionTask, ...]
    spec: MissionSpec


def _validate(context):
    if not math.isfinite(context.now_t) or not context.exposure or len(context.exposure) != len(context.coverage_age):
        raise ValueError('Invalid mission state dimensions/time')
    if any(not math.isfinite(x) or x < 0 for x in (*context.exposure, *context.coverage_age)):
        raise ValueError('Exposure and coverage ages must be finite/nonnegative')
    ids = [t.task_id for t in context.tasks]
    robot_ids = [r.robot_id for r in context.robots]
    if len(ids) != len(set(ids)) or len(robot_ids) != len(set(robot_ids)):
        raise ValueError('Duplicate task or robot identity')
    for robot in context.robots:
        if not math.isfinite(robot.speed_mps) or robot.speed_mps <= 0 or not all(math.isfinite(x) for x in robot.position):
            raise ValueError('Invalid robot motion state')
    for task in context.tasks:
        values = (*task.target_xy, task.created_t, task.service_s, task.beta, task.omega_s, task.eta)
        if task.robot_id not in robot_ids or not all(math.isfinite(x) for x in values):
            raise ValueError('Invalid task state')
        if task.service_s < 0 or task.beta < 0 or task.omega_s <= 0 or not 0 <= task.eta <= 1:
            raise ValueError('Invalid task dynamics')
        if task.cell_id is not None and not 0 <= task.cell_id < len(context.exposure):
            raise ValueError('Invalid responsibility-zone id')
        if task.reactive and not task.deterring:
            raise ValueError('Reactive tasks must be deterrence actions')


def pending_schedule(context, deciding_robot=None, first_task_id=None):
    """Return (task, relative completion time), without mutating any input."""
    events = []
    for robot in context.robots:
        queue = sorted((t for t in context.tasks if t.robot_id == robot.robot_id),
                       key=lambda t: (t.created_t, t.task_id))
        current = next((t for t in queue if t.task_id == robot.current_task_id), None)
        holding = robot.hold_until_t > context.now_t
        chosen = (next((t for t in queue if t.task_id == first_task_id), None)
                  if robot.robot_id == deciding_robot else None)
        first = current if holding else (chosen or current)
        if first is not None:
            queue = [first] + [t for t in queue if t.task_id != first.task_id]
        clock = max(0.0, robot.hold_until_t - context.now_t) if holding else 0.0
        pos = robot.position
        for i, task in enumerate(queue):
            if i == 0 and holding and current is not None:
                pass
            else:
                clock += math.dist(pos, task.target_xy) / robot.speed_mps + task.service_s
            events.append((task, clock))
            pos = task.target_xy
            # One simulator-step turnaround between queued services.
            clock += context.spec.step_s
    return tuple(sorted(events, key=lambda e: (e[1], e[0].task_id)))


def _shared_times(context, schedules):
    spec = context.spec
    times = set(np.arange(0., spec.horizon_s, spec.monitor_dt_s).tolist())
    times.update((0., spec.horizon_s))
    for schedule in schedules:
        for _task, completion in schedule:
            if 0 <= completion <= spec.horizon_s:
                times.add(float(completion))
                if completion > 0:
                    times.add(float(np.nextafter(completion, -np.inf)))
    for task in context.tasks:
        if task.reactive:
            due = task.created_t + spec.reactive_deadline_s - context.now_t
            if 0 <= due <= spec.horizon_s:
                times.add(float(due))
    return np.asarray(sorted(times), dtype=float)


def forecast_margins(context, schedule, times):
    """Normalized four-clause traces; finite original-deadline completion slack."""
    spec = context.spec
    exposure = np.asarray(context.exposure)[:, None] * np.exp(-times[None, :] / spec.omega_e_s)
    coverage = np.asarray(context.coverage_age)[:, None] + times[None, :]
    effectiveness = np.ones_like(exposure)
    completions = {task.task_id: t for task, t in schedule if t <= spec.horizon_s}
    for task, completion in schedule:
        if not task.deterring or task.cell_id is None or completion > spec.horizon_s:
            continue
        after = times >= completion
        age = times[after] - completion
        exposure[task.cell_id, after] -= task.eta * task.beta * spec.kernel_self * np.exp(-age / task.omega_s)
        coverage[task.cell_id, after] = age
        effectiveness[task.cell_id, after] = task.eta
    exposure = np.maximum(exposure, 0.)
    reactive = []
    for task in context.tasks:
        if not task.reactive:
            continue
        deadline = task.created_t + spec.reactive_deadline_s - context.now_t
        if deadline <= spec.horizon_s:
            completion = completions.get(task.task_id, spec.horizon_s + spec.step_s)
            reactive.append((deadline - completion) / spec.reactive_deadline_s)
    margins = dict(exp=(spec.E_star - exposure) / spec.E_star,
                   cov=(spec.T_cov_s - coverage) / spec.T_cov_s,
                   react=np.asarray(reactive if reactive else [1.], dtype=float))
    if spec.include_habituation:
        margins['hab'] = (effectiveness - spec.eta_min) / (1. - spec.eta_min)
    return margins


def _robustness(context, schedule, times):
    agg = Aggregator('smooth' if context.spec.smooth else 'classical', context.spec.theta)
    margins = forecast_margins(context, schedule, times)
    clauses = {name: float(agg.amin(values.ravel())) for name, values in margins.items()}
    return float(agg.amin(list(clauses.values()))), clauses


def select_mission_task(context, robot_id, candidate_stream=None):
    """Score admitted actions against one reference and the configured mission clauses."""
    _validate(context)
    robot = next((r for r in context.robots if r.robot_id == robot_id), None)
    if robot is None:
        raise ValueError('Unknown deciding robot')
    own_tasks = sorted((t for t in context.tasks if t.robot_id == robot_id),
                       key=lambda t: (t.created_t, t.task_id))
    if not own_tasks:
        return None, dict(candidates=0, scores=(), sampling_count=0)
    if candidate_stream is None:
        candidates = own_tasks
    elif candidate_stream == 'predictive':
        candidates = [t for t in own_tasks if t.deterring and not t.reactive]
    else:
        raise ValueError(f'Unsupported mission candidate stream: {candidate_stream!r}')
    if not candidates:
        return None, dict(candidates=0, scores=(), sampling_count=0)
    current = next((t for t in own_tasks if t.task_id == robot.current_task_id), None)
    if robot.hold_until_t > context.now_t:
        return (None if current is None else current.task_id), dict(
            candidates=0, holding=True, scores=(), sampling_count=0)
    reference_first = current or own_tasks[0]
    schedules = [pending_schedule(context)]
    schedules.extend(pending_schedule(context, robot_id, t.task_id) for t in candidates)
    times = _shared_times(context, schedules)
    rho_reference, reference_clauses = _robustness(context, schedules[0], times)
    reference_is_candidate = any(t.task_id == reference_first.task_id for t in candidates)
    best_id = reference_first.task_id if reference_is_candidate else candidates[0].task_id
    best_value = 0. if reference_is_candidate else -math.inf
    scores = []
    for task, schedule in zip(candidates, schedules[1:]):
        rho, clauses = _robustness(context, schedule, times)
        value = rho - rho_reference
        if not math.isfinite(value):
            raise ValueError('Nonfinite mission robustness')
        scores.append(dict(task_id=task.task_id, reactive=task.reactive, value=value, robustness=rho, clauses=clauses))
        if value > best_value + 1.e-12:
            best_id, best_value = task.task_id, value
    return best_id, dict(candidates=len(candidates), sampling_count=len(times), scores=tuple(scores),
                         selected_value=best_value, reference_task_id=reference_first.task_id,
                         reference_robustness=rho_reference, reference_clauses=reference_clauses)
