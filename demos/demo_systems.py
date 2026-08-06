from __future__ import annotations

"""
Synchronized live demo for the reactive, prediction-only, and proposed systems.

This file is intentionally standalone. It does not modify the simulation runtime
and only uses existing repository entrypoints.

What the demo shows:
- Three synchronized system views on one screen:
  reactive, prediction_only, and proposed.
- A to-scale vineyard map with row bands and robot regions (zones).
- Robot footprints rendered with a typical Husky top-view footprint.
- Assigned tasks split into:
  - current tasks: the task a robot is currently driving toward
  - queued tasks: other active tasks still assigned to that robot
- Live metric plots on the same figure.

Important note about queued tasks:
The runtime snapshot now exposes tracking links for the current task per robot.
Queued tasks are rendered as active assigned tasks that are not the robot's
current motion-command task.

Usage:
    python -m demos.demo_systems --config configs/demo_config.json

Headless smoke run:
    python -m demos.demo_systems --config configs/demo_config.json --no-show --max-frames 5

Optional final-frame export:
    python -m demos.demo_systems --config configs/demo_config.json --save-figure results/demo_systems.png
"""

import argparse
import json
import math
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import matplotlib
import numpy as np

if "--no-show" in sys.argv:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.widgets import Button

from calibration_config import DEFAULT_CALIBRATION_MANIFEST_PATH
try:
    from demos._bootstrap import REPO_ROOT, resolve_repo_path
except ModuleNotFoundError:
    from _bootstrap import REPO_ROOT, resolve_repo_path

import DeterrentSystem as ds
from planner_profiles import get_planner_profile_values
from simplification.stages import get_stage


DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "demo_config.json"
PATH_KWARG_KEYS = ("calibration_ranking_path", "calibration_manifest_path", "telemetry_dir")
DEFAULT_CALIBRATION_MANIFEST = str(DEFAULT_CALIBRATION_MANIFEST_PATH)
CALIBRATION_MANAGED_MODEL_KWARGS = (
    "sigma",
    "omega",
    "omega_inhib",
    "alpha_in",
    "alpha_cross",
    "alpha_inhib",
    "mu_base",
    "bg_ema",
    "model_feedback_sigma_scale",
    "model_feedback_omega_scale",
)


SYSTEM_MODE_DEFAULTS: dict[str, dict[str, Any]] = {
    "reactive": {
        "simulation_mode": "reactive",
        "enable_patrolling": False,
        "enable_intervention_feedback": False,
        "include_fallback_patrol": False,
        "enable_model_scored_deterring": False,
    },
    "prediction_only": {
        "simulation_mode": "prediction_only",
        "enable_patrolling": True,
        "enable_intervention_feedback": False,
        "include_fallback_patrol": True,
        "enable_model_scored_deterring": False,
    },
    "proposed": {
        "simulation_mode": "proposed",
        "enable_patrolling": True,
        "enable_intervention_feedback": True,
        "include_fallback_patrol": True,
        "enable_model_scored_deterring": True,
    },
}


DEFAULT_CONFIG: dict[str, Any] = {
    "display": {
        "title": "Reactive vs Prediction Only vs Proposed",
        "figure_width": 19.5,
        "figure_height": 10.8,
        "fps": 10,
        "live_tracking_fps": 30,
        "motion_smoothing": True,
        "motion_easing": "smoothstep",
        "steps_per_frame": 1,
        "goal_match_radius_m": 25.0,
        "task_line_alpha": 0.75,
        "queued_task_line_alpha": 0.50,
        "label_fontsize": 9,
        "status_fontsize": 8,
        "legend_fontsize": 8,
        "metric_title_fontsize": 9,
        "metric_tick_fontsize": 8,
        "map_tick_fontsize": 8,
        "metric_columns": 4,
        "map_view_mode": "full_field",
        "map_full_margin_m": 8.0,
        "map_zoom_rows": 14,
        "map_zoom_min_rows": 10,
        "map_zoom_max_rows": 20,
        "map_zoom_width_m": 170.0,
        "map_zoom_max_width_m": 230.0,
        "map_zoom_margin_m": 10.0,
        "map_zoom_smoothing": 0.18,
    },
    "robot_rendering": {
        "husky_length_m": 0.99,
        "husky_width_m": 0.67,
        "display_length_m": 6.0,
        "display_width_m": 3.4,
        "heading_line_m": 4.0,
        "label_offset_m": 3.4,
        "body_alpha": 0.95,
    },
    "vineyard": {
        "W": 240.0,
        "H": 96.0,
        "row_spacing_m": 4.8,
        "row_width_m": 3.2,
        "headland_space_m": 8.0,
        "turn_space_m": 10.0,
    },
    "scenario": {
        "duration_s": 1800.0,
        "dt": 5.0,
        "seed": 321,
        "fps": 1,
        "NX": 54,
        "NY": 24,
        "Nrobots": 4,
        "uav_fraction": 0.0,
        "warmup_s": 600.0,
        "task_replan_period_s": 20.0,
        "arrival_radius_m": 3.0,
        "hold_time_s": 12.0,
        "idle_roam_enabled": True,
        "idle_roam_interval_s": 25.0,
        "idle_roam_jitter_m": 18.0,
        "mu_true": 1.8e-7,
        "alpha_true": 0.10,
        "omega_true": 1000.0,
        "sigma_true": 9.0,
        "beta_true": 0.35,
        "detect_range_m": 220.0,
        "row_gain": 2.0,
        "edge_gain": 0.9,
        "event_viz_window_s": 10.0,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
        "report_metrics_end": False,
    },
    "tracking": {
        "emit_tracking_state": True,
        "tracking_include_arrays": False,
        "tracking_preview_limit": 50,
        "tracking_capture_frame_locals": False,
    },
    "metrics": [
        {"key": "value_weighted_exposure", "label": "Value-Weighted Exposure", "goal": "lower"},
        {"key": "completed_tasks_total", "label": "Completed Tasks", "goal": "higher"},
        {"key": "mean_response_time_s", "label": "Mean Response Time (s)", "goal": "lower"},
        {"key": "birds_deterred_pct_last_hour", "label": "Birds Deterred Last Hour (%)", "goal": "higher"},
    ],
    "systems": [
        {
            "key": "reactive",
            "title": "Reactive",
            "mode": "reactive",
            "color": "#6e6e6e",
            "line_style": "-",
            "marker": "o",
            "short_label": "R",
            "overrides": {},
        },
        {
            "key": "prediction_only",
            "title": "Prediction Only",
            "mode": "prediction_only",
            "color": "#1f77b4",
            "line_style": "--",
            "marker": "s",
            "short_label": "P",
            "overrides": {
                "use_frozen_calibration": True,
                "calibration_manifest_path": DEFAULT_CALIBRATION_MANIFEST,
            },
        },
        {
            "key": "proposed",
            "title": "Proposed",
            "mode": "proposed",
            "color": "#d62728",
            "line_style": "-.",
            "marker": "^",
            "short_label": "T",
            "stage": "s5_current_thesis_profile",
            "overrides": {
                "use_frozen_calibration": True,
                "calibration_manifest_path": DEFAULT_CALIBRATION_MANIFEST,
            },
        },
    ],
}


@dataclass
class MetricSpec:
    key: str
    label: str
    goal: str


@dataclass
class SystemSpec:
    key: str
    title: str
    mode: str
    color: str
    line_style: str
    marker: str
    short_label: str
    stage: str | None
    overrides: dict[str, Any]
    sim_kwargs: dict[str, Any]


@dataclass
class MapArtists:
    axis: Any
    status_axis: Any
    boundary_line: Any
    row_patches: list[Any]
    row_lines: Any
    zone_patches: list[Any]
    truth_scatter: Any
    detection_scatter: Any
    deterring_active_scatter: Any
    deterring_queued_scatter: Any
    patrol_active_scatter: Any
    patrol_queued_scatter: Any
    active_line_collection: Any
    queued_line_collection: Any
    robot_patches: dict[str, Any]
    robot_heading_lines: dict[str, Any]
    robot_labels: dict[str, Any]
    robot_colors: dict[str, Any]
    info_text: Any


