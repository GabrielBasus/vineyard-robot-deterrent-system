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
    "ladder": RESULTS / "habituation_stl_revised_confirm_with_b2_1800s_10seed" / "per_run_metrics.csv",
    "joint_sweep": RESULTS / "habituation_stl_joint_sweep" / "joint_sweep_summary.csv",
    "override_sweep": RESULTS / "habituation_stl_override_sweep" / "override_sweep_summary.csv",
    "rho_res_sweep": RESULTS / "habituation_stl_rho_res_sweep" / "rho_res_sweep_summary.csv",
    "h4_30seed": RESULTS / "h4_tost_extended_mu1em04_kappa0p50" / "h4_tost_30seed_summary.csv",
    "h4_rho_res_sweep": RESULTS / "h4_rho_res_sweep_mu1em04" / "h4_rho_res_sweep_summary.csv",
    "ladder_1em04": RESULTS / "habituation_stl_load_sweep_highload" / "mu_1em04" / "per_run_metrics.csv",
    "ladder_4em04": RESULTS / "habituation_stl_load_sweep_highload" / "mu_4em04" / "per_run_metrics.csv",
}

# ── Label maps ────────────────────────────────────────────────────────────────
SYSTEM_LABELS: dict[str, str] = {
    "B1_greedy_fixedcue":        "B1: Greedy\n(reference)",
    "B2_res_deltaJ_fixedcue":    "B2: Res. + ΔJ",
    "B3_res_stl_nohab_fixedcue": "B3: Res. + STL\n(no habituation)",
    "B3_res_stl_nohab_multicue": "B3: Res. + STL\n(no habituation)",
    "B4_res_stl_full_multicue":  "B4: STL + Hab.\n(proposed)",
    "B5_greedy_habcue":          "B5: Greedy\n+ Hab. Cues",
}

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
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "figure.dpi": 150,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.35,
        "grid.linestyle": "--",
    })

def _savefig(fig: plt.Figure, stem: str, outdir: Path) -> None:
    fig_dir = outdir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_dir / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(fig_dir / f"{stem}.svg", bbox_inches="tight")
    print(f"  saved {stem}.pdf / .svg")
    plt.close(fig)

# ─────────────────────────────────────────────────────────────────────────────
# Figure 1 — Baseline ladder bar chart (B1–B5, confirmatory point)
# ─────────────────────────────────────────────────────────────────────────────
def _fig1_ladder(outdir: Path) -> list[dict]:
    rows = _read_csv(SOURCE_FILES["ladder"])
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
    fig, ax = plt.subplots(figsize=(7.5, 4.2))

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

    bar_on  = ax.bar(x - width/2, means_on,  width, yerr=errs_on,  capsize=4,
                     color=COLORS["hab_on"],  alpha=0.85, label="Habituation ON",
                     error_kw={"ecolor": "#114422", "lw": 1.5})
    bar_off = ax.bar(x + width/2, means_off, width, yerr=errs_off, capsize=4,
                     color=COLORS["hab_off"], alpha=0.85, label="Habituation OFF",
                     error_kw={"ecolor": "#223355", "lw": 1.5})

    # Highlight B4
    ax.axvspan(x[order.index("B4_res_stl_full_multicue")] - 0.45,
               x[order.index("B4_res_stl_full_multicue")] + 0.45,
               color="#CCFFCC", alpha=0.4, zorder=0)

    ax.set_xticks(x)
    ax.set_xticklabels([SYSTEM_LABELS.get(s, s) for s in order], fontsize=8.5)
    ax.set_ylabel("Mean value-weighted cumulative exposure\n(lower = stronger deterrence)", fontsize=9)
    ax.set_title("Baseline Ladder: Policies B1–B5\n"
                 "µ = 2×10⁻⁵,  κ = 0.50,  T = 1800 s\n"
                 "n = 30 seeds (B1, B4, B5);  n = 10 seeds (B2, B3)",
                 pad=8)
    ax.legend(framealpha=0.8, loc="upper left")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v/1e3:.0f}k"))
    fig.tight_layout()
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

    # line styles and colors per load regime
    mu_styles = {
        2e-5:  {"color": "#228833", "ls": "o-",  "label": MU_LABELS[2e-5].replace("\n", " ")},
        1e-4:  {"color": "#4477AA", "ls": "s--", "label": MU_LABELS[1e-4].replace("\n", " ")},
        4e-4:  {"color": "#CC3300", "ls": "^:",  "label": MU_LABELS[4e-4].replace("\n", " ")},
    }

    _style()
    fig, (ax_on, ax_off) = plt.subplots(1, 2, figsize=(9.5, 4.0), sharey=False)

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
                    lw=2.0, ms=7, label=style.get("label", str(mu)))

            # Star significant points
            for xi, (kap, pct, sig) in enumerate(zip(kap_vals, pcts, sigs)):
                if sig and math.isfinite(pct):
                    ax.annotate("*", xy=(kap, pct), xytext=(0, 6),
                                textcoords="offset points", ha="center",
                                fontsize=11, color=style.get("color", "#000"))

        ax.axhline(0, color="#888888", lw=1.0, ls=":", label="B1 reference (0%)")
        ax.set_xlabel("Habituation strength  κ  (decrement per cue application)", fontsize=9)
        ax.set_ylabel("Exposure change relative to B1 (%)\n(negative = B4 achieves lower exposure)", fontsize=9)
        hab_label = "Habituation ON" if hab == "hab_on" else "Habituation OFF"
        ax.set_title(f"({panel_letter})  {hab_label}", fontsize=10)
        ax.set_xticks(kap_vals)
        ax.set_xticklabels([f"{k:.2f}" for k in kap_vals], fontsize=8.5)
        ax.legend(fontsize=8, framealpha=0.8, loc="lower left")

    fig.suptitle("B4 vs. B1: Exposure change (%) as a function of habituation strength κ\n"
                 "* p < 0.05, Wilcoxon signed-rank test  |  10 seeds per cell",
                 y=1.03, fontsize=10)
    fig.tight_layout()
    _savefig(fig, "fig2_kappa_dose_response", outdir)


