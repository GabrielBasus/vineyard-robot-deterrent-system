"""
ρ_res sweep at the heavy spare-capacity operating point (µ=1e-4, κ=0.50).

Purpose
-------
The 30-seed H4 extension found B4 significantly worse than B1 under hab-off at
µ=1e-4 (+4,942, p=0.007).  Code audit attributes this to the reserved-capacity
dispatch policy (res) reserving ρ_res=0.25 of fleet capacity for predictive
work even when habituation is absent and predictive work carries no benefit.

This sweep tests whether the H4 overhead diminishes as ρ_res → 0, which would
confirm the reservation policy as the mechanism.

Fixed parameters
----------------
mu_true  = 1e-4   (ρ_load ≈ 0.82 at κ=0.50 — heavy spare-capacity regime)
kappa    = 0.50   (confirmatory habituation decrement)

Sweep dimensions
----------------
ρ_res ∈ {0.00, 0.05, 0.10, 0.15, 0.20, 0.25}
    Systems: B1_greedy_fixedcue, B4_res_stl_full_multicue
    Both hab-on and hab-off conditions (ladder runs both by default)

Output layout
-------------
results/testbench/h4_rho_res_sweep_mu1em04/
  rho_res_0p00/
    raw/
    per_run_metrics.csv
    THESIS_RESULTS_SUMMARY.md
  rho_res_0p05/
  ...
  rho_res_0p25/
  h4_rho_res_sweep_summary.csv
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


# ── Sweep grid ─────────────────────────────────────────────────────────────────

DEFAULT_RHO_RES_VALUES: list[float] = [0.00, 0.05, 0.10, 0.15, 0.20, 0.25]

DEFAULT_SYSTEMS: list[str] = [
    "B1_greedy_fixedcue",
    "B4_res_stl_full_multicue",
]

_FIXED_MU: float = 1e-4
_FIXED_KAPPA: float = 0.50

_SUMMARY_METRIC = "value_weighted_exposure"
_AUX_METRICS = [
    "reactive_completed_fraction",
    "predictive_completed_fraction",
    "habituation_eta_at_apply_mean",
    "habituation_variety_index",
    "mean_response_time_s",
]


# ── Filesystem token ───────────────────────────────────────────────────────────

def _rho_token(rho: float) -> str:
    return f"rho_res_{rho:.2f}".replace(".", "p")


# ── Base ladder args ──────────────────────────────────────────────────────────

def _base_ladder_args(sweep_args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        mu_true=_FIXED_MU,
        habituation_kappa=_FIXED_KAPPA,
        outdir="",
        merge_existing_raw=False,
        nx=int(sweep_args.nx),
        ny=int(sweep_args.ny),
        nrobots=int(sweep_args.nrobots),
        duration_s=float(sweep_args.duration_s),
        warmup_s=0.0,
        task_replan_period_s=45.0,
        num_runs=int(sweep_args.num_runs),
        seed_start=int(sweep_args.seed_start),
        max_workers=int(sweep_args.max_workers),
        systems=[],
        selected_config_overrides={},
        reservation_fraction=0.25,   # placeholder; overridden per cell
        alpha_true=0.3,
        beta_true=0.25,
        sigma_true=12.0,
        omega_true=600.0,
        deterrence_beta_scale=float(sweep_args.deterrence_beta_scale),
        deterrence_sigma_scale=float(sweep_args.deterrence_sigma_scale),
        deterrence_omega_scale=float(sweep_args.deterrence_omega_scale),
        fixed_cue_mode="laser",
        truth_habituation_t_rec_s=None,
        truth_habituation_kappa=None,
        truth_habituation_gamma=None,
        truth_habituation_update_model=None,
        planner_habituation_t_rec_s=None,
        planner_habituation_kappa=None,
        planner_habituation_gamma=None,
        planner_habituation_update_model=None,
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
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    all_keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys)
        writer.writeheader()
        writer.writerows(rows)


# ── Statistics helpers ────────────────────────────────────────────────────────

def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return float("nan")


def _ci95(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (float("nan"), float("nan"))
    n = len(values)
    mean = stats.mean(values)
    se = stats.stdev(values) / math.sqrt(n)
    t_crit = 2.262 if n == 10 else 2.0
    return (mean - t_crit * se, mean + t_crit * se)


def _paired_deltas(
    rows: list[dict[str, Any]],
    baseline_a: str,
    baseline_b: str,
    hab_cond: str,
    metric: str = _SUMMARY_METRIC,
) -> list[float]:
    sys_a = f"{baseline_a}_{hab_cond}"
    sys_b = f"{baseline_b}_{hab_cond}"
    a_by_seed = {r["seed"]: _safe_float(r[metric]) for r in rows if r["system"] == sys_a}
    b_by_seed = {r["seed"]: _safe_float(r[metric]) for r in rows if r["system"] == sys_b}
    seeds = sorted(set(a_by_seed) & set(b_by_seed))
    return [a_by_seed[s] - b_by_seed[s] for s in seeds]


# ── Cross-rho summary ─────────────────────────────────────────────────────────

def _build_summary_row(
    rho_label: str,
    subdir: Path,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    if not rows:
        return out
    systems_present = sorted({r["system"] for r in rows})
    for sys in systems_present:
        sys_rows = [r for r in rows if r["system"] == sys]
        if not sys_rows:
            continue
        n = len(sys_rows)
        exposures = [_safe_float(r[_SUMMARY_METRIC]) for r in sys_rows]
        ci_lo, ci_hi = _ci95(exposures)
        row_out: dict[str, Any] = {
            "rho_res_label": rho_label,
            "system": sys,
            "n_seeds": n,
            f"mean_{_SUMMARY_METRIC}": stats.mean(exposures) if exposures else float("nan"),
            f"{_SUMMARY_METRIC}_ci_lo": ci_lo,
            f"{_SUMMARY_METRIC}_ci_hi": ci_hi,
        }
        for m in _AUX_METRICS:
            vals = [_safe_float(r.get(m, float("nan"))) for r in sys_rows]
            row_out[f"mean_{m}"] = (
                stats.mean([v for v in vals if not math.isnan(v)]) if vals else float("nan")
            )
        out.append(row_out)
    return out


# ── Main sweep logic ──────────────────────────────────────────────────────────

def run(sweep_args: argparse.Namespace) -> None:
    outdir = Path(sweep_args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    base_args = _base_ladder_args(sweep_args)
    all_summary_rows: list[dict[str, Any]] = []

    b1_haboff_by_rho: dict[str, float] = {}   # rho_label → B1 mean hab-off (for % of B1)

    for rho in sweep_args.rho_res_values:
        token = _rho_token(rho)
        cell_dir = outdir / token
        label = f"{rho:.2f}"
        print(f"\n[h4_rho_res_sweep] ρ_res={label}  dir={cell_dir}", flush=True)

        cell_args = copy.copy(base_args)
        cell_args.outdir = str(cell_dir)
        cell_args.reservation_fraction = rho
        cell_args.systems = list(sweep_args.systems)

        if not (cell_dir / "per_run_metrics.csv").exists():
            ladder.run(cell_args)
        else:
            print(f"[h4_rho_res_sweep] skipping {token} (per_run_metrics.csv exists)", flush=True)

        rows = _load_per_run_csv(cell_dir)
        all_summary_rows.extend(_build_summary_row(f"fixed_{token}", cell_dir, rows))

        # Compute B1 hab-off mean for % reporting
        b1_sys = "B1_greedy_fixedcue_hab_off"
        b1_vals = [_safe_float(r[_SUMMARY_METRIC]) for r in rows if r["system"] == b1_sys]
        b1_mean = stats.mean(b1_vals) if b1_vals else float("nan")
        b1_haboff_by_rho[label] = b1_mean

        for hab in ("hab_on", "hab_off"):
            deltas = _paired_deltas(rows, "B4_res_stl_full_multicue", "B1_greedy_fixedcue", hab)
            if deltas:
                mean_d = stats.mean(deltas)
                ci_lo, ci_hi = _ci95(deltas)
                n_neg = sum(1 for d in deltas if d < 0)
                pct_b1 = mean_d / b1_mean * 100 if not math.isnan(b1_mean) else float("nan")
                print(
                    f"  [{hab}] B4-B1: mean={mean_d:+,.0f} ({pct_b1:+.1f}% of B1)"
                    f"  CI=[{ci_lo:+,.0f},{ci_hi:+,.0f}]"
                    f"  n_neg={n_neg}/{len(deltas)}",
                    flush=True,
                )

    # ── Print hab-off summary table ────────────────────────────────────────────
    print("\n" + "="*65)
    print("H4 ρ_res sweep summary: B4-B1 hab-off  (µ=1e-4, κ=0.50)")
    print("="*65)
    print(f"{'ρ_res':>8}  {'mean delta':>12}  {'% of B1':>9}  {'CI lo':>10}  {'CI hi':>10}")
    for rho in sweep_args.rho_res_values:
        token = _rho_token(rho)
        cell_dir = outdir / token
        rows = _load_per_run_csv(cell_dir)
        deltas = _paired_deltas(rows, "B4_res_stl_full_multicue", "B1_greedy_fixedcue", "hab_off")
        b1_mean = b1_haboff_by_rho.get(f"{rho:.2f}", float("nan"))
        if deltas:
            mean_d = stats.mean(deltas)
            ci_lo, ci_hi = _ci95(deltas)
            pct = mean_d / b1_mean * 100 if not math.isnan(b1_mean) else float("nan")
            print(f"{rho:>8.2f}  {mean_d:>+12,.0f}  {pct:>+8.1f}%  {ci_lo:>+10,.0f}  {ci_hi:>+10,.0f}")

    # ── Write combined summary ─────────────────────────────────────────────────
    summary_path = outdir / "h4_rho_res_sweep_summary.csv"
    _write_csv(summary_path, all_summary_rows)
    print(f"\n[h4_rho_res_sweep] summary → {summary_path}", flush=True)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ρ_res sweep at the heavy spare-capacity point (µ=1e-4, κ=0.50) "
                    "to test whether B4's H4 overhead is caused by the reservation policy."
    )
    p.add_argument(
        "--rho-res-values", nargs="+", type=float,
        default=DEFAULT_RHO_RES_VALUES,
        metavar="FLOAT",
        help="Reservation fractions to sweep (default: 0.00 0.05 0.10 0.15 0.20 0.25).",
    )
    p.add_argument(
        "--systems", nargs="+", type=str,
        default=DEFAULT_SYSTEMS,
        metavar="SYS",
    )
    p.add_argument(
        "--outdir", type=str,
        default="results/testbench/h4_rho_res_sweep_mu1em04",
    )
    p.add_argument("--num-runs", type=int, default=10)
    p.add_argument("--seed-start", type=int, default=125)
    p.add_argument("--duration-s", type=float, default=1800.0)
    p.add_argument("--max-workers", type=int, default=4)
    p.add_argument("--nx", type=int, default=60)
    p.add_argument("--ny", type=int, default=48)
    p.add_argument("--nrobots", type=int, default=4)
    p.add_argument("--deterrence-beta-scale", type=float, default=4.0)
    p.add_argument("--deterrence-sigma-scale", type=float, default=4.0)
    p.add_argument("--deterrence-omega-scale", type=float, default=3.0)
    return p.parse_args()


if __name__ == "__main__":
    run(_parse_args())
