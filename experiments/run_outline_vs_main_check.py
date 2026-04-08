from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

import experiments.run_current_vs_main_benchmark as bench
import experiments.run_system_performance_check as perf
from simplification.stages import SIMPLIFICATION_STAGE_ORDER, get_stage


OUTLINE_LABEL = "outline_only"
MAIN_LABEL = "main"
SYSTEM_ORDER: tuple[str, ...] = (OUTLINE_LABEL, MAIN_LABEL)
REFERENCE_LABEL = MAIN_LABEL

NATIVE_METRICS: tuple[bench.MetricSpec, ...] = (
    bench.MetricSpec("native_value_weighted_exposure", "Native Value-Weighted Exposure", "lower"),
    bench.MetricSpec("native_mean_response_time_s", "Native Mean Response Time (s)", "lower"),
    bench.MetricSpec("native_birds_deterred_pct_last_hour", "Native Last-Hour Birds Deterred (%)", "higher"),
    bench.MetricSpec("native_birds_deterred_pct", "Native Birds Deterred (%)", "higher"),
    bench.MetricSpec("native_boundary_message_count", "Native Boundary Message Count", "lower"),
)


def _clean_optional_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _summarize_metric_specs(
    per_run_df: pd.DataFrame,
    *,
    metric_specs: Sequence[bench.MetricSpec],
    system_order: Sequence[str],
    reference_label: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for spec in metric_specs:
        row: dict[str, Any] = {
            "metric": spec.column,
            "label": spec.label,
            "goal": spec.goal,
        }
        means: dict[str, float] = {}
        for label in system_order:
            if spec.column not in per_run_df.columns:
                stats = (float("nan"), float("nan"), float("nan"), 0)
            else:
                stats = bench._ci95(per_run_df.loc[per_run_df["system"] == label, spec.column])
            row[f"{label}_mean"] = stats[0]
            row[f"{label}_ci_lo"] = stats[1]
            row[f"{label}_ci_hi"] = stats[2]
            row[f"{label}_n"] = stats[3]
            if np.isfinite(stats[0]):
                means[label] = float(stats[0])
            if label == reference_label:
                continue
            if spec.column not in per_run_df.columns:
                adv_stats = (float("nan"), float("nan"), float("nan"), 0)
            else:
                adv_stats = perf._paired_advantage_stats(
                    per_run_df,
                    metric_column=spec.column,
                    goal=spec.goal,
                    system_label=label,
                    reference_label=reference_label,
                )
            row[f"{label}_advantage_vs_{reference_label}_pct_mean"] = adv_stats[0]
            row[f"{label}_advantage_vs_{reference_label}_pct_ci_lo"] = adv_stats[1]
            row[f"{label}_advantage_vs_{reference_label}_pct_ci_hi"] = adv_stats[2]
            row[f"{label}_advantage_vs_{reference_label}_paired_seed_count"] = adv_stats[3]

        if len(means) < 2:
            winner = ""
        else:
            best_value = max(means.values()) if spec.goal == "higher" else min(means.values())
            tied = [
                label
                for label, value in means.items()
                if math.isclose(value, best_value, rel_tol=1.0e-12, abs_tol=1.0e-12)
            ]
            winner = tied[0] if len(tied) == 1 else "tie"
        row["winner"] = winner
        rows.append(row)
    return pd.DataFrame(rows)


def _build_system_specs(*, outline_stage_key: str) -> tuple[dict[str, Any], tuple[perf.SystemSpec, ...]]:
    stage = get_stage(outline_stage_key)
    if stage.module_name != "DeterrentSystem":
        raise ValueError(
            f"Outline-only benchmark currently supports DeterrentSystem stages only, got {stage.module_name!r} "
            f"for stage {outline_stage_key!r}."
        )

    outline_params = {
        "simulation_mode": "proposed",
        "enable_patrolling": True,
        "enable_intervention_feedback": True,
        "include_fallback_patrol": True,
        "enable_model_scored_deterring": True,
        **dict(stage.overrides),
    }

    system_specs = (
        perf.SystemSpec(
            label=OUTLINE_LABEL,
            repo_key="current",
            description=(
                "Current workspace constrained to the thesis-outline-only additions: "
                "main runtime plus the stripped-down core stage overrides, with later "
                "protective and throttling heuristics removed."
            ),
            params=outline_params,
        ),
        perf.SystemSpec(
            label=MAIN_LABEL,
            repo_key="main",
            description="Sibling main worktree benchmarked with its native supported defaults.",
            params={},
        ),
    )
    return stage.public_dict(), system_specs


def _write_report(
    out_path: Path,
    *,
    common_summary_df: pd.DataFrame,
    native_summary_df: pd.DataFrame,
    scoreboard_df: pd.DataFrame,
    current_repo: Path,
    main_repo: Path,
    shared_params: dict[str, Any],
    system_specs: Sequence[perf.SystemSpec],
    outline_stage_public: dict[str, Any],
) -> None:
    current_desc = bench._repo_descriptor(current_repo)
    main_desc = bench._repo_descriptor(main_repo)
    common_view = perf._build_summary_view(common_summary_df, system_order=SYSTEM_ORDER)
    common_advantage = perf._build_advantage_view(
        common_summary_df,
        system_order=SYSTEM_ORDER,
        reference_label=REFERENCE_LABEL,
    )
    native_view = perf._build_summary_view(native_summary_df, system_order=SYSTEM_ORDER) if not native_summary_df.empty else pd.DataFrame()

    lines = [
        "# Outline Vs Main Check",
        "",
        "This benchmark compares the sibling `main` worktree against a current-workspace runtime that keeps only the thesis-outline additions.",
        "",
        "## Repositories",
        "",
        f"- current: `{current_desc['path']}`",
        f"- current branch: `{current_desc['branch'] or 'unknown'}`",
        f"- current commit: `{current_desc['commit'] or 'unknown'}`",
        f"- current dirty: `{current_desc['dirty']}`",
        f"- main: `{main_desc['path']}`",
        f"- main branch: `{main_desc['branch'] or 'unknown'}`",
        f"- main commit: `{main_desc['commit'] or 'unknown'}`",
        f"- main dirty: `{main_desc['dirty']}`",
        "",
        "## Outline Stage",
        "",
        f"- key: `{outline_stage_public.get('key', '')}`",
        f"- title: `{outline_stage_public.get('title', '')}`",
        f"- module: `{outline_stage_public.get('module_name', '')}`",
        f"- description: {outline_stage_public.get('description', '')}",
        f"- added_back: `{', '.join(outline_stage_public.get('added_back', []))}`",
        "",
        "## Systems",
        "",
    ]
    for spec in system_specs:
        lines.append(f"- `{spec.label}`: {spec.description}")
    lines.extend(["", "## Benchmark Parameters", ""])
    for key in sorted(shared_params.keys()):
        lines.append(f"- `{key}`: `{shared_params[key]}`")
    lines.extend(
        [
            "",
            "## Common Metric Wins",
            "",
            bench._dataframe_to_markdown(scoreboard_df),
            "",
            "## Common Summary",
            "",
            bench._dataframe_to_markdown(common_view),
            "",
            f"Positive advantage means `{OUTLINE_LABEL}` outperformed `{REFERENCE_LABEL}` after accounting for metric direction.",
            "",
            "## Common Advantage Vs Main",
            "",
            bench._dataframe_to_markdown(common_advantage),
        ]
    )
    if not native_view.empty:
        lines.extend(
            [
                "",
                "## Native Metric Summary",
                "",
                "Rows marked `n/a` for `main` indicate that the sibling main worktree does not emit that metric in this harness.",
                "",
                bench._dataframe_to_markdown(native_view),
            ]
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `per_run_metrics.csv`: one row per system per seed",
            "- `summary_common.csv`: aggregate common metrics used for fair cross-worktree comparison",
            "- `summary_native.csv`: native current-workspace metrics when emitted by the runner",
            "- `system_scoreboard.csv`: metric win counts on the common comparison set",
            "- `per_run_timeseries.csv`: sampled trajectory metrics when available",
            "- `summary_compare.png`: grouped common-metric plot",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare main against a current-workspace runtime that keeps only thesis-outline additions."
    )
    parser.add_argument("--current-repo", default=str(Path.cwd()), help="Path to the current workspace.")
    parser.add_argument(
        "--main-repo",
        default=str(Path.cwd().parent / f"{Path.cwd().name}-main"),
        help="Path to the sibling main worktree.",
    )
    parser.add_argument(
        "--outline-stage",
        default="s1_risk_open_core",
        choices=SIMPLIFICATION_STAGE_ORDER,
        help="Simplification stage used to define the outline-only current runtime.",
    )
    parser.add_argument(
        "--outdir",
        default="results/outline_vs_main_check",
        help="Output directory for the comparison artifacts.",
    )
    parser.add_argument("--num-runs", type=int, default=5, help="Seeds to run per system.")
    parser.add_argument("--seed-start", type=int, default=1000, help="First seed value.")
    parser.add_argument("--duration-s", type=float, default=3600.0, help="Simulation horizon in seconds.")
    parser.add_argument("--dt", type=float, default=5.0, help="Simulation step size.")
    parser.add_argument("--fps", type=int, default=1, help="Frame cadence parameter passed to the simulation.")
    parser.add_argument("--W", type=float, default=500.0, help="Field width.")
    parser.add_argument("--H", type=float, default=500.0, help="Field height.")
    parser.add_argument("--NX", type=int, default=80, help="Grid width.")
    parser.add_argument("--NY", type=int, default=64, help="Grid height.")
    parser.add_argument("--Nrobots", type=int, default=6, help="Robot count when supported.")
    parser.add_argument("--uav-fraction", type=float, default=0.0, help="UAV fraction when supported.")
    parser.add_argument("--task-replan-period-s", type=float, default=45.0, help="Replan cadence.")
    parser.add_argument("--arrival-radius-m", type=float, default=3.0, help="Task arrival radius.")
    parser.add_argument("--hold-time-s", type=float, default=20.0, help="Deterring hold time.")
    parser.add_argument("--sample-every-s", type=float, default=60.0, help="Timeseries sample cadence.")
    parser.add_argument("--max-workers", type=int, default=1, help="Concurrent worker processes.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    current_repo = Path(args.current_repo).resolve()
    main_repo = Path(args.main_repo).resolve()
    if not current_repo.exists():
        raise FileNotFoundError(f"Current repo does not exist: {current_repo}")
    if not main_repo.exists():
        raise FileNotFoundError(f"Main repo does not exist: {main_repo}")

    outdir = Path(args.outdir)
    raw_dir = outdir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    shared_params = {
        "W": float(args.W),
        "H": float(args.H),
        "T_end": float(args.duration_s),
        "dt": float(args.dt),
        "fps": int(args.fps),
        "NX": int(args.NX),
        "NY": int(args.NY),
        "Nrobots": int(args.Nrobots),
        "uav_fraction": float(args.uav_fraction),
        "task_replan_period_s": float(args.task_replan_period_s),
        "arrival_radius_m": float(args.arrival_radius_m),
        "hold_time_s": float(args.hold_time_s),
        "sample_every_s": float(args.sample_every_s),
    }

    outline_stage_public, system_specs = _build_system_specs(outline_stage_key=str(args.outline_stage))
    jobs = perf.build_jobs(
        current_repo=current_repo,
        main_repo=main_repo,
        shared_params=shared_params,
        system_specs=system_specs,
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        raw_dir=raw_dir,
    )

    summaries: list[dict[str, Any]] = []
    max_workers = max(1, int(args.max_workers))
    if max_workers == 1:
        for job in jobs:
            print(f"[outline-vs-main] running {job['system_label']} seed={job['seed']}")
            summaries.append(bench._run_worker_subprocess(**job))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(bench._run_worker_subprocess, **job): job for job in jobs}
            for future in as_completed(future_map):
                job = future_map[future]
                print(f"[outline-vs-main] completed {job['system_label']} seed={job['seed']}")
                summaries.append(future.result())

    if not summaries:
        raise RuntimeError("Outline-vs-main benchmark produced no run summaries.")

    order_map = {label: idx for idx, label in enumerate(SYSTEM_ORDER)}
    per_run_df = pd.DataFrame(summaries).sort_values(
        by=["system", "seed"],
        key=lambda col: col.map(order_map) if col.name == "system" else col,
    ).reset_index(drop=True)
    per_run_csv = outdir / "per_run_metrics.csv"
    per_run_df.to_csv(per_run_csv, index=False)

    timeseries_parts = []
    for job in jobs:
        csv_path = Path(job["out_csv"])
        if csv_path.exists():
            timeseries_parts.append(pd.read_csv(csv_path))
    timeseries_df = pd.concat(timeseries_parts, ignore_index=True) if timeseries_parts else pd.DataFrame()
    if not timeseries_df.empty:
        timeseries_df.to_csv(outdir / "per_run_timeseries.csv", index=False)

    common_summary_df = perf.summarize_systems(
        per_run_df,
        system_order=SYSTEM_ORDER,
        reference_label=REFERENCE_LABEL,
    )
    common_summary_df.to_csv(outdir / "summary_common.csv", index=False)

    native_summary_df = _summarize_metric_specs(
        per_run_df,
        metric_specs=NATIVE_METRICS,
        system_order=SYSTEM_ORDER,
        reference_label=REFERENCE_LABEL,
    )
    native_summary_df.to_csv(outdir / "summary_native.csv", index=False)

    scoreboard_df = perf.build_scoreboard(common_summary_df, system_order=SYSTEM_ORDER)
    scoreboard_df.to_csv(outdir / "system_scoreboard.csv", index=False)

    perf._plot_summary(common_summary_df, outdir / "summary_compare.png", system_order=SYSTEM_ORDER)

    manifest = {
        "current_repo": bench._repo_descriptor(current_repo),
        "main_repo": bench._repo_descriptor(main_repo),
        "benchmark_params": {
            "num_runs": int(args.num_runs),
            "seed_start": int(args.seed_start),
            "max_workers": int(args.max_workers),
            **shared_params,
            "outline_stage": str(args.outline_stage),
        },
        "outline_stage": outline_stage_public,
        "systems": [
            {
                "label": spec.label,
                "repo_key": spec.repo_key,
                "description": spec.description,
                "params": dict(spec.params),
            }
            for spec in system_specs
        ],
    }
    (outdir / "benchmark_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_report(
        outdir / "report.md",
        common_summary_df=common_summary_df,
        native_summary_df=native_summary_df,
        scoreboard_df=scoreboard_df,
        current_repo=current_repo,
        main_repo=main_repo,
        shared_params=manifest["benchmark_params"],
        system_specs=system_specs,
        outline_stage_public=outline_stage_public,
    )

    print("[outline-vs-main] outputs written to:")
    print(f"- {outdir}")
    print("- per_run_metrics.csv")
    print("- summary_common.csv")
    print("- summary_native.csv")
    print("- system_scoreboard.csv")
    print("- report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
