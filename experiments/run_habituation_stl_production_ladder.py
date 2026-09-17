from __future__ import annotations

import argparse
import csv
import json
import math
import random as _random
import statistics as stats
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))



DEFAULT_DETERRING_MODES = {
    "formation": {"beta": 0.30, "omega": 800.0, "sigma": 18.0, "w_eta": 1.0, "fixed_cost": 0.0},
    "laser": {"beta": 0.45, "omega": 400.0, "sigma": 10.0, "w_eta": 1.5, "fixed_cost": 0.0},
    "biosonic": {"beta": 0.25, "omega": 600.0, "sigma": 20.0, "w_eta": 1.2, "fixed_cost": 0.0},
}


def _scaled_deterring_modes(args: argparse.Namespace) -> dict[str, dict[str, float]]:
    beta_scale = float(args.deterrence_beta_scale)
    sigma_scale = float(args.deterrence_sigma_scale)
    omega_scale = float(args.deterrence_omega_scale)
    modes: dict[str, dict[str, float]] = {}
    for mode, params in DEFAULT_DETERRING_MODES.items():
        scaled = dict(params)
        scaled["beta"] = float(params["beta"]) * beta_scale
        scaled["sigma"] = float(params["sigma"]) * sigma_scale
        scaled["omega"] = float(params["omega"]) * omega_scale
        modes[str(mode)] = scaled
    return modes

METRIC_FIELDS = [
    "value_weighted_exposure",
    "mean_response_time_s",
    "reactive_mean_response_time_s",
    "response_samples",
    "completed_tasks_total",
    "reactive_completed_total",
    "predictive_completed_total",
    "predictive_generated_total",
    "predictive_admitted_total",
    "reactive_completed_fraction",
    "predictive_completed_fraction",
    "predictive_completion_ratio",
    "predictive_expired_total",
    "predictive_expired_fraction",
    "predictive_deadline_feasible_total",
    "predictive_deadline_checked_total",
    "predictive_deadline_feasible_fraction",
    "travel_distance_total",
    "tasks_per_unit_distance",
    "exposure_per_completed_task",
    "zone_repartition_total",
    "health_retirement_total",
    "health_return_total",
    "active_robot_count",
    "retired_robot_count",
    "truth_candidate_events",
    "truth_accepted_events",
    "truth_suppressed_events",
    "truth_suppression_rate",
    "truth_suppression_effect_mean",
    "truth_suppression_effect_sum",
    "birds_deterred_pct",
    "habituation_eta_mean",
    "habituation_eta_min",
    "planner_habituation_eta_mean",
    "planner_habituation_eta_min",
    "habituation_eta_at_apply_mean",
    "habituation_variety_index",
    "stl_robustness_global_mean",
    "stl_robustness_global_min",
    "stl_robustness_exp",
    "stl_robustness_cov",
    "stl_robustness_hab",
]


def _common_params(args: argparse.Namespace) -> dict[str, Any]:
    params = {
        "W": 500.0,
        "H": 500.0,
        "NX": int(args.nx),
        "NY": int(args.ny),
        "Nrobots": int(args.nrobots),
        "T_end": float(args.duration_s),
        "dt": 1.0,
        "fps": 1,
        "task_replan_period_s": float(args.task_replan_period_s),
        "arrival_radius_m": 3.0,
        "hold_time_s": 20.0,
        "mu_true": float(args.mu_true),
        "alpha_true": float(args.alpha_true),
        "beta_true": float(args.beta_true) * float(args.deterrence_beta_scale),
        "sigma_true": float(args.sigma_true) * float(args.deterrence_sigma_scale),
        "omega_true": float(args.omega_true) * float(args.deterrence_omega_scale),
        "deterring_modes": _scaled_deterring_modes(args),
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
        "warmup_s": float(args.warmup_s),
        "stl_E_star": float(args.stl_e_star),
        "stl_T_cov_s": float(args.stl_t_cov_s),
        "stl_W_s": float(args.stl_w_s),
        "stl_eta_min": float(args.stl_eta_min),
        "stl_horizon_s": float(args.stl_horizon_s),
        "stl_theta": float(args.stl_theta),
    }
    optional_mismatch_args = {
        "truth_habituation_T_rec_s": args.truth_habituation_t_rec_s,
        "truth_habituation_kappa": args.truth_habituation_kappa,
        "truth_habituation_gamma": args.truth_habituation_gamma,
        "truth_habituation_update_model": args.truth_habituation_update_model,
        "planner_habituation_T_rec_s": args.planner_habituation_t_rec_s,
        "planner_habituation_kappa": args.planner_habituation_kappa,
        "planner_habituation_gamma": args.planner_habituation_gamma,
        "planner_habituation_update_model": args.planner_habituation_update_model,
    }
    for key, value in optional_mismatch_args.items():
        if value is not None:
            params[key] = value
    return params


