"""Reproduce the real scorer/logger failure and check the run-local operational repair."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from experiments import run_hierarchical_calibration as h


def repaired_callback():
    path = h.ROOT/'results/hierarchical_acc_calibration/resume_reporting_fix.py'
    spec = importlib.util.spec_from_file_location('hierarchical_reporting_patch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.repaired_status


def test_original_status_collision_is_reproduced_and_repaired(tmp_path):
    runner = SimpleNamespace(out=tmp_path, workers=19)
    import pytest
    with pytest.raises(TypeError, match='workers'):
        h.Runner.status(runner, 'evaluating_candidate', workers=8, candidate=1)
    repaired_callback()(runner, 'evaluating_candidate', workers=8, candidate=1)
    state = json.loads((tmp_path/'status.json').read_text())
    assert state['workers'] == 8
    assert state['candidate'] == 1
    assert state['stage'] == 'evaluating_candidate'
    assert state['deployed'] is False


def test_repaired_status_accepts_all_current_evaluator_progress_calls(tmp_path):
    runner = SimpleNamespace(out=tmp_path, workers=19)
    callback = repaired_callback()
    for stage, details in [('waiting_for_memory', {'available_gb': 4.1}),
                           ('evaluating_candidate', {'workers': 19, 'candidate_stage': 'proposed',
                                                    'candidate': 1, 'candidate_limit': 2}),
                           ('replaying', {'workers': 19, 'completed': 30, 'total': 30}),
                           ('finished', {'phase': 'all'})]:
        callback(runner, stage, **details)
        saved = json.loads((tmp_path/'status.json').read_text())
        assert saved['stage'] == stage
        assert all(saved[k] == v for k,v in details.items())


def test_run_local_patch_does_not_change_frozen_source_identity():
    before = h.sources()
    repaired_callback()
    assert h.sources() == before
    manifest = h.read(h.ROOT/'results/hierarchical_acc_calibration/manifest.json')
    assert before == manifest['source']
