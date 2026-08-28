from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.run_habituation_stl_production_ladder import (  # noqa: E402
    _advantage_rows,
    _habituation_delta_rows,
    _summarize,
    _write_csv,
    _write_markdown_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize raw habituation/STL production ladder JSON outputs."
    )
    parser.add_argument(
        "--outdir",
        default="results/testbench/habituation_stl_production_ladder_short",
        help="Ladder output directory containing raw/*.json files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outdir = Path(args.outdir).resolve()
    raw_dir = outdir / "raw"
    rows = []
    for path in sorted(raw_dir.glob("*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    if not rows:
        raise SystemExit(f"No raw JSON files found in {raw_dir}")

    rows = sorted(rows, key=lambda r: (str(r["baseline"]), str(r["habituation_condition"]), int(r["seed"])))
    _write_csv(rows, outdir / "per_run_metrics.csv")
    _write_csv(_summarize(rows), outdir / "summary_by_system.csv")
    _write_csv(_advantage_rows(rows), outdir / "advantage_vs_reference.csv")
    _write_csv(_habituation_delta_rows(rows), outdir / "habituation_on_vs_off.csv")
    _write_markdown_summary(rows, outdir)
    print(f"[summarize] rows={len(rows)} outdir={outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
