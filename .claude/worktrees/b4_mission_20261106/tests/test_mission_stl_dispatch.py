from copy import deepcopy
from dataclasses import replace
from unittest import mock

import numpy as np
import pytest

import mission_stl_dispatch as mission
from mission_stl_dispatch import (
    MissionContext, MissionRobot, MissionSpec, MissionTask,
    forecast_margins, pending_schedule, select_mission_task,
)
from experiments.b4_mission_profile import build_b4_mission


def spec(**changes):
    return replace(MissionSpec(E_star=100., T_cov_s=1000., eta_min=.4,
                              horizon_s=100., monitor_dt_s=30., theta=12., omega_e_s=600.), **changes)


def task(task_id, **changes):
    return replace(MissionTask(task_id=task_id, robot_id='r', created_t=0., target_xy=(0., 0.),
                               cell_id=0, service_s=5., reactive=False, deterring=True), **changes)


def context(tasks, **changes):
    return replace(MissionContext(now_t=0., exposure=(0.,), coverage_age=(0.,),
                                  robots=(MissionRobot('r', (0., 0.), 1.),),
                                  tasks=tuple(tasks), spec=spec()), **changes)


def test_original_deadline_not_restarted_at_decision():
    ctx = context([task(1, reactive=True, service_s=20.)], now_t=80.)
    margins = forecast_margins(ctx, pending_schedule(ctx), np.array([0., 20., 100.]))
    # Original deadline 90, current time 80, completion at 100: ten seconds late.
    assert margins['react'][0] == pytest.approx(-10. / 90.)


def test_reactive_service_consequence_changes_selection():
    ctx = context([task(1, created_t=-10., service_s=20.), task(2, reactive=True, service_s=5.)], now_t=80.)
    chosen, diag = select_mission_task(ctx, 'r')
    assert chosen == 2
    assert diag['selected_value'] > 0
    assert set(diag['reference_clauses']) == {'exp', 'cov', 'hab', 'react'}
    # Removing the actual reactive obligation removes the reason to reorder.
    no_obligation = replace(ctx, tasks=tuple(replace(t, reactive=False) for t in ctx.tasks))
    assert select_mission_task(no_obligation, 'r')[0] == 1


@pytest.mark.parametrize('reactive', [True, False])
def test_effectiveness_floor_applies_to_both_deterrence_streams(reactive):
    ctx = context([task(1, reactive=reactive, eta=.1, service_s=0.),
                   task(2, eta=1., service_s=20.)], spec=spec(horizon_s=10.))
    assert select_mission_task(ctx, 'r')[0] == 2


def test_patrol_has_no_suppression_or_deterrence_recency_reset():
    patrol = task(1, deterring=False, beta=100., eta=.1, service_s=0.)
    ctx = context([patrol], exposure=(10.,), coverage_age=(30.,))
    times = np.array([0., 10.])
    margins = forecast_margins(ctx, pending_schedule(ctx), times)
    assert margins['cov'][0, 1] == pytest.approx((1000. - 40.) / 1000.)
    assert margins['exp'][0, 0] == pytest.approx(.9)
    assert margins['hab'][0, 0] == pytest.approx(1.)


def test_future_deter_completion_resets_coverage_and_reduces_exposure():
    ctx = context([task(1, service_s=5., beta=2., eta=.5)], exposure=(10.,), coverage_age=(30.,))
    times = np.array([0., 5., 6.])
    margins = forecast_margins(ctx, pending_schedule(ctx), times)
    assert margins['cov'][0, 1] == pytest.approx(1.)
    assert margins['cov'][0, 2] == pytest.approx(.999)
    assert margins['exp'][0, 1] == pytest.approx((100. - (10.*np.exp(-5./600.) - 1.)) / 100.)


