from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import DeterrentSystem as ds


DEFAULT_REFERENCE = Path("regression_references/core_default_proposed_seed123_t10_dt1.json")
REFERENCE_SCHEMA_VERSION = 1


def _round_float(value: float, digits: int = 12) -> float | str:
    value = float(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return round(value, digits)


def _normalize_point(value: Any) -> list[float] | None:
    if value is None:
        return None
    return [_round_float(float(value[0]), 6), _round_float(float(value[1]), 6)]


def _normalize_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(mapping.keys()):
        value = mapping[key]
        if isinstance(value, dict):
            out[str(key)] = _normalize_mapping(value)
        elif isinstance(value, (list, tuple)):
            out[str(key)] = [_normalize_scalar(v) for v in value]
        else:
            out[str(key)] = _normalize_scalar(value)
    return out


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, float):
        return _round_float(value)
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return _normalize_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_normalize_scalar(v) for v in value]
    return str(value)


def _normalize_motion_command(command: dict[str, Any]) -> dict[str, Any]:
    return {
        "robot_id": str(command.get("robot_id")),
        "command_type": str(command.get("command_type")),
        "source": str(command.get("source")),
        "assigned_task_id": command.get("assigned_task_id"),
        "assigned_task_type": command.get("assigned_task_type"),
        "assigned_task_mode": command.get("assigned_task_mode"),
        "goal": _normalize_point(command.get("goal")),
        "effective_goal": _normalize_point(command.get("effective_goal")),
        "current_pose": _normalize_point(command.get("current_pose")),
    }


def build_fingerprint(
    *,
    seed: int,
    t_end: float,
    dt: float,
    fps: int,
    simulation_mode: str,
    **sim_kwargs,
) -> dict[str, Any]:
    mon = getattr(ds, "mon", None)
    prev_enabled = getattr(mon, "enabled", None) if mon is not None else None
    if mon is not None and hasattr(mon, "enabled"):
        mon.enabled = False
    try:
        frames = list(
            ds.run_simulation_frames_persistent(
                seed=seed,
                T_end=t_end,
                dt=dt,
                fps=fps,
                simulation_mode=simulation_mode,
                report_metrics_end=False,
                telemetry_clear_on_start=False,
                telemetry_prompt_save=False,
                motion_orchestration_mode="local",
                motion_command_callback=None,
                motion_state_callback=None,
                **sim_kwargs,
            )
        )
    finally:
        if mon is not None and prev_enabled is not None:
            mon.enabled = prev_enabled

    per_frame: list[dict[str, Any]] = []
    for frame in frames:
        per_frame.append(
            {
                "t": _round_float(float(frame["t"]), 6),
                "poses": {str(rid): _normalize_point(xy) for rid, xy in sorted(frame["poses"].items())},
                "robot_states": {str(rid): str(state) for rid, state in sorted(frame["robot_states"].items())},
                "robot_goals": {str(rid): _normalize_point(xy) for rid, xy in sorted(frame["robot_goals"].items())},
                "active_task_ids": sorted(int(task["id"]) for task in frame["tasks_active"]),
                "done_task_ids": sorted(int(task["id"]) for task in frame["tasks_done"]),
                "motion_commands": [_normalize_motion_command(cmd) for cmd in frame.get("motion_commands", [])],
                "task_generation_structured": {
                    "candidate_count": int(frame["task_generation_structured"]["candidate_count"]),
                    "patrolling_enabled": bool(frame["task_generation_structured"]["patrolling_enabled"]),
                },
                "dispatch_structured": {
                    "candidate_count": int(frame["dispatch_structured"]["candidate_count"]),
                    "accepted_count": int(frame["dispatch_structured"]["accepted_count"]),
                    "rejected_counts": _normalize_mapping(frame["dispatch_structured"]["rejected_counts"]),
                },
                "motion_execution_structured": {
                    "motion_orchestration_mode": str(frame["motion_execution_structured"]["motion_orchestration_mode"]),
                    "motion_execution_backend": str(frame["motion_execution_structured"]["motion_execution_backend"]),
                    "external_feedback_applied": bool(frame["motion_execution_structured"]["external_feedback_applied"]),
                    "external_pose_updates_this_step": int(frame["motion_execution_structured"]["external_pose_updates_this_step"]),
                    "goals_active_count": int(frame["motion_execution_structured"]["goals_active_count"]),
                    "completed_patrolling_this_step": int(frame["motion_execution_structured"]["completed_patrolling_this_step"]),
                    "completed_deterring_this_step": int(frame["motion_execution_structured"]["completed_deterring_this_step"]),
                    "stale_goal_clears_this_step": int(frame["motion_execution_structured"]["stale_goal_clears_this_step"]),
                },
                "truth_generation_structured": {
                    "truth_events_added_this_step": int(frame["truth_generation_structured"]["truth_events_added_this_step"]),
                    "detections_added_this_step": int(frame["truth_generation_structured"]["detections_added_this_step"]),
                    "truth_candidate_events_total": int(frame["truth_generation_structured"]["truth_candidate_events_total"]),
                    "truth_accepted_events_total": int(frame["truth_generation_structured"]["truth_accepted_events_total"]),
                    "truth_suppressed_events_total": int(frame["truth_generation_structured"]["truth_suppressed_events_total"]),
                },
                "forecast_model_structured": {
                    "forecast_eval_ran_this_step": bool(frame["forecast_model_structured"]["forecast_eval_ran_this_step"]),
                    "forecast_future_event_count": int(frame["forecast_model_structured"]["forecast_future_event_count"]),
                    "forecast_hotspot_count": int(frame["forecast_model_structured"]["forecast_hotspot_count"]),
                    "forecast_hit_count": int(frame["forecast_model_structured"]["forecast_hit_count"]),
                    "forecast_covered_event_count": int(frame["forecast_model_structured"]["forecast_covered_event_count"]),
                },
            }
        )

    return {
        "reference_schema_version": REFERENCE_SCHEMA_VERSION,
        "metadata": {
            "seed": int(seed),
            "t_end": _round_float(float(t_end), 6),
            "dt": _round_float(float(dt), 6),
            "fps": int(fps),
            "simulation_mode": str(simulation_mode),
        },
        "frame_count": int(len(per_frame)),
        "final_metrics_compact": _normalize_mapping(frames[-1]["metrics_compact"] if frames else {}),
        "frames": per_frame,
    }


