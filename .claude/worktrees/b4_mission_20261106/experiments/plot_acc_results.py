"""plot_acc_results.py

Generate publication-quality figures and a self-contained data package for the
ACC submission.  Run from the repo root:

    python experiments/plot_acc_results.py [--outdir results/acc_submission]

Outputs
-------
results/acc_submission/
    figures/
        fig1_baseline_ladder.pdf / .png
        fig2_kappa_dose_response.pdf / .png
        fig3_tradeoff_scatter.pdf / .png
        fig4_override_counts.pdf / .png
    data/                          (copies only — originals untouched)
        ladder_per_run_metrics.csv
        joint_sweep_summary.csv
        override_sweep_summary.csv
        rho_res_sweep_summary.csv
        h4_30seed_extended_summary.csv
    tables/
        table1_ladder_summary.csv
        table1_ladder_summary.md
        table2_override_sweep_summary.csv
        table2_override_sweep_summary.md
"""
from __future__ import annotations

import argparse
import csv
import math
import shutil
import statistics as stats
import sys
import textwrap
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS = REPO_ROOT / "results" / "testbench"

SOURCE_FILES = {
    # Merged: B1-B5 at mu=2e-5 with 30-seed B2/B3 topup + fresh (bugfixed) B4
    "ladder": RESULTS / "acc_merged" / "ladder_2em05.csv",
    # Merged joint sweep: B1-B3/B5 from original + fresh B4 rows
    "joint_sweep": RESULTS / "acc_merged" / "joint_sweep_summary.csv",
    "override_sweep": RESULTS / "habituation_stl_override_sweep" / "override_sweep_summary.csv",
    "rho_res_sweep": RESULTS / "habituation_stl_rho_res_sweep" / "rho_res_sweep_summary.csv",
    "h4_30seed": RESULTS / "h4_tost_extended_mu1em04_kappa0p50" / "h4_tost_30seed_summary.csv",
    # Merged h4 rho_res sweep with fresh B4
    "h4_rho_res_sweep": RESULTS / "acc_merged" / "h4_rho_res_sweep_summary.csv",
    # Merged highload ladders with fresh B4 and 30-seed B2/B3-fixedcue
    "ladder_1em04": RESULTS / "acc_merged" / "ladder_1em04.csv",
    "ladder_4em04": RESULTS / "acc_merged" / "ladder_4em04.csv",
    # Topup data is now incorporated into merged ladder files; set to None to skip
    "topup_2em05": None,
    "topup_1em04": None,
    "topup_4em04": None,
    # Preemption variant results — populated by run_preemption_variant.py
    "preemption_2em05": RESULTS / "habituation_stl_preemption_variant" / "mu_2em05" / "per_run_metrics.csv",
    "preemption_1em04": RESULTS / "habituation_stl_preemption_variant" / "mu_1em04" / "per_run_metrics.csv",
    "preemption_4em04": RESULTS / "habituation_stl_preemption_variant" / "mu_4em04" / "per_run_metrics.csv",
    # 2×2 cost-decomposition (fixed-cue vs. multi-cue, hab-on vs. hab-off)
    "2x2_overhead": RESULTS / "acc_merged" / "2x2_overhead_corrected.csv",
}

# ── Label maps ────────────────────────────────────────────────────────────────
SYSTEM_LABELS: dict[str, str] = {
    "B1_greedy_fixedcue":        "B1",
    "B2_res_deltaJ_fixedcue":    "B2",
    "B3_res_stl_nohab_fixedcue": "B3",
    "B3_res_stl_nohab_multicue": "B3",
    "B4_res_stl_full_multicue":  "B4★",
    "B5_greedy_habcue":          "B5",
}
# Footnote used by Fig 1 and Fig 5 to label systems
SYS_FOOTNOTE = ("B1=Greedy, B2=Res.+ΔJ, B3=STL/no-hab, "
                "B4★=STL+Hab (proposed), B5=Greedy+Hab")
# Pre-wrapped at ~40 chars/line so neither line exceeds 3.5" at 7pt
SYS_FOOTNOTE_WRAPPED = (
    "B1=Greedy, B2=Res.+ΔJ, B3=STL/no-hab,\n"
    "B4★=STL+Hab (proposed), B5=Greedy+Hab"
)

# Short labels used for inline annotations in Fig 3
SLACK_LABELS_SHORT: dict[str, str] = {
    "B4_slack_30s":      "30 s",
    "B4_slack_45s":      "45 s",
    "B4_slack_60s":      "60 s",
    "B4_slack_90s":      "90 s",
    "B4_travel_cap_60s": "cap 60 s",
    "B4_travel_cap_90s": "cap 90 s",
}

SLACK_LABELS: dict[str, str] = {
    "B1_greedy_fixedcue":  "B1 (reference)",
    "B4_slack_30s":        "Slack 30 s",
    "B4_slack_45s":        "Slack 45 s",
    "B4_slack_60s":        "Slack 60 s",
    "B4_slack_90s":        "Slack 90 s (default)",
    "B4_travel_cap_60s":   "Travel cap 60 s",
    "B4_travel_cap_90s":   "Travel cap 90 s",
}

MU_LABELS: dict[float, str] = {
    2e-5:  "µ = 2×10⁻⁵\n(spare)",
    1e-4:  "µ = 1×10⁻⁴\n(heavy spare)",
    4e-4:  "µ = 4×10⁻⁴\n(overloaded)",
}

# ── Color palette (colorblind-safe) ───────────────────────────────────────────
COLORS = {
    "B1": "#4477AA",   # blue
    "B2": "#AAAAAA",   # grey
    "B3": "#EE8833",   # orange
    "B4": "#228833",   # green  ← proposed
    "B5": "#AA3377",   # purple
    "hab_on":  "#228833",
    "hab_off": "#4477AA",
}

def _system_color(key: str) -> str:
    for prefix in ("B1", "B2", "B3", "B4", "B5"):
        if key.startswith(prefix):
            return COLORS.get(prefix, "#888888")
    return "#888888"

# ── I/O helpers ───────────────────────────────────────────────────────────────
def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path or not path.exists():
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

def _safe(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")

def _ci95(vals: list[float]) -> tuple[float, float]:
    n = len(vals)
    if n < 2:
        return (float("nan"), float("nan"))
    m = stats.mean(vals)
    s = stats.stdev(vals)
    hw = 1.96 * s / math.sqrt(n)
    return (m - hw, m + hw)

# ── Figure helpers ────────────────────────────────────────────────────────────
def _style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 8.5,
        "figure.dpi": 300,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.35,
        "grid.linestyle": "--",
        "lines.linewidth": 1.5,
        "lines.markersize": 5,
        "errorbar.capsize": 2,
    })

