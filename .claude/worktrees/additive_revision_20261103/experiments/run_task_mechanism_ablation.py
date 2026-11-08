from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


TASK_MECHANISMS: tuple[dict[str, Any], ...] = (
    {
        "key": "reactive_patrol",
        "label": "R+P",
        "description": "Direct-detection reactive deterrence plus predictive patrol positioning.",
        "params": {
            "enable_direct_detection_tasks": True,
            "enable_predictive_patrol_tasks": True,
            "enable_model_scored_deterring": False,
            "preventive_policy": "off",
        },
    },
    {
        "key": "reactive_model_deterring",
        "label": "R+D",
        "description": "Direct-detection reactive deterrence plus model-scored predictive deterrence.",
        "params": {
            "enable_direct_detection_tasks": True,
            "enable_predictive_patrol_tasks": False,
            "enable_model_scored_deterring": True,
            "preventive_policy": "heuristic",
        },
    },
    {
        "key": "patrol_model_deterring",
        "label": "P+D",
        "description": "Predictive patrol positioning plus model-scored predictive deterrence, with direct detections used for learning but not turned into reactive tasks.",
        "params": {
            "enable_direct_detection_tasks": False,
            "enable_predictive_patrol_tasks": True,
            "enable_model_scored_deterring": True,
            "preventive_policy": "heuristic",
        },
    },
    {
        "key": "reactive_patrol_model_deterring",
        "label": "R+P+D",
        "description": "All three concrete task mechanisms enabled.",
        "params": {
            "enable_direct_detection_tasks": True,
            "enable_predictive_patrol_tasks": True,
            "enable_model_scored_deterring": True,
            "preventive_policy": "heuristic",
        },
    },
)


POLICIES: tuple[dict[str, Any], ...] = (
    {
        "key": "unc",
        "title": "UNC",
        "params": {"dispatch_policy": "unc"},
    },
    {
        "key": "res_0p25",
        "title": "RES rho=0.25",
        "params": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "utility",
        },
    },
    {
        "key": "res_rand_0p25",
        "title": "RES-RAND rho=0.25",
        "params": {
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
            "predictive_selection_policy": "random",
        },
    },
)


def _metrics() -> list[str]:
    return [
        "native_value_weighted_exposure",
        "native_reactive_mean_response_time_s",
        "total_robot_distance_m",
        "native_reactive_completed_fraction",
        "native_predictive_completed_fraction",
        "native_reactive_load_factor_truth",
        "native_reactive_load_factor_observable",
        "native_reactive_load_factor_observed",
        "native_reactive_load_factor_estimate",
        "native_truth_accepted_events",
        "native_truth_detections_observed",
        "native_reactive_generated_total",
        "native_reactive_admitted_total",
        "native_reactive_dispatched_total",
        "native_reactive_completed_total",
        "native_predictive_generated_total",
        "native_predictive_admitted_total",
        "native_predictive_dispatched_total",
        "native_predictive_completed_total",
        "native_predictive_expected_deltaJ_total",
        "native_predictive_raw_deltaJ_total",
        "native_predictive_success_ratio",
        "native_predictive_false_positive_ratio",
        "native_model_deterring_candidates_total",
        "native_model_deterring_generated",
        "native_model_deterring_accepted",
        "native_model_deterring_not_selected",
        "native_model_deterring_rejected_budget",
        "native_deterring_actions_completed_direct_detection",
        "native_deterring_actions_completed_model_scored",
        "native_suppression_per_direct_deterring_action",
        "native_suppression_per_model_deterring_action",
        "native_direct_detection_task_response_matches",
        "native_robot_idle_fraction_mean",
        "native_robot_reactive_fraction_mean",
        "native_robot_predictive_fraction_mean",
        "native_urgent_reactive_override_total",
    ]


def _time_plot_metrics() -> list[str]:
    return [
        "native_value_weighted_exposure",
        "native_reactive_mean_response_time_s",
        "native_reactive_load_factor_observed",
        "native_reactive_load_factor_estimate",
        "native_reactive_completed_fraction",
        "native_predictive_completed_fraction",
        "native_reactive_generated_total",
        "native_predictive_generated_total",
        "native_model_deterring_generated",
        "native_urgent_reactive_override_total",
        "active_tasks",
        "completed_deterring_total",
        "completed_patrolling_total",
    ]


