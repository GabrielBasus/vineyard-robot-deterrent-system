from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .stages import SIMPLIFICATION_STAGE_ORDER


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Aggregate simplification stage outputs into one comparison table. "
            "Reads results/simplification/<stage>/comparison.csv files produced by "
            "python -m simplification.run_stage."
        )
    )
    p.add_argument(
        "--stage",
        action="append",
        dest="stages",
        help="Specific stage key to include. Repeat to include multiple stages.",
    )
    p.add_argument(
        "--all-found",
        action="store_true",
        help="Include every stage directory found under the output root, not just the canonical stage order.",
    )
    p.add_argument(
        "--output-root",
        default="results/simplification",
        help="Root directory containing per-stage outputs.",
    )
    p.add_argument(
        "--main-stage",
        default="auto",
        help=(
            "Stage key to treat as the current full/main reference. "
            "Default: auto, which prefers s5_current_thesis_profile and otherwise "
            "falls back to the most complete available stage."
        ),
    )
    return p


def _safe_float(value: Any) -> float:
    if value is None:
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    return str(value)


def _pct_improvement(reference: float, candidate: float) -> float:
    ref = _safe_float(reference)
    cand = _safe_float(candidate)
    if not np.isfinite(ref) or abs(ref) <= 1.0e-12 or not np.isfinite(cand):
        return float("nan")
    return 100.0 * (ref - cand) / ref


def _pct_change(reference: float, candidate: float) -> float:
    ref = _safe_float(reference)
    cand = _safe_float(candidate)
    if not np.isfinite(ref) or abs(ref) <= 1.0e-12 or not np.isfinite(cand):
        return float("nan")
    return 100.0 * (cand - ref) / ref


def _column_or_nan(df: pd.DataFrame, baseline: str, column: str) -> float:
    if column not in df.columns:
        return float("nan")
    rows = df.loc[df["baseline"] == baseline, column]
    if rows.empty:
        return float("nan")
    return _safe_float(rows.iloc[0])


def _column_or_text(df: pd.DataFrame, baseline: str, column: str) -> str:
    if column not in df.columns:
        return ""
    rows = df.loc[df["baseline"] == baseline, column]
    if rows.empty:
        return ""
    return _safe_text(rows.iloc[0])


def _bird_metric_column(df: pd.DataFrame) -> str:
    for column in ("birds_deterred_pct_last_hour_mean", "birds_deterred_pct_mean"):
        if column in df.columns:
            return column
    return "birds_deterred_pct_mean"


def _bird_metric_value(df: pd.DataFrame, baseline: str) -> float:
    for column in ("birds_deterred_pct_last_hour_mean", "birds_deterred_pct_mean"):
        value = _column_or_nan(df, baseline, column)
        if np.isfinite(value):
            return value
    return float("nan")


def _bird_metric_label(column: str) -> str:
    if str(column) == "birds_deterred_pct_last_hour_mean":
        return "last-hour bird deterrence"
    return "bird deterrence"


def _stage_keys(args: argparse.Namespace, output_root: Path) -> tuple[str, ...]:
    if args.all_found:
        found = sorted(p.name for p in output_root.iterdir() if p.is_dir())
        return tuple(found)
    if args.stages:
        return tuple(args.stages)
    return tuple(key for key in SIMPLIFICATION_STAGE_ORDER if (output_root / key).is_dir())


def _load_manifest(stage_dir: Path) -> dict[str, Any]:
    manifest_path = stage_dir / "stage_manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _comm_reference_column(df: pd.DataFrame) -> str:
    if "boundary_bytes_sent_mean" in df.columns:
        return "boundary_bytes_sent_mean"
    if "boundary_message_count_mean" in df.columns:
        return "boundary_message_count_mean"
    return ""


