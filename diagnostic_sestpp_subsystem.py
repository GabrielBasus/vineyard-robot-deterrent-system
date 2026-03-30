from __future__ import annotations

import argparse
import heapq
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from SESTPP import OnlineSESTPP


@dataclass
class SubsystemConfig:
    # Map / model grid
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

    # Value map (rows + edges) for truth generation
    row_spacing_m: float = 4.8
    row_gain: float = 1.5
    edge_gain: float = 0.6
    edge_scale_m: float = 35.0

    # External intervention replay (independent of task generation)
    intervention_prob: float = 0.45
    intervention_cooldown_s: float = 40.0
    intervention_delay_s: float = 10.0
    intervention_sigma: float = 12.0
    intervention_omega: float = 600.0
    intervention_shuffle: str = "none"  # one of: none, space, time, spacetime
    shuffle_time_window_s: float = 300.0

    # OnlineSESTPP params
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

    # Plot controls
    final_map_recent_truth: int = 400
    final_map_recent_interventions: int = 120


def _make_value_sampler(cfg: SubsystemConfig):
    xs = np.linspace(0.0, cfg.W, cfg.NX)
    ys = np.linspace(0.0, cfg.H, cfg.NY)
    X, Y = np.meshgrid(xs, ys, indexing="xy")

    # Edge preference
    dist_edge = np.minimum.reduce([X, cfg.W - X, Y, cfg.H - Y])
    edge_term = cfg.edge_gain * np.exp(-dist_edge / max(cfg.edge_scale_m, 1e-9))

    # Row preference
    if cfg.row_spacing_m > 0:
        row_phase = 2.0 * math.pi * (Y / cfg.row_spacing_m)
        row_term = cfg.row_gain * (0.5 + 0.5 * np.cos(row_phase))
    else:
        row_term = np.zeros_like(X)

    w = 1.0 + edge_term + row_term
    w = np.clip(w, 1e-9, None)
    p = (w / np.sum(w)).ravel()
    cdf = np.cumsum(p)
    dx = cfg.W / max(cfg.NX - 1, 1)
    dy = cfg.H / max(cfg.NY - 1, 1)
    return xs, ys, cdf, dx, dy


def _sample_from_value_map(rng: np.random.Generator, xs, ys, cdf, dx, dy, cfg: SubsystemConfig):
    u = float(rng.random())
    k = int(np.searchsorted(cdf, u, side="left"))
    k = max(0, min(k, cdf.size - 1))
    iy, ix = divmod(k, xs.size)
    x = float(xs[ix] + rng.uniform(-0.5 * dx, 0.5 * dx))
    y = float(ys[iy] + rng.uniform(-0.5 * dy, 0.5 * dy))
    return float(np.clip(x, 0.0, cfg.W)), float(np.clip(y, 0.0, cfg.H))


def _suppression_keep_prob(x: float, y: float, t_now: float, interventions, cfg: SubsystemConfig):
    if not interventions:
        return 1.0, 0.0
    s = 0.0
    sig2 = max(cfg.intervention_sigma ** 2, 1e-9)
    om = max(cfg.intervention_omega, 1e-9)
    for ev in interventions:
        dt = t_now - float(ev["t"])
        if dt < 0:
            continue
        dx = x - float(ev["x"])
        dy = y - float(ev["y"])
        k = math.exp(-0.5 * (dx * dx + dy * dy) / sig2)
        s += cfg.beta_true * k * math.exp(-dt / om)
    p_keep = math.exp(-s) if s > 0 else 1.0
    return float(p_keep), float(s)