def _savefig(fig: plt.Figure, stem: str, outdir: Path) -> None:
    fig_dir = outdir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_dir / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(fig_dir / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(fig_dir / f"{stem}.eps", bbox_inches="tight", format="eps")
    print(f"  saved {stem}.pdf / .svg / .eps")
    plt.close(fig)

# ─────────────────────────────────────────────────────────────────────────────
# Figure 1 — Baseline ladder bar chart (B1–B5, confirmatory point)
# ─────────────────────────────────────────────────────────────────────────────
def _fig1_ladder(outdir: Path) -> list[dict]:
    rows = _read_csv(SOURCE_FILES["ladder"])
    # Merge topup data (30-seed B2/B3) if available
    topup_rows = _read_csv(SOURCE_FILES["topup_2em05"])
    topup_baselines = {"B2_res_deltaJ_fixedcue", "B3_res_stl_nohab_fixedcue"}
    if topup_rows:
        topup_seeds = {(r.get("baseline",""), r.get("habituation_condition",""),
                        str(r.get("seed","")))
                       for r in topup_rows if r.get("baseline","") in topup_baselines}
        # Remove old B2/B3 rows that are duplicated in topup (shouldn't be, but guard)
        rows = [r for r in rows
                if r.get("baseline","") not in topup_baselines
                or (r.get("baseline",""), r.get("habituation_condition",""),
                    str(r.get("seed",""))) not in topup_seeds]
        rows.extend(topup_rows)

    order = [
        "B1_greedy_fixedcue",
        "B2_res_deltaJ_fixedcue",
        "B3_res_stl_nohab_fixedcue",
        "B4_res_stl_full_multicue",
        "B5_greedy_habcue",
    ]

    # Aggregate per (baseline, hab_condition)
    from collections import defaultdict
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        b = r.get("baseline", "")
        h = r.get("habituation_condition", "")
        v = _safe(r.get("value_weighted_exposure"))
        if b in order and h in ("hab_on", "hab_off") and math.isfinite(v):
            grouped[(b, h)].append(v)

    _style()
    fig, ax = plt.subplots(figsize=(3.5, 2.9))

    n_sys = len(order)
    x = np.arange(n_sys)
    width = 0.35

    means_on, errs_on, means_off, errs_off = [], [], [], []
    for sys in order:
        vals_on  = grouped.get((sys, "hab_on"),  [])
        vals_off = grouped.get((sys, "hab_off"), [])
        m_on  = stats.mean(vals_on)  if vals_on  else float("nan")
        m_off = stats.mean(vals_off) if vals_off else float("nan")
        lo_on, hi_on   = _ci95(vals_on)
        lo_off, hi_off = _ci95(vals_off)
        means_on.append(m_on);   errs_on.append(m_on  - lo_on)
        means_off.append(m_off); errs_off.append(m_off - lo_off)

    bar_on  = ax.bar(x - width/2, means_on,  width, yerr=errs_on,  capsize=2.5,
                     color=COLORS["hab_on"],  alpha=0.85, label="Hab. ON",
                     error_kw={"ecolor": "#114422", "lw": 1.2})
    bar_off = ax.bar(x + width/2, means_off, width, yerr=errs_off, capsize=2.5,
                     color=COLORS["hab_off"], alpha=0.85, label="Hab. OFF",
                     error_kw={"ecolor": "#223355", "lw": 1.2})

    # Highlight B4
    ax.axvspan(x[order.index("B4_res_stl_full_multicue")] - 0.45,
               x[order.index("B4_res_stl_full_multicue")] + 0.45,
               color="#CCFFCC", alpha=0.4, zorder=0)

    ax.set_xticks(x)
    ax.set_xticklabels([SYSTEM_LABELS.get(s, s) for s in order], fontsize=8.5)
    ax.set_ylabel("Value-weighted exposure\n(lower = stronger deterrence)", fontsize=9)
    b2_n = len(grouped.get(("B2_res_deltaJ_fixedcue", "hab_on"), []))
    b3_n = len(grouped.get(("B3_res_stl_nohab_fixedcue", "hab_on"), []))
    seed_note = "n=30 (all)" if min(b2_n, b3_n) >= 30 else f"n=30 (B1,B4,B5); n={min(b2_n,b3_n)} (B2,B3)"
    ax.set_title(f"B1–B5  |  µ=2×10⁻⁵, κ=0.50  |  {seed_note}", fontsize=9, pad=4)
    ax.legend(framealpha=0.9, loc="upper center", bbox_to_anchor=(0.5, -0.16),
              ncol=2, edgecolor="#cccccc", fontsize=8.5)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v/1e3:.0f}k"))
    fig.tight_layout(pad=0.6)
    fig.subplots_adjust(bottom=0.22)
    fig.text(0.5, -0.01, SYS_FOOTNOTE_WRAPPED, ha="center", va="top",
             fontsize=8.5, color="#555555", style="italic")
    _savefig(fig, "fig1_baseline_ladder", outdir)

    # Build table rows (% change vs B1 reference)
    table_rows = []
    b1_ref = {}
    for hab in ("hab_on", "hab_off"):
        b1_vals = grouped.get(("B1_greedy_fixedcue", hab), [])
        b1_ref[hab] = stats.mean(b1_vals) if b1_vals else float("nan")

    for sys in order:
        vals_on  = grouped.get((sys, "hab_on"),  [])
        vals_off = grouped.get((sys, "hab_off"), [])
        for hab, vals in [("hab_on", vals_on), ("hab_off", vals_off)]:
            if not vals:
                continue
            ref = b1_ref[hab]
            pct_vals = [(v - ref) / ref * 100 for v in vals]
            pct_mean = stats.mean(pct_vals)
            lo_pct, hi_pct = _ci95(pct_vals)
            table_rows.append({
                "system": SYSTEM_LABELS.get(sys, sys),
                "system_key": sys,
                "hab_condition": "Habituation ON" if hab == "hab_on" else "Habituation OFF",
                "n_seeds": len(vals),
                "pct_change_vs_B1": f"{pct_mean:+.1f}%",
                "ci_95_lo_pct": f"{lo_pct:+.1f}%",
                "ci_95_hi_pct": f"{hi_pct:+.1f}%",
            })
    return table_rows


# ─────────────────────────────────────────────────────────────────────────────
# Figure 2 — Kappa dose-response line chart (B4 vs B1 %, one line per load)
# ─────────────────────────────────────────────────────────────────────────────
def _fig2_kappa_dose_response(outdir: Path) -> None:
    rows = _read_csv(SOURCE_FILES["joint_sweep"])

    mu_vals  = sorted({_safe(r["mu_true"]) for r in rows if _safe(r["mu_true"]) > 0})
    kap_vals = sorted({_safe(r["kappa"])   for r in rows})

    # Build B1 exposure lookup: (mu, kappa, hab) -> mean_value_weighted_exposure
    # B4's pct_delta_mean is 0 in the CSV (B4-only sweep had no B1 reference),
    # so compute it manually from raw exposures.
    b1_exp: dict[tuple, float] = {}
    for r in rows:
        if r.get("system") == "B1_greedy_fixedcue":
            key = (round(_safe(r["mu_true"]), 12), round(_safe(r["kappa"]), 8),
                   r.get("habituation_condition", ""))
            b1_exp[key] = _safe(r["mean_value_weighted_exposure"])

    # line styles and colors per load regime
    mu_styles = {
        2e-5:  {"color": "#228833", "ls": "o-",  "label": MU_LABELS[2e-5].replace("\n", " ")},
        1e-4:  {"color": "#4477AA", "ls": "s--", "label": MU_LABELS[1e-4].replace("\n", " ")},
        4e-4:  {"color": "#CC3300", "ls": "^:",  "label": MU_LABELS[4e-4].replace("\n", " ")},
    }

    _style()
    fig, (ax_on, ax_off) = plt.subplots(2, 1, figsize=(3.5, 4.8), sharey=False)

    for ax, hab, panel_letter in [(ax_on, "hab_on", "a"), (ax_off, "hab_off", "b")]:
        for mu in mu_vals:
            style = mu_styles.get(mu, {})
            pcts, sigs = [], []
            for kap in kap_vals:
                match = [r for r in rows
                         if r.get("system") == "B4_res_stl_full_multicue"
                         and r.get("habituation_condition") == hab
                         and abs(_safe(r["mu_true"]) - mu) < 1e-10
                         and abs(_safe(r["kappa"]) - kap) < 1e-6]
                if match:
                    # pct_delta_mean is 0 in B4 rows; compute from raw exposures
                    b4_exp = _safe(match[0].get("mean_value_weighted_exposure", "nan"))
                    b1_ref = b1_exp.get((round(mu, 12), round(kap, 8), hab), float("nan"))
                    if math.isfinite(b4_exp) and math.isfinite(b1_ref) and b1_ref != 0:
                        pcts.append((b4_exp - b1_ref) / b1_ref * 100.0)
                    else:
                        pcts.append(_safe(match[0].get("pct_delta_mean", "nan")))
                    p = _safe(match[0].get("wilcoxon_p", "nan"))
                    sigs.append(math.isfinite(p) and p < 0.05)
                else:
                    pcts.append(float("nan"))
                    sigs.append(False)

            fmt = style.get("ls", "o-")
            marker = fmt[0]
            ls_str = fmt[1:]
            ax.plot(kap_vals, pcts, ls_str, marker=marker,
                    color=style.get("color", "#888888"),
                    lw=1.5, ms=5, label=style.get("label", str(mu)))

            # Star significant points
            for xi, (kap, pct, sig) in enumerate(zip(kap_vals, pcts, sigs)):
                if sig and math.isfinite(pct):
                    ax.annotate("*", xy=(kap, pct), xytext=(0, 5),
                                textcoords="offset points", ha="center",
                                fontsize=9, color=style.get("color", "#000"))

        ax.axhline(0, color="#888888", lw=1.0, ls=":", label="B1 reference (0%)")
        ax.set_ylabel("Exposure change vs. B1 (%)\n(negative = B4 lower)", fontsize=9)
        hab_label = "Hab. ON" if hab == "hab_on" else "Hab. OFF"
        ax.set_title(f"({panel_letter})  {hab_label}", fontsize=10)
        ax.set_xticks(kap_vals)
        ax.set_xticklabels([f"{k:.2f}" for k in kap_vals], fontsize=8.5)
    ax_off.set_xlabel("Habituation strength κ", fontsize=9)
    fig.suptitle("B4 vs. B1: κ dose-response  (* p<0.05, Wilcoxon, n=10)",
                 fontsize=9)
    fig.tight_layout(pad=0.7)
    handles, labels = ax_on.get_legend_handles_labels()
    fig.legend(handles, labels,
               fontsize=8, framealpha=0.9, edgecolor="#cccccc",
               ncol=2, handlelength=1.8, borderpad=0.5,
               loc="lower center", bbox_to_anchor=(0.5, 0.01))
    fig.subplots_adjust(bottom=0.20)
    _savefig(fig, "fig2_kappa_dose_response", outdir)