def test_holds_cannot_be_interrupted_even_by_urgent_reactive_work():
    ctx = context([task(1), task(2, reactive=True)], now_t=85.,
                  robots=(MissionRobot('r', (0., 0.), 1., current_task_id=1, hold_until_t=105.),))
    chosen, diag = select_mission_task(ctx, 'r')
    assert chosen == 1 and diag['holding']
    events = pending_schedule(ctx, 'r', 2)
    assert [(t.task_id, t_c) for t, t_c in events] == [(1, 20.), (2, 26.)]


def test_unmatched_hold_delays_queued_work_without_treating_it_as_committed():
    ctx = context([task(1, target_xy=(3., 0.), service_s=5.)],
                  robots=(MissionRobot('r', (0., 0.), 1., current_task_id=99,
                                       hold_until_t=10.),))
    assert pending_schedule(ctx, 'r', 1) == ((ctx.tasks[0], 18.),)


def test_unfinished_due_task_has_finite_negative_margin():
    ctx = context([task(1, reactive=True, target_xy=(200., 0.))])
    margins = forecast_margins(ctx, pending_schedule(ctx), np.array([0., 100.]))
    assert np.isfinite(margins['react']).all()
    assert margins['react'][0] < 0


def test_task_not_due_within_horizon_is_not_falsely_declared_late():
    ctx = context([task(1, reactive=True, target_xy=(200., 0.))], spec=spec(horizon_s=10.))
    assert forecast_margins(ctx, pending_schedule(ctx), np.array([0., 10.]))['react'][0] == 1.


def test_current_task_wins_exact_ties_and_inputs_stay_unchanged():
    ctx = context([task(1, cell_id=None), task(2, cell_id=None)],
                  robots=(MissionRobot('r', (0., 0.), 1., current_task_id=2),))
    before = deepcopy(ctx)
    chosen, diag = select_mission_task(ctx, 'r')
    assert chosen == 2 and diag['selected_value'] == 0.
    assert ctx == before
    assert next(s for s in diag['scores'] if s['task_id'] == 2)['value'] == 0.


def test_candidate_forecasts_use_identical_sampling_grid():
    ctx = context([task(1, target_xy=(3., 0.)), task(2, target_xy=(17., 0.))])
    grids = []
    original = mission._robustness
    def record(ctx, schedule, times):
        grids.append(times.copy())
        return original(ctx, schedule, times)
    with mock.patch.object(mission, '_robustness', record):
        select_mission_task(ctx, 'r')
    assert len(grids) == 3
    assert all(np.array_equal(grids[0], grid) for grid in grids)
    assert 0. in grids[0] and ctx.spec.horizon_s in grids[0]


def test_task_input_permutation_does_not_change_result():
    ctx = context([task(2, reactive=True), task(1)], now_t=85.)
    assert select_mission_task(ctx, 'r') == select_mission_task(replace(ctx, tasks=tuple(reversed(ctx.tasks))), 'r')


def test_other_robot_pending_work_is_present_in_deadline_clause():
    ctx = context([task(1), task(2, robot_id='other', reactive=True, target_xy=(200., 0.))],
                  robots=(MissionRobot('r', (0., 0.), 1.), MissionRobot('other', (0., 0.), 1.)))
    _chosen, diag = select_mission_task(ctx, 'r')
    assert diag['reference_clauses']['react'] < 0


def test_coverage_requirement_can_change_choice_between_predictive_actions():
    ctx = context([task(1, cell_id=0, service_s=3.), task(2, cell_id=1, service_s=3.)],
                  exposure=(0., 0.), coverage_age=(0., 90.), spec=spec(T_cov_s=100., horizon_s=20.))
    assert select_mission_task(ctx, 'r')[0] == 2


def test_exposure_requirement_can_change_choice_between_predictive_actions():
    ctx = context([task(1, cell_id=1, service_s=1., beta=5.), task(2, cell_id=0, service_s=1., beta=5.)],
                  exposure=(10., 1.), coverage_age=(0., 0.), spec=spec(E_star=5., horizon_s=50.))
    assert select_mission_task(ctx, 'r')[0] == 2


