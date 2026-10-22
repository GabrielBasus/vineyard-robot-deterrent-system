"""
analyze_plan_confirmatory.py -- confirmatory analysis for the improvement plan (Plan Sec. 6).

Declared before the evaluation runs (family 2026-10-14; noninferiority test revised by
user decision 24, 2026-10-21; reference B5_c in PLAN_ENV, decision 2):

Confirmatory family (six hypotheses, Holm step-down together, familywise alpha 0.05).
For each load in {spare 2e-5, heavy 1e-4, overload 4e-4}, habituation on, E_plan vs B5_c:
  H1(load) exposure: two-sided Wilcoxon signed-rank on paired value_weighted_exposure.
  H2(load) service noninferiority: H0: mean paired (E_plan - B5_c) reactive_miss_fraction
           >= +0.02 (2 pp, predeclared 2026-10-13).  Decision 24: reject H0 iff the paired
           percentile-bootstrap UPPER bound on the MEAN difference, at the Holm-adjusted
           one-sided level of that hypothesis, lies below +0.02.

Holm with a bootstrap test.  Each H2 also gets a one-sided bootstrap p-value
  p_boot = (1 + #{bootstrap means >= 0.02}) / (B + 1),
used only to ORDER the six hypotheses in Holm's step-down procedure.  At step k
(k = 0..5, ascending p) the hypothesis is tested at level alpha / (6 - k): H1 rejects iff
p_Wilcoxon <= alpha / (6 - k); H2 rejects iff the bootstrap upper bound at quantile
1 - alpha / (6 - k) is below the margin.  The procedure stops at the first non-rejection;
every later hypothesis is retained.  The reported bound of each H2 is the one at its own
Holm level (for retained hypotheses after the stop: at the level of its position).
Supplementary (not part of the decision): one-sided Wilcoxon on (diff - 0.02).

Everything else (other variants, habituation off, mechanism metrics) is exploratory.

Percent effect = mean paired difference / mean of the reference (B5_c) x 100.
Pairs: a seed is used only when both systems have a finite value; missing seeds are
listed and comparisons with fewer than the expected pairs are flagged.

Usage:
  py -3.10 -m experiments.analyze_plan_confirmatory \
      --dirs spare=results/plan_studies/confirmatory/spare heavy=... overload=...
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

NI_MARGIN = 0.02
ALPHA = 0.05
N_BOOT = 10000
BOOT_SEED = 12345


def load_rows(d: Path) -> list[dict]:
    raw = Path(d) / "raw"
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(raw.glob("*.json"))]


def paired(rows, ref, trt, metric, hab="hab_on"):
    def by_seed(v):
        out = {}
        for r in rows:
            if r.get("variant") == v and r.get("habituation_condition") == hab:
                try:
                    x = float(r.get(metric))
                except (TypeError, ValueError):
                    x = float("nan")
                out[int(r["seed"])] = x
        return out

    a, b = by_seed(ref), by_seed(trt)
    seeds = sorted(set(a) | set(b))
    used = [s for s in seeds if s in a and s in b and math.isfinite(a[s]) and math.isfinite(b[s])]
    missing = [s for s in seeds if s not in used]
    return np.array([a[s] for s in used]), np.array([b[s] for s in used]), used, missing


def bootstrap_means(d, n_boot=N_BOOT, seed=BOOT_SEED) -> np.ndarray:
    """Means of n_boot resamples of whole seed pairs."""
    d = np.asarray(d, float)
    if d.size < 2:
        return np.zeros(0)
    rng = np.random.default_rng(seed)
    return d[rng.integers(0, d.size, size=(n_boot, d.size))].mean(axis=1)


def bootstrap_ci(d, n_boot=N_BOOT, seed=BOOT_SEED):
    m = bootstrap_means(d, n_boot, seed)
    if m.size == 0:
        return float("nan"), float("nan")
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def bootstrap_upper(d, level: float, n_boot=N_BOOT, seed=BOOT_SEED) -> float:
    """One-sided upper confidence bound of the mean at confidence 1 - level (percentile)."""
    m = bootstrap_means(d, n_boot, seed)
    return float(np.percentile(m, 100.0 * (1.0 - float(level)))) if m.size else float("nan")


def bootstrap_ni_p(d, margin=NI_MARGIN, n_boot=N_BOOT, seed=BOOT_SEED) -> float:
    m = bootstrap_means(d, n_boot, seed)
    if m.size == 0:
        return 1.0
    return float((1 + np.sum(m >= float(margin))) / (m.size + 1))


def holm(pvals: list[float]) -> list[float]:
    """Holm step-down adjusted p-values (monotone, capped at 1)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


def holm_decisions(tests: list[dict], alpha: float = ALPHA) -> None:
    """Holm step-down with a per-hypothesis test at level alpha / (m - k).

    Each test dict has "p" (ordering p-value) and "kind" ("wilcoxon" or "ni_bootstrap",
    the latter with "diffs").  Adds "holm_step", "holm_level", "reject" and, for NI,
    "ub_at_holm_level".
    """
    m = len(tests)
    order = sorted(range(m), key=lambda i: tests[i]["p"])
    stopped = False
    for k, i in enumerate(order):
        t = tests[i]
        level = alpha / (m - k)
        t["holm_step"] = k + 1
        t["holm_level"] = level
        if t["kind"] == "ni_bootstrap":
            t["ub_at_holm_level"] = bootstrap_upper(t["diffs"], level)
            ok = bool(math.isfinite(t["ub_at_holm_level"]) and t["ub_at_holm_level"] < NI_MARGIN)
        else:
            ok = bool(t["p"] <= level)
        t["reject"] = bool(ok and not stopped)
        if not ok:
            stopped = True
    adj = holm([t["p"] for t in tests])
    for t, pa in zip(tests, adj):
        t["p_holm"] = pa