# ─────────────────────────────────────────────────────────────────────────────
# Figure 3 — Forest/dot plot: variants on y, two metric panels, CI whiskers
# ─────────────────────────────────────────────────────────────────────────────
def _fig3_tradeoff_scatter(outdir: Path) -> list[dict]:
    """Forest / dot plot: variants on y-axis, two metric panels with 95% CI whiskers.

    Left panel:  exposure change vs B1 (%).  Negative = B4 reduces exposure (better).
    Right panel: reactive miss-rate increase vs B1 (pp).  Positive = more misses (worse).

    Three load regimes encoded by color+shape.  All CI whiskers are horizontal,
    making overlap (or lack thereof) immediately readable.
    """
    rows = _read_csv(SOURCE_FILES["override_sweep"])

    slack_variants   = ["B4_slack_30s", "B4_slack_45s", "B4_slack_60s", "B4_slack_90s"]
    cap_variants     = ["B4_travel_cap_60s", "B4_travel_cap_90s"]
    variants_ordered = slack_variants + cap_variants
    mu_vals  = [4e-4, 1e-4, 2e-5]   # bottom → top so spare is at the top
    mu_short = {2e-5: "spare", 1e-4: "heavy spare", 4e-4: "overloaded"}

    # Colors by load (RdBu: blue=spare, dark blue=heavy spare, red=overloaded)
    mu_colors  = {2e-5: "#4393C3", 1e-4: "#2166AC", 4e-4: "#D6604D"}
    mu_markers = {2e-5: "o",       1e-4: "s",       4e-4: "^"}

    # y layout: one row per variant, 3 dots per row staggered by load
    Y_STEP = 1.5                        # gap between variant center lines
    Y_OFF  = {4e-4: -0.30, 1e-4: 0.0, 2e-5: +0.30}   # within-row offsets

    var_labels = {
        "B4_slack_30s":      "Slack 30 s",
        "B4_slack_45s":      "Slack 45 s  ✦",   # directionally best at heavy spare
        "B4_slack_60s":      "Slack 60 s",
        "B4_slack_90s":      "Slack 90 s",
        "B4_travel_cap_60s": "Cap 60 s",
        "B4_travel_cap_90s": "Cap 90 s",
    }

    table_rows = []

    _style()
    fig, (ax_exp, ax_miss) = plt.subplots(
        2, 1, figsize=(3.5, 5.8),
        gridspec_kw={"hspace": 0.55},
    )

    for vi, var in enumerate(variants_ordered):
        y_base = vi * Y_STEP
        is_cap = var in cap_variants

        for mu in mu_vals:
            mu_rows = {r["variant"]: r for r in rows
                       if abs(_safe(r["mu_true"]) - mu) < 1e-10
                       and r.get("habituation_condition") == "hab_on"}
            b1      = mu_rows.get("B1_greedy_fixedcue", {})
            b1_exp  = _safe(b1.get("mean_exposure",               "nan"))
            b1_frac = _safe(b1.get("mean_reactive_completed_frac", "nan"))
            r = mu_rows.get(var, {})
            if not r:
                continue

            exp_v      = _safe(r.get("mean_exposure",               "nan"))
            exp_ci_lo  = _safe(r.get("exposure_ci_lo",              "nan"))
            exp_ci_hi  = _safe(r.get("exposure_ci_hi",              "nan"))
            frac_v     = _safe(r.get("mean_reactive_completed_frac","nan"))
            frac_ci_lo = _safe(r.get("reactive_frac_ci_lo",         "nan"))
            frac_ci_hi = _safe(r.get("reactive_frac_ci_hi",         "nan"))
            ov         = _safe(r.get("mean_override_count",          "nan"))

            if not (math.isfinite(exp_v) and math.isfinite(frac_v)):
                continue

            pct_d  = (exp_v - b1_exp)  / b1_exp * 100
            miss_d = (b1_frac - frac_v) * 100

            # Approximate 95% CI half-widths (from B4's CI columns)
            exp_lo  = max(0.0, (exp_v - exp_ci_lo)  / b1_exp * 100)
            exp_hi  = max(0.0, (exp_ci_hi - exp_v)  / b1_exp * 100)
            miss_lo = max(0.0, (frac_ci_hi - frac_v) * 100)
            miss_hi = max(0.0, (frac_v - frac_ci_lo) * 100)

            y = y_base + Y_OFF[mu]
            c = mu_colors[mu]
            m = mu_markers[mu]

            kw = dict(fmt=m, color=c, ms=5.5, lw=0,
                      elinewidth=1.1, ecolor=c, capsize=2.5, capthick=1.0,
                      alpha=0.88, zorder=3)
            ax_exp.errorbar( pct_d,  y, xerr=[[exp_lo],  [exp_hi]],  **kw)
            ax_miss.errorbar(miss_d, y, xerr=[[miss_lo], [miss_hi]], **kw)

            table_rows.append({
                "load": mu_short[mu],
                "variant": SLACK_LABELS.get(var, var).replace("\n", " "),
                "type": "travel cap" if is_cap else "override slack",
                "hab_condition": "Habituation ON",
                "exposure_change_pct": f"{pct_d:+.1f}%",
                "miss_rate_cost_pp": f"{miss_d:+.1f} pp",
                "reactive_completed_frac": f"{frac_v:.3f}",
                "mean_override_per_seed": f"{ov:.0f}" if math.isfinite(ov) else "—",
            })

    # Separator between slack and cap groups
    sep_y = len(slack_variants) * Y_STEP - Y_STEP * 0.5
    y_max = (len(variants_ordered) - 1) * Y_STEP + 0.7

    for ax in (ax_exp, ax_miss):
        ax.axhline(sep_y, color="#cccccc", lw=1.0, ls="-", zorder=0)
        ax.axvline(0, color="#444444", lw=0.9, ls="--", zorder=1)
        ax.set_yticks([vi * Y_STEP for vi in range(len(variants_ordered))])
        ax.set_ylim(-0.7, y_max)
        ax.tick_params(labelsize=8.5)
        ax.grid(True, axis="x", alpha=0.25, ls=":")
        ax.grid(False, axis="y")

    for ax in (ax_exp, ax_miss):
        ax.set_yticklabels([var_labels[v] for v in variants_ordered], fontsize=8.5)

    ax_exp.set_xlabel(
        "Exposure change vs. B1 (%)\n(negative = B4 reduces exposure)",
        fontsize=9,
    )
    ax_miss.set_xlabel(
        "Miss-rate increase vs. B1 (pp)\n(positive = B4 misses more tasks)",
        fontsize=9,
    )
    ax_exp.set_title("(a)  Deterrence metric", fontsize=10, pad=4)
    ax_miss.set_title("(b)  Reactive service metric", fontsize=10, pad=4)

    # Legend inside top panel
    legend_handles = [
        plt.Line2D([0],[0], marker="o", color=mu_colors[2e-5], ls="", ms=5.5,
                   label="Spare  (µ=2×10⁻⁵)"),
        plt.Line2D([0],[0], marker="s", color=mu_colors[1e-4], ls="", ms=5.5,
                   label="Heavy spare  (µ=1×10⁻⁴)"),
        plt.Line2D([0],[0], marker="^", color=mu_colors[4e-4], ls="", ms=5.5,
                   label="Overloaded  (µ=4×10⁻⁴)"),
    ]
    fig.suptitle(
        "B4 Override Variants vs. B1\nhab. ON, n=10 seeds, 95% CI  |  ✦ best at heavy spare",
        fontsize=9, y=1.01,
    )
    fig.tight_layout(pad=0.6)
    fig.legend(handles=legend_handles, ncol=1, fontsize=7.5,
               framealpha=0.92, edgecolor="#cccccc",
               loc="lower center", bbox_to_anchor=(0.5, 0.04))
    fig.subplots_adjust(bottom=0.26)
    _savefig(fig, "fig3_tradeoff_scatter", outdir)
    return table_rows


