from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from itertools import product
import argparse
import os
import time

import pandas as pd

from DeterrentSystem import run_baseline_suite


def _mode_pack(scale_beta=1.0, scale_cost=1.0):
    return {
        "formation": {"beta": 0.30 * scale_beta, "omega": 800.0, "sigma": 18.0, "w_eta": 1.0 * scale_cost, "fixed_cost": 0.0},
        "laser": {"beta": 0.45 * scale_beta, "omega": 400.0, "sigma": 10.0, "w_eta": 1.5 * scale_cost, "fixed_cost": 0.0},
        "biosonic": {"beta": 0.25 * scale_beta, "omega": 600.0, "sigma": 20.0, "w_eta": 1.2 * scale_cost, "fixed_cost": 0.0},
    }


def _flatten_run_metrics(result, seed_start, exp_id, scenario_id, tune_id):
    rows = []
    baselines = result.get("baselines", {})
    for baseline_name, baseline_result in baselines.items():
        run_list = baseline_result.get("runs", [])
        for run_idx, m in enumerate(run_list):
            seed = seed_start + run_idx
            travel_by_type = m.get("travel_distance_by_type", {})
            energy_by_type = m.get("energy_by_type", {})
            completed_by_type = m.get("completed_tasks_by_type", {})
            rows.append(
                {
                    "exp_id": exp_id,
                    "scenario_id": scenario_id,
                    "tune_id": tune_id,
                    "baseline": baseline_name,
                    "run_idx": int(run_idx),
                    "seed": int(seed),
                    "value_weighted_exposure": float(m.get("value_weighted_exposure", float("nan"))),
                    "mean_response_time_s": float(m.get("mean_response_time_s", float("nan"))),
                    "response_samples": int(m.get("response_samples", 0)),
                    "completed_tasks_total": int(m.get("completed_tasks_total", 0)),
                    "completed_tasks_deterring": int(completed_by_type.get("deterring", 0)),
                    "completed_tasks_patrolling": int(completed_by_type.get("patrolling", 0)),
                    "tasks_per_unit_distance": float(m.get("tasks_per_unit_distance", float("nan"))),
                    "exposure_per_completed_task": float(m.get("exposure_per_completed_task", float("nan"))),
                    "score_per_completed_task": float(m.get("score_per_completed_task", float("nan"))),
                    "travel_distance_ugv": float(travel_by_type.get("UGV", float("nan"))),
                    "travel_distance_uav": float(travel_by_type.get("UAV", float("nan"))),
                    "energy_ugv": float(energy_by_type.get("UGV", float("nan"))),
                    "energy_uav": float(energy_by_type.get("UAV", float("nan"))),
                    "boundary_message_count": int(m.get("boundary_message_count", 0)),
                    "boundary_bytes_sent": int(m.get("boundary_bytes_sent", 0)),
                }
            )
    return rows


def _run_one_experiment(job):
    exp_tag = job["exp_tag"]
    scenario_id = job["scenario_id"]
    tune_id = job["tune_id"]
    num_runs = int(job["num_runs"])
    seed_start = int(job["seed_start"])
    run_kwargs = deepcopy(job["run_kwargs"])
    started = time.time()

    result = run_baseline_suite(
        num_runs=num_runs,
        seed_start=seed_start,
        report_each_run=False,
        csv_path=None,
        **run_kwargs,
    )

    cmp_df = result["comparison"].copy()
    cmp_df.insert(0, "exp_id", exp_tag)
    cmp_df.insert(1, "scenario_id", scenario_id)
    cmp_df.insert(2, "tune_id", tune_id)
    cmp_df["tune_beta_scale"] = float(job["tune_beta_scale"])
    cmp_df["tune_cost_scale"] = float(job["tune_cost_scale"])

    run_rows = _flatten_run_metrics(result, seed_start, exp_tag, scenario_id, tune_id)
    manifest_row = {
        "exp_id": exp_tag,
        "scenario_id": scenario_id,
        "tune_id": tune_id,
        "num_runs": num_runs,
        "seed_start": seed_start,
        "params": str(run_kwargs),
        "wall_s": float(time.time() - started),
    }

    return {
        "exp_tag": exp_tag,
        "comparison_records": cmp_df.to_dict(orient="records"),
        "run_rows": run_rows,
        "manifest_row": manifest_row,
    }


