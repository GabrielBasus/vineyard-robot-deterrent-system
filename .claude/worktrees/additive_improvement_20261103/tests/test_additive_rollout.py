import copy,math
from types import SimpleNamespace
import numpy as np
import pytest
from additive_intensity import ADDITIVE_CONTRACT,CellGrid,AdditiveGridTruth
from random_streams import CoupledRandomStreams
from habituation_stl import scenario_rollout as sr
from habituation_stl import additive_rollout as ar

def small_snapshot(form='legacy',**over):
    shape=(6,8)
    fc=sr.IntensityForecast(form=form,bg_node_rate=np.full(shape,.002),sigma=7,omega=100,
        legacy_trigger_mass=np.full(shape,.001),legacy_inhib_channels={},legacy_alpha_in=.15,
        legacy_alpha_inhib=.9,legacy_stamp_units='mass_per_cell',grid_contract=ADDITIVE_CONTRACT,
        alpha=.3,truth_excitation_density=np.zeros(shape),legacy_state_time=0.)
    values=dict(t0=0.,horizon_s=20.,nx=8,ny=6,W=80.,H=60.,forecast=fc,cfg=SimpleNamespace(dt=1.),
        robots=[],region_mask=np.ones(shape,bool),w_node=np.ones(shape),w_bg_node=np.ones(shape),start_stage='replan')
    values.update(over)
    snap=SimpleNamespace(**values)
    snap.xs,snap.ys=ar.axes(snap.W,snap.H,snap.nx,snap.ny)
    return snap

def test_cell_axes_indices_and_inhibition_match_online_model():
    from SESTPP import OnlineSESTPP
    snap=small_snapshot();world=sr._World(snap,[])
    m=OnlineSESTPP(0,80,0,60,8,6,sigma=7,omega=100,alpha_inhib=.9,mu_base=.002,
        legacy_stamp_units='mass_per_cell',grid_contract=ADDITIVE_CONTRACT)
    for x,y in [(0,0),(80,60),(9.999,29.99),(10,30)]:
        assert tuple(map(int,ar.indices(x,y,80,60,8,6)))==m.world_to_idx(x,y)
        before=world.I.get('laser',(np.zeros((6,8)),100))[0].copy()
        world.add_legacy_inhibition(x,y,'laser',.7,7,100)
        m.add_intervention_event(x,y,weight=.7,sigma=7,omega_inhib=100,mode='laser')
        np.testing.assert_allclose(world.I['laser'][0],m.inhib_channels['laser'],rtol=1e-14,atol=1e-16)
    assert world.node_area==m.dx*m.dy==100

def test_planner_sampler_and_quadrature_agree_without_future_branching():
    snap=small_snapshot(); totals=[]
    world=sr._World(snap,[]);world.end_step()
    for k in range(1,21):world.begin_step(k);world.end_step()
    for seed in range(100):
        tree=sr._sample_scenario_tree(snap,seed,0);totals.append(len(tree.t))
        assert np.all((tree.x>=0)&(tree.x<80)&(tree.y>=0)&(tree.y<60))
        iy,ix=ar.indices(tree.x,tree.y,80,60,8,6)
        np.testing.assert_array_equal(tree.node,iy*8+ix)
        assert not np.any(tree.parent>=0)
    assert abs(np.mean(totals)-world.J)<4*math.sqrt(world.J/100)

def test_oracle_rollout_uses_exact_truth_engine_and_keyed_draws():
    snap=small_snapshot('additive_truth');store=[dict(x=40.,y=30.,t=0.,eta=.7,beta=.2,sigma=7.,omega=100.)]
    world=sr._World(snap,store)
    direct=AdditiveGridTruth(CellGrid(80,60,8,6),snap.forecast.bg_node_rate,
        branching_mean=.3,sigma=7,omega=100,dt=1)
    tree=sr._sample_scenario_tree(snap,17,0);streams=CoupledRandomStreams(tree.jitter_seed)
    expected_J=0.
    for k in range(1,21):
        direct.begin_step(k,1,store);world.begin_step(k)
        proposals=direct.proposals(streams,k)
        accepted=[(x,y) for x,y,t,eid,kind in proposals if streams.thinning_uniform(eid)<direct.suppression_at(x,y)[0]]
        ids=sr._world_process_events(world,tree,np.zeros(0,bool),k,k)
        assert world.accepted==accepted
        np.testing.assert_array_equal(world.engine.intensity,direct.intensity)
        expected_J+=direct.intensity.sum()*100
        direct.finish_step(accepted);world.end_step()
        np.testing.assert_array_equal(world.engine.excitation,direct.excitation)
    assert world.J==expected_J