def _proposed_generation_params() -> dict[str, Any]:
    return {
        "simulation_mode": "proposed",
        "enable_patrolling": True,
        "enable_intervention_feedback": True,
        "include_fallback_patrol": True,
        "enable_model_scored_deterring": True,
    }


def _reserved_dispatch_params(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "dispatch_policy": "res",
        "reservation_fraction": float(args.reservation_fraction),
        "reservation_window_s": 600.0,
        "reactive_override_slack_s": 90.0,
        "predictive_selection_policy": "utility",
    }


def _fixed_cue_params(args: argparse.Namespace) -> dict[str, Any]:
    return {"predictive_fixed_deterring_mode": str(args.fixed_cue_mode)}


def _system_params(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    reserved = _reserved_dispatch_params(args)
    proposed = _proposed_generation_params()
    fixed_cue = _fixed_cue_params(args)
    return {
        "B0_reactive": {
            "simulation_mode": "reactive",
            "enable_patrolling": False,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": False,
            "enable_model_scored_deterring": False,
            "dispatch_policy": "react",
            "predictive_utility_mode": "legacy",
        },
        "B1_greedy_fixedcue": {
            **proposed,
            **fixed_cue,
            "dispatch_policy": "unc",
            "predictive_utility_mode": "legacy",
        },
        "B2_res_deltaJ_fixedcue": {
            **proposed,
            **reserved,
            **fixed_cue,
            "predictive_utility_mode": "deltaJ",
        },
        "B3_res_stl_nohab_multicue": {
            **proposed,
            **reserved,
            "predictive_fixed_deterring_mode": None,
            "predictive_utility_mode": "stl_robustness",
            "stl_active_clauses": ("exp", "cov"),
        },
        "B4_res_stl_full_multicue": {
            **proposed,
            **reserved,
            "predictive_fixed_deterring_mode": None,
            "predictive_utility_mode": "stl_robustness",
            "stl_active_clauses": ("exp", "cov", "hab"),
        },
        "B5_greedy_habcue": {
            **proposed,
            "dispatch_policy": "unc",
            "predictive_fixed_deterring_mode": None,
            "predictive_utility_mode": "legacy_habituation",
        },
        "B5_res_habcue_multicue": {
            **proposed,
            **reserved,
            "predictive_fixed_deterring_mode": None,
            "predictive_utility_mode": "legacy_habituation",
        },
    }


def _habituation_params(enabled: bool, args: argparse.Namespace) -> dict[str, Any]:
    if enabled:
        return {
            "habituation_condition": "hab_on",
            "enable_habituation": True,
            "habituation_kappa": float(args.habituation_kappa),
        }
    return {
        "habituation_condition": "hab_off",
        "enable_habituation": False,
        "habituation_kappa": 0.0,
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def _run_one(job: dict[str, Any]) -> dict[str, Any]:
    import DeterrentSystem as ds

    params = dict(job["params"])
    params.pop("habituation_condition", None)
    params["seed"] = int(job["seed"])
    started = time.time()
    last = None
    for frame in ds.run_simulation_frames_persistent(**params):
        last = frame
    elapsed = time.time() - started
    metrics = (last or {}).get("metrics_compact") or (last or {}).get("metrics") or {}
    row = {
        "system": str(job["system"]),
        "baseline": str(job["baseline"]),
        "habituation_condition": str(job["habituation_condition"]),
        "seed": int(job["seed"]),
        "elapsed_s": float(elapsed),
    }
    for field in METRIC_FIELDS:
        row[field] = _safe_float(metrics.get(field))
    return row


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    # Union of all keys in insertion order so that rows with different
    # schema versions (e.g. old 10-seed rows merged with newer 20-seed rows)
    # all write cleanly.  Old rows missing a new field get an empty string
    # via restval; new rows with extra fields are included rather than raising.
    seen: set[str] = set()
    fields: list[str] = []
    for row in rows:
        for k in row:
            if k not in seen:
                fields.append(k)
                seen.add(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, restval="")
        writer.writeheader()
        writer.writerows(rows)


def _finite_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    vals = []
    for row in rows:
        value = _safe_float(row.get(field))
        if math.isfinite(value):
            vals.append(value)
    return vals


def _summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["baseline"]), str(row["habituation_condition"]))
        groups.setdefault(key, []).append(row)

    out = []
    for (baseline, hab), sub in sorted(groups.items()):
        summary: dict[str, Any] = {
            "baseline": baseline,
            "habituation_condition": hab,
            "n": len(sub),
        }
        for field in METRIC_FIELDS:
            vals = _finite_values(sub, field)
            summary[f"{field}_mean"] = float(stats.mean(vals)) if vals else float("nan")
            summary[f"{field}_sd"] = float(stats.pstdev(vals)) if len(vals) > 1 else 0.0
        out.append(summary)
    return out


