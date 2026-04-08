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

import pandas as pd

from exploration.compare_system_performance import (
    DEFAULT_STAGE_KEYS,
    DEFAULT_VARIANT_KEYS,
    _bird_metric_label,
    _build_summary_row,
    _fmt_float,
    _target_title,
)
from exploration.variants import EXPLORATION_VARIANTS, variant_names
from simplification.stages import SIMPLIFICATION_STAGE_ORDER, get_stage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare how a pre-run seeding phase (`warmup_s`) changes system "
            "performance across selected simplification stages and exploration variants."
        )
    )
    parser.add_argument("--stage", action="append", dest="stages", choices=SIMPLIFICATION_STAGE_ORDER)
    parser.add_argument("--variant", action="append", dest="variants", choices=variant_names())
    parser.add_argument("--include-default-stages", action="store_true", help="Include the default simplification comparison set.")
    parser.add_argument("--include-all-variants", action="store_true", help="Include every exploration variant.")
    parser.add_argument("--list", action="store_true", help="List known stage and variant targets and exit.")
    parser.add_argument(
        "--warmup-values",
        default="0,300,900,1800",
        help="Comma-separated seeding / warmup durations in seconds.",
    )
    parser.add_argument("--num-runs", type=int, default=3, help="Runs per baseline family.")
    parser.add_argument("--seed-start", type=int, default=123, help="First seed for matched-seed comparisons.")
    parser.add_argument("--t-end", type=float, default=3600.0, help="Scored simulation horizon in seconds.")
    parser.add_argument("--dt", type=float, default=1.0, help="Simulation step in seconds.")
    parser.add_argument("--nx", type=int, default=120, help="SESTPP grid X cells.")
    parser.add_argument("--ny", type=int, default=96, help="SESTPP grid Y cells.")
    parser.add_argument("--time-metrics-period-s", type=float, default=300.0, help="Time-series sampling cadence.")
    parser.add_argument("--output-root", default="results/seeding_phase_compare", help="Directory for warmup-comparison outputs.")
    parser.add_argument("--quiet", action="store_true", help="Reduce underlying runner output.")
    parser.add_argument("--max-workers", type=int, default=0, help="0 => auto. Parallelism is across system x warmup jobs.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip a job if its comparison.csv already exists.")
    return parser


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


