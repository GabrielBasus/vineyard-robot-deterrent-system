"""
run_plan_completion.py -- controlled progression of the improvement plan (Plan Sec. 6).

Every evaluated system runs in ONE environment, PLAN_ENV, so every comparison is
matched (user decisions of 2026-10-16, 2026-10-19 and Section 6 decision 1):

  PLAN_ENV = legacy planner estimator (the original system's assumptions),
             coupled exogenous random streams (Plan Sec. 6),
             complete truth deterrence memory with exact pruning (2026-10-19),
             stl_forecast_correction=True (decision 1: q x beta everywhere: candidate,
             B5 continuation and executed model feedback).

Variants (decisions 3-8, 26):
  B1_c, B5_c   ladder B1 / B5 (paper configuration) in PLAN_ENV.
  A            the submitted B4 implementation exactly (ladder B4_res_stl_full_multicue):
               stl_forecast_correction=False and every new flag at its default, although
               PLAN_ENV sets the correction True for every other system (user decision
               2026-10-22).  Only the PLAN_ENV environment (streams, truth memory) and the
               diagnostic same-state shadow re-score (decision 12) are added.
  B            A + all Section 2 items (decision 5): forecast correction, forward
               trajectory correction, committed schedule (reactive tasks in the pending
               timeline, mapped to the laser cue), queue-aware lead, planner update model.
  C            B + Plan Eq. 3 valuation over all cells (decision 6).
  C_gate       C + the same gate as D (strict U > 0) and the same reservation ceiling (decision 7).
  C_plan       plan procedure with the one-intervention Eq. 3 valuation, NO service
               protection (decision 8 and the WS-B follow-up).
  D_plan       plan procedure, continuation rollouts, no service protection.
  E_plan       D_plan + pending-service protection (confirmatory E, decision 2).
  E_plan_tr    E_plan + timed recovery (Plan Eq. 4) with the fixed dev-seed thresholds
               of docs/calibration/timed_recovery_thresholds.json (exploratory, decision 2).
  E_plan_floor E_plan + effectiveness floor 0.4 at application (decision 26).

The old rollout variants D, E, *_adm and *_cue_adm are dropped (decision 4).

Original legacy setup (Section 7 reproduction only; NOT part of the progression):
  B1, B5, B4   the ladder systems exactly as the ACC submission ran them (legacy random
               streams, window200 memory, no new flags).  See
               experiments/reproduce_acc_submission.py.

Predeclared service criterion (fixed 2026-10-13, before any evaluation run):
  E is noninferior to B5 on reactive service when the upper confidence bound of the
  paired mean (E minus B5) reactive_miss_fraction is below +0.02 (2 pp).  The
  confirmatory version (Holm-adjusted level, decision 24) is in
  experiments/analyze_plan_confirmatory.py; this script reports the nominal 95% bound.

Seeds: development 200-209, final evaluation 300-329.  Never tune on evaluation seeds.

Execution (memory-safe, resumable):
  * every job runs in its own subprocess and writes raw/<system>_seed_<seed>.json;
    a job whose raw JSON exists is not rerun;
  * before EVERY launch the scheduler waits until at least --min-free-gb (12 GB) of
    memory is available, polling every --poll-s (300 s);
  * ordinary jobs run at most --max-workers (default 2) at a time and plan-procedure jobs
    at most --plan-concurrency (default 2) at a time; by default ordinary jobs run first,
    --overlap runs both pools at the same time (fastest).
    Each plan run sizes its own rollout pool with the existing memory cap
    (scenario_rollout.RolloutPool.memory_capped_workers: available memory minus a 30%
    reserve, 1.5 GB per worker, at most ROLLOUT_MAX_WORKERS=12).  Consecutive plan
    launches are separated by --plan-stagger-s (300 s) so a new run sizes its pool
    after the previous run's pool exists.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

# Batch runs must not append to telemetry_live/ (set before DeterrentSystem is imported).
os.environ.setdefault("DETERRENT_TELEMETRY", "0")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from experiments.run_habituation_stl_production_ladder import METRIC_FIELDS, _write_csv

EVAL_SEED_START = 300
DEV_SEED_START = 200
NONINFERIORITY_MARGIN_PP = 0.02
LOADS = {"spare": 2e-5, "heavy": 1e-4, "overload": 4e-4}
TIMED_RECOVERY_FILE = _root / "docs" / "calibration" / "timed_recovery_thresholds.json"

# Memory safety (a 31-worker pool once exhausted 32 GB and forced a reboot).
MIN_FREE_GB = 12.0
MEMORY_POLL_S = 300.0

# ---------------------------------------------------------------------------
# Configuration: the ACC paper configuration, built by the ladder's own builders
# ---------------------------------------------------------------------------
# The confirmatory and ACC runs scale deterrence, including each cue's own beta and
# sigma (deterring_modes), and use no warmup (docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md).
CONFIGS = ("paper",)
PAPER_LADDER_ARGV = [
    "--duration-s", "1800", "--warmup-s", "0", "--nx", "60", "--ny", "48", "--nrobots", "4",
    "--reservation-fraction", "0.25", "--deterrence-beta-scale", "4.0",
    "--deterrence-sigma-scale", "4.0", "--deterrence-omega-scale", "3.0",
    "--habituation-kappa", "0.5",
]
LADDER_SYSTEMS = {"B4": "B4_res_stl_full_multicue", "B1": "B1_greedy_fixedcue",
                  "B5": "B5_greedy_habcue"}
# Backward-compatible name used by older scripts.
LADDER_BASE = LADDER_SYSTEMS


def _ladder_params(system: str, hab_on: bool, mu: float) -> dict:
    """Parameters of ladder ``system`` exactly as the ACC paper configuration runs it."""
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


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------
# Section 7 reproduction: the ladder systems in the ORIGINAL legacy setup (legacy
# random streams, window200 truth memory, no new flags).  "B1" and "B5" keep their
# historical meaning for older scripts and tests.
LEGACY_VARIANTS = {"B1": "B1", "B5": "B5", "B4": "B4"}

# Shared environment of every evaluated system (decisions 2026-10-16, 2026-10-19, Sec. 6 #1).
PLAN_ENV = {"estimator_mode": "legacy", "random_stream_mode": "coupled",
            "truth_deterrence_memory": "complete", "stl_forecast_correction": True}

# Section 2 items of variant B (decision 5).
_SECTION2 = {
    "stl_forecast_correction": True,
    "stl_forward_trajectory_correction": True,
    "stl_committed_schedule": True,
    "stl_queue_aware_lead": True,
    "stl_forecast_planner_update_model": True,
}
_A = {"stl_forecast_correction": False,
      # decision 12: keep the same-state A vs B shadow ranking for the B4 variants
      "stl_shadow_overrides": {"forecast_correction": True}}
_B = {**_SECTION2, "stl_shadow_overrides": {"forecast_correction": False}}
_C = {**_SECTION2, "stl_valuation_mode": "integrated_exposure_eq3"}
_C_GATE = {**_C, "stl_strict_admission": True, "stl_benefit_gate": 0.0, "reservation_mode": "ceiling"}

# name -> (ladder system, overrides applied on top of the ladder params and PLAN_ENV)
B4_VARIANTS: dict[str, tuple[str, dict]] = {
    "A": ("B4", _A),
    "B": ("B4", _B),
    "C": ("B4", _C),
    "C_gate": ("B4", _C_GATE),
}

# rho = 0.25 over 600 s, the paper's reservation setting, used as a CEILING on a robot's
# predictive-time share for admitting deviations (it never forces work).
# plan_compute_budget_s=1e9: no wall-clock timeout in evaluation runs (decision 16; the
# simulator clock is frozen while the planner computes).
_PLAN = {"planner_procedure": "plan", "reservation_fraction": 0.25, "reservation_window_s": 600.0,
         "plan_compute_budget_s": 1e9,
         # Gate (user decision 2026-10-18): eps_gate = 0 with Monte Carlo significance,
         # admit only if the mean paired U exceeds 2 standard errors over scenarios.
         "plan_eps_gate": 0.0, "plan_gate_se_multiplier": 2.0,
         # decision 12: oracle of all round-0 candidates on the oracle-sampled decisions
         "plan_oracle_all_candidates": True}

PLAN_TR_KEYS = ("plan_E_high", "plan_E_low", "plan_T_response_s")

PLAN_VARIANTS: dict[str, tuple[str, dict]] = {
    "B1_c": ("B1", {}),
    "B5_c": ("B5", {}),
    "D_plan": ("B5", {**_PLAN, "plan_service_protection": False}),
    "E_plan": ("B5", {**_PLAN, "plan_service_protection": True}),
    # decision 2: exploratory "with STL constraints"; thresholds from TIMED_RECOVERY_FILE
    "E_plan_tr": ("B5", {**_PLAN, "plan_service_protection": True}),
    # decision 8 + WS-B follow-up: one-intervention Eq. 3 valuation inside the plan
    # procedure, NO service protection (matches D_plan; isolates the continuation).
    # TODO(FU-1): plan_procedure.py may add C_plan parameters; this entry uses only
    # plan_valuation="one_intervention" and plan_service_protection=False.
    "C_plan": ("B5", {**_PLAN, "plan_service_protection": False, "plan_valuation": "one_intervention"}),
    # decision 26: reject candidates whose eta at application < 0.4 in any applied scenario
    "E_plan_floor": ("B5", {**_PLAN, "plan_service_protection": True, "plan_eta_floor": 0.4}),
}

# Evaluation variants in progression order (all in PLAN_ENV).
VARIANTS = ["B1_c", "B5_c", "A", "B", "C", "C_gate", "C_plan", "D_plan", "E_plan", "E_plan_tr",
            "E_plan_floor"]

# (reference, treatment, label). Deltas are treatment minus reference.  Every pair is
# within PLAN_ENV, same load, same habituation condition, same seeds.
COMPARISONS = [
    ("A", "B", "B vs A: Section 2 forecast changes"),
    ("B", "C", "C vs B: Eq. 3 objective alignment"),
    ("C", "C_gate", "C_gate vs C: positive-benefit gate and reservation ceiling"),
    ("C_gate", "C_plan", "C_plan vs C_gate: plan procedure (B5 candidates, unc dispatch, fleet view)"),
    ("C_plan", "D_plan", "D_plan vs C_plan: continuation valuation"),
    ("D_plan", "E_plan", "E_plan vs D_plan: pending-service protection"),
    ("B5_c", "E_plan", "E_plan vs B5_c: practical system benefit"),
    ("E_plan", "E_plan_tr", "E_plan_tr vs E_plan: timed recovery constraint"),
    ("E_plan", "E_plan_floor", "E_plan_floor vs E_plan: effectiveness floor 0.4"),
    ("B1_c", "B5_c", "B5_c vs B1_c: habituation-aware greedy"),
    ("B5_c", "A", "A vs B5_c: submitted B4"),
]

# Mission, service (decisions 9-11) and mechanism/implementation metrics (decisions
# 12-16, 29).  Plan metrics are compared only where both systems report them.
REPORT_METRICS = [
    # mission
    "value_weighted_exposure",
    # service
    "reactive_miss_fraction",
    "reactive_missed_total",
    "reactive_generated_total",
    "reactive_completed_total",
    "reactive_on_time_total",
    "reactive_late_total",
    "reactive_overdue_time_completed_s",
    "reactive_age_at_completion_mean_s",
    "reactive_age_at_completion_p50_s",
    "reactive_age_at_completion_p90_s",
    "mean_response_time_s",
    "reactive_unfinished_total",
    "reactive_unfinished_overdue_total",
    "reactive_unfinished_overdue_time_s",
    # mechanism
    "predictive_completed_total",
    "predictive_rejected_benefit_gate_total",
    "travel_distance_total",
    "motion_time_reactive_s",
    "motion_time_predictive_s",
    "motion_time_deviation_s",
    "eta_truth_at_application_all_mean",
    "eta_truth_at_application_reactive_mean",
    "eta_truth_at_application_predictive_mean",
    "eta_truth_at_application_deviation_mean",
    "eta_planner_at_application_all_mean",
    "cue_reuse_all_interval_mean_s",
    "cue_reuse_all_eta_truth_at_reuse_mean",
    "cue_reuse_deviation_interval_mean_s",
    "cue_reuse_deviation_eta_truth_at_reuse_mean",
    "stl_shadow_top1_agree_fraction",
    "stl_shadow_kendall_tau_mean",
    "stl_masked_group_fraction",
    # implementation
    "stl_eval_runtime_p95_ms",
    "plan_deviations_admitted",
    "plan_candidates_per_decision_mean",
    "plan_runtime_mean_s",
    "plan_runtime_p95_s",
    "plan_runtime_p99_s",
    "plan_timeout_rate",
    "plan_dev_differs_from_b5_fraction",
    "plan_dev_b5_rank_mean",
    "plan_oracle_kendall_tau_mean",
    "plan_pred_err_U_mean_abs",
    "plan_dev_travel_err_mean_s",
    "plan_F0_protected_missed",
    "plan_F0_protected_all_scen_missed",
]


def load_timed_recovery(path: Path | str = TIMED_RECOVERY_FILE) -> dict:
    """Fixed dev-seed thresholds (2026-10-17) as plan_* parameters."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"plan_E_high": float(d["E_high"]), "plan_E_low": float(d["E_low"]),
            "plan_T_response_s": float(d["T_response_s"])}