@dataclass
class MetricArtists:
    axis: Any
    lines: dict[str, Any]
    markers: dict[str, Any]
    labels: dict[str, Any]


@dataclass
class SystemRun:
    spec: SystemSpec
    frames: Iterator[dict[str, Any]]
    snapshot: dict[str, Any]
    previous_poses: dict[str, tuple[float, float]] = field(default_factory=dict)
    previous_t_s: float = 0.0
    display_headings: dict[str, float] = field(default_factory=dict)
    history_t_min: list[float] = field(default_factory=list)
    history_metrics: dict[str, list[float]] = field(default_factory=dict)
    map_artists: MapArtists | None = None


@dataclass
class MapViewState:
    center_x: float
    center_y: float
    width: float
    height: float


@dataclass
class PlaybackControls:
    paused: bool = False
    button: Any | None = None


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = {k: deepcopy(v) for k, v in base.items()}
        for key, value in override.items():
            merged[str(key)] = _deep_merge(merged.get(str(key)), value)
        return merged
    return deepcopy(override)


def _load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Demo config not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Demo config root must be a JSON object: {path}")
    return payload


def load_config(path: Path) -> dict[str, Any]:
    user_config = _load_json_config(path)
    return _deep_merge(DEFAULT_CONFIG, user_config)


def _fmt_hms(t_s: float) -> str:
    total = max(0, int(round(float(t_s))))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _safe_float(value: Any) -> float:
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return value_f


def _fmt_metric(value: Any, pattern: str = "{:.2f}") -> str:
    value_f = _safe_float(value)
    if not np.isfinite(value_f):
        return "n/a"
    return pattern.format(value_f)


def _scenario_sim_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    scenario = dict(config.get("scenario", {}))
    vineyard = dict(config.get("vineyard", {}))
    tracking = dict(config.get("tracking", {}))
    sim_kwargs = dict(vineyard)
    sim_kwargs.update(scenario)
    sim_kwargs.update(tracking)
    duration_s = float(sim_kwargs.pop("duration_s"))
    sim_kwargs["T_end"] = duration_s
    sim_kwargs["seed"] = int(sim_kwargs.get("seed", 0))
    sim_kwargs["report_metrics_end"] = False
    sim_kwargs["telemetry_clear_on_start"] = False
    sim_kwargs["telemetry_prompt_save"] = False
    return sim_kwargs


def _normalize_sim_path_kwargs(sim_kwargs: dict[str, Any]) -> None:
    for key in PATH_KWARG_KEYS:
        value = sim_kwargs.get(key)
        if value in (None, ""):
            continue
        sim_kwargs[key] = str(resolve_repo_path(str(value)))


def _drop_calibration_managed_model_kwargs(sim_kwargs: dict[str, Any]) -> None:
    if not bool(sim_kwargs.get("use_frozen_calibration", False)):
        return
    for key in CALIBRATION_MANAGED_MODEL_KWARGS:
        sim_kwargs.pop(key, None)


def _resolve_system_specs(config: dict[str, Any]) -> list[SystemSpec]:
    base_sim_kwargs = _scenario_sim_kwargs(config)
    specs: list[SystemSpec] = []
    for raw_system in config.get("systems", []):
        if not isinstance(raw_system, dict):
            raise ValueError("Each system entry must be a JSON object.")
        mode = str(raw_system.get("mode", "")).strip().lower()
        if mode not in SYSTEM_MODE_DEFAULTS:
            choices = ", ".join(sorted(SYSTEM_MODE_DEFAULTS))
            raise ValueError(f"Unknown system mode {mode!r}. Expected one of: {choices}")
        spec_kwargs = dict(base_sim_kwargs)
        spec_kwargs.update(SYSTEM_MODE_DEFAULTS[mode])
        stage_name = raw_system.get("stage")
        if stage_name:
            stage = get_stage(str(stage_name))
            spec_kwargs.update(stage.overrides)
        spec_kwargs.update(dict(raw_system.get("overrides", {})))
        if mode in ("prediction_only", "proposed"):
            spec_kwargs.setdefault("use_frozen_calibration", True)
            spec_kwargs.setdefault("calibration_manifest_path", DEFAULT_CALIBRATION_MANIFEST)
        planner_profile = str(spec_kwargs.get("planner_profile", "")).strip()
        if planner_profile:
            profile_values = get_planner_profile_values(planner_profile)
            for key in PATH_KWARG_KEYS:
                if spec_kwargs.get(key) in (None, "") and profile_values.get(key) not in (None, ""):
                    spec_kwargs[key] = profile_values.get(key)
        _normalize_sim_path_kwargs(spec_kwargs)
        _drop_calibration_managed_model_kwargs(spec_kwargs)
        spec_kwargs["report_metrics_end"] = False
        specs.append(
            SystemSpec(
                key=str(raw_system.get("key", mode)),
                title=str(raw_system.get("title", mode.replace("_", " ").title())),
                mode=mode,
                color=str(raw_system.get("color", "#333333")),
                line_style=str(raw_system.get("line_style", "-")),
                marker=str(raw_system.get("marker", "o")),
                short_label=str(raw_system.get("short_label", str(raw_system.get("key", mode))[:1])).strip() or str(raw_system.get("key", mode))[:1],
                stage=(None if not stage_name else str(stage_name)),
                overrides=dict(raw_system.get("overrides", {})),
                sim_kwargs=spec_kwargs,
            )
        )
    if len(specs) != 3:
        raise ValueError("This demo expects exactly three systems in the config.")
    return specs


def _metric_specs(config: dict[str, Any]) -> list[MetricSpec]:
    specs: list[MetricSpec] = []
    for raw_metric in config.get("metrics", []):
        if not isinstance(raw_metric, dict):
            raise ValueError("Each metric entry must be a JSON object.")
        specs.append(
            MetricSpec(
                key=str(raw_metric.get("key", "")),
                label=str(raw_metric.get("label", raw_metric.get("key", ""))),
                goal=str(raw_metric.get("goal", "higher")),
            )
        )
    if not specs:
        raise ValueError("At least one metric must be configured.")
    return specs


def _metric_value(snapshot: dict[str, Any], key: str) -> float:
    metrics = snapshot.get("metrics", {}) or {}
    compact = snapshot.get("metrics_compact", {}) or {}
    active_tasks = [
        task
        for task in snapshot.get("tasks_active", [])
        if str(task.get("state", "")).strip().lower() == "active"
    ]
    if key == "active_tasks":
        return float(len(active_tasks))
    if key == "completed_deterring_total":
        by_type = metrics.get("completed_tasks_by_type", {})
        return float(by_type.get("deterring", 0))
    if key == "completed_patrolling_total":
        by_type = metrics.get("completed_tasks_by_type", {})
        return float(by_type.get("patrolling", 0))
    if key in metrics:
        return _safe_float(metrics.get(key))
    if key in compact:
        return _safe_float(compact.get(key))
    return float("nan")


def _row_lines_for_vineyard(
    W: float,
    H: float,
    row_spacing_m: float,
    row_width_m: float,
    headland_space_m: float,
) -> tuple[list[list[tuple[float, float]]], list[tuple[tuple[float, float], tuple[float, float]]]]:
    row_polygons: list[list[tuple[float, float]]] = []
    center_lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
    if row_spacing_m <= 0 or row_width_m <= 0:
        return row_polygons, center_lines
    index = 0
    while True:
        y_center = headland_space_m + index * row_spacing_m
        if y_center - 0.5 * row_width_m > (H - headland_space_m):
            break
        y0 = y_center - 0.5 * row_width_m
        y1 = y_center + 0.5 * row_width_m
        row_polygons.append(
            [
                (headland_space_m, y0),
                (W - headland_space_m, y0),
                (W - headland_space_m, y1),
                (headland_space_m, y1),
            ]
        )
        center_lines.append(((headland_space_m, y_center), (W - headland_space_m, y_center)))
        index += 1
    return row_polygons, center_lines


def _row_span_height_m(rows_visible: int, row_spacing_m: float, row_width_m: float) -> float:
    rows_visible = max(int(rows_visible), 1)
    return max(float(row_width_m), float(row_width_m) + float(max(rows_visible - 1, 0)) * float(row_spacing_m))


