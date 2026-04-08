from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import experiments.run_current_vs_main_benchmark as bench
from exploration.variants import EXPLORATION_VARIANTS
from simplification.stages import get_stage


CURRENT_REPO_ALIAS = "current"
MAIN_REPO_ALIAS = "main"
DEFAULT_OUTPUT_METRICS: tuple[str, ...] = (
    "native_value_weighted_exposure",
    "native_mean_response_time_s",
    "native_birds_deterred_pct_last_hour",
    "completed_tasks_total",
    "completed_deterring_total",
    "tasks_per_km_travel",
    "native_boundary_message_count",
)
DEFAULT_SCOREBOARD_METRICS: tuple[str, ...] = (
    "native_value_weighted_exposure",
    "native_mean_response_time_s",
    "native_birds_deterred_pct_last_hour",
    "completed_tasks_total",
    "native_boundary_message_count",
)
DEFAULT_TIME_PLOT_METRICS: tuple[str, ...] = (
    "native_value_weighted_exposure",
    "native_mean_response_time_s",
    "native_birds_deterred_pct_last_hour",
    "completed_deterring_total",
    "completed_tasks_total",
    "active_tasks",
)
PROPOSED_MODE_DEFAULTS: dict[str, Any] = {
    "simulation_mode": "proposed",
    "enable_patrolling": True,
    "enable_intervention_feedback": True,
    "include_fallback_patrol": True,
    "enable_model_scored_deterring": True,
}
PREDICTION_ONLY_MODE_DEFAULTS: dict[str, Any] = {
    "simulation_mode": "prediction_only",
    "enable_patrolling": True,
    "enable_intervention_feedback": False,
    "include_fallback_patrol": True,
    "enable_model_scored_deterring": False,
}
REACTIVE_MODE_DEFAULTS: dict[str, Any] = {
    "simulation_mode": "reactive",
    "enable_patrolling": False,
    "enable_intervention_feedback": False,
    "include_fallback_patrol": False,
    "enable_model_scored_deterring": False,
}
STAGE_PROPOSED_DEFAULTS: dict[str, Any] = dict(PROPOSED_MODE_DEFAULTS)
NATIVE_METRICS: tuple[bench.MetricSpec, ...] = (
    bench.MetricSpec("native_value_weighted_exposure", "Value-Weighted Exposure", "lower"),
    bench.MetricSpec("native_mean_response_time_s", "Mean Response Time (s)", "lower"),
    bench.MetricSpec("native_truth_suppression_rate_last_hour", "Last-Hour Truth Suppression Rate", "higher"),
    bench.MetricSpec("native_birds_deterred_pct_last_hour", "Last-Hour Birds Deterred (%)", "higher"),
    bench.MetricSpec("native_truth_suppression_rate", "Truth Suppression Rate", "higher"),
    bench.MetricSpec("native_birds_deterred_pct", "Birds Deterred (%)", "higher"),
    bench.MetricSpec("native_boundary_message_count", "Boundary Message Count", "lower"),
    bench.MetricSpec("native_forecast_recall_at_k", "Forecast Recall@K", "higher"),
    bench.MetricSpec("native_forecast_precision_at_k", "Forecast Precision@K", "higher"),
)
METRIC_LIBRARY: dict[str, bench.MetricSpec] = {
    spec.column: spec for spec in (*bench.COMMON_METRICS, *NATIVE_METRICS)
}
TIME_METRIC_LIBRARY: dict[str, bench.MetricSpec] = {
    **METRIC_LIBRARY,
    "active_tasks": bench.MetricSpec("active_tasks", "Active Tasks", "lower"),
    "active_deterring": bench.MetricSpec("active_deterring", "Active Deterring", "higher"),
    "active_patrolling": bench.MetricSpec("active_patrolling", "Active Patrolling", "higher"),
    "completed_tasks_total": bench.MetricSpec("completed_tasks_total", "Completed Tasks", "higher"),
    "completed_deterring_total": bench.MetricSpec("completed_deterring_total", "Completed Deterring", "higher"),
    "completed_patrolling_total": bench.MetricSpec("completed_patrolling_total", "Completed Patrolling", "higher"),
    "cumulative_distance_m": bench.MetricSpec("cumulative_distance_m", "Cumulative Distance (m)", "lower"),
    "tasks_per_km_travel": bench.MetricSpec("tasks_per_km_travel", "Tasks / km Travel", "higher"),
}
EXAMPLE_CONFIG: dict[str, Any] = {
    "scenario": {
        "num_runs": 3,
        "seed_start": 123,
        "duration_s": 3600.0,
        "dt": 1.0,
        "fps": 1,
        "W": 500.0,
        "H": 500.0,
        "NX": 120,
        "NY": 96,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "task_replan_period_s": 45.0,
        "arrival_radius_m": 3.0,
        "hold_time_s": 20.0,
        "sample_every_s": 300.0,
    },
    "outputs": {
        "outdir": "results/testbench/example",
        "reference_system": "outline_core",
        "metrics": list(DEFAULT_OUTPUT_METRICS),
        "scoreboard_metrics": list(DEFAULT_SCOREBOARD_METRICS),
        "time_plot_metrics": list(DEFAULT_TIME_PLOT_METRICS),
    },
    "systems": [
        {
            "key": "outline_core",
            "type": "simplification_stage",
            "stage": "s1_risk_open_core",
            "title": "Outline Core",
        },
        {
            "key": "exploration_local_queue",
            "type": "exploration_variant",
            "variant": "row_local_priority_queue",
            "title": "Exploration Local Queue",
        },
        {
            "key": "current_prediction",
            "type": "current_mode",
            "mode": "prediction_only",
            "title": "Current Prediction Only",
        },
        {
            "key": "current_reactive",
            "type": "current_mode",
            "mode": "reactive",
            "title": "Current Reactive",
        },
    ],
}


