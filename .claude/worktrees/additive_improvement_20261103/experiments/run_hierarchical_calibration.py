"""Fair B1--B5 calibration: upstream selection, frozen inheritance, finite searches.

Run with --phase all (default), or stop after estimator/policy/evaluation stages.
Outputs are experiment-local; this command never deploys global planner defaults.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
import hashlib
import inspect
import itertools
import json
import math
import os
from pathlib import Path
import pickle
import subprocess
import sys
import time

os.environ.setdefault('DETERRENT_TELEMETRY', '0')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import psutil
from experiments import run_bounded_calibration as bounded
from experiments import refit_sim_truth as replay
from experiments import run_plan_completion as rpc

PARENTS = {'B1': None, 'B2': 'B1', 'B3': 'B2', 'B5': 'B1', 'B4': 'B3'}
SYSTEMS = tuple(PARENTS)
MARGINS = {s: 'model_deterring_score_margin_'+scale for s, scale in
           [('B1', 'legacy'), ('B2', 'deltaJ'), ('B3', 'stl')]}
POSITIVE = ('min_hotspot_score', 'model_deterring_risk_scale',
            'deterring_cost_multiplier', 'patrol_cost_weight',
            'model_deterring_busy_fallback_deltaJ_per_cost_min')
OWNED = {
    'B1': frozenset((*POSITIVE, MARGINS['B1'], 'model_deterring_budget_per_robot_per_hr',
                     'model_deterring_max_eta_s', 'predictive_lead_time_max_eta_s',
                     'forecast_horizon_s', 'stl_horizon_s')),
    'B2': frozenset((MARGINS['B2'], 'reservation_fraction', 'reservation_window_s',
                     'reactive_override_slack_s')),
    'B3': frozenset((MARGINS['B3'],)), 'B4': frozenset(), 'B5': frozenset(),
}
SWITCHES = {
    'B1': {},
    'B2': {'dispatch_policy': 'res', 'predictive_utility_mode': 'deltaJ',
           'predictive_selection_policy': 'utility'},
    'B3': {'predictive_utility_mode': 'stl_robustness', 'stl_active_clauses': ['exp', 'cov']},
    'B5': {'predictive_utility_mode': 'legacy_habituation', 'predictive_fixed_deterring_mode': None},
    # A is submitted B4: preserve the improvement plan's explicit correction exception.
    'B4': {'predictive_fixed_deterring_mode': None, 'stl_active_clauses': ['exp', 'cov', 'hab'],
           **deepcopy(rpc.B4_VARIANTS['A'][1])},
}
TRAIN = tuple(range(200, 210))
DEV = tuple(range(210, 220))
FRESH = tuple(range(220, 230))
EVAL = tuple(range(300, 310))
Q = (0, .1, .25, .5, .75, .9, 1)
STL_REQUIREMENTS = ('stl_E_star', 'stl_T_cov_s', 'stl_W_s', 'stl_eta_min', 'stl_theta')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bounded.atomic_json(path, value)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sources():
    files = list(ROOT.glob('*.py'))
    for directory in ('experiments', 'habituation_stl', 'diagnostics'):
        files.extend((ROOT/directory).rglob('*.py'))
    return {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files) if '__pycache__' not in p.parts}


def materialize(params):
    """Resolve every public argument and profile once; runtime profiles are disabled."""
    import DeterrentSystem as ds
    from planner_profiles import get_planner_profile_values
    values = {k: deepcopy(v.default) for k, v in inspect.signature(
        ds.run_simulation_frames_persistent).parameters.items() if v.default is not inspect.Parameter.empty}
    values.update(deepcopy(params))
    profile = values.get('planner_profile')
    if profile:
        values.update(deepcopy(get_planner_profile_values(profile)))
    values.update(deepcopy(values.get('planner_profile_overrides') or {}))
    values.update(planner_profile='', planner_profile_overrides=None, use_frozen_calibration=False,
                  calibration_manifest_path=None, calibration_ranking_path=None)
    # Round trip makes tuples/lists stable between an in-memory job and its checkpoint.
    return json.loads(json.dumps(values, allow_nan=False))


def paper_reference():
    params = rpc._ladder_params(rpc.LADDER_SYSTEMS['B1'], True, rpc.LOADS['spare'])
    params.update(rpc.PLAN_ENV)
    params = materialize(params)
    params['proposed_model_overrides'] = replay._sim_overrides(bounded.REFERENCE)
    for scale in ('legacy', 'deltaJ', 'stl', 'eq3'):
        params['model_deterring_score_margin_'+scale] = params['model_deterring_score_margin']
    return params


def derive(system, parent, additions=None):
    additions = deepcopy(additions or {})
    illegal = set(additions)-OWNED[system]
    if illegal:
        raise ValueError(f'{system} cannot retune inherited/specification parameters: {sorted(illegal)}')
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in additions.values()):
        raise ValueError('Calibration additions must be finite numbers')
    out = deepcopy(parent)
    out.update(SWITCHES[system])
    out.update(additions)
    for key in set(parent)-OWNED[system]-set(SWITCHES[system]):
        if out[key] != parent[key]:
            raise AssertionError(f'Inherited value changed: {key}')
    return out


def audit_runtime(local, params):
    """Inspect the running generator after profile/model resolution, before accepting output."""
    keys = set().union(*OWNED.values(), *[set(s) for s in SWITCHES.values()])
    keys.update((*STL_REQUIREMENTS, *rpc.PLAN_ENV, 'truth_process_mode', 'W', 'H', 'NX', 'NY', 'Nrobots',
                 'T_end', 'dt', 'task_replan_period_s', 'deterring_modes', 'habituation_kappa',
                 'planner_profile', 'assigner_w_task_value', 'use_frozen_calibration'))
    checked = {}
    for key in keys:
        if key not in local:
            raise RuntimeError(f'Cannot audit runtime parameter: {key}')
        actual = json.loads(json.dumps(local[key]))
        expected = params[key]
        if actual != expected:
            raise RuntimeError(f'Runtime changed {key}: {actual!r} != {expected!r}')
        checked[key] = actual
    resolved = local['calibration_resolution']
    for key, expected in params['proposed_model_overrides'].items():
        if resolved[key] != expected:
            raise RuntimeError(f'Runtime estimator differs: {key}')
    return checked


def margin_values(rows, paper_margin):
    """A training-only empirical grid; no matching to old-system gate frequencies."""
    gaps = [v for r in rows for v in r.get('score_gaps', []) if math.isfinite(v)]
    vals = [float(paper_margin)]
    if gaps:
        vals += np.quantile(np.asarray(gaps), Q).tolist()
    return sorted(set(vals))


def candidate_space(system, reference, margins):
    if system == 'B1':
        space = {key: [reference[key]*f for f in (.001, .01, .1, 1., 10.)] for key in POSITIVE}
        if any(reference[k] <= 0 for k in POSITIVE):
            raise ValueError('Positive model-unit search requires positive reference values')
        space.update(model_deterring_budget_per_robot_per_hr=[3, 4, 6],
                     model_deterring_max_eta_s=[90., 120.], forecast_horizon_s=[240., 300., 420.])
    elif system == 'B2':
        space = dict(reservation_fraction=[.10, .25, .40], reservation_window_s=[300., 600.],
                     reactive_override_slack_s=[60., 90., 120.])
    elif system == 'B3':
        space = {}
    else:
        return [{}]
    space[MARGINS[system]] = margins
    return space


def candidates(system, reference, margins, limit=48):
    space = candidate_space(system, reference, margins)
    if isinstance(space, list):
        return space
    names = sorted(space)
    total = math.prod(len(space[k]) for k in names)
    ref = {k: reference[k] for k in names}
    def expand(p):
        p = dict(p)
        if system == 'B1':
            p['predictive_lead_time_max_eta_s'] = p['model_deterring_max_eta_s']
            p['stl_horizon_s'] = p['forecast_horizon_s']
        return p
    out, seen = [expand(ref)], {digest(expand(ref))}
    rng = np.random.default_rng(0)
    # Sample product indices rather than materializing the multi-million-row B1 grid.
    indices = rng.choice(total, size=min(total, limit*4), replace=False)
    if total <= limit:
        indices = np.arange(total)
    for index in indices:
        p = {}
        for key in reversed(names):
            index, digit = divmod(int(index), len(space[key]))
            p[key] = space[key][digit]
        p = expand(p)
        if digest(p) not in seen:
            seen.add(digest(p)); out.append(p)
        if len(out) == limit:
            break
    return out


def exposure_score(rows, denominators, seeds):
    expected = {(load, s) for load in rpc.LOADS for s in seeds}
    if len(rows) != len(expected) or {(r['load'], r['seed']) for r in rows} != expected:
        raise ValueError('Exposure selection requires every paired seed/load exactly once')
    if any(not math.isfinite(denominators[l]) or denominators[l] <= 0 for l in rpc.LOADS):
        raise ValueError('Invalid B1 reference normalization')
    return float(np.mean([np.mean([r['metrics']['value_weighted_exposure']/denominators[load]
                                  for r in rows if r['load'] == load]) for load in rpc.LOADS]))


def distance(additions, reference):
    return sum(((v-reference[k])/max(abs(reference[k]), 1.))**2 for k, v in additions.items())


def worker(job):
    params = deepcopy(job['params'])
    params.update(seed=job['seed'], mu_true=rpc.LOADS[job['load']],
                  enable_habituation=job['hab_on'], habituation_kappa=.5 if job['hab_on'] else 0.)
    if job['kind'] == 'record':
        temporary = Path(job['out']).with_suffix(f'.{os.getpid()}.partial')
        recording = replay.record_run(dict(job, params=params, mu=rpc.LOADS[job['load']],
                                         out=str(temporary), runtime_expectations=params))
        temporary.replace(job['out'])
        return dict(identity=job['identity'], **recording)
    import DeterrentSystem as ds
    gen = ds.run_simulation_frames_persistent(**params)
    audit, last, taskgen = None, None, None
    started = time.monotonic()
    try:
        for frame in gen:
            if audit is None:
                local = gen.gi_frame.f_locals
                audit = audit_runtime(local, params)
                taskgen = local['taskgen']
                if job.get('probe'):
                    taskgen.calibration_score_gaps = []
            last = frame
    finally:
        gen.close()
    if last is None or audit is None:
        raise RuntimeError('Simulation produced no audited frames')
    metrics = last.get('metrics_compact') or last.get('metrics') or {}
    numeric = {k: float(v) for k, v in metrics.items()
               if isinstance(v, (int, float, np.number)) and math.isfinite(v)}
    if 'value_weighted_exposure' not in numeric:
        raise RuntimeError('Missing mission exposure')
    return dict(identity=job['identity'], system=job['system'], load=job['load'], seed=job['seed'],
                hab_on=job['hab_on'], metrics=numeric, elapsed_s=time.monotonic()-started,
                runtime=audit, config_hash=digest(params),
                score_gaps=(taskgen.calibration_score_gaps or []) if job.get('probe') else [])


def cached(job):
    path = Path(job['out'])
    if not path.exists():
        return None
    if job['kind'] == 'record':
        with path.open('rb') as stream:
            rec = pickle.load(stream)
        if rec.get('recording_identity') != job['identity']:
            raise ValueError(f'Stale recording: {path}')
        return {'identity': job['identity'], 'reused': True}
    row = read(path)
    if row.get('identity') != job['identity']:
        raise ValueError(f'Stale simulation checkpoint: {path}')
    return row


class Runner:
    def __init__(self, out, requested=0):
        self.out = Path(out)
        self.source = sources()
        self.machine = rpc.machine_identity()
        self.identity = digest(dict(source=self.source, machine=self.machine))
        self.requested = requested
        self.workers = self.limit()

    def limit(self):
        return max(0, min(self.requested or psutil.cpu_count(logical=False) or 1,
                          psutil.cpu_count(logical=False) or 1,
                          int(max(0, psutil.virtual_memory().available/1e9-4)/.75)))

    def status(self, stage, **details):
        state = dict(stage=stage, pid=os.getpid(), updated_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                     workers=self.workers, deployed=False, **details)
        bounded.atomic_json(self.out/'status.json', state, best_effort=True)
        print(json.dumps(state), flush=True)

    def jobs(self, tag, system, params, seeds, *, record=False, probe=False, habs=(True,)):
        if any(s < 0 or (s >= 300 and (record or probe or tag.startswith(('train', 'dev')))) for s in seeds):
            raise ValueError('Evaluation seeds cannot enter tuning/recordings')
        rows = []
        for load, seed, hab in itertools.product(rpc.LOADS, seeds, habs):
            job = dict(kind='record' if record else 'simulation', system=system, params=params,
                       load=load, seed=seed, hab_on=hab, probe=probe,
                       recording_constants=dict(bounded.REFERENCE))
            job['identity'] = digest(dict(job, source=self.identity))
            folder = self.out/tag
            name = f'{load}_{seed}' if record else f'{system}_{load}_{seed}_hab{int(hab)}'
            job['out'] = str(folder/(name+('.pkl' if record else '.json')))
            rows.append(job)
        return rows

    def run(self, stage, jobs, *, force=False, workers=None):
        results, todo = {}, []
        for job in jobs:
            Path(job['out']).parent.mkdir(parents=True, exist_ok=True)
            row = None if force else cached(job)
            if row is None:
                todo.append(job)
            else:
                results[job['identity']] = row
        count = min(workers or self.workers, self.limit(), len(todo))
        while todo and count == 0:
            self.status('waiting_for_memory', next_stage=stage, reserve_gb=4)
            time.sleep(5)
            count = min(workers or self.workers or 1, self.limit(), len(todo))
        if todo:
            pool = ProcessPoolExecutor(max_workers=count)
            pending = {}
            try:
                while todo or pending:
                    if psutil.virtual_memory().available < 4e9:
                        raise RuntimeError('Memory reserve fell below 4 GB; completed jobs remain resumable')
                    while todo and len(pending) < count and psutil.virtual_memory().available >= 4.75e9:
                        job = todo.pop(0)
                        pending[pool.submit(worker, job)] = job
                    done, _ = wait(pending, timeout=5, return_when=FIRST_COMPLETED) if pending else ([], [])
                    for future in done:
                        job = pending.pop(future)
                        row = future.result()
                        if job['kind'] != 'record':
                            save(job['out'], row)
                        results[job['identity']] = row
                    self.status(stage, completed=len(results), total=len(jobs), running=len(pending))
                    if not pending and todo:
                        time.sleep(5)
            except BaseException:
                bounded.abort_pool(pool)
                raise
            else:
                pool.shutdown()
        return [results[j['identity']] for j in jobs]

    def benchmark(self, reference):
        path = self.out/'benchmark.json'
        if path.exists():
            self.workers = min(read(path)['selected_workers'], self.limit())
            return
        smoke = dict(reference, T_end=180.)
        n = min(self.limit(), len(TRAIN)*len(rpc.LOADS))
        if n == 0:
            raise RuntimeError('Insufficient memory for benchmark')
        jobs = self.jobs('benchmark', 'B1', smoke, range(200, 200+max(2, n//3)))
        trials, checks = [], []
        for count in sorted(set((min(8, n), n))):
            start = time.monotonic()
            rows = self.run('benchmarking', jobs, force=True, workers=count)
            checksum = digest([r['metrics']['value_weighted_exposure'] for r in rows])
            trials.append(dict(workers=count, seconds=time.monotonic()-start, checksum=checksum))
            checks.append(checksum)
        if len(set(checks)) != 1:
            raise RuntimeError('Worker counts changed benchmark exposure')
        self.workers = min(trials, key=lambda r: r['seconds'])['workers']
        save(path, dict(selected_workers=self.workers, trials=trials, duration_s=180))


def normalization(rows):
    return {load: float(np.mean([r['metrics']['value_weighted_exposure'] for r in rows if r['load'] == load]))
            for load in rpc.LOADS}


def select_estimator(result):
    accepted = [v for v in result.get('validation', []) if v['validated_improvement']]
    if not accepted:
        return dict(params=dict(bounded.REFERENCE), status='calibration_failed_reference_retained')
    winner = min(accepted, key=lambda v: v['metrics']['proposed']['pooled']['nll_per_event'])
    return dict(params=winner['params'], status='validated_B1_estimator', validation=winner)


def estimator_stage(runner, reference, hours):
    folder = runner.out/'B1_recordings'
    for seeds in (TRAIN, DEV):
        runner.run('collecting_B1_reference', runner.jobs('B1_recordings', 'B1', reference, seeds, record=True))
    out = runner.out/'estimator'
    if not (out/'result.json').exists() or not read(out/'result.json').get('validation'):
        runner.status('B1_estimator_search', output=str(out))
        command = [sys.executable, '-u', '-m', 'experiments.run_bounded_calibration',
                   '--out', str(out), '--recording-dir', str(folder), '--recording-system', 'B1',
                   '--full-budget', '--hours', str(hours), '--workers', str(runner.workers)]
        command += ['--truth-process-mode', reference.get('truth_process_mode', 'historical_thinning')]
        with (runner.out/'estimator.log').open('a', encoding='utf-8') as stream:
            proc = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            try:
                while proc.poll() is None:
                    runner.status('B1_estimator_search', child_pid=proc.pid, output=str(out))
                    time.sleep(10)
            except BaseException:
                for child in psutil.Process(proc.pid).children(recursive=True):
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                proc.terminate()
                proc.wait(timeout=10)
                raise
        if proc.returncode:
            raise RuntimeError('B1 estimator search stopped; inspect estimator.log before resuming')
    result = select_estimator(read(out/'result.json'))
    save(runner.out/'estimator_selection.json', result)
    return result['params']


def freeze(runner, system, params, parent, selection):
    manifest = dict(system=system, parent=PARENTS[system], parent_hash=digest(parent),
                    config_hash=digest(params), params=params, selection=selection,
                    owned=sorted(OWNED[system]), switches=SWITCHES[system], source_identity=runner.identity)
    save(runner.out/'frozen'/f'{system}.json', manifest)
    return params


def restore_frozen(runner, system, parent, stored):
    if (stored['parent_hash'] != digest(parent) or stored['source_identity'] != runner.identity or
            stored['config_hash'] != digest(stored['params'])):
        raise ValueError(f'Stale or altered frozen configuration for {system}')
    additions = {k: stored['params'][k] for k in OWNED[system]}
    if derive(system, parent, additions) != stored['params']:
        raise ValueError(f'Frozen {system} violates inheritance')
    return stored['params']


def policy_stage(runner, reference, estimator):
    base = dict(reference, proposed_model_overrides=replay._sim_overrides(estimator))
    norms = {}
    for label, seeds in (('train', TRAIN), ('dev', DEV)):
        rows = runner.run(f'{label}_reference', runner.jobs(f'{label}_reference', 'B1', reference, seeds))
        norms[label] = normalization(rows)
    frozen = {}
    for system in SYSTEMS:
        parent = base if system == 'B1' else frozen[PARENTS[system]]
        path = runner.out/'frozen'/f'{system}.json'
        if path.exists():
            stored = read(path)
            frozen[system] = restore_frozen(runner, system, parent, stored)
            continue
        if not OWNED[system]:
            frozen[system] = freeze(runner, system, derive(system, parent), parent,
                                    {'status': 'paper_addition_no_free_parameters'})
            continue
        probe = derive(system, parent)
        rows = runner.run('training_margin_probe', runner.jobs(f'probe/{system}', system, probe, TRAIN, probe=True))
        margins = margin_values(rows, reference[MARGINS[system]])
        points = candidates(system, reference, margins)
        save(runner.out/'candidates'/f'{system}.json', dict(parent_hash=digest(parent),
             quantiles=Q, margins=margins, training_sample_count=sum(len(r['score_gaps']) for r in rows),
             space=candidate_space(system, reference, margins), candidates=points, seed=0))
        training = []
        for index, addition in enumerate(points):
            params = derive(system, parent, addition)
            rows = runner.run(f'train_{system}_{index}', runner.jobs(f'train/{system}/{index:03}', system, params, TRAIN))
            training.append(dict(index=index, additions=addition, score=exposure_score(rows, norms['train'], TRAIN),
                                 distance=distance(addition, reference)))
            save(runner.out/'selection'/f'{system}_training.json', training)
        finalists = sorted(training, key=lambda r: (r['score'], r['distance'], r['index']))[:3]
        development = []
        for candidate in finalists:
            params = derive(system, parent, candidate['additions'])
            rows = runner.run(f'dev_{system}_{candidate["index"]}', runner.jobs(
                f'dev/{system}/{candidate["index"]:03}', system, params, DEV))
            development.append(dict(candidate, development_score=exposure_score(rows, norms['dev'], DEV)))
        winner = min(development, key=lambda r: (r['development_score'], r['distance'], r['index']))
        grid = candidate_space(system, reference, margins)
        winner['boundary_parameters'] = [k for k, vals in grid.items()
                                         if winner['additions'][k] in (min(vals), max(vals))]
        save(runner.out/'selection'/f'{system}_development.json', development)
        frozen[system] = freeze(runner, system, derive(system, parent, winner['additions']), parent, winner)
    save(runner.out/'frozen_configs.json', frozen)
    return frozen


def paired_report(rows):
    """Seed-block intervals; never treat events or overlapping windows as replicates."""
    out = []
    wanted = ('value_weighted_exposure', 'completion_miss_fraction', 'deadline_miss_fraction',
              'mean_response_time_s', 'stl_robustness_cov', 'habituation_eta_mean',
              'eta_truth_at_application_all_mean', 'travel_distance_total')
    comparisons = list(itertools.combinations(('B1', 'B2', 'B3', 'B4', 'B5'), 2))
    comparisons += [(f'{s}_unchanged', s) for s in SYSTEMS]
    lookup = {(r['system'], r['load'], r['hab_on'], r['seed']): r for r in rows}
    seeds = sorted({r['seed'] for r in rows})
    for ref, treatment in comparisons:
        for load, hab, metric in itertools.product(rpc.LOADS, (True, False), wanted):
            pairs = [(lookup.get((ref, load, hab, s)), lookup.get((treatment, load, hab, s))) for s in seeds]
            if any(a is None or b is None for a, b in pairs):
                continue
            if any(metric not in a['metrics'] or metric not in b['metrics'] for a, b in pairs):
                continue
            delta = np.array([b['metrics'][metric]-a['metrics'][metric] for a, b in pairs])
            rng = np.random.default_rng(0)
            lo, hi = np.percentile(delta[rng.integers(0, len(delta), (10000, len(delta)))].mean(axis=1), [2.5, 97.5])
            out.append(dict(reference=ref, treatment=treatment, load=load, hab_on=hab, metric=metric,
                            n=len(delta), mean_difference=float(delta.mean()), ci95=[float(lo), float(hi)]))
    return out


def service_metrics(row):
    metrics = row['metrics']
    generated = metrics.get('reactive_generated_total', 0)
    if generated > 0:
        metrics['completion_miss_fraction'] = 1-metrics['reactive_completed_total']/generated
        metrics['deadline_miss_fraction'] = 1-metrics['reactive_on_time_total']/generated
    return row


def final_stages(runner, reference, frozen):
    # New closed-loop recordings under every frozen policy: offline truth never enters the policy.
    forecast = {}
    for system, params in frozen.items():
        tag = f'fresh_recordings/{system}'
        jobs = runner.jobs(tag, system, params, FRESH, record=True)
        for job in jobs:
            # The replay reconstructs the actual fitted collecting estimator, not the old reference.
            job['recording_constants'] = {k: params['proposed_model_overrides'][v]
                                         for k, v in {
                'sigma':'sigma', 'omega':'omega', 'omega_inhib':'omega_inhib', 'alpha_in':'alpha_in',
                'alpha_cross':'alpha_cross', 'alpha_inhib':'alpha_inhib', 'mu_base':'mu_base', 'bg_ema':'bg_ema',
                'feedback_sigma_scale':'model_feedback_sigma_scale',
                'feedback_omega_scale':'model_feedback_omega_scale'}.items()}
            identity_job = {k:v for k,v in job.items() if k not in ('identity', 'out')}
            job['identity'] = digest(dict(identity_job, source=runner.identity))
        runner.run('fresh_closed_loop_validation', jobs)
        params_model = jobs[0]['recording_constants']
        evaluator = bounded.Evaluator(runner.out/'fresh_scores'/system, runner.workers, print,
                                      [j['out'] for j in jobs], deadline=time.monotonic()+3600,
                                      progress=runner.status, max_configs={'proposed': 2})
        try:
            baseline = evaluator.evaluate_one('proposed', bounded.REFERENCE, bounded.REFERENCE)
            calibrated = evaluator.evaluate_one('proposed', bounded.REFERENCE, params_model)
            forecast[system] = dict(reference=baseline['metrics'], calibrated=calibrated['metrics'],
                                    failures=[load for load in rpc.LOADS if
                       calibrated['metrics']['proposed']['per_load'][load]['nll_per_event'] >
                       baseline['metrics']['proposed']['per_load'][load]['nll_per_event'] or
                       calibrated['metrics']['proposed']['per_load'][load]['brier'] >
                       baseline['metrics']['proposed']['per_load'][load]['brier']+.005])
        finally:
            evaluator.close()
        save(runner.out/'fresh_validation.json', forecast)
    rows = []
    unchanged = {'B1': reference}
    for system in SYSTEMS[1:]:
        unchanged[system] = derive(system, unchanged[PARENTS[system]])
    for arm, configs in (('calibrated', frozen), ('unchanged', unchanged)):
        for system, params in configs.items():
            label = system if arm == 'calibrated' else system+'_unchanged'
            jobs = runner.jobs(f'evaluation/{arm}', label, params, EVAL, habs=(True, False))
            rows.extend(service_metrics(r) for r in runner.run('evaluating_B1_B5', jobs))
            save(runner.out/'evaluation_rows.json', rows)
    save(runner.out/'paired_comparisons.json', paired_report(rows))
    save(runner.out/'evaluation_summary.json', dict(
        metric_means=[dict(system=s, load=l, hab_on=h,
             means={k: float(np.mean([r['metrics'][k] for r in group if k in r['metrics']]))
                    for k in sorted(set.intersection(*(set(r['metrics']) for r in group)))})
        for s,l,h in itertools.product(sorted({r['system'] for r in rows}), rpc.LOADS, (True,False))
        if (group := [r for r in rows if (r['system'],r['load'],r['hab_on']) == (s,l,h)])],
        fresh_forecast_validation=forecast, seeds=EVAL, deployed=False))


def export_improvement_configs(runner, frozen):
    """Carry shared calibration into A--E while retaining each declared controlled factor."""
    out = {}
    for variant in ('A', 'B', 'C', 'D_plan', 'E_plan'):
        parent = frozen['B4'] if variant in ('A', 'B', 'C') else frozen['B5']
        params = deepcopy(parent)
        if variant in rpc.B4_VARIANTS:
            _, changes = rpc.B4_VARIANTS[variant]
        else:
            _, changes = rpc.PLAN_VARIANTS[variant]
        params.update(deepcopy(changes))
        if variant in ('D_plan', 'E_plan'):
            params['stl_forecast_correction'] = True
        out[variant] = dict(params=params, calibration_parent='B4' if variant in ('A','B','C') else 'B5',
                            parent_hash=digest(parent), controlled_changes=changes,
                            retuned=False, evaluation_seeds=EVAL)
    if out['A']['params'] != frozen['B4']:
        raise ValueError('Improvement arm A must equal B4')
    save(runner.out/'improvement_plan_configs.json', out)


def improvement_evaluation(runner, frozen):
    """Separate, untuned A--E evaluation; one outer job for nested rollout planners."""
    arms = read(runner.out/'improvement_plan_configs.json')
    rows = []
    # A reuses the identical B4 runs, including their source/config identity.
    for variant, params in [('B5', frozen['B5']), ('A', frozen['B4']),
                            *[(v, arms[v]['params']) for v in ('B','C','D_plan','E_plan')]]:
        label = 'B4' if variant == 'A' else variant
        tag = 'evaluation/calibrated' if variant in ('A','B5') else 'improvement_evaluation'
        previous = runner.workers
        if variant in ('D_plan','E_plan'):
            runner.workers = 1
        try:
            jobs = runner.jobs(tag, label, params, EVAL, habs=(True,False))
            rows.extend(dict(service_metrics(r), system=variant) for r in runner.run('evaluating_A_E', jobs))
        finally:
            runner.workers = previous
        save(runner.out/'improvement_evaluation_rows.json', rows)
    # Use the established improvement-plan paired analysis, including its service criterion.
    version = rpc.code_version()
    report_rows = [dict(r['metrics'], variant=r['system'], baseline=r['load'],
                       seed=r['seed'], habituation_condition='hab_on' if r['hab_on'] else 'hab_off',
                       **version) for r in rows]
    # This standalone arm has fixed, explicitly enumerated contrasts.
    contrasts = [('A','B','B versus A'), ('B','C','C versus B'),
                 ('C','D_plan','D versus C'), ('D_plan','E_plan','E versus D'),
                 ('B5','E_plan','E versus B5')]
    reports = []
    for load in rpc.LOADS:
        subset = [r for r in report_rows if r['baseline'] == load]
        for hab in ('hab_on','hab_off'):
            reports.extend(dict(r, load=load, habituation_condition=hab) for r in rpc.analyze(
                subset, hab=hab, comparisons=contrasts, expected_seeds=EVAL))
    save(runner.out/'improvement_paired_comparisons.json', reports)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'results/hierarchical_acc_calibration')
    parser.add_argument('--workers', type=int, default=0)
    parser.add_argument('--estimator-hours', type=float, default=4.)
    parser.add_argument('--phase', choices=('estimator','policy','all','improvement'), default='all')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.workers < 0 or not 0 < args.estimator_hours <= 4:
        raise ValueError('Invalid resource/time budget')
    reference = paper_reference()
    if args.dry_run:
        print(json.dumps(dict(parents=PARENTS, ownership={s:sorted(k) for s,k in OWNED.items()},
                              reference_hash=digest(reference), seeds=dict(training=TRAIN, development=DEV,
                              fresh=FRESH, evaluation=EVAL), candidate_caps=dict(estimator=81,policy=48)), indent=2))
        return
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    lock = args.out/'RUNNING.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    runner = None
    try:
        runner = Runner(args.out, args.workers)
        manifest = dict(source=runner.source, source_identity=runner.identity, machine=runner.machine,
                        reference=reference, parents=PARENTS, ownership={s:sorted(v) for s,v in OWNED.items()},
                        switches=SWITCHES, training=TRAIN, development=DEV, fresh=FRESH, evaluation=EVAL,
                        objective='equal-load mean normalized exposure; no service selection constraint',
                        specifications='paper requirements unchanged; no quantile mapping',
                        estimator_cap=81, policy_cap=48, estimator_hours=args.estimator_hours)
        existing = args.out/'manifest.json'
        if existing.exists() and digest(read(existing)) != digest(manifest):
            raise ValueError('Manifest/source changed; use a new output directory rather than mixing results')
        save(existing, manifest)
        runner.benchmark(reference)
        if args.phase == 'improvement':
            frozen = read(runner.out/'frozen_configs.json')
            export_improvement_configs(runner, frozen)
            improvement_evaluation(runner, frozen)
            runner.status('finished', phase=args.phase)
            return
        estimator = estimator_stage(runner, reference, args.estimator_hours)
        if args.phase == 'estimator':
            runner.status('estimator_finished')
            return
        frozen = policy_stage(runner, reference, estimator)
        export_improvement_configs(runner, frozen)
        if args.phase == 'all':
            final_stages(runner, reference, frozen)
        runner.status('finished', phase=args.phase)
    except BaseException as exc:
        if runner:
            runner.status('stopped', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
