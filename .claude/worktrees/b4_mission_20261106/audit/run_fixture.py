"""Short verification fixtures, never study/evaluation results."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
os.environ['DETERRENT_TELEMETRY'] = '0'
import sys
sys.dont_write_bytecode = True
import argparse
import json
import math
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument('--root', required=True)
parser.add_argument('--system', choices=['B1', 'B4', 'B5', 'B4_mission'], required=True)
parser.add_argument('--hab', type=int, choices=[0, 1], default=1)
parser.add_argument('--duration', type=float, default=180.)
parser.add_argument('--out', required=True)
args = parser.parse_args()
root = Path(args.root).resolve()
snapshot = Path(__file__).resolve().parents[1]
parent = snapshot.parent / 'additive_revision_20261103'
frozen = json.loads((parent / 'results/additive_newloads_b1recal_v1/new_frozen/frozen_configs.json').read_text())
params = dict(frozen['B4' if args.system == 'B4_mission' else args.system])
params.update(seed=99011, T_end=args.duration, enable_habituation=bool(args.hab),
              habituation_kappa=.5 if args.hab else 0.)
if args.system == 'B4_mission':
    params.update(stl_proposal_predictive_dispatch=True,
                  stl_active_clauses=['exp', 'cov', 'hab', 'react'],
                  stl_T_react_s=90.)
sys.path.insert(0, str(root))
import DeterrentSystem as ds
started = time.monotonic()
last = None
first_context = None
if args.system == 'B4_mission':
    original = ds.select_mission_task
    def observe(context, robot_id, candidate_stream=None):
        global first_context
        if first_context is None:
            first_context = dict(context_type=type(context).__name__, robot_id=robot_id,
                                 zones=len(context.exposure), pending=len(context.tasks),
                                 deadline=context.spec.reactive_deadline_s)
        return original(context, robot_id, candidate_stream=candidate_stream)
    ds.select_mission_task = observe
gen = ds.run_simulation_frames_persistent(**params)
try:
    for frame in gen:
        last = frame
finally:
    gen.close()
assert last is not None
metrics = last.get('metrics_compact') or last.get('metrics')
scalars = {k: v for k, v in metrics.items() if isinstance(v, (int, float)) and math.isfinite(v)}
if args.system == 'B4_mission':
    assert scalars.get('stl_proposal_predictive_dispatch') == 1, 'Proposal dispatch missing from exported metrics'
    assert scalars.get('stl_mission_wide') == 0, 'Proposal must retain the existing dispatcher'
    assert scalars.get('mission_dispatch_decisions', 0) > 0
    if args.duration >= 900:
        assert scalars.get('mission_dispatch_candidates', 0) > 0, 'No predictive deterrence candidates were scored'
        assert scalars.get('urgent_reactive_override_total', 0) > 0, 'Reactive override path was not exercised'
    assert scalars.get('mission_reactive_deadline_s') == 90.
    assert scalars.get('stl_T_react_s') == 90.
    assert first_context is not None
Path(args.out).write_text(json.dumps(dict(system=args.system, hab=args.hab, params=params, metrics=scalars,
                                         first_context=first_context, elapsed_s=time.monotonic()-started), indent=2))
print(json.dumps(dict(system=args.system, hab=args.hab, scalar_count=len(scalars),
                     mission_decisions=scalars.get('mission_dispatch_decisions'),
                     elapsed_s=round(time.monotonic()-started, 2))))
