"""Cross-machine equivalence check (user request 2026-10-23).

Run the same short fixed jobs on two machines and compare every behavioral metric bit for
bit before results from a second machine are used.  The jobs cover the ordinary pipeline
(B5_c), the B4 STL pipeline with its Section 3 shadow (A), the Section 2 variant (B) and the
plan procedure with a 2-worker rollout pool (E_plan), so the process-pool start method
(fork on Linux, spawn on Windows) is exercised too.

    python -m experiments.cross_machine_check run --out results/cross_machine/<name>.json
    python -m experiments.cross_machine_check compare a.json b.json

``compare`` exits 0 only when both files come from the same git commit and every
behavioral metric is identical.  Wall-clock metrics (runtime, elapsed, wall time) and the
``selected_calibration_*`` echo of the on-disk calibration record are excluded; copy
results/sestpp_calibration_sweep/ to the second machine anyway.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DETERRENT_TELEMETRY", "0")

from experiments import run_plan_completion as rpc  # noqa: E402

HEAVY, SPARE = 1e-4, 2e-5
SEED = 300
# (name, variant, mu, T_end, extra params)
JOBS = (
    ("B5_c_heavy", "B5_c", HEAVY, 600.0, {}),
    ("A_heavy", "A", HEAVY, 600.0, {}),
    ("B_heavy", "B", HEAVY, 300.0, {}),
    ("E_plan_spare", "E_plan", SPARE, 300.0, {"plan_pool_workers": 2}),
)
_TIMING = re.compile(r"(runtime|elapsed|wall|timing|_ms$|_ms_|^selected_calibration_)")


def _scalar(v):
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else repr(v)
    return None


def run(out: Path, min_free_gb: float) -> None:
    import DeterrentSystem as ds

    result = {"code": rpc.code_version(), "jobs": {}}
    for name, variant, mu, t_end, extra in JOBS:
        rpc.wait_for_memory(min_free_gb, tag="xcheck")
        params = rpc.build_params(variant, True, mu, t_end)
        params.update(extra)
        params["seed"] = SEED
        t0 = time.time()
        last = None
        for frame in ds.run_simulation_frames_persistent(**params):
            last = frame
        m = (last or {}).get("metrics_compact") or (last or {}).get("metrics") or {}
        metrics = {k: _scalar(v) for k, v in m.items() if _scalar(v) is not None or v is None}
        result["jobs"][name] = {"metrics": metrics, "wall_s": time.time() - t0}
        print(f"[xcheck] {name}: VWE {m.get('value_weighted_exposure')} in {time.time() - t0:.0f} s", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True))
    print(f"[xcheck] wrote {out}")


def compare(a: Path, b: Path) -> int:
    A, B = json.loads(a.read_text()), json.loads(b.read_text())
    ok = True
    ca, cb = A["code"], B["code"]
    print(f"A: {ca.get('machine_host')} {ca.get('machine_platform')} commit {ca['git_commit'][:10]}"
          f"{' dirty' if ca.get('git_dirty') else ''}")
    print(f"B: {cb.get('machine_host')} {cb.get('machine_platform')} commit {cb['git_commit'][:10]}"
          f"{' dirty' if cb.get('git_dirty') else ''}")
    if (ca["git_commit"], ca.get("git_diff_sha1")) != (cb["git_commit"], cb.get("git_diff_sha1")):
        print("FAIL: different code (commit or uncommitted changes); rerun both on one commit")
        ok = False
    for k in ("machine_python", "machine_numpy", "machine_scipy"):
        if ca.get(k) != cb.get(k):
            print(f"WARN: {k} differs ({ca.get(k)} vs {cb.get(k)}); install requirements.txt")
    for name in sorted(set(A["jobs"]) | set(B["jobs"])):
        ma, mb = A["jobs"].get(name, {}).get("metrics"), B["jobs"].get(name, {}).get("metrics")
        if ma is None or mb is None:
            print(f"FAIL {name}: missing on one machine")
            ok = False
            continue
        keys = sorted(k for k in set(ma) | set(mb) if not _TIMING.search(k))
        diffs = [k for k in keys if ma.get(k) != mb.get(k)]
        if diffs:
            ok = False
            print(f"FAIL {name}: {len(diffs)} of {len(keys)} metrics differ, e.g.")
            for k in diffs[:15]:
                va, vb = ma.get(k), mb.get(k)
                rel = ""
                if isinstance(va, float) and isinstance(vb, float) and va:
                    rel = f"  (rel {abs(va - vb) / abs(va):.2e})"
                print(f"   {k}: {va!r} vs {vb!r}{rel}")
        else:
            print(f"OK   {name}: all {len(keys)} behavioral metrics identical")
    print("RESULT:", "IDENTICAL" if ok else "DIFFERENT (do not mix these machines within a comparison)")
    return 0 if ok else 1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--min-free-gb", type=float, default=rpc.MIN_FREE_GB)
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    args = p.parse_args()
    if args.cmd == "run":
        run(Path(args.out), args.min_free_gb)
    else:
        sys.exit(compare(Path(args.a), Path(args.b)))


if __name__ == "__main__":
    main()
