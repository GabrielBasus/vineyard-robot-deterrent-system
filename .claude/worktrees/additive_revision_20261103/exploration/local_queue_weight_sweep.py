from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any

import numpy as np
import pandas as pd

from exploration.variants import EXPLORATION_VARIANTS, variant_names


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate the exploratory row/local-priority system by forcing the "
            "preventive branch open first, then sweeping local queue weights and "
            "repartition timing one parameter family at a time."
        )
    )
    parser.add_argument(
        "--base-variant",
        default="row_local_priority_queue",
        choices=variant_names(),
        help="Exploration variant used as the calibration base.",
    )
    parser.add_argument(
        "--distance-values",
        default="0.02,0.05,0.08,0.12",
        help="Comma-separated values for local_queue_distance_weight.",
    )
    parser.add_argument(
        "--deterring-bonus-values",
        default="4,8,12,16",
        help="Comma-separated values for local_queue_deterring_bonus.",
    )
    parser.add_argument(
        "--direct-bonus-values",
        default="8,10,14,18",
        help="Comma-separated values for local_queue_direct_detection_bonus.",
    )
    parser.add_argument(
        "--age-weight-values",
        default="0.0,0.005,0.01,0.02",
        help="Comma-separated values for local_queue_age_weight.",
    )
    parser.add_argument(
        "--preempt-margin-values",
        default="0.0,0.10,0.25,0.50",
        help="Comma-separated values for local_queue_preempt_margin.",
    )
    parser.add_argument(
        "--repartition-period-values",
        default="15,30,60,120",
        help="Comma-separated values for zone_repartition_period_s.",
    )
    parser.add_argument(
        "--risk-threshold",
        type=float,
        default=0.0,
        help="Heuristic preventive risk threshold applied to every sweep variant.",
    )
    parser.add_argument(
        "--risk-scale",
        type=float,
        default=1e-4,
        help="Heuristic preventive risk scale applied to every sweep variant.",
    )
    parser.add_argument("--num-runs", type=int, default=3, help="Runs per baseline family.")
    parser.add_argument("--seed-start", type=int, default=123, help="First seed for the baseline sweep.")
    parser.add_argument("--t-end", type=float, default=3600.0, help="Simulation horizon in seconds.")
    parser.add_argument("--dt", type=float, default=1.0, help="Simulation step in seconds.")
    parser.add_argument("--nx", type=int, default=120, help="SESTPP grid X cells.")
    parser.add_argument("--ny", type=int, default=96, help="SESTPP grid Y cells.")
    parser.add_argument(
        "--time-metrics-period-s",
        type=float,
        default=300.0,
        help="Time-series sampling cadence.",
    )
    parser.add_argument(
        "--output-root",
        default="results/exploration/local_queue_weight_sweep",
        help="Directory for sweep outputs.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=0,
        help="0 => auto. Parallelism is across sweep variants.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip a sweep variant if its comparison.csv already exists.",
    )
    parser.add_argument(
        "--verbose-variant-logs",
        action="store_true",
        help="Do not pass --quiet to the exploration subprocesses.",
    )
    return parser


def _safe_float(value: Any) -> float:
    try:
        if value in ("", None):
            return float("nan")
        out = float(value)
        if math.isfinite(out):
            return out
        return float("nan")
    except Exception:
        return float("nan")


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _fmt_float(value: Any, digits: int = 3) -> str:
    value_f = _safe_float(value)
    if not math.isfinite(value_f):
        return "nan"
    return f"{value_f:.{digits}f}"


def _pct_improvement(candidate: float, baseline: float) -> float:
    if (not math.isfinite(candidate)) or (not math.isfinite(baseline)) or baseline == 0.0:
        return float("nan")
    return 100.0 * (baseline - candidate) / baseline


def _pct_change(candidate: float, baseline: float) -> float:
    if (not math.isfinite(candidate)) or (not math.isfinite(baseline)) or baseline == 0.0:
        return float("nan")
    return 100.0 * (candidate - baseline) / baseline


