"""Verification fixtures only. Seeds below are not study validation seeds."""
import os
os.environ.setdefault("DETERRENT_TELEMETRY", "0")

import numpy as np
import pytest
from additive_intensity import ADDITIVE_CONTRACT, AdditiveGridTruth, CellGrid
from random_streams import CoupledRandomStreams
from SESTPP import OnlineSESTPP


@pytest.fixture(scope="session", autouse=True)
def record_verified_source_identity(record_testsuite_property):
    from experiments import run_hierarchical_calibration as h
    sources = h.sources()
    record_testsuite_property("additive_source_sha256", h.digest(sources))
    yield
    assert h.sources() == sources, "runtime source changed during verification"


def engine(**overrides):
    grid = CellGrid(80., 60., 16, 12)
    params = dict(branching_mean=.3, sigma=7., omega=100., dt=1.)
    params.update(overrides)
    return AdditiveGridTruth(grid, np.ones((grid.ny, grid.nx)), **params)


def event(**overrides):
    row = dict(x=40., y=30., t=0., eta=.7, beta=.2, sigma=7., omega=100., mode="laser")
    row.update(overrides)
    return row


def test_truth_and_estimator_same_supplied_inhibition_and_excitation():
    truth = engine()
    model = OnlineSESTPP(0, 80, 0, 60, 16, 12, sigma=7., omega=100., omega_inhib=100.,
                        alpha_in=truth.gain, alpha_cross=0., alpha_inhib=1., mu_base=.001, bg_ema=0.,
                        legacy_stamp_units="mass_per_cell", grid_contract=ADDITIVE_CONTRACT)
    truth.begin_step(0., .001, [])
    truth.finish_step([(39., 29.), (1., 1.)])
    for x, y in [(39., 29.), (1., 1.)]:
        model.add_local_event(x, y)
    # Truth at step 1 retains the initial next-step gain, while the supplied
    # estimator is deliberately not advanced: this isolates equal state fields.
    row = event(t=1.)
    truth.begin_step(1., .001, [row])
    model.add_intervention_event(row["x"], row["y"], weight=row["eta"]*row["beta"], mode="laser")
    np.testing.assert_allclose(model.trigger_mass, truth.excitation, atol=1e-16)
    np.testing.assert_allclose(model.inhib_mass, truth.inhibition, atol=1e-16)
    np.testing.assert_allclose(model.lam, truth.intensity, atol=1e-16)


def test_pending_intervention_timing_zero_strength_and_additive_overlap():
    truth = engine(branching_mean=0.)
    truth.begin_step(0., .001, [event(t=2.), event(beta=0.)])
    assert not np.any(truth.inhibition)
    truth.finish_step([])
    truth.begin_step(1., .001, [event(beta=.4), event(beta=.4)])
    single = .7*.4*np.exp(-1/100.)*truth.kernel(40., 30., 7.)
    np.testing.assert_allclose(truth.inhibition, 2*single)
    assert np.all(truth.intensity >= 0)
    assert np.any(truth.intensity == 0)
    p, suppressed, modes, sources = truth.suppression_at(40., 30.)
    assert p == 0.
    assert sum(modes.values()) == pytest.approx(suppressed)
    assert sum(sources.values()) == pytest.approx(suppressed)


def test_pre_depletion_effectiveness_is_immutable_and_time_decay_correct():
    truth = engine()
    row = event(eta=.8)
    truth.begin_step(0., .001, [row])
    initial = truth.inhibition.copy()
    truth.finish_step([])
    truth.begin_step(1., .001, [row])
    np.testing.assert_allclose(truth.inhibition, initial*np.exp(-1/100.))
    assert row["eta"] == .8


def test_accepted_events_alone_excite_and_new_excitation_is_next_step():
    truth = engine()
    truth.begin_step(0., .001, [])
    assert not np.any(truth.excitation)
    frozen = truth.candidate.copy()
    truth.finish_step([(40., 30.)])
    np.testing.assert_array_equal(truth.candidate, frozen)
    np.testing.assert_allclose(truth.excitation, truth.gain*truth.kernel(40., 30., 7.))
    truth.begin_step(1., .001, [])
    old = truth.excitation.copy()
    truth.finish_step([])
    np.testing.assert_allclose(truth.excitation, old*truth.decay)


def test_background_and_uniforms_coupled_across_different_endogenous_histories():
    a, b = engine(), engine()
    sa, sb = CoupledRandomStreams(91001), CoupledRandomStreams(91001)
    for t in range(6):
        ba = []
        for truth, streams in [(a, sa), (b, sb)]:
            truth.begin_step(float(t), .002, [])
            proposals = truth.proposals(streams, streams.next_step_index())
            ba.append([(x, y, time, key, streams.thinning_uniform(key))
                       for x, y, time, key, origin in proposals if origin == "background"])
            truth.finish_step([(40., 30.)] * (10 if truth is a else 0))
        assert ba[0] == ba[1]


