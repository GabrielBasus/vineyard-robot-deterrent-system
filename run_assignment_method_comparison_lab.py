from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

import assignment_methods_lab as aml
import DeterrentSystem_assignment_lab as ds


BASELINES = ["reactive", "prediction_only", "proposed"]
METHODS = ["frozen_greedy", "hungarian", "auction", "cbba"]


def _baseline_cfg(name: str) -> dict:
    if name == "reactive":
        return {
            "simulation_mode": "reactive",
            "enable_patrolling": False,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": False,
            "enable_model_scored_deterring": False,
        }
    if name == "prediction_only":
        return {
            "simulation_mode": "prediction_only",
            "enable_patrolling": True,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": True,
            "enable_model_scored_deterring": False,
        }
    if name == "proposed":
        return {
            "simulation_mode": "proposed",
            "enable_patrolling": True,
            "enable_intervention_feedback": True,
            "include_fallback_patrol": True,
            "enable_model_scored_deterring": True,
        }
    raise ValueError(f"Unknown baseline: {name}")


def _ci95(series: pd.Series) -> float:
    x = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    n = x.size
    if n <= 1:
        return float("nan")
    return float(1.96 * np.std(x, ddof=1) / np.sqrt(n))


def _stats(df: pd.DataFrame, col: str) -> dict:
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(s) == 0:
        return {"mean": float("nan"), "std": float("nan"), "ci95": float("nan"), "n": 0}
    return {
        "mean": float(s.mean()),
        "std": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
        "ci95": _ci95(s),
        "n": int(len(s)),
    }


def _validate_solver_result(req: aml.AssignmentRequest, res: aml.AssignmentResult) -> List[str]:
    issues: List[str] = []
    assigned = dict(res.primary_by_task_idx)

    if len(assigned) != len(set(assigned.keys())):
        issues.append("duplicate task assignment")

    for tidx, rid in assigned.items():
        if not req.eligible_fn(rid, tidx):
            issues.append(f"ineligible assignment rid={rid} task={tidx}")

    per_robot: Dict[str, int] = {}
    for rid in assigned.values():
        per_robot[rid] = per_robot.get(rid, 0) + 1
    for rid, used in per_robot.items():
        cap = int(req.capacity_by_robot.get(rid, 0))
        if used > cap:
            issues.append(f"capacity exceeded rid={rid} used={used} cap={cap}")

    return issues


def run_unit_checks() -> None:
    tasks = [
        {"type": "patrolling", "x": 10.0, "y": 10.0},
        {"type": "patrolling", "x": 20.0, "y": 20.0},
        {"type": "deterring", "x": 30.0, "y": 30.0},
        {"type": "deterring", "x": 40.0, "y": 40.0},
    ]
    robots = ["r1", "r2", "r3"]
    capacity = {"r1": 1, "r2": 2, "r3": 1}

    score_map = {
        ("r1", 0): 0.9,
        ("r1", 1): 0.3,
        ("r1", 2): 0.2,
        ("r2", 0): 0.8,
        ("r2", 1): 0.7,
        ("r2", 2): 0.5,
        ("r2", 3): 0.1,
        ("r3", 1): 0.8,
        ("r3", 3): 0.9,
    }

    def score_fn(rid: str, tidx: int) -> float:
        return float(score_map.get((rid, tidx), float("-inf")))

    def eligible_fn(rid: str, tidx: int) -> bool:
        return (rid, tidx) in score_map

    req = aml.AssignmentRequest(
        tasks=tasks,
        robots=robots,
        capacity_by_robot=capacity,
        score_fn=score_fn,
        eligible_fn=eligible_fn,
        task_type_fn=lambda j: str(tasks[j].get("type", "")).strip().lower(),
    )

    for method in METHODS:
        r1 = aml.solve_assignment(method, req)
        r2 = aml.solve_assignment(method, req)

        issues = _validate_solver_result(req, r1)
        if issues:
            raise RuntimeError(f"[{method}] unit-check failed: {'; '.join(issues)}")

        if dict(r1.primary_by_task_idx) != dict(r2.primary_by_task_idx):
            raise RuntimeError(f"[{method}] non-deterministic assignment under fixed request")