def _robot_display_dimensions(robot_cfg: dict[str, Any]) -> tuple[float, float]:
    length_m = float(robot_cfg.get("display_length_m", robot_cfg.get("husky_length_m", 1.0)))
    width_m = float(robot_cfg.get("display_width_m", robot_cfg.get("husky_width_m", 1.0)))
    return length_m, width_m


def _vehicle_polygon(cx: float, cy: float, heading_rad: float, length_m: float, width_m: float) -> np.ndarray:
    half_length = 0.5 * float(length_m)
    half_width = 0.5 * float(width_m)
    corners = np.array(
        [
            [half_length, half_width],
            [half_length, -half_width],
            [-half_length, -half_width],
            [-half_length, half_width],
        ],
        dtype=float,
    )
    cos_h = math.cos(heading_rad)
    sin_h = math.sin(heading_rad)
    rot = np.array([[cos_h, -sin_h], [sin_h, cos_h]], dtype=float)
    pts = corners @ rot.T
    pts[:, 0] += float(cx)
    pts[:, 1] += float(cy)
    return pts


def _current_heading(
    snapshot: dict[str, Any],
    previous_pose: dict[str, tuple[float, float]],
    robot_id: str,
    fallback_heading: float = 0.0,
) -> float:
    pose = snapshot.get("poses", {}).get(robot_id)
    if pose is None:
        return float(fallback_heading)
    x, y = pose
    prev = previous_pose.get(robot_id)
    if prev is not None:
        dx = float(x) - float(prev[0])
        dy = float(y) - float(prev[1])
        if (dx * dx + dy * dy) > 1.0e-9:
            return math.atan2(dy, dx)
    goal = snapshot.get("robot_goals", {}).get(robot_id)
    if goal is not None:
        dx = float(goal[0]) - float(x)
        dy = float(goal[1]) - float(y)
        if (dx * dx + dy * dy) > 1.0e-9:
            return math.atan2(dy, dx)
    return float(fallback_heading)


def _ease_motion_alpha(alpha: float, easing: str) -> float:
    alpha = min(max(float(alpha), 0.0), 1.0)
    mode = str(easing).strip().lower()
    if mode in {"smoothstep", "ease", "ease_in_out"}:
        return alpha * alpha * (3.0 - 2.0 * alpha)
    return alpha


def _interpolated_snapshot(run: SystemRun, alpha: float, config: dict[str, Any]) -> dict[str, Any]:
    snapshot = run.snapshot
    poses = snapshot.get("poses", {}) or {}
    if not poses or not run.previous_poses:
        return snapshot

    display_cfg = config.get("display", {})
    if not bool(display_cfg.get("motion_smoothing", True)):
        return snapshot

    alpha_eased = _ease_motion_alpha(alpha, str(display_cfg.get("motion_easing", "smoothstep")))
    merged_ids = sorted({str(robot_id) for robot_id in poses} | set(run.previous_poses.keys()))
    interp_poses: dict[str, tuple[float, float]] = {}
    for robot_id in merged_ids:
        current_pose = poses.get(robot_id)
        previous_pose = run.previous_poses.get(robot_id)
        if current_pose is None and previous_pose is None:
            continue
        if current_pose is None:
            interp_poses[robot_id] = (float(previous_pose[0]), float(previous_pose[1]))
            continue
        if previous_pose is None:
            interp_poses[robot_id] = (float(current_pose[0]), float(current_pose[1]))
            continue
        interp_poses[robot_id] = (
            float(previous_pose[0]) + (float(current_pose[0]) - float(previous_pose[0])) * alpha_eased,
            float(previous_pose[1]) + (float(current_pose[1]) - float(previous_pose[1])) * alpha_eased,
        )

    previous_t = float(run.previous_t_s)
    current_t = float(snapshot.get("t", previous_t))
    display_snapshot = dict(snapshot)
    display_snapshot["poses"] = interp_poses
    display_snapshot["t"] = previous_t + (current_t - previous_t) * alpha_eased
    return display_snapshot


def _task_buckets(
    snapshot: dict[str, Any],
    goal_match_radius_m: float,
) -> dict[str, Any]:
    active_tasks = [
        task
        for task in snapshot.get("tasks_active", [])
        if str(task.get("state", "")).strip().lower() == "active" and task.get("assigned_primary")
    ]
    tasks_by_robot: dict[str, list[dict[str, Any]]] = {}
    for task in active_tasks:
        robot_id = str(task.get("assigned_primary"))
        tasks_by_robot.setdefault(robot_id, []).append(task)

    current_deterring: list[dict[str, Any]] = []
    queued_deterring: list[dict[str, Any]] = []
    current_patrol: list[dict[str, Any]] = []
    queued_patrol: list[dict[str, Any]] = []
    active_segments: list[list[tuple[float, float]]] = []
    queued_segments: list[list[tuple[float, float]]] = []
    current_task_ids_by_robot: dict[str, int] = {}
    tracking_state = snapshot.get("tracking_state") or {}
    demo_links = tracking_state.get("demo_links") or {}
    current_task_map = demo_links.get("current_task_ids_by_robot")
    if isinstance(current_task_map, dict):
        for robot_id, task_id in current_task_map.items():
            try:
                current_task_ids_by_robot[str(robot_id)] = int(task_id)
            except (TypeError, ValueError):
                continue
    if not current_task_ids_by_robot:
        for command in snapshot.get("motion_commands", []):
            if command.get("assigned_task_id") is None:
                continue
            if str(command.get("command_type", "")).strip().lower() not in {"move", "hold"}:
                continue
            current_task_ids_by_robot[str(command.get("robot_id"))] = int(command["assigned_task_id"])

    for robot_id, robot_tasks in tasks_by_robot.items():
        pose = snapshot.get("poses", {}).get(robot_id)
        if pose is None:
            continue
        robot_pose = (float(pose[0]), float(pose[1]))
        current_task: dict[str, Any] | None = None
        current_task_id = current_task_ids_by_robot.get(robot_id)
        if current_task_id is not None:
            for task_row in robot_tasks:
                if int(task_row.get("id", -1)) == current_task_id:
                    current_task = task_row
                    break
        goal = snapshot.get("robot_goals", {}).get(robot_id)
        if current_task is None and goal is not None and robot_tasks:
            def goal_distance(task_row: dict[str, Any]) -> float:
                return math.hypot(float(task_row.get("x", 0.0)) - float(goal[0]), float(task_row.get("y", 0.0)) - float(goal[1]))

            nearest_to_goal = min(robot_tasks, key=goal_distance)
            if goal_distance(nearest_to_goal) <= float(goal_match_radius_m):
                current_task = nearest_to_goal
        if current_task is None and snapshot.get("robot_states", {}).get(robot_id) == "moving" and robot_tasks:
            current_task = min(
                robot_tasks,
                key=lambda task_row: math.hypot(
                    float(task_row.get("x", 0.0)) - robot_pose[0],
                    float(task_row.get("y", 0.0)) - robot_pose[1],
                ),
            )

        for task in robot_tasks:
            point = (float(task.get("x", 0.0)), float(task.get("y", 0.0)))
            is_current = current_task is task
            is_deterring = str(task.get("type", "")).strip().lower() == "deterring"
            if is_current:
                active_segments.append([robot_pose, point])
                if is_deterring:
                    current_deterring.append(task)
                else:
                    current_patrol.append(task)
            else:
                queued_segments.append([robot_pose, point])
                if is_deterring:
                    queued_deterring.append(task)
                else:
                    queued_patrol.append(task)

    return {
        "current_deterring": current_deterring,
        "queued_deterring": queued_deterring,
        "current_patrol": current_patrol,
        "queued_patrol": queued_patrol,
        "active_segments": active_segments,
        "queued_segments": queued_segments,
    }


