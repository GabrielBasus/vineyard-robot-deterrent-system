from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any

from .stages import SIMPLIFICATION_STAGE_ORDER, get_stage, iter_stages


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Run baseline comparisons for one or more simplification stages. "
            "Use this to start from the simplest thesis-consistent system and "
            "add planner controls back incrementally."
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
        help="Run every simplification stage in order.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List available stages and exit.",
    )
    p.add_argument("--num-runs", type=int, default=1, help="Runs per baseline family.")
    p.add_argument("--seed-start", type=int, default=123, help="First seed for the baseline sweep.")
    p.add_argument("--t-end", type=float, default=1800.0, help="Simulation horizon in seconds.")
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
        help="Directory where stage outputs will be written.",
    )
    p.add_argument(
        "--label",
        default="",
        help="Optional output directory name override for this stage run.",
    )
    p.add_argument(
        "--set",
        action="append",
        dest="set_items",
        help="Extra simulation override as KEY=VALUE. Repeat as needed.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-run progress output from the baseline runner.",
    )
    return p


def _stage_keys_from_args(args: argparse.Namespace) -> tuple[str, ...]:
    if args.all:
        return SIMPLIFICATION_STAGE_ORDER
    if args.stages:
        return tuple(args.stages)
    return ("s0_simple_tasks_core",)


def _load_module(module_name: str):
    return importlib.import_module(module_name)


def _base_sim_kwargs(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    return {
        "T_end": float(args.t_end),
        "dt": float(args.dt),
        "NX": int(args.nx),
        "NY": int(args.ny),
        "report_metrics_end": False,
        "telemetry_dir": str(output_dir / "telemetry"),
        "telemetry_prompt_save": False,
    }


def _parse_override_value(raw: str) -> Any:
    text = str(raw).strip()
    lowered = text.lower()
    if lowered == "none":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "nan":
        return float("nan")
    try:
        return json.loads(text)
    except Exception:
        return text


def _parse_override_assignments(items: list[str] | None) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for item in items or []:
        text = str(item)
        if "=" not in text:
            raise ValueError(f"Override must be KEY=VALUE, got: {item!r}")
        key, raw_value = text.split("=", 1)
        key = str(key).strip()
        if not key:
            raise ValueError(f"Override key is empty in: {item!r}")
        overrides[key] = _parse_override_value(raw_value)
    return overrides


def _write_manifest(
    path: Path,
    *,
    stage,
    sim_kwargs: dict[str, Any],
    args: argparse.Namespace,
    output_name: str,
    extra_overrides: dict[str, Any] | None = None,
) -> None:
    payload = {
        "stage": stage.public_dict(),
        "output_name": str(output_name),
        "runner_args": {
            "num_runs": int(args.num_runs),
            "seed_start": int(args.seed_start),
            "t_end": float(args.t_end),
            "dt": float(args.dt),
            "nx": int(args.nx),
            "ny": int(args.ny),
            "time_metrics_period_s": float(args.time_metrics_period_s),
            "output_root": str(args.output_root),
        },
        "extra_overrides": dict(extra_overrides or {}),
        "sim_kwargs": dict(sim_kwargs),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _print_stage_list() -> None:
    for stage in iter_stages():
        print(f"{stage.key}: {stage.title}")
        print(f"  module={stage.module_name}")
        print(f"  {stage.description}")
        if stage.added_back:
            print("  adds back:")
            for item in stage.added_back:
                print(f"    - {item}")


def run_stage_once(
    stage_key: str,
    *,
    num_runs: int = 1,
    seed_start: int = 123,
    t_end: float = 1800.0,
    dt: float = 1.0,
    nx: int = 120,
    ny: int = 96,
    time_metrics_period_s: float = 300.0,
    output_root: str = "results/simplification",
    output_name: str | None = None,
    extra_overrides: dict[str, Any] | None = None,
    quiet: bool = False,
    emit_logs: bool = True,
) -> dict[str, Any]:
    stage = get_stage(stage_key)
    module = _load_module(stage.module_name)

    output_name = str(output_name or stage.key)
    output_dir = Path(output_root) / output_name
    output_dir.mkdir(parents=True, exist_ok=True)

    args = argparse.Namespace(
        num_runs=int(num_runs),
        seed_start=int(seed_start),
        t_end=float(t_end),
        dt=float(dt),
        nx=int(nx),
        ny=int(ny),
        time_metrics_period_s=float(time_metrics_period_s),
        output_root=str(output_root),
        quiet=bool(quiet),
    )

    sim_kwargs = _base_sim_kwargs(args, output_dir)
    sim_kwargs.update(stage.overrides)
    sim_kwargs.update(dict(extra_overrides or {}))

    comparison_csv = output_dir / "comparison.csv"
    _write_manifest(
        output_dir / "stage_manifest.json",
        stage=stage,
        sim_kwargs=sim_kwargs,
        args=args,
        output_name=output_name,
        extra_overrides=extra_overrides,
    )

    if emit_logs:
        print(f"[simplification] stage={stage.key} title={stage.title}")
        print(f"[simplification] module={stage.module_name}")
        print(f"[simplification] output={output_dir}")

    result = module.run_baseline_suite(
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        report_each_run=not bool(args.quiet),
        csv_path=str(comparison_csv),
        collect_time_metrics=True,
        time_metrics_period_s=float(args.time_metrics_period_s),
        **sim_kwargs,
    )

    comparison_df = result.get("comparison")
    time_df = result.get("comparison_over_time")
    if comparison_df is not None:
        comparison_preview = output_dir / "comparison_preview.txt"
        comparison_preview.write_text(comparison_df.head(12).to_string(index=False), encoding="utf-8")
    if emit_logs and time_df is not None:
        print(f"[simplification] time_rows={len(time_df)} comparison_rows={len(comparison_df)}")
    if emit_logs:
        print(f"[simplification] wrote {comparison_csv}")

    return {
        "stage_key": stage.key,
        "stage_title": stage.title,
        "module_name": stage.module_name,
        "output_name": str(output_name),
        "output_dir": str(output_dir),
        "comparison_csv": str(comparison_csv),
        "comparison_rows": int(len(comparison_df)) if comparison_df is not None else 0,
        "time_rows": int(len(time_df)) if time_df is not None else 0,
    }


def _run_stage(stage_key: str, args: argparse.Namespace) -> None:
    run_stage_once(
        stage_key,
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        t_end=float(args.t_end),
        dt=float(args.dt),
        nx=int(args.nx),
        ny=int(args.ny),
        time_metrics_period_s=float(args.time_metrics_period_s),
        output_root=str(args.output_root),
        output_name=(None if getattr(args, "label", None) in (None, "") else str(args.label)),
        extra_overrides=_parse_override_assignments(getattr(args, "set_items", None)),
        quiet=bool(args.quiet),
        emit_logs=True,
    )


def main() -> None:
    args = _parser().parse_args()
    if args.list:
        _print_stage_list()
        return

    for stage_key in _stage_keys_from_args(args):
        _run_stage(stage_key, args)


if __name__ == "__main__":
    main()