def _parse_float_list(text: str) -> tuple[float, ...]:
    out = []
    for item in str(text).split(","):
        token = str(item).strip()
        if not token:
            continue
        out.append(float(token))
    if not out:
        raise ValueError(f"No numeric values found in list: {text!r}")
    return tuple(out)


def _slug_num(value: float) -> str:
    return (
        f"{float(value):.6g}"
        .replace("-", "m")
        .replace("+", "")
        .replace(".", "p")
    )


def _first_present(row: pd.Series, candidates: list[str]) -> float:
    for column in candidates:
        if column in row.index:
            value = _safe_float(row.get(column))
            if math.isfinite(value):
                return value
    return float("nan")


def _row_by_baseline(df: pd.DataFrame, baseline: str) -> pd.Series:
    rows = df.loc[df["baseline"] == str(baseline)]
    if rows.empty:
        raise ValueError(f"Missing baseline row {baseline!r}.")
    return rows.iloc[0]


def _communication_value(row: pd.Series) -> tuple[str, float]:
    if "boundary_bytes_sent_mean" in row.index:
        value = _safe_float(row.get("boundary_bytes_sent_mean"))
        if math.isfinite(value):
            return "boundary_bytes_sent_mean", value
    if "boundary_message_count_mean" in row.index:
        value = _safe_float(row.get("boundary_message_count_mean"))
        if math.isfinite(value):
            return "boundary_message_count_mean", value
    return "boundary_message_count_mean", float("nan")


def _bird_metric_column(row: pd.Series) -> str:
    for column in ("birds_deterred_pct_last_hour_mean", "birds_deterred_pct_mean"):
        if column in row.index:
            return column
    return "birds_deterred_pct_mean"


def _bird_metric_value(row: pd.Series) -> float:
    return _first_present(row, ["birds_deterred_pct_last_hour_mean", "birds_deterred_pct_mean"])


def _bird_metric_label(column: str) -> str:
    if str(column) == "birds_deterred_pct_last_hour_mean":
        return "Last-hour bird deterrence"
    return "Bird deterrence"


def _compute_total_planner_rejections(row: pd.Series) -> float:
    total = 0.0
    found = False
    for column in row.index:
        if column.startswith("planner_rejected_") and column.endswith("_mean"):
            value = _safe_float(row.get(column))
            if math.isfinite(value):
                total += value
                found = True
    return float(total) if found else float("nan")


def _effective_max_workers(requested: int, target_count: int) -> int:
    if target_count <= 1:
        return 1
    if int(requested) > 0:
        return max(1, min(int(requested), int(target_count)))
    cpu = os.cpu_count() or 1
    return max(1, min(int(target_count), int(cpu)))


def _target_output_exists(output_root: Path, output_name: str) -> bool:
    return (output_root / output_name / "comparison.csv").exists()


def _spec_output_name(base_variant: str, family: str, value: float | None) -> str:
    if family == "base":
        return f"{base_variant}__risk_open__base"
    return f"{base_variant}__risk_open__{family}_{_slug_num(float(value))}"


