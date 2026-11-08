from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from exploration.row_local_priority_system import run_baseline_suite
from exploration.variants import EXPLORATION_VARIANTS, variant_names


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


def run_variant_once(
    variant_key: str,
    *,
    num_runs: int = 1,
    seed_start: int = 123,
    t_end: float = 3600.0,
    dt: float = 1.0,
    nx: int = 120,
    ny: int = 96,
    time_metrics_period_s: float = 300.0,
    output_root: str = "results/exploration",
    output_name: str | None = None,
    extra_overrides: dict[str, Any] | None = None,
    quiet: bool = False,
    emit_logs: bool = True,
) -> dict[str, Any]:
    payload = EXPLORATION_VARIANTS[variant_key]
    output_dir = Path(output_root) / str(output_name or variant_key)
    output_dir.mkdir(parents=True, exist_ok=True)

    effective_overrides = dict(payload.get("overrides", {}))
    effective_overrides.update(dict(extra_overrides or {}))

    manifest = {
        "variant_key": str(variant_key),
        "title": str(payload["title"]),
        "description": str(payload["description"]),
        "output_name": str(output_name or variant_key),
        "runner_args": {
            "num_runs": int(num_runs),
            "seed_start": int(seed_start),
            "t_end": float(t_end),
            "dt": float(dt),
            "nx": int(nx),
            "ny": int(ny),
            "time_metrics_period_s": float(time_metrics_period_s),
            "output_root": str(output_root),
        },
        "extra_overrides": dict(extra_overrides or {}),
        "effective_overrides": dict(effective_overrides),
    }
    (output_dir / "variant_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if emit_logs and (not quiet):
        print(f"[exploration] variant={variant_key} output={output_dir}")

    result = run_baseline_suite(
        num_runs=int(num_runs),
        seed_start=int(seed_start),
        T_end=float(t_end),
        dt=float(dt),
        NX=int(nx),
        NY=int(ny),
        time_metrics_period_s=float(time_metrics_period_s),
        csv_path=str(output_dir / "comparison.csv"),
        report_each_run=(not bool(quiet)),
        report_metrics_end=False,
        telemetry_dir=str(output_dir / "telemetry_live"),
        telemetry_prompt_save=False,
        telemetry_clear_on_start=True,
        **effective_overrides,
    )

    comparison_df = result.get("comparison")
    time_df = result.get("comparison_over_time")
    return {
        "variant_key": str(variant_key),
        "title": str(payload["title"]),
        "output_name": str(output_name or variant_key),
        "output_dir": str(output_dir),
        "comparison_csv": str(output_dir / "comparison.csv"),
        "comparison_rows": int(len(comparison_df)) if comparison_df is not None else 0,
        "time_rows": int(len(time_df)) if time_df is not None else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run isolated exploratory row/local-priority variants.")
    parser.add_argument("--list", action="store_true", help="List available exploration variants.")
    parser.add_argument("--variant", action="append", choices=variant_names(), help="Variant name to run.")
    parser.add_argument("--num-runs", type=int, default=1, help="Matched-seed runs per baseline.")
    parser.add_argument("--seed-start", type=int, default=123, help="First seed for matched-seed comparisons.")
    parser.add_argument("--t-end", type=float, default=3600.0, help="Simulation horizon in seconds.")
    parser.add_argument("--dt", type=float, default=1.0, help="Simulation step in seconds.")
    parser.add_argument("--nx", type=int, default=120, help="SESTPP grid X cells.")
    parser.add_argument("--ny", type=int, default=96, help="SESTPP grid Y cells.")
    parser.add_argument("--time-metrics-period-s", type=float, default=300.0, help="Time-series reporting cadence.")
    parser.add_argument("--output-root", type=str, default="results/exploration", help="Root output directory.")
    parser.add_argument("--label", type=str, default="", help="Optional output directory name override for a single variant.")
    parser.add_argument("--set", action="append", dest="set_items", help="Extra simulation override as KEY=VALUE. Repeat as needed.")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    args = parser.parse_args()

    if args.list:
        for key, payload in EXPLORATION_VARIANTS.items():
            print(f"{key}: {payload['title']}")
            print(f"  {payload['description']}")
        return

    variants = args.variant or [next(iter(EXPLORATION_VARIANTS.keys()))]
    if args.label and len(variants) > 1:
        raise ValueError("--label can only be used when running a single exploration variant.")
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    extra_overrides = _parse_override_assignments(getattr(args, "set_items", None))

    for variant_key in variants:
        run_variant_once(
            variant_key,
            num_runs=int(args.num_runs),
            seed_start=int(args.seed_start),
            t_end=float(args.t_end),
            dt=float(args.dt),
            nx=int(args.nx),
            ny=int(args.ny),
            time_metrics_period_s=float(args.time_metrics_period_s),
            output_root=str(args.output_root),
            output_name=(str(args.label) if args.label else None),
            extra_overrides=extra_overrides,
            quiet=bool(args.quiet),
            emit_logs=True,
        )


if __name__ == "__main__":
    main()
