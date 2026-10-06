"""
run_variant_ab_comparison.py -- A vs B controlled comparison experiment.

Runs B4_res_stl_full_multicue under two forecast-correction settings:
  variant_A: stl_forecast_correction=False  (original submitted system)
  variant_B: stl_forecast_correction=True   (Proposal §2 corrections)

Uses 30 fresh evaluation seeds (155-184) to keep confirmatory seeds 125-154
frozen as published results.  Both variants run on the same seed set and
identical configuration so the comparison is paired.

Output: results/testbench/variant_ab/
  per_run_metrics.csv, summary_by_system.csv, variant_ab_comparison.md
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics as stats
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Make project root importable when run as a script.
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from experiments.run_habituation_stl_production_ladder import (
    METRIC_FIELDS,
    _run_one,
    _write_csv,
)


SEED_START = 155
SEED_COUNT = 30

# Base simulation config matching the B4 confirmatory setup.
_COMMON = {
    "W": 500.0,
    "H": 500.0,
    "NX": 60,
    "NY": 48,
    "Nrobots": 4,
    "T_end": 1800.0,
    "dt": 1.0,
    "fps": 1,
    "task_replan_period_s": 45.0,
    "arrival_radius_m": 3.0,
    "hold_time_s": 20.0,
    "mu_true": 2e-5,
    "alpha_true": 0.3,
    "beta_true": 0.25,
    "sigma_true": 12.0,
    "omega_true": 600.0,
    "planner_profile": "thesis_calibrated_selective_proposed",
    "use_split_task_extraction_selection_pipeline": True,
    "preassignment_selection_policy": "pass_through",
    "enable_predictive_lead_time": True,
    "predictive_lead_time_min_s": 30.0,
    "predictive_lead_time_max_eta_s": 120.0,
    "predictive_lead_time_buffer_s": 15.0,
    "predictive_lead_time_risk_power": 1.0,
    "report_metrics_end": False,
    "telemetry_clear_on_start": False,
    "telemetry_prompt_save": False,
    "warmup_s": 300.0,
    "stl_E_star": 5.0,
    "stl_T_cov_s": 1200.0,
    "stl_W_s": 600.0,
    "stl_eta_min": 0.4,
    "stl_horizon_s": 300.0,
    "stl_theta": 12.0,
    "habituation_kappa": 0.5,
    "reservation_fraction": 0.25,
}

_B4_SYS = {
    "simulation_mode": "proposed",
    "enable_patrolling": True,
    "enable_intervention_feedback": True,
    "include_fallback_patrol": True,
    "enable_model_scored_deterring": True,
    "dispatch_policy": "res",
    "reservation_fraction": 0.25,
    "reservation_window_s": 600.0,
    "reactive_override_slack_s": 90.0,
    "predictive_selection_policy": "utility",
    "predictive_fixed_deterring_mode": None,
    "predictive_utility_mode": "stl_robustness",
    "stl_active_clauses": ("exp", "cov", "hab"),
}


def _hab_params(enabled: bool) -> dict:
    if enabled:
        return {
            "enable_habituation": True,
            "habituation_condition": "hab_on",
        }
    return {
        "enable_habituation": False,
        "habituation_condition": "hab_off",
    }


def _build_jobs(seed_start: int, seed_count: int) -> list[dict]:
    jobs = []
    for seed in range(seed_start, seed_start + seed_count):
        for variant, forecast_correction in [("variant_A", False), ("variant_B", True)]:
            for hab_enabled in (True, False):
                hab = _hab_params(hab_enabled)
                params = dict(_COMMON)
                params.update(_B4_SYS)
                params.update(hab)
                params["stl_forecast_correction"] = forecast_correction
                system = f"{variant}_{hab['habituation_condition']}"
                jobs.append({
                    "system": system,
                    "baseline": variant,
                    "habituation_condition": hab["habituation_condition"],
                    "seed": seed,
                    "params": params,
                })
    return jobs


def _safe_float(v) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _paired_deltas(rows: list[dict], sys_a: str, sys_b: str, metric: str) -> list[float]:
    """Return B - A deltas for seeds that appear in both systems under hab_on."""
    a_by_seed = {
        r["seed"]: _safe_float(r.get(metric))
        for r in rows
        if r["baseline"] == sys_a and r["habituation_condition"] == "hab_on"
    }
    b_by_seed = {
        r["seed"]: _safe_float(r.get(metric))
        for r in rows
        if r["baseline"] == sys_b and r["habituation_condition"] == "hab_on"
    }
    deltas = []
    for seed in sorted(a_by_seed):
        if seed in b_by_seed:
            a, b = a_by_seed[seed], b_by_seed[seed]
            if math.isfinite(a) and math.isfinite(b):
                deltas.append(b - a)
    return deltas


def _summarize(rows: list[dict]) -> list[dict]:
    from collections import defaultdict
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        key = (row["baseline"], row["habituation_condition"])
        for field in METRIC_FIELDS:
            val = _safe_float(row.get(field))
            if math.isfinite(val):
                groups[key].append((field, val))

    summary = []
    field_by_key: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key = (row["baseline"], row["habituation_condition"])
        for field in METRIC_FIELDS:
            val = _safe_float(row.get(field))
            if math.isfinite(val):
                field_by_key[key][field].append(val)

    for (baseline, hab_cond), fields in field_by_key.items():
        srow = {"baseline": baseline, "habituation_condition": hab_cond,
                "n_seeds": len(rows)}
        for field, vals in fields.items():
            if vals:
                srow[f"{field}_mean"] = stats.mean(vals)
                srow[f"{field}_stdev"] = stats.stdev(vals) if len(vals) > 1 else float("nan")
        summary.append(srow)
    return sorted(summary, key=lambda r: (r["baseline"], r["habituation_condition"]))


def _write_comparison_md(rows: list[dict], outdir: Path) -> None:
    deltas = _paired_deltas(rows, "variant_A", "variant_B", "value_weighted_exposure")
    n = len(deltas)
    if n == 0:
        (outdir / "variant_ab_comparison.md").write_text("No paired data.\n", encoding="utf-8")
        return
    mean_d = stats.mean(deltas)
    mean_pct = mean_d / stats.mean(
        _safe_float(r.get("value_weighted_exposure"))
        for r in rows
        if r["baseline"] == "variant_A" and r["habituation_condition"] == "hab_on"
        and math.isfinite(_safe_float(r.get("value_weighted_exposure")))
    ) * 100.0

    lines = [
        "# Variant A vs B Comparison",
        "",
        "- variant_A: stl_forecast_correction=False (submitted B4)",
        "- variant_B: stl_forecast_correction=True  (Proposal §2 corrections)",
        f"- Seeds: {SEED_START}-{SEED_START + SEED_COUNT - 1} (n={n} paired)",
        "",
        "## Primary Metric: value_weighted_exposure (hab_on)",
        "",
        f"Mean B - A = {mean_d:+.4f} ({mean_pct:+.1f}%)",
        "(negative = variant B lower exposure = improvement)",
        "",
        "## Raw Deltas",
        "",
    ]
    lines += [f"- seed {SEED_START + i}: {d:+.4f}" for i, d in enumerate(deltas)]
    (outdir / "variant_ab_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir).resolve()
    raw_dir = outdir / "raw"
    outdir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    jobs = _build_jobs(int(args.seed_start), int(args.num_runs))
    print(f"[ab] jobs={len(jobs)} outdir={outdir}", flush=True)
    started = time.time()

    rows: list[dict] = []
    max_workers = max(1, min(int(args.max_workers), len(jobs))) if jobs else 1
    if max_workers == 1:
        for idx, job in enumerate(jobs, start=1):
            print(f"[ab] {idx}/{len(jobs)} {job['system']} seed={job['seed']}", flush=True)
            row = _run_one(job)
            rows.append(row)
            (raw_dir / f"{row['system']}_seed_{row['seed']}.json").write_text(
                json.dumps(row, indent=2, allow_nan=True), encoding="utf-8"
            )
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_run_one, job): job for job in jobs}
            for idx, future in enumerate(as_completed(future_map), start=1):
                job = future_map[future]
                row = future.result()
                rows.append(row)
                (raw_dir / f"{row['system']}_seed_{row['seed']}.json").write_text(
                    json.dumps(row, indent=2, allow_nan=True), encoding="utf-8"
                )
                print(
                    f"[ab] done {idx}/{len(jobs)} {row['system']} seed={row['seed']} "
                    f"elapsed={row['elapsed_s']:.1f}s Jexp={row['value_weighted_exposure']:.3f}",
                    flush=True,
                )

    rows.sort(key=lambda r: (r["baseline"], r["habituation_condition"], int(r["seed"])))
    _write_csv(rows, outdir / "per_run_metrics.csv")
    _write_csv(_summarize(rows), outdir / "summary_by_system.csv")
    _write_comparison_md(rows, outdir)
    (outdir / "manifest.json").write_text(
        json.dumps({"elapsed_s": time.time() - started, "seed_start": args.seed_start,
                    "num_runs": args.num_runs}, indent=2),
        encoding="utf-8",
    )
    print(f"[ab] wrote {outdir}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Paired A vs B comparison on seeds 155-184."
    )
    parser.add_argument("--outdir", default="results/testbench/variant_ab")
    parser.add_argument("--num-runs", type=int, default=SEED_COUNT,
                        help="Number of seeds (default 30, starting at --seed-start).")
    parser.add_argument("--seed-start", type=int, default=SEED_START)
    parser.add_argument("--max-workers", type=int, default=1)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