def _variant_specs(args: argparse.Namespace) -> tuple[dict[str, Any], ...]:
    base_variant = str(args.base_variant)
    base_overrides = dict(EXPLORATION_VARIANTS[base_variant]["overrides"])
    families = (
        ("distance", "local_queue_distance_weight", _parse_float_list(args.distance_values)),
        ("deterring_bonus", "local_queue_deterring_bonus", _parse_float_list(args.deterring_bonus_values)),
        ("direct_bonus", "local_queue_direct_detection_bonus", _parse_float_list(args.direct_bonus_values)),
        ("age_weight", "local_queue_age_weight", _parse_float_list(args.age_weight_values)),
        ("preempt_margin", "local_queue_preempt_margin", _parse_float_list(args.preempt_margin_values)),
        ("repartition_period", "zone_repartition_period_s", _parse_float_list(args.repartition_period_values)),
    )

    specs: list[dict[str, Any]] = []
    specs.append(
        {
            "family": "base",
            "param_key": "",
            "param_value": float("nan"),
            "output_name": _spec_output_name(base_variant, "base", None),
            "overrides": {},
        }
    )

    seen: set[tuple[str, float]] = set()
    for family, param_key, values in families:
        base_value = _safe_float(base_overrides.get(param_key))
        for value in values:
            value_f = float(value)
            key = (str(param_key), value_f)
            if key in seen:
                continue
            seen.add(key)
            if math.isfinite(base_value) and abs(value_f - base_value) <= 1.0e-12:
                continue
            specs.append(
                {
                    "family": str(family),
                    "param_key": str(param_key),
                    "param_value": value_f,
                    "output_name": _spec_output_name(base_variant, str(family), value_f),
                    "overrides": {str(param_key): value_f},
                }
            )
    return tuple(specs)