def is_plan_job(params: dict) -> bool:
    return str(params.get("planner_procedure", "legacy")).strip().lower() == "plan"


def build_params(variant: str, hab_on: bool, mu: float, t_end: float | None,
                 extra: dict | None = None, config: str = "paper", timed_recovery: dict | None = None) -> dict:
    """Simulator parameters of ``variant``.

    Evaluation variants (VARIANTS) = ladder paper params + PLAN_ENV + variant overrides.
    Legacy variants (B1, B5, B4) = ladder paper params unchanged (Section 7 reproduction).
    ``extra`` is applied last.  E_plan_tr reads TIMED_RECOVERY_FILE unless
    ``timed_recovery`` gives all three thresholds.
    """
    if config not in CONFIGS:
        raise ValueError(f"config must be one of {CONFIGS}")
    extra = dict(extra or {})
    if any(k in extra for k in PLAN_TR_KEYS):
        raise ValueError("pass timed-recovery thresholds with timed_recovery (they apply to E_plan_tr only)")
    if variant in LEGACY_VARIANTS:
        params = _ladder_params(LADDER_SYSTEMS[LEGACY_VARIANTS[variant]], hab_on, mu)
    elif variant in PLAN_VARIANTS or variant in B4_VARIANTS:
        ladder, over = PLAN_VARIANTS[variant] if variant in PLAN_VARIANTS else B4_VARIANTS[variant]
        params = _ladder_params(LADDER_SYSTEMS[ladder], hab_on, mu)
        params.update(PLAN_ENV)
        params.update(json.loads(json.dumps(over)))  # deep copy of nested overrides
        if variant == "E_plan_tr":
            tr = dict(timed_recovery) if timed_recovery else load_timed_recovery()
            missing = [k for k in PLAN_TR_KEYS if tr.get(k) is None]
            if missing:
                raise ValueError("E_plan_tr needs timed-recovery thresholds " + ", ".join(missing))
            params.update({k: float(tr[k]) for k in PLAN_TR_KEYS})
    else:
        raise KeyError(f"unknown variant {variant!r}; evaluation variants: {VARIANTS}, "
                       f"legacy: {sorted(LEGACY_VARIANTS)}")
    params["mu_true"] = float(mu)
    if t_end is not None:
        params["T_end"] = float(t_end)
    params.update(extra)
    return params