def _focus_points_from_snapshot(snapshot: dict[str, Any]) -> np.ndarray:
    poses = snapshot.get("poses", {}) or {}
    active_tasks = [
        task
        for task in snapshot.get("tasks_active", [])
        if str(task.get("state", "")).strip().lower() == "active"
    ]
    focus_points: list[tuple[float, float]] = []
    seen_robot_ids: set[str] = set()
    if active_tasks:
        for task in active_tasks:
            focus_points.append((float(task.get("x", 0.0)), float(task.get("y", 0.0))))
            robot_id = str(task.get("assigned_primary", ""))
            pose = poses.get(robot_id)
            if pose is not None and robot_id not in seen_robot_ids:
                focus_points.append((float(pose[0]), float(pose[1])))
                seen_robot_ids.add(robot_id)
    if focus_points:
        return np.array(focus_points, dtype=float)
    pose_points = np.array(
        [(float(x), float(y)) for x, y in poses.values()],
        dtype=float,
    )
    if pose_points.size == 0 or len(pose_points) <= 3:
        return pose_points.reshape((-1, 2))
    center = np.median(pose_points, axis=0)
    ranked = sorted(
        pose_points.tolist(),
        key=lambda point: math.hypot(float(point[0]) - float(center[0]), float(point[1]) - float(center[1])),
    )
    return np.array(ranked[: min(len(ranked), 4)], dtype=float)


def _target_map_view(runs: list[SystemRun], config: dict[str, Any]) -> MapViewState:
    display_cfg = config["display"]
    vineyard_cfg = config["vineyard"]
    W = float(vineyard_cfg.get("W", 0.0))
    H = float(vineyard_cfg.get("H", 0.0))
    view_mode = str(display_cfg.get("map_view_mode", "auto_zoom")).strip().lower()
    if view_mode in {"full_field", "full", "field"}:
        snapshot = runs[0].snapshot if runs else {}
        W = float(snapshot.get("W", W))
        H = float(snapshot.get("H", H))
        margin_m = max(0.0, float(display_cfg.get("map_full_margin_m", 0.0)))
        return MapViewState(
            center_x=0.5 * W,
            center_y=0.5 * H,
            width=max(W + 2.0 * margin_m, 1.0),
            height=max(H + 2.0 * margin_m, 1.0),
        )
    row_spacing_m = float(vineyard_cfg.get("row_spacing_m", 0.0))
    row_width_m = float(vineyard_cfg.get("row_width_m", 0.0))
    target_rows = int(display_cfg.get("map_zoom_rows", 14))
    min_rows = int(display_cfg.get("map_zoom_min_rows", 10))
    max_rows = int(display_cfg.get("map_zoom_max_rows", 20))
    target_rows = min(max(target_rows, min_rows), max_rows)
    min_height = _row_span_height_m(min_rows, row_spacing_m, row_width_m)
    target_height = _row_span_height_m(target_rows, row_spacing_m, row_width_m)
    max_height = _row_span_height_m(max_rows, row_spacing_m, row_width_m)
    base_width = float(display_cfg.get("map_zoom_width_m", max(target_height * 2.3, 120.0)))
    max_width = max(base_width, float(display_cfg.get("map_zoom_max_width_m", base_width * 1.35)))
    margin_m = float(display_cfg.get("map_zoom_margin_m", 10.0))

    point_sets = [_focus_points_from_snapshot(run.snapshot) for run in runs]
    non_empty = [pts for pts in point_sets if pts.size > 0]
    if not non_empty:
        return MapViewState(center_x=0.5 * W, center_y=0.5 * H, width=base_width, height=target_height)

    pts = np.vstack(non_empty)
    center_x = float(np.median(pts[:, 0]))
    center_y = float(np.median(pts[:, 1]))
    span_x = float(np.ptp(pts[:, 0])) if len(pts) > 1 else 0.0
    span_y = float(np.ptp(pts[:, 1])) if len(pts) > 1 else 0.0
    width = min(max(base_width, span_x + 2.0 * margin_m), max_width, max(W, base_width))
    height = min(max(target_height, span_y + 2.0 * margin_m, min_height), max_height, max(H, target_height))
    width = min(width, W if W > 0.0 else width)
    height = min(height, H if H > 0.0 else height)
    half_width = 0.5 * width
    half_height = 0.5 * height
    center_x = min(max(center_x, half_width), max(half_width, W - half_width))
    center_y = min(max(center_y, half_height), max(half_height, H - half_height))
    return MapViewState(center_x=center_x, center_y=center_y, width=width, height=height)


def _update_shared_map_view_state(
    current_view: MapViewState | None,
    runs: list[SystemRun],
    config: dict[str, Any],
) -> MapViewState:
    target_view = _target_map_view(runs, config)
    if current_view is None:
        return target_view
    alpha = min(max(float(config["display"].get("map_zoom_smoothing", 0.18)), 0.0), 1.0)
    if alpha <= 0.0:
        return current_view
    if alpha >= 1.0:
        return target_view
    return MapViewState(
        center_x=(1.0 - alpha) * current_view.center_x + alpha * target_view.center_x,
        center_y=(1.0 - alpha) * current_view.center_y + alpha * target_view.center_y,
        width=(1.0 - alpha) * current_view.width + alpha * target_view.width,
        height=(1.0 - alpha) * current_view.height + alpha * target_view.height,
    )


def _scatter_points(tasks: list[dict[str, Any]]) -> np.ndarray:
    if not tasks:
        return np.empty((0, 2), dtype=float)
    return np.array([(float(task.get("x", 0.0)), float(task.get("y", 0.0))) for task in tasks], dtype=float)


def _set_scatter_points(scatter_artist: Any, pts: np.ndarray) -> None:
    if pts.size == 0:
        scatter_artist.set_offsets(np.empty((0, 2), dtype=float))
    else:
        scatter_artist.set_offsets(pts)


def _polygon_centroid(poly: list[tuple[float, float]]) -> tuple[float, float]:
    if not poly:
        return 0.0, 0.0
    area_twice = 0.0
    cx = 0.0
    cy = 0.0
    for idx, (x0, y0) in enumerate(poly):
        x1, y1 = poly[(idx + 1) % len(poly)]
        cross = float(x0) * float(y1) - float(x1) * float(y0)
        area_twice += cross
        cx += (float(x0) + float(x1)) * cross
        cy += (float(y0) + float(y1)) * cross
    if abs(area_twice) < 1.0e-9:
        xs = [float(x) for x, _ in poly]
        ys = [float(y) for _, y in poly]
        return float(np.mean(xs)), float(np.mean(ys))
    return cx / (3.0 * area_twice), cy / (3.0 * area_twice)


def _point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = float(poly[i][0]), float(poly[i][1])
        xj, yj = float(poly[j][0]), float(poly[j][1])
        intersects = ((yi > y) != (yj > y)) and (x < ((xj - xi) * (y - yi) / max(yj - yi, 1.0e-12) + xi))
        if intersects:
            inside = not inside
        j = i
    return inside


def _robot_ids_by_cell(snapshot: dict[str, Any]) -> list[str | None]:
    poses = {
        str(robot_id): (float(pose[0]), float(pose[1]))
        for robot_id, pose in (snapshot.get("poses", {}) or {}).items()
    }
    remaining = set(poses.keys())
    cell_robot_ids: list[str | None] = []
    for cell in snapshot.get("cells", []):
        if not cell:
            cell_robot_ids.append(None)
            continue
        matched_robot: str | None = None
        for robot_id in sorted(remaining):
            px, py = poses[robot_id]
            if _point_in_polygon(px, py, cell):
                matched_robot = robot_id
                break
        if matched_robot is None and remaining:
            cx, cy = _polygon_centroid(cell)
            matched_robot = min(remaining, key=lambda robot_id: math.hypot(poses[robot_id][0] - cx, poses[robot_id][1] - cy))
        if matched_robot is not None:
            remaining.discard(matched_robot)
        cell_robot_ids.append(matched_robot)
    return cell_robot_ids


def _label_rect(x: float, y: float, ha: str, va: str, width_m: float, height_m: float) -> tuple[float, float, float, float]:
    if ha == "center":
        x0 = x - 0.5 * width_m
    elif ha == "left":
        x0 = x
    else:
        x0 = x - width_m
    if va == "center":
        y0 = y - 0.5 * height_m
    elif va == "bottom":
        y0 = y
    else:
        y0 = y - height_m
    return (x0, y0, x0 + width_m, y0 + height_m)


