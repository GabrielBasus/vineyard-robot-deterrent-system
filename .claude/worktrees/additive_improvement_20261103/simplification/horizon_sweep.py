from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any

import numpy as np
import pandas as pd

from .stages import SIMPLIFICATION_STAGE_ORDER, iter_stages


_DEFAULT_STAGE_KEYS = (
    "s1_risk_open_core",
    "s5_current_thesis_profile",
)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Run a matched-seed simplification sweep across multiple simulation horizons. "
            "This is the main comparison runner for checking whether exposure wins, "
            "bird-deterrence percentage, preventive yield, and communication hold up "
            "as the horizon grows."
        )
    )
    p.add_argument(
        "--stage",
        action="append",
        dest="stages",
        help="Simplification stage key. Repeat to compare multiple stages.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List available stages and exit.",
    )
    p.add_argument(
        "--time-horizons-h",
        default="2,4,6",
        help="Comma-separated simulation horizons in hours.",
    )
    p.add_argument("--num-runs", type=int, default=3, help="Runs per baseline family.")
    p.add_argument("--seed-start", type=int, default=123, help="First seed for the baseline sweep.")
    p.add_argument("--dt", type=float, default=1.0, help="Simulation step in seconds.")
    p.add_argument("--nx", type=int, default=120, help="SESTPP grid X cells.")
    p.add_argument("--ny", type=int, default=96, help="SESTPP grid Y cells.")
    p.add_argument(
        "--time-metrics-period-s",
        type=float,
        default=300.0,
        help="Sample period for over-time metrics during baseline runs.",
    )
    p.add_argument(
        "--output-root",
        default="results/simplification/horizon_sweep",
        help="Directory where horizon-sweep outputs will be written.",
    )
    p.add_argument(
        "--main-stage",
        default="s5_current_thesis_profile",
        help="Stage key to treat as the current/main reference in the report.",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=0,
        help="0 => auto. Parallelism is across stage x horizon jobs.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip a job if its comparison.csv and stage manifest already exist.",
    )
    p.add_argument(
        "--verbose-stage-logs",
        action="store_true",
        help="Allow baseline logs from worker processes.",
    )
    return p


def _print_stage_list() -> None:
    for stage in iter_stages():
        print(f"{stage.key}: {stage.title}")
        print(f"  module={stage.module_name}")
        print(f"  {stage.description}")


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


def _fmt_float(value: Any, digits: int = 3) -> str:
    val = _safe_float(value)
    if not np.isfinite(val):
        return "nan"
    return f"{val:.{digits}f}"


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


def _stage_keys_from_args(args: argparse.Namespace) -> tuple[str, ...]:
    if args.stages:
        return tuple(args.stages)
    return _DEFAULT_STAGE_KEYS


def _effective_max_workers(requested: int, job_count: int) -> int:
    if job_count <= 1:
        return 1
    if int(requested) > 0:
        return max(1, min(int(requested), int(job_count)))
    cpu = os.cpu_count() or 1
    return max(1, min(int(job_count), int(cpu)))


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


def _slug_num(value: float) -> str:
    text = f"{float(value):.6g}"
    return text.replace("-", "m").replace("+", "").replace(".", "p")


def _job_output_name(stage_key: str, horizon_h: float) -> str:
    return f"{stage_key}__h_{_slug_num(horizon_h)}"


def _job_output_exists(output_root: str, output_name: str) -> bool:
    output_dir = Path(output_root) / output_name
    return (output_dir / "comparison.csv").exists() and (output_dir / "stage_manifest.json").exists()