# ---------------------------------------------------------------------------
# One job
# ---------------------------------------------------------------------------
def _scalar(v):
    if isinstance(v, (bool, np.bool_)):
        return float(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    if isinstance(v, str):
        return v
    return None


# Non-scalar metrics kept in the raw JSON (per-window and per-robot breakdowns).
STRUCTURED_METRICS = ("value_weighted_exposure_windows", "outcome_windows", "motion_time_by_robot_stream_s",
                      "motion_time_by_robot_s")


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
    for key in ("cell", "study"):
        if key in job:
            row[key] = job[key]
    if params.get("arrival_burst"):
        # decision 29: record the burst actually injected (start drawn per seed)
        row["arrival_burst_start_s"] = float(params["arrival_burst"]["start_s"])
        row["arrival_burst_duration_s"] = float(params["arrival_burst"]["duration_s"])
        row["arrival_burst_factor"] = float(params["arrival_burst"]["factor"])
    for field in METRIC_FIELDS:
        row[field] = float("nan")
    for field, value in metrics.items():
        s = _scalar(value)
        if s is not None:
            row[field] = s
    for key in STRUCTURED_METRICS:
        if key in metrics:
            row[key] = metrics[key]
    return row


def _raw_path(raw: Path, system: str, seed: int) -> Path:
    return raw / f"{system}_seed_{int(seed)}.json"


def make_job(raw: Path, variant: str, hab_on: bool, seed: int, params: dict, **meta) -> dict:
    cond = "hab_on" if hab_on else "hab_off"
    system = f"{variant}_{cond}"
    job = {"system": system, "variant": variant, "habituation_condition": cond, "seed": int(seed),
           "raw_json": str(_raw_path(raw, system, seed)),
           "decision_log": str(raw / f"{system}_seed_{int(seed)}_decisions.jsonl"),
           "params": params}
    job.update(meta)
    return job


def _run_job_file(path: str) -> int:
    """Subprocess entry point: run one pickled job and write its raw JSON atomically."""
    with open(path, "rb") as fh:
        job = pickle.load(fh)
    row = run_job(job)
    out = Path(job["raw_json"])
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row, indent=2, allow_nan=True, default=str), encoding="utf-8")
    os.replace(tmp, out)
    print(f"[job] done {job['system']} seed={job['seed']} {row['elapsed_s']:.0f}s "
          f"VWE={row.get('value_weighted_exposure', float('nan')):.1f}", flush=True)
    return 0


