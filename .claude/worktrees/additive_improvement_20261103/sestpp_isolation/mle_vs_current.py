from __future__ import annotations

import argparse
import heapq
import json
import math
from dataclasses import asdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from SESTPP import OnlineSESTPP as MainlineSESTPP
from sestpp_isolation.paired_benchmark import (
    IsolationConfig,
    _forecast_metrics_for_snapshot,
    _horizon_truth_grids,
    _make_value_sampler,
    _probability_metrics,
    _sample_from_value_map,
    _stats,
    _suppression_keep_prob,
    _truth_time_multiplier,
)


MODEL_ORDER = ("current_fixed", "mle_fitted")


def _build_mainline_model(cfg: IsolationConfig, params: dict | None = None):
    params = params or {}
    return MainlineSESTPP(
        x_min=0.0,
        x_max=cfg.W,
        y_min=0.0,
        y_max=cfg.H,
        nx=cfg.NX,
        ny=cfg.NY,
        sigma=float(params.get("model_sigma", cfg.model_sigma)),
        omega=float(params.get("model_omega", cfg.model_omega)),
        omega_inhib=float(params.get("model_omega_inhib", cfg.model_omega_inhib)),
        alpha_in=float(params.get("model_alpha_in", cfg.model_alpha_in)),
        alpha_cross=float(params.get("model_alpha_cross", cfg.model_alpha_cross)),
        alpha_inhib=float(params.get("model_alpha_inhib", cfg.model_alpha_inhib)),
        mu_base=float(params.get("model_mu_base", cfg.model_mu_base)),
        bg_ema=float(params.get("model_bg_ema", cfg.model_bg_ema)),
    )


def _generate_truth_stream(seed: int, cfg: IsolationConfig) -> dict:
    rng = np.random.default_rng(seed)
    xs, ys, cdf, dx_cell, dy_cell = _make_value_sampler(cfg)
    cell_area = float(dx_cell * dy_cell)
    total_s = float(cfg.warmup_s + cfg.T_end)
    n_steps = int(math.ceil(total_s / max(cfg.dt, 1e-9)))

    truth_times_rel = []
    truth_xy_rel = []
    intervention_events_rel = []

    active_truth_interventions = []
    truth_intervention_queue = []
    model_intervention_queue = []
    offspring_queue = []
    last_intervention_trigger_t = -1e18

    steps = []
    for k in range(n_steps):
        t_abs = float((k + 1) * cfg.dt)
        if t_abs > total_s + 1e-9:
            break

        while truth_intervention_queue and truth_intervention_queue[0][0] <= t_abs + 1e-9:
            ti, xi, yi = heapq.heappop(truth_intervention_queue)
            active_truth_interventions.append({"t": float(ti), "x": float(xi), "y": float(yi)})

        due_interventions = []
        while model_intervention_queue and model_intervention_queue[0][0] <= t_abs + 1e-9:
            ti, xi, yi = heapq.heappop(model_intervention_queue)
            due_interventions.append((float(xi), float(yi), float(ti)))
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

        steps.append(
            {
                "t_abs": t_abs,
                "events": step_events,
                "interventions": due_interventions,
            }
        )

    truth_times_rel = np.asarray(truth_times_rel, dtype=float)
    truth_xy_rel = np.asarray(truth_xy_rel, dtype=float) if truth_xy_rel else np.empty((0, 2), dtype=float)
    return {
        "seed": int(seed),
        "cell_area": cell_area,
        "steps": steps,
        "truth_times_rel": truth_times_rel,
        "truth_xy_rel": truth_xy_rel,
        "intervention_events_rel": intervention_events_rel,
    }


def _pack_theta(cfg: IsolationConfig) -> np.ndarray:
    return np.array(
        [
            math.log(max(cfg.model_sigma, 1e-6)),
            math.log(max(cfg.model_omega, 1e-6)),
            math.log(max(cfg.model_omega_inhib, 1e-6)),
            math.log(max(cfg.model_alpha_in, 1e-6)),
            math.log(max(cfg.model_alpha_inhib, 1e-6)),
            math.log(max(cfg.model_mu_base, 1e-12)),
        ],
        dtype=float,
    )


