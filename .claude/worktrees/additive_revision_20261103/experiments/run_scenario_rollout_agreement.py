"""
run_scenario_rollout_agreement.py -- agreement of the scenario-rollout engine's B5 with real B5 runs.

The real simulator cannot be restarted from a saved state, so the comparison is
done window by window: during real B5 runs (paper configuration) the engine is
started from snapshots taken at fixed times (full observability, planner
parameters equal to the truth) and predicts the distribution of the next
H seconds.  Each real window is one draw from the distribution the engine
should reproduce, so z = (real - engine mean) / engine sd should be ~N(0, 1).

Usage:
  py -3.10 experiments/run_scenario_rollout_agreement.py --loads 2e-5 4e-4 --seeds 8 --out results/scenario_rollout_agreement
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("DETERRENT_TELEMETRY", "0")
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np


def _one_run(args):
    mu, seed, starts, H, n_scen, t_end = args
    import DeterrentSystem as ds
    from experiments.run_plan_completion import build_params
    from habituation_stl import scenario_rollout as sr

    p = build_params("B5", True, mu, t_end)
    p["seed"] = int(seed)
    gen = ds.run_simulation_frames_persistent(**p)
    snaps = {}
    L = None
    t_wall = time.time()
    for _fr in gen:
        L = gen.gi_frame.f_locals
        t = float(L["t"])
        if t in starts:
            snaps[t] = sr.snapshot_from_sim_locals(L, horizon_s=H)
        if t >= max(starts) + H:
            break
    real_wall = time.time() - t_wall
    log = list(L["exposure_event_log"])
    done = list(L["completed_tasks"])
    dets = list(L["recent_detections"])
    rows = []
    for t0, snap in sorted(snaps.items()):
        lo, hi = t0, t0 + H
        real_exp = sum(w for (te, w) in log if lo < te <= hi)
        real_react = sum(1 for tr in done if lo < float(tr.get("t_done", -1)) <= hi
                         and str(tr.get("origin", "")) == "detection")
        real_pred = sum(1 for tr in done if lo < float(tr.get("t_done", -1)) <= hi
                        and str(tr.get("origin", "")) != "detection" and str(tr.get("type")) == "deterring")
        real_det = sum(1 for (_x, _y, te) in dets if lo < te <= hi)
        t1 = time.time()
        res = sr.run_policy(snap, sr.NOOP, n_scenarios=n_scen, seed=int(seed) * 1000 + int(t0))
        eng_wall = time.time() - t1
        J = np.array([r["J"] for r in res])
        cnt = np.array([r["counted_exposure"] for r in res])
        rc = np.array([r["reactive_completed"] for r in res])
        pc = np.array([sum(1 for iv in r["interventions"] if iv["source"] == "model_scored") for r in res])
        dc = np.array([r["detections"] for r in res])
        rows.append({
            "mu": mu, "seed": seed, "t0": t0, "H": H,
            "real_exposure": real_exp, "eng_J_mean": float(J.mean()), "eng_J_sd": float(J.std(ddof=1)),
            "eng_counted_mean": float(cnt.mean()), "eng_counted_sd": float(cnt.std(ddof=1)),
            "real_reactive_completed": real_react, "eng_reactive_mean": float(rc.mean()), "eng_reactive_sd": float(rc.std(ddof=1)),
            "real_predictive_completed": real_pred, "eng_predictive_mean": float(pc.mean()), "eng_predictive_sd": float(pc.std(ddof=1)),
            "real_detections": real_det, "eng_detections_mean": float(dc.mean()), "eng_detections_sd": float(dc.std(ddof=1)),
            "engine_wall_s": eng_wall, "real_wall_s": real_wall,
        })
    return rows


def _z(rows, real, mean, sd):
    z = []
    for r in rows:
        s = math.sqrt(r[sd] ** 2 * (1 + 1.0 / 16) + 1e-12)
        z.append((r[real] - r[mean]) / s if s > 0 else 0.0)
    return np.array(z)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loads", type=float, nargs="+", default=[2e-5, 4e-4])
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--seed-start", type=int, default=200)
    ap.add_argument("--H", type=float, default=300.0)
    ap.add_argument("--starts", type=float, nargs="+", default=[150.0, 450.0, 750.0, 1050.0])
    ap.add_argument("--n-scenarios", type=int, default=16)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default="results/scenario_rollout_agreement")
    a = ap.parse_args()
    t_end = max(a.starts) + a.H + 5
    jobs = [(mu, a.seed_start + i, tuple(a.starts), a.H, a.n_scenarios, t_end) for mu in a.loads for i in range(a.seeds)]
    rows = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for part in ex.map(_one_run, jobs):
            rows.extend(part)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "windows.json").write_text(json.dumps(rows, indent=1))
    summary = {}
    for mu in a.loads:
        rs = [r for r in rows if r["mu"] == mu]
        s = {"n_windows": len(rs)}
        for name, real, mean, sd in [
            ("exposure_vs_J", "real_exposure", "eng_J_mean", "eng_counted_sd"),
            ("exposure_vs_counted", "real_exposure", "eng_counted_mean", "eng_counted_sd"),
            ("reactive_completed", "real_reactive_completed", "eng_reactive_mean", "eng_reactive_sd"),
            ("predictive_completed", "real_predictive_completed", "eng_predictive_mean", "eng_predictive_sd"),
            ("detections", "real_detections", "eng_detections_mean", "eng_detections_sd"),
        ]:
            z = _z(rs, real, mean, sd)
            diff = np.array([r[real] - r[mean] for r in rs])
            s[name] = {
                "real_mean": float(np.mean([r[real] for r in rs])),
                "engine_mean": float(np.mean([r[mean] for r in rs])),
                "mean_diff": float(diff.mean()),
                "mean_diff_se": float(diff.std(ddof=1) / math.sqrt(len(diff))),
                "rel_diff": float(diff.mean() / max(abs(np.mean([r[mean] for r in rs])), 1e-12)),
                "z_mean": float(z.mean()), "z_sd": float(z.std(ddof=1)),
                "frac_abs_z_gt_2": float(np.mean(np.abs(z) > 2)),
            }
        s["engine_wall_s_per_window_16scen"] = float(np.mean([r["engine_wall_s"] for r in rs]))
        summary[str(mu)] = s
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
