from __future__ import annotations

import argparse
import heapq
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from SESTPP import OnlineSESTPP as MainlineSESTPP
from sestpp_isolation.model import OnlineSESTPP as SandboxSESTPP


@dataclass
class IsolationConfig:
    # Map / grid
    W: float = 500.0
    H: float = 500.0
    NX: int = 80
    NY: int = 64

    # Time
    dt: float = 5.0
    T_end: float = 10800.0
    warmup_s: float = 1800.0
    eval_period_s: float = 30.0
    forecast_horizon_s: float = 300.0

    # Forecast scoring
    forecast_top_k: int = 5
    match_radius_m: float = 20.0

    # Ground-truth process
    mu_true: float = 1.0e-6
    alpha_true: float = 0.30
    omega_true: float = 600.0
    sigma_true: float = 12.0
    beta_true: float = 0.30

    # Value map
    row_spacing_m: float = 4.8
    row_gain: float = 1.5
    edge_gain: float = 0.6
    edge_scale_m: float = 35.0

    # External intervention replay
    intervention_prob: float = 0.45
    intervention_cooldown_s: float = 40.0
    intervention_delay_s: float = 10.0
    intervention_sigma: float = 12.0
    intervention_omega: float = 600.0
    intervention_shuffle: str = "none"  # none, space, time, spacetime
    shuffle_time_window_s: float = 300.0

    # Shared model params
    model_sigma: float = 12.0
    model_omega: float = 600.0
    model_omega_inhib: float = 900.0
    model_alpha_in: float = 0.25
    model_alpha_cross: float = 0.0
    model_alpha_inhib: float = 0.45
    model_mu_base: float = 5.0e-5
    model_bg_ema: float = 1.0e-6

    # Multi-run
    runs: int = 8
    seed_start: int = 2026


MODEL_ORDER = ("mainline", "sandbox")


def _truth_time_multiplier(t_abs: float) -> float:
    day = 24.0 * 3600.0
    phi = 2.0 * math.pi * (t_abs % day) / day
    mult = 1.0 + 0.4 * math.sin(phi) + 0.15 * math.sin(2.0 * phi)
    return max(0.2, mult)


def _make_value_sampler(cfg: IsolationConfig):
    xs = np.linspace(0.0, cfg.W, cfg.NX)
    ys = np.linspace(0.0, cfg.H, cfg.NY)
    X, Y = np.meshgrid(xs, ys, indexing="xy")

    dist_edge = np.minimum.reduce([X, cfg.W - X, Y, cfg.H - Y])
    edge_term = cfg.edge_gain * np.exp(-dist_edge / max(cfg.edge_scale_m, 1e-9))

    if cfg.row_spacing_m > 0:
        row_phase = 2.0 * math.pi * (Y / cfg.row_spacing_m)
        row_term = cfg.row_gain * (0.5 + 0.5 * np.cos(row_phase))
    else:
        row_term = np.zeros_like(X)

    weights = 1.0 + edge_term + row_term
    weights = np.clip(weights, 1e-9, None)
    prob = (weights / np.sum(weights)).ravel()
    cdf = np.cumsum(prob)
    dx = cfg.W / max(cfg.NX - 1, 1)
    dy = cfg.H / max(cfg.NY - 1, 1)
    return xs, ys, cdf, dx, dy


def _sample_from_value_map(
    rng: np.random.Generator,
    xs: np.ndarray,
    ys: np.ndarray,
    cdf: np.ndarray,
    dx: float,
    dy: float,
    cfg: IsolationConfig,
):
    u = float(rng.random())
    k = int(np.searchsorted(cdf, u, side="left"))
    k = max(0, min(k, cdf.size - 1))
    iy, ix = divmod(k, xs.size)
    x = float(xs[ix] + rng.uniform(-0.5 * dx, 0.5 * dx))
    y = float(ys[iy] + rng.uniform(-0.5 * dy, 0.5 * dy))
    return float(np.clip(x, 0.0, cfg.W)), float(np.clip(y, 0.0, cfg.H))