def run_matrix(
    num_runs: int,
    seed_start: int,
    base_params: dict,
    baselines: List[str] | None = None,
    methods: List[str] | None = None,
) -> pd.DataFrame:
    rows: List[dict] = []
    use_baselines = list(baselines or BASELINES)
    use_methods = list(methods or METHODS)
    total = len(use_baselines) * len(use_methods)
    done = 0

    for baseline in use_baselines:
        for method in use_methods:
            done += 1
            print(f"[run] {done}/{total} baseline={baseline} method={method}")
            kwargs = dict(base_params)
            kwargs.update(_baseline_cfg(baseline))
            kwargs["assignment_method"] = method

            result = ds.run_metrics_experiments(
                num_runs=int(num_runs),
                seed_start=int(seed_start),
                report_each_run=False,
                **kwargs,
            )

            for r in result.get("runs", []):
                exposure = float(r.get("value_weighted_exposure", np.nan))
                response_time_s = float(r.get("mean_response_time_s", np.nan))
                comm_count = float(r.get("boundary_message_count", np.nan))
                comm_bytes = float(r.get("boundary_bytes_sent", np.nan))
                rows.append(
                    {
                        "baseline": baseline,
                        "assignment_method": method,
                        "seed": int(r.get("seed", -1)),
                        "run_idx": int(r.get("run_idx", -1)),
                        "exposure": exposure,
                        "response_time_s": response_time_s,
                        "comm_count": comm_count,
                        "comm_bytes": comm_bytes,
                        "value_weighted_exposure": exposure,
                        "mean_response_time_s": response_time_s,
                        "boundary_message_count": comm_count,
                        "boundary_bytes_sent": comm_bytes,
                        "tasks_per_unit_distance": float(r.get("tasks_per_unit_distance", np.nan)),
                        "model_deterring_generated": float(r.get("model_deterring_generated", np.nan)),
                        "model_deterring_accepted": float(r.get("model_deterring_accepted", np.nan)),
                        "deterring_actions_completed_model_scored": float(
                            r.get("deterring_actions_completed_model_scored", np.nan)
                        ),
                        "stale_goal_clears": float(r.get("stale_goal_clears", np.nan)),
                        "assignment_solver_runtime_ms": float(r.get("assignment_solver_runtime_ms", np.nan)),
                        "assignment_solver_assigned_mean": float(r.get("assignment_solver_assigned_mean", np.nan)),
                        "assignment_solver_objective_mean": float(r.get("assignment_solver_objective_mean", np.nan)),
                        "assignment_solver_calls": float(r.get("assignment_solver_calls", np.nan)),
                        "assignment_solver_conflicts_resolved": float(
                            r.get("assignment_solver_conflicts_resolved", np.nan)
                        ),
                        "assignment_solver_unassigned": float(r.get("assignment_solver_unassigned", np.nan)),
                        "assignment_solver_rounds_mean": float(r.get("assignment_solver_rounds_mean", np.nan)),
                        "assignment_solver_bid_updates": float(r.get("assignment_solver_bid_updates", np.nan)),
                        "assignment_solver_message_passes": float(r.get("assignment_solver_message_passes", np.nan)),
                        "assignment_solver_failures": float(r.get("assignment_solver_failures", np.nan)),
                        "assignment_solver_feasible_edges": float(r.get("assignment_solver_feasible_edges", np.nan)),
                        "assignment_solver_infeasible_edges": float(r.get("assignment_solver_infeasible_edges", np.nan)),
                        "assignment_solver_feasible_edge_rate": float(r.get("assignment_solver_feasible_edge_rate", np.nan)),
                    }
                )

    return pd.DataFrame(rows)