def _theta_to_params(theta: np.ndarray) -> dict:
    sigma = float(np.clip(np.exp(theta[0]), 4.0, 40.0))
    omega = float(np.clip(np.exp(theta[1]), 60.0, 3600.0))
    omega_inhib = float(np.clip(np.exp(theta[2]), 60.0, 3600.0))
    alpha_in = float(np.clip(np.exp(theta[3]), 1.0e-3, 2.0))
    alpha_inhib = float(np.clip(np.exp(theta[4]), 1.0e-4, 2.0))
    mu_base = float(np.clip(np.exp(theta[5]), 1.0e-7, 1.0e-2))
    return {
        "model_sigma": sigma,
        "model_omega": omega,
        "model_omega_inhib": omega_inhib,
        "model_alpha_in": alpha_in,
        "model_alpha_inhib": alpha_inhib,
        "model_mu_base": mu_base,
    }


def _training_nll(stream: dict, cfg: IsolationConfig, params: dict) -> float:
    model = _build_mainline_model(cfg, params=params)
    cell_area = float(stream["cell_area"])
    eps = 1e-12
    ll = 0.0

    for step in stream["steps"]:
        t_abs = float(step["t_abs"])
        if t_abs > cfg.warmup_s + 1e-9:
            break

        model.advance_time(cfg.dt)
        for xi, yi, _ti in step["interventions"]:
            model.add_intervention_event(
                xi,
                yi,
                weight=1.0,
                sigma=cfg.intervention_sigma,
                omega_inhib=cfg.intervention_omega,
            )

        lam_snapshot = model.lam
        ll -= float(np.sum(lam_snapshot) * cell_area * cfg.dt)
        for xe, ye, _te in step["events"]:
            iy, ix = model.world_to_idx(xe, ye)
            lv = max(float(lam_snapshot[iy, ix]), eps)
            ll += math.log(lv)

        for xe, ye, _te in step["events"]:
            model.add_local_event(xe, ye)

    return float(-ll)


