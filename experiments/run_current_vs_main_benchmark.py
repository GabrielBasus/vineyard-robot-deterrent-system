from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


CURRENT_LABEL = "current"
MAIN_LABEL = "main"
MOVE_EPS_M = 1e-6


@dataclass(frozen=True)
class MetricSpec:
    column: str
    label: str
    goal: str


COMMON_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("completed_tasks_total", "Completed Tasks", "higher"),
    MetricSpec("completed_deterring_total", "Completed Deterring", "higher"),
    MetricSpec("completed_patrolling_total", "Completed Patrolling", "higher"),
    MetricSpec("completed_tasks_per_hour", "Completed Tasks / Hour", "higher"),
    MetricSpec("mean_completion_latency_s", "Mean Completion Latency (s)", "lower"),
    MetricSpec("tasks_per_km_travel", "Tasks / km Travel", "higher"),
    MetricSpec("mean_active_tasks", "Mean Active Backlog", "lower"),
    MetricSpec("final_active_tasks", "Final Active Backlog", "lower"),
)


OPTIONAL_NATIVE_METRICS: tuple[str, ...] = (
    "value_weighted_exposure",
    "mean_response_time_s",
    "truth_suppression_rate_last_hour",
    "birds_deterred_pct_last_hour",
    "truth_suppression_rate",
    "birds_deterred_pct",
    "boundary_message_count",
    "forecast_recall_at_k",
    "forecast_precision_at_k",
)


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    return out if math.isfinite(out) else float(default)


def _task_type(task: dict[str, Any]) -> str:
    return str(task.get("type", "")).strip().lower()


def _task_key(task: dict[str, Any]) -> str:
    if task.get("id") not in (None, ""):
        return f"id:{task.get('id')}"
    x = _safe_float(task.get("x"))
    y = _safe_float(task.get("y"))
    t = _safe_float(task.get("time"))
    return f"{_task_type(task)}:{round(x, 4)}:{round(y, 4)}:{round(t, 4)}"


def _ci95(values: Iterable[float]) -> tuple[float, float, float, int]:
    arr = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna().to_numpy(dtype=float)
    n = int(arr.size)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 0
    mean = float(np.mean(arr))
    if n == 1:
        return mean, mean, mean, n
    ci = float(1.96 * np.std(arr, ddof=1) / np.sqrt(n))
    return mean, mean - ci, mean + ci, n


def _format_ci(mean: float, lo: float, hi: float) -> str:
    if not np.isfinite(mean):
        return "n/a"
    if not np.isfinite(lo) or not np.isfinite(hi):
        return f"{mean:.3f}"
    return f"{mean:.3f} [{lo:.3f}, {hi:.3f}]"


