from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd


CURRENT_SMOKE = Path("testbench/thesis_compare_unc_vs_time_score_smoke.json")
CURRENT_FULL = Path("testbench/thesis_compare_unc_vs_time_score_nominal_24h.json")
ADVISOR_SMOKE = Path("testbench/thesis_compare_unc_vs_time_score_advisor_smoke.json")
ADVISOR_FULL = Path("testbench/thesis_compare_unc_vs_time_score_advisor_nominal_24h.json")
SUMMARY_NAME = "DUAL_METRIC_COMPARISON_SUMMARY.md"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_outdir(config: dict[str, Any]) -> Path:
    outputs = dict(config.get("outputs") or {})
    return Path(str(outputs.get("outdir") or "results/testbench/dual_metric_compare"))


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


def _read_scoreboard(outdir: Path) -> pd.DataFrame:
    return pd.read_csv(outdir / "system_scoreboard.csv")


def _read_summary(outdir: Path) -> pd.DataFrame:
    return pd.read_csv(outdir / "summary_by_metric.csv")


def _fmt(value: Any) -> str:
    try:
        value_f = float(value)
    except Exception:
        return str(value)
    if pd.isna(value_f):
        return "n/a"
    return f"{value_f:.3f}"


def _winner_keys(scoreboard_df: pd.DataFrame) -> list[str]:
    if scoreboard_df.empty:
        return []
    best_wins = scoreboard_df["metric_wins"].max()
    rows = scoreboard_df.loc[scoreboard_df["metric_wins"] == best_wins].sort_values("system")
    return [str(value) for value in rows["system"].tolist()]


def _write_dual_summary(
    *,
    current_config: dict[str, Any],
    advisor_config: dict[str, Any],
    current_outdir: Path,
    advisor_outdir: Path,
) -> Path:
    current_scoreboard = _read_scoreboard(current_outdir)
    advisor_scoreboard = _read_scoreboard(advisor_outdir)
    current_summary = _read_summary(current_outdir)
    advisor_summary = _read_summary(advisor_outdir)

    current_winners = _winner_keys(current_scoreboard)
    advisor_winners = _winner_keys(advisor_scoreboard)

    advisor_mapping = dict((advisor_config.get("metadata") or {}).get("advisor_metric_mapping") or {})

    lines: list[str] = []
    lines.append("# Dual Metric Comparison Summary")
    lines.append("")
    lines.append("This summary compares the same systems under two metric contracts:")
    lines.append("- the current thesis metric set")
    lines.append("- the advisor-suggested metric set")
    lines.append("")
    lines.append("## Winner Summary")
    lines.append("")
    lines.append(
        f"- current metric set winner(s): "
        + (", ".join(f"`{key}`" for key in current_winners) if current_winners else "unavailable")
    )
    lines.append(
        f"- advisor metric set winner(s): "
        + (", ".join(f"`{key}`" for key in advisor_winners) if advisor_winners else "unavailable")
    )
    lines.append("")
    lines.append("## Advisor Metric Mapping")
    lines.append("")
    for name, column in advisor_mapping.items():
        lines.append(f"- `{name}` -> `{column}`")
    lines.append("")

    lines.append("## Current Metric Set")
    lines.append("")
    lines.append(f"- report: [report.md]({(current_outdir / 'report.md').as_posix()})")
    lines.append(f"- scoreboard: [system_scoreboard.csv]({(current_outdir / 'system_scoreboard.csv').as_posix()})")
    lines.append(f"- plot: [time_metric_compare.png]({(current_outdir / 'time_metric_compare.png').as_posix()})")
    lines.append("")
    lines.append("| system | metric_wins | win_share |")
    lines.append("|:--|--:|--:|")
    for row in current_scoreboard.sort_values(["metric_wins", "win_share", "system"], ascending=[False, False, True]).itertuples(index=False):
        lines.append(f"| `{row.system}` | {int(row.metric_wins)} | {_fmt(row.win_share)} |")
    lines.append("")

    lines.append("## Advisor Metric Set")
    lines.append("")
    lines.append(f"- report: [report.md]({(advisor_outdir / 'report.md').as_posix()})")
    lines.append(f"- scoreboard: [system_scoreboard.csv]({(advisor_outdir / 'system_scoreboard.csv').as_posix()})")
    lines.append(f"- plot: [time_metric_compare.png]({(advisor_outdir / 'time_metric_compare.png').as_posix()})")
    lines.append("")
    lines.append("| system | metric_wins | win_share |")
    lines.append("|:--|--:|--:|")
    for row in advisor_scoreboard.sort_values(["metric_wins", "win_share", "system"], ascending=[False, False, True]).itertuples(index=False):
        lines.append(f"| `{row.system}` | {int(row.metric_wins)} | {_fmt(row.win_share)} |")
    lines.append("")

    lines.append("## Metric Winners By Contract")
    lines.append("")
    lines.append("| Metric Set | Metric | Winner |")
    lines.append("|:--|:--|:--|")
    for row in current_summary.itertuples(index=False):
        lines.append(f"| current | `{row.metric}` | `{row.winner}` |")
    for row in advisor_summary.itertuples(index=False):
        lines.append(f"| advisor | `{row.metric}` | `{row.winner}` |")
    lines.append("")

    summary_path = current_outdir.parent / SUMMARY_NAME
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the current-metric and advisor-metric time-score comparisons and write a combined markdown summary."
    )
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args()

    current_config_path = (CURRENT_SMOKE if args.smoke else CURRENT_FULL).resolve()
    advisor_config_path = (ADVISOR_SMOKE if args.smoke else ADVISOR_FULL).resolve()
    current_config = _load_json(current_config_path)
    advisor_config = _load_json(advisor_config_path)
    current_outdir = _resolve_outdir(current_config)
    advisor_outdir = _resolve_outdir(advisor_config)

    if not args.skip_run:
        _run_config(current_config_path, max_workers=int(args.max_workers))
        _run_config(advisor_config_path, max_workers=int(args.max_workers))

    summary_path = _write_dual_summary(
        current_config=current_config,
        advisor_config=advisor_config,
        current_outdir=current_outdir,
        advisor_outdir=advisor_outdir,
    )
    print(f"[dual-metric-compare] wrote {summary_path}")
    print(f"[dual-metric-compare] current results {current_outdir}")
    print(f"[dual-metric-compare] advisor results {advisor_outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
