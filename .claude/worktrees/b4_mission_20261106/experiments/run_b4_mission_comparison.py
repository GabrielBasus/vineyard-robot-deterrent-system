"""Run B4_mission on the frozen main B1-B5 matched evaluation design."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent / "additive_revision_20261103"
COHORT = PARENT / "results" / "additive_newloads_b1recal_v1"
MAIN_JOBS = COHORT / "jobs.json"
MAIN_ROWS = COHORT / "rows" / "all_studies.json"
WORKER_PATH = COHORT / "newloads_worker.py"
OUTDIR = ROOT.parents[2] / "results" / "testbench" / "b4_mission_main_comparison_v1"
LOADS = ("spare", "heavy", "overload")
HAB_STATES = (False, True)
SEEDS = tuple(range(400, 430))
BASELINES = ("B1", "B2", "B3", "B4", "B5")
METRICS = (
    "value_weighted_exposure",
    "completion_miss_fraction",
    "deadline_miss_fraction",
    "reactive_completed_total",
    "reactive_on_time_total",
    "predictive_completed_total",
)
RESERVE_GB = 4.0
LAUNCH_MARGIN_GB = 0.5
ABORT_GB = 3.0
INITIAL_WORKER_PEAK_GB = 0.75
MAX_ATTEMPTS = 3

for _import_root in (PARENT, ROOT):
    if str(_import_root) not in sys.path:
        sys.path.insert(0, str(_import_root))


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_identity() -> tuple[str, dict[str, str]]:
    excluded = {"tests", "__pycache__", ".pytest_cache"}
    sources = {}
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if any(part in excluded for part in relative.parts):
            continue
        sources[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _json_hash(sources), sources


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def _high_priority() -> None:
    if os.name == "nt":
        import psutil
        psutil.Process().nice(psutil.HIGH_PRIORITY_CLASS)


def _build_jobs(
    source_identity: str, source_hashes: dict[str, str]
) -> tuple[list[dict], list[dict]]:
    from experiments.b4_mission_profile import build_b4_mission

    raw_jobs = json.loads(MAIN_JOBS.read_text(encoding="utf-8"))
    raw_rows = json.loads(MAIN_ROWS.read_text(encoding="utf-8"))
    main_rows = [row for row in raw_rows if row.get("study") == "main_calibrated"]
    expected_baseline_keys = {
        (system, load, seed, hab)
        for system in BASELINES
        for load in LOADS
        for seed in SEEDS
        for hab in HAB_STATES
    }
    observed_baseline_keys = {
        (row["system"], row["load"], int(row["seed"]), bool(row["hab_on"]))
        for row in main_rows
    }
    if observed_baseline_keys != expected_baseline_keys or len(main_rows) != len(expected_baseline_keys):
        raise ValueError("The completed main B1-B5 rows do not match the declared 900-run design")

    selected = [
        job for job in raw_jobs
        if job.get("first_study") == "main_calibrated"
        and job.get("system") == "B4"
        and job.get("load") in LOADS
        and int(job.get("seed", -1)) in SEEDS
        and bool(job.get("hab_on")) in HAB_STATES
    ]
    expected_mission_keys = {
        (load, seed, hab)
        for load in LOADS for seed in SEEDS for hab in HAB_STATES
    }
    observed_mission_keys = {
        (job["load"], int(job["seed"]), bool(job["hab_on"])) for job in selected
    }
    if len(selected) != len(expected_mission_keys) or observed_mission_keys != expected_mission_keys:
        raise ValueError("The frozen main B4 jobs do not match the declared 180-run design")

    result_jobs = []
    for original in selected:
        params = build_b4_mission(original["params"])
        if bool(params.get("stl_mission_wide", False)):
            raise ValueError("The proposal profile must preserve the existing B4 dispatcher")
        key = (original["load"], int(original["seed"]), bool(original["hab_on"]))
        reference = next(
            row for row in main_rows
            if (row["system"], row["load"], int(row["seed"]), bool(row["hab_on"]))
            == ("B4", *key)
        )
        identity = _json_hash({
            "source_identity": source_identity,
            "baseline_identity": original["identity"],
            "params": params,
        })
        run_id = f"{original['load']}_hab{int(bool(original['hab_on']))}_seed{int(original['seed'])}"
        result_jobs.append({
            "identity": identity,
            "run_id": run_id,
            "cohort": "b4_mission_main_comparison_v1",
            "system": "B4_mission",
            "load": original["load"],
            "mu": float(original["mu"]),
            "seed": int(original["seed"]),
            "hab_on": bool(original["hab_on"]),
            "params": params,
            "audit_keys": [
                "stl_proposal_predictive_dispatch", "stl_mission_wide", "stl_T_react_s",
            ],
            "baseline_identity": original["identity"],
            "baseline_b4_row": reference,
            "source_identity": source_identity,
            "source_files": source_hashes,
            "output_path": str(OUTDIR / "raw" / f"{run_id}.json"),
        })
    return result_jobs, main_rows


def _worker(job_path: Path) -> int:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("b4_mission_main_worker", WORKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load evaluation worker: {WORKER_PATH}")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    _high_priority()
    row = worker.run_case(job)
    metrics = row["metrics"]
    if metrics.get("stl_proposal_predictive_dispatch") != 1.0:
        raise RuntimeError("Proposal-aligned B4_mission was not active")
    if metrics.get("stl_mission_wide") != 0.0:
        raise RuntimeError("B4_mission unexpectedly replaced the reserved dispatcher")
    if metrics.get("mission_dispatch_decisions", 0.0) <= 0.0:
        raise RuntimeError("B4_mission selector did not run")
    row.update(
        system="B4_mission",
        run_id=job["run_id"],
        identity=job["identity"],
        source_identity=job["source_identity"],
        baseline_identity=job["baseline_identity"],
        baseline_b4_row=job["baseline_b4_row"],
    )
    row["execution_provenance"]["runtime_source_identity"] = job["source_identity"]
    row["execution_provenance"]["runtime_source"] = job["source_files"]
    output = Path(job["output_path"])
    _write_json(output, row)
    print(json.dumps({
        "run_id": job["run_id"],
        "elapsed_s": round(float(row["elapsed_s"]), 2),
        "worker_peak_gb": round(float(row["worker_peak_gb"]), 3),
        "mission_candidates": metrics.get("mission_dispatch_candidates", 0.0),
        "urgent_overrides": metrics.get("urgent_reactive_override_total", 0.0),
    }), flush=True)
    return 0


def _prepare(source_identity: str, source_hashes: dict[str, str]) -> tuple[list[dict], list[dict]]:
    jobs, main_rows = _build_jobs(source_identity, source_hashes)
    manifest_path = OUTDIR / "manifest.json"
    manifest = {
        "cohort": "b4_mission_main_comparison_v1",
        "created_utc": _utc(),
        "system": "B4_mission",
        "source_identity": source_identity,
        "source_hashes": source_hashes,
        "reference_cohort": str(COHORT),
        "reference_runtime_source_identity": main_rows[0]["runtime_source_identity"],
        "reference_design": {
            "systems": list(BASELINES),
            "loads": list(LOADS),
            "seeds": [SEEDS[0], SEEDS[-1]],
            "habituation_states": list(HAB_STATES),
            "runs_per_system": len(main_rows) // len(BASELINES),
        },
        "mission_design": {
            "matched_runs": len(jobs),
            "duration_s": float(jobs[0]["params"]["T_end"]),
            "workers_max": 21,
            "priority": "high",
            "calibration": "reused frozen B4 parameters; no calibration jobs launched",
            "parameter_changes": [
                "stl_active_clauses",
                "stl_T_react_s",
                "stl_proposal_predictive_dispatch",
            ],
            "dispatch_contract": "retain reserved-capacity and urgent reactive override; STL ranks predictive deterrence only",
        },
        "resource_policy": {
            "reserve_gb": RESERVE_GB,
            "launch_margin_gb": LAUNCH_MARGIN_GB,
            "abort_below_available_gb": ABORT_GB,
            "initial_per_worker_estimate_gb": INITIAL_WORKER_PEAK_GB,
            "numerical_threads_per_worker": 1,
        },
        "analysis": {
            "paired_unit": "seed within load and habituation condition",
            "metrics": list(METRICS),
            "bootstrap_resamples": 10000,
            "bootstrap_rng_seed": 12345,
            "test": "two-sided Wilcoxon signed-rank",
            "interpretation": "exploratory cross-source comparison; report runtime identity difference",
        },
        "outputs": {
            "status": str(OUTDIR / "status.json"),
            "per_run_metrics": str(OUTDIR / "per_run_metrics.csv"),
            "comparison_summary": str(OUTDIR / "comparison_summary.csv"),
        },
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("source_identity") != source_identity:
            raise ValueError(f"Output directory contains a different source snapshot: {manifest_path}")
    else:
        _write_json(manifest_path, manifest)
    jobs_dir = OUTDIR / "jobs"
    for job in jobs:
        _write_json(jobs_dir / f"{job['run_id']}.json", job)
    return jobs, main_rows


def _status(**values) -> None:
    _write_json(OUTDIR / "status.json", {"updated_utc": _utc(), **values})


def _run_one(job: dict, attempts: int) -> dict:
    job_path = OUTDIR / "jobs" / f"{job['run_id']}.json"
    log_path = OUTDIR / "logs" / f"{job['run_id']}.log"
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(job_path)]
    env = os.environ.copy()
    env.update({
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "DETERRENT_TELEMETRY": "0",
    })
    last_error = None
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=3600,
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"attempt={attempt}\nreturncode={result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            encoding="utf-8",
        )
        if result.returncode == 0:
            row = json.loads(Path(job["output_path"]).read_text(encoding="utf-8"))
            if row.get("identity") != job["identity"] or row.get("config_hash") != _json_hash(job["params"]):
                raise RuntimeError(f"Identity/configuration mismatch for {job['run_id']}")
            return row
        last_error = RuntimeError(
            f"{job['run_id']} failed on attempt {attempt}: {result.stderr[-3000:]}"
        )
        if attempt < attempts:
            time.sleep(2 * attempt)
    raise last_error


def _write_run_metrics(rows: list[dict]) -> None:
    output = OUTDIR / "per_run_metrics.csv"
    fields = [
        "system", "load", "mu", "seed", "hab_on", "elapsed_s", "worker_peak_gb",
        "mission_dispatch_decisions", "mission_dispatch_candidates",
        "mission_predictive_selections", "urgent_reactive_override_total",
        *METRICS,
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (r["load"], r["hab_on"], r["seed"])):
            flat = {key: row.get(key) for key in fields}
            flat.update(row["metrics"])
            writer.writerow(flat)


def _analyze(rows: list[dict], main_rows: list[dict], source_identity: str) -> None:
    import numpy as np
    from scipy.stats import wilcoxon

    mission_by_key = {
        (r["load"], int(r["seed"]), bool(r["hab_on"])): r
        for r in rows
    }
    main_by_key = {
        (r["system"], r["load"], int(r["seed"]), bool(r["hab_on"])): r
        for r in main_rows
    }
    summary = []
    for load in LOADS:
        for hab in HAB_STATES:
            for baseline in BASELINES:
                paired = [
                    (mission_by_key[(load, seed, hab)], main_by_key[(baseline, load, seed, hab)])
                    for seed in SEEDS
                ]
                for metric in METRICS:
                    mission_values = np.asarray([a["metrics"][metric] for a, _ in paired], dtype=float)
                    baseline_values = np.asarray([b["metrics"][metric] for _, b in paired], dtype=float)
                    differences = mission_values - baseline_values
                    rng = np.random.default_rng(12345)
                    sample_indices = rng.integers(0, len(differences), size=(10000, len(differences)))
                    bootstrap = differences[sample_indices].mean(axis=1)
                    if np.all(differences == 0.0):
                        p_value = 1.0
                    else:
                        p_value = float(wilcoxon(differences, alternative="two-sided").pvalue)
                    base_mean = float(baseline_values.mean())
                    summary.append({
                        "load": load,
                        "hab_on": hab,
                        "baseline": baseline,
                        "metric": metric,
                        "n": int(len(differences)),
                        "mission_mean": float(mission_values.mean()),
                        "baseline_mean": base_mean,
                        "mean_difference": float(differences.mean()),
                        "difference_ci95_low": float(np.quantile(bootstrap, 0.025)),
                        "difference_ci95_high": float(np.quantile(bootstrap, 0.975)),
                        "difference_pct_of_baseline": (
                            float(100.0 * differences.mean() / base_mean)
                            if base_mean != 0.0 else None
                        ),
                        "wilcoxon_p": p_value,
                    })
    with (OUTDIR / "comparison_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    _write_json(OUTDIR / "comparison_summary.json", {
        "source_identity": source_identity,
        "reference_runtime_source_identity": main_rows[0]["runtime_source_identity"],
        "same_runtime_source": source_identity == main_rows[0]["runtime_source_identity"],
        "interpretation": (
            "Exploratory matched comparison. B4_mission and main B1-B5 have different runtime "
            "source identities; do not treat these contrasts as confirmatory."
        ),
        "comparisons": summary,
    })


def _load_completed(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    completed, pending = [], []
    for job in jobs:
        path = Path(job["output_path"])
        if not path.exists():
            pending.append(job)
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("identity") != job["identity"] or row.get("config_hash") != _json_hash(job["params"]):
            raise ValueError(f"Existing checkpoint does not match this run: {path}")
        completed.append(row)
    return completed, pending


def run(max_workers: int) -> None:
    import psutil

    _high_priority()
    source_identity, source_hashes = _source_identity()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    lock = OUTDIR / "RUNNING.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "started_utc": _utc()}))
    except FileExistsError as exc:
        raise RuntimeError(f"Another comparison runner holds {lock}") from exc

    pending = {}
    pool = None
    try:
        jobs, main_rows = _prepare(source_identity, source_hashes)
        completed, queue = _load_completed(jobs)
        _write_run_metrics(completed)
        _status(stage="running", completed=len(completed), total=len(jobs), queued=len(queue),
                running=0, max_workers=max_workers, priority="high",
                available_gb=round(psutil.virtual_memory().available / 1e9, 2))
        pool = ThreadPoolExecutor(max_workers=max_workers)
        peak_gb = INITIAL_WORKER_PEAK_GB
        last_status = 0.0
        while queue or pending:
            available = psutil.virtual_memory().available / 1e9
            if available < ABORT_GB:
                raise MemoryError("Available memory fell below 3 GB; completed checkpoints retained")
            while queue and len(pending) < max_workers and available >= (
                RESERVE_GB + LAUNCH_MARGIN_GB + peak_gb
            ):
                job = queue.pop(0)
                pending[pool.submit(_run_one, job, MAX_ATTEMPTS)] = job
                available -= peak_gb
            if pending:
                finished, _ = wait(pending, timeout=3, return_when=FIRST_COMPLETED)
                for future in finished:
                    job = pending.pop(future)
                    try:
                        row = future.result()
                    except Exception:
                        with (OUTDIR / "failures.jsonl").open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps({
                                "utc": _utc(),
                                "run_id": job["run_id"],
                                "error": traceback.format_exc(),
                            }) + "\n")
                        raise
                    completed.append(row)
                    peak_gb = max(0.3, peak_gb, float(row.get("worker_peak_gb", 0.0)))
                    _write_run_metrics(completed)
            elif queue:
                time.sleep(5)
            if time.monotonic() - last_status >= 10:
                _status(stage="running", completed=len(completed), total=len(jobs),
                        queued=len(queue), running=len(pending), max_workers=max_workers,
                        priority="high", available_gb=round(psutil.virtual_memory().available / 1e9, 2),
                        worker_peak_estimate_gb=round(peak_gb, 3))
                last_status = time.monotonic()
        pool.shutdown()
        pool = None
        if len(completed) != len(jobs):
            raise RuntimeError(f"Expected {len(jobs)} complete runs, found {len(completed)}")
        _write_run_metrics(completed)
        _analyze(completed, main_rows, source_identity)
        _status(stage="finished", completed=len(completed), total=len(jobs),
                max_workers=max_workers, priority="high",
                available_gb=round(psutil.virtual_memory().available / 1e9, 2))
    except BaseException as exc:
        _status(stage="failed", completed=len(completed) if "completed" in locals() else 0,
                total=len(jobs) if "jobs" in locals() else 180,
                running=len(pending), max_workers=max_workers, priority="high",
                error=repr(exc))
        raise
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-workers", type=int, default=21)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker is not None:
        return _worker(args.worker)
    if not 1 <= args.max_workers <= 21:
        parser.error("--max-workers must be in [1, 21]")
    run(args.max_workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
