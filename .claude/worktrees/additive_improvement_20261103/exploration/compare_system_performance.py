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
from simplification.stages import SIMPLIFICATION_STAGE_ORDER, get_stage


DEFAULT_STAGE_KEYS = (
    "s0_simple_tasks_core",
    "s1_risk_open_core",
    "s5_current_thesis_profile",
)
DEFAULT_VARIANT_KEYS = tuple(EXPLORATION_VARIANTS.keys())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a matched-seed performance comparison across exploratory local-priority "
            "variants and the existing simplification / thesis system lines."
        )
    )
    parser.add_argument("--stage", action="append", dest="stages", choices=SIMPLIFICATION_STAGE_ORDER)
    parser.add_argument("--variant", action="append", dest="variants", choices=variant_names())
    parser.add_argument("--include-default-stages", action="store_true", help="Include the default simplification comparison set.")
    parser.add_argument("--include-all-variants", action="store_true", help="Include every exploration variant.")
    parser.add_argument("--list", action="store_true", help="List known stage and variant targets and exit.")
    parser.add_argument("--num-runs", type=int, default=1, help="Runs per baseline family.")
    parser.add_argument("--seed-start", type=int, default=123, help="First seed for matched-seed comparisons.")
    parser.add_argument("--t-end", type=float, default=3600.0, help="Simulation horizon in seconds.")
    parser.add_argument("--dt", type=float, default=1.0, help="Simulation step in seconds.")
    parser.add_argument("--nx", type=int, default=120, help="SESTPP grid X cells.")
    parser.add_argument("--ny", type=int, default=96, help="SESTPP grid Y cells.")
    parser.add_argument("--time-metrics-period-s", type=float, default=300.0, help="Time-series sampling cadence.")
    parser.add_argument("--output-root", default="results/exploration_compare", help="Directory for comparison outputs.")
    parser.add_argument("--reference-key", default="s5_current_thesis_profile", help="System key used for delta-vs-reference columns.")
    parser.add_argument("--quiet", action="store_true", help="Reduce underlying runner output.")
    parser.add_argument("--max-workers", type=int, default=0, help="0 => auto. Parallelism is across selected systems.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip a system if its comparison.csv already exists.")
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


def _pct_improvement(candidate: float, baseline: float) -> float:
    if (not math.isfinite(candidate)) or (not math.isfinite(baseline)) or baseline == 0.0:
        return float("nan")
    return 100.0 * (baseline - candidate) / baseline


def _pct_change(candidate: float, baseline: float) -> float:
    if (not math.isfinite(candidate)) or (not math.isfinite(baseline)) or baseline == 0.0:
        return float("nan")
    return 100.0 * (candidate - baseline) / baseline


def _first_present(row: pd.Series, candidates: list[str]) -> float:
    for column in candidates:
        if column in row.index:
            value = _safe_float(row.get(column))
            if math.isfinite(value):
                return value
    return float("nan")


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


def _row_by_baseline(df: pd.DataFrame, baseline: str) -> pd.Series:
    rows = df.loc[df["baseline"] == str(baseline)]
    if rows.empty:
        raise ValueError(f"Missing baseline row {baseline!r} in comparison dataframe.")
    return rows.iloc[0]


def _effective_max_workers(requested: int, target_count: int) -> int:
    if target_count <= 1:
        return 1
    if int(requested) > 0:
        return max(1, min(int(requested), int(target_count)))
    cpu = os.cpu_count() or 1
    return max(1, min(int(target_count), int(cpu)))


def _target_output_exists(output_root: Path, system_key: str) -> bool:
    return (output_root / system_key / "comparison.csv").exists()


