"""Protocol invariants and runtime integration for frozen calibration inheritance."""
from copy import deepcopy
import json
import pickle

import numpy as np
import pytest

from experiments import run_hierarchical_calibration as h
from TaskGenerator import score_margin_scale, resolve_score_margin


@pytest.fixture
def reference():
    return h.paper_reference()


def hierarchy(reference):
    configs = {}
    for s in h.SYSTEMS:
        configs[s] = h.derive(s, reference if s == 'B1' else configs[h.PARENTS[s]])
    return configs


def test_materialization_preserves_paper_values_without_runtime_profile(reference):
    assert reference['planner_profile'] == ''
    assert reference['planner_profile_overrides'] is None
    assert reference['use_frozen_calibration'] is False
    assert reference['model_deterring_score_margin_legacy'] == .1
    assert reference['assigner_w_task_value'] == .2
    assert reference['proposed_model_overrides'] == h.replay._sim_overrides(h.bounded.REFERENCE)
    assert reference['legacy_stamp_units'] == 'mass_per_cell'
    assert reference['truth_deterrence_memory'] == 'complete'
    assert reference['random_stream_mode'] == 'coupled'


@pytest.mark.parametrize('system,change', [
    ('B2', {'patrol_cost_weight': .01}), ('B3', {'reservation_fraction': .4}),
    ('B4', {'model_deterring_score_margin_stl': .5}),
    ('B5', {'model_deterring_score_margin_legacy': .5}),
    ('B1', {'stl_E_star': 99}), ('B3', {'stl_T_cov_s': 10}),
    ('B4', {'stl_eta_min': .1}), ('B5', {'deterring_modes': {}}),
    ('B2', {'dispatch_policy': 'unc'}), ('B1', {'proposed_model_overrides': {}}),
])
def test_rejects_retuning_shared_components_specifications_and_switches(reference, system, change):
    with pytest.raises(ValueError):
        h.derive(system, reference, change)


def test_inheritance_has_two_branches_and_freezes_all_other_parameters(reference):
    tuned_b1 = h.derive('B1', reference, {'patrol_cost_weight': .07, h.MARGINS['B1']: -.2})
    tuned_b2 = h.derive('B2', tuned_b1, {'reservation_fraction': .4, h.MARGINS['B2']: .3})
    tuned_b3 = h.derive('B3', tuned_b2, {h.MARGINS['B3']: -.1})
    configs = {'B1': tuned_b1, 'B2': tuned_b2, 'B3': tuned_b3,
               'B4': h.derive('B4', tuned_b3), 'B5': h.derive('B5', tuned_b1)}
    for s, params in configs.items():
        assert params['patrol_cost_weight'] == .07
        assert params[h.MARGINS['B1']] == -.2
        for key in h.STL_REQUIREMENTS:
            assert params[key] == reference[key]
        if s in ('B3', 'B4'):
            assert params['reservation_fraction'] == .4
            assert params[h.MARGINS['B2']] == .3
    assert configs['B4'][h.MARGINS['B3']] == -.1
    assert configs['B5']['dispatch_policy'] == 'unc'
    assert configs['B5'][h.MARGINS['B2']] == reference[h.MARGINS['B2']]
    assert configs['B3']['predictive_fixed_deterring_mode'] == 'laser'
    assert configs['B4']['predictive_fixed_deterring_mode'] is None


@pytest.mark.parametrize('s', ('B1','B2','B3'))
def test_candidates_are_finite_deterministic_owned_and_include_reference(reference, s):
    margins = [-5, 0, .1, 3, 9]
    points = h.candidates(s, reference, margins)
    assert points == h.candidates(s, reference, margins)
    assert 1 <= len(points) <= 48
    assert len({h.digest(p) for p in points}) == len(points)
    for k,v in points[0].items():
        assert v == reference[k]
    for p in points:
        assert set(p) <= h.OWNED[s]
        for k in h.POSITIVE:
            if k in p:
                assert reference[k]*.001 <= p[k] <= reference[k]*10
        if s == 'B1':
            assert p['forecast_horizon_s'] == p['stl_horizon_s']
            assert p['model_deterring_max_eta_s'] == p['predictive_lead_time_max_eta_s']
    if s == 'B3':
        assert len(points) == len(margins)


def test_quantiles_are_empirical_include_reference_and_do_not_fail_when_no_checks():
    assert h.margin_values([], .1) == [.1]
    vals = h.margin_values([{'score_gaps': [-3, 0, 5, float('nan')]}], .1)
    assert -3 in vals and 5 in vals and .1 in vals
    assert all(np.isfinite(vals))