@pytest.fixture(scope='module')
def live():
    import DeterrentSystem as ds
    from experiments import additive_protocol as p
    params=p.resolved_hierarchy()['B5']
    params.update(W=80.,H=60.,NX=16,NY=12,Nrobots=2,warmup_s=0.,T_end=3.,seed=91007)
    gen=ds.run_simulation_frames_persistent(**params)
    next(gen)
    yield gen.gi_frame.f_locals
    gen.close()

@pytest.mark.parametrize('oracle',[False,True])
def test_live_snapshot_noop_deterministic_and_does_not_mutate_live_state(live,oracle):
    snap=sr.snapshot_from_sim_locals(live,horizon_s=5.,full_observability=oracle,n_sub_weight=2)
    assert snap.forecast.grid_contract==ADDITIVE_CONTRACT
    assert snap.forecast.form==('additive_truth' if oracle else 'legacy')
    engine=live['additive_engine'].excitation.copy()
    eta=live['planner_hab'].eta.copy()
    a=sr.run_policy(snap,sr.NOOP,n_scenarios=2,seed=22)
    b=sr.run_policy(snap,sr.NOOP,n_scenarios=2,seed=22)
    assert [r['J'] for r in a]==[r['J'] for r in b]
    np.testing.assert_array_equal(engine,live['additive_engine'].excitation)
    np.testing.assert_array_equal(eta,live['planner_hab'].eta)

@pytest.mark.parametrize('oracle',[False,True])
def test_candidate_parallel_serial_and_noop_pairing(live,oracle,monkeypatch):
    # These 16x12, 30-second verification worlds are much smaller than the
    # production pool's per-worker allowance; retain its full memory reserve.
    monkeypatch.setattr(sr.RolloutPool,'WORKER_MEM_GB',.2)
    snap=sr.snapshot_from_sim_locals(live,horizon_s=30.,full_observability=oracle,n_sub_weight=2)
    robot=snap.robots[0]
    candidate=sr.Candidate(robot.rid,*robot.pose,'laser')
    a=sr.evaluate(snap,[sr.NOOP,candidate],n_scenarios=2,seed=19,n_workers=1)
    b=sr.evaluate(snap,[sr.NOOP,candidate],n_scenarios=2,seed=19,n_workers=2)
    np.testing.assert_array_equal(a.J,b.J)
    np.testing.assert_array_equal(a.U[0],0)
    assert np.isfinite(a.J).all()

@pytest.mark.parametrize('variant',['D_plan','E_plan'])
def test_plan_runtime_accepts_verified_additive_world_and_executes(variant):
    import DeterrentSystem as ds
    from experiments import additive_protocol as p
    from experiments import run_plan_completion as rpc
    params=p.resolved_hierarchy()['B5']
    params.update(copy.deepcopy(rpc.PLAN_VARIANTS[variant][1]))
    params.update(W=80.,H=60.,NX=16,NY=12,Nrobots=2,warmup_s=0.,T_end=2.,seed=91008,
        plan_n_scenarios=2,plan_oracle_scenarios=2,plan_horizon_s=4.,plan_pool_workers=1,reactive_override_slack_s=3.,
        plan_oracle_fraction=1.,stl_forecast_correction=True)
    gen=ds.run_simulation_frames_persistent(**params)
    try:
        frames=list(gen)
        assert frames[-1]['metrics_compact']['additive_truth_mode']==1
    finally:gen.close()
