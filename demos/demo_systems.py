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

import DeterrentSystem as ds
from simplification.stages import get_stage


DEFAULT_CONFIG_PATH = Path("configs/demo_config.json")


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
        "figure_width": 19.0,
        "figure_height": 10.5,
        "fps": 10,
        "steps_per_frame": 1,
        "goal_match_radius_m": 25.0,
        "task_line_alpha": 0.75,
        "queued_task_line_alpha": 0.50,
        "label_fontsize": 8,
    },
    "robot_rendering": {
        "husky_length_m": 0.99,
        "husky_width_m": 0.67,
        "heading_line_m": 2.0,
        "label_offset_m": 2.0,
        "body_alpha": 0.90,
    },
    "vineyard": {
        "W": 500.0,
        "H": 500.0,
        "row_spacing_m": 4.8,
        "row_width_m": 3.2,
        "headland_space_m": 10.0,
        "turn_space_m": 20.0,
    },
    "scenario": {
        "duration_s": 1800.0,
        "dt": 5.0,
        "seed": 321,
        "fps": 1,
        "NX": 90,
        "NY": 72,
        "Nrobots": 6,
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
            "overrides": {},
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
            "overrides": {},
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
    history_t_min: list[float] = field(default_factory=list)
    history_metrics: dict[str, list[float]] = field(default_factory=dict)
    map_artists: MapArtists | None = None


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
) -> float:
    pose = snapshot.get("poses", {}).get(robot_id)
    if pose is None:
        return 0.0
    x, y = pose
    goal = snapshot.get("robot_goals", {}).get(robot_id)
    if goal is not None:
        dx = float(goal[0]) - float(x)
        dy = float(goal[1]) - float(y)
        if (dx * dx + dy * dy) > 1.0e-9:
            return math.atan2(dy, dx)
    prev = previous_pose.get(robot_id)
    if prev is not None:
        dx = float(x) - float(prev[0])
        dy = float(y) - float(prev[1])
        if (dx * dx + dy * dy) > 1.0e-9:
            return math.atan2(dy, dx)
    return 0.0


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


def _scatter_points(tasks: list[dict[str, Any]]) -> np.ndarray:
    if not tasks:
        return np.empty((0, 2), dtype=float)
    return np.array([(float(task.get("x", 0.0)), float(task.get("y", 0.0))) for task in tasks], dtype=float)


def _set_scatter_points(scatter_artist: Any, pts: np.ndarray) -> None:
    if pts.size == 0:
        scatter_artist.set_offsets(np.empty((0, 2), dtype=float))
    else:
        scatter_artist.set_offsets(pts)


def _configure_map_axis(ax: Any, title: str, color: str, W: float, H: float, turn_space_m: float) -> None:
    ax.set_title(title, color=color, fontsize=12, fontweight="bold")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-turn_space_m - 10.0, W + turn_space_m + 10.0)
    ax.set_ylim(-turn_space_m - 10.0, H + turn_space_m + 10.0)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.grid(alpha=0.12)


