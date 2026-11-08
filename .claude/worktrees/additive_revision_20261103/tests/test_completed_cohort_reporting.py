"""Do not drop seeds or block primary comparisons on undefined conditional diagnostics."""
import importlib.util
from types import SimpleNamespace

import pytest
from experiments import run_hierarchical_calibration as h


def reporter():
    spec=importlib.util.spec_from_file_location('cohort_reporting',
        h.ROOT/'results/remote_worker_setup/postprocess_cohorts.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def examples():
    rows=[]
    for system in ('B5','E_plan'):
        for seed in h.EVAL:
            metrics=dict(value_weighted_exposure=100+seed,reactive_miss_fraction=.2,
                         eta_at_application_predictive_count=1.,
                         eta_truth_at_application_predictive_mean=.7)
            if system=='B5' and seed==302:
                metrics.pop('eta_truth_at_application_predictive_mean')
                metrics['eta_at_application_predictive_count']=0.
            rows.append(dict(system=system,load='spare',hab_on=False,seed=seed,metrics=metrics))
    return rows


def test_zero_application_mean_is_flagged_without_dropping_primary_seed_pairs():
    m=reporter()
    rows,availability,pending=m.report(examples(),'test',{'machine_id':'test'},{},('spare',))
    assert len(rows)==2
    assert all(r['n']==10 and r['n_dropped']==0 for r in rows)
    missing=[r for r in availability if r['metric']=='eta_truth_at_application_predictive_mean']
    assert len(missing)==1
    assert missing[0]['missing']==[dict(variant='B5',seed=302,reason='undefined: zero applications in this stream')]
    assert missing[0]['seeds_dropped']==0 and missing[0]['imputed_values']==0


def test_missing_primary_metric_still_fails_strictly():
    m=reporter()
    rows=examples()
    rows[0]['metrics'].pop('reactive_miss_fraction')
    with pytest.raises(ValueError,match='Primary metric incomplete'):
        m.report(rows,'test',{'machine_id':'test'},{},('spare',))


def test_checkpoint_from_different_source_or_machine_is_rejected(tmp_path):
    m=reporter()
    owner=SimpleNamespace(out=tmp_path,identity='expected-source-and-machine')
    job=h.Runner.jobs(owner,'evaluation/calibrated','B5',{},h.EVAL,habs=(True,False))[0]
    h.save(job['out'],dict(identity='wrong-source-and-machine'))
    with pytest.raises(ValueError,match='Wrong source/machine'):
        m.collect(tmp_path,owner.identity,{'B5':{}},{})