def _worker_entry(payload: dict[str, Any]) -> dict[str, Any]:
    output_name = str(payload["output_name"])
    output_dir = Path(payload["output_root"]) / output_name
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "horizon_sweep_stdout.log"
    stderr_path = output_dir / "horizon_sweep_stderr.log"
    start = time.time()
    try:
        if bool(payload.get("skip_existing")) and _job_output_exists(str(payload["output_root"]), output_name):
            return {
                "stage_key": str(payload["stage_key"]),
                "horizon_h": float(payload["horizon_h"]),
                "output_name": output_name,
                "status": "skipped",
                "duration_s": 0.0,
                "output_dir": str(output_dir),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }

        cmd = [
            sys.executable,
            "-m",
            "simplification.run_stage",
            "--stage",
            str(payload["stage_key"]),
            "--num-runs",
            str(int(payload["num_runs"])),
            "--seed-start",
            str(int(payload["seed_start"])),
            "--t-end",
            str(float(payload["horizon_h"]) * 3600.0),
            "--dt",
            str(float(payload["dt"])),
            "--nx",
            str(int(payload["nx"])),
            "--ny",
            str(int(payload["ny"])),
            "--time-metrics-period-s",
            str(float(payload["time_metrics_period_s"])),
            "--output-root",
            str(payload["output_root"]),
            "--label",
            output_name,
        ]
        if not bool(payload.get("verbose_stage_logs")):
            cmd.append("--quiet")

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"Horizon sweep subprocess failed with exit code {completed.returncode}. "
                f"See {stderr_path}."
            )
        return {
            "stage_key": str(payload["stage_key"]),
            "horizon_h": float(payload["horizon_h"]),
            "output_name": output_name,
            "status": "ok",
            "duration_s": float(time.time() - start),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    except Exception as exc:
        return {
            "stage_key": str(payload["stage_key"]),
            "horizon_h": float(payload["horizon_h"]),
            "output_name": output_name,
            "status": "failed",
            "duration_s": float(time.time() - start),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


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


def _build_summary_row(output_root: Path, output_name: str) -> tuple[dict[str, Any], pd.DataFrame]:
    output_dir = output_root / output_name
    manifest = _load_manifest(output_dir / "stage_manifest.json")
    comparison_df = _load_csv(output_dir / "comparison.csv")
    if comparison_df.empty:
        raise FileNotFoundError(f"Missing or empty comparison.csv for {output_name!r} at {output_dir}")

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
        "output_name": str(output_name),
        "stage_key": _safe_text(stage_info.get("key")),
        "stage_title": _safe_text(stage_info.get("title")),
        "module_name": _safe_text(stage_info.get("module_name")),
        "description": _safe_text(stage_info.get("description")),
        "planner_profile": _safe_text(sim_kwargs.get("planner_profile")),
        "preventive_policy": _column_or_text(comparison_df, "proposed", "preventive_policy"),
        "preventive_policy_source": _column_or_text(comparison_df, "proposed", "preventive_policy_source"),
        "num_runs": int(runner_args.get("num_runs", 0)),
        "seed_start": int(runner_args.get("seed_start", 0)),
        "horizon_h": float(runner_args.get("t_end", 0.0)) / 3600.0,
        "t_end_s": _safe_float(runner_args.get("t_end")),
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
        "proposed_truth_suppression_rate_mean": _column_or_nan(comparison_df, "proposed", "truth_suppression_rate_mean"),
        "proposed_model_candidates_mean": _column_or_nan(comparison_df, "proposed", "model_deterring_candidates_total_mean"),
        "proposed_model_generated_mean": _column_or_nan(comparison_df, "proposed", "model_deterring_generated_mean"),
        "proposed_model_accepted_mean": _column_or_nan(comparison_df, "proposed", "model_deterring_accepted_mean"),
        "proposed_model_completed_mean": _column_or_nan(comparison_df, "proposed", "deterring_actions_completed_model_scored_mean"),
        "proposed_total_planner_rejections_mean": _planner_rejection_total_proposed(comparison_df),
    }

    comparison_df = comparison_df.copy()
    comparison_df.insert(0, "output_name", str(output_name))
    comparison_df.insert(1, "stage_key", row["stage_key"])
    comparison_df.insert(2, "stage_title", row["stage_title"])
    comparison_df.insert(3, "horizon_h", float(row["horizon_h"]))
    return row, comparison_df


def _best_row(df: pd.DataFrame, column: str, *, larger_is_better: bool = True) -> pd.Series | None:
    if df.empty or column not in df.columns:
        return None
    tmp = df.copy()
    tmp[column] = pd.to_numeric(tmp[column], errors="coerce")
    tmp = tmp[np.isfinite(tmp[column])]
    if tmp.empty:
        return None
    idx = tmp[column].idxmax() if larger_is_better else tmp[column].idxmin()
    return tmp.loc[idx]


def _trend_delta(df: pd.DataFrame, value_col: str) -> float:
    if df.empty or value_col not in df.columns or "horizon_h" not in df.columns:
        return float("nan")
    tmp = df.copy()
    tmp["horizon_h"] = pd.to_numeric(tmp["horizon_h"], errors="coerce")
    tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce")
    tmp = tmp[np.isfinite(tmp["horizon_h"]) & np.isfinite(tmp[value_col])].sort_values("horizon_h")
    if len(tmp) < 2:
        return float("nan")
    return float(tmp.iloc[-1][value_col] - tmp.iloc[0][value_col])


def _render_report(summary_df: pd.DataFrame, runtime_df: pd.DataFrame, *, main_stage_key: str, worker_count: int, args: argparse.Namespace) -> str:
    lines = [
        "# Simplification Horizon Sweep",
        "",
        f"- Stages: {', '.join(sorted({str(v) for v in summary_df['stage_key'].tolist()}))}",
        f"- Horizons [h]: {', '.join(_fmt_float(v, 3) for v in sorted({float(v) for v in summary_df['horizon_h'].tolist()}))}",
        f"- Main/current reference stage: `{main_stage_key}`",
        f"- Runs per baseline: `{int(args.num_runs)}`",
        f"- Max workers: `{int(worker_count)}`",
        "",
        "## Runtime",
        "",
        "```text",
    ]
    runtime_cols = [c for c in ["stage_key", "horizon_h", "status", "duration_s"] if c in runtime_df.columns]
    if runtime_cols:
        lines.append(runtime_df[runtime_cols].to_string(index=False))
    else:
        lines.append("No runtime rows.")
    lines.extend(["```", "", "## Horizon Summary", "", "```text"])
    keep_cols = [
        "stage_key",
        "horizon_h",
        "proposed_vs_prediction_exposure_improve_pct",
        "proposed_vs_reactive_exposure_improve_pct",
        "proposed_birds_deterred_pct_mean",
        "proposed_minus_prediction_birds_deterred_pct_pts",
        "proposed_minus_reactive_birds_deterred_pct_pts",
        "proposed_model_completed_mean",
        "proposed_total_planner_rejections_mean",
    ]
    lines.append(summary_df[[c for c in keep_cols if c in summary_df.columns]].to_string(index=False))
    lines.extend(["```", "", "## Findings", ""])

    for horizon_h in sorted({float(v) for v in summary_df["horizon_h"].tolist()}):
        horizon_df = summary_df.loc[np.isclose(summary_df["horizon_h"], float(horizon_h))].copy()
        best_exp = _best_row(horizon_df, "proposed_vs_prediction_exposure_improve_pct", larger_is_better=True)
        best_birds = _best_row(horizon_df, "proposed_birds_deterred_pct_mean", larger_is_better=True)
        if best_exp is not None:
            lines.append(
                f"- At `{_fmt_float(horizon_h, 2)} h`, best exposure vs prediction: "
                f"`{best_exp['stage_key']}` ({_fmt_float(best_exp.get('proposed_vs_prediction_exposure_improve_pct'))}%)."
            )
        if best_birds is not None:
            lines.append(
                f"- At `{_fmt_float(horizon_h, 2)} h`, highest "
                f"{_bird_metric_label(_safe_text(best_birds.get('bird_metric_column')))}: "
                f"`{best_birds['stage_key']}` ({_fmt_float(best_birds.get('proposed_birds_deterred_pct_mean'))}%)."
            )

    lines.extend(["", "## Stage Trends", ""])
    for stage_key in summary_df["stage_key"].drop_duplicates().tolist():
        stage_df = summary_df.loc[summary_df["stage_key"] == stage_key].copy().sort_values("horizon_h")
        exp_delta = _trend_delta(stage_df, "proposed_vs_prediction_exposure_improve_pct")
        birds_delta = _trend_delta(stage_df, "proposed_birds_deterred_pct_mean")
        lines.append(
            f"- `{stage_key}`: "
            f"delta exposure vs prediction from shortest to longest horizon = {_fmt_float(exp_delta)} pts; "
            f"delta {_bird_metric_label(_safe_text(stage_df.iloc[0].get('bird_metric_column')))} = {_fmt_float(birds_delta)} pts."
        )

    lines.extend(["", "## Recommendation", ""])
    main_df = summary_df.loc[summary_df["stage_key"] == str(main_stage_key)].copy().sort_values("horizon_h")
    best_overall = _best_row(summary_df, "proposed_vs_prediction_exposure_improve_pct", larger_is_better=True)
    if best_overall is not None and str(best_overall.get("stage_key")) != str(main_stage_key):
        lines.append(
            f"1. Use `{best_overall['stage_key']}` as the next reference if the goal is horizon-robust exposure gain. "
            f"Its best observed horizon is `{_fmt_float(best_overall.get('horizon_h'), 2)} h` with "
            f"`{_fmt_float(best_overall.get('proposed_vs_prediction_exposure_improve_pct'))}%` exposure improvement vs prediction."
        )
    if not main_df.empty:
        lines.append(
            f"1. Keep checking `{main_stage_key}` across longer horizons only if its birds-deterred percentage or exposure trend improves materially. "
            f"Current shortest-to-longest exposure delta is `{_fmt_float(_trend_delta(main_df, 'proposed_vs_prediction_exposure_improve_pct'))}` pts."
        )
    lines.append(
        "1. Compare methods using the paired set of metrics: exposure, response time, last-hour bird deterrence, communication, and preventive completions. "
        "Do not choose a method based on the bird-deterrence metric alone."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parser().parse_args()
    if args.list:
        _print_stage_list()
        return

    stage_keys = _stage_keys_from_args(args)
    horizons_h = tuple(sorted(_parse_float_list(args.time_horizons_h)))
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    stage_set = {stage.key for stage in iter_stages()}
    unknown = [key for key in stage_keys if key not in stage_set]
    if unknown:
        raise ValueError(f"Unknown stage key(s): {', '.join(unknown)}")
    if str(args.main_stage) not in stage_set:
        raise ValueError(f"Unknown --main-stage: {args.main_stage!r}")

    jobs = []
    for stage_key in stage_keys:
        for horizon_h in horizons_h:
            jobs.append(
                {
                    "stage_key": str(stage_key),
                    "horizon_h": float(horizon_h),
                    "output_name": _job_output_name(str(stage_key), float(horizon_h)),
                    "output_root": str(output_root),
                    "num_runs": int(args.num_runs),
                    "seed_start": int(args.seed_start),
                    "dt": float(args.dt),
                    "nx": int(args.nx),
                    "ny": int(args.ny),
                    "time_metrics_period_s": float(args.time_metrics_period_s),
                    "skip_existing": bool(args.skip_existing),
                    "verbose_stage_logs": bool(args.verbose_stage_logs),
                }
            )

    worker_count = _effective_max_workers(int(args.max_workers), len(jobs))
    wall_start = time.time()
    runtime_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    baseline_frames: list[pd.DataFrame] = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {executor.submit(_worker_entry, job): job for job in jobs}
        for future in as_completed(future_map):
            result = future.result()
            runtime_rows.append(result)

    runtime_df = pd.DataFrame(runtime_rows)
    if not runtime_df.empty:
        runtime_df["horizon_h"] = pd.to_numeric(runtime_df.get("horizon_h"), errors="coerce")
        runtime_df["duration_s"] = pd.to_numeric(runtime_df.get("duration_s"), errors="coerce")
        stage_rank = {key: idx for idx, key in enumerate(SIMPLIFICATION_STAGE_ORDER)}
        runtime_df["_stage_rank"] = runtime_df["stage_key"].map(stage_rank).fillna(len(stage_rank))
        runtime_df = runtime_df.sort_values(["_stage_rank", "horizon_h", "stage_key"]).drop(columns=["_stage_rank"])

    for row in runtime_rows:
        if str(row.get("status")) not in {"ok", "skipped"}:
            continue
        output_name = str(row["output_name"])
        summary_row, baseline_df = _build_summary_row(output_root, output_name)
        summary_rows.append(summary_row)
        baseline_frames.append(baseline_df)

    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        stage_rank = {key: idx for idx, key in enumerate(SIMPLIFICATION_STAGE_ORDER)}
        summary_df["horizon_h"] = pd.to_numeric(summary_df["horizon_h"], errors="coerce")
        summary_df["_stage_rank"] = summary_df["stage_key"].map(stage_rank).fillna(len(stage_rank))
        summary_df = summary_df.sort_values(["_stage_rank", "horizon_h", "stage_key"]).drop(columns=["_stage_rank"])

    baseline_long_df = pd.concat(baseline_frames, ignore_index=True) if baseline_frames else pd.DataFrame()
    if not baseline_long_df.empty:
        stage_rank = {key: idx for idx, key in enumerate(SIMPLIFICATION_STAGE_ORDER)}
        baseline_long_df["horizon_h"] = pd.to_numeric(baseline_long_df["horizon_h"], errors="coerce")
        baseline_long_df["_stage_rank"] = baseline_long_df["stage_key"].map(stage_rank).fillna(len(stage_rank))
        baseline_long_df = baseline_long_df.sort_values(["_stage_rank", "horizon_h", "baseline"]).drop(columns=["_stage_rank"])

    manifest = {
        "generated_at_unix_s": float(time.time()),
        "elapsed_wall_s": float(time.time() - wall_start),
        "stage_keys": list(stage_keys),
        "time_horizons_h": [float(v) for v in horizons_h],
        "num_runs": int(args.num_runs),
        "seed_start": int(args.seed_start),
        "dt": float(args.dt),
        "nx": int(args.nx),
        "ny": int(args.ny),
        "time_metrics_period_s": float(args.time_metrics_period_s),
        "output_root": str(output_root),
        "main_stage": str(args.main_stage),
        "max_workers": int(worker_count),
        "skip_existing": bool(args.skip_existing),
        "verbose_stage_logs": bool(args.verbose_stage_logs),
        "runtime_rows": runtime_rows,
    }

    runtime_path = output_root / "horizon_sweep_runtime.csv"
    summary_path = output_root / "horizon_sweep_summary.csv"
    baseline_long_path = output_root / "horizon_sweep_baseline_long.csv"
    manifest_path = output_root / "horizon_sweep_manifest.json"
    report_path = output_root / "horizon_sweep.md"

    runtime_df.to_csv(runtime_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    baseline_long_df.to_csv(baseline_long_path, index=False)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report_text = _render_report(
        summary_df=summary_df,
        runtime_df=runtime_df,
        main_stage_key=str(args.main_stage),
        worker_count=worker_count,
        args=args,
    )
    report_path.write_text(report_text, encoding="utf-8")

    print(f"Wrote {runtime_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {baseline_long_path}")
    print(f"Wrote {manifest_path}")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
