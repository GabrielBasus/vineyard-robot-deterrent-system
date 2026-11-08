"""TOST (Two One-Sided Tests) equivalence analysis for H4.

H4 predicts that B4 provides no spurious benefit over B1 when habituation is
disabled (hab_off): the reservation and STL structure alone should not produce
a significant advantage. This is tested by declaring B4−B1 equivalent to zero
within a pre-specified equivalence bound ±delta.

Method: non-parametric TOST using two one-sided Wilcoxon signed-rank tests,
exactly consistent with the two-sided Wilcoxon used throughout the analysis
(same tie correction, same continuity correction, same erfc-based p-value).

  Upper test (H0+: θ ≥ +delta): one-sided "less" on (deltas − delta)
  Lower test (H0-: θ ≤ −delta): one-sided "greater" on (deltas + delta)
  Equivalence declared if both p_upper < alpha AND p_lower < alpha.

IMPORTANT — pre-specification requirement:
  The equivalence bound --delta must be chosen on substantive grounds BEFORE
  looking at results. A principled starting point: 25% of the matched-condition
  B4-B1 advantage at the same load point.
    spare-capacity peak (mu=1e-4, kappa=0.50): 0.25 × 13,648 ≈ 3,400 units
    low-load spare-capacity  (mu=2e-5, kappa=0.50): 0.25 × 3,697 ≈  925 units
  Using the same delta for both load points is conservative for the low-load test.

Under hab_off, kappa is irrelevant (eta ≡ 1 regardless), so all 7 kappa cells
give identical results. The analysis uses a single representative kappa (default
0.50) to avoid pseudoreplication.

Usage:
    python -m experiments.run_h4_tost --delta 3400
    python -m experiments.run_h4_tost --delta 3400 --alpha 0.05
    python -m experiments.run_h4_tost --delta 3400 --mus 2e-5 1e-4
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics as st
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

JOINT_DIR = REPO_ROOT / "results/testbench/habituation_stl_joint_sweep"

MUS_DEFAULT: list[float] = [2e-5, 1e-4, 4e-4]
KAPPA_DEFAULT: float = 0.50

B1 = "B1_greedy_fixedcue"
B3 = "B3_res_stl_nohab_multicue"
B4 = "B4_res_stl_full_multicue"

RHO_LOAD: dict[tuple[float, float], float] = {
    (2e-5, 0.00): 0.384, (2e-5, 0.10): 0.434, (2e-5, 0.25): 0.389,
    (2e-5, 0.40): 0.456, (2e-5, 0.50): 0.458, (2e-5, 0.65): 0.457,
    (2e-5, 0.80): 0.524,
    (1e-4, 0.00): 0.458, (1e-4, 0.10): 0.504, (1e-4, 0.25): 0.599,
    (1e-4, 0.40): 0.700, (1e-4, 0.50): 0.821, (1e-4, 0.65): 0.718,
    (1e-4, 0.80): 0.856,
    (4e-4, 0.00): 0.884, (4e-4, 0.10): 0.957, (4e-4, 0.25): 1.259,
    (4e-4, 0.40): 1.669, (4e-4, 0.50): 1.659, (4e-4, 0.65): 1.817,
    (4e-4, 0.80): 1.919,
}


# ── data loading ──────────────────────────────────────────────────────────────

def sf(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except Exception:
        return None


def mu_token(mu: float) -> str:
    exp = math.floor(math.log10(mu))
    m = f"{mu / (10.0 ** exp):.4g}".replace(".", "p")
    return f"mu_{m}em{abs(exp):02d}"


def kappa_token(k: float) -> str:
    return f"kappa_{k:.2f}".replace(".", "p")


def load_per_run(mu: float, kappa: float) -> list[dict]:
    cell = JOINT_DIR / f"{mu_token(mu)}_{kappa_token(kappa)}"
    p = cell / "per_run_metrics.csv"
    if not p.exists():
        return []
    return list(csv.DictReader(p.open(encoding="utf-8")))


def pairwise_deltas(
    rows: list[dict],
    target: str,
    ref: str,
    hab: str = "hab_off",
    metric: str = "value_weighted_exposure",
) -> list[float]:
    by = {
        (r["baseline"], r["habituation_condition"], int(float(r["seed"]))): r
        for r in rows
    }
    seeds = sorted({int(float(r["seed"])) for r in rows if r.get("habituation_condition") == hab})
    deltas = []
    for seed in seeds:
        t = by.get((target, hab, seed))
        r = by.get((ref, hab, seed))
        if t and r:
            tv, rv = sf(t[metric]), sf(r[metric])
            if tv is not None and rv is not None:
                deltas.append(tv - rv)
    return deltas


# ── Wilcoxon one-sided test ───────────────────────────────────────────────────

def _wplus_stats(deltas: list[float]) -> tuple[float, float, float]:
    """Return (W+, mu_W, var_W) for a list of deltas (zeros excluded).

    Uses the same tie correction and ranking as finalize_thesis_results.wilcoxon_p().
    """
    nonzero = [d for d in deltas if d != 0.0]
    n = len(nonzero)
    if n == 0:
        return 0.0, 0.0, 0.0

    pairs = sorted(((abs(d), 1 if d > 0 else -1) for d in nonzero), key=lambda x: x[0])
    ranked: list[tuple[int, float]] = []
    i = 0
    while i < n:
        j = i
        while j < n and pairs[j][0] == pairs[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranked.append((pairs[k][1], avg))
        i = j

    w_plus = sum(r for s, r in ranked if s > 0)
    tc = sum(t * (t - 1) * (t + 1) for t in Counter(p[0] for p in pairs).values()) / 48.0
    mu_W = n * (n + 1) / 4.0
    var_W = n * (n + 1) * (2 * n + 1) / 24.0 - tc
    return w_plus, mu_W, var_W


def wilcoxon_onesided(deltas: list[float], alternative: str) -> float:
    """One-sided Wilcoxon signed-rank p-value.

    alternative: 'less'    — H0: median ≥ 0, H1: median < 0
                 'greater' — H0: median ≤ 0, H1: median > 0

    Returns 1.0 when n < 4 (matches finalize_thesis_results guard).
    Uses continuity correction and erfc-based normal approximation.
    """
    nonzero = [d for d in deltas if d != 0.0]
    if len(nonzero) < 4:
        return 1.0

    w_plus, mu_W, var_W = _wplus_stats(deltas)
    if var_W <= 0.0:
        return 1.0
    sigma = math.sqrt(var_W)

    if alternative == "less":
        # P(W+ ≤ w_plus): small W+ supports H1 (median < 0)
        z = (w_plus + 0.5 - mu_W) / sigma
        return 0.5 * math.erfc(-z / math.sqrt(2.0))
    elif alternative == "greater":
        # P(W+ ≥ w_plus): large W+ supports H1 (median > 0)
        z = (w_plus - 0.5 - mu_W) / sigma
        return 0.5 * math.erfc(z / math.sqrt(2.0))
    else:
        raise ValueError(f"alternative must be 'less' or 'greater', got {alternative!r}")


def tost_wilcoxon(deltas: list[float], delta: float) -> tuple[float, float]:
    """Non-parametric TOST: return (p_upper, p_lower).

    p_upper tests H0+: θ ≥ +delta  (reject → upper bound clear)
    p_lower tests H0-: θ ≤ −delta  (reject → lower bound clear)
    Equivalence when max(p_upper, p_lower) < alpha.
    """
    shifted_upper = [d - delta for d in deltas]   # shift toward zero from above
    shifted_lower = [d + delta for d in deltas]   # shift toward zero from below
    p_upper = wilcoxon_onesided(shifted_upper, "less")
    p_lower = wilcoxon_onesided(shifted_lower, "greater")
    return p_upper, p_lower


# ── reporting ─────────────────────────────────────────────────────────────────

def _fmt_mu(mu: float) -> str:
    s = f"{mu:.0e}"
    # "2e-05" → "2×10⁻⁵"
    mantissa, exp_part = s.split("e")
    exp_val = int(exp_part)
    return f"{mantissa}×10{superscript(exp_val)}"


def superscript(n: int) -> str:
    sup = {"0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶","7":"⁷","8":"⁸","9":"⁹","-":"⁻"}
    return "".join(sup.get(c, c) for c in str(n))


def _fmt_delta(v: float) -> str:
    if math.isnan(v):
        return "     NaN"
    return f"{v:+9,.0f}"


def run(args: argparse.Namespace) -> None:
    delta = args.delta
    alpha = args.alpha
    kappa_rep = args.kappa_rep
    mus = args.mus

    print()
    print("=" * 76)
    print("  TOST Equivalence Analysis — H4  (B4 vs B1, hab_off)")
    print("=" * 76)
    print(f"  Equivalence bound : ±{delta:,.0f} units")
    print(f"  Significance level: α = {alpha}")
    print(f"  Test              : two one-sided Wilcoxon signed-rank (non-parametric)")
    print(f"  Representative κ  : {kappa_rep:.2f}  (κ irrelevant under hab_off; η ≡ 1)")
    print(f"  H4 scope          : spare-capacity regime (ρ_load < ~0.86)")
    print()
    print(
        f"  {'μ':>9}  {'ρ_load':>6}  {'n':>3}  {'mean(B4−B1)':>12}"
        f"  {'p_upper':>8}  {'p_lower':>8}  {'p_max':>7}  result"
    )
    print("  " + "─" * 80)

    for mu in mus:
        rows = load_per_run(mu, kappa_rep)
        if not rows:
            tok = f"{mu_token(mu)}_{kappa_token(kappa_rep)}"
            print(f"  {'':>9}  —  no data found at {tok}")
            continue

        deltas = pairwise_deltas(rows, B4, B1, hab="hab_off")
        if not deltas:
            print(f"  {_fmt_mu(mu):>9}  —  no paired B4/B1 data under hab_off")
            continue

        n = len(deltas)
        mean_d = st.mean(deltas)
        rho = RHO_LOAD.get((mu, kappa_rep), float("nan"))
        p_upper, p_lower = tost_wilcoxon(deltas, delta)
        p_max = max(p_upper, p_lower)
        equiv = p_max < alpha

        if equiv:
            result = f"EQUIVALENT     (p_max = {p_max:.3f} < {alpha})"
        else:
            result = f"not equivalent (p_max = {p_max:.3f} ≥ {alpha})"

        print(
            f"  {_fmt_mu(mu):>9}  {rho:>6.3f}  {n:>3}  {_fmt_delta(mean_d):>12}"
            f"  {p_upper:>8.3f}  {p_lower:>8.3f}  {p_max:>7.3f}  {result}"
        )

    print()
    print("  Note: μ=4×10⁻⁴ is the overloaded regime; B4 is significantly worse")
    print("  there even under hab_on (reservation overhead exceeds benefit).")
    print("  TOST equivalence is not expected or claimed for that column.")
    print()

    # ── B4 vs B3 mechanistic verification ─────────────────────────────────────
    print("─" * 76)
    print("  B4 vs B3 under hab_off — mechanistic verification")
    print("  (with η ≡ 1 the habituation clause is inert; B4 and B3 are identical)")
    print()
    print(f"  {'μ':>9}  {'ρ_load':>6}  {'n':>3}  {'mean(B4−B3)':>12}  result")
    print("  " + "─" * 60)

    for mu in mus:
        rows = load_per_run(mu, kappa_rep)
        if not rows:
            continue
        deltas_b4b3 = pairwise_deltas(rows, B4, B3, hab="hab_off")
        if not deltas_b4b3:
            continue
        mean_b4b3 = st.mean(deltas_b4b3)
        rho = RHO_LOAD.get((mu, kappa_rep), float("nan"))
        all_zero = all(d == 0.0 for d in deltas_b4b3)
        note = "identically zero ✓" if all_zero else (
            f"NOT identically zero — max |d| = {max(abs(d) for d in deltas_b4b3):.1f}"
        )
        print(
            f"  {_fmt_mu(mu):>9}  {rho:>6.3f}  {len(deltas_b4b3):>3}"
            f"  {_fmt_delta(mean_b4b3):>12}  {note}"
        )

    print()


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Non-parametric TOST equivalence test for H4 (B4 vs B1 under hab_off). "
            "Reads from the joint sweep hab_off cells. "
            "The equivalence bound --delta must be pre-specified on substantive grounds."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Suggested delta values (25%% of matched-condition B4-B1 advantage):\n"
            "  --delta 3400   based on peak spare-capacity advantage  (0.25 × 13,648)\n"
            "  --delta  925   based on low-load spare-capacity point  (0.25 ×  3,697)"
        ),
    )
    parser.add_argument(
        "--delta",
        type=float,
        required=True,
        metavar="UNITS",
        help=(
            "Equivalence bound in value_weighted_exposure units. "
            "Must be pre-specified before looking at results."
        ),
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        metavar="FLOAT",
        help="Significance level for each one-sided test (default: 0.05).",
    )
    parser.add_argument(
        "--kappa-rep",
        type=float,
        default=KAPPA_DEFAULT,
        metavar="FLOAT",
        help=(
            "Representative κ value to read from the joint sweep (default: 0.50). "
            "Under hab_off κ has no effect on outcomes."
        ),
    )
    parser.add_argument(
        "--mus",
        nargs="+",
        type=float,
        default=MUS_DEFAULT,
        metavar="FLOAT",
        help=f"μ values to test (default: {MUS_DEFAULT}).",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
