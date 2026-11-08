"""
30-seed H4 TOST extension at mu=1e-4, kappa=0.50.
Adds seeds 135-154 (20 more) to the existing 10-seed data for B1 and B4,
then re-runs the TOST with the pooled 30-seed dataset.

Run from project root:
  $env:PYTHONPATH=(Resolve-Path .).Path
  python -m experiments.run_h4_tost_extended
"""
import argparse, csv, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from scipy.stats import ttest_1samp

from experiments import run_habituation_stl_production_ladder as ladder


OUTDIR = Path("results/testbench/h4_tost_extended_mu1em04_kappa0p50")
METRIC = "value_weighted_exposure"
EQUIV_DELTA = 3400   # ±3,400: same margin as the mu=2e-5 TOST
N_BOOT = 9999
RNG = np.random.default_rng(42)


def _base_args() -> argparse.Namespace:
    return argparse.Namespace(
        mu_true=1e-4,
        habituation_kappa=0.50,
        outdir="",
        merge_existing_raw=False,
        nx=60,
        ny=48,
        nrobots=4,
        duration_s=1800.0,
        warmup_s=0.0,
        task_replan_period_s=45.0,
        num_runs=10,      # overridden per call
        seed_start=125,   # overridden per call
        max_workers=4,
        systems=["B1_greedy_fixedcue", "B4_res_stl_full_multicue"],
        selected_config_overrides={},
        reservation_fraction=0.25,
        alpha_true=0.3,
        beta_true=0.25,
        sigma_true=12.0,
        omega_true=600.0,
        deterrence_beta_scale=4.0,
        deterrence_sigma_scale=4.0,
        deterrence_omega_scale=3.0,
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


def run_extension(outdir: Path, seed_start: int, num_runs: int):
    ns = _base_args()
    ns.seed_start   = seed_start
    ns.num_runs     = num_runs
    ns.outdir       = str(outdir)
    ns.merge_existing_raw = False
    print(f"\n[H4 extension] seeds {seed_start}–{seed_start+num_runs-1} → {outdir}")
    ladder.run(ns)


def load_exposure(csv_path: Path, sys_full: str):
    """Return {seed: exposure} for given system string."""
    out = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["system"] == sys_full:
                out[row["seed"]] = float(row[METRIC])
    return out


def tost_one_sided(diffs: list, lo: float, hi: float, alpha: float = 0.05):
    """
    Two one-sided t-tests (TOST).
    Returns (p_lo, p_hi, equiv_declared).
    equiv_declared iff both p < alpha.
    """
    arr = np.array(diffs)
    # H01: mean <= lo  →  alternative: mean > lo  →  t against lo
    t_lo = (arr.mean() - lo) / (arr.std(ddof=1) / np.sqrt(len(arr)))
    from scipy.stats import t as t_dist
    p_lo = t_dist.sf(t_lo, df=len(arr)-1)   # P(T > t_lo | H01)
    # H02: mean >= hi  →  alternative: mean < hi
    t_hi = (arr.mean() - hi) / (arr.std(ddof=1) / np.sqrt(len(arr)))
    p_hi = t_dist.cdf(t_hi, df=len(arr)-1)  # P(T < t_hi | H02)
    return p_lo, p_hi, max(p_lo, p_hi) < alpha


def main():
    # ── 1. Run the extension (seeds 135-154) ──────────────────────────────────
    ext_dir = OUTDIR / "ext_seeds_135_154"
    ext_dir.mkdir(parents=True, exist_ok=True)
    run_extension(ext_dir, seed_start=135, num_runs=20)

    # ── 2. Load existing 10-seed data (seeds 125-134) from joint sweep ────────
    joint = Path("results/testbench/habituation_stl_joint_sweep/mu_1em04_kappa_0p50")
    orig_csv = joint / "per_run_metrics.csv"
    ext_csv  = ext_dir / "per_run_metrics.csv"

    if not orig_csv.exists():
        print(f"ERROR: original CSV not found at {orig_csv}"); sys.exit(1)
    if not ext_csv.exists():
        print(f"ERROR: extension CSV not found at {ext_csv}"); sys.exit(1)

    b1_sys = "B1_greedy_fixedcue_hab_off"
    b4_sys = "B4_res_stl_full_multicue_hab_off"

    b1_orig = load_exposure(orig_csv, b1_sys)
    b4_orig = load_exposure(orig_csv, b4_sys)
    b1_ext  = load_exposure(ext_csv,  b1_sys)
    b4_ext  = load_exposure(ext_csv,  b4_sys)

    # Pool
    b1_all = {**b1_orig, **b1_ext}
    b4_all = {**b4_orig, **b4_ext}
    seeds = sorted(set(b1_all) & set(b4_all))
    diffs = [b4_all[s] - b1_all[s] for s in seeds]

    n = len(diffs)
    mean_d = np.mean(diffs)
    sd_d   = np.std(diffs, ddof=1)
    se     = sd_d / np.sqrt(n)
    from scipy.stats import t as t_dist
    t_ci   = t_dist.ppf(0.975, df=n-1)
    ci_lo  = mean_d - t_ci * se
    ci_hi  = mean_d + t_ci * se

    from scipy.stats import wilcoxon
    _, p_wilcoxon = wilcoxon(diffs, alternative="two-sided")

    # Bootstrap CI
    arr = np.array(diffs)
    boot_means = [RNG.choice(arr, n, replace=True).mean() for _ in range(N_BOOT)]
    boot_lo = float(np.percentile(boot_means, 2.5))
    boot_hi = float(np.percentile(boot_means, 97.5))

    # TOST
    p_lo, p_hi, equiv = tost_one_sided(diffs, -EQUIV_DELTA, EQUIV_DELTA)

    # ── 3. Print report ────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("H4 TOST: 30-seed pooled results (mu=1e-4, kappa=0.50, hab-off)")
    print("="*60)
    print(f"  n = {n} seeds (orig {len(b1_orig)} + ext {len(b1_ext)})")
    print(f"  B4-B1 mean    = {mean_d:+,.0f}")
    print(f"  SD            = {sd_d:,.0f}")
    print(f"  t-CI (95%)    = [{ci_lo:+,.0f}, {ci_hi:+,.0f}]")
    print(f"  boot-CI (95%) = [{boot_lo:+,.0f}, {boot_hi:+,.0f}]")
    print(f"  Wilcoxon p    = {p_wilcoxon:.4f}")
    print(f"  TOST margin   = ±{EQUIV_DELTA:,.0f}")
    print(f"  TOST p_lo     = {p_lo:.4f}  (H01: mean ≤ -{EQUIV_DELTA})")
    print(f"  TOST p_hi     = {p_hi:.4f}  (H02: mean ≥ +{EQUIV_DELTA})")
    print(f"  TOST equiv    = {'YES  ← declared' if equiv else 'NO'}")

    # B1 mean to express as %
    b1_mean = float(np.mean([b1_all[s] for s in seeds]))
    pct_d = mean_d / b1_mean * 100
    print(f"  B1 mean hab-off = {b1_mean:,.0f}")
    print(f"  delta as % of B1 = {pct_d:+.2f}%")

    # Save summary
    out_csv = OUTDIR / "h4_tost_30seed_summary.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n","mean","sd","ci_lo","ci_hi","boot_lo","boot_hi",
                    "wilcoxon_p","tost_margin","tost_p_lo","tost_p_hi","tost_equiv",
                    "b1_mean_haboff","pct_delta"])
        w.writerow([n, mean_d, sd_d, ci_lo, ci_hi, boot_lo, boot_hi,
                    p_wilcoxon, EQUIV_DELTA, p_lo, p_hi, equiv,
                    b1_mean, pct_d])
    print(f"\n  Results written to {out_csv}")


if __name__ == "__main__":
    main()
