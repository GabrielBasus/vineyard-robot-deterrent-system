from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import DeterrentSystem as ds_frozen
import DeterrentSystem_simple_tasks as ds_simple


@dataclass
class BaselineSpec:
    name: str
    module_name: str
    simulation_mode: str
    use_simple_tasks: bool = False


def _task_source(tr: dict) -> str:
    ttype = str(tr.get("type", "")).strip().lower()
    if ttype != "deterring":
        return "-"
    mode = tr.get("mode")
    if mode not in (None, "", "none"):
        return "model_scored"
    origin = str(tr.get("origin", "")).strip().lower()
    return "direct_detection" if origin in ("", "detection") else "model_scored"


def _count_tasks(tasks: List[dict]) -> Dict[str, int]:
    out = {
        "deterring_total": 0,
        "patrolling_total": 0,
        "deterring_model_scored": 0,
        "deterring_direct_detection": 0,
    }
    for tr in tasks:
        ttype = str(tr.get("type", "")).strip().lower()
        if ttype == "deterring":
            out["deterring_total"] += 1
            src = _task_source(tr)
            if src == "model_scored":
                out["deterring_model_scored"] += 1
            else:
                out["deterring_direct_detection"] += 1
        elif ttype == "patrolling":
            out["patrolling_total"] += 1
    return out


def _module_for(spec: BaselineSpec):
    return ds_simple if spec.module_name == "simple" else ds_frozen


def _run_collect(spec: BaselineSpec, run_params: dict, sample_every_s: float):
    mod = _module_for(spec)
    kwargs = dict(run_params)
    kwargs["simulation_mode"] = spec.simulation_mode
    if spec.use_simple_tasks:
        kwargs["simple_task_management"] = True

    frames = mod.run_simulation_frames_persistent(**kwargs)
    rows = []
    pose_hist: Dict[str, List[Tuple[float, float, float]]] = {}
    first = None
    last = None
    next_sample_t = -1e18

    for snap in frames:
        if first is None:
            first = snap
        last = snap
        t = float(snap.get("t", 0.0))
        for rid, (x, y) in snap.get("poses", {}).items():
            pose_hist.setdefault(str(rid), []).append((t, float(x), float(y)))

        if t < next_sample_t:
            continue
        next_sample_t = t + float(sample_every_s)

        m = snap.get("metrics", {})
        model_diag = snap.get("model_diag", {})
        lam_means = [v.get("lam_mean", np.nan) for v in model_diag.values()]
        trig_sums = [v.get("trigger_sum", np.nan) for v in model_diag.values()]
        inhib_sums = [v.get("inhib_sum", np.nan) for v in model_diag.values()]

        active_c = _count_tasks(list(snap.get("tasks_active", [])))
        done_c = _count_tasks(list(snap.get("tasks_done", [])))

        rows.append(
            {
                "baseline": spec.name,
                "t": t,
                "value_weighted_exposure": float(m.get("value_weighted_exposure", np.nan)),
                "mean_response_time_s": float(m.get("mean_response_time_s", np.nan)),
                "tasks_per_unit_distance": float(m.get("tasks_per_unit_distance", np.nan)),
                "boundary_message_count": float(m.get("boundary_message_count", np.nan)),
                "forecast_recall_at_k": float(m.get("forecast_recall_at_k", np.nan)),
                "forecast_precision_at_k": float(m.get("forecast_precision_at_k", np.nan)),
                "fleet_task_engagement_fraction_so_far": float(m.get("fleet_task_engagement_fraction_so_far", np.nan)),
                "fleet_idle_no_task_fraction_so_far": float(m.get("fleet_idle_no_task_fraction_so_far", np.nan)),
                "stale_goal_clears": float(m.get("stale_goal_clears", np.nan)),
                "truth_suppression_rate": float(m.get("truth_suppression_rate", np.nan)),
                "active_deterring": int(active_c["deterring_total"]),
                "active_patrolling": int(active_c["patrolling_total"]),
                "active_deterring_model_scored": int(active_c["deterring_model_scored"]),
                "done_deterring": int(done_c["deterring_total"]),
                "done_patrolling": int(done_c["patrolling_total"]),
                "done_deterring_model_scored": int(done_c["deterring_model_scored"]),
                "done_deterring_direct_detection": int(done_c["deterring_direct_detection"]),
                "model_deterring_candidates_total": float(m.get("model_deterring_candidates_total", np.nan)),
                "model_deterring_rejected_risk": float(m.get("model_deterring_rejected_risk", np.nan)),
                "model_deterring_rejected_support": float(m.get("model_deterring_rejected_support", np.nan)),
                "model_deterring_rejected_persistence": float(m.get("model_deterring_rejected_persistence", np.nan)),
                "model_deterring_accepted": float(m.get("model_deterring_accepted", np.nan)),
                "model_deterring_generated": float(m.get("model_deterring_generated", np.nan)),
                "model_deterring_rejected_budget": float(m.get("model_deterring_rejected_budget", np.nan)),
                "planner_rejected_task_cap": float(m.get("planner_rejected_task_cap", np.nan)),
                "planner_rejected_patrol_cap": float(m.get("planner_rejected_patrol_cap", np.nan)),
                "planner_rejected_model_det_cap": float(m.get("planner_rejected_model_det_cap", np.nan)),
                "planner_replaced_patrol": float(m.get("planner_replaced_patrol", np.nan)),
                "lam_mean_avg": float(np.nanmean(lam_means)) if lam_means else np.nan,
                "trigger_sum_total": float(np.nansum(trig_sums)) if trig_sums else np.nan,
                "inhib_sum_total": float(np.nansum(inhib_sums)) if inhib_sums else np.nan,
            }
        )

    return pd.DataFrame(rows), first, last, pose_hist


