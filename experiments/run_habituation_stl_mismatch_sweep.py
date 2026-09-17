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
from experiments.habituation_stl_selected_configs import load_selected_config_overrides


# Truth kappa values swept while planner kappa stays fixed at 0.5 (nominal confirmatory value).
# truth_kappa < planner_kappa: truth is more forgiving than the planner assumes.
# truth_kappa = planner_kappa: matched (replication check).
# truth_kappa > planner_kappa: truth is more severe than the planner assumes.
DEFAULT_TRUTH_KAPPA_VALUES = [0.10, 0.25, 0.50, 0.75, 0.90]
DEFAULT_PLANNER_KAPPA = 0.5

DEFAULT_SYSTEMS = [
    "B1_greedy_fixedcue",
    "B2_res_deltaJ_fixedcue",
    "B3_res_stl_nohab_multicue",
    "B4_res_stl_full_multicue",
    "B5_greedy_habcue",
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
]


def _truth_kappa_token(tk: float) -> str:
    """e.g. 0.25 -> truth_kappa_0p25"""
    return f"truth_kappa_{tk:.2f}".replace(".", "p")


def _base_ladder_args(sweep_args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        habituation_kappa=float(sweep_args.planner_kappa),
        outdir="",
        merge_existing_raw=False,
        mu_true=float(sweep_args.mu_true),
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
        selected_config_overrides=dict(getattr(sweep_args, "selected_config_overrides", {}) or {}),
        reservation_fraction=float(sweep_args.reservation_fraction),
        alpha_true=0.3,
        beta_true=0.25,
        sigma_true=12.0,
        omega_true=600.0,
        deterrence_beta_scale=float(sweep_args.deterrence_beta_scale),
        deterrence_sigma_scale=float(sweep_args.deterrence_sigma_scale),
        deterrence_omega_scale=float(sweep_args.deterrence_omega_scale),
        fixed_cue_mode="laser",
        # mismatch: planner kappa fixed at nominal, truth kappa swept (overridden per iteration)
        truth_habituation_kappa=float(sweep_args.truth_kappa_placeholder),  # placeholder, overridden
        truth_habituation_t_rec_s=None,
        truth_habituation_gamma=None,
        truth_habituation_update_model=None,
        planner_habituation_kappa=float(sweep_args.planner_kappa),  # fixed at nominal
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


def _build_cross_mismatch_summary(
    sweep_results: list[tuple[float, list[dict[str, Any]]]],
    systems: list[str],
    planner_kappa: float,
) -> list[dict[str, Any]]:
    _B1 = "B1_greedy_fixedcue"
    reference = _B1 if _B1 in systems else (systems[0] if systems else _B1)
    out = []
    for truth_kappa, rows in sweep_results:
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
                    "truth_kappa": truth_kappa,
                    "planner_kappa": planner_kappa,
                    "kappa_mismatch": truth_kappa - planner_kappa,
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

    truth_kappa_values: list[float] = sorted(args.truth_kappa_values)
    planner_kappa = float(args.planner_kappa)
    systems: list[str] = list(args.systems)
    selected_overrides = load_selected_config_overrides(args.selection_path, systems=systems)
    args.selected_config_overrides = selected_overrides

    print(
        f"[mismatch_sweep] planner_kappa={planner_kappa} (fixed)  truth_kappa_values={truth_kappa_values}"
        f"  mu_true={args.mu_true:.2e}  systems={systems}  num_runs={args.num_runs}"
        f"  outdir={outdir}",
        flush=True,
    )
    if selected_overrides:
        print(
            f"[mismatch_sweep] frozen selected configs applied for {sorted(selected_overrides)}",
            flush=True,
        )

    args.truth_kappa_placeholder = truth_kappa_values[0]  # placeholder; overridden per iteration
    base = _base_ladder_args(args)

    sweep_results: list[tuple[float, list[dict[str, Any]]]] = []

    for tk in truth_kappa_values:
        token = _truth_kappa_token(tk)
        sub_outdir = outdir / token
        mismatch_str = f"{tk - planner_kappa:+.2f}"
        existing_csv = sub_outdir / "per_run_metrics.csv"

        if existing_csv.exists():
            per_run_rows = _load_per_run_csv(sub_outdir)
            sweep_results.append((tk, per_run_rows))
            print(
                f"\n[mismatch_sweep] --- truth_kappa={tk:.2f} (mismatch={mismatch_str})"
                f"  SKIPPING (per_run_metrics.csv exists, {len(per_run_rows)} rows) ---",
                flush=True,
            )
            continue

        print(
            f"\n[mismatch_sweep] --- truth_kappa={tk:.2f} (mismatch={mismatch_str})"
            f"  subdir={token} ---",
            flush=True,
        )

        tk_args = copy.copy(base)
        tk_args.truth_habituation_kappa = tk
        tk_args.outdir = str(sub_outdir)

        ladder.run(tk_args)

        per_run_rows = _load_per_run_csv(sub_outdir)
        sweep_results.append((tk, per_run_rows))
        print(
            f"[mismatch_sweep] truth_kappa={tk:.2f} done  "
            f"({len(per_run_rows)} per-run rows loaded)",
            flush=True,
        )

    print("\n[mismatch_sweep] Writing cross-mismatch summary...", flush=True)
    summary_rows = _build_cross_mismatch_summary(sweep_results, systems, planner_kappa)
    summary_path = outdir / "mismatch_sweep_summary.csv"
    _write_csv(summary_rows, summary_path)
    print(
        f"[mismatch_sweep] mismatch_sweep_summary.csv: {len(summary_rows)} rows -> {summary_path}",
        flush=True,
    )
    print(
        f"[mismatch_sweep] Complete: {len(truth_kappa_values)} truth-kappa points × "
        f"{len(systems)} systems × 2 hab conditions.",
        flush=True,
    )


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep truth kappa (ground-truth habituation severity) while keeping planner kappa "
            "fixed at the confirmatory value (0.5). Tests robustness of B4's STL habituation "
            "clause when the real world is more or less severe than the planner's model assumes. "
            "truth_kappa < planner_kappa: truth more forgiving (planner overestimates severity); "
            "truth_kappa > planner_kappa: truth more severe (planner underestimates severity). "
            "Results go to per-kappa subdirectories under --outdir plus a combined "
            "mismatch_sweep_summary.csv at the root."
        )
    )
    parser.add_argument(
        "--truth-kappa-values",
        nargs="+",
        type=float,
        default=DEFAULT_TRUTH_KAPPA_VALUES,
        metavar="FLOAT",
        help="Truth kappa values to sweep. Default: 0.1 0.25 0.5 0.75 0.9",
    )
    parser.add_argument(
        "--planner-kappa",
        type=float,
        default=DEFAULT_PLANNER_KAPPA,
        help="Fixed planner habituation kappa (default: 0.5, the confirmatory value).",
    )
    parser.add_argument(
        "--mu-true",
        type=float,
        default=2e-05,
        help="Fixed mu_true for all points (default: 2e-05).",
    )
    parser.add_argument(
        "--outdir",
        default="results/testbench/habituation_stl_mismatch_sweep",
    )
    parser.add_argument(
        "--systems",
        nargs="*",
        default=DEFAULT_SYSTEMS,
        help="Systems to run. Default: B1 B3 B4 B5_greedy.",
    )
    parser.add_argument(
        "--selection-path",
        default=None,
        help="Optional fair-tuning selected_configs.json for frozen structural overrides.",
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
