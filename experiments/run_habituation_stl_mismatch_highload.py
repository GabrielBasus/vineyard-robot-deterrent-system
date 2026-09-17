"""Mismatch sweep at the high-load operating point (mu=1e-4, rho~0.82).

This is the informative robustness test for H1: at mu=2e-5 (rho~0.46) B4's matched
advantage over B1 is near-zero and not testable for survival under mismatch. At
mu=1e-4 (rho~0.82) B4 beats B1 by -13,648 (p<0.01) in the matched joint sweep, so
here we can directly ask whether that advantage survives truth/planner kappa mismatch.

Runs the existing mismatch sweep infrastructure unchanged, just with mu=1e-4 and a
separate output directory.

Usage (from repo root):
    python -m experiments.run_habituation_stl_mismatch_highload
    python -m experiments.run_habituation_stl_mismatch_highload --max-workers 6

All other defaults (truth_kappa_values, planner_kappa, num_runs, seed_start) match
the low-load mismatch sweep so the two experiments are directly comparable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import experiments.run_habituation_stl_mismatch_sweep as mismatch


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Mismatch sweep at mu=1e-4 (rho~0.82) — the high-load operating point "
            "where B4's matched advantage is -13,648 (p<0.01). Tests whether that "
            "advantage survives truth/planner kappa mismatch. Planner kappa fixed at "
            "0.5; truth kappa swept over {0.10, 0.25, 0.50, 0.75, 0.90}."
        )
    )
    parser.add_argument("--outdir", default="results/testbench/habituation_stl_mismatch_sweep_mu1em04")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--num-runs", type=int, default=10)
    parser.add_argument("--seed-start", type=int, default=125)
    parser.add_argument(
        "--truth-kappa-values", nargs="+", type=float,
        default=[0.10, 0.25, 0.50, 0.75, 0.90],
        metavar="FLOAT",
    )
    parser.add_argument("--planner-kappa", type=float, default=0.5)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    # Build a full mismatch_sweep args namespace using the low-load sweep defaults
    # as a base, then override mu_true and outdir.
    base = mismatch.parse_args([
        "--mu-true", "1e-4",
        "--outdir", args.outdir,
        "--max-workers", str(args.max_workers),
        "--num-runs", str(args.num_runs),
        "--seed-start", str(args.seed_start),
        "--planner-kappa", str(args.planner_kappa),
        "--truth-kappa-values",
        *[str(tk) for tk in args.truth_kappa_values],
    ])
    print(
        f"[mismatch_highload] Starting high-load mismatch sweep  "
        f"mu=1e-4  planner_kappa={args.planner_kappa}  "
        f"truth_kappa_values={args.truth_kappa_values}  "
        f"num_runs={args.num_runs}  outdir={args.outdir}",
        flush=True,
    )
    mismatch.run(base)


if __name__ == "__main__":
    run(parse_args())