def _build_grids(profile: str):
    scenario_grid = [
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

    if profile == "fast":
        prio_list = [1.8, 2.2]
        beta_list = [0.90, 1.10]
        cost_list = [1.0]
        replan_list = [60.0]
        scenario_grid = scenario_grid[:2]
    else:
        prio_list = [1.8, 2.2]
        beta_list = [0.85, 1.00, 1.15]
        cost_list = [0.9, 1.0]
        replan_list = [45.0, 60.0]

    tune_grid = []
    for i, (prio_det, beta_scale, cost_scale, replan_s) in enumerate(
        product(prio_list, beta_list, cost_list, replan_list),
        start=1,
    ):
        tune_grid.append(
            {
                "tune_id": f"T{i:02d}",
                "prio_deterring": float(prio_det),
                "prio_patrolling": 0.25,
                "task_replan_period_s": float(replan_s),
                "deterring_modes": _mode_pack(scale_beta=float(beta_scale), scale_cost=float(cost_scale)),
                "tune_beta_scale": float(beta_scale),
                "tune_cost_scale": float(cost_scale),
            }
        )
    return scenario_grid, tune_grid


def main():
    parser = argparse.ArgumentParser(description="Parallel 24h experiment sweep")
    parser.add_argument("--profile", choices=["fast", "final"], default="fast")
    parser.add_argument("--max-workers", type=int, default=0, help="0 => auto")
    parser.add_argument("--num-runs", type=int, default=0, help="0 => profile default")
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--dt", type=float, default=0.0, help="0 => profile default")
    parser.add_argument("--nx", type=int, default=0, help="0 => profile default")
    parser.add_argument("--ny", type=int, default=0, help="0 => profile default")
    parser.add_argument("--limit-settings", type=int, default=0, help="0 => all")
    args = parser.parse_args()

    seed_start = int(args.seed_start)
    if args.max_workers > 0:
        max_workers = int(args.max_workers)
    else:
        auto_cap = 12 if args.profile == "fast" else 8
        max_workers = max(1, min((os.cpu_count() or 2) - 1, auto_cap))

    profile_defaults = {
        "fast": {"num_runs": 5, "dt": 10.0, "NX": 64, "NY": 48},
        "final": {"num_runs": 12, "dt": 5.0, "NX": 80, "NY": 64},
    }
    dflt = profile_defaults[args.profile]
    num_runs = int(args.num_runs if args.num_runs > 0 else dflt["num_runs"])
    dt = float(args.dt if args.dt > 0 else dflt["dt"])
    nx = int(args.nx if args.nx > 0 else dflt["NX"])
    ny = int(args.ny if args.ny > 0 else dflt["NY"])

    base_params = {
        "T_end": 24 * 3600,
        "dt": dt,
        "task_replan_period_s": 60.0,
        "NX": nx,
        "NY": ny,
        "W": 500.0,
        "H": 500.0,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        # unique telemetry folder per worker prevents file contention
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }
    scenario_grid, tune_grid = _build_grids(args.profile)

    jobs = []
    exp_id = 0
    for s in scenario_grid:
        for t in tune_grid:
            exp_id += 1
            exp_tag = f"E{exp_id:03d}"
            run_kwargs = deepcopy(base_params)
            run_kwargs.update({k: v for k, v in s.items() if k != "scenario_id"})
            run_kwargs.update({k: v for k, v in t.items() if k not in {"tune_id", "tune_beta_scale", "tune_cost_scale"}})
            run_kwargs["telemetry_dir"] = f"telemetry_live_{exp_tag}"
            jobs.append(
                {
                    "exp_tag": exp_tag,
                    "scenario_id": s["scenario_id"],
                    "tune_id": t["tune_id"],
                    "num_runs": num_runs,
                    "seed_start": seed_start,
                    "run_kwargs": run_kwargs,
                    "tune_beta_scale": t["tune_beta_scale"],
                    "tune_cost_scale": t["tune_cost_scale"],
                }
            )

    if args.limit_settings > 0:
        jobs = jobs[: int(args.limit_settings)]

    print(
        f"Launching {len(jobs)} settings | profile={args.profile} "
        f"| workers={max_workers} | runs={num_runs} | dt={dt} | grid={nx}x{ny}"
    )
    started = time.time()

    comparison_rows = []
    run_rows = []
    manifest_rows = []
    done = 0
    total = len(jobs)

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_one_experiment, job) for job in jobs]
        for fut in as_completed(futures):
            out = fut.result()
            done += 1
            comparison_rows.extend(out["comparison_records"])
            run_rows.extend(out["run_rows"])
            manifest_rows.append(out["manifest_row"])
            pct = 100.0 * done / max(total, 1)
            print(f"[parallel] {done}/{total} ({pct:.1f}%) complete: {out['exp_tag']}")

    comparison_df = pd.DataFrame(comparison_rows)
    runs_df = pd.DataFrame(run_rows)
    manifest_df = pd.DataFrame(manifest_rows)

    suffix = f"_{args.profile}"
    comparison_csv = f"baseline_comparison_24h_sweep_parallel{suffix}.csv"
    per_run_csv = f"baseline_runs_24h_sweep_parallel{suffix}.csv"
    manifest_csv = f"experiment_manifest_24h_sweep_parallel{suffix}.csv"
    comparison_df.to_csv(comparison_csv, index=False)
    runs_df.to_csv(per_run_csv, index=False)
    manifest_df.to_csv(manifest_csv, index=False)

    print("\nSaved files:")
    print(f"- {comparison_csv}")
    print(f"- {per_run_csv}")
    print(f"- {manifest_csv}")
    print(f"Wall time: {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