# ---------------------------------------------------------------------------
# Memory-safe scheduler
# ---------------------------------------------------------------------------
def free_memory_gb() -> float:
    import psutil
    return psutil.virtual_memory().available / 1024 ** 3


def wait_for_memory(min_free_gb: float = MIN_FREE_GB, poll_s: float = MEMORY_POLL_S, tag: str = "sched") -> float:
    """Block until at least ``min_free_gb`` of memory is available; poll every ``poll_s``."""
    while True:
        free = free_memory_gb()
        if free >= float(min_free_gb):
            return free
        print(f"[{tag}] only {free:.1f} GB free (< {min_free_gb:.0f} GB); waiting {poll_s:.0f} s", flush=True)
        time.sleep(float(poll_s))


def _launch(job: dict):
    raw_json = Path(job["raw_json"])
    raw_json.parent.mkdir(parents=True, exist_ok=True)
    jobs_dir = raw_json.parent / "_jobs"
    jobs_dir.mkdir(exist_ok=True)
    jf = jobs_dir / (raw_json.stem + ".pkl")
    with open(jf, "wb") as fh:
        pickle.dump(job, fh)
    logfh = open(raw_json.with_suffix(".log"), "w", encoding="utf-8")
    env = dict(os.environ, DETERRENT_TELEMETRY="0")
    proc = subprocess.Popen([sys.executable, "-m", "experiments.run_plan_completion", "--run-job", str(jf)],
                            cwd=str(_root), env=env, stdout=logfh, stderr=subprocess.STDOUT)
    return proc, logfh, str(jf)


