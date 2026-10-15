"""
bench_scenario_rollout.py -- wall time of scenario_rollout.evaluate() for a realistic decision.

Paper B5 configuration (4 robots, 60x48 grid on 500x500 m), H=300 s, about 30
candidates (each robot: its two strongest preventive seeds or patrol points
plus its own position, times three cues), 16 scenarios.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DETERRENT_TELEMETRY", "0")
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np


def realistic_snapshot(mu, steps=300, seed=301, horizon_s=300.0):
    import DeterrentSystem as ds
    from experiments.run_plan_completion import build_params
    from habituation_stl import scenario_rollout as sr
    p = build_params("B5", True, mu, 1800.0)
    p["seed"] = seed
    gen = ds.run_simulation_frames_persistent(**p)
    for _ in range(steps):
        next(gen)
    return sr.snapshot_from_sim_locals(gen.gi_frame.f_locals, horizon_s=horizon_s)


def candidates_for(snap, per_robot=10):
    from habituation_stl import scenario_rollout as sr
    out = []
    modes = list(snap.deterring_modes)
    for rs in snap.robots:
        m = rs.planner.m
        hs = m.hotspots(top_k=2, merge_radius=25.0, use_excess=True, mask_poly=rs.zone_polygon or None)
        pts = [(h["x"], h["y"]) for h in hs][:2] + [tuple(rs.pose)]
        for (x, y) in pts:
            for mode in modes:
                if len([c for c in out if c.robot_id == rs.rid]) < per_robot:
                    out.append(sr.Candidate(rs.rid, float(x), float(y), mode))
    return out[:30]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loads", type=float, nargs="+", default=[2e-5, 4e-4])
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--n-scenarios", type=int, default=16)
    ap.add_argument("--compare-lazy", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    from habituation_stl import scenario_rollout as sr
    report = {}
    t = time.perf_counter()
    pool = sr.RolloutPool(a.workers)
    pool_start_s = time.perf_counter() - t
    print("pool start-up s", pool_start_s, "workers", pool.n_workers, flush=True)
    for mu in a.loads:
        snap = realistic_snapshot(mu)
        cands = candidates_for(snap)
        t = time.perf_counter()
        trees = [sr._sample_scenario_tree(snap, 0, s) for s in range(a.n_scenarios)]
        t_tree = (time.perf_counter() - t) / a.n_scenarios
        t = time.perf_counter()
        sr.run_policy(snap, sr.NOOP, n_scenarios=2, seed=0, trees=trees[:2])
        t_run = (time.perf_counter() - t) / 2
        cold = sr.evaluate(snap, cands, n_scenarios=a.n_scenarios, seed=0, n_workers=a.workers)
        walls = []
        for rep in range(3):
            res = sr.evaluate(snap, cands, n_scenarios=a.n_scenarios, seed=0, pool=pool)
            walls.append(res.wall_time_s)
        assert np.array_equal(res.J, cold.J)
        r = {
            "pool_startup_s": pool_start_s, "cold_pool_evaluate_wall_s": cold.wall_time_s,
            "warm_pool_evaluate_wall_s": walls,
            "n_candidates": len(cands), "n_scenarios": a.n_scenarios,
            "events_per_scenario": int(trees[0].order.size),
            "tree_build_s_per_scenario": t_tree, "serial_s_per_policy_scenario": t_run,
            "J0_mean": float(res.J_mean[0]), "J0_se": float(res.J_se[0]),
            "U_mean_range": [float(res.U_mean.min()), float(res.U_mean.max())],
            "U_se_median": float(np.median(res.U_se)),
        }
        if a.compare_lazy:
            lazy = sr.evaluate(snap, cands, n_scenarios=a.n_scenarios, seed=0, pool=pool,
                               planner_model_advance="lazy")
            r["lazy_evaluate_wall_s"] = lazy.wall_time_s
            r["lazy_max_abs_J_diff"] = float(np.max(np.abs(lazy.J - res.J)))
            r["lazy_max_abs_U_mean_diff"] = float(np.max(np.abs(lazy.U_mean - res.U_mean)))
            r["lazy_same_ranking"] = bool(np.array_equal(np.argsort(lazy.U_mean), np.argsort(res.U_mean)))
        report[str(mu)] = r
        print(mu, json.dumps(r, indent=1), flush=True)
    pool.close()
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