def _rects_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], padding_m: float) -> bool:
    return not (
        a[2] + padding_m <= b[0]
        or b[2] + padding_m <= a[0]
        or a[3] + padding_m <= b[1]
        or b[3] + padding_m <= a[1]
    )


def _visible_row_range(y_min: float, y_max: float, snapshot: dict[str, Any], config: dict[str, Any]) -> tuple[int, int] | None:
    vineyard_cfg = config["vineyard"]
    row_spacing_m = float(vineyard_cfg.get("row_spacing_m", 0.0))
    row_width_m = float(vineyard_cfg.get("row_width_m", 0.0))
    headland_space_m = float(vineyard_cfg.get("headland_space_m", 0.0))
    H = float(snapshot.get("H", vineyard_cfg.get("H", 0.0)))
    if row_spacing_m <= 0.0 or row_width_m <= 0.0:
        return None
    visible_rows: list[int] = []
    row_idx = 0
    while True:
        y_center = headland_space_m + row_idx * row_spacing_m
        if y_center - 0.5 * row_width_m > (H - headland_space_m):
            break
        if (y_center + 0.5 * row_width_m) >= y_min and (y_center - 0.5 * row_width_m) <= y_max:
            visible_rows.append(row_idx + 1)
        row_idx += 1
    if not visible_rows:
        return None
    return visible_rows[0], visible_rows[-1]


def _place_robot_labels(
    artists: MapArtists,
    snapshot: dict[str, Any],
    robot_cfg: dict[str, Any],
    view_state: MapViewState,
) -> None:
    length_m, width_m = _robot_display_dimensions(robot_cfg)
    label_pad_m = float(robot_cfg.get("label_offset_m", 3.4))
    label_width_m = min(max(0.085 * float(view_state.width), 8.0), 13.0)
    label_height_m = min(max(0.080 * float(view_state.height), 3.2), 5.4)
    x_min = float(view_state.center_x) - 0.5 * float(view_state.width)
    x_max = float(view_state.center_x) + 0.5 * float(view_state.width)
    y_min = float(view_state.center_y) - 0.5 * float(view_state.height)
    y_max = float(view_state.center_y) + 0.5 * float(view_state.height)
    placed_rects: list[tuple[float, float, float, float]] = []
    poses = snapshot.get("poses", {}) or {}
    ordered_ids = sorted(
        poses.keys(),
        key=lambda robot_id: (-float(poses[robot_id][1]), float(poses[robot_id][0]), str(robot_id)),
    )
    for robot_id in artists.robot_labels.keys():
        artists.robot_labels[robot_id].set_visible(False)
    for robot_id in ordered_ids:
        if robot_id not in artists.robot_labels:
            continue
        x, y = float(poses[robot_id][0]), float(poses[robot_id][1])
        in_view = (
            (x >= (x_min - length_m))
            and (x <= (x_max + length_m))
            and (y >= (y_min - width_m))
            and (y <= (y_max + width_m))
        )
        if not in_view:
            continue
        candidates = [
            (x, y + 0.5 * width_m + label_pad_m, "center", "bottom"),
            (x + 0.5 * length_m + label_pad_m, y, "left", "center"),
            (x - 0.5 * length_m - label_pad_m, y, "right", "center"),
            (x, y - 0.5 * width_m - label_pad_m, "center", "top"),
            (x + 0.35 * length_m + label_pad_m, y + 0.35 * width_m + label_pad_m, "left", "bottom"),
            (x - 0.35 * length_m - label_pad_m, y + 0.35 * width_m + label_pad_m, "right", "bottom"),
        ]
        chosen: tuple[float, float, str, str] | None = None
        chosen_rect: tuple[float, float, float, float] | None = None
        for cand_x, cand_y, ha, va in candidates:
            rect = _label_rect(cand_x, cand_y, ha, va, label_width_m, label_height_m)
            inside_view = (
                rect[0] >= (x_min + 1.0)
                and rect[2] <= (x_max - 1.0)
                and rect[1] >= (y_min + 1.0)
                and rect[3] <= (y_max - 1.0)
            )
            overlaps = any(_rects_overlap(rect, other, padding_m=0.9) for other in placed_rects)
            if inside_view and not overlaps:
                chosen = (cand_x, cand_y, ha, va)
                chosen_rect = rect
                break
            if chosen is None and inside_view:
                chosen = (cand_x, cand_y, ha, va)
                chosen_rect = rect
        if chosen is None or chosen_rect is None:
            chosen = (x, y + 0.5 * width_m + label_pad_m, "center", "bottom")
            chosen_rect = _label_rect(chosen[0], chosen[1], chosen[2], chosen[3], label_width_m, label_height_m)
        label = artists.robot_labels[robot_id]
        label.set_position((chosen[0], chosen[1]))
        label.set_ha(chosen[2])
        label.set_va(chosen[3])
        label.set_visible(True)
        placed_rects.append(chosen_rect)


def _configure_map_axis(
    ax: Any,
    title: str,
    color: str,
    W: float,
    H: float,
    turn_space_m: float,
    display_cfg: dict[str, Any],
) -> None:
    ax.set_title(title, color=color, fontsize=12, fontweight="bold")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-turn_space_m - 10.0, W + turn_space_m + 10.0)
    ax.set_ylim(-turn_space_m - 10.0, H + turn_space_m + 10.0)
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.tick_params(axis="both", labelsize=int(display_cfg.get("map_tick_fontsize", 8)))
    ax.grid(alpha=0.10, linewidth=0.6)
    ax.set_facecolor("#fbfaf7")


