"""Compare old/new historical implementations without calibration artifacts.

This is a regression fixture, not a policy evaluation. All values are resolved
explicitly; published numerical results are not reconstructed by this check.
"""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys


def child(source, params_path):
    os.environ["DETERRENT_TELEMETRY"] = "0"
    sys.path.insert(0, str(source))
    import DeterrentSystem as ds
    params = json.loads(params_path.read_text(encoding="utf-8"))
    names = inspect.signature(ds.run_simulation_frames_persistent).parameters
    unknown = set(params)-set(names)
    if unknown-set(["truth_process_mode"]):
        raise ValueError(f"unexpected configuration differences {unknown}")
    for name in unknown:
        params.pop(name)
    last = None
    for last in ds.run_simulation_frames_persistent(**params):
        pass
    metrics = last["metrics_compact"]
    keys = ("value_weighted_exposure", "truth_candidate_events", "truth_accepted_events",
            "truth_suppressed_events", "reactive_generated_total", "reactive_completed_total")
    print("REGRESSION_JSON=" + json.dumps({key: metrics[key] for key in keys}, allow_nan=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child-source", type=Path)
    parser.add_argument("--params", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.child_source is not None:
        child(args.child_source, args.params)
        return
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from experiments import run_hierarchical_calibration as h
    tested_sources = h.sources()
    baseline = json.loads((root/"ADDITIVE_BASELINE_MANIFEST.json").read_text())
    original = Path(baseline["source_directory"])
    changed = [name for name, value in baseline["files"].items()
               if name.endswith(".py") and hashlib.sha256((original/name).read_bytes()).hexdigest() != value]
    if changed:
        raise RuntimeError(f"Original source changed since snapshot: {changed}")
    output = args.out or root/"results/additive_verification/historical_pair.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    reference = h.paper_reference()
    configs = {}
    rows = []
    for system in h.SYSTEMS:
        parent = reference if system == "B1" else configs[h.PARENTS[system]]
        configs[system] = h.derive(system, parent)
        if system not in ("B1", "B4", "B5"):
            continue
        params = dict(configs[system], T_end=90., seed=201)
        path = output.parent/f"historical_fixture_{system}.json"
        path.write_text(json.dumps(params, allow_nan=False), encoding="utf-8")
        results = []
        for source in (original, root):
            proc = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                "--child-source", str(source), "--params", str(path)],
                cwd=root, capture_output=True, text=True, timeout=180)
            if proc.returncode:
                raise RuntimeError(proc.stderr[-4000:])
            lines = [line for line in proc.stdout.splitlines() if line.startswith("REGRESSION_JSON=")]
            if len(lines) != 1:
                raise RuntimeError("missing child regression metrics")
            results.append(json.loads(lines[0].split("=", 1)[1]))
        if results[0] != results[1]:
            raise AssertionError(f"historical regression differs for {system}: {results}")
        rows.append(dict(system=system, exact_match=True, metrics=results[0]))
        print(f"{system}: original and isolated historical mode agree exactly", flush=True)
    if h.sources() != tested_sources:
        raise RuntimeError("Source changed while historical regressions were executing")
    output.write_text(json.dumps(dict(original=str(original), original_runtime_source_unchanged=True,
        source_hashes=tested_sources,
        purpose="regression fixture only; not submitted-result reproduction", comparisons=rows), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