# ─────────────────────────────────────────────────────────────────────────────
# Figure 4 — Override counts by load × variant
# ─────────────────────────────────────────────────────────────────────────────
def _fig4_override_counts(outdir: Path) -> None:
    rows = _read_csv(SOURCE_FILES["override_sweep"])
    mu_vals   = [2e-5, 1e-4, 4e-4]
    variants  = ["B4_slack_30s", "B4_slack_45s", "B4_slack_60s", "B4_slack_90s"]

    _style()
    fig, ax = plt.subplots(figsize=(3.5, 2.9))

    x       = np.arange(len(mu_vals))
    n_var   = len(variants)
    w_total = 0.72
    width   = w_total / n_var
    var_colors = ["#1A6634", "#228833", "#44AA55", "#77CC88"]

    MU_LABELS_SHORT = {2e-5: "Spare\n(2×10⁻⁵)", 1e-4: "Heavy spare\n(1×10⁻⁴)", 4e-4: "Overloaded\n(4×10⁻⁴)"}
    for vi, var in enumerate(variants):
        offsets, means = [], []
        for mu in mu_vals:
            match = [r for r in rows
                     if abs(_safe(r["mu_true"]) - mu) < 1e-10
                     and r["variant"] == var
                     and r.get("habituation_condition") == "hab_on"]
            ov = _safe(match[0]["mean_override_count"]) if match else float("nan")
            offsets.append(x[mu_vals.index(mu)] + (vi - (n_var - 1) / 2) * width)
            means.append(ov)
        lbl = SLACK_LABELS.get(var, var).replace("\n", " ").replace("Slack ", "").replace("(default)", "★")
        ax.bar(offsets, means, width * 0.9, label=lbl, color=var_colors[vi], alpha=0.88)

    ax.set_xticks(x)
    ax.set_xticklabels([MU_LABELS_SHORT.get(m, str(m)) for m in mu_vals], fontsize=8.5, linespacing=1.2)
    ax.set_ylabel("Mean overrides per run", fontsize=9)
    ax.set_title("Override Frequency by Load  |  hab. ON, n=10", fontsize=9, pad=4)
    ax.legend(title="Slack (★=90 s default)", title_fontsize=8, fontsize=8.5, framealpha=0.8,
              loc="upper center", bbox_to_anchor=(0.5, -0.26), ncol=2)
    fig.tight_layout(pad=0.6)
    fig.subplots_adjust(bottom=0.24)
    _savefig(fig, "fig4_override_counts", outdir)


# ─────────────────────────────────────────────────────────────────────────────
# Table builders
# ─────────────────────────────────────────────────────────────────────────────
def _md_table(rows: list[dict], title: str) -> str:
    if not rows:
        return f"# {title}\n\n(no data)\n"
    cols = list(rows[0].keys())
    lines = [f"# {title}", "",
             "| " + " | ".join(cols) + " |",
             "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def _tex_esc(s: str) -> str:
    """Escape special LaTeX characters for table cell content."""
    return (str(s)
            .replace("\\", r"\textbackslash{}")
            .replace("%",  r"\%")
            .replace("&",  r"\&")
            .replace("_",  r"\_")
            .replace("^",  r"\^{}")
            .replace("#",  r"\#")
            .replace("~",  r"\textasciitilde{}"))


def _tex_table(rows: list[dict], caption: str, label: str,
               col_fields: list[str], col_headers: list[str],
               col_align: str) -> str:
    """Return a complete LaTeX table fragment (requires booktabs package)."""
    if not rows:
        return f"% Table '{label}' — no data\n"

    header_line = " & ".join(col_headers) + r" \\"
    data_lines  = "\n".join(
        " & ".join(_tex_esc(r.get(f, "")) for f in col_fields) + r" \\"
        for r in rows
    )
    return "\n".join([
        r"\begin{table}[t]",
        r"\centering",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{col_align}}}",
        r"\toprule",
        header_line,
        r"\midrule",
        data_lines,
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
        "",
    ])


def _write_table(rows: list[dict], stem: str, title: str, outdir: Path,
                 tex_spec: dict | None = None,
                 tex_rows: list[dict] | None = None) -> None:
    td = outdir / "tables"
    td.mkdir(parents=True, exist_ok=True)
    _write_csv(rows, td / f"{stem}.csv")
    (td / f"{stem}.md").write_text(_md_table(rows, title), encoding="utf-8")
    if tex_spec:
        _trows = tex_rows if tex_rows is not None else rows
        tex = _tex_table(_trows, **tex_spec)
        (td / f"{stem}.tex").write_text(tex, encoding="utf-8")
        print(f"  saved {stem}.csv / .md / .tex")
    else:
        print(f"  saved {stem}.csv / .md")


# ─────────────────────────────────────────────────────────────────────────────
# Data collection (copy only)
# ─────────────────────────────────────────────────────────────────────────────
COPY_MAP = {
    "ladder_per_run_metrics.csv":             SOURCE_FILES["ladder"],
    "joint_sweep_summary.csv":                SOURCE_FILES["joint_sweep"],
    "override_sweep_summary.csv":             SOURCE_FILES["override_sweep"],
    "rho_res_sweep_summary.csv":              SOURCE_FILES["rho_res_sweep"],
    "h4_30seed_extended_summary.csv":         SOURCE_FILES["h4_30seed"],
    "ladder_heavy_spare_per_run_metrics.csv": SOURCE_FILES["ladder_1em04"],
    "ladder_overloaded_per_run_metrics.csv":  SOURCE_FILES["ladder_4em04"],
    "h4_rho_res_sweep_summary.csv":           SOURCE_FILES["h4_rho_res_sweep"],
    "topup_b2b3_spare_per_run_metrics.csv":   SOURCE_FILES["topup_2em05"],
    "topup_b2b3_heavy_per_run_metrics.csv":   SOURCE_FILES["topup_1em04"],
    "topup_b2b3_overload_per_run_metrics.csv": SOURCE_FILES["topup_4em04"],
    "preemption_spare_per_run_metrics.csv":   SOURCE_FILES["preemption_2em05"],
    "preemption_heavy_per_run_metrics.csv":   SOURCE_FILES["preemption_1em04"],
    "preemption_overload_per_run_metrics.csv": SOURCE_FILES["preemption_4em04"],
    "2x2_overhead_corrected.csv":             SOURCE_FILES["2x2_overhead"],
}

