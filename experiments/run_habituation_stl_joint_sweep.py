"""
2-D joint sweep over mu_true (reactive load regime) and habituation_kappa (habituation
strength), running the full B1–B5 baseline ladder at every (mu, kappa) cell.

Design rationale (proposal §8.3 and §8.5):
  - Load regime (mu_true) and habituation strength (kappa) are both factors in §8.3.
  - Running them as independent 1-D slices would miss the interaction: B4's advantage
    requires both sufficient habituation pressure (kappa > 0) *and* spare capacity to
    execute STL-prescribed cue rotation (rho_load not too high).  A 2-D grid is the
    minimal design that reveals whether the advantage is separable or joint.
  - Three mu anchors cover the load regimes of interest:
      mu = 2e-5  →  rho_load ≈ 0.35  (moderate / confirmatory point)
      mu = 1e-4  →  rho_load ≈ 0.62  (heavy    / peak B4 advantage)
      mu = 4e-4  →  rho_load ≈ 0.78  (near-saturated / B4 reversal onset)
  - Seven kappa values trace the full dose-response from no-habituation (kappa=0)
    to severe habituation (kappa=0.8); kappa=0.5 replicates the confirmatory run.

Systems included to cover all proposal hypotheses across the full (mu, kappa) space:
  B1  —  reference greedy fixed-cue                (H1, H4 denominator)
  B2  —  prior deltaJ reserved-capacity            (H3: B3 >= B2)
  B3  —  STL exposure+coverage, no habituation clause, multi-cue   (H2: B4 > B3)
  B4  —  full proposal: STL with habituation clause, multi-cue     (primary claim)
  B5  —  greedy with non-STL habituation-aware cue selection       (H5 ablation)

All fixed parameters match the confirmatory run (seed_start=125, num_runs=10,
duration_s=1800, nx=60, ny=48, nrobots=4, reservation_fraction=0.25, etc.).

Output:
  results/testbench/habituation_stl_joint_sweep/
    mu_2em05_kappa_0p00/   per_run_metrics.csv  ...
    mu_2em05_kappa_0p10/   ...
    ...
    mu_4em04_kappa_0p80/   ...
    joint_sweep_summary.csv   <- one row per (mu, kappa, system, hab_condition)

The skip logic checks for an existing per_run_metrics.csv before running each cell,
so the sweep can be safely restarted after interruption.
"""
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


# ── Sweep grid defaults ────────────────────────────────────────────────────────
# Three mu anchors: moderate (confirmatory), heavy (peak B4 advantage), near-saturated
DEFAULT_MU_VALUES: list[float] = [2e-5, 1e-4, 4e-4]

# Seven kappa values spanning no-habituation → severe habituation.
# kappa=0.5 replicates the confirmatory run; kappa=0 is the sanity anchor.
DEFAULT_KAPPA_VALUES: list[float] = [0.0, 0.10, 0.25, 0.40, 0.50, 0.65, 0.80]

# All five ladder systems so every proposal hypothesis (H1–H4 + the B4-vs-B5 ablation)
# can be evaluated across the full (mu, kappa) space.
DEFAULT_SYSTEMS: list[str] = [
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
    "predictive_deadline_feasible_fraction",
    "travel_distance_total",
    "stl_robustness_cov",
    "stl_robustness_global_mean",
]


# ── Token helpers ──────────────────────────────────────────────────────────────

def _mu_token(mu: float) -> str:
    """Filesystem-safe token for a mu_true value, e.g. 2.5e-05 → mu_2p5em05.

    Defined locally (not imported from run_habituation_stl_load_sweep) to keep
    this script self-contained.  The convention must match the load sweep's token
    so that directory names are consistent if the two outputs are ever merged.
    """
    exp = math.floor(math.log10(mu))
    mantissa = mu / (10.0 ** exp)
    mantissa_str = f"{mantissa:.4g}".replace(".", "p")
    return f"mu_{mantissa_str}em{abs(exp):02d}"


def _kappa_token(kappa: float) -> str:
    """Filesystem-safe token for a kappa value, e.g. 0.50 → kappa_0p50."""
    return f"kappa_{kappa:.2f}".replace(".", "p")


def _cell_token(mu: float, kappa: float) -> str:
    return f"{_mu_token(mu)}_{_kappa_token(kappa)}"


# ── Base args builder ──────────────────────────────────────────────────────────

