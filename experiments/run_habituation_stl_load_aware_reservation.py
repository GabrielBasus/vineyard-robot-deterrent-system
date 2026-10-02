from __future__ import annotations

"""Compare load-aware reservation dispatch (res-soft, res-adaptive) against
B1 and B4 (fixed reservation) across load regimes.

The canonical B4 configuration uses a fixed reservation fraction (rho_res=0.25).
At overload (mu=4e-4) B4 falls below B1 (H1 reversal) because res-dispatch
withholds predictive capacity. Two existing load-aware variants dynamically soften
rho_res in proportion to reactive pressure:

  B4_res_soft_multicue:     rho_eff = rho / (1 + alpha * reactive_pressure)
  B4_res_adaptive_multicue: rho_eff = rho / (1 + alpha * reactive_pressure + age_beta * age_norm)

This experiment tests whether dynamic softening recovers the overload reversal
while preserving spare-capacity advantage.
"""

import argparse
import copy
import csv
import math
import statistics as stats
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import experiments.run_habituation_stl_production_ladder as ladder


DEFAULT_MU_VALUES = [2e-5, 1e-4, 4e-4]

DEFAULT_SYSTEMS = [
    "B1_greedy_fixedcue",
    "B4_res_stl_full_multicue",
    "B4_res_soft_multicue",
    "B4_res_adaptive_multicue",
]

_SUMMARY_METRIC = "value_weighted_exposure"
_AUX_METRICS = [
    "habituation_eta_at_apply_mean",
    "habituation_variety_index",
    "truth_suppression_effect_sum",
    "mean_response_time_s",
    "predictive_completion_ratio",
    "predictive_expired_fraction",
    "travel_distance_total",
    "stl_robustness_global_mean",
    "stl_robustness_cov",
]


def _mu_token(mu: float) -> str:
    if mu < 1e-4:
        return f"mu_{int(round(mu * 1e5))}em05"
    return f"mu_{int(round(mu * 1e4))}em04"


def _base_ladder_args(sweep_args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        habituation_kappa=0.5,
        outdir="",
        merge_existing_raw=False,
        mu_true=float(sweep_args.mu_placeholder),  # overridden per iteration
        nx=int(sweep_args.nx),
        ny=int(sweep_args.ny),
        nrobots=int(sweep_args.nrobots),
        duration_s=float(sweep_args.duration_s),
        warmup_s=0.0,
        task_replan_period_s=45.0,
        num_runs=int(sweep_args.num_runs),
        seed_start=int(sweep_args.seed_start),
        max_workers=int(sweep_args.max_workers),
        systems=list(sweep_args.systems),
        selected_config_overrides={},
        reservation_fraction=float(sweep_args.reservation_fraction),
        alpha_true=0.3,
        beta_true=0.25,
        sigma_true=12.0,
        omega_true=600.0,
        deterrence_beta_scale=float(sweep_args.deterrence_beta_scale),
        deterrence_sigma_scale=float(sweep_args.deterrence_sigma_scale),
        deterrence_omega_scale=float(sweep_args.deterrence_omega_scale),
        fixed_cue_mode="laser",
        # No mismatch — all parameters matched between truth and planner
        truth_habituation_kappa=None,
        truth_habituation_t_rec_s=None,
        truth_habituation_gamma=None,
        truth_habituation_update_model=None,
        planner_habituation_kappa=None,
        planner_habituation_t_rec_s=None,
        planner_habituation_gamma=None,
        planner_habituation_update_model=None,
        stl_e_star=5.0,
        stl_t_cov_s=1200.0,
        stl_w_s=600.0,
        stl_eta_min=0.4,
        stl_horizon_s=300.0,
        stl_theta=12.0,
    )


