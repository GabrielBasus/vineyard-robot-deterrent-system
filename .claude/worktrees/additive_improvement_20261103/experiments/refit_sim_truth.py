"""
refit_sim_truth.py -- PHASE 1 (PROVISIONAL) refit of the legacy SESTPP estimator constants
under the unit fix, against the EVALUATION SIMULATOR (user decisions 2026-10-28, audit
round 2 and the phase-1 decisions D-a .. D-d).

Phase 1 = open loop, record once and replay offline:
  * RECORD (D-a): for every load (2e-5, 1e-4, 4e-4) and dev seed (200-209), one 1800 s run of
    B5_c (PLAN_ENV, legacy_stamp_units="mass_per_cell") with the EQUIVALENT-START constants
    (calibration C001 with alpha_in and alpha_inhib x dx*dy, i.e. the old estimator exactly)
    and the old thresholds. The optional --recording-start paper instead uses unchanged
    ACC numeric constants in a separate recordings_paper directory. Every call that mutates
    a robot's estimator is logged in order
    (advance_time, add_local_event, add_cross_event, add_intervention_event), with a marker
    per simulator step, the zone-owner grid whenever it changes (scenario_rollout's
    _zone_owner_grid, as the planner assembles the fleet field) and the DETECTED events.
  * SCORED EVENTS (user decision 2026-10-29, replacing D-d): ALL accepted truth bird events
    (the simulator's truth_events of the scored run), as the original calibration scored
    all harness truth events.  DIAGNOSTIC only (--target detected): the detected events, a
    truth event passed to the zone owner's Robot.ingest_detection (owner in range and the
    detection draw passed), counted once, as the owner received it.
  * REPLAY (D-b, open loop): for candidate constants the fleet's estimators are rebuilt and
    the logged calls replayed.  The candidate's sigma / omega replace the recording's in
    relayed detections (the sender model's own values) and its feedback scales replace the
    recording's in interventions (cue sigma / omega x scale; model defaults when the cue has
    none).  FIXED AT THE RECORDING (phase-1 assumptions): the policy (B5_c's decisions,
    hence the truth and the interventions), and the relay set (which detections and
    interventions were relayed: border radius 1.5 x the recording sigma, the bus gates).
    A replay with the recording constants reproduces the live estimators bit for bit
    (tests/test_refit_sim_truth.py).
  * SCORE (D-c): every 30 s from t = 0 to 1500 s (horizon 300 s inside the run), the field
    each node's zone owner holds (fleet mean at unowned nodes) is scored against the
    accepted truth events of [t, t + 300 s): occupancy log-loss and Brier of
    p = 1 - exp(-lam dA 300) per node (the calibration harness's metrics), and the point-
    process NLL over the whole run. For the truth target both the step integral and
    event log term use the field at the START of that step, before its own observations.
    The detected-only diagnostic retains its pre-detection event log term.
    "prediction-only" replays without the intervention calls; "proposed" with them.
  * SEARCH: the machinery of experiments/refit_sestpp_new_units.py (stages prediction-only,
    proposed, joint 3 x 3 with the guardrail; cyclic coordinate line search, factor-2 log
    grid, edge extension, 3^k local check; two cycle orders, the better kept; tie
    tolerance 1e-9; 2^60 cap labelled unbounded; 0 hard lower bound for alpha_cross and
    bg_ema, 1 upper bound for bg_ema); the 30 (load, seed) runs pooled with EQUAL weight;
    parameters whose line is flat are reported NOT IDENTIFIED (current value kept).
  * STOP RULE: if alpha_in goes to its lower bound (its line ends unbounded downwards or
    below start x 2^-40) the refit stops and writes the objective profile over alpha_in;
    nothing is deployed.

Usage:
  py -3.10 -m experiments.refit_sim_truth record --workers 8
  py -3.10 -m experiments.refit_sim_truth refit --workers 8
Outputs: results/refit_sim_truth/ (recordings/, refit_truth_v2/ or refit_detected_diagnostic_v2/),
all stamped with the code version.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("DETERRENT_TELEMETRY", "0")
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from experiments import refit_sestpp_new_units as rh   # search machinery (harness refit, superseded)

PHASE = "phase 1 (provisional)"
SCORER_VERSION = "predictable_step_nll_v2"
OUT = _root / "results" / "refit_sim_truth"
LOADS = {"spare": 2e-5, "heavy": 1e-4, "overload": 4e-4}
DEV_SEEDS = tuple(range(200, 210))
SCORE_EVERY_S = 30.0
SCORE_LAST_S = 1500.0
HORIZON_S = 300.0
EPS = 1e-12
ALPHA_IN_STOP_STEPS = 40
# recording constants: C001 in the new units (the old estimator exactly)
REC_PROP = rh.equivalent_start(rh.C001_PROPOSED)
REC_PRED = rh.equivalent_start(rh.C001_PREDICTION)
PAPER_PROP = dict(rh.C001_PROPOSED)
PRED_DEFAULTS = {"omega_inhib": REC_PROP["omega_inhib"], "alpha_inhib": REC_PROP["alpha_inhib"],
                 "feedback_sigma_scale": 1.0, "feedback_omega_scale": 1.0}


def _sim_overrides(p: dict) -> dict:
    return {"sigma": p["sigma"], "omega": p["omega"], "omega_inhib": p["omega_inhib"], "alpha_in": p["alpha_in"],
            "alpha_cross": p["alpha_cross"], "alpha_inhib": p["alpha_inhib"], "mu_base": p["mu_base"],
            "bg_ema": p["bg_ema"], "model_feedback_sigma_scale": p["feedback_sigma_scale"],
            "model_feedback_omega_scale": p["feedback_omega_scale"]}


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------
class _Recorder:
    def __init__(self):
        self.active = False
        self.model_rid: dict[int, str] = {}
        self.log: list = []

    def idx(self, model):
        return self.model_rid.get(id(model))


REC = _Recorder()
_INSTALLED = False


def install_recorder():
    """Class-level wrappers that log calls on the robots' live estimators (not on copies)."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    import Robot as robot_mod
    from SESTPP import OnlineSESTPP

    orig_init = robot_mod.Robot.__init__

    def robot_init(self, robot_id, model, *a, **kw):
        orig_init(self, robot_id, model, *a, **kw)
        if REC.active:
            REC.model_rid[id(model)] = str(robot_id)

    robot_mod.Robot.__init__ = robot_init

    orig_det = robot_mod.Robot.ingest_detection

    def ingest_detection(self, x, y, t):
        if REC.active and REC.idx(self.m) is not None:
            REC.log.append(("det", float(x), float(y), float(t)))
        return orig_det(self, x, y, t)

    robot_mod.Robot.ingest_detection = ingest_detection

    o_adv = OnlineSESTPP.advance_time
    o_loc = OnlineSESTPP.add_local_event
    o_cross = OnlineSESTPP.add_cross_event
    o_int = OnlineSESTPP.add_intervention_event

    def advance_time(self, dt):
        rid = REC.idx(self) if REC.active else None
        if rid is not None:
            REC.log.append(("adv", rid, float(dt)))
        return o_adv(self, dt)

    def add_local_event(self, x, y):
        rid = REC.idx(self) if REC.active else None
        if rid is not None:
            REC.log.append(("loc", rid, float(x), float(y)))
        return o_loc(self, x, y)

    def add_cross_event(self, x, y, weight=0.35, sigma=None, omega=None, t=None):
        rid = REC.idx(self) if REC.active else None
        if rid is not None:
            REC.log.append(("cross", rid, float(x), float(y), float(weight), sigma, omega, t))
        return o_cross(self, x, y, weight=weight, sigma=sigma, omega=omega, t=t)

    def add_intervention_event(self, x, y, weight=1.0, sigma=None, omega_inhib=None, *, mode=None, t=None):
        rid = REC.idx(self) if REC.active else None
        if rid is not None:
            REC.log.append(("int", rid, float(x), float(y), float(weight), sigma, omega_inhib, mode, t))
        return o_int(self, x, y, weight=weight, sigma=sigma, omega_inhib=omega_inhib, mode=mode, t=t)

    # ConsistentOnlineSESTPP overrides these; it is never recorded (legacy estimator only)
    OnlineSESTPP.advance_time = advance_time
    OnlineSESTPP.add_local_event = add_local_event
    OnlineSESTPP.add_cross_event = add_cross_event
    OnlineSESTPP.add_intervention_event = add_intervention_event


