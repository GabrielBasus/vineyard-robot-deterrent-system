"""Budget, bounds, balancing and data separation checks; no search is executed."""
import time
import json
import pickle
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from experiments import run_bounded_calibration as bc
from experiments import collect_calibration_recordings as collection


@pytest.mark.parametrize('stage,axes,n', [('prediction',bc.PRED_AXES,24),('proposed',bc.PROP_AXES,48)])
def test_candidate_sets_are_bounded_deterministic_and_reference_preserving(stage,axes,n):
    include = [bc.REFERENCE]
    if stage=='proposed':
        include.append(dict(bc.REFERENCE,alpha_inhib=0.0))
    a = bc.candidates(bc.REFERENCE,axes,n,123,include=include)
    assert a==bc.candidates(bc.REFERENCE,axes,n,123,include=include)
    assert len(a)==n and a[0]==bc.REFERENCE
    if stage=='proposed':
        assert a[1]['alpha_inhib']==0.0
    for point in a:
        bc.validate_params(point)
        for key in set(bc.REFERENCE)-set(axes):
            assert point[key]==bc.REFERENCE[key]


def test_local_probes_respect_bounds_even_on_a_boundary():
    center = dict(bc.REFERENCE,sigma=80,alpha_inhib=0)
    for p in bc.candidates(center,bc.PROP_AXES,16,123,local=True):
        bc.validate_params(p)


@pytest.mark.parametrize('change', [{'sigma':1280},{'omega':1e9},{'alpha_cross':1.0},{'mu_base':float('nan')}])
def test_invalid_or_fixed_parameter_changes_are_rejected(change):
    with pytest.raises(ValueError):
        bc.validate_params(dict(bc.REFERENCE,**change))


def test_metrics_balance_loads_and_normalize_each_recording_before_averaging():
    rows = [dict(load='spare',truth_events=10,proposed_nll=20,proposed_field_brier=.1,
                 proposed_field_logloss=.2,proposed_expected_events=10)]*3
    rows += [dict(load='overload',truth_events=1000,proposed_nll=4000,proposed_field_brier=.3,
                  proposed_field_logloss=.4,proposed_expected_events=1100)]
    m = bc.pool_metrics(rows,'proposed')
    assert m['pooled']['nll_per_event']==3.0
    assert m['pooled']['brier']==pytest.approx(.2)
    assert m['pooled']['relative_count_bias']==pytest.approx(.05)


@pytest.mark.parametrize('seeds', [(300,),(-1,),(200,310)])
def test_evaluation_or_negative_seeds_are_never_calibration_inputs(seeds):
    with pytest.raises(ValueError):
        bc.paths_for(seeds)


def test_validation_and_training_seeds_are_disjoint_and_all_precede_evaluation():
    assert not set(bc.TRAIN_SEEDS)&set(bc.VALIDATION_SEEDS)
    assert max((*bc.TRAIN_SEEDS,*bc.VALIDATION_SEEDS))<300


@pytest.mark.parametrize('changes',[{'seed':201},{'mu':4e-4},{'NX':120},{'units':'density'}])
def test_recording_preflight_rejects_wrong_experiment_metadata(tmp_path,changes):
    record=dict(units='mass_per_cell',rec_constants=bc.REFERENCE,load='spare',seed=200,
                mu=2e-5,W=500.,H=500.,NX=60,NY=48,dt=1.,truth_events=[(0,0,.5)],log=[('step',1801)])
    p=tmp_path/'spare_200.pkl'
    p.write_bytes(pickle.dumps(record))
    bc.validate_recordings([str(p)])
    p.write_bytes(pickle.dumps(dict(record,**changes)))
    with pytest.raises(ValueError):
        bc.validate_recordings([str(p)])


def test_benchmark_cannot_expand_candidate_budget():
    assert bc.budget_for_estimate(100,14400)==bc.MAX_BUDGET
    reduced = bc.budget_for_estimate(20000,14400)
    assert all(reduced[k]<=bc.MAX_BUDGET[k] for k in reduced)
    with pytest.raises(bc.SearchStop):
        bc.budget_for_estimate(1e9,14400)


def test_timeout_terminates_workers_instead_of_waiting_past_the_cap():
    events=[]
    proc=SimpleNamespace(is_alive=lambda:True,terminate=lambda:events.append('terminate'),
                         join=lambda timeout:events.append('join'))
    pool=SimpleNamespace(_processes={1:proc},shutdown=lambda **kwargs:events.append('shutdown'))
    ev=object.__new__(bc.Evaluator)
    ev.pool,ev.deadline,ev.aborted=pool,time.monotonic()-1,False
    with pytest.raises(bc.SearchStop):
        ev.check_time()
    assert ev.aborted and events==['terminate','shutdown','join']


def test_candidate_budget_rejects_additional_evaluations_before_launching_workers():
    ev=object.__new__(bc.Evaluator)
    ev.cache={'other':dict(stage='prediction')}
    ev.max_configs={'prediction':1}
    with pytest.raises(bc.SearchStop,match='candidate-count'):
        ev.evaluate_one('prediction',bc.REFERENCE,bc.REFERENCE)