def build_summary(runs_df: pd.DataFrame) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame()

    metrics = [
        "value_weighted_exposure",
        "mean_response_time_s",
        "boundary_message_count",
        "boundary_bytes_sent",
        "tasks_per_unit_distance",
        "model_deterring_generated",
        "model_deterring_accepted",
        "deterring_actions_completed_model_scored",
        "stale_goal_clears",
        "assignment_solver_runtime_ms",
        "assignment_solver_assigned_mean",
        "assignment_solver_objective_mean",
        "assignment_solver_conflicts_resolved",
        "assignment_solver_unassigned",
        "assignment_solver_rounds_mean",
        "assignment_solver_bid_updates",
        "assignment_solver_message_passes",
        "assignment_solver_failures",
        "assignment_solver_feasible_edges",
        "assignment_solver_infeasible_edges",
        "assignment_solver_feasible_edge_rate",
    ]

    out_rows = []
    for (baseline, method), g in runs_df.groupby(["baseline", "assignment_method"], as_index=False):
        row = {"baseline": baseline, "assignment_method": method, "n_runs": int(len(g))}
        for m in metrics:
            st = _stats(g, m)
            row[f"{m}_mean"] = st["mean"]
            row[f"{m}_std"] = st["std"]
            row[f"{m}_ci95"] = st["ci95"]
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def build_deltas_vs_frozen(runs_df: pd.DataFrame) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame()

    keys = ["baseline", "seed", "run_idx"]
    base = runs_df[runs_df["assignment_method"] == "frozen_greedy"].copy()
    out = []
    methods = sorted({str(m) for m in runs_df["assignment_method"].dropna().unique()})
    for method in [m for m in methods if m != "frozen_greedy"]:
        cur = runs_df[runs_df["assignment_method"] == method].copy()
        pair = cur.merge(base, on=keys, suffixes=("_m", "_f"), how="inner")
        if pair.empty:
            continue
        pair["assignment_method"] = method
        pair["delta_exposure_abs"] = pair["value_weighted_exposure_f"] - pair["value_weighted_exposure_m"]
        pair["delta_response_abs"] = pair["mean_response_time_s_f"] - pair["mean_response_time_s_m"]
        pair["delta_comm_abs"] = pair["boundary_message_count_m"] - pair["boundary_message_count_f"]
        den_e = pair["value_weighted_exposure_f"].replace(0.0, np.nan)
        den_r = pair["mean_response_time_s_f"].replace(0.0, np.nan)
        den_c = pair["boundary_message_count_f"].replace(0.0, np.nan)
        pair["delta_exposure_pct"] = 100.0 * pair["delta_exposure_abs"] / den_e
        pair["delta_response_pct"] = 100.0 * pair["delta_response_abs"] / den_r
        pair["delta_comm_pct"] = 100.0 * pair["delta_comm_abs"] / den_c

        g = pair.groupby(["baseline", "assignment_method"], as_index=False).agg(
            delta_exposure_pct_mean=("delta_exposure_pct", "mean"),
            delta_exposure_pct_std=("delta_exposure_pct", "std"),
            delta_response_pct_mean=("delta_response_pct", "mean"),
            delta_response_pct_std=("delta_response_pct", "std"),
            delta_comm_pct_mean=("delta_comm_pct", "mean"),
            delta_comm_pct_std=("delta_comm_pct", "std"),
            n=("delta_exposure_pct", "count"),
        )
        g["delta_exposure_pct_ci95"] = 1.96 * g["delta_exposure_pct_std"] / np.sqrt(g["n"].clip(lower=1))
        g["delta_response_pct_ci95"] = 1.96 * g["delta_response_pct_std"] / np.sqrt(g["n"].clip(lower=1))
        g["delta_comm_pct_ci95"] = 1.96 * g["delta_comm_pct_std"] / np.sqrt(g["n"].clip(lower=1))
        out.append(g)

    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True)


