from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from run_habituation_stl_production_ladder import (  # noqa: E402
    METRIC_FIELDS,
    _common_params,
    _habituation_params,
    _safe_float,
    _system_params,
)



DEFAULT_DETERRING_MODES = {
    "formation": {"beta": 0.30, "omega": 800.0, "sigma": 18.0, "w_eta": 1.0, "fixed_cost": 0.0},
    "laser": {"beta": 0.45, "omega": 400.0, "sigma": 10.0, "w_eta": 1.5, "fixed_cost": 0.0},
    "biosonic": {"beta": 0.25, "omega": 600.0, "sigma": 20.0, "w_eta": 1.2, "fixed_cost": 0.0},
}


def _scaled_deterring_modes(args: argparse.Namespace) -> dict[str, dict[str, float]]:
    beta_scale = float(args.deterrence_beta_scale)
    sigma_scale = float(args.deterrence_sigma_scale)
    omega_scale = float(args.deterrence_omega_scale)
    modes: dict[str, dict[str, float]] = {}
    for mode, params in DEFAULT_DETERRING_MODES.items():
        scaled = dict(params)
        scaled["beta"] = float(params["beta"]) * beta_scale
        scaled["sigma"] = float(params["sigma"]) * sigma_scale
        scaled["omega"] = float(params["omega"]) * omega_scale
        modes[str(mode)] = scaled
    return modes

SUMMARY_METRIC_FIELDS = [
    "value_weighted_exposure",
    "truth_candidate_events",
    "truth_accepted_events",
    "truth_suppressed_events",
    "truth_suppression_rate",
    "truth_suppression_effect_mean",
    "truth_suppression_effect_sum",
    "birds_deterred_pct",
    "predictive_generated_total",
    "predictive_admitted_total",
    "predictive_completed_total",
    "habituation_eta_mean",
    "habituation_eta_min",
    "habituation_eta_at_apply_mean",
    "habituation_variety_index",
    "stl_robustness_global_mean",
    "stl_robustness_exp",
    "stl_robustness_cov",
    "stl_robustness_hab",
]


def _finite(values: list[float]) -> list[float]:
    return [float(v) for v in values if math.isfinite(float(v))]


def _mean(values: list[float]) -> float:
    vals = _finite(values)
    return float(sum(vals) / len(vals)) if vals else float("nan")


def _min(values: list[float]) -> float:
    vals = _finite(values)
    return float(min(vals)) if vals else float("nan")


def _max(values: list[float]) -> float:
    vals = _finite(values)
    return float(max(vals)) if vals else float("nan")


def _task_action_name(row: dict[str, Any]) -> str:
    action = row.get("action")
    if isinstance(action, dict):
        value = action.get("name") or action.get("action_name") or action.get("mode")
        if value is not None:
            return str(value)
    return str(row.get("action_name") or row.get("mode") or "")


def _is_predictive_deterring(row: dict[str, Any]) -> bool:
    if str(row.get("type", "")).strip().lower() != "deterring":
        return False
    return _task_action_name(row).strip().lower() != "direct_detection"


def _row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("origin") or ""),
        str(row.get("mode") or _task_action_name(row) or ""),
        round(_safe_float(row.get("x")), 1),
        round(_safe_float(row.get("y")), 1),
    )


def _tracking_recent_deterrences(frame: dict[str, Any]) -> list[dict[str, Any]]:
    tracking = frame.get("tracking_state") or {}
    runtime = tracking.get("runtime_state") if isinstance(tracking, dict) else None
    if not isinstance(runtime, dict):
        state = frame.get("system_state_structured") or {}
        tracking = state.get("tracking") if isinstance(state, dict) else None
        runtime = tracking.get("runtime_state") if isinstance(tracking, dict) else None
    recent = runtime.get("recent_deterrences") if isinstance(runtime, dict) else None
    if isinstance(recent, dict) and isinstance(recent.get("items"), list):
        recent = recent.get("items")
    if not isinstance(recent, list):
        return []
    return [ev for ev in recent if isinstance(ev, dict)]


def _event_key(ev: dict[str, Any]) -> tuple[Any, ...]:
    return (
        round(_safe_float(ev.get("t")), 3),
        str(ev.get("mode") or ""),
        round(_safe_float(ev.get("x")), 2),
        round(_safe_float(ev.get("y")), 2),
        str(ev.get("source") or ""),
        str(ev.get("action_id") or ""),
    )