def _planner_rejection_total_proposed(df: pd.DataFrame) -> float:
    cols = [
        "planner_rejected_task_cap_mean",
        "planner_rejected_patrol_cap_mean",
        "planner_rejected_model_det_cap_mean",
        "planner_rejected_model_det_cycle_cap_mean",
        "planner_rejected_model_det_busy_primary_mean",
        "planner_rejected_model_det_busy_fallback_quality_mean",
        "planner_rejected_model_det_direct_conflict_mean",
        "planner_rejected_patrol_locked_model_det_mean",
        "planner_rejected_unassigned_mean",
    ]
    vals = [_column_or_nan(df, "proposed", c) for c in cols if c in df.columns]
    if not vals:
        return float("nan")
    return float(np.nansum(vals))


def _resolve_main_reference_stage(summary_df: pd.DataFrame, requested_stage: str) -> str:
    if summary_df.empty or "stage_key" not in summary_df.columns:
        return ""

    available = {str(v) for v in summary_df["stage_key"].tolist()}
    requested = _safe_text(requested_stage).strip()
    if requested and requested.lower() not in {"auto", "none"}:
        if requested not in available:
            choices = ", ".join(sorted(available))
            raise KeyError(
                f"Requested main reference stage {requested!r} is not available. "
                f"Found stages: {choices}"
            )
        return requested

    preferred = (
        "s5_current_thesis_profile",
        "s4_capacity_budget",
        "s3_persistence",
        "s2_direct_conflict",
        "s1_risk_open_core",
        "s1_main_core",
        "s0_simple_tasks_core",
    )
    for stage_key in preferred:
        if stage_key in available:
            return stage_key
    return str(summary_df.iloc[-1]["stage_key"])


