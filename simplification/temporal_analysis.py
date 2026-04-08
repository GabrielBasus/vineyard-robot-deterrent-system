from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .stages import SIMPLIFICATION_STAGE_ORDER


_MAIN_STAGE_PREFERENCE = (
    "s5_current_thesis_profile",
    "s4_capacity_budget",
    "s3_persistence",
    "s2_direct_conflict",
    "s1_risk_open_core",
    "s1_main_core",
    "s0_simple_tasks_core",
)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Analyze simplification-stage performance over time. "
            "Reads per-stage comparison_over_time.csv files and produces both "
            "cumulative horizon metrics and windowed time-bout metrics."
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
        help="Stage key to treat as the current full/main reference in the markdown summary.",
    )
    p.add_argument(
        "--bout-seconds",
        type=float,
        default=0.0,
        help="Time-bout window in seconds. 0 => use the native sample period from comparison_over_time.csv.",
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


def _fmt_float(value: Any, digits: int = 3) -> str:
    val = _safe_float(value)
    if not np.isfinite(val):
        return "nan"
    return f"{val:.{digits}f}"


def _bird_metric_column(df: pd.DataFrame) -> str:
    for column in ("birds_deterred_pct_last_hour_mean", "birds_deterred_pct_mean"):
        if column in df.columns:
            return column
    return "birds_deterred_pct_mean"


def _bird_metric_label(column: str) -> str:
    if str(column) == "birds_deterred_pct_last_hour_mean":
        return "last-hour bird deterrence"
    return "bird deterrence"


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


def _load_manifest(stage_dir: Path) -> dict[str, Any]:
    manifest_path = stage_dir / "stage_manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _stage_keys(args: argparse.Namespace, output_root: Path) -> tuple[str, ...]:
    if args.all_found:
        found = sorted(p.name for p in output_root.iterdir() if p.is_dir())
        return tuple(found)
    if args.stages:
        return tuple(args.stages)
    return tuple(key for key in SIMPLIFICATION_STAGE_ORDER if (output_root / key).is_dir())


def _resolve_main_reference_stage(stage_keys: tuple[str, ...], requested_stage: str) -> str:
    available = {str(v) for v in stage_keys}
    requested = _safe_text(requested_stage).strip()
    if requested and requested.lower() not in {"auto", "none"}:
        if requested not in available:
            choices = ", ".join(sorted(available))
            raise KeyError(
                f"Requested main reference stage {requested!r} is not available. "
                f"Found stages: {choices}"
            )
        return requested
    for stage_key in _MAIN_STAGE_PREFERENCE:
        if stage_key in available:
            return stage_key
    return str(stage_keys[-1]) if stage_keys else ""


def _native_sample_period_s(df: pd.DataFrame) -> float:
    if df.empty or "t_s" not in df.columns:
        return float("nan")
    times = sorted({_safe_float(v) for v in df["t_s"].tolist() if np.isfinite(_safe_float(v))})
    if len(times) < 2:
        return float("nan")
    diffs = [times[idx] - times[idx - 1] for idx in range(1, len(times)) if (times[idx] - times[idx - 1]) > 1.0e-9]
    if not diffs:
        return float("nan")
    return float(min(diffs))


def _prepare_time_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    numeric_cols = [c for c in out.columns if c != "baseline"]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["baseline"] = out["baseline"].astype(str)
    out = out.sort_values(["t_s", "baseline"]).reset_index(drop=True)
    return out


def _row_metric(df: pd.DataFrame, baseline: str, t_s: float, column: str) -> float:
    rows = df.loc[(df["baseline"] == str(baseline)) & (np.isclose(df["t_s"], float(t_s)))]
    if rows.empty or column not in rows.columns:
        return float("nan")
    return _safe_float(rows.iloc[0][column])


def _build_cumulative_long(stage_key: str, stage_meta: dict[str, Any], df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    times = sorted({_safe_float(v) for v in df["t_s"].tolist() if np.isfinite(_safe_float(v))})
    bird_metric_column = _bird_metric_column(df)
    for t_s in times:
        prop_exp = _row_metric(df, "proposed", t_s, "value_weighted_exposure_mean")
        pred_exp = _row_metric(df, "prediction_only", t_s, "value_weighted_exposure_mean")
        react_exp = _row_metric(df, "reactive", t_s, "value_weighted_exposure_mean")
        prop_exp_rate = _row_metric(df, "proposed", t_s, "exposure_rate_per_hour_so_far_mean")
        pred_exp_rate = _row_metric(df, "prediction_only", t_s, "exposure_rate_per_hour_so_far_mean")
        react_exp_rate = _row_metric(df, "reactive", t_s, "exposure_rate_per_hour_so_far_mean")
        prop_tasks_ph = _row_metric(df, "proposed", t_s, "tasks_per_hour_so_far_mean")
        pred_tasks_ph = _row_metric(df, "prediction_only", t_s, "tasks_per_hour_so_far_mean")
        react_tasks_ph = _row_metric(df, "reactive", t_s, "tasks_per_hour_so_far_mean")
        prop_comm = _row_metric(df, "proposed", t_s, "boundary_message_count_mean")
        pred_comm = _row_metric(df, "prediction_only", t_s, "boundary_message_count_mean")
        react_comm = _row_metric(df, "reactive", t_s, "boundary_message_count_mean")
        rows.append(
            {
                "stage_key": stage_key,
                "stage_title": _safe_text(stage_meta.get("title")),
                "module_name": _safe_text(stage_meta.get("module_name")),
                "bird_metric_column": bird_metric_column,
                "t_s": float(t_s),
                "horizon_h": float(t_s) / 3600.0,
                "proposed_exposure_mean": prop_exp,
                "prediction_only_exposure_mean": pred_exp,
                "reactive_exposure_mean": react_exp,
                "proposed_vs_prediction_exposure_improve_pct": _pct_improvement(pred_exp, prop_exp),
                "proposed_vs_reactive_exposure_improve_pct": _pct_improvement(react_exp, prop_exp),
                "proposed_exposure_rate_per_hour_so_far_mean": prop_exp_rate,
                "prediction_only_exposure_rate_per_hour_so_far_mean": pred_exp_rate,
                "reactive_exposure_rate_per_hour_so_far_mean": react_exp_rate,
                "proposed_vs_prediction_exposure_rate_improve_pct": _pct_improvement(pred_exp_rate, prop_exp_rate),
                "proposed_vs_reactive_exposure_rate_improve_pct": _pct_improvement(react_exp_rate, prop_exp_rate),
                "proposed_tasks_per_hour_so_far_mean": prop_tasks_ph,
                "prediction_only_tasks_per_hour_so_far_mean": pred_tasks_ph,
                "reactive_tasks_per_hour_so_far_mean": react_tasks_ph,
                "proposed_vs_prediction_tasks_per_hour_change_pct": _pct_change(pred_tasks_ph, prop_tasks_ph),
                "proposed_vs_reactive_tasks_per_hour_change_pct": _pct_change(react_tasks_ph, prop_tasks_ph),
                "proposed_boundary_message_count_mean": prop_comm,
                "prediction_only_boundary_message_count_mean": pred_comm,
                "reactive_boundary_message_count_mean": react_comm,
                "proposed_vs_prediction_comm_change_pct": _pct_change(pred_comm, prop_comm),
                "proposed_vs_reactive_comm_change_pct": _pct_change(react_comm, prop_comm),
                "proposed_completed_tasks_total_mean": _row_metric(df, "proposed", t_s, "completed_tasks_total_mean"),
                "prediction_only_completed_tasks_total_mean": _row_metric(df, "prediction_only", t_s, "completed_tasks_total_mean"),
                "reactive_completed_tasks_total_mean": _row_metric(df, "reactive", t_s, "completed_tasks_total_mean"),
                "proposed_model_deterring_generated_mean": _row_metric(df, "proposed", t_s, "model_deterring_generated_mean"),
                "proposed_model_deterring_accepted_mean": _row_metric(df, "proposed", t_s, "model_deterring_accepted_mean"),
                "proposed_truth_suppressed_events_mean": _row_metric(df, "proposed", t_s, "truth_suppressed_events_mean"),
                "prediction_only_truth_suppressed_events_mean": _row_metric(df, "prediction_only", t_s, "truth_suppressed_events_mean"),
                "reactive_truth_suppressed_events_mean": _row_metric(df, "reactive", t_s, "truth_suppressed_events_mean"),
                "proposed_truth_suppression_rate_mean": _row_metric(df, "proposed", t_s, "truth_suppression_rate_mean"),
                "prediction_only_truth_suppression_rate_mean": _row_metric(df, "prediction_only", t_s, "truth_suppression_rate_mean"),
                "reactive_truth_suppression_rate_mean": _row_metric(df, "reactive", t_s, "truth_suppression_rate_mean"),
                "proposed_birds_deterred_pct_mean": _row_metric(df, "proposed", t_s, bird_metric_column),
                "prediction_only_birds_deterred_pct_mean": _row_metric(df, "prediction_only", t_s, bird_metric_column),
                "reactive_birds_deterred_pct_mean": _row_metric(df, "reactive", t_s, bird_metric_column),
            }
        )
    return pd.DataFrame(rows)


def _resolve_bout_seconds(requested_bout_s: float, native_step_s: float) -> float:
    if not np.isfinite(native_step_s) or native_step_s <= 0.0:
        return float("nan")
    if not np.isfinite(requested_bout_s) or requested_bout_s <= 0.0:
        return float(native_step_s)
    multiple = float(requested_bout_s) / float(native_step_s)
    if abs(multiple - round(multiple)) > 1.0e-6:
        raise ValueError(
            f"Requested bout length {requested_bout_s} s is not an integer multiple of "
            f"the native sampling period {native_step_s} s."
        )
    return float(requested_bout_s)


def _build_bout_long(
    stage_key: str,
    stage_meta: dict[str, Any],
    df: pd.DataFrame,
    bout_seconds: float,
) -> pd.DataFrame:
    times = sorted({int(round(_safe_float(v))) for v in df["t_s"].tolist() if np.isfinite(_safe_float(v))})
    if not times:
        return pd.DataFrame()
    time_set = set(times)
    max_time = int(max(times))
    bout_s_int = int(round(float(bout_seconds)))
    boundaries = list(range(0, max_time + bout_s_int, bout_s_int))
    if boundaries[-1] > max_time:
        boundaries[-1] = max_time
    boundaries = sorted(set(boundaries))
    if boundaries[0] != 0:
        boundaries.insert(0, 0)
    if boundaries[-1] != max_time:
        boundaries.append(max_time)
    missing = [t for t in boundaries if t not in time_set]
    if missing:
        raise ValueError(
            f"Stage {stage_key!r} is missing comparison_over_time samples for required bout boundaries: {missing}"
        )

    delta_metrics = [
        "value_weighted_exposure_mean",
        "completed_tasks_total_mean",
        "boundary_message_count_mean",
        "model_deterring_generated_mean",
        "model_deterring_accepted_mean",
        "truth_candidate_events_mean",
        "truth_suppressed_events_mean",
    ]
    baselines = ("proposed", "prediction_only", "reactive")
    rows: list[dict[str, Any]] = []
    for idx in range(1, len(boundaries)):
        start_s = int(boundaries[idx - 1])
        end_s = int(boundaries[idx])
        duration_s = float(end_s - start_s)
        duration_h = duration_s / 3600.0 if duration_s > 0.0 else float("nan")
        out: dict[str, Any] = {
            "stage_key": stage_key,
            "stage_title": _safe_text(stage_meta.get("title")),
            "module_name": _safe_text(stage_meta.get("module_name")),
            "bout_start_s": float(start_s),
            "bout_end_s": float(end_s),
            "bout_start_h": float(start_s) / 3600.0,
            "bout_end_h": float(end_s) / 3600.0,
            "bout_duration_s": duration_s,
            "bout_duration_h": duration_h,
        }
        for baseline in baselines:
            for metric in delta_metrics:
                end_val = _row_metric(df, baseline, end_s, metric)
                start_val = _row_metric(df, baseline, start_s, metric)
                out[f"{baseline}_{metric}_delta"] = end_val - start_val if np.isfinite(end_val) and np.isfinite(start_val) else float("nan")
            exposure_delta = _safe_float(out.get(f"{baseline}_value_weighted_exposure_mean_delta"))
            tasks_delta = _safe_float(out.get(f"{baseline}_completed_tasks_total_mean_delta"))
            comm_delta = _safe_float(out.get(f"{baseline}_boundary_message_count_mean_delta"))
            out[f"{baseline}_exposure_rate_per_hour_in_bout"] = (
                exposure_delta / duration_h if np.isfinite(exposure_delta) and np.isfinite(duration_h) and duration_h > 0.0 else float("nan")
            )
            out[f"{baseline}_tasks_per_hour_in_bout"] = (
                tasks_delta / duration_h if np.isfinite(tasks_delta) and np.isfinite(duration_h) and duration_h > 0.0 else float("nan")
            )
            out[f"{baseline}_boundary_messages_per_hour_in_bout"] = (
                comm_delta / duration_h if np.isfinite(comm_delta) and np.isfinite(duration_h) and duration_h > 0.0 else float("nan")
            )

        out["proposed_vs_prediction_exposure_improve_pct_bout"] = _pct_improvement(
            out.get("prediction_only_value_weighted_exposure_mean_delta"),
            out.get("proposed_value_weighted_exposure_mean_delta"),
        )
        out["proposed_vs_reactive_exposure_improve_pct_bout"] = _pct_improvement(
            out.get("reactive_value_weighted_exposure_mean_delta"),
            out.get("proposed_value_weighted_exposure_mean_delta"),
        )
        out["proposed_vs_prediction_exposure_rate_improve_pct_bout"] = _pct_improvement(
            out.get("prediction_only_exposure_rate_per_hour_in_bout"),
            out.get("proposed_exposure_rate_per_hour_in_bout"),
        )
        out["proposed_vs_reactive_exposure_rate_improve_pct_bout"] = _pct_improvement(
            out.get("reactive_exposure_rate_per_hour_in_bout"),
            out.get("proposed_exposure_rate_per_hour_in_bout"),
        )
        out["proposed_vs_prediction_tasks_per_hour_change_pct_bout"] = _pct_change(
            out.get("prediction_only_tasks_per_hour_in_bout"),
            out.get("proposed_tasks_per_hour_in_bout"),
        )
        out["proposed_vs_reactive_tasks_per_hour_change_pct_bout"] = _pct_change(
            out.get("reactive_tasks_per_hour_in_bout"),
            out.get("proposed_tasks_per_hour_in_bout"),
        )
        out["proposed_vs_prediction_comm_change_pct_bout"] = _pct_change(
            out.get("prediction_only_boundary_messages_per_hour_in_bout"),
            out.get("proposed_boundary_messages_per_hour_in_bout"),
        )
        out["proposed_vs_reactive_comm_change_pct_bout"] = _pct_change(
            out.get("reactive_boundary_messages_per_hour_in_bout"),
            out.get("proposed_boundary_messages_per_hour_in_bout"),
        )
        rows.append(out)
    return pd.DataFrame(rows)


def _first_positive_time(df: pd.DataFrame, col: str, *, time_col: str) -> float:
    if df.empty or col not in df.columns or time_col not in df.columns:
        return float("nan")
    tmp = df.copy()
    tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
    tmp[time_col] = pd.to_numeric(tmp[time_col], errors="coerce")
    tmp = tmp[np.isfinite(tmp[col]) & np.isfinite(tmp[time_col])]
    tmp = tmp.loc[tmp[col] > 0.0].sort_values(time_col)
    if tmp.empty:
        return float("nan")
    return float(tmp.iloc[0][time_col])


def _best_row(df: pd.DataFrame, col: str, *, larger_is_better: bool = True) -> pd.Series | None:
    if df.empty or col not in df.columns:
        return None
    tmp = df.copy()
    tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
    tmp = tmp[np.isfinite(tmp[col])]
    if tmp.empty:
        return None
    idx = tmp[col].idxmax() if larger_is_better else tmp[col].idxmin()
    return tmp.loc[idx]


def _half_delta(df: pd.DataFrame, time_col: str, value_col: str) -> float:
    if df.empty or time_col not in df.columns or value_col not in df.columns:
        return float("nan")
    tmp = df.copy()
    tmp[time_col] = pd.to_numeric(tmp[time_col], errors="coerce")
    tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce")
    tmp = tmp[np.isfinite(tmp[time_col]) & np.isfinite(tmp[value_col])]
    if tmp.empty:
        return float("nan")
    split = float(tmp[time_col].max()) / 2.0
    early = tmp.loc[tmp[time_col] <= split, value_col]
    late = tmp.loc[tmp[time_col] > split, value_col]
    if early.empty or late.empty:
        return float("nan")
    return float(late.mean() - early.mean())


def _positive_share(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return float("nan")
    vals = pd.to_numeric(df[col], errors="coerce")
    vals = vals[np.isfinite(vals)]
    if vals.empty:
        return float("nan")
    return float((vals > 0.0).mean())


def _build_stage_summary(
    stage_key: str,
    stage_meta: dict[str, Any],
    cumulative_df: pd.DataFrame,
    bout_df: pd.DataFrame,
    *,
    bout_seconds: float,
) -> dict[str, Any]:
    if cumulative_df.empty:
        raise ValueError(f"No cumulative temporal rows for stage {stage_key!r}")
    final_row = cumulative_df.sort_values("t_s").iloc[-1]
    best_pred_row = _best_row(cumulative_df, "proposed_vs_prediction_exposure_improve_pct", larger_is_better=True)
    best_react_row = _best_row(cumulative_df, "proposed_vs_reactive_exposure_improve_pct", larger_is_better=True)
    best_pred_bout_row = _best_row(bout_df, "proposed_vs_prediction_exposure_improve_pct_bout", larger_is_better=True)
    best_react_bout_row = _best_row(bout_df, "proposed_vs_reactive_exposure_improve_pct_bout", larger_is_better=True)

    return {
        "stage_key": stage_key,
        "stage_title": _safe_text(stage_meta.get("title")),
        "module_name": _safe_text(stage_meta.get("module_name")),
        "description": _safe_text(stage_meta.get("description")),
        "bird_metric_column": _safe_text(final_row.get("bird_metric_column")),
        "final_horizon_h": _safe_float(final_row.get("horizon_h")),
        "bout_seconds": float(bout_seconds),
        "bout_h": float(bout_seconds) / 3600.0 if np.isfinite(bout_seconds) else float("nan"),
        "final_proposed_vs_prediction_exposure_improve_pct": _safe_float(final_row.get("proposed_vs_prediction_exposure_improve_pct")),
        "final_proposed_vs_reactive_exposure_improve_pct": _safe_float(final_row.get("proposed_vs_reactive_exposure_improve_pct")),
        "final_proposed_vs_prediction_exposure_rate_improve_pct": _safe_float(final_row.get("proposed_vs_prediction_exposure_rate_improve_pct")),
        "final_proposed_vs_reactive_exposure_rate_improve_pct": _safe_float(final_row.get("proposed_vs_reactive_exposure_rate_improve_pct")),
        "final_proposed_vs_prediction_tasks_per_hour_change_pct": _safe_float(final_row.get("proposed_vs_prediction_tasks_per_hour_change_pct")),
        "final_proposed_vs_reactive_tasks_per_hour_change_pct": _safe_float(final_row.get("proposed_vs_reactive_tasks_per_hour_change_pct")),
        "final_proposed_vs_prediction_comm_change_pct": _safe_float(final_row.get("proposed_vs_prediction_comm_change_pct")),
        "final_proposed_vs_reactive_comm_change_pct": _safe_float(final_row.get("proposed_vs_reactive_comm_change_pct")),
        "final_proposed_model_deterring_generated_mean": _safe_float(final_row.get("proposed_model_deterring_generated_mean")),
        "final_proposed_model_deterring_accepted_mean": _safe_float(final_row.get("proposed_model_deterring_accepted_mean")),
        "final_proposed_completed_tasks_total_mean": _safe_float(final_row.get("proposed_completed_tasks_total_mean")),
        "final_proposed_birds_deterred_pct_mean": _safe_float(final_row.get("proposed_birds_deterred_pct_mean")),
        "final_prediction_only_birds_deterred_pct_mean": _safe_float(final_row.get("prediction_only_birds_deterred_pct_mean")),
        "final_reactive_birds_deterred_pct_mean": _safe_float(final_row.get("reactive_birds_deterred_pct_mean")),
        "first_positive_horizon_vs_prediction_h": _first_positive_time(
            cumulative_df, "proposed_vs_prediction_exposure_improve_pct", time_col="horizon_h"
        ),
        "first_positive_horizon_vs_reactive_h": _first_positive_time(
            cumulative_df, "proposed_vs_reactive_exposure_improve_pct", time_col="horizon_h"
        ),
        "best_horizon_vs_prediction_h": _safe_float(best_pred_row.get("horizon_h")) if best_pred_row is not None else float("nan"),
        "best_horizon_vs_prediction_exposure_improve_pct": _safe_float(best_pred_row.get("proposed_vs_prediction_exposure_improve_pct"))
        if best_pred_row is not None
        else float("nan"),
        "best_horizon_vs_reactive_h": _safe_float(best_react_row.get("horizon_h")) if best_react_row is not None else float("nan"),
        "best_horizon_vs_reactive_exposure_improve_pct": _safe_float(best_react_row.get("proposed_vs_reactive_exposure_improve_pct"))
        if best_react_row is not None
        else float("nan"),
        "best_bout_start_h_vs_prediction": _safe_float(best_pred_bout_row.get("bout_start_h")) if best_pred_bout_row is not None else float("nan"),
        "best_bout_end_h_vs_prediction": _safe_float(best_pred_bout_row.get("bout_end_h")) if best_pred_bout_row is not None else float("nan"),
        "best_bout_vs_prediction_exposure_improve_pct": _safe_float(best_pred_bout_row.get("proposed_vs_prediction_exposure_improve_pct_bout"))
        if best_pred_bout_row is not None
        else float("nan"),
        "best_bout_start_h_vs_reactive": _safe_float(best_react_bout_row.get("bout_start_h")) if best_react_bout_row is not None else float("nan"),
        "best_bout_end_h_vs_reactive": _safe_float(best_react_bout_row.get("bout_end_h")) if best_react_bout_row is not None else float("nan"),
        "best_bout_vs_reactive_exposure_improve_pct": _safe_float(best_react_bout_row.get("proposed_vs_reactive_exposure_improve_pct_bout"))
        if best_react_bout_row is not None
        else float("nan"),
        "positive_bout_share_vs_prediction": _positive_share(bout_df, "proposed_vs_prediction_exposure_improve_pct_bout"),
        "positive_bout_share_vs_reactive": _positive_share(bout_df, "proposed_vs_reactive_exposure_improve_pct_bout"),
        "birds_deterred_pct_minus_prediction_pts": (
            _safe_float(final_row.get("proposed_birds_deterred_pct_mean"))
            - _safe_float(final_row.get("prediction_only_birds_deterred_pct_mean"))
        ),
        "birds_deterred_pct_minus_reactive_pts": (
            _safe_float(final_row.get("proposed_birds_deterred_pct_mean"))
            - _safe_float(final_row.get("reactive_birds_deterred_pct_mean"))
        ),
        "late_minus_early_cumulative_vs_prediction_pct": _half_delta(
            cumulative_df, "horizon_h", "proposed_vs_prediction_exposure_improve_pct"
        ),
        "late_minus_early_cumulative_vs_reactive_pct": _half_delta(
            cumulative_df, "horizon_h", "proposed_vs_reactive_exposure_improve_pct"
        ),
        "late_minus_early_bout_vs_prediction_pct": _half_delta(
            bout_df, "bout_end_h", "proposed_vs_prediction_exposure_improve_pct_bout"
        ),
        "late_minus_early_bout_vs_reactive_pct": _half_delta(
            bout_df, "bout_end_h", "proposed_vs_reactive_exposure_improve_pct_bout"
        ),
    }


def _render_trend_text(delta_value: float) -> str:
    val = _safe_float(delta_value)
    if not np.isfinite(val):
        return "trend unclear"
    if val > 0.25:
        return "strengthens late"
    if val < -0.25:
        return "weakens late"
    return "roughly stable"


def _render_markdown(summary_df: pd.DataFrame, main_stage_key: str) -> str:
    if summary_df.empty:
        return "# Temporal Analysis\n\nNo temporal stage outputs were found.\n"

    bout_s = _safe_float(summary_df.iloc[0].get("bout_seconds"))
    lines = [
        "# Temporal Analysis",
        "",
        "This report summarizes how stage performance changes with horizon length and across consecutive time bouts.",
        "",
        f"Main/current reference stage: `{main_stage_key}`" if main_stage_key else "Main/current reference stage: not set",
        f"Native bout window used in this report: `{_fmt_float(bout_s, 1)}` s" if np.isfinite(bout_s) else "Native bout window used in this report: unknown",
        "",
        "## Stage Summary",
        "",
        "```text",
    ]
    keep_cols = [
        "stage_key",
        "final_proposed_vs_prediction_exposure_improve_pct",
        "final_proposed_vs_reactive_exposure_improve_pct",
        "best_horizon_vs_prediction_h",
        "best_horizon_vs_prediction_exposure_improve_pct",
        "best_horizon_vs_reactive_h",
        "best_horizon_vs_reactive_exposure_improve_pct",
        "best_bout_vs_prediction_exposure_improve_pct",
        "best_bout_vs_reactive_exposure_improve_pct",
        "positive_bout_share_vs_prediction",
        "positive_bout_share_vs_reactive",
        "final_proposed_birds_deterred_pct_mean",
        "final_proposed_model_deterring_accepted_mean",
        "final_proposed_model_deterring_generated_mean",
    ]
    lines.append(summary_df[[c for c in keep_cols if c in summary_df.columns]].to_string(index=False))
    lines.extend(["```", "", "## Stage Notes", ""])

    for _, row in summary_df.iterrows():
        lines.append(f"### {row['stage_key']}: {row.get('stage_title', '')}")
        lines.append(
            f"- Final horizon ({_fmt_float(row.get('final_horizon_h'), 2)} h): "
            f"vs prediction={_fmt_float(row.get('final_proposed_vs_prediction_exposure_improve_pct'))}%, "
            f"vs reactive={_fmt_float(row.get('final_proposed_vs_reactive_exposure_improve_pct'))}%."
        )
        lines.append(
            f"- Best cumulative horizon: "
            f"vs prediction={_fmt_float(row.get('best_horizon_vs_prediction_exposure_improve_pct'))}% "
            f"at {_fmt_float(row.get('best_horizon_vs_prediction_h'), 2)} h; "
            f"vs reactive={_fmt_float(row.get('best_horizon_vs_reactive_exposure_improve_pct'))}% "
            f"at {_fmt_float(row.get('best_horizon_vs_reactive_h'), 2)} h."
        )
        lines.append(
            f"- Best time bout: "
            f"vs prediction={_fmt_float(row.get('best_bout_vs_prediction_exposure_improve_pct'))}% "
            f"from {_fmt_float(row.get('best_bout_start_h_vs_prediction'), 2)} to {_fmt_float(row.get('best_bout_end_h_vs_prediction'), 2)} h; "
            f"vs reactive={_fmt_float(row.get('best_bout_vs_reactive_exposure_improve_pct'))}% "
            f"from {_fmt_float(row.get('best_bout_start_h_vs_reactive'), 2)} to {_fmt_float(row.get('best_bout_end_h_vs_reactive'), 2)} h."
        )
        lines.append(
            f"- Positive-bout share: "
            f"vs prediction={_fmt_float(100.0 * _safe_float(row.get('positive_bout_share_vs_prediction')))}%, "
            f"vs reactive={_fmt_float(100.0 * _safe_float(row.get('positive_bout_share_vs_reactive')))}%."
        )
        lines.append(
            f"- Horizon trend: vs prediction {_render_trend_text(row.get('late_minus_early_cumulative_vs_prediction_pct'))}; "
            f"vs reactive {_render_trend_text(row.get('late_minus_early_cumulative_vs_reactive_pct'))}."
        )
        lines.append(
            f"- Preventive activity by final horizon: generated={_fmt_float(row.get('final_proposed_model_deterring_generated_mean'))}, "
            f"accepted={_fmt_float(row.get('final_proposed_model_deterring_accepted_mean'))}, "
            f"completed_tasks={_fmt_float(row.get('final_proposed_completed_tasks_total_mean'))}."
        )
        lines.append(
            f"- {_bird_metric_label(_safe_text(row.get('bird_metric_column'))).capitalize()} by final horizon: "
            f"proposed={_fmt_float(row.get('final_proposed_birds_deterred_pct_mean'))}%, "
            f"prediction_only={_fmt_float(row.get('final_prediction_only_birds_deterred_pct_mean'))}%, "
            f"reactive={_fmt_float(row.get('final_reactive_birds_deterred_pct_mean'))}%, "
            f"delta_vs_prediction={_fmt_float(row.get('birds_deterred_pct_minus_prediction_pts'))} pts, "
            f"delta_vs_reactive={_fmt_float(row.get('birds_deterred_pct_minus_reactive_pts'))} pts."
        )
        lines.append("")
    return "\n".join(lines)


def write_temporal_analysis(
    *,
    output_root: str | Path = "results/simplification",
    stage_keys: tuple[str, ...] | None = None,
    main_stage: str = "auto",
    bout_seconds: float = 0.0,
) -> dict[str, Any]:
    output_root = Path(output_root)
    if stage_keys is None:
        stage_keys = tuple(key for key in SIMPLIFICATION_STAGE_ORDER if (output_root / key).is_dir())
    if not stage_keys:
        raise FileNotFoundError(f"No stage outputs found under {output_root}")

    summary_rows: list[dict[str, Any]] = []
    cumulative_frames: list[pd.DataFrame] = []
    bout_frames: list[pd.DataFrame] = []
    resolved_bout_seconds = float("nan")

    for stage_key in stage_keys:
        stage_dir = output_root / stage_key
        manifest = _load_manifest(stage_dir)
        stage_meta = manifest.get("stage", {})
        time_df = _prepare_time_df(_load_csv(stage_dir / "comparison_over_time.csv"))
        if time_df.empty:
            raise FileNotFoundError(
                f"Missing or empty comparison_over_time.csv for stage {stage_key!r} at {stage_dir}"
            )
        native_step_s = _native_sample_period_s(time_df)
        resolved_stage_bout_s = _resolve_bout_seconds(float(bout_seconds), native_step_s)
        if not np.isfinite(resolved_bout_seconds):
            resolved_bout_seconds = resolved_stage_bout_s
        elif abs(float(resolved_bout_seconds) - float(resolved_stage_bout_s)) > 1.0e-6:
            raise ValueError(
                "All selected stages must have the same resolved bout length. "
                f"Got {resolved_bout_seconds} and {resolved_stage_bout_s}."
            )

        cumulative_df = _build_cumulative_long(stage_key, stage_meta, time_df)
        bout_df = _build_bout_long(stage_key, stage_meta, time_df, resolved_stage_bout_s)
        summary_rows.append(
            _build_stage_summary(
                stage_key,
                stage_meta,
                cumulative_df,
                bout_df,
                bout_seconds=resolved_stage_bout_s,
            )
        )
        cumulative_frames.append(cumulative_df)
        bout_frames.append(bout_df)

    summary_df = pd.DataFrame(summary_rows)
    order_rank = {key: idx for idx, key in enumerate(SIMPLIFICATION_STAGE_ORDER)}
    summary_df["stage_order"] = summary_df["stage_key"].map(lambda k: order_rank.get(k, 10_000))
    summary_df = summary_df.sort_values(["stage_order", "stage_key"]).reset_index(drop=True)

    cumulative_long_df = pd.concat(cumulative_frames, ignore_index=True) if cumulative_frames else pd.DataFrame()
    bout_long_df = pd.concat(bout_frames, ignore_index=True) if bout_frames else pd.DataFrame()
    if not cumulative_long_df.empty:
        cumulative_long_df["stage_order"] = cumulative_long_df["stage_key"].map(lambda k: order_rank.get(k, 10_000))
        cumulative_long_df = cumulative_long_df.sort_values(["stage_order", "stage_key", "t_s"]).reset_index(drop=True)
    if not bout_long_df.empty:
        bout_long_df["stage_order"] = bout_long_df["stage_key"].map(lambda k: order_rank.get(k, 10_000))
        bout_long_df = bout_long_df.sort_values(["stage_order", "stage_key", "bout_end_s"]).reset_index(drop=True)

    main_stage_key = _resolve_main_reference_stage(tuple(summary_df["stage_key"].tolist()), str(main_stage))
    summary_path = output_root / "temporal_horizon_summary.csv"
    cumulative_path = output_root / "temporal_horizon_long.csv"
    bout_path = output_root / "temporal_bout_long.csv"
    bout_summary_path = output_root / "temporal_bout_summary.csv"
    report_path = output_root / "temporal_analysis.md"

    summary_df.to_csv(summary_path, index=False)
    summary_df.to_csv(bout_summary_path, index=False)
    if not cumulative_long_df.empty:
        cumulative_long_df.to_csv(cumulative_path, index=False)
    if not bout_long_df.empty:
        bout_long_df.to_csv(bout_path, index=False)
    report_path.write_text(_render_markdown(summary_df, main_stage_key), encoding="utf-8")

    return {
        "summary_df": summary_df,
        "cumulative_long_df": cumulative_long_df,
        "bout_long_df": bout_long_df,
        "main_stage_key": main_stage_key,
        "resolved_bout_seconds": resolved_bout_seconds,
        "summary_path": summary_path,
        "cumulative_path": cumulative_path,
        "bout_path": bout_path,
        "bout_summary_path": bout_summary_path,
        "report_path": report_path,
    }


def main() -> None:
    args = _parser().parse_args()
    output_root = Path(args.output_root)
    stage_keys = _stage_keys(args, output_root)
    result = write_temporal_analysis(
        output_root=output_root,
        stage_keys=stage_keys,
        main_stage=str(args.main_stage),
        bout_seconds=float(args.bout_seconds),
    )

    print(f"[simplification] wrote {result['summary_path']}")
    if not result["cumulative_long_df"].empty:
        print(f"[simplification] wrote {result['cumulative_path']}")
    if not result["bout_long_df"].empty:
        print(f"[simplification] wrote {result['bout_path']}")
    print(f"[simplification] wrote {result['bout_summary_path']}")
    print(f"[simplification] wrote {result['report_path']}")


if __name__ == "__main__":
    main()