def _advantage_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        (str(row["baseline"]), str(row["habituation_condition"]), int(row["seed"])): row
        for row in rows
    }
    out = []
    comparisons = [
        ("H1_B4_vs_B1", "B4_res_stl_full_multicue", "B1_greedy_fixedcue", "value_weighted_exposure", "lower"),
        ("H2_B4_vs_B3", "B4_res_stl_full_multicue", "B3_res_stl_nohab_multicue", "value_weighted_exposure", "lower"),
        ("H3_B3_vs_B2", "B3_res_stl_nohab_multicue", "B2_res_deltaJ_fixedcue", "value_weighted_exposure", "lower"),
        ("H4_B5_vs_B1", "B5_greedy_habcue", "B1_greedy_fixedcue", "value_weighted_exposure", "lower"),
        ("H5_B4_vs_B5", "B4_res_stl_full_multicue", "B5_greedy_habcue", "value_weighted_exposure", "lower"),
        (
            "robustness_B4_vs_B3",
            "B4_res_stl_full_multicue",
            "B3_res_stl_nohab_multicue",
            "stl_robustness_global_mean",
            "higher",
        ),
    ]
    for hab in ("hab_on", "hab_off"):
        seeds = sorted({int(row["seed"]) for row in rows if row["habituation_condition"] == hab})
        for label, system, reference, metric, goal in comparisons:
            deltas = []
            for seed in seeds:
                srow = by_key.get((system, hab, seed))
                rrow = by_key.get((reference, hab, seed))
                if srow is None or rrow is None:
                    continue
                sval = _safe_float(srow.get(metric))
                rval = _safe_float(rrow.get(metric))
                if not math.isfinite(sval) or not math.isfinite(rval):
                    continue
                den = abs(rval) if abs(rval) > 1e-12 else float("nan")
                if not math.isfinite(den):
                    continue
                if goal == "lower":
                    delta = 100.0 * (rval - sval) / den
                else:
                    delta = 100.0 * (sval - rval) / den
                deltas.append(delta)
            out.append(
                {
                    "comparison": label,
                    "habituation_condition": hab,
                    "system": system,
                    "reference": reference,
                    "metric": metric,
                    "goal": goal,
                    "paired_seed_count": len(deltas),
                    "advantage_pct_mean": float(stats.mean(deltas)) if deltas else float("nan"),
                    "advantage_pct_sd": float(stats.pstdev(deltas)) if len(deltas) > 1 else 0.0,
                }
            )
    return out



def _habituation_delta_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        (str(row["baseline"]), str(row["habituation_condition"]), int(row["seed"])): row
        for row in rows
    }
    baselines = sorted({str(row["baseline"]) for row in rows})
    seeds_by_baseline = {
        baseline: sorted({int(row["seed"]) for row in rows if str(row["baseline"]) == baseline})
        for baseline in baselines
    }
    out = []
    for baseline in baselines:
        seeds = seeds_by_baseline[baseline]
        for metric in METRIC_FIELDS:
            paired = []
            on_vals = []
            off_vals = []
            for seed in seeds:
                on_row = by_key.get((baseline, "hab_on", seed))
                off_row = by_key.get((baseline, "hab_off", seed))
                if on_row is None or off_row is None:
                    continue
                on_val = _safe_float(on_row.get(metric))
                off_val = _safe_float(off_row.get(metric))
                if not math.isfinite(on_val) or not math.isfinite(off_val):
                    continue
                on_vals.append(on_val)
                off_vals.append(off_val)
                paired.append(on_val - off_val)
            if not paired:
                continue
            off_mean = float(stats.mean(off_vals))
            on_mean = float(stats.mean(on_vals))
            delta_mean = float(stats.mean(paired))
            denom = abs(off_mean) if abs(off_mean) > 1e-12 else float("nan")
            out.append(
                {
                    "baseline": baseline,
                    "metric": metric,
                    "paired_seed_count": len(paired),
                    "hab_off_mean": off_mean,
                    "hab_on_mean": on_mean,
                    "delta_on_minus_off_mean": delta_mean,
                    "delta_on_minus_off_sd": float(stats.pstdev(paired)) if len(paired) > 1 else 0.0,
                    "pct_delta_on_minus_off": (100.0 * delta_mean / denom) if math.isfinite(denom) else float("nan"),
                }
            )
    return out