def test_equal_load_exposure_selection_ignores_service():
    rows = [dict(load=l, seed=s, metrics={'value_weighted_exposure': v, 'reactive_miss_fraction': 1})
            for l,v in zip(h.rpc.LOADS, [10, 1000, 30000]) for s in (200,201)]
    norms = dict(zip(h.rpc.LOADS, [10, 100, 1000]))
    assert h.exposure_score(rows, norms, (200,201)) == pytest.approx(41/3)
    with pytest.raises(ValueError):
        h.exposure_score(rows[:-1], norms, (200,201))
    with pytest.raises(ValueError):
        h.exposure_score(rows+[rows[0]], norms, (200,201))


def test_no_estimator_finalist_is_adopted_unless_guardrails_pass():
    bad = dict(params=dict(h.bounded.REFERENCE, sigma=80), validated_improvement=False)
    assert h.select_estimator({'validation': [bad]})['params'] == h.bounded.REFERENCE
    good = dict(bad, validated_improvement=True,
                metrics={'proposed': {'pooled': {'nll_per_event': 1}}})
    assert h.select_estimator({'validation': [bad,good]})['params'] == good['params']


def test_checkpoints_require_exact_identity_and_reject_B5_recordings(tmp_path):
    path = tmp_path/'spare_200.pkl'
    path.write_bytes(pickle.dumps({'recording_identity': 'old', 'recording_system': 'B5_c'}))
    with pytest.raises(ValueError, match='Stale recording'):
        h.cached(dict(kind='record', out=path, identity='new'))
    with pytest.raises(ValueError, match='another policy'):
        h.bounded.validate_recordings([path], expected_system='B1')
    path = tmp_path/'job.json'
    h.save(path, {'identity': 'matching'})
    assert h.cached(dict(kind='simulation', out=path, identity='matching'))['identity'] == 'matching'
    with pytest.raises(ValueError, match='Stale simulation'):
        h.cached(dict(kind='simulation', out=path, identity='other'))


def test_evaluation_seeds_cannot_enter_search_jobs(tmp_path, reference):
    runner = h.Runner(tmp_path, 1)
    for options in ({'record': True}, {'probe': True}):
        with pytest.raises(ValueError):
            runner.jobs('fresh', 'B1', reference, [300], **options)
    with pytest.raises(ValueError):
        runner.jobs('train/B1', 'B1', reference, [300])
    assert len(runner.jobs('evaluation', 'B1', reference, [300])) == 3


def test_deltaJ_scale_is_separate_and_defaults_remain_compatible():
    assert score_margin_scale('deltaJ') == 'deltaJ'
    assert resolve_score_margin('deltaJ', .1, legacy=9, stl=8) == .1
    assert resolve_score_margin('deltaJ', .1, deltaJ=.7, legacy=9) == .7
    assert score_margin_scale('legacy_habituation') == 'legacy'


@pytest.mark.parametrize('s', h.SYSTEMS)
def test_live_runtime_configuration_and_margin_routing(reference, s):
    import DeterrentSystem as ds
    params = hierarchy(reference)[s]
    params.update(T_end=2., seed=200)
    params.update({h.MARGINS['B1']: .31, h.MARGINS['B2']: .42, h.MARGINS['B3']: .53})
    gen = ds.run_simulation_frames_persistent(**params)
    try:
        next(gen)
        local = gen.gi_frame.f_locals
        h.audit_runtime(local, params)
        scale = 'legacy' if s in ('B1','B5') else 'deltaJ' if s == 'B2' else 'stl'
        assert local['taskgen'].last_score_margin == (scale, {'legacy':.31, 'deltaJ':.42, 'stl':.53}[scale])
        corrupted = dict(params, patrol_cost_weight=99)
        with pytest.raises(RuntimeError, match='patrol_cost_weight'):
            h.audit_runtime(local, corrupted)
    finally:
        gen.close()


def test_improvement_export_keeps_A_equal_B4_and_declared_factors(tmp_path, reference):
    runner = h.Runner(tmp_path, 1)
    configs = hierarchy(reference)
    h.export_improvement_configs(runner, configs)
    arms = h.read(tmp_path/'improvement_plan_configs.json')
    assert arms['A']['params'] == configs['B4']
    assert arms['B']['params']['stl_forecast_correction'] is True
    assert arms['C']['params']['stl_valuation_mode'] == 'integrated_exposure_eq3'
    assert arms['D_plan']['params']['dispatch_policy'] == 'unc'
    assert arms['D_plan']['params']['plan_service_protection'] is False
    assert arms['E_plan']['params']['plan_service_protection'] is True
    for arm in arms.values():
        assert arm['params']['proposed_model_overrides'] == configs['B1']['proposed_model_overrides']
        assert arm['retuned'] is False


def test_completion_and_deadline_misses_remain_distinct():
    row = {'metrics': dict(reactive_generated_total=10, reactive_completed_total=8, reactive_on_time_total=6)}
    h.service_metrics(row)
    assert row['metrics']['completion_miss_fraction'] == pytest.approx(.2)
    assert row['metrics']['deadline_miss_fraction'] == pytest.approx(.4)


