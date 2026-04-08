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

from diagnostics.diagnostic_sestpp_subsystem import (
    SubsystemConfig,
    _build_model,
    _make_value_sampler,
    _sample_from_value_map,
    _suppression_keep_prob,
)


def _horizon_truth_grids(t_eval: float, horizon_s: float, truth_times: np.ndarray, truth_xy: np.ndarray, model):
    i0 = int(np.searchsorted(truth_times, t_eval, side="right"))
    i1 = int(np.searchsorted(truth_times, t_eval + horizon_s, side="right"))
    fut_xy = truth_xy[i0:i1]
    count_grid = np.zeros_like(model.lam, dtype=float)
    for ex, ey in fut_xy:
        iy, ix = model.world_to_idx(float(ex), float(ey))
        count_grid[iy, ix] += 1.0
    occ_grid = (count_grid > 0.0).astype(float)
    return occ_grid, count_grid, int(len(fut_xy))


def _probability_metrics(prob: np.ndarray, occ_grid: np.ndarray, count_grid: np.ndarray, cell_area: float, horizon_s: float):
    eps = 1e-9
    p = np.clip(prob.astype(float), eps, 1.0 - eps)
    y = occ_grid.astype(float)
    truth_rate = count_grid.astype(float) / max(cell_area * horizon_s, eps)

    brier = float(np.mean((p - y) ** 2))
    logloss = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
    rate_l1 = float(np.mean(np.abs(((-np.log1p(-p)) / max(cell_area * horizon_s, eps)) - truth_rate)))
    rate_l2 = float(np.sqrt(np.mean((((-np.log1p(-p)) / max(cell_area * horizon_s, eps)) - truth_rate) ** 2)))

    event_mask = y > 0.5
    nonevent_mask = ~event_mask
    event_prob_mean = float(np.mean(p[event_mask])) if np.any(event_mask) else float("nan")
    nonevent_prob_mean = float(np.mean(p[nonevent_mask])) if np.any(nonevent_mask) else float("nan")
    occupied_frac = float(np.mean(y))

    return {
        "field_brier": brier,
        "field_logloss": logloss,
        "field_rate_l1": rate_l1,
        "field_rate_l2": rate_l2,
        "event_cell_probability_mean": event_prob_mean,
        "non_event_cell_probability_mean": nonevent_prob_mean,
        "truth_occupied_cell_fraction": occupied_frac,
    }


