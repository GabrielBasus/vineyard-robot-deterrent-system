"""
consistent_threshold_mapping.py -- quantile mapping of model-unit thresholds to
estimator_mode="consistent".

The candidate-generation and scoring thresholds of the paper planner profile
(thesis_calibrated_selective_proposed) were tuned against the legacy SESTPP
estimator, whose intensity is not a density. Under the consistent estimator the
same numbers sit at a different place in the distribution of the quantity they
gate. Rule (fixed by the user, no free choices): for each threshold T in model
units,

    q        = F_legacy(T)          (pooled over B1, B5, B4(A) and the three loads,
                                     or only over the systems that use T)
    T_mapped = F_consistent^{-1}(q)

measured at the point where the quantity is compared with T, on development
seeds 200-209 only (never on evaluation seeds 300-329), with the paper
configuration (run_plan_completion._ladder_params) in the new evaluation
environment (random_stream_mode="coupled", truth_deterrence_memory="complete").
Because thresholds of earlier stages change what later stages see, the
consistent distributions are recollected with the mapped thresholds until every
mapped value moves by less than 1% (at most 5 iterations).

Instrumentation is read-only and lives entirely in this script:
  * a line tracer on TaskGenerator.periodic_patrolling (and its
    _collect_border_hotspots closure) reads the frame locals at each comparison
    line (located by source text, not hard-coded line numbers),
  * planner_task_estimation.counterfactual_value is wrapped to read the STL
    exposure signals (compared with stl_E_star) and the suppression amplitude
    ratio (compared with Dynamics.kernel_self),
  * DeterrentSystem.passes_busy_fallback_quality is wrapped to read p_event and
    deltaJ_per_cost.
Threshold values under test are injected through a temporary planner profile and
existing simulator parameters, plus two wrapper-level overrides
(min_hotspot_score, kernel_self) that have no simulator parameter.

Usage:
  py -3.10 experiments/consistent_threshold_mapping.py collect --estimator legacy --tag legacy
  py -3.10 experiments/consistent_threshold_mapping.py collect --estimator consistent --tag consistent_it0
  py -3.10 experiments/consistent_threshold_mapping.py map --legacy-tag legacy --consistent-tag consistent_it0 --out it1.json
  py -3.10 experiments/consistent_threshold_mapping.py collect --estimator consistent --tag consistent_it1 --overrides it1.json
  ...
  py -3.10 experiments/consistent_threshold_mapping.py validate --tags legacy consistent_it0 consistent_final
"""
from __future__ import annotations

import argparse
import inspect
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

DEV_SEEDS = tuple(range(200, 210))
MUS = (2e-5, 1e-4, 4e-4)
SYSTEMS = ("B1", "B5", "A")
OUT_ROOT = _root / "results" / "consistent_threshold_mapping"
ENV = {"random_stream_mode": "coupled", "truth_deterrence_memory": "complete"}
BASE_PROFILE = "thesis_calibrated_selective_proposed"
TMP_PROFILE = "tmp_consistent_threshold_mapping"

