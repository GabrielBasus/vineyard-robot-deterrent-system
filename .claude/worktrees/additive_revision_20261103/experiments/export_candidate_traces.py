"""
export_candidate_traces.py -- Section 7 work package 1: candidate-level traces of a few decisions.

Sources:
  * plan decision JSONL (habituation_stl/plan_procedure.py, one record per replan decision,
    written to raw/<system>_seed_<seed>_decisions.jsonl by run_plan_completion), and
  * the Section 3 binding log of the B4 variants (stl_binding_log_path, one record per
    STL-scored candidate of a sampled decision: TaskGenerator.configure_binding_log).

Selection (deterministic, so the traces are reproducible): from each plan log, up to
--per-kind decisions of each kind, earliest first:
  admitted        a deviation was admitted;
  gate            the best feasible candidate failed the Monte Carlo gate (U <= 2 SE);
  service         some candidate was rejected as infeasible_service / infeasible_late;
  floor / obligation / timeout   when present.
From each binding log, the first --per-kind sampled decisions (t, robot) with >= 2 candidates.

Outputs (in --out):
  plan_traces.csv     one row per (decision, candidate, round): robot, target, cue, origin,
                      B5 rank and score, U mean / SE, J, q_hat at application range,
                      rejection reason, final status, J0 of the round, oracle U if sampled;
  plan_traces.md      the same decisions as readable tables (forecast error appears as
                      planner U vs oracle U where the oracle sampled the decision);
  binding_traces.csv  one row per binding-log record (every key flattened);
  binding_traces.md   grouped by decision: which clause / time / cell bound each score
                      (robustness masking shows as equal scores bound by the same clause).

Usage:
  py -3.10 -m experiments.export_candidate_traces \
      --plan-logs results/plan_studies/confirmatory/heavy/raw/E_plan_hab_on_seed_300_decisions.jsonl \
      --binding-logs results/plan_studies/confirmatory/heavy/raw/A_hab_on_seed_300_binding.jsonl \
      --out results/candidate_traces
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

KINDS = ("admitted", "gate", "service", "floor", "obligation", "timeout")


def read_jsonl(path: Path) -> list:
    out = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def decision_kinds(rec: dict) -> set:
    st = {c.get("status") for c in rec.get("candidates", [])}
    reasons = {e.get("reason") for c in rec.get("candidates", []) for e in c.get("rounds", [])}
    kinds = set()
    if rec.get("admitted"):
        kinds.add("admitted")
    if "gate" in st or "gate" in reasons:
        kinds.add("gate")
    if st & {"infeasible_service", "infeasible_late"}:
        kinds.add("service")
    if "floor" in st:
        kinds.add("floor")
    if st & {"infeasible_obligation", "obligation_exceedance"}:
        kinds.add("obligation")
    if rec.get("timed_out"):
        kinds.add("timeout")
    return kinds


def select_decisions(records: list, per_kind: int) -> list:
    chosen, seen = [], set()
    for kind in KINDS:
        n = 0
        for rec in records:
            if "decision" not in rec:
                continue           # the trailing {"obligations": ...} record
            if kind in decision_kinds(rec) and n < per_kind:
                n += 1
                if rec["decision"] not in seen:
                    seen.add(rec["decision"])
                    chosen.append((kind, rec))
    return chosen


def _oracle_u(rec: dict) -> dict:
    """candidate index -> (U_oracle, U_oracle_se) from the oracle's all-round-0 evaluation."""
    orc = rec.get("oracle") or {}
    a0 = orc.get("all_round0") or {}
    out = {}
    for i, u, se in zip(a0.get("cand_indices", []), a0.get("U_oracle", []), a0.get("U_oracle_se", [])):
        out[int(i)] = (u, se)
    return out


def plan_rows(source: str, kind: str, rec: dict) -> list:
    rows = []
    j0 = {r["round"]: r.get("J0_mean") for r in rec.get("rounds", [])}
    orc = _oracle_u(rec)
    for idx, c in enumerate(rec.get("candidates", [])):
        rounds = c.get("rounds") or [{}]
        for e in rounds:
            u_o = orc.get(idx, (None, None)) if e.get("round") == 0 else (None, None)
            rows.append({
                "source": source, "kind": kind, "decision": rec["decision"], "t": rec["t"],
                "candidate": idx, "robot": c.get("robot"), "x": c.get("x"), "y": c.get("y"), "cue": c.get("mode"),
                "origin": c.get("origin"), "b5_rank": c.get("b5_rank"), "b5_score": c.get("b5_score"),
                "round": e.get("round"), "J0_round": j0.get(e.get("round")),
                "J_candidate": e.get("J_mean"), "U_mean": e.get("U_mean"), "U_se": e.get("U_se"),
                "q_hat_app_min": e.get("q_hat_app_min"), "q_hat_app_max": e.get("q_hat_app_max"),
                "round_reason": e.get("reason"), "final_status": c.get("status"),
                "U_oracle": u_o[0], "U_oracle_se": u_o[1],
                "share": (rec.get("robot_share") or {}).get(c.get("robot")), "rho": rec.get("rho"),
                "runtime_s": rec.get("runtime_s"), "timed_out": rec.get("timed_out"),
            })
    return rows