def _suppression_keep_prob(
    x: float,
    y: float,
    t_now: float,
    interventions,
    cfg: IsolationConfig,
):
    if not interventions:
        return 1.0, 0.0
    total = 0.0
    sig2 = max(cfg.intervention_sigma ** 2, 1e-9)
    om = max(cfg.intervention_omega, 1e-9)
    for ev in interventions:
        dt = t_now - float(ev["t"])
        if dt < 0.0:
            continue
        dx = x - float(ev["x"])
        dy = y - float(ev["y"])
        kernel = math.exp(-0.5 * (dx * dx + dy * dy) / sig2)
        total += cfg.beta_true * kernel * math.exp(-dt / om)
    keep = math.exp(-total) if total > 0.0 else 1.0
    return float(keep), float(total)


def _build_model(model_cls, cfg: IsolationConfig):
    return model_cls(
        x_min=0.0,
        x_max=cfg.W,
        y_min=0.0,
        y_max=cfg.H,
        nx=cfg.NX,
        ny=cfg.NY,
        sigma=cfg.model_sigma,
        omega=cfg.model_omega,
        omega_inhib=cfg.model_omega_inhib,
        alpha_in=cfg.model_alpha_in,
        alpha_cross=cfg.model_alpha_cross,
        alpha_inhib=cfg.model_alpha_inhib,
        mu_base=cfg.model_mu_base,
        bg_ema=cfg.model_bg_ema,
    )


def _horizon_truth_grids(
    t_eval: float,
    horizon_s: float,
    truth_times: np.ndarray,
    truth_xy: np.ndarray,
    model,
):
    i0 = int(np.searchsorted(truth_times, t_eval, side="right"))
    i1 = int(np.searchsorted(truth_times, t_eval + horizon_s, side="right"))
    fut_xy = truth_xy[i0:i1]
    count_grid = np.zeros_like(model.lam, dtype=float)
    for ex, ey in fut_xy:
        iy, ix = model.world_to_idx(float(ex), float(ey))
        count_grid[iy, ix] += 1.0
    occ_grid = (count_grid > 0.0).astype(float)
    return occ_grid, count_grid, int(len(fut_xy))


def _probability_metrics(
    prob: np.ndarray,
    occ_grid: np.ndarray,
    count_grid: np.ndarray,
    cell_area: float,
    horizon_s: float,
):
    eps = 1e-9
    p = np.clip(prob.astype(float), eps, 1.0 - eps)
    y = occ_grid.astype(float)
    truth_rate = count_grid.astype(float) / max(cell_area * horizon_s, eps)

    brier = float(np.mean((p - y) ** 2))
    logloss = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
    rate_l1 = float(np.mean(np.abs(((-np.log1p(-p)) / max(cell_area * horizon_s, eps)) - truth_rate)))

    event_mask = y > 0.5
    nonevent_mask = ~event_mask
    event_prob_mean = float(np.mean(p[event_mask])) if np.any(event_mask) else float("nan")
    nonevent_prob_mean = float(np.mean(p[nonevent_mask])) if np.any(nonevent_mask) else float("nan")

    return {
        "field_brier": brier,
        "field_logloss": logloss,
        "field_rate_l1": rate_l1,
        "event_cell_probability_mean": event_prob_mean,
        "non_event_cell_probability_mean": nonevent_prob_mean,
    }


def _forecast_metrics_for_snapshot(
    t_eval: float,
    hotspots,
    truth_times: np.ndarray,
    truth_xy: np.ndarray,
    cfg: IsolationConfig,
):
    i0 = int(np.searchsorted(truth_times, t_eval, side="right"))
    i1 = int(np.searchsorted(truth_times, t_eval + cfg.forecast_horizon_s, side="right"))
    fut_times = truth_times[i0:i1]
    fut_xy = truth_xy[i0:i1]
    n_events = len(fut_times)
    if n_events == 0:
        return {
            "future_events": 0,
            "forecast_recall_at_k": np.nan,
            "forecast_precision_at_k": np.nan,
            "forecast_hit_rate": np.nan,
            "forecast_lead_time_s": np.nan,
        }

    r2 = float(cfg.match_radius_m) ** 2
    event_matched = np.zeros(n_events, dtype=bool)
    hotspot_hit = np.zeros(len(hotspots), dtype=bool)
    lead_times = []

    for hi, (hx, hy) in enumerate(hotspots):
        for ei, (ex, ey) in enumerate(fut_xy):
            dx = float(ex) - float(hx)
            dy = float(ey) - float(hy)
            if (dx * dx + dy * dy) <= r2:
                hotspot_hit[hi] = True
                event_matched[ei] = True
                lead_times.append(float(fut_times[ei] - t_eval))

    k_eff = max(len(hotspots), 1)
    recall = float(np.sum(event_matched) / n_events)
    precision = float(np.sum(hotspot_hit) / k_eff)
    hit_rate = float(1.0 if np.any(event_matched) else 0.0)
    lead_time = float(np.mean(lead_times)) if lead_times else float("nan")
    return {
        "future_events": int(n_events),
        "forecast_recall_at_k": recall,
        "forecast_precision_at_k": precision,
        "forecast_hit_rate": hit_rate,
        "forecast_lead_time_s": lead_time,
    }


