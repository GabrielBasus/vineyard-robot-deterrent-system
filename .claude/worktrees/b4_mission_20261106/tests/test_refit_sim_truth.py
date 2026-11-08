"""Phase 1 (provisional) record-and-replay refit against the evaluation simulator
(user decisions 2026-10-28): the replay with the recording constants reproduces the live
estimators bit for bit."""
import math
import json
import os
import pickle
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

from experiments import refit_sim_truth as rst  # noqa: E402


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    out = tmp_path_factory.mktemp("rec") / "heavy_200.pkl"
    rst.record_run({"load": "heavy", "mu": 4e-4, "seed": 200, "out": str(out), "t_end": 240.0,
                    "check_lam": True})
    with open(out, "rb") as fh:
        return pickle.load(fh), str(out)


def test_recording_contents(recording):
    rec, _ = recording
    ops = {e[0] for e in rec["log"]}
    assert {"adv", "loc", "step", "owner", "det"} <= ops
    assert rec["units"] == "mass_per_cell" and rec["rec_constants"] == rst.REC_PROP
    assert rec["rec_constants"]["alpha_in"] == pytest.approx(0.15 * rst.rh.NODE_AREA)
    assert sum(1 for e in rec["log"] if e[0] == "det") == sum(1 for e in rec["log"] if e[0] == "loc")
    assert len(rec["live_lam"]) == sum(1 for e in rec["log"] if e[0] == "step")
    assert "git_commit" in rec["code_version"]
    # all accepted truth events are recorded; detected events are a subset of them
    truth = {(round(x, 9), round(y, 9), round(t, 9)) for x, y, t in rec["truth_events"]}
    dets = [(round(e[1], 9), round(e[2], 9), round(e[3], 9)) for e in rec["log"] if e[0] == "det"]
    assert len(truth) > len(dets) > 0 and all(d in truth for d in dets)


def test_paper_recording_preserves_numeric_constants_and_replays_live_field(tmp_path):
    path = tmp_path / 'paper.pkl'
    rst.record_run(dict(load='spare', mu=2e-5, seed=200, out=str(path), t_end=2.0,
                        check_lam=True, recording_constants=rst.PAPER_PROP))
    rec = pickle.loads(path.read_bytes())
    assert rec['rec_constants']['alpha_in'] == 0.15
    assert rec['rec_constants']['alpha_inhib'] == 0.9
    assert rec['units'] == 'mass_per_cell'
    result = rst.replay(rec, rec['rec_constants'], True, keep_lam=True)
    assert len(result['lam']) == len(rec['live_lam'])
    assert all(np.array_equal(a, b) for a, b in zip(result['lam'], rec['live_lam']))


def test_truth_and_detected_targets(recording):
    rec, _ = recording
    a = rst.replay(rec, dict(rst.REC_PROP), True)                       # default: all truth events
    b = rst.replay(rec, dict(rst.REC_PROP), True, target="detected")
    assert a["target"] == "truth" and a["scored_events"] == len(rec["truth_events"])
    assert b["scored_events"] == b["detected_events"] < a["scored_events"]
    assert a["field_logloss"] != b["field_logloss"] and math.isfinite(a["nll"])
    with pytest.raises(ValueError):
        rst.replay(rec, dict(rst.REC_PROP), True, target="all")


def test_replay_with_recording_constants_is_bit_for_bit(recording):
    rec, _ = recording
    out = rst.replay(rec, dict(rst.REC_PROP), with_interventions=True, keep_lam=True)
    assert len(out["lam"]) == len(rec["live_lam"])
    for a, b in zip(out["lam"], rec["live_lam"]):
        assert np.array_equal(a, b)
    assert any(e[0] == "int" for e in rec["log"]) and any(e[0] == "cross" for e in rec["log"])


def test_replay_metrics_and_candidate_change(recording):
    rec, path = recording
    base = rst._run(("joint", dict(rst.REC_PRED), dict(rst.REC_PROP), path))
    assert all(math.isfinite(base[k]) for k in ("prediction_only_field_logloss", "proposed_field_logloss",
                                                "proposed_nll", "delta_nll_proposed_minus_prediction"))
    assert base["truth_events"] > 0
    other = dict(rst.REC_PROP, alpha_in=rst.REC_PROP["alpha_in"] / 100.0)
    res = rst._run(("proposed", dict(rst.REC_PRED), other, path))
    assert res["proposed_field_logloss"] != base["proposed_field_logloss"]
    assert math.isnan(res["prediction_only_field_logloss"])


