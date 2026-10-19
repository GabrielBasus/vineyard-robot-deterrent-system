"""
run_plan_completion.py -- controlled A to E progression with the completion fixes.

Extends run_variant_ab_comparison.py with:
  * positive-benefit admission (stl_strict_admission): candidates with U(a) <= gate
    are dropped instead of dispatched with a zero score (Plan §4),
  * C with the same benefit gate (C_gate) to split D's changes (Plan §6),
  * B1 and B5 baselines in the same harness so E vs B5 is paired,
  * deadline-based service outcomes, rejected-candidate counts, valuation runtime,
    same-state A vs B ranking agreement and travel-recovery gap (Plan §2, §6),
  * paired bootstrap 95% CIs and the predeclared service noninferiority test.

Predeclared service criterion (fixed 2026-10-13, before any evaluation run):
  E is noninferior to B5 on reactive service when the upper bound of the paired
  95% bootstrap CI of (E minus B5) reactive_miss_fraction is below +0.02 (2 pp).
  reactive_miss_fraction = 1 - (reactive tasks completed within 90 s of creation)
  / (reactive tasks generated); unfinished tasks count as missed.

Seeds: development 200-209 (smoke and tuning), final evaluation 300-329. Never tune
on evaluation seeds.

Plan decision procedure (habituation_stl/plan_procedure.py, planner_procedure="plan"):
  B1_c, B5_c  B1 and B5 in the plan environment: the original system (legacy
              estimator, paper thresholds, 200-entry truth deterrence memory, paper
              excitation kernel) with coupled random streams (Plan Sec. 6),
  D_plan      B5 plus deviations admitted by continuation rollouts, U(a) > eps_gate,
              no service protection (plan variant D),
  E_plan      D_plan with pending-service protection (plan variant E),
  E_plan_tr   E_plan with the timed-recovery requirement (Plan Eq. 4); thresholds
              only through --timed-recovery.
Plan jobs run one at a time after the ordinary jobs (their rollout pool uses the
whole machine); each writes its per-decision JSONL next to its raw JSON.

The run is resumable: a job whose raw JSON already exists is not rerun.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics as stats
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import os

# Batch runs must not append to telemetry_live/ (set before DeterrentSystem is imported).
os.environ.setdefault("DETERRENT_TELEMETRY", "0")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from experiments.run_habituation_stl_production_ladder import METRIC_FIELDS, _write_csv
from experiments.run_variant_ab_comparison import _B4_SYS, _COMMON

EVAL_SEED_START = 300
NONINFERIORITY_MARGIN_PP = 0.02

EXTRA_FIELDS = [
    "reactive_on_time_total",
    "reactive_late_total",
    "reactive_missed_total",
    "reactive_miss_fraction",
    "reactive_unfinished_total",
    "reactive_overdue_time_completed_s",
    "reactive_age_at_completion_p50_s",
    "reactive_age_at_completion_p90_s",
    "predictive_rejected_benefit_gate_total",
    "predictive_passed_benefit_gate_total",
    "stl_eval_count",
    "stl_eval_runtime_mean_ms",
    "stl_eval_runtime_p95_ms",
    "stl_eval_runtime_p99_ms",
    "stl_decision_groups",
    "stl_masked_group_fraction",
    "stl_shadow_compared_groups",
    "stl_shadow_top1_agree_fraction",
    "stl_shadow_kendall_tau_mean",
    "stl_travel_recovery_gap_mean",
    "stl_travel_recovery_gap_p90",
    "stl_travel_recovery_gap_max",
    "stl_travel_recovery_gap_rel_mean",
    "goal_switch_total",
    "goal_switch_abandoned_distance_m",
    "exposure_window_s",
]

_PROPOSED = {
    "simulation_mode": "proposed",
    "enable_patrolling": True,
    "enable_intervention_feedback": True,
    "include_fallback_patrol": True,
    "enable_model_scored_deterring": True,
}

# The confirmatory and ACC runs scale deterrence, including each cue's own beta and
# sigma (deterring_modes), and use no warmup (docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md).
# run_variant_ab_comparison.py (_COMMON) does neither; in that weak-deterrence setting
# every system, B1 included, lands within 0.4% exposure of every other, so it cannot
# test a valuation change. "paper" therefore builds jobs from the ladder's own param
# builders with the confirmatory command-line settings.
CONFIGS = ("paper", "variant_abc")
PAPER_LADDER_ARGV = [
    "--duration-s", "1800", "--warmup-s", "0", "--nx", "60", "--ny", "48", "--nrobots", "4",
    "--reservation-fraction", "0.25", "--deterrence-beta-scale", "4.0",
    "--deterrence-sigma-scale", "4.0", "--deterrence-omega-scale", "3.0",
    "--habituation-kappa", "0.5",
]
# Plan variant -> ladder system it is built on.
LADDER_BASE = {"B4": "B4_res_stl_full_multicue", "B1": "B1_greedy_fixedcue",
               "B5": "B5_greedy_habcue"}


def _ladder_params(system: str, hab_on: bool, mu: float) -> dict:
    import experiments.run_habituation_stl_production_ladder as ladder

    saved = sys.argv
    try:
        sys.argv = ["ladder", *PAPER_LADDER_ARGV, "--mu-true", repr(float(mu))]
        args = ladder.parse_args()
    finally:
        sys.argv = saved
    params = ladder._common_params(args)
    params.update(ladder._system_params(args)[system])
    params.update(ladder._habituation_params(hab_on, args))
    params.pop("habituation_condition", None)
    return params

_ROLLOUT = {"stl_valuation_mode": "continuation_rollout", "stl_benefit_gate": 0.0}

# name -> (base, overrides). base "B4" = _COMMON + _B4_SYS; base "greedy" = _COMMON + _PROPOSED.
VARIANTS: dict[str, tuple[str, dict]] = {
    "B1": ("greedy", {"dispatch_policy": "unc", "predictive_utility_mode": "legacy",
                      "predictive_fixed_deterring_mode": "laser"}),
    "B5": ("greedy", {"dispatch_policy": "unc", "predictive_utility_mode": "legacy_habituation",
                      "predictive_fixed_deterring_mode": None}),
    "A": ("B4", {"stl_forecast_correction": False,
                 "stl_shadow_overrides": {"forecast_correction": True}}),
    "B": ("B4", {"stl_forecast_correction": True,
                 "stl_shadow_overrides": {"forecast_correction": False}}),
    "C": ("B4", {"stl_forecast_correction": True, "stl_valuation_mode": "integrated_exposure"}),
    "C_gate": ("B4", {"stl_forecast_correction": True, "stl_valuation_mode": "integrated_exposure",
                      "stl_strict_admission": True}),
    "D": ("B4", {"stl_forecast_correction": True, **_ROLLOUT}),
    "E": ("B4", {"stl_forecast_correction": True, **_ROLLOUT, "stl_service_protection": True}),
    "D_adm": ("B4", {"stl_forecast_correction": True, **_ROLLOUT, "stl_strict_admission": True}),
    "E_adm": ("B4", {"stl_forecast_correction": True, **_ROLLOUT, "stl_strict_admission": True,
                     "stl_service_protection": True}),
    "D_cue_adm": ("B4", {"stl_forecast_correction": True, **_ROLLOUT, "stl_strict_admission": True,
                         "stl_rollout_cue_dynamics": True}),
    "E_cue_adm": ("B4", {"stl_forecast_correction": True, **_ROLLOUT, "stl_strict_admission": True,
                         "stl_service_protection": True, "stl_rollout_cue_dynamics": True}),
}

# Plan decision procedure (planner_procedure="plan", habituation_stl/plan_procedure.py).
# Every system in this group runs in the same environment: the consistent planner
# estimator, coupled exogenous random streams and complete truth deterrence memory.
# User decision 2026-10-16: the system keeps its original assumptions; only the plan's
# components are new. Coupled random streams are kept (Plan Sec. 6 requires them).
# User decision 2026-10-19: exact deterrence pruning (drop an entry only when its
# remaining suppression is negligible) instead of the 200-entry cap.
PLAN_ENV = {"estimator_mode": "legacy", "random_stream_mode": "coupled",
            "truth_deterrence_memory": "complete"}
# rho = 0.25 over 600 s, the paper's reservation setting, used as a CEILING on a
# robot's predictive-time share for admitting deviations (it never forces work).
# plan_compute_budget_s=1e9: no wall-clock timeout in evaluation runs (the simulator clock
# is frozen while the planner computes; a budget would only add machine-load dependence).
_PLAN = {"planner_procedure": "plan", "reservation_fraction": 0.25, "reservation_window_s": 600.0,
         "plan_compute_budget_s": 1e9,
         # Gate (user decision 2026-10-18): eps_gate = 0 with Monte Carlo significance,
         # admit only if the mean paired U exceeds 2 standard errors over scenarios.
         "plan_eps_gate": 0.0, "plan_gate_se_multiplier": 2.0}
# name -> (ladder variant the system is built on, overrides)
PLAN_VARIANTS: dict[str, tuple[str, dict]] = {
    "B1_c": ("B1", dict(PLAN_ENV)),
    "B5_c": ("B5", dict(PLAN_ENV)),
    "D_plan": ("B5", {**PLAN_ENV, **_PLAN, "plan_service_protection": False}),
    "E_plan": ("B5", {**PLAN_ENV, **_PLAN, "plan_service_protection": True}),
    # E_plan + timed recovery (Plan Eq. 4): plan_E_high, plan_E_low and plan_T_response_s
    # must be supplied through --extra (no defaults are assumed).
    "E_plan_tr": ("B5", {**PLAN_ENV, **_PLAN, "plan_service_protection": True}),
}
PLAN_TR_KEYS = ("plan_E_high", "plan_E_low", "plan_T_response_s")


def is_plan_job(params: dict) -> bool:
    return str(params.get("planner_procedure", "legacy")).strip().lower() == "plan"


# (reference, treatment, label). Deltas are treatment minus reference.
COMPARISONS = [
    ("B1_c", "B5_c", "B5_c vs B1_c: habituation-aware greedy (plan environment)"),
    ("B5_c", "D_plan", "D_plan vs B5_c: plan procedure without service protection"),
    ("B5_c", "E_plan", "E_plan vs B5_c: practical system benefit of the plan procedure"),
    ("D_plan", "E_plan", "E_plan vs D_plan: pending-service protection"),
    ("E_plan", "E_plan_tr", "E_plan_tr vs E_plan: timed recovery constraint"),
    ("A", "B", "B vs A: consistent forecast"),
    ("B", "C", "C vs B: integrated exposure objective"),
    ("C", "C_gate", "C_gate vs C: benefit gate on C"),
    ("C_gate", "D_adm", "D_adm vs C_gate: rollout valuation, gate held fixed"),
    ("D", "D_adm", "D_adm vs D: positive-benefit admission"),
    ("D", "E", "E vs D: service protection (no admission)"),
    ("D_adm", "E_adm", "E_adm vs D_adm: service protection"),
    ("D_adm", "D_cue_adm", "D_cue_adm vs D_adm: cue dynamics in rollout"),
    ("E_adm", "E_cue_adm", "E_cue_adm vs E_adm: cue dynamics in rollout"),
    ("B1", "B5", "B5 vs B1: habituation-aware greedy"),
    ("B5", "A", "A vs B5: submitted B4"),
    ("B5", "E_adm", "E_adm vs B5: practical system benefit"),
    ("B5", "E_cue_adm", "E_cue_adm vs B5: practical system benefit"),
]

REPORT_METRICS = [
    "value_weighted_exposure",
    "reactive_miss_fraction",
    "reactive_missed_total",
    "reactive_completed_total",
    "reactive_overdue_time_completed_s",
    "predictive_completed_total",
    "predictive_rejected_benefit_gate_total",
]


def build_params(variant: str, hab_on: bool, mu: float, t_end: float | None,
                 extra: dict | None = None, config: str = "paper", timed_recovery: dict | None = None) -> dict:
    if any(k in (extra or {}) for k in PLAN_TR_KEYS):
        raise ValueError("pass timed-recovery thresholds with --timed-recovery (they apply to E_plan_tr only)")
    if variant in PLAN_VARIANTS:
        ladder_variant, plan_over = PLAN_VARIANTS[variant]
        params = build_params(ladder_variant, hab_on, mu, t_end, None, config)
        params.update(plan_over)
        params.update(extra or {})
        if variant == "E_plan_tr":
            tr = dict(timed_recovery or {})
            missing = [k for k in PLAN_TR_KEYS if tr.get(k) is None]
            if missing:
                raise ValueError("E_plan_tr needs --timed-recovery with " + ", ".join(missing))
            params.update({k: float(tr[k]) for k in PLAN_TR_KEYS})
        return params
    base, overrides = VARIANTS[variant]
    if config == "paper":
        ladder_system = LADDER_BASE["B4"] if base == "B4" else LADDER_BASE[variant]
        params = _ladder_params(ladder_system, hab_on, mu)
        if base != "B4":
            overrides = {}  # B1 and B5 are taken exactly as the ladder defines them
    else:
        params = dict(_COMMON)
        params.update(_B4_SYS if base == "B4" else _PROPOSED)
        params["enable_habituation"] = bool(hab_on)
    params.update(overrides)
    params["mu_true"] = float(mu)
    if t_end is not None:
        params["T_end"] = float(t_end)
    params.update(extra or {})
    return params


def run_job(job: dict) -> dict:
    import DeterrentSystem as ds

    params = dict(job["params"])
    params["seed"] = int(job["seed"])
    if is_plan_job(params) and job.get("decision_log") and not params.get("plan_log_path"):
        params["plan_log_path"] = str(job["decision_log"])
    started = time.time()
    last = None
    for frame in ds.run_simulation_frames_persistent(**params):
        last = frame
    metrics = (last or {}).get("metrics_compact") or (last or {}).get("metrics") or {}
    row = {
        "system": job["system"],
        "variant": job["variant"],
        "habituation_condition": job["habituation_condition"],
        "seed": int(job["seed"]),
        "mu_true": float(params["mu_true"]),
        "elapsed_s": time.time() - started,
    }
    for field in list(METRIC_FIELDS) + EXTRA_FIELDS:
        try:
            row[field] = float(metrics.get(field))
        except (TypeError, ValueError):
            row[field] = float("nan")
    for field, value in metrics.items():
        if str(field).startswith("plan_"):
            try:
                row[field] = float(value)
            except (TypeError, ValueError):
                row[field] = value
    for key in ("value_weighted_exposure_windows",):
        if key in metrics:
            row[key] = metrics[key]
    return row


def _f(v) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def paired(rows, ref, trt, metric, hab="hab_on"):
    """Return (ref_values, trt_values) aligned by seed."""
    a = {r["seed"]: _f(r.get(metric)) for r in rows
         if r["variant"] == ref and r["habituation_condition"] == hab}
    b = {r["seed"]: _f(r.get(metric)) for r in rows
         if r["variant"] == trt and r["habituation_condition"] == hab}
    seeds = [s for s in sorted(a) if s in b and math.isfinite(a[s]) and math.isfinite(b[s])]
    return np.array([a[s] for s in seeds]), np.array([b[s] for s in seeds])


def bootstrap_ci(diffs: np.ndarray, n_boot: int = 10000, seed: int = 12345):
    """Percentile 95% CI of the mean paired difference, resampling whole seed pairs."""
    if diffs.size < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, diffs.size, size=(n_boot, diffs.size))
    means = diffs[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def analyze(rows: list[dict], outdir: Path, hab: str = "hab_on") -> list[dict]:
    present = {r["variant"] for r in rows if r["habituation_condition"] == hab}
    out = []
    for ref, trt, label in COMPARISONS:
        if ref not in present or trt not in present:
            continue
        for metric in REPORT_METRICS:
            a, b = paired(rows, ref, trt, metric, hab)
            if a.size == 0:
                continue
            d = b - a
            lo, hi = bootstrap_ci(d)
            ref_mean = float(np.mean(a))
            pct = 100.0 * float(np.mean(d)) / ref_mean if ref_mean else float("nan")
            out.append({
                "comparison": label, "reference": ref, "treatment": trt,
                "habituation_condition": hab, "metric": metric, "n": int(d.size),
                "ref_mean": ref_mean, "trt_mean": float(np.mean(b)),
                "mean_diff": float(np.mean(d)), "ci_lo": lo, "ci_hi": hi,
                # Percent effect = mean paired difference / reference mean x 100.
                "pct_of_ref": pct,
            })
    return out


def write_report(rows, outdir: Path, meta: dict) -> None:
    lines = [
        "# Plan completion comparison",
        "",
        f"mu_true={meta['mu']}, seeds {meta['seed_start']}-{meta['seed_start'] + meta['num_runs'] - 1}, "
        f"T_end={meta['t_end']}",
        "Percent effect = mean paired difference / reference mean x 100; 95% CI by bootstrap",
        "over seed pairs (10000 resamples). Negative exposure difference = improvement.",
        "",
    ]
    all_stats = []
    for hab in ("hab_on", "hab_off"):
        stats_rows = analyze(rows, outdir, hab)
        all_stats += stats_rows
        if not stats_rows:
            continue
        lines += [f"## {hab}", "", "| Comparison | Metric | n | Ref mean | Diff | 95% CI | % of ref |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for s in stats_rows:
            lines.append(
                f"| {s['comparison']} | {s['metric']} | {s['n']} | {s['ref_mean']:.4g} | "
                f"{s['mean_diff']:+.4g} | [{s['ci_lo']:+.4g}, {s['ci_hi']:+.4g}] | {s['pct_of_ref']:+.2f}% |"
            )
        lines.append("")
        for ref, trt in (("B5", "E_adm"), ("B5", "E_cue_adm"), ("B5_c", "E_plan"), ("B5_c", "E_plan_tr")):
            ni = [s for s in stats_rows if s["reference"] == ref and s["treatment"] == trt
                  and s["metric"] == "reactive_miss_fraction"]
            if ni:
                s = ni[0]
                verdict = "NONINFERIOR" if s["ci_hi"] < NONINFERIORITY_MARGIN_PP else "NOT SHOWN"
                lines.append(
                    f"Service noninferiority {trt} vs {ref} ({hab}): upper 95% bound "
                    f"{100 * s['ci_hi']:+.2f} pp vs margin +{100 * NONINFERIORITY_MARGIN_PP:.0f} pp -> {verdict}"
                )
        lines.append("")
    _write_csv(all_stats, outdir / "paired_stats.csv")
    (outdir / "plan_completion_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--outdir", default="results/testbench/plan_completion")
    p.add_argument("--variants", default=",".join(VARIANTS))
    p.add_argument("--hab", default="on,off", help="on, off or on,off")
    p.add_argument("--mu", type=float, default=2e-5)
    p.add_argument("--seed-start", type=int, default=EVAL_SEED_START)
    p.add_argument("--num-runs", type=int, default=30)
    p.add_argument("--t-end", type=float, default=None)
    p.add_argument("--max-workers", type=int, default=1)
    p.add_argument("--extra", default="{}", help="JSON dict of params applied to every job")
    p.add_argument("--config", default="paper", choices=CONFIGS)
    p.add_argument("--timed-recovery", default="{}",
                   help='JSON {"plan_E_high": .., "plan_E_low": .., "plan_T_response_s": ..} for E_plan_tr')
    p.add_argument("--analyze-only", action="store_true")
    args = p.parse_args()

    outdir = Path(args.outdir).resolve()
    raw = outdir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    habs = [h.strip() == "on" for h in args.hab.split(",") if h.strip()]
    extra = json.loads(args.extra)
    timed_recovery = json.loads(args.timed_recovery)

    jobs = []
    for seed in range(args.seed_start, args.seed_start + args.num_runs):
        for v in variants:
            for hab_on in habs:
                cond = "hab_on" if hab_on else "hab_off"
                system = f"{v}_{cond}"
                if (raw / f"{system}_seed_{seed}.json").exists():
                    continue
                jobs.append({"system": system, "variant": v, "habituation_condition": cond,
                             "seed": seed,
                             "decision_log": str(raw / f"{system}_seed_{seed}_decisions.jsonl"),
                             "params": build_params(v, hab_on, args.mu, args.t_end, extra, args.config,
                                                    timed_recovery)})
    print(f"[completion] pending jobs={len(jobs)} outdir={outdir}", flush=True)
    started = time.time()

    def _record(i, n, row):
        (raw / f"{row['system']}_seed_{row['seed']}.json").write_text(
            json.dumps(row, indent=2, allow_nan=True), encoding="utf-8")
        print(f"[completion] {i}/{n} {row['system']} seed={row['seed']} "
              f"{row['elapsed_s']:.0f}s VWE={row['value_weighted_exposure']:.1f} "
              f"miss={row['reactive_miss_fraction']:.3f}", flush=True)

    if jobs and not args.analyze_only:
        # Plan-procedure jobs use the whole machine through their rollout worker pool,
        # so they run ONE AT A TIME in this process, after the ordinary jobs (which run
        # in parallel) have finished; their decision runtimes then see an idle machine.
        plan_jobs = [j for j in jobs if is_plan_job(j["params"])]
        other_jobs = [j for j in jobs if not is_plan_job(j["params"])]
        done = 0
        if other_jobs:
            workers = max(1, min(args.max_workers, len(other_jobs)))
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(run_job, j): j for j in other_jobs}
                for fut in as_completed(futs):
                    job = futs[fut]
                    done += 1
                    try:
                        row = fut.result()
                    except Exception as exc:  # keep the sweep alive; record the failure
                        print(f"[completion] FAILED {job['system']} seed={job['seed']}: {exc!r}", flush=True)
                        continue
                    _record(done, len(jobs), row)
        for job in plan_jobs:
            done += 1
            try:
                row = run_job(job)
            except Exception as exc:  # keep the sweep alive; record the failure
                print(f"[completion] FAILED {job['system']} seed={job['seed']}: {exc!r}", flush=True)
                continue
            _record(done, len(jobs), row)

    rows = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(raw.glob("*.json"))]
    rows.sort(key=lambda r: (r["variant"], r["habituation_condition"], int(r["seed"])))
    _write_csv(rows, outdir / "per_run_metrics.csv")
    meta = {"config": args.config, "ladder_argv": PAPER_LADDER_ARGV if args.config == "paper" else None, "mu": args.mu, "seed_start": args.seed_start, "num_runs": args.num_runs,
            "t_end": args.t_end or _COMMON["T_end"], "extra": extra, "timed_recovery": timed_recovery,
            "elapsed_s": time.time() - started,
            "noninferiority_margin_pp": NONINFERIORITY_MARGIN_PP}
    (outdir / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    write_report(rows, outdir, meta)
    print(f"[completion] wrote {outdir}", flush=True)


if __name__ == "__main__":
    main()
