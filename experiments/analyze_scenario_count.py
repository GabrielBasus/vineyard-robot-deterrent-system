"""
analyze_scenario_count.py -- can E_plan use fewer Monte Carlo scenarios? (user, 2026-10-19)

Scenarios are keyed by index, so the first n scenarios of a 16-scenario evaluation are
exactly what an n-scenario evaluation sees. From runs logged with plan_log_per_scenario
and plan_oracle_all_candidates, every round-0 decision is replayed for n in {2, 4, 8, 16}:
  admissible = service-feasible in all n scenarios (on-time and late-task conditions)
               and mean paired U > 2 * SE over the n scenarios (the evaluation gate);
  choice     = argmax mean U among admissible (or no deviation).
Decisions with an oracle evaluation of all round-0 candidates are scored by true benefit:
  the oracle U of the chosen candidate (0 when nothing is admitted).

Criterion D (predeclared by the user, 2026-10-19): an n is good enough if BOTH
  (B) quality: total true benefit of n's choices is within 10% of n=16's, i.e. the lower
      bound of the paired bootstrap 95% CI of (Q_n - Q_16) / Q_16 is above -10%;
  (C) harm: the share of n's admitted deviations with negative oracle U exceeds the
      n=16 share by at most 2 percentage points.
Limitation: only round 0 of each decision is replayed (later rounds depend on the
round-0 commitment); round 0 is where every first commitment is made.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
from pathlib import Path

import numpy as np

NS = (2, 4, 8, 16)


def replay(rnd, n):
    U = np.asarray(rnd["U_per_scenario"], float)[:, :n]
    viol = rnd["viol_per_scenario"]
    mean = U.mean(axis=1)
    se = U.std(axis=1, ddof=1) / math.sqrt(n) if n > 1 else np.full(U.shape[0], np.inf)
    best, best_u = None, -math.inf
    for j in range(U.shape[0]):
        if any(v[0] or v[1] for v in viol[j][:n]):
            continue
        if not (mean[j] > 2.0 * se[j]):
            continue
        if mean[j] > best_u:
            best, best_u = j, mean[j]
    return None if best is None else int(rnd["cand_indices"][best])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dirs", nargs="+", default=sorted(glob.glob("results/testbench/scenario_test_mu*")))
    p.add_argument("--out", default="results/testbench/scenario_count_analysis.json")
    args = p.parse_args()
    report = {}
    for d in args.dirs:
        decisions, scored = [], []
        for f in glob.glob(str(Path(d) / "raw" / "*_decisions.jsonl")):
            for line in open(f, encoding="utf-8"):
                rec = json.loads(line)
                if "rounds" not in rec or not rec["rounds"] or "U_per_scenario" not in rec["rounds"][0]:
                    continue
                rnd = rec["rounds"][0]
                choice = {n: replay(rnd, n) for n in NS}
                decisions.append(choice)
                orc = (rec.get("oracle") or {}).get("all_round0")
                if orc:
                    u_or = dict(zip(orc["cand_indices"], orc["U_oracle"]))
                    scored.append({n: (0.0 if choice[n] is None else float(u_or[choice[n]]), choice[n]) for n in NS})
        res = {"decisions": len(decisions), "scored_decisions": len(scored)}
        for n in NS:
            agree = np.mean([c[n] == c[16] for c in decisions]) if decisions else math.nan
            q = np.array([s[n][0] for s in scored]); q16 = np.array([s[16][0] for s in scored])
            adm = [s[n][0] for s in scored if s[n][1] is not None]
            harm = float(np.mean([u < 0 for u in adm])) if adm else math.nan
            row = {"same_choice_as_16": float(agree), "admitted": len(adm), "harm_share": harm,
                   "true_benefit_total": float(q.sum()) if q.size else math.nan}
            if q.size >= 2 and q16.sum() != 0:
                rng = np.random.default_rng(12345)
                idx = rng.integers(0, q.size, size=(10000, q.size))
                rel = (q[idx].sum(1) - q16[idx].sum(1)) / np.where(q16[idx].sum(1) == 0, np.nan, q16[idx].sum(1))
                lo, hi = np.nanpercentile(rel, [2.5, 97.5])
                row.update(rel_quality=float((q.sum() - q16.sum()) / q16.sum()), rel_ci=[float(lo), float(hi)])
            res[f"n{n}"] = row
        h16 = res["n16"]["harm_share"]
        for n in NS:
            r = res[f"n{n}"]
            okB = ("rel_ci" in r) and r["rel_ci"][0] > -0.10
            okC = not math.isnan(r["harm_share"]) and not math.isnan(h16) and r["harm_share"] - h16 <= 0.02
            r["criterion_D"] = bool(okB and okC) if n != 16 else True
        report[Path(d).name] = res
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