# Legacy (paper) values of every active model-unit threshold.
#   op: the gate rejects when  quantity <op> threshold  ("lt": <, "le": <=)
LEGACY_THRESHOLDS = {
    "min_hotspot_score": {"value": 1.0e-4, "op": "lt", "systems": SYSTEMS},
    # effective field-score cut of the heuristic risk gate:
    #   risk_conf = 1 - exp(-fs / risk_scale) < risk_threshold  <=>  fs < -risk_scale ln(1 - risk_threshold)
    "risk_field_cut": {"value": -1.0e-4 * math.log(1.0 - 0.35), "op": "lt", "systems": SYSTEMS},
    # busy-robot override: same risk_conf compared with model_deterring_busy_risk_override = 0.20
    "busy_risk_field": {"value": -1.0e-4 * math.log(1.0 - 0.20), "op": "lt", "systems": SYSTEMS},
    "model_deterring_score_margin": {"value": 0.10, "op": "le", "systems": SYSTEMS},
    "model_deterring_busy_fallback_p_event_min": {"value": 0.95, "op": "lt", "systems": SYSTEMS},
    "model_deterring_busy_fallback_deltaJ_per_cost_min": {"value": 1.0e6, "op": "lt", "systems": SYSTEMS},
    "stl_E_star": {"value": 5.0, "op": "le_star", "systems": ("A",)},
    "stl_kernel_self": {"value": 1.0, "op": "lt", "systems": ("A",)},
    # Implicit break-even of utility = predicted_deltaJ - cost_eta (model units minus
    # seconds). Under dispatch_policy "unc" (B1, B5) a generated predictive task outranks
    # a non-urgent reactive task (score 0) iff utility > 0, i.e. iff
    # predicted_deltaJ / raw_cost > c with c = 1 (legacy). The quantity is the raw
    # benefit-to-cost ratio of generated tasks; the mapped c is applied as a multiplier
    # on the travel-cost weights (deterring_modes w_eta / fixed_cost, patrol cost_w_eta).
    "deterring_cost_multiplier": {"value": 1.0, "op": "le", "systems": ("B1", "B5")},
    "patrol_cost_multiplier": {"value": 1.0, "op": "le", "systems": ("B1", "B5")},
}
RISK_THRESHOLD = 0.35  # unit free; kept, risk_scale carries the units
POSITIVE_FLOOR = {"risk_field_cut": 1.0e-12 * -math.log(1.0 - 0.35), "cost": 1.0e-300}


