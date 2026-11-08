"""Bounded, reproducible calibration of the unit-corrected ACC estimator.

No expanding grids, policy optimization, evaluation seeds, or deployment. Uses
the audited predictable-step scorer. Defaults to unchanged-ACC B5 reference
recordings; --recording-dir and --recording-system select isolated policy data.
"""
from __future__ import annotations

import argparse
from concurrent.futures import wait, FIRST_COMPLETED
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

os.environ.setdefault('DETERRENT_TELEMETRY', '0')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import psutil
from experiments import refit_sim_truth as replay
from experiments import run_plan_completion as rpc

BOUNDS = {'sigma': (5.0, 80.0), 'omega': (112.5, 1800.0),
          'alpha_in': (0.0375, 0.6), 'alpha_inhib': (0.0, 3.6),
          'mu_base': (6.25e-6, 1e-4)}
PRED_AXES = ('sigma', 'omega', 'alpha_in', 'mu_base')
PROP_AXES = (*PRED_AXES, 'alpha_inhib')
REFERENCE = dict(replay.PAPER_PROP)
TRAIN_SEEDS = tuple(range(200, 210))
VALIDATION_SEEDS = tuple(range(210, 220))
MAX_BUDGET = {'prediction': 24, 'proposed': 48, 'joint': 9}


def validate_params(params):
    if set(params) != set(REFERENCE):
        raise ValueError('Candidate parameter keys must match the ACC reference')
    for key, value in params.items():
        if not math.isfinite(float(value)):
            raise ValueError(f'Nonfinite parameter: {key}')
        if key in BOUNDS:
            lo, hi = BOUNDS[key]
            if not lo <= value <= hi:
                raise ValueError(f'Parameter outside approved bounds: {key}={value}')
        elif value != REFERENCE[key]:
            raise ValueError(f'Fixed nuisance parameter changed: {key}')


def candidates(center, axes, count, seed, *, local=False, include=()):
    """Seeded Latin hypercube, with exact reference/controls and bounded local probes."""
    rng = np.random.default_rng(seed)
    points, seen = [], set()

    def add(point):
        validate_params(point)
        key = json.dumps(point, sort_keys=True)
        if key not in seen and len(points) < count:
            seen.add(key)
            points.append(dict(point))

    for point in include:
        add(point)
    if local:
        for key in axes:
            for direction in (-1, 1):
                p = dict(center)
                lo, hi = BOUNDS[key]
                step = (hi-lo)/8 if lo == 0 else None
                p[key] = float(np.clip(center[key] + direction*step if lo == 0 else
                                       center[key]*2.0**(direction*0.5), lo, hi))
                add(p)
    n = max(count, 1)
    cells = np.array([(rng.permutation(n) + rng.random(n))/n for _ in axes]).T
    for row in cells:
        p = dict(center)
        for key, u in zip(axes, row):
            lo, hi = BOUNDS[key]
            if local:
                if lo == 0:
                    lo, hi = max(lo, center[key]-(hi-lo)/4), min(hi, center[key]+(hi-lo)/4)
                else:
                    lo, hi = max(lo, center[key]/2), min(hi, center[key]*2)
            p[key] = float(lo + u*(hi-lo) if lo == 0 else math.exp(math.log(lo)+u*math.log(hi/lo)))
        add(p)
    return points


def pool_metrics(runs, prefix):
    """Equal recording, seed and load weight; never weight by event count."""
    by_load = {}
    for row in runs:
        n = float(row['truth_events'])
        if n <= 0:
            raise ValueError('Per-event likelihood requires a nonempty truth recording')
        m = {'nll_per_event': float(row[prefix+'_nll'])/n,
             'brier': float(row[prefix+'_field_brier']),
             'logloss': float(row[prefix+'_field_logloss']),
             'relative_count_bias': float(row[prefix+'_expected_events'])/n-1}
        if not all(math.isfinite(v) for v in m.values()):
            raise ValueError('Nonfinite active calibration metric')
        by_load.setdefault(row['load'], []).append(m)
    per_load = {load: {key: float(np.mean([r[key] for r in values])) for key in values[0]}
                for load, values in by_load.items()}
    pooled = {key: float(np.mean([m[key] for m in per_load.values()])) for key in next(iter(per_load.values()))}
    return dict(pooled=pooled, per_load=per_load)