# ─────────────────────────────────────────────────────────────────────────────
# Figure 3 — Trade-off scatter: exposure reduction vs miss-rate cost
# Each point is one (variant, load) cell; color = load regime, shape = variant type.
# ─────────────────────────────────────────────────────────────────────────────
def _fig3_tradeoff_scatter(outdir: Path) -> list[dict]:
    rows = _read_csv(SOURCE_FILES["override_sweep"])

    slack_variants = ["B4_slack_30s", "B4_slack_45s", "B4_slack_60s", "B4_slack_90s"]
    cap_variants   = ["B4_travel_cap_60s", "B4_travel_cap_90s"]
    mu_vals = [2e-5, 1e-4, 4e-4]

    mu_colors = {2e-5: "#228833", 1e-4: "#4477AA", 4e-4: "#CC3300"}
    mu_short  = {2e-5: "spare", 1e-4: "heavy spare", 4e-4: "overloaded"}

    _style()
    fig, ax = plt.subplots(figsize=(7.5, 5.0))

    table_rows = []

    for mu in mu_vals:
        mu_rows = {r["variant"]: r for r in rows
                   if abs(_safe(r["mu_true"]) - mu) < 1e-10
                   and r.get("habituation_condition") == "hab_on"}
        b1 = mu_rows.get("B1_greedy_fixedcue", {})
        b1_exp  = _safe(b1.get("mean_exposure", "nan"))
        b1_frac = _safe(b1.get("mean_reactive_completed_frac", "nan"))

        for vi, var in enumerate(slack_variants + cap_variants):
            r = mu_rows.get(var, {})
            if not r:
                continue
            exp_v  = _safe(r.get("mean_exposure", "nan"))
            frac_v = _safe(r.get("mean_reactive_completed_frac", "nan"))
            ov     = _safe(r.get("mean_override_count", "nan"))
            if not (math.isfinite(exp_v) and math.isfinite(frac_v)):
                continue
            pct_d  = (b1_exp - exp_v) / b1_exp * 100   # positive = better (lower exposure)
            miss_d = (b1_frac - frac_v) * 100           # positive = worse  (more misses)

            is_cap = var in cap_variants
            marker = "D" if is_cap else "o"
            color  = mu_colors[mu]
            ax.scatter(miss_d, pct_d, s=80, c=color, marker=marker,
                       edgecolors="white", linewidths=0.6, zorder=3,
                       alpha=0.92)

            # Annotate with slack value; offset direction avoids overlap with marker
            short = SLACK_LABELS_SHORT.get(var, var)
            dx = 5 if miss_d >= 0 else -5
            dy = 5 if pct_d >= 0 else -8
            ha = "left" if dx > 0 else "right"
            ax.annotate(short, xy=(miss_d, pct_d),
                        xytext=(dx, dy), textcoords="offset points",
                        fontsize=7.5, color="#444444", ha=ha,
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7))

            table_rows.append({
                "load": mu_short[mu],
                "variant": SLACK_LABELS.get(var, var).replace("\n", " "),
                "type": "travel cap" if is_cap else "override slack",
                "hab_condition": "Habituation ON",
                "exposure_reduction_pct": f"{pct_d:+.1f}%",
                "miss_rate_cost_pp": f"{miss_d:+.1f} pp",
                "reactive_completed_frac": f"{frac_v:.3f}",
                "mean_override_per_seed": f"{ov:.0f}" if math.isfinite(ov) else "—",
            })

    # Reference lines
    ax.axhline(0, color="#888888", lw=0.9, ls=":")
    ax.axvline(0, color="#888888", lw=0.9, ls=":")

    # Quadrant annotations — all in muted grey so they don't compete with data colors
    _qa = dict(transform=ax.transAxes, fontsize=8, color="#999999", style="italic")
    ax.text(0.98, 0.98, "exposure ↑, misses ↑\n(worse on both)", ha="right", va="top", **_qa)
    ax.text(0.02, 0.98, "exposure ↓, misses stable\n(Pareto-improving)", ha="left", va="top", **_qa)
    ax.text(0.98, 0.02, "exposure stable, misses ↑\n(reactive cost only)", ha="right", va="bottom", **_qa)
    ax.text(0.02, 0.02, "exposure ↓, misses ↓\n(dominant)", ha="left", va="bottom", **_qa)

    ax.set_xlabel("Reactive task miss-rate increase vs. B1 (percentage points)", fontsize=9)
    ax.set_ylabel("Deterrent exposure reduction vs. B1 (%)", fontsize=9)

    # Legend: load regime (color) + variant type (shape) — upper right avoids data cluster
    legend_handles = [
        mpatches.Patch(color=mu_colors[2e-5], label="Spare  (µ = 2×10⁻⁵)"),
        mpatches.Patch(color=mu_colors[1e-4], label="Heavy spare  (µ = 1×10⁻⁴)"),
        mpatches.Patch(color=mu_colors[4e-4], label="Overloaded  (µ = 4×10⁻⁴)"),
        plt.Line2D([0],[0], marker="o", color="#555555", ls="", ms=8, label="Override slack variant"),
        plt.Line2D([0],[0], marker="D", color="#555555", ls="", ms=8, label="Travel cap variant"),
    ]
    ax.legend(handles=legend_handles, fontsize=8, framealpha=0.85,
              loc="upper right")

    ax.set_title("Exposure Reduction vs. Reactive Miss-Rate Cost\n"
                 "B4 variants vs. B1 reference  |  hab. ON  |  10 seeds per cell", pad=8)
    fig.tight_layout()
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
    fig, ax = plt.subplots(figsize=(7, 4))

    x       = np.arange(len(mu_vals))
    n_var   = len(variants)
    w_total = 0.72
    width   = w_total / n_var
    var_colors = ["#1A6634", "#228833", "#44AA55", "#77CC88"]

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
        ax.bar(offsets, means, width * 0.9, label=SLACK_LABELS.get(var, var).replace("\n", " "),
               color=var_colors[vi], alpha=0.88)

    ax.set_xticks(x)
    ax.set_xticklabels([MU_LABELS.get(m, str(m)) for m in mu_vals], fontsize=9)
    ax.set_ylabel("Mean urgent reactive overrides per run\n(robot re-routed to reactive task)", fontsize=9)
    ax.set_title("Measured Reactive Override Frequency by Load and Override Slack\n"
                 "hab. ON  |  mean over 10 seeds", pad=8)
    ax.legend(title="Override slack threshold", framealpha=0.8)
    fig.tight_layout()
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


