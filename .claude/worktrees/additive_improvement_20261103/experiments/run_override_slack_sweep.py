"""run_override_slack_sweep.py

Sweep reactive_override_slack_s and predictive_max_eta_s for B4
vs the B1 reference baseline across multiple load levels (mu_true).

For each (mu_true, variant) combination the script calls
``ladder.run(args)`` with appropriately patched args so that
``_reserved_dispatch_params`` picks up the correct slack / cap values.

Output layout::

    results/testbench/habituation_stl_override_sweep/
        mu_2em05/
            per_run_metrics.csv        — all variants + B1 combined
            THESIS_RESULTS_SUMMARY.md  — markdown table per mu
        mu_1em04/ ...
        mu_4em04/ ...
        override_sweep_summary.csv     — cross-mu / cross-variant summary
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

# ── Constants ────────────────────────────────────────────────────────────────
B1_LABEL = "B1_greedy_fixedcue"
B4_BASE = "B4_res_stl_full_multicue"

_KEY_METRICS = [
    "value_weighted_exposure",
    "reactive_completed_fraction",
    "reactive_mean_response_time_s",
    "urgent_reactive_override_total",
    "habituation_eta_at_apply_mean",
    "habituation_variety_index",
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _mu_token(mu: float) -> str:
    """e.g. 2e-05 → 'mu_2em05',  4e-04 → 'mu_4em04'."""
    exp = math.floor(math.log10(mu))
    mantissa = mu / (10.0 ** exp)
    mantissa_str = f"{mantissa:.4g}".replace(".", "p")
    return f"mu_{mantissa_str}em{abs(exp):02d}"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _base_ladder_args(sweep_args: argparse.Namespace, mu_true: float) -> argparse.Namespace:
    """Build the ladder argparse.Namespace for a given mu_true, copying fixed params from sweep_args."""
    return argparse.Namespace(
        mu_true=mu_true,
        outdir="",            # set per call
        merge_existing_raw=False,
        # grid / fleet
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
        # systems — set per variant call
        systems=[],
        selected_config_overrides={},
        # dispatch — set per variant call
        reservation_fraction=0.25,
        reactive_override_slack_s=90.0,
        predictive_max_eta_s=None,
        # ground-truth process
        alpha_true=0.3,
        beta_true=0.25,
        sigma_true=12.0,
        omega_true=600.0,
        deterrence_beta_scale=4.0,
        deterrence_sigma_scale=4.0,
        deterrence_omega_scale=4.0,
        fixed_cue_mode="laser",
        # habituation
        habituation_kappa=0.5,
        truth_habituation_t_rec_s=None,
        truth_habituation_kappa=None,
        truth_habituation_gamma=None,
        truth_habituation_update_model=None,
        planner_habituation_t_rec_s=None,
        planner_habituation_kappa=None,
        planner_habituation_gamma=None,
        planner_habituation_update_model=None,
        # STL at confirmatory-run defaults
        stl_e_star=5.0,
        stl_t_cov_s=1200.0,
        stl_w_s=600.0,
        stl_eta_min=0.4,
        stl_horizon_s=300.0,
        stl_theta=12.0,
    )


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    """Write rows to CSV, unioning field names across all rows."""
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
        writer = csv.DictWriter(f, fieldnames=fields, restval="")
        writer.writeheader()
        writer.writerows(rows)


def _run_variant(
    base_args: argparse.Namespace,
    systems: list[str],
    outdir: str,
    reactive_override_slack_s: float,
    predictive_max_eta_s: float | None,
) -> list[dict[str, Any]]:
    """Run the ladder for a single variant configuration."""
    v_args = copy.copy(base_args)
    v_args.systems = list(systems)
    v_args.outdir = outdir
    v_args.reactive_override_slack_s = float(reactive_override_slack_s)
    v_args.predictive_max_eta_s = predictive_max_eta_s
    return ladder.run(v_args)


def _load_per_run_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ── Summary builders ──────────────────────────────────────────────────────────
def _build_mu_summary(
    all_rows: list[dict[str, Any]],
    all_variant_labels: list[str],
    mu_true: float,
) -> list[dict[str, Any]]:
    """Build per-(variant, hab_condition) summary rows for one mu_true value."""
    out: list[dict[str, Any]] = []
    for hab in ("hab_on", "hab_off"):
        for variant in all_variant_labels:
            sub = [
                r for r in all_rows
                if str(r.get("baseline")) == variant
                and str(r.get("habituation_condition")) == hab
            ]
            if not sub:
                continue

            exp_vals = [_safe_float(r.get("value_weighted_exposure")) for r in sub]
            exp_vals = [v for v in exp_vals if math.isfinite(v)]
            frac_vals = [_safe_float(r.get("reactive_completed_fraction")) for r in sub]
            frac_vals = [v for v in frac_vals if math.isfinite(v)]
            override_vals = [_safe_float(r.get("urgent_reactive_override_total")) for r in sub]
            override_vals = [v for v in override_vals if math.isfinite(v)]
            eta_vals = [_safe_float(r.get("habituation_eta_at_apply_mean")) for r in sub]
            eta_vals = [v for v in eta_vals if math.isfinite(v)]
            variety_vals = [_safe_float(r.get("habituation_variety_index")) for r in sub]
            variety_vals = [v for v in variety_vals if math.isfinite(v)]

            mean_exp = float(stats.mean(exp_vals)) if exp_vals else float("nan")
            exp_ci_lo, exp_ci_hi = ladder._ci95(exp_vals)
            mean_frac = float(stats.mean(frac_vals)) if frac_vals else float("nan")
            frac_ci_lo, frac_ci_hi = ladder._ci95(frac_vals)

            delta_exp = ladder._paired_deltas(all_rows, variant, B1_LABEL, hab, "value_weighted_exposure")
            delta_frac = ladder._paired_deltas(all_rows, variant, B1_LABEL, hab, "reactive_completed_fraction")

            row: dict[str, Any] = {
                "mu_true": mu_true,
                "variant": variant,
                "habituation_condition": hab,
                "n_seeds": len(exp_vals),
                "mean_exposure": mean_exp,
                "exposure_ci_lo": exp_ci_lo,
                "exposure_ci_hi": exp_ci_hi,
                "mean_reactive_completed_frac": mean_frac,
                "reactive_frac_ci_lo": frac_ci_lo,
                "reactive_frac_ci_hi": frac_ci_hi,
                "mean_override_count": float(stats.mean(override_vals)) if override_vals else float("nan"),
                "mean_eta_at_apply": float(stats.mean(eta_vals)) if eta_vals else float("nan"),
                "mean_variety_index": float(stats.mean(variety_vals)) if variety_vals else float("nan"),
                "delta_exposure_vs_B1": float(stats.mean(delta_exp)) if delta_exp else float("nan"),
                "delta_frac_vs_B1": float(stats.mean(delta_frac)) if delta_frac else float("nan"),
            }
            out.append(row)
    return out


def _write_mu_markdown(
    all_rows: list[dict[str, Any]],
    all_variant_labels: list[str],
    mu_true: float,
    outdir: Path,
) -> None:
    """Write a per-mu Markdown summary table."""
    lines = [
        f"# Override Slack Sweep — mu_true={mu_true:.2e}",
        "",
        "| Variant | Hab | N | Mean exposure | Mean reactive frac | Mean overrides | Δexp vs B1 | Δfrac vs B1 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for hab in ("hab_on", "hab_off"):
        for variant in all_variant_labels:
            sub = [
                r for r in all_rows
                if str(r.get("baseline")) == variant
                and str(r.get("habituation_condition")) == hab
            ]
            if not sub:
                continue
            exp_vals = [_safe_float(r.get("value_weighted_exposure")) for r in sub]
            exp_vals = [v for v in exp_vals if math.isfinite(v)]
            frac_vals = [_safe_float(r.get("reactive_completed_fraction")) for r in sub]
            frac_vals = [v for v in frac_vals if math.isfinite(v)]
            override_vals = [_safe_float(r.get("urgent_reactive_override_total")) for r in sub]
            override_vals = [v for v in override_vals if math.isfinite(v)]

            mean_exp_str = f"{stats.mean(exp_vals):.4f}" if exp_vals else "—"
            mean_frac_str = f"{stats.mean(frac_vals):.3f}" if frac_vals else "—"
            mean_ov_str = f"{stats.mean(override_vals):.1f}" if override_vals else "—"

            delta_exp = ladder._paired_deltas(all_rows, variant, B1_LABEL, hab, "value_weighted_exposure")
            delta_frac = ladder._paired_deltas(all_rows, variant, B1_LABEL, hab, "reactive_completed_fraction")
            d_exp_str: str
            d_frac_str: str
            if delta_exp:
                d_exp_str = f"{stats.mean(delta_exp):.4f}"
            elif variant == B1_LABEL:
                d_exp_str = "0.0000"
            else:
                d_exp_str = "—"
            if delta_frac:
                d_frac_str = f"{stats.mean(delta_frac):.3f}"
            elif variant == B1_LABEL:
                d_frac_str = "0.000"
            else:
                d_frac_str = "—"

            lines.append(
                f"| {variant} | {hab} | {len(sub)} | {mean_exp_str} "
                f"| {mean_frac_str} | {mean_ov_str} | {d_exp_str} | {d_frac_str} |"
            )
    lines.append("")
    lines.append(
        "Negative Δexp vs B1 means lower exposure (better). "
        "Positive Δfrac vs B1 means higher reactive completion rate (better)."
    )
    lines.append("")
    lines += [
        "## Source Tables",
        "",
        "- `per_run_metrics.csv`",
        "- `../override_sweep_summary.csv`",
    ]
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "THESIS_RESULTS_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Main run ──────────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    mu_values: list[float] = sorted(args.mu_values)
    override_slack_values: list[float] = sorted(args.override_slack_values)
    travel_cap_values: list[float] = sorted(args.travel_cap_values)

    # Build the variant table:
    # Each entry is (variant_label, systems_list, reactive_override_slack_s, predictive_max_eta_s)
    b4_variants: list[tuple[str, list[str], float, float | None]] = [
        (f"B4_slack_{int(s)}s", [B1_LABEL, B4_BASE], s, None)
        for s in override_slack_values
    ]
    b4_variants += [
        (f"B4_travel_cap_{int(c)}s", [B1_LABEL, B4_BASE], 90.0, c)
        for c in sorted(travel_cap_values)
    ]

    b4_variant_labels = [v[0] for v in b4_variants]
    all_variant_labels = [B1_LABEL] + b4_variant_labels

    print(
        f"[override_sweep] mu_values={[f'{m:.2e}' for m in mu_values]}  "
        f"variants={b4_variant_labels}  num_runs={args.num_runs}  outdir={outdir}",
        flush=True,
    )

    all_summary_rows: list[dict[str, Any]] = []

    for mu_true in mu_values:
        token = _mu_token(mu_true)
        mu_outdir = outdir / token
        mu_outdir.mkdir(parents=True, exist_ok=True)

        combined_csv = mu_outdir / "per_run_metrics.csv"
        if combined_csv.exists():
            print(
                f"\n[override_sweep] mu={mu_true:.2e}  SKIPPING "
                f"(per_run_metrics.csv exists)",
                flush=True,
            )
            existing = _load_per_run_csv(combined_csv)
            present = sorted({str(r.get("baseline")) for r in existing})
            present_b4 = [v for v in b4_variant_labels if v in present]
            present_all = ([B1_LABEL] if B1_LABEL in present else []) + present_b4
            all_summary_rows += _build_mu_summary(existing, present_all, mu_true)
            continue

        print(f"\n[override_sweep] --- mu={mu_true:.2e}  subdir={token} ---", flush=True)
        base_args = _base_ladder_args(args, mu_true)

        # Collect all rows across variants; B1 will be duplicated (once per variant call)
        all_rows: list[dict[str, Any]] = []

        for variant_label, systems, slack, max_eta in b4_variants:
            variant_outdir = mu_outdir / variant_label
            print(
                f"[override_sweep]   running variant={variant_label}  "
                f"slack={slack}  max_eta={max_eta}",
                flush=True,
            )
            rows = _run_variant(
                base_args=base_args,
                systems=systems,
                outdir=str(variant_outdir),
                reactive_override_slack_s=slack,
                predictive_max_eta_s=max_eta,
            )
            # Rename B4 rows to the variant label; keep B1 rows with their original label
            for row in rows:
                row_copy = dict(row)
                if str(row_copy.get("baseline")) == B4_BASE:
                    hab = str(row_copy.get("habituation_condition", ""))
                    row_copy["baseline"] = variant_label
                    row_copy["system"] = f"{variant_label}_{hab}"
                all_rows.append(row_copy)

        # De-duplicate B1 rows: each variant call ran B1 at the same seeds,
        # so keep only the first occurrence of each (hab_condition, seed) pair.
        seen_b1: set[tuple[str, int]] = set()
        b1_rows: list[dict[str, Any]] = []
        b4_rows: list[dict[str, Any]] = []
        for row in all_rows:
            if str(row.get("baseline")) == B1_LABEL:
                key = (str(row.get("habituation_condition", "")), int(row.get("seed", 0)))
                if key not in seen_b1:
                    seen_b1.add(key)
                    b1_rows.append(row)
            else:
                b4_rows.append(row)
        combined_rows = b1_rows + b4_rows

        _write_csv(combined_rows, combined_csv)
        _write_mu_markdown(combined_rows, all_variant_labels, mu_true, mu_outdir)
        mu_summary = _build_mu_summary(combined_rows, all_variant_labels, mu_true)
        all_summary_rows += mu_summary
        print(
            f"[override_sweep] mu={mu_true:.2e} done  "
            f"{len(combined_rows)} combined rows  "
            f"{len(mu_summary)} summary rows",
            flush=True,
        )

    summary_path = outdir / "override_sweep_summary.csv"
    _write_csv(all_summary_rows, summary_path)
    print(
        f"\n[override_sweep] Complete.  "
        f"{len(mu_values)} mu_true points × "
        f"{len(b4_variants)} B4 variants + B1 reference.",
        flush=True,
    )
    print(f"[override_sweep] Summary: {summary_path}", flush=True)


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep reactive_override_slack_s and predictive_max_eta_s for B4 "
            "vs the B1 reference baseline across multiple load levels. "
            "Fixed parameters match the confirmatory thesis runs."
        )
    )
    parser.add_argument(
        "--mu-values",
        nargs="+",
        type=float,
        default=[2e-5, 1e-4, 4e-4],
        metavar="FLOAT",
        help="mu_true values to sweep. Default: 2e-5 1e-4 4e-4.",
    )
    parser.add_argument(
        "--outdir",
        default="results/testbench/habituation_stl_override_sweep",
        help="Root output directory.",
    )
    parser.add_argument("--num-runs", type=int, default=10)
    parser.add_argument("--seed-start", type=int, default=125)
    parser.add_argument("--duration-s", type=float, default=1800.0)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--nx", type=int, default=60)
    parser.add_argument("--ny", type=int, default=48)
    parser.add_argument("--nrobots", type=int, default=4)
    parser.add_argument(
        "--override-slack-values",
        nargs="+",
        type=float,
        default=[30.0, 45.0, 60.0, 90.0],
        metavar="FLOAT",
        help="reactive_override_slack_s values to sweep for B4. Default: 30 45 60 90.",
    )
    parser.add_argument(
        "--travel-cap-values",
        nargs="+",
        type=float,
        default=[60.0, 90.0],
        metavar="FLOAT",
        help="predictive_max_eta_s values to test (with slack=90). Default: 60 90.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
