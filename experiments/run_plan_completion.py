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
  C_gate       C + the same gate as D (strict U > 0) (decision 7).  No reservation ceiling
               anywhere (user decision 2026-10-22, audit round): C_gate keeps the submitted
               B4 reservation FLOOR (reservation_mode "floor", rho 0.25 over 600 s) of A, B, C.
  C_plan       plan procedure with the one-intervention Eq. 3 valuation, NO service
               protection (decision 8 and the WS-B follow-up).
  Reservation (final user decision 2026-10-22): the B4-based variants A, B, C, C_gate keep
  the submitted B4 reservation FLOOR (rho 0.25 over 600 s); the B5-based plan variants
  (C_plan, D_plan, E_plan, E_plan_tr, E_plan_floor) have NO reservation.  So the step
  C_gate -> C_plan also changes the reservation (floor -> none).
  D_plan       plan procedure, continuation rollouts, no service protection.
  E_plan       D_plan + pending-service protection (confirmatory E, decision 2).
  E_plan_tr    E_plan + timed recovery (Plan Eq. 4) with the fixed dev-seed thresholds
               of docs/calibration/timed_recovery_thresholds.json (exploratory, decision 2).
  E_plan_floor E_plan + effectiveness floor 0.4 at application (decision 26).

The old rollout variants D, E, *_adm and *_cue_adm are dropped (decision 4).

Original legacy setup (Section 7 reproduction only; NOT part of the progression):
  B1, B5, B4, B3  the ladder systems exactly as the ACC submission ran them (legacy random
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
                  "B5": "B5_greedy_habcue",
                  # B3 as in the paper's joint sweep (Table VII), Section 7 reproduction only
                  "B3": "B3_res_stl_nohab_multicue"}
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
LEGACY_VARIANTS = {"B1": "B1", "B5": "B5", "B4": "B4", "B3": "B3"}

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
# Decision 12 / user 2026-10-22 (audit round and confirmed side-session decision 2): DUAL
# same-state shadow for variant A.  A keeps the forecast-only shadow (stl_shadow_overrides
# {"forecast_correction": True}, reported as stl_shadow_forecast_*) AND gains a full-set
# shadow that re-scores every candidate with B's FULL Section 2 set, inputs too (committed
# schedule, queue-aware lead), reported as stl_shadow_full_*; the full-set shadow score of A
# must equal B's primary score on the same state.
SHADOW_B_FULL_SECTION2 = dict(_SECTION2)
# B's shadows mirror A's: forecast-only off, and the full Section 2 set off (= A's scoring).
SHADOW_A_SECTION2 = {k: False for k in _SECTION2}
_A = {"stl_forecast_correction": False,
      "stl_shadow_overrides": {"forecast_correction": True},
      "stl_shadow_full_section2": dict(SHADOW_B_FULL_SECTION2)}
_B = {**_SECTION2, "stl_shadow_overrides": {"forecast_correction": False},
      "stl_shadow_full_section2": dict(SHADOW_A_SECTION2)}
_C = {**_SECTION2, "stl_valuation_mode": "integrated_exposure_eq3"}
# No ceiling (audit round 2026-10-22): C_gate keeps the ladder B4 reservation floor of A/B/C
# (dispatch_policy "res", reservation_fraction 0.25, reservation_window_s 600, simulator
# default reservation_mode "floor"), so C -> C_gate isolates the gate alone.
_C_GATE = {**_C, "stl_strict_admission": True, "stl_benefit_gate": 0.0}

# name -> (ladder system, overrides applied on top of the ladder params and PLAN_ENV)
B4_VARIANTS: dict[str, tuple[str, dict]] = {
    "A": ("B4", _A),
    "B": ("B4", _B),
    "C": ("B4", _C),
    "C_gate": ("B4", _C_GATE),
}