def _first_baseline(rows: list[dict[str, Any]], candidates: list[str]) -> str | None:
    """Return the first candidate baseline name present in the run rows."""
    present = {str(row.get("baseline")) for row in rows}
    for candidate in candidates:
        if candidate in present:
            return candidate
    return None


def _paired_deltas(
    rows: list[dict[str, Any]],
    system: str,
    reference: str,
    habituation_condition: str,
    metric: str,
) -> list[float]:
    """Compute paired `system - reference` metric deltas over matching seeds."""
    by_key = {
        (str(row["baseline"]), str(row["habituation_condition"]), int(row["seed"])): row
        for row in rows
    }
    seeds = sorted(
        {
            int(row["seed"])
            for row in rows
            if str(row.get("habituation_condition")) == str(habituation_condition)
        }
    )
    deltas: list[float] = []
    for seed in seeds:
        srow = by_key.get((system, habituation_condition, seed))
        rrow = by_key.get((reference, habituation_condition, seed))
        if srow is None or rrow is None:
            continue
        sval = _safe_float(srow.get(metric))
        rval = _safe_float(rrow.get(metric))
        if math.isfinite(sval) and math.isfinite(rval):
            deltas.append(sval - rval)
    return deltas


def _ci95(values: list[float]) -> tuple[float, float]:
    """Return a two-sided 95% Student-t confidence interval for paired deltas."""
    if not values:
        return float("nan"), float("nan")
    mean = float(stats.mean(values))
    if len(values) <= 1:
        return mean, mean
    t_critical_95 = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        11: 2.201,
        12: 2.179,
        13: 2.160,
        14: 2.145,
        15: 2.131,
        16: 2.120,
        17: 2.110,
        18: 2.101,
        19: 2.093,
        20: 2.086,
        21: 2.080,
        22: 2.074,
        23: 2.069,
        24: 2.064,
        25: 2.060,
        26: 2.056,
        27: 2.052,
        28: 2.048,
        29: 2.045,
        30: 2.042,
    }
    df = len(values) - 1
    critical = t_critical_95.get(df, 1.96)
    half_width = critical * float(stats.stdev(values)) / math.sqrt(len(values))
    return mean - half_width, mean + half_width