@dataclass(frozen=True)
class RunnableTarget:
    key: str
    title: str
    description: str
    kind: str
    repo: str
    module_name: str
    params: dict[str, Any]
    source: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "repo": self.repo,
            "module_name": self.module_name,
            "params": dict(self.params),
            "source": dict(self.source),
        }


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _deepcopy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload))


def _mode_defaults(mode: str) -> dict[str, Any]:
    mode_key = str(mode).strip().lower()
    if mode_key == "proposed":
        return dict(PROPOSED_MODE_DEFAULTS)
    if mode_key == "prediction_only":
        return dict(PREDICTION_ONLY_MODE_DEFAULTS)
    if mode_key == "reactive":
        return dict(REACTIVE_MODE_DEFAULTS)
    raise ValueError(f"Unknown current_mode {mode!r}. Expected proposed, prediction_only, or reactive.")


def _resolve_repo_path(
    repo_value: Any,
    *,
    current_repo: Path,
    main_repo: Path,
    config_dir: Path,
) -> Path:
    token = _safe_text(repo_value).strip()
    if token in ("", CURRENT_REPO_ALIAS):
        return current_repo.resolve()
    if token == MAIN_REPO_ALIAS:
        return main_repo.resolve()
    path = Path(token)
    if not path.is_absolute():
        path = (config_dir / path).resolve()
    return path


def _module_path(repo: Path, module_name: str) -> Path:
    return (repo / (str(module_name).replace(".", os.sep) + ".py")).resolve()


def _normalize_scenario(config: dict[str, Any]) -> dict[str, Any]:
    scenario = {
        "num_runs": 1,
        "seed_start": 123,
        "duration_s": 3600.0,
        "dt": 1.0,
        "fps": 1,
        "W": 500.0,
        "H": 500.0,
        "NX": 120,
        "NY": 96,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "task_replan_period_s": 45.0,
        "arrival_radius_m": 3.0,
        "hold_time_s": 20.0,
        "sample_every_s": 300.0,
        "warmup_s": 0.0,
    }
    raw = dict(config.get("scenario") or {})
    scenario.update(raw)
    return scenario