def _build_summary_row(system_key: str, *, system_kind: str, title: str, comparison_df: pd.DataFrame) -> dict[str, Any]:
    proposed = _row_by_baseline(comparison_df, "proposed")
    prediction = _row_by_baseline(comparison_df, "prediction_only")
    reactive = _row_by_baseline(comparison_df, "reactive")

    comm_col, proposed_comm = _communication_value(proposed)
    _pred_comm_col, prediction_comm = _communication_value(prediction)
    _react_comm_col, reactive_comm = _communication_value(reactive)

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

    proposed_model_completed = _first_present(
        proposed,
        [
            "deterring_actions_completed_model_scored_mean",
            "model_deterring_completed_mean",
            "completed_tasks_total_mean",
        ],
    )
    proposed_model_generated = _first_present(proposed, ["model_deterring_generated_mean"])
    proposed_model_accepted = _first_present(proposed, ["model_deterring_accepted_mean"])

    proposed_total_rejections = _compute_total_planner_rejections(proposed)

    return {
        "system_key": str(system_key),
        "system_kind": str(system_kind),
        "title": str(title),
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
        "proposed_model_generated_mean": proposed_model_generated,
        "proposed_model_accepted_mean": proposed_model_accepted,
        "proposed_model_completed_mean": proposed_model_completed,
        "proposed_total_planner_rejections_mean": proposed_total_rejections,
        "proposed_task_cap_rejections_mean": _safe_float(proposed.get("planner_rejected_task_cap_mean")),
        "proposed_patrol_cap_rejections_mean": _safe_float(proposed.get("planner_rejected_patrol_cap_mean")),
        "proposed_model_cap_rejections_mean": _safe_float(proposed.get("planner_rejected_model_det_cap_mean")),
        "proposed_boundary_message_count_mean": _safe_float(proposed.get("boundary_message_count_mean")),
        "proposed_boundary_bytes_sent_mean": _safe_float(proposed.get("boundary_bytes_sent_mean")),
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
        if smaller_is_better:
            df[rank_col] = metric.rank(method="min", ascending=True)
        else:
            df[rank_col] = metric.rank(method="min", ascending=False)
    rank_cols = [name for (name, _metric, _dir) in rank_specs]
    df["rank_overall_mean"] = df[rank_cols].mean(axis=1, skipna=True)
    df["rank_overall"] = df["rank_overall_mean"].rank(method="min", ascending=True)
    return df


def _apply_reference_deltas(summary_df: pd.DataFrame, reference_key: str) -> pd.DataFrame:
    df = summary_df.copy()
    ref_rows = df.loc[df["system_key"] == str(reference_key)]
    if ref_rows.empty:
        return df
    ref = ref_rows.iloc[0]
    ref_exp = _safe_float(ref.get("proposed_exposure_mean"))
    ref_resp = _safe_float(ref.get("proposed_response_time_mean"))
    ref_birds = _safe_float(ref.get("proposed_birds_deterred_pct_mean"))
    ref_comm = _safe_float(ref.get("proposed_comm_mean"))
    ref_rej = _safe_float(ref.get("proposed_total_planner_rejections_mean"))

    df["reference_key"] = str(reference_key)
    df["delta_vs_reference_exposure_mean"] = pd.to_numeric(df["proposed_exposure_mean"], errors="coerce") - ref_exp
    df["delta_vs_reference_response_time_mean"] = pd.to_numeric(df["proposed_response_time_mean"], errors="coerce") - ref_resp
    df["delta_vs_reference_birds_deterred_pct_pts"] = pd.to_numeric(df["proposed_birds_deterred_pct_mean"], errors="coerce") - ref_birds
    df["delta_vs_reference_comm_mean"] = pd.to_numeric(df["proposed_comm_mean"], errors="coerce") - ref_comm
    df["delta_vs_reference_total_planner_rejections_mean"] = pd.to_numeric(df["proposed_total_planner_rejections_mean"], errors="coerce") - ref_rej
    return df


def _fmt_float(value: Any, digits: int = 2) -> str:
    v = _safe_float(value)
    if not math.isfinite(v):
        return "nan"
    return f"{v:.{digits}f}"


def _render_markdown(summary_df: pd.DataFrame, *, reference_key: str, manifest_rows: list[dict[str, Any]]) -> str:
    def _best_finite(metric_col: str, *, ascending: bool) -> pd.Series | None:
        metric = pd.to_numeric(summary_df.get(metric_col), errors="coerce")
        tmp = summary_df.loc[metric.notna()].copy()
        if tmp.empty:
            return None
        return tmp.sort_values(metric_col, ascending=ascending).iloc[0]

    lines: list[str] = []
    lines.append("# Cross-System Performance Comparison")
    lines.append("")
    lines.append("Systems were run on matched seeds and summarized using the proposed baseline plus its paired gains over `prediction_only` and `reactive`.")
    lines.append("")

    if not summary_df.empty:
        best_exposure = _best_finite("proposed_exposure_mean", ascending=True)
        best_response = _best_finite("proposed_response_time_mean", ascending=True)
        best_birds = _best_finite("proposed_birds_deterred_pct_mean", ascending=False)
        best_overall = summary_df.sort_values("rank_overall_mean", ascending=True).iloc[0]
        lines.append("## Highlights")
        lines.append("")
        if best_exposure is not None:
            lines.append(
                f"- Best exposure: `{best_exposure['system_key']}` at `{_fmt_float(best_exposure.get('proposed_exposure_mean'))}` "
                f"with `{_fmt_float(best_exposure.get('proposed_vs_reactive_exposure_improve_pct'))}%` vs reactive."
            )
        if best_response is not None:
            lines.append(
                f"- Best response time: `{best_response['system_key']}` at `{_fmt_float(best_response.get('proposed_response_time_mean'))} s`."
            )
        if best_birds is not None:
            lines.append(
                f"- Best {_bird_metric_label(_safe_text(best_birds.get('bird_metric_column'))).lower()}: "
                f"`{best_birds['system_key']}` at `{_fmt_float(best_birds.get('proposed_birds_deterred_pct_mean'))}%`."
            )
        lines.append(
            f"- Best balanced rank: `{best_overall['system_key']}` with overall rank `{_fmt_float(best_overall.get('rank_overall_mean'))}`."
        )
        lines.append("")

    lines.append("## Systems")
    lines.append("")
    for _, row in summary_df.sort_values(["rank_overall_mean", "proposed_exposure_mean"], ascending=[True, True]).iterrows():
        lines.append(f"### {row['system_key']}: {row['title']}")
        lines.append(
            f"- Exposure: `{_fmt_float(row.get('proposed_exposure_mean'))}` "
            f"(vs prediction `{_fmt_float(row.get('proposed_vs_prediction_exposure_improve_pct'))}%`, "
            f"vs reactive `{_fmt_float(row.get('proposed_vs_reactive_exposure_improve_pct'))}%`)."
        )
        lines.append(
            f"- Response time: `{_fmt_float(row.get('proposed_response_time_mean'))} s` "
            f"(vs reactive `{_fmt_float(row.get('proposed_vs_reactive_response_improve_pct'))}%`)."
        )
        lines.append(
            f"- {_bird_metric_label(_safe_text(row.get('bird_metric_column')))}: "
            f"`{_fmt_float(row.get('proposed_birds_deterred_pct_mean'))}%` "
            f"(delta vs reactive `{_fmt_float(row.get('proposed_minus_reactive_birds_deterred_pct_pts'))}` pts)."
        )
        lines.append(
            f"- Communication: `{_fmt_float(row.get('proposed_comm_mean'))}` via `{row.get('comm_reference_column')}`."
        )
        lines.append(
            f"- Preventive completions / planner rejections: "
            f"`{_fmt_float(row.get('proposed_model_completed_mean'))}` / "
            f"`{_fmt_float(row.get('proposed_total_planner_rejections_mean'))}`."
        )
        if row.get("reference_key") == reference_key:
            lines.append(
                f"- Delta vs reference `{reference_key}`: exposure `{_fmt_float(row.get('delta_vs_reference_exposure_mean'))}`, "
                f"response `{_fmt_float(row.get('delta_vs_reference_response_time_mean'))} s`, "
                f"{_bird_metric_label(_safe_text(row.get('bird_metric_column'))).lower()} "
                f"`{_fmt_float(row.get('delta_vs_reference_birds_deterred_pct_pts'))}` pts."
            )
        lines.append("")

    lines.append("## Manifest")
    lines.append("")
    for payload in manifest_rows:
        lines.append(f"- `{payload['system_key']}`: kind=`{payload['system_kind']}` output=`{payload['output_dir']}`")
    lines.append("")
    return "\n".join(lines)


def _target_title(system_kind: str, system_key: str) -> str:
    if str(system_kind) == "simplification_stage":
        return str(get_stage(system_key).title)
    if str(system_kind) == "exploration_variant":
        return str(EXPLORATION_VARIANTS[system_key]["title"])
    return str(system_key)


def _worker_entry(payload: dict[str, Any]) -> dict[str, Any]:
    system_key = str(payload["system_key"])
    system_kind = str(payload["system_kind"])
    output_root = Path(str(payload["output_root"]))
    output_dir = output_root / system_key
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "worker_stdout.log"
    stderr_path = output_dir / "worker_stderr.log"
    start = time.time()
    try:
        if bool(payload.get("skip_existing")) and _target_output_exists(output_root, system_key):
            return {
                "system_key": system_key,
                "system_kind": system_kind,
                "status": "skipped",
                "duration_s": 0.0,
                "output_dir": str(output_dir),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }

        if system_kind == "simplification_stage":
            cmd = [
                sys.executable,
                "-m",
                "simplification.run_stage",
                "--stage",
                system_key,
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
            ]
            if bool(payload.get("quiet")):
                cmd.append("--quiet")
        elif system_kind == "exploration_variant":
            cmd = [
                sys.executable,
                "-m",
                "exploration.run_variant",
                "--variant",
                system_key,
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
            ]
            if bool(payload.get("quiet")):
                cmd.append("--quiet")
        else:
            raise ValueError(f"Unknown system kind: {system_kind!r}")

        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"Worker subprocess failed with exit code {completed.returncode}. See {stderr_path}."
            )

        return {
            "system_key": system_key,
            "system_kind": system_kind,
            "status": "ok",
            "duration_s": float(time.time() - start),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    except Exception as exc:
        return {
            "system_key": system_key,
            "system_kind": system_kind,
            "status": "failed",
            "duration_s": float(time.time() - start),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }


def _summarize_completed_target(system_key: str, system_kind: str, output_root: Path) -> dict[str, Any]:
    comparison_csv = output_root / system_key / "comparison.csv"
    if not comparison_csv.exists():
        raise FileNotFoundError(f"Missing comparison output for {system_key!r}: {comparison_csv}")
    comparison_df = pd.read_csv(comparison_csv)
    summary = _build_summary_row(
        system_key,
        system_kind=system_kind,
        title=_target_title(system_kind, system_key),
        comparison_df=comparison_df,
    )
    return {
        "system_key": system_key,
        "system_kind": system_kind,
        "title": _target_title(system_kind, system_key),
        "output_dir": str(output_root / system_key),
        "comparison_csv": str(comparison_csv),
        "summary": summary,
    }


def _print_targets() -> None:
    print("Simplification stages:")
    for key in DEFAULT_STAGE_KEYS:
        stage = get_stage(key)
        print(f"  {key}: {stage.title}")
    print("Exploration variants:")
    for key, payload in EXPLORATION_VARIANTS.items():
        print(f"  {key}: {payload['title']}")


def _selected_targets(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    if args.list:
        _print_targets()
        raise SystemExit(0)

    stages: list[str] = []
    variants: list[str] = []
    if args.include_default_stages or (not args.stages and not args.variants and not args.include_all_variants):
        stages.extend(DEFAULT_STAGE_KEYS)
    if args.include_all_variants or (not args.stages and not args.variants):
        variants.extend(DEFAULT_VARIANT_KEYS)
    stages.extend(args.stages or [])
    variants.extend(args.variants or [])

    dedup_stages = []
    for key in stages:
        if key not in dedup_stages:
            dedup_stages.append(key)
    dedup_variants = []
    for key in variants:
        if key not in dedup_variants:
            dedup_variants.append(key)
    return dedup_stages, dedup_variants


def main() -> None:
    args = _parser().parse_args()
    stages, variants = _selected_targets(args)

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    targets = (
        [{"system_key": key, "system_kind": "simplification_stage"} for key in stages]
        + [{"system_key": key, "system_kind": "exploration_variant"} for key in variants]
    )
    if not targets:
        raise ValueError("No systems were selected for comparison.")

    worker_count = _effective_max_workers(int(args.max_workers), len(targets))
    if not bool(args.quiet):
        print(f"[system-compare] running {len(targets)} systems with max_workers={worker_count}")

    payloads = [
        {
            "system_key": target["system_key"],
            "system_kind": target["system_kind"],
            "num_runs": int(args.num_runs),
            "seed_start": int(args.seed_start),
            "t_end": float(args.t_end),
            "dt": float(args.dt),
            "nx": int(args.nx),
            "ny": int(args.ny),
            "time_metrics_period_s": float(args.time_metrics_period_s),
            "output_root": str(output_root),
            "quiet": bool(args.quiet),
            "skip_existing": bool(args.skip_existing),
        }
        for target in targets
    ]

    runtime_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {
            pool.submit(_worker_entry, payload): (payload["system_key"], payload["system_kind"])
            for payload in payloads
        }
        completed = 0
        for future in as_completed(future_map):
            completed += 1
            system_key, system_kind = future_map[future]
            result = future.result()
            runtime_results.append(result)
            if not bool(args.quiet):
                print(
                    f"[system-compare] completed {completed}/{len(payloads)} "
                    f"system={system_key} kind={system_kind} "
                    f"status={result.get('status')} duration_s={_fmt_float(result.get('duration_s'))}"
                )

    failed = [row for row in runtime_results if str(row.get("status")) == "failed"]
    if failed:
        runtime_path = output_root / "system_comparison_runtime.csv"
        pd.DataFrame(runtime_results).to_csv(runtime_path, index=False)
        failed_keys = ", ".join(str(row.get("system_key")) for row in failed)
        raise RuntimeError(f"Comparison workers failed for: {failed_keys}. See {runtime_path} and worker logs.")

    manifest_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for target in targets:
        out = _summarize_completed_target(
            system_key=str(target["system_key"]),
            system_kind=str(target["system_kind"]),
            output_root=output_root,
        )
        manifest_rows.append({k: out[k] for k in ("system_key", "system_kind", "title", "output_dir", "comparison_csv")})
        summary_rows.append(dict(out["summary"]))

    summary_df = pd.DataFrame(summary_rows)
    if summary_df.empty:
        raise ValueError("No systems were selected for comparison.")

    summary_df = _assign_ranks(summary_df)
    summary_df = _apply_reference_deltas(summary_df, str(args.reference_key))
    summary_df = summary_df.sort_values(["rank_overall_mean", "proposed_exposure_mean"], ascending=[True, True]).reset_index(drop=True)

    summary_csv = output_root / "system_comparison_summary.csv"
    summary_df.to_csv(summary_csv, index=False)
    runtime_csv = output_root / "system_comparison_runtime.csv"
    pd.DataFrame(runtime_results).to_csv(runtime_csv, index=False)
    manifest_path = output_root / "system_comparison_manifest.json"
    manifest_path.write_text(json.dumps(manifest_rows, indent=2), encoding="utf-8")
    md_path = output_root / "system_comparison.md"
    md_path.write_text(
        _render_markdown(summary_df, reference_key=str(args.reference_key), manifest_rows=manifest_rows),
        encoding="utf-8",
    )

    if not bool(args.quiet):
        print(f"[system-compare] wrote {summary_csv}")
        print(f"[system-compare] wrote {runtime_csv}")
        print(f"[system-compare] wrote {md_path}")


if __name__ == "__main__":
    main()
