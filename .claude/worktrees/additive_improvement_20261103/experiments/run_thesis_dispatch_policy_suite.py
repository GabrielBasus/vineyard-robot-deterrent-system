from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import DeterrentSystem as ds


THESIS_DISPATCH_BASELINES: list[tuple[str, dict[str, Any]]] = [
    (
        "react",
        {
            "planner_profile": "thesis_dispatch_react",
            "dispatch_policy": "react",
            "reservation_fraction": 0.0,
            "predictive_selection_policy": "utility",
        },
    ),
    (
        "unc",
        {
            "planner_profile": "thesis_dispatch_unc",
            "dispatch_policy": "unc",
            "reservation_fraction": 0.0,
            "predictive_selection_policy": "utility",
        },
    ),
    (
        "res_0p10",
        {
            "planner_profile": "thesis_dispatch_res_0p10",
            "dispatch_policy": "res",
            "reservation_fraction": 0.10,
            "predictive_selection_policy": "utility",
        },
    ),
    (
        "res_0p25",
        {
            "planner_profile": "thesis_dispatch_res_0p25",
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "predictive_selection_policy": "utility",
        },
    ),
    (
        "res_0p40",
        {
            "planner_profile": "thesis_dispatch_res_0p40",
            "dispatch_policy": "res",
            "reservation_fraction": 0.40,
            "predictive_selection_policy": "utility",
        },
    ),
    (
        "res_rand_0p25",
        {
            "planner_profile": "thesis_dispatch_res_rand_0p25",
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
            "predictive_selection_policy": "random",
        },
    ),
]


def _shared_runtime_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "simulation_mode": "proposed",
        "T_end": float(args.t_end),
        "dt": float(args.dt),
        "fps": int(args.fps),
        "W": float(args.W),
        "H": float(args.H),
        "NX": int(args.NX),
        "NY": int(args.NY),
        "Nrobots": int(args.nrobots),
        "uav_fraction": float(args.uav_fraction),
        "task_replan_period_s": float(args.task_replan_period_s),
        "arrival_radius_m": float(args.arrival_radius_m),
        "hold_time_s": float(args.hold_time_s),
        "warmup_s": float(args.warmup_s),
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
        "report_metrics_end": False,
    }


def _comparison_rows(result: dict[str, Any], *, baseline_name: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "baseline": baseline_name,
        "num_runs": int(result.get("num_runs", 0)),
    }
    for metric_name, stats in dict(result.get("summary", {})).items():
        row[f"{metric_name}_mean"] = float(stats.get("mean", float("nan")))
        row[f"{metric_name}_var"] = float(stats.get("var", float("nan")))
    config_summary = dict(result.get("config_summary", {}))
    for key, value in config_summary.items():
        row[f"config_{key}"] = value
    return row


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    baselines = list(THESIS_DISPATCH_BASELINES)
    if bool(args.include_rho0):
        baselines.insert(
            2,
            (
                "res_0p00",
                {
                    "planner_profile": "thesis_dispatch_res_0p00",
                    "dispatch_policy": "res",
                    "reservation_fraction": 0.0,
                    "predictive_selection_policy": "utility",
                },
            ),
        )

    shared_kwargs = _shared_runtime_kwargs(args)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    per_baseline: dict[str, Any] = {}
    comparison_rows: list[dict[str, Any]] = []
    for baseline_name, params in baselines:
        run_kwargs = dict(shared_kwargs)
        run_kwargs.update(params)
        print(f"[thesis-dispatch] baseline={baseline_name}", flush=True)
        result = ds.run_metrics_experiments(
            num_runs=int(args.num_runs),
            seed_start=int(args.seed_start),
            report_each_run=bool(args.report_each_run),
            collect_time_metrics=True,
            time_metrics_period_s=float(args.sample_every_s),
            **run_kwargs,
        )
        per_baseline[baseline_name] = result
        comparison_rows.append(_comparison_rows(result, baseline_name=baseline_name))

    comparison_df = pd.DataFrame(comparison_rows)
    comparison_csv = outdir / "thesis_dispatch_policy_comparison.csv"
    comparison_df.to_csv(comparison_csv, index=False)

    manifest = {
        "baselines": {
            name: {
                "params": params,
                "summary": result.get("summary", {}),
                "config_summary": result.get("config_summary", {}),
            }
            for (name, params), result in zip(baselines, [per_baseline[name] for name, _ in baselines])
        },
        "shared_kwargs": shared_kwargs,
        "num_runs": int(args.num_runs),
        "seed_start": int(args.seed_start),
        "comparison_csv": str(comparison_csv),
    }
    manifest_path = outdir / "thesis_dispatch_policy_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[thesis-dispatch] wrote {comparison_csv}", flush=True)
    print(f"[thesis-dispatch] wrote {manifest_path}", flush=True)

    return {
        "baselines": per_baseline,
        "comparison": comparison_df,
        "manifest_path": str(manifest_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the April thesis dispatch-policy comparison suite.")
    parser.add_argument("--outdir", default="results/thesis_dispatch_policy_suite")
    parser.add_argument("--num-runs", type=int, default=5)
    parser.add_argument("--seed-start", type=int, default=123)
    parser.add_argument("--t-end", type=float, default=3600.0)
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument("--fps", type=int, default=1)
    parser.add_argument("--W", type=float, default=500.0)
    parser.add_argument("--H", type=float, default=500.0)
    parser.add_argument("--NX", type=int, default=120)
    parser.add_argument("--NY", type=int, default=96)
    parser.add_argument("--nrobots", type=int, default=6)
    parser.add_argument("--uav-fraction", type=float, default=0.0)
    parser.add_argument("--task-replan-period-s", type=float, default=45.0)
    parser.add_argument("--arrival-radius-m", type=float, default=3.0)
    parser.add_argument("--hold-time-s", type=float, default=20.0)
    parser.add_argument("--warmup-s", type=float, default=0.0)
    parser.add_argument("--sample-every-s", type=float, default=300.0)
    parser.add_argument("--include-rho0", action="store_true")
    parser.add_argument("--report-each-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    run_suite(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