def test_relay_and_feedback_transforms():
    assert rst._swap(10.0, 10.0, 25.0) == 25.0 and rst._swap(40.0, 10.0, 25.0) == 40.0 and rst._swap(None, 1, 2) is None
    # cue sigma 72 x 0.875 -> candidate scale 0.5; model default 10 x 0.875 -> candidate default 20 x 0.5
    assert rst._feedback(63.0, 0.875, 10.0, 0.5, 20.0) == pytest.approx(36.0)
    assert rst._feedback(8.75, 0.875, 10.0, 0.5, 20.0) == pytest.approx(10.0)
    assert rst._feedback(8.75, 0.875, 10.0, 0.875, 10.0) == 8.75     # unchanged constants: exact value


def test_stop_rule_exception_type():
    assert issubclass(rst.AlphaInToZero, RuntimeError)


def test_truth_nll_integrates_the_same_predictable_field_used_for_events():
    """An event's own stamp must not enter the integral of its already scored step."""
    p = dict(rst.REC_PROP, sigma=0.1, alpha_in=1.0, mu_base=0.2, bg_ema=0.0)
    rec = dict(robots=['r0'], x_min=0.0, x_max=2.0, y_min=0.0, y_max=2.0,
               W=2.0, H=2.0, NX=3, NY=3, dt=1.0, rec_constants=p, units='mass_per_cell',
               owners=[np.zeros((3, 3), dtype=int)], truth_events=[(1.0, 1.0, 0.5)],
               log=[('adv', 0, 1.0), ('det', 1.0, 1.0, 0.5), ('loc', 0, 1.0, 1.0),
                    ('step', 1.0), ('adv', 0, 1.0), ('step', 2.0)])
    model = rst._build_models(rec, p)[0]
    first = model.lam.copy()
    model.advance_time(1.0)
    model.add_local_event(1.0, 1.0)
    second = model.lam.copy()
    expected = float(first.sum() + second.sum()) * model.dx * model.dy - math.log(first[1, 1])
    result = rst.replay(rec, p, True, target='truth')
    assert result['nll'] == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize('units', ['density', None])
def test_replay_rejects_old_or_untagged_unit_recordings(units):
    with pytest.raises(ValueError, match='mass_per_cell'):
        rst.replay({'units': units}, dict(rst.REC_PROP), True)


def test_replay_cache_rejects_different_recordings_or_target(tmp_path):
    recording_path = tmp_path / 'input.pkl'
    recording_path.write_bytes(b'recording version one')
    output = tmp_path / 'cache'
    output.mkdir()
    ev = rst.SimEvaluator(output, 1, lambda _: None, [str(recording_path)], target='truth')
    version = dict(ev.version)
    ev.close()
    (output / 'evals.jsonl').write_text(json.dumps(dict(key='cached', **version)) + '\n')
    valid = rst.SimEvaluator(output, 1, lambda _: None, [str(recording_path)], target='truth')
    valid.close()
    with pytest.raises(ValueError, match='cache'):
        rst.SimEvaluator(output, 1, lambda _: None, [str(recording_path)], target='detected')
    recording_path.write_bytes(b'recording version two')
    with pytest.raises(ValueError, match='cache'):
        rst.SimEvaluator(output, 1, lambda _: None, [str(recording_path)], target='truth')


def test_replay_cache_rejects_results_without_current_scorer_version(tmp_path):
    recording_path = tmp_path / 'input.pkl'
    recording_path.write_bytes(b'old recording')
    output = tmp_path / 'cache'
    output.mkdir()
    (output / 'evals.jsonl').write_text(json.dumps(dict(key='old-unversioned')) + '\n')
    with pytest.raises(ValueError, match='cache'):
        rst.SimEvaluator(output, 1, lambda _: None, [str(recording_path)])


