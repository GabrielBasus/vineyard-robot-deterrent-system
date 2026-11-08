"""Verified additive B1 estimator stage. Never dispatches historical recordings.

This entry point deliberately stops after the finite estimator stage. Policy
search and fresh evaluation require their own declared downstream seed roles.
The A-E continuation implementation remains separately gated.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

os.environ.setdefault("DETERRENT_TELEMETRY", "0")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments import additive_protocol as protocol
from experiments import run_hierarchical_calibration as h


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verification_gate(path):
    gate = h.read(path)
    if gate.get("scope") != "additive_B1_B5_core" or gate.get("source_hashes") != h.sources():
        raise ValueError("Additive verification is missing or stale for this source snapshot")
    for key in ("tests", "historical_regression"):
        artifact = gate[key]
        if file_hash(artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"Verification artifact changed: {key}")
    report = ET.parse(gate["tests"]["path"]).getroot()
    suites = [report] if report.tag == "testsuite" else list(report.iter("testsuite"))
    if not suites or sum(int(s.get("tests", 0)) for s in suites) < 90 or any(
            int(s.get("failures", 0)) or int(s.get("errors", 0)) for s in suites):
        raise ValueError("Additive verification tests did not pass")
    identities = [prop.get("value") for prop in report.iter("property")
                  if prop.get("name") == "additive_source_sha256"]
    if identities != [h.digest(h.sources())]:
        raise ValueError("Test report does not verify the current runtime source")
    regression = h.read(gate["historical_regression"]["path"])
    if regression.get("source_hashes") != h.sources():
        raise ValueError("Historical regression source identity is stale")
    if not regression.get("original_runtime_source_unchanged") or len(regression.get("comparisons", [])) != 3 or not all(
            r.get("exact_match") for r in regression["comparisons"]):
        raise ValueError("Historical source regression has not passed")
    return gate


class AdditiveRunner(h.Runner):
    def benchmark(self, reference):
        path = self.out/"benchmark.json"
        if path.exists():
            self.workers = min(h.read(path)["selected_workers"], self.limit())
            return
        ceiling = min(self.limit(), 30)
        if ceiling == 0:
            raise RuntimeError("Insufficient memory for additive benchmark with 4 GB reserve")
        params = dict(reference, T_end=180.)
        jobs = self.jobs("benchmark", "B1", params, range(200, 200+max(2, ceiling//3)))
        trials = []
        for count in sorted(set((1, min(2, ceiling), ceiling))):
            started = time.monotonic()
            rows = self.run("benchmarking_additive_B1", jobs, force=True, workers=count)
            checksum = h.digest([r["metrics"]["value_weighted_exposure"] for r in rows])
            trials.append(dict(workers=count, seconds=time.monotonic()-started,
                               jobs=len(jobs), checksum=checksum))
            h.save(self.out/"benchmark_progress.json", trials)
        if len({r["checksum"] for r in trials}) != 1:
            raise RuntimeError("Worker benchmark changed deterministic numerical outputs")
        self.workers = min(trials, key=lambda row: row["seconds"])["workers"]
        h.save(path, dict(selected_workers=self.workers, trials=trials, duration_s=180., reserve_gb=4.))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT/"results/additive_calibration_v1")
    parser.add_argument("--verification", type=Path, default=ROOT/"results/additive_verification/release.json")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--estimator-hours", type=float, default=4.)
    args = parser.parse_args(argv)
    if args.workers < 1 or not 0 < args.estimator_hours <= 4:
        raise ValueError("Invalid finite calibration resource budget")
    verification = verification_gate(args.verification)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    lock = args.out/"RUNNING.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    runner = None
    try:
        runner = AdditiveRunner(args.out, args.workers)
        reference = protocol.reference()
        manifest = dict(contract=protocol.CONTRACT, reference=reference,
                        nominal_hierarchy=protocol.resolved_hierarchy(),
                        source=runner.source, source_identity=runner.identity, machine=runner.machine,
                        verification=verification,
                        training=list(h.TRAIN), development=list(h.DEV),
                        seed_note="200-219 are reused training/development identifiers, not fresh validation",
                        future_validation="not yet allocated; 220-229 and 300-309 are previously used",
                        estimator_candidate_cap=81, estimator_hours=args.estimator_hours,
                        policy_candidate_cap=48, selection_objective="equal-load normalized exposure only",
                        scope="B1 estimator stage only; no policy/evaluation/continuation runs", deployed=False)
        path = runner.out/"manifest.json"
        if path.exists() and h.digest(h.read(path)) != h.digest(manifest):
            raise ValueError("Manifest/source changed: use a new output directory")
        h.save(path, manifest)
        runner.benchmark(reference)
        selected = h.estimator_stage(runner, reference, args.estimator_hours)
        runner.status("additive_B1_estimator_finished", selected=selected,
                      next_stage="freeze downstream policy protocol and fresh seed roles")
    except BaseException as error:
        if runner is not None:
            runner.status("stopped", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
