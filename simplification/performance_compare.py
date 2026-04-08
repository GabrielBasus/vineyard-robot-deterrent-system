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

from .compare_stages import write_stage_comparison
from .stages import SIMPLIFICATION_STAGE_ORDER, iter_stages


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Run simplification-stage performance comparisons in parallel, then build "
            "a cross-stage report and next-step recommendations."
        )
    )
    p.add_argument(
        "--stage",
        action="append",
        dest="stages",
        help="Simplification stage key. Repeat to run multiple stages.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Run the full simplification stage ladder. Default if no --stage is given.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List available stages and exit.",
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
        default="results/simplification",
        help="Directory where stage outputs and reports will be written.",
    )
    p.add_argument(
        "--main-stage",
        default="auto",
        help="Stage key to treat as the main/current reference in the comparison report.",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=0,
        help="0 => auto. Parallelism is across simplification stages.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip a stage if its comparison.csv and stage manifest already exist.",
    )
    p.add_argument(
        "--verbose-stage-logs",
        action="store_true",
        help="Allow per-stage baseline logs from worker processes.",
    )
    return p


def _print_stage_list() -> None:
    for stage in iter_stages():
        print(f"{stage.key}: {stage.title}")
        print(f"  module={stage.module_name}")
        print(f"  {stage.description}")


def _stage_keys_from_args(args: argparse.Namespace) -> tuple[str, ...]:
    if args.stages:
        return tuple(args.stages)
    if args.all or not args.stages:
        return SIMPLIFICATION_STAGE_ORDER
    return ()


def _effective_max_workers(requested: int, stage_count: int) -> int:
    if stage_count <= 1:
        return 1
    if int(requested) > 0:
        return max(1, min(int(requested), int(stage_count)))
    cpu = os.cpu_count() or 1
    return max(1, min(int(stage_count), int(cpu)))


def _stage_output_exists(output_root: str, stage_key: str) -> bool:
    stage_dir = Path(output_root) / stage_key
    return (stage_dir / "comparison.csv").exists() and (stage_dir / "stage_manifest.json").exists()


def _safe_float(value: Any) -> float:
    if value is None:
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _fmt_float(value: Any, digits: int = 3) -> str:
    val = _safe_float(value)
    if not np.isfinite(val):
        return "nan"
    return f"{val:.{digits}f}"