def _stats(arr) -> dict:
    vals = np.asarray(arr, dtype=float)
    vals = vals[np.isfinite(vals)]
    n = int(vals.size)
    if n == 0:
        return {"mean": float("nan"), "std": float("nan"), "ci95": float("nan"), "n": 0}
    mean = float(np.mean(vals))
    std = float(np.std(vals))
    ci95 = float(1.96 * std / math.sqrt(n)) if n > 1 else 0.0
    return {"mean": mean, "std": std, "ci95": ci95, "n": n}


def simulate_one_run(run_idx: int, seed: int, cfg: IsolationConfig):
    rng = np.random.default_rng(seed)
    models = {
        "mainline": _build_model(MainlineSESTPP, cfg),
        "sandbox": _build_model(SandboxSESTPP, cfg),
    }

    xs, ys, cdf, dx_cell, dy_cell = _make_value_sampler(cfg)
    cell_area = float(dx_cell * dy_cell)
    total_s = float(cfg.warmup_s + cfg.T_end)
    n_steps = int(math.ceil(total_s / max(cfg.dt, 1e-9)))
    next_eval_t = float(cfg.warmup_s)

    truth_times_rel = []
    truth_xy_rel = []
    intervention_events_rel = []

    active_truth_interventions = []
    truth_intervention_queue = []
    model_intervention_queue = []
    offspring_queue = []
    last_intervention_trigger_t = -1e18

    ll = {name: 0.0 for name in MODEL_ORDER}
    eval_snapshots = []
    eps = 1e-12

    for k in range(n_steps):
        t_abs = float((k + 1) * cfg.dt)
        if t_abs > total_s + 1e-9:
            break

        for model in models.values():
            model.advance_time(cfg.dt)

        while truth_intervention_queue and truth_intervention_queue[0][0] <= t_abs + 1e-9:
            ti, xi, yi = heapq.heappop(truth_intervention_queue)
            active_truth_interventions.append({"t": float(ti), "x": float(xi), "y": float(yi)})

        while model_intervention_queue and model_intervention_queue[0][0] <= t_abs + 1e-9:
            ti, xi, yi = heapq.heappop(model_intervention_queue)
            for model in models.values():
                model.add_intervention_event(
                    xi,
                    yi,
                    weight=1.0,
                    sigma=cfg.intervention_sigma,
                    omega_inhib=cfg.intervention_omega,
                )
            if ti >= cfg.warmup_s:
                intervention_events_rel.append((float(xi), float(yi), float(ti - cfg.warmup_s)))

        t_keep = t_abs - 5.0 * max(cfg.intervention_omega, cfg.omega_true)
        if active_truth_interventions:
            active_truth_interventions = [ev for ev in active_truth_interventions if float(ev["t"]) >= t_keep]

        candidates = []
        lam0 = max(cfg.mu_true * _truth_time_multiplier(t_abs) * cfg.W * cfg.H, 0.0)
        n_base = int(rng.poisson(lam0 * cfg.dt))
        for _ in range(n_base):
            x, y = _sample_from_value_map(rng, xs, ys, cdf, dx_cell, dy_cell, cfg)
            candidates.append((x, y, t_abs))
        while offspring_queue and offspring_queue[0][0] <= t_abs + 1e-9:
            to, xo, yo = heapq.heappop(offspring_queue)
            candidates.append((float(xo), float(yo), float(to)))

        lam_snapshot = {name: models[name].lam for name in MODEL_ORDER}
        step_events = []
        for xe, ye, te in candidates:
            p_keep, _supp = _suppression_keep_prob(xe, ye, te, active_truth_interventions, cfg)
            if rng.random() > p_keep:
                continue

            step_events.append((float(xe), float(ye), float(te)))
            if te >= cfg.warmup_s:
                truth_times_rel.append(float(te - cfg.warmup_s))
                truth_xy_rel.append((float(xe), float(ye)))

            n_child = int(rng.poisson(cfg.alpha_true))
            for _ in range(n_child):
                dt_child = float(rng.exponential(max(cfg.omega_true, 1e-9)))
                tc = float(te + dt_child)
                if tc > total_s:
                    continue
                xc = float(np.clip(xe + rng.normal(0.0, cfg.sigma_true), 0.0, cfg.W))
                yc = float(np.clip(ye + rng.normal(0.0, cfg.sigma_true), 0.0, cfg.H))
                heapq.heappush(offspring_queue, (tc, xc, yc))

            if (te - last_intervention_trigger_t) >= cfg.intervention_cooldown_s:
                if rng.random() < cfg.intervention_prob:
                    ti_truth = float(te + cfg.intervention_delay_s)
                    xi_truth = float(xe)
                    yi_truth = float(ye)
                    if ti_truth <= total_s:
                        heapq.heappush(truth_intervention_queue, (ti_truth, xi_truth, yi_truth))

                    ti_model = float(ti_truth)
                    xi_model = float(xi_truth)
                    yi_model = float(yi_truth)
                    shuffle_mode = str(cfg.intervention_shuffle).strip().lower()
                    if shuffle_mode in ("space", "spacetime"):
                        xi_model, yi_model = _sample_from_value_map(rng, xs, ys, cdf, dx_cell, dy_cell, cfg)
                    if shuffle_mode in ("time", "spacetime"):
                        ti_model += float(rng.uniform(-cfg.shuffle_time_window_s, cfg.shuffle_time_window_s))
                        ti_model = float(np.clip(ti_model, te + 1e-3, total_s))
                    if ti_model <= total_s:
                        heapq.heappush(model_intervention_queue, (ti_model, float(xi_model), float(yi_model)))
                    last_intervention_trigger_t = float(te)

        if t_abs >= cfg.warmup_s:
            for name in MODEL_ORDER:
                ll[name] -= float(np.sum(lam_snapshot[name]) * cell_area * cfg.dt)
            for xe, ye, _te in step_events:
                for name in MODEL_ORDER:
                    model = models[name]
                    iy, ix = model.world_to_idx(xe, ye)
                    lv = max(float(lam_snapshot[name][iy, ix]), eps)
                    ll[name] += math.log(lv)

        for xe, ye, _te in step_events:
            for model in models.values():
                model.add_local_event(xe, ye)

        if t_abs >= next_eval_t - 1e-9:
            t_rel = float(t_abs - cfg.warmup_s)
            if t_rel >= 0.0:
                for name in MODEL_ORDER:
                    model = models[name]
                    hs = model.hotspots(
                        top_k=cfg.forecast_top_k,
                        merge_radius=cfg.match_radius_m,
                        use_excess=True,
                        mask_poly=None,
                    )
                    eval_snapshots.append(
                        {
                            "run_idx": int(run_idx),
                            "seed": int(seed),
                            "model": name,
                            "t_s": t_rel,
                            "lam": model.lam.copy(),
                            "hotspots": [(float(h["x"]), float(h["y"])) for h in hs],
                        }
                    )
            next_eval_t += cfg.eval_period_s

    truth_times_rel = np.asarray(truth_times_rel, dtype=float)
    truth_xy_rel = np.asarray(truth_xy_rel, dtype=float) if truth_xy_rel else np.empty((0, 2), dtype=float)
    horizon_s = float(cfg.forecast_horizon_s)
    horizon_scale = max(cell_area * horizon_s, 1e-9)

    eval_rows = []
    for snap in eval_snapshots:
        model = models[snap["model"]]
        occ_grid, count_grid, future_event_count = _horizon_truth_grids(
            t_eval=float(snap["t_s"]),
            horizon_s=horizon_s,
            truth_times=truth_times_rel,
            truth_xy=truth_xy_rel,
            model=model,
        )
        prob = 1.0 - np.exp(-np.clip(snap["lam"], 0.0, None) * horizon_scale)
        prob_metrics = _probability_metrics(prob, occ_grid, count_grid, cell_area, horizon_s)
        forecast_metrics = _forecast_metrics_for_snapshot(
            t_eval=float(snap["t_s"]),
            hotspots=list(snap["hotspots"]),
            truth_times=truth_times_rel,
            truth_xy=truth_xy_rel,
            cfg=cfg,
        )
        eval_rows.append(
            {
                "run_idx": int(run_idx),
                "seed": int(seed),
                "model": snap["model"],
                "t_s": float(snap["t_s"]),
                "future_event_count": int(future_event_count),
                **prob_metrics,
                **forecast_metrics,
            }
        )

    eval_df = pd.DataFrame(eval_rows)

    def _agg(model_name: str, metric_name: str) -> float:
        arr = (
            eval_df[eval_df["model"] == model_name][metric_name].to_numpy(dtype=float)
            if metric_name in eval_df.columns
            else np.array([], dtype=float)
        )
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return float("nan")
        return float(np.mean(arr))

    paired = {
        "run_idx": int(run_idx),
        "seed": int(seed),
        "truth_events": int(truth_times_rel.size),
        "interventions_replayed": int(len(intervention_events_rel)),
    }

    metrics = [
        "field_brier",
        "field_logloss",
        "field_rate_l1",
        "event_cell_probability_mean",
        "non_event_cell_probability_mean",
        "forecast_recall_at_k",
        "forecast_precision_at_k",
        "forecast_hit_rate",
        "forecast_lead_time_s",
    ]
    for name in MODEL_ORDER:
        for metric in metrics:
            paired[f"{name}_{metric}"] = _agg(name, metric)
        paired[f"{name}_nll"] = float(-ll[name])

    delta_metrics = metrics + ["nll"]
    for metric in delta_metrics:
        paired[f"delta_{metric}_sandbox_minus_mainline"] = (
            paired[f"sandbox_{metric}"] - paired[f"mainline_{metric}"]
        )

    for metric in ("field_brier", "field_logloss", "field_rate_l1", "nll"):
        baseline = paired[f"mainline_{metric}"]
        candidate = paired[f"sandbox_{metric}"]
        if np.isfinite(baseline) and abs(baseline) > 1e-12:
            paired[f"{metric}_improvement_pct"] = 100.0 * (baseline - candidate) / abs(baseline)
        else:
            paired[f"{metric}_improvement_pct"] = float("nan")

    return {
        "paired_metrics": paired,
        "eval_rows": eval_rows,
    }


