from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_ROBOT_COUNTS: tuple[int, ...] = (3, 2)
DEFAULT_MU_VALUES: tuple[float, ...] = (1.0e-5,)
DEFAULT_RESERVATION_FRACTIONS: tuple[float, ...] = (
    0.00,
    0.05,
    0.10,
    0.15,
    0.20,
    0.25,
    0.30,
    0.35,
    0.40,
)


def _value_token(value: float) -> str:
    text = f"{float(value):.0e}".replace("+", "")
    return text.replace("-", "m").replace(".", "p")


def _fraction_token(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".").replace(".", "p")


def _parse_float_list(values: list[str] | None, default: tuple[float, ...]) -> list[float]:
    if not values:
        return list(default)
    out: list[float] = []
    for item in values:
        for part in str(item).split(","):
            token = part.strip()
            if token:
                out.append(float(token))
    if not out:
        raise ValueError("Expected at least one float value.")
    return out


def _metrics() -> list[str]:
    return [
        "native_value_weighted_exposure",
        "native_reactive_mean_response_time_s",
        "total_robot_distance_m",
        "native_reactive_completed_fraction",
        "native_predictive_completed_fraction",
        "native_reactive_load_factor_truth_candidate",
        "native_reactive_load_factor_truth",
        "native_reactive_load_factor_observable",
        "native_reactive_load_factor_observed",
        "native_reactive_load_factor_estimate",
        "native_reactive_load_window_truth_candidate_events",
        "native_reactive_load_window_truth_accepted_events",
        "native_reactive_load_window_detection_opportunities",
        "native_reactive_load_window_detections_in_range",
        "native_reactive_load_window_detections_observed",
        "native_truth_candidate_events",
        "native_truth_accepted_events",
        "native_truth_detection_opportunities",
        "native_truth_detections_observed",
        "native_reactive_generated_total",
        "native_reactive_admitted_total",
        "native_reactive_dispatched_total",
        "native_reactive_completed_total",
        "native_predictive_generated_total",
        "native_predictive_admitted_total",
        "native_predictive_dispatched_total",
        "native_predictive_completed_total",
        "native_robot_idle_fraction_mean",
        "native_robot_reactive_fraction_mean",
        "native_robot_predictive_fraction_mean",
        "native_urgent_reactive_override_total",
    ]


def _time_plot_metrics() -> list[str]:
    return [
        "native_reactive_load_factor_truth",
        "native_reactive_load_factor_observable",
        "native_reactive_load_factor_observed",
        "native_reactive_load_factor_estimate",
        "native_value_weighted_exposure",
        "native_reactive_mean_response_time_s",
        "native_reactive_completed_fraction",
        "native_predictive_completed_fraction",
        "native_urgent_reactive_override_total",
        "active_tasks",
    ]


def _policy_systems(*, reservation_fractions: list[float]) -> list[dict[str, Any]]:
    systems: list[dict[str, Any]] = [
        {
            "key": "unc",
            "title": "UNC",
            "description": "Unconstrained mixed-greedy dispatch baseline.",
            "params": {"dispatch_policy": "unc"},
        }
    ]

    for fraction in reservation_fractions:
        if fraction < 0.0 or fraction > 1.0:
            raise ValueError(f"reservation_fraction must be in [0, 1], got {fraction!r}")
        token = _fraction_token(float(fraction))
        common = {
            "dispatch_policy": "res",
            "reservation_fraction": float(fraction),
            "reservation_window_s": 600.0,
            "reactive_override_slack_s": 90.0,
        }
        systems.append(
            {
                "key": f"res_{token}",
                "title": f"RES rho={fraction:.2f}",
                "description": "Reserved-capacity policy with utility-ranked predictive selection.",
                "params": {
                    **common,
                    "predictive_selection_policy": "utility",
                },
            }
        )
        systems.append(
            {
                "key": f"res_rand_{token}",
                "title": f"RES-RAND rho={fraction:.2f}",
                "description": "Reserved-capacity random-selection ablation at the same reservation fraction.",
                "params": {
                    **common,
                    "predictive_selection_policy": "random",
                },
            }
        )
        systems.append(
            {
                "key": f"res_idle_feasible_confidence_{token}",
                "title": f"RES-IFC rho={fraction:.2f}",
                "description": (
                    "Most selective next-formulation policy: idle-only, reactive-pressure-gated, "
                    "deadline-feasible, confidence-weighted reservation."
                ),
                "params": {
                    "dispatch_policy": "res-idle-feasible-confidence",
                    "reservation_fraction": float(fraction),
                    "reservation_window_s": 600.0,
                    "reactive_override_slack_s": 90.0,
                    "predictive_selection_policy": "confidence-weighted",
                    "enable_predictive_lead_time": True,
                    "predictive_timing_mode": "arrival_offset",
                    "predictive_lead_time_min_s": 30.0,
                    "predictive_lead_time_max_eta_s": 120.0,
                    "predictive_lead_time_buffer_s": 15.0,
                    "predictive_lead_time_risk_power": 1.0,
                    "predictive_slack_min_s": 15.0,
                    "reactive_pressure_max_for_predictive": 0.5,
                    "predictive_confidence_min": 0.25,
                    "predictive_deadline_weight": 2.0,
                    "predictive_eta_penalty_weight": 0.1,
                    "predictive_confidence_source": "p_event_times_selection_weight",
                },
            }
        )
    return systems


