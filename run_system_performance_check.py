from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import run_current_vs_main_benchmark as bench


SYSTEM_ORDER: tuple[str, ...] = ("proposed", "prediction_only", "main", "reactive")
REFERENCE_LABEL = "main"


@dataclass(frozen=True)
class SystemSpec:
    label: str
    repo_key: str
    description: str
    params: dict[str, Any]


def _clean_optional_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def build_system_specs(
    *,
    planner_profile: str = "",
    proposed_preventive_policy: str = "",
    use_frozen_calibration: bool = False,
    calibration_ranking_path: str = "",
    calibration_manifest_path: str = "",
    calibration_config_id: str = "",
) -> tuple[SystemSpec, ...]:
    shared_current_params: dict[str, Any] = {}
    if planner_profile:
        shared_current_params["planner_profile"] = str(planner_profile)

    proposed_params = {
        **shared_current_params,
        "simulation_mode": "proposed",
        "enable_patrolling": True,
        "enable_intervention_feedback": True,
        "include_fallback_patrol": True,
        "enable_model_scored_deterring": True,
    }
    if proposed_preventive_policy:
        proposed_params["preventive_policy"] = str(proposed_preventive_policy)
    if bool(use_frozen_calibration):
        proposed_params["use_frozen_calibration"] = True
        if calibration_ranking_path:
            proposed_params["calibration_ranking_path"] = str(calibration_ranking_path)
        if calibration_manifest_path:
            proposed_params["calibration_manifest_path"] = str(calibration_manifest_path)
        if calibration_config_id:
            proposed_params["calibration_config_id"] = str(calibration_config_id)

    return (
        SystemSpec(
            label="proposed",
            repo_key="current",
            description=(
                "Current workspace with predictive patrol, intervention feedback, "
                "and model-scored preventive deterring enabled."
            ),
            params=proposed_params,
        ),
        SystemSpec(
            label="prediction_only",
            repo_key="current",
            description=(
                "Current workspace with predictive patrol enabled, but without "
                "intervention feedback or model-scored preventive deterring."
            ),
            params={
                **shared_current_params,
                "simulation_mode": "prediction_only",
                "enable_patrolling": True,
                "enable_intervention_feedback": False,
                "include_fallback_patrol": True,
                "enable_model_scored_deterring": False,
            },
        ),
        SystemSpec(
            label="main",
            repo_key="main",
            description="Sibling main worktree benchmarked with its native supported defaults.",
            params={},
        ),
        SystemSpec(
            label="reactive",
            repo_key="current",
            description=(
                "Current workspace in detections-only mode with no predictive patrol, "
                "no intervention feedback, and no model-scored preventive deterring."
            ),
            params={
                **shared_current_params,
                "simulation_mode": "reactive",
                "enable_patrolling": False,
                "enable_intervention_feedback": False,
                "include_fallback_patrol": False,
                "enable_model_scored_deterring": False,
            },
        ),
    )