def _bootstrap_ci95(
    values: list[float], n_boot: int = 9999, rng_seed: int = 0
) -> tuple[float, float]:
    """Percentile bootstrap 95% CI for the mean of *values*."""
    if not values:
        return float("nan"), float("nan")
    if len(values) == 1:
        v = float(values[0])
        return v, v
    rng = _random.Random(rng_seed)
    n = len(values)
    boot_means: list[float] = sorted(
        sum(values[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(n_boot)
    )
    lo = boot_means[int(0.025 * n_boot)]
    hi = boot_means[min(int(0.975 * n_boot), n_boot - 1)]
    return lo, hi


def _wilcoxon_signed_rank(
    deltas: list[float],
) -> tuple[float, float, int]:
    """Two-sided Wilcoxon signed-rank test against H0: median(delta)=0.

    Returns (W, p_value, n_nonzero).  Uses normal approximation with
    continuity correction and tie-corrected variance.  Valid for n >= 4;
    returns p=1.0 for degenerate inputs.
    """
    nonzero = [d for d in deltas if d != 0.0]
    n = len(nonzero)
    if n < 4:
        return 0.0, 1.0, n
    # Sort by |d|, record sign
    pairs = sorted(((abs(d), 1 if d > 0 else -1) for d in nonzero), key=lambda x: x[0])
    # Assign average ranks (tie groups get the same average rank)
    ranked: list[tuple[int, float]] = []
    i = 0
    while i < n:
        j = i
        while j < n and pairs[j][0] == pairs[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0  # 1-indexed midpoint
        for k in range(i, j):
            ranked.append((pairs[k][1], avg))
        i = j
    w_plus = sum(r for s, r in ranked if s > 0)
    w_minus = sum(r for s, r in ranked if s < 0)
    w_stat = min(w_plus, w_minus)
    # Tie-corrected variance
    tie_sizes = Counter(p[0] for p in pairs).values()
    tie_corr = sum(t * (t - 1) * (t + 1) for t in tie_sizes) / 48.0
    var_w = n * (n + 1) * (2 * n + 1) / 24.0 - tie_corr
    if var_w <= 0:
        return w_stat, 1.0, n
    mu_w = n * (n + 1) / 4.0
    z = (w_stat - mu_w + 0.5) / math.sqrt(var_w)  # continuity-corrected
    # Two-tailed p via erfc (no extra import needed; math.erfc is stdlib)
    p_one = 0.5 * math.erfc(-z / math.sqrt(2.0))
    p_val = min(1.0, 2.0 * min(p_one, 1.0 - p_one))
    return w_stat, p_val, n


def _paired_deltas_pct(
    rows: list[dict[str, Any]],
    system: str,
    reference: str,
    habituation_condition: str,
    metric: str,
) -> list[float]:
    """Like _paired_deltas but returns 100*(system - ref)/ref for each seed."""
    by_key = {
        (str(row["baseline"]), str(row["habituation_condition"]), int(row["seed"])): row
        for row in rows
    }
    seeds = sorted(
        {
            int(row["seed"])
            for row in rows
            if str(row.get("habituation_condition")) == str(habituation_condition)
        }
    )
    pcts: list[float] = []
    for seed in seeds:
        srow = by_key.get((system, habituation_condition, seed))
        rrow = by_key.get((reference, habituation_condition, seed))
        if srow is None or rrow is None:
            continue
        sval = _safe_float(srow.get(metric))
        rval = _safe_float(rrow.get(metric))
        if math.isfinite(sval) and math.isfinite(rval) and rval != 0.0:
            pcts.append(100.0 * (sval - rval) / rval)
    return pcts


def _fmt(value: Any, digits: int = 3) -> str:
    """Format finite floats while keeping missing values explicit in Markdown."""
    fval = _safe_float(value)
    if not math.isfinite(fval):
        return "n/a"
    return f"{fval:.{digits}f}"


def _comparison_row(
    rows: list[dict[str, Any]],
    label: str,
    system: str | None,
    reference: str | None,
    habituation_condition: str,
    metric: str,
    lower_is_better: bool,
) -> str | None:
    """Build one Markdown table row for a paired metric comparison."""
    if system is None or reference is None:
        return None
    deltas = _paired_deltas(rows, system, reference, habituation_condition, metric)
    if not deltas:
        return None
    mean_delta = float(stats.mean(deltas))
    pct_deltas = _paired_deltas_pct(rows, system, reference, habituation_condition, metric)
    mean_pct = float(stats.mean(pct_deltas)) if pct_deltas else float("nan")
    boot_lo, boot_hi = _bootstrap_ci95(pct_deltas) if pct_deltas else (float("nan"), float("nan"))
    w_stat, p_val, _n_nz = _wilcoxon_signed_rank(deltas)
    if lower_is_better:
        improved = sum(1 for delta in deltas if delta < 0.0)
    else:
        improved = sum(1 for delta in deltas if delta > 0.0)
    pct_str = f"{mean_pct:+.1f}%" if math.isfinite(mean_pct) else "n/a"
    ci_str = (
        f"[{boot_lo:+.1f}%, {boot_hi:+.1f}%]"
        if math.isfinite(boot_lo) and math.isfinite(boot_hi)
        else "n/a"
    )
    p_str = f"{p_val:.3f}" if math.isfinite(p_val) else "n/a"
    w_str = f"{w_stat:.0f}" if math.isfinite(w_stat) else "n/a"
    return (
        f"| {label} | {habituation_condition} | {_fmt(mean_delta)} | "
        f"{pct_str} | {ci_str} | {w_str} | {p_str} | {improved}/{len(deltas)} |"
    )


def _metric_delta_row(
    rows: list[dict[str, Any]],
    label: str,
    system: str | None,
    reference: str | None,
    metric: str,
) -> str | None:
    """Build one mechanism-metric row for B4 minus B3 under habituating truth."""
    if system is None or reference is None:
        return None
    deltas = _paired_deltas(rows, system, reference, "hab_on", metric)
    if not deltas:
        return None
    mean_delta = float(stats.mean(deltas))
    ci_lo, ci_hi = _ci95(deltas)
    return f"| {label} | {_fmt(mean_delta, 4)} | [{_fmt(ci_lo, 4)}, {_fmt(ci_hi, 4)}] |"


def _write_markdown_summary(rows: list[dict[str, Any]], outdir: Path) -> None:
    """Write a thesis-facing Markdown recap next to the ladder CSV outputs."""
    if not rows:
        return

    manifest_path = outdir / "ladder_manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    args = manifest.get("args", {}) if isinstance(manifest.get("args", {}), dict) else {}

    b1 = _first_baseline(rows, ["B1_greedy_fixedcue", "B1_unc_legacy"])
    b2 = _first_baseline(rows, ["B2_res_deltaJ_fixedcue", "B2_res_deltaJ"])
    b3 = _first_baseline(rows, ["B3_res_stl_nohab_multicue", "B3_res_stl_nohab_fixedcue", "B3_res_stl_nohab"])
    b4 = _first_baseline(rows, ["B4_res_stl_full_multicue", "B4_res_stl_full"])
    b5 = _first_baseline(rows, ["B5_greedy_habcue"])

    paired_counts = [
        len(_paired_deltas(rows, b4, ref, "hab_on", "value_weighted_exposure"))
        for ref in (b1, b3)
        if b4 is not None and ref is not None
    ]
    max_paired = max(paired_counts) if paired_counts else 0
    status = "confirmatory" if max_paired >= 10 else "preliminary"

    systems = ", ".join(sorted({str(row["baseline"]) for row in rows}))
    seed_values = sorted({int(row["seed"]) for row in rows})
    seed_span = f"{seed_values[0]} through {seed_values[-1]}" if seed_values else "n/a"

    lines = [
        "# Habituation STL Ladder Results",
        "",
        f"Source run: `{outdir.as_posix()}`.",
        "",
        "## Run Configuration",
        "",
        f"- Status: `{status}`",
        f"- Duration: `{_fmt(args.get('duration_s'))}` seconds",
        f"- Seeds: `{seed_span}`",
        f"- Systems: `{systems}`",
        f"- Jobs completed: `{len(rows)}` raw rows",
        f"- Grid/fleet: `nx={args.get('nx', 'n/a')}`, `ny={args.get('ny', 'n/a')}`, `nrobots={args.get('nrobots', 'n/a')}`",
        f"- Truth rate: `mu_true={args.get('mu_true', 'n/a')}`",
        f"- Habituation kappa: `habituation_kappa={args.get('habituation_kappa', 'n/a')}`",
        "",
        "## Primary Paired Exposure Results",
        "",
        "| Comparison | Truth control | Mean ΔJexp | Δ̄% | 95% Boot CI% | W | p | Seeds ↓ |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    comparison_rows = [
        _comparison_row(
            rows,
            "B4 - B1",
            b4,
            b1,
            "hab_on",
            "value_weighted_exposure",
            lower_is_better=True,
        ),
        _comparison_row(
            rows,
            "B4 - B3",
            b4,
            b3,
            "hab_on",
            "value_weighted_exposure",
            lower_is_better=True,
        ),
        _comparison_row(
            rows,
            "B4 - B3",
            b4,
            b3,
            "hab_off",
            "value_weighted_exposure",
            lower_is_better=True,
        ),
        _comparison_row(
            rows,
            "B3 - B2",
            b3,
            b2,
            "hab_on",
            "value_weighted_exposure",
            lower_is_better=True,
        ),
        _comparison_row(
            rows,
            "B5 - B1",
            b5,
            b1,
            "hab_on",
            "value_weighted_exposure",
            lower_is_better=True,
        ),
        _comparison_row(
            rows,
            "B4 - B5",
            b4,
            b5,
            "hab_on",
            "value_weighted_exposure",
            lower_is_better=True,
        ),
    ]
    lines.extend(row for row in comparison_rows if row is not None)
    lines.extend(
        [
            "",
            "Negative exposure deltas are better because lower value-weighted exposure is the desired outcome.",
            "Δ̄% = mean per-seed percentage improvement over reference. 95% Boot CI%: percentile bootstrap "
            "(9999 resamples) of the mean percentage. W: Wilcoxon signed-rank statistic (two-sided, normal "
            "approximation with tie correction and continuity correction). p: two-tailed p-value.",
            "",
            "## Mechanism Evidence: B4 - B3 Under Habituation On",
            "",
            "| Metric | Mean delta | 95% CI |",
            "|---|---:|---:|",
        ]
    )
    metric_rows = [
        _metric_delta_row(rows, "Truth suppression rate", b4, b3, "truth_suppression_rate"),
        _metric_delta_row(rows, "Truth suppression effect sum", b4, b3, "truth_suppression_effect_sum"),
        _metric_delta_row(rows, "Eta at apply", b4, b3, "habituation_eta_at_apply_mean"),
        _metric_delta_row(rows, "Variety index", b4, b3, "habituation_variety_index"),
    ]
    lines.extend(row for row in metric_rows if row is not None)
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "B4 is the proposal system with the full exposure, coverage, and habituation STL clauses and multi-cue action variants. B3 uses the same multi-cue dispatch and reserved structure but removes the habituation STL clause, so B4 - B3 isolates the effect of habituation-aware STL planning while controlling for cue mode. B5 keeps B1's unconstrained exposure-greedy dispatch but lets the legacy exposure value choose cues using current habituation effectiveness, so B4 - B5 tests whether STL constraint enforcement adds value beyond a simple cue-rotation heuristic. The B4/B3 hab_off control must be near zero because the only difference between them under no habituation is the inactive habituation clause.",
        ]
    )
    if status == "preliminary":
        lines.extend(
            [
                "",
                "This run is preliminary because it has fewer than 10 paired seeds. Use it for debugging and calibration, not as the final thesis claim.",
            ]
        )
    lines.extend(
        [
            "",
            "## Source Tables",
            "",
            "- `per_run_metrics.csv`",
            "- `summary_by_system.csv`",
            "- `advantage_vs_reference.csv`",
            "- `habituation_on_vs_off.csv`",
        ]
    )

    (outdir / "THESIS_RESULTS_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
def _build_jobs(args: argparse.Namespace) -> list[dict[str, Any]]:
    common = _common_params(args)
    systems = _system_params(args)
    selected_config_overrides = getattr(args, "selected_config_overrides", None) or {}
    aliases = {
        "B1_unc_legacy": "B1_greedy_fixedcue",
        "B2_res_deltaJ": "B2_res_deltaJ_fixedcue",
        "B3_res_stl_nohab": "B3_res_stl_nohab_multicue",
        "B3_res_stl_nohab_fixedcue": "B3_res_stl_nohab_multicue",
        "B4_res_stl_full": "B4_res_stl_full_multicue",
        "B5_greedy_habcue": "B5_greedy_habcue",
        "B5_res_habcue_multicue": "B5_res_habcue_multicue",
    }
    wanted = {
        aliases.get(str(name), str(name))
        for name in (args.systems or systems.keys())
    }
    jobs = []
    for seed in range(int(args.seed_start), int(args.seed_start) + int(args.num_runs)):
        for baseline, sys_params in systems.items():
            if baseline not in wanted:
                continue
            for hab_enabled in (True, False):
                hab_params = _habituation_params(hab_enabled, args)
                params = dict(common)
                params.update(sys_params)
                params.update(dict(selected_config_overrides.get(baseline, {})))
                params.update(hab_params)
                system = f"{baseline}_{hab_params['habituation_condition']}"
                jobs.append(
                    {
                        "system": system,
                        "baseline": baseline,
                        "habituation_condition": hab_params["habituation_condition"],
                        "seed": seed,
                        "params": params,
                    }
                )
    return jobs


def _load_raw_rows(raw_dir: Path) -> list[dict[str, Any]]:
    """Load previously completed raw JSON rows from a ladder output directory."""
    rows = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(row, dict) and {"baseline", "habituation_condition", "seed"} <= set(row):
            rows.append(row)
    return rows


def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    outdir = Path(args.outdir).resolve()
    raw_dir = outdir / "raw"
    outdir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    jobs = _build_jobs(args)
    rows = []
    print(f"[ladder] jobs={len(jobs)} outdir={outdir}", flush=True)
    started = time.time()
    max_workers = max(1, min(int(args.max_workers), len(jobs))) if jobs else 1
    if max_workers == 1:
        for idx, job in enumerate(jobs, start=1):
            print(f"[ladder] start {idx}/{len(jobs)} {job['system']} seed={job['seed']}", flush=True)
            row = _run_one(job)
            rows.append(row)
            (raw_dir / f"{row['system']}_seed_{row['seed']}.json").write_text(
                json.dumps(row, indent=2, allow_nan=True),
                encoding="utf-8",
            )
            print(
                f"[ladder] done {idx}/{len(jobs)} {row['system']} seed={row['seed']} "
                f"elapsed={row['elapsed_s']:.1f}s Jexp={row['value_weighted_exposure']:.3f}",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_run_one, job): job for job in jobs}
            for idx, future in enumerate(as_completed(future_map), start=1):
                job = future_map[future]
                row = future.result()
                rows.append(row)
                (raw_dir / f"{row['system']}_seed_{row['seed']}.json").write_text(
                    json.dumps(row, indent=2, allow_nan=True),
                    encoding="utf-8",
                )
                print(
                    f"[ladder] done {idx}/{len(jobs)} {row['system']} seed={row['seed']} "
                    f"elapsed={row['elapsed_s']:.1f}s Jexp={row['value_weighted_exposure']:.3f}",
                    flush=True,
                )

    if bool(getattr(args, "merge_existing_raw", False)):
        merged_by_key = {
            (str(row["baseline"]), str(row["habituation_condition"]), int(row["seed"])): row
            for row in _load_raw_rows(raw_dir)
        }
        for row in rows:
            merged_by_key[(str(row["baseline"]), str(row["habituation_condition"]), int(row["seed"]))] = row
        rows = list(merged_by_key.values())

    rows = sorted(rows, key=lambda r: (str(r["baseline"]), str(r["habituation_condition"]), int(r["seed"])))
    _write_csv(rows, outdir / "per_run_metrics.csv")
    _write_csv(_summarize(rows), outdir / "summary_by_system.csv")
    _write_csv(_advantage_rows(rows), outdir / "advantage_vs_reference.csv")
    _write_csv(_habituation_delta_rows(rows), outdir / "habituation_on_vs_off.csv")
    (outdir / "ladder_manifest.json").write_text(
        json.dumps(
            {
                "args": vars(args),
                "job_count": len(jobs),
                "elapsed_s": time.time() - started,
                "metric_fields": METRIC_FIELDS,
            },
            indent=2,
            allow_nan=True,
        ),
        encoding="utf-8",
    )
    _write_markdown_summary(rows, outdir)
    print(f"[ladder] wrote {outdir}", flush=True)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run clean B0-B5 habituation/STL production ladder.")
    parser.add_argument("--outdir", default="results/testbench/habituation_stl_production_ladder_short")
    parser.add_argument("--duration-s", type=float, default=900.0)
    parser.add_argument("--num-runs", type=int, default=3)
    parser.add_argument("--seed-start", type=int, default=123)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--nx", type=int, default=120)
    parser.add_argument("--ny", type=int, default=96)
    parser.add_argument("--nrobots", type=int, default=6)
    parser.add_argument("--warmup-s", type=float, default=300.0)
    parser.add_argument("--task-replan-period-s", type=float, default=45.0)
    parser.add_argument("--reservation-fraction", type=float, default=0.25)
    parser.add_argument("--mu-true", type=float, default=1.0e-6)
    parser.add_argument("--alpha-true", type=float, default=0.3)
    parser.add_argument("--beta-true", type=float, default=0.25)
    parser.add_argument("--sigma-true", type=float, default=12.0)
    parser.add_argument("--omega-true", type=float, default=600.0)
    parser.add_argument("--deterrence-beta-scale", type=float, default=1.0)
    parser.add_argument("--deterrence-sigma-scale", type=float, default=1.0)
    parser.add_argument("--deterrence-omega-scale", type=float, default=1.0)
    parser.add_argument("--fixed-cue-mode", default="laser")
    parser.add_argument("--habituation-kappa", type=float, default=0.5)
    parser.add_argument("--truth-habituation-t-rec-s", type=float, default=None)
    parser.add_argument("--truth-habituation-kappa", type=float, default=None)
    parser.add_argument("--truth-habituation-gamma", type=float, default=None)
    parser.add_argument("--truth-habituation-update-model", default=None)
    parser.add_argument("--planner-habituation-t-rec-s", type=float, default=None)
    parser.add_argument("--planner-habituation-kappa", type=float, default=None)
    parser.add_argument("--planner-habituation-gamma", type=float, default=None)
    parser.add_argument("--planner-habituation-update-model", default=None)
    parser.add_argument("--stl-e-star", type=float, default=5.0)
    parser.add_argument("--stl-t-cov-s", type=float, default=1200.0)
    parser.add_argument("--stl-w-s", type=float, default=600.0)
    parser.add_argument("--stl-eta-min", type=float, default=0.4)
    parser.add_argument("--stl-horizon-s", type=float, default=300.0)
    parser.add_argument("--stl-theta", type=float, default=12.0)
    parser.add_argument(
        "--merge-existing-raw",
        action="store_true",
        help=(
            "After running the requested systems, rebuild summary CSV/Markdown from all raw JSON "
            "files already present in --outdir. Use this for B5-only supplemental runs."
        ),
    )
    parser.add_argument(
        "--systems",
        nargs="*",
        default=None,
        help=(
            "Optional subset: B0_reactive B1_greedy_fixedcue "
            "B2_res_deltaJ_fixedcue B3_res_stl_nohab_multicue "
            "B4_res_stl_full_multicue B5_greedy_habcue "
            "B5_res_habcue_multicue. Legacy names are accepted as aliases."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