def _create_map_artists(
    ax: Any,
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

    _configure_map_axis(ax, title, system_color, W, H, turn_space_m)

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
    for row_polygon in row_polygons:
        patch = MplPolygon(
            row_polygon,
            closed=True,
            fill=True,
            alpha=0.15,
            edgecolor="none",
            facecolor="#6f8f5e",
            zorder=0.1,
        )
        ax.add_patch(patch)
        row_patches.append(patch)
    if row_center_lines:
        row_lines = LineCollection(
            row_center_lines,
            colors="#557148",
            linewidths=0.35,
            alpha=0.30,
            zorder=0.2,
        )
        ax.add_collection(row_lines)

    zone_patches: list[Any] = []
    zone_colors = plt.get_cmap("tab20")(np.linspace(0.0, 1.0, max(len(snapshot["cells"]), 1)))
    for idx, cell in enumerate(snapshot["cells"]):
        if not cell:
            zone_patches.append(None)
            continue
        zone_color = zone_colors[idx % len(zone_colors)]
        patch = MplPolygon(
            cell,
            closed=True,
            fill=True,
            alpha=0.10,
            edgecolor=zone_color,
            facecolor=zone_color,
            linewidth=1.0,
            zorder=0.4,
        )
        ax.add_patch(patch)
        zone_patches.append(patch)

    truth_scatter = ax.scatter([], [], s=36, c="#2ca02c", marker="x", zorder=4)
    detection_scatter = ax.scatter([], [], s=36, c="#ff7f0e", marker="x", zorder=5)
    deterring_active_scatter = ax.scatter([], [], s=70, c="#d62728", marker="o", edgecolors="black", linewidths=0.4, zorder=6)
    deterring_queued_scatter = ax.scatter([], [], s=58, facecolors="none", edgecolors="#d62728", marker="o", linewidths=1.1, zorder=5.5)
    patrol_active_scatter = ax.scatter([], [], s=72, c="#1f77b4", marker="D", edgecolors="black", linewidths=0.3, zorder=6)
    patrol_queued_scatter = ax.scatter([], [], s=60, facecolors="none", edgecolors="#1f77b4", marker="D", linewidths=1.0, zorder=5.5)
    active_line_collection = LineCollection([], colors="#444444", linewidths=1.2, alpha=float(display_cfg["task_line_alpha"]), zorder=3)
    queued_line_collection = LineCollection([], colors="#777777", linewidths=1.0, alpha=float(display_cfg["queued_task_line_alpha"]), zorder=2.8)
    queued_line_collection.set_linestyle("dashed")
    ax.add_collection(active_line_collection)
    ax.add_collection(queued_line_collection)

    robot_patches: dict[str, Any] = {}
    robot_heading_lines: dict[str, Any] = {}
    robot_labels: dict[str, Any] = {}
    robot_colors = plt.get_cmap("tab10")(np.linspace(0.0, 1.0, max(len(snapshot["poses"]), 1)))
    for idx, robot_id in enumerate(sorted(snapshot["poses"].keys())):
        x, y = snapshot["poses"][robot_id]
        robot_color = robot_colors[idx % len(robot_colors)]
        body = MplPolygon(
            _vehicle_polygon(
                float(x),
                float(y),
                0.0,
                float(robot_cfg["husky_length_m"]),
                float(robot_cfg["husky_width_m"]),
            ),
            closed=True,
            fill=True,
            edgecolor="black",
            facecolor=robot_color,
            linewidth=0.7,
            alpha=float(robot_cfg["body_alpha"]),
            zorder=7,
        )
        ax.add_patch(body)
        robot_patches[robot_id] = body
        (heading_line,) = ax.plot([], [], color="black", linewidth=0.9, zorder=7.1)
        robot_heading_lines[robot_id] = heading_line
        label = ax.text(
            float(x) + float(robot_cfg["label_offset_m"]),
            float(y) + float(robot_cfg["label_offset_m"]),
            str(robot_id),
            fontsize=int(display_cfg["label_fontsize"]),
            color="black",
            zorder=8,
            bbox={"boxstyle": "round,pad=0.18", "fc": "white", "ec": "none", "alpha": 0.8},
        )
        robot_labels[robot_id] = label

    info_text = ax.text(
        0.02,
        0.98,
        "",
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=9,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.30", "fc": "white", "ec": "#cccccc", "alpha": 0.90},
        zorder=9,
    )

    return MapArtists(
        axis=ax,
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
        info_text=info_text,
    )


def _update_map(run: SystemRun, config: dict[str, Any]) -> None:
    assert run.map_artists is not None
    artists = run.map_artists
    snapshot = run.snapshot
    display_cfg = config["display"]
    robot_cfg = config["robot_rendering"]
    buckets = _task_buckets(snapshot, goal_match_radius_m=float(display_cfg["goal_match_radius_m"]))

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
        heading = _current_heading(snapshot, run.previous_poses, robot_id)
        artists.robot_patches[robot_id].set_xy(
            _vehicle_polygon(
                x,
                y,
                heading,
                float(robot_cfg["husky_length_m"]),
                float(robot_cfg["husky_width_m"]),
            )
        )
        heading_len = 0.5 * float(robot_cfg["husky_length_m"]) + float(robot_cfg["heading_line_m"])
        artists.robot_heading_lines[robot_id].set_data(
            [x, x + heading_len * math.cos(heading)],
            [y, y + heading_len * math.sin(heading)],
        )
        artists.robot_labels[robot_id].set_position(
            (
                x + float(robot_cfg["label_offset_m"]),
                y + float(robot_cfg["label_offset_m"]),
            )
        )
        artists.robot_labels[robot_id].set_text(str(robot_id))

    metrics = snapshot.get("metrics", {}) or {}
    robot_states = snapshot.get("robot_states", {}) or {}
    moving_count = sum(1 for state in robot_states.values() if state == "moving")
    holding_count = sum(1 for state in robot_states.values() if state == "holding")
    idle_count = sum(1 for state in robot_states.values() if state == "idle")
    completed_by_type = metrics.get("completed_tasks_by_type", {}) or {}
    info_lines = [
        f"t       {_fmt_hms(snapshot.get('t', 0.0))}",
        f"m/h/i   {moving_count}/{holding_count}/{idle_count}",
        f"cur D/P {len(buckets['current_deterring'])}/{len(buckets['current_patrol'])}",
        f"qed D/P {len(buckets['queued_deterring'])}/{len(buckets['queued_patrol'])}",
        f"done    {int(_safe_float(metrics.get('completed_tasks_total', 0.0))):d}",
        f"done D  {int(_safe_float(completed_by_type.get('deterring', 0.0))):d}",
        f"exp     {_fmt_metric(metrics.get('value_weighted_exposure'), '{:.1f}')}",
        f"resp    {_fmt_metric(metrics.get('mean_response_time_s'), '{:.1f}')}",
        f"birds%  {_fmt_metric(metrics.get('birds_deterred_pct_last_hour'), '{:.1f}')}",
        f"msgs    {int(_safe_float(metrics.get('boundary_message_count', 0.0))):d}",
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


def _create_metric_axes(fig: Any, parent_spec: Any, metric_specs: list[MetricSpec], systems: list[SystemRun], duration_min: float) -> dict[str, MetricArtists]:
    rows = int(math.ceil(len(metric_specs) / 2.0))
    cols = min(2, len(metric_specs))
    subgrid = parent_spec.subgridspec(rows, cols, hspace=0.35, wspace=0.22)
    artists: dict[str, MetricArtists] = {}
    for idx, metric in enumerate(metric_specs):
        ax = fig.add_subplot(subgrid[idx // cols, idx % cols])
        ax.set_title(f"{metric.label} ({metric.goal} better)", fontsize=10)
        ax.set_xlim(0.0, max(duration_min * 1.12, 1.0))
        ax.set_xlabel("Sim Time (min)")
        ax.grid(alpha=0.25)
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
        if idx == 0:
            ax.legend(loc="best", fontsize=8)
        artists[metric.key] = MetricArtists(axis=ax, lines=line_map, markers=marker_map, labels=label_map)
    return artists


def _update_metric_axes(metric_axes: dict[str, MetricArtists], systems: list[SystemRun], metric_specs: list[MetricSpec], duration_min: float) -> None:
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
        ax.set_xlim(0.0, max(duration_min * 1.12, 1.0))
        ax.relim()
        ax.autoscale_view(scalex=False, scaley=True)
        y_min, y_max = ax.get_ylim()
        label_positions = _stack_metric_label_positions(last_points, y_min=y_min, y_max=y_max)
        label_x = max(duration_min, 1.0) * 1.015
        for run in systems:
            label_artist = metric_artist.labels[run.spec.key]
            match = next((item for item in last_points if item["key"] == run.spec.key), None)
            if match is None:
                label_artist.set_text("")
                continue
            label_artist.set_position((label_x, label_positions.get(run.spec.key, float(match["y"]))))
            label_artist.set_text(f"{run.spec.short_label} {match['y']:.1f}")


def _legend_handles() -> list[Any]:
    return [
        Line2D([], [], color="black", linewidth=1.2, label="Current task link"),
        Line2D([], [], color="#777777", linewidth=1.0, linestyle="dashed", label="Queued task link"),
        Line2D([], [], marker="o", color="w", markerfacecolor="#d62728", markeredgecolor="black", markersize=8, label="Deterring current"),
        Line2D([], [], marker="o", color="w", markerfacecolor="none", markeredgecolor="#d62728", markersize=8, label="Deterring queued"),
        Line2D([], [], marker="D", color="w", markerfacecolor="#1f77b4", markeredgecolor="black", markersize=8, label="Patrol current"),
        Line2D([], [], marker="D", color="w", markerfacecolor="none", markeredgecolor="#1f77b4", markersize=8, label="Patrol queued"),
        Line2D([], [], marker="x", color="#2ca02c", linestyle="none", markersize=8, label="Truth"),
        Line2D([], [], marker="x", color="#ff7f0e", linestyle="none", markersize=8, label="Detection"),
    ]


def _build_runs(config: dict[str, Any], metric_specs: list[MetricSpec]) -> list[SystemRun]:
    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    runs: list[SystemRun] = []
    for spec in _resolve_system_specs(config):
        frames = ds.run_simulation_frames_persistent(**spec.sim_kwargs)
        first_snapshot = next(frames)
        run = SystemRun(spec=spec, frames=frames, snapshot=first_snapshot)
        _record_history(run, metric_specs)
        runs.append(run)
    return runs


def _make_figure(config: dict[str, Any], runs: list[SystemRun], metric_specs: list[MetricSpec]) -> tuple[Any, dict[str, MetricArtists]]:
    display_cfg = config["display"]
    fig = plt.figure(
        figsize=(float(display_cfg["figure_width"]), float(display_cfg["figure_height"])),
        constrained_layout=False,
    )
    gs = fig.add_gridspec(
        2,
        6,
        height_ratios=[2.55, 1.85],
        left=0.04,
        right=0.99,
        top=0.91,
        bottom=0.06,
        hspace=0.28,
        wspace=0.22,
    )
    fig.suptitle(str(display_cfg["title"]), fontsize=16, fontweight="bold")

    for idx, run in enumerate(runs):
        ax = fig.add_subplot(gs[0, 2 * idx : 2 * (idx + 1)])
        run.map_artists = _create_map_artists(ax, run.spec.title, run.spec.color, run.snapshot, config)

    runs[0].map_artists.axis.legend(handles=_legend_handles(), loc="lower left", fontsize=7, frameon=True)

    duration_min = float(config["scenario"]["duration_s"]) / 60.0
    metric_axes = _create_metric_axes(fig, gs[1, :], metric_specs, runs, duration_min)
    return fig, metric_axes


def _render_once(runs: list[SystemRun], config: dict[str, Any], metric_axes: dict[str, MetricArtists], metric_specs: list[MetricSpec]) -> None:
    duration_min = float(config["scenario"]["duration_s"]) / 60.0
    for run in runs:
        _update_map(run, config)
    _update_metric_axes(metric_axes, runs, metric_specs, duration_min)


def run_demo(
    config: dict[str, Any],
    *,
    no_show: bool = False,
    max_frames: int | None = None,
    save_figure: Path | None = None,
) -> None:
    metric_specs = _metric_specs(config)
    runs = _build_runs(config, metric_specs)
    fig, metric_axes = _make_figure(config, runs, metric_specs)

    steps_per_frame = int(config["display"]["steps_per_frame"])
    fps = max(1, int(config["display"]["fps"]))
    frame_interval_s = 1.0 / float(fps)

    _render_once(runs, config, metric_axes, metric_specs)
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
        if not _advance_runs(runs, metric_specs, steps_per_frame):
            break
        _render_once(runs, config, metric_axes, metric_specs)
        rendered_frames += 1
        if no_show:
            continue
        fig.canvas.draw_idle()
        fig.canvas.flush_events()
        plt.pause(frame_interval_s)

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
        help="Optional limit for rendered frames. Useful for smoke tests.",
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
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    save_figure = Path(args.save_figure).expanduser().resolve() if str(args.save_figure).strip() else None
    run_demo(
        config,
        no_show=bool(args.no_show),
        max_frames=args.max_frames,
        save_figure=save_figure,
    )


if __name__ == "__main__":
    main()