def _shared_runner_params(scenario: dict[str, Any]) -> dict[str, Any]:
    params = {
        "W": float(scenario["W"]),
        "H": float(scenario["H"]),
        "T_end": float(scenario["duration_s"]),
        "dt": float(scenario["dt"]),
        "fps": int(scenario["fps"]),
        "NX": int(scenario["NX"]),
        "NY": int(scenario["NY"]),
        "Nrobots": int(scenario["Nrobots"]),
        "uav_fraction": float(scenario["uav_fraction"]),
        "task_replan_period_s": float(scenario["task_replan_period_s"]),
        "arrival_radius_m": float(scenario["arrival_radius_m"]),
        "hold_time_s": float(scenario["hold_time_s"]),
        "sample_every_s": float(scenario["sample_every_s"]),
        "warmup_s": float(scenario["warmup_s"]),
    }
    extra = dict((scenario.get("extra_params") or {}))
    params.update(extra)
    return params


def _resolve_target(
    payload: dict[str, Any],
    *,
    current_repo: Path,
    main_repo: Path,
    config_dir: Path,
) -> RunnableTarget:
    key = _safe_text(payload.get("key")).strip()
    if not key:
        raise ValueError(f"System entry is missing a non-empty key: {payload!r}")
    kind = _safe_text(payload.get("type")).strip()
    if not kind:
        raise ValueError(f"System {key!r} is missing a type.")

    if kind == "simplification_stage":
        stage_key = _safe_text(payload.get("stage")).strip()
        stage = get_stage(stage_key)
        params = dict(STAGE_PROPOSED_DEFAULTS)
        params.update(dict(stage.overrides))
        params.update(dict(payload.get("params") or {}))
        title = _safe_text(payload.get("title")).strip() or str(stage.title)
        description = (
            _safe_text(payload.get("description")).strip()
            or f"Simplification stage {stage.key}: {stage.description}"
        )
        return RunnableTarget(
            key=key,
            title=title,
            description=description,
            kind=kind,
            repo=str(current_repo.resolve()),
            module_name=str(stage.module_name),
            params=params,
            source={"stage": stage.public_dict()},
        )

    if kind == "exploration_variant":
        variant_key = _safe_text(payload.get("variant")).strip()
        if variant_key not in EXPLORATION_VARIANTS:
            known = ", ".join(sorted(EXPLORATION_VARIANTS.keys()))
            raise KeyError(f"Unknown exploration variant {variant_key!r}. Expected one of: {known}")
        variant = EXPLORATION_VARIANTS[variant_key]
        params = dict(variant.get("overrides", {}))
        params.update(dict(payload.get("params") or {}))
        title = _safe_text(payload.get("title")).strip() or _safe_text(variant.get("title"))
        description = (
            _safe_text(payload.get("description")).strip()
            or _safe_text(variant.get("description"))
        )
        return RunnableTarget(
            key=key,
            title=title,
            description=description,
            kind=kind,
            repo=str(current_repo.resolve()),
            module_name="exploration.row_local_priority_system",
            params=params,
            source={"variant_key": variant_key, "variant": dict(variant)},
        )

    if kind == "current_mode":
        mode = _safe_text(payload.get("mode")).strip()
        params = _mode_defaults(mode)
        params.update(dict(payload.get("params") or {}))
        module_name = _safe_text(payload.get("module")).strip() or "DeterrentSystem"
        title = _safe_text(payload.get("title")).strip() or f"Current {mode}"
        description = _safe_text(payload.get("description")).strip() or f"Current workspace mode {mode}."
        return RunnableTarget(
            key=key,
            title=title,
            description=description,
            kind=kind,
            repo=str(current_repo.resolve()),
            module_name=module_name,
            params=params,
            source={"mode": mode},
        )

    if kind == "repo_module":
        repo = _resolve_repo_path(
            payload.get("repo"),
            current_repo=current_repo,
            main_repo=main_repo,
            config_dir=config_dir,
        )
        module_name = _safe_text(payload.get("module")).strip()
        if not module_name:
            raise ValueError(f"repo_module target {key!r} is missing `module`.")
        params = dict(payload.get("params") or {})
        title = _safe_text(payload.get("title")).strip() or key
        description = _safe_text(payload.get("description")).strip() or f"Module target {module_name} in {repo}."
        return RunnableTarget(
            key=key,
            title=title,
            description=description,
            kind=kind,
            repo=str(repo),
            module_name=module_name,
            params=params,
            source={"repo": _safe_text(payload.get("repo")), "module": module_name},
        )

    raise ValueError(
        f"Unknown system type {kind!r} for {key!r}. Expected simplification_stage, exploration_variant, current_mode, or repo_module."
    )