def _fmt(v, nd=3):
    if v is None:
        return "-"
    if isinstance(v, float):
        return "nan" if not math.isfinite(v) else f"{v:.{nd}g}"
    return str(v)


def plan_markdown(source: str, kind: str, rec: dict, rows: list) -> list:
    lines = [f"### {source} decision {rec['decision']} (t = {rec['t']:.0f} s, kind: {kind})", "",
             f"candidates {rec.get('n_candidates')}, evaluated {rec.get('n_evaluated')}, rounds "
             f"{len(rec.get('rounds', []))}, admitted {len(rec.get('admitted', []))}, runtime "
             f"{_fmt(rec.get('runtime_s'))} s, timed out {rec.get('timed_out')}, pending reactive "
             f"{rec.get('pending')}, J_hat executed {_fmt(rec.get('J_hat_executed'))}", "",
             "| cand | robot | cue | origin | B5 rank | round | U mean | U se | U oracle | q_hat app | reason | status |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        q = "-" if r["q_hat_app_min"] is None else f"{_fmt(r['q_hat_app_min'])}-{_fmt(r['q_hat_app_max'])}"
        lines.append(f"| {r['candidate']} | {r['robot']} | {r['cue']} | {r['origin']} | {_fmt(r['b5_rank'])} | "
                     f"{_fmt(r['round'])} | {_fmt(r['U_mean'])} | {_fmt(r['U_se'])} | {_fmt(r['U_oracle'])} | {q} | "
                     f"{_fmt(r['round_reason'])} | {r['final_status']} |")
    for a in rec.get("admitted", []):
        lines.append("")
        lines.append(f"Admitted: robot {a.get('robot')} cue {a.get('mode')} U {_fmt(a.get('U_mean'))} +- "
                     f"{_fmt(a.get('U_se'))}, differs from B5 {a.get('differs_from_b5')}, predicted travel "
                     f"{_fmt(a.get('pred_travel_s_mean'))} s, realized {_fmt(a.get('real_travel_s'))} s")
    lines.append("")
    return lines


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif isinstance(v, (list, tuple)):
            out[key] = json.dumps(v)
        else:
            out[key] = v
    return out


def binding_groups(records: list, per_kind: int) -> list:
    groups = {}
    for r in records:
        groups.setdefault((r.get("t"), r.get("robot")), []).append(r)
    keys = [k for k in groups if len(groups[k]) >= 2][:per_kind]
    return [(k, groups[k]) for k in keys]


def _write(rows: list, path: Path) -> None:
    if not rows:
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(rows)


def export(plan_logs: list, binding_logs: list, out: Path, per_kind: int = 2) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    all_rows, md = [], ["# Candidate-level traces (plan procedure)", ""]
    for p in plan_logs:
        recs = read_jsonl(Path(p))
        for kind, rec in select_decisions(recs, per_kind):
            rows = plan_rows(Path(p).name, kind, rec)
            all_rows += rows
            md += plan_markdown(Path(p).name, kind, rec, rows)
    _write(all_rows, out / "plan_traces.csv")
    (out / "plan_traces.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    b_rows, bmd = [], ["# Section 3 binding traces (B4 variants)", ""]
    for p in binding_logs:
        for (t, robot), recs in binding_groups(read_jsonl(Path(p)), per_kind):
            flat = [_flatten(r) for r in recs]
            for f in flat:
                f["source"] = Path(p).name
            b_rows += flat
            # readable view: the score, and where the binding clause of each robustness bound
            keys = ["mode", "x", "y", "U", "q_hat", "lead_s", "rho_nom", "rho_wa",
                    "binding_clause_nom", "binding_clause_wa"]
            bmd += [f"### {Path(p).name} t = {t} robot {robot} ({len(recs)} candidates)", "",
                    "| " + " | ".join(keys) + " | nom bound at (t_s, cell, value) | wa bound at (t_s, cell, value) |",
                    "| " + " | ".join("---" for _ in keys) + " | --- | --- |"]
            for f in flat:
                cells = []
                for side in ("nom", "wa"):
                    c = f.get(f"binding_clause_{side}")
                    cells.append(f"({_fmt(f.get(f'binding_{side}.{c}.t_s'))}, {_fmt(f.get(f'binding_{side}.{c}.cell'))}, "
                                 f"{_fmt(f.get(f'binding_{side}.{c}.value'))})" if c else "-")
                bmd.append("| " + " | ".join(_fmt(f.get(k)) for k in keys) + " | " + " | ".join(cells) + " |")
            bmd.append("")
    _write(b_rows, out / "binding_traces.csv")
    (out / "binding_traces.md").write_text("\n".join(bmd) + "\n", encoding="utf-8")
    return {"plan_rows": len(all_rows), "binding_rows": len(b_rows)}


def main() -> None:
    p = argparse.ArgumentParser(description="Export candidate-level decision traces (Section 7)")
    p.add_argument("--plan-logs", nargs="*", default=[])
    p.add_argument("--binding-logs", nargs="*", default=[])
    p.add_argument("--per-kind", type=int, default=2)
    p.add_argument("--out", default="results/candidate_traces")
    args = p.parse_args()
    print(export(args.plan_logs, args.binding_logs, Path(args.out), args.per_kind))


if __name__ == "__main__":
    main()