def _compare(expected: Any, actual: Any, path: str = "root") -> tuple[bool, str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        expected_keys = set(expected.keys())
        actual_keys = set(actual.keys())
        if expected_keys != actual_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            return False, f"{path}: key mismatch missing={missing} extra={extra}"
        for key in sorted(expected_keys):
            ok, msg = _compare(expected[key], actual[key], f"{path}.{key}")
            if not ok:
                return ok, msg
        return True, "ok"
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return False, f"{path}: length mismatch {len(expected)} != {len(actual)}"
        for idx, (exp_item, act_item) in enumerate(zip(expected, actual)):
            ok, msg = _compare(exp_item, act_item, f"{path}[{idx}]")
            if not ok:
                return ok, msg
        return True, "ok"
    if expected != actual:
        return False, f"{path}: {expected!r} != {actual!r}"
    return True, "ok"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze or compare a deterministic core-system regression reference.")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE, help="Reference JSON file.")
    parser.add_argument("--write-reference", action="store_true", help="Write the current run as the frozen reference.")
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--t-end", type=float, default=10.0)
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument("--fps", type=int, default=1)
    parser.add_argument("--simulation-mode", default="proposed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fingerprint = build_fingerprint(
        seed=args.seed,
        t_end=args.t_end,
        dt=args.dt,
        fps=args.fps,
        simulation_mode=args.simulation_mode,
    )
    args.reference.parent.mkdir(parents=True, exist_ok=True)
    if args.write_reference:
        args.reference.write_text(json.dumps(fingerprint, indent=2), encoding="utf-8")
        print(f"[regression] wrote reference: {args.reference}")
        return 0

    if not args.reference.exists():
        print(f"[regression] missing reference: {args.reference}")
        print("[regression] rerun with --write-reference to freeze the current baseline.")
        return 2

    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    ok, msg = _compare(reference, fingerprint)
    if ok:
        print(f"[regression] PASS {args.reference}")
        return 0
    print(f"[regression] FAIL {args.reference}")
    print(f"[regression] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