def _resolve_targets(
    config: dict[str, Any],
    *,
    current_repo: Path,
    main_repo: Path,
    config_dir: Path,
) -> list[RunnableTarget]:
    systems = list(config.get("systems") or [])
    if not systems:
        raise ValueError("Testbench config must define at least one system.")
    targets: list[RunnableTarget] = []
    seen: set[str] = set()
    for payload in systems:
        target = _resolve_target(
            dict(payload),
            current_repo=current_repo,
            main_repo=main_repo,
            config_dir=config_dir,
        )
        if target.key in seen:
            raise ValueError(f"Duplicate system key in testbench config: {target.key!r}")
        seen.add(target.key)
        module_path = _module_path(Path(target.repo), target.module_name)
        if not module_path.exists():
            raise FileNotFoundError(
                f"Target {target.key!r} points to missing module path: {module_path}"
            )
        targets.append(target)
    return targets


def _metric_spec_from_entry(entry: Any) -> bench.MetricSpec:
    if isinstance(entry, str):
        if entry not in METRIC_LIBRARY:
            known = ", ".join(sorted(METRIC_LIBRARY.keys()))
            raise KeyError(f"Unknown metric {entry!r}. Expected one of: {known}")
        return METRIC_LIBRARY[entry]
    if not isinstance(entry, dict):
        raise TypeError(f"Metric entry must be a string or object, got: {entry!r}")
    column = _safe_text(entry.get("column")).strip()
    if not column:
        raise ValueError(f"Metric entry is missing `column`: {entry!r}")
    label = _safe_text(entry.get("label")).strip() or column
    goal = _safe_text(entry.get("goal")).strip().lower() or "higher"
    if goal not in {"higher", "lower"}:
        raise ValueError(f"Metric goal must be 'higher' or 'lower', got {goal!r}")
    return bench.MetricSpec(column, label, goal)


def _resolve_metric_specs(entries: Sequence[Any] | None, default_columns: Sequence[str]) -> tuple[bench.MetricSpec, ...]:
    if not entries:
        entries = list(default_columns)
    specs: list[bench.MetricSpec] = []
    seen: set[str] = set()
    for entry in entries:
        spec = _metric_spec_from_entry(entry)
        if spec.column in seen:
            continue
        seen.add(spec.column)
        specs.append(spec)
    return tuple(specs)


def _resolve_time_metric_specs(entries: Sequence[Any] | None, default_columns: Sequence[str]) -> tuple[bench.MetricSpec, ...]:
    if not entries:
        entries = list(default_columns)
    specs: list[bench.MetricSpec] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            if entry not in TIME_METRIC_LIBRARY:
                known = ", ".join(sorted(TIME_METRIC_LIBRARY.keys()))
                raise KeyError(f"Unknown time-plot metric {entry!r}. Expected one of: {known}")
            spec = TIME_METRIC_LIBRARY[entry]
        else:
            spec = _metric_spec_from_entry(entry)
        if spec.column in seen:
            continue
        seen.add(spec.column)
        specs.append(spec)
    return tuple(specs)


def _paired_advantage_stats(
    per_run_df: pd.DataFrame,
    *,
    metric_column: str,
    goal: str,
    system_label: str,
    reference_label: str,
) -> tuple[float, float, float, int]:
    if metric_column not in per_run_df.columns:
        return float("nan"), float("nan"), float("nan"), 0
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