def family_tests(dirs: dict, treatment: str = "E_plan", reference: str = "B5_c") -> list[dict]:
    tests = []
    for load, path in dirs.items():
        rows = load_rows(Path(path))
        a, b, used, missing = paired(rows, reference, treatment, "value_weighted_exposure")
        d = b - a
        lo, hi = bootstrap_ci(d)
        p_exp = float(wilcoxon(d).pvalue) if d.size >= 2 and np.any(d != 0) else 1.0
        tests.append({"load": load, "hypothesis": "H1 exposure (two-sided Wilcoxon)", "kind": "wilcoxon",
                      "n": int(d.size), "missing_seeds": missing,
                      "mean_diff": float(d.mean()) if d.size else float("nan"),
                      "pct_of_ref": float(100 * d.mean() / a.mean()) if d.size and a.mean() else float("nan"),
                      "ci_lo": lo, "ci_hi": hi, "p": p_exp, "diffs": d})
        a, b, used, missing = paired(rows, reference, treatment, "reactive_miss_fraction")
        d = b - a
        lo, hi = bootstrap_ci(d)
        p_w = float(wilcoxon(d - NI_MARGIN, alternative="less").pvalue) if d.size >= 2 and np.any(
            d != NI_MARGIN) else 1.0
        tests.append({"load": load, "hypothesis": "H2 service noninferiority (bootstrap UB on mean, +2 pp)",
                      "kind": "ni_bootstrap", "n": int(d.size), "missing_seeds": missing,
                      "mean_diff": float(d.mean()) if d.size else float("nan"), "pct_of_ref": float("nan"),
                      "ci_lo": lo, "ci_hi": hi, "p": bootstrap_ni_p(d), "p_wilcoxon_supplementary": p_w,
                      "diffs": d})
    holm_decisions(tests)
    return tests


def run_family(*, treatment: str, reference: str, dirs: dict, expected_n: int, out: Path) -> list[dict]:
    tests = family_tests(dirs, treatment, reference)
    for t in tests:
        t["n_flag"] = "" if t["n"] == expected_n else f"n={t['n']} < expected {expected_n}"
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    fields = ["load", "hypothesis", "n", "missing_seeds", "mean_diff", "pct_of_ref", "ci_lo", "ci_hi", "p",
              "p_wilcoxon_supplementary", "holm_step", "holm_level", "ub_at_holm_level", "p_holm", "reject",
              "n_flag"]
    with (out / "confirmatory_tests.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader()
        for t in tests:
            w.writerow({k: (json.dumps(v) if isinstance(v, list) else v) for k, v in t.items()})
    lines = [f"# Confirmatory family: {treatment} vs {reference} (habituation on)", "",
             "Six hypotheses, Holm step-down, familywise alpha 0.05. H1: two-sided Wilcoxon on exposure.",
             "H2: reject (noninferior) iff the paired bootstrap upper bound on the mean miss-fraction",
             "difference at the hypothesis' Holm level is below +0.02 (decision 24). The one-sided",
             "Wilcoxon on (diff - 0.02) is supplementary only.", "",
             "| Load | Hypothesis | n | Mean diff | 95% CI | % of ref | p (ordering) | Holm step / level | "
             "UB at Holm level | Reject H0 | Wilcoxon (suppl.) | Notes |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in tests:
        note = "; ".join(x for x in [t["n_flag"], ("missing seeds " + str(t["missing_seeds"]))
                                     if t["missing_seeds"] else ""] if x)
        ub = t.get("ub_at_holm_level")
        lines.append(f"| {t['load']} | {t['hypothesis']} | {t['n']} | {t['mean_diff']:+.4g} | "
                     f"[{t['ci_lo']:+.4g}, {t['ci_hi']:+.4g}] | {t['pct_of_ref']:+.2f} | {t['p']:.4g} | "
                     f"{t['holm_step']} / {t['holm_level']:.4g} | "
                     f"{'' if ub is None else f'{ub:+.4g}'} | {t['reject']} | "
                     f"{t.get('p_wilcoxon_supplementary', float('nan')):.4g} | {note} |")
    (out / "confirmatory_tests.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return tests


def main() -> None:
    p = argparse.ArgumentParser(description="Plan Sec. 6 confirmatory analysis")
    p.add_argument("--treatment", default="E_plan")
    p.add_argument("--reference", default="B5_c")
    p.add_argument("--dirs", nargs="+", required=True, help="load=path entries")
    p.add_argument("--expected-n", type=int, default=30)
    p.add_argument("--out", default="results/plan_studies/confirmatory/confirmatory_family")
    args = p.parse_args()
    dirs = dict(e.split("=", 1) for e in args.dirs)
    run_family(treatment=args.treatment, reference=args.reference, dirs=dirs, expected_n=args.expected_n,
               out=Path(args.out))


if __name__ == "__main__":
    main()