# Reservation (final user decision 2026-10-22): the plan variants are B5-based and carry NO
# reservation parameter (no ceiling, no floor); the B4-based variants keep the B4 floor.
# plan_compute_budget_s=1e9: no wall-clock timeout in evaluation runs (decision 16; the
# simulator clock is frozen while the planner computes).
_PLAN = {"planner_procedure": "plan",
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
    ("C", "C_gate", "C_gate vs C: positive-benefit gate (same reservation floor)"),
    ("C_gate", "C_plan", "C_plan vs C_gate: plan procedure (B5 candidates, unc dispatch, fleet view) "
                         "and reservation floor -> none"),
    ("C_plan", "D_plan", "D_plan vs C_plan: continuation valuation"),
    ("C", "D_plan", "D_plan vs C: plan procedure with continuation vs B4-pipeline Eq. 3"),
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
    # B4 forecast: travel-recovery gap of the candidate's cue (user decision 2026-10-22)
    "stl_travel_recovery_gap_mean",
    "stl_travel_recovery_gap_p90",
    "stl_travel_recovery_gap_max",
    "stl_travel_recovery_gap_rel_mean",
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
    "plan_dev_travel_err_mean_s",
    "plan_F0_protected_missed",
    "plan_F0_protected_all_scen_missed",
    # fleet argmax ties broken to the lowest index (accepted 2026-10-22): count of exact-U ties
    "plan_exact_u_tie_count",
    # oracle cost (all candidates on 25% of decisions, 64 scenarios)
    "plan_oracle_decisions",
    "plan_oracle_wall_s_total",
]

# Dual same-state shadow of A vs B (confirmed 2026-10-22): forecast-only and full Section 2
# set, each over all valuations and over first evaluations only (*_first_eval).
SHADOW_KINDS = ("forecast", "full")
SHADOW_STATS = ("top1_agree_fraction", "kendall_tau_mean", "masked_group_fraction", "compared_groups")
SHADOW_METRICS = [f"stl_shadow_{k}_{s}{suf}" for k in SHADOW_KINDS for s in SHADOW_STATS for suf in ("", "_first_eval")]

# Candidate rejection reasons of the plan procedure (user decision 2026-10-22): counts and
# per-decision means of every final status of habituation_stl/plan_procedure.REJECTION_REASONS
# (there is no ceiling) plus the groups feasibility (infeasible_service + infeasible_late)
# and obligation (infeasible_obligation + obligation_exceedance).
REJECTION_REASONS = ("infeasible_service", "infeasible_late", "gate", "floor", "infeasible_obligation",
                     "obligation_exceedance", "timeout", "robot_committed", "not_selected",
                     "feasibility", "obligation")
PLAN_REJECTION_METRICS = [f"plan_rejected_{r}{suf}" for r in REJECTION_REASONS for suf in ("", "_per_decision_mean")]

# Prop. 2 (user decision 2026-10-22, audit round): scale-free metrics are PRIMARY, raw
# unit-mixed errors (planner legacy units vs truth units, suffix _raw_units) SECONDARY.
PROP2_PRIMARY_METRICS = [
    "plan_prop2_sign_agree_fraction",                 # planner vs oracle sign agreement of U
    "plan_prop2_sign_agree_n",
    "plan_prop2_kendall_tau_mean",                    # planner vs oracle ranking of the candidates
    "plan_prop2_kendall_tau_median",
    "plan_prop2_kendall_tau_n",
    "plan_prop2_admitted_oracle_U_positive_fraction",  # admitted deviations with oracle U > 0
    "plan_prop2_admitted_oracle_n",
]
RAW_UNITS_SUFFIX = "_raw_units"
PROP2_SECONDARY_METRICS = [
    "plan_pred_err_U_bias_raw_units",
    "plan_pred_err_U_mean_abs_raw_units",
    "plan_pred_err_U_p95_abs_raw_units",
    "plan_pred_err_U_max_abs_raw_units",
    "plan_pred_err_J0_bias_raw_units",
    "plan_pred_err_J0_mean_abs_raw_units",
    "plan_pred_err_J0_p95_abs_raw_units",
    "plan_pred_err_J0_max_abs_raw_units",
    "plan_pred_err_J0_rel_mean",
    "plan_pred_err_Ja_bias_raw_units",
    "plan_pred_err_Ja_mean_abs_raw_units",
    "plan_pred_err_Ja_p95_abs_raw_units",
    "plan_realized_minus_pred_mean_raw_units",
    "plan_realized_minus_pred_mean_abs_raw_units",
    "plan_oracle_J0_se_mean_raw_units",
    "plan_oracle_U_se_mean_raw_units",
    "plan_oracle_admitted_U_oracle_mean_raw_units",
    # C_plan: its J-hat is the one-intervention J (no continuation)
    "plan_realized_minus_one_intervention_J_windows",
    "plan_realized_minus_one_intervention_J_mean_raw_units",
]