def summarize_metric_specs(
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
            adv = _paired_advantage_stats(
                per_run_df,
                metric_column=spec.column,
                goal=spec.goal,
                system_label=label,
                reference_label=reference_label,
            )
            row[f"{label}_advantage_vs_{reference_label}_pct_mean"] = adv[0]
            row[f"{label}_advantage_vs_{reference_label}_pct_ci_lo"] = adv[1]
            row[f"{label}_advantage_vs_{reference_label}_pct_ci_hi"] = adv[2]
            row[f"{label}_advantage_vs_{reference_label}_paired_seed_count"] = adv[3]

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


def build_scoreboard(summary_df: pd.DataFrame, *, system_order: Sequence[str]) -> pd.DataFrame:
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


def _build_summary_view(summary_df: pd.DataFrame, *, system_order: Sequence[str]) -> pd.DataFrame:
    view = summary_df[["label", "goal", "winner"]].copy()
    for label in system_order:
        view[label] = [
            bench._format_ci(mean, lo, hi)
            for mean, lo, hi in zip(
                summary_df[f"{label}_mean"],
                summary_df[f"{label}_ci_lo"],
                summary_df[f"{label}_ci_hi"],
            )
        ]
    ordered = view[["label", "goal", *system_order, "winner"]].copy()
    return ordered.rename(columns={"label": "Metric", "goal": "Goal", "winner": "Winner"})


def _build_advantage_view(
    summary_df: pd.DataFrame,
    *,
    system_order: Sequence[str],
    reference_label: str,
) -> pd.DataFrame:
    out = pd.DataFrame({"Metric": summary_df["label"]})
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


def _plot_time_metrics(
    timeseries_df: pd.DataFrame,
    out_png: Path,
    *,
    metric_specs: Sequence[bench.MetricSpec],
    system_order: Sequence[str],
) -> bool:
    if timeseries_df.empty or not metric_specs:
        return False
    available_specs = [
        spec
        for spec in metric_specs
        if spec.column in timeseries_df.columns
        and pd.to_numeric(timeseries_df[spec.column], errors="coerce").notna().any()
    ]
    if not available_specs:
        return False

    grouped = (
        timeseries_df.groupby(["system", "t"], as_index=False)[[spec.column for spec in available_specs]]
        .mean()
        .sort_values(["system", "t"])
    )
    nplots = len(available_specs)
    ncols = 2 if nplots > 1 else 1
    nrows = int(math.ceil(float(nplots) / float(ncols)))
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 4.0 * nrows), sharex=True)
    if isinstance(axes, np.ndarray):
        axes_flat = axes.ravel()
    else:
        axes_flat = np.array([axes], dtype=object)

    for ax, spec in zip(axes_flat, available_specs):
        for system_name in system_order:
            sub = grouped.loc[grouped["system"] == system_name, ["t", spec.column]].copy()
            if sub.empty:
                continue
            values = pd.to_numeric(sub[spec.column], errors="coerce")
            if not values.notna().any():
                continue
            ax.plot(sub["t"], values, label=system_name, linewidth=1.6)
        ax.set_title(f"{spec.label}\n({spec.goal} better)")
        ax.grid(alpha=0.25)
    for ax in axes_flat[nplots:]:
        ax.axis("off")
    if axes_flat.size > 0:
        axes_flat[0].legend(frameon=False)
    for ax in axes_flat[-ncols:]:
        ax.set_xlabel("Simulation Time (s)")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)
    return True


def _repo_descriptor(repo: Path) -> dict[str, Any]:
    if not repo.exists():
        return {"path": str(repo), "branch": "", "commit": "", "dirty": False}
    return bench._repo_descriptor(repo)