def test_zero_excitation_zero_suppression_sample_count_matches_poisson():
    truth = engine(branching_mean=0.)
    streams = CoupledRandomStreams(91002)
    total = 0
    for t in range(300):
        truth.begin_step(float(t), .002, [])
        proposals = truth.proposals(streams, streams.next_step_index())
        assert all(truth.suppression_at(x, y)[0] == 1. for x, y, *_ in proposals)
        total += len(proposals)
        truth.finish_step([])
    mean = .002*80*60*300
    assert abs(total-mean) < 6*np.sqrt(mean)


def test_step_lifecycle_rejects_repeated_or_skipped_times():
    truth = engine()
    with pytest.raises(RuntimeError):
        truth.finish_step([])
    truth.begin_step(0., .001, [])
    with pytest.raises(RuntimeError):
        truth.begin_step(0., .001, [])
    truth.finish_step([])
    with pytest.raises(ValueError):
        truth.begin_step(2., .001, [])


def sim_params(**overrides):
    p = dict(W=80., H=60., NX=16, NY=12, Nrobots=2, seed=91003, dt=1., T_end=4.,
             use_ground_truth=True, simulation_mode="reactive", planner_profile="",
             use_frozen_calibration=False, warmup_s=0., mu_true=.0001,
             truth_process_mode=ADDITIVE_CONTRACT, random_stream_mode="coupled",
             truth_deterrence_memory="complete", legacy_stamp_units="mass_per_cell")
    p.update(overrides)
    return p


def test_runtime_new_mode_and_warmup_use_the_same_engine():
    import DeterrentSystem as ds
    gen = ds.run_simulation_frames_persistent(**sim_params(warmup_s=2.))
    next(gen)
    loc = gen.gi_frame.f_locals
    assert loc["additive_engine"]._last_t == 2.
    assert {r.m.grid_contract for r in loc["robots"].values()} == {ADDITIVE_CONTRACT}
    assert not loc["truth_queue"]
    assert {r.m.t_now for r in loc["robots"].values()} == {3.}
    for _ in gen:
        pass


@pytest.mark.parametrize("overrides", [dict(random_stream_mode="legacy"),
    dict(truth_deterrence_memory="window200"), dict(estimator_mode="consistent"),
    dict(legacy_stamp_units="density"), dict(truth_background_timing="continuous"),
    dict(planner_procedure="plan")])
def test_runtime_rejects_unverified_combinations(overrides):
    import DeterrentSystem as ds
    with pytest.raises(ValueError, match="additive"):
        next(ds.run_simulation_frames_persistent(**sim_params(**overrides)))


def test_continuation_entry_points_reject_additive_states_instead_of_using_thinning():
    from habituation_stl import scenario_rollout as sr
    loc = {"truth_process_mode": ADDITIVE_CONTRACT}
    for function in (sr.snapshot_from_sim_locals, sr.planner_forecast_from_sim_locals,
                     sr.truth_forecast_from_sim_locals):
        kwargs = dict(horizon_s=30.)
        if function is not sr.snapshot_from_sim_locals:
            kwargs["t0"] = 0.
        with pytest.raises(ValueError, match="additive continuation"):
            function(loc, **kwargs)


def test_counterfactual_uses_the_same_cell_kernel_and_area():
    from planner_task_estimation import estimate_counterfactual_reduction
    truth = engine()
    model = OnlineSESTPP(0, 80, 0, 60, 16, 12, sigma=7., omega=100.,
                        alpha_inhib=1., mu_base=.001, bg_ema=0.,
                        legacy_stamp_units="mass_per_cell", grid_contract=ADDITIVE_CONTRACT)
    model.trigger_mass[:] = 100.
    model._update_lambda()
    horizon = 10.
    beta = .2
    actual = estimate_counterfactual_reduction(model, 1., 1., beta_u=beta,
        sigma_u=7., omega_u=100., horizon_s=horizon, weight_fn=lambda x,y: 1.)
    expected = beta * 100. * (-np.expm1(-horizon/100.)) * truth.kernel(1., 1., 7.).sum()*truth.grid.area
    assert actual["predicted_reduction_raw"] == pytest.approx(expected)


