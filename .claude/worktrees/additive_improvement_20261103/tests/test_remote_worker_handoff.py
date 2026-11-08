"""The remote-cohort handoff must never interrupt an incomplete original evaluation."""
import importlib.util
import json
from pathlib import Path

from experiments import run_hierarchical_calibration as h


def module():
    path = h.ROOT/'results/remote_worker_setup/handoff_local.py'
    spec = importlib.util.spec_from_file_location('remote_handoff',path)
    out = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(out)
    return out


def rows():
    systems = list(h.SYSTEMS)+[s+'_unchanged' for s in h.SYSTEMS]
    return [dict(system=s,load=l,hab_on=hab,seed=seed)
            for s in systems for l in h.rpc.LOADS for hab in (True,False) for seed in h.EVAL]


def test_complete_requires_all_600_distinct_cells():
    m = module()
    data = rows()
    assert len(data) == 600 and m.complete(data)
    assert not m.complete(data[:-1])
    assert not m.complete(data[:-1]+[data[0]])
    assert not m.complete(data+[data[0]])


def test_final_reports_and_all_fresh_validation_arms_are_required(tmp_path):
    m = module()
    assert not m.ready(tmp_path)
    (tmp_path/'evaluation_rows.json').write_text(json.dumps(rows()))
    (tmp_path/'evaluation_summary.json').write_text('{}')
    (tmp_path/'paired_comparisons.json').write_text('[]')
    (tmp_path/'fresh_validation.json').write_text(json.dumps({s:{} for s in h.SYSTEMS if s!='B4'}))
    assert not m.ready(tmp_path)
    (tmp_path/'fresh_validation.json').write_text(json.dumps({s:{} for s in h.SYSTEMS}))
    assert m.ready(tmp_path)


def test_handoff_control_does_not_change_original_runtime_source():
    original = h.read(h.ROOT/'results/hierarchical_acc_calibration/manifest.json')['source']
    assert h.sources() == original
    module()
    assert h.sources() == original