def record_params(mu: float, t_end: float | None = None, recording_constants: dict | None = None) -> dict:
    import experiments.run_plan_completion as rpc
    saved = rpc.NEW_UNITS_OVERRIDES
    try:
        rpc.NEW_UNITS_OVERRIDES = {}        # old thresholds (D-a)
        params = rpc.build_params("B5_c", True, float(mu), t_end)
    finally:
        rpc.NEW_UNITS_OVERRIDES = saved
    params["legacy_stamp_units"] = "mass_per_cell"
    params["proposed_model_overrides"] = _sim_overrides(
        REC_PROP if recording_constants is None else recording_constants)
    return params


def record_run(job: dict) -> dict:
    import DeterrentSystem as ds
    from habituation_stl import scenario_rollout as sr

    install_recorder()
    REC.model_rid, REC.log = {}, []
    recording_constants = dict(job.get('recording_constants') or REC_PROP)
    params = dict(job['params']) if 'params' in job else record_params(job["mu"], job.get("t_end"), recording_constants)
    params["seed"] = int(job["seed"])
    if int(job["seed"]) >= 300:
        raise ValueError("evaluation seeds (>= 300) are never used for calibration")
    check_lam = bool(job.get("check_lam", False))
    started = time.time()
    REC.active = True
    gen = ds.run_simulation_frames_persistent(**params)
    owners, live_lam, prev_owner = [], [], None
    meta = None
    truth_list = None
    try:
        for _frame in gen:
            L = gen.gi_frame.f_locals
            if meta is None:
                if job.get('runtime_expectations'):
                    from experiments.run_hierarchical_calibration import audit_runtime
                    audit_runtime(L, job['runtime_expectations'])
                rdef = [str(r["id"]) for r in L["robots_def"]]
                W, H, NX, NY = float(L["W"]), float(L["H"]), int(L["NX"]), int(L["NY"])
                m0 = L["robots"][rdef[0]].m
                XX, YY = np.meshgrid(m0.xs, m0.ys, indexing="xy")
                meta = {"robots": rdef, "W": W, "H": H, "NX": NX, "NY": NY, "dt": float(L["dt"]),
                        "x_min": float(m0.x_min), "x_max": float(m0.x_max), "y_min": float(m0.y_min),
                        "y_max": float(m0.y_max),
                        "rec_constants": dict(recording_constants), "units": str(m0.legacy_stamp_units),
                        "grid_contract": getattr(m0, "grid_contract", "legacy_nodes"),
                        "truth_process_mode": L.get("truth_process_mode", "historical_thinning")}
                assert set(REC.model_rid.values()) >= set(rdef)
            truth_list = L["truth_events"]   # accepted truth bird events (x, y, t) of the scored run
            owner = sr._zone_owner_grid(L, XX, YY)
            if prev_owner is None or not np.array_equal(owner, prev_owner):
                owners.append(owner.copy())
                REC.log.append(("owner", len(owners) - 1))
                prev_owner = owner
            t_model = float(L["robots"][meta["robots"][0]].m.t_now)
            REC.log.append(("step", t_model))
            if check_lam:
                lams = np.stack([L["robots"][r].m.lam for r in meta["robots"]])
                live_lam.append(_assemble(lams, owner))
    finally:
        REC.active = False
        gen.close()
    rid_index = {rid: i for i, rid in enumerate(meta["robots"])}
    log = []
    for e in REC.log:   # robot id -> index; calls on robots outside robots_def are dropped
        if e[0] in ("adv", "loc", "cross", "int"):
            if e[1] not in rid_index:
                continue
            e = (e[0], rid_index[e[1]]) + tuple(e[2:])
        log.append(e)
    from experiments.run_plan_completion import code_version
    rec = {"phase": PHASE, "load": job["load"], "mu": float(job["mu"]), "seed": int(job["seed"]), **meta,
           "recording_system": job.get('system', 'B5_c'), "resolved_params": params,
           "recording_identity": job.get('identity'),
           "log": log, "owners": owners, "code_version": code_version(), "elapsed_s": time.time() - started,
           "truth_events": [(float(x), float(y), float(t)) for (x, y, t) in (truth_list or [])]}
    if check_lam:
        rec["live_lam"] = live_lam
    path = Path(job["out"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(rec, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return {"load": job["load"], "seed": job["seed"], "elapsed_s": rec["elapsed_s"],
            "n_log": len(log), "n_det": sum(1 for e in log if e[0] == "det"), "n_truth": len(rec["truth_events"])}


def _assemble(lams: np.ndarray, owner: np.ndarray) -> np.ndarray:
    """scenario_rollout._by_owner: the zone owner's value, fleet mean at unowned nodes."""
    picked = np.take_along_axis(lams, np.maximum(owner, 0)[None], axis=0)[0]
    return np.where(owner >= 0, picked, lams.mean(axis=0))


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def _build_models(rec: dict, p: dict) -> list:
    from SESTPP import OnlineSESTPP
    from additive_intensity import ADDITIVE_CONTRACT
    if rec.get("truth_process_mode") == ADDITIVE_CONTRACT and rec.get("grid_contract") != ADDITIVE_CONTRACT:
        raise ValueError("additive recordings require their explicit additive grid contract")
    return [OnlineSESTPP(rec["x_min"], rec["x_max"], rec["y_min"], rec["y_max"], rec["NX"], rec["NY"],
                         sigma=p["sigma"], omega=p["omega"], omega_inhib=p["omega_inhib"], alpha_in=p["alpha_in"],
                         alpha_cross=p["alpha_cross"], alpha_inhib=p["alpha_inhib"], mu_base=p["mu_base"],
                         bg_ema=p["bg_ema"], legacy_stamp_units="mass_per_cell",
                         grid_contract=rec.get("grid_contract", "legacy_nodes"))
            for _ in rec["robots"]]


def _swap(value, rec_default, cand_default):
    """A relayed model value (sigma / omega of the sending model): the candidate's own."""
    if value is None:
        return None
    return float(cand_default) if math.isclose(float(value), float(rec_default), rel_tol=1e-12) else float(value)


def _feedback(value, rec_scale, rec_default, cand_scale, cand_default):
    """An intervention's sigma or omega (cue value, or the model default, times the feedback
    scale): re-expressed with the candidate's scale and default.  Exact when unchanged."""
    if value is None:
        return None
    if cand_scale == rec_scale and cand_default == rec_default:
        return float(value)
    base = float(value) / float(rec_scale)
    if math.isclose(base, float(rec_default), rel_tol=1e-12):
        base = float(cand_default)
    return base * float(cand_scale)


def replay(rec: dict, p: dict, with_interventions: bool, *, keep_lam: bool = False, target: str = "truth") -> dict:
    """Replay the logged estimator inputs with constants ``p``; field metrics against
    ``target``: "truth" = every accepted truth bird event (user decision 2026-10-29, as the
    original calibration; NLL log term from the assembled field at the start of the event's
    simulator step) or "detected" = the detected events only (diagnostic; NLL log term just
    before the detection's own stamp)."""
    if target not in ("truth", "detected"):
        raise ValueError(target)
    if rec.get('units') != 'mass_per_cell':
        raise ValueError('replay requires a recording explicitly tagged mass_per_cell')
    from diagnostics.diagnostic_field_truth_compare import _probability_metrics

    rc = rec["rec_constants"]
    models = _build_models(rec, p)
    owners = rec["owners"]
    owner = owners[0] if owners else np.full((rec["NY"], rec["NX"]), -1, np.int64)
    m0 = models[0]
    area = float(m0.dx * m0.dy)
    dt = float(rec["dt"])
    integral = 0.0
    log_sum = 0.0
    n_det = 0
    snaps, live = [], []
    dets = []
    next_score = 0.0
    if target == "truth" and "truth_events" not in rec:
        raise ValueError("recording has no truth events (re-record)")
    truth, t_node = _truth_arrays(rec, m0)
    ti = 0
    lam_prev = _assemble(np.stack([m.lam for m in models]), owner)
    for e in rec["log"]:
        op = e[0]
        if op == "adv":
            models[e[1]].advance_time(e[2])
        elif op == "loc":
            models[e[1]].add_local_event(e[2], e[3])
        elif op == "cross":
            _, i, x, y, w, sg, om, t = e
            models[i].add_cross_event(x, y, weight=w, sigma=_swap(sg, rc["sigma"], p["sigma"]),
                                      omega=_swap(om, rc["omega"], p["omega"]), t=t)
        elif op == "int":
            if not with_interventions:
                continue
            _, i, x, y, w, sg, om, mode, t = e
            models[i].add_intervention_event(
                x, y, weight=w,
                sigma=_feedback(sg, rc["feedback_sigma_scale"], rc["sigma"], p["feedback_sigma_scale"], p["sigma"]),
                omega_inhib=_feedback(om, rc["feedback_omega_scale"], rc["omega_inhib"],
                                      p["feedback_omega_scale"], p["omega_inhib"]),
                mode=mode, t=t)
        elif op == "det":
            _, x, y, t = e
            iy, ix = m0.world_to_idx(x, y)
            k = int(owner[iy, ix])
            if target == "detected":
                lam = float(models[k].lam[iy, ix]) if k >= 0 else float(np.mean([m.lam[iy, ix] for m in models]))
                log_sum += math.log(max(lam, EPS))
            n_det += 1
            dets.append((x, y, t))
        elif op == "owner":
            owner = owners[e[1]]
        elif op == "step":
            lam_f = _assemble(np.stack([m.lam for m in models]), owner)
            # Match the left-step field used for truth-event likelihoods. Using
            # lam_f here lets this step's own detections enter its integral while
            # its log term is still scored against the pre-observation field.
            integral += float(np.sum(lam_prev)) * area * dt
            if target == "truth":
                s_now = float(e[1])
                tj = int(np.searchsorted(truth[:, 2], s_now, side="left"))
                if tj > ti:
                    vals = lam_prev.ravel()[t_node[ti:tj]]
                    log_sum += float(np.sum(np.log(np.maximum(vals, EPS))))
                    ti = tj
            lam_prev = lam_f
            if keep_lam:
                live.append(lam_f)
            s = float(e[1])
            if s >= next_score - 1e-6 and s <= SCORE_LAST_S + 1e-6:
                snaps.append((s, lam_f.copy()))
                next_score = s + SCORE_EVERY_S
    if target == "detected":
        det = np.asarray(dets, float).reshape(-1, 3)
        det_node = _node_index(det[:, 0], det[:, 1], m0) if det.size else np.zeros(0, np.int64)
    else:
        det, det_node = truth, t_node
    rows = []
    hscale = area * HORIZON_S
    ncell = int(rec["NX"]) * int(rec["NY"])
    for s, lam_f in snaps:
        lo = int(np.searchsorted(det[:, 2], s, side="left")) if det.size else 0
        hi = int(np.searchsorted(det[:, 2], s + HORIZON_S, side="left")) if det.size else 0
        count = np.bincount(det_node[lo:hi], minlength=ncell).astype(float).reshape(lam_f.shape)
        occ = (count > 0).astype(float)
        prob = 1.0 - np.exp(-np.clip(lam_f, 0.0, None) * hscale)
        rows.append(_probability_metrics(prob, occ, count, area, HORIZON_S))
    out = {"field_logloss": float(np.mean([r["field_logloss"] for r in rows])),
           "field_brier": float(np.mean([r["field_brier"] for r in rows])),
           "nll": float(integral - log_sum), "detected_events": int(n_det), "truth_events": int(truth.shape[0]),
           "scored_events": int(det.shape[0]), "target": target, "n_snapshots": len(rows),
           "expected_events": float(integral), "count_bias": float(integral - det.shape[0]),
           "scoring_version": SCORER_VERSION}
    if keep_lam:
        out["lam"] = live
    return out


def _node_index(x: np.ndarray, y: np.ndarray, m) -> np.ndarray:
    """Vectorised OnlineSESTPP.world_to_idx (round half to even, clipped) as flat indices."""
    from additive_intensity import ADDITIVE_CONTRACT
    if getattr(m, "grid_contract", "legacy_nodes") == ADDITIVE_CONTRACT:
        ix = np.floor((np.asarray(x) - m.x_min) / m.dx).astype(np.int64)
        iy = np.floor((np.asarray(y) - m.y_min) / m.dy).astype(np.int64)
        return np.clip(iy, 0, m.ny - 1) * m.nx + np.clip(ix, 0, m.nx - 1)
    ix = np.rint((np.asarray(x) - m.x_min) / (m.x_max - m.x_min) * (m.nx - 1)).astype(np.int64)
    iy = np.rint((np.asarray(y) - m.y_min) / (m.y_max - m.y_min) * (m.ny - 1)).astype(np.int64)
    return np.clip(iy, 0, m.ny - 1) * m.nx + np.clip(ix, 0, m.nx - 1)


def _truth_arrays(rec: dict, m) -> tuple:
    """Time-sorted truth events (n, 3) and their flat node indices, cached in ``rec``."""
    if "_truth_sorted" not in rec:
        tr = np.asarray(rec.get("truth_events", []), float).reshape(-1, 3)
        tr = tr[np.argsort(tr[:, 2], kind="stable")] if tr.size else tr
        rec["_truth_sorted"] = tr
        rec["_truth_node"] = _node_index(tr[:, 0], tr[:, 1], m) if tr.size else np.zeros(0, np.int64)
    return rec["_truth_sorted"], rec["_truth_node"]


# ---------------------------------------------------------------------------
# Search plumbing (workers)
# ---------------------------------------------------------------------------
_CACHE: dict = {}


def _load(path: str) -> dict:
    if path not in _CACHE:
        with open(path, "rb") as fh:
            rec = pickle.load(fh)
        # compact the truth events (hundreds of thousands of tuples at overload)
        rec["truth_events"] = np.asarray(rec.get("truth_events", []), float).reshape(-1, 3)
        _CACHE[path] = rec
    return _CACHE[path]


def _run(job):
    stage, pred, prop, path = job[:4]
    target = job[4] if len(job) > 4 else "truth"
    rec = _load(path)
    nan = float("nan")
    res = {k: nan for k in rh.METRIC_KEYS}
    a = b = None
    if stage in ("prediction", "joint"):
        a = replay(rec, {**PRED_DEFAULTS, **pred}, with_interventions=False, target=target)
        res.update(prediction_only_field_logloss=a["field_logloss"], prediction_only_field_brier=a["field_brier"],
                   prediction_only_nll=a["nll"], truth_events=float(a["scored_events"]),
                   prediction_only_expected_events=a['expected_events'])
    if stage in ("proposed", "joint"):
        b = replay(rec, prop, with_interventions=True, target=target)
        res.update(proposed_field_logloss=b["field_logloss"], proposed_field_brier=b["field_brier"],
                   proposed_nll=b["nll"], truth_events=float(b["scored_events"]),
                   proposed_expected_events=b['expected_events'])
    if a is not None and b is not None:
        res["delta_field_logloss_proposed_minus_prediction"] = b["field_logloss"] - a["field_logloss"]
        res["delta_field_brier_proposed_minus_prediction"] = b["field_brier"] - a["field_brier"]
        res["delta_nll_proposed_minus_prediction"] = b["nll"] - a["nll"]
    return res


class SimEvaluator(rh.Evaluator):
    """rh.Evaluator over the 30 recordings (equal weight), stage-aware replays."""

    def __init__(self, out: Path, workers: int, log, paths: list, target: str = "truth"):
        self.paths = list(paths)
        self.target = target
        super().__init__(out, workers, log)
        try:
            def digest(path):
                value = hashlib.sha256()
                with Path(path).open('rb') as fh:
                    for block in iter(lambda: fh.read(1024 * 1024), b''):
                        value.update(block)
                return value.hexdigest()

            # Parameter keys alone do not identify a replay: seed subsets, target,
            # recordings, model implementation, and scoring settings must agree.
            signature = {'target': target, 'scoring_version': SCORER_VERSION,
                         'recordings': [(str(Path(p).resolve()), digest(p)) for p in sorted(self.paths)],
                         'sources': {str(p.relative_to(_root)): digest(p) for p in
                                     (Path(__file__), _root / 'SESTPP.py',
                                      _root / 'additive_intensity.py',
                                      _root / 'diagnostics/diagnostic_field_truth_compare.py')},
                         'score_every_s': SCORE_EVERY_S, 'score_last_s': SCORE_LAST_S,
                         'horizon_s': HORIZON_S, 'epsilon': EPS}
            fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
            self.version.update(scoring_version=SCORER_VERSION, replay_signature=fingerprint)
            for row in self.cache.values():
                if (row.get('scoring_version') != SCORER_VERSION or
                        row.get('replay_signature') != fingerprint):
                    raise ValueError('Replay cache belongs to another scorer, data set, or target; '
                                     'use a new output directory instead of mixing cached scores')
        except Exception:
            self.close()
            raise

    def evaluate(self, stage, configs):
        todo = []
        for pred, prop in configs:
            key = rh.config_key(stage, pred, prop)
            if key not in self.cache and key not in [k for k, _, _ in todo]:
                todo.append((key, pred, prop))
        if todo:
            rh.wait_memory(self.log)
            jobs, owners_ = [], []
            for key, pred, prop in todo:
                for pth in self.paths:
                    jobs.append((stage, pred, prop, pth, self.target))
                    owners_.append(key)
            t0 = time.time()
            results = list(self.pool.map(_run, jobs, chunksize=2))
            self.n_runs += len(jobs)
            per = {}
            for key, job, r in zip(owners_, jobs, results):
                per.setdefault(key, []).append({"recording": Path(job[3]).name, **r})
            with self.cache_path.open("a", encoding="utf-8") as fh:
                for key, pred, prop in todo:
                    runs = per[key]
                    pooled = {k: float(np.mean([r[k] for r in runs])) for k in rh.METRIC_KEYS}  # equal weight
                    row = {"key": key, "stage": stage, "pred": pred, "prop": prop, "pooled": pooled, "runs": runs,
                           "phase": PHASE, "target": self.target, **self.version}
                    self.cache[key] = row
                    fh.write(json.dumps(row) + "\n")
            self.log(f"[eval] {stage}: {len(todo)} configs, {len(jobs)} replays, {time.time() - t0:.0f} s")
        return [self.cache[rh.config_key(stage, pred, prop)] for pred, prop in configs]


class AlphaInToZero(RuntimeError):
    pass


class SimSearch(rh.Search):
    """rh.Search with the alpha_in STOP rule and the not-identified report."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.start = dict(self.x)
        self.flat: dict[str, bool] = {}
        self.local_checks: list = []

    def line(self, name):
        n_hist = len(self.history)
        changed = super().line(name)
        h = self.history[n_hist]
        # a line is flat when every evaluated value tied with the current one
        rows = [r for r in self.ev.cache.values() if r["stage"] == self.stage
                and self._same_except(r, name)]
        vals = [rh.objective(self.stage, r)[0] for r in rows]
        if vals:
            ref = rh.objective(self.stage, self.ev.evaluate(self.stage, [self._pair(self.x)])[0])[0]
            self.flat[name] = all(abs(v - ref) <= rh.TIE_RTOL * abs(ref) for v in vals)
        if name == "alpha_in" and (h["status"] == "unbounded_down"
                                   or self.x["alpha_in"] <= self.start["alpha_in"] * rh.STEP ** -ALPHA_IN_STOP_STEPS):
            prof = sorted((r["prop" if self.stage != "prediction" else "pred"]["alpha_in"],
                           rh.objective(self.stage, r)[0]) for r in rows)
            raise AlphaInToZero(json.dumps({"stage": self.stage, "alpha_in": self.x["alpha_in"],
                                            "status": h["status"], "profile": prof}))
        return changed

    def _axis(self, n):
        c = self.x[n]
        if c == 0.0:
            vals = [0.0, self._ladder(n, 0, 0)[0]]
        else:
            vals = [c / rh.STEP, c, c * rh.STEP]
        ub = rh.UPPER_BOUND.get(n)
        if ub is not None:
            vals = [min(v, ub) for v in vals]
        return sorted(set(vals))

    def local_check(self, max_configs: int) -> bool:
        """Full 3^k check over the moved parameters, or, when it exceeds ``max_configs``,
        PAIRWISE 3 x 3 checks over every pair of moved parameters (user decision
        2026-10-29); bounds respected (bg_ema <= 1, zero-bounded axes {0, base})."""
        from itertools import combinations, product
        moved = [n for n in self.names if n in self.moved]
        axes = {n: self._axis(n) for n in moved}
        n_full = int(np.prod([len(a) for a in axes.values()])) if axes else 1
        if n_full <= max_configs:
            kind = f"full 3^k over {moved}"
            pts = [{**self.x, **dict(zip(moved, combo))} for combo in product(*[axes[n] for n in moved])]
        else:
            kind = f"pairwise 3x3 over {len(moved)} moved parameters (full 3^k would be {n_full})"
            seen, pts = set(), []
            for a, b in combinations(moved, 2):
                for va, vb in product(axes[a], axes[b]):
                    pt = {**self.x, a: va, b: vb}
                    key = tuple(sorted((k, rh._r(v)) for k, v in pt.items()))
                    if key not in seen:
                        seen.add(key)
                        pts.append(pt)
        self.log(f"[{self.stage}] local check: {kind}: {len(pts)} configs")
        if not pts:
            return False
        scored = self._eval_points(pts)
        cur_score = rh.objective(self.stage, self.ev.evaluate(self.stage, [self._pair(self.x)])[0])
        best_i = min(range(len(pts)), key=lambda i: scored[i][0])
        if scored[best_i][0][0] < cur_score[0] - rh.TIE_RTOL * abs(cur_score[0]):
            self.log(f"[{self.stage}] local check improved {cur_score[0]:.6f} -> {scored[best_i][0][0]:.6f}")
            for n in moved:
                self.x[n] = pts[best_i][n]
            self.local_checks.append({"kind": kind, "n": len(pts), "improved": True})
            return True
        self.log(f"[{self.stage}] local check: current point is the best of {len(pts)}")
        self.local_checks.append({"kind": kind, "n": len(pts), "improved": False})
        return False

    def _same_except(self, row, name):
        pred, prop = self._pair(self.x)
        target = row["pred"] if self.stage == "prediction" else row["prop"]
        cur = pred if self.stage == "prediction" else prop
        return all(rh._r(target.get(k, float("nan"))) == rh._r(v) for k, v in cur.items() if k != name)


def cmd_record(args):
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    recording_start = getattr(args, 'recording_start', 'equivalent')
    folder = 'recordings_paper' if recording_start == 'paper' else 'recordings'
    constants = PAPER_PROP if recording_start == 'paper' else REC_PROP
    for load, mu in LOADS.items():
        for seed in args.seeds:
            out = OUT / folder / f"{load}_{seed}.pkl"
            if out.exists():
                continue
            jobs.append({"load": load, "mu": mu, "seed": int(seed), "out": str(out), "t_end": args.t_end,
                         'recording_constants': constants})
    print(f"{len(jobs)} recordings", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = []
        for j in jobs:
            rh.wait_memory(print)
            futs.append(ex.submit(record_run, j))
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            print(f"[{i}/{len(jobs)}] {r} (wall {time.time() - t0:.0f}s)", flush=True)


def cmd_refit(args):
    if any(int(seed) < 0 or int(seed) >= 300 for seed in args.seeds):
        raise ValueError('calibration seeds must be nonnegative and below 300; evaluation seeds are excluded')
    OUT.mkdir(parents=True, exist_ok=True)
    rh.MIN_FREE_GB = float(args.min_free_gb)
    recording_start = getattr(args, 'recording_start', 'equivalent')
    folder = 'recordings_paper' if recording_start == 'paper' else 'recordings'
    paths = [str(OUT / folder / f"{load}_{seed}.pkl") for load in LOADS for seed in args.seeds]
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        raise SystemExit(f"missing recordings: {missing}")
    # Previous search artifacts retain their historical scores; never silently reuse
    # their post-observation NLL integral with the corrected scorer.
    rdir = OUT / ("refit_truth_v2" if args.target == "truth" else "refit_detected_diagnostic_v2")
    if recording_start == 'paper':
        rdir = rdir.with_name(rdir.name + '_paper_recordings')
    rdir.mkdir(parents=True, exist_ok=True)
    logf = (rdir / "refit.log").open("a", encoding="utf-8")

    def log(msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    ev = SimEvaluator(rdir, args.workers, log, paths, target=args.target)
    recording_constants = PAPER_PROP if recording_start == 'paper' else REC_PROP
    reference_name = 'paper_start' if recording_start == 'paper' else 'equivalent_start'
    result = {"phase": PHASE, **ev.version, "target": args.target, 'recording_start': recording_start,
              'reference_start': reference_name,
              "target_definition": ("all accepted truth bird events (DeterrentSystem truth_events of the scored "
                                    "run), as the original calibration (user decision 2026-10-29)"
                                    if args.target == "truth" else
                                    "DIAGNOSTIC: detected events only"), "recording_constants": recording_constants, "loads": LOADS,
              "dev_seeds": list(args.seeds), "score": {"every_s": SCORE_EVERY_S, "last_s": SCORE_LAST_S,
                                                       "horizon_s": HORIZON_S},
              "detected_event_definition": ("events passed to the zone owner's Robot.ingest_detection (owner in "
                                            "range and detection draw passed), once per event; relayed copies "
                                            "are not separate events")}
    try:
        start_pred = dict(rh.C001_PREDICTION if recording_start == 'paper' else REC_PRED)
        start_prop = dict(recording_constants)

        def _orders(names):
            amp = tuple(n for n in rh.STAMP_KEYS if n in names) + tuple(n for n in names if n not in rh.STAMP_KEYS)
            return {"amplitudes_first": amp, "listed": tuple(names)}

        def _stage(stage, names, starts, other):
            runs = {}
            for start_label, start in starts.items():
                for label, order in _orders(names).items():
                    key = f"{start_label}/{label}"
                    log(f"[{stage}] start {start_label}, order {label}: {order}")
                    s = SimSearch(stage, order, start, other, ev, log)
                    runs[key] = (s, s.run(args.max_local_configs))
            best = min(runs, key=lambda k: tuple(runs[k][1]["objective"]))
            s, res = runs[best]
            res = dict(res, order=best, not_identified=sorted(k for k, v in s.flat.items() if v),
                       by_order={k: {"x": v[1]["x"], "objective": v[1]["objective"], "moved": v[1]["moved"],
                                     "line_status": v[1]["line_status"], "local_checks": v[0].local_checks,
                                     "not_identified": sorted(n for n, f in v[0].flat.items() if f)}
                                 for k, v in runs.items()})
            return s, res

        s0 = SimSearch("prediction", rh.PRED_PARAMS, start_pred, {}, ev, log)
        result[f"{reference_name}_objective_prediction"] = list(
            rh.objective("prediction", ev.evaluate("prediction", [s0._pair(start_pred)])[0]))
        s_pred, res_pred = _stage("prediction", rh.PRED_PARAMS, {reference_name: start_pred}, {})
        result["prediction_stage"] = res_pred
        other = {k: res_pred["x"][k] for k in rh.PRED_PARAMS}
        s1 = SimSearch("proposed", rh.PROP_PARAMS, start_prop, other, ev, log)
        result[f"{reference_name}_objective_proposed"] = list(
            rh.objective("proposed", ev.evaluate("proposed", [s1._pair(start_prop)])[0]))
        # third start (user decision 2026-10-29): shared constants from the prediction-only
        # optimum, intervention constants from the selected reference start.
        start_third = {**start_prop, **{k: res_pred["x"][k] for k in rh.PRED_PARAMS}}
        result["third_start"] = start_third
        s_prop, res_prop = _stage("proposed", rh.PROP_PARAMS,
                                  {reference_name: start_prop, "prediction_optimum": start_third}, other)
        result["proposed_stage"] = res_prop
        top_pred, top_prop = s_pred.top(3), s_prop.top(3)
        joint = ev.evaluate("joint", [(dict(a["pred"]), dict(b["prop"])) for a in top_pred for b in top_prop])
        ranked = sorted(joint, key=lambda r: (not rh.guardrail_ok(r), rh.objective("proposed", r), r["key"]))
        best = ranked[0]
        start_joint = ev.evaluate("joint", [(start_pred, start_prop)])[0]
        result.update(
            joint_ranking=[{"pred": r["pred"], "prop": r["prop"], "guardrail": rh.guardrail_ok(r), "pooled": r["pooled"]}
                           for r in ranked],
            reference_start_joint={"pooled": start_joint["pooled"], "guardrail": rh.guardrail_ok(start_joint)},
            best={"prediction_only": best["pred"], "proposed": best["prop"], "guardrail": rh.guardrail_ok(best),
                  "pooled": best["pooled"]},
            deployed_constants={f"model_{k}" if not k.startswith("feedback") else f"model_{k}": v
                                for k, v in best["prop"].items()},
            status="finished" if rh.guardrail_ok(best) else "finished_guardrail_FAILED", replays=ev.n_runs,
            best_proposed_vs_prediction_only={"proposed_logloss": best["pooled"]["proposed_field_logloss"],
                                              "prediction_only_logloss": best["pooled"]["prediction_only_field_logloss"]})
        if recording_start == 'equivalent':
            result['equivalent_start_joint'] = result['reference_start_joint']
        log(f"[joint] best {best['prop']} guardrail {rh.guardrail_ok(best)}")
    except AlphaInToZero as exc:
        result.update(status="STOP_alpha_in_to_zero", stop=json.loads(str(exc)), replays=ev.n_runs)
        log(f"STOP: alpha_in went to its lower bound: {exc}")
    finally:
        ev.close()
        temporary = rdir / 'refit_result.json.tmp'
        temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
        temporary.replace(rdir / 'refit_result.json')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--seeds", nargs="+", type=int, default=list(DEV_SEEDS))
    r.add_argument("--t-end", type=float, default=None)
    r.add_argument('--recording-start', choices=('equivalent', 'paper'), default='equivalent',
                   help='equivalent preserves the old-unit-equivalent recordings; paper uses unchanged ACC constants')
    f = sub.add_parser("refit")
    f.add_argument("--workers", type=int, default=2)
    f.add_argument('--recording-start', choices=('equivalent', 'paper'), default='equivalent')
    f.add_argument("--seeds", nargs="+", type=int, default=list(DEV_SEEDS))
    f.add_argument("--max-local-configs", type=int, default=800)
    f.add_argument("--min-free-gb", type=float, default=4.0,
                   help="free-memory floor checked before every batch (user decision 2026-10-29: 4 GB)")
    f.add_argument("--target", choices=("truth", "detected"), default="truth",
                   help="score against all truth events (decision 2026-10-29) or detected only (diagnostic)")
    args = ap.parse_args()
    {"record": cmd_record, "refit": cmd_refit}[args.cmd](args)


if __name__ == "__main__":
    main()