# Per-robot Prop. 2 (per-robot information sets; neighbor study).  The per-robot keys
# plan_pr_prop2_<metric>_<rid> and plan_pr_*_<rid> are added automatically from the rows.
PER_ROBOT_PREFIX = "plan_pr_"
PER_ROBOT_METRICS = (
    ["plan_pr_robots"]
    + [f"plan_pr_prop2_{m}_robot_{s}" for m in ("sign_agree_fraction", "kendall_tau_mean",
                                                 "admitted_oracle_U_positive_fraction") for s in ("mean", "spread_sd")]
    + [f"plan_pr_realized_minus_pred_{m}_raw_units" for m in ("mean", "mean_abs", "spread_sd", "spread_range")]
)

REPORT_METRICS = (REPORT_METRICS + SHADOW_METRICS + PLAN_REJECTION_METRICS + PROP2_PRIMARY_METRICS
                  + PROP2_SECONDARY_METRICS)

METRIC_GROUPS = {
    **{m: "B4 dual shadow" for m in SHADOW_METRICS},
    **{m: "plan rejection reason" for m in PLAN_REJECTION_METRICS},
    **{m: "Prop. 2 PRIMARY (scale-free)" for m in PROP2_PRIMARY_METRICS},
    **{m: "Prop. 2 secondary (raw, unit-mixed)" for m in PROP2_SECONDARY_METRICS},
    **{m: "Prop. 2 per robot" for m in PER_ROBOT_METRICS},
}


def metric_group(metric: str) -> str:
    if metric in METRIC_GROUPS:
        return METRIC_GROUPS[metric]
    if metric.startswith(PER_ROBOT_PREFIX):
        return "Prop. 2 per robot"
    if metric.startswith("plan_") and metric.endswith(RAW_UNITS_SUFFIX):
        return "Prop. 2 secondary (raw, unit-mixed)"
    return ""


def expand_metrics(metrics: list, rows: list, per_robot: bool = False) -> list:
    """``metrics`` plus every *_raw_units plan metric present in ``rows`` and, with
    ``per_robot``, the per-robot Prop. 2 metrics (fixed list + every plan_pr_* key)."""
    out = list(metrics)
    if per_robot:
        out += [m for m in PER_ROBOT_METRICS if m not in out]
    keys = sorted({k for r in rows for k in r})
    for k in keys:
        if k in out:
            continue
        if k.startswith("plan_") and k.endswith(RAW_UNITS_SUFFIX):
            out.append(k)
        elif per_robot and k.startswith(PER_ROBOT_PREFIX):
            out.append(k)
    return out


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
    Legacy variants (B1, B5, B4, B3) = ladder paper params unchanged (Section 7 reproduction).
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