def _build_params(args: argparse.Namespace, baseline: str, hab_enabled: bool) -> dict[str, Any]:
    params = _common_params(args)
    systems = _system_params(args)
    if baseline not in systems:
        raise KeyError(f"Unknown baseline {baseline!r}. Available: {', '.join(sorted(systems))}")
    params.update(systems[baseline])
    params.update(_habituation_params(hab_enabled))
    params.pop("habituation_condition", None)
    params.update(
        {
            "seed": int(args.seed),
            "mu_true": float(args.mu_true),
            "alpha_true": float(args.alpha_true),
            "beta_true": float(args.beta_true) * float(args.deterrence_beta_scale),
            "sigma_true": float(args.sigma_true) * float(args.deterrence_sigma_scale),
            "omega_true": float(args.omega_true) * float(args.deterrence_omega_scale),
            "deterring_modes": _scaled_deterring_modes(args),
            "emit_planning_diagnostics": True,
            "planning_candidate_limit": int(args.planning_candidate_limit),
            "planning_hotspot_top_k": int(args.planning_hotspot_top_k),
            "emit_tracking_state": True,
            "tracking_include_arrays": False,
            "tracking_preview_limit": int(args.tracking_preview_limit),
            "report_metrics_end": False,
            "telemetry_clear_on_start": False,
            "telemetry_prompt_save": False,
        }
    )
    return params


def _stage_record(
    *,
    baseline: str,
    hab_condition: str,
    seed: int,
    frame: dict[str, Any],
    seen_events: set[tuple[Any, ...]],
) -> dict[str, Any]:
    diag = frame.get("planning_diagnostics") or {}
    generation = frame.get("task_generation_structured") or {}
    dispatch = frame.get("dispatch_structured") or {}
    metrics = frame.get("metrics_compact") or frame.get("metrics") or {}

    candidates = diag.get("model_deterring_candidates") or []
    accepted = diag.get("accepted_deterring_tasks") or []
    if not isinstance(candidates, list):
        candidates = []
    if not isinstance(accepted, list):
        accepted = []

    predictive_candidates = [row for row in candidates if _is_predictive_deterring(row)]
    predictive_accepted = [row for row in accepted if _is_predictive_deterring(row)]
    candidate_u = [_safe_float(row.get("predictive_stl_U")) for row in predictive_candidates]
    candidate_utility = [_safe_float(row.get("utility")) for row in predictive_candidates]
    accepted_u = [_safe_float(row.get("predictive_stl_U")) for row in predictive_accepted]
    accepted_utility = [_safe_float(row.get("utility")) for row in predictive_accepted]

    recent_events = _tracking_recent_deterrences(frame)
    new_events = []
    for ev in recent_events:
        key = _event_key(ev)
        if key in seen_events:
            continue
        seen_events.add(key)
        new_events.append(ev)
    recent_eta = [_safe_float(ev.get("eta", 1.0)) for ev in recent_events]
    new_eta = [_safe_float(ev.get("eta", 1.0)) for ev in new_events]

    completed = frame.get("tasks_done") or []
    if not isinstance(completed, list):
        completed = []
    predictive_completed = [row for row in completed if isinstance(row, dict) and _is_predictive_deterring(row)]

    mode_counts = Counter(str(row.get("mode") or _task_action_name(row) or "") for row in predictive_candidates)
    accepted_mode_counts = Counter(str(row.get("mode") or _task_action_name(row) or "") for row in predictive_accepted)

    return {
        "baseline": baseline,
        "habituation_condition": hab_condition,
        "seed": int(seed),
        "t": _safe_float(frame.get("t")),
        "generation_now_t": _safe_float(generation.get("now_t")),
        "dispatch_now_t": _safe_float(dispatch.get("now_t")),
        "candidate_count": int(len(candidates)),
        "predictive_candidate_count": int(len(predictive_candidates)),
        "candidate_with_stl_u_count": int(sum(math.isfinite(_safe_float(row.get("predictive_stl_U"))) for row in predictive_candidates)),
        "candidate_stl_u_mean": _mean(candidate_u),
        "candidate_stl_u_min": _min(candidate_u),
        "candidate_stl_u_max": _max(candidate_u),
        "candidate_utility_mean": _mean(candidate_utility),
        "candidate_utility_max": _max(candidate_utility),
        "candidate_modes_json": json.dumps(dict(sorted(mode_counts.items())), sort_keys=True),
        "accepted_deterring_count": int(len(accepted)),
        "accepted_predictive_deterring_count": int(len(predictive_accepted)),
        "accepted_stl_u_mean": _mean(accepted_u),
        "accepted_utility_mean": _mean(accepted_utility),
        "accepted_modes_json": json.dumps(dict(sorted(accepted_mode_counts.items())), sort_keys=True),
        "completed_predictive_deterring_total_so_far": int(len(predictive_completed)),
        "recent_deterrence_count": int(len(recent_events)),
        "recent_deterrence_eta_mean": _mean(recent_eta),
        "recent_deterrence_eta_min": _min(recent_eta),
        "new_deterrence_count": int(len(new_events)),
        "new_deterrence_eta_mean": _mean(new_eta),
        "new_deterrence_eta_min": _min(new_eta),
        "truth_candidate_events": _safe_float(metrics.get("truth_candidate_events")),
        "truth_accepted_events": _safe_float(metrics.get("truth_accepted_events")),
        "truth_suppressed_events": _safe_float(metrics.get("truth_suppressed_events")),
        "truth_suppression_rate": _safe_float(metrics.get("truth_suppression_rate")),
        "truth_suppression_effect_mean": _safe_float(metrics.get("truth_suppression_effect_mean")),
        "truth_suppression_effect_sum": _safe_float(metrics.get("truth_suppression_effect_sum")),
        "birds_deterred_pct": _safe_float(metrics.get("birds_deterred_pct")),
        "habituation_eta_mean": _safe_float(metrics.get("habituation_eta_mean")),
        "habituation_eta_at_apply_mean": _safe_float(metrics.get("habituation_eta_at_apply_mean")),
        "stl_robustness_global_mean": _safe_float(metrics.get("stl_robustness_global_mean")),
        "stl_robustness_hab": _safe_float(metrics.get("stl_robustness_hab")),
    }