def _plot_timeseries(eval_df: pd.DataFrame, out_png: Path):
    if eval_df.empty:
        return
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
    plot_specs = [
        ("field_brier", "Field Brier"),
        ("field_logloss", "Field Log Loss"),
        ("forecast_recall_at_k", "Recall@k"),
        ("forecast_precision_at_k", "Precision@k"),
    ]
    for ax, (metric, title) in zip(axes.ravel(), plot_specs):
        for model in MODEL_ORDER:
            d = eval_df[eval_df["model"] == model]
            if d.empty:
                continue
            g = d.groupby("t_s")[metric].agg(["mean", "std"]).reset_index()
            ax.plot(g["t_s"], g["mean"], label=model, lw=1.8)
            lo = g["mean"] - g["std"].fillna(0.0)
            hi = g["mean"] + g["std"].fillna(0.0)
            ax.fill_between(g["t_s"], lo, hi, alpha=0.15)
        ax.set_title(title)
        ax.grid(alpha=0.25)
    for ax in axes[1]:
        ax.set_xlabel("Simulation time after warmup (s)")
    fig.legend(MODEL_ORDER, loc="upper center", ncol=2)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.96))
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _make_summary(run_df: pd.DataFrame) -> pd.DataFrame:
    metric_cols = [
        "delta_field_brier_sandbox_minus_mainline",
        "delta_field_logloss_sandbox_minus_mainline",
        "delta_field_rate_l1_sandbox_minus_mainline",
        "delta_nll_sandbox_minus_mainline",
        "delta_forecast_recall_at_k_sandbox_minus_mainline",
        "delta_forecast_precision_at_k_sandbox_minus_mainline",
        "delta_forecast_hit_rate_sandbox_minus_mainline",
        "delta_forecast_lead_time_s_sandbox_minus_mainline",
        "field_brier_improvement_pct",
        "field_logloss_improvement_pct",
        "field_rate_l1_improvement_pct",
        "nll_improvement_pct",
    ]
    rows = []
    for metric in metric_cols:
        if metric not in run_df.columns:
            continue
        stats = _stats(run_df[metric].to_numpy(dtype=float))
        rows.append({"metric": metric, **stats})
    return pd.DataFrame(rows)