def _create_map_artists(
    ax: Any,
    status_ax: Any,
    title: str,
    system_color: str,
    snapshot: dict[str, Any],
    config: dict[str, Any],
) -> MapArtists:
    vineyard_cfg = config["vineyard"]
    display_cfg = config["display"]
    robot_cfg = config["robot_rendering"]
    W = float(snapshot["W"])
    H = float(snapshot["H"])
    turn_space_m = float(vineyard_cfg.get("turn_space_m", 20.0))

    _configure_map_axis(ax, title, system_color, W, H, turn_space_m, display_cfg)

    boundary = snapshot["boundary"]
    bx, by = zip(*(boundary + [boundary[0]]))
    (boundary_line,) = ax.plot(bx, by, color="black", linewidth=1.1, zorder=0.8)

    row_patches: list[Any] = []
    row_lines = None
    row_polygons, row_center_lines = _row_lines_for_vineyard(
        W=W,
        H=H,
        row_spacing_m=float(vineyard_cfg.get("row_spacing_m", 0.0)),
        row_width_m=float(vineyard_cfg.get("row_width_m", 0.0)),
        headland_space_m=float(vineyard_cfg.get("headland_space_m", 0.0)),
    )
    for row_idx, row_polygon in enumerate(row_polygons):
        patch = MplPolygon(
            row_polygon,
            closed=True,
            fill=True,
            alpha=0.55,
            edgecolor="none",
            facecolor=("#e3edd8" if (row_idx % 2 == 0) else "#d7e5ca"),
            zorder=0.1,
        )
        ax.add_patch(patch)
        row_patches.append(patch)
    if row_center_lines:
        row_lines = LineCollection(
            row_center_lines,
            colors="#8aa07d",
            linewidths=0.60,
            alpha=0.60,
            zorder=0.2,
        )
        ax.add_collection(row_lines)

    zone_patches: list[Any] = []
    robot_ids = sorted(snapshot["poses"].keys())
    robot_palette = plt.get_cmap("tab10")(np.linspace(0.0, 1.0, max(len(robot_ids), 1)))
    robot_colors = {robot_id: robot_palette[idx % len(robot_palette)] for idx, robot_id in enumerate(robot_ids)}
    cell_robot_ids = _robot_ids_by_cell(snapshot)
    zone_colors = plt.get_cmap("tab20")(np.linspace(0.0, 1.0, max(len(snapshot["cells"]), 1)))
    for idx, cell in enumerate(snapshot["cells"]):
        if not cell:
            zone_patches.append(None)
            continue
        zone_color = robot_colors.get(cell_robot_ids[idx], zone_colors[idx % len(zone_colors)])
        patch = MplPolygon(
            cell,
            closed=True,
            fill=True,
            alpha=0.12,
            edgecolor=zone_color,
            facecolor=zone_color,
            linewidth=1.3,
            zorder=0.4,
        )
        ax.add_patch(patch)
        zone_patches.append(patch)

    truth_scatter = ax.scatter([], [], s=44, c="#2ca02c", marker="x", zorder=4)
    detection_scatter = ax.scatter([], [], s=44, c="#ff7f0e", marker="x", zorder=5)
    deterring_active_scatter = ax.scatter([], [], s=84, c="#d62728", marker="o", edgecolors="black", linewidths=0.4, zorder=6)
    deterring_queued_scatter = ax.scatter([], [], s=70, facecolors="none", edgecolors="#d62728", marker="o", linewidths=1.2, zorder=5.5)
    patrol_active_scatter = ax.scatter([], [], s=84, c="#1f77b4", marker="D", edgecolors="black", linewidths=0.3, zorder=6)
    patrol_queued_scatter = ax.scatter([], [], s=72, facecolors="none", edgecolors="#1f77b4", marker="D", linewidths=1.1, zorder=5.5)
    active_line_collection = LineCollection([], colors="#444444", linewidths=1.4, alpha=float(display_cfg["task_line_alpha"]), zorder=3)
    queued_line_collection = LineCollection([], colors="#7b7b7b", linewidths=1.1, alpha=float(display_cfg["queued_task_line_alpha"]), zorder=2.8)
    queued_line_collection.set_linestyle("dashed")
    ax.add_collection(active_line_collection)
    ax.add_collection(queued_line_collection)

    robot_patches: dict[str, Any] = {}
    robot_heading_lines: dict[str, Any] = {}
    robot_labels: dict[str, Any] = {}
    display_length_m, display_width_m = _robot_display_dimensions(robot_cfg)
    for robot_id in robot_ids:
        x, y = snapshot["poses"][robot_id]
        robot_color = robot_colors[robot_id]
        body = MplPolygon(
            _vehicle_polygon(
                float(x),
                float(y),
                0.0,
                display_length_m,
                display_width_m,
            ),
            closed=True,
            fill=True,
            edgecolor="black",
            facecolor=robot_color,
            linewidth=1.2,
            alpha=float(robot_cfg["body_alpha"]),
            zorder=7,
        )
        ax.add_patch(body)
        robot_patches[robot_id] = body
        (heading_line,) = ax.plot([], [], color="black", linewidth=1.2, zorder=7.1)
        robot_heading_lines[robot_id] = heading_line
        label = ax.text(
            float(x),
            float(y),
            str(robot_id),
            fontsize=int(display_cfg["label_fontsize"]),
            color="#111111",
            ha="center",
            va="bottom",
            clip_on=False,
            zorder=8,
            bbox={"boxstyle": "round,pad=0.24", "fc": "white", "ec": robot_color, "alpha": 0.96},
        )
        robot_labels[robot_id] = label

    status_ax.set_facecolor("#fbfaf7")
    status_ax.set_axis_off()
    status_ax.axhline(0.98, color="#d7d3cb", linewidth=0.8, xmin=0.0, xmax=1.0)
    info_text = status_ax.text(
        0.00,
        0.82,
        "",
        transform=status_ax.transAxes,
        va="top",
        ha="left",
        fontsize=int(display_cfg.get("status_fontsize", 8)),
        family="monospace",
        color="#1f1f1f",
        zorder=9,
    )

    return MapArtists(
        axis=ax,
        status_axis=status_ax,
        boundary_line=boundary_line,
        row_patches=row_patches,
        row_lines=row_lines,
        zone_patches=zone_patches,
        truth_scatter=truth_scatter,
        detection_scatter=detection_scatter,
        deterring_active_scatter=deterring_active_scatter,
        deterring_queued_scatter=deterring_queued_scatter,
        patrol_active_scatter=patrol_active_scatter,
        patrol_queued_scatter=patrol_queued_scatter,
        active_line_collection=active_line_collection,
        queued_line_collection=queued_line_collection,
        robot_patches=robot_patches,
        robot_heading_lines=robot_heading_lines,
        robot_labels=robot_labels,
        robot_colors=robot_colors,
        info_text=info_text,
    )


def _update_map(run: SystemRun, config: dict[str, Any], view_state: MapViewState, interpolation_alpha: float = 1.0) -> None:
    assert run.map_artists is not None
    artists = run.map_artists
    snapshot = _interpolated_snapshot(run, interpolation_alpha, config)
    display_cfg = config["display"]
    robot_cfg = config["robot_rendering"]
    buckets = _task_buckets(snapshot, goal_match_radius_m=float(display_cfg["goal_match_radius_m"]))
    display_length_m, display_width_m = _robot_display_dimensions(robot_cfg)
    x_min = float(view_state.center_x) - 0.5 * float(view_state.width)
    x_max = float(view_state.center_x) + 0.5 * float(view_state.width)
    y_min = float(view_state.center_y) - 0.5 * float(view_state.height)
    y_max = float(view_state.center_y) + 0.5 * float(view_state.height)
    artists.axis.set_xlim(x_min, x_max)
    artists.axis.set_ylim(y_min, y_max)

    for patch, cell in zip(artists.zone_patches, snapshot["cells"]):
        if patch is not None and cell:
            patch.set_xy(cell)

    truth_pts = np.array(snapshot.get("truth_pts", []), dtype=float)
    det_pts = np.array(snapshot.get("det_pts", []), dtype=float)
    _set_scatter_points(artists.truth_scatter, truth_pts)
    _set_scatter_points(artists.detection_scatter, det_pts)
    _set_scatter_points(artists.deterring_active_scatter, _scatter_points(buckets["current_deterring"]))
    _set_scatter_points(artists.deterring_queued_scatter, _scatter_points(buckets["queued_deterring"]))
    _set_scatter_points(artists.patrol_active_scatter, _scatter_points(buckets["current_patrol"]))
    _set_scatter_points(artists.patrol_queued_scatter, _scatter_points(buckets["queued_patrol"]))
    artists.active_line_collection.set_segments(buckets["active_segments"])
    artists.queued_line_collection.set_segments(buckets["queued_segments"])

    for robot_id, pose in snapshot.get("poses", {}).items():
        x, y = float(pose[0]), float(pose[1])
        heading = _current_heading(
            snapshot,
            run.previous_poses,
            robot_id,
            fallback_heading=float(run.display_headings.get(robot_id, 0.0)),
        )
        run.display_headings[robot_id] = float(heading)
        in_view = (
            (x >= (x_min - display_length_m))
            and (x <= (x_max + display_length_m))
            and (y >= (y_min - display_width_m))
            and (y <= (y_max + display_width_m))
        )
        artists.robot_patches[robot_id].set_xy(
            _vehicle_polygon(
                x,
                y,
                heading,
                display_length_m,
                display_width_m,
            )
        )
        artists.robot_patches[robot_id].set_visible(in_view)
        heading_len = 0.5 * display_length_m + float(robot_cfg["heading_line_m"])
        artists.robot_heading_lines[robot_id].set_data(
            [x, x + heading_len * math.cos(heading)],
            [y, y + heading_len * math.sin(heading)],
        )
        artists.robot_heading_lines[robot_id].set_visible(in_view)
        artists.robot_labels[robot_id].set_text(str(robot_id))

    _place_robot_labels(artists, snapshot, robot_cfg, view_state)

    metrics = snapshot.get("metrics", {}) or {}
    robot_states = snapshot.get("robot_states", {}) or {}
    moving_count = sum(1 for state in robot_states.values() if state == "moving")
    holding_count = sum(1 for state in robot_states.values() if state == "holding")
    idle_count = sum(1 for state in robot_states.values() if state == "idle")
    completed_by_type = metrics.get("completed_tasks_by_type", {}) or {}
    visible_rows = _visible_row_range(y_min, y_max, snapshot, config)
    row_text = "--" if visible_rows is None else f"{visible_rows[0]}-{visible_rows[1]}"
    info_lines = [
        f"Time {_fmt_hms(snapshot.get('t', 0.0))} | Rows {row_text} | M/H/I {moving_count}/{holding_count}/{idle_count}",
        (
            f"Cur D/P {len(buckets['current_deterring'])}/{len(buckets['current_patrol'])} | "
            f"Q D/P {len(buckets['queued_deterring'])}/{len(buckets['queued_patrol'])} | "
            f"Done {int(_safe_float(metrics.get('completed_tasks_total', 0.0))):d} | "
            f"Exp {_fmt_metric(metrics.get('value_weighted_exposure'), '{:.1f}')} | "
            f"Resp {_fmt_metric(metrics.get('mean_response_time_s'), '{:.1f}')}"
        ),
    ]
    artists.info_text.set_text("\n".join(info_lines))