# ---------------------------------------------------------------------------
# Instrumentation (runs inside worker processes)
# ---------------------------------------------------------------------------
class _Recorder:
    def __init__(self):
        self.samples: dict[str, list] = {}
        self.taskgen_diag: dict = {}
        self.overrides: dict = {}
        self.record_shadow_free = True

    def add(self, key, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if math.isfinite(v):
            self.samples.setdefault(key, []).append(v)

    def extend(self, key, values):
        arr = np.asarray(values, dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size:
            self.samples.setdefault(key, []).extend(arr.tolist())


REC = _Recorder()


def _field_excess(rob, x, y):
    iy, ix = rob.m.world_to_idx(float(x), float(y))
    return float(rob.m.lam[iy, ix] - rob.m.mu[iy, ix])


def _find_line(func_src_lines, start, needle):
    hits = [start + i for i, line in enumerate(func_src_lines) if needle in line]
    if len(hits) != 1:
        raise RuntimeError(f"instrumentation: expected one line containing {needle!r}, found {hits}")
    return hits[0]


def _nested_code(code, name):
    for const in code.co_consts:
        if inspect.iscode(const):
            if const.co_name == name:
                return const
            found = _nested_code(const, name)
            if found is not None:
                return found
    return None


_INSTALLED = False


def install_instrumentation():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    import DeterrentSystem as ds
    import planner_task_estimation as pte
    import TaskGenerator as tg
    from habituation_stl import task_value as tv
    from dataclasses import replace

    func = tg.TaskGenerator.periodic_patrolling
    src, start = inspect.getsourcelines(func)
    code_pp = func.__code__
    code_border = _nested_code(code_pp, "_collect_border_hotspots")
    bsrc, bstart = inspect.getsourcelines(code_border)

    def h_patrol(loc):
        REC.add("min_hotspot_score", loc["field_val"])

    def h_border(loc):
        REC.add("min_hotspot_score", loc["score"])
        REC.add("min_hotspot_score__border", loc["score"])

    def h_risk(loc):
        REC.add("risk_field_cut", _field_excess(loc["rob"], loc["x"], loc["y"]))

    def h_busy(loc):
        cand = loc["cand"]
        REC.add("busy_risk_field", _field_excess(loc["rob"], cand["x"], cand["y"]))

    def h_margin(loc):
        best = loc["best"]
        patrol = loc["best_patrol"]
        REC.add("model_deterring_score_margin", float(best["score"]) - float(patrol["score"]))

    def h_add(loc):
        best = loc["best"]
        if not loc.get("task_added"):
            return
        kind = "det" if loc.get("ttype") == "deterring" else "patrol"
        REC.add(f"info_generated_{kind}_utility", best.get("utility", float("nan")))
        REC.add(f"info_generated_{kind}_predicted_deltaJ", best.get("predicted_deltaJ", float("nan")))
        REC.add(f"info_generated_{kind}_cost_eta", best.get("cost_eta", float("nan")))
        mult_key = "deterring_cost_multiplier" if kind == "det" else "patrol_cost_multiplier"
        mult = float(REC.overrides.get(mult_key, 1.0))
        cost = float(best.get("cost_eta", float("nan")))
        if cost > 0.0:
            REC.add(mult_key, float(best.get("predicted_deltaJ", float("nan"))) / (cost / mult))

    hooks = {
        (code_pp, _find_line(src, start, "if field_val < min_hotspot_score:")): h_patrol,
        (code_pp, _find_line(src, start, "if conf < float(deterring_risk_threshold):")): h_risk,
        (code_pp, _find_line(src, start, "if (cand_support < busy_support_override) and (cand_conf < busy_risk_override):")): h_busy,
        (code_pp, _find_line(src, start, 'if float(best["score"]) <= float(best_patrol["score"]) + score_margin:')): h_margin,
        (code_pp, _find_line(src, start, 'if ttype == "deterring" and task_added:')): h_add,
        (code_border, _find_line(bsrc, bstart, "if score < border_min_score:")): h_border,
    }
    targets = {code_pp, code_border}

    def _local(frame, event, arg):
        if event == "line":
            hook = hooks.get((frame.f_code, frame.f_lineno))
            if hook is not None:
                hook(frame.f_locals)
        return _local

    def _global(frame, event, arg):
        if frame.f_code in targets:
            return _local
        return None

    orig_pp = func

    def periodic_patrolling(self, *args, **kwargs):
        prev = sys.gettrace()
        sys.settrace(_global)
        try:
            return orig_pp(self, *args, **kwargs)
        finally:
            sys.settrace(prev)
            REC.taskgen_diag = dict(getattr(self, "diag_counts", {}) or {})

    tg.TaskGenerator.periodic_patrolling = periodic_patrolling

    orig_cv = pte.counterfactual_value

    def counterfactual_value(action, cells, cell_states, hab, params, dyn, *a, **kw):
        primary = bool(getattr(dyn, "shadow_overrides", ())) or REC.record_shadow_free
        if primary:
            try:
                times = tv._times(params)
                omega_e = float(dyn.omega_e)
                decay = np.exp(-times / omega_e)
                e0 = np.array([float(cell_states[c].e0) for c in cells], dtype=float)
                # nominal exposure signal e_z(t) for every local cell at every monitor time
                REC.extend("stl_E_star", np.outer(e0, decay))
                a_cell, a_mode, lead = int(action[0]), int(action[1]), float(action[2])
                q_hat, _ = tv._compute_q_hat(a_cell, a_mode, lead, hab, dyn, params,
                                             kw.get("pending_events"))
                beta_c = float(dyn.beta[a_mode]) if a_mode < len(dyn.beta) else float(dyn.beta[-1])
                after = times >= lead
                unit_supp = q_hat * beta_c * np.exp(-(times[after] - lead) / float(dyn.omega_u))
                e_target = float(cell_states[a_cell].e0) * decay[after]
                ok = unit_supp > 0.0
                # min(e_nom, kernel_self * unit_supp): kernel_self binds when e/unit_supp > kernel_self
                REC.extend("stl_kernel_self", e_target[ok] / unit_supp[ok])
            except Exception as exc:  # pragma: no cover - diagnostic only
                REC.add("instrumentation_error_stl", 1.0)
                print("instrumentation STL error:", repr(exc), file=sys.stderr)
        return orig_cv(action, cells, cell_states, hab, params, dyn, *a, **kw)

    pte.counterfactual_value = counterfactual_value

    orig_bf = ds.passes_busy_fallback_quality

    def passes_busy_fallback_quality(*, task_row, p_event_min, deltaJ_per_cost_min, eta_s_max):
        REC.add("model_deterring_busy_fallback_p_event_min", task_row.get("p_event", 0.0))
        REC.add("model_deterring_busy_fallback_deltaJ_per_cost_min", task_row.get("deltaJ_per_cost", 0.0))
        REC.add("info_busy_fallback_eta_s", task_row.get("eta_s", float("inf")))
        return orig_bf(task_row=task_row, p_event_min=p_event_min,
                       deltaJ_per_cost_min=deltaJ_per_cost_min, eta_s_max=eta_s_max)

    ds.passes_busy_fallback_quality = passes_busy_fallback_quality


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def build_job_params(system: str, mu: float, estimator: str, overrides: dict, profile: str | None) -> dict:
    from experiments.run_plan_completion import build_params

    params = build_params(system, True, float(mu), None)
    params.update(ENV)
    params["estimator_mode"] = str(estimator)
    if profile is not None:
        params["planner_profile"] = profile
    if "model_deterring_risk_scale" in overrides:
        params["model_deterring_risk_scale"] = float(overrides["model_deterring_risk_scale"])
        params["model_deterring_risk_threshold"] = float(overrides.get("model_deterring_risk_threshold", RISK_THRESHOLD))
        if "model_deterring_busy_risk_override" in overrides:
            params["model_deterring_busy_risk_override"] = float(overrides["model_deterring_busy_risk_override"])
    elif "risk_field_cut" in overrides:
        params["model_deterring_risk_scale"] = float(overrides["risk_field_cut"]) / (-math.log(1.0 - RISK_THRESHOLD))
    for key, param in (("stl_E_star", "stl_E_star"), ("stl_kernel_self", "stl_kernel_self"),
                       ("min_hotspot_score", "min_hotspot_score"),
                       ("patrol_cost_multiplier", "patrol_cost_weight"),
                       ("deterring_cost_multiplier", "deterring_cost_multiplier")):
        if key in overrides:
            params[param] = float(overrides[key])
    return params


def run_job(job: dict) -> dict:
    import planner_profiles as pp
    import DeterrentSystem as ds

    install_instrumentation()
    REC.samples = {}
    REC.taskgen_diag = {}
    overrides = dict(job.get("overrides") or {})
    REC.overrides = overrides
    REC.record_shadow_free = job["system"] != "A"  # A scores a same-state shadow; record the primary only
    profile = job.get("profile")
    profile_keys = ("model_deterring_score_margin",
                    "model_deterring_busy_fallback_p_event_min",
                    "model_deterring_busy_fallback_deltaJ_per_cost_min")
    if profile is None:
        # Always run from an explicit copy of the legacy-unit base profile so the
        # estimator-mode profile resolution never swaps in already-mapped values.
        values = pp.get_planner_profile_values(BASE_PROFILE)
        for key in profile_keys:
            if key in overrides:
                values[key] = float(overrides[key])
        pp.PLANNER_PROFILES[TMP_PROFILE] = {"description": "temporary mapping profile", "values": values,
                                             "rationale": {}}
        profile = TMP_PROFILE
    params = build_job_params(job["system"], job["mu"], job["estimator"], overrides, profile)
    params["seed"] = int(job["seed"])
    if job.get("t_end") is not None:  # smoke tests only
        params["T_end"] = float(job["t_end"])
    started = time.time()
    last = None
    for frame in ds.run_simulation_frames_persistent(**params):
        last = frame
    metrics = (last or {}).get("metrics_compact") or (last or {}).get("metrics") or {}
    numeric = {}
    for key, val in metrics.items():
        if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val)):
            numeric[key] = float(val)
    out = {
        "system": job["system"], "mu": float(job["mu"]), "seed": int(job["seed"]),
        "estimator": job["estimator"], "overrides": overrides, "profile": params.get("planner_profile"),
        "elapsed_s": time.time() - started,
        "metrics": numeric,
        "taskgen_diag": {k: float(v) for k, v in REC.taskgen_diag.items()
                         if isinstance(v, (int, float)) and math.isfinite(float(v))},
    }
    path = Path(job["out_dir"]) / f"{job['system']}_{job['mu']:.0e}_{job['seed']}"
    np.savez_compressed(str(path) + ".npz", **{k: np.asarray(v, dtype=np.float64) for k, v in REC.samples.items()})
    with open(str(path) + ".json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    return {"system": job["system"], "mu": job["mu"], "seed": job["seed"], "elapsed_s": out["elapsed_s"]}


def cmd_collect(args) -> None:
    out_dir = OUT_ROOT / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    overrides = {}
    if args.overrides:
        payload = json.loads(Path(args.overrides).read_text(encoding="utf-8"))
        overrides = dict(payload.get("mapped", payload))
        # A threshold whose consistent distribution was still empty (its stage was
        # starved by an earlier unmapped threshold) keeps its legacy value this round.
        overrides = {k: float(v) for k, v in overrides.items()
                     if (k in LEGACY_THRESHOLDS or k.startswith("model_deterring_risk_")
                         or k == "model_deterring_busy_risk_override")
                     and v is not None and math.isfinite(float(v))}
    jobs = []
    for system in args.systems:
        for mu in args.mus:
            for seed in args.seeds:
                if int(seed) >= 300:
                    raise SystemExit("evaluation seeds (>=300) must not be used for threshold mapping")
                stem = out_dir / f"{system}_{float(mu):.0e}_{int(seed)}"
                if Path(str(stem) + ".json").exists():
                    continue
                jobs.append({"system": system, "mu": float(mu), "seed": int(seed),
                             "estimator": args.estimator, "overrides": overrides,
                             "profile": args.profile, "out_dir": str(out_dir)})
    (out_dir / "collect_meta.json").write_text(json.dumps({
        "estimator": args.estimator, "overrides": overrides, "profile": args.profile,
        "systems": list(args.systems), "mus": list(args.mus), "seeds": list(args.seeds), "env": ENV,
    }, indent=1), encoding="utf-8")
    print(f"{len(jobs)} jobs -> {out_dir}", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run_job, j) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            print(f"[{i}/{len(jobs)}] {r['system']} mu={r['mu']:.0e} seed={r['seed']} "
                  f"{r['elapsed_s']:.0f}s (wall {time.time() - t0:.0f}s)", flush=True)


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------
def load_samples(tag: str, key: str, systems) -> np.ndarray:
    parts = []
    for npz in sorted((OUT_ROOT / tag).glob("*.npz")):
        if npz.name.split("_")[0] not in systems:
            continue
        with np.load(npz) as data:
            if key in data.files:
                parts.append(np.asarray(data[key], dtype=float))
    return np.concatenate(parts) if parts else np.zeros(0)


def ecdf_below(samples: np.ndarray, thr: float, op: str) -> float:
    if samples.size == 0:
        return float("nan")
    if op in ("le", "le_star"):
        return float(np.mean(samples <= thr))
    return float(np.mean(samples < thr))


def inverse_quantile(samples: np.ndarray, q: float, op: str) -> float:
    """Smallest threshold T with ecdf_below(samples, T) >= q (q in [0, 1])."""
    s = np.sort(samples)
    n = s.size
    if n == 0 or not math.isfinite(q):
        return float("nan")
    if q <= 0.0:
        # gate never rejects in legacy: keep it non-binding (strictly below every value)
        lo = s[0]
        return float(lo - abs(lo) * 1e-9 - 1e-300) if op in ("le", "le_star") else float(lo)
    if q >= 1.0:
        hi = s[-1]
        return float(hi) if op in ("le", "le_star") else float(np.nextafter(hi, np.inf))
    k = int(math.ceil(q * n))  # need at least k samples counted as "below"
    k = min(max(k, 1), n)
    v = s[k - 1]
    # With ties at v (e.g. many exact zeros) the achievable rejection rates jump
    # from P(x < v) to P(x <= v); take the boundary whose rate is closer to q.
    p_lt = float(np.mean(s < v))
    p_le = float(np.mean(s <= v))
    if op in ("le", "le_star"):
        return float(v) if abs(p_le - q) <= abs(p_lt - q) else float(np.nextafter(v, -np.inf))
    return float(np.nextafter(v, np.inf)) if abs(p_le - q) <= abs(p_lt - q) else float(v)


def cmd_map(args) -> None:
    prev = {}
    if args.previous:
        prev = json.loads(Path(args.previous).read_text(encoding="utf-8")).get("mapped", {})
    report = {"legacy_tag": args.legacy_tag, "consistent_tag": args.consistent_tag,
              "seeds": list(DEV_SEEDS), "mus": list(MUS), "systems": list(SYSTEMS),
              "thresholds": {}, "mapped": {}}
    for name, spec in LEGACY_THRESHOLDS.items():
        systems = spec["systems"]
        leg = load_samples(args.legacy_tag, name, systems)
        con = load_samples(args.consistent_tag, name, systems)
        q = ecdf_below(leg, spec["value"], spec["op"])
        q_con_at_legacy = ecdf_below(con, spec["value"], spec["op"])
        if q in (0.0, 1.0) and q_con_at_legacy == q:
            # The quantile map is set-valued at q = 0 or 1 (any value outside the
            # support). When the legacy value already lies in that set, keep it.
            mapped = float(spec["value"])
        else:
            mapped = inverse_quantile(con, q, spec["op"])
        entry = {
            "legacy_value": spec["value"], "op": spec["op"], "systems": list(systems),
            "q": q, "mapped_value": mapped, "q_consistent_at_legacy_value": q_con_at_legacy,
            "n_legacy": int(leg.size), "n_consistent": int(con.size),
            "q_check_consistent": ecdf_below(con, mapped, spec["op"]),
            "legacy_p05_p50_p95": [float(np.quantile(leg, p)) for p in (0.05, 0.5, 0.95)] if leg.size else None,
            "consistent_p05_p50_p95": [float(np.quantile(con, p)) for p in (0.05, 0.5, 0.95)] if con.size else None,
        }
        entry["q_legacy_by_system"] = {
            s: ecdf_below(load_samples(args.legacy_tag, name, (s,)), spec["value"], spec["op"]) for s in systems
        }
        entry["q_consistent_mapped_by_system"] = {
            s: ecdf_below(load_samples(args.consistent_tag, name, (s,)), mapped, spec["op"]) for s in systems
        }
        if name in prev and math.isfinite(prev[name]) and prev[name] != 0.0:
            entry["rel_change_vs_previous"] = abs(mapped - prev[name]) / abs(prev[name])
        report["thresholds"][name] = entry
        report["mapped"][name] = mapped
    # Positivity: risk_scale, and the travel-cost weights, are positive by construction
    # (the unit-free risk_threshold 0.35 is not mapped). When the mapped value is <= 0 the
    # q-quantile is not attainable and the nearest feasible setting is the limit 0+:
    # risk_scale at TaskGenerator's floor 1e-12 (rejects exactly the non-positive field
    # scores) and cost weight 1e-300 (utility > 0 iff predicted_deltaJ > 0).
    for name, floor in (("risk_field_cut", POSITIVE_FLOOR["risk_field_cut"]),
                        ("deterring_cost_multiplier", POSITIVE_FLOOR["cost"]),
                        ("patrol_cost_multiplier", POSITIVE_FLOOR["cost"])):
        val = report["mapped"][name]
        entry = report["thresholds"][name]
        if math.isfinite(val) and val <= 0.0:
            con = load_samples(args.consistent_tag, name, LEGACY_THRESHOLDS[name]["systems"])
            report["mapped"][name] = floor
            entry["mapped_value"] = floor
            entry["unconstrained_mapped_value"] = val
            entry["q_check_consistent"] = ecdf_below(con, floor, LEGACY_THRESHOLDS[name]["op"])
            entry["representation"] = (f"mapped value {val:.4g} <= 0 is infeasible; limit 0+ used "
                                       f"(achieved rate {entry['q_check_consistent']:.4f} vs q {entry['q']:.4f})")
            entry["q_consistent_mapped_by_system"] = {
                s: ecdf_below(load_samples(args.consistent_tag, name, (s,)), floor, LEGACY_THRESHOLDS[name]["op"])
                for s in LEGACY_THRESHOLDS[name]["systems"]
            }
        else:
            entry["representation"] = "exact"
    cut = report["mapped"]["risk_field_cut"]
    if math.isfinite(cut):
        report["mapped"]["model_deterring_risk_scale"] = (
            1.0e-12 if cut <= POSITIVE_FLOOR["risk_field_cut"] else cut / (-math.log(1.0 - RISK_THRESHOLD))
        )
    # busy_risk_field is not a free parameter: the busy override (0.20) is unit free and shares
    # risk_scale, so its consistent rate is only reported.
    report["mapped"].pop("busy_risk_field", None)
    busy = report["thresholds"]["busy_risk_field"]
    scale = report["mapped"].get("model_deterring_risk_scale", 1.0e-4)
    busy_con = load_samples(args.consistent_tag, "busy_risk_field", SYSTEMS)
    busy["mapped_value"] = None
    busy["representation"] = "derived (busy override 0.20 unit free; uses mapped risk_scale)"
    busy["q_check_consistent"] = ecdf_below(busy_con, -scale * math.log(1.0 - 0.20), "lt")
    # informational: q of the unchanged busy risk override (0.20) under each estimator
    for tag_key, tag in (("legacy", args.legacy_tag), ("consistent", args.consistent_tag)):
        busy = load_samples(tag, "busy_risk_field", SYSTEMS)
        scale = 1e-4 if tag_key == "legacy" else report["mapped"]["model_deterring_risk_scale"]
        cut = -scale * math.log(1.0 - 0.20)
        report.setdefault("info", {})[f"busy_risk_override_q_{tag_key}"] = ecdf_below(busy, cut, "lt")
        report["info"][f"busy_risk_n_{tag_key}"] = int(busy.size)
        for kind in ("det", "patrol"):
            for field in ("utility", "predicted_deltaJ", "cost_eta"):
                key = f"info_generated_{kind}_{field}"
                for s in SYSTEMS:
                    vals = load_samples(tag, key, (s,))
                    if vals.size:
                        report["info"][f"{key}_{s}_{tag_key}_p05_p50_p95"] = [
                            float(np.quantile(vals, p)) for p in (0.05, 0.5, 0.95)]
                        if field == "utility":
                            report["info"][f"{key}_{s}_{tag_key}_frac_positive"] = float(np.mean(vals > 0.0))
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    for name, e in report["thresholds"].items():
        rc = e.get("rel_change_vs_previous")
        print(f"{name:52s} legacy={e['legacy_value']:.4g} q={e['q']:.4f} mapped={(e['mapped_value'] if e['mapped_value'] is not None else float('nan')):.4g} "
              f"n=({e['n_legacy']},{e['n_consistent']})" + (f" rel_change={rc:.4f}" if rc is not None else ""))
    print(json.dumps(report.get("info", {}), indent=1))


# ---------------------------------------------------------------------------
# Validation table
# ---------------------------------------------------------------------------
VALIDATION_FIELDS = [
    ("pred_generated", ("metrics", "predictive_generated_total")),
    ("pred_admitted", ("metrics", "predictive_admitted_total")),
    ("pred_completed", ("metrics", "predictive_completed_total")),
    ("model_det_generated", ("taskgen_diag", "model_deterring_generated")),
    ("hotspot_patrol_generated", ("npz_count", "info_generated_patrol_utility")),
    ("det_vs_patrol_margin_checks", ("npz_count", "model_deterring_score_margin")),
    ("reactive_completed", ("metrics", "reactive_completed_total")),
    ("reactive_generated", ("metrics", "reactive_generated_total")),
    ("vwe", ("metrics", "value_weighted_exposure")),
]


def cmd_validate(args) -> None:
    rows = []
    for tag in args.tags:
        for js in sorted((OUT_ROOT / tag).glob("*.json")):
            if js.name == "collect_meta.json":
                continue
            d = json.loads(js.read_text(encoding="utf-8"))
            row = {"tag": tag, "system": d["system"], "mu": d["mu"], "seed": d["seed"]}
            for name, (src, key) in VALIDATION_FIELDS:
                if src == "npz_count":
                    with np.load(str(js)[:-5] + ".npz") as data:
                        row[name] = float(data[key].size) if key in data.files else 0.0
                else:
                    row[name] = float(d.get(src, {}).get(key, float("nan")))
            rows.append(row)
    table = {}
    for r in rows:
        k = (r["system"], r["mu"], r["tag"])
        table.setdefault(k, []).append(r)
    names = [n for n, _ in VALIDATION_FIELDS]
    lines = ["| system | mu | estimator/tag | n | " + " | ".join(names) + " |",
             "|---|---|---|---|" + "|".join("---" for _ in names) + "|"]
    summary = []
    for (system, mu, tag) in sorted(table, key=lambda k: (SYSTEMS.index(k[0]), k[1], args.tags.index(k[2]))):
        rs = table[(system, mu, tag)]
        means = {n: float(np.nanmean([r[n] for r in rs])) for n in names}
        summary.append({"system": system, "mu": mu, "tag": tag, "n": len(rs), **means})
        cells = []
        for n in names:
            v = means[n]
            cells.append(f"{v:.0f}" if n == "vwe" else f"{v:.1f}")
        lines.append(f"| {system} | {mu:.0e} | {tag} | {len(rs)} | " + " | ".join(cells) + " |")
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(json.dumps({"rows": summary, "markdown": text}, indent=1), encoding="utf-8")


PROFILE_KEY = {  # mapped threshold -> planner profile / simulator key
    "min_hotspot_score": "min_hotspot_score",
    "model_deterring_risk_scale": "model_deterring_risk_scale",
    "model_deterring_score_margin": "model_deterring_score_margin",
    "model_deterring_busy_fallback_p_event_min": "model_deterring_busy_fallback_p_event_min",
    "model_deterring_busy_fallback_deltaJ_per_cost_min": "model_deterring_busy_fallback_deltaJ_per_cost_min",
    "stl_E_star": "stl_E_star",
    "stl_kernel_self": "stl_kernel_self",
    "deterring_cost_multiplier": "deterring_cost_multiplier",
    "patrol_cost_multiplier": "patrol_cost_weight",
}


def cmd_finalize(args) -> None:
    """Write the provenance JSON from the iteration maps (last one is final)."""
    maps = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.maps]
    final = maps[-1]
    history = {name: [m["mapped"].get(name) for m in maps] for name in PROFILE_KEY}
    convergence = {}
    for name, vals in history.items():
        a, b = vals[-2], vals[-1]
        if a is None or b is None:
            rel = None
        elif a == b:
            rel = 0.0
        else:
            rel = abs(b - a) / max(abs(a), abs(b))
        convergence[name] = rel
    payload = {
        "description": ("Quantile mapping of model-unit planner thresholds from the legacy to the "
                        "consistent SESTPP estimator (experiments/consistent_threshold_mapping.py)."),
        "dev_seeds": list(DEV_SEEDS), "mus": list(MUS), "systems": list(SYSTEMS),
        "environment": ENV, "configuration": "run_plan_completion._ladder_params (paper), hab_on",
        "base_profile": BASE_PROFILE,
        "iteration_maps": [str(p) for p in args.maps],
        "thresholds": final["thresholds"],
        "mapped_history": history,
        "final_relative_change": convergence,
        "converged_1pct": {k: (v is not None and v < 0.01) for k, v in convergence.items()},
        "profile_values": {PROFILE_KEY[k]: final["mapped"][k] for k in PROFILE_KEY},
        "info": final.get("info", {}),
    }
    Path(args.out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(json.dumps({"profile_values": payload["profile_values"], "final_relative_change": convergence}, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--estimator", choices=("legacy", "consistent"), required=True)
    c.add_argument("--tag", required=True)
    c.add_argument("--overrides", default=None, help="JSON with a 'mapped' block (output of map)")
    c.add_argument("--profile", default=None, help="planner profile to force (default: system default)")
    c.add_argument("--systems", nargs="+", default=list(SYSTEMS))
    c.add_argument("--mus", nargs="+", type=float, default=list(MUS))
    c.add_argument("--seeds", nargs="+", type=int, default=list(DEV_SEEDS))
    c.add_argument("--workers", type=int, default=20)
    m = sub.add_parser("map")
    m.add_argument("--legacy-tag", required=True)
    m.add_argument("--consistent-tag", required=True)
    m.add_argument("--previous", default=None)
    m.add_argument("--out", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--tags", nargs="+", required=True)
    v.add_argument("--out", default=None)
    f = sub.add_parser("finalize")
    f.add_argument("--maps", nargs="+", required=True, help="iteration map JSONs in order")
    f.add_argument("--out", required=True)
    args = ap.parse_args()
    {"collect": cmd_collect, "map": cmd_map, "validate": cmd_validate,
     "finalize": cmd_finalize}[args.cmd](args)


if __name__ == "__main__":
    main()
