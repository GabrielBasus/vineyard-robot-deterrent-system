"""
refit_sestpp_new_units.py -- HARNESS-TRUTH refit (SUPERSEDED 2026-10-28, audit round 2: the refit
must target the evaluation simulator truth; kept for provenance of the superseded run).

Original description: refit the calibrated legacy SESTPP constants under the unit fix.

User decisions 2026-10-28 (D, D1-D5):
  * same machinery and objective as experiments/run_sestpp_calibration_sweep.py:
    diagnostics/diagnostic_field_truth_compare.simulate_one_run (synthetic harness truth,
    replayed interventions), stages prediction-only -> proposed -> joint 3 x 3;
    prediction-only ranked by (field logloss, field Brier, NLL) of the prediction-only model,
    proposed by (field logloss, Brier, NLL) of the proposed model, joint by
    (guardrail satisfied, proposed logloss, Brier, NLL) with the original guardrail
    (pooled mean deltas proposed minus prediction-only of logloss, Brier and NLL <= 1e-12);
  * evaluation grid 60 x 48 on 500 x 500, legacy_stamp_units="mass_per_cell";
  * dev seeds 200-209 only, THREE harness truths mu_true x {0.2, 1, 4} (mirroring the
    loads), metrics pooled (mean over the 30 truth x seed runs);
  * search: cyclic coordinate line search on a log grid (run with two cycle orders,
    stamp amplitudes first and the listed order, from the same start; the better final
    objective is kept) (factor 2, 7 points centred on the
    current value); a line whose optimum is at an end is extended until it is interior;
    0 is a hard lower bound for alpha_cross and bg_ema (never widened past); cycles repeat
    until nothing moves; then a 3^k local check over the moved parameters (factor 2);
    if the local check improves, the cycles resume from the improved point;
  * start: the EQUIVALENT start = calibration best_config C001 with every stamp amplitude
    (alpha_in, alpha_inhib, alpha_cross) multiplied by the node area dx * dy, which reproduces
    the old-unit model exactly (tests/test_legacy_stamp_units.py);
  * all ten constants are swept (D2), including omega_inhib, alpha_cross and bg_ema;
  * no divergence re-rank stage (D4); the prediction-only model is refitted too (D5).

The prediction-only model receives no intervention replay, so its alpha_inhib, omega_inhib
and feedback scales have no effect; it is swept over sigma, omega, alpha_in, alpha_cross,
mu_base and bg_ema (the original shared stage).  The harness never stamps cross events, so
alpha_cross is not identifiable (flat objective); ties keep the current value.

Memory: before every batch the scheduler waits for >= 12 GB available (poll 300 s).
Resumable: every evaluated (stage, config) is cached in <out>/evals.jsonl.

Usage:
  py -3.10 -m experiments.refit_sestpp_new_units --workers 8
  py -3.10 -m experiments.refit_sestpp_new_units --check-equivalence
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from itertools import product
from pathlib import Path

os.environ.setdefault("DETERRENT_TELEMETRY", "0")
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from diagnostics.diagnostic_field_truth_compare import SubsystemConfig, simulate_one_run

NX, NY, W, H = 60, 48, 500.0, 500.0
NODE_AREA = (W / (NX - 1)) * (H / (NY - 1))
DEV_SEEDS = tuple(range(200, 210))
TRUTH_SCALES = (0.2, 1.0, 4.0)
BASE_MU_TRUE = float(SubsystemConfig.mu_true)
UNITS = "mass_per_cell"
MIN_FREE_GB = 12.0
POLL_S = 300.0
STEP = 2.0
HALF_WIDTH = 3          # 7-point lines: x * 2^-3 .. x * 2^3
TIE_RTOL = 1e-9         # relative tie tolerance on the primary metric (pooled logloss)
MAX_EXT_STEPS = 30      # a line spans at most 2^60 before it is reported unbounded

# Calibration best_config C001 (results/sestpp_calibration_sweep manifest), old units.
C001_PROPOSED = {"sigma": 10.0, "omega": 450.0, "omega_inhib": 900.0, "alpha_in": 0.15, "alpha_cross": 0.0,
                 "alpha_inhib": 0.9, "mu_base": 2.5e-5, "bg_ema": 1e-7,
                 "feedback_sigma_scale": 0.875, "feedback_omega_scale": 2.0}
C001_PREDICTION = {"sigma": 10.0, "omega": 450.0, "alpha_in": 0.15, "alpha_cross": 0.0, "mu_base": 2.5e-5,
                   "bg_ema": 1e-7}
# prediction-only stage of the original sweep: alpha_inhib / omega_inhib fixed (no replay)
PRED_FIXED = {"omega_inhib": 900.0, "alpha_inhib": 0.45, "feedback_sigma_scale": 1.0, "feedback_omega_scale": 1.0}
STAMP_KEYS = ("alpha_in", "alpha_inhib", "alpha_cross")
ZERO_BOUNDED = ("alpha_cross", "bg_ema")
# bg_ema is an EMA weight (mu <- (1 - b) mu + b lam): 1 is a hard upper bound
UPPER_BOUND = {"bg_ema": 1.0}
PRED_PARAMS = ("sigma", "omega", "alpha_in", "alpha_cross", "mu_base", "bg_ema")
PROP_PARAMS = ("sigma", "omega", "omega_inhib", "alpha_in", "alpha_cross", "alpha_inhib", "mu_base", "bg_ema",
               "feedback_sigma_scale", "feedback_omega_scale")
METRIC_KEYS = ("prediction_only_field_logloss", "prediction_only_field_brier", "prediction_only_nll",
               "proposed_field_logloss", "proposed_field_brier", "proposed_nll",
               "delta_field_logloss_proposed_minus_prediction", "delta_field_brier_proposed_minus_prediction",
               "delta_nll_proposed_minus_prediction", "truth_events")


def equivalent_start(params: dict) -> dict:
    return {k: (float(v) * NODE_AREA if k in STAMP_KEYS else float(v)) for k, v in params.items()}


def _r(v: float) -> float:
    return float(f"{float(v):.10g}")


def config_key(stage: str, pred: dict, prop: dict) -> str:
    return json.dumps({"stage": stage, "pred": {k: _r(v) for k, v in sorted(pred.items())},
                       "prop": {k: _r(v) for k, v in sorted(prop.items())}}, sort_keys=True)


def make_cfg(pred: dict, prop: dict, mu_scale: float, seed: int, units: str = UNITS) -> SubsystemConfig:
    kw = dict(NX=NX, NY=NY, W=W, H=H, runs=1, seed_start=int(seed), mu_true=BASE_MU_TRUE * float(mu_scale),
              model_legacy_stamp_units=units)
    for prefix, p in (("prediction_only", pred), ("proposed", prop)):
        for k, v in p.items():
            name = f"{prefix}_model_{k}"
            if not hasattr(SubsystemConfig, name):
                raise KeyError(name)
            kw[name] = float(v)
    return SubsystemConfig(**kw)


def _run(job):
    pred, prop, mu_scale, seed, units = job
    if int(seed) >= 300:
        raise ValueError("evaluation seeds (>= 300) are never used for calibration")
    res = simulate_one_run(0, int(seed), make_cfg(pred, prop, mu_scale, seed, units))
    pm = res["paired_metrics"]
    return {k: float(pm[k]) for k in METRIC_KEYS}


def free_gb() -> float:
    import psutil
    return psutil.virtual_memory().available / 1e9


def wait_memory(log):
    while True:
        g = free_gb()
        if g >= MIN_FREE_GB:
            return g
        log(f"[mem] {g:.1f} GB available < {MIN_FREE_GB} GB; waiting {POLL_S:.0f} s")
        time.sleep(POLL_S)


class Evaluator:
    def __init__(self, out: Path, workers: int, log):
        self.out = out
        self.workers = int(workers)
        self.log = log
        self.cache_path = out / "evals.jsonl"
        self.cache: dict[str, dict] = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.cache[row["key"]] = row
        self.pool = ProcessPoolExecutor(max_workers=self.workers)
        from experiments.run_plan_completion import code_version
        self.version = code_version()   # commit, dirty flag, diff hash, machine (user 2026-10-28, 3b)
        self.n_runs = 0

    def close(self):
        self.pool.shutdown()

    def evaluate(self, stage: str, configs: list[tuple[dict, dict]]) -> list[dict]:
        todo = []
        for pred, prop in configs:
            key = config_key(stage, pred, prop)
            if key not in self.cache and key not in [k for k, _, _ in todo]:
                todo.append((key, pred, prop))
        if todo:
            wait_memory(self.log)
            jobs, owners = [], []
            for key, pred, prop in todo:
                for s in TRUTH_SCALES:
                    for seed in DEV_SEEDS:
                        jobs.append((pred, prop, s, seed, UNITS))
                        owners.append(key)
            t0 = time.time()
            results = list(self.pool.map(_run, jobs, chunksize=4))
            self.n_runs += len(jobs)
            per = {}
            for key, job, r in zip(owners, jobs, results):
                per.setdefault(key, []).append({"mu_scale": job[2], "seed": job[3], **r})
            with self.cache_path.open("a", encoding="utf-8") as fh:
                for key, pred, prop in todo:
                    runs = per[key]
                    pooled = {k: float(np.mean([r[k] for r in runs])) for k in METRIC_KEYS}
                    row = {"key": key, "stage": stage, "pred": pred, "prop": prop, "pooled": pooled, "runs": runs,
                           **self.version}
                    self.cache[key] = row
                    fh.write(json.dumps(row) + "\n")
            self.log(f"[eval] {stage}: {len(todo)} configs, {len(jobs)} runs, {time.time() - t0:.0f} s")
        return [self.cache[config_key(stage, pred, prop)] for pred, prop in configs]


def objective(stage: str, row: dict) -> tuple:
    p = row["pooled"]
    if stage == "prediction":
        return (p["prediction_only_field_logloss"], p["prediction_only_field_brier"], p["prediction_only_nll"])
    if stage == "proposed":
        return (p["proposed_field_logloss"], p["proposed_field_brier"], p["proposed_nll"])
    raise ValueError(stage)


def guardrail_ok(row: dict) -> bool:
    p = row["pooled"]
    return all(np.isfinite(p[k]) and p[k] <= 1e-12 for k in (
        "delta_field_logloss_proposed_minus_prediction", "delta_field_brier_proposed_minus_prediction",
        "delta_nll_proposed_minus_prediction"))


class Search:
    """Cyclic coordinate line search (log grid, factor 2) + 3^k local check for one stage."""

    def __init__(self, stage: str, names: tuple, start: dict, fixed_other: dict, ev: Evaluator, log):
        self.stage, self.names, self.ev, self.log = stage, names, ev, log
        self.x = dict(start)
        self.other = dict(fixed_other)
        self.moved: set[str] = set()
        self.history = []
        self.interior: dict[str, str] = {}

    def _pair(self, x: dict):
        if self.stage == "prediction":
            pred = {k: x[k] for k in PRED_PARAMS}
            # original shared stage: the proposed model mirrors the prediction-only params
            prop = {**{k: x[k] for k in PRED_PARAMS}, **PRED_FIXED}
            return pred, prop
        return dict(self.other), {k: x[k] for k in PROP_PARAMS}

    def _eval_points(self, points: list[dict]) -> list[tuple[tuple, dict]]:
        rows = self.ev.evaluate(self.stage, [self._pair(p) for p in points])
        return [(objective(self.stage, r), r) for r in rows]

    def _ladder(self, name: str, lo_k: int, hi_k: int) -> list[float]:
        c = self.x[name]
        if c == 0.0:
            base = self.x["alpha_in"] if name == "alpha_cross" else 1e-7
            return [base * STEP ** k for k in range(lo_k, hi_k + 1)]
        return [c * STEP ** k for k in range(lo_k, hi_k + 1)]

    def line(self, name: str) -> bool:
        cur = self.x[name]
        zero_b = name in ZERO_BOUNDED
        if cur == 0.0:
            lo_k, hi_k = -6, 0
        else:
            lo_k, hi_k = -HALF_WIDTH, HALF_WIDTH
        while True:
            ub = UPPER_BOUND.get(name)
            ladder = [v for v in self._ladder(name, lo_k, hi_k) if ub is None or v < ub]
            vals = sorted(set(ladder) | ({0.0} if zero_b else set()) | ({ub} if ub is not None and max(ladder) * STEP > ub else set()) | {cur})
            pts = [{**self.x, name: v} for v in vals]
            scored = self._eval_points(pts)
            cur_score = next(s for (s, _), v in zip(scored, vals) if v == cur)
            # exact ties (a plateau, e.g. a kernel narrower than the grid acts as a point stamp)
            # go to the current value, else to the tied value nearest to it (log distance), so a
            # plateau never drags the search to the end of the line
            # (relative tolerance TIE_RTOL on the primary metric: when a parameter has no
            # effect, e.g. sigma or omega with alpha_in ~ 0, differences at the 1e-12 level
            # must not move it)
            best_score = min(sc for sc, _ in scored)
            tied = [i for i in range(len(vals))
                    if abs(scored[i][0][0] - best_score[0]) <= TIE_RTOL * abs(best_score[0])]

            def _dist(i):
                v = vals[i]
                if v == cur:
                    return -1.0
                if v == 0.0 or cur == 0.0:
                    return float("inf")
                return abs(math.log(v / cur))

            best_i = min(tied, key=_dist)
            best_v = vals[best_i]
            positive = [v for v in vals if v > 0.0]
            at_top = best_v == max(vals)
            at_bottom_pos = best_v > 0.0 and best_v == min(positive)
            if best_v == 0.0 and zero_b:
                status = "zero_bound"
                break
            if hi_k - lo_k > 2 * MAX_EXT_STEPS:
                status = "unbounded_" + ("up" if at_top else "down")
                self.log(f"  [{self.stage}] {name}: still at an end after {hi_k - lo_k} steps; stopping")
                break
            if ub is not None and best_v == ub:
                status = "upper_bound"
                break
            if at_top:
                hi_k += HALF_WIDTH
                self.log(f"  [{self.stage}] {name}: optimum {best_v:.4g} at upper end, extending")
                continue
            if at_bottom_pos:
                lo_k -= HALF_WIDTH
                self.log(f"  [{self.stage}] {name}: optimum {best_v:.4g} at lower end, extending")
                continue
            status = "interior"
            break
        self.interior[name] = status
        changed = best_v != cur
        self.log(f"  [{self.stage}] {name}: {cur:.6g} -> {best_v:.6g} ({status}) "
                 f"obj {cur_score[0]:.6f} -> {scored[best_i][0][0]:.6f}")
        self.history.append({"param": name, "from": cur, "to": best_v, "status": status,
                             "obj_from": list(cur_score), "obj_to": list(scored[best_i][0])})
        if changed:
            self.x[name] = best_v
            self.moved.add(name)
        return changed

    def cycles(self, max_cycles: int = 20) -> None:
        for c in range(1, max_cycles + 1):
            self.log(f"[{self.stage}] cycle {c}")
            changed = [n for n in self.names if self.line(n)]
            if not changed:
                self.log(f"[{self.stage}] cycle {c}: nothing moved")
                return
        raise RuntimeError(f"{self.stage}: no convergence in {max_cycles} cycles")

    def local_check(self, max_configs: int) -> bool:
        moved = [n for n in self.names if n in self.moved]
        axes = []
        for n in moved:
            c = self.x[n]
            if c == 0.0:
                axes.append([0.0, self._ladder(n, 0, 0)[0]])
            else:
                axes.append([c / STEP, c, c * STEP])
        n_cfg = int(np.prod([len(a) for a in axes])) if axes else 1
        self.log(f"[{self.stage}] local 3^k check over {moved}: {n_cfg} configs")
        if n_cfg > max_configs:
            raise SystemExit(f"[{self.stage}] local check needs {n_cfg} configs > --max-local-configs "
                             f"{max_configs}; stopping for a decision (state cached in evals.jsonl)")
        pts = [{**self.x, **dict(zip(moved, combo))} for combo in product(*axes)]
        scored = self._eval_points(pts)
        cur_score = objective(self.stage, self.ev.evaluate(self.stage, [self._pair(self.x)])[0])
        best_i = min(range(len(pts)), key=lambda i: scored[i][0])
        if scored[best_i][0][0] < cur_score[0] - TIE_RTOL * abs(cur_score[0]):
            self.log(f"[{self.stage}] local check improved {cur_score[0]:.6f} -> {scored[best_i][0][0]:.6f}")
            for n in moved:
                if pts[best_i][n] != self.x[n]:
                    self.x[n] = pts[best_i][n]
            return True
        self.log(f"[{self.stage}] local check: current point is the best of {len(pts)}")
        return False

    def run(self, max_local: int) -> dict:
        while True:
            self.cycles()
            if not self.local_check(max_local):
                break
        best = self.ev.evaluate(self.stage, [self._pair(self.x)])[0]
        return {"x": dict(self.x), "moved": sorted(self.moved), "objective": list(objective(self.stage, best)),
                "line_status": dict(self.interior), "history": self.history}

    def top(self, n: int) -> list[dict]:
        rows = [r for r in self.ev.cache.values() if r["stage"] == self.stage]
        rows.sort(key=lambda r: (objective(self.stage, r), r["key"]))
        return rows[:n]


def check_equivalence(log) -> dict:
    """Old units with C001 == new units with the equivalent start (one truth, two seeds)."""
    pred_old, prop_old = dict(C001_PREDICTION), dict(C001_PROPOSED)
    pred_new, prop_new = equivalent_start(pred_old), equivalent_start(prop_old)
    out = {}
    for seed in DEV_SEEDS[:2]:
        a = _run((pred_old, prop_old, 1.0, seed, "density"))
        b = _run((pred_new, prop_new, 1.0, seed, UNITS))
        rel = {k: abs(a[k] - b[k]) / max(abs(a[k]), 1e-300) for k in METRIC_KEYS}
        out[seed] = {"old": a, "new": b, "max_rel_diff": max(rel.values())}
        log(f"[equiv] seed {seed}: max relative difference {max(rel.values()):.3e}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results/sestpp_refit_new_units")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-local-configs", type=int, default=800)
    ap.add_argument("--check-equivalence", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = (out / "refit.log").open("a", encoding="utf-8")

    def log(msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    eq = check_equivalence(log)
    from experiments.run_plan_completion import code_version
    (out / "equivalence.json").write_text(json.dumps({**code_version(), "runs": eq}, indent=2), encoding="utf-8")
    if args.check_equivalence:
        return
    ev = Evaluator(out, args.workers, log)
    try:
        start_pred = equivalent_start(C001_PREDICTION)
        start_prop = equivalent_start(C001_PROPOSED)
        # objective at the equivalent start (the old fit expressed in the new units)
        # Two cycle orders from the same start (coordinate search is order dependent: with
        # the old-unit amplitudes x node area, shrinking omega first switches the excitation
        # off before alpha_in can adapt).  The better final objective is kept; both reported.
        def _orders(names):
            amp_first = tuple(n for n in STAMP_KEYS if n in names) + tuple(n for n in names if n not in STAMP_KEYS)
            return {"amplitudes_first": amp_first, "listed": tuple(names)}

        def _stage(stage, names, start, other):
            runs = {}
            for label, order in _orders(names).items():
                log(f"[{stage}] order {label}: {order}")
                srch = Search(stage, order, start, other, ev, log)
                runs[label] = (srch, srch.run(args.max_local_configs))
            best_label = min(runs, key=lambda k: tuple(runs[k][1]["objective"]))
            srch, res = runs[best_label]
            res = dict(res, order=best_label,
                       by_order={k: {"x": v[1]["x"], "objective": v[1]["objective"], "moved": v[1]["moved"],
                                     "line_status": v[1]["line_status"]} for k, v in runs.items()})
            return srch, res

        s_pred0 = Search("prediction", PRED_PARAMS, start_pred, {}, ev, log)
        start_pred_obj = objective("prediction", ev.evaluate("prediction", [s_pred0._pair(start_pred)])[0])
        s_pred, res_pred = _stage("prediction", PRED_PARAMS, start_pred, {})
        log(f"[prediction] done ({res_pred['order']}): {res_pred['x']} obj {res_pred['objective']}")

        other = {k: res_pred["x"][k] for k in PRED_PARAMS}
        s_prop0 = Search("proposed", PROP_PARAMS, start_prop, other, ev, log)
        start_prop_obj = objective("proposed", ev.evaluate("proposed", [s_prop0._pair(start_prop)])[0])
        s_prop, res_prop = _stage("proposed", PROP_PARAMS, start_prop, other)
        log(f"[proposed] done ({res_prop['order']}): {res_prop['x']} obj {res_prop['objective']}")

        # joint stage: top-3 x top-3 as the original shortlist, ranked with the guardrail
        top_pred = s_pred.top(3)
        top_prop = s_prop.top(3)
        joint_cfgs = [(dict(rp["pred"]), dict(rq["prop"])) for rp in top_pred for rq in top_prop]
        joint_rows = ev.evaluate("joint", joint_cfgs)
        ranked = sorted(joint_rows, key=lambda r: (not guardrail_ok(r), objective("proposed", r), r["key"]))
        best = ranked[0]
        # equivalent start in the joint setting (old fit, new units)
        start_joint = ev.evaluate("joint", [(start_pred, start_prop)])[0]
        result = {
            **ev.version,
            "decision": "user 2026-10-28 D (D1-D5)",
            "grid": [NX, NY], "units": UNITS, "node_area_m2": NODE_AREA, "dev_seeds": list(DEV_SEEDS),
            "truth_mu_true": [BASE_MU_TRUE * s for s in TRUTH_SCALES],
            "equivalent_start": {"prediction": start_pred, "proposed": start_prop},
            "equivalent_start_objective": {"prediction": list(start_pred_obj), "proposed": list(start_prop_obj),
                                           "joint_pooled": start_joint["pooled"],
                                           "joint_guardrail": guardrail_ok(start_joint)},
            "prediction_stage": res_pred, "proposed_stage": res_prop,
            "joint_ranking": [{"pred": r["pred"], "prop": r["prop"], "guardrail": guardrail_ok(r),
                               "pooled": r["pooled"]} for r in ranked],
            "best": {"prediction_only": best["pred"], "proposed": best["prop"], "guardrail": guardrail_ok(best),
                     "pooled": best["pooled"]},
            "deployed_constants": {
                "model_sigma": best["prop"]["sigma"], "model_omega": best["prop"]["omega"],
                "model_omega_inhib": best["prop"]["omega_inhib"], "model_alpha_in": best["prop"]["alpha_in"],
                "model_alpha_cross": best["prop"]["alpha_cross"], "model_alpha_inhib": best["prop"]["alpha_inhib"],
                "model_mu_base": best["prop"]["mu_base"], "model_bg_ema": best["prop"]["bg_ema"],
                "model_feedback_sigma_scale": best["prop"]["feedback_sigma_scale"],
                "model_feedback_omega_scale": best["prop"]["feedback_omega_scale"]},
            "runs_executed": ev.n_runs,
        }
        (out / "refit_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        log(f"[joint] best {result['deployed_constants']} guardrail {result['best']['guardrail']}")
    finally:
        ev.close()


if __name__ == "__main__":
    main()