def simulate_one_run(run_idx: int, seed: int, cfg: SubsystemConfig):
    rng = np.random.default_rng(seed)
    pred = _build_model(cfg)
    prop = _build_model(cfg)

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

    eval_snapshots = []
    ll = {"prediction_only": 0.0, "proposed": 0.0}
    eps = 1e-12

    for k in range(n_steps):
        t_abs = float((k + 1) * cfg.dt)
        if t_abs > total_s + 1e-9:
            break

        pred.advance_time(cfg.dt)
        prop.advance_time(cfg.dt)

        while truth_intervention_queue and truth_intervention_queue[0][0] <= t_abs + 1e-9:
            ti, xi, yi = heapq.heappop(truth_intervention_queue)
            active_truth_interventions.append({"t": float(ti), "x": float(xi), "y": float(yi)})

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

        t_keep = t_abs - 5.0 * max(cfg.intervention_omega, cfg.omega_true)
        if active_truth_interventions:
            active_truth_interventions = [ev for ev in active_truth_interventions if float(ev["t"]) >= t_keep]

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

        lam_pred = pred.lam
        lam_prop = prop.lam
        step_events = []
        for xe, ye, te in candidates:
            p_keep, _s_val = _suppression_keep_prob(xe, ye, te, active_truth_interventions, cfg)
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
            ll["prediction_only"] -= float(np.sum(lam_pred) * cell_area * cfg.dt)
            ll["proposed"] -= float(np.sum(lam_prop) * cell_area * cfg.dt)
            for xe, ye, _te in step_events:
                iy_p, ix_p = pred.world_to_idx(xe, ye)
                iy_i, ix_i = prop.world_to_idx(xe, ye)
                lv_pred = max(float(lam_pred[iy_p, ix_p]), eps)
                lv_prop = max(float(lam_prop[iy_i, ix_i]), eps)
                ll["prediction_only"] += math.log(lv_pred)
                ll["proposed"] += math.log(lv_prop)

        for xe, ye, _te in step_events:
            pred.add_local_event(xe, ye)
            prop.add_local_event(xe, ye)

        if t_abs >= next_eval_t - 1e-9:
            t_rel = float(t_abs - cfg.warmup_s)
            if t_rel >= 0.0:
                eval_snapshots.append(
                    {
                        "run_idx": int(run_idx),
                        "seed": int(seed),
                        "t_s": float(t_rel),
                        "pred_lam": pred.lam.copy(),
                        "prop_lam": prop.lam.copy(),
                    }
                )
            next_eval_t += cfg.eval_period_s

    truth_times_rel = np.asarray(truth_times_rel, dtype=float)
    truth_xy_rel = np.asarray(truth_xy_rel, dtype=float) if truth_xy_rel else np.empty((0, 2), dtype=float)

    eval_rows = []
    final_maps = None
    horizon_s = float(cfg.forecast_horizon_s)
    horizon_scale = max(cell_area * horizon_s, 1e-9)

    for snap in eval_snapshots:
        occ_grid, count_grid, future_event_count = _horizon_truth_grids(
            t_eval=float(snap["t_s"]),
            horizon_s=horizon_s,
            truth_times=truth_times_rel,
            truth_xy=truth_xy_rel,
            model=pred,
        )
        pred_prob = 1.0 - np.exp(-np.clip(snap["pred_lam"], 0.0, None) * horizon_scale)
        prop_prob = 1.0 - np.exp(-np.clip(snap["prop_lam"], 0.0, None) * horizon_scale)

        pred_metrics = _probability_metrics(pred_prob, occ_grid, count_grid, cell_area, horizon_s)
        prop_metrics = _probability_metrics(prop_prob, occ_grid, count_grid, cell_area, horizon_s)

        row = {
            "run_idx": int(run_idx),
            "seed": int(seed),
            "t_s": float(snap["t_s"]),
            "future_event_count": int(future_event_count),
            "truth_occupied_cell_count": int(np.sum(occ_grid)),
        }
        for key, val in pred_metrics.items():
            row[f"prediction_only_{key}"] = float(val)
        for key, val in prop_metrics.items():
            row[f"proposed_{key}"] = float(val)
        row["delta_field_brier_proposed_minus_prediction"] = (
            row["proposed_field_brier"] - row["prediction_only_field_brier"]
        )
        row["delta_field_logloss_proposed_minus_prediction"] = (
            row["proposed_field_logloss"] - row["prediction_only_field_logloss"]
        )
        row["delta_field_rate_l1_proposed_minus_prediction"] = (
            row["proposed_field_rate_l1"] - row["prediction_only_field_rate_l1"]
        )
        row["delta_event_cell_probability_mean_proposed_minus_prediction"] = (
            row["proposed_event_cell_probability_mean"] - row["prediction_only_event_cell_probability_mean"]
        )
        eval_rows.append(row)

        final_maps = {
            "truth_occ": occ_grid,
            "pred_prob": pred_prob,
            "prop_prob": prop_prob,
        }

    eval_df = pd.DataFrame(eval_rows)

    def _agg(metric_name: str):
        arr = eval_df[metric_name].to_numpy(dtype=float) if metric_name in eval_df.columns else np.array([], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return float("nan")
        return float(np.mean(arr))

    paired = {
        "run_idx": int(run_idx),
        "seed": int(seed),
        "truth_events": int(truth_times_rel.size),
        "prediction_only_field_brier": _agg("prediction_only_field_brier"),
        "proposed_field_brier": _agg("proposed_field_brier"),
        "prediction_only_field_logloss": _agg("prediction_only_field_logloss"),
        "proposed_field_logloss": _agg("proposed_field_logloss"),
        "prediction_only_field_rate_l1": _agg("prediction_only_field_rate_l1"),
        "proposed_field_rate_l1": _agg("proposed_field_rate_l1"),
        "prediction_only_event_cell_probability_mean": _agg("prediction_only_event_cell_probability_mean"),
        "proposed_event_cell_probability_mean": _agg("proposed_event_cell_probability_mean"),
        "prediction_only_nll": float(-ll["prediction_only"]),
        "proposed_nll": float(-ll["proposed"]),
    }
    paired["delta_field_brier_proposed_minus_prediction"] = (
        paired["proposed_field_brier"] - paired["prediction_only_field_brier"]
    )
    paired["delta_field_logloss_proposed_minus_prediction"] = (
        paired["proposed_field_logloss"] - paired["prediction_only_field_logloss"]
    )
    paired["delta_field_rate_l1_proposed_minus_prediction"] = (
        paired["proposed_field_rate_l1"] - paired["prediction_only_field_rate_l1"]
    )
    paired["delta_event_cell_probability_mean_proposed_minus_prediction"] = (
        paired["proposed_event_cell_probability_mean"] - paired["prediction_only_event_cell_probability_mean"]
    )
    paired["delta_nll_proposed_minus_prediction"] = (
        paired["proposed_nll"] - paired["prediction_only_nll"]
    )
    if np.isfinite(paired["prediction_only_field_brier"]) and abs(paired["prediction_only_field_brier"]) > 1e-12:
        paired["brier_improvement_pct"] = 100.0 * (
            paired["prediction_only_field_brier"] - paired["proposed_field_brier"]
        ) / abs(paired["prediction_only_field_brier"])
    else:
        paired["brier_improvement_pct"] = float("nan")
    if np.isfinite(paired["prediction_only_field_logloss"]) and abs(paired["prediction_only_field_logloss"]) > 1e-12:
        paired["logloss_improvement_pct"] = 100.0 * (
            paired["prediction_only_field_logloss"] - paired["proposed_field_logloss"]
        ) / abs(paired["prediction_only_field_logloss"])
    else:
        paired["logloss_improvement_pct"] = float("nan")
    if np.isfinite(paired["prediction_only_nll"]) and abs(paired["prediction_only_nll"]) > 1e-12:
        paired["nll_improvement_pct"] = 100.0 * (
            paired["prediction_only_nll"] - paired["proposed_nll"]
        ) / abs(paired["prediction_only_nll"])
    else:
        paired["nll_improvement_pct"] = float("nan")

    return {
        "paired_metrics": paired,
        "eval_rows": eval_rows,
        "final_maps": final_maps,
    }


def _aggregate_summary(run_df: pd.DataFrame):
    out = {}
    metrics = [
        "delta_field_brier_proposed_minus_prediction",
        "delta_field_logloss_proposed_minus_prediction",
        "delta_field_rate_l1_proposed_minus_prediction",
        "delta_event_cell_probability_mean_proposed_minus_prediction",
        "delta_nll_proposed_minus_prediction",
        "brier_improvement_pct",
        "logloss_improvement_pct",
        "nll_improvement_pct",
    ]
    for col in metrics:
        arr = run_df[col].to_numpy(dtype=float) if col in run_df.columns else np.array([], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            out[col] = {"mean": float("nan"), "std": float("nan"), "n": 0}
            continue
        out[col] = {"mean": float(np.mean(arr)), "std": float(np.std(arr)), "n": int(arr.size)}
    return out


def _plot_timeseries(eval_df: pd.DataFrame, out_png: Path):
    if eval_df.empty:
        return
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    pairs = [
        ("field_brier", "Field Brier"),
        ("field_logloss", "Field Log Loss"),
        ("event_cell_probability_mean", "Mean probability on occupied truth cells"),
    ]
    for ax, (metric, title) in zip(axes, pairs):
        for model in ["prediction_only", "proposed"]:
            col = f"{model}_{metric}"
            d = eval_df.groupby("t_s")[col].agg(["mean", "std"]).reset_index()
            ax.plot(d["t_s"], d["mean"], label=model, lw=1.8)
            lo = d["mean"] - d["std"].fillna(0.0)
            hi = d["mean"] + d["std"].fillna(0.0)
            ax.fill_between(d["t_s"], lo, hi, alpha=0.15)
        ax.set_ylabel(title)
        ax.grid(alpha=0.25)
    axes[0].set_title("Field-Level Truth-vs-Model Forecast Diagnostic")
    axes[-1].set_xlabel("Simulation time after warmup (s)")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _plot_final_maps(final_maps: dict, cfg: SubsystemConfig, out_png: Path):
    if not final_maps:
        return
    fig, axes = plt.subplots(2, 2, figsize=(12, 10), sharex=True, sharey=True)
    panels = [
        ("truth_occ", "Truth occupancy field"),
        ("pred_prob", "Prediction-only horizon probability"),
        ("prop_prob", "Proposed horizon probability"),
        ("delta", "Proposed - prediction probability"),
    ]
    delta = final_maps["prop_prob"] - final_maps["pred_prob"]
    for ax, (key, title) in zip(axes.ravel(), panels):
        field = delta if key == "delta" else final_maps[key]
        cmap = "coolwarm" if key == "delta" else "magma"
        im = ax.imshow(
            field,
            origin="lower",
            extent=(0.0, cfg.W, 0.0, cfg.H),
            cmap=cmap,
            aspect="auto",
        )
        ax.set_title(title)
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        plt.colorbar(im, ax=ax, shrink=0.85)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _make_report(cfg: SubsystemConfig, run_df: pd.DataFrame, summary: dict):
    lines = []
    lines.append("# Field-Level Truth-vs-Model Forecast Report")
    lines.append("")
    lines.append("This diagnostic compares forecast probability fields against realized future truth occupancy fields.")
    lines.append("Model lambda is converted to a per-cell horizon event probability with a Poisson approximation.")
    lines.append("Truth is represented as realized occupied cells in the future horizon, not the latent closed-form Hawkes probability field.")
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
        "prediction_only_field_brier",
        "proposed_field_brier",
        "delta_field_brier_proposed_minus_prediction",
        "prediction_only_field_logloss",
        "proposed_field_logloss",
        "delta_field_logloss_proposed_minus_prediction",
        "prediction_only_nll",
        "proposed_nll",
        "delta_nll_proposed_minus_prediction",
        "brier_improvement_pct",
        "logloss_improvement_pct",
        "nll_improvement_pct",
    ]
    keep = [c for c in show_cols if c in run_df.columns]
    lines.append(run_df[keep].round(6).to_markdown(index=False))
    lines.append("")
    lines.append("## Aggregate deltas")
    lines.append("")
    for k, st in summary.items():
        lines.append(f"- `{k}`: mean={st['mean']:.6f}, std={st['std']:.6f}, n={st['n']}")
    lines.append("")
    lines.append("## Critical interpretation")
    lines.append("")
    d_brier = summary.get("delta_field_brier_proposed_minus_prediction", {}).get("mean", float("nan"))
    d_logloss = summary.get("delta_field_logloss_proposed_minus_prediction", {}).get("mean", float("nan"))
    d_event_prob = summary.get("delta_event_cell_probability_mean_proposed_minus_prediction", {}).get("mean", float("nan"))
    d_nll = summary.get("delta_nll_proposed_minus_prediction", {}).get("mean", float("nan"))
    if np.isfinite(d_brier) and np.isfinite(d_logloss):
        if d_brier < 0.0 and d_logloss < 0.0:
            lines.append("- Proposed is better on field-level forecast quality in this setup.")
            lines.append("- If closed-loop performance is still weak, the next bottleneck is planner/task policy rather than the core predictive field.")
        else:
            lines.append("- Proposed is not consistently better on field-level forecast quality yet.")
            lines.append("- That points to model/intervention calibration issues, not only planner-side issues.")
    else:
        lines.append("- Insufficient finite field metrics to conclude; check horizon length and truth event density.")
    if np.isfinite(d_nll):
        lines.append(f"- Proposed minus prediction NLL: {d_nll:.6f} (lower is better).")
    if np.isfinite(d_event_prob):
        lines.append(f"- Proposed minus prediction mean probability on occupied truth cells: {d_event_prob:.6f}.")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Field-level truth-vs-model forecast diagnostic")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--seed-start", type=int, default=2026)
    parser.add_argument("--T-end", type=float, default=10800.0)
    parser.add_argument("--warmup-s", type=float, default=1800.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--forecast-horizon-s", type=float, default=300.0)
    parser.add_argument("--eval-period-s", type=float, default=30.0)
    parser.add_argument("--outdir", type=str, default="results/field_truth_compare")
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
        forecast_horizon_s=float(args.forecast_horizon_s),
        eval_period_s=float(args.eval_period_s),
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
    final_maps = None

    for i in range(cfg.runs):
        seed = cfg.seed_start + i
        res = simulate_one_run(i, seed, cfg)
        run_rows.append(res["paired_metrics"])
        eval_rows.extend(res["eval_rows"])
        final_maps = res["final_maps"]
        print(
            f"[run {i+1}/{cfg.runs} seed={seed}] "
            f"brier_improve={res['paired_metrics'].get('brier_improvement_pct', float('nan')):.3f}% "
            f"logloss_improve={res['paired_metrics'].get('logloss_improvement_pct', float('nan')):.3f}%"
        )

    run_df = pd.DataFrame(run_rows)
    eval_df = pd.DataFrame(eval_rows)
    summary = _aggregate_summary(run_df)
    report_md = _make_report(cfg, run_df, summary)

    run_csv = outdir / "field_truth_compare_per_run.csv"
    eval_csv = outdir / "field_truth_compare_per_eval.csv"
    summary_json = outdir / "field_truth_compare_summary.json"
    report_path = outdir / "field_truth_compare_report.md"

    run_df.to_csv(run_csv, index=False)
    eval_df.to_csv(eval_csv, index=False)
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump({"config": asdict(cfg), "summary": summary}, f, indent=2)
    report_path.write_text(report_md, encoding="utf-8")

    _plot_timeseries(eval_df, outdir / "field_truth_compare_timeseries.png")
    _plot_final_maps(final_maps, cfg, outdir / "field_truth_compare_final_maps.png")

    print("Saved:")
    print(f"- {run_csv}")
    print(f"- {eval_csv}")
    print(f"- {summary_json}")
    print(f"- {report_path}")
    print(f"- {outdir / 'field_truth_compare_timeseries.png'}")
    print(f"- {outdir / 'field_truth_compare_final_maps.png'}")


if __name__ == "__main__":
    main()