def _make_report(cfg: IsolationConfig, run_df: pd.DataFrame, summary_df: pd.DataFrame) -> str:
    lines = []
    lines.append("# SESTPP Isolation Benchmark")
    lines.append("")
    lines.append("This benchmark compares the current mainline SESTPP against the sandbox copy in `sestpp_isolation/model.py`.")
    lines.append("Both models receive the same truth stream, detections, and intervention replay on matched seeds.")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    for key, value in asdict(cfg).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- Negative `delta_*_sandbox_minus_mainline` is better for loss metrics such as Brier, log loss, rate L1, and NLL.")
    lines.append("- Positive `delta_*_sandbox_minus_mainline` is better for recall, precision, and hit rate.")
    lines.append("- Positive `*_improvement_pct` means the sandbox beat the current mainline model on that loss metric.")
    lines.append("")
    lines.append("## Per-Run Snapshot")
    lines.append("")
    show_cols = [
        "run_idx",
        "seed",
        "truth_events",
        "interventions_replayed",
        "mainline_field_logloss",
        "sandbox_field_logloss",
        "delta_field_logloss_sandbox_minus_mainline",
        "mainline_nll",
        "sandbox_nll",
        "delta_nll_sandbox_minus_mainline",
        "mainline_forecast_recall_at_k",
        "sandbox_forecast_recall_at_k",
        "delta_forecast_recall_at_k_sandbox_minus_mainline",
    ]
    keep = [col for col in show_cols if col in run_df.columns]
    if keep:
        lines.append(run_df[keep].round(4).to_markdown(index=False))
    else:
        lines.append("No per-run rows available.")
    lines.append("")
    lines.append("## Aggregate Summary")
    lines.append("")
    if not summary_df.empty:
        lines.append(summary_df.round(6).to_markdown(index=False))
    else:
        lines.append("No finite aggregate metrics available.")
    lines.append("")

    def _summary_mean(metric: str) -> float:
        rows = summary_df[summary_df["metric"] == metric]
        return float(rows.iloc[0]["mean"]) if not rows.empty else float("nan")

    d_logloss = _summary_mean("delta_field_logloss_sandbox_minus_mainline")
    d_brier = _summary_mean("delta_field_brier_sandbox_minus_mainline")
    d_nll = _summary_mean("delta_nll_sandbox_minus_mainline")
    d_recall = _summary_mean("delta_forecast_recall_at_k_sandbox_minus_mainline")
    d_prec = _summary_mean("delta_forecast_precision_at_k_sandbox_minus_mainline")

    lines.append("## Readout")
    lines.append("")
    if all(np.isfinite(x) for x in (d_logloss, d_brier, d_nll, d_recall, d_prec)):
        if d_logloss < 0.0 and d_brier < 0.0 and d_nll < 0.0 and d_recall >= 0.0 and d_prec >= 0.0:
            lines.append("- The sandbox changes improved both probabilistic calibration and hotspot forecasting in this run set.")
        elif d_logloss < 0.0 or d_brier < 0.0 or d_nll < 0.0:
            lines.append("- The sandbox changes improved some calibration metrics, but the gain is not yet uniform across forecast metrics.")
        else:
            lines.append("- The sandbox changes did not beat the mainline model on the primary isolated metrics in this run set.")
    else:
        lines.append("- Not enough finite metrics were available to interpret the comparison.")
    lines.append("- If the sandbox and mainline models are still identical, the deltas should stay near zero. Use that as a smoke check.")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Paired benchmark for isolated SESTPP model experiments")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--T-end", type=float, default=10800.0)
    parser.add_argument("--warmup-s", type=float, default=1800.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--eval-period-s", type=float, default=30.0)
    parser.add_argument("--forecast-horizon-s", type=float, default=300.0)
    parser.add_argument("--outdir", type=str, default="results/sestpp_isolation")
    parser.add_argument("--intervention-prob", type=float, default=0.45)
    parser.add_argument("--intervention-cooldown-s", type=float, default=40.0)
    parser.add_argument("--intervention-delay-s", type=float, default=10.0)
    parser.add_argument("--intervention-shuffle", choices=["none", "space", "time", "spacetime"], default="none")
    parser.add_argument("--shuffle-time-window-s", type=float, default=300.0)
    parser.add_argument("--beta-true", type=float, default=0.30)
    parser.add_argument("--model-sigma", type=float, default=12.0)
    parser.add_argument("--model-omega", type=float, default=600.0)
    parser.add_argument("--model-omega-inhib", type=float, default=900.0)
    parser.add_argument("--model-alpha-in", type=float, default=0.25)
    parser.add_argument("--model-alpha-cross", type=float, default=0.0)
    parser.add_argument("--model-alpha-inhib", type=float, default=0.45)
    parser.add_argument("--model-mu-base", type=float, default=5.0e-5)
    parser.add_argument("--model-bg-ema", type=float, default=1.0e-6)
    args = parser.parse_args()

    cfg = IsolationConfig(
        runs=int(args.runs),
        seed_start=int(args.seed_start),
        T_end=float(args.T_end),
        warmup_s=float(args.warmup_s),
        dt=float(args.dt),
        eval_period_s=float(args.eval_period_s),
        forecast_horizon_s=float(args.forecast_horizon_s),
        intervention_prob=float(args.intervention_prob),
        intervention_cooldown_s=float(args.intervention_cooldown_s),
        intervention_delay_s=float(args.intervention_delay_s),
        intervention_shuffle=str(args.intervention_shuffle),
        shuffle_time_window_s=float(args.shuffle_time_window_s),
        beta_true=float(args.beta_true),
        model_sigma=float(args.model_sigma),
        model_omega=float(args.model_omega),
        model_omega_inhib=float(args.model_omega_inhib),
        model_alpha_in=float(args.model_alpha_in),
        model_alpha_cross=float(args.model_alpha_cross),
        model_alpha_inhib=float(args.model_alpha_inhib),
        model_mu_base=float(args.model_mu_base),
        model_bg_ema=float(args.model_bg_ema),
    )

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    run_rows = []
    eval_rows = []
    for run_idx in range(cfg.runs):
        seed = cfg.seed_start + run_idx
        res = simulate_one_run(run_idx, seed, cfg)
        run_rows.append(res["paired_metrics"])
        eval_rows.extend(res["eval_rows"])
        print(
            f"[run {run_idx + 1}/{cfg.runs}] seed={seed} "
            f"logloss_delta={res['paired_metrics'].get('delta_field_logloss_sandbox_minus_mainline', float('nan')):.6f} "
            f"nll_delta={res['paired_metrics'].get('delta_nll_sandbox_minus_mainline', float('nan')):.6f}"
        )

    run_df = pd.DataFrame(run_rows)
    eval_df = pd.DataFrame(eval_rows)
    summary_df = _make_summary(run_df)

    per_run_csv = outdir / "paired_per_run.csv"
    per_eval_csv = outdir / "paired_per_eval.csv"
    summary_csv = outdir / "paired_summary.csv"
    report_md = outdir / "paired_report.md"
    manifest_json = outdir / "manifest.json"
    plot_png = outdir / "paired_timeseries.png"

    run_df.to_csv(per_run_csv, index=False)
    eval_df.to_csv(per_eval_csv, index=False)
    summary_df.to_csv(summary_csv, index=False)
    report_md.write_text(_make_report(cfg, run_df, summary_df) + "\n", encoding="utf-8")
    manifest_json.write_text(
        json.dumps(
            {
                "config": asdict(cfg),
                "outputs": {
                    "per_run_csv": str(per_run_csv),
                    "per_eval_csv": str(per_eval_csv),
                    "summary_csv": str(summary_csv),
                    "report_md": str(report_md),
                    "plot_png": str(plot_png),
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _plot_timeseries(eval_df, plot_png)

    print("Wrote:")
    print(f"- {per_run_csv}")
    print(f"- {per_eval_csv}")
    print(f"- {summary_csv}")
    print(f"- {report_md}")
    print(f"- {plot_png}")
    print(f"- {manifest_json}")


if __name__ == "__main__":
    main()
