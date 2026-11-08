"""Memory-aware collection of unchanged-ACC reference recordings.

Same record_run implementation as the audited recorder; only scheduling differs.
Completed files are validated and reused. Incomplete writes never become final files.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
os.environ.setdefault('DETERRENT_TELEMETRY','0')
import psutil
from experiments import refit_sim_truth as replay
from experiments.run_bounded_calibration import validate_recordings


def worker_limit(available_gb,physical_cores,pending,requested=0):
    if available_gb<4.5 or pending<=0:
        return 0
    # Completed fixed-setting recordings used ~0.15 GB resident memory/worker;
    # allow 0.5 GB per worker and retain the approved 4 GB reserve.
    return min(physical_cores or 1,requested or physical_cores or 1,pending,
               int(math.floor((available_gb-4.0)/0.5)))


def record_atomic(job):
    final=Path(job['out'])
    temporary=final.with_name(final.name+f'.{os.getpid()}.partial')
    result=replay.record_run(dict(job,out=str(temporary)))
    temporary.replace(final)
    return result


def pending_jobs(seeds):
    if any(s<0 or s>=300 for s in seeds):
        raise ValueError('Evaluation seeds are excluded from reference collection')
    jobs=[]
    for load,mu in replay.LOADS.items():
        for seed in seeds:
            path=replay.OUT/'recordings_paper'/f'{load}_{seed}.pkl'
            if path.exists():
                validate_recordings([str(path)])
                continue
            path.parent.mkdir(parents=True,exist_ok=True)
            jobs.append(dict(load=load,mu=mu,seed=seed,out=str(path),t_end=None,
                             recording_constants=dict(replay.PAPER_PROP)))
    return jobs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workers',type=int,default=0)
    p.add_argument('--seeds',type=int,nargs='+',required=True)
    args=p.parse_args()
    if args.workers<0:
        raise ValueError('Worker count must be nonnegative')
    jobs=pending_jobs(args.seeds)
    if not jobs:
        print('All requested reference recordings already complete.',flush=True)
        return
    workers=0
    while not workers:
        workers=worker_limit(psutil.virtual_memory().available/1e9,
                             psutil.cpu_count(logical=False),len(jobs),args.workers)
        if not workers:
            print('[memory] Waiting for 4 GB reserve plus one job.',flush=True)
            time.sleep(5)
    print(json.dumps(dict(workers=workers,pending=len(jobs),reserve_gb=4,
                          estimated_peak_gb_per_worker=.5)),flush=True)
    started=time.monotonic()
    completed=0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending={}
        while jobs or pending:
            while jobs and len(pending)<workers and psutil.virtual_memory().available>=4.5e9:
                job=jobs.pop(0)
                pending[pool.submit(record_atomic,job)]=job
            if not pending:
                time.sleep(5)
                continue
            done,_=wait(pending,timeout=5,return_when=FIRST_COMPLETED)
            for future in done:
                job=pending.pop(future)
                result=future.result()
                validate_recordings([job['out']])
                completed+=1
                print(f'[{completed}] {result} wall={time.monotonic()-started:.0f}s',flush=True)


if __name__=='__main__':
    main()