@pytest.mark.parametrize('recording_start', ['paper', 'equivalent'])
def test_refit_start_and_result_metadata_follow_the_selected_recording_start(tmp_path, monkeypatch, recording_start):
    """Exercise command routing without launching a parameter search or worker pool."""
    monkeypatch.setattr(rst, 'OUT', tmp_path)
    folder = 'recordings_paper' if recording_start == 'paper' else 'recordings'
    (tmp_path / folder).mkdir()
    for load in rst.LOADS:
        (tmp_path / folder / f'{load}_200.pkl').write_bytes(b'input')

    class Evaluator:
        def __init__(self, out, workers, log, paths, target):
            assert all(folder in path for path in paths)
            self.version, self.n_runs = {'scoring_version': rst.SCORER_VERSION}, 0

        def evaluate(self, stage, configs):
            metrics = {k: 0.0 if k.startswith('delta_') else 1.0 for k in rst.rh.METRIC_KEYS}
            return [dict(key=rst.rh.config_key(stage, pred, prop), pred=pred, prop=prop, pooled=metrics)
                    for pred, prop in configs]

        def close(self):
            pass

    class Search:
        def __init__(self, stage, names, start, other, ev, log):
            self.stage, self.x, self.other, self.ev = stage, dict(start), other, ev
            self.flat, self.local_checks = {}, []

        def _pair(self, x):
            return (dict(x), {}) if self.stage == 'prediction' else (self.other, dict(x))

        def run(self, max_configs):
            return dict(x=dict(self.x), objective=[1.0, 1.0, 1.0], moved=[], line_status={})

        def top(self, n):
            return self.ev.evaluate(self.stage, [self._pair(self.x)] * n)

    monkeypatch.setattr(rst, 'SimEvaluator', Evaluator)
    monkeypatch.setattr(rst, 'SimSearch', Search)
    rst.cmd_refit(SimpleNamespace(seeds=[200], recording_start=recording_start,
                                 target='truth', workers=1, min_free_gb=4.0, max_local_configs=800))
    suffix = '_paper_recordings' if recording_start == 'paper' else ''
    result = json.loads((tmp_path / ('refit_truth_v2' + suffix) / 'refit_result.json').read_text())
    expected = rst.PAPER_PROP if recording_start == 'paper' else rst.REC_PROP
    assert result['recording_constants'] == expected
    assert result['recording_start'] == recording_start
    assert result['prediction_stage']['x']['alpha_in'] == expected['alpha_in']
    assert result['proposed_stage']['x']['alpha_inhib'] == expected['alpha_inhib']
    assert result['reference_start'] == ('paper_start' if recording_start == 'paper' else 'equivalent_start')


def test_vectorised_node_index_matches_model(recording):
    rec, _ = recording
    from SESTPP import OnlineSESTPP
    m = OnlineSESTPP(rec["x_min"], rec["x_max"], rec["y_min"], rec["y_max"], rec["NX"], rec["NY"])
    rng = np.random.default_rng(1)
    xs = np.concatenate([rng.uniform(-5, 505, 2000), np.linspace(0, 500, 59 * 2 + 1)])
    ys = np.concatenate([rng.uniform(-5, 505, 2000), np.linspace(0, 500, 59 * 2 + 1)])
    flat = rst._node_index(xs, ys, m)
    ref = [m.world_to_idx(x, y) for x, y in zip(xs, ys)]
    assert np.array_equal(flat, np.array([iy * m.nx + ix for iy, ix in ref]))


class _FakeEv:
    """Objective = squared log distance of the proposed constants to a target."""
    def __init__(self, target):
        self.target, self.cache = target, {}

    def evaluate(self, stage, configs):
        out = []
        for pred, prop in configs:
            key = rst.rh.config_key(stage, pred, prop)
            if key not in self.cache:
                d = sum((math.log(max(prop[k], 1e-300)) - math.log(v)) ** 2 for k, v in self.target.items())
                self.cache[key] = {"key": key, "stage": stage, "pred": pred, "prop": prop,
                                   "pooled": {"proposed_field_logloss": d, "proposed_field_brier": d,
                                              "proposed_nll": d}}
            out.append(self.cache[key])
        return out


def test_pairwise_local_check_when_full_check_exceeds_cap():
    start = dict(rst.REC_PROP)
    target = {"alpha_in": start["alpha_in"] * 2, "sigma": start["sigma"] * 2}
    s = rst.SimSearch("proposed", rst.rh.PROP_PARAMS, start, dict(rst.REC_PRED), _FakeEv(target), lambda m: None)
    s.moved = set(rst.rh.PROP_PARAMS) - {"alpha_cross"}          # 9 moved: full 3^9 = 19683 > cap
    assert s.local_check(800) is True                             # the pair (alpha_in, sigma) finds it
    assert s.x["alpha_in"] == target["alpha_in"] and s.x["sigma"] == target["sigma"]
    assert "pairwise" in s.local_checks[-1]["kind"] and s.local_checks[-1]["n"] <= 36 * 8 + 1
    s.x["bg_ema"] = 1.0
    assert max(s._axis("bg_ema")) == 1.0                          # upper bound respected