def execute_jobs(jobs: list[dict], *, max_workers: int = 2, plan_concurrency: int = 2,
                 plan_stagger_s: float = 300.0, min_free_gb: float = MIN_FREE_GB,
                 poll_s: float = MEMORY_POLL_S, tag: str = "completion", check_s: float = 5.0,
                 overlap: bool = False) -> dict:
    """Run jobs in subprocesses with a memory check (>= min_free_gb, polled every poll_s)
    before every launch.

    Two pools: ordinary jobs (<= max_workers at once) and plan jobs (<= plan_concurrency at
    once, consecutive launches separated by plan_stagger_s so each new run sizes its rollout
    pool after the previous run's pool exists).  overlap=False: ordinary jobs first, then
    plan jobs (plan runtimes then see no ordinary load).  overlap=True: both pools run at
    the same time (fastest; plan runtimes are measured under the extra load).
    Returns {"done": n, "failed": [...]}.
    """
    pending = [j for j in jobs if not Path(j["raw_json"]).exists()]
    pools = {"ordinary": {"queue": [j for j in pending if not is_plan_job(j["params"])],
                          "slots": max(1, int(max_workers)), "stagger": 0.0},
             "plan": {"queue": [j for j in pending if is_plan_job(j["params"])],
                      "slots": max(1, int(plan_concurrency)), "stagger": float(plan_stagger_s)}}
    for pool in pools.values():
        pool["running"] = []
        pool["last"] = -math.inf
    order = ["ordinary", "plan"]
    total = len(pending)
    done = 0
    failed = []
    print(f"[{tag}] pending jobs={total} (ordinary {len(pools['ordinary']['queue'])}, "
          f"plan {len(pools['plan']['queue'])}), overlap={overlap}", flush=True)

    def active_pools():
        if overlap:
            return order
        for name in order:   # sequential: the first pool with work left
            if pools[name]["queue"] or pools[name]["running"]:
                return [name]
        return []

    try:
        while any(pools[n]["queue"] or pools[n]["running"] for n in order):
            for name in order:
                pool = pools[name]
                for item in list(pool["running"]):
                    proc, job, logfh, jf = item
                    if proc.poll() is None:
                        continue
                    pool["running"].remove(item)
                    logfh.close()
                    done += 1
                    if proc.returncode == 0 and Path(job["raw_json"]).exists():
                        Path(jf).unlink(missing_ok=True)
                        print(f"[{tag}] {done}/{total} {job['system']} seed={job['seed']} ok", flush=True)
                    else:
                        failed.append({"system": job["system"], "seed": job["seed"], "returncode": proc.returncode,
                                       "log": job["raw_json"].replace(".json", ".log")})
                        print(f"[{tag}] {done}/{total} FAILED {job['system']} seed={job['seed']} "
                              f"rc={proc.returncode} (see log)", flush=True)
            launched = False
            for name in active_pools():
                pool = pools[name]
                if pool["queue"] and len(pool["running"]) < pool["slots"] and \
                        (time.time() - pool["last"]) >= pool["stagger"]:
                    wait_for_memory(min_free_gb, poll_s, tag)
                    job = pool["queue"].pop(0)
                    proc, logfh, jf = _launch(job)
                    pool["running"].append((proc, job, logfh, jf))
                    pool["last"] = time.time()
                    launched = True
                    print(f"[{tag}] launched {name} {job['system']} seed={job['seed']} "
                          f"(running {len(pool['running'])}/{pool['slots']}, free {free_memory_gb():.1f} GB)",
                          flush=True)
            if not launched:
                time.sleep(check_s)
    except KeyboardInterrupt:
        for pool in pools.values():
            for proc, _, logfh, _ in pool["running"]:
                proc.terminate()
                logfh.close()
        raise
    return {"done": done, "failed": failed}