def _selected_targets(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    if args.list:
        print("Simplification stages:")
        for key in DEFAULT_STAGE_KEYS:
            stage = get_stage(key)
            print(f"  {key}: {stage.title}")
        print("Exploration variants:")
        for key, payload in EXPLORATION_VARIANTS.items():
            print(f"  {key}: {payload['title']}")
        raise SystemExit(0)

    stages: list[str] = []
    variants: list[str] = []
    if args.include_default_stages or (not args.stages and not args.variants and not args.include_all_variants):
        stages.extend(DEFAULT_STAGE_KEYS)
    if args.include_all_variants or (not args.stages and not args.variants):
        variants.extend(DEFAULT_VARIANT_KEYS)
    stages.extend(args.stages or [])
    variants.extend(args.variants or [])

    dedup_stages: list[str] = []
    for key in stages:
        if key not in dedup_stages:
            dedup_stages.append(key)
    dedup_variants: list[str] = []
    for key in variants:
        if key not in dedup_variants:
            dedup_variants.append(key)
    return dedup_stages, dedup_variants


def _effective_max_workers(requested: int, target_count: int) -> int:
    if target_count <= 1:
        return 1
    if int(requested) > 0:
        return max(1, min(int(requested), int(target_count)))
    cpu = os.cpu_count() or 1
    return max(1, min(int(target_count), int(cpu)))


def _output_name(system_key: str, warmup_s: float) -> str:
    return f"{system_key}__warmup_{_slug_num(warmup_s)}"


def _target_output_exists(output_root: Path, output_name: str) -> bool:
    return (output_root / output_name / "comparison.csv").exists()


def _worker_entry(payload: dict[str, Any]) -> dict[str, Any]:
    system_key = str(payload["system_key"])
    system_kind = str(payload["system_kind"])
    warmup_s = float(payload["warmup_s"])
    output_root = Path(str(payload["output_root"]))
    output_name = str(payload["output_name"])
    output_dir = output_root / output_name
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "warmup_worker_stdout.log"
    stderr_path = output_dir / "warmup_worker_stderr.log"
    start = time.time()
    try:
        if bool(payload.get("skip_existing")) and _target_output_exists(output_root, output_name):
            return {
                "system_key": system_key,
                "system_kind": system_kind,
                "warmup_s": warmup_s,
                "output_name": output_name,
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
                "--label",
                output_name,
                "--set",
                f"warmup_s={warmup_s}",
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
                "--label",
                output_name,
                "--set",
                f"warmup_s={warmup_s}",
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
                f"Warmup subprocess failed with exit code {completed.returncode}. See {stderr_path}."
            )

        return {
            "system_key": system_key,
            "system_kind": system_kind,
            "warmup_s": warmup_s,
            "output_name": output_name,
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
            "warmup_s": warmup_s,
            "output_name": output_name,
            "status": "failed",
            "duration_s": float(time.time() - start),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }


def _append_same_system_reference_deltas(summary_df: pd.DataFrame) -> pd.DataFrame:
    df = summary_df.copy()
    delta_specs = [
        ("proposed_exposure_mean", "delta_vs_no_warmup_exposure_mean"),
        ("proposed_response_time_mean", "delta_vs_no_warmup_response_time_mean"),
        ("proposed_birds_deterred_pct_mean", "delta_vs_no_warmup_birds_deterred_pct_pts"),
        ("proposed_comm_mean", "delta_vs_no_warmup_comm_mean"),
        ("proposed_total_planner_rejections_mean", "delta_vs_no_warmup_total_planner_rejections_mean"),
        ("proposed_model_completed_mean", "delta_vs_no_warmup_model_completed_mean"),
    ]
    for out_col in [name for (_src, name) in delta_specs]:
        df[out_col] = float("nan")
    df["reference_warmup_s"] = float("nan")

    for system_key, sub in df.groupby("system_key"):
        exact_zero = sub.loc[sub["warmup_s"] == 0.0]
        if not exact_zero.empty:
            ref = exact_zero.iloc[0]
        else:
            ref = sub.sort_values("warmup_s", ascending=True).iloc[0]
        ref_warmup = float(ref.get("warmup_s", float("nan")))
        mask = df["system_key"] == system_key
        df.loc[mask, "reference_warmup_s"] = ref_warmup
        for src_col, out_col in delta_specs:
            ref_val = float(ref.get(src_col, float("nan")))
            df.loc[mask, out_col] = pd.to_numeric(df.loc[mask, src_col], errors="coerce") - ref_val
    return df


def _build_best_by_system(summary_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for system_key, sub in summary_df.groupby("system_key"):
        exposure_sub = sub[pd.to_numeric(sub["proposed_exposure_mean"], errors="coerce").notna()].sort_values("proposed_exposure_mean", ascending=True)
        response_sub = sub[pd.to_numeric(sub["proposed_response_time_mean"], errors="coerce").notna()].sort_values("proposed_response_time_mean", ascending=True)
        birds_sub = sub[pd.to_numeric(sub["proposed_birds_deterred_pct_mean"], errors="coerce").notna()].sort_values("proposed_birds_deterred_pct_mean", ascending=False)
        comm_sub = sub[pd.to_numeric(sub["proposed_comm_mean"], errors="coerce").notna()].sort_values("proposed_comm_mean", ascending=True)
        exp_best = exposure_sub.iloc[0] if not exposure_sub.empty else None
        resp_best = response_sub.iloc[0] if not response_sub.empty else None
        birds_best = birds_sub.iloc[0] if not birds_sub.empty else None
        comm_best = comm_sub.iloc[0] if not comm_sub.empty else None

        rows.append(
            {
                "system_key": str(system_key),
                "system_kind": str(sub.iloc[0]["system_kind"]),
                "title": str(sub.iloc[0]["title"]),
                "reference_warmup_s": float(sub.iloc[0].get("reference_warmup_s", float("nan"))),
                "best_exposure_warmup_s": float(exp_best["warmup_s"]) if exp_best is not None else float("nan"),
                "best_exposure_mean": float(exp_best["proposed_exposure_mean"]) if exp_best is not None else float("nan"),
                "best_exposure_delta_vs_no_warmup": float(exp_best["delta_vs_no_warmup_exposure_mean"]) if exp_best is not None else float("nan"),
                "best_response_warmup_s": float(resp_best["warmup_s"]) if resp_best is not None else float("nan"),
                "best_response_time_mean": float(resp_best["proposed_response_time_mean"]) if resp_best is not None else float("nan"),
                "best_response_delta_vs_no_warmup": float(resp_best["delta_vs_no_warmup_response_time_mean"]) if resp_best is not None else float("nan"),
                "best_birds_warmup_s": float(birds_best["warmup_s"]) if birds_best is not None else float("nan"),
                "best_birds_deterred_pct_mean": float(birds_best["proposed_birds_deterred_pct_mean"]) if birds_best is not None else float("nan"),
                "best_birds_delta_vs_no_warmup": float(birds_best["delta_vs_no_warmup_birds_deterred_pct_pts"]) if birds_best is not None else float("nan"),
                "lowest_comm_warmup_s": float(comm_best["warmup_s"]) if comm_best is not None else float("nan"),
                "lowest_comm_mean": float(comm_best["proposed_comm_mean"]) if comm_best is not None else float("nan"),
                "lowest_comm_delta_vs_no_warmup": float(comm_best["delta_vs_no_warmup_comm_mean"]) if comm_best is not None else float("nan"),
            }
        )
    return pd.DataFrame(rows).sort_values(["best_exposure_mean", "system_key"], ascending=[True, True]).reset_index(drop=True)


def _render_report(summary_df: pd.DataFrame, best_df: pd.DataFrame, runtime_df: pd.DataFrame, *, warmup_values: tuple[float, ...]) -> str:
    lines: list[str] = []
    lines.append("# Seeding Phase Comparison")
    lines.append("")
    lines.append(
        "Each job uses the existing `warmup_s` pre-run truth burn-in to seed SESTPP state, then resets public metrics before the scored horizon starts."
    )
    lines.append("")
    lines.append(f"- Warmup values: `{', '.join(_fmt_float(v, 0) for v in warmup_values)}` seconds")
    lines.append("")
    lines.append("## Best By System")
    lines.append("")
    for _, row in best_df.iterrows():
        lines.append(f"### {row['system_key']}: {row['title']}")
        lines.append(
            f"- Best exposure warmup: `{_fmt_float(row.get('best_exposure_warmup_s'), 0)} s` "
            f"with exposure `{_fmt_float(row.get('best_exposure_mean'))}` "
            f"(delta vs no-warmup `{_fmt_float(row.get('best_exposure_delta_vs_no_warmup'))}`)."
        )
        lines.append(
            f"- Best response warmup: `{_fmt_float(row.get('best_response_warmup_s'), 0)} s` "
            f"with response `{_fmt_float(row.get('best_response_time_mean'))} s` "
            f"(delta `{_fmt_float(row.get('best_response_delta_vs_no_warmup'))} s`)."
        )
        lines.append(
            f"- Best {_bird_metric_label(str(row.get('bird_metric_column', 'birds_deterred_pct_mean'))).lower()} warmup: "
            f"`{_fmt_float(row.get('best_birds_warmup_s'), 0)} s` "
            f"at `{_fmt_float(row.get('best_birds_deterred_pct_mean'))}%` "
            f"(delta `{_fmt_float(row.get('best_birds_delta_vs_no_warmup'))}` pts)."
        )
        lines.append("")

    lines.append("## Runtime")
    lines.append("")
    lines.append("```text")
    keep_runtime = [c for c in ["system_key", "warmup_s", "status", "duration_s"] if c in runtime_df.columns]
    lines.append(runtime_df[keep_runtime].to_string(index=False) if keep_runtime else "No runtime rows.")
    lines.append("```")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("```text")
    keep_cols = [
        "system_key",
        "warmup_s",
        "proposed_exposure_mean",
        "delta_vs_no_warmup_exposure_mean",
        "proposed_response_time_mean",
        "delta_vs_no_warmup_response_time_mean",
        "proposed_birds_deterred_pct_mean",
        "delta_vs_no_warmup_birds_deterred_pct_pts",
        "proposed_comm_mean",
        "delta_vs_no_warmup_comm_mean",
        "proposed_model_completed_mean",
        "delta_vs_no_warmup_model_completed_mean",
    ]
    present = [c for c in keep_cols if c in summary_df.columns]
    lines.append(summary_df[present].to_string(index=False))
    lines.append("```")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parser().parse_args()
    stages, variants = _selected_targets(args)
    warmup_values = _parse_float_list(args.warmup_values)

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    targets = (
        [{"system_key": key, "system_kind": "simplification_stage"} for key in stages]
        + [{"system_key": key, "system_kind": "exploration_variant"} for key in variants]
    )
    if not targets:
        raise ValueError("No systems were selected for seeding-phase comparison.")

    payloads = []
    for target in targets:
        for warmup_s in warmup_values:
            payloads.append(
                {
                    "system_key": str(target["system_key"]),
                    "system_kind": str(target["system_kind"]),
                    "warmup_s": float(warmup_s),
                    "output_name": _output_name(str(target["system_key"]), float(warmup_s)),
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
            )

    worker_count = _effective_max_workers(int(args.max_workers), len(payloads))
    if not bool(args.quiet):
        print(f"[warmup-compare] running {len(payloads)} jobs with max_workers={worker_count}")

    runtime_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {
            pool.submit(_worker_entry, payload): (payload["system_key"], payload["warmup_s"])
            for payload in payloads
        }
        completed = 0
        for future in as_completed(future_map):
            completed += 1
            system_key, warmup_s = future_map[future]
            result = future.result()
            runtime_results.append(result)
            if not bool(args.quiet):
                print(
                    f"[warmup-compare] completed {completed}/{len(payloads)} "
                    f"system={system_key} warmup_s={_fmt_float(warmup_s, 0)} "
                    f"status={result.get('status')} duration_s={_fmt_float(result.get('duration_s'))}"
                )

    failed = [row for row in runtime_results if str(row.get("status")) == "failed"]
    runtime_df = pd.DataFrame(runtime_results)
    runtime_path = output_root / "seeding_phase_runtime.csv"
    runtime_df.to_csv(runtime_path, index=False)
    if failed:
        failed_keys = ", ".join(f"{row.get('system_key')}@{row.get('warmup_s')}" for row in failed)
        raise RuntimeError(f"Warmup workers failed for: {failed_keys}. See {runtime_path}.")

    summary_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    for payload in payloads:
        comparison_csv = output_root / str(payload["output_name"]) / "comparison.csv"
        if not comparison_csv.exists():
            raise FileNotFoundError(f"Missing comparison output: {comparison_csv}")
        comparison_df = pd.read_csv(comparison_csv)
        summary = _build_summary_row(
            str(payload["system_key"]),
            system_kind=str(payload["system_kind"]),
            title=_target_title(str(payload["system_kind"]), str(payload["system_key"])),
            comparison_df=comparison_df,
        )
        summary["warmup_s"] = float(payload["warmup_s"])
        summary["output_name"] = str(payload["output_name"])
        summary_rows.append(summary)
        manifest_rows.append(
            {
                "system_key": str(payload["system_key"]),
                "system_kind": str(payload["system_kind"]),
                "title": _target_title(str(payload["system_kind"]), str(payload["system_key"])),
                "warmup_s": float(payload["warmup_s"]),
                "output_name": str(payload["output_name"]),
                "output_dir": str(output_root / str(payload["output_name"])),
                "comparison_csv": str(comparison_csv),
            }
        )

    summary_df = pd.DataFrame(summary_rows)
    summary_df = _append_same_system_reference_deltas(summary_df)
    summary_df = summary_df.sort_values(["system_key", "warmup_s"], ascending=[True, True]).reset_index(drop=True)
    best_df = _build_best_by_system(summary_df)

    summary_path = output_root / "seeding_phase_summary.csv"
    best_path = output_root / "seeding_phase_best_by_system.csv"
    manifest_path = output_root / "seeding_phase_manifest.json"
    report_path = output_root / "seeding_phase_report.md"

    summary_df.to_csv(summary_path, index=False)
    best_df.to_csv(best_path, index=False)
    manifest_path.write_text(json.dumps(manifest_rows, indent=2), encoding="utf-8")
    report_path.write_text(_render_report(summary_df, best_df, runtime_df, warmup_values=warmup_values), encoding="utf-8")

    if not bool(args.quiet):
        print(f"[warmup-compare] wrote {summary_path}")
        print(f"[warmup-compare] wrote {best_path}")
        print(f"[warmup-compare] wrote {runtime_path}")
        print(f"[warmup-compare] wrote {report_path}")


if __name__ == "__main__":
    main()