class SearchStop(RuntimeError):
    pass


def abort_pool(pool):
    processes = list((getattr(pool, '_processes', None) or {}).values())
    for proc in processes:
        if proc.is_alive():
            proc.terminate()
    pool.shutdown(wait=False, cancel_futures=True)
    for proc in processes:
        proc.join(timeout=3)


class Evaluator(replay.SimEvaluator):
    def __init__(self, *args, deadline, progress, max_configs, **kwargs):
        Path(args[0] if args else kwargs['out']).mkdir(parents=True, exist_ok=True)
        super().__init__(*args, **kwargs)
        self.deadline, self.progress, self.max_configs = deadline, progress, dict(max_configs)
        self.aborted = False

    def check_time(self):
        if time.monotonic() >= self.deadline:
            self.aborted = True
            abort_pool(self.pool)
            raise SearchStop('Hard wall-time limit reached; complete candidates remain cached')

    def execute(self, jobs):
        while psutil.virtual_memory().available < 4.5e9:
            self.check_time()
            self.progress('waiting_for_memory', available_gb=psutil.virtual_memory().available/1e9)
            time.sleep(2)
        self.check_time()
        pending = {self.pool.submit(replay._run, job): i for i, job in enumerate(jobs)}
        results = [None]*len(jobs)
        while pending:
            self.check_time()
            done, _ = wait(pending, timeout=min(5, max(0.01, self.deadline-time.monotonic())),
                           return_when=FIRST_COMPLETED)
            for future in done:
                results[pending.pop(future)] = future.result()
            if psutil.virtual_memory().available < 4e9:
                self.aborted = True
                abort_pool(self.pool)
                raise SearchStop('Memory reserve below 4 GB; stopping before memory exhaustion')
            self.progress('replaying', completed=len(jobs)-len(pending), total=len(jobs),
                          workers=self.workers,
                          available_gb=round(psutil.virtual_memory().available/1e9, 2))
        return results

    def evaluate_one(self, stage, pred, prop):
        validate_params(pred)
        validate_params(prop)
        key = replay.rh.config_key(stage, pred, prop)
        if key in self.cache:
            return self.cache[key]
        used = sum(r.get('stage') == stage for r in self.cache.values())
        if used >= self.max_configs[stage]:
            raise SearchStop(f'{stage} candidate-count budget exhausted')
        self.progress('evaluating_candidate', candidate_stage=stage, candidate=used+1,
                      workers=self.workers,
                      candidate_limit=self.max_configs[stage], parameters=prop if stage!='prediction' else pred)
        jobs = [(stage, pred, prop, path, 'truth') for path in self.paths]
        values = self.execute(jobs)
        runs = [dict(r, recording=Path(path).name, load=Path(path).stem.rsplit('_', 1)[0],
                     seed=int(Path(path).stem.rsplit('_', 1)[1])) for r, path in zip(values, self.paths)]
        metrics = {}
        for prefix in ('prediction_only', 'proposed'):
            if stage == 'joint' or (prefix == 'prediction_only') == (stage == 'prediction'):
                metrics[prefix] = pool_metrics(runs, prefix)
        row = dict(key=key, stage=stage, pred=pred, prop=prop, runs=runs, metrics=metrics,
                   **self.version)
        with self.cache_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row)+'\n')
        self.cache[key] = row
        return row

    def close(self):
        if not getattr(self, 'aborted', False):
            super().close()


def ranking(row, stage):
    prefix = 'prediction_only' if stage == 'prediction' else 'proposed'
    metrics = row['metrics'][prefix]['pooled']
    p = row['pred'] if stage == 'prediction' else row['prop']
    distance = sum(((p[k]-REFERENCE[k])/(BOUNDS[k][1]-BOUNDS[k][0]))**2 for k in BOUNDS)
    return (round(metrics['nll_per_event'], 9), distance, metrics['brier'], metrics['logloss'])


