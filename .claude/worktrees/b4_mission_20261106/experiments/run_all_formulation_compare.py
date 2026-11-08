from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_CONFIG = Path("testbench/thesis_compare_all_formulations_nominal_24h.json")
SUMMARY_FILENAME = "FORMULATION_COMPARISON_SUMMARY.md"


def _load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_outdir(config: dict[str, Any]) -> Path:
    outputs = dict(config.get("outputs") or {})
    return Path(str(outputs.get("outdir") or "results/testbench/thesis_compare_all_formulations"))


def _run_testbench(config_path: Path, *, max_workers: int) -> None:
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


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        value_f = float(value)
    except Exception:
        return str(value)
    if pd.isna(value_f):
        return "n/a"
    return f"{value_f:.3f}"


def _write_summary(
    *,
    config: dict[str, Any],
    outdir: Path,
    summary_df: pd.DataFrame,
    scoreboard_df: pd.DataFrame,
) -> Path:
    systems = list(config.get("systems") or [])
    system_keys = [str(system.get("key")) for system in systems]
    system_titles = {str(system.get("key")): str(system.get("title") or system.get("key")) for system in systems}
    outputs = dict(config.get("outputs") or {})
    scenario = dict(config.get("scenario") or {})
    scoreboard_metrics = list(outputs.get("scoreboard_metrics") or [])
    all_metrics = list(outputs.get("metrics") or [])

    overall_winner = ""
    if not scoreboard_df.empty and "metric_wins" in scoreboard_df.columns:
        ranked = scoreboard_df.sort_values(["metric_wins", "win_share", "system"], ascending=[False, False, True])
        overall_winner = str(ranked.iloc[0]["system"])

    lines: list[str] = []
    lines.append("# All Formulation Comparison Summary")
    lines.append("")
    lines.append("This summary is generated from the testbench outputs after running the full all-formulations comparison.")
    lines.append("")
    lines.append("## Decision Rule")
    lines.append("")
    lines.append("The overall winner is the system with the highest `metric_wins` count on the configured scoreboard metrics.")
    lines.append("")
    lines.append("## Overall Winner")
    lines.append("")
    if overall_winner:
        lines.append(f"- winner key: `{overall_winner}`")
        lines.append(f"- winner title: {system_titles.get(overall_winner, overall_winner)}")
    else:
        lines.append("- winner: unavailable")
    lines.append("")
    lines.append("## Scenario")
    lines.append("")
    lines.append(f"- duration_s: `{scenario.get('duration_s', 'n/a')}`")
    lines.append(f"- warmup_s: `{scenario.get('warmup_s', 'n/a')}`")
    lines.append(f"- num_runs: `{scenario.get('num_runs', 'n/a')}`")
    lines.append(f"- seed_start: `{scenario.get('seed_start', 'n/a')}`")
    lines.append(f"- reference_system: `{outputs.get('reference_system', '')}`")
    lines.append("")
    lines.append("## Systems")
    lines.append("")
    for key in system_keys:
        lines.append(f"- `{key}`: {system_titles.get(key, key)}")
    lines.append("")
    lines.append("## Scoreboard Metrics")
    lines.append("")
    for metric in scoreboard_metrics:
        lines.append(f"- `{metric}`")
    lines.append("")
    lines.append("## Diagnostic Metrics")
    lines.append("")
    for metric in all_metrics:
        if metric not in scoreboard_metrics:
            lines.append(f"- `{metric}`")
    lines.append("")
    lines.append("## Scoreboard")
    lines.append("")
    if scoreboard_df.empty:
        lines.append("No scoreboard data found.")
    else:
        lines.append("| system | title | metric_wins | win_share |")
        lines.append("|:--|:--|--:|--:|")
        for row in scoreboard_df.sort_values(["metric_wins", "win_share", "system"], ascending=[False, False, True]).itertuples(index=False):
            key = str(row.system)
            lines.append(
                f"| `{key}` | {system_titles.get(key, key)} | {int(getattr(row, 'metric_wins', 0))} | {_fmt(getattr(row, 'win_share', 'n/a'))} |"
            )
    lines.append("")
    lines.append("## Metric Detail")
    lines.append("")
    for row in summary_df.itertuples(index=False):
        metric = str(getattr(row, "metric"))
        label = str(getattr(row, "label"))
        goal = str(getattr(row, "goal"))
        winner = str(getattr(row, "winner"))
        lines.append(f"### {label}")
        lines.append("")
        lines.append(f"- metric: `{metric}`")
        lines.append(f"- goal: `{goal}`")
        lines.append(f"- winner: `{winner}`")
        lines.append("")
        lines.append("| system | title | mean | ci95 low | ci95 high |")
        lines.append("|:--|:--|--:|--:|--:|")
        for key in system_keys:
            mean = getattr(row, f"{key}_mean", None)
            ci_lo = getattr(row, f"{key}_ci_lo", None)
            ci_hi = getattr(row, f"{key}_ci_hi", None)
            if mean is None and ci_lo is None and ci_hi is None:
                continue
            lines.append(
                f"| `{key}` | {system_titles.get(key, key)} | {_fmt(mean)} | {_fmt(ci_lo)} | {_fmt(ci_hi)} |"
            )
        lines.append("")
    lines.append("## Artifact References")
    lines.append("")
    lines.append(f"- full testbench report: [report.md]({(outdir / 'report.md').as_posix()})")
    lines.append(f"- scoreboard csv: [system_scoreboard.csv]({(outdir / 'system_scoreboard.csv').as_posix()})")
    lines.append(f"- summary csv: [summary_by_metric.csv]({(outdir / 'summary_by_metric.csv').as_posix()})")
    lines.append(f"- per-run metrics: [per_run_metrics.csv]({(outdir / 'per_run_metrics.csv').as_posix()})")

    summary_path = outdir / SUMMARY_FILENAME
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the all-formulations testbench comparison and write a markdown winner summary."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = _load_config(config_path)
    outdir = _resolve_outdir(config)

    if not args.skip_run:
        _run_testbench(config_path, max_workers=int(args.max_workers))

    summary_csv = outdir / "summary_by_metric.csv"
    scoreboard_csv = outdir / "system_scoreboard.csv"
    if not summary_csv.exists():
        raise FileNotFoundError(f"Expected summary metrics at {summary_csv}")
    if not scoreboard_csv.exists():
        raise FileNotFoundError(f"Expected scoreboard metrics at {scoreboard_csv}")

    summary_df = pd.read_csv(summary_csv)
    scoreboard_df = pd.read_csv(scoreboard_csv)
    summary_path = _write_summary(
        config=config,
        outdir=outdir,
        summary_df=summary_df,
        scoreboard_df=scoreboard_df,
    )
    print(f"[all-formulation-compare] wrote {summary_path}")
    print(f"[all-formulation-compare] source {summary_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