def _variant_records(
    *,
    baseline: str,
    hab_condition: str,
    seed: int,
    frame: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flatten candidate action variants into per-mode diagnostic rows."""
    diag = frame.get("planning_diagnostics") or {}
    generation = frame.get("task_generation_structured") or {}
    dispatch = frame.get("dispatch_structured") or {}
    out: list[dict[str, Any]] = []

    def rows_for(collection_name: str, rows: Any) -> None:
        """Append variant records from one diagnostic collection."""
        if not isinstance(rows, list):
            return
        for candidate_index, row in enumerate(rows):
            if not isinstance(row, dict) or not _is_predictive_deterring(row):
                continue
            variants = row.get("predictive_action_variants") or []
            if not isinstance(variants, list) or not variants:
                continue
            selected_mode = str(row.get("mode") or _task_action_name(row) or "")
            selected_u = _safe_float(row.get("predictive_stl_U"))
            for variant_index, variant in enumerate(variants):
                if not isinstance(variant, dict):
                    continue
                variant_mode = str(variant.get("mode") or _task_action_name(variant) or "")
                stl_summary = variant.get("stl_summary") if isinstance(variant.get("stl_summary"), dict) else {}
                out.append(
                    {
                        "baseline": baseline,
                        "habituation_condition": hab_condition,
                        "seed": int(seed),
                        "t": _safe_float(frame.get("t")),
                        "generation_now_t": _safe_float(generation.get("now_t")),
                        "dispatch_now_t": _safe_float(dispatch.get("now_t")),
                        "collection": collection_name,
                        "candidate_index": int(candidate_index),
                        "variant_index": int(variant_index),
                        "candidate_key": row.get("candidate_key") or row.get("predictive_opportunity_key") or row.get("cluster_key"),
                        "origin": row.get("origin"),
                        "x": _safe_float(row.get("x")),
                        "y": _safe_float(row.get("y")),
                        "selected_mode": selected_mode,
                        "variant_mode": variant_mode,
                        "variant_is_selected": int(variant_mode == selected_mode),
                        "selected_predictive_stl_U": selected_u,
                        "variant_predictive_stl_U": _safe_float(variant.get("predictive_stl_U")),
                        "variant_utility": _safe_float(variant.get("utility")),
                        "variant_score": _safe_float(variant.get("score")),
                        "variant_predicted_deltaJ": _safe_float(variant.get("predicted_deltaJ")),
                        "variant_deltaJ_per_cost": _safe_float(variant.get("deltaJ_per_cost")),
                        "variant_cost_eta": _safe_float(variant.get("cost_eta")),
                        "variant_p_event": _safe_float(variant.get("p_event")),
                        "stl_available": stl_summary.get("stl_available"),
                        "stl_reason": stl_summary.get("stl_reason"),
                        "stl_target_cell": stl_summary.get("stl_target_cell"),
                        "stl_mode_id": stl_summary.get("stl_mode_id"),
                        "stl_eta_at_apply": _safe_float(stl_summary.get("stl_eta_at_apply")),
                        "stl_local_cell_count": stl_summary.get("stl_local_cell_count"),
                        "stl_completion_lead_s": _safe_float(stl_summary.get("stl_completion_lead_s")),
                        "stl_target_exposure_rate": _safe_float(stl_summary.get("stl_target_exposure_rate")),
                        "stl_target_coverage_age_s": _safe_float(stl_summary.get("stl_target_coverage_age_s")),
                    }
                )

    rows_for("candidate", diag.get("model_deterring_candidates"))
    rows_for("accepted", diag.get("accepted_deterring_tasks"))
    return out
def _run_one(args: argparse.Namespace, baseline: str, hab_enabled: bool) -> dict[str, Any]:
    import DeterrentSystem as ds

    hab_condition = "hab_on" if hab_enabled else "hab_off"
    params = _build_params(args, baseline, hab_enabled)
    stage_rows = []
    event_rows = []
    variant_rows = []
    seen_stage_times = set()
    seen_stage_events: set[tuple[Any, ...]] = set()
    seen_exported_events: set[tuple[Any, ...]] = set()
    last_frame = None
    started = time.time()

    for frame in ds.run_simulation_frames_persistent(**params):
        last_frame = frame
        dispatch = frame.get("dispatch_structured") or {}
        dispatch_now_t = round(_safe_float(dispatch.get("now_t")), 6)
        if math.isfinite(dispatch_now_t) and dispatch_now_t not in seen_stage_times:
            seen_stage_times.add(dispatch_now_t)
            stage_rows.append(
                _stage_record(
                    baseline=baseline,
                    hab_condition=hab_condition,
                    seed=int(args.seed),
                    frame=frame,
                    seen_events=seen_stage_events,
                )
            )
            variant_rows.extend(
                _variant_records(
                    baseline=baseline,
                    hab_condition=hab_condition,
                    seed=int(args.seed),
                    frame=frame,
                )
            )
        for ev in _tracking_recent_deterrences(frame):
            key = _event_key(ev)
            if key in seen_exported_events:
                continue
            seen_exported_events.add(key)
            event_rows.append(
                {
                    "baseline": baseline,
                    "habituation_condition": hab_condition,
                    "seed": int(args.seed),
                    "t": _safe_float(ev.get("t")),
                    "x": _safe_float(ev.get("x")),
                    "y": _safe_float(ev.get("y")),
                    "mode": ev.get("mode"),
                    "habituation_mode": ev.get("habituation_mode"),
                    "source": ev.get("source"),
                    "action_id": ev.get("action_id"),
                    "eta": _safe_float(ev.get("eta", 1.0)),
                    "beta": _safe_float(ev.get("beta")),
                    "sigma": _safe_float(ev.get("sigma")),
                    "omega": _safe_float(ev.get("omega")),
                }
            )

    metrics = (last_frame or {}).get("metrics_compact") or (last_frame or {}).get("metrics") or {}
    final_row = {
        "baseline": baseline,
        "habituation_condition": hab_condition,
        "seed": int(args.seed),
        "elapsed_s": time.time() - started,
        "stage_count": int(len(stage_rows)),
        "event_count": int(len(event_rows)),
    }
    for field in SUMMARY_METRIC_FIELDS:
        final_row[field] = _safe_float(metrics.get(field))

    return {
        "final": final_row,
        "stages": stage_rows,
        "events": event_rows,
        "variants": variant_rows,
        "last_frame_metrics": {field: _safe_float(metrics.get(field)) for field in METRIC_FIELDS},
    }


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _compare_stage_rows(stage_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        (
            str(row["habituation_condition"]),
            int(row["seed"]),
            round(_safe_float(row["dispatch_now_t"]), 6),
            str(row["baseline"]),
        ): row
        for row in stage_rows
    }
    out = []
    for hab in sorted({str(row["habituation_condition"]) for row in stage_rows}):
        times = sorted(
            {
                round(_safe_float(row["dispatch_now_t"]), 6)
                for row in stage_rows
                if str(row["habituation_condition"]) == hab
            }
        )
        for now_t in times:
            b3 = by_key.get((hab, int(stage_rows[0]["seed"]), now_t, "B3_res_stl_nohab"))
            b4 = by_key.get((hab, int(stage_rows[0]["seed"]), now_t, "B4_res_stl_full"))
            if b3 is None or b4 is None:
                continue
            out.append(
                {
                    "habituation_condition": hab,
                    "seed": int(stage_rows[0]["seed"]),
                    "dispatch_now_t": float(now_t),
                    "candidate_count_delta_b4_minus_b3": int(b4["predictive_candidate_count"]) - int(b3["predictive_candidate_count"]),
                    "candidate_stl_u_mean_delta_b4_minus_b3": _safe_float(b4["candidate_stl_u_mean"]) - _safe_float(b3["candidate_stl_u_mean"]),
                    "candidate_utility_mean_delta_b4_minus_b3": _safe_float(b4["candidate_utility_mean"]) - _safe_float(b3["candidate_utility_mean"]),
                    "accepted_count_delta_b4_minus_b3": int(b4["accepted_predictive_deterring_count"]) - int(b3["accepted_predictive_deterring_count"]),
                    "accepted_stl_u_mean_delta_b4_minus_b3": _safe_float(b4["accepted_stl_u_mean"]) - _safe_float(b3["accepted_stl_u_mean"]),
                    "accepted_modes_equal": str(b4["accepted_modes_json"]) == str(b3["accepted_modes_json"]),
                    "b3_accepted_modes_json": b3["accepted_modes_json"],
                    "b4_accepted_modes_json": b4["accepted_modes_json"],
                }
            )
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    wanted_baselines = list(args.baselines)
    wanted_hab = [False, True] if args.habituation == "both" else [args.habituation == "on"]

    final_rows = []
    stage_rows = []
    event_rows = []
    variant_rows = []
    raw: dict[str, Any] = {"args": vars(args), "runs": []}
    for baseline in wanted_baselines:
        for hab_enabled in wanted_hab:
            label = f"{baseline}_{'hab_on' if hab_enabled else 'hab_off'}"
            print(f"[diagnose] start {label} seed={args.seed}", flush=True)
            result = _run_one(args, baseline, hab_enabled)
            print(
                f"[diagnose] done {label} stages={result['final']['stage_count']} "
                f"events={result['final']['event_count']} Jexp={result['final']['value_weighted_exposure']:.3f}",
                flush=True,
            )
            final_rows.append(result["final"])
            stage_rows.extend(result["stages"])
            event_rows.extend(result["events"])
            variant_rows.extend(result.get("variants", []))
            raw["runs"].append({"label": label, **result})

    stage_compare_rows = _compare_stage_rows(stage_rows)
    _write_csv(final_rows, outdir / "diagnostic_final_metrics.csv")
    _write_csv(stage_rows, outdir / "diagnostic_stage_rows.csv")
    _write_csv(event_rows, outdir / "diagnostic_deterrence_events.csv")
    _write_csv(variant_rows, outdir / "diagnostic_action_variants.csv")
    _write_csv(stage_compare_rows, outdir / "diagnostic_b3_b4_stage_compare.csv")
    (outdir / "diagnostic_raw.json").write_text(json.dumps(raw, indent=2, allow_nan=True), encoding="utf-8")
    print(f"[diagnose] wrote {outdir}", flush=True)
    return raw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect where habituation/STL changes disappear in production runs.")
    parser.add_argument("--outdir", default="results/diagnostics/habituation_stl_production_debug")
    parser.add_argument("--duration-s", type=float, default=120.0)
    parser.add_argument("--seed", type=int, default=125)
    parser.add_argument("--nx", type=int, default=60)
    parser.add_argument("--ny", type=int, default=48)
    parser.add_argument("--nrobots", type=int, default=4)
    parser.add_argument("--warmup-s", type=float, default=0.0)
    parser.add_argument("--reservation-fraction", type=float, default=0.25)
    parser.add_argument("--mu-true", type=float, default=1.0e-6)
    parser.add_argument("--alpha-true", type=float, default=0.3)
    parser.add_argument("--beta-true", type=float, default=0.25)
    parser.add_argument("--sigma-true", type=float, default=12.0)
    parser.add_argument("--omega-true", type=float, default=600.0)
    parser.add_argument("--deterrence-beta-scale", type=float, default=1.0)
    parser.add_argument("--deterrence-sigma-scale", type=float, default=1.0)
    parser.add_argument("--deterrence-omega-scale", type=float, default=1.0)
    parser.add_argument("--planning-candidate-limit", type=int, default=100)
    parser.add_argument("--planning-hotspot-top-k", type=int, default=20)
    parser.add_argument("--tracking-preview-limit", type=int, default=250)
    parser.add_argument("--habituation", choices=("both", "on", "off"), default="both")
    parser.add_argument(
        "--baselines",
        nargs="*",
        default=["B3_res_stl_nohab", "B4_res_stl_full"],
        help="Subset from ladder baselines, usually B3_res_stl_nohab and B4_res_stl_full.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
