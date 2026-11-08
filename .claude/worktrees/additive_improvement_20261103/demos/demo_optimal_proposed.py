from __future__ import annotations

import argparse
from copy import deepcopy
from itertools import product
from pathlib import Path

import pandas as pd

try:
    from demos._bootstrap import REPO_ROOT, resolve_repo_path
except ModuleNotFoundError:
    from _bootstrap import REPO_ROOT, resolve_repo_path

from calibration_config import DEFAULT_CALIBRATION_MANIFEST_PATH
import DeterrentSystem as ds


ARCHIVE_OUTPUTS_DIR = REPO_ROOT / "etc" / "archive_outputs"


def _mode_pack(scale_beta=1.0, scale_cost=1.0):
    return {
        "formation": {"beta": 0.30 * scale_beta, "omega": 800.0, "sigma": 18.0, "w_eta": 1.0 * scale_cost, "fixed_cost": 0.0},
        "laser": {"beta": 0.45 * scale_beta, "omega": 400.0, "sigma": 10.0, "w_eta": 1.5 * scale_cost, "fixed_cost": 0.0},
        "biosonic": {"beta": 0.25 * scale_beta, "omega": 600.0, "sigma": 20.0, "w_eta": 1.2 * scale_cost, "fixed_cost": 0.0},
    }


def _build_scenario_grid():
    return [
        {
            "scenario_id": "S1_low_pressure_short_range",
            "mu_true": 7.5e-7,
            "alpha_true": 0.20,
            "omega_true": 700.0,
            "sigma_true": 10.0,
            "beta_true": 0.30,
            "detect_range_m": 25.0,
            "row_gain": 1.2,
            "edge_gain": 0.5,
        },
        {
            "scenario_id": "S2_nominal",
            "mu_true": 1.0e-6,
            "alpha_true": 0.30,
            "omega_true": 600.0,
            "sigma_true": 12.0,
            "beta_true": 0.25,
            "detect_range_m": 30.0,
            "row_gain": 1.5,
            "edge_gain": 0.6,
        },
        {
            "scenario_id": "S3_high_pressure_long_range",
            "mu_true": 1.5e-6,
            "alpha_true": 0.45,
            "omega_true": 500.0,
            "sigma_true": 14.0,
            "beta_true": 0.22,
            "detect_range_m": 35.0,
            "row_gain": 1.8,
            "edge_gain": 0.8,
        },
    ]


def _build_tune_grid():
    tune_grid = []
    for i, (prio_det, beta_scale, cost_scale, replan_s) in enumerate(
        product([1.8, 2.2], [0.85, 1.00, 1.15], [0.9, 1.0], [45.0, 60.0]),
        start=1,
    ):
        tune_grid.append(
            {
                "tune_id": f"T{i:02d}",
                "prio_deterring": float(prio_det),
                "prio_patrolling": 0.25,
                "task_replan_period_s": float(replan_s),
                "deterring_modes": _mode_pack(scale_beta=float(beta_scale), scale_cost=float(cost_scale)),
            }
        )
    return tune_grid


def _select_best_from_summary(summary_path: Path):
    if not summary_path.exists():
        return None
    df = pd.read_csv(summary_path)
    if df.empty:
        return None
    d = df[df["baseline"] == "proposed"].copy()
    if d.empty:
        return None
    # Pick the strongest proposed row by overall rank, then exposure, then response.
    d = d.sort_values(
        ["rank_overall", "composite_rank_score", "value_weighted_exposure_mean", "mean_response_time_s_mean"],
        ascending=[True, True, True, True],
    )
    row = d.iloc[0]
    return {"scenario_id": row["scenario_id"], "tune_id": row["tune_id"]}


def _resolve_summary_csv(path_str: str) -> Path:
    requested = resolve_repo_path(path_str)
    if requested.exists():
        return requested

    archived = ARCHIVE_OUTPUTS_DIR / requested.name
    if archived.exists():
        return archived

    return requested


def main():
    parser = argparse.ArgumentParser(description="Visual demo for best proposed 24h configuration")
    parser.add_argument("--summary-csv", default="thesis_summary_24h_sweep.csv")
    parser.add_argument("--duration-s", type=float, default=1800.0, help="Demo simulation length in seconds")
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--seed", type=int, default=321)
    parser.add_argument("--save-path", default=None, help="Optional animation output path (e.g., demo.mp4)")
    args = parser.parse_args()

    scenarios = _build_scenario_grid()
    tunes = _build_tune_grid()
    scenario_by_id = {s["scenario_id"]: s for s in scenarios}
    tune_by_id = {t["tune_id"]: t for t in tunes}

    best = _select_best_from_summary(_resolve_summary_csv(args.summary_csv))
    if best is None:
        scenario_id = "S2_nominal"
        tune_id = "T08"
        print(f"[demo] summary not found/usable, using fallback: {scenario_id} + {tune_id}")
    else:
        scenario_id = str(best["scenario_id"])
        tune_id = str(best["tune_id"])
        print(f"[demo] using best proposed config from summary: {scenario_id} + {tune_id}")

    scenario = deepcopy(scenario_by_id[scenario_id])
    tune = deepcopy(tune_by_id[tune_id])

    # For demo mode, keep telemetry on only if needed elsewhere.
    # This script focuses on visualization.
    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    sim_kwargs = {
        "simulation_mode": "proposed",
        "use_frozen_calibration": True,
        "calibration_manifest_path": str(DEFAULT_CALIBRATION_MANIFEST_PATH),
        "T_end": float(args.duration_s),
        "dt": 1.0,
        "W": 500.0,
        "H": 500.0,
        "NX": 100,
        "NY": 80,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "seed": int(args.seed),
        "task_replan_period_s": tune["task_replan_period_s"],
        "prio_deterring": tune["prio_deterring"],
        "prio_patrolling": tune["prio_patrolling"],
        "deterring_modes": tune["deterring_modes"],
    }
    sim_kwargs.update({k: v for k, v in scenario.items() if k != "scenario_id"})

    print(
        f"[demo] running proposed visualization | scenario={scenario_id} tune={tune_id} "
        f"duration={args.duration_s}s fps={args.fps}"
    )
    ds.animate_demo_persistent(
        save_path=args.save_path,
        fps=int(args.fps),
        duration_s=float(args.duration_s),
        **sim_kwargs,
    )


if __name__ == "__main__":
    main()
