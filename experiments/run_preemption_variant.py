"""run_preemption_variant.py

Compare B4 (standard) vs B4_preempt (preempts mid-flight predictive tasks
when a reactive task is waiting) at three load levels.

Each (mu, variant) pair is run through the production ladder.
B4_preempt uses ``selected_config_overrides`` to inject
``preempt_predictive_with_reactive=True`` into the B4 params.

Output layout::

    results/testbench/habituation_stl_preemption_variant/
        mu_2em05/
            B4_base/         per_run_metrics.csv (B1 + B4 base)
            B4_preempt/      per_run_metrics.csv (B1 + B4 preempt)
            per_run_metrics.csv   (combined, B1 de-duplicated)
            THESIS_RESULTS_SUMMARY.md
        mu_1em04/ ...
        mu_4em04/ ...
        preemption_variant_summary.csv
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

B1_LABEL   = "B1_greedy_fixedcue"
B4_BASE    = "B4_res_stl_full_multicue"
B4_PREEMPT = "B4_preempt"

DEFAULT_MU_VALUES   = [2e-5, 1e-4, 4e-4]
DEFAULT_OUTDIR      = "results/testbench/habituation_stl_preemption_variant"
DEFAULT_NUM_RUNS    = 30
DEFAULT_SEED_START  = 125
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


def _base_args(sweep_args: argparse.Namespace, mu_true: float) -> argparse.Namespace:
    return argparse.Namespace(
        mu_true=mu_true,
        outdir="",
        merge_existing_raw=False,
        nx=60,
        ny=48,
        nrobots=4,
        duration_s=1800.0,
        warmup_s=0.0,
        task_replan_period_s=45.0,
        num_runs=int(sweep_args.num_runs),
        seed_start=int(sweep_args.seed_start),
        max_workers=int(sweep_args.max_workers),
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


def _run_variant(
    base_args: argparse.Namespace,
    systems: list[str],
    outdir: str,
    config_overrides: dict,
) -> list[dict]:
    v = copy.copy(base_args)
    v.systems = list(systems)
    v.outdir = outdir
    v.selected_config_overrides = dict(config_overrides)
    return ladder.run(v)


def _build_summary(rows: list[dict], variants: list[str], mu_true: float) -> list[dict]:
    out = []
    for hab in ("hab_on", "hab_off"):
        for variant in variants:
            sub = [r for r in rows
                   if str(r.get("baseline")) == variant
                   and str(r.get("habituation_condition")) == hab]
            if not sub:
                continue
            exp_vals     = [v for v in (_safe(r.get("value_weighted_exposure")) for r in sub)
                            if math.isfinite(v)]
            frac_vals    = [v for v in (_safe(r.get("reactive_completed_fraction")) for r in sub)
                            if math.isfinite(v)]
            preempt_vals = [v for v in (_safe(r.get("preempt_predictive_override_total")) for r in sub)
                            if math.isfinite(v)]
            override_vals = [v for v in (_safe(r.get("urgent_reactive_override_total")) for r in sub)
                             if math.isfinite(v)]

            mean_exp = stats.mean(exp_vals) if exp_vals else float("nan")
            exp_lo, exp_hi = ladder._ci95(exp_vals)
            mean_frac = stats.mean(frac_vals) if frac_vals else float("nan")
            frac_lo, frac_hi = ladder._ci95(frac_vals)
            miss_rate = 1.0 - mean_frac if math.isfinite(mean_frac) else float("nan")

            delta_exp  = ladder._paired_deltas(rows, variant, B1_LABEL, hab, "value_weighted_exposure")
            delta_frac = ladder._paired_deltas(rows, variant, B1_LABEL, hab, "reactive_completed_fraction")

            out.append({
                "mu_true": mu_true,
                "variant": variant,
                "habituation_condition": hab,
                "n_seeds": len(exp_vals),
                "mean_exposure": mean_exp,
                "exposure_ci_lo": exp_lo,
                "exposure_ci_hi": exp_hi,
                "mean_reactive_completed_frac": mean_frac,
                "reactive_frac_ci_lo": frac_lo,
                "reactive_frac_ci_hi": frac_hi,
                "miss_rate": miss_rate,
                "mean_preempt_count": stats.mean(preempt_vals) if preempt_vals else float("nan"),
                "mean_override_count": stats.mean(override_vals) if override_vals else float("nan"),
                "delta_exposure_vs_B1": stats.mean(delta_exp) if delta_exp else float("nan"),
                "delta_frac_vs_B1": stats.mean(delta_frac) if delta_frac else float("nan"),
            })
    return out


# ── main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    mu_values: list[float] = sorted(args.mu_values)
    print(
        f"[preemption_variant] mu_values={[f'{m:.2e}' for m in mu_values]}"
        f"  num_runs={args.num_runs}  max_workers={args.max_workers}  outdir={outdir}",
        flush=True,
    )

    all_summary_rows: list[dict] = []
    all_variants = [B1_LABEL, B4_BASE, B4_PREEMPT]

    for mu_true in mu_values:
        token = _mu_token(mu_true)
        mu_outdir = outdir / token
        mu_outdir.mkdir(parents=True, exist_ok=True)
        combined_csv = mu_outdir / "per_run_metrics.csv"

        if combined_csv.exists():
            print(f"\n[preemption_variant] mu={mu_true:.2e} SKIPPING (per_run_metrics.csv exists)",
                  flush=True)
            existing = _load_csv(combined_csv)
            present = sorted({str(r.get("baseline")) for r in existing})
            all_summary_rows += _build_summary(existing, present, mu_true)
            continue

        print(f"\n[preemption_variant] --- mu={mu_true:.2e}  subdir={token} ---", flush=True)
        base = _base_args(args, mu_true)
        all_rows: list[dict] = []

        # --- B4 base (preemption disabled, default) ---
        print("[preemption_variant]   running B4_base ...", flush=True)
        base_rows = _run_variant(
            base,
            systems=[B1_LABEL, B4_BASE],
            outdir=str(mu_outdir / "B4_base"),
            config_overrides={},
        )
        all_rows.extend(base_rows)

        # --- B4 preempt (preemption enabled) ---
        print("[preemption_variant]   running B4_preempt ...", flush=True)
        preempt_rows = _run_variant(
            base,
            systems=[B4_BASE],
            outdir=str(mu_outdir / "B4_preempt"),
            config_overrides={B4_BASE: {"preempt_predictive_with_reactive": True}},
        )
        # Relabel B4 rows as B4_preempt
        for row in preempt_rows:
            row_copy = dict(row)
            if str(row_copy.get("baseline")) == B4_BASE:
                hab = str(row_copy.get("habituation_condition", ""))
                row_copy["baseline"] = B4_PREEMPT
                row_copy["system"] = f"{B4_PREEMPT}_{hab}"
            all_rows.append(row_copy)

        # De-duplicate B1 rows
        seen_b1: set[tuple[str, int]] = set()
        dedup: list[dict] = []
        for row in all_rows:
            if str(row.get("baseline")) == B1_LABEL:
                key = (str(row.get("habituation_condition", "")), int(row.get("seed", 0)))
                if key in seen_b1:
                    continue
                seen_b1.add(key)
            dedup.append(row)

        _write_csv(dedup, combined_csv)
        print(f"[preemption_variant]   wrote {combined_csv}", flush=True)

        summary_rows = _build_summary(dedup, all_variants, mu_true)
        all_summary_rows.extend(summary_rows)

        # Markdown summary
        _write_markdown(dedup, all_variants, mu_true, mu_outdir)

    # Global summary CSV
    _write_csv(all_summary_rows, outdir / "preemption_variant_summary.csv")
    print(f"\n[preemption_variant] Done.  Summary: {outdir / 'preemption_variant_summary.csv'}",
          flush=True)


def _write_markdown(rows: list[dict], variants: list[str], mu_true: float, outdir: Path) -> None:
    lines = [
        f"# Preemption Variant — mu_true={mu_true:.2e}",
        "",
        "| Variant | Hab | N | Mean exposure | Miss rate | Preempt count | Δexp vs B1 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for hab in ("hab_on", "hab_off"):
        for variant in variants:
            sub = [r for r in rows
                   if str(r.get("baseline")) == variant
                   and str(r.get("habituation_condition")) == hab]
            if not sub:
                continue
            exp_vals = [v for v in (_safe(r.get("value_weighted_exposure")) for r in sub)
                        if math.isfinite(v)]
            frac_vals = [v for v in (_safe(r.get("reactive_completed_fraction")) for r in sub)
                         if math.isfinite(v)]
            pre_vals = [v for v in (_safe(r.get("preempt_predictive_override_total")) for r in sub)
                        if math.isfinite(v)]
            delta_exp = ladder._paired_deltas(rows, variant, B1_LABEL, hab, "value_weighted_exposure")
            mean_exp = f"{stats.mean(exp_vals):.0f}" if exp_vals else "—"
            miss_r = f"{(1-stats.mean(frac_vals))*100:.1f}%" if frac_vals else "—"
            pre_c = f"{stats.mean(pre_vals):.0f}" if pre_vals else "0"
            d_exp = f"{stats.mean(delta_exp):.0f}" if delta_exp else ("0" if variant == B1_LABEL else "—")
            lines.append(f"| {variant} | {hab} | {len(sub)} | {mean_exp} | {miss_r} | {pre_c} | {d_exp} |")
    lines.append("")
    (outdir / "THESIS_RESULTS_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Preemption variant experiment for B4.")
    p.add_argument("--mu-values", nargs="+", type=float,
                   default=DEFAULT_MU_VALUES, metavar="MU",
                   help="Bird arrival rate(s) (default: 2e-5 1e-4 4e-4)")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR)
    p.add_argument("--num-runs", type=int, default=DEFAULT_NUM_RUNS)
    p.add_argument("--seed-start", type=int, default=DEFAULT_SEED_START)
    p.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    return p.parse_args(argv)


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