def _build_config(
    *,
    robot_count: int,
    mu_true: float,
    mode_label: str,
    num_runs: int,
    seed_start: int,
    duration_s: float,
    sample_every_s: float,
    warmup_s: float,
    bird_detection_prob: float,
    detect_range_m: float,
    alpha_true: float,
    reactive_load_factor_window_s: float,
    reservation_fractions: list[float],
    outdir: Path,
) -> dict[str, Any]:
    pressure_key = f"mu_{_value_token(mu_true)}"
    systems = []
    for policy in _policy_systems(reservation_fractions=reservation_fractions):
        systems.append(
            {
                "key": policy["key"],
                "type": "repo_module",
                "repo": "current",
                "module": "DeterrentSystem",
                "title": f"{policy['title']} {robot_count} Robots {pressure_key}",
                "description": policy["description"],
                "params": dict(policy["params"]),
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
                "enable_patrolling": True,
                "enable_intervention_feedback": True,
                "include_fallback_patrol": True,
                "enable_model_scored_deterring": False,
                "planner_profile": "thesis_calibrated_selective_proposed",
                "use_ground_truth": True,
                "mu_true": float(mu_true),
                "alpha_true": float(alpha_true),
                "bird_detection_prob": float(bird_detection_prob),
                "detect_range_m": float(detect_range_m),
                "reactive_load_factor_window_s": float(reactive_load_factor_window_s),
                "report_metrics_end": False,
                "telemetry_clear_on_start": False,
                "telemetry_prompt_save": False,
            },
        },
        "outputs": {
            "outdir": str(outdir / f"{robot_count}r" / pressure_key),
            "reference_system": "unc",
            "metrics": _metrics(),
            "scoreboard_metrics": [
                "native_value_weighted_exposure",
                "native_reactive_mean_response_time_s",
                "total_robot_distance_m",
                "native_reactive_completed_fraction",
                "native_predictive_completed_fraction",
                "native_reactive_load_factor_truth",
                "native_reactive_load_factor_observed",
                "native_reactive_load_factor_estimate",
                "native_urgent_reactive_override_total",
            ],
            "time_plot_metrics": _time_plot_metrics(),
        },
        "systems": systems,
        "metadata": {
            "experiment": "april_reservation_fraction_sweep",
            "mode": str(mode_label),
            "pressure_key": pressure_key,
            "swept_parameter": "reservation_fraction",
            "reservation_fractions": [float(v) for v in reservation_fractions],
            "mu_true": float(mu_true),
            "robot_count": int(robot_count),
            "reactive_load_factor_window_s": float(reactive_load_factor_window_s),
            "selection_policy_controls": {
                "res": "utility-ranked predictive task selection",
                "res_rand": "random predictive task selection at the same reservation fraction",
                "res_idle_feasible_confidence": (
                    "combined idle, feasibility, reactive-pressure, and confidence-gated next formulation"
                ),
            },
            "load_factor_formulas": {
                "truth": "truth_accepted_events/window_s * tau_service_s/Nrobots",
                "observable": "in_range_truth_detections/window_s * tau_service_s/Nrobots",
                "observed": "truth_detections_observed/window_s * tau_service_s/Nrobots",
                "estimate": "assigned_direct_detection_tasks/window_s * mean_realized_reactive_service_time/Nrobots",
            },
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _run_config(config_path: Path, *, max_workers: int) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "testbench.run_testbench",
            "--config",
            str(config_path),
            "--max-workers",
            str(int(max_workers)),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tune reserved-capacity fraction under high reactive load. "
            "Use the selected fraction later as a fixed policy in load-factor validation."
        )
    )
    parser.add_argument("--full", action="store_true", help="Use 5 seeds instead of the 2-seed pilot default.")
    parser.add_argument("--skip-run", action="store_true", help="Generate configs and print commands without running.")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--num-runs", type=int, default=None)
    parser.add_argument("--seed-start", type=int, default=123)
    parser.add_argument("--duration-s", type=float, default=86400.0)
    parser.add_argument("--sample-every-s", type=float, default=120.0)
    parser.add_argument("--warmup-s", type=float, default=21600.0)
    parser.add_argument("--load-window-s", type=float, default=120.0)
    parser.add_argument("--bird-detection-prob", type=float, default=1.0)
    parser.add_argument("--detect-range-m", type=float, default=30.0)
    parser.add_argument("--alpha-true", type=float, default=0.30)
    parser.add_argument("--mu-values", nargs="*", default=None, help="Space- or comma-separated mu_true values.")
    parser.add_argument(
        "--robot-counts",
        nargs="*",
        type=int,
        default=list(DEFAULT_ROBOT_COUNTS),
        help="High-load robot counts to run. Default: 3 2.",
    )
    parser.add_argument(
        "--reservation-fractions",
        nargs="*",
        default=None,
        help="Space- or comma-separated reservation fractions. Default: 0.00 0.05 ... 0.40.",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Directory for generated testbench configs.",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help="Root results directory for the sweep.",
    )
    args = parser.parse_args()

    mode_label = "full" if bool(args.full) else "pilot"
    num_runs = int(args.num_runs if args.num_runs is not None else (5 if args.full else 2))
    mu_values = _parse_float_list(args.mu_values, DEFAULT_MU_VALUES)
    reservation_fractions = _parse_float_list(args.reservation_fractions, DEFAULT_RESERVATION_FRACTIONS)
    requested_counts = [int(v) for v in args.robot_counts]
    if any(count <= 0 for count in requested_counts):
        raise SystemExit(f"Robot counts must be positive, got {requested_counts!r}")
    if any((float(v) < 0.0 or float(v) > 1.0) for v in reservation_fractions):
        raise SystemExit(f"Reservation fractions must be in [0, 1], got {reservation_fractions!r}")

    outdir = Path(args.outdir or f"results/testbench/april_reservation_fraction_sweep_{mode_label}")
    config_dir = Path(args.config_dir or f"testbench/generated/april_reservation_fraction_sweep_{mode_label}")

    print(
        f"[april-reservation-sweep] mode={mode_label} runs={num_runs} "
        f"counts={requested_counts} mu_values={mu_values} reservation_fractions={reservation_fractions}"
    )
    print(
        f"[april-reservation-sweep] load_window_s={float(args.load_window_s)} "
        f"bird_detection_prob={float(args.bird_detection_prob)} detect_range_m={float(args.detect_range_m)}"
    )

    for robot_count in requested_counts:
        for mu_true in mu_values:
            pressure_key = f"mu_{_value_token(mu_true)}"
            config_path = config_dir / f"april_reservation_fraction_{mode_label}_{robot_count}r_{pressure_key}.json"
            config = _build_config(
                robot_count=int(robot_count),
                mu_true=float(mu_true),
                mode_label=mode_label,
                num_runs=num_runs,
                seed_start=int(args.seed_start),
                duration_s=float(args.duration_s),
                sample_every_s=float(args.sample_every_s),
                warmup_s=float(args.warmup_s),
                bird_detection_prob=float(args.bird_detection_prob),
                detect_range_m=float(args.detect_range_m),
                alpha_true=float(args.alpha_true),
                reactive_load_factor_window_s=float(args.load_window_s),
                reservation_fractions=[float(v) for v in reservation_fractions],
                outdir=outdir,
            )
            _write_json(config_path, config)
            print(f"[april-reservation-sweep] {robot_count} robots {pressure_key} -> {config_path}")
            print(f"[april-reservation-sweep] output -> {config['outputs']['outdir']}")
            if not args.skip_run:
                _run_config(config_path, max_workers=int(args.max_workers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