def _record_history(run: SystemRun, metric_specs: list[MetricSpec]) -> None:
    t_min = float(run.snapshot.get("t", 0.0)) / 60.0
    run.history_t_min.append(t_min)
    for metric in metric_specs:
        run.history_metrics.setdefault(metric.key, []).append(_metric_value(run.snapshot, metric.key))


def _advance_runs(runs: list[SystemRun], metric_specs: list[MetricSpec], steps_per_frame: int) -> bool:
    for _ in range(max(int(steps_per_frame), 1)):
        for run in runs:
            run.previous_t_s = float(run.snapshot.get("t", run.previous_t_s))
            run.previous_poses = {
                str(robot_id): (float(px), float(py))
                for robot_id, (px, py) in run.snapshot.get("poses", {}).items()
            }
            try:
                run.snapshot = next(run.frames)
            except StopIteration:
                return False
            _record_history(run, metric_specs)
    return True


def _stack_metric_label_positions(points: list[dict[str, Any]], y_min: float, y_max: float) -> dict[str, float]:
    if not points:
        return {}
    span = max(float(y_max) - float(y_min), 1.0)
    min_gap = 0.05 * span
    sorted_points = sorted(points, key=lambda item: float(item["y"]))
    adjusted: dict[str, float] = {}
    prev_y: float | None = None
    for item in sorted_points:
        y_val = float(item["y"])
        if prev_y is not None and y_val < (prev_y + min_gap):
            y_val = prev_y + min_gap
        adjusted[str(item["key"])] = y_val
        prev_y = y_val
    top_limit = float(y_max) - 0.03 * span
    bottom_limit = float(y_min) + 0.03 * span
    overflow = max(0.0, max(adjusted.values()) - top_limit)
    if overflow > 0.0:
        for key in list(adjusted.keys()):
            adjusted[key] -= overflow
    underflow = max(0.0, bottom_limit - min(adjusted.values()))
    if underflow > 0.0:
        for key in list(adjusted.keys()):
            adjusted[key] += underflow
    return adjusted


