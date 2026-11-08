"""
unit_threshold_matching.py -- quantile matching of the unit-dependent thresholds after the
legacy-estimator unit fix (user decisions 2026-10-28 E).

Two sides, same systems, loads and dev seeds:
  old  = PLAN_ENV variant with legacy_stamp_units="density", the old estimator constants
         (frozen calibration C001) and the old thresholds (for A this is A_legacy_units);
  new  = PLAN_ENV variant with legacy_stamp_units="mass_per_cell", the refitted estimator
         constants (--constants: experiments/refit_sestpp_new_units.py refit_result.json)
         and the matched values of the previous iteration (--overrides: output of `map`).
Rule (as experiments/consistent_threshold_mapping.py): for every threshold T,
    q = F_old(T) at the point of comparison,  T_new = F_new^{-1}(q),
with the same tie and positivity rules, iterated (recollect the new side with the matched
values) until every value moves by less than 1%, at most 5 iterations.
Scope: systems B1_c, B5_c, A, B pooled (or the subset that uses T); loads 2e-5, 1e-4, 4e-4;
dev seeds 200-209 only.

Statistics (user decisions 2026-10-28, E1-E10):
  1 risk: threshold 0.35 kept; risk_scale matched on the share of risk-gate checks with
    excess below the cut (scale = cut / -ln(1 - 0.35)); busy override 0.20 kept, its
    achieved rate reported;
  2 min_hotspot_score: share of patrol candidates plus border seeds rejected;
  3 task_refresh_min_score: share of patrol refresh checks that prune;
  4 costs: ONE w_eta PER CUE (formation 1.0, laser 1.5, biosonic 1.2), each matched on the
    share of that cue's deterrence candidates (every evaluated (location, cue) pair in the
    B5-family generation) with benefit > cost; patrol_cost_weight (= the B5 copy's
    cost_w_eta) on the share of patrol candidates with benefit > cost;
    deterring_cost_multiplier stays 1.0;
  5 score_margin: share of preventive-vs-patrol checks with best_det - best_patrol <= margin,
    POOLED over the B5 and B4 families (per-family shares reported);
  6 w_task_value: ALWAYS matched on the assignment-change share (primary robot with the term
    versus without it); if the old share is 0, retain the paper value when it also
    produces no changes, otherwise use the closest no-change value on the factor-2
    grid. A zero-change statistic does not identify a largest meaningful weight;
  7 stl_E_star: share of nominal cell-exposure samples above E_star;
  8 stl_kernel_self: binding share, the share of signal steps where kernel_self * supp >=
    e_nom (the cap of min(e_nom, kernel_self * supp) binds);
  9 busy fallback 0.95 / 1e6 / 1.25 s KEPT; passes counted (expected never to fire);
 10 E_high / E_low: experiments/calibrate_timed_recovery.py rerun after the matching.

Instrumentation (read-only, in this script): consistent_threshold_mapping's line tracer and
wrappers (hotspot score, risk gate, busy override, score margin, STL signals, busy
fallback), plus line hooks on the cue loop and the patrol loop of periodic_patrolling
(benefit / unit-weight cost), a wrapper of DeterrentSystem.excess_at (only caller:
_task_intensity_score, compared with task_refresh_min_score), a wrapper of
TaskAssigner.assign_task (re-run on the w_task_value grid) and one on the busy-fallback
gate result.

Usage:
  py -3.10 -m experiments.unit_threshold_matching collect --side old --tag old --workers 8
  py -3.10 -m experiments.unit_threshold_matching collect --side new --tag new_it0 --constants R.json --workers 8
  py -3.10 -m experiments.unit_threshold_matching map --old-tag old --new-tag new_it0 --out it1.json
  py -3.10 -m experiments.unit_threshold_matching collect --side new --tag new_it1 --constants R.json --overrides it1.json
  ...
  py -3.10 -m experiments.unit_threshold_matching loop --constants R.json --workers 8   (all of it)
Every launch requires the 4 GB reserve plus the 0.5 GB estimated job peak, with at
most 8 workers (poll 300 s).
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("DETERRENT_TELEMETRY", "0")
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from experiments import consistent_threshold_mapping as ctm

DEV_SEEDS = tuple(range(200, 210))
MUS = (2e-5, 1e-4, 4e-4)
SYSTEMS = ("B1_c", "B5_c", "A", "B")
B5_FAMILY = ("B1_c", "B5_c")
STL_FAMILY = ("A", "B")
OUT_ROOT = _root / "results" / "unit_threshold_matching"
# User decision 2026-10-29: launch a job only while available memory >= 4 GB + the job's
# measured peak (JOB_PEAK_GB); never more than 8 workers.
MIN_FREE_GB = 4.0
JOB_PEAK_GB = 0.5
POLL_S = 300.0
RISK_THRESHOLD = 0.35
BUSY_RISK_OVERRIDE = 0.20
CUES = {"formation": 1.0, "laser": 1.5, "biosonic": 1.2}   # old per-cue w_eta (fixed_cost 0)
OLD_W_TASK_VALUE = 0.20
W_GRID = OLD_W_TASK_VALUE * 2.0 ** np.arange(-60, 61)     # w_task_value search grid (both directions)
MAX_ITERATIONS = 5
REL_TOL = 0.01

# Old values; op: q = share with  quantity <op> threshold  ("lt" <, "le" <=).
OLD_THRESHOLDS = {
    "min_hotspot_score": {"value": 1.0e-4, "op": "lt", "systems": SYSTEMS},
    "risk_field_cut": {"value": -1.0e-4 * math.log(1.0 - RISK_THRESHOLD), "op": "lt", "systems": SYSTEMS},
    "task_refresh_min_score": {"value": 1.0e-4, "op": "lt", "systems": SYSTEMS},
    "model_deterring_score_margin": {"value": 0.10, "op": "le", "systems": SYSTEMS},
    "stl_E_star": {"value": 5.0, "op": "le_star", "systems": STL_FAMILY},
    "stl_kernel_self": {"value": 1.0, "op": "le", "systems": STL_FAMILY},
    # benefit / (cost / w): benefit > cost  <=>  ratio > w ; q = share NOT passing (<= w)
    **{f"w_eta__{cue}": {"value": w, "op": "le", "systems": B5_FAMILY} for cue, w in CUES.items()},
    "patrol_cost_weight": {"value": 1.0, "op": "le", "systems": B5_FAMILY},
}
POSITIVE = ("risk_field_cut", "patrol_cost_weight") + tuple(f"w_eta__{c}" for c in CUES)
POSITIVE_FLOOR = {"risk_field_cut": 1.0e-12 * -math.log(1.0 - RISK_THRESHOLD)}
COST_FLOOR = 1.0e-300
KEPT = {"model_deterring_risk_threshold": RISK_THRESHOLD,
        "model_deterring_busy_risk_override": BUSY_RISK_OVERRIDE,
        "model_deterring_busy_fallback_p_event_min": 0.95,
        "model_deterring_busy_fallback_deltaJ_per_cost_min": 1.0e6,
        "model_deterring_busy_fallback_eta_s_max": 1.25,
        "deterring_cost_multiplier": 1.0}
# matched name -> simulator argument (also written into the job's planner profile)
PARAM_KEY = {
    "min_hotspot_score": "min_hotspot_score",
    "model_deterring_risk_scale": "model_deterring_risk_scale",
    "task_refresh_min_score": "task_refresh_min_score",
    "model_deterring_score_margin": "model_deterring_score_margin",
    "stl_E_star": "stl_E_star",
    "stl_kernel_self": "stl_kernel_self",
    "patrol_cost_weight": "patrol_cost_weight",
    "w_task_value": "assigner_w_task_value",
}
CONSTANT_KEYS = {  # refit_result.json deployed_constants -> proposed_model_overrides key
    "model_sigma": "sigma", "model_omega": "omega", "model_omega_inhib": "omega_inhib",
    "model_alpha_in": "alpha_in", "model_alpha_cross": "alpha_cross", "model_alpha_inhib": "alpha_inhib",
    "model_mu_base": "mu_base", "model_bg_ema": "bg_ema",
    "model_feedback_sigma_scale": "model_feedback_sigma_scale",
    "model_feedback_omega_scale": "model_feedback_omega_scale",
}


# ---------------------------------------------------------------------------
# Extra instrumentation (worker processes)
# ---------------------------------------------------------------------------
class _Assign:
    def __init__(self):
        self.rows: list[np.ndarray] = []    # per decision: changed(w_j) vs w = 0, j over W_GRID


ASSIGN = _Assign()
_EXTRA = False


def install_extra_instrumentation():
    global _EXTRA
    if _EXTRA:
        return
    _EXTRA = True
    import inspect
    import DeterrentSystem as ds
    import TaskGenerator as tg

    # 3. refresh: the only DeterrentSystem caller of excess_at is _task_intensity_score
    orig_excess = ds.excess_at

    def excess_at(model, iy, ix):
        v = orig_excess(model, iy, ix)
        ctm.REC.add("task_refresh_min_score", v)
        return v

    ds.excess_at = excess_at

    # 6. w_task_value: primary robot on the grid of w versus w = 0 (same state, no side effects)
    orig_assign = tg.TaskAssigner.assign_task

    def assign_task(self, task, eligible_ids=None):
        out = orig_assign(self, task, eligible_ids)
        if out is None:
            return out
        w_now = self.w.get("w_task_value", 0.0)
        try:
            self.w["w_task_value"] = 0.0
            base = orig_assign(self, task, eligible_ids)["primary"]
            changed = np.zeros(W_GRID.size, dtype=np.uint8)
            for j, w in enumerate(W_GRID):
                self.w["w_task_value"] = float(w)
                changed[j] = orig_assign(self, task, eligible_ids)["primary"] != base
            self.w["w_task_value"] = 0.0
            ctm.REC.add("info_assign_change_at_current_w",
                        float(out["primary"] != base) if float(w_now) != 0.0 else 0.0)
        finally:
            self.w["w_task_value"] = w_now
        ASSIGN.rows.append(changed)
        return out

    tg.TaskAssigner.assign_task = assign_task

    # 9. busy fallback: count passes (values kept)
    orig_bf = ds.passes_busy_fallback_quality

    def passes_busy_fallback_quality(**kw):
        ok = orig_bf(**kw)
        ctm.REC.add("info_busy_fallback_pass", float(bool(ok)))
        return ok

    ds.passes_busy_fallback_quality = passes_busy_fallback_quality

    # 4. cue and patrol candidates: line hooks dispatched by consistent_threshold_mapping's tracer
    func = ctm.ORIGINAL["periodic_patrolling"]
    src, start = inspect.getsourcelines(func)
    code_pp = func.__code__

    def h_cue(loc):
        m = loc["mode_metrics"]
        if "predictive_stl_U" in m:      # STL valuation (A, B): the cost is not subtracted
            return
        mode = str(loc["mode"])
        w = float(dict(loc["deterring_modes"].get(mode, {})).get("w_eta", loc["cost_w_eta"]))
        cost = float(m["cost_eta"])
        if cost > 0.0 and w > 0.0:
            ctm.REC.add(f"w_eta__{mode}", float(m["predicted_deltaJ"]) / (cost / w))

    def h_patrol(loc):
        m = loc["patrol_metrics"]
        w = float(loc["cost_w_eta"])
        cost = float(m["cost_eta"])
        if cost > 0.0 and w > 0.0:
            ctm.REC.add("patrol_cost_weight", float(m["benefit"]) / (cost / w))

    ctm.EXTRA_LINE_HOOKS[(code_pp, ctm._find_line(src, start, 'mode_cost = float(mode_metrics["cost_eta"])'))] = h_cue
    ctm.EXTRA_LINE_HOOKS[(code_pp, ctm._find_line(src, start, 'utility = float(patrol_metrics["utility"])'))] = h_patrol


def _install_all():
    ctm.install_instrumentation()
    install_extra_instrumentation()


# ---------------------------------------------------------------------------
# Parameters of a side
# ---------------------------------------------------------------------------
def build_side_params(system: str, mu: float, side: str, constants: dict, overrides: dict) -> dict:
    import experiments.run_plan_completion as rpc

    saved = rpc.NEW_UNITS_OVERRIDES
    try:
        rpc.NEW_UNITS_OVERRIDES = {}
        params = rpc.build_params(system, True, float(mu), None)
    finally:
        rpc.NEW_UNITS_OVERRIDES = saved
    if side == "old":
        params["legacy_stamp_units"] = "density"
        return params
    params["legacy_stamp_units"] = "mass_per_cell"
    if constants:
        params["proposed_model_overrides"] = dict(constants)
    for name, value in overrides.items():
        if name in PARAM_KEY:
            params[PARAM_KEY[name]] = float(value)
    if "risk_field_cut" in overrides and "model_deterring_risk_scale" not in overrides:
        params["model_deterring_risk_scale"] = float(overrides["risk_field_cut"]) / (-math.log(1.0 - RISK_THRESHOLD))
    cue_w = {k.split("__", 1)[1]: float(v) for k, v in overrides.items() if k.startswith("w_eta__")}
    if cue_w:
        modes = copy.deepcopy(params["deterring_modes"])
        for cue, w in cue_w.items():
            modes[cue]["w_eta"] = w
        params["deterring_modes"] = modes
    return params


def side_profile_overlay(params: dict, side: str, overrides: dict) -> dict:
    """planner_profile_overrides of a job: every matched value that is also a profile key
    (profile values win over simulator arguments, e.g. score margin and w_task_value)."""
    if side != "new":
        return {}
    overlay = {PARAM_KEY[n]: params[PARAM_KEY[n]] for n in overrides if n in PARAM_KEY and PARAM_KEY[n] in params}
    if "model_deterring_risk_scale" in params and ("risk_field_cut" in overrides
                                                   or "model_deterring_risk_scale" in overrides):
        overlay["model_deterring_risk_scale"] = params["model_deterring_risk_scale"]
    return overlay


def load_constants(path: str | None) -> dict:
    if not path:
        return {}
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    dep = d.get("deployed_constants", d)
    return {CONSTANT_KEYS[k]: float(v) for k, v in dep.items() if k in CONSTANT_KEYS}


def run_job(job: dict) -> dict:
    import DeterrentSystem as ds

    _install_all()
    ctm.REC.samples = {}
    ctm.REC.taskgen_diag = {}
    ASSIGN.rows = []
    overrides = dict(job.get("overrides") or {})
    ctm.REC.overrides = {}
    # A and B score same-state shadows; record the primary valuation only
    ctm.REC.record_shadow_free = job["system"] not in STL_FAMILY
    params = build_side_params(job["system"], job["mu"], job["side"], job.get("constants") or {}, overrides)
    overlay = side_profile_overlay(params, job["side"], overrides)
    if overlay:
        params["planner_profile_overrides"] = {**dict(params.get("planner_profile_overrides") or {}), **overlay}
    params["seed"] = int(job["seed"])
    if job.get("t_end") is not None:  # smoke only
        params["T_end"] = float(job["t_end"])
    started = time.time()
    last = None
    for frame in ds.run_simulation_frames_persistent(**params):
        last = frame
    metrics = (last or {}).get("metrics_compact") or (last or {}).get("metrics") or {}
    numeric = {k: float(v) for k, v in metrics.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))}
    out = {"system": job["system"], "mu": float(job["mu"]), "seed": int(job["seed"]), "side": job["side"],
           **(job.get("code_version") or {}),
           "overrides": overrides, "constants": job.get("constants") or {},
           "legacy_stamp_units": params["legacy_stamp_units"], "elapsed_s": time.time() - started,
           "metrics": numeric, "taskgen_diag": {k: float(v) for k, v in ctm.REC.taskgen_diag.items()
                                                if isinstance(v, (int, float)) and math.isfinite(float(v))}}
    path = Path(job["out_dir"]) / f"{job['system']}_{job['mu']:.0e}_{job['seed']}"
    arrays = {k: np.asarray(v, dtype=np.float64) for k, v in ctm.REC.samples.items()}
    arrays["assign_change_grid"] = (np.stack(ASSIGN.rows) if ASSIGN.rows
                                    else np.zeros((0, W_GRID.size), dtype=np.uint8))
    np.savez_compressed(str(path) + ".npz", **arrays)
    with open(str(path) + ".json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    return {"system": job["system"], "mu": job["mu"], "seed": job["seed"], "elapsed_s": out["elapsed_s"]}


def _wait_memory():
    import psutil
    need = MIN_FREE_GB + JOB_PEAK_GB
    while psutil.virtual_memory().available / 1e9 < need:
        print(f"[mem] < {need} GB available; waiting {POLL_S:.0f} s", flush=True)
        time.sleep(POLL_S)


def collect(side: str, tag: str, constants: dict, overrides: dict, *, systems=SYSTEMS, mus=MUS,
            seeds=DEV_SEEDS, workers: int = 2, t_end=None) -> Path:
    out_dir = OUT_ROOT / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    if side == "old" and (overrides or constants):
        raise SystemExit("the old side runs the old constants and thresholds only")
    jobs = []
    for system in systems:
        for mu in mus:
            for seed in seeds:
                if int(seed) >= 300:
                    raise SystemExit("evaluation seeds (>= 300) must not be used for threshold matching")
                stem = out_dir / f"{system}_{float(mu):.0e}_{int(seed)}"
                if Path(str(stem) + ".json").exists():
                    continue
                jobs.append({"system": system, "mu": float(mu), "seed": int(seed), "side": side,
                             "overrides": overrides, "constants": constants, "out_dir": str(out_dir),
                             "t_end": t_end})
    from experiments.run_plan_completion import code_version
    version = code_version()   # commit, dirty flag, diff hash and machine (user 2026-10-28, 3b)
    for j in jobs:
        j["code_version"] = version
    (out_dir / "collect_meta.json").write_text(json.dumps({
        **version, "side": side, "overrides": overrides, "constants": constants, "systems": list(systems),
        "mus": list(mus), "seeds": list(seeds), "t_end": t_end}, indent=1), encoding="utf-8")
    print(f"{len(jobs)} jobs -> {out_dir}", flush=True)
    t0 = time.time()
    workers = min(int(workers), 8)
    from concurrent.futures import FIRST_COMPLETED, wait
    with ProcessPoolExecutor(max_workers=workers) as ex:
        pending, todo, done_n = set(), list(jobs), 0
        while todo or pending:
            # launch only while a slot is free and memory allows (checked at each launch)
            while todo and len(pending) < workers:
                _wait_memory()
                pending.add(ex.submit(run_job, todo.pop(0)))
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                r = fut.result()
                done_n += 1
                print(f"[{done_n}/{len(jobs)}] {r['system']} mu={r['mu']:.0e} seed={r['seed']} "
                      f"{r['elapsed_s']:.0f}s (wall {time.time() - t0:.0f}s)", flush=True)
    return out_dir


def _read_overrides(path) -> dict:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: float(v) for k, v in dict(payload.get("mapped", payload)).items()
            if v is not None and math.isfinite(float(v))}


def cmd_collect(args) -> None:
    collect(args.side, args.tag, load_constants(args.constants), _read_overrides(args.overrides),
            systems=args.systems, mus=args.mus, seeds=args.seeds, workers=args.workers, t_end=args.t_end)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def _system_of(npz: Path) -> str:
    return npz.name.rsplit("_", 2)[0]


def load_samples(tag: str, key: str, systems) -> np.ndarray:
    parts = []
    for npz in sorted((OUT_ROOT / tag).glob("*.npz")):
        if _system_of(npz) not in systems:
            continue
        with np.load(npz) as data:
            if key in data.files:
                parts.append(np.asarray(data[key], dtype=float).ravel())
    return np.concatenate(parts) if parts else np.zeros(0)


def load_assign_grid(tag: str, systems) -> np.ndarray:
    parts = []
    for npz in sorted((OUT_ROOT / tag).glob("*.npz")):
        if _system_of(npz) not in systems:
            continue
        with np.load(npz) as data:
            if "assign_change_grid" in data.files and data["assign_change_grid"].size:
                parts.append(np.asarray(data["assign_change_grid"], dtype=np.uint8))
    return np.concatenate(parts) if parts else np.zeros((0, W_GRID.size), dtype=np.uint8)


def match_w_task_value(old_grid: np.ndarray, new_grid: np.ndarray, old_current: np.ndarray) -> dict:
    """Assignment-change share with the term versus without it (decision 6)."""
    j_old = int(np.argmin(np.abs(W_GRID - OLD_W_TASK_VALUE)))
    q = float(old_grid[:, j_old].mean()) if old_grid.size else float("nan")
    share_new = new_grid.mean(axis=0) if new_grid.size else np.full(W_GRID.size, np.nan)
    entry = {"old_value": OLD_W_TASK_VALUE, "q": q, "n_old": int(old_grid.shape[0]),
             "n_new": int(new_grid.shape[0]),
             "old_share_at_current_w_check": float(old_current.mean()) if old_current.size else float("nan"),
             "grid": [float(w) for w in W_GRID], "new_change_share_on_grid": [float(s) for s in share_new]}
    if not math.isfinite(q) or not new_grid.size:
        entry["matched_value"] = float("nan")
        return entry
    if q == 0.0:
        never = [j for j in range(W_GRID.size) if share_new[j] == 0.0]
        first_change = next((j for j in range(W_GRID.size) if share_new[j] > 0.0), None)
        chosen = min(never, key=lambda j: abs(j - j_old)) if never else None
        entry["identified"] = False
        entry["representation"] = ('old share 0: keep paper weight when compatible; otherwise '
                                   'choose closest zero-change grid value; the weight is not identified')
        entry["first_changing_value"] = None if first_change is None else float(W_GRID[first_change])
        entry["grid_top_reached"] = first_change is None
        entry["matched_value"] = float(W_GRID[chosen]) if chosen is not None else float("nan")
        entry["achieved_share"] = float(share_new[chosen]) if chosen is not None else float("nan")
        entry["values_never_changing"] = len(never)
        return entry
    j = int(np.argmin(np.abs(share_new - q)))
    entry.update(matched_value=float(W_GRID[j]), achieved_share=float(share_new[j]),
                 representation="grid value with the nearest change share")
    return entry


def cmd_map(args) -> dict:
    prev = {}
    if args.previous:
        prev = json.loads(Path(args.previous).read_text(encoding="utf-8")).get("mapped", {})
    from experiments.run_plan_completion import code_version
    report = {**code_version(), "old_tag": args.old_tag, "new_tag": args.new_tag, "seeds": list(DEV_SEEDS), "mus": list(MUS),
              "systems": list(SYSTEMS), "kept": KEPT, "thresholds": {}, "mapped": {}}
    for name, spec in OLD_THRESHOLDS.items():
        systems = spec["systems"]
        old = load_samples(args.old_tag, name, systems)
        new = load_samples(args.new_tag, name, systems)
        q = ctm.ecdf_below(old, spec["value"], spec["op"])
        q_new_at_old = ctm.ecdf_below(new, spec["value"], spec["op"])
        if q in (0.0, 1.0) and q_new_at_old == q:
            mapped = float(spec["value"])
        else:
            mapped = ctm.inverse_quantile(new, q, spec["op"])
        entry = {"old_value": spec["value"], "op": spec["op"], "systems": list(systems), "q": q,
                 "matched_value": mapped, "q_new_at_old_value": q_new_at_old, "n_old": int(old.size),
                 "n_new": int(new.size),
                 "q_old_by_system": {s: ctm.ecdf_below(load_samples(args.old_tag, name, (s,)), spec["value"],
                                                       spec["op"]) for s in systems}}
        if name in POSITIVE and math.isfinite(mapped) and mapped <= 0.0:
            floor = POSITIVE_FLOOR.get(name, COST_FLOOR)
            entry.update(unconstrained_matched_value=mapped, representation="limit 0+ (matched value <= 0)")
            mapped = floor
            entry["matched_value"] = mapped
        entry["q_check_new"] = ctm.ecdf_below(new, mapped, spec["op"])
        entry["q_new_by_system"] = {s: ctm.ecdf_below(load_samples(args.new_tag, name, (s,)), mapped, spec["op"])
                                    for s in systems}
        if name == "model_deterring_score_margin":
            for fam, mem in (("B5_family", B5_FAMILY), ("B4_family", STL_FAMILY)):
                entry[f"q_old_{fam}"] = ctm.ecdf_below(load_samples(args.old_tag, name, mem), spec["value"], spec["op"])
                entry[f"q_new_{fam}"] = ctm.ecdf_below(load_samples(args.new_tag, name, mem), mapped, spec["op"])
        report["thresholds"][name] = entry
        report["mapped"][name] = mapped
    cut = report["mapped"]["risk_field_cut"]
    report["mapped"]["model_deterring_risk_scale"] = cut / (-math.log(1.0 - RISK_THRESHOLD))
    # busy override 0.20 kept: its rate under the matched scale (ctm records the busy field)
    scale_new = report["mapped"]["model_deterring_risk_scale"]
    report["busy_risk_override"] = {
        "kept_value": BUSY_RISK_OVERRIDE,
        "share_below_old": ctm.ecdf_below(load_samples(args.old_tag, "busy_risk_field", SYSTEMS),
                                          -1e-4 * math.log(1 - BUSY_RISK_OVERRIDE), "lt"),
        "share_below_new": ctm.ecdf_below(load_samples(args.new_tag, "busy_risk_field", SYSTEMS),
                                          -scale_new * math.log(1 - BUSY_RISK_OVERRIDE), "lt")}
    w = match_w_task_value(load_assign_grid(args.old_tag, SYSTEMS), load_assign_grid(args.new_tag, SYSTEMS),
                           load_samples(args.old_tag, "info_assign_change_at_current_w", SYSTEMS))
    report["thresholds"]["w_task_value"] = w
    report["mapped"]["w_task_value"] = w["matched_value"]
    report["busy_fallback"] = {
        side: {"checks": int(load_samples(tag, "info_busy_fallback_pass", SYSTEMS).size),
               "passes": int(load_samples(tag, "info_busy_fallback_pass", SYSTEMS).sum())}
        for side, tag in (("old", args.old_tag), ("new", args.new_tag))}
    for name, e in report["thresholds"].items():
        if name in prev and prev[name] is not None and math.isfinite(prev[name]) and math.isfinite(
                report["mapped"][name]):
            a, b = float(prev[name]), float(report["mapped"][name])
            e["rel_change_vs_previous"] = 0.0 if a == b else abs(b - a) / max(abs(a), abs(b))
    changes = [e.get("rel_change_vs_previous") for e in report["thresholds"].values()]
    report["converged_1pct"] = bool(prev) and all(c is not None and c < REL_TOL for c in changes)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    for name, e in report["thresholds"].items():
        print(f"{name:32s} old={e.get('old_value')} q={e.get('q')} matched={e.get('matched_value')} "
              f"achieved={e.get('q_check_new', e.get('achieved_share'))} n=({e.get('n_old')},{e.get('n_new')}) "
              f"rel_change={e.get('rel_change_vs_previous')}", flush=True)
    print("busy fallback:", report["busy_fallback"], "busy override:", report["busy_risk_override"], flush=True)
    print("converged (<1%):", report["converged_1pct"], flush=True)
    return report


def cmd_loop(args) -> None:
    """Old side once, then new-side iterations until < 1% change (at most 5 iterations)."""
    constants = load_constants(args.constants)
    kw = dict(systems=args.systems, mus=args.mus, seeds=args.seeds, workers=args.workers, t_end=args.t_end)
    collect("old", args.prefix + "old", {}, {}, **kw)
    overrides: dict = {}
    prev_path = None
    for it in range(0, MAX_ITERATIONS + 1):
        tag = f"{args.prefix}new_it{it}"
        collect("new", tag, constants, overrides, **kw)
        out = OUT_ROOT / f"{args.prefix}map_it{it + 1}.json"
        rep = cmd_map(argparse.Namespace(old_tag=args.prefix + "old", new_tag=tag, previous=prev_path, out=str(out)))
        overrides = {k: float(v) for k, v in rep["mapped"].items() if v is not None and math.isfinite(float(v))}
        prev_path = str(out)
        if rep["converged_1pct"]:
            print(f"converged after map_it{it + 1}", flush=True)
            break
        if it + 1 >= MAX_ITERATIONS:
            print(f"stopped at the iteration limit ({MAX_ITERATIONS}) without < 1% convergence", flush=True)
            break


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--side", choices=("old", "new"), required=True)
    c.add_argument("--tag", required=True)
    c.add_argument("--constants", default=None, help="refit_result.json (new side)")
    c.add_argument("--overrides", default=None, help="map output of the previous iteration (new side)")
    m = sub.add_parser("map")
    m.add_argument("--old-tag", required=True)
    m.add_argument("--new-tag", required=True)
    m.add_argument("--previous", default=None)
    m.add_argument("--out", required=True)
    lp = sub.add_parser("loop")
    lp.add_argument("--constants", required=True)
    lp.add_argument("--prefix", default="")
    for p in (c, lp):
        p.add_argument("--systems", nargs="+", default=list(SYSTEMS))
        p.add_argument("--mus", nargs="+", type=float, default=list(MUS))
        p.add_argument("--seeds", nargs="+", type=int, default=list(DEV_SEEDS))
        p.add_argument("--workers", type=int, default=2)
        p.add_argument("--t-end", type=float, default=None, help="smoke tests only")
    args = ap.parse_args()
    {"collect": cmd_collect, "map": cmd_map, "loop": cmd_loop}[args.cmd](args)


if __name__ == "__main__":
    main()