# ---------------------------------------------------------------------------
# Paired analysis
# ---------------------------------------------------------------------------
def _f(v) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def paired(rows, ref, trt, metric, hab="hab_on"):
    """Return (ref_values, trt_values) aligned by seed (finite pairs only)."""
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


def analyze(rows: list[dict], outdir: Path | None = None, hab: str = "hab_on",
            comparisons=None, metrics=None) -> list[dict]:
    present = {r["variant"] for r in rows if r["habituation_condition"] == hab}
    out = []
    for ref, trt, label in (comparisons or COMPARISONS):
        if ref not in present or trt not in present:
            continue
        for metric in (metrics or REPORT_METRICS):
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


def write_report(rows, outdir: Path, meta: dict, comparisons=None) -> list[dict]:
    lines = [
        "# Plan completion comparison",
        "",
        f"mu_true={meta.get('mu')}, seeds {meta.get('seeds')}, T_end={meta.get('t_end')}",
        "Environment PLAN_ENV = " + json.dumps(PLAN_ENV),
        "Percent effect = mean paired difference / reference mean x 100; 95% CI by bootstrap",
        "over seed pairs (10000 resamples). Negative exposure difference = improvement.",
        "Exploratory: nominal intervals, no multiplicity adjustment (the confirmatory family",
        "is in experiments/analyze_plan_confirmatory.py).",
        "",
    ]
    all_stats = []
    for hab in ("hab_on", "hab_off"):
        stats_rows = analyze(rows, outdir, hab, comparisons)
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
        for s in stats_rows:
            if s["reference"] == "B5_c" and s["metric"] == "reactive_miss_fraction" and \
                    s["treatment"].startswith("E_plan"):
                verdict = "below margin" if s["ci_hi"] < NONINFERIORITY_MARGIN_PP else "NOT below margin"
                lines.append(
                    f"Service (nominal 95%, exploratory) {s['treatment']} vs B5_c ({hab}): upper bound "
                    f"{100 * s['ci_hi']:+.2f} pp vs margin +{100 * NONINFERIORITY_MARGIN_PP:.0f} pp -> {verdict}")
        lines.append("")
    _write_csv(all_stats, outdir / "paired_stats.csv")
    (outdir / "plan_completion_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return all_stats


def load_rows(outdir: Path) -> list[dict]:
    raw = Path(outdir) / "raw"
    rows = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(raw.glob("*.json"))]
    rows.sort(key=lambda r: (r["variant"], r["habituation_condition"], int(r["seed"])))
    return rows