def test_additive_record_and_replay_preserve_the_live_field(tmp_path):
    import pickle
    from experiments import refit_sim_truth as rst
    path = tmp_path / "additive_fixture.pkl"
    p = sim_params(seed=201, T_end=12., mu_true=.001, bird_detection_prob=1., detect_sigma_m=100.)
    p.update(rst._sim_overrides(rst.PAPER_PROP))
    rst.record_run(dict(load="fixture", mu=.001, seed=201, out=str(path),
                        params=p, check_lam=True, recording_constants=rst.PAPER_PROP, system="B1_fixture"))
    rec = pickle.loads(path.read_bytes())
    assert rec["truth_process_mode"] == rec["grid_contract"] == ADDITIVE_CONTRACT
    assert any(e[0] == "loc" for e in rec["log"])
    replay = rst.replay(rec, rst.PAPER_PROP, True, keep_lam=True)
    assert len(replay["lam"]) == len(rec["live_lam"])
    for a, b in zip(replay["lam"], rec["live_lam"]):
        np.testing.assert_array_equal(a, b)
    rec.pop("grid_contract")
    with pytest.raises(ValueError, match="grid contract"):
        rst.replay(rec, rst.PAPER_PROP, True)


@pytest.mark.parametrize("system", ["B1", "B2", "B3", "B4", "B5"])
def test_paper_baseline_hierarchy_uses_additive_runtime_without_hidden_overrides(system):
    import DeterrentSystem as ds
    from experiments import additive_protocol as protocol
    from experiments import run_hierarchical_calibration as h
    params = protocol.resolved_hierarchy()[system]
    # Short integration fixture, not a policy evaluation or calibration recording.
    params.update(T_end=2., seed=201)
    gen = ds.run_simulation_frames_persistent(**params)
    try:
        frame = next(gen)
        local = gen.gi_frame.f_locals
        h.audit_runtime(local, params)
        assert frame["truth_process_mode"] == ADDITIVE_CONTRACT
        assert frame["metrics_compact"]["additive_truth_mode"] == 1
        assert all(r.m.grid_contract == ADDITIVE_CONTRACT for r in local["robots"].values())
        assert not local["stl_forecast_correction"]
        assert not local["stl_forward_trajectory_correction"]
        assert params["deterring_modes"] == protocol.reference()["deterring_modes"]
        assert params["mu_true"] == protocol.reference()["mu_true"]
    finally:
        gen.close()


def test_historical_truth_is_default_and_explicit_flag_preserves_that_path():
    import inspect
    import DeterrentSystem as ds
    assert inspect.signature(ds.run_simulation_frames_persistent).parameters[
        "truth_process_mode"].default == "historical_thinning"
    results = []
    for explicit in (False, True):
        params = sim_params(truth_process_mode="historical_thinning")
        if not explicit:
            params.pop("truth_process_mode")
        gen = ds.run_simulation_frames_persistent(**params)
        try:
            frame = next(gen)
            local = gen.gi_frame.f_locals
            assert local["additive_engine"] is None
            assert frame["truth_process_mode"] == "historical_thinning"
            assert frame["planner_grid_contract"] == "legacy_nodes"
            results.append({key: frame["metrics_compact"][key] for key in
                ("value_weighted_exposure", "truth_candidate_events", "truth_accepted_events")})
        finally:
            gen.close()
    assert results[0] == results[1]


def test_truth_mode_changes_job_identity_and_cannot_reuse_historical_checkpoint(tmp_path):
    from experiments import additive_protocol as protocol
    from experiments import run_hierarchical_calibration as h
    import pickle
    runner = h.Runner(tmp_path, 1)
    old = runner.jobs("recordings", "B1", h.paper_reference(), [200], record=True)[0]
    new = runner.jobs("recordings", "B1", protocol.reference(), [200], record=True)[0]
    assert old["identity"] != new["identity"]
    path = tmp_path/"recordings"/"spare_200.pkl"
    path.parent.mkdir()
    path.write_bytes(pickle.dumps({"recording_identity": old["identity"]}))
    with pytest.raises(ValueError, match="Stale recording"):
        h.cached(new)


def test_additive_recording_validator_rejects_wrong_environment_before_replaying(tmp_path):
    import pickle
    from experiments import run_bounded_calibration as bounded
    path = tmp_path/"spare_200.pkl"
    path.write_bytes(pickle.dumps(dict(truth_process_mode="historical_thinning")))
    with pytest.raises(ValueError, match="another truth process"):
        bounded.validate_recordings([path], expected_truth_process_mode=ADDITIVE_CONTRACT)
    path.write_bytes(pickle.dumps(dict(truth_process_mode=ADDITIVE_CONTRACT)))
    with pytest.raises(ValueError, match="grid contract"):
        bounded.validate_recordings([path], expected_truth_process_mode=ADDITIVE_CONTRACT)
