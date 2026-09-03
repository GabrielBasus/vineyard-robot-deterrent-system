from __future__ import annotations

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


DEFAULT_KAPPA_VALUES = [0.0, 0.10, 0.25, 0.40, 0.50, 0.65, 0.80]

DEFAULT_SYSTEMS = [
    "B1_greedy_fixedcue",
    "B4_res_stl_full_multicue",
    "B5_greedy_habcue",
]

_SUMMARY_METRIC = "value_weighted_exposure"
_AUX_METRICS = [
    "habituation_eta_at_apply_mean",
    "habituation_variety_index",
    "truth_suppression_effect_sum",
    "mean_response_time_s",
]


def _kappa_token(kappa: float) -> str:
    """Convert kappa float to a filesystem-safe directory token, e.g. 0.50 -> kappa_0p50."""
    return f"kappa_{kappa:.2f}".replace(".", "p")


def _base_ladder_args(sweep_args: argparse.Namespace) -> argparse.Namespace:
    """Build the argparse.Namespace that the ladder's run() and helpers expect."""
    return argparse.Namespace(
        # kappa swept per iteration — placeholder, overridden in the loop
        habituation_kappa=float(sweep_args.kappa_placeholder),
        outdir="",
        merge_existing_raw=False,
        # mu_true fixed for this sweep
        mu_true=float(sweep_args.mu_true),
        # fixed grid / fleet
        nx=int(sweep_args.nx),
        ny=int(sweep_args.ny),
        nrobots=int(sweep_args.nrobots),
        # timing
        duration_s=float(sweep_args.duration_s),
        warmup_s=0.0,
        task_replan_period_s=45.0,
        # seeds
        num_runs=int(sweep_args.num_runs),
        seed_start=int(sweep_args.seed_start),
        # concurrency
        max_workers=int(sweep_args.max_workers),
        # systems
        systems=list(sweep_args.systems),
        # dispatch
        reservation_fraction=float(sweep_args.reservation_fraction),
        # ground-truth process shape parameters at proposal defaults
        alpha_true=0.3,
        beta_true=0.25,
        sigma_true=12.0,
        omega_true=600.0,
        deterrence_beta_scale=float(sweep_args.deterrence_beta_scale),
        deterrence_sigma_scale=float(sweep_args.deterrence_sigma_scale),
        deterrence_omega_scale=float(sweep_args.deterrence_omega_scale),
        fixed_cue_mode="laser",
        # mismatch fields: not used in a plain kappa sweep
        truth_habituation_t_rec_s=None,
        truth_habituation_kappa=None,
        truth_habituation_gamma=None,
        truth_habituation_update_model=None,
        planner_habituation_t_rec_s=None,
        planner_habituation_kappa=None,
        planner_habituation_gamma=None,
        planner_habituation_update_model=None,
        # STL parameters at confirmatory-run defaults
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


def _build_cross_kappa_summary(
    kappa_results: list[tuple[float, list[dict[str, Any]]]],
    systems: list[str],
) -> list[dict[str, Any]]:
    reference = systems[0] if systems else "B1_greedy_fixedcue"
    out = []
    for kappa, rows in kappa_results:
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
                boot_lo, boot_hi = ladder._bootstrap_ci95(pct_deltas) if pct_deltas else (float("nan"), float("nan"))
                w_stat, p_val, _n_nz = ladder._wilcoxon_signed_rank(deltas)

                summary_row: dict[str, Any] = {
                    "kappa": kappa,
                    "system": system,
                    "habituation_condition": hab_cond,
                    "n_seeds": len(vals),
                    "mean_value_weighted_exposure": mean_exp,
                    "exposure_ci_lo": ci_lo,
                    "exposure_ci_hi": ci_hi,
                    "delta_vs_reference_mean": delta_mean,
                    "delta_ci_lo": d_lo,
                    "delta_ci_hi": d_hi,
                    "pct_delta_mean": pct_mean,
                    "pct_boot_ci_lo": boot_lo,
                    "pct_boot_ci_hi": boot_hi,
                    "wilcoxon_W": w_stat,
                    "wilcoxon_p": p_val,
                    "seeds_below_reference": seeds_below,
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
    fields = list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    kappa_values: list[float] = sorted(args.kappa_values)
    systems: list[str] = list(args.systems)

    print(
        f"[kappa_sweep] kappa_values={kappa_values}  mu_true={args.mu_true:.2e}  "
        f"systems={systems}  num_runs={args.num_runs}  outdir={outdir}",
        flush=True,
    )

    args.kappa_placeholder = kappa_values[0]
    base = _base_ladder_args(args)

    kappa_results: list[tuple[float, list[dict[str, Any]]]] = []

    for kappa in kappa_values:
        token = _kappa_token(kappa)
        kappa_outdir = outdir / token
        print(f"\n[kappa_sweep] --- kappa={kappa:.2f}  subdir={token} ---", flush=True)

        kappa_args = copy.copy(base)
        kappa_args.habituation_kappa = kappa
        kappa_args.outdir = str(kappa_outdir)

        ladder.run(kappa_args)

        per_run_rows = _load_per_run_csv(kappa_outdir)
        kappa_results.append((kappa, per_run_rows))
        print(
            f"[kappa_sweep] kappa={kappa:.2f} done  "
            f"({len(per_run_rows)} per-run rows loaded)",
            flush=True,
        )

    print("\n[kappa_sweep] Writing cross-kappa summary...", flush=True)
    summary_rows = _build_cross_kappa_summary(kappa_results, systems)
    summary_path = outdir / "kappa_sweep_summary.csv"
    _write_csv(summary_rows, summary_path)
    print(
        f"[kappa_sweep] kappa_sweep_summary.csv: {len(summary_rows)} rows -> {summary_path}",
        flush=True,
    )
    print(
        f"[kappa_sweep] Complete: {len(kappa_values)} kappa points × "
        f"{len(systems)} systems × 2 hab conditions.",
        flush=True,
    )


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep habituation_kappa across dose levels and run the B1/B4/B5 ladder "
            "at each point (mu_true fixed at confirmatory value). Traces the dose-response "
            "curve from kappa=0 (no habituation, B4 gap should be ~0) to kappa=0.80 "
            "(strong habituation). Results go to per-kappa subdirectories under --outdir "
            "plus a combined kappa_sweep_summary.csv at the root."
        )
    )
    parser.add_argument(
        "--kappa-values",
        nargs="+",
        type=float,
        default=DEFAULT_KAPPA_VALUES,
        metavar="FLOAT",
        help="kappa values to sweep. Default: 0.0 0.1 0.25 0.4 0.5 0.65 0.8",
    )
    parser.add_argument(
        "--mu-true",
        type=float,
        default=2e-05,
        help="Fixed mu_true for all kappa points (default: 2e-05, the confirmatory value).",
    )
    parser.add_argument(
        "--outdir",
        default="results/testbench/habituation_stl_kappa_sweep",
    )
    parser.add_argument(
        "--systems",
        nargs="*",
        default=DEFAULT_SYSTEMS,
        help="Systems to run at each kappa point. Default: B1 B4 B5.",
    )
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
