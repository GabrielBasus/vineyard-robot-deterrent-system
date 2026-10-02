"""run_b2_b3_topup.py

Top up B2 (Res + ΔJ) and B3 (Res + STL, no-hab, fixedcue) to 30 seeds at
three load levels: µ=2×10⁻⁵, µ=1×10⁻⁴, µ=4×10⁻⁴.

Existing data:
  µ=2e-5:  seeds 125-134 for B2+B3 in
           habituation_stl_revised_confirm_with_b2_1800s_10seed/
  µ=1e-4:  seeds 125-134 for B2 (B3 was multicue, unusable) in
           habituation_stl_load_sweep_highload/mu_1em04/
  µ=4e-4:  same as µ=1e-4

New seeds:
  µ=2e-5:  seeds 135-154 for B2 and B3-fixedcue  (20 per system)
  µ=1e-4:  seeds 135-154 for B2  (20) + seeds 125-154 for B3-fixedcue  (30)
  µ=4e-4:  same as µ=1e-4

Output layout::

    results/testbench/habituation_stl_b2_b3_topup/
        mu_2em05/
            per_run_metrics.csv     (new seeds 135-154 for B2+B3)
        mu_1em04/
            per_run_metrics.csv     (B2 seeds 135-154 + B3-fixedcue seeds 125-154)
        mu_4em04/
            per_run_metrics.csv
        topup_summary.csv           (per-system summary of new-seed data only)
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

B2_LABEL = "B2_res_deltaJ_fixedcue"
B3_LABEL = "B3_res_stl_nohab_fixedcue"

DEFAULT_OUTDIR      = "results/testbench/habituation_stl_b2_b3_topup"
DEFAULT_MAX_WORKERS = 20


# ── helpers ───────────────────────────────────────────────────────────────────

def _mu_token(mu: float) -> str:
    exp = math.floor(math.log10(mu))
    mantissa = mu / (10.0 ** exp)
    return f"mu_{mantissa:.4g}em{abs(exp):02d}".replace(".", "p")


def _safe(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


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


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _base_args(mu_true: float, systems: list[str],
               seed_start: int, num_runs: int, max_workers: int,
               outdir: str) -> argparse.Namespace:
    return argparse.Namespace(
        mu_true=mu_true,
        outdir=outdir,
        merge_existing_raw=False,
        nx=60,
        ny=48,
        nrobots=4,
        duration_s=1800.0,
        warmup_s=0.0,
        task_replan_period_s=45.0,
        num_runs=num_runs,
        seed_start=seed_start,
        max_workers=max_workers,
        systems=systems,
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
        deterrence_omega_scale=4.0,
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


def _build_summary(rows: list[dict], mu_true: float) -> list[dict]:
    systems = sorted({str(r.get("baseline")) for r in rows})
    out = []
    for hab in ("hab_on", "hab_off"):
        for sys in systems:
            sub = [r for r in rows
                   if str(r.get("baseline")) == sys
                   and str(r.get("habituation_condition")) == hab]
            if not sub:
                continue
            exp_vals = [v for v in (_safe(r.get("value_weighted_exposure")) for r in sub)
                        if math.isfinite(v)]
            frac_vals = [v for v in (_safe(r.get("reactive_completed_fraction")) for r in sub)
                         if math.isfinite(v)]
            exp_lo, exp_hi = ladder._ci95(exp_vals)
            out.append({
                "mu_true": mu_true,
                "system": sys,
                "habituation_condition": hab,
                "n_seeds": len(exp_vals),
                "mean_exposure": stats.mean(exp_vals) if exp_vals else float("nan"),
                "exposure_ci_lo": exp_lo,
                "exposure_ci_hi": exp_hi,
                "mean_reactive_completed_frac": stats.mean(frac_vals) if frac_vals else float("nan"),
            })
    return out


# ── run schedule ─────────────────────────────────────────────────────────────

#  Each entry: (mu_true, system, seed_start, num_runs)
#  We break into separate batch calls so each has its own output CSV.
_RUN_SCHEDULE: list[tuple[float, list[str], int, int]] = [
    # µ=2e-5: top up B2 and B3-fixedcue from seed 135 (20 more seeds)
    (2e-5,  [B2_LABEL, B3_LABEL], 135, 20),
    # µ=1e-4: top up B2 from seed 135, B3-fixedcue all 30 seeds
    (1e-4,  [B2_LABEL],           135, 20),
    (1e-4,  [B3_LABEL],           125, 30),
    # µ=4e-4: same as µ=1e-4
    (4e-4,  [B2_LABEL],           135, 20),
    (4e-4,  [B3_LABEL],           125, 30),
]


def run(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"[b2_b3_topup] outdir={outdir}  max_workers={args.max_workers}", flush=True)

    all_summary: list[dict] = []

    # Group the schedule by mu for combined per_run_metrics.csv output
    mu_all_rows: dict[float, list[dict]] = {}

    for mu_true, systems, seed_start, num_runs in _RUN_SCHEDULE:
        token = _mu_token(mu_true)
        # Create a per-batch subdirectory to avoid collisions
        sys_token = "_".join(s.split("_")[0] for s in systems)
        batch_label = f"{sys_token}_s{seed_start}_n{num_runs}"
        batch_outdir = outdir / token / batch_label
        combined_csv = batch_outdir / "per_run_metrics.csv"

        if combined_csv.exists():
            print(f"\n[b2_b3_topup] {token}/{batch_label} SKIPPING (CSV exists)", flush=True)
            existing = _load_csv(combined_csv)
            mu_all_rows.setdefault(mu_true, []).extend(existing)
            continue

        print(
            f"\n[b2_b3_topup] {token}/{batch_label}  systems={systems}"
            f"  seeds {seed_start}–{seed_start+num_runs-1}",
            flush=True,
        )
        a = _base_args(
            mu_true=mu_true,
            systems=systems,
            seed_start=seed_start,
            num_runs=num_runs,
            max_workers=int(args.max_workers),
            outdir=str(batch_outdir),
        )
        rows = ladder.run(a)
        mu_all_rows.setdefault(mu_true, []).extend(rows)

    # Write per-mu combined CSV
    for mu_true, rows in mu_all_rows.items():
        token = _mu_token(mu_true)
        mu_outdir = outdir / token
        _write_csv(rows, mu_outdir / "per_run_metrics.csv")
        print(f"[b2_b3_topup] wrote combined {token}/per_run_metrics.csv  ({len(rows)} rows)",
              flush=True)
        all_summary.extend(_build_summary(rows, mu_true))

    _write_csv(all_summary, outdir / "topup_summary.csv")
    print(f"\n[b2_b3_topup] Done.  {outdir / 'topup_summary.csv'}", flush=True)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Top up B2/B3-fixedcue to 30 seeds at 3 loads.")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR)
    p.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    return p.parse_args(argv)


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