def _worker_entry(payload: dict[str, Any]) -> dict[str, Any]:
    stage_key = str(payload["stage_key"])
    start = time.time()
    output_dir = Path(payload["output_root"]) / stage_key
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "performance_worker_stdout.log"
    stderr_path = output_dir / "performance_worker_stderr.log"
    try:
        if bool(payload.get("skip_existing")) and _stage_output_exists(str(payload["output_root"]), stage_key):
            return {
                "stage_key": stage_key,
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
            stage_key,
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
        ]
        if bool(payload["quiet"]):
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
                f"Stage subprocess failed with exit code {completed.returncode}. "
                f"See {stderr_path}."
            )
        return {
            "stage_key": stage_key,
            "status": "ok",
            "duration_s": float(time.time() - start),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    except Exception as exc:
        return {
            "stage_key": stage_key,
            "status": "failed",
            "duration_s": float(time.time() - start),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }


def _best_row(summary_df: pd.DataFrame, column: str, *, larger_is_better: bool = True) -> pd.Series | None:
    if summary_df.empty or column not in summary_df.columns:
        return None
    tmp = summary_df.copy()
    tmp[column] = pd.to_numeric(tmp[column], errors="coerce")
    tmp = tmp[np.isfinite(tmp[column])]
    if tmp.empty:
        return None
    idx = tmp[column].idxmax() if larger_is_better else tmp[column].idxmin()
    return tmp.loc[idx]


def _build_next_steps_report(
    summary_df: pd.DataFrame,
    runtime_df: pd.DataFrame,
    *,
    main_stage_key: str,
    worker_count: int,
    stage_keys: tuple[str, ...],
    args: argparse.Namespace,
) -> str:
    lines = [
        "# Simplification Performance Comparison",
        "",
        f"- Stages: {', '.join(stage_keys)}",
        f"- Main/current reference stage: `{main_stage_key}`",
        f"- Runs per baseline: `{int(args.num_runs)}`",
        f"- Horizon: `{float(args.t_end)}` s",
        f"- Max workers: `{int(worker_count)}`",
        "",
        "## Runtime",
        "",
        "```text",
    ]

    runtime_cols = [c for c in ["stage_key", "status", "duration_s", "output_dir"] if c in runtime_df.columns]
    if runtime_cols:
        lines.append(runtime_df[runtime_cols].to_string(index=False))
    else:
        lines.append("No runtime rows.")
    lines.extend(["```", "", "## Findings", ""])

    best_exposure = _best_row(summary_df, "proposed_vs_prediction_exposure_improve_pct", larger_is_better=True)
    best_completion = _best_row(summary_df, "proposed_model_completed_mean", larger_is_better=True)
    main_rows = summary_df.loc[summary_df["stage_key"] == main_stage_key] if "stage_key" in summary_df.columns else pd.DataFrame()
    main_row = None if main_rows.empty else main_rows.iloc[0]

    if best_exposure is not None and _safe_float(best_exposure.get("proposed_vs_prediction_exposure_improve_pct")) > 0.0:
        lines.append(
            f"- Best proposed-vs-prediction exposure stage: `{best_exposure['stage_key']}` "
            f"({ _fmt_float(best_exposure.get('proposed_vs_prediction_exposure_improve_pct')) }%)."
        )
    else:
        lines.append("- No stage shows a positive proposed-vs-prediction exposure win in this run.")
    if best_completion is not None and _safe_float(best_completion.get("proposed_model_completed_mean")) > 0.0:
        lines.append(
            f"- Highest model-scored preventive completions: `{best_completion['stage_key']}` "
            f"({ _fmt_float(best_completion.get('proposed_model_completed_mean')) })."
        )
    else:
        lines.append("- No stage completed any model-scored preventive actions in this run.")
    if main_row is not None:
        lines.append(
            f"- Current main stage `{main_stage_key}`: "
            f"exposure vs prediction={_fmt_float(main_row.get('proposed_vs_prediction_exposure_improve_pct'))}%, "
            f"exposure vs reactive={_fmt_float(main_row.get('proposed_vs_reactive_exposure_improve_pct'))}%, "
            f"preventive completed={_fmt_float(main_row.get('proposed_model_completed_mean'))}, "
            f"planner rejections={_fmt_float(main_row.get('proposed_total_planner_rejections_mean'))}."
        )

    lines.extend(["", "## Recommended Next Steps", ""])

    recommendations: list[str] = []
    observations: list[str] = []

    if main_row is not None:
        candidates = _safe_float(main_row.get("proposed_model_candidates_mean"))
        completed = _safe_float(main_row.get("proposed_model_completed_mean"))
        if np.isfinite(candidates) and candidates > 0.0 and (not np.isfinite(completed) or completed <= 0.0):
            recommendations.append(
                "Focus on preventive dispatch/admission before adding more model-side complexity. "
                "The current main stage is generating preventive candidates but not converting them into completed model-scored actions."
            )

        comm_vs_reactive = _safe_float(main_row.get("proposed_vs_reactive_comm_change_pct"))
        exp_vs_reactive = _safe_float(main_row.get("proposed_vs_reactive_exposure_improve_pct"))
        if np.isfinite(comm_vs_reactive) and comm_vs_reactive > 0.0 and (not np.isfinite(exp_vs_reactive) or exp_vs_reactive <= 0.0):
            recommendations.append(
                "Do not prioritize additional communication-heavy controls yet. "
                "The current main stage is paying more communication cost without beating the reactive baseline on exposure."
            )

    if not summary_df.empty and "stage_order" in summary_df.columns:
        ordered = summary_df.sort_values(["stage_order", "stage_key"]).reset_index(drop=True)
        for idx in range(1, len(ordered)):
            prev = ordered.iloc[idx - 1]
            cur = ordered.iloc[idx]
            d_rej = _safe_float(cur.get("delta_prev_proposed_total_planner_rejections_mean"))
            d_done = _safe_float(cur.get("delta_prev_proposed_model_completed_mean"))
            d_exp = _safe_float(cur.get("delta_prev_proposed_vs_prediction_exposure_improve_pct"))
            d_comm = _safe_float(cur.get("delta_prev_proposed_vs_prediction_comm_change_pct"))

            if np.isfinite(d_rej) and d_rej > 0.0 and (not np.isfinite(d_done) or d_done <= 0.0) and (not np.isfinite(d_exp) or d_exp <= 0.0):
                recommendations.append(
                    f"Treat `{cur['stage_key']}` as the next suspect control layer. "
                    f"It adds {d_rej:.3f} planner rejections over `{prev['stage_key']}` without improving proposed-vs-prediction exposure or completed preventive actions."
                )
            elif np.isfinite(d_done) and d_done > 0.0 and (not np.isfinite(d_exp) or d_exp >= 0.0):
                observations.append(
                    f"`{cur['stage_key']}` looks promising relative to `{prev['stage_key']}`: "
                    f"completed preventive actions +{d_done:.3f} with non-worse exposure."
                )
            elif np.isfinite(d_comm) and d_comm > 0.0 and (not np.isfinite(d_exp) or d_exp <= 0.0):
                observations.append(
                    f"`{cur['stage_key']}` increases communication relative to `{prev['stage_key']}` without an exposure gain."
                )

    finite_exposure = pd.to_numeric(summary_df.get("proposed_vs_prediction_exposure_improve_pct"), errors="coerce") if "proposed_vs_prediction_exposure_improve_pct" in summary_df.columns else pd.Series(dtype=float)
    finite_completed = pd.to_numeric(summary_df.get("proposed_model_completed_mean"), errors="coerce") if "proposed_model_completed_mean" in summary_df.columns else pd.Series(dtype=float)
    exposure_flat = finite_exposure.empty or finite_exposure.fillna(0.0).abs().max() <= 1.0e-9
    completed_flat = finite_completed.empty or finite_completed.fillna(0.0).max() <= 0.0
    if exposure_flat and completed_flat:
        recommendations.insert(
            0,
            "This run is still too inconclusive for planner decisions. Increase `--t-end` and/or `--num-runs` before drawing subsystem conclusions."
        )

    if best_exposure is not None and main_row is not None and str(best_exposure["stage_key"]) != str(main_stage_key):
        best_val = _safe_float(best_exposure.get("proposed_vs_prediction_exposure_improve_pct"))
        main_val = _safe_float(main_row.get("proposed_vs_prediction_exposure_improve_pct"))
        if np.isfinite(best_val) and (not np.isfinite(main_val) or best_val > main_val):
            recommendations.append(
                f"Use `{best_exposure['stage_key']}` as the next debugging base. "
                f"It currently outperforms the main stage on proposed-vs-prediction exposure."
            )

    if best_completion is not None and main_row is not None and str(best_completion["stage_key"]) != str(main_stage_key):
        best_done = _safe_float(best_completion.get("proposed_model_completed_mean"))
        main_done = _safe_float(main_row.get("proposed_model_completed_mean"))
        if np.isfinite(best_done) and (not np.isfinite(main_done) or best_done > main_done):
            recommendations.append(
                f"Use `{best_completion['stage_key']}` as the next preventive-yield debugging base. "
                f"It currently completes more model-scored preventive actions than the main stage."
            )

    if not recommendations:
        recommendations.append(
            "No single stage is clearly dominant from this run. Inspect the first stage where planner rejections increase sharply, then rerun with a longer horizon and more seeds."
        )

    for rec in recommendations:
        lines.append(f"1. {rec}")

    if observations:
        lines.extend(["", "## Secondary Observations", ""])
        for obs in observations:
            lines.append(f"- {obs}")

    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parser().parse_args()
    if args.list:
        _print_stage_list()
        return

    stage_keys = _stage_keys_from_args(args)
    if not stage_keys:
        raise SystemExit("No simplification stages selected.")

    worker_count = _effective_max_workers(int(args.max_workers), len(stage_keys))
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    payloads = [
        {
            "stage_key": stage_key,
            "num_runs": int(args.num_runs),
            "seed_start": int(args.seed_start),
            "t_end": float(args.t_end),
            "dt": float(args.dt),
            "nx": int(args.nx),
            "ny": int(args.ny),
            "time_metrics_period_s": float(args.time_metrics_period_s),
            "output_root": str(args.output_root),
            "quiet": not bool(args.verbose_stage_logs),
            "verbose_stage_logs": bool(args.verbose_stage_logs),
            "skip_existing": bool(args.skip_existing),
        }
        for stage_key in stage_keys
    ]

    print(f"[simplification] running {len(stage_keys)} stages with max_workers={worker_count}")
    start_all = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {pool.submit(_worker_entry, payload): payload["stage_key"] for payload in payloads}
        completed = 0
        for future in as_completed(future_map):
            completed += 1
            stage_key = future_map[future]
            result = future.result()
            results.append(result)
            status = str(result.get("status", "unknown"))
            duration_s = _fmt_float(result.get("duration_s"))
            print(
                f"[simplification] completed {completed}/{len(stage_keys)} "
                f"stage={stage_key} status={status} duration_s={duration_s}"
            )
            if status == "failed":
                print(f"[simplification] stage={stage_key} error={result.get('error', '')}")

    runtime_df = pd.DataFrame(results)
    if not runtime_df.empty:
        order_rank = {key: idx for idx, key in enumerate(SIMPLIFICATION_STAGE_ORDER)}
        runtime_df["stage_order"] = runtime_df["stage_key"].map(lambda k: order_rank.get(k, 10_000))
        runtime_df = runtime_df.sort_values(["stage_order", "stage_key"]).reset_index(drop=True)

    successful_stage_keys = tuple(
        str(row["stage_key"])
        for _, row in runtime_df.iterrows()
        if str(row.get("status", "")) in {"ok", "skipped"}
    )
    if not successful_stage_keys:
        raise SystemExit("All stage runs failed. No comparison report was generated.")

    compare_result = write_stage_comparison(
        output_root=output_root,
        stage_keys=successful_stage_keys,
        main_stage=str(args.main_stage),
    )
    summary_df = compare_result["summary_df"]
    main_stage_key = str(compare_result["main_stage_key"])

    runtime_path = output_root / "performance_runtime.csv"
    manifest_path = output_root / "performance_compare_manifest.json"
    next_steps_path = output_root / "performance_next_steps.md"

    runtime_df.to_csv(runtime_path, index=False)
    manifest = {
        "stage_keys": list(stage_keys),
        "successful_stage_keys": list(successful_stage_keys),
        "num_runs": int(args.num_runs),
        "seed_start": int(args.seed_start),
        "t_end": float(args.t_end),
        "dt": float(args.dt),
        "nx": int(args.nx),
        "ny": int(args.ny),
        "time_metrics_period_s": float(args.time_metrics_period_s),
        "output_root": str(args.output_root),
        "main_stage": str(args.main_stage),
        "resolved_main_stage": str(main_stage_key),
        "max_workers": int(worker_count),
        "elapsed_wall_s": float(time.time() - start_all),
        "skip_existing": bool(args.skip_existing),
        "verbose_stage_logs": bool(args.verbose_stage_logs),
        "results": runtime_df.to_dict(orient="records"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    next_steps_path.write_text(
        _build_next_steps_report(
            summary_df,
            runtime_df,
            main_stage_key=main_stage_key,
            worker_count=worker_count,
            stage_keys=successful_stage_keys,
            args=args,
        ),
        encoding="utf-8",
    )

    print(f"[simplification] wrote {compare_result['summary_path']}")
    print(f"[simplification] wrote {compare_result['report_path']}")
    print(f"[simplification] wrote {runtime_path}")
    print(f"[simplification] wrote {manifest_path}")
    print(f"[simplification] wrote {next_steps_path}")


if __name__ == "__main__":
    main()