def code_version(root: Path = _root) -> dict:
    """Git commit of the code that runs (user decision 2026-10-22: every raw result records
    it; analyses refuse to compare runs from different code).  ``git_dirty`` = tracked files
    differ from HEAD; ``git_diff_sha1`` = SHA-1 of ``git diff HEAD`` (empty string if clean),
    so two dirty runs count as the same code only when their uncommitted changes are equal."""
    import hashlib

    def _git(*a):
        return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=True).stdout
    try:
        commit = _git("rev-parse", "HEAD").strip()
        diff = _git("diff", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": "unknown", "git_dirty": None, "git_diff_sha1": ""}
    return {"git_commit": commit, "git_dirty": bool(diff.strip()),
            "git_diff_sha1": hashlib.sha1(diff.encode("utf-8")).hexdigest() if diff.strip() else ""}


def code_key(row: dict) -> str:
    """Identity of the code that produced ``row`` (commit plus uncommitted-diff hash)."""
    c = str(row.get("git_commit") or "unknown")
    return c + (f"+dirty:{row['git_diff_sha1'][:12]}" if row.get("git_dirty") else "")


class MixedCommitsError(RuntimeError):
    """Raised when an analysis would compare runs produced by different code."""


def check_commits(rows: list, where: str = "", allow_mixed: bool = False) -> dict:
    """code_key -> number of rows; raise MixedCommitsError when more than one code version
    (or a run without a recorded commit) is present, unless ``allow_mixed``."""
    keys = {}
    for r in rows:
        keys[code_key(r)] = keys.get(code_key(r), 0) + 1
    if len(keys) > 1 and not allow_mixed:
        raise MixedCommitsError(f"{where}: runs from different code versions {json.dumps(keys)}; rerun every "
                                f"affected system on one commit (or pass --allow-mixed-commits)")
    return keys


def run_job(job: dict) -> dict:
    import DeterrentSystem as ds

    params = dict(job["params"])
    params["seed"] = int(job["seed"])
    if is_plan_job(params) and job.get("decision_log") and not params.get("plan_log_path"):
        params["plan_log_path"] = str(job["decision_log"])
    version = job.get("code_version") or code_version()   # recorded before the run starts
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
        **version,
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


DEFAULT_RETRIES = 1


def _log_tail(path: Path, n: int = 40) -> str:
    try:
        return "\n".join(Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def failure_record(job: dict, returncode, attempt: int, retries: int) -> dict:
    """One failed attempt: system, seed, return code, attempt, and the error (log tail)."""
    log = Path(job["raw_json"]).with_suffix(".log")
    return {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "system": job["system"], "seed": job["seed"],
            "study": job.get("study"), "cell": job.get("cell"), "returncode": returncode,
            "attempt": int(attempt), "retries": int(retries), "final": int(attempt) > int(retries),
            "log": str(log), "error_tail": _log_tail(log)}


def write_failure_report(rec: dict) -> Path:
    """Append ``rec`` to <raw dir>/failures.jsonl and rewrite <raw dir>/failures.md."""
    raw = Path(rec["log"]).parent
    raw.mkdir(parents=True, exist_ok=True)
    jl = raw / "failures.jsonl"
    with open(jl, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    recs = [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]
    lines = ["# Failed runs", "", "| Time | System | Seed | Attempt | Final | Return code | Log |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {r['time']} | {r['system']} | {r['seed']} | {r['attempt']} | {r['final']} | {r['returncode']} | "
              f"{r['log']} |" for r in recs]
    for r in recs:
        lines += ["", f"## {r['system']} seed {r['seed']} attempt {r['attempt']}", "", "```", r["error_tail"], "```"]
    (raw / "failures.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jl


def execute_jobs(jobs: list[dict], *, max_workers: int = 2, plan_concurrency: int = 2,
                 plan_stagger_s: float = 300.0, min_free_gb: float = MIN_FREE_GB,
                 poll_s: float = MEMORY_POLL_S, tag: str = "completion", check_s: float = 5.0,
                 overlap: bool = False, retries: int = DEFAULT_RETRIES) -> dict:
    """Run jobs in subprocesses with a memory check (>= min_free_gb, polled every poll_s)
    before every launch.  A failed job is retried up to ``retries`` times; every failed
    attempt is written to <raw dir>/failures.jsonl and failures.md with its log tail.

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
                        attempt = int(job.get("_attempt", 1))
                        rec = failure_record(job, proc.returncode, attempt, retries)
                        if attempt <= int(retries):
                            # retry: keep this attempt's log, requeue the job at the front
                            log = Path(job["raw_json"]).with_suffix(".log")
                            if log.exists():
                                os.replace(log, log.with_suffix(f".attempt{attempt}.log"))
                                rec["log"] = str(log.with_suffix(f".attempt{attempt}.log"))
                            job["_attempt"] = attempt + 1
                            pool["queue"].insert(0, job)
                            done -= 1
                            print(f"[{tag}] FAILED {job['system']} seed={job['seed']} rc={proc.returncode}; "
                                  f"retry {attempt}/{retries}", flush=True)
                        else:
                            failed.append(rec)
                            print(f"[{tag}] {done}/{total} FAILED {job['system']} seed={job['seed']} "
                                  f"rc={proc.returncode} after {attempt} attempt(s) (see log)", flush=True)
                        write_failure_report(rec)
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


class MissingSeedsError(RuntimeError):
    """Raised when a paired comparison lacks runs for expected seeds (user decision
    2026-10-22: the analysis errors by default; investigate and rerun, never drop silently)."""


def paired_detail(rows, ref, trt, metric, hab="hab_on", expected_seeds=None) -> dict:
    """Seed-aligned pairs of ``metric`` plus every seed that was dropped and why.

    Seeds considered: every seed with a run of ``ref`` or ``trt`` plus ``expected_seeds``.
    A seed is dropped when a run is missing ("no <variant> run") or a value is not finite
    ("<variant> value not finite").  Returns {"ref", "trt" (arrays), "seeds" (used),
    "dropped": [{"seed", "reason"}]}.
    """
    a = {int(r["seed"]): _f(r.get(metric)) for r in rows
         if r["variant"] == ref and r["habituation_condition"] == hab}
    b = {int(r["seed"]): _f(r.get(metric)) for r in rows
         if r["variant"] == trt and r["habituation_condition"] == hab}
    seeds = sorted(set(a) | set(b) | {int(s) for s in (expected_seeds or [])})
    used, dropped = [], []
    for s in seeds:
        why = []
        for v, d in ((ref, a), (trt, b)):
            if s not in d:
                why.append(f"no {v} run")
            elif not math.isfinite(d[s]):
                why.append(f"{v} value not finite")
        if why:
            dropped.append({"seed": s, "reason": "; ".join(why)})
        else:
            used.append(s)
    return {"ref": np.array([a[s] for s in used]), "trt": np.array([b[s] for s in used]),
            "seeds": used, "dropped": dropped}


def paired(rows, ref, trt, metric, hab="hab_on"):
    """Return (ref_values, trt_values) aligned by seed (finite pairs only); the dropped
    seeds and their reasons are in paired_detail."""
    d = paired_detail(rows, ref, trt, metric, hab)
    return d["ref"], d["trt"]


def missing_runs(rows, variants, seeds, hab="hab_on") -> dict:
    """variant -> sorted expected seeds without a run (raw JSON)."""
    out = {}
    for v in variants:
        have = {int(r["seed"]) for r in rows if r["variant"] == v and r["habituation_condition"] == hab}
        miss = sorted(int(s) for s in seeds if int(s) not in have)
        if miss:
            out[v] = miss
    return out


def check_missing(rows, comparisons, seeds, hab="hab_on", allow_missing=False, where="") -> dict:
    """Missing runs of every variant of ``comparisons``; raise MissingSeedsError unless
    ``allow_missing`` (then the missing seeds are only reported)."""
    present = {r["variant"] for r in rows if r["habituation_condition"] == hab}
    variants = sorted({v for ref, trt, _ in comparisons for v in (ref, trt) if v in present})
    miss = missing_runs(rows, variants, seeds, hab) if seeds else {}
    if miss and not allow_missing:
        raise MissingSeedsError(f"{where} {hab}: missing runs {json.dumps(miss)}; investigate and rerun "
                                f"(or pass --allow-missing to report a partial analysis)")
    return miss


def _fmt_dropped(dropped: list) -> str:
    return "; ".join(f"{d['seed']}: {d['reason']}" for d in dropped)


def bootstrap_ci(diffs: np.ndarray, n_boot: int = 10000, seed: int = 12345):
    """Percentile 95% CI of the mean paired difference, resampling whole seed pairs."""
    if diffs.size < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, diffs.size, size=(n_boot, diffs.size))
    means = diffs[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


# Mission and service outcomes (used by the trade-off and the confirmatory family).
PRIMARY_METRICS = ("value_weighted_exposure", "reactive_miss_fraction")


def reports(rows, variant, metric, hab="hab_on") -> bool:
    """A system REPORTS a metric when at least one of its runs has a finite value (plan
    metrics of B4 or B5 systems, shadow metrics of plan systems, ... are not reported and
    are not compared)."""
    return any(r["variant"] == variant and r["habituation_condition"] == hab and math.isfinite(_f(r.get(metric)))
               for r in rows)


def analyze(rows: list[dict], outdir: Path | None = None, hab: str = "hab_on",
            comparisons=None, metrics=None, expected_seeds=None, allow_missing: bool = False,
            allow_mixed: bool = False) -> list[dict]:
    """Paired statistics of every comparison and metric (user decision 2026-10-22).

    * With ``expected_seeds``, a missing run of a compared variant raises
      MissingSeedsError unless ``allow_missing`` (then the seeds are listed).
    * A metric is compared when both systems report it (``reports``).  Then ANY non-finite
      value of a planned seed, in ANY metric, raises MissingSeedsError unless
      ``allow_missing`` (final user decision 2026-10-22); with the flag the seeds are dropped
      and listed with reasons (``dropped_seeds``).
    * Runs of the two compared variants must come from one code version (git commit and
      uncommitted diff), else MixedCommitsError unless ``allow_mixed``.
    Timeouts are an outcome (plan_timeout_rate), never a drop reason.
    """
    comparisons = comparisons or COMPARISONS
    if expected_seeds:
        check_missing(rows, comparisons, expected_seeds, hab, allow_missing)
    present = {r["variant"] for r in rows if r["habituation_condition"] == hab}
    metrics = expand_metrics(metrics or REPORT_METRICS, rows)
    out = []
    for ref, trt, label in comparisons:
        if ref not in present or trt not in present:
            continue
        check_commits([r for r in rows if r["variant"] in (ref, trt) and r["habituation_condition"] == hab],
                      f"{label} ({hab})", allow_mixed)
        for metric in metrics:
            if not (reports(rows, ref, metric, hab) and reports(rows, trt, metric, hab)):
                continue   # not reported by both systems (e.g. plan metrics of B4 variants)
            det = paired_detail(rows, ref, trt, metric, hab, expected_seeds)
            a, b = det["ref"], det["trt"]
            if det["dropped"] and not allow_missing:
                raise MissingSeedsError(f"{label} ({hab}) {metric}: dropped seeds {_fmt_dropped(det['dropped'])}; "
                                        f"investigate and rerun (or pass --allow-missing)")
            if a.size == 0:
                continue
            d = b - a
            lo, hi = bootstrap_ci(d)
            ref_mean = float(np.mean(a))
            pct = 100.0 * float(np.mean(d)) / ref_mean if ref_mean else float("nan")
            out.append({
                "comparison": label, "reference": ref, "treatment": trt,
                "habituation_condition": hab, "metric": metric, "group": metric_group(metric),
                "n": int(d.size),
                "ref_mean": ref_mean, "trt_mean": float(np.mean(b)),
                "mean_diff": float(np.mean(d)), "ci_lo": lo, "ci_hi": hi,
                # Percent effect = mean paired difference / reference mean x 100.
                "pct_of_ref": pct,
                "n_dropped": len(det["dropped"]), "dropped_seeds": _fmt_dropped(det["dropped"]),
            })
    return out


def analyze_did(rows: list[dict], cell_pair: tuple, ref_pair: tuple, label: str, hab: str = "hab_on",
                metrics=None, expected_seeds=None, allow_mixed: bool = False,
                allow_missing: bool = False) -> list[dict]:
    """Difference of paired differences, per seed:
    (cell_pair[1] - cell_pair[0]) - (ref_pair[1] - ref_pair[0]), e.g. (E_plan - B5_c) in a
    delay/drop cell minus (E_plan - B5_c) in the reference cell; bootstrap over seeds."""
    check_commits([r for r in rows if r["variant"] in (*cell_pair, *ref_pair) and r["habituation_condition"] == hab],
                  label, allow_mixed)
    out = []
    for metric in expand_metrics(metrics or REPORT_METRICS, rows):
        if not all(reports(rows, v, metric, hab) for v in (*cell_pair, *ref_pair)):
            continue
        dc = paired_detail(rows, cell_pair[0], cell_pair[1], metric, hab, expected_seeds)
        dr = paired_detail(rows, ref_pair[0], ref_pair[1], metric, hab, expected_seeds)
        c = dict(zip(dc["seeds"], dc["trt"] - dc["ref"]))
        r = dict(zip(dr["seeds"], dr["trt"] - dr["ref"]))
        seeds = [s for s in sorted(c) if s in r]
        if not seeds:
            continue
        dropped = [{"seed": x["seed"], "reason": "cell: " + x["reason"]} for x in dc["dropped"]]
        dropped += [{"seed": x["seed"], "reason": "reference: " + x["reason"]} for x in dr["dropped"]]
        dropped += [{"seed": s, "reason": "no reference pair"} for s in sorted(c) if s not in r]
        dropped += [{"seed": s, "reason": "no cell pair"} for s in sorted(r) if s not in c]
        if dropped and not allow_missing:
            raise MissingSeedsError(f"{label} ({hab}) {metric}: dropped seeds {_fmt_dropped(dropped)}; "
                                    f"investigate and rerun (or pass --allow-missing)")
        d = np.array([c[s] - r[s] for s in seeds])
        lo, hi = bootstrap_ci(d)
        rm = float(np.mean([r[s] for s in seeds]))
        out.append({
            "comparison": label, "reference": f"{ref_pair[1]} - {ref_pair[0]}",
            "treatment": f"{cell_pair[1]} - {cell_pair[0]}", "habituation_condition": hab,
            "metric": metric, "group": metric_group(metric), "n": int(d.size),
            "ref_mean": rm, "trt_mean": float(np.mean([c[s] for s in seeds])),
            "mean_diff": float(np.mean(d)), "ci_lo": lo, "ci_hi": hi,
            "pct_of_ref": float("nan"),   # a difference of differences has no natural base
            "n_dropped": len(dropped), "dropped_seeds": _fmt_dropped(sorted(dropped, key=lambda x: x["seed"])),
        })
    return out


# ---------------------------------------------------------------------------
# Exposure vs service trade-off (user decision 2026-10-22)
# ---------------------------------------------------------------------------
def tradeoff(rows: list[dict], hab: str = "hab_on", reference: str = "B5_c", variants=None,
             expected_seeds=None, allow_mixed: bool = False, allow_missing: bool = False) -> list[dict]:
    """One point per variant: mean exposure as % of the reference (100 + percent effect,
    percent effect = mean paired difference / reference mean x 100, CI = bootstrap CI of
    the mean paired difference on the same scale) against the mean paired reactive
    miss-fraction difference in percentage points (bootstrap 95% CI)."""
    present = sorted({r["variant"] for r in rows if r["habituation_condition"] == hab})
    if reference not in present:
        return []
    out = []
    for v in (variants or present):
        if v == reference or v not in present:
            continue
        check_commits([r for r in rows if r["variant"] in (reference, v) and r["habituation_condition"] == hab],
                      f"trade-off {v} vs {reference} ({hab})", allow_mixed)
        e = paired_detail(rows, reference, v, "value_weighted_exposure", hab, expected_seeds)
        m = paired_detail(rows, reference, v, "reactive_miss_fraction", hab, expected_seeds)
        if (e["dropped"] or m["dropped"]) and not allow_missing:
            raise MissingSeedsError(f"trade-off {v} vs {reference} ({hab}): dropped seeds "
                                    f"{_fmt_dropped(e['dropped'] + m['dropped'])} (or pass --allow-missing)")
        if e["ref"].size == 0 or m["ref"].size == 0:
            continue
        de = e["trt"] - e["ref"]
        ref_mean = float(np.mean(e["ref"]))
        elo, ehi = bootstrap_ci(de)
        dm = m["trt"] - m["ref"]
        mlo, mhi = bootstrap_ci(dm)
        pct = (lambda x: 100.0 + 100.0 * x / ref_mean if ref_mean else float("nan"))
        out.append({
            "reference": reference, "variant": v, "habituation_condition": hab,
            "n_exposure": int(de.size), "n_service": int(dm.size),
            "exposure_pct_of_ref": pct(float(np.mean(de))), "exposure_pct_ci_lo": pct(elo),
            "exposure_pct_ci_hi": pct(ehi),
            "miss_diff_pp": 100.0 * float(np.mean(dm)), "miss_diff_pp_ci_lo": 100.0 * mlo,
            "miss_diff_pp_ci_hi": 100.0 * mhi,
            "dropped_seeds": _fmt_dropped(e["dropped"] + [x for x in m["dropped"]
                                                          if x not in e["dropped"]]),
        })
    return out


def write_tradeoff(points: dict, out_dir: Path, stem: str = "tradeoff", title: str = "") -> list[dict]:
    """``points``: panel name (load or cell) -> tradeoff() rows.  Writes <stem>.csv, <stem>.md
    and <stem>.png (one panel per load; x = exposure % of B5_c, y = miss-fraction
    difference in pp; error bars = 95% bootstrap CIs; reference at (100, 0))."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    flat = [dict(p, panel=name) for name, pts in points.items() for p in pts]
    if not flat:
        return flat
    _write_csv(flat, out_dir / f"{stem}.csv")
    lines = [f"# Exposure vs service trade-off {title}".rstrip(), "",
             "Exposure as % of B5_c (100 + mean paired difference / B5_c mean x 100) and paired",
             "reactive miss-fraction difference (pp), 95% percentile bootstrap CIs over seed pairs.", "",
             "| Panel | Variant | n | Exposure % of B5_c | 95% CI | Miss diff (pp) | 95% CI | Dropped seeds |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for p in flat:
        lines.append(f"| {p['panel']} | {p['variant']} | {p['n_exposure']} | {p['exposure_pct_of_ref']:.1f} | "
                     f"[{p['exposure_pct_ci_lo']:.1f}, {p['exposure_pct_ci_hi']:.1f}] | {p['miss_diff_pp']:+.2f} | "
                     f"[{p['miss_diff_pp_ci_lo']:+.2f}, {p['miss_diff_pp_ci_hi']:+.2f}] | {p['dropped_seeds']} |")
    (out_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return flat
    names = [n for n, pts in points.items() if pts]
    fig, axes = plt.subplots(1, len(names), figsize=(4.6 * len(names), 4.2), squeeze=False)
    ink, muted = "#1f2937", "#9ca3af"
    for ax, name in zip(axes[0], names):
        ax.axvline(100.0, color=muted, lw=1, zorder=0)
        ax.axhline(0.0, color=muted, lw=1, zorder=0)
        ax.axhline(100.0 * NONINFERIORITY_MARGIN_PP, color=muted, lw=1, ls="--", zorder=0)
        for p in points[name]:
            x, y = p["exposure_pct_of_ref"], p["miss_diff_pp"]
            ax.errorbar(x, y, xerr=[[x - p["exposure_pct_ci_lo"]], [p["exposure_pct_ci_hi"] - x]],
                        yerr=[[y - p["miss_diff_pp_ci_lo"]], [p["miss_diff_pp_ci_hi"] - y]],
                        fmt="o", ms=6, color="#2563eb", ecolor="#93c5fd", elinewidth=1.5, capsize=0)
            ax.annotate(p["variant"], (x, y), textcoords="offset points", xytext=(5, 5), fontsize=8, color=ink)
        ax.set_title(str(name), fontsize=10, color=ink)
        ax.set_xlabel("Exposure, % of B5_c (lower is better)", fontsize=9, color=ink)
        ax.set_ylabel("Miss fraction minus B5_c (pp)", fontsize=9, color=ink)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(labelsize=8, colors=ink)
    if title:
        fig.suptitle(title, fontsize=11, color=ink)
    fig.tight_layout()
    fig.savefig(out_dir / f"{stem}.png", dpi=150)
    plt.close(fig)
    return flat


def stats_table(stats_rows: list) -> list:
    """Markdown table of analyze() rows, with the group and the dropped seeds of each pair."""
    lines = ["| Comparison | Metric | Group | n | Ref mean | Diff | 95% CI | % of ref | Dropped seeds |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in stats_rows:
        lines.append(
            f"| {s['comparison']} | {s['metric']} | {s.get('group', '')} | {s['n']} | {s['ref_mean']:.4g} | "
            f"{s['mean_diff']:+.4g} | [{s['ci_lo']:+.4g}, {s['ci_hi']:+.4g}] | {s['pct_of_ref']:+.2f}% | "
            f"{s.get('dropped_seeds', '')} |")
    return lines


def write_report(rows, outdir: Path, meta: dict, comparisons=None, expected_seeds=None,
                 allow_missing: bool = False, allow_mixed: bool = False) -> list[dict]:
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
        if not any(r["habituation_condition"] == hab for r in rows):
            continue
        miss = check_missing(rows, comparisons or COMPARISONS, expected_seeds, hab, allow_missing,
                             str(outdir))
        stats_rows = analyze(rows, outdir, hab, comparisons, expected_seeds=expected_seeds,
                             allow_missing=allow_missing, allow_mixed=allow_mixed)
        all_stats += stats_rows
        if not stats_rows:
            continue
        lines += [f"## {hab}", ""]
        if miss:
            lines += [f"MISSING RUNS (partial analysis, --allow-missing): {json.dumps(miss)}", ""]
        lines += stats_table(stats_rows)
        lines.append("")
        write_tradeoff({f"mu={meta.get('mu')}": tradeoff(rows, hab, expected_seeds=expected_seeds,
                                                               allow_mixed=allow_mixed,
                                                               allow_missing=allow_missing)}, outdir,
                       f"tradeoff_{hab}", f"({hab})")
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
    p.add_argument("--allow-missing", action="store_true",
                   help="report a partial analysis instead of failing on missing runs (seeds listed)")
    p.add_argument("--allow-mixed-commits", action="store_true",
                   help="compare runs from different code versions (default: refuse)")
    p.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="retries of a failed run")
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
                     overlap=args.overlap, retries=args.retries)

    rows = load_rows(outdir)
    _write_csv(flat_rows(rows), outdir / "per_run_metrics.csv")
    t_end = args.t_end if args.t_end is not None else 1800.0
    meta = {"config": "paper", "ladder_argv": PAPER_LADDER_ARGV, "plan_env": PLAN_ENV, "mu": args.mu,
            "seeds": f"{seeds[0]}-{seeds[-1]}" if seeds else "", "t_end": t_end, "extra": extra,
            "timed_recovery": timed_recovery or load_timed_recovery(), "elapsed_s": time.time() - started,
            "noninferiority_margin_pp": NONINFERIORITY_MARGIN_PP}
    (outdir / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    write_report(rows, outdir, meta, expected_seeds=seeds, allow_missing=args.allow_missing,
                 allow_mixed=args.allow_mixed_commits)
    print(f"[completion] wrote {outdir}", flush=True)


if __name__ == "__main__":
    main()