def test_proposal_dispatch_only_scores_predictive_deterrence_candidates():
    ctx = context([task(1, reactive=True, created_t=-5.),
                   task(2, created_t=0.),
                   task(3, deterring=False, created_t=1.)])
    chosen, diag = select_mission_task(ctx, 'r', candidate_stream='predictive')
    assert chosen == 2
    assert diag['candidates'] == 1
    with pytest.raises(ValueError, match='Unsupported mission candidate stream'):
        select_mission_task(ctx, 'r', candidate_stream='patrol')


def test_simulator_adapter_has_no_private_truth_inputs():
    import ast
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'DeterrentSystem.py').read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    adapter = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_select_mission_task_for_robot')
    reads = {n.id for n in ast.walk(adapter) if isinstance(n, ast.Name)}
    assert not reads & {'truth_hab', 'hab', 'truth_events', 'additive_engine',
                        'truth_deterrence_store', 'recent_truth', 'beta_true', 'sigma_true', 'omega_true'}
    assert {'_planner_hab_for_robot', 'cell_exposure_rate', 'active_tasks', 'pose'} <= reads


def test_non_habituating_control_keeps_other_three_clauses():
    ctx = context([task(1)], spec=spec(include_habituation=False))
    assert set(select_mission_task(ctx, 'r')[1]['reference_clauses']) == {'exp', 'cov', 'react'}


@pytest.mark.parametrize('changes', [{'theta': 0}, {'reactive_deadline_s': 0}, {'eta_min': 1}, {'kernel_self': -1}])
def test_invalid_spec_fails_closed(changes):
    with pytest.raises(ValueError):
        spec(**changes)


def test_duplicate_task_ids_rejected():
    with pytest.raises(ValueError, match='Duplicate'):
        select_mission_task(context([task(1), task(1)]), 'r')


def test_profile_changes_only_mission_enable_and_fourth_clause():
    import json
    from pathlib import Path
    parent = json.loads((Path(__file__).resolve().parents[1] / 'audit/parent_B4.json').read_text())
    before = deepcopy(parent)
    profile = build_b4_mission(parent)
    assert parent == before
    assert {k for k in profile if profile[k] != parent.get(k)} == {
        'stl_active_clauses', 'stl_T_react_s', 'stl_proposal_predictive_dispatch',
    }
    assert profile['stl_active_clauses'] == ['exp', 'cov', 'hab', 'react']
    assert profile['stl_T_react_s'] == profile['reactive_service_deadline_s']
    assert profile['stl_proposal_predictive_dispatch'] is True
    assert profile.get('stl_mission_wide', False) is False
    assert profile['dispatch_policy'] == 'res'


@pytest.mark.parametrize('changes', [
    {'dispatch_policy': 'unc'}, {'stl_active_clauses': ['exp', 'cov', 'hab']},
    {'stl_T_react_s': 60.}, {'stl_forecast_correction': True},
    {'planner_procedure': 'plan'}, {'motion_planning_mode': 'graph'},
    {'stl_mission_wide': True},
])
def test_incompatible_mission_combinations_fail_before_simulating(changes):
    import json
    from pathlib import Path
    import DeterrentSystem as ds
    parent = json.loads((Path(__file__).resolve().parents[1] / 'audit/parent_B4.json').read_text())
    profile = build_b4_mission(parent)
    profile.update(changes)
    gen = ds.run_simulation_frames_persistent(**profile)
    try:
        # The parent additive-world gate rejects plan mode even earlier.
        if changes.get('planner_procedure') == 'plan':
            error = 'additive A-E continuation'
        elif changes.get('stl_mission_wide'):
            error = 'mutually exclusive'
        else:
            error = 'B4_mission'
        with pytest.raises(ValueError, match=error):
            next(gen)
    finally:
        gen.close()