# ─────────────────────────────────────────────────────────────────────────────
# Figure 5 — Full B1–B5 ladder across three load regimes (hab_on only)
# ─────────────────────────────────────────────────────────────────────────────
def _fig5_full_ladder_by_load(outdir: Path) -> None:
    from collections import defaultdict

    order = [
        "B1_greedy_fixedcue",
        "B2_res_deltaJ_fixedcue",
        "B3_res_stl_nohab_fixedcue",
        "B3_res_stl_nohab_multicue",
        "B4_res_stl_full_multicue",
        "B5_greedy_habcue",
    ]
    # Canonical 5-bar order (B3 variants unified)
    display_order = [
        "B1_greedy_fixedcue",
        "B2_res_deltaJ_fixedcue",
        "B3",
        "B4_res_stl_full_multicue",
        "B5_greedy_habcue",
    ]
    display_labels = [
        "B1",
        "B2",
        "B3",
        "B4★",
        "B5",
    ]

    load_configs = [
        (2e-5,  SOURCE_FILES["ladder"],      "topup_2em05", "spare",       "fixedcue"),
        (1e-4,  SOURCE_FILES["ladder_1em04"], "topup_1em04", "heavy spare", "fixedcue"),
        (4e-4,  SOURCE_FILES["ladder_4em04"], "topup_4em04", "overloaded",  "fixedcue"),
    ]
    topup_baselines = {"B2_res_deltaJ_fixedcue", "B3_res_stl_nohab_fixedcue"}

    # If merged ladder files are in use (acc_merged/), B2/B3-fixedcue are already
    # incorporated with 30 seeds — treat as fully topped up.
    merged_ladder_path = SOURCE_FILES.get("ladder_1em04")
    all_topup_available = (
        merged_ladder_path is not None
        and "acc_merged" in str(merged_ladder_path)
        and merged_ladder_path.exists()
    )

    # ── Collect pct-vs-B1 data for each (system, load) ──────────────────────
    # Result: pct_data[display_key][mu] = (mean_pct, half_ci)
    pct_data: dict[str, dict[float, tuple[float, float]]] = {k: {} for k in display_order}

    for mu, csv_path, topup_key, load_label, b3_variant in load_configs:
        rows = _read_csv(csv_path)
        topup = _read_csv(SOURCE_FILES.get(topup_key, Path("")))
        if topup:
            topup_ids = {(r.get("baseline",""), r.get("habituation_condition",""),
                          str(r.get("seed","")))
                         for r in topup if r.get("baseline","") in topup_baselines}
            rows = [r for r in rows
                    if r.get("baseline","") != "B3_res_stl_nohab_multicue"
                    and (r.get("baseline","") not in topup_baselines
                         or (r.get("baseline",""), r.get("habituation_condition",""),
                             str(r.get("seed",""))) not in topup_ids)]
            rows.extend(topup)

        grouped: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            b = r.get("baseline", "")
            h = r.get("habituation_condition", "")
            v = _safe(r.get("value_weighted_exposure"))
            if b in order and h == "hab_on" and math.isfinite(v):
                key = "B3" if b.startswith("B3_") else b
                grouped[key].append(v)

        b1_vals = grouped.get("B1_greedy_fixedcue", [])
        b1_mean = stats.mean(b1_vals) if b1_vals else float("nan")

        for key in display_order:
            vals = grouped.get(key, [])
            if key == "B1_greedy_fixedcue" or not vals or not math.isfinite(b1_mean):
                pct_data[key][mu] = (0.0, 0.0)
            else:
                pcts = [(v - b1_mean) / b1_mean * 100 for v in vals]
                m = stats.mean(pcts)
                lo, hi = _ci95(pcts)
                half_ci = m - lo if math.isfinite(lo) else 0.0
                pct_data[key][mu] = (m, half_ci)

    # ── Grouped bar chart: x = systems, 3 bars per group (one per load) ─────
    _style()
    fig, ax = plt.subplots(figsize=(3.5, 2.9))

    mu_list   = [2e-5, 1e-4, 4e-4]
    mu_colors_fig5 = {2e-5: "#228833", 1e-4: "#4477AA", 4e-4: "#CC3300"}
    mu_labels_fig5 = {2e-5: "Spare (2×10⁻⁵)", 1e-4: "Heavy spare (1×10⁻⁴)", 4e-4: "Overloaded (4×10⁻⁴)"}
    n_sys  = len(display_order)
    n_load = len(mu_list)
    w      = 0.22          # bar width
    group_gap = 0.78       # center-to-center of system groups
    offsets = np.array([-w, 0, w])   # within each group

    x_centers = np.arange(n_sys) * group_gap

    for li, mu in enumerate(mu_list):
        means = [pct_data[k][mu][0] for k in display_order]
        errs  = [pct_data[k][mu][1] for k in display_order]
        xs    = x_centers + offsets[li]
        ax.bar(xs, means, w * 0.92, yerr=errs, capsize=2.5,
               color=mu_colors_fig5[mu], alpha=0.85,
               label=mu_labels_fig5[mu],
               error_kw={"ecolor": "#333333", "lw": 1.0})

    ax.axhline(0, color="#555555", lw=0.9, zorder=2)

    # Highlight B4 group
    b4_idx = display_order.index("B4_res_stl_full_multicue")
    ax.axvspan(x_centers[b4_idx] - group_gap * 0.48,
               x_centers[b4_idx] + group_gap * 0.48,
               color="#CCFFCC", alpha=0.35, zorder=0)

    ax.set_xticks(x_centers)
    ax.set_xticklabels(display_labels, fontsize=8.5)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    ax.set_ylabel("Exposure change vs. B1 (%)\n(negative = stronger deterrence)", fontsize=9)
    ax.set_title("Ladder across load regimes  |  hab. ON, κ=0.50", fontsize=9, pad=4)
    ax.legend(fontsize=8, framealpha=0.9, edgecolor="#cccccc",
              loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=1)
    ax.grid(True, alpha=0.3, ls="--")
    fig.tight_layout(pad=0.6)
    fig.subplots_adjust(bottom=0.38)
    _note5 = SYS_FOOTNOTE_WRAPPED + "\nn=30 (B4); n=10–30 (others)"
    fig.text(0.5, 0.05, _note5, ha="center", va="top",
             fontsize=7, color="#555555", style="italic")
    _savefig(fig, "fig5_full_ladder_by_load", outdir)