def _write_report(
    out_path: Path,
    *,
    resolved_config: dict[str, Any],
    targets: Sequence[RunnableTarget],
    metric_summary_df: pd.DataFrame,
    scoreboard_df: pd.DataFrame,
    advantage_df: pd.DataFrame,
    current_repo: Path,
    main_repo: Path,
    reference_label: str,
) -> None:
    summary_view = _build_summary_view(metric_summary_df, system_order=[target.key for target in targets])
    outputs_cfg = dict(resolved_config.get("outputs") or {})
    scenario_cfg = dict(resolved_config.get("scenario") or {})
    current_desc = _repo_descriptor(current_repo)
    main_desc = _repo_descriptor(main_repo)

    lines = [
        "# Pluggable Testbench",
        "",
        "This report evaluates all configured systems under the same scenario and metric contract.",
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
        "## Scenario",
        "",
    ]
    for key in sorted(scenario_cfg.keys()):
        lines.append(f"- `{key}`: `{scenario_cfg[key]}`")
    lines.extend(["", "## Systems", ""])
    for target in targets:
        lines.append(f"- `{target.key}`: {target.title}")
        lines.append(f"  kind=`{target.kind}` module=`{target.module_name}` repo=`{target.repo}`")
        lines.append(f"  {target.description}")
    lines.extend(["", "## Output Contract", ""])
    lines.append(f"- reference system: `{reference_label}`")
    lines.append(f"- summarized metrics: `{', '.join(str(item) for item in outputs_cfg.get('metrics', []))}`")
    lines.append(f"- scoreboard metrics: `{', '.join(str(item) for item in outputs_cfg.get('scoreboard_metrics', []))}`")
    lines.append(f"- time-plot metrics: `{', '.join(str(item) for item in outputs_cfg.get('time_plot_metrics', []))}`")
    lines.extend(
        [
            "",
            "## Scoreboard",
            "",
            bench._dataframe_to_markdown(scoreboard_df),
            "",
            "## Metric Summary",
            "",
            bench._dataframe_to_markdown(summary_view),
            "",
            f"Positive advantage means the listed system outperformed `{reference_label}` after accounting for metric direction.",
            "",
            "## Advantage Vs Reference",
            "",
            bench._dataframe_to_markdown(advantage_df),
            "",
            "## Artifacts",
            "",
            "- `per_run_metrics.csv`: one row per system per seed",
            "- `per_run_timeseries.csv`: sampled trajectory metrics when available",
            "- `summary_by_metric.csv`: aggregate means, CI95, and paired deltas vs the reference system",
            "- `trajectory_compare.png`: generic backlog/completion trajectories",
            "- `time_metric_compare.png`: time-series comparison for the selected result metrics",
            "- `system_scoreboard.csv`: metric win counts on the selected scoreboard metric set",
            "- `testbench_manifest.json`: resolved config and target metadata",
            "- `report.md`: this summary",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_worker_subprocess(
    *,
    system_label: str,
    repo: Path,
    module_name: str,
    seed: int,
    params: dict[str, Any],
    out_json: Path,
    out_csv: Path,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "testbench.run_testbench",
        "--worker",
        "--worker-label",
        system_label,
        "--worker-repo",
        str(repo.resolve()),
        "--worker-module",
        module_name,
        "--worker-seed",
        str(seed),
        "--worker-params-json",
        json.dumps(params),
        "--worker-out-json",
        str(out_json.resolve()),
        "--worker-out-csv",
        str(out_csv.resolve()),
    ]
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    proc = subprocess.run(cmd, cwd=str(Path.cwd()), capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Worker failed for {system_label} seed={seed}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    return payload["summary"]


def run_worker(args: argparse.Namespace) -> int:
    repo = Path(args.worker_repo).resolve()
    module_name = str(args.worker_module)
    module_path = _module_path(repo, module_name)
    script_dir = Path(__file__).resolve().parent
    filtered_sys_path: list[str] = []
    for entry in sys.path:
        try:
            if entry and Path(entry).resolve() == script_dir:
                continue
        except Exception:
            pass
        filtered_sys_path.append(entry)
    sys.path = [str(repo)] + filtered_sys_path
    os.chdir(repo)

    spec = importlib.util.spec_from_file_location(f"testbench_target_{module_name.replace('.', '_')}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module {module_name!r} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"testbench_target_{module_name.replace('.', '_')}"] = module
    spec.loader.exec_module(module)

    mon = getattr(module, "mon", None)
    if mon is not None and hasattr(mon, "enabled"):
        mon.enabled = False

    params = json.loads(args.worker_params_json)
    params["seed"] = int(args.worker_seed)
    sample_every_s = bench._safe_float(params.pop("sample_every_s", 60.0), 60.0)

    runner = getattr(module, "run_simulation_frames_persistent", None)
    if runner is None:
        raise AttributeError(f"Module {module_name!r} does not expose run_simulation_frames_persistent.")
    call_kwargs = bench._filter_supported_kwargs(runner, params)
    sig = inspect.signature(runner).parameters
    if "report_metrics_end" in sig:
        call_kwargs.setdefault("report_metrics_end", False)
    if "telemetry_clear_on_start" in sig:
        call_kwargs.setdefault("telemetry_clear_on_start", False)
    if "telemetry_prompt_save" in sig:
        call_kwargs.setdefault("telemetry_prompt_save", False)
    if "simulation_mode" in sig:
        call_kwargs.setdefault("simulation_mode", "proposed")
    if "telemetry_dir" in sig:
        call_kwargs.setdefault("telemetry_dir", f"telemetry_testbench_{args.worker_label}_{args.worker_seed}")

    collector = bench.BenchmarkCollector(sample_every_s=sample_every_s)
    for frame in runner(**call_kwargs):
        collector.consume(frame)

    summary = collector.finalize()
    summary["system"] = str(args.worker_label)
    summary["seed"] = int(args.worker_seed)
    summary["repo"] = str(repo)
    summary["module_name"] = module_name
    summary["supported_call_kwargs"] = call_kwargs
    summary["sample_every_s"] = sample_every_s

    out_json = Path(args.worker_out_json)
    out_csv = Path(args.worker_out_csv)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"summary": summary}, indent=2), encoding="utf-8")
    pd.DataFrame(collector.sample_rows).assign(
        system=str(args.worker_label),
        seed=int(args.worker_seed),
    ).to_csv(out_csv, index=False)
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a config-driven pluggable testbench over simplification stages, exploration variants, "
            "and direct repo modules."
        )
    )
    parser.add_argument("--config", default="testbench/example_config.json", help="Path to a JSON testbench config.")
    parser.add_argument("--current-repo", default=str(Path.cwd()), help="Path to the current workspace.")
    parser.add_argument(
        "--main-repo",
        default=str(Path.cwd().parent / f"{Path.cwd().name}-main"),
        help="Path to the sibling main worktree.",
    )
    parser.add_argument("--outdir", default="", help="Optional output-directory override.")
    parser.add_argument("--max-workers", type=int, default=0, help="Override config parallelism. 0 => auto.")
    parser.add_argument("--write-example-config", default="", help="Write the bundled example config to this path and exit.")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-label", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-repo", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-module", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--worker-params-json", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-out-json", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-out-csv", default="", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _write_example_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(EXAMPLE_CONFIG, indent=2), encoding="utf-8")


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Testbench config does not exist: {config_path}")
    return json.loads(config_path.read_text(encoding="utf-8"))