def _load_per_run_csv(subdir: Path) -> list[dict[str, Any]]:
    path = subdir / "per_run_metrics.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _build_sweep_summary(
    sweep_results: list[tuple[float, list[dict[str, Any]]]],
    systems: list[str],
) -> list[dict[str, Any]]:
    _B1 = "B1_greedy_fixedcue"
    reference = _B1 if _B1 in systems else systems[0]
    out = []
    for mu, rows in sweep_results:
        for hab_cond in ("hab_on", "hab_off"):
            for system in systems:
                sub = [
                    r for r in rows
                    if str(r.get("baseline")) == system
                    and str(r.get("habituation_condition")) == hab_cond
                ]
                if not sub:
                    continue

                vals = [_safe_float(r.get(_SUMMARY_METRIC)) for r in sub]
                vals = [v for v in vals if math.isfinite(v)]
                mean_exp = float(stats.mean(vals)) if vals else float("nan")
                ci_lo, ci_hi = ladder._ci95(vals)

                deltas = ladder._paired_deltas(rows, system, reference, hab_cond, _SUMMARY_METRIC)
                delta_mean = float(stats.mean(deltas)) if deltas else float("nan")
                d_lo, d_hi = ladder._ci95(deltas)
                seeds_below = sum(1 for d in deltas if d < 0)

                pct_deltas = ladder._paired_deltas_pct(rows, system, reference, hab_cond, _SUMMARY_METRIC)
                pct_mean = float(stats.mean(pct_deltas)) if pct_deltas else float("nan")
                boot_lo, boot_hi = (
                    ladder._bootstrap_ci95(pct_deltas) if pct_deltas else (float("nan"), float("nan"))
                )
                w_stat, p_val, _n_nz = ladder._wilcoxon_signed_rank(deltas)

                summary_row: dict[str, Any] = {
                    "mu_true": mu,
                    "system": system,
                    "habituation_condition": hab_cond,
                    "n_seeds": len(vals),
                    "mean_value_weighted_exposure": mean_exp,
                    "exposure_ci_lo": ci_lo,
                    "exposure_ci_hi": ci_hi,
                    "delta_vs_B1_mean": delta_mean,
                    "delta_ci_lo": d_lo,
                    "delta_ci_hi": d_hi,
                    "pct_delta_mean": pct_mean,
                    "pct_boot_ci_lo": boot_lo,
                    "pct_boot_ci_hi": boot_hi,
                    "wilcoxon_W": w_stat,
                    "wilcoxon_p": p_val,
                    "seeds_below_B1": seeds_below,
                    "n_paired_seeds": len(deltas),
                }
                for field in _AUX_METRICS:
                    aux = [_safe_float(r.get(field)) for r in sub]
                    aux = [v for v in aux if math.isfinite(v)]
                    summary_row[f"mean_{field}"] = float(stats.mean(aux)) if aux else float("nan")

                out.append(summary_row)
    return out


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    all_fields: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                all_fields.append(k)
                seen.add(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    mu_values: list[float] = sorted(args.mu_values)
    systems: list[str] = list(args.systems)

    print(
        f"[load_aware_res] mu_values={mu_values}"
        f"  systems={systems}  num_runs={args.num_runs}"
        f"  outdir={outdir}",
        flush=True,
    )

    args.mu_placeholder = mu_values[0]
    base = _base_ladder_args(args)

    sweep_results: list[tuple[float, list[dict[str, Any]]]] = []

    for mu in mu_values:
        token = _mu_token(mu)
        sub_outdir = outdir / token
        existing_csv = sub_outdir / "per_run_metrics.csv"

        if existing_csv.exists():
            per_run_rows = _load_per_run_csv(sub_outdir)
            sweep_results.append((mu, per_run_rows))
            print(
                f"\n[load_aware_res] --- mu_true={mu:.2e}"
                f"  SKIPPING (per_run_metrics.csv exists, {len(per_run_rows)} rows) ---",
                flush=True,
            )
            continue

        print(
            f"\n[load_aware_res] --- mu_true={mu:.2e}  subdir={token} ---",
            flush=True,
        )

        mu_args = copy.copy(base)
        mu_args.mu_true = mu
        mu_args.outdir = str(sub_outdir)

        ladder.run(mu_args)

        per_run_rows = _load_per_run_csv(sub_outdir)
        sweep_results.append((mu, per_run_rows))
        print(
            f"[load_aware_res] mu_true={mu:.2e} done  "
            f"({len(per_run_rows)} per-run rows loaded)",
            flush=True,
        )

    print("\n[load_aware_res] Writing sweep summary...", flush=True)
    summary_rows = _build_sweep_summary(sweep_results, systems)
    summary_path = outdir / "load_aware_reservation_summary.csv"
    _write_csv(summary_rows, summary_path)
    print(
        f"[load_aware_res] load_aware_reservation_summary.csv: "
        f"{len(summary_rows)} rows -> {summary_path}",
        flush=True,
    )
    print(
        f"[load_aware_res] Complete: {len(mu_values)} mu points x "
        f"{len(systems)} systems x 2 hab conditions.",
        flush=True,
    )


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare load-aware reservation dispatch (B4_res_soft_multicue, "
            "B4_res_adaptive_multicue) against B1 and B4 (fixed reservation) "
            "across load regimes. Tests whether dynamic rho_res softening "
            "recovers the overload reversal (mu=4e-4) while maintaining "
            "spare-capacity advantage."
        )
    )
    parser.add_argument(
        "--mu-values",
        nargs="+",
        type=float,
        default=DEFAULT_MU_VALUES,
        metavar="FLOAT",
        help="mu_true values to run. Default: 2e-5 1e-4 4e-4",
    )
    parser.add_argument(
        "--outdir",
        default="results/testbench/habituation_stl_load_aware_reservation",
    )
    parser.add_argument("--systems", nargs="*", default=DEFAULT_SYSTEMS)
    parser.add_argument("--duration-s", type=float, default=1800.0)
    parser.add_argument("--num-runs", type=int, default=10)
    parser.add_argument("--seed-start", type=int, default=125)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--nx", type=int, default=60)
    parser.add_argument("--ny", type=int, default=48)
    parser.add_argument("--nrobots", type=int, default=4)
    parser.add_argument("--reservation-fraction", type=float, default=0.25)
    parser.add_argument("--deterrence-beta-scale", type=float, default=4.0)
    parser.add_argument("--deterrence-sigma-scale", type=float, default=4.0)
    parser.add_argument("--deterrence-omega-scale", type=float, default=3.0)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
