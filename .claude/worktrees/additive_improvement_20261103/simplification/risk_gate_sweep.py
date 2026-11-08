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


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Sweep the preventive heuristic risk gate controls on top of a base "
            "simplification stage. Variants are run in parallel and summarized to show "
            "whether risk-threshold / risk-scale changes let preventive candidates "
            "become generated, accepted, or completed tasks."
        )
    )
    p.add_argument("--base-stage", default="s1_main_core", help="Base simplification stage to perturb.")
    p.add_argument(
        "--threshold-values",
        default="0.0,0.05,0.10,0.20,0.35",
        help="Comma-separated heuristic risk-threshold values to test.",
    )
    p.add_argument(
        "--scale-values",
        default="1e-4,2e-4,5e-4,1e-3",
        help="Comma-separated heuristic risk-scale values to test.",
    )
    p.add_argument(
        "--cross-product",
        action="store_true",
        help="Evaluate the full threshold x scale grid instead of one-at-a-time sweeps around the current defaults.",
    )
    p.add_argument(
        "--no-current",
        action="store_false",
        dest="include_current",
        help="Do not include the current/base risk setting as an explicit reference variant.",
    )
    p.set_defaults(include_current=True)
    p.add_argument(
        "--current-risk-threshold",
        type=float,
        default=0.35,
        help="Current/default heuristic risk threshold used as the reference value.",
    )
    p.add_argument(
        "--current-risk-scale",
        type=float,
        default=1e-4,
        help="Current/default heuristic risk scale used as the reference value.",
    )
    p.add_argument("--num-runs", type=int, default=3, help="Runs per baseline family.")
    p.add_argument("--seed-start", type=int, default=123, help="First seed for the baseline sweep.")
    p.add_argument("--t-end", type=float, default=3600.0, help="Simulation horizon in seconds.")
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
        default="results/simplification/risk_gate_sweep",
        help="Directory where risk-gate sweep outputs will be written.",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=0,
        help="0 => auto. Parallelism is across risk-gate variants.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip a variant if its comparison.csv and stage manifest already exist.",
    )
    p.add_argument(
        "--verbose-variant-logs",
        action="store_true",
        help="Do not pass --quiet to the stage subprocesses.",
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


def _slug_num(value: float) -> str:
    text = f"{float(value):.6g}"
    return (
        text.replace("-", "m")
        .replace("+", "")
        .replace(".", "p")
    )


def _variant_output_name(base_stage: str, threshold: float, scale: float) -> str:
    return f"{base_stage}__thr_{_slug_num(threshold)}__scale_{_slug_num(scale)}"


def _variant_specs(args: argparse.Namespace) -> tuple[dict[str, Any], ...]:
    thresholds = _parse_float_list(args.threshold_values)
    scales = _parse_float_list(args.scale_values)
    base_thr = float(args.current_risk_threshold)
    base_scale = float(args.current_risk_scale)

    seen: set[tuple[float, float]] = set()
    specs: list[dict[str, Any]] = []

    def add_variant(threshold: float, scale: float, variant_kind: str) -> None:
        key = (float(threshold), float(scale))
        if key in seen:
            return
        seen.add(key)
        specs.append(
            {
                "variant_kind": str(variant_kind),
                "risk_threshold": float(threshold),
                "risk_scale": float(scale),
                "output_name": _variant_output_name(str(args.base_stage), float(threshold), float(scale)),
            }
        )

    if bool(args.include_current):
        add_variant(base_thr, base_scale, "current")

    if bool(args.cross_product):
        for thr in thresholds:
            for scale in scales:
                add_variant(float(thr), float(scale), "grid")
    else:
        for thr in thresholds:
            add_variant(float(thr), base_scale, "threshold")
        for scale in scales:
            add_variant(base_thr, float(scale), "scale")

    return tuple(specs)


def _effective_max_workers(requested: int, count: int) -> int:
    if count <= 1:
        return 1
    if int(requested) > 0:
        return max(1, min(int(requested), int(count)))
    cpu = os.cpu_count() or 1
    return max(1, min(int(count), int(cpu)))


def _variant_output_exists(output_root: str, output_name: str) -> bool:
    output_dir = Path(output_root) / output_name
    return (output_dir / "comparison.csv").exists() and (output_dir / "stage_manifest.json").exists()


def _worker_entry(payload: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(payload["output_root"]) / str(payload["output_name"])
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "risk_gate_worker_stdout.log"
    stderr_path = output_dir / "risk_gate_worker_stderr.log"
    start = time.time()
    try:
        if bool(payload.get("skip_existing")) and _variant_output_exists(str(payload["output_root"]), str(payload["output_name"])):
            return {
                "output_name": str(payload["output_name"]),
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
            str(payload["base_stage"]),
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
            str(payload["output_root"]),
            "--label",
            str(payload["output_name"]),
            "--set",
            f"model_deterring_risk_threshold={float(payload['risk_threshold'])}",
            "--set",
            f"model_deterring_risk_scale={float(payload['risk_scale'])}",
        ]
        if not bool(payload["verbose_variant_logs"]):
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
                f"Variant subprocess failed with exit code {completed.returncode}. "
                f"See {stderr_path}."
            )
        return {
            "output_name": str(payload["output_name"]),
            "status": "ok",
            "duration_s": float(time.time() - start),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    except Exception as exc:
        return {
            "output_name": str(payload["output_name"]),
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


def _row_value(df: pd.DataFrame, baseline: str, column: str) -> float:
    if column not in df.columns:
        return float("nan")
    rows = df.loc[df["baseline"] == baseline, column]
    if rows.empty:
        return float("nan")
    return _safe_float(rows.iloc[0])


def _row_text(df: pd.DataFrame, baseline: str, column: str) -> str:
    if column not in df.columns:
        return ""
    rows = df.loc[df["baseline"] == baseline, column]
    if rows.empty:
        return ""
    return _safe_text(rows.iloc[0])


def _build_variant_summary(output_root: Path, output_name: str) -> tuple[dict[str, Any], pd.DataFrame]:
    output_dir = output_root / output_name
    manifest = _load_manifest(output_dir / "stage_manifest.json")
    comparison_df = _load_csv(output_dir / "comparison.csv")
    if comparison_df.empty:
        raise FileNotFoundError(f"Missing or empty comparison.csv for variant {output_name!r} at {output_dir}")

    stage = manifest.get("stage", {})
    sim_kwargs = manifest.get("sim_kwargs", {})
    risk_threshold = _safe_float(sim_kwargs.get("model_deterring_risk_threshold"))
    risk_scale = _safe_float(sim_kwargs.get("model_deterring_risk_scale"))

    exp_prop = _row_value(comparison_df, "proposed", "value_weighted_exposure_mean")
    exp_pred = _row_value(comparison_df, "prediction_only", "value_weighted_exposure_mean")
    exp_react = _row_value(comparison_df, "reactive", "value_weighted_exposure_mean")
    resp_prop = _row_value(comparison_df, "proposed", "mean_response_time_s_mean")
    resp_pred = _row_value(comparison_df, "prediction_only", "mean_response_time_s_mean")
    resp_react = _row_value(comparison_df, "reactive", "mean_response_time_s_mean")
    comm_prop = _row_value(comparison_df, "proposed", "boundary_bytes_sent_mean")
    comm_pred = _row_value(comparison_df, "prediction_only", "boundary_bytes_sent_mean")
    comm_react = _row_value(comparison_df, "reactive", "boundary_bytes_sent_mean")

    candidates = _row_value(comparison_df, "proposed", "model_deterring_candidates_total_mean")
    pass_field = _row_value(comparison_df, "proposed", "model_deterring_pass_field_mean")
    rejected_risk = _row_value(comparison_df, "proposed", "model_deterring_rejected_risk_mean")
    pass_risk = _row_value(comparison_df, "proposed", "model_deterring_pass_risk_mean")
    rejected_busy = _row_value(comparison_df, "proposed", "model_deterring_rejected_busy_mean")
    rejected_eta = _row_value(comparison_df, "proposed", "model_deterring_rejected_eta_mean")
    rejected_support = _row_value(comparison_df, "proposed", "model_deterring_rejected_support_mean")
    rejected_persistence = _row_value(comparison_df, "proposed", "model_deterring_rejected_persistence_mean")
    not_selected = _row_value(comparison_df, "proposed", "model_deterring_not_selected_mean")
    generated = _row_value(comparison_df, "proposed", "model_deterring_generated_mean")
    accepted = _row_value(comparison_df, "proposed", "model_deterring_accepted_mean")
    completed = _row_value(comparison_df, "proposed", "deterring_actions_completed_model_scored_mean")
    planner_task_cap = _row_value(comparison_df, "proposed", "planner_rejected_task_cap_mean")
    planner_patrol_cap = _row_value(comparison_df, "proposed", "planner_rejected_patrol_cap_mean")
    planner_model_cap = _row_value(comparison_df, "proposed", "planner_rejected_model_det_cap_mean")
    planner_total = (
        np.nansum([
            planner_task_cap,
            planner_patrol_cap,
            planner_model_cap,
            _row_value(comparison_df, "proposed", "planner_rejected_model_det_cycle_cap_mean"),
            _row_value(comparison_df, "proposed", "planner_rejected_model_det_busy_primary_mean"),
            _row_value(comparison_df, "proposed", "planner_rejected_model_det_busy_fallback_quality_mean"),
            _row_value(comparison_df, "proposed", "planner_rejected_model_det_direct_conflict_mean"),
            _row_value(comparison_df, "proposed", "planner_rejected_patrol_locked_model_det_mean"),
            _row_value(comparison_df, "proposed", "planner_rejected_unassigned_mean"),
        ])
    )

    def _rate(num: float, den: float) -> float:
        if not np.isfinite(num) or not np.isfinite(den) or den <= 0.0:
            return float("nan")
        return float(num / den)

    row = {
        "output_name": str(output_name),
        "base_stage": _safe_text(stage.get("key")),
        "stage_title": _safe_text(stage.get("title")),
        "risk_threshold": risk_threshold,
        "risk_scale": risk_scale,
        "preventive_policy": _row_text(comparison_df, "proposed", "preventive_policy"),
        "preventive_policy_source": _row_text(comparison_df, "proposed", "preventive_policy_source"),
        "proposed_exposure_mean": exp_prop,
        "prediction_only_exposure_mean": exp_pred,
        "reactive_exposure_mean": exp_react,
        "proposed_vs_prediction_exposure_improve_pct": _pct_improvement(exp_pred, exp_prop),
        "proposed_vs_reactive_exposure_improve_pct": _pct_improvement(exp_react, exp_prop),
        "proposed_response_time_mean": resp_prop,
        "proposed_vs_prediction_response_improve_pct": _pct_improvement(resp_pred, resp_prop),
        "proposed_vs_reactive_response_improve_pct": _pct_improvement(resp_react, resp_prop),
        "proposed_comm_mean": comm_prop,
        "proposed_vs_prediction_comm_change_pct": _pct_change(comm_pred, comm_prop),
        "proposed_vs_reactive_comm_change_pct": _pct_change(comm_react, comm_prop),
        "candidates_mean": candidates,
        "pass_field_mean": pass_field,
        "rejected_risk_mean": rejected_risk,
        "pass_risk_mean": pass_risk,
        "rejected_busy_mean": rejected_busy,
        "rejected_eta_mean": rejected_eta,
        "rejected_support_mean": rejected_support,
        "rejected_persistence_mean": rejected_persistence,
        "not_selected_mean": not_selected,
        "generated_mean": generated,
        "accepted_mean": accepted,
        "completed_model_scored_mean": completed,
        "planner_rejected_task_cap_mean": planner_task_cap,
        "planner_rejected_patrol_cap_mean": planner_patrol_cap,
        "planner_rejected_model_det_cap_mean": planner_model_cap,
        "planner_rejections_total_mean": float(planner_total),
        "pass_field_rate": _rate(pass_field, candidates),
        "risk_rejection_rate": _rate(rejected_risk, candidates),
        "risk_pass_rate": _rate(pass_risk, candidates),
        "generation_rate": _rate(generated, candidates),
        "accept_rate": _rate(accepted, candidates),
        "completion_rate": _rate(completed, candidates),
    }

    comparison_df = comparison_df.copy()
    comparison_df.insert(0, "output_name", str(output_name))
    comparison_df.insert(1, "risk_threshold", float(risk_threshold))
    comparison_df.insert(2, "risk_scale", float(risk_scale))
    return row, comparison_df


def _append_deltas(summary_df: pd.DataFrame, base_output_name: str) -> pd.DataFrame:
    if summary_df.empty:
        return summary_df
    rows = summary_df.loc[summary_df["output_name"] == base_output_name]
    if rows.empty:
        return summary_df
    base = rows.iloc[0]
    summary_df = summary_df.copy()
    summary_df["base_output_name"] = str(base_output_name)
    cols = [
        "proposed_vs_prediction_exposure_improve_pct",
        "proposed_vs_reactive_exposure_improve_pct",
        "proposed_response_time_mean",
        "proposed_comm_mean",
        "candidates_mean",
        "rejected_risk_mean",
        "pass_risk_mean",
        "generated_mean",
        "accepted_mean",
        "completed_model_scored_mean",
        "planner_rejections_total_mean",
    ]
    for col in cols:
        if col not in summary_df.columns:
            continue
        base_val = _safe_float(base.get(col))
        if not np.isfinite(base_val):
            summary_df[f"delta_base_{col}"] = float("nan")
            continue
        summary_df[f"delta_base_{col}"] = summary_df[col] - base_val
    return summary_df


def _build_report(summary_df: pd.DataFrame, runtime_df: pd.DataFrame, *, base_output_name: str, args: argparse.Namespace) -> str:
    lines = [
        "# Risk Gate Sweep",
        "",
        f"- Base stage: `{args.base_stage}`",
        f"- Base/current variant: `{base_output_name}`",
        f"- Runs per baseline: `{int(args.num_runs)}`",
        f"- Horizon: `{float(args.t_end)}` s",
        f"- Max workers: `{int(args.max_workers if int(args.max_workers) > 0 else 0)}`",
        "",
        "## Runtime",
        "",
        "```text",
    ]
    runtime_cols = [c for c in ["output_name", "status", "duration_s"] if c in runtime_df.columns]
    if runtime_cols:
        lines.append(runtime_df[runtime_cols].to_string(index=False))
    else:
        lines.append("No runtime rows.")
    lines.extend(["```", "", "## Variant Summary", "", "```text"])
    keep_cols = [
        "output_name",
        "risk_threshold",
        "risk_scale",
        "proposed_vs_prediction_exposure_improve_pct",
        "proposed_vs_reactive_exposure_improve_pct",
        "risk_rejection_rate",
        "risk_pass_rate",
        "generated_mean",
        "accepted_mean",
        "completed_model_scored_mean",
        "planner_rejections_total_mean",
    ]
    present = [c for c in keep_cols if c in summary_df.columns]
    lines.append(summary_df[present].to_string(index=False))
    lines.extend(["```", "", "## Findings", ""])

    gen_rows = summary_df[pd.to_numeric(summary_df.get("generated_mean"), errors="coerce").fillna(0.0) > 0.0]
    completed_rows = summary_df[pd.to_numeric(summary_df.get("completed_model_scored_mean"), errors="coerce").fillna(0.0) > 0.0]
    min_risk_row = None
    if "risk_rejection_rate" in summary_df.columns:
        tmp = summary_df.copy()
        tmp["risk_rejection_rate"] = pd.to_numeric(tmp["risk_rejection_rate"], errors="coerce")
        tmp = tmp[np.isfinite(tmp["risk_rejection_rate"])]
        if not tmp.empty:
            min_risk_row = tmp.loc[tmp["risk_rejection_rate"].idxmin()]

    if gen_rows.empty:
        lines.append("- No variant generated any model-scored preventive tasks.")
    else:
        best_gen = gen_rows.sort_values(["generated_mean", "completed_model_scored_mean"], ascending=[False, False]).iloc[0]
        lines.append(
            f"- Best generation variant: `{best_gen['output_name']}` "
            f"(generated={_fmt_float(best_gen.get('generated_mean'))}, "
            f"accepted={_fmt_float(best_gen.get('accepted_mean'))}, "
            f"completed={_fmt_float(best_gen.get('completed_model_scored_mean'))})."
        )

    if completed_rows.empty:
        lines.append("- No variant completed any model-scored preventive tasks.")
    else:
        best_done = completed_rows.sort_values(["completed_model_scored_mean"], ascending=[False]).iloc[0]
        lines.append(
            f"- Best completion variant: `{best_done['output_name']}` "
            f"(completed={_fmt_float(best_done.get('completed_model_scored_mean'))}, "
            f"exposure vs prediction={_fmt_float(best_done.get('proposed_vs_prediction_exposure_improve_pct'))}%)."
        )

    if min_risk_row is not None:
        lines.append(
            f"- Lowest risk-rejection rate: `{min_risk_row['output_name']}` "
            f"(threshold={_fmt_float(min_risk_row.get('risk_threshold'))}, "
            f"scale={_fmt_float(min_risk_row.get('risk_scale'), 6)}, "
            f"risk_rejection_rate={_fmt_float(min_risk_row.get('risk_rejection_rate'))}, "
            f"generated={_fmt_float(min_risk_row.get('generated_mean'))})."
        )

    lines.extend(["", "## Recommended Next Steps", ""])

    recommendations: list[str] = []
    if gen_rows.empty:
        recommendations.append(
            "Risk-threshold / risk-scale changes alone are not enough to make the preventive branch emit tasks. "
            "The next inspection should compare `model_deterring_rejected_risk_mean`, `model_deterring_pass_risk_mean`, "
            "and `model_deterring_not_selected_mean` across variants to see whether the branch is still dying at risk or "
            "is immediately losing to patrol after passing risk."
        )
    elif completed_rows.empty:
        recommendations.append(
            "At least one variant generates preventive tasks, but none complete. That means the risk gate is part of the blocker, "
            "but the next bottleneck is downstream in dispatch/queueing."
        )
    else:
        recommendations.append(
            "Use the best completion variant as the new debugging base and then inspect dispatch protection / queue pressure "
            "only after the risk gate is confirmed open."
        )

    if min_risk_row is not None and _safe_float(min_risk_row.get("risk_rejection_rate")) < 0.5 and _safe_float(min_risk_row.get("generated_mean")) <= 0.0:
        recommendations.append(
            "The risk gate can be opened without creating preventive tasks. Inspect patrol/preventive arbitration next, especially `model_deterring_not_selected` and the margin comparison against patrol."
        )

    if min_risk_row is not None and str(min_risk_row.get("output_name")) != str(base_output_name):
        recommendations.append(
            f"Rerun the promising risk variant `{min_risk_row['output_name']}` at the full thesis horizon after this sweep, because it minimizes risk rejection relative to the current setting."
        )

    if not recommendations:
        recommendations.append(
            "No single risk setting stands out yet. Increase the sweep horizon and add a few more threshold points near the current boundary."
        )

    for rec in recommendations:
        lines.append(f"1. {rec}")

    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parser().parse_args()
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    specs = _variant_specs(args)
    worker_count = _effective_max_workers(int(args.max_workers), len(specs))

    payloads = [
        {
            "base_stage": str(args.base_stage),
            "output_name": str(spec["output_name"]),
            "risk_threshold": float(spec["risk_threshold"]),
            "risk_scale": float(spec["risk_scale"]),
            "variant_kind": str(spec["variant_kind"]),
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

    print(f"[risk-sweep] running {len(specs)} variants with max_workers={worker_count}")
    start_all = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {pool.submit(_worker_entry, payload): payload["output_name"] for payload in payloads}
        completed = 0
        for future in as_completed(future_map):
            completed += 1
            output_name = future_map[future]
            result = future.result()
            results.append(result)
            print(
                f"[risk-sweep] completed {completed}/{len(specs)} "
                f"variant={output_name} status={result.get('status')} duration_s={_fmt_float(result.get('duration_s'))}"
            )
            if str(result.get("status")) == "failed":
                print(f"[risk-sweep] variant={output_name} error={result.get('error', '')}")

    runtime_df = pd.DataFrame(results)
    successful = [str(r["output_name"]) for r in results if str(r.get("status")) in {"ok", "skipped"}]
    if not successful:
        raise SystemExit("All risk-gate variants failed.")

    summary_rows = []
    long_frames = []
    for output_name in successful:
        row, long_df = _build_variant_summary(output_root, output_name)
        summary_rows.append(row)
        long_frames.append(long_df)

    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df.sort_values(["risk_threshold", "risk_scale", "output_name"]).reset_index(drop=True)
    base_output_name = _variant_output_name(str(args.base_stage), float(args.current_risk_threshold), float(args.current_risk_scale))
    summary_df = _append_deltas(summary_df, base_output_name)
    long_df = pd.concat(long_frames, ignore_index=True) if long_frames else pd.DataFrame()

    runtime_path = output_root / "risk_gate_runtime.csv"
    summary_path = output_root / "risk_gate_summary.csv"
    long_path = output_root / "risk_gate_long.csv"
    report_path = output_root / "risk_gate_sweep.md"
    manifest_path = output_root / "risk_gate_sweep_manifest.json"

    runtime_df.to_csv(runtime_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    if not long_df.empty:
        long_df.to_csv(long_path, index=False)
    report_path.write_text(_build_report(summary_df, runtime_df, base_output_name=base_output_name, args=args), encoding="utf-8")

    manifest = {
        "base_stage": str(args.base_stage),
        "current_risk_threshold": float(args.current_risk_threshold),
        "current_risk_scale": float(args.current_risk_scale),
        "threshold_values": list(_parse_float_list(args.threshold_values)),
        "scale_values": list(_parse_float_list(args.scale_values)),
        "cross_product": bool(args.cross_product),
        "include_current": bool(args.include_current),
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
        "successful_variants": list(successful),
        "results": runtime_df.to_dict(orient="records"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[risk-sweep] wrote {runtime_path}")
    print(f"[risk-sweep] wrote {summary_path}")
    if not long_df.empty:
        print(f"[risk-sweep] wrote {long_path}")
    print(f"[risk-sweep] wrote {report_path}")
    print(f"[risk-sweep] wrote {manifest_path}")


if __name__ == "__main__":
    main()