def ranked_unique(rows, stage):
    return sorted({r['key']:r for r in rows}.values(), key=lambda r:ranking(r,stage))


def profile_diagnostics(rows, stage, center):
    """Use already budgeted one-axis probes; no extra model evaluations."""
    which = 'pred' if stage=='prediction' else 'prop'
    prefix = 'prediction_only' if stage=='prediction' else 'proposed'
    profiles = {}
    for axis in (PRED_AXES if stage=='prediction' else PROP_AXES):
        points = {}
        for row in rows:
            p = row[which]
            if all(p[k]==center[k] for k in center if k!=axis):
                points[p[axis]] = row['metrics'][prefix]['pooled']['nll_per_event']
        values = list(points.values())
        profiles[axis] = dict(points=sorted(points.items()),
                              numerically_flat=(max(values)-min(values)<=1e-6*max(1,abs(np.mean(values))))
                              if len(values)>1 else None)
    return dict(center=center,profiles=profiles,
                interpretation='Finite one-axis training probes; not a statistical identifiability guarantee')


def paths_for(seeds, directory=None):
    if any(s < 0 or s >= 300 for s in seeds):
        raise ValueError('Evaluation seeds are excluded from calibration and validation')
    directory = Path(directory) if directory else replay.OUT/'recordings_paper'
    return [str(directory/f'{load}_{seed}.pkl') for load in replay.LOADS for seed in seeds]


def atomic_json(path, payload, *, best_effort=False):
    """Readers on Windows can briefly deny replacement; status is not a compute dependency."""
    fd,name = tempfile.mkstemp(prefix=path.stem+'.',suffix='.tmp',dir=path.parent)
    temp=Path(name)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(payload,stream,indent=2,default=str)
        for attempt in range(20):
            try:
                temp.replace(path)
                return True
            except PermissionError:
                if attempt==19:
                    if best_effort:
                        return False
                    raise
                time.sleep(min(.01*2**attempt,.1))
    finally:
        try:
            temp.unlink(missing_ok=True)
        except PermissionError:
            pass


def validate_recordings(paths, expected_system=None, expected_truth_process_mode=None):
    import pickle
    from additive_intensity import ADDITIVE_CONTRACT
    modes = set()
    for path in paths:
        with open(path, 'rb') as stream:
            rec = pickle.load(stream)
        mode = rec.get('truth_process_mode', 'historical_thinning')
        modes.add(mode)
        if expected_truth_process_mode is not None and mode != expected_truth_process_mode:
            raise ValueError(f'Recording belongs to another truth process: {path}')
        if mode == ADDITIVE_CONTRACT and rec.get('grid_contract') != ADDITIVE_CONTRACT:
            raise ValueError(f'Additive recording lacks its grid contract: {path}')
        if expected_system is not None and rec.get('recording_system') != expected_system:
            raise ValueError(f'Recording belongs to another policy: {path}')
        if rec.get('units') != 'mass_per_cell' or rec.get('rec_constants') != REFERENCE:
            raise ValueError(f'Recording is not an unchanged-ACC corrected-unit reference: {path}')
        load,seed = Path(path).stem.rsplit('_',1)
        if (load not in replay.LOADS or rec.get('load')!=load or rec.get('seed')!=int(seed) or
                not math.isclose(rec.get('mu',math.nan),replay.LOADS[load],rel_tol=1e-12)):
            raise ValueError(f'Recording load/seed metadata differs from its declared cell: {path}')
        if any(rec.get(k)!=v for k,v in {'W':500.,'H':500.,'NX':60,'NY':48,'dt':1.}.items()):
            raise ValueError(f'Recording differs from the approved ACC geometry/timestep: {path}')
        if not rec.get('truth_events') or not rec['log'] or rec['log'][-1][0] != 'step' or rec['log'][-1][1] < 1800:
            raise ValueError(f'Incomplete production recording: {path}')
        if rec['log'][-1][1]>1801:
            raise ValueError(f'Recording exceeds the approved 1800-second run: {path}')
    if len(modes) > 1:
        raise ValueError('Cannot mix recordings from different truth processes')