def _worker_entry(payload: dict[str, Any]) -> dict[str, Any]:
    output_root = Path(str(payload["output_root"]))
    output_name = str(payload["output_name"])
    output_dir = output_root / output_name
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "weight_sweep_worker_stdout.log"
    stderr_path = output_dir / "weight_sweep_worker_stderr.log"
    start = time.time()
    try:
        if bool(payload.get("skip_existing")) and _target_output_exists(output_root, output_name):
            return {
                "output_name": output_name,
                "family": str(payload["family"]),
                "status": "skipped",
                "duration_s": 0.0,
                "output_dir": str(output_dir),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }

        cmd = [
            sys.executable,
            "-m",
            "exploration.run_variant",
            "--variant",
            str(payload["base_variant"]),
            "--num-runs",
            str(int(payload["num_runs"])),
            "--seed-start",
            str(int(payload["seed_start"])),
            "--t-end",
            str(float(payload["t_end"])),
            "--dt",
            str(float(payload["dt"])),
            "--nx",
            str(int(payload["nx"])),
            "--ny",
            str(int(payload["ny"])),
            "--time-metrics-period-s",
            str(float(payload["time_metrics_period_s"])),
            "--output-root",
            str(output_root),
            "--label",
            output_name,
            "--set",
            f"model_deterring_risk_threshold={float(payload['risk_threshold'])}",
            "--set",
            f"model_deterring_risk_scale={float(payload['risk_scale'])}",
        ]
        param_key = str(payload.get("param_key", ""))
        if param_key:
            cmd.extend(["--set", f"{param_key}={float(payload['param_value'])}"])
        if not bool(payload.get("verbose_variant_logs")):
            cmd.append("--quiet")

        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"Sweep subprocess failed with exit code {completed.returncode}. See {stderr_path}."
            )
        return {
            "output_name": output_name,
            "family": str(payload["family"]),
            "status": "ok",
            "duration_s": float(time.time() - start),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    except Exception as exc:
        return {
            "output_name": output_name,
            "family": str(payload["family"]),
            "status": "failed",
            "duration_s": float(time.time() - start),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }


def _build_summary_row(output_name: str, spec: dict[str, Any], comparison_df: pd.DataFrame, *, base_variant: str, risk_threshold: float, risk_scale: float) -> dict[str, Any]:
    proposed = _row_by_baseline(comparison_df, "proposed")
    prediction = _row_by_baseline(comparison_df, "prediction_only")
    reactive = _row_by_baseline(comparison_df, "reactive")

    comm_col, proposed_comm = _communication_value(proposed)
    _pred_col, prediction_comm = _communication_value(prediction)
    _react_col, reactive_comm = _communication_value(reactive)

    proposed_exposure = _safe_float(proposed.get("value_weighted_exposure_mean"))
    prediction_exposure = _safe_float(prediction.get("value_weighted_exposure_mean"))
    reactive_exposure = _safe_float(reactive.get("value_weighted_exposure_mean"))

    proposed_response = _safe_float(proposed.get("mean_response_time_s_mean"))
    prediction_response = _safe_float(prediction.get("mean_response_time_s_mean"))
    reactive_response = _safe_float(reactive.get("mean_response_time_s_mean"))

    bird_metric_column = _bird_metric_column(proposed)
    proposed_birds = _bird_metric_value(proposed)
    prediction_birds = _bird_metric_value(prediction)
    reactive_birds = _bird_metric_value(reactive)

    return {
        "output_name": str(output_name),
        "base_variant": str(base_variant),
        "family": str(spec["family"]),
        "param_key": str(spec["param_key"]),
        "param_value": _safe_float(spec["param_value"]),
        "risk_threshold": float(risk_threshold),
        "risk_scale": float(risk_scale),
        "comm_reference_column": str(comm_col),
        "bird_metric_column": str(bird_metric_column),
        "proposed_exposure_mean": proposed_exposure,
        "prediction_only_exposure_mean": prediction_exposure,
        "reactive_exposure_mean": reactive_exposure,
        "proposed_vs_prediction_exposure_improve_pct": _pct_improvement(proposed_exposure, prediction_exposure),
        "proposed_vs_reactive_exposure_improve_pct": _pct_improvement(proposed_exposure, reactive_exposure),
        "proposed_response_time_mean": proposed_response,
        "prediction_only_response_time_mean": prediction_response,
        "reactive_response_time_mean": reactive_response,
        "proposed_vs_prediction_response_improve_pct": _pct_improvement(proposed_response, prediction_response),
        "proposed_vs_reactive_response_improve_pct": _pct_improvement(proposed_response, reactive_response),
        "proposed_comm_mean": proposed_comm,
        "prediction_only_comm_mean": prediction_comm,
        "reactive_comm_mean": reactive_comm,
        "proposed_vs_prediction_comm_change_pct": _pct_change(proposed_comm, prediction_comm),
        "proposed_vs_reactive_comm_change_pct": _pct_change(proposed_comm, reactive_comm),
        "proposed_birds_deterred_pct_mean": proposed_birds,
        "prediction_only_birds_deterred_pct_mean": prediction_birds,
        "reactive_birds_deterred_pct_mean": reactive_birds,
        "proposed_minus_prediction_birds_deterred_pct_pts": (
            proposed_birds - prediction_birds if math.isfinite(proposed_birds) and math.isfinite(prediction_birds) else float("nan")
        ),
        "proposed_minus_reactive_birds_deterred_pct_pts": (
            proposed_birds - reactive_birds if math.isfinite(proposed_birds) and math.isfinite(reactive_birds) else float("nan")
        ),
        "proposed_model_generated_mean": _first_present(proposed, ["model_deterring_generated_mean"]),
        "proposed_model_accepted_mean": _first_present(proposed, ["model_deterring_accepted_mean"]),
        "proposed_model_completed_mean": _first_present(
            proposed,
            ["deterring_actions_completed_model_scored_mean", "model_deterring_completed_mean"],
        ),
        "proposed_total_planner_rejections_mean": _compute_total_planner_rejections(proposed),
        "proposed_task_cap_rejections_mean": _safe_float(proposed.get("planner_rejected_task_cap_mean")),
        "proposed_patrol_cap_rejections_mean": _safe_float(proposed.get("planner_rejected_patrol_cap_mean")),
        "proposed_model_cap_rejections_mean": _safe_float(proposed.get("planner_rejected_model_det_cap_mean")),
        "proposed_truth_suppression_rate_mean": _safe_float(proposed.get("truth_suppression_rate_mean")),
        "proposed_truth_suppressed_events_mean": _safe_float(proposed.get("truth_suppressed_events_mean")),
        "proposed_tasks_per_unit_distance_mean": _safe_float(proposed.get("tasks_per_unit_distance_mean")),
        "proposed_fleet_task_engagement_fraction_mean": _safe_float(proposed.get("fleet_task_engagement_fraction_so_far_mean")),
        "proposed_fleet_idle_no_task_fraction_mean": _safe_float(proposed.get("fleet_idle_no_task_fraction_so_far_mean")),
    }


def _assign_ranks(summary_df: pd.DataFrame) -> pd.DataFrame:
    df = summary_df.copy()
    rank_specs = [
        ("rank_exposure", "proposed_exposure_mean", True),
        ("rank_response", "proposed_response_time_mean", True),
        ("rank_birds_deterred", "proposed_birds_deterred_pct_mean", False),
        ("rank_comm", "proposed_comm_mean", True),
        ("rank_planner_rejections", "proposed_total_planner_rejections_mean", True),
    ]
    for rank_col, metric_col, smaller_is_better in rank_specs:
        metric = pd.to_numeric(df.get(metric_col), errors="coerce")
        df[rank_col] = metric.rank(method="min", ascending=smaller_is_better)
    rank_cols = [name for (name, _metric, _dir) in rank_specs]
    df["rank_overall_mean"] = df[rank_cols].mean(axis=1, skipna=True)
    df["rank_overall"] = df["rank_overall_mean"].rank(method="min", ascending=True)
    return df


def _append_base_deltas(summary_df: pd.DataFrame, base_output_name: str) -> pd.DataFrame:
    rows = summary_df.loc[summary_df["output_name"] == str(base_output_name)]
    if rows.empty:
        return summary_df
    base = rows.iloc[0]
    df = summary_df.copy()
    df["base_output_name"] = str(base_output_name)
    for col in [
        "proposed_exposure_mean",
        "proposed_vs_prediction_exposure_improve_pct",
        "proposed_vs_reactive_exposure_improve_pct",
        "proposed_response_time_mean",
        "proposed_birds_deterred_pct_mean",
        "proposed_comm_mean",
        "proposed_model_completed_mean",
        "proposed_total_planner_rejections_mean",
    ]:
        if col in df.columns:
            df[f"delta_base_{col}"] = pd.to_numeric(df[col], errors="coerce") - _safe_float(base.get(col))
    return df


def _render_report(summary_df: pd.DataFrame, runtime_df: pd.DataFrame, *, base_output_name: str, args: argparse.Namespace) -> str:
    def _best(metric_col: str, *, ascending: bool) -> pd.Series | None:
        metric = pd.to_numeric(summary_df.get(metric_col), errors="coerce")
        tmp = summary_df.loc[metric.notna()].copy()
        if tmp.empty:
            return None
        return tmp.sort_values(metric_col, ascending=ascending).iloc[0]

    lines = [
        "# Local Queue Weight Sweep",
        "",
        f"- Base variant: `{args.base_variant}`",
        f"- Risk-open setting: threshold=`{_fmt_float(args.risk_threshold, 4)}` scale=`{_fmt_float(args.risk_scale, 6)}`",
        f"- Runs per baseline: `{int(args.num_runs)}`",
        f"- Horizon: `{float(args.t_end)}` s",
        "",
        "## Highlights",
        "",
    ]
    best_exposure = _best("proposed_exposure_mean", ascending=True)
    best_response = _best("proposed_response_time_mean", ascending=True)
    best_birds = _best("proposed_birds_deterred_pct_mean", ascending=False)
    best_overall = summary_df.sort_values("rank_overall_mean", ascending=True).iloc[0] if not summary_df.empty else None
    if best_exposure is not None:
        lines.append(
            f"- Best exposure: `{best_exposure['output_name']}` at `{_fmt_float(best_exposure.get('proposed_exposure_mean'))}` "
            f"with `{_fmt_float(best_exposure.get('proposed_vs_reactive_exposure_improve_pct'))}%` vs reactive."
        )
    if best_response is not None:
        lines.append(
            f"- Best response: `{best_response['output_name']}` at `{_fmt_float(best_response.get('proposed_response_time_mean'))} s`."
        )
    if best_birds is not None:
        lines.append(
            f"- Best {_bird_metric_label(_safe_text(best_birds.get('bird_metric_column'))).lower()}: "
            f"`{best_birds['output_name']}` at `{_fmt_float(best_birds.get('proposed_birds_deterred_pct_mean'))}%`."
        )
    if best_overall is not None:
        lines.append(
            f"- Best overall rank: `{best_overall['output_name']}` with `{_fmt_float(best_overall.get('rank_overall_mean'))}`."
        )
    lines.extend(["", "## Runtime", "", "```text"])
    runtime_cols = [c for c in ["output_name", "family", "status", "duration_s"] if c in runtime_df.columns]
    lines.append(runtime_df[runtime_cols].to_string(index=False) if runtime_cols else "No runtime rows.")
    lines.extend(["```", "", "## Sweep Summary", "", "```text"])
    keep_cols = [
        "output_name",
        "family",
        "param_value",
        "proposed_vs_prediction_exposure_improve_pct",
        "proposed_vs_reactive_exposure_improve_pct",
        "proposed_response_time_mean",
        "proposed_birds_deterred_pct_mean",
        "proposed_comm_mean",
        "proposed_model_completed_mean",
        "proposed_total_planner_rejections_mean",
    ]
    present = [c for c in keep_cols if c in summary_df.columns]
    lines.append(summary_df[present].to_string(index=False))
    lines.extend(["```", "", "## Recommended Next Step", ""])
    if best_overall is not None:
        lines.append(
            f"1. Treat `{best_overall['output_name']}` as the next exploratory candidate and compare it directly against `s1_risk_open_core` using `exploration.compare_system_performance` after promoting its settings into a named exploration variant."
        )
    else:
        lines.append(
            "1. No successful sweep variants were summarized."
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parser().parse_args()
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    specs = _variant_specs(args)
    specs_by_output = {str(spec["output_name"]): spec for spec in specs}
    worker_count = _effective_max_workers(int(args.max_workers), len(specs))

    payloads = [
        {
            "base_variant": str(args.base_variant),
            "family": str(spec["family"]),
            "param_key": str(spec["param_key"]),
            "param_value": spec["param_value"],
            "output_name": str(spec["output_name"]),
            "risk_threshold": float(args.risk_threshold),
            "risk_scale": float(args.risk_scale),
            "num_runs": int(args.num_runs),
            "seed_start": int(args.seed_start),
            "t_end": float(args.t_end),
            "dt": float(args.dt),
            "nx": int(args.nx),
            "ny": int(args.ny),
            "time_metrics_period_s": float(args.time_metrics_period_s),
            "output_root": str(args.output_root),
            "skip_existing": bool(args.skip_existing),
            "verbose_variant_logs": bool(args.verbose_variant_logs),
        }
        for spec in specs
    ]

    print(f"[queue-sweep] running {len(specs)} variants with max_workers={worker_count}")
    start_all = time.time()
    runtime_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {pool.submit(_worker_entry, payload): payload["output_name"] for payload in payloads}
        completed = 0
        for future in as_completed(future_map):
            completed += 1
            output_name = future_map[future]
            result = future.result()
            runtime_results.append(result)
            print(
                f"[queue-sweep] completed {completed}/{len(specs)} "
                f"variant={output_name} status={result.get('status')} duration_s={_fmt_float(result.get('duration_s'))}"
            )

    failed = [row for row in runtime_results if str(row.get("status")) == "failed"]
    runtime_df = pd.DataFrame(runtime_results)
    runtime_path = output_root / "local_queue_weight_runtime.csv"
    runtime_df.to_csv(runtime_path, index=False)
    if failed:
        failed_keys = ", ".join(str(row.get("output_name")) for row in failed)
        raise RuntimeError(f"Sweep workers failed for: {failed_keys}. See {runtime_path}.")

    summary_rows: list[dict[str, Any]] = []
    long_frames: list[pd.DataFrame] = []
    successful = [str(row["output_name"]) for row in runtime_results if str(row.get("status")) in {"ok", "skipped"}]
    for output_name in successful:
        comparison_path = output_root / output_name / "comparison.csv"
        comparison_df = pd.read_csv(comparison_path)
        spec = specs_by_output[output_name]
        summary_rows.append(
            _build_summary_row(
                output_name,
                spec,
                comparison_df,
                base_variant=str(args.base_variant),
                risk_threshold=float(args.risk_threshold),
                risk_scale=float(args.risk_scale),
            )
        )
        long_df = comparison_df.copy()
        long_df.insert(0, "output_name", str(output_name))
        long_df.insert(1, "family", str(spec["family"]))
        long_df.insert(2, "param_key", str(spec["param_key"]))
        long_df.insert(3, "param_value", _safe_float(spec["param_value"]))
        long_df.insert(4, "risk_threshold", float(args.risk_threshold))
        long_df.insert(5, "risk_scale", float(args.risk_scale))
        long_frames.append(long_df)

    summary_df = pd.DataFrame(summary_rows)
    summary_df = _assign_ranks(summary_df)
    base_output_name = _spec_output_name(str(args.base_variant), "base", None)
    summary_df = _append_base_deltas(summary_df, base_output_name)
    summary_df = summary_df.sort_values(["rank_overall_mean", "proposed_exposure_mean"], ascending=[True, True]).reset_index(drop=True)
    long_df = pd.concat(long_frames, ignore_index=True) if long_frames else pd.DataFrame()

    summary_path = output_root / "local_queue_weight_summary.csv"
    long_path = output_root / "local_queue_weight_long.csv"
    report_path = output_root / "local_queue_weight_sweep.md"
    manifest_path = output_root / "local_queue_weight_sweep_manifest.json"

    summary_df.to_csv(summary_path, index=False)
    if not long_df.empty:
        long_df.to_csv(long_path, index=False)
    report_path.write_text(_render_report(summary_df, runtime_df, base_output_name=base_output_name, args=args), encoding="utf-8")

    manifest = {
        "base_variant": str(args.base_variant),
        "risk_threshold": float(args.risk_threshold),
        "risk_scale": float(args.risk_scale),
        "distance_values": list(_parse_float_list(args.distance_values)),
        "deterring_bonus_values": list(_parse_float_list(args.deterring_bonus_values)),
        "direct_bonus_values": list(_parse_float_list(args.direct_bonus_values)),
        "age_weight_values": list(_parse_float_list(args.age_weight_values)),
        "preempt_margin_values": list(_parse_float_list(args.preempt_margin_values)),
        "repartition_period_values": list(_parse_float_list(args.repartition_period_values)),
        "num_runs": int(args.num_runs),
        "seed_start": int(args.seed_start),
        "t_end": float(args.t_end),
        "dt": float(args.dt),
        "nx": int(args.nx),
        "ny": int(args.ny),
        "time_metrics_period_s": float(args.time_metrics_period_s),
        "output_root": str(args.output_root),
        "max_workers": int(worker_count),
        "elapsed_wall_s": float(time.time() - start_all),
        "variants": list(specs),
        "runtime_results": runtime_df.to_dict(orient="records"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[queue-sweep] wrote {runtime_path}")
    print(f"[queue-sweep] wrote {summary_path}")
    if not long_df.empty:
        print(f"[queue-sweep] wrote {long_path}")
    print(f"[queue-sweep] wrote {report_path}")
    print(f"[queue-sweep] wrote {manifest_path}")


if __name__ == "__main__":
    main()