def build_jobs(
    *,
    current_repo: Path,
    main_repo: Path,
    shared_params: dict[str, Any],
    system_specs: Sequence[SystemSpec],
    num_runs: int,
    seed_start: int,
    raw_dir: Path,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    repo_lookup = {
        "current": Path(current_repo).resolve(),
        "main": Path(main_repo).resolve(),
    }
    for offset in range(int(num_runs)):
        seed = int(seed_start) + offset
        for spec in system_specs:
            repo = repo_lookup[spec.repo_key]
            params = dict(shared_params)
            params.update(spec.params)
            jobs.append(
                {
                    "system_label": spec.label,
                    "repo": repo,
                    "seed": seed,
                    "params": params,
                    "out_json": raw_dir / spec.label / f"seed_{seed}.json",
                    "out_csv": raw_dir / spec.label / f"seed_{seed}.csv",
                }
            )
    return jobs


def _paired_advantage_stats(
    per_run_df: pd.DataFrame,
    *,
    metric_column: str,
    goal: str,
    system_label: str,
    reference_label: str,
) -> tuple[float, float, float, int]:
    paired = (
        per_run_df.loc[per_run_df["system"] == system_label, ["seed", metric_column]]
        .merge(
            per_run_df.loc[per_run_df["system"] == reference_label, ["seed", metric_column]],
            on="seed",
            suffixes=("_system", "_reference"),
            how="inner",
        )
    )
    if paired.empty:
        return float("nan"), float("nan"), float("nan"), 0
    system_col = f"{metric_column}_system"
    reference_col = f"{metric_column}_reference"
    den = paired[reference_col].replace(0.0, np.nan)
    if goal == "higher":
        advantage = 100.0 * (paired[system_col] - paired[reference_col]) / den
    else:
        advantage = 100.0 * (paired[reference_col] - paired[system_col]) / den
    return bench._ci95(advantage)


def summarize_systems(
    per_run_df: pd.DataFrame,
    *,
    system_order: Sequence[str] = SYSTEM_ORDER,
    reference_label: str = REFERENCE_LABEL,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for spec in bench.COMMON_METRICS:
        row: dict[str, Any] = {
            "metric": spec.column,
            "label": spec.label,
            "goal": spec.goal,
        }
        means: dict[str, float] = {}
        for label in system_order:
            stats = bench._ci95(per_run_df.loc[per_run_df["system"] == label, spec.column])
            row[f"{label}_mean"] = stats[0]
            row[f"{label}_ci_lo"] = stats[1]
            row[f"{label}_ci_hi"] = stats[2]
            row[f"{label}_n"] = stats[3]
            if np.isfinite(stats[0]):
                means[label] = float(stats[0])
            if label == reference_label:
                continue
            adv_stats = _paired_advantage_stats(
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

        if not means:
            winner = ""
        else:
            best_value = max(means.values()) if spec.goal == "higher" else min(means.values())
            tied = [
                label
                for label, value in means.items()
                if math.isclose(value, best_value, rel_tol=1e-12, abs_tol=1e-12)
            ]
            winner = tied[0] if len(tied) == 1 else "tie"
        row["winner"] = winner
        rows.append(row)
    return pd.DataFrame(rows)


def build_scoreboard(
    summary_df: pd.DataFrame,
    *,
    system_order: Sequence[str] = SYSTEM_ORDER,
) -> pd.DataFrame:
    win_counts = {label: 0 for label in system_order}
    decisive_metric_count = 0
    for winner in summary_df.get("winner", pd.Series(dtype=str)).fillna(""):
        if winner in win_counts:
            win_counts[winner] += 1
            decisive_metric_count += 1
    rows = []
    for label in system_order:
        wins = int(win_counts[label])
        rows.append(
            {
                "system": label,
                "metric_wins": wins,
                "win_share": (float(wins) / float(decisive_metric_count) if decisive_metric_count > 0 else float("nan")),
            }
        )
    return pd.DataFrame(rows).sort_values(["metric_wins", "system"], ascending=[False, True]).reset_index(drop=True)


def _plot_summary(summary_df: pd.DataFrame, out_png: Path, *, system_order: Sequence[str]) -> None:
    color_map = {
        "proposed": "#1f77b4",
        "prediction_only": "#2ca02c",
        "main": "#ff7f0e",
        "reactive": "#d62728",
    }
    short_labels = {
        "proposed": "proposed",
        "prediction_only": "prediction",
        "main": "main",
        "reactive": "reactive",
    }
    fig, axes = plt.subplots(2, 4, figsize=(22, 8))
    for ax, spec in zip(axes.flat, bench.COMMON_METRICS):
        row = summary_df.loc[summary_df["metric"] == spec.column].iloc[0]
        means = np.array([row.get(f"{label}_mean", float("nan")) for label in system_order], dtype=float)
        lows = np.array([row.get(f"{label}_ci_lo", float("nan")) for label in system_order], dtype=float)
        highs = np.array([row.get(f"{label}_ci_hi", float("nan")) for label in system_order], dtype=float)
        x = np.arange(len(system_order))
        ax.bar(
            x,
            means,
            color=[color_map.get(label, "#808080") for label in system_order],
            alpha=0.9,
        )
        for idx, mean in enumerate(means):
            if not (np.isfinite(mean) and np.isfinite(lows[idx]) and np.isfinite(highs[idx])):
                continue
            ax.errorbar(
                [x[idx]],
                [mean],
                yerr=np.array([[mean - lows[idx]], [highs[idx] - mean]], dtype=float),
                fmt="none",
                ecolor="black",
                capsize=4,
                linewidth=1.0,
            )
        ax.set_xticks(x)
        ax.set_xticklabels([short_labels.get(label, label) for label in system_order], rotation=15)
        ax.set_title(f"{spec.label}\n({spec.goal} better)")
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _build_summary_view(summary_df: pd.DataFrame, *, system_order: Sequence[str]) -> pd.DataFrame:
    view = summary_df[["label", "winner"]].copy()
    for label in system_order:
        view[label] = [
            bench._format_ci(mean, lo, hi)
            for mean, lo, hi in zip(
                summary_df[f"{label}_mean"],
                summary_df[f"{label}_ci_lo"],
                summary_df[f"{label}_ci_hi"],
            )
        ]
    ordered = view[["label", *system_order, "winner"]].copy()
    return ordered.rename(columns={"label": "Metric", "winner": "Winner"})


def _build_advantage_view(
    summary_df: pd.DataFrame,
    *,
    system_order: Sequence[str],
    reference_label: str,
) -> pd.DataFrame:
    cols = ["label"]
    rename_map = {"label": "Metric"}
    for label in system_order:
        if label == reference_label:
            continue
        out_col = f"{label}_advantage_vs_{reference_label}_pct"
        cols.extend(
            [
                f"{label}_advantage_vs_{reference_label}_pct_mean",
                f"{label}_advantage_vs_{reference_label}_pct_ci_lo",
                f"{label}_advantage_vs_{reference_label}_pct_ci_hi",
            ]
        )
        rename_map[out_col] = f"{label} vs {reference_label} advantage %"
    view = summary_df[cols].copy()
    out = pd.DataFrame({"Metric": view["label"]})
    for label in system_order:
        if label == reference_label:
            continue
        out[f"{label} vs {reference_label} advantage %"] = [
            bench._format_ci(mean, lo, hi)
            for mean, lo, hi in zip(
                summary_df[f"{label}_advantage_vs_{reference_label}_pct_mean"],
                summary_df[f"{label}_advantage_vs_{reference_label}_pct_ci_lo"],
                summary_df[f"{label}_advantage_vs_{reference_label}_pct_ci_hi"],
            )
        ]
    return out


def _write_report(
    out_path: Path,
    *,
    summary_df: pd.DataFrame,
    scoreboard_df: pd.DataFrame,
    current_repo: Path,
    main_repo: Path,
    shared_params: dict[str, Any],
    system_specs: Sequence[SystemSpec],
    reference_label: str,
) -> None:
    current_desc = bench._repo_descriptor(current_repo)
    main_desc = bench._repo_descriptor(main_repo)
    summary_view = _build_summary_view(summary_df, system_order=SYSTEM_ORDER)
    advantage_view = _build_advantage_view(summary_df, system_order=SYSTEM_ORDER, reference_label=reference_label)
    lines = [
        "# System Performance Check",
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
        "## Systems",
        "",
    ]
    for spec in system_specs:
        lines.append(f"- `{spec.label}`: {spec.description}")
    lines.extend(
        [
            "",
            "## Benchmark Parameters",
            "",
        ]
    )
    for key in sorted(shared_params.keys()):
        lines.append(f"- `{key}`: `{shared_params[key]}`")
    lines.extend(
        [
            "",
            "## Metric Wins",
            "",
            bench._dataframe_to_markdown(scoreboard_df),
            "",
            "## Summary",
            "",
            bench._dataframe_to_markdown(summary_view),
            "",
            f"Positive advantage means the listed system outperformed `{reference_label}` after accounting for metric direction.",
            "",
            "## Advantage Vs Main",
            "",
            bench._dataframe_to_markdown(advantage_view),
            "",
            "## Artifacts",
            "",
            "- `per_run_metrics.csv`: one row per system per seed",
            "- `summary_by_metric.csv`: aggregate means, CI95, and paired deltas vs main",
            "- `system_scoreboard.csv`: metric win counts by system",
            "- `per_run_timeseries.csv`: sampled trajectory metrics when available",
            "- `summary_compare.png`: grouped aggregate metric plot",
            "- `trajectory_compare.png`: mean trajectories over time when timeseries are available",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare proposed, prediction_only, reactive, and main under matched seeds."
    )
    parser.add_argument("--current-repo", default=str(Path.cwd()), help="Path to the current workspace.")
    parser.add_argument(
        "--main-repo",
        default=str(Path.cwd().parent / f"{Path.cwd().name}-main"),
        help="Path to the sibling main worktree.",
    )
    parser.add_argument(
        "--outdir",
        default="results/system_performance_check",
        help="Output directory for the performance-check artifacts.",
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
    parser.add_argument("--planner-profile", default="", help="Optional planner profile forwarded to the current workspace baselines.")
    parser.add_argument(
        "--proposed-preventive-policy",
        default="",
        help="Optional preventive policy override for the current proposed system.",
    )
    parser.add_argument(
        "--use-frozen-calibration",
        action="store_true",
        help="Enable frozen calibration for the current proposed system.",
    )
    parser.add_argument("--calibration-ranking-path", default="", help="Optional frozen-calibration ranking CSV path.")
    parser.add_argument("--calibration-manifest-path", default="", help="Optional frozen-calibration manifest path.")
    parser.add_argument("--calibration-config-id", default="", help="Optional frozen-calibration config id.")
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
    system_specs = build_system_specs(
        planner_profile=_clean_optional_text(args.planner_profile),
        proposed_preventive_policy=_clean_optional_text(args.proposed_preventive_policy),
        use_frozen_calibration=bool(args.use_frozen_calibration),
        calibration_ranking_path=_clean_optional_text(args.calibration_ranking_path),
        calibration_manifest_path=_clean_optional_text(args.calibration_manifest_path),
        calibration_config_id=_clean_optional_text(args.calibration_config_id),
    )
    jobs = build_jobs(
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
            print(f"[perf-check] running {job['system_label']} seed={job['seed']}")
            summaries.append(bench._run_worker_subprocess(**job))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(bench._run_worker_subprocess, **job): job for job in jobs}
            for future in as_completed(future_map):
                job = future_map[future]
                print(f"[perf-check] completed {job['system_label']} seed={job['seed']}")
                summaries.append(future.result())

    if not summaries:
        raise RuntimeError("Performance check produced no run summaries.")

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

    summary_df = summarize_systems(per_run_df, system_order=SYSTEM_ORDER, reference_label=REFERENCE_LABEL)
    summary_csv = outdir / "summary_by_metric.csv"
    summary_df.to_csv(summary_csv, index=False)

    scoreboard_df = build_scoreboard(summary_df, system_order=SYSTEM_ORDER)
    scoreboard_df.to_csv(outdir / "system_scoreboard.csv", index=False)

    _plot_summary(summary_df, outdir / "summary_compare.png", system_order=SYSTEM_ORDER)
    if not timeseries_df.empty:
        bench._plot_trajectories(timeseries_df, outdir / "trajectory_compare.png")

    manifest = {
        "current_repo": bench._repo_descriptor(current_repo),
        "main_repo": bench._repo_descriptor(main_repo),
        "benchmark_params": {
            "num_runs": int(args.num_runs),
            "seed_start": int(args.seed_start),
            "max_workers": int(args.max_workers),
            **shared_params,
            "planner_profile": _clean_optional_text(args.planner_profile),
            "proposed_preventive_policy": _clean_optional_text(args.proposed_preventive_policy),
            "use_frozen_calibration": bool(args.use_frozen_calibration),
            "calibration_ranking_path": _clean_optional_text(args.calibration_ranking_path),
            "calibration_manifest_path": _clean_optional_text(args.calibration_manifest_path),
            "calibration_config_id": _clean_optional_text(args.calibration_config_id),
        },
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
        summary_df=summary_df,
        scoreboard_df=scoreboard_df,
        current_repo=current_repo,
        main_repo=main_repo,
        shared_params=manifest["benchmark_params"],
        system_specs=system_specs,
        reference_label=REFERENCE_LABEL,
    )

    print("[perf-check] outputs written to:")
    print(f"- {outdir}")
    print(f"- {per_run_csv.name}")
    print(f"- {summary_csv.name}")
    print("- system_scoreboard.csv")
    print("- report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