def budget_for_estimate(seconds, cap):
    if seconds <= cap*0.85:
        return dict(MAX_BUDGET)
    # Joint pairs run both model arms, so reserve their 18 replay units first.
    scale = max(0, (cap*0.85/seconds*90-18)/72)
    counts = {'prediction': max(6, int(24*scale)), 'proposed': max(8, int(48*scale)), 'joint': 9}
    replay_units = counts['prediction']+counts['proposed']+2*counts['joint']
    if replay_units/90*seconds > cap*0.95:
        raise SearchStop('Even the minimum candidate budget exceeds the benchmarked time cap')
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default=str(ROOT/'results/bounded_acc_calibration'))
    ap.add_argument('--workers', type=int, default=0, help='0 = benchmark memory-capped worker counts up to physical cores')
    ap.add_argument('--hours', type=float, default=4.0)
    ap.add_argument('--skip-validation', action='store_true')
    ap.add_argument('--recording-dir', default=None)
    ap.add_argument('--recording-system', default=None)
    ap.add_argument('--truth-process-mode', choices=('historical_thinning', 'additive_cells_v1'), default=None)
    ap.add_argument('--full-budget', action='store_true', help='Keep all 81 candidates; stop rather than shrink if the time cap is insufficient')
    ap.add_argument('--wait-for-recordings', action='store_true',
                    help='Wait up to two hours for the already running reference recording collection')
    args = ap.parse_args()
    if not 0 < args.hours <= 4.0:
        raise ValueError('The approved search cap is at most four hours')
    if args.workers < 0:
        raise ValueError('Worker count must be zero (automatic) or positive')
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock = out/'RUNNING.lock'
    if lock.exists():
        raise RuntimeError('Existing run lock: inspect its PID before restarting')
    lock.write_text(str(os.getpid()))
    state = {'pid': os.getpid(), 'deployed': False, 'training_seeds': TRAIN_SEEDS,
             'validation_seeds': VALIDATION_SEEDS, 'bounds': BOUNDS, 'fixed_reference': REFERENCE}
    manifest = dict(state, version=rpc.code_version(),
                    recording_system=args.recording_system, recording_dir=args.recording_dir,
                    truth_process_mode=args.truth_process_mode,
                    runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    existing = json.loads((out/'manifest.json').read_text()) if (out/'manifest.json').exists() else {}

    last_status_write=0.0

    def progress(stage, **details):
        nonlocal last_status_write
        state.update(stage=stage, updated_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **details)
        now=time.monotonic()
        if stage!='replaying' or now-last_status_write>=1 or details.get('completed')==details.get('total'):
            if not atomic_json(out/'status.json',state,best_effort=True):
                print('[status] reader holds status file; computation continues',file=sys.stderr,flush=True)
            last_status_write=now
        # Persist all progress, without printing one line per replay completion.
        if stage != 'replaying':
            print(state['updated_utc'], stage, json.dumps(details), flush=True)

    active = None
    try:
        if existing and existing.get('runner_sha256') != manifest['runner_sha256']:
            raise ValueError('Existing run has a different bounded-runner version; use a fresh output directory')
        if existing and any(existing.get(k) != manifest.get(k) for k in ('recording_dir', 'recording_system')):
            raise ValueError('Existing run belongs to a different recording source/policy')
        if existing.get('search_deadline_epoch', math.inf) <= time.time():
            raise SearchStop('Original four-hour deadline has expired; no automatic budget reset')
        train = paths_for(TRAIN_SEEDS, args.recording_dir)
        if args.wait_for_recordings:
            recording_deadline = time.monotonic()+7200
            while not all(Path(p).is_file() for p in train):
                progress('waiting_for_training_recordings', completed=sum(Path(p).is_file() for p in train),
                         total=len(train))
                if time.monotonic()>=recording_deadline:
                    raise SearchStop('Reference recording collection did not finish within two hours')
                time.sleep(15)
            # Allow the final pickle writer to finish before reading it.
            time.sleep(3)
        validate_recordings(train, args.recording_system, args.truth_process_mode)
        available = psutil.virtual_memory().available/1e9
        maximum = max(1, min(psutil.cpu_count(logical=False) or 1, int(max(0, available-4)/1.0)))
        if args.workers:
            maximum = min(maximum, args.workers)
        trial_workers = sorted(set(min(n, maximum) for n in (8, 16, maximum)))
        bench_paths = [p for p in train if int(Path(p).stem.rsplit('_',1)[1]) in (200, 201)]
        jobs = [(stage, REFERENCE, REFERENCE, path, 'truth') for _ in range(4)
                for path in bench_paths for stage in ('prediction', 'proposed')]
        benches, checksums = [], []
        for workers in trial_workers:
            progress('benchmarking', workers=workers, jobs=len(jobs))
            active = Evaluator(out/f'benchmark_{workers}', workers, print, train,
                               deadline=time.monotonic()+900, progress=progress, max_configs=MAX_BUDGET)
            started = time.monotonic()
            values = active.execute(jobs)
            seconds = time.monotonic()-started
            checksums.append(hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest())
            active.close()
            active = None
            benches.append(dict(workers=workers, seconds=seconds, model_replays=len(jobs),
                                checksum=checksums[-1]))
            atomic_json(out/'benchmark.json', benches)
        if len(set(checksums)) != 1:
            raise RuntimeError('Parallel replay benchmark changed numerical results across worker counts')
        best = min(benches, key=lambda b:b['seconds'])
        workers = best['workers']
        estimate = best['seconds']/len(jobs)*(24+48+2*9)*len(train)
        budgets = dict(MAX_BUDGET) if args.full_budget else budget_for_estimate(estimate, args.hours*3600)
        deadline_epoch = existing.get('search_deadline_epoch', time.time()+args.hours*3600)
        manifest.update(workers=workers, benchmarks=benches, full_budget_estimate_s=estimate,
                        budgets=budgets, search_cap_s=args.hours*3600, search_deadline_epoch=deadline_epoch)
        atomic_json(out/'manifest.json', manifest)
        deadline = time.monotonic()+max(0,deadline_epoch-time.time())
        active = Evaluator(out/'training', workers, print, train, deadline=deadline,
                           progress=progress, max_configs=budgets)
        predictions, proposals = [], []
        centers = {}
        for stage, axes, total in [('prediction', PRED_AXES, budgets['prediction']),
                                   ('proposed', PROP_AXES, budgets['proposed'])]:
            initial_n = min(total, 16 if stage == 'prediction' else 32)
            include = [REFERENCE]
            pred_best = sorted(predictions, key=lambda r:ranking(r,'prediction'))[0]['pred'] if predictions else REFERENCE
            if stage == 'proposed':
                include += [dict(REFERENCE, alpha_inhib=0.0),
                            dict(pred_best, alpha_inhib=REFERENCE['alpha_inhib']),
                            dict(pred_best, alpha_inhib=0.0)]
            points = candidates(REFERENCE, axes, initial_n, 20261030+(stage=='proposed'), include=include)
            rows = predictions if stage == 'prediction' else proposals
            for p in points:
                rows.append(active.evaluate_one(stage, p if stage=='prediction' else pred_best,
                                                p if stage=='proposed' else REFERENCE))
            center = min(rows, key=lambda r:ranking(r, stage))['pred' if stage=='prediction' else 'prop']
            centers[stage] = center
            for p in candidates(center, axes, total-initial_n, 20261032+(stage=='proposed'), local=True):
                rows.append(active.evaluate_one(stage, p if stage=='prediction' else pred_best,
                                                p if stage=='proposed' else REFERENCE))
            progress('stage_finished', completed_stage=stage, candidates=len(rows),
                     best=min(rows,key=lambda r:ranking(r,stage))['metrics'])
        pred_top = ranked_unique(predictions,'prediction')[:3]
        prop_top = ranked_unique(proposals,'proposed')[:3]
        joint = [active.evaluate_one('joint', a['pred'], b['prop']) for a in pred_top for b in prop_top]
        ordered = ranked_unique(proposals,'proposed')
        winner = ordered[0]['prop']
        selected = list({json.dumps(r['prop'],sort_keys=True):r['prop'] for r in ordered
                         if r['prop'] != REFERENCE}.values())[:2]
        result = dict(status='training_finished', candidate=winner, selected_finalists=selected,
                      training_best=ordered[0]['metrics'], benchmark=benches, budgets=budgets,
                      joint_metrics=[dict(pred=r['pred'],prop=r['prop'],metrics=r['metrics']) for r in joint],
                      refinement_centers=centers,
                      profile_diagnostics={stage:profile_diagnostics(rows,stage,centers[stage])
                                           for stage,rows in [('prediction',predictions),('proposed',proposals)]},
                      boundary_parameters=[k for k,(lo,hi) in BOUNDS.items() if winner[k] in (lo,hi)],
                      model_adequacy_review_required=winner['alpha_inhib']==0, deployed=False)
        atomic_json(out/'result.json', result)
        active.close()
        active = None
        if args.skip_validation:
            progress('training_ready_for_review', result=str(out/'result.json'))
            return
        # Fresh, nominal-reference recordings: candidates see the same held-out truths.
        validation_paths = paths_for(VALIDATION_SEEDS, args.recording_dir)
        if args.recording_dir and not all(Path(p).is_file() for p in validation_paths):
            raise ValueError('Custom-policy development recordings must be collected before the search')
        progress('collecting_validation_recordings')
        if not args.recording_dir:
            with (out/'validation_recordings.log').open('a',encoding='utf-8') as log:
                proc = subprocess.Popen([sys.executable,'-u','-m','experiments.collect_calibration_recordings',
                                     '--workers','0',
                                     '--seeds',*[str(s) for s in VALIDATION_SEEDS]],
                                    cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                state['recording_pid'] = proc.pid
                while proc.poll() is None:
                    progress('collecting_validation_recordings')
                    time.sleep(15)
                state.pop('recording_pid',None)
                if proc.returncode:
                    raise RuntimeError('Validation recording collection failed; inspect its log')
        validate_recordings(validation_paths, args.recording_system, args.truth_process_mode)
        active = Evaluator(out/'validation',workers,print,validation_paths,
                           deadline=time.monotonic()+3600,progress=progress,
                           max_configs={'prediction':0,'proposed':3,'joint':0})
        reference_row = active.evaluate_one('proposed',REFERENCE,REFERENCE)
        validation = []
        for p in selected:
            row = active.evaluate_one('proposed',REFERENCE,p)
            a = {(r['load'],r['seed']):r for r in reference_row['runs']}
            by_seed = []
            for seed in VALIDATION_SEEDS:
                by_seed.append(np.mean([r['proposed_nll']/r['truth_events']-
                    a[(r['load'],seed)]['proposed_nll']/a[(r['load'],seed)]['truth_events']
                    for r in row['runs'] if r['seed']==seed]))
            d = np.asarray(by_seed)
            rng = np.random.default_rng(20261030)
            lo,hi = np.percentile(d[rng.integers(0,len(d),(10000,len(d)))].mean(axis=1),[2.5,97.5])
            brier = {load: row['metrics']['proposed']['per_load'][load]['brier']-
                     reference_row['metrics']['proposed']['per_load'][load]['brier'] for load in replay.LOADS}
            review = (p['alpha_inhib']==0 or any(v>0.005 for v in brier.values()) or
                      any(row['metrics']['proposed']['per_load'][load]['nll_per_event']>
                          reference_row['metrics']['proposed']['per_load'][load]['nll_per_event']
                          for load in replay.LOADS))
            validation.append(dict(params=p,metrics=row['metrics'],paired_nll_difference=float(d.mean()),
                                   paired_ci=[float(lo),float(hi)],brier_deltas=brier,
                                   review_required=review,validated_improvement=bool(hi<0 and not review)))
        result.update(status='validation_finished_review_required',validation=validation,
                      validation_reference=reference_row['metrics'],deployed=False)
        atomic_json(out/'result.json',result)
        progress('calibration_ready_for_review', result=str(out/'result.json'),deployed=False)
    except Exception as exc:
        progress('stopped_for_review',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        if active is not None:
            active.close()
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    main()