def _filter_supported_kwargs(fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    params = set(inspect.signature(fn).parameters.keys())
    return {key: value for key, value in kwargs.items() if key in params}


class BenchmarkCollector:
    def __init__(self, *, sample_every_s: float) -> None:
        self.sample_every_s = max(float(sample_every_s), 1.0)
        self.frame_count = 0
        self.last_t = 0.0
        self.prev_pose: dict[str, tuple[float, float]] | None = None
        self.total_distance_by_robot: dict[str, float] = {}
        self.robot_count = 0
        self.active_sum = 0.0
        self.active_deterring_sum = 0.0
        self.active_patrolling_sum = 0.0
        self.max_active_tasks = 0
        self.final_active_tasks = 0
        self.moving_robot_frames = 0
        self.robot_frame_observations = 0
        self.done_keys_seen: set[str] = set()
        self.completed_total = 0
        self.completed_deterring = 0
        self.completed_patrolling = 0
        self.completion_latencies: list[float] = []
        self.deterring_latencies: list[float] = []
        self.patrolling_latencies: list[float] = []
        self.next_sample_t = -float("inf")
        self.sample_rows: list[dict[str, Any]] = []
        self.native_metrics: dict[str, float] = {}

    def consume(self, frame: dict[str, Any]) -> None:
        t = _safe_float(frame.get("t"), 0.0)
        poses = {
            str(rid): (float(xy[0]), float(xy[1]))
            for rid, xy in dict(frame.get("poses", {})).items()
            if isinstance(xy, (tuple, list)) and len(xy) >= 2
        }
        self.robot_count = max(self.robot_count, len(poses))
        if self.prev_pose is not None:
            for rid, xy in poses.items():
                prev_xy = self.prev_pose.get(rid)
                if prev_xy is None:
                    continue
                step = math.hypot(xy[0] - prev_xy[0], xy[1] - prev_xy[1])
                self.total_distance_by_robot[rid] = self.total_distance_by_robot.get(rid, 0.0) + float(step)
                self.robot_frame_observations += 1
                if step > MOVE_EPS_M:
                    self.moving_robot_frames += 1
        else:
            for rid in poses:
                self.total_distance_by_robot.setdefault(rid, 0.0)
        self.prev_pose = poses

        active_tasks = list(frame.get("tasks_active", []))
        done_tasks = list(frame.get("tasks_done", []))
        active_deterring = sum(1 for task in active_tasks if _task_type(task) == "deterring")
        active_patrolling = sum(1 for task in active_tasks if _task_type(task) == "patrolling")
        self.frame_count += 1
        self.last_t = float(t)
        self.active_sum += float(len(active_tasks))
        self.active_deterring_sum += float(active_deterring)
        self.active_patrolling_sum += float(active_patrolling)
        self.max_active_tasks = max(self.max_active_tasks, len(active_tasks))
        self.final_active_tasks = len(active_tasks)

        for task in done_tasks:
            key = _task_key(task)
            if key in self.done_keys_seen:
                continue
            self.done_keys_seen.add(key)
            task_type = _task_type(task)
            self.completed_total += 1
            if task_type == "deterring":
                self.completed_deterring += 1
            elif task_type == "patrolling":
                self.completed_patrolling += 1
            created_t = _safe_float(task.get("time"))
            if np.isfinite(created_t):
                latency = max(0.0, float(t) - created_t)
                self.completion_latencies.append(latency)
                if task_type == "deterring":
                    self.deterring_latencies.append(latency)
                elif task_type == "patrolling":
                    self.patrolling_latencies.append(latency)

        native = frame.get("metrics_compact") or frame.get("metrics") or {}
        if isinstance(native, dict):
            for key in OPTIONAL_NATIVE_METRICS:
                value = _safe_float(native.get(key))
                if np.isfinite(value):
                    self.native_metrics[f"native_{key}"] = value

        if t + 1e-9 >= self.next_sample_t:
            total_distance = float(sum(self.total_distance_by_robot.values()))
            sample_row = {
                "t": float(t),
                "active_tasks": int(len(active_tasks)),
                "active_deterring": int(active_deterring),
                "active_patrolling": int(active_patrolling),
                "completed_tasks_total": int(self.completed_total),
                "completed_deterring_total": int(self.completed_deterring),
                "completed_patrolling_total": int(self.completed_patrolling),
                "cumulative_distance_m": total_distance,
                "tasks_per_km_travel": (
                    1000.0 * float(self.completed_total) / total_distance if total_distance > MOVE_EPS_M else float("nan")
                ),
            }
            if isinstance(native, dict):
                for key in OPTIONAL_NATIVE_METRICS:
                    value = _safe_float(native.get(key))
                    sample_row[f"native_{key}"] = value
            self.sample_rows.append(
                sample_row
            )
            self.next_sample_t = float(t) + self.sample_every_s

    def finalize(self) -> dict[str, Any]:
        total_distance = float(sum(self.total_distance_by_robot.values()))
        duration_s = float(self.last_t)
        summary = {
            "frame_count": int(self.frame_count),
            "duration_s": duration_s,
            "robot_count": int(self.robot_count),
            "completed_tasks_total": int(self.completed_total),
            "completed_deterring_total": int(self.completed_deterring),
            "completed_patrolling_total": int(self.completed_patrolling),
            "completed_tasks_per_hour": (
                3600.0 * float(self.completed_total) / duration_s if duration_s > MOVE_EPS_M else float("nan")
            ),
            "mean_completion_latency_s": (
                float(np.mean(self.completion_latencies)) if self.completion_latencies else float("nan")
            ),
            "mean_deterring_latency_s": (
                float(np.mean(self.deterring_latencies)) if self.deterring_latencies else float("nan")
            ),
            "mean_patrolling_latency_s": (
                float(np.mean(self.patrolling_latencies)) if self.patrolling_latencies else float("nan")
            ),
            "total_robot_distance_m": total_distance,
            "mean_robot_distance_m": (total_distance / float(self.robot_count) if self.robot_count > 0 else float("nan")),
            "tasks_per_km_travel": (
                1000.0 * float(self.completed_total) / total_distance if total_distance > MOVE_EPS_M else float("nan")
            ),
            "mean_active_tasks": (
                float(self.active_sum / float(self.frame_count)) if self.frame_count > 0 else float("nan")
            ),
            "mean_active_deterring": (
                float(self.active_deterring_sum / float(self.frame_count)) if self.frame_count > 0 else float("nan")
            ),
            "mean_active_patrolling": (
                float(self.active_patrolling_sum / float(self.frame_count)) if self.frame_count > 0 else float("nan")
            ),
            "max_active_tasks": int(self.max_active_tasks),
            "final_active_tasks": int(self.final_active_tasks),
            "robot_moving_fraction": (
                float(self.moving_robot_frames) / float(self.robot_frame_observations)
                if self.robot_frame_observations > 0 else float("nan")
            ),
        }
        summary.update(self.native_metrics)
        return summary


def summarize_benchmark(
    per_run_df: pd.DataFrame,
    *,
    current_label: str = CURRENT_LABEL,
    main_label: str = MAIN_LABEL,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for spec in COMMON_METRICS:
        current_values = per_run_df.loc[per_run_df["system"] == current_label, spec.column]
        main_values = per_run_df.loc[per_run_df["system"] == main_label, spec.column]
        cur_stats = _ci95(current_values)
        main_stats = _ci95(main_values)
        paired = (
            per_run_df.loc[per_run_df["system"] == current_label, ["seed", spec.column]]
            .merge(
                per_run_df.loc[per_run_df["system"] == main_label, ["seed", spec.column]],
                on="seed",
                suffixes=("_current", "_main"),
                how="inner",
            )
        )
        if not paired.empty:
            cur_col = f"{spec.column}_current"
            main_col = f"{spec.column}_main"
            if spec.goal == "higher":
                paired_adv = 100.0 * (paired[cur_col] - paired[main_col]) / paired[main_col].replace(0.0, np.nan)
            else:
                paired_adv = 100.0 * (paired[main_col] - paired[cur_col]) / paired[main_col].replace(0.0, np.nan)
            adv_stats = _ci95(paired_adv)
        else:
            adv_stats = (float("nan"), float("nan"), float("nan"), 0)
        if np.isfinite(cur_stats[0]) and np.isfinite(main_stats[0]) and math.isclose(cur_stats[0], main_stats[0], rel_tol=1e-12, abs_tol=1e-12):
            winner = "tie"
        elif spec.goal == "higher":
            winner = current_label if cur_stats[0] > main_stats[0] else main_label
        elif spec.goal == "lower":
            winner = current_label if cur_stats[0] < main_stats[0] else main_label
        else:
            winner = ""
        rows.append(
            {
                "metric": spec.column,
                "label": spec.label,
                "goal": spec.goal,
                f"{current_label}_mean": cur_stats[0],
                f"{current_label}_ci_lo": cur_stats[1],
                f"{current_label}_ci_hi": cur_stats[2],
                f"{current_label}_n": cur_stats[3],
                f"{main_label}_mean": main_stats[0],
                f"{main_label}_ci_lo": main_stats[1],
                f"{main_label}_ci_hi": main_stats[2],
                f"{main_label}_n": main_stats[3],
                "mean_difference_current_minus_main": (
                    cur_stats[0] - main_stats[0] if np.isfinite(cur_stats[0]) and np.isfinite(main_stats[0]) else float("nan")
                ),
                "current_advantage_pct_mean": adv_stats[0],
                "current_advantage_pct_ci_lo": adv_stats[1],
                "current_advantage_pct_ci_hi": adv_stats[2],
                "paired_seed_count": adv_stats[3],
                "winner": winner,
            }
        )
    return pd.DataFrame(rows)


def _plot_summary(summary_df: pd.DataFrame, out_png: Path, *, current_label: str, main_label: str) -> None:
    fig, axes = plt.subplots(2, 4, figsize=(18, 8))
    colors = {current_label: "#1f77b4", main_label: "#ff7f0e"}
    for ax, spec in zip(axes.flat, COMMON_METRICS):
        row = summary_df.loc[summary_df["metric"] == spec.column].iloc[0]
        means = np.array([row[f"{current_label}_mean"], row[f"{main_label}_mean"]], dtype=float)
        lows = np.array([row[f"{current_label}_ci_lo"], row[f"{main_label}_ci_lo"]], dtype=float)
        highs = np.array([row[f"{current_label}_ci_hi"], row[f"{main_label}_ci_hi"]], dtype=float)
        errs = np.vstack([means - lows, highs - means])
        x = np.arange(2)
        ax.bar(x, means, color=[colors[current_label], colors[main_label]], alpha=0.9)
        ax.errorbar(x, means, yerr=errs, fmt="none", ecolor="black", capsize=4, linewidth=1.0)
        ax.set_xticks(x)
        ax.set_xticklabels([current_label, main_label])
        ax.set_title(f"{spec.label}\n({spec.goal} better)")
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _plot_trajectories(timeseries_df: pd.DataFrame, out_png: Path) -> None:
    grouped = (
        timeseries_df.groupby(["system", "t"], as_index=False)[
            ["completed_tasks_total", "completed_deterring_total", "active_tasks", "cumulative_distance_m"]
        ]
        .mean()
        .sort_values(["system", "t"])
    )
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    plot_specs = [
        ("completed_tasks_total", "Completed Tasks"),
        ("completed_deterring_total", "Completed Deterring"),
        ("active_tasks", "Active Backlog"),
        ("cumulative_distance_m", "Cumulative Distance (m)"),
    ]
    for ax, (column, title) in zip(axes.flat, plot_specs):
        for system_name, sub in grouped.groupby("system"):
            ax.plot(sub["t"], sub[column], label=system_name, linewidth=1.6)
        ax.set_title(title)
        ax.grid(alpha=0.25)
    axes[0, 0].legend(frameon=False)
    for ax in axes[1]:
        ax.set_xlabel("Simulation Time (s)")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _dataframe_to_markdown(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def _git_capture(repo: Path, *args: str) -> str:
    cmd = ["git", "-c", f"safe.directory={repo.resolve()}", "-C", str(repo.resolve()), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _repo_descriptor(repo: Path) -> dict[str, Any]:
    return {
        "path": str(repo.resolve()),
        "branch": _git_capture(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "commit": _git_capture(repo, "rev-parse", "HEAD"),
        "dirty": bool(_git_capture(repo, "status", "--short")),
    }


def _write_report(
    out_path: Path,
    *,
    summary_df: pd.DataFrame,
    current_repo: Path,
    main_repo: Path,
    benchmark_params: dict[str, Any],
    current_label: str,
    main_label: str,
) -> None:
    view = summary_df[
        [
            "label",
            f"{current_label}_mean",
            f"{current_label}_ci_lo",
            f"{current_label}_ci_hi",
            f"{main_label}_mean",
            f"{main_label}_ci_lo",
            f"{main_label}_ci_hi",
            "current_advantage_pct_mean",
            "current_advantage_pct_ci_lo",
            "current_advantage_pct_ci_hi",
            "winner",
        ]
    ].copy()
    view[f"{current_label}_summary"] = [
        _format_ci(mean, lo, hi)
        for mean, lo, hi in zip(view[f"{current_label}_mean"], view[f"{current_label}_ci_lo"], view[f"{current_label}_ci_hi"])
    ]
    view[f"{main_label}_summary"] = [
        _format_ci(mean, lo, hi)
        for mean, lo, hi in zip(view[f"{main_label}_mean"], view[f"{main_label}_ci_lo"], view[f"{main_label}_ci_hi"])
    ]
    view["current_advantage_pct"] = [
        _format_ci(mean, lo, hi)
        for mean, lo, hi in zip(
            view["current_advantage_pct_mean"],
            view["current_advantage_pct_ci_lo"],
            view["current_advantage_pct_ci_hi"],
        )
    ]
    view = view[["label", f"{current_label}_summary", f"{main_label}_summary", "current_advantage_pct", "winner"]]
    view = view.rename(
        columns={
            "label": "Metric",
            f"{current_label}_summary": current_label,
            f"{main_label}_summary": main_label,
            "current_advantage_pct": f"{current_label} Advantage %",
            "winner": "Winner",
        }
    )

    current_desc = _repo_descriptor(current_repo)
    main_desc = _repo_descriptor(main_repo)
    lines = [
        "# Current vs Main Benchmark",
        "",
        "## Repositories",
        "",
        f"- `{current_label}`: `{current_desc['path']}`",
        f"- branch: `{current_desc['branch'] or 'unknown'}`",
        f"- commit: `{current_desc['commit'] or 'unknown'}`",
        f"- dirty: `{current_desc['dirty']}`",
        f"- `{main_label}`: `{main_desc['path']}`",
        f"- branch: `{main_desc['branch'] or 'unknown'}`",
        f"- commit: `{main_desc['commit'] or 'unknown'}`",
        f"- dirty: `{main_desc['dirty']}`",
        "",
        "## Benchmark Parameters",
        "",
    ]
    for key in sorted(benchmark_params.keys()):
        lines.append(f"- `{key}`: `{benchmark_params[key]}`")
    lines.extend(
        [
            "",
            "## Summary",
            "",
            _dataframe_to_markdown(view),
            "",
            "Positive advantage means the current workspace outperformed main after accounting for metric direction.",
            "",
            "## Artifacts",
            "",
            "- `per_run_metrics.csv`: one row per system per seed",
            "- `summary_by_metric.csv`: aggregate metrics with CI95 and paired seed deltas",
            "- `per_run_timeseries.csv`: sampled trajectory metrics",
            "- `summary_compare.png`: bar chart of aggregate outcomes",
            "- `trajectory_compare.png`: mean trajectories over time when timeseries are available",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_worker_subprocess(
    *,
    system_label: str,
    repo: Path,
    seed: int,
    params: dict[str, Any],
    out_json: Path,
    out_csv: Path,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--worker-label",
        system_label,
        "--worker-repo",
        str(repo.resolve()),
        "--worker-seed",
        str(seed),
        "--worker-params-json",
        json.dumps(params),
        "--worker-out-json",
        str(out_json.resolve()),
        "--worker-out-csv",
        str(out_csv.resolve()),
    ]
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    proc = subprocess.run(cmd, cwd=str(repo.resolve()), capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Worker failed for {system_label} seed={seed}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    return payload["summary"]


def run_worker(args: argparse.Namespace) -> int:
    repo = Path(args.worker_repo).resolve()
    script_dir = Path(__file__).resolve().parent
    filtered_sys_path: list[str] = []
    for entry in sys.path:
        try:
            if entry and Path(entry).resolve() == script_dir:
                continue
        except Exception:
            pass
        filtered_sys_path.append(entry)
    sys.path = [str(repo)] + filtered_sys_path
    os.chdir(repo)

    spec = importlib.util.spec_from_file_location("benchmark_target_deterrent_system", repo / "DeterrentSystem.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load DeterrentSystem.py from {repo}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_target_deterrent_system"] = module
    spec.loader.exec_module(module)

    mon = getattr(module, "mon", None)
    if mon is not None and hasattr(mon, "enabled"):
        mon.enabled = False

    params = json.loads(args.worker_params_json)
    params["seed"] = int(args.worker_seed)
    sample_every_s = _safe_float(params.pop("sample_every_s", 60.0), 60.0)

    runner = getattr(module, "run_simulation_frames_persistent")
    call_kwargs = _filter_supported_kwargs(runner, params)
    sig = inspect.signature(runner).parameters
    if "report_metrics_end" in sig:
        call_kwargs.setdefault("report_metrics_end", False)
    if "telemetry_clear_on_start" in sig:
        call_kwargs.setdefault("telemetry_clear_on_start", False)
    if "telemetry_prompt_save" in sig:
        call_kwargs.setdefault("telemetry_prompt_save", False)
    if "simulation_mode" in sig:
        call_kwargs.setdefault("simulation_mode", "proposed")
    if "telemetry_dir" in sig:
        call_kwargs.setdefault("telemetry_dir", f"telemetry_benchmark_{args.worker_label}_{args.worker_seed}")

    collector = BenchmarkCollector(sample_every_s=sample_every_s)
    for frame in runner(**call_kwargs):
        collector.consume(frame)

    summary = collector.finalize()
    summary["system"] = str(args.worker_label)
    summary["seed"] = int(args.worker_seed)
    summary["repo"] = str(repo)
    summary["supported_call_kwargs"] = call_kwargs
    summary["sample_every_s"] = sample_every_s

    out_json = Path(args.worker_out_json)
    out_csv = Path(args.worker_out_csv)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"summary": summary}, indent=2), encoding="utf-8")
    pd.DataFrame(collector.sample_rows).assign(
        system=str(args.worker_label),
        seed=int(args.worker_seed),
    ).to_csv(out_csv, index=False)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the current workspace against the main worktree.")
    parser.add_argument("--current-repo", default=str(Path.cwd()), help="Path to the current workspace.")
    parser.add_argument("--main-repo", default=str(Path.cwd().parent / f"{Path.cwd().name}-main"), help="Path to the main worktree.")
    parser.add_argument("--outdir", default="results/current_vs_main_benchmark", help="Benchmark output directory.")
    parser.add_argument("--num-runs", type=int, default=5, help="Seeds to run per system.")
    parser.add_argument("--seed-start", type=int, default=1000, help="First seed value.")
    parser.add_argument("--duration-s", type=float, default=3600.0, help="Simulation horizon in seconds.")
    parser.add_argument("--dt", type=float, default=5.0, help="Simulation step size.")
    parser.add_argument("--fps", type=int, default=1, help="Frame cadence parameter passed to the simulation.")
    parser.add_argument("--W", type=float, default=500.0, help="Field width.")
    parser.add_argument("--H", type=float, default=500.0, help="Field height.")
    parser.add_argument("--NX", type=int, default=80, help="Grid width.")
    parser.add_argument("--NY", type=int, default=64, help="Grid height.")
    parser.add_argument("--Nrobots", type=int, default=6, help="Robot count when supported.")
    parser.add_argument("--uav-fraction", type=float, default=0.0, help="UAV fraction when supported.")
    parser.add_argument("--task-replan-period-s", type=float, default=45.0, help="Replan cadence.")
    parser.add_argument("--arrival-radius-m", type=float, default=3.0, help="Task arrival radius.")
    parser.add_argument("--hold-time-s", type=float, default=20.0, help="Deterring hold time.")
    parser.add_argument("--sample-every-s", type=float, default=60.0, help="Timeseries sample cadence.")
    parser.add_argument("--current-simulation-mode", default="proposed", help="Simulation mode for the current repo when supported.")
    parser.add_argument("--max-workers", type=int, default=1, help="Concurrent worker processes.")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-label", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-repo", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--worker-params-json", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-out-json", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-out-csv", default="", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.worker:
        return run_worker(args)

    current_repo = Path(args.current_repo).resolve()
    main_repo = Path(args.main_repo).resolve()
    if not current_repo.exists():
        raise FileNotFoundError(f"Current repo does not exist: {current_repo}")
    if not main_repo.exists():
        raise FileNotFoundError(f"Main repo does not exist: {main_repo}")

    outdir = Path(args.outdir)
    raw_dir = outdir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    shared_params = {
        "W": float(args.W),
        "H": float(args.H),
        "T_end": float(args.duration_s),
        "dt": float(args.dt),
        "fps": int(args.fps),
        "NX": int(args.NX),
        "NY": int(args.NY),
        "Nrobots": int(args.Nrobots),
        "uav_fraction": float(args.uav_fraction),
        "task_replan_period_s": float(args.task_replan_period_s),
        "arrival_radius_m": float(args.arrival_radius_m),
        "hold_time_s": float(args.hold_time_s),
        "sample_every_s": float(args.sample_every_s),
    }
    current_params = dict(shared_params)
    current_params["simulation_mode"] = str(args.current_simulation_mode)
    main_params = dict(shared_params)

    jobs: list[dict[str, Any]] = []
    for offset in range(int(args.num_runs)):
        seed = int(args.seed_start) + offset
        jobs.append(
            {
                "system_label": CURRENT_LABEL,
                "repo": current_repo,
                "seed": seed,
                "params": current_params,
                "out_json": raw_dir / CURRENT_LABEL / f"seed_{seed}.json",
                "out_csv": raw_dir / CURRENT_LABEL / f"seed_{seed}.csv",
            }
        )
        jobs.append(
            {
                "system_label": MAIN_LABEL,
                "repo": main_repo,
                "seed": seed,
                "params": main_params,
                "out_json": raw_dir / MAIN_LABEL / f"seed_{seed}.json",
                "out_csv": raw_dir / MAIN_LABEL / f"seed_{seed}.csv",
            }
        )

    summaries: list[dict[str, Any]] = []
    max_workers = max(1, int(args.max_workers))
    if max_workers == 1:
        for job in jobs:
            print(f"[benchmark] running {job['system_label']} seed={job['seed']}")
            summaries.append(_run_worker_subprocess(**job))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_run_worker_subprocess, **job): job for job in jobs}
            for future in as_completed(future_map):
                job = future_map[future]
                print(f"[benchmark] completed {job['system_label']} seed={job['seed']}")
                summaries.append(future.result())

    per_run_df = pd.DataFrame(summaries).sort_values(["system", "seed"]).reset_index(drop=True)
    if per_run_df.empty:
        raise RuntimeError("Benchmark produced no run summaries.")
    per_run_csv = outdir / "per_run_metrics.csv"
    per_run_df.to_csv(per_run_csv, index=False)

    timeseries_parts = []
    for job in jobs:
        csv_path = Path(job["out_csv"])
        if csv_path.exists():
            timeseries_parts.append(pd.read_csv(csv_path))
    timeseries_df = pd.concat(timeseries_parts, ignore_index=True) if timeseries_parts else pd.DataFrame()
    if not timeseries_df.empty:
        timeseries_df.to_csv(outdir / "per_run_timeseries.csv", index=False)

    summary_df = summarize_benchmark(per_run_df, current_label=CURRENT_LABEL, main_label=MAIN_LABEL)
    summary_csv = outdir / "summary_by_metric.csv"
    summary_df.to_csv(summary_csv, index=False)
    _plot_summary(summary_df, outdir / "summary_compare.png", current_label=CURRENT_LABEL, main_label=MAIN_LABEL)
    if not timeseries_df.empty:
        _plot_trajectories(timeseries_df, outdir / "trajectory_compare.png")

    manifest = {
        "current_repo": _repo_descriptor(current_repo),
        "main_repo": _repo_descriptor(main_repo),
        "benchmark_params": {
            "num_runs": int(args.num_runs),
            "seed_start": int(args.seed_start),
            **shared_params,
            "current_simulation_mode": str(args.current_simulation_mode),
        },
    }
    (outdir / "benchmark_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_report(
        outdir / "report.md",
        summary_df=summary_df,
        current_repo=current_repo,
        main_repo=main_repo,
        benchmark_params=manifest["benchmark_params"],
        current_label=CURRENT_LABEL,
        main_label=MAIN_LABEL,
    )

    print("[benchmark] outputs written to:")
    print(f"- {outdir}")
    print(f"- {per_run_csv.name}")
    print(f"- {summary_csv.name}")
    print("- report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
