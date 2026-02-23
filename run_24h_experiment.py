from copy import deepcopy
from itertools import product

import pandas as pd

from DeterrentSystem import run_baseline_suite


def _mode_pack(scale_beta=1.0, scale_cost=1.0):
    # Tunable deterrence action model pack (formation/laser/biosonic).
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


def main():
    # --------------------- 24h base simulation params --------------------- #
    num_runs = 12
    seed_start = 1000
    base_params = {
        "T_end": 24 * 3600,  # 24h simulated time
        "dt": 5.0,  # bigger dt => faster local runtime
        "task_replan_period_s": 60.0,
        "NX": 80,
        "NY": 64,
        "W": 500.0,
        "H": 500.0,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "telemetry_dir": "telemetry_live",
        "telemetry_clear_on_start": True,
        "telemetry_prompt_save": False,
    }

    # ------------------- Scenario knobs (realism/stress) ------------------ #
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

    # ------------------- Tunable planner/action settings ------------------ #
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
                "tune_beta_scale": float(beta_scale),
                "tune_cost_scale": float(cost_scale),
            }
        )

    comparison_rows = []
    run_rows = []
    manifest_rows = []

    exp_id = 0
    for s in scenario_grid:
        for t in tune_grid:
            exp_id += 1
            exp_tag = f"E{exp_id:03d}"
            scenario_id = s["scenario_id"]
            tune_id = t["tune_id"]
            print(f"\n=== {exp_tag} | {scenario_id} | {tune_id} ===")

            run_kwargs = deepcopy(base_params)
            run_kwargs.update({k: v for k, v in s.items() if k != "scenario_id"})
            run_kwargs.update({k: v for k, v in t.items() if k not in {"tune_id", "tune_beta_scale", "tune_cost_scale"}})

            result = run_baseline_suite(
                num_runs=num_runs,
                seed_start=seed_start,
                report_each_run=True,
                csv_path=None,  # write one consolidated file at the end
                **run_kwargs,
            )

            # Baseline-level comparison rows.
            cmp_df = result["comparison"].copy()
            cmp_df.insert(0, "exp_id", exp_tag)
            cmp_df.insert(1, "scenario_id", scenario_id)
            cmp_df.insert(2, "tune_id", tune_id)
            cmp_df["tune_beta_scale"] = float(t["tune_beta_scale"])
            cmp_df["tune_cost_scale"] = float(t["tune_cost_scale"])
            comparison_rows.append(cmp_df)

            # Run-level rows.
            run_rows.extend(_flatten_run_metrics(result, seed_start, exp_tag, scenario_id, tune_id))

            # Experiment manifest row (what knobs were used).
            manifest_rows.append(
                {
                    "exp_id": exp_tag,
                    "scenario_id": scenario_id,
                    "tune_id": tune_id,
                    "num_runs": int(num_runs),
                    "seed_start": int(seed_start),
                    "params": str(run_kwargs),
                }
            )

    comparison_df = pd.concat(comparison_rows, ignore_index=True) if comparison_rows else pd.DataFrame()
    runs_df = pd.DataFrame(run_rows)
    manifest_df = pd.DataFrame(manifest_rows)

    comparison_csv = "baseline_comparison_24h_sweep.csv"
    per_run_csv = "baseline_runs_24h_sweep.csv"
    manifest_csv = "experiment_manifest_24h_sweep.csv"

    comparison_df.to_csv(comparison_csv, index=False)
    runs_df.to_csv(per_run_csv, index=False)
    manifest_df.to_csv(manifest_csv, index=False)

    # --------------------- Final thesis-ready combined summary --------------------- #
    # Build a single table that combines comparison stats with run-level counts
    # and adds easy-to-read ranking fields.
    summary_df = comparison_df.copy()
    if not runs_df.empty:
        run_counts = (
            runs_df.groupby(["exp_id", "scenario_id", "tune_id", "baseline"], as_index=False)
            .agg(
                n_runs=("run_idx", "nunique"),
                n_samples_response=("response_samples", "sum"),
                mean_completed_tasks=("completed_tasks_total", "mean"),
                mean_travel_ugv=("travel_distance_ugv", "mean"),
                mean_energy_ugv=("energy_ugv", "mean"),
            )
        )
        summary_df = summary_df.merge(
            run_counts,
            on=["exp_id", "scenario_id", "tune_id", "baseline"],
            how="left",
        )

    # Within each experiment setting, rank baselines by key objectives.
    summary_df["rank_exposure"] = (
        summary_df.groupby(["exp_id"])["value_weighted_exposure_mean"].rank(method="min", ascending=True).astype(int)
    )
    summary_df["rank_response"] = (
        summary_df.groupby(["exp_id"])["mean_response_time_s_mean"].rank(method="min", ascending=True).astype(int)
    )
    summary_df["rank_task_eff"] = (
        summary_df.groupby(["exp_id"])["tasks_per_unit_distance_mean"].rank(method="min", ascending=False).astype(int)
    )
    summary_df["rank_comm"] = (
        summary_df.groupby(["exp_id"])["boundary_message_count_mean"].rank(method="min", ascending=True).astype(int)
    )

    summary_df["composite_rank_score"] = (
        summary_df["rank_exposure"]
        + summary_df["rank_response"]
        + summary_df["rank_task_eff"]
        + summary_df["rank_comm"]
    )
    summary_df["rank_overall"] = (
        summary_df.groupby(["exp_id"])["composite_rank_score"].rank(method="min", ascending=True).astype(int)
    )

    final_summary_csv = "thesis_summary_24h_sweep.csv"
    summary_df = summary_df.sort_values(["exp_id", "rank_overall", "baseline"]).reset_index(drop=True)
    summary_df.to_csv(final_summary_csv, index=False)

    # Also emit a concise markdown report for thesis meetings.
    final_summary_md = "thesis_summary_24h_sweep.md"
    lines = []
    lines.append("# 24h Experiment Sweep Summary")
    lines.append("")
    lines.append(f"- Total settings: {len(scenario_grid) * len(tune_grid)}")
    lines.append(f"- Runs per setting (per baseline): {num_runs}")
    lines.append("")
    lines.append("## Best baseline per experiment setting")
    lines.append("")
    if not summary_df.empty:
        winners = summary_df[summary_df["rank_overall"] == 1].copy()
        winners = winners[
            [
                "exp_id",
                "scenario_id",
                "tune_id",
                "baseline",
                "value_weighted_exposure_mean",
                "mean_response_time_s_mean",
                "tasks_per_unit_distance_mean",
                "boundary_message_count_mean",
                "composite_rank_score",
            ]
        ]
        lines.append(winners.to_markdown(index=False))
    else:
        lines.append("_No data available._")
    lines.append("")
    lines.append("## Output files")
    lines.append("")
    lines.append(f"- `{comparison_csv}`: baseline-level mean/variance per setting")
    lines.append(f"- `{per_run_csv}`: per-run metrics")
    lines.append(f"- `{manifest_csv}`: full parameter manifest")
    lines.append(f"- `{final_summary_csv}`: combined thesis-ready summary table")

    with open(final_summary_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\nSaved files:")
    print(f"- {comparison_csv} (baseline summary for each scenario/tuning)")
    print(f"- {per_run_csv} (per-run metrics for each scenario/tuning)")
    print(f"- {manifest_csv} (full parameter manifest)")
    print(f"- {final_summary_csv} (combined thesis-ready summary table)")
    print(f"- {final_summary_md} (readable summary report)")
    print(f"\nTotal experiment settings: {len(scenario_grid) * len(tune_grid)}")


if __name__ == "__main__":
    main()