def _forecast_metrics_for_snapshot(t_eval, hotspots, truth_times, truth_xy, cfg: SubsystemConfig):
    i0 = int(np.searchsorted(truth_times, t_eval, side="right"))
    i1 = int(np.searchsorted(truth_times, t_eval + cfg.forecast_horizon_s, side="right"))
    fut_times = truth_times[i0:i1]
    fut_xy = truth_xy[i0:i1]
    n_events = len(fut_times)
    if n_events == 0:
        return {
            "future_events": 0,
            "recall_at_k": np.nan,
            "precision_at_k": np.nan,
            "hit_rate": np.nan,
            "lead_time_s": np.nan,
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
    lead = float(np.mean(lead_times)) if lead_times else float("nan")
    return {
        "future_events": int(n_events),
        "recall_at_k": recall,
        "precision_at_k": precision,
        "hit_rate": hit_rate,
        "lead_time_s": lead,
    }


def _build_model(cfg: SubsystemConfig):
    return OnlineSESTPP(
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


def simulate_one_run(run_idx: int, seed: int, cfg: SubsystemConfig):
    rng = np.random.default_rng(seed)
    pred = _build_model(cfg)
    prop = _build_model(cfg)
    models = {"prediction_only": pred, "proposed": prop}

    xs, ys, cdf, dx_cell, dy_cell = _make_value_sampler(cfg)
    cell_area = float(dx_cell * dy_cell)
    total_s = float(cfg.warmup_s + cfg.T_end)
    n_steps = int(math.ceil(total_s / max(cfg.dt, 1e-9)))
    next_eval_t = float(cfg.warmup_s)
    next_ts_t = float(cfg.warmup_s)

    truth_events_abs = []  # (x, y, t_abs)
    truth_times_rel = []
    truth_xy_rel = []
    intervention_events_rel = []  # (x, y, t_rel)

    active_truth_interventions = []
    truth_intervention_queue = []  # heap: (t, x, y) used by truth suppression
    model_intervention_queue = []  # heap: (t, x, y) replayed into proposed model
    offspring_queue = []  # heap: (t, x, y)
    last_intervention_trigger_t = -1e18

    diag = {
        "truth_candidate_events": 0,
        "truth_accepted_events": 0,
        "truth_suppressed_events": 0,
        "suppression_effect_sum": 0.0,
        "interventions_truth_replayed": 0,
        "interventions_model_replayed": 0,
    }

    ll = {"prediction_only": 0.0, "proposed": 0.0}
    event_log_sum = {"prediction_only": 0.0, "proposed": 0.0}
    event_lam_sum = {"prediction_only": 0.0, "proposed": 0.0}
    event_count = 0

    eval_snapshots = []  # rows: run, model, t, hotspots
    timeseries_rows = []
    eps = 1e-12

    for k in range(n_steps):
        t_abs = float((k + 1) * cfg.dt)
        if t_abs > total_s + 1e-9:
            break

        # Advance both models.
        pred.advance_time(cfg.dt)
        prop.advance_time(cfg.dt)

        # Activate due truth interventions (affect ground truth only).
        while truth_intervention_queue and truth_intervention_queue[0][0] <= t_abs + 1e-9:
            ti, xi, yi = heapq.heappop(truth_intervention_queue)
            active_truth_interventions.append({"t": float(ti), "x": float(xi), "y": float(yi)})
            diag["interventions_truth_replayed"] += 1

        # Activate due model interventions (affect proposed model only).
        while model_intervention_queue and model_intervention_queue[0][0] <= t_abs + 1e-9:
            ti, xi, yi = heapq.heappop(model_intervention_queue)
            prop.add_intervention_event(
                xi,
                yi,
                weight=1.0,
                sigma=cfg.intervention_sigma,
                omega_inhib=cfg.intervention_omega,
            )
            if ti >= cfg.warmup_s:
                intervention_events_rel.append((float(xi), float(yi), float(ti - cfg.warmup_s)))
            diag["interventions_model_replayed"] += 1

        # Drop old truth interventions from suppression memory.
        t_keep = t_abs - 5.0 * max(cfg.intervention_omega, cfg.omega_true)
        if active_truth_interventions:
            active_truth_interventions = [ev for ev in active_truth_interventions if float(ev["t"]) >= t_keep]

        # Lambda snapshots for log-likelihood at this step.
        lam_pred = pred.lam
        lam_prop = prop.lam

        # Build truth candidates in this step.
        candidates = []
        day_mult = pred.time_multiplier(t_abs)
        lam0 = max(cfg.mu_true * day_mult * cfg.W * cfg.H, 0.0)
        n_base = int(rng.poisson(lam0 * cfg.dt))
        for _ in range(n_base):
            x, y = _sample_from_value_map(rng, xs, ys, cdf, dx_cell, dy_cell, cfg)
            candidates.append((x, y, t_abs))
        while offspring_queue and offspring_queue[0][0] <= t_abs + 1e-9:
            to, xo, yo = heapq.heappop(offspring_queue)
            candidates.append((float(xo), float(yo), float(to)))

        step_events = []
        for (xe, ye, te) in candidates:
            p_keep, s_val = _suppression_keep_prob(xe, ye, te, active_truth_interventions, cfg)
            diag["truth_candidate_events"] += 1
            diag["suppression_effect_sum"] += float(1.0 - p_keep)
            if rng.random() > p_keep:
                diag["truth_suppressed_events"] += 1
                continue

            diag["truth_accepted_events"] += 1
            truth_events_abs.append((float(xe), float(ye), float(te)))
            step_events.append((float(xe), float(ye), float(te)))
            if te >= cfg.warmup_s:
                truth_times_rel.append(float(te - cfg.warmup_s))
                truth_xy_rel.append((float(xe), float(ye)))

            # Schedule offspring from accepted events.
            n_child = int(rng.poisson(cfg.alpha_true))
            for _ in range(n_child):
                dt_child = float(rng.exponential(max(cfg.omega_true, 1e-9)))
                tc = float(te + dt_child)
                if tc > total_s:
                    continue
                xc = float(np.clip(xe + rng.normal(0.0, cfg.sigma_true), 0.0, cfg.W))
                yc = float(np.clip(ye + rng.normal(0.0, cfg.sigma_true), 0.0, cfg.H))
                heapq.heappush(offspring_queue, (tc, xc, yc))

            # External intervention replay trigger from detections (task-generation-free).
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

        # Log-likelihood and event-intensity diagnostics only in measured horizon.
        if t_abs >= cfg.warmup_s:
            lam_mass_pred = float(np.sum(lam_pred) * cell_area * cfg.dt)
            lam_mass_prop = float(np.sum(lam_prop) * cell_area * cfg.dt)
            ll["prediction_only"] -= lam_mass_pred
            ll["proposed"] -= lam_mass_prop
            for (xe, ye, _te) in step_events:
                iy_p, ix_p = pred.world_to_idx(xe, ye)
                iy_i, ix_i = prop.world_to_idx(xe, ye)
                lv_pred = max(float(lam_pred[iy_p, ix_p]), eps)
                lv_prop = max(float(lam_prop[iy_i, ix_i]), eps)
                ll["prediction_only"] += math.log(lv_pred)
                ll["proposed"] += math.log(lv_prop)
                event_log_sum["prediction_only"] += math.log(lv_pred)
                event_log_sum["proposed"] += math.log(lv_prop)
                event_lam_sum["prediction_only"] += lv_pred
                event_lam_sum["proposed"] += lv_prop
                event_count += 1

        # Feed detections to both models (same stream, no task system).
        for (xe, ye, _te) in step_events:
            pred.add_local_event(xe, ye)
            prop.add_local_event(xe, ye)

        # Forecast snapshots at fixed cadence.
        if t_abs >= next_eval_t - 1e-9:
            t_rel = float(t_abs - cfg.warmup_s)
            if t_rel >= 0.0:
                hs_pred = pred.hotspots(
                    top_k=cfg.forecast_top_k,
                    merge_radius=cfg.match_radius_m,
                    use_excess=True,
                    mask_poly=None,
                )
                hs_prop = prop.hotspots(
                    top_k=cfg.forecast_top_k,
                    merge_radius=cfg.match_radius_m,
                    use_excess=True,
                    mask_poly=None,
                )
                eval_snapshots.append(
                    {"run_idx": run_idx, "seed": seed, "model": "prediction_only", "t_s": t_rel,
                     "hotspots": [(float(h["x"]), float(h["y"])) for h in hs_pred]}
                )
                eval_snapshots.append(
                    {"run_idx": run_idx, "seed": seed, "model": "proposed", "t_s": t_rel,
                     "hotspots": [(float(h["x"]), float(h["y"])) for h in hs_prop]}
                )
            next_eval_t += cfg.eval_period_s

        if t_abs >= next_ts_t - 1e-9:
            t_rel = float(t_abs - cfg.warmup_s)
            if t_rel >= 0.0:
                timeseries_rows.append(
                    {
                        "run_idx": run_idx,
                        "seed": seed,
                        "t_s": t_rel,
                        "truth_events_cum": int(len(truth_times_rel)),
                        "interventions_cum": int(len(intervention_events_rel)),
                        "lam_mass_prediction_only": float(np.sum(pred.lam) * cell_area),
                        "lam_mass_proposed": float(np.sum(prop.lam) * cell_area),
                        "ll_prediction_only": float(ll["prediction_only"]),
                        "ll_proposed": float(ll["proposed"]),
                    }
                )
            next_ts_t += cfg.eval_period_s

    truth_times_rel = np.asarray(truth_times_rel, dtype=float)
    truth_xy_rel = np.asarray(truth_xy_rel, dtype=float) if truth_xy_rel else np.empty((0, 2), dtype=float)

    # Offline forecast scoring against realized future truth.
    eval_rows = []
    for snap in eval_snapshots:
        fm = _forecast_metrics_for_snapshot(
            t_eval=float(snap["t_s"]),
            hotspots=list(snap["hotspots"]),
            truth_times=truth_times_rel,
            truth_xy=truth_xy_rel,
            cfg=cfg,
        )
        eval_rows.append(
            {
                "run_idx": run_idx,
                "seed": seed,
                "model": snap["model"],
                "t_s": float(snap["t_s"]),
                **fm,
            }
        )

    def _model_stats(model_name: str):
        er = [r for r in eval_rows if r["model"] == model_name]
        recall = float(np.nanmean([r["recall_at_k"] for r in er])) if er else float("nan")
        precision = float(np.nanmean([r["precision_at_k"] for r in er])) if er else float("nan")
        hit_rate = float(np.nanmean([r["hit_rate"] for r in er])) if er else float("nan")
        lead = float(np.nanmean([r["lead_time_s"] for r in er])) if er else float("nan")
        nll = float(-ll[model_name])
        nll_per_hour = nll / max(cfg.T_end / 3600.0, 1e-9)
        mean_log_lam = float(event_log_sum[model_name] / max(event_count, 1))
        mean_lam_at_events = float(event_lam_sum[model_name] / max(event_count, 1))
        return {
            "forecast_recall_at_k": recall,
            "forecast_precision_at_k": precision,
            "forecast_hit_rate": hit_rate,
            "forecast_lead_time_s": lead,
            "nll": nll,
            "nll_per_hour": nll_per_hour,
            "mean_log_lambda_at_events": mean_log_lam,
            "mean_lambda_at_events": mean_lam_at_events,
        }

    model_metrics = {
        "prediction_only": _model_stats("prediction_only"),
        "proposed": _model_stats("proposed"),
    }
    paired = {
        "run_idx": int(run_idx),
        "seed": int(seed),
        "truth_events": int(len(truth_times_rel)),
        "interventions_truth_replayed": int(diag["interventions_truth_replayed"]),
        "interventions_model_replayed": int(diag["interventions_model_replayed"]),
        "truth_suppression_rate": float(diag["truth_suppressed_events"] / max(diag["truth_candidate_events"], 1)),
        "truth_suppression_effect_mean": float(diag["suppression_effect_sum"] / max(diag["truth_candidate_events"], 1)),
    }
    for k in model_metrics["prediction_only"].keys():
        vp = float(model_metrics["prediction_only"][k])
        vi = float(model_metrics["proposed"][k])
        paired[f"prediction_only_{k}"] = vp
        paired[f"proposed_{k}"] = vi
        paired[f"delta_{k}_proposed_minus_prediction"] = vi - vp
    if np.isfinite(paired["prediction_only_nll"]) and abs(paired["prediction_only_nll"]) > 1e-9:
        paired["nll_improvement_pct"] = 100.0 * (
            paired["prediction_only_nll"] - paired["proposed_nll"]
        ) / abs(paired["prediction_only_nll"])
    else:
        paired["nll_improvement_pct"] = float("nan")

    final_state = {
        "pred_lam": pred.lam.copy(),
        "prop_lam": prop.lam.copy(),
        "truth_events_rel": truth_xy_rel,
        "interventions_rel": np.asarray([(x, y) for (x, y, _t) in intervention_events_rel], dtype=float)
        if intervention_events_rel else np.empty((0, 2), dtype=float),
    }

    return {
        "paired_metrics": paired,
        "eval_rows": eval_rows,
        "timeseries_rows": timeseries_rows,
        "final_state": final_state,
    }


def _plot_eval_timeseries(eval_df: pd.DataFrame, out_png: Path):
    if eval_df.empty:
        return
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for metric, ax in [("recall_at_k", axes[0]), ("precision_at_k", axes[1])]:
        for model in ["prediction_only", "proposed"]:
            d = eval_df[eval_df["model"] == model]
            if d.empty:
                continue
            g = d.groupby("t_s")[metric].agg(["mean", "std"]).reset_index()
            ax.plot(g["t_s"], g["mean"], label=model, lw=1.8)
            lo = g["mean"] - g["std"].fillna(0.0)
            hi = g["mean"] + g["std"].fillna(0.0)
            ax.fill_between(g["t_s"], lo, hi, alpha=0.15)
        ax.set_ylabel(metric)
        ax.grid(alpha=0.25)
    axes[0].set_title("SESTPP Subsystem Forecast Quality Over Time")
    axes[1].set_xlabel("Simulation time after warmup (s)")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _plot_run_deltas(run_df: pd.DataFrame, out_png: Path):
    if run_df.empty:
        return
    metrics = [
        ("delta_forecast_recall_at_k_proposed_minus_prediction", "Recall@k delta"),
        ("delta_forecast_precision_at_k_proposed_minus_prediction", "Precision@k delta"),
        ("nll_improvement_pct", "NLL improvement (%)"),
        ("delta_mean_log_lambda_at_events_proposed_minus_prediction", "Mean log lambda@events delta"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    axes = axes.ravel()
    for ax, (col, title) in zip(axes, metrics):
        if col not in run_df.columns:
            ax.set_axis_off()
            continue
        vals = run_df[col].to_numpy(dtype=float)
        ax.bar(np.arange(len(vals)), vals)
        ax.axhline(0.0, color="k", lw=0.8)
        ax.set_title(title)
        ax.set_xlabel("run")
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _plot_final_maps(final_state: dict, cfg: SubsystemConfig, out_png: Path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharex=True, sharey=True)
    for ax, field, title in [
        (axes[0], final_state["pred_lam"], "Prediction-only final lambda"),
        (axes[1], final_state["prop_lam"], "Proposed final lambda"),
    ]:
        im = ax.imshow(
            field,
            origin="lower",
            extent=(0.0, cfg.W, 0.0, cfg.H),
            cmap="magma",
            aspect="auto",
        )
        truth = final_state["truth_events_rel"]
        if truth.size > 0:
            n_keep = min(cfg.final_map_recent_truth, truth.shape[0])
            tplot = truth[-n_keep:, :]
            ax.scatter(tplot[:, 0], tplot[:, 1], s=12, c="#39a845", marker="x", alpha=0.65, label="truth")
        ints = final_state["interventions_rel"]
        if ints.size > 0:
            n_keep_i = min(cfg.final_map_recent_interventions, ints.shape[0])
            iplot = ints[-n_keep_i:, :]
            ax.scatter(iplot[:, 0], iplot[:, 1], s=18, c="#00bcd4", marker="^", alpha=0.70, label="interventions")
        ax.set_title(title)
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        ax.legend(loc="upper right")
        plt.colorbar(im, ax=ax, shrink=0.9)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _aggregate_summary(run_df: pd.DataFrame):
    out = {}
    metrics = [
        "delta_forecast_recall_at_k_proposed_minus_prediction",
        "delta_forecast_precision_at_k_proposed_minus_prediction",
        "delta_forecast_hit_rate_proposed_minus_prediction",
        "delta_forecast_lead_time_s_proposed_minus_prediction",
        "delta_nll_proposed_minus_prediction",
        "nll_improvement_pct",
        "delta_mean_log_lambda_at_events_proposed_minus_prediction",
        "delta_mean_lambda_at_events_proposed_minus_prediction",
    ]
    for m in metrics:
        if m not in run_df.columns:
            continue
        arr = run_df[m].to_numpy(dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            out[m] = {"mean": float("nan"), "std": float("nan"), "n": 0}
            continue
        out[m] = {
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "n": int(arr.size),
        }
    return out


def _make_report(cfg: SubsystemConfig, run_df: pd.DataFrame, summary: dict):
    lines = []
    lines.append("# SESTPP Subsystem Isolation Report")
    lines.append("")
    lines.append("This test isolates the intensity-model subsystem from task generation and assignment.")
    lines.append("Both models receive the same detections from the same truth stream.")
    lines.append("Only the proposed model receives replayed intervention events.")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    for k, v in asdict(cfg).items():
        lines.append(f"- `{k}`: `{v}`")
    lines.append("")
    lines.append("## Per-run results")
    lines.append("")
    show_cols = [
        "run_idx",
        "seed",
        "truth_events",
        "interventions_truth_replayed",
        "interventions_model_replayed",
        "prediction_only_forecast_recall_at_k",
        "proposed_forecast_recall_at_k",
        "delta_forecast_recall_at_k_proposed_minus_prediction",
        "prediction_only_nll",
        "proposed_nll",
        "nll_improvement_pct",
    ]
    keep = [c for c in show_cols if c in run_df.columns]
    lines.append(run_df[keep].round(4).to_markdown(index=False))
    lines.append("")
    lines.append("## Aggregate deltas (proposed - prediction_only unless noted)")
    lines.append("")
    for k, st in summary.items():
        lines.append(f"- `{k}`: mean={st['mean']:.6f}, std={st['std']:.6f}, n={st['n']}")
    lines.append("")

    # Critical interpretation
    d_recall = summary.get("delta_forecast_recall_at_k_proposed_minus_prediction", {}).get("mean", float("nan"))
    d_prec = summary.get("delta_forecast_precision_at_k_proposed_minus_prediction", {}).get("mean", float("nan"))
    nll_gain = summary.get("nll_improvement_pct", {}).get("mean", float("nan"))
    lines.append("## Critical interpretation")
    lines.append("")
    if np.isfinite(d_recall) and np.isfinite(d_prec) and np.isfinite(nll_gain):
        if (d_recall > 0.0) and (d_prec > 0.0) and (nll_gain > 0.0):
            lines.append("- Proposed SESTPP is better on isolated forecasting metrics in this setup.")
            lines.append("- Remaining closed-loop underperformance is more likely in task generation/dispatch policy.")
        else:
            lines.append("- Proposed SESTPP is not consistently better in isolation yet.")
            lines.append("- This indicates parameter mismatch or intervention replay realism issues, not only task-generation issues.")
    else:
        lines.append("- Insufficient finite metrics to conclude; check event/intervention volume and horizon.")
    lines.append("- This subsystem test is necessary but not sufficient for thesis claims; keep full baseline experiments.")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="SESTPP subsystem isolation diagnostic")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--T-end", type=float, default=10800.0)
    parser.add_argument("--warmup-s", type=float, default=1800.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--outdir", type=str, default="results/sestpp_subsystem")
    parser.add_argument("--intervention-prob", type=float, default=0.45)
    parser.add_argument("--intervention-cooldown-s", type=float, default=40.0)
    parser.add_argument("--intervention-delay-s", type=float, default=10.0)
    parser.add_argument("--intervention-shuffle", choices=["none", "space", "time", "spacetime"], default="none")
    parser.add_argument("--shuffle-time-window-s", type=float, default=300.0)
    parser.add_argument("--beta-true", type=float, default=0.30)
    parser.add_argument("--model-omega-inhib", type=float, default=SubsystemConfig.model_omega_inhib)
    parser.add_argument("--model-alpha-inhib", type=float, default=SubsystemConfig.model_alpha_inhib)
    parser.add_argument("--model-mu-base", type=float, default=SubsystemConfig.model_mu_base)
    parser.add_argument("--model-bg-ema", type=float, default=SubsystemConfig.model_bg_ema)
    args = parser.parse_args()

    cfg = SubsystemConfig(
        runs=int(args.runs),
        seed_start=int(args.seed_start),
        T_end=float(args.T_end),
        warmup_s=float(args.warmup_s),
        dt=float(args.dt),
        intervention_prob=float(args.intervention_prob),
        intervention_cooldown_s=float(args.intervention_cooldown_s),
        intervention_delay_s=float(args.intervention_delay_s),
        intervention_shuffle=str(args.intervention_shuffle),
        shuffle_time_window_s=float(args.shuffle_time_window_s),
        beta_true=float(args.beta_true),
        model_omega_inhib=float(args.model_omega_inhib),
        model_alpha_inhib=float(args.model_alpha_inhib),
        model_mu_base=float(args.model_mu_base),
        model_bg_ema=float(args.model_bg_ema),
    )

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    run_rows = []
    eval_rows = []
    ts_rows = []
    final_state_last = None

    for i in range(cfg.runs):
        seed = cfg.seed_start + i
        res = simulate_one_run(i, seed, cfg)
        run_rows.append(res["paired_metrics"])
        eval_rows.extend(res["eval_rows"])
        ts_rows.extend(res["timeseries_rows"])
        final_state_last = res["final_state"]
        print(
            f"[run {i+1}/{cfg.runs} seed={seed}] "
            f"nll_improve={res['paired_metrics'].get('nll_improvement_pct', float('nan')):.3f}% "
            f"d_recall={res['paired_metrics'].get('delta_forecast_recall_at_k_proposed_minus_prediction', float('nan')):.4f}"
        )

    run_df = pd.DataFrame(run_rows)
    eval_df = pd.DataFrame(eval_rows)
    ts_df = pd.DataFrame(ts_rows)
    summary = _aggregate_summary(run_df)
    report_md = _make_report(cfg, run_df, summary)

    run_csv = outdir / "sestpp_subsystem_per_run.csv"
    eval_csv = outdir / "sestpp_subsystem_per_eval.csv"
    ts_csv = outdir / "sestpp_subsystem_timeseries.csv"
    summary_json = outdir / "sestpp_subsystem_summary.json"
    report_path = outdir / "sestpp_subsystem_report.md"

    run_df.to_csv(run_csv, index=False)
    eval_df.to_csv(eval_csv, index=False)
    ts_df.to_csv(ts_csv, index=False)
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump({"config": asdict(cfg), "summary": summary}, f, indent=2)
    report_path.write_text(report_md, encoding="utf-8")

    _plot_eval_timeseries(eval_df, outdir / "sestpp_subsystem_forecast_timeseries.png")
    _plot_run_deltas(run_df, outdir / "sestpp_subsystem_run_deltas.png")
    if final_state_last is not None:
        _plot_final_maps(final_state_last, cfg, outdir / "sestpp_subsystem_final_maps.png")

    print("Saved:")
    print(f"- {run_csv}")
    print(f"- {eval_csv}")
    print(f"- {ts_csv}")
    print(f"- {summary_json}")
    print(f"- {report_path}")
    print(f"- {outdir / 'sestpp_subsystem_forecast_timeseries.png'}")
    print(f"- {outdir / 'sestpp_subsystem_run_deltas.png'}")
    print(f"- {outdir / 'sestpp_subsystem_final_maps.png'}")


if __name__ == "__main__":
    main()