def _create_metric_axes(
    fig: Any,
    parent_spec: Any,
    metric_specs: list[MetricSpec],
    systems: list[SystemRun],
    duration_min: float,
    config: dict[str, Any],
) -> dict[str, MetricArtists]:
    display_cfg = config["display"]
    cols = min(max(1, int(display_cfg.get("metric_columns", len(metric_specs)))), len(metric_specs))
    rows = int(math.ceil(len(metric_specs) / float(cols)))
    subgrid = parent_spec.subgridspec(rows, cols, hspace=(0.62 if rows > 1 else 0.0), wspace=0.28)
    artists: dict[str, MetricArtists] = {}
    for idx, metric in enumerate(metric_specs):
        ax = fig.add_subplot(subgrid[idx // cols, idx % cols])
        ax.set_title(
            f"{metric.label}\n({metric.goal} better)",
            fontsize=int(display_cfg.get("metric_title_fontsize", 9)),
            pad=8,
        )
        ax.set_xlim(0.0, max(duration_min * 1.12, 1.0))
        ax.set_xlabel("Sim Time (min)" if (idx // cols) == (rows - 1) else "")
        ax.grid(alpha=0.25)
        ax.tick_params(axis="both", labelsize=int(display_cfg.get("metric_tick_fontsize", 8)))
        ax.set_facecolor("#fbfbfb")
        line_map: dict[str, Any] = {}
        marker_map: dict[str, Any] = {}
        label_map: dict[str, Any] = {}
        for run in systems:
            (line,) = ax.plot(
                [],
                [],
                color=run.spec.color,
                linewidth=2.0,
                linestyle=run.spec.line_style,
                alpha=0.95,
                label=run.spec.title,
            )
            line_map[run.spec.key] = line
            (marker_line,) = ax.plot(
                [],
                [],
                linestyle="none",
                marker=run.spec.marker,
                markersize=6.0,
                markerfacecolor="white",
                markeredgecolor=run.spec.color,
                markeredgewidth=1.3,
                zorder=4.5,
            )
            marker_map[run.spec.key] = marker_line
            label_map[run.spec.key] = ax.text(
                0.0,
                0.0,
                "",
                fontsize=7,
                color=run.spec.color,
                ha="left",
                va="center",
                clip_on=False,
                zorder=5.0,
                bbox={"boxstyle": "round,pad=0.18", "fc": "white", "ec": "none", "alpha": 0.75},
            )
        artists[metric.key] = MetricArtists(axis=ax, lines=line_map, markers=marker_map, labels=label_map)
    return artists


def _update_metric_axes(
    metric_axes: dict[str, MetricArtists],
    systems: list[SystemRun],
    metric_specs: list[MetricSpec],
    duration_min: float,
) -> None:
    max_history_t_min = max(
        (max(run.history_t_min) if run.history_t_min else 0.0)
        for run in systems
    ) if systems else 0.0
    visible_duration_min = max(float(duration_min), float(max_history_t_min), 1.0)
    axis_x_max = max(visible_duration_min * 1.12, 1.0)
    label_x = visible_duration_min * 1.015
    for metric in metric_specs:
        metric_artist = metric_axes[metric.key]
        ax = metric_artist.axis
        last_points: list[dict[str, Any]] = []
        for run in systems:
            xs = run.history_t_min
            ys = run.history_metrics.get(metric.key, [])
            metric_artist.lines[run.spec.key].set_data(xs, ys)
            finite_points = [
                (float(x), float(y))
                for x, y in zip(xs, ys)
                if np.isfinite(float(x)) and np.isfinite(float(y))
            ]
            if finite_points:
                x_last, y_last = finite_points[-1]
                metric_artist.markers[run.spec.key].set_data([x_last], [y_last])
                last_points.append(
                    {
                        "key": run.spec.key,
                        "x": x_last,
                        "y": y_last,
                        "label": run.spec.short_label,
                    }
                )
            else:
                metric_artist.markers[run.spec.key].set_data([], [])
                metric_artist.labels[run.spec.key].set_text("")
        ax.set_xlim(0.0, axis_x_max)
        ax.relim()
        ax.autoscale_view(scalex=False, scaley=True)
        y_min, y_max = ax.get_ylim()
        label_positions = _stack_metric_label_positions(last_points, y_min=y_min, y_max=y_max)
        for run in systems:
            label_artist = metric_artist.labels[run.spec.key]
            match = next((item for item in last_points if item["key"] == run.spec.key), None)
            if match is None:
                label_artist.set_text("")
                continue
            label_artist.set_position((label_x, label_positions.get(run.spec.key, float(match["y"]))))
            label_artist.set_text(f"{run.spec.short_label} {match['y']:.1f}")


def _map_legend_handles() -> list[Any]:
    return [
        Line2D([], [], color="black", linewidth=1.4, label="Current task"),
        Line2D([], [], color="#7b7b7b", linewidth=1.1, linestyle="dashed", label="Queued task"),
        Line2D([], [], marker="o", color="w", markerfacecolor="#d62728", markeredgecolor="black", markersize=8, label="Deterring"),
        Line2D([], [], marker="o", color="w", markerfacecolor="none", markeredgecolor="#d62728", markersize=8, label="Queued deterrence"),
        Line2D([], [], marker="D", color="w", markerfacecolor="#1f77b4", markeredgecolor="black", markersize=8, label="Patrol"),
        Line2D([], [], marker="D", color="w", markerfacecolor="none", markeredgecolor="#1f77b4", markersize=8, label="Queued patrol"),
        Line2D([], [], marker="x", color="#2ca02c", linestyle="none", markersize=8, label="Truth"),
        Line2D([], [], marker="x", color="#ff7f0e", linestyle="none", markersize=8, label="Detection"),
    ]


def _system_legend_handles(runs: list[SystemRun]) -> list[Any]:
    return [
        Line2D(
            [],
            [],
            color=run.spec.color,
            linewidth=2.2,
            linestyle=run.spec.line_style,
            marker=run.spec.marker,
            markersize=6.0,
            markerfacecolor="white",
            markeredgecolor=run.spec.color,
            markeredgewidth=1.2,
            label=run.spec.title,
        )
        for run in runs
    ]


def _build_runs(config: dict[str, Any], metric_specs: list[MetricSpec]) -> list[SystemRun]:
    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    runs: list[SystemRun] = []
    for spec in _resolve_system_specs(config):
        frames = ds.run_simulation_frames_persistent(**spec.sim_kwargs)
        first_snapshot = next(frames)
        initial_poses = {
            str(robot_id): (float(px), float(py))
            for robot_id, (px, py) in first_snapshot.get("poses", {}).items()
        }
        run = SystemRun(
            spec=spec,
            frames=frames,
            snapshot=first_snapshot,
            previous_poses=dict(initial_poses),
            previous_t_s=float(first_snapshot.get("t", 0.0)),
        )
        for robot_id in initial_poses:
            run.display_headings[robot_id] = _current_heading(first_snapshot, initial_poses, robot_id, 0.0)
        _record_history(run, metric_specs)
        runs.append(run)
    return runs


def _make_playback_controls(fig: Any) -> PlaybackControls:
    controls = PlaybackControls()
    button_ax = fig.add_axes([0.905, 0.845, 0.08, 0.04])
    button = Button(button_ax, "Pause", color="#f4f4f4", hovercolor="#e6e6e6")
    button.label.set_fontsize(9)

    def _set_paused(paused: bool) -> None:
        controls.paused = bool(paused)
        button.label.set_text("Resume" if controls.paused else "Pause")
        fig.canvas.draw_idle()

    def _toggle(_event: Any) -> None:
        _set_paused(not controls.paused)

    def _on_key_press(event: Any) -> None:
        if getattr(event, "key", None) in {" ", "space"}:
            _toggle(event)

    button.on_clicked(_toggle)
    fig.canvas.mpl_connect("key_press_event", _on_key_press)
    controls.button = button
    fig._demo_playback_controls = controls
    return controls


def _make_figure(config: dict[str, Any], runs: list[SystemRun], metric_specs: list[MetricSpec]) -> tuple[Any, dict[str, MetricArtists]]:
    display_cfg = config["display"]
    fig = plt.figure(
        figsize=(float(display_cfg["figure_width"]), float(display_cfg["figure_height"])),
        constrained_layout=False,
    )
    gs = fig.add_gridspec(
        2,
        1,
        height_ratios=[3.30, 1.25],
        left=0.035,
        right=0.995,
        top=0.84,
        bottom=0.06,
        hspace=0.34,
    )
    fig.suptitle(str(display_cfg["title"]), fontsize=16, fontweight="bold", y=0.975)

    map_grid = gs[0].subgridspec(
        2,
        3,
        height_ratios=[12.0, 1.55],
        hspace=0.05,
        wspace=0.14,
    )
    for idx, run in enumerate(runs):
        ax = fig.add_subplot(map_grid[0, idx])
        status_ax = fig.add_subplot(map_grid[1, idx])
        run.map_artists = _create_map_artists(ax, status_ax, run.spec.title, run.spec.color, run.snapshot, config)
        if idx == 0:
            ax.set_ylabel("Y (m)")
        else:
            ax.tick_params(axis="y", labelleft=False)

    legend_handles = _system_legend_handles(runs) + _map_legend_handles()
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.935),
        ncol=6,
        fontsize=int(display_cfg.get("legend_fontsize", 8)),
        frameon=True,
        handlelength=2.4,
        columnspacing=1.2,
        handletextpad=0.6,
    )

    duration_min = float(config["scenario"]["duration_s"]) / 60.0
    metric_axes = _create_metric_axes(fig, gs[1], metric_specs, runs, duration_min, config)
    return fig, metric_axes


def _render_once(
    runs: list[SystemRun],
    config: dict[str, Any],
    metric_axes: dict[str, MetricArtists],
    metric_specs: list[MetricSpec],
    map_view_state: MapViewState | None,
    interpolation_alpha: float = 1.0,
) -> MapViewState:
    duration_min = float(config["scenario"]["duration_s"]) / 60.0
    map_view_state = _update_shared_map_view_state(map_view_state, runs, config)
    for run in runs:
        _update_map(run, config, map_view_state, interpolation_alpha=interpolation_alpha)
    _update_metric_axes(metric_axes, runs, metric_specs, duration_min)
    return map_view_state


def run_demo(
    config: dict[str, Any],
    *,
    no_show: bool = False,
    max_frames: int | None = None,
    save_figure: Path | None = None,
) -> None:
    metric_specs = _metric_specs(config)
    continuous_run = (not no_show) and max_frames is None and save_figure is None
    run_config = deepcopy(config)
    if continuous_run:
        run_config.setdefault("scenario", {})
        run_config["scenario"]["duration_s"] = float("inf")
    runs = _build_runs(run_config, metric_specs)
    fig, metric_axes = _make_figure(config, runs, metric_specs)

    steps_per_frame = int(config["display"]["steps_per_frame"])
    fps = max(1, int(config["display"]["fps"]))
    frame_interval_s = 1.0 / float(fps)
    live_tracking_fps = max(float(fps), float(config["display"].get("live_tracking_fps", fps)))
    interpolation_subframes = 1 if no_show else max(1, int(math.ceil(live_tracking_fps / float(fps))))
    subframe_interval_s = frame_interval_s / float(interpolation_subframes)
    map_view_state: MapViewState | None = None
    playback_controls = _make_playback_controls(fig) if continuous_run else None

    map_view_state = _render_once(runs, config, metric_axes, metric_specs, map_view_state, interpolation_alpha=1.0)
    if not no_show:
        plt.ion()
        fig.show()
        fig.canvas.draw_idle()
        fig.canvas.flush_events()

    rendered_frames = 1
    while True:
        if max_frames is not None and rendered_frames >= int(max_frames):
            break
        if not no_show and not plt.fignum_exists(fig.number):
            break
        if playback_controls is not None and playback_controls.paused:
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            plt.pause(frame_interval_s)
            continue
        if not _advance_runs(runs, metric_specs, steps_per_frame):
            break
        rendered_frames += 1
        if no_show:
            map_view_state = _render_once(runs, config, metric_axes, metric_specs, map_view_state, interpolation_alpha=1.0)
            continue
        window_closed = False
        for subframe_idx in range(interpolation_subframes):
            if not plt.fignum_exists(fig.number):
                window_closed = True
                break
            while playback_controls is not None and playback_controls.paused:
                if not plt.fignum_exists(fig.number):
                    window_closed = True
                    break
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                plt.pause(frame_interval_s)
            if window_closed:
                break
            alpha = float(subframe_idx + 1) / float(interpolation_subframes)
            map_view_state = _render_once(
                runs,
                config,
                metric_axes,
                metric_specs,
                map_view_state,
                interpolation_alpha=alpha,
            )
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            plt.pause(subframe_interval_s)
        if window_closed:
            break

    if save_figure is not None:
        save_figure.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_figure, dpi=160)

    if not no_show and plt.fignum_exists(fig.number):
        plt.ioff()
        plt.show()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronized systems demo: reactive vs prediction_only vs proposed.")
    parser.add_argument(
        "--config",
        type=str,
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to a JSON demo config file.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Run the demo loop without opening a GUI window.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional limit for rendered frames. Useful for smoke tests; interactive runs continue until the window is closed when omitted.",
    )
    parser.add_argument(
        "--save-figure",
        type=str,
        default="",
        help="Optional path for a final-frame PNG export.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    config = load_config(config_path)
    save_figure = resolve_repo_path(args.save_figure) if str(args.save_figure).strip() else None
    run_demo(
        config,
        no_show=bool(args.no_show),
        max_frames=args.max_frames,
        save_figure=save_figure,
    )


if __name__ == "__main__":
    main()