def flat_rows(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k not in STRUCTURED_METRICS} for r in rows]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--run-job", default=None, help=argparse.SUPPRESS)
    p.add_argument("--outdir", default="results/plan_completion")
    p.add_argument("--variants", default=",".join(VARIANTS))
    p.add_argument("--hab", default="on", help="on, off or on,off")
    p.add_argument("--mu", type=float, default=2e-5)
    p.add_argument("--seed-start", type=int, default=EVAL_SEED_START)
    p.add_argument("--num-runs", type=int, default=30)
    p.add_argument("--t-end", type=float, default=None)
    p.add_argument("--max-workers", type=int, default=2, help="concurrent ordinary (non-plan) jobs")
    p.add_argument("--plan-concurrency", type=int, default=2, help="concurrent plan-procedure runs")
    p.add_argument("--plan-stagger-s", type=float, default=300.0)
    p.add_argument("--overlap", action="store_true",
                   help="run ordinary jobs at the same time as plan jobs (fastest; default: ordinary first)")
    p.add_argument("--min-free-gb", type=float, default=MIN_FREE_GB)
    p.add_argument("--poll-s", type=float, default=MEMORY_POLL_S)
    p.add_argument("--extra", default="{}", help="JSON dict of params applied to every job")
    p.add_argument("--timed-recovery", default="",
                   help='JSON {"plan_E_high": .., "plan_E_low": .., "plan_T_response_s": ..}; '
                        "default: docs/calibration/timed_recovery_thresholds.json")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--analyze-only", action="store_true")
    args = p.parse_args()
    if args.run_job:
        sys.exit(_run_job_file(args.run_job))

    outdir = Path(args.outdir).resolve()
    raw = outdir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    habs = [h.strip() == "on" for h in args.hab.split(",") if h.strip()]
    extra = json.loads(args.extra)
    timed_recovery = json.loads(args.timed_recovery) if args.timed_recovery else None
    seeds = list(range(args.seed_start, args.seed_start + args.num_runs))

    jobs = [make_job(raw, v, hab_on, seed,
                     build_params(v, hab_on, args.mu, args.t_end, extra, "paper", timed_recovery))
            for seed in seeds for v in variants for hab_on in habs]
    if args.dry_run:
        for j in jobs:
            state = "done" if Path(j["raw_json"]).exists() else ("plan" if is_plan_job(j["params"]) else "ordinary")
            print(f"{j['system']} seed={j['seed']} {state}")
        return
    started = time.time()
    if not args.analyze_only:
        execute_jobs(jobs, max_workers=args.max_workers, plan_concurrency=args.plan_concurrency,
                     plan_stagger_s=args.plan_stagger_s, min_free_gb=args.min_free_gb, poll_s=args.poll_s,
                     overlap=args.overlap)

    rows = load_rows(outdir)
    _write_csv(flat_rows(rows), outdir / "per_run_metrics.csv")
    t_end = args.t_end if args.t_end is not None else 1800.0
    meta = {"config": "paper", "ladder_argv": PAPER_LADDER_ARGV, "plan_env": PLAN_ENV, "mu": args.mu,
            "seeds": f"{seeds[0]}-{seeds[-1]}" if seeds else "", "t_end": t_end, "extra": extra,
            "timed_recovery": timed_recovery or load_timed_recovery(), "elapsed_s": time.time() - started,
            "noninferiority_margin_pp": NONINFERIORITY_MARGIN_PP}
    (outdir / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    write_report(rows, outdir, meta)
    print(f"[completion] wrote {outdir}", flush=True)


if __name__ == "__main__":
    main()