def _selected(values: list[str] | None, defaults: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    if not values:
        return list(defaults)
    wanted = {str(v).strip() for item in values for v in str(item).split(",") if str(v).strip()}
    out = [entry for entry in defaults if str(entry["key"]) in wanted]
    missing = sorted(wanted - {str(entry["key"]) for entry in out})
    if missing:
        valid = ", ".join(str(entry["key"]) for entry in defaults)
        raise ValueError(f"Unknown selection(s) {missing}. Valid values: {valid}")
    return out


def _build_config(
    *,
    outdir: Path,
    num_runs: int,
    seed_start: int,
    duration_s: float,
    warmup_s: float,
    sample_every_s: float,
    robot_count: int,
    mu_true: float,
    alpha_true: float,
    include_fallback_patrol: bool,
    mechanisms: list[dict[str, Any]],
    policies: list[dict[str, Any]],
) -> dict[str, Any]:
    systems = []
    for mechanism in mechanisms:
        for policy in policies:
            params = {}
            params.update(dict(mechanism["params"]))
            params.update(dict(policy["params"]))
            systems.append(
                {
                    "key": f"{policy['key']}__{mechanism['key']}",
                    "type": "repo_module",
                    "repo": "current",
                    "module": "DeterrentSystem",
                    "title": f"{policy['title']} {mechanism['label']}",
                    "description": str(mechanism["description"]),
                    "params": params,
                }
            )

    return {
        "scenario": {
            "num_runs": int(num_runs),
            "seed_start": int(seed_start),
            "duration_s": float(duration_s),
            "dt": 1.0,
            "fps": 1,
            "W": 500.0,
            "H": 500.0,
            "NX": 120,
            "NY": 96,
            "Nrobots": int(robot_count),
            "uav_fraction": 0.0,
            "task_replan_period_s": 45.0,
            "arrival_radius_m": 3.0,
            "hold_time_s": 20.0,
            "sample_every_s": float(sample_every_s),
            "warmup_s": float(warmup_s),
            "extra_params": {
                "simulation_mode": "proposed",
                "planner_profile": "thesis_calibrated_selective_proposed",
                "enable_patrolling": True,
                "include_fallback_patrol": bool(include_fallback_patrol),
                "enable_intervention_feedback": True,
                "use_ground_truth": True,
                "mu_true": float(mu_true),
                "alpha_true": float(alpha_true),
                "bird_detection_prob": 1.0,
                "detect_range_m": 30.0,
                "reactive_load_factor_window_s": 120.0,
                "report_metrics_end": False,
                "telemetry_clear_on_start": False,
                "telemetry_prompt_save": False,
            },
        },
        "outputs": {
            "outdir": str(outdir),
            "reference_system": systems[0]["key"] if systems else "",
            "metrics": _metrics(),
            "scoreboard_metrics": [
                "native_value_weighted_exposure",
                "native_reactive_mean_response_time_s",
                "total_robot_distance_m",
                "native_reactive_completed_fraction",
                "native_predictive_completed_fraction",
                "native_predictive_raw_deltaJ_total",
                "native_model_deterring_generated",
                "native_deterring_actions_completed_model_scored",
            ],
            "time_plot_metrics": _time_plot_metrics(),
        },
        "systems": systems,
        "metadata": {
            "experiment": "task_mechanism_ablation",
            "task_mechanisms": [
                {
                    "key": str(item["key"]),
                    "label": str(item["label"]),
                    "description": str(item["description"]),
                    "params": dict(item["params"]),
                }
                for item in mechanisms
            ],
            "policies": [str(item["key"]) for item in policies],
            "legend": {
                "R": "direct-detection reactive deterrence",
                "P": "predictive patrol positioning",
                "D": "model-scored predictive deterrence",
            },
            "include_fallback_patrol": bool(include_fallback_patrol),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a task-mechanism ablation over the three concrete task mechanisms: "
            "reactive direct detections, predictive patrol, and model-scored predictive deterrence."
        )
    )
    parser.add_argument("--outdir", type=Path, default=Path("results/testbench/task_mechanism_ablation_pilot"))
    parser.add_argument("--config", type=Path, default=Path("testbench/task_mechanism_ablation_pilot.json"))
    parser.add_argument("--skip-run", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--num-runs", type=int, default=2)
    parser.add_argument("--seed-start", type=int, default=123)
    parser.add_argument("--duration-s", type=float, default=3600.0)
    parser.add_argument("--warmup-s", type=float, default=3600.0)
    parser.add_argument("--sample-every-s", type=float, default=120.0)
    parser.add_argument("--robots", type=int, default=2)
    parser.add_argument("--mu-true", type=float, default=5.0e-6)
    parser.add_argument("--alpha-true", type=float, default=0.30)
    parser.add_argument("--include-fallback-patrol", action="store_true")
    parser.add_argument("--mechanisms", nargs="*", default=None, help="Subset: reactive_patrol reactive_model_deterring patrol_model_deterring reactive_patrol_model_deterring")
    parser.add_argument("--policies", nargs="*", default=None, help="Subset: unc res_0p25 res_rand_0p25")
    args = parser.parse_args()

    mechanisms = _selected(args.mechanisms, TASK_MECHANISMS)
    policies = _selected(args.policies, POLICIES)
    config = _build_config(
        outdir=Path(args.outdir),
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        duration_s=float(args.duration_s),
        warmup_s=float(args.warmup_s),
        sample_every_s=float(args.sample_every_s),
        robot_count=int(args.robots),
        mu_true=float(args.mu_true),
        alpha_true=float(args.alpha_true),
        include_fallback_patrol=bool(args.include_fallback_patrol),
        mechanisms=mechanisms,
        policies=policies,
    )
    config_path = Path(args.config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[task-mechanism-ablation] wrote {config_path}")
    print(f"[task-mechanism-ablation] systems={len(config['systems'])} runs={len(config['systems']) * int(args.num_runs)}")
    if args.skip_run:
        print(
            "[task-mechanism-ablation] run with: "
            f"{sys.executable} -m testbench.run_testbench --config {config_path} --max-workers {int(args.max_workers)}"
        )
        return 0
    subprocess.run(
        [
            sys.executable,
            "-m",
            "testbench.run_testbench",
            "--config",
            str(config_path),
            "--max-workers",
            str(int(args.max_workers)),
        ],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
