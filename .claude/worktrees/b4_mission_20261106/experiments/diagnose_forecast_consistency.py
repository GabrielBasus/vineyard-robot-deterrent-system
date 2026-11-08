"""
diagnose_forecast_consistency.py -- Proposal §2 forecast-correction diagnostic.

Runs a short simulation with seeds 200-204 (development seeds) and collects
stl_travel_recovery_delta across all candidate evaluations.  Prints distribution
statistics and Kendall-tau rank correlation of candidate rankings before vs
after the travel-recovery correction.

Usage:
    python -m experiments.diagnose_forecast_consistency [--num-runs N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import math
import statistics as stats

import DeterrentSystem as ds


SEED_START = 200
DEV_SEEDS = 5  # seeds 200-204


def _run_seed(seed: int, stl_forecast_correction: bool) -> list[dict]:
    """Run one seed and return per-step candidate STL diagnostics."""
    records = []
    for frame in ds.run_simulation_frames_persistent(
        W=500.0, H=500.0, NX=60, NY=48, Nrobots=4,
        T_end=600.0, dt=1.0, fps=1,
        task_replan_period_s=45.0,
        arrival_radius_m=3.0, hold_time_s=20.0,
        mu_true=2e-5, alpha_true=0.3, beta_true=0.25,
        sigma_true=12.0, omega_true=600.0,
        planner_profile="thesis_calibrated_selective_proposed",
        use_split_task_extraction_selection_pipeline=True,
        preassignment_selection_policy="pass_through",
        enable_predictive_lead_time=True,
        predictive_lead_time_min_s=30.0,
        predictive_lead_time_max_eta_s=120.0,
        predictive_lead_time_buffer_s=15.0,
        predictive_lead_time_risk_power=1.0,
        report_metrics_end=False,
        telemetry_clear_on_start=False,
        telemetry_prompt_save=False,
        warmup_s=120.0,
        stl_E_star=5.0, stl_T_cov_s=1200.0, stl_W_s=600.0,
        stl_eta_min=0.4, stl_horizon_s=300.0, stl_theta=12.0,
        habituation_kappa=0.5, reservation_fraction=0.25,
        simulation_mode="proposed",
        enable_patrolling=True,
        enable_intervention_feedback=True,
        include_fallback_patrol=True,
        enable_model_scored_deterring=True,
        dispatch_policy="res",
        reservation_window_s=600.0,
        reactive_override_slack_s=90.0,
        predictive_selection_policy="utility",
        predictive_fixed_deterring_mode=None,
        predictive_utility_mode="stl_robustness",
        stl_active_clauses=("exp", "cov", "hab"),
        stl_forecast_correction=stl_forecast_correction,
        enable_habituation=True,
        seed=seed,
    ):
        # Collect per-candidate stl diagnostics from active task lists.
        tasks = (frame.get("active_tasks") or [])
        for task in tasks:
            delta = task.get("stl_travel_recovery_delta")
            eta_now = task.get("stl_eta_at_apply")
            if delta is not None and eta_now is not None:
                try:
                    records.append({
                        "seed": seed,
                        "stl_travel_recovery_delta": float(delta),
                        "stl_eta_at_apply": float(eta_now),
                    })
                except (TypeError, ValueError):
                    pass
    return records


def _kendall_tau(rank_a: list[int], rank_b: list[int]) -> float:
    """Kendall-tau rank correlation."""
    n = len(rank_a)
    if n < 2:
        return float("nan")
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            da = rank_a[i] - rank_a[j]
            db = rank_b[i] - rank_b[j]
            sign = da * db
            if sign > 0:
                concordant += 1
            elif sign < 0:
                discordant += 1
    total = n * (n - 1) // 2
    return (concordant - discordant) / total if total > 0 else float("nan")


def run(args: argparse.Namespace) -> None:
    print(f"[diag] collecting diagnostics over {args.num_runs} seed(s) "
          f"({args.seed_start}-{args.seed_start + args.num_runs - 1})", flush=True)

    all_deltas: list[float] = []
    all_eta_now_a: list[float] = []  # eta_now (variant A readout)
    all_eta_corrected_b: list[float] = []  # eta_at_apply with correction (variant B readout)

    for seed in range(args.seed_start, args.seed_start + args.num_runs):
        print(f"[diag] seed={seed} variant_A ...", flush=True)
        recs_a = _run_seed(seed, stl_forecast_correction=False)
        print(f"[diag] seed={seed} variant_B ...", flush=True)
        recs_b = _run_seed(seed, stl_forecast_correction=True)

        for r in recs_a:
            all_eta_now_a.append(r["stl_eta_at_apply"])
        for r in recs_b:
            all_deltas.append(r["stl_travel_recovery_delta"])
            all_eta_corrected_b.append(r["stl_eta_at_apply"])

    print("\n=== stl_travel_recovery_delta distribution (variant B) ===")
    finite_d = [d for d in all_deltas if math.isfinite(d)]
    if finite_d:
        print(f"  n      = {len(finite_d)}")
        print(f"  mean   = {stats.mean(finite_d):.4f}")
        print(f"  stdev  = {stats.stdev(finite_d):.4f}" if len(finite_d) > 1 else "  stdev  = n/a")
        print(f"  min    = {min(finite_d):.4f}")
        print(f"  max    = {max(finite_d):.4f}")
        print(f"  > 0.01 = {sum(1 for d in finite_d if d > 0.01)} ({100*sum(1 for d in finite_d if d > 0.01)/len(finite_d):.1f}%)")
    else:
        print("  (no finite deltas collected -- check task dict keys)")

    print("\n=== stl_eta_at_apply comparison ===")
    n_a = len([x for x in all_eta_now_a if math.isfinite(x)])
    n_b = len([x for x in all_eta_corrected_b if math.isfinite(x)])
    if n_a:
        print(f"  variant A mean eta_at_apply = {stats.mean(x for x in all_eta_now_a if math.isfinite(x)):.4f}  (n={n_a})")
    if n_b:
        print(f"  variant B mean eta_at_apply = {stats.mean(x for x in all_eta_corrected_b if math.isfinite(x)):.4f}  (n={n_b})")

    # Kendall-tau on eta_at_apply values (proxy for ranking change).
    min_n = min(len(all_eta_now_a), len(all_eta_corrected_b))
    if min_n >= 2:
        rank_a = sorted(range(min_n), key=lambda i: all_eta_now_a[i])
        rank_b = sorted(range(min_n), key=lambda i: all_eta_corrected_b[i])
        tau = _kendall_tau(rank_a, rank_b)
        print(f"\n  Kendall-tau (A vs B ranking) = {tau:.4f}  (1.0 = identical, -1.0 = reversed)")
    else:
        print("\n  (insufficient data for Kendall-tau)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Forecast consistency diagnostic.")
    parser.add_argument("--seed-start", type=int, default=SEED_START)
    parser.add_argument("--num-runs", type=int, default=DEV_SEEDS)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
