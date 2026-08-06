from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROBOT_COUNTS: tuple[int, ...] = (6, 4, 3, 2)
PILOT_CONFIGS: dict[int, Path] = {
    6: Path("testbench/april_thesis_load_sweep_pilot_6r.json"),
    4: Path("testbench/april_thesis_load_sweep_pilot_4r.json"),
    3: Path("testbench/april_thesis_load_sweep_pilot_3r.json"),
    2: Path("testbench/april_thesis_load_sweep_pilot_2r.json"),
}
FULL_CONFIGS: dict[int, Path] = {
    6: Path("testbench/april_thesis_load_sweep_full_6r.json"),
    4: Path("testbench/april_thesis_load_sweep_full_4r.json"),
    3: Path("testbench/april_thesis_load_sweep_full_3r.json"),
    2: Path("testbench/april_thesis_load_sweep_full_2r.json"),
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_outdir(config_path: Path) -> Path:
    config = _load_json(config_path)
    outputs = dict(config.get("outputs") or {})
    return Path(str(outputs.get("outdir") or "results/testbench/april_thesis_load_sweep"))


def _run_config(config_path: Path, *, max_workers: int) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "testbench.run_testbench",
            "--config",
            str(config_path),
            "--max-workers",
            str(int(max_workers)),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the April-thesis reserved-capacity load sweep using the core "
            "UNC / RES(0.25) / RES-RAND(0.25) policy set."
        )
    )
    parser.add_argument("--full", action="store_true", help="Run the 5-seed full sweep instead of the 2-seed pilot sweep.")
    parser.add_argument("--skip-run", action="store_true", help="Do not execute the configs; just print what would run.")
    parser.add_argument("--max-workers", type=int, default=3)
    parser.add_argument(
        "--robot-counts",
        nargs="*",
        type=int,
        default=list(ROBOT_COUNTS),
        help="Subset of robot counts to run, chosen from 6 4 3 2.",
    )
    args = parser.parse_args()

    config_map = FULL_CONFIGS if args.full else PILOT_CONFIGS
    selected_counts = []
    for value in args.robot_counts:
        if int(value) not in config_map:
            raise SystemExit(f"Unsupported robot count {value!r}. Expected one of: {', '.join(str(v) for v in ROBOT_COUNTS)}")
        selected_counts.append(int(value))

    selected_counts = [count for count in ROBOT_COUNTS if count in set(selected_counts)]
    label = "full" if args.full else "pilot"
    print(f"[april-load-sweep] mode={label} counts={selected_counts} max_workers={int(args.max_workers)}")
    for count in selected_counts:
        config_path = config_map[count].resolve()
        outdir = _resolve_outdir(config_path)
        print(f"[april-load-sweep] {count} robots -> {config_path}")
        print(f"[april-load-sweep] output -> {outdir}")
        if not args.skip_run:
            _run_config(config_path, max_workers=int(args.max_workers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