# ─────────────────────────────────────────────────────────────────────────────
# Figure 6 — Override sweep: exposure change and miss-rate gap (2×3 small multiples)
# ─────────────────────────────────────────────────────────────────────────────
def _fig6_override_sweep(outdir: Path) -> None:
    """2-row × 3-column small multiples.

    Row 0: exposure change vs B1 (%) — diverging bar, negative = B4 better.
    Row 1: reactive miss-rate gap vs B1 (pp) — magnitude bar, positive = B4 worse.
    Columns: spare, heavy spare, overloaded.
    Error bars are 95% CI from the summary CSV.
    """
    from matplotlib.patches import Patch
    import matplotlib.lines as mlines

    rows = _read_csv(SOURCE_FILES["override_sweep"])
    mu_vals  = [2e-5, 1e-4, 4e-4]
    variants = [
        "B4_slack_30s", "B4_slack_45s", "B4_slack_60s", "B4_slack_90s",
        "B4_travel_cap_60s", "B4_travel_cap_90s",
    ]

    # ── Build B1 reference dict ──
    b1_ref: dict[float, dict] = {}
    for r in rows:
        if r["variant"] == "B1_greedy_fixedcue" and r["habituation_condition"] == "hab_on":
            mu = _safe(r["mu_true"])
            b1_ref[mu] = {k: _safe(r[k]) for k in (
                "mean_exposure", "exposure_ci_lo", "exposure_ci_hi",
                "mean_reactive_completed_frac",
                "reactive_frac_ci_lo", "reactive_frac_ci_hi",
            )}

    def _pct_vs_b1(var_row: dict, ref: dict) -> tuple[float, float, float]:
        """(point_pct, err_lo, err_hi) for exposure change vs B1."""
        b1e  = ref["mean_exposure"]
        exp  = _safe(var_row.get("mean_exposure",    "nan"))
        elo  = _safe(var_row.get("exposure_ci_lo",   "nan"))
        ehi  = _safe(var_row.get("exposure_ci_hi",   "nan"))
        p    = (exp - b1e) / b1e * 100
        return p, p - (elo - b1e) / b1e * 100, (ehi - b1e) / b1e * 100 - p

    def _miss_gap(var_row: dict, ref: dict) -> tuple[float, float, float]:
        """(point_pp, err_lo, err_hi) for miss-rate gap vs B1 in percentage points."""
        b1m  = (1 - ref["mean_reactive_completed_frac"]) * 100
        frac = _safe(var_row.get("mean_reactive_completed_frac", "nan"))
        flo  = _safe(var_row.get("reactive_frac_ci_lo",          "nan"))
        fhi  = _safe(var_row.get("reactive_frac_ci_hi",          "nan"))
        p    = (1 - frac) * 100 - b1m
        return p, p - ((1 - fhi) * 100 - b1m), (1 - flo) * 100 - b1m - p

    # ── Palette (ColorBrewer RdBu — CVD-validated) ──
    C_SLACK    = "#4393C3"   # blue — all slack variants
    C_SLACK_45 = "#2166AC"   # darker blue — 45 s emphasis
    C_CAP      = "#D6604D"   # warm orange-red — travel cap
    C_REF      = "#777777"   # neutral gray — B1 reference line

    BAR_COLORS = [C_SLACK, C_SLACK_45, C_SLACK, C_SLACK, C_CAP, C_CAP]
    BAR_ALPHAS = [0.80,    0.95,       0.80,    0.80,    0.80,  0.80]
    BW = 0.66

    # x positions: slack group 0-3, cap group 4.6-5.6 (visual gap between types)
    XS = np.array([0.0, 1.0, 2.0, 3.0, 4.6, 5.6])
    X_DIVIDER = 3.85   # dotted separator line x position

    XLIM    = (-0.52, 6.12)
    XTICKS  = ["30 s", "45 s", "60 s", "90 s", "Cap\n60 s", "Cap\n90 s"]
    COL_TITLES = [
        "Spare (µ=2×10⁻⁵)",
        "Heavy spare (µ=1×10⁻⁴)",
        "Overloaded (µ=4×10⁻⁴)",
    ]

    _style()
    fig, axes = plt.subplots(
        2, 3,
        figsize=(7.0, 4.8),
        sharey="row",
        gridspec_kw={"hspace": 0.48, "wspace": 0.06},
    )

    for col, mu in enumerate(mu_vals):
        ref  = b1_ref[mu]
        rmap = {r["variant"]: r for r in rows
                if abs(_safe(r["mu_true"]) - mu) < 1e-10
                and r["habituation_condition"] == "hab_on"}

        ep_pts, ep_lo, ep_hi     = [], [], []
        mg_pts, mg_lo_e, mg_hi_e = [], [], []
        for var in variants:
            rv = rmap.get(var, {})
            p, lo, hi = _pct_vs_b1(rv, ref);  ep_pts.append(p); ep_lo.append(lo); ep_hi.append(hi)
            p, lo, hi = _miss_gap(rv, ref);    mg_pts.append(p); mg_lo_e.append(lo); mg_hi_e.append(hi)

        for row_idx, (pts, lo_e, hi_e) in enumerate(
            [(ep_pts, ep_lo, ep_hi), (mg_pts, mg_lo_e, mg_hi_e)]
        ):
            ax = axes[row_idx, col]

            # Reference line at B1 = 0
            ax.axhline(0, color=C_REF, lw=1.1, ls="--", zorder=0)

            # Dotted visual separator between slack and cap groups
            ax.axvline(X_DIVIDER, color="#cccccc", lw=0.8, ls=":", zorder=0)

            # Bars (drawn individually to allow per-bar alpha)
            for xi, yi, c, a in zip(XS, pts, BAR_COLORS, BAR_ALPHAS):
                ax.bar(xi, yi, BW, color=c, alpha=a, linewidth=0, zorder=2)

            # Error bars (95% CI)
            ax.errorbar(XS, pts,
                        yerr=[lo_e, hi_e],
                        fmt="none",
                        ecolor="#333333", elinewidth=0.9,
                        capsize=2.8, capthick=0.9,
                        zorder=3)

            ax.set_xticks(XS)
            ax.set_xticklabels(XTICKS, fontsize=8.5, linespacing=1.2)
            ax.set_xlim(XLIM)
            ax.tick_params(axis="y", labelsize=8.5)
            ax.tick_params(axis="x", length=0, pad=4)

            # Column title on top row only
            if row_idx == 0:
                ax.set_title(COL_TITLES[col], fontsize=9, pad=5)

            # y-axis label on left column only (sharey hides the rest)
            if col == 0:
                if row_idx == 0:
                    ax.set_ylabel(
                        "Exposure change vs. B1 (%)\nnegative = B4 reduces exposure",
                        fontsize=9, labelpad=4,
                    )
                else:
                    ax.set_ylabel(
                        "Miss-rate gap vs. B1 (pp)\npositive = B4 misses more",
                        fontsize=9, labelpad=4,
                    )

            # B1 ref annotation on right column, middle of line
            if col == 2:
                ax.annotate(
                    "B1", xy=(5.95, 0),
                    xytext=(5.95, 0),
                    fontsize=7.5, color=C_REF,
                    va="bottom", ha="right",
                )

    # ── y-axis formatters (left column only; sharey propagates scale) ──
    axes[0, 0].yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v:+.0f}%")
    )
    axes[1, 0].yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"+{v:.0f}" if v > 0 else "0")
    )

    # ── Legend ──
    legend_handles = [
        Patch(facecolor=C_SLACK,    alpha=0.82, label="Override slack (30/60/90 s)"),
        Patch(facecolor=C_SLACK_45, alpha=0.95, label="Override slack 45 s (✦ best at heavy spare)"),
        Patch(facecolor=C_CAP,      alpha=0.82, label="Travel cap (60/90 s)"),
        mlines.Line2D([], [], color=C_REF, lw=1.0, ls="--", label="B1 greedy baseline"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="lower center", ncol=2,
        fontsize=8.5,
        bbox_to_anchor=(0.5, -0.09),
        framealpha=0.92, edgecolor="#cccccc",
    )

    fig.suptitle(
        "Sensitivity Analysis: Override Slack and Travel Cap vs. B1  |  hab. ON, n=10 seeds, 95% CI",
        fontsize=9, y=1.02,
    )

    _savefig(fig, "fig6_override_sweep", outdir)


# ─────────────────────────────────────────────────────────────────────────────
# Figure 7 — Preemption variant: B4-base vs B4-preempt at 3 loads
# ─────────────────────────────────────────────────────────────────────────────
def _fig7_preemption_comparison(outdir: Path) -> None:
    """2-panel figure: left = exposure change vs B1 (%), right = miss rate.

    Each panel shows B4-base and B4-preempt side-by-side for 3 load levels.
    Data from run_preemption_variant.py outputs.
    Returns without writing if data not yet available.
    """
    mu_keys = [("2em05", 2e-5), ("1em04", 1e-4), ("4em04", 4e-4)]
    # Keep rows keyed by mu so we never need mu_true (absent from preemption CSVs)
    rows_by_mu: dict[float, list[dict]] = {}
    for mu_tok, mu_val in mu_keys:
        key = f"preemption_{mu_tok}"
        path = SOURCE_FILES.get(key)
        rows = _read_csv(path) if path else []
        if rows:
            rows_by_mu[mu_val] = rows

    if not rows_by_mu:
        print("  [fig7] Preemption variant data not yet available — skipping.")
        return

    # Compute n_seeds from the first available mu block
    _first_bl = next(iter(rows_by_mu.values()))
    n_seeds = len([r for r in _first_bl
                   if r.get("baseline") == "B4_res_stl_full_multicue"
                   and r.get("habituation_condition") == "hab_on"])

    mu_vals = [2e-5, 1e-4, 4e-4]
    mu_labels_short = {2e-5: "Spare\n(µ=2×10⁻⁵)", 1e-4: "Heavy spare\n(µ=1×10⁻⁴)", 4e-4: "Overloaded\n(µ=4×10⁻⁴)"}
    variants = ["B1_greedy_fixedcue", "B4_res_stl_full_multicue", "B4_preempt"]
    var_colors = {"B1_greedy_fixedcue": "#777777", "B4_res_stl_full_multicue": "#228833", "B4_preempt": "#4477AA"}
    var_labels = {"B1_greedy_fixedcue": "B1 (reference)", "B4_res_stl_full_multicue": "B4 base", "B4_preempt": "B4 + preemption"}

    _style()
    fig, (ax_exp, ax_miss) = plt.subplots(2, 1, figsize=(3.5, 4.5), sharex=True)

    x = np.arange(len(mu_vals))
    width = 0.26
    offsets = {"B1_greedy_fixedcue": -0.27, "B4_res_stl_full_multicue": 0.0, "B4_preempt": +0.27}

    for vi, var in enumerate(variants):
        if var == "B1_greedy_fixedcue":
            continue  # B1 is reference line, not a bar
        exp_means, miss_means, exp_errs, miss_errs = [], [], [], []
        for mu in mu_vals:
            mu_rows = rows_by_mu.get(mu, [])
            b1_sub = [r for r in mu_rows
                      if r.get("baseline") == "B1_greedy_fixedcue"
                      and r.get("habituation_condition") == "hab_on"]
            var_sub = [r for r in mu_rows
                       if r.get("baseline") == var
                       and r.get("habituation_condition") == "hab_on"]
            if b1_sub and var_sub:
                b1_exp = stats.mean([_safe(r["value_weighted_exposure"]) for r in b1_sub
                                     if math.isfinite(_safe(r["value_weighted_exposure"]))])
                var_exp = stats.mean([_safe(r["value_weighted_exposure"]) for r in var_sub
                                      if math.isfinite(_safe(r["value_weighted_exposure"]))])
                pct = (var_exp - b1_exp) / b1_exp * 100
                exp_means.append(pct)
                exp_errs.append(0)  # simplified; full CI would need seed-level paired deltas

                b1_frac = stats.mean([_safe(r["reactive_completed_fraction"]) for r in b1_sub
                                      if math.isfinite(_safe(r["reactive_completed_fraction"]))])
                var_frac = stats.mean([_safe(r["reactive_completed_fraction"]) for r in var_sub
                                       if math.isfinite(_safe(r["reactive_completed_fraction"]))])
                miss_gap = (1 - var_frac) * 100 - (1 - b1_frac) * 100
                miss_means.append(miss_gap)
                miss_errs.append(0)
            else:
                exp_means.append(float("nan"))
                miss_means.append(float("nan"))
                exp_errs.append(0)
                miss_errs.append(0)

        off = offsets[var]
        c = var_colors[var]
        lbl = var_labels[var]
        ax_exp.bar(x + off, exp_means, width * 0.9, color=c, alpha=0.85, label=lbl)
        ax_miss.bar(x + off, miss_means, width * 0.9, color=c, alpha=0.85, label=lbl)

    for ax in (ax_exp, ax_miss):
        ax.axhline(0, color="#444444", lw=0.9, ls="--", zorder=1)
        ax.set_xticks(x)
        ax.grid(True, axis="y", alpha=0.25, ls=":")
        ax.tick_params(labelsize=8.5)

    ax_miss.set_xticklabels([mu_labels_short[m] for m in mu_vals], fontsize=8.5, linespacing=1.2)
    ax_exp.set_ylabel("Exposure change vs. B1 (%)\n(negative = lower exposure)", fontsize=9)
    ax_miss.set_ylabel("Miss-rate gap vs. B1 (pp)\n(positive = more misses)", fontsize=9)
    ax_exp.set_title("(a)  Deterrence", fontsize=10, pad=4)
    ax_miss.set_title("(b)  Reactive service", fontsize=10, pad=4)
    fig.suptitle(
        f"Preemption Variant: B4-base vs. B4+preempt\nhab. ON, κ=0.50, n={n_seeds} seeds",
        fontsize=9, y=1.01,
    )
    fig.tight_layout(pad=0.7)
    handles, labels = ax_exp.get_legend_handles_labels()
    fig.legend(handles, labels,
               fontsize=8.5, framealpha=0.9, edgecolor="#cccccc",
               ncol=2, loc="lower center", bbox_to_anchor=(0.5, 0.01))
    fig.subplots_adjust(bottom=0.16)
    _savefig(fig, "fig7_preemption_comparison", outdir)


def _table4_2x2_overhead(outdir: Path) -> list[dict]:
    """Cost decomposition: fixed-cue vs. multi-cue overhead across hab conditions.

    5 systems × 2 hab conditions; reports mean exposure pct vs B1 with 95% CI.
    """
    from collections import defaultdict
    csv_path = SOURCE_FILES.get("2x2_overhead")
    rows = _read_csv(csv_path)
    if not rows:
        print("  [table4] 2×2 overhead data not available — skipping.")
        return []

    DISPLAY = {
        "B1_greedy_fixedcue":        "B1 (reference)",
        "B3_res_stl_nohab_fixedcue": "B3 fixed-cue",
        "B3_res_stl_nohab_multicue": "B3 multi-cue",
        "B4_res_stl_full_fixedcue":  "B4 fixed-cue",
        "B4_res_stl_full_multicue":  "B4★ multi-cue",
    }
    sys_order = list(DISPLAY.keys())

    grouped: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        b = r.get("baseline", "")
        h = r.get("habituation_condition", "")
        v = _safe(r.get("value_weighted_exposure", "nan"))
        if b in DISPLAY and math.isfinite(v):
            grouped[(b, h)].append(v)

    b1_on  = stats.mean(grouped.get(("B1_greedy_fixedcue", "hab_on"),  [float("nan")]))
    b1_off = stats.mean(grouped.get(("B1_greedy_fixedcue", "hab_off"), [float("nan")]))

    out = []
    for baseline in sys_order:
        for hab, b1_mean in [("hab_on", b1_on), ("hab_off", b1_off)]:
            vals = grouped.get((baseline, hab), [])
            n = len(vals)
            if not vals or not math.isfinite(b1_mean):
                continue
            if baseline == "B1_greedy_fixedcue":
                pcts = [0.0] * n
            else:
                pcts = [(v - b1_mean) / b1_mean * 100 for v in vals]
            m = stats.mean(pcts)
            lo, hi = _ci95(pcts) if n > 1 else (float("nan"), float("nan"))
            out.append({
                "system":        DISPLAY[baseline],
                "hab_condition": "Hab. ON" if hab == "hab_on" else "Hab. OFF",
                "n_seeds":       n,
                "pct_vs_B1":     f"{m:+.1f}%",
                "ci_95":         (f"[{lo:+.1f}%, {hi:+.1f}%]"
                                  if math.isfinite(lo) else "—"),
            })
    return out


def _collect_data(outdir: Path) -> None:
    data_dir = outdir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for dest_name, src_path in COPY_MAP.items():
        if src_path is None:
            continue
        if src_path.exists():
            shutil.copy2(src_path, data_dir / dest_name)
            print(f"  copied  {src_path.name}  →  data/{dest_name}")
        else:
            print(f"  MISSING {src_path}  (skipped)")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate ACC submission figures and data package.")
    p.add_argument("--outdir", default="results/acc_submission",
                   help="Root output directory (default: results/acc_submission)")
    return p.parse_args(argv)


# ─────────────────────────────────────────────────────────────────────────────
# Table 3 — Paired B4–B5 comparison across three load regimes
# ─────────────────────────────────────────────────────────────────────────────
def _table3_b4_b5_comparison(outdir: Path) -> list[dict]:
    """Paired B4--B5 exposure difference at κ=0.50, hab_on, across three loads.

    Matches tab:h5-load in 07_results.tex. Uses bootstrap CI and Wilcoxon
    signed-rank from the production ladder module.
    """
    import experiments.run_habituation_stl_production_ladder as ladder

    B4  = "B4_res_stl_full_multicue"
    B5  = "B5_greedy_habcue"
    B1  = "B1_greedy_fixedcue"
    HAB = "hab_on"

    configs = [
        ("Spare (µ=2×10⁻⁵)",       SOURCE_FILES["ladder"],       2e-5),
        ("Heavy spare (µ=1×10⁻⁴)", SOURCE_FILES["ladder_1em04"], 1e-4),
        ("Overloaded (µ=4×10⁻⁴)",  SOURCE_FILES["ladder_4em04"], 4e-4),
    ]

    out = []
    for label, csv_path, _mu in configs:
        rows = _read_csv(csv_path)
        if not rows:
            print(f"  [table3] {label}: data not available — skipping row.")
            continue

        deltas = ladder._paired_deltas(rows, B4, B5, HAB, "value_weighted_exposure")
        if not deltas:
            print(f"  [table3] {label}: no paired B4/B5 seeds found — skipping row.")
            continue

        mean_d   = stats.mean(deltas)
        ci_lo, ci_hi = ladder._bootstrap_ci95(deltas)
        _, p_val, _  = ladder._wilcoxon_signed_rank(deltas)
        n        = len(deltas)
        n_better = sum(1 for d in deltas if d < 0)

        b1_exp = [_safe(r.get("value_weighted_exposure"))
                  for r in rows
                  if r.get("baseline") == B1 and r.get("habituation_condition") == HAB]
        b1_exp = [v for v in b1_exp if math.isfinite(v)]
        b1_mean = stats.mean(b1_exp) if b1_exp else float("nan")
        pct_b1  = mean_d / b1_mean * 100 if math.isfinite(b1_mean) and b1_mean != 0 else float("nan")

        sig = "**" if p_val < 0.01 else ("*" if p_val < 0.05 else "n.s.")

        out.append({
            "Load":          label,
            "n":             n,
            "delta_B4_B5":   f"{mean_d:+,.0f}",
            "pct_B1":        f"{pct_b1:+.1f}%",
            "CI_95":         f"[{ci_lo:+,.0f}, {ci_hi:+,.0f}]",
            "p":             f"{p_val:.4f}",
            "sig":           sig,
            "seeds_B4_lt_B5": f"{n_better}/{n}",
        })

    return out


def main(argv=None) -> None:
    args  = parse_args(argv)
    outdir = (REPO_ROOT / args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"\n[acc] Output root: {outdir}\n")

    print("[acc] Generating Figure 1 — Baseline ladder …")
    ladder_table = _fig1_ladder(outdir)

    print("[acc] Generating Figure 2 — Kappa dose-response …")
    _fig2_kappa_dose_response(outdir)

    print("[acc] Generating Figure 3 — Trade-off scatter …")
    slack_table = _fig3_tradeoff_scatter(outdir)

    print("[acc] Generating Figure 4 — Override counts …")
    _fig4_override_counts(outdir)

    print("[acc] Generating Figure 5 — Full ladder by load …")
    _fig5_full_ladder_by_load(outdir)

    print("[acc] Generating Figure 6 — Override sweep …")
    _fig6_override_sweep(outdir)

    print("[acc] Generating Figure 7 — Preemption variant …")
    _fig7_preemption_comparison(outdir)

    print("\n[acc] Writing tables …")
    merged_ladder = SOURCE_FILES.get("ladder")
    topup_avail = (
        merged_ladder is not None
        and merged_ladder.exists()
        and "acc_merged" in str(merged_ladder)
    )
    t1_title = ("Table 1 — Baseline Ladder Summary (B1–B5, µ=2×10⁻⁵, κ=0.50, n=30 seeds all)"
                if topup_avail else
                "Table 1 — Baseline Ladder Summary (B1–B5, µ=2×10⁻⁵, κ=0.50, n=30 B1/B4/B5; n=10 B2/B3)")
    t1_tex_rows = [{**r, "ci_95": f"[{r['ci_95_lo_pct']}, {r['ci_95_hi_pct']}]"}
                   for r in ladder_table]
    t1_tex_spec = {
        "caption": (
            r"Baseline ladder: mean value-weighted exposure relative to B1 (\%), "
            r"$\mu = 2 \times 10^{-5}$, $\kappa = 0.50$, $T = 1800\,\mathrm{s}$. "
            r"Negative $=$ lower exposure than B1 (stronger deterrence). "
            r"Bootstrap 95\,\% CI."
        ),
        "label": "tab:acc-ladder-summary",
        "col_fields": ["system", "hab_condition", "n_seeds", "pct_change_vs_B1", "ci_95"],
        "col_headers": [r"System", r"Hab.\ condition", r"$n$",
                        r"$\Delta$ vs B1 (\%)", r"95\,\% CI"],
        "col_align": r"l l r r l",
    }
    _write_table(ladder_table, "table1_ladder_summary", t1_title, outdir,
                 tex_spec=t1_tex_spec, tex_rows=t1_tex_rows)

    t2_tex_spec = {
        "caption": (
            r"Override slack and travel cap sensitivity analysis: "
            r"B4 performance relative to B1 across all three load regimes, hab.\ ON\@. "
            r"Negative exposure $\Delta$ $=$ stronger deterrence; "
            r"miss-rate $\Delta$ in percentage points relative to the 90\,s default."
        ),
        "label": "tab:acc-override-sweep",
        "col_fields": ["load", "variant", "type", "exposure_change_pct",
                       "miss_rate_cost_pp", "reactive_completed_frac"],
        "col_headers": [r"Load", r"Variant", r"Type", r"Exposure $\Delta$",
                        r"Miss-rate $\Delta$ (pp)", r"React.\ compl.\ frac."],
        "col_align": r"l l l r r r",
    }
    _write_table(slack_table,
                 "table2_override_sweep_summary",
                 "Table 2 — Override Slack / Travel Cap Trade-off (all three load regimes, hab. ON)",
                 outdir, tex_spec=t2_tex_spec)

    print("[acc] Generating Table 3 — B4 vs B5 paired comparison …")
    b4_b5_table = _table3_b4_b5_comparison(outdir)
    if b4_b5_table:
        t3_tex_spec = {
            "caption": (
                r"Paired B4--B5 value-weighted exposure difference across three load regimes, "
                r"$\kappa = 0.50$, hab.\ ON\@. "
                r"Negative $\Delta$ $=$ B4 produces lower exposure than B5. "
                r"Bootstrap 95\,\% CI; Wilcoxon signed-rank $p$-value. "
                r"${\ast\ast}$: $p < 0.01$; ${\ast}$: $p < 0.05$; n.s.: $p \geq 0.05$."
            ),
            "label": "tab:acc-b4-b5-comparison",
            "col_fields": ["Load", "n", "delta_B4_B5", "pct_B1", "CI_95",
                           "p", "sig", "seeds_B4_lt_B5"],
            "col_headers": [r"Load", r"$n$", r"$\Delta$ (B4$-$B5)", r"\% of B1",
                            r"95\,\% CI", r"$p$", r"Sig.", r"B4$<$B5"],
            "col_align": r"l r r r l r c c",
        }
        _write_table(b4_b5_table,
                     "table3_b4_vs_b5_load_comparison",
                     "Table 3 — Paired B4–B5 Exposure Difference Across Load Regimes "
                     "(κ=0.50, hab. ON; negative = B4 better; bootstrap 95% CI, Wilcoxon signed-rank)",
                     outdir, tex_spec=t3_tex_spec)

    print("[acc] Generating Table 4 — 2×2 cost decomposition …")
    overhead_table = _table4_2x2_overhead(outdir)
    if overhead_table:
        t4_tex_spec = {
            "caption": (
                r"Cost decomposition: fixed-cue vs.\ multi-cue overhead under hab.\ ON and hab.\ OFF, "
                r"$\mu = 2 \times 10^{-5}$, $\kappa = 0.50$. "
                r"Values are mean value-weighted exposure relative to B1 (\%). "
                r"Negative $=$ lower exposure than B1 (stronger deterrence). "
                r"Bootstrap 95\,\% CI."
            ),
            "label": "tab:acc-2x2-overhead",
            "col_fields": ["system", "hab_condition", "n_seeds", "pct_vs_B1", "ci_95"],
            "col_headers": [r"System", r"Hab.\ condition", r"$n$",
                            r"$\Delta$ vs B1 (\%)", r"95\,\% CI"],
            "col_align": r"l l r r l",
        }
        _write_table(overhead_table,
                     "table4_2x2_overhead_decomposition",
                     "Table 4 — 2×2 Cost Decomposition: Fixed-cue vs. Multi-cue "
                     "(µ=2×10⁻⁵, κ=0.50; % vs B1; bootstrap 95% CI)",
                     outdir, tex_spec=t4_tex_spec)

    print("\n[acc] Collecting source data …")
    _collect_data(outdir)

    print(f"\n[acc] Done.  Package at: {outdir}")
    print("  figures/   — 7 PDF + SVG + EPS figures")
    print("  tables/    — 4 CSV + Markdown + LaTeX tables")
    print("  data/      — source CSVs (copies only, originals untouched)")


if __name__ == "__main__":
    main()
