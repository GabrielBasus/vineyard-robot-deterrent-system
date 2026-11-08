"""Default-path comparison against the pinned parent, in separate processes."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PARENT = ROOT.parent / 'additive_revision_20261103'
FIXTURE = HERE / 'run_fixture.py'
PYTHON = sys.executable
JOBS = [(label, source, system, hab, 180) for label, source in [('parent', PARENT), ('new', ROOT)]
        for system in ('B1', 'B4', 'B5') for hab in (0, 1)]
JOBS += [('mission', ROOT, 'B4_mission', hab, 900) for hab in (0, 1)]


def run(job):
    label, source, system, hab, duration = job
    output = HERE / f'bridge_{label}_{system}_hab{hab}.json'
    command = [PYTHON, str(FIXTURE), '--root', str(source), '--system', system,
               '--hab', str(hab), '--duration', str(duration), '--out', str(output)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=240)
    if result.returncode:
        raise RuntimeError(str(job) + '\n' + result.stdout + '\n' + result.stderr)
    return str(output.name), result.stdout.strip()


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(run, job) for job in JOBS]):
            print(future.result(), flush=True)
    comparisons = []
    for system in ('B1', 'B4', 'B5'):
        for hab in (0, 1):
            old = json.loads((HERE / f'bridge_parent_{system}_hab{hab}.json').read_text())['metrics']
            new = json.loads((HERE / f'bridge_new_{system}_hab{hab}.json').read_text())['metrics']
            keys = (set(old) | set(new))
            ignored = sorted(k for k in keys if k.startswith('stl_eval_runtime_'))
            differences = {k: [old.get(k), new.get(k)] for k in sorted(keys - set(ignored)) if old.get(k) != new.get(k)}
            comparisons.append(dict(system=system, hab=hab, compared=len(keys)-len(ignored),
                                    ignored_wall_clock_only=ignored, differences=differences))
    passed = all(not c['differences'] for c in comparisons)
    report = dict(passed=passed, fixture_seed=99011, default_duration_s=180,
                  mission_duration_s=900,
                  independent_processes=True, comparisons=comparisons)
    (HERE / 'baseline_bridge.json').write_text(json.dumps(report, indent=2))
    if not passed:
        raise RuntimeError('Default-path regression failed: ' + str([c for c in comparisons if c['differences']]))
    print('All six B1/B4/B5 default comparisons match exactly outside measured wall time.', flush=True)