def _effective_max_workers(requested: int, job_count: int) -> int:
    if job_count <= 1:
        return 1
    if int(requested) > 0:
        return max(1, min(int(requested), int(job_count)))
    cpu = os.cpu_count() or 1
    return max(1, min(int(cpu), int(job_count)))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.worker:
        return run_worker(args)

    if args.write_example_config:
        _write_example_config(Path(args.write_example_config))
        print(f"[testbench] wrote example config to {Path(args.write_example_config).resolve()}")
        return 0

    current_repo = Path(args.current_repo).resolve()
    main_repo = Path(args.main_repo).resolve()
    config_path = Path(args.config).resolve()
    config_dir = config_path.parent
    config = _load_config(config_path)
    scenario = _normalize_scenario(config)
    outputs_cfg = dict(config.get("outputs") or {})
    shared_params = _shared_runner_params(scenario)
    targets = _resolve_targets(
        config,
        current_repo=current_repo,
        main_repo=main_repo,
        config_dir=config_dir,
    )
    system_order = [target.key for target in targets]

    outdir_text = _safe_text(args.outdir).strip() or _safe_text(outputs_cfg.get("outdir")).strip()
    if not outdir_text:
        outdir_text = "results/testbench/default"
    outdir = Path(outdir_text)
    if not outdir.is_absolute():
        outdir = (current_repo / outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    raw_dir = outdir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    metric_specs = _resolve_metric_specs(outputs_cfg.get("metrics"), DEFAULT_OUTPUT_METRICS)
    scoreboard_specs = _resolve_metric_specs(outputs_cfg.get("scoreboard_metrics"), DEFAULT_SCOREBOARD_METRICS)
    time_plot_specs = _resolve_time_metric_specs(outputs_cfg.get("time_plot_metrics"), DEFAULT_TIME_PLOT_METRICS)
    reference_label = _safe_text(outputs_cfg.get("reference_system")).strip() or system_order[0]
    if reference_label not in system_order:
        raise ValueError(
            f"Reference system {reference_label!r} is not in the configured systems: {', '.join(system_order)}"
        )

    jobs: list[dict[str, Any]] = []
    for offset in range(int(scenario["num_runs"])):
        seed = int(scenario["seed_start"]) + offset
        for target in targets:
            params = dict(shared_params)
            params.update(dict(target.params))
            jobs.append(
                {
                    "system_label": target.key,
                    "repo": Path(target.repo),
                    "module_name": target.module_name,
                    "seed": seed,
                    "params": params,
                    "out_json": raw_dir / target.key / f"seed_{seed}.json",
                    "out_csv": raw_dir / target.key / f"seed_{seed}.csv",
                }
            )

    summaries: list[dict[str, Any]] = []
    max_workers = _effective_max_workers(int(args.max_workers), len(jobs))
    if max_workers == 1:
        for job in jobs:
            print(f"[testbench] running {job['system_label']} seed={job['seed']}")
            summaries.append(_run_worker_subprocess(**job))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_run_worker_subprocess, **job): job for job in jobs}
            completed = 0
            for future in as_completed(future_map):
                completed += 1
                job = future_map[future]
                print(
                    f"[testbench] completed {completed}/{len(jobs)} "
                    f"system={job['system_label']} seed={job['seed']}"
                )
                summaries.append(future.result())

    if not summaries:
        raise RuntimeError("Testbench produced no run summaries.")

    order_map = {label: idx for idx, label in enumerate(system_order)}
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
        bench._plot_trajectories(timeseries_df, outdir / "trajectory_compare.png")
        _plot_time_metrics(
            timeseries_df,
            outdir / "time_metric_compare.png",
            metric_specs=time_plot_specs,
            system_order=system_order,
        )

    metric_summary_df = summarize_metric_specs(
        per_run_df,
        metric_specs=metric_specs,
        system_order=system_order,
        reference_label=reference_label,
    )
    metric_summary_df.to_csv(outdir / "summary_by_metric.csv", index=False)

    scoreboard_metric_columns = {spec.column for spec in scoreboard_specs}
    scoreboard_summary_df = metric_summary_df.loc[
        metric_summary_df["metric"].isin(scoreboard_metric_columns)
    ].reset_index(drop=True)
    scoreboard_df = build_scoreboard(scoreboard_summary_df, system_order=system_order)
    scoreboard_df.to_csv(outdir / "system_scoreboard.csv", index=False)

    advantage_df = _build_advantage_view(
        metric_summary_df,
        system_order=system_order,
        reference_label=reference_label,
    )
    advantage_df.to_csv(outdir / "advantage_vs_reference.csv", index=False)

    resolved_config = _deepcopy_payload(config)
    resolved_config["scenario"] = dict(scenario)
    resolved_config["outputs"] = {
        **outputs_cfg,
        "outdir": str(outdir),
        "reference_system": reference_label,
        "metrics": [spec.column for spec in metric_specs],
        "scoreboard_metrics": [spec.column for spec in scoreboard_specs],
        "time_plot_metrics": [spec.column for spec in time_plot_specs],
    }
    manifest = {
        "config_path": str(config_path),
        "current_repo": _repo_descriptor(current_repo),
        "main_repo": _repo_descriptor(main_repo),
        "resolved_config": resolved_config,
        "targets": [target.public_dict() for target in targets],
    }
    (outdir / "testbench_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_report(
        outdir / "report.md",
        resolved_config=resolved_config,
        targets=targets,
        metric_summary_df=metric_summary_df,
        scoreboard_df=scoreboard_df,
        advantage_df=advantage_df,
        current_repo=current_repo,
        main_repo=main_repo,
        reference_label=reference_label,
    )

    print("[testbench] outputs written to:")
    print(f"- {outdir}")
    print("- per_run_metrics.csv")
    print("- summary_by_metric.csv")
    print("- system_scoreboard.csv")
    print("- report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