def test_frozen_resume_rejects_changed_parent_changed_owned_or_inherited_values(tmp_path, reference):
    runner = h.Runner(tmp_path, 1)
    params = h.derive('B2', reference, {'reservation_fraction': .4})
    h.freeze(runner, 'B2', params, reference, {})
    stored = h.read(tmp_path/'frozen/B2.json')
    assert h.restore_frozen(runner, 'B2', reference, stored) == params
    with pytest.raises(ValueError):
        h.restore_frozen(runner, 'B2', dict(reference, patrol_cost_weight=2), stored)
    changed = deepcopy(stored)
    changed['params']['reservation_fraction'] = .1
    with pytest.raises(ValueError):
        h.restore_frozen(runner, 'B2', reference, changed)
    changed['params']['patrol_cost_weight'] = 3
    changed['config_hash'] = h.digest(changed['params'])
    with pytest.raises(ValueError, match='inheritance'):
        h.restore_frozen(runner, 'B2', reference, changed)


def test_B1_recording_and_replay_use_identical_fixed_unit_fields(tmp_path, reference):
    params = dict(reference, T_end=60., mu_true=h.rpc.LOADS['overload'])
    path = tmp_path/'overload_200.pkl'
    h.replay.record_run(dict(params=params, runtime_expectations=params, load='overload',
        mu=h.rpc.LOADS['overload'], seed=200, out=str(path), check_lam=True,
        system='B1', identity='B1-test', recording_constants=h.bounded.REFERENCE))
    with path.open('rb') as stream:
        rec = pickle.load(stream)
    assert rec['recording_system'] == 'B1'
    assert rec['recording_identity'] == 'B1-test'
    result = h.replay.replay(rec, h.bounded.REFERENCE, True, keep_lam=True)
    assert len(rec['live_lam']) > 20
    # See the audited scorer's existing reconstruction check for the output convention.
    assert np.array_equal(np.asarray(result['lam']), np.asarray(rec['live_lam']))


def test_policy_pipeline_selects_only_exposure_and_resumes_frozen_parents(tmp_path, reference):
    class FakeRunner(h.Runner):
        def run(self, stage, jobs, **kw):
            rows = []
            for j in jobs:
                p = j['params']
                score = (100 + p['patrol_cost_weight'] + p['reservation_fraction'] +
                         abs(p['model_deterring_score_margin_stl']))
                rows.append(dict(load=j['load'], seed=j['seed'], score_gaps=[-2.,0.,2.],
                                 metrics={'value_weighted_exposure': score,
                                          'reactive_miss_fraction': 1-p['patrol_cost_weight']/10}))
            return rows
    runner = FakeRunner(tmp_path, 1)
    chosen = h.policy_stage(runner, reference, h.bounded.REFERENCE)
    assert chosen['B1']['patrol_cost_weight'] < reference['patrol_cost_weight']
    for s,p in chosen.items():
        assert p['patrol_cost_weight'] == chosen['B1']['patrol_cost_weight']
        assert p['proposed_model_overrides'] == reference['proposed_model_overrides']
        if s in ('B3','B4'):
            assert p['reservation_fraction'] == chosen['B2']['reservation_fraction']
    assert h.policy_stage(runner, reference, h.bounded.REFERENCE) == chosen
    for s in ('B4','B5'):
        assert h.read(tmp_path/f'frozen/{s}.json')['selection']['status'] == 'paper_addition_no_free_parameters'


def test_separate_improvement_analysis_accepts_exported_rows(tmp_path, reference):
    class FakeRunner(h.Runner):
        def run(self, stage, jobs, **kw):
            return [dict(system=j['system'], load=j['load'], seed=j['seed'], hab_on=j['hab_on'],
                         metrics=dict(value_weighted_exposure=10+j['seed'], reactive_generated_total=10,
                                      reactive_completed_total=8, reactive_on_time_total=6,
                                      reactive_miss_fraction=.2)) for j in jobs]
    runner = FakeRunner(tmp_path, 1)
    frozen = hierarchy(reference)
    h.export_improvement_configs(runner, frozen)
    h.improvement_evaluation(runner, frozen)
    rows = h.read(tmp_path/'improvement_evaluation_rows.json')
    assert {r['system'] for r in rows} == {'A','B','C','D_plan','E_plan','B5'}
    assert len(rows) == 6*3*10*2
    assert h.read(tmp_path/'improvement_paired_comparisons.json')


def test_paired_report_uses_seed_pairs():
    rows = [dict(system=s, load=l, seed=seed, hab_on=hab, metrics={'value_weighted_exposure': v+seed})
            for s,v in [('B1',10),('B2',12)] for l in h.rpc.LOADS
            for seed in (300,301) for hab in (True,False)]
    report = h.paired_report(rows)
    assert len(report) == 6
    assert all(r['mean_difference'] == 2 and r['ci95'] == [2,2] and r['n'] == 2 for r in report)