def _base_ladder_args(sweep_args: argparse.Namespace) -> argparse.Namespace:
    """Build a base ladder Namespace with all fixed parameters.

    mu_true and habituation_kappa are placeholders; the per-cell loop overrides them.
    All values match the confirmatory run defaults (proposal §8.1).
    """
    return argparse.Namespace(
        # swept per cell — overridden in the loop; placeholders are valid floats
        mu_true=float(sweep_args.mu_values[0]),
        habituation_kappa=float(sweep_args.kappa_values[0]),
        outdir="",
        merge_existing_raw=False,
        # grid / fleet (confirmatory defaults)
        nx=int(sweep_args.nx),
        ny=int(sweep_args.ny),
        nrobots=int(sweep_args.nrobots),
        # timing (confirmatory defaults)
        duration_s=float(sweep_args.duration_s),
        warmup_s=0.0,
        task_replan_period_s=45.0,
        # seeds (confirmatory defaults: seeds 125–134)
        num_runs=int(sweep_args.num_runs),
        seed_start=int(sweep_args.seed_start),
        # concurrency
        max_workers=int(sweep_args.max_workers),
        # systems
        systems=list(sweep_args.systems),
        selected_config_overrides=dict(getattr(sweep_args, "selected_config_overrides", {}) or {}),
        # reserved-capacity dispatcher
        reservation_fraction=float(sweep_args.reservation_fraction),
        # ground-truth SESTPP shape parameters (proposal defaults)
        alpha_true=0.3,
        beta_true=0.25,
        sigma_true=12.0,
        omega_true=600.0,
        deterrence_beta_scale=float(sweep_args.deterrence_beta_scale),
        deterrence_sigma_scale=float(sweep_args.deterrence_sigma_scale),
        deterrence_omega_scale=float(sweep_args.deterrence_omega_scale),
        fixed_cue_mode="laser",
        # mismatch fields: None → matched-model (no mismatch injection)
        truth_habituation_t_rec_s=None,
        truth_habituation_kappa=None,
        truth_habituation_gamma=None,
        truth_habituation_update_model=None,
        planner_habituation_t_rec_s=None,
        planner_habituation_kappa=None,
        planner_habituation_gamma=None,
        planner_habituation_update_model=None,
        # STL specification parameters (confirmatory defaults, proposal §5)
        stl_e_star=5.0,
        stl_t_cov_s=1200.0,
        stl_w_s=600.0,
        stl_eta_min=0.4,
        stl_horizon_s=300.0,
        stl_theta=12.0,
    )