def _write_table(rows: list[dict], stem: str, title: str, outdir: Path) -> None:
    td = outdir / "tables"
    td.mkdir(parents=True, exist_ok=True)
    _write_csv(rows, td / f"{stem}.csv")
    (td / f"{stem}.md").write_text(_md_table(rows, title), encoding="utf-8")
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
    # B3 note: fixedcue at µ=2e-5 (confirmatory), multicue at higher loads.
    # Without habituation, cue rotation provides little benefit, so the variants
    # are functionally comparable, but the dagger marks the difference.
    display_labels = [
        "B1: Greedy",
        "B2: Res. + ΔJ",
        "B3: STL\n(no hab.)†",
        "B4: STL+Hab.\n(proposed)",
        "B5: Greedy\n+Hab. Cues",
    ]

    load_configs = [
        (2e-5,  SOURCE_FILES["ladder"],      "spare",       "fixedcue"),
        (1e-4,  SOURCE_FILES["ladder_1em04"], "heavy spare", "multicue"),
        (4e-4,  SOURCE_FILES["ladder_4em04"], "overloaded",  "multicue"),
    ]

    _style()
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.5), sharey=False)

    for ax_idx, (mu, csv_path, load_label, b3_variant) in enumerate(load_configs):
        ax = axes[ax_idx]
        rows = _read_csv(csv_path)
        grouped: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            b = r.get("baseline", "")
            h = r.get("habituation_condition", "")
            v = _safe(r.get("value_weighted_exposure"))
            if b in order and h == "hab_on" and math.isfinite(v):
                # Merge B3 variants
                key = "B3" if b.startswith("B3_") else b
                grouped[key].append(v)

        b1_vals = grouped.get("B1_greedy_fixedcue", [])
        b1_mean = stats.mean(b1_vals) if b1_vals else float("nan")

        pct_means, pct_errs, colors = [], [], []
        for key in display_order:
            vals = grouped.get(key, [])
            if key == "B1_greedy_fixedcue" or not vals or not math.isfinite(b1_mean):
                pct_means.append(0.0)
                pct_errs.append(0.0)
            else:
                pcts = [(v - b1_mean) / b1_mean * 100 for v in vals]
                m = stats.mean(pcts)
                lo, hi = _ci95(pcts)
                pct_means.append(m)
                pct_errs.append(m - lo if math.isfinite(lo) else 0.0)
            colors.append(COLORS["B4"] if key == "B4_res_stl_full_multicue" else COLORS["hab_on"])

        x = np.arange(len(display_order))
        ax.bar(x, pct_means, width=0.6, yerr=pct_errs, capsize=4,
               color=colors, alpha=0.85,
               error_kw={"ecolor": "#114422", "lw": 1.5})

        ax.axhline(0, color="#555555", lw=1.0, zorder=2)

        # Highlight B4 bar
        b4_idx = display_order.index("B4_res_stl_full_multicue")
        ax.axvspan(b4_idx - 0.38, b4_idx + 0.38, color="#CCFFCC", alpha=0.4, zorder=0)

        # Mark B1 bar as reference
        ax.text(x[0], 1.5, "ref.", ha="center", va="bottom", fontsize=7.5,
                color="#555555", style="italic")

        ax.set_xticks(x)
        ax.set_xticklabels(display_labels, fontsize=8)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
        panel_title = MU_LABELS.get(mu, f"µ = {mu:.1e}") + f"\n[B3: {b3_variant}]"
        ax.set_title(panel_title, fontsize=9)
        if ax_idx == 0:
            ax.set_ylabel("Exposure change vs. B1 reference (%)\n(negative = lower exposure, stronger deterrence)",
                          fontsize=9)
        ax.grid(True, alpha=0.3, ls="--")

    # Shared legend
    legend_handles = [
        mpatches.Patch(color=COLORS["hab_on"], label="B1–B3, B5  (comparison baselines)"),
        mpatches.Patch(color=COLORS["B4"],     label="B4: STL + Habituation  (proposed)"),
    ]
    fig.legend(handles=legend_handles, loc="upper center", ncol=2, fontsize=9,
               bbox_to_anchor=(0.5, 1.02), framealpha=0.85)
    fig.suptitle("Full Ladder Comparison Across Load Regimes  |  hab. ON,  κ = 0.50,  n = 10 seeds each",
                 y=1.08, fontsize=10)
    fig.text(0.5, -0.02,
             "† B3 cue strategy: fixedcue at µ=2×10⁻⁵ (confirmatory dataset); "
             "multicue at µ=1×10⁻⁴ and µ=4×10⁻⁴ (load-sweep dataset).\n"
             "Without habituation, cue rotation provides negligible benefit; "
             "values are comparable across panels.",
             ha="center", va="top", fontsize=7.5, color="#555555", style="italic",
             wrap=True)
    fig.tight_layout()
    _savefig(fig, "fig5_full_ladder_by_load", outdir)


def _collect_data(outdir: Path) -> None:
    data_dir = outdir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for dest_name, src_path in COPY_MAP.items():
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

    print("\n[acc] Writing tables …")
    _write_table(ladder_table,
                 "table1_ladder_summary",
                 "Table 1 — Baseline Ladder Summary (B1–B5, µ=2×10⁻⁵, κ=0.50, 10 seeds)",
                 outdir)
    _write_table(slack_table,
                 "table2_override_sweep_summary",
                 "Table 2 — Override Slack / Travel Cap Trade-off (µ=1×10⁻⁴, hab. ON)",
                 outdir)

    print("\n[acc] Collecting source data …")
    _collect_data(outdir)

    print(f"\n[acc] Done.  Package at: {outdir}")
    print("  figures/   — 5 PDF + SVG figures")
    print("  tables/    — 2 CSV + Markdown tables")
    print("  data/      — source CSVs (copies only, originals untouched)")


if __name__ == "__main__":
    main()