def choose_winner(runs_df: pd.DataFrame) -> dict:
    if runs_df.empty:
        return {"winner": None, "reason": "empty runs"}

    methods = sorted({str(m) for m in runs_df["assignment_method"].dropna().unique()})
    rows = []
    for method in methods:
        p = runs_df[(runs_df["assignment_method"] == method) & (runs_df["baseline"] == "proposed")]
        q = runs_df[(runs_df["assignment_method"] == method) & (runs_df["baseline"] == "prediction_only")]
        pair = p.merge(q, on=["seed", "run_idx", "assignment_method"], suffixes=("_p", "_q"), how="inner")
        if pair.empty:
            continue

        den_e = pair["value_weighted_exposure_q"].replace(0.0, np.nan)
        den_r = pair["mean_response_time_s_q"].replace(0.0, np.nan)
        den_c = pair["boundary_message_count_q"].replace(0.0, np.nan)
        exp_imp = 100.0 * (pair["value_weighted_exposure_q"] - pair["value_weighted_exposure_p"]) / den_e
        resp_imp = 100.0 * (pair["mean_response_time_s_q"] - pair["mean_response_time_s_p"]) / den_r
        comm_inc = 100.0 * (pair["boundary_message_count_p"] - pair["boundary_message_count_q"]) / den_c

        p_calls = pd.to_numeric(p["assignment_solver_calls"], errors="coerce")
        p_runtime = pd.to_numeric(p["assignment_solver_runtime_ms"], errors="coerce")
        p_unassigned = pd.to_numeric(p["assignment_solver_unassigned"], errors="coerce")
        p_failures = pd.to_numeric(p["assignment_solver_failures"], errors="coerce")

        unstable = bool(
            (~np.isfinite(pair["value_weighted_exposure_p"]).all())
            or (~np.isfinite(pair["mean_response_time_s_p"]).all())
            or (p_calls.isna().any())
            or (p_calls.mean() <= 0.0)
            or (p_runtime.isna().any())
            or ((p_unassigned < 0).any())
            or (p_failures.isna().any())
            or ((p_failures > 0.0).any())
        )

        exp_mean = float(np.nanmean(exp_imp))
        resp_mean = float(np.nanmean(resp_imp))
        comm_mean = float(np.nanmean(comm_inc))
        runtime_mean = float(np.nanmean(p_runtime.to_numpy(dtype=float))) if len(p_runtime) else float("inf")

        hard_reject = unstable or ((comm_mean > 100.0) and (exp_mean < 0.5))

        rows.append(
            {
                "assignment_method": method,
                "exp_improve_pct_mean": exp_mean,
                "resp_improve_pct_mean": resp_mean,
                "comm_increase_pct_mean": comm_mean,
                "runtime_ms_mean": runtime_mean,
                "unstable": bool(unstable),
                "hard_reject": bool(hard_reject),
            }
        )

    if not rows:
        return {"winner": None, "reason": "no comparable rows"}

    cand = [r for r in rows if not r["hard_reject"]]
    if not cand:
        return {"winner": None, "reason": "all methods hard-rejected", "table": rows}

    cand.sort(
        key=lambda r: (
            -r["exp_improve_pct_mean"],
            -r["resp_improve_pct_mean"],
            r["comm_increase_pct_mean"],
            r["runtime_ms_mean"],
            r["assignment_method"],
        )
    )
    return {"winner": cand[0]["assignment_method"], "table": rows}


def _build_base_params(t_end: float, dt: float) -> dict:
    return {
        "W": 500.0,
        "H": 500.0,
        "NX": 80,
        "NY": 64,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "warmup_s": 1800.0,
        "task_replan_period_s": 45.0,
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
        "collect_time_metrics": False,
        "T_end": float(t_end),
        "dt": float(dt),
    }


