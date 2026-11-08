from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.run_core_regression_check import _compare, build_fingerprint


CASES: dict[str, dict] = {
    "unc": {
        "reference": Path("regression_references/thesis_dispatch_unc_seed123_t10_dt1.json"),
        "kwargs": {
            "seed": 123,
            "t_end": 10.0,
            "dt": 1.0,
            "fps": 1,
            "simulation_mode": "proposed",
            "dispatch_policy": "unc",
        },
    },
    "react": {
        "reference": Path("regression_references/thesis_dispatch_react_seed123_t10_dt1.json"),
        "kwargs": {
            "seed": 123,
            "t_end": 10.0,
            "dt": 1.0,
            "fps": 1,
            "simulation_mode": "proposed",
            "dispatch_policy": "react",
        },
    },
    "res_0p25": {
        "reference": Path("regression_references/thesis_dispatch_res_0p25_seed123_t10_dt1.json"),
        "kwargs": {
            "seed": 123,
            "t_end": 10.0,
            "dt": 1.0,
            "fps": 1,
            "simulation_mode": "proposed",
            "dispatch_policy": "res",
            "reservation_fraction": 0.25,
        },
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze or compare thesis dispatch regression references.")
    parser.add_argument("--case", choices=sorted(CASES.keys()), nargs="*", default=sorted(CASES.keys()))
    parser.add_argument("--write-reference", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failed = False
    for case_name in args.case:
        case = CASES[case_name]
        reference = Path(case["reference"])
        fingerprint = build_fingerprint(**case["kwargs"])
        reference.parent.mkdir(parents=True, exist_ok=True)
        if args.write_reference:
            reference.write_text(json.dumps(fingerprint, indent=2), encoding="utf-8")
            print(f"[thesis-regression] wrote {reference}")
            continue
        if not reference.exists():
            print(f"[thesis-regression] missing reference: {reference}")
            failed = True
            continue
        expected = json.loads(reference.read_text(encoding="utf-8"))
        ok, message = _compare(expected, fingerprint)
        if ok:
            print(f"[thesis-regression] PASS {case_name} {reference}")
        else:
            print(f"[thesis-regression] FAIL {case_name} {reference}")
            print(f"[thesis-regression] {message}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