def _draw_rows(ax, W: float, H: float, params: dict):
    row_spacing_m = float(params.get("row_spacing_m", 4.8))
    row_width_m = float(params.get("row_width_m", 3.2))
    headland_space_m = float(params.get("headland_space_m", 10.0))
    if row_spacing_m <= 0.0 or row_width_m <= 0.0:
        return
    k = 0
    while True:
        y = headland_space_m + k * row_spacing_m
        if y - 0.5 * row_width_m > (H - headland_space_m):
            break
        y0 = y - 0.5 * row_width_m
        y1 = y + 0.5 * row_width_m
        ax.fill(
            [headland_space_m, W - headland_space_m, W - headland_space_m, headland_space_m],
            [y0, y0, y1, y1],
            color="#5f6f47",
            alpha=0.22,
            zorder=0,
            linewidth=0,
        )
        k += 1


def _plot_zone_partition_and_paths(last_by_name: dict, first_by_name: dict, pose_hist_by_name: dict, params: dict, out_png: Path):
    names = list(last_by_name.keys())
    fig, axes = plt.subplots(2, 2, figsize=(15, 11), sharex=True, sharey=True)
    axes = axes.ravel()
    for idx, name in enumerate(names):
        ax = axes[idx]
        snap = last_by_name[name]
        first = first_by_name[name]
        W = float(snap["W"])
        H = float(snap["H"])
        ax.set_title(name)
        ax.set_xlim(0.0, W)
        ax.set_ylim(0.0, H)
        ax.set_aspect("equal", adjustable="box")

        bx, by = zip(*(snap["boundary"] + [snap["boundary"][0]]))
        ax.plot(bx, by, "k-", lw=1.1, zorder=1)
        _draw_rows(ax, W, H, params)

        for cell in snap.get("cells", []):
            if not cell:
                continue
            xs = [p[0] for p in cell] + [cell[0][0]]
            ys = [p[1] for p in cell] + [cell[0][1]]
            ax.plot(xs, ys, "-", color="#3b4c66", lw=0.9, alpha=0.9, zorder=2)

        for rid, hist in pose_hist_by_name[name].items():
            if not hist:
                continue
            xs = [h[1] for h in hist]
            ys = [h[2] for h in hist]
            ax.plot(xs, ys, lw=0.7, alpha=0.5, zorder=3)

        p0x = [v[0] for v in first.get("poses", {}).values()]
        p0y = [v[1] for v in first.get("poses", {}).values()]
        ax.scatter(p0x, p0y, c="#9e9e9e", s=16, marker="s", zorder=4, label="start")

        px = [v[0] for v in snap.get("poses", {}).values()]
        py = [v[1] for v in snap.get("poses", {}).values()]
        ax.scatter(px, py, c="black", s=22, zorder=5, label="robots")

        tp = snap.get("truth_pts", [])
        dp = snap.get("det_pts", [])
        if tp:
            ax.scatter([p[0] for p in tp], [p[1] for p in tp], c="#2ca02c", marker="x", s=26, alpha=0.7, zorder=4)
        if dp:
            ax.scatter([p[0] for p in dp], [p[1] for p in dp], c="#d62728", marker="x", s=26, alpha=0.7, zorder=4)

        active = list(snap.get("tasks_active", []))
        det = [tr for tr in active if str(tr.get("type", "")).strip().lower() == "deterring"]
        pat = [tr for tr in active if str(tr.get("type", "")).strip().lower() == "patrolling"]
        if det:
            ax.scatter([tr["x"] for tr in det], [tr["y"] for tr in det], c="#ff7f0e", s=22, zorder=6)
        if pat:
            ax.scatter([tr["x"] for tr in pat], [tr["y"] for tr in pat], c="#1f77b4", marker="D", s=20, zorder=6)

        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")

    fig.suptitle("Zone Partitioning + Robot Paths + Tasks (4-system comparison)")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_model_internals(ts: pd.DataFrame, out_png: Path):
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    fields = [
        ("lam_mean_avg", "Mean lambda (avg robots)"),
        ("trigger_sum_total", "Trigger mass sum"),
        ("inhib_sum_total", "Inhibition mass sum"),
        ("truth_suppression_rate", "Truth suppression rate"),
    ]
    for ax, (col, title) in zip(axes.ravel(), fields):
        for name, g in ts.groupby("baseline"):
            ax.plot(g["t"], g[col], lw=1.6, label=name)
        ax.set_title(title)
        ax.grid(alpha=0.25)
        ax.set_xlabel("time (s)")
    axes[0, 0].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_task_funnel(ts: pd.DataFrame, out_png: Path):
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    fields = [
        ("model_deterring_candidates_total", "Candidates total"),
        ("model_deterring_rejected_risk", "Rejected by risk"),
        ("model_deterring_accepted", "Accepted (post planner)"),
        ("done_deterring_model_scored", "Completed model-scored deterring"),
    ]
    for ax, (col, title) in zip(axes.ravel(), fields):
        for name, g in ts.groupby("baseline"):
            ax.plot(g["t"], g[col], lw=1.6, label=name)
        ax.set_title(title)
        ax.grid(alpha=0.25)
        ax.set_xlabel("time (s)")
    axes[0, 0].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_dispatch_diagnostics(ts: pd.DataFrame, out_png: Path):
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    fields = [
        ("fleet_task_engagement_fraction_so_far", "Fleet task engagement"),
        ("fleet_idle_no_task_fraction_so_far", "Fleet idle no-task fraction"),
        ("stale_goal_clears", "Stale goal clears"),
        ("planner_rejected_task_cap", "Planner rejected (task cap)"),
    ]
    for ax, (col, title) in zip(axes.ravel(), fields):
        for name, g in ts.groupby("baseline"):
            ax.plot(g["t"], g[col], lw=1.6, label=name)
        ax.set_title(title)
        ax.grid(alpha=0.25)
        ax.set_xlabel("time (s)")
    axes[0, 0].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_performance(ts: pd.DataFrame, final_df: pd.DataFrame, out_png: Path):
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    for name, g in ts.groupby("baseline"):
        axes[0, 0].plot(g["t"], g["value_weighted_exposure"], lw=1.6, label=name)
        axes[0, 1].plot(g["t"], g["mean_response_time_s"], lw=1.6, label=name)

    axes[0, 0].set_title("Exposure over time")
    axes[0, 1].set_title("Mean response time over time")
    axes[0, 0].grid(alpha=0.25)
    axes[0, 1].grid(alpha=0.25)
    axes[0, 0].set_xlabel("time (s)")
    axes[0, 1].set_xlabel("time (s)")

    bar_metrics = [
        "value_weighted_exposure",
        "mean_response_time_s",
        "boundary_message_count",
        "fleet_task_engagement_fraction_so_far",
    ]
    x = np.arange(len(final_df))
    for j, col in enumerate(bar_metrics):
        ax = axes[1, 0] if j < 2 else axes[1, 1]
        if j % 2 == 0:
            ax.cla()
        vals = final_df[col].to_numpy(dtype=float)
        ax.bar(x + (0.35 * (j % 2)), vals, width=0.35, label=col)
        ax.set_xticks(x + 0.175)
        ax.set_xticklabels(final_df["baseline"], rotation=20, ha="right")
        ax.grid(axis="y", alpha=0.25)
        if j % 2 == 1:
            ax.legend(loc="best", fontsize=8)

    axes[1, 0].set_title("Final metrics: exposure/response")
    axes[1, 1].set_title("Final metrics: communication/engagement")

    axes[0, 0].legend(loc="best", fontsize=8)
    axes[0, 1].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _plot_delta_vs_prediction(ts: pd.DataFrame, out_png: Path):
    """Plot over-time deltas against prediction_only baseline."""
    if ts.empty or "baseline" not in ts.columns or "t" not in ts.columns:
        return

    compare_baselines = [b for b in ["reactive", "proposed", "proposed_simple_tasks"] if b in set(ts["baseline"].unique())]
    if not compare_baselines or "prediction_only" not in set(ts["baseline"].unique()):
        return

    def _delta_pct(metric: str, baseline: str, higher_is_better: bool = True):
        piv = ts.pivot_table(index="t", columns="baseline", values=metric, aggfunc="last")
        if ("prediction_only" not in piv.columns) or (baseline not in piv.columns):
            return None, None
        pred = piv["prediction_only"].replace(0.0, np.nan)
        base = piv[baseline]
        if higher_is_better:
            y = 100.0 * (pred - base) / pred
        else:
            y = 100.0 * (base - pred) / pred
        return piv.index.to_numpy(dtype=float), y.to_numpy(dtype=float)

    def _delta_abs(metric: str, baseline: str):
        piv = ts.pivot_table(index="t", columns="baseline", values=metric, aggfunc="last")
        if ("prediction_only" not in piv.columns) or (baseline not in piv.columns):
            return None, None
        y = piv[baseline] - piv["prediction_only"]
        return piv.index.to_numpy(dtype=float), y.to_numpy(dtype=float)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    cmap = {
        "reactive": "#7f7f7f",
        "proposed": "#1f77b4",
        "proposed_simple_tasks": "#d62728",
    }

    for b in compare_baselines:
        c = cmap.get(b, None)
        x, y = _delta_pct("value_weighted_exposure", b, higher_is_better=True)
        if x is not None:
            axes[0, 0].plot(x, y, lw=1.8, label=b, color=c)
        x, y = _delta_pct("mean_response_time_s", b, higher_is_better=True)
        if x is not None:
            axes[0, 1].plot(x, y, lw=1.8, label=b, color=c)
        x, y = _delta_pct("boundary_message_count", b, higher_is_better=False)
        if x is not None:
            axes[1, 0].plot(x, y, lw=1.8, label=b, color=c)
        x, y = _delta_abs("done_deterring_model_scored", b)
        if x is not None:
            axes[1, 1].plot(x, y, lw=1.8, label=b, color=c)

    axes[0, 0].axhline(0.0, color="k", ls="--", lw=1.0)
    axes[0, 1].axhline(0.0, color="k", ls="--", lw=1.0)
    axes[1, 0].axhline(0.0, color="k", ls="--", lw=1.0)
    axes[1, 0].axhline(30.0, color="red", ls=":", lw=1.1)
    axes[1, 1].axhline(0.0, color="k", ls="--", lw=1.0)

    axes[0, 0].set_title("Exposure improvement vs prediction_only [%]")
    axes[0, 1].set_title("Response improvement vs prediction_only [%]")
    axes[1, 0].set_title("Communication increase vs prediction_only [%]")
    axes[1, 1].set_title("Model-scored completions gain vs prediction_only")

    for ax in axes.ravel():
        ax.grid(alpha=0.25)
        ax.set_xlabel("time (s)")
    axes[0, 0].legend(loc="best", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def _zone_stats(snap: dict) -> pd.DataFrame:
    cells = list(snap.get("cells", []))
    W = float(snap.get("W", np.nan))
    H = float(snap.get("H", np.nan))
    total = W * H if np.isfinite(W) and np.isfinite(H) else np.nan
    rows = []
    for i, cell in enumerate(cells):
        if not cell:
            area = 0.0
        else:
            x = np.array([p[0] for p in cell], dtype=float)
            y = np.array([p[1] for p in cell], dtype=float)
            area = 0.5 * float(np.abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
        frac = area / total if np.isfinite(total) and total > 0 else np.nan
        rows.append({"zone_idx": i, "area_m2": area, "area_frac": frac})
    return pd.DataFrame(rows)


def _write_params_outputs(outdir: Path, run_params: dict, baseline_specs: List[BaselineSpec]):
    params_json = {
        "run_parameters": run_params,
        "baselines": [
            {
                "name": b.name,
                "module": b.module_name,
                "simulation_mode": b.simulation_mode,
                "simple_task_management": b.use_simple_tasks,
            }
            for b in baseline_specs
        ],
    }
    (outdir / "params.json").write_text(json.dumps(params_json, indent=2), encoding="utf-8")

    groups = {
        "geometry_motion": ["W", "H", "Nrobots", "uav_fraction", "row_spacing_m", "row_width_m", "headland_space_m", "headland_m"],
        "sestpp_model": ["NX", "NY", "sigma", "omega", "mu_base", "bg_ema", "warmup_s"],
        "truth_generation": ["mu_true", "alpha_true", "omega_true", "sigma_true", "beta_true", "detect_range_m"],
        "task_generation_gating": [
            "task_replan_period_s", "task_max_age_s", "task_refresh_min_score", "model_deterring_window_s",
            "model_deterring_risk_threshold", "model_deterring_risk_scale", "model_deterring_min_recent_points",
            "model_deterring_min_persistence_replans", "model_deterring_score_margin", "model_deterring_budget_per_robot_per_hr",
        ],
        "dispatch": [
            "max_active_tasks_per_robot", "max_active_patrolling_per_robot", "max_active_model_deterring_per_robot",
            "preempt_deterring_goals", "preempt_direct_detection_goals", "preempt_model_scored_goals", "assigner_w_load",
        ],
    }
    rows = []
    for grp, keys in groups.items():
        for k in keys:
            rows.append({"group": grp, "parameter": k, "value": run_params.get(k, "<default>")})
    pd.DataFrame(rows).to_csv(outdir / "params_table.csv", index=False)


def main():
    parser = argparse.ArgumentParser(description="Component diagnostics with simple-task ablation")
    parser.add_argument("--T-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--sample-every-s", type=float, default=30.0)
    parser.add_argument("--outdir", type=str, default="results/diagnostic_components_simple")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if getattr(ds_frozen, "mon", None) is not None:
        ds_frozen.mon.enabled = False
    if getattr(ds_simple, "mon", None) is not None:
        ds_simple.mon.enabled = False

    run_params = {
        "T_end": float(args.T_end),
        "dt": float(args.dt),
        "seed": int(args.seed),
        "W": 500.0,
        "H": 500.0,
        "NX": 80,
        "NY": 64,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "warmup_s": 1800.0,
        "task_replan_period_s": 45.0,
        "task_max_age_s": 120.0,
        "model_deterring_window_s": 90.0,
        "model_deterring_risk_threshold": 0.35,
        "model_deterring_budget_per_robot_per_hr": 4,
        "model_deterring_min_recent_points": 1,
        "forecast_horizon_s": 300.0,
        "forecast_match_radius_m": 20.0,
        "forecast_top_k": 5,
        "forecast_eval_period_s": 30.0,
        "telemetry_clear_on_start": False,
        "telemetry_prompt_save": False,
    }

    baseline_specs = [
        BaselineSpec(name="reactive", module_name="frozen", simulation_mode="reactive", use_simple_tasks=False),
        BaselineSpec(name="prediction_only", module_name="frozen", simulation_mode="prediction_only", use_simple_tasks=False),
        BaselineSpec(name="proposed", module_name="frozen", simulation_mode="proposed", use_simple_tasks=False),
        BaselineSpec(name="proposed_simple_tasks", module_name="simple", simulation_mode="proposed", use_simple_tasks=True),
    ]

    _write_params_outputs(outdir, run_params, baseline_specs)

    ts_all = []
    last_by_name = {}
    first_by_name = {}
    pose_hist_by_name = {}
    final_rows = []

    for spec in baseline_specs:
        print(f"[run] {spec.name}")
        ts, first_snap, last_snap, pose_hist = _run_collect(spec, run_params, sample_every_s=float(args.sample_every_s))
        ts.to_csv(outdir / f"timeseries_{spec.name}.csv", index=False)
        ts_all.append(ts)
        last_by_name[spec.name] = last_snap
        first_by_name[spec.name] = first_snap
        pose_hist_by_name[spec.name] = pose_hist
        if last_snap is not None:
            m = last_snap.get("metrics", {})
            final_rows.append(
                {
                    "baseline": spec.name,
                    "value_weighted_exposure": float(m.get("value_weighted_exposure", np.nan)),
                    "mean_response_time_s": float(m.get("mean_response_time_s", np.nan)),
                    "boundary_message_count": float(m.get("boundary_message_count", np.nan)),
                    "tasks_per_unit_distance": float(m.get("tasks_per_unit_distance", np.nan)),
                    "fleet_task_engagement_fraction_so_far": float(m.get("fleet_task_engagement_fraction_so_far", np.nan)),
                    "fleet_idle_no_task_fraction_so_far": float(m.get("fleet_idle_no_task_fraction_so_far", np.nan)),
                    "stale_goal_clears": float(m.get("stale_goal_clears", np.nan)),
                    "model_deterring_accepted": float(m.get("model_deterring_accepted", np.nan)),
                    "model_deterring_generated": float(m.get("model_deterring_generated", np.nan)),
                    "model_deterring_candidates_total": float(m.get("model_deterring_candidates_total", np.nan)),
                }
            )

    ts_df = pd.concat(ts_all, ignore_index=True)
    final_df = pd.DataFrame(final_rows)
    ts_df.to_csv(outdir / "timeseries_all.csv", index=False)
    final_df.to_csv(outdir / "final_metrics_all.csv", index=False)

    # Zone stats from frozen proposed baseline (partitioning is shared config-level).
    zref = last_by_name.get("proposed")
    if zref is not None:
        _zone_stats(zref).to_csv(outdir / "zone_stats.csv", index=False)

    _plot_zone_partition_and_paths(last_by_name, first_by_name, pose_hist_by_name, run_params, outdir / "01_zone_partition_paths_tasks.png")
    _plot_model_internals(ts_df, outdir / "02_model_internals_timeseries.png")
    _plot_task_funnel(ts_df, outdir / "03_task_funnel_timeseries.png")
    _plot_dispatch_diagnostics(ts_df, outdir / "04_dispatch_diagnostics.png")
    _plot_performance(ts_df, final_df, outdir / "05_performance_compare.png")
    _plot_delta_vs_prediction(ts_df, outdir / "06_delta_vs_prediction_over_time.png")

    # Compact markdown report
    lines = []
    lines.append("# Component Diagnostic Report (Frozen vs Simple Task Management)")
    lines.append("")
    lines.append("## Baselines Compared")
    for spec in baseline_specs:
        lines.append(f"- `{spec.name}`: module={spec.module_name}, simulation_mode={spec.simulation_mode}, simple_task_management={spec.use_simple_tasks}")
    lines.append("")
    lines.append("## Final Metrics")
    lines.append("")
    if not final_df.empty:
        lines.append(final_df.round(4).to_markdown(index=False))
    else:
        lines.append("No metrics collected.")
    lines.append("")
    lines.append("## Critical checks")
    if not final_df.empty:
        try:
            p = final_df.set_index("baseline")
            if "proposed_simple_tasks" in p.index and "proposed" in p.index:
                stale_delta = p.loc["proposed_simple_tasks", "stale_goal_clears"] - p.loc["proposed", "stale_goal_clears"]
                lines.append(f"- stale_goal_clears (simple - proposed): `{stale_delta:.3f}`")
            if "proposed" in p.index and "prediction_only" in p.index:
                exp_imp = 100.0 * (p.loc["prediction_only", "value_weighted_exposure"] - p.loc["proposed", "value_weighted_exposure"]) / max(p.loc["prediction_only", "value_weighted_exposure"], 1e-9)
                lines.append(f"- proposed exposure improvement vs prediction_only: `{exp_imp:.3f}%`")
            if "proposed_simple_tasks" in p.index and "prediction_only" in p.index:
                exp_imp_s = 100.0 * (p.loc["prediction_only", "value_weighted_exposure"] - p.loc["proposed_simple_tasks", "value_weighted_exposure"]) / max(p.loc["prediction_only", "value_weighted_exposure"], 1e-9)
                lines.append(f"- proposed_simple_tasks exposure improvement vs prediction_only: `{exp_imp_s:.3f}%`")
        except Exception as exc:
            lines.append(f"- Could not compute derived checks: {exc}")
    lines.append("")
    lines.append("## Output files")
    lines.append("- `params.json`, `params_table.csv`")
    lines.append("- `timeseries_*.csv`, `timeseries_all.csv`, `final_metrics_all.csv`, `zone_stats.csv`")
    lines.append("- `01_zone_partition_paths_tasks.png`")
    lines.append("- `02_model_internals_timeseries.png`")
    lines.append("- `03_task_funnel_timeseries.png`")
    lines.append("- `04_dispatch_diagnostics.png`")
    lines.append("- `05_performance_compare.png`")
    lines.append("- `06_delta_vs_prediction_over_time.png`")

    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[done] diagnostic outputs written to: {outdir}")


if __name__ == "__main__":
    main()
