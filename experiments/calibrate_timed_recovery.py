"""
calibrate_timed_recovery.py -- fix the Plan Eq. 4 thresholds before any evaluation run.

User decision (2026-10-15): from development seeds 200-209 under B5, pooled over the three
loads (one operational requirement for all loads, as the paper uses one profile):
  E_high = 90th percentile of the per-step planner forecast cell exposure e_z,
  E_low  = median of the same distribution,
  T_response = 300 s (the planning horizon).
Runs use the evaluation environment (original system + coupled streams) in observe-only
plan mode, so the executed system is exactly B5 and no rollout pool is started.

Output: results/testbench/timed_recovery_calibration/{exposure_*.jsonl, thresholds.json}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("DETERRENT_TELEMETRY", "0")
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

OUT = Path("results/testbench/timed_recovery_calibration")
LOADS = {"spare": 2e-5, "heavy": 1e-4, "overload": 4e-4}


def _run(load: str, mu: float, seed: int) -> str:
    from experiments.run_plan_completion import build_params, run_job
    log = (OUT / f"exposure_{load}_seed{seed}.jsonl").resolve()
    if log.exists():
        log.unlink()
    params = build_params("E_plan", True, mu, None)
    params.update(plan_observe_only=True, plan_exposure_log_path=str(log), plan_oracle_fraction=0.0)
    run_job({"system": f"B5obs_{load}", "variant": "E_plan", "habituation_condition": "hab_on",
             "seed": seed, "params": params})
    (OUT / f"done_{load}_seed{seed}").write_text("ok", encoding="utf-8")
    return str(log)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed-start", type=int, default=200)
    p.add_argument("--num-runs", type=int, default=10)
    p.add_argument("--max-workers", type=int, default=8)
    p.add_argument("--analyze-only", action="store_true")
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    seeds = range(args.seed_start, args.seed_start + args.num_runs)
    if not args.analyze_only:
        jobs = [(l, mu, s) for l, mu in LOADS.items() for s in seeds
                if not (OUT / f"done_{l}_seed{s}").exists()]
        with ProcessPoolExecutor(max_workers=args.max_workers) as ex:
            futs = {ex.submit(_run, *j): j for j in jobs}
            for f in as_completed(futs):
                print("[tr-cal] done", futs[f], flush=True)
    vals = []
    per_load = {}
    for l in LOADS:
        lv = []
        for s in seeds:
            fp = OUT / f"exposure_{l}_seed{s}.jsonl"
            if not (OUT / f"done_{l}_seed{s}").exists():
                raise SystemExit(f"missing run {l} seed {s}")
            for line in fp.read_text(encoding="utf-8").splitlines():
                lv.extend(json.loads(line)["e"].values())
        per_load[l] = {"n": len(lv), "p50": float(np.percentile(lv, 50)), "p90": float(np.percentile(lv, 90))}
        vals.extend(lv)
    res = {"E_high": float(np.percentile(vals, 90)), "E_low": float(np.percentile(vals, 50)),
           "T_response_s": 300.0, "n_samples": len(vals), "seeds": list(seeds),
           "rule": "pooled over loads: E_high = p90, E_low = p50 of per-step planner forecast cell exposure under B5",
           "per_load": per_load}
    (OUT / "thresholds.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