# ── I/O helpers ───────────────────────────────────────────────────────────────

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


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    """Write rows to CSV.  Union of all fieldnames across rows handles schema variation."""
    if not rows:
        return
    seen: set[str] = set()
    fields: list[str] = []
    for row in rows:
        for k in row:
            if k not in seen:
                fields.append(k)
                seen.add(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ── Summary builder ───────────────────────────────────────────────────────────

def _build_joint_summary(
    cell_results: list[tuple[float, float, list[dict[str, Any]]]],
    systems: list[str],
) -> list[dict[str, Any]]:
    """Build a cross-(mu, kappa) summary with one row per (mu, kappa, system, hab_cond).

    Paired statistics (Wilcoxon, delta CI) are computed against B1 as reference,
    matching the confirmatory-run convention.  Each cell's rows list is kept separate
    so pairing is always within the same (mu, kappa) cell.
    """
    _B1 = "B1_greedy_fixedcue"
    reference = _B1 if _B1 in systems else (systems[0] if systems else _B1)
    out: list[dict[str, Any]] = []

    for mu, kappa, rows in cell_results:
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

                # Paired deltas vs reference — rows contains all systems for this cell
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

                row: dict[str, Any] = {
                    "mu_true": mu,
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
                    row[f"mean_{field}"] = float(stats.mean(aux)) if aux else float("nan")

                out.append(row)

    return out


# ── Main runner ───────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    # Sort in-place so _base_ladder_args and the loop iterate in the same order
    args.mu_values = sorted(args.mu_values)
    args.kappa_values = sorted(args.kappa_values)
    systems: list[str] = list(args.systems)

    selected_overrides = load_selected_config_overrides(args.selection_path, systems=systems)
    args.selected_config_overrides = selected_overrides

    n_cells = len(args.mu_values) * len(args.kappa_values)
    print(
        f"[joint_sweep] mu_values={[f'{m:.2e}' for m in args.mu_values]}  "
        f"kappa_values={args.kappa_values}  systems={systems}  "
        f"num_runs={args.num_runs}  cells={n_cells}  outdir={outdir}",
        flush=True,
    )
    if selected_overrides:
        print(
            f"[joint_sweep] frozen selected configs applied for {sorted(selected_overrides)}",
            flush=True,
        )

    base = _base_ladder_args(args)
    # (mu, kappa, per-run rows) triples — one per completed cell
    cell_results: list[tuple[float, float, list[dict[str, Any]]]] = []

    for mu in args.mu_values:
        for kappa in args.kappa_values:
            token = _cell_token(mu, kappa)
            cell_outdir = outdir / token
            existing_csv = cell_outdir / "per_run_metrics.csv"

            if existing_csv.exists():
                per_run_rows = _load_per_run_csv(cell_outdir)
                cell_results.append((mu, kappa, per_run_rows))
                print(
                    f"\n[joint_sweep] --- mu={mu:.2e} kappa={kappa:.2f}  SKIPPING"
                    f" (per_run_metrics.csv exists, {len(per_run_rows)} rows) ---",
                    flush=True,
                )
                continue

            print(
                f"\n[joint_sweep] --- mu={mu:.2e} kappa={kappa:.2f}  cell={token} ---",
                flush=True,
            )

            cell_args = copy.copy(base)
            cell_args.mu_true = mu
            cell_args.habituation_kappa = kappa
            cell_args.outdir = str(cell_outdir)

            ladder.run(cell_args)

            per_run_rows = _load_per_run_csv(cell_outdir)
            cell_results.append((mu, kappa, per_run_rows))
            print(
                f"[joint_sweep] mu={mu:.2e} kappa={kappa:.2f} done  "
                f"({len(per_run_rows)} per-run rows loaded)",
                flush=True,
            )

    print("\n[joint_sweep] Writing joint summary...", flush=True)
    summary_rows = _build_joint_summary(cell_results, systems)
    summary_path = outdir / "joint_sweep_summary.csv"
    _write_csv(summary_rows, summary_path)
    print(
        f"[joint_sweep] joint_sweep_summary.csv: {len(summary_rows)} rows → {summary_path}",
        flush=True,
    )
    print(
        f"[joint_sweep] Complete: {len(args.mu_values)} mu × {len(args.kappa_values)} kappa × "
        f"{len(systems)} systems × 2 hab conditions = "
        f"{len(args.mu_values) * len(args.kappa_values) * len(systems) * 2} summary rows.",
        flush=True,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "2-D joint sweep over mu_true (reactive load) and habituation_kappa "
            "(habituation strength).  Runs the full B1–B5 ladder at each (mu, kappa) "
            "cell to characterise the load × habituation interaction surface identified "
            "in proposal §8.3.  Covers all four proposal hypotheses (H1–H4) plus the "
            "B4-vs-B5 STL-vs-cue-rotation ablation across the full grid.  Per-cell "
            "results land in subdirectories named mu_<tok>_kappa_<tok>; a combined "
            "joint_sweep_summary.csv with both mu_true and kappa columns is written at "
            "the root.  Already-computed cells are skipped automatically."
        )
    )
    parser.add_argument(
        "--mu-values",
        nargs="+",
        type=float,
        default=DEFAULT_MU_VALUES,
        metavar="FLOAT",
        help=(
            "mu_true values to sweep.  Default: 2e-5 1e-4 4e-4 "
            "(rho_load ≈ 0.35 / 0.62 / 0.78: moderate / peak-advantage / near-saturated)."
        ),
    )
    parser.add_argument(
        "--kappa-values",
        nargs="+",
        type=float,
        default=DEFAULT_KAPPA_VALUES,
        metavar="FLOAT",
        help="kappa values to sweep.  Default: 0.0 0.1 0.25 0.4 0.5 0.65 0.8",
    )
    parser.add_argument(
        "--outdir",
        default="results/testbench/habituation_stl_joint_sweep",
    )
    parser.add_argument(
        "--systems",
        nargs="*",
        default=DEFAULT_SYSTEMS,
        help=(
            "Baseline systems to run at each cell.  Default: all five ladder systems "
            "(B1 B2 B3 B4 B5) to cover H1–H4 and the B4-vs-B5 ablation."
        ),
    )
    parser.add_argument(
        "--selection-path",
        default=None,
        help=(
            "Optional fair-tuning selected_configs.json.  Matching baselines receive "
            "frozen tuned hyperparameters (rho, cue mode, etc.)."
        ),
    )
    # Simulation parameters — defaults match the confirmatory run (proposal §8.1)
    parser.add_argument("--duration-s", type=float, default=1800.0)
    parser.add_argument("--num-runs", type=int, default=10,
                        help="Seeds per cell.  Default 10 (seeds seed_start … seed_start+9).")
    parser.add_argument("--seed-start", type=int, default=125,
                        help="First seed.  Default 125 (confirmatory seeds 125–134).")
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
