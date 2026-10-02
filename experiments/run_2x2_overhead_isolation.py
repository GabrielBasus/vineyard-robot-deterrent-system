"""run_2x2_overhead_isolation.py

Isolates the source of B4's +3.2% hab-off overhead relative to B3's +0.1%.

2x2 design at spare load (mu=2e-5), examining hab-off rows, 30 seeds:
    B3 x {fixed-cue, multicue}
    B4 x {fixed-cue, multicue}

Interpretation:
    If B4-fixedcue ~= +3%:  the STL habituation clause changes task rankings
                             even when eta=1 (softmin / ranking effect).
    If B3-multicue ~= +3%:  multicue selection interacting with reservation
                             dispatch is the source.
    If neither:              interaction effect between both factors.

B3-fixedcue and B4-multicue already exist in the confirmatory ladder (seeds
125-154, n=30).  Only B3-multicue and B4-fixedcue are run fresh.
B1 is included as reference and loaded from the existing confirmatory ladder.

B4_res_stl_full_fixedcue must be defined in run_habituation_stl_production_ladder.py
(added alongside the other system definitions).

Output:
    results/testbench/habituation_stl_2x2_overhead/
        per_run_metrics.csv          (all 4 cells + B1)
        overhead_2x2_summary.csv
        overhead_2x2_summary.md
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

# ── Constants ─────────────────────────────────────────────────────────────────

B1          = "B1_greedy_fixedcue"
B3_FIXED    = "B3_res_stl_nohab_fixedcue"
B3_MULTI    = "B3_res_stl_nohab_multicue"
B4_MULTI    = "B4_res_stl_full_multicue"
B4_FIXED    = "B4_res_stl_full_fixedcue"

# Confirmatory ladder CSV — provides B1, B3_FIXED (seeds 125–154)
CONFIRM_CSV = (REPO_ROOT / "results" / "testbench"
               / "habituation_stl_revised_confirm_with_b2_1800s_10seed"
               / "per_run_metrics.csv")

# Post-softmin-fix B4-multicue (correct arena, correct hab_off)
B4_CORRECTED_CSV = (REPO_ROOT / "results" / "testbench"
                    / "habituation_stl_b4_corrected_2em05"
                    / "per_run_metrics.csv")

DEFAULT_OUTDIR      = "results/testbench/habituation_stl_2x2_overhead"
DEFAULT_NUM_RUNS    = 30
DEFAULT_SEED_START  = 125
DEFAULT_MAX_WORKERS = 20
DEFAULT_MU          = 2e-5


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(rows: list[dict], path: Path) -> None:
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
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(rows)


def _base_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        mu_true=getattr(args, "mu", DEFAULT_MU),
        outdir="",
        merge_existing_raw=False,
        nx=60,
        ny=48,
        nrobots=4,
        duration_s=1800.0,
        warmup_s=0.0,
        task_replan_period_s=45.0,
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        max_workers=int(args.max_workers),
        systems=[],
        selected_config_overrides={},
        reservation_fraction=0.25,
        reactive_override_slack_s=90.0,
        predictive_max_eta_s=None,
        alpha_true=0.3,
        beta_true=0.25,
        sigma_true=12.0,
        omega_true=600.0,
        deterrence_beta_scale=4.0,
        deterrence_sigma_scale=4.0,
        deterrence_omega_scale=getattr(args, "deterrence_omega_scale", 3.0),
        fixed_cue_mode="laser",
        habituation_kappa=0.5,
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


def _run_systems(base: argparse.Namespace, systems: list[str], outdir: str) -> list[dict]:
    v = copy.copy(base)
    v.systems = list(systems)
    v.outdir = outdir
    v.selected_config_overrides = {}
    return ladder.run(v)


# ── Summary helpers ───────────────────────────────────────────────────────────

def _cell_stats(
    rows: list[dict],
    system: str,
    hab: str,
    b1_mean: float,
) -> dict:
    sub = [r for r in rows
           if str(r.get("baseline")) == system
           and str(r.get("habituation_condition")) == hab]
    exp_vals = [_safe(r.get("value_weighted_exposure")) for r in sub]
    exp_vals = [v for v in exp_vals if math.isfinite(v)]
    if not exp_vals:
        return {"system": system, "hab": hab, "n": 0,
                "mean_exposure": float("nan"), "pct_B1": float("nan"),
                "delta_vs_B1": float("nan")}
    mean_exp = stats.mean(exp_vals)
    delta    = mean_exp - b1_mean
    pct_b1   = delta / b1_mean * 100 if b1_mean and math.isfinite(b1_mean) else float("nan")
    return {
        "system":        system,
        "hab":           hab,
        "n":             len(exp_vals),
        "mean_exposure": round(mean_exp, 1),
        "delta_vs_B1":   round(delta, 1),
        "pct_B1":        round(pct_b1, 2),
    }


def _build_summary(all_rows: list[dict]) -> list[dict]:
    out = []
    for hab in ("hab_on", "hab_off"):
        b1_sub = [_safe(r.get("value_weighted_exposure")) for r in all_rows
                  if str(r.get("baseline")) == B1
                  and str(r.get("habituation_condition")) == hab]
        b1_sub = [v for v in b1_sub if math.isfinite(v)]
        b1_mean = stats.mean(b1_sub) if b1_sub else float("nan")
        for sys in (B1, B3_FIXED, B3_MULTI, B4_MULTI, B4_FIXED):
            out.append(_cell_stats(all_rows, sys, hab, b1_mean))
    return out


def _write_markdown(summary: list[dict], outdir: Path) -> None:
    lines = [
        "# 2x2 Overhead Isolation — hab-off results",
        "",
        "Design: {B3, B4} x {fixed-cue, multicue} at spare load "
        f"(mu=2e-5, kappa=0.50, n=30 seeds).",
        "",
        "**Interpretation**: If B4-fixedcue ~= +3%, overhead is from the STL "
        "habituation clause (softmin ranking effect). "
        "If B3-multicue ~= +3%, it is from multicue x reservation interaction.",
        "",
        "## hab-off",
        "",
        "| System | n | Mean exposure | Delta vs B1 | % B1 |",
        "|--------|---|--------------|-------------|------|",
    ]
    for row in summary:
        if row["hab"] != "hab_off":
            continue
        lines.append(
            f"| {row['system']} | {row['n']} "
            f"| {row['mean_exposure']:,.0f} "
            f"| {row['delta_vs_B1']:+,.0f} "
            f"| {row['pct_B1']:+.1f}% |"
        )
    lines += [
        "",
        "## hab-on (for reference)",
        "",
        "| System | n | Mean exposure | Delta vs B1 | % B1 |",
        "|--------|---|--------------|-------------|------|",
    ]
    for row in summary:
        if row["hab"] != "hab_on":
            continue
        lines.append(
            f"| {row['system']} | {row['n']} "
            f"| {row['mean_exposure']:,.0f} "
            f"| {row['delta_vs_B1']:+,.0f} "
            f"| {row['pct_B1']:+.1f}% |"
        )
    lines.append("")
    (outdir / "overhead_2x2_summary.md").write_text("\n".join(lines), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    combined_csv = outdir / "per_run_metrics.csv"

    if combined_csv.exists() and not getattr(args, "force_rerun", False):
        print(f"[2x2] Combined CSV exists — loading from {combined_csv}", flush=True)
        all_rows = _load_csv(combined_csv)
    else:
        base = _base_args(args)

        # ── Load existing data: B1 + B3-fixedcue from confirmatory,
        #    B4-multicue from corrected run (post-softmin-fix, correct hab_off) ──
        print(f"[2x2] Loading B1/B3-fixed from confirmatory: {CONFIRM_CSV}", flush=True)
        confirm_rows = _load_csv(CONFIRM_CSV)
        if not confirm_rows:
            print("[2x2] WARNING: confirmatory CSV not found — B1/B3-fixedcue "
                  "will be run fresh.", flush=True)

        print(f"[2x2] Loading B4-multi from corrected run: {B4_CORRECTED_CSV}", flush=True)
        b4_corrected_rows = _load_csv(B4_CORRECTED_CSV)
        if not b4_corrected_rows:
            print("[2x2] WARNING: B4_CORRECTED_CSV not found — B4-multicue hab_off "
                  "will be incorrect (softmin collapse bug). Run b4_corrected_2em05 first.",
                  flush=True)

        existing_rows = (
            [r for r in confirm_rows if str(r.get("baseline")) in {B1, B3_FIXED}]
            + [r for r in b4_corrected_rows if str(r.get("baseline")) == B4_MULTI]
        )

        seeds_needed = set(range(args.seed_start, args.seed_start + args.num_runs))
        existing_seeds = {int(r["seed"]) for r in existing_rows
                          if r.get("baseline") == B1 and r.get("habituation_condition") == "hab_on"
                          and r.get("seed", "").lstrip("-").isdigit()}
        missing_seeds = seeds_needed - existing_seeds
        if missing_seeds:
            print(f"[2x2] WARNING: seeds {sorted(missing_seeds)} missing from confirmatory "
                  f"data for B1 — they will be re-run.", flush=True)

        # ── Run B3-multicue and B4-fixedcue fresh ────────────────────────────
        print(f"[2x2] Running B3-multicue and B4-fixedcue "
              f"(seeds {args.seed_start}–{args.seed_start + args.num_runs - 1}, "
              f"max_workers={args.max_workers}) ...", flush=True)
        new_rows = _run_systems(
            base,
            systems=[B3_MULTI, B4_FIXED],
            outdir=str(outdir / "new_cells"),
        )

        # ── Merge: de-duplicate B1 rows if re-run ────────────────────────────
        new_baselines = {str(r.get("baseline")) for r in new_rows}
        all_rows = list(existing_rows)
        seen_b1: set[tuple[str, int]] = set()
        for r in existing_rows:
            if str(r.get("baseline")) == B1:
                key = (str(r.get("habituation_condition", "")), int(r.get("seed", 0)))
                seen_b1.add(key)
        for r in new_rows:
            if str(r.get("baseline")) == B1:
                key = (str(r.get("habituation_condition", "")), int(r.get("seed", 0)))
                if key in seen_b1:
                    continue
                seen_b1.add(key)
            all_rows.append(r)

        _write_csv(all_rows, combined_csv)
        print(f"[2x2] Wrote {len(all_rows)} rows to {combined_csv}", flush=True)

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = _build_summary(all_rows)
    _write_csv(summary, outdir / "overhead_2x2_summary.csv")
    _write_markdown(summary, outdir)

    print("\n[2x2] === hab-off results ===", flush=True)
    print(f"  {'System':<35} {'n':>4}  {'delta_vs_B1':>12}  {'pct_B1':>8}", flush=True)
    for row in summary:
        if row["hab"] != "hab_off":
            continue
        print(f"  {row['system']:<35} {row['n']:>4}  "
              f"{row['delta_vs_B1']:>+12,.0f}  {row['pct_B1']:>+7.2f}%", flush=True)
    print(f"\n[2x2] Done. Results at {outdir}", flush=True)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="2x2 overhead isolation: {B3,B4} x {fixed-cue,multicue} at spare load, hab-off."
    )
    p.add_argument("--outdir", default=DEFAULT_OUTDIR)
    p.add_argument("--num-runs", type=int, default=DEFAULT_NUM_RUNS)
    p.add_argument("--seed-start", type=int, default=DEFAULT_SEED_START)
    p.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    p.add_argument("--deterrence-omega-scale", type=float, default=3.0,
                   help="Omega scale for deterrence window (canonical=3.0).")
    p.add_argument("--force-rerun", action="store_true",
                   help="Re-run even if combined CSV already exists.")
    return p.parse_args(argv)


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