def _build_stage_summary(stage_key: str, output_root: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    stage_dir = output_root / stage_key
    manifest = _load_manifest(stage_dir)
    comparison_df = _load_csv(stage_dir / "comparison.csv")
    over_time_df = _load_csv(stage_dir / "comparison_over_time.csv")

    if comparison_df.empty:
        raise FileNotFoundError(f"Missing or empty comparison.csv for stage {stage_key!r} at {stage_dir}")

    stage_info = manifest.get("stage", {})
    runner_args = manifest.get("runner_args", {})
    sim_kwargs = manifest.get("sim_kwargs", {})

    exp_prop = _column_or_nan(comparison_df, "proposed", "value_weighted_exposure_mean")
    exp_pred = _column_or_nan(comparison_df, "prediction_only", "value_weighted_exposure_mean")
    exp_react = _column_or_nan(comparison_df, "reactive", "value_weighted_exposure_mean")

    resp_prop = _column_or_nan(comparison_df, "proposed", "mean_response_time_s_mean")
    resp_pred = _column_or_nan(comparison_df, "prediction_only", "mean_response_time_s_mean")
    resp_react = _column_or_nan(comparison_df, "reactive", "mean_response_time_s_mean")

    comm_col = _comm_reference_column(comparison_df)
    comm_prop = _column_or_nan(comparison_df, "proposed", comm_col) if comm_col else float("nan")
    comm_pred = _column_or_nan(comparison_df, "prediction_only", comm_col) if comm_col else float("nan")
    comm_react = _column_or_nan(comparison_df, "reactive", comm_col) if comm_col else float("nan")
    bird_metric_column = _bird_metric_column(comparison_df)

    row = {
        "stage_key": stage_key,
        "stage_title": _safe_text(stage_info.get("title")),
        "module_name": _safe_text(stage_info.get("module_name")),
        "description": _safe_text(stage_info.get("description")),
        "added_back": " | ".join(stage_info.get("added_back", [])),
        "num_runs": int(runner_args.get("num_runs", 0)),
        "seed_start": int(runner_args.get("seed_start", 0)),
        "t_end": _safe_float(runner_args.get("t_end")),
        "dt": _safe_float(runner_args.get("dt")),
        "nx": int(runner_args.get("nx", 0)),
        "ny": int(runner_args.get("ny", 0)),
        "planner_profile": _safe_text(sim_kwargs.get("planner_profile")),
        "preventive_policy": _column_or_text(comparison_df, "proposed", "preventive_policy"),
        "preventive_policy_source": _column_or_text(comparison_df, "proposed", "preventive_policy_source"),
        "use_frozen_calibration": _column_or_nan(comparison_df, "proposed", "use_frozen_calibration_mean"),
        "selective_preventive_enabled": _column_or_nan(comparison_df, "proposed", "selective_preventive_enabled_mean"),
        "proposed_exposure_mean": exp_prop,
        "prediction_only_exposure_mean": exp_pred,
        "reactive_exposure_mean": exp_react,
        "proposed_vs_prediction_exposure_improve_pct": _pct_improvement(exp_pred, exp_prop),
        "proposed_vs_reactive_exposure_improve_pct": _pct_improvement(exp_react, exp_prop),
        "proposed_response_time_mean": resp_prop,
        "prediction_only_response_time_mean": resp_pred,
        "reactive_response_time_mean": resp_react,
        "proposed_vs_prediction_response_improve_pct": _pct_improvement(resp_pred, resp_prop),
        "proposed_vs_reactive_response_improve_pct": _pct_improvement(resp_react, resp_prop),
        "comm_reference_column": comm_col,
        "bird_metric_column": bird_metric_column,
        "proposed_comm_mean": comm_prop,
        "prediction_only_comm_mean": comm_pred,
        "reactive_comm_mean": comm_react,
        "proposed_vs_prediction_comm_change_pct": _pct_change(comm_pred, comm_prop),
        "proposed_vs_reactive_comm_change_pct": _pct_change(comm_react, comm_prop),
        "proposed_model_candidates_mean": _column_or_nan(comparison_df, "proposed", "model_deterring_candidates_total_mean"),
        "proposed_model_generated_mean": _column_or_nan(comparison_df, "proposed", "model_deterring_generated_mean"),
        "proposed_model_accepted_mean": _column_or_nan(comparison_df, "proposed", "model_deterring_accepted_mean"),
        "proposed_model_completed_mean": _column_or_nan(comparison_df, "proposed", "deterring_actions_completed_model_scored_mean"),
        "proposed_model_precision_mean": _column_or_nan(comparison_df, "proposed", "deterring_action_precision_model_scored_mean"),
        "proposed_model_suppression_per_action_mean": _column_or_nan(comparison_df, "proposed", "suppression_per_model_deterring_action_mean"),
        "proposed_model_vs_direct_yield_ratio_mean": _column_or_nan(comparison_df, "proposed", "model_vs_direct_suppression_yield_ratio_mean"),
        "proposed_birds_deterred_pct_mean": _bird_metric_value(comparison_df, "proposed"),
        "prediction_only_birds_deterred_pct_mean": _bird_metric_value(comparison_df, "prediction_only"),
        "reactive_birds_deterred_pct_mean": _bird_metric_value(comparison_df, "reactive"),
        "proposed_minus_prediction_birds_deterred_pct_pts": (
            _bird_metric_value(comparison_df, "proposed")
            - _bird_metric_value(comparison_df, "prediction_only")
        ),
        "proposed_minus_reactive_birds_deterred_pct_pts": (
            _bird_metric_value(comparison_df, "proposed")
            - _bird_metric_value(comparison_df, "reactive")
        ),
        "proposed_budget_rejections_mean": _column_or_nan(comparison_df, "proposed", "model_deterring_rejected_budget_mean"),
        "proposed_capacity_pending_mean": _column_or_nan(comparison_df, "proposed", "model_deterring_capacity_pending_mean"),
        "proposed_task_cap_rejections_mean": _column_or_nan(comparison_df, "proposed", "planner_rejected_task_cap_mean"),
        "proposed_patrol_cap_rejections_mean": _column_or_nan(comparison_df, "proposed", "planner_rejected_patrol_cap_mean"),
        "proposed_model_cap_rejections_mean": _column_or_nan(comparison_df, "proposed", "planner_rejected_model_det_cap_mean"),
        "proposed_cycle_cap_rejections_mean": _column_or_nan(comparison_df, "proposed", "planner_rejected_model_det_cycle_cap_mean"),
        "proposed_busy_primary_rejections_mean": _column_or_nan(comparison_df, "proposed", "planner_rejected_model_det_busy_primary_mean"),
        "proposed_busy_quality_rejections_mean": _column_or_nan(comparison_df, "proposed", "planner_rejected_model_det_busy_fallback_quality_mean"),
        "proposed_direct_conflict_rejections_mean": _column_or_nan(comparison_df, "proposed", "planner_rejected_model_det_direct_conflict_mean"),
        "proposed_patrol_locked_rejections_mean": _column_or_nan(comparison_df, "proposed", "planner_rejected_patrol_locked_model_det_mean"),
        "proposed_total_planner_rejections_mean": _planner_rejection_total_proposed(comparison_df),
    }

    if not comparison_df.empty:
        comparison_df = comparison_df.copy()
        comparison_df.insert(0, "stage_key", stage_key)
        comparison_df.insert(1, "stage_title", row["stage_title"])
        comparison_df.insert(2, "module_name", row["module_name"])
    if not over_time_df.empty:
        over_time_df = over_time_df.copy()
        over_time_df.insert(0, "stage_key", stage_key)
        over_time_df.insert(1, "stage_title", row["stage_title"])
        over_time_df.insert(2, "module_name", row["module_name"])
    return row, comparison_df, over_time_df


def _append_stage_deltas(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return summary_df
    summary_df = summary_df.copy()
    delta_cols = [
        "proposed_exposure_mean",
        "proposed_vs_prediction_exposure_improve_pct",
        "proposed_vs_reactive_exposure_improve_pct",
        "proposed_response_time_mean",
        "proposed_vs_prediction_response_improve_pct",
        "proposed_vs_reactive_response_improve_pct",
        "proposed_comm_mean",
        "proposed_vs_prediction_comm_change_pct",
        "proposed_vs_reactive_comm_change_pct",
        "proposed_model_accepted_mean",
        "proposed_model_completed_mean",
        "proposed_birds_deterred_pct_mean",
        "proposed_minus_prediction_birds_deterred_pct_pts",
        "proposed_minus_reactive_birds_deterred_pct_pts",
        "proposed_total_planner_rejections_mean",
    ]
    for col in delta_cols:
        if col not in summary_df.columns:
            continue
        summary_df[f"delta_prev_{col}"] = summary_df[col].diff()
    return summary_df


def _append_main_reference_comparisons(summary_df: pd.DataFrame, main_stage_key: str) -> pd.DataFrame:
    if summary_df.empty or not main_stage_key:
        return summary_df
    ref_rows = summary_df.loc[summary_df["stage_key"] == main_stage_key]
    if ref_rows.empty:
        return summary_df

    ref = ref_rows.iloc[0]
    summary_df = summary_df.copy()
    summary_df["main_reference_stage_key"] = str(main_stage_key)
    summary_df["is_main_reference_stage"] = summary_df["stage_key"].eq(main_stage_key).astype(int)

    delta_cols = [
        "proposed_exposure_mean",
        "proposed_vs_prediction_exposure_improve_pct",
        "proposed_vs_reactive_exposure_improve_pct",
        "proposed_response_time_mean",
        "proposed_vs_prediction_response_improve_pct",
        "proposed_vs_reactive_response_improve_pct",
        "proposed_comm_mean",
        "proposed_vs_prediction_comm_change_pct",
        "proposed_vs_reactive_comm_change_pct",
        "proposed_model_accepted_mean",
        "proposed_model_completed_mean",
        "proposed_total_planner_rejections_mean",
    ]
    for col in delta_cols:
        if col not in summary_df.columns:
            continue
        ref_value = _safe_float(ref.get(col))
        if not np.isfinite(ref_value):
            summary_df[f"delta_main_{col}"] = float("nan")
            continue
        summary_df[f"delta_main_{col}"] = summary_df[col] - ref_value
    return summary_df


def _render_markdown(summary_df: pd.DataFrame, main_stage_key: str) -> str:
    if summary_df.empty:
        return "# Simplification Stage Comparison\n\nNo stage outputs were found.\n"

    lines = [
        "# Simplification Stage Comparison",
        "",
        "This file summarizes how each staged planner/control layer changes the thesis baselines.",
        "",
        f"Main/current reference stage: `{main_stage_key}`" if main_stage_key else "Main/current reference stage: not set",
        "",
        "## Key Metrics",
        "",
    ]
    keep_cols = [
        "stage_key",
        "module_name",
        "proposed_vs_prediction_exposure_improve_pct",
        "proposed_vs_reactive_exposure_improve_pct",
        "proposed_vs_prediction_response_improve_pct",
        "proposed_vs_reactive_response_improve_pct",
        "proposed_vs_prediction_comm_change_pct",
        "proposed_vs_reactive_comm_change_pct",
        "proposed_model_accepted_mean",
        "proposed_model_completed_mean",
        "proposed_total_planner_rejections_mean",
        "delta_main_proposed_exposure_mean",
        "delta_main_proposed_model_completed_mean",
        "delta_main_proposed_total_planner_rejections_mean",
    ]
    present = [c for c in keep_cols if c in summary_df.columns]
    lines.append("```text")
    lines.append(summary_df[present].to_string(index=False))
    lines.append("```")
    lines.append("")
    lines.append("## Stage Notes")
    lines.append("")
    for _, row in summary_df.iterrows():
        lines.append(f"### {row['stage_key']}: {row.get('stage_title', '')}")
        lines.append(f"- Module: `{row.get('module_name', '')}`")
        desc = _safe_text(row.get("description"))
        if desc:
            lines.append(f"- Description: {desc}")
        added_back = _safe_text(row.get("added_back"))
        if added_back:
            lines.append(f"- Adds back: {added_back}")
        lines.append(
            "- Proposed vs prediction-only:"
            f" exposure={_safe_float(row.get('proposed_vs_prediction_exposure_improve_pct')):.3f}%"
            f", response={_safe_float(row.get('proposed_vs_prediction_response_improve_pct')):.3f}%"
            f", comm={_safe_float(row.get('proposed_vs_prediction_comm_change_pct')):.3f}%"
        )
        lines.append(
            "- Proposed vs reactive:"
            f" exposure={_safe_float(row.get('proposed_vs_reactive_exposure_improve_pct')):.3f}%"
            f", response={_safe_float(row.get('proposed_vs_reactive_response_improve_pct')):.3f}%"
            f", comm={_safe_float(row.get('proposed_vs_reactive_comm_change_pct')):.3f}%"
        )
        lines.append(
            "- Preventive yield:"
            f" accepted={_safe_float(row.get('proposed_model_accepted_mean')):.3f},"
            f" completed={_safe_float(row.get('proposed_model_completed_mean')):.3f},"
            f" {_bird_metric_label(_safe_text(row.get('bird_metric_column')))}={_safe_float(row.get('proposed_birds_deterred_pct_mean')):.3f},"
            f" planner_rejections={_safe_float(row.get('proposed_total_planner_rejections_mean')):.3f}"
        )
        lines.append(
            f"- {_bird_metric_label(_safe_text(row.get('bird_metric_column'))).capitalize()} comparison:"
            f" vs prediction={_safe_float(row.get('proposed_minus_prediction_birds_deterred_pct_pts')):.3f} pts,"
            f" vs reactive={_safe_float(row.get('proposed_minus_reactive_birds_deterred_pct_pts')):.3f} pts"
        )
        if main_stage_key:
            lines.append(
                f"- Versus main/current stage `{main_stage_key}`:"
                f" exposure_delta={_safe_float(row.get('delta_main_proposed_exposure_mean')):.3f},"
                f" response_delta={_safe_float(row.get('delta_main_proposed_response_time_mean')):.3f},"
                f" comm_delta={_safe_float(row.get('delta_main_proposed_comm_mean')):.3f},"
                f" completed_delta={_safe_float(row.get('delta_main_proposed_model_completed_mean')):.3f},"
                f" planner_rejections_delta={_safe_float(row.get('delta_main_proposed_total_planner_rejections_mean')):.3f}"
            )
        lines.append("")
    return "\n".join(lines)


def write_stage_comparison(
    *,
    output_root: str | Path = "results/simplification",
    stage_keys: tuple[str, ...] | None = None,
    main_stage: str = "auto",
) -> dict[str, Any]:
    output_root = Path(output_root)
    if stage_keys is None:
        stage_keys = tuple(key for key in SIMPLIFICATION_STAGE_ORDER if (output_root / key).is_dir())
    if not stage_keys:
        raise FileNotFoundError(f"No stage outputs found under {output_root}")

    summary_rows = []
    long_frames = []
    time_frames = []
    for stage_key in stage_keys:
        row, comparison_df, over_time_df = _build_stage_summary(stage_key, output_root)
        summary_rows.append(row)
        if not comparison_df.empty:
            long_frames.append(comparison_df)
        if not over_time_df.empty:
            time_frames.append(over_time_df)

    summary_df = pd.DataFrame(summary_rows)
    order_rank = {key: idx for idx, key in enumerate(SIMPLIFICATION_STAGE_ORDER)}
    if "stage_key" in summary_df.columns:
        summary_df["stage_order"] = summary_df["stage_key"].map(lambda k: order_rank.get(k, 10_000))
        summary_df = summary_df.sort_values(["stage_order", "stage_key"]).reset_index(drop=True)
    summary_df = _append_stage_deltas(summary_df)
    main_stage_key = _resolve_main_reference_stage(summary_df, main_stage)
    summary_df = _append_main_reference_comparisons(summary_df, main_stage_key)

    baseline_long_df = pd.concat(long_frames, ignore_index=True) if long_frames else pd.DataFrame()
    over_time_long_df = pd.concat(time_frames, ignore_index=True) if time_frames else pd.DataFrame()

    summary_path = output_root / "stage_comparison.csv"
    baseline_long_path = output_root / "stage_baseline_long.csv"
    over_time_path = output_root / "stage_over_time_long.csv"
    report_path = output_root / "stage_comparison.md"

    summary_df.to_csv(summary_path, index=False)
    if not baseline_long_df.empty:
        baseline_long_df.to_csv(baseline_long_path, index=False)
    if not over_time_long_df.empty:
        over_time_long_df.to_csv(over_time_path, index=False)
    report_path.write_text(_render_markdown(summary_df, main_stage_key), encoding="utf-8")

    return {
        "summary_df": summary_df,
        "baseline_long_df": baseline_long_df,
        "over_time_long_df": over_time_long_df,
        "main_stage_key": main_stage_key,
        "summary_path": summary_path,
        "baseline_long_path": baseline_long_path,
        "over_time_path": over_time_path,
        "report_path": report_path,
    }


def main() -> None:
    args = _parser().parse_args()
    output_root = Path(args.output_root)
    stage_keys = _stage_keys(args, output_root)
    result = write_stage_comparison(
        output_root=output_root,
        stage_keys=stage_keys,
        main_stage=str(args.main_stage),
    )

    print(f"[simplification] wrote {result['summary_path']}")
    if not result["baseline_long_df"].empty:
        print(f"[simplification] wrote {result['baseline_long_path']}")
    if not result["over_time_long_df"].empty:
        print(f"[simplification] wrote {result['over_time_path']}")
    print(f"[simplification] wrote {result['report_path']}")


if __name__ == "__main__":
    main()