def _evaluate_model(stream: dict, cfg: IsolationConfig, params: dict) -> dict:
    model = _build_mainline_model(cfg, params=params)
    cell_area = float(stream["cell_area"])
    truth_times_rel = stream["truth_times_rel"]
    truth_xy_rel = stream["truth_xy_rel"]
    horizon_s = float(cfg.forecast_horizon_s)
    horizon_scale = max(cell_area * horizon_s, 1e-9)
    eps = 1e-12

    train_ll = 0.0
    eval_ll = 0.0
    eval_snapshots = []
    next_eval_t = float(cfg.warmup_s)

    for step in stream["steps"]:
        model.advance_time(cfg.dt)
        for xi, yi, _ti in step["interventions"]:
            model.add_intervention_event(
                xi,
                yi,
                weight=1.0,
                sigma=cfg.intervention_sigma,
                omega_inhib=cfg.intervention_omega,
            )

        t_abs = float(step["t_abs"])
        lam_snapshot = model.lam
        ll_target = None
        if t_abs <= cfg.warmup_s + 1e-9:
            ll_target = "train"
            train_ll -= float(np.sum(lam_snapshot) * cell_area * cfg.dt)
        else:
            ll_target = "eval"
            eval_ll -= float(np.sum(lam_snapshot) * cell_area * cfg.dt)

        for xe, ye, _te in step["events"]:
            iy, ix = model.world_to_idx(xe, ye)
            lv = max(float(lam_snapshot[iy, ix]), eps)
            if ll_target == "train":
                train_ll += math.log(lv)
            else:
                eval_ll += math.log(lv)

        for xe, ye, _te in step["events"]:
            model.add_local_event(xe, ye)

        if t_abs >= next_eval_t - 1e-9:
            t_rel = float(t_abs - cfg.warmup_s)
            if t_rel >= 0.0:
                hs = model.hotspots(
                    top_k=cfg.forecast_top_k,
                    merge_radius=cfg.match_radius_m,
                    use_excess=True,
                    mask_poly=None,
                )
                eval_snapshots.append(
                    {
                        "t_s": t_rel,
                        "lam": model.lam.copy(),
                        "hotspots": [(float(h["x"]), float(h["y"])) for h in hs],
                    }
                )
            next_eval_t += cfg.eval_period_s

    eval_rows = []
    for snap in eval_snapshots:
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
                "t_s": float(snap["t_s"]),
                "future_event_count": int(future_event_count),
                **prob_metrics,
                **forecast_metrics,
            }
        )

    eval_df = pd.DataFrame(eval_rows)

    def _agg(metric_name: str) -> float:
        arr = eval_df[metric_name].to_numpy(dtype=float) if metric_name in eval_df.columns else np.array([], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return float("nan")
        return float(np.mean(arr))

    return {
        "train_nll": float(-train_ll),
        "eval_nll": float(-eval_ll),
        "eval_rows": eval_rows,
        "metrics": {
            "field_brier": _agg("field_brier"),
            "field_logloss": _agg("field_logloss"),
            "field_rate_l1": _agg("field_rate_l1"),
            "event_cell_probability_mean": _agg("event_cell_probability_mean"),
            "non_event_cell_probability_mean": _agg("non_event_cell_probability_mean"),
            "forecast_recall_at_k": _agg("forecast_recall_at_k"),
            "forecast_precision_at_k": _agg("forecast_precision_at_k"),
            "forecast_hit_rate": _agg("forecast_hit_rate"),
            "forecast_lead_time_s": _agg("forecast_lead_time_s"),
        },
    }


def _fit_mle_params(stream: dict, cfg: IsolationConfig, maxiter: int, restarts: int, jitter: float, seed: int) -> dict:
    x0 = _pack_theta(cfg)
    rng = np.random.default_rng(seed + 99173)

    starts = [x0]
    for _ in range(max(0, restarts - 1)):
        starts.append(x0 + rng.normal(0.0, jitter, size=x0.shape))

    best = None
    objective_trace = []
    for start in starts:
        res = minimize(
            fun=lambda th: _training_nll(stream, cfg, _theta_to_params(np.asarray(th, dtype=float))),
            x0=np.asarray(start, dtype=float),
            method="Powell",
            options={"maxiter": int(maxiter), "disp": False},
        )
        objective_trace.append(float(res.fun))
        if (best is None) or (float(res.fun) < float(best.fun)):
            best = res

    assert best is not None
    best_params = _theta_to_params(np.asarray(best.x, dtype=float))
    return {
        "params": best_params,
        "objective_trace": objective_trace,
        "optimizer_success": bool(best.success),
        "optimizer_status": int(best.status),
        "optimizer_message": str(best.message),
        "train_nll": float(best.fun),
        "num_restarts": int(restarts),
    }


def simulate_one_run(
    run_idx: int,
    seed: int,
    cfg: IsolationConfig,
    mle_maxiter: int,
    mle_restarts: int,
    mle_jitter: float,
):
    stream = _generate_truth_stream(seed, cfg)
    fit = _fit_mle_params(
        stream=stream,
        cfg=cfg,
        maxiter=mle_maxiter,
        restarts=mle_restarts,
        jitter=mle_jitter,
        seed=seed,
    )

    current_eval = _evaluate_model(stream, cfg, params={})
    mle_eval = _evaluate_model(stream, cfg, params=fit["params"])

    paired = {
        "run_idx": int(run_idx),
        "seed": int(seed),
        "truth_events": int(stream["truth_times_rel"].size),
        "interventions_replayed": int(len(stream["intervention_events_rel"])),
        "mle_optimizer_success": int(fit["optimizer_success"]),
        "mle_optimizer_status": int(fit["optimizer_status"]),
        "mle_train_nll_objective": float(fit["train_nll"]),
    }

    for key, value in fit["params"].items():
        paired[f"fitted_{key}"] = float(value)

    metric_names = [
        "train_nll",
        "eval_nll",
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

    current_metrics = {"train_nll": current_eval["train_nll"], "eval_nll": current_eval["eval_nll"], **current_eval["metrics"]}
    mle_metrics = {"train_nll": mle_eval["train_nll"], "eval_nll": mle_eval["eval_nll"], **mle_eval["metrics"]}

    for metric in metric_names:
        paired[f"current_fixed_{metric}"] = float(current_metrics[metric])
        paired[f"mle_fitted_{metric}"] = float(mle_metrics[metric])
        paired[f"delta_{metric}_mle_minus_current"] = float(mle_metrics[metric] - current_metrics[metric])

    for metric in ("train_nll", "eval_nll", "field_brier", "field_logloss", "field_rate_l1"):
        baseline = float(current_metrics[metric])
        candidate = float(mle_metrics[metric])
        if np.isfinite(baseline) and abs(baseline) > 1e-12:
            paired[f"{metric}_improvement_pct"] = 100.0 * (baseline - candidate) / abs(baseline)
        else:
            paired[f"{metric}_improvement_pct"] = float("nan")

    eval_rows = []
    for model_name, model_eval in (("current_fixed", current_eval), ("mle_fitted", mle_eval)):
        for row in model_eval["eval_rows"]:
            eval_rows.append(
                {
                    "run_idx": int(run_idx),
                    "seed": int(seed),
                    "model": model_name,
                    **row,
                }
            )

    return {
        "paired_metrics": paired,
        "eval_rows": eval_rows,
        "fit": fit,
    }


def _make_summary(run_df: pd.DataFrame) -> pd.DataFrame:
    metric_cols = [
        "delta_train_nll_mle_minus_current",
        "delta_eval_nll_mle_minus_current",
        "delta_field_brier_mle_minus_current",
        "delta_field_logloss_mle_minus_current",
        "delta_field_rate_l1_mle_minus_current",
        "delta_forecast_recall_at_k_mle_minus_current",
        "delta_forecast_precision_at_k_mle_minus_current",
        "delta_forecast_hit_rate_mle_minus_current",
        "delta_forecast_lead_time_s_mle_minus_current",
        "train_nll_improvement_pct",
        "eval_nll_improvement_pct",
        "field_brier_improvement_pct",
        "field_logloss_improvement_pct",
        "field_rate_l1_improvement_pct",
    ]
    rows = []
    for metric in metric_cols:
        if metric not in run_df.columns:
            continue
        stats = _stats(run_df[metric].to_numpy(dtype=float))
        rows.append({"metric": metric, **stats})
    return pd.DataFrame(rows)


def _plot_eval_timeseries(eval_df: pd.DataFrame, out_png: Path):
    if eval_df.empty:
        return
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
    plot_specs = [
        ("field_logloss", "Field Log Loss"),
        ("field_brier", "Field Brier"),
        ("forecast_recall_at_k", "Recall@k"),
        ("forecast_precision_at_k", "Precision@k"),
    ]
    for ax, (metric, title) in zip(axes.ravel(), plot_specs):
        for model_name in MODEL_ORDER:
            d = eval_df[eval_df["model"] == model_name]
            if d.empty:
                continue
            g = d.groupby("t_s")[metric].agg(["mean", "std"]).reset_index()
            ax.plot(g["t_s"], g["mean"], label=model_name, lw=1.8)
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


def _make_report(
    cfg: IsolationConfig,
    run_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    mle_maxiter: int,
    mle_restarts: int,
) -> str:
    lines = []
    lines.append("# SESTPP MLE vs Current")
    lines.append("")
    lines.append("This benchmark fits a maximum-likelihood-style version of the current SESTPP on the warmup segment, then compares held-out realism metrics against the current fixed-parameter model.")
    lines.append("Both models use the same SESTPP structure from `SESTPP.py`; only the parameter estimation method differs.")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    for key, value in asdict(cfg).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append(f"- `mle_maxiter`: `{mle_maxiter}`")
    lines.append(f"- `mle_restarts`: `{mle_restarts}`")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- Better training NLL alone is not enough; realism should be judged mainly by held-out `eval_nll`, field log loss, field Brier, and forecast metrics.")
    lines.append("- Negative `delta_*_mle_minus_current` is better for losses and positive is better for recall or precision.")
    lines.append("- On synthetic truth, this measures realism with respect to the simulator, not necessarily real-world vineyard behavior.")
    lines.append("")
    lines.append("## Per-Run Snapshot")
    lines.append("")
    show_cols = [
        "run_idx",
        "seed",
        "truth_events",
        "current_fixed_train_nll",
        "mle_fitted_train_nll",
        "delta_train_nll_mle_minus_current",
        "current_fixed_eval_nll",
        "mle_fitted_eval_nll",
        "delta_eval_nll_mle_minus_current",
        "current_fixed_field_logloss",
        "mle_fitted_field_logloss",
        "delta_field_logloss_mle_minus_current",
        "current_fixed_forecast_recall_at_k",
        "mle_fitted_forecast_recall_at_k",
        "delta_forecast_recall_at_k_mle_minus_current",
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

    d_train = _summary_mean("delta_train_nll_mle_minus_current")
    d_eval = _summary_mean("delta_eval_nll_mle_minus_current")
    d_logloss = _summary_mean("delta_field_logloss_mle_minus_current")
    d_brier = _summary_mean("delta_field_brier_mle_minus_current")
    d_recall = _summary_mean("delta_forecast_recall_at_k_mle_minus_current")
    d_prec = _summary_mean("delta_forecast_precision_at_k_mle_minus_current")

    lines.append("## Readout")
    lines.append("")
    if all(np.isfinite(x) for x in (d_train, d_eval, d_logloss, d_brier)):
        if d_train < 0.0 and d_eval < 0.0 and d_logloss < 0.0 and d_brier < 0.0:
            if np.isfinite(d_recall) and np.isfinite(d_prec) and d_recall >= 0.0 and d_prec >= 0.0:
                lines.append("- The MLE-fitted model improved both fit and held-out forecast quality in this run set.")
            else:
                lines.append("- The MLE-fitted model improved held-out calibration, but hotspot metrics are not uniformly better yet.")
        elif d_train < 0.0 and not (d_eval < 0.0 and d_logloss < 0.0 and d_brier < 0.0):
            lines.append("- The MLE fit improved training likelihood but did not clearly improve held-out realism.")
        else:
            lines.append("- The MLE fit did not beat the current fixed model on the main held-out metrics in this run set.")
    else:
        lines.append("- Not enough finite metrics were available to interpret the comparison.")
    lines.append("- If you want to claim real-world realism, replace the synthetic truth stream with held-out logged field detections and interventions.")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Held-out MLE vs current SESTPP comparison")
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--T-end", type=float, default=3600.0)
    parser.add_argument("--warmup-s", type=float, default=900.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--eval-period-s", type=float, default=30.0)
    parser.add_argument("--forecast-horizon-s", type=float, default=300.0)
    parser.add_argument("--outdir", type=str, default="results/sestpp_mle_vs_current")
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
    parser.add_argument("--mle-maxiter", type=int, default=30)
    parser.add_argument("--mle-restarts", type=int, default=2)
    parser.add_argument("--mle-jitter", type=float, default=0.30)
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
    fit_rows = []
    for run_idx in range(cfg.runs):
        seed = cfg.seed_start + run_idx
        res = simulate_one_run(
            run_idx=run_idx,
            seed=seed,
            cfg=cfg,
            mle_maxiter=int(args.mle_maxiter),
            mle_restarts=int(args.mle_restarts),
            mle_jitter=float(args.mle_jitter),
        )
        run_rows.append(res["paired_metrics"])
        eval_rows.extend(res["eval_rows"])
        fit_rows.append(
            {
                "run_idx": int(run_idx),
                "seed": int(seed),
                **{k: v for k, v in res["fit"].items() if k != "params"},
                **res["fit"]["params"],
            }
        )
        print(
            f"[run {run_idx + 1}/{cfg.runs}] seed={seed} "
            f"train_nll_delta={res['paired_metrics'].get('delta_train_nll_mle_minus_current', float('nan')):.6f} "
            f"eval_nll_delta={res['paired_metrics'].get('delta_eval_nll_mle_minus_current', float('nan')):.6f}"
        )

    run_df = pd.DataFrame(run_rows)
    eval_df = pd.DataFrame(eval_rows)
    fit_df = pd.DataFrame(fit_rows)
    summary_df = _make_summary(run_df)

    per_run_csv = outdir / "mle_vs_current_per_run.csv"
    per_eval_csv = outdir / "mle_vs_current_per_eval.csv"
    fit_csv = outdir / "mle_fit_details.csv"
    summary_csv = outdir / "mle_vs_current_summary.csv"
    report_md = outdir / "mle_vs_current_report.md"
    plot_png = outdir / "mle_vs_current_timeseries.png"
    manifest_json = outdir / "manifest.json"

    run_df.to_csv(per_run_csv, index=False)
    eval_df.to_csv(per_eval_csv, index=False)
    fit_df.to_csv(fit_csv, index=False)
    summary_df.to_csv(summary_csv, index=False)
    report_md.write_text(
        _make_report(
            cfg=cfg,
            run_df=run_df,
            summary_df=summary_df,
            mle_maxiter=int(args.mle_maxiter),
            mle_restarts=int(args.mle_restarts),
        )
        + "\n",
        encoding="utf-8",
    )
    _plot_eval_timeseries(eval_df, plot_png)
    manifest_json.write_text(
        json.dumps(
            {
                "config": asdict(cfg),
                "mle": {
                    "maxiter": int(args.mle_maxiter),
                    "restarts": int(args.mle_restarts),
                    "jitter": float(args.mle_jitter),
                },
                "outputs": {
                    "per_run_csv": str(per_run_csv),
                    "per_eval_csv": str(per_eval_csv),
                    "fit_csv": str(fit_csv),
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

    print("Wrote:")
    print(f"- {per_run_csv}")
    print(f"- {per_eval_csv}")
    print(f"- {fit_csv}")
    print(f"- {summary_csv}")
    print(f"- {report_md}")
    print(f"- {plot_png}")
    print(f"- {manifest_json}")


if __name__ == "__main__":
    main()