def test_evaluator_creates_nested_cache_directory_before_first_candidate(tmp_path):
    recording=tmp_path/'input.pkl'
    recording.write_bytes(b'input fingerprint')
    out=tmp_path/'new'/'training'
    ev=bc.Evaluator(out,1,lambda _:None,[str(recording)],deadline=time.monotonic()+10,
                    progress=lambda *a,**kw:None,max_configs=bc.MAX_BUDGET)
    try:
        assert ev.cache_path.parent.is_dir()
        ev.cache_path.write_text('')
    finally:
        ev.close()


def test_atomic_json_retries_transient_reader_locks(tmp_path,monkeypatch):
    real=Path.replace
    calls=[]
    def replace(source,target):
        calls.append(1)
        if len(calls)<3:
            raise PermissionError('reader holds target')
        return real(source,target)
    monkeypatch.setattr(Path,'replace',replace)
    monkeypatch.setattr(bc.time,'sleep',lambda _:None)
    target=tmp_path/'status.json'
    assert bc.atomic_json(target,{'stage':'running'})
    assert json.loads(target.read_text())['stage']=='running'
    assert len(calls)==3 and not list(tmp_path.glob('*.tmp'))


def test_optional_status_failure_does_not_abort_work_and_required_outputs_still_fail(tmp_path,monkeypatch):
    def denied(*args,**kwargs):
        raise PermissionError('persistent reader lock')
    monkeypatch.setattr(Path,'replace',denied)
    monkeypatch.setattr(bc.time,'sleep',lambda _:None)
    assert bc.atomic_json(tmp_path/'status.json',{},best_effort=True) is False
    with pytest.raises(PermissionError):
        bc.atomic_json(tmp_path/'result.json',{})
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.skipif(os.name!='nt',reason='Windows file sharing regression')
def test_real_windows_status_reader_does_not_abort_calculation(tmp_path,monkeypatch):
    target=tmp_path/'status.json'
    target.write_text('{"stage":"old"}')
    monkeypatch.setattr(bc.time,'sleep',lambda _:None)
    with target.open('r') as reader:
        assert bc.atomic_json(target,{'stage':'new'},best_effort=True) is False
        assert json.load(reader)['stage']=='old'
    assert bc.atomic_json(target,{'stage':'new'})


def test_recording_concurrency_uses_available_cores_and_keeps_memory_reserve():
    assert collection.worker_limit(18.6,24,22)==22
    assert collection.worker_limit(5.0,24,22)==2
    assert collection.worker_limit(4.4,24,22)==0
    assert collection.worker_limit(30,24,22,8)==8


def test_new_collector_cannot_use_evaluation_seeds():
    with pytest.raises(ValueError,match='Evaluation seeds'):
        collection.pending_jobs([300])


def test_atomic_recording_is_published_only_after_success(tmp_path,monkeypatch):
    target=tmp_path/'spare_200.pkl'
    def record(job):
        assert not target.exists()
        Path(job['out']).write_bytes(b'complete recording')
        return {'seed':200}
    monkeypatch.setattr(collection.replay,'record_run',record)
    assert collection.record_atomic({'out':str(target)})=={'seed':200}
    assert target.read_bytes()==b'complete recording'
    assert not list(tmp_path.glob('*.partial'))


def test_ranking_prefers_reference_when_primary_scores_are_numerically_tied():
    def row(p,key):
        return dict(key=key,prop=p,metrics={'proposed':{'pooled':dict(nll_per_event=2.,brier=.1,logloss=.2)}})
    reference=row(bc.REFERENCE,'reference')
    other=row(dict(bc.REFERENCE,sigma=40),'other')
    assert bc.ranked_unique([other,reference,other],'proposed')==[reference,other]


@pytest.mark.parametrize('stage,prefix',[('prediction','prediction_only'),('proposed','proposed'),('joint',None)])
def test_evaluator_scores_only_active_arms_and_caches_complete_candidates(tmp_path,stage,prefix):
    ev=object.__new__(bc.Evaluator)
    ev.workers=1
    ev.cache,ev.max_configs={},dict(bc.MAX_BUDGET)
    ev.version={'scoring_version':'test'}
    ev.paths=['spare_200.pkl','heavy_200.pkl']
    ev.progress=lambda *args,**kw:None
    ev.cache_path=tmp_path/'cache.jsonl'
    def execute(jobs):
        data=[]
        for job in jobs:
            row=dict(truth_events=10)
            for arm in ('prediction_only','proposed'):
                active=stage=='joint' or prefix==arm
                row.update({arm+'_nll':20. if active else float('nan'),
                            arm+'_field_brier':.1 if active else float('nan'),
                            arm+'_field_logloss':.2 if active else float('nan'),
                            arm+'_expected_events':10. if active else float('nan')})
            data.append(row)
        return data
    ev.execute=execute
    row=ev.evaluate_one(stage,bc.REFERENCE,bc.REFERENCE)
    assert set(row['metrics'])==({'prediction_only','proposed'} if stage=='joint' else {prefix})
    assert len(json.loads(ev.cache_path.read_text())['runs'])==2
    ev.execute=lambda _:pytest.fail('complete cache entry must not be replayed')
    assert ev.evaluate_one(stage,bc.REFERENCE,bc.REFERENCE) is row