def _run_smoke(seed_start: int, outdir: Path, dt: float, methods: List[str]) -> pd.DataFrame:
    smoke_params = _build_base_params(t_end=600.0, dt=dt)
    df = run_matrix(
        num_runs=2,
        seed_start=int(seed_start),
        base_params=smoke_params,
        baselines=BASELINES,
        methods=methods,
    )
    if df.empty:
        raise RuntimeError("integration smoke produced no runs")

    smoke_outdir = outdir / "smoke"
    smoke_outdir.mkdir(parents=True, exist_ok=True)
    df.to_csv(smoke_outdir / "assignment_method_runs_lab_smoke.csv", index=False)
    build_summary(df).to_csv(smoke_outdir / "assignment_method_summary_lab_smoke.csv", index=False)
    build_deltas_vs_frozen(df).to_csv(smoke_outdir / "assignment_method_deltas_lab_smoke.csv", index=False)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Assignment method comparison lab")
    parser.add_argument("--num-runs", type=int, default=10)
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--t-end", type=float, default=3 * 3600.0)
    parser.add_argument("--dt", type=float, default=5.0)
    parser.add_argument("--outdir", type=str, default="results/assignment_method_lab")
    parser.add_argument(
        "--methods",
        type=str,
        default=",".join(METHODS),
        help="Comma-separated methods, e.g. frozen_greedy,hungarian,cbba,cbba_centralized",
    )
    parser.add_argument("--skip-unit-checks", action="store_true")
    parser.add_argument("--with-smoke-check", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    methods = [m.strip() for m in str(args.methods).split(",") if m.strip()]
    if not methods:
        raise ValueError("No methods selected. Pass --methods with at least one method.")

    if getattr(ds, "mon", None) is not None:
        ds.mon.enabled = False

    if not args.skip_unit_checks:
        print("[check] running solver unit checks")
        run_unit_checks()

    if args.with_smoke_check or args.smoke_only:
        print("[check] running 10-minute integration smoke")
        smoke_df = _run_smoke(
            seed_start=int(args.seed_start),
            outdir=outdir,
            dt=float(args.dt),
            methods=methods,
        )
        print(f"[check] smoke completed rows={len(smoke_df)}")
        if args.smoke_only:
            print("[done] smoke-only requested; exiting")
            return

    base_params = _build_base_params(t_end=float(args.t_end), dt=float(args.dt))
    runs_df = run_matrix(
        num_runs=int(args.num_runs),
        seed_start=int(args.seed_start),
        base_params=base_params,
        baselines=BASELINES,
        methods=methods,
    )
    summary_df = build_summary(runs_df)
    deltas_df = build_deltas_vs_frozen(runs_df)
    winner = choose_winner(runs_df)

    runs_path = outdir / "assignment_method_runs_lab.csv"
    summary_path = outdir / "assignment_method_summary_lab.csv"
    deltas_path = outdir / "assignment_method_deltas_lab.csv"
    manifest_path = outdir / "assignment_method_manifest_lab.json"

    runs_df.to_csv(runs_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    deltas_df.to_csv(deltas_path, index=False)

    seed_list = [int(args.seed_start) + i for i in range(int(args.num_runs))]
    manifest = {
        "num_runs": int(args.num_runs),
        "seed_start": int(args.seed_start),
        "seed_list": seed_list,
        "t_end": float(args.t_end),
        "dt": float(args.dt),
        "baselines": BASELINES,
        "methods": methods,
        "base_params": base_params,
        "winner_selection": {
            "objective": [
                "maximize proposed exposure reduction vs prediction_only",
                "then maximize response improvement",
                "then minimize communication increase",
                "then minimize solver runtime",
            ],
            "hard_reject": [
                "unstable or infeasible assignments",
                "communication increase >100% with exposure gain <0.5%",
            ],
            "winner": winner,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[done] wrote outputs to: {outdir}")
    print(f"- {runs_path}")
    print(f"- {summary_path}")
    print(f"- {deltas_path}")
    print(f"- {manifest_path}")


if __name__ == "__main__":
    main()
