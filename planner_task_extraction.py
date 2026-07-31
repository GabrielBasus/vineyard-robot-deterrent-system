from __future__ import annotations

from typing import Any, Callable, Iterable

import numpy as np


PREDICTIVE_UTILITY_MODES = (
    "legacy",
    "deltaJ",
    "bernoulli_expected_deltaJ",
    "stl_robustness",
)


def canonical_predictive_utility_mode(mode: str | None) -> str:
    """Normalize predictive utility mode names used by task generation and dispatch."""
    key = str(mode or "legacy").strip().lower().replace("-", "_")
    if key in {"", "legacy", "taskgenerator", "task_generator"}:
        return "legacy"
    if key in {"deltaj", "delta_j", "raw_deltaj", "raw_delta_j", "deterministic"}:
        return "deltaJ"
    if key in {
        "bernoulli",
        "expected_deltaj",
        "expected_delta_j",
        "bernoulli_expected_deltaj",
        "bernoulli_expected_delta_j",
        "confidence_weighted_deltaj",
        "confidence_weighted_delta_j",
    }:
        return "bernoulli_expected_deltaJ"
    if key in {
        "stl",
        "stl_robustness",
        "stlrobustness",
        "robustness",
        "counterfactual_robustness",
        "counterfactual_stl",
    }:
        return "stl_robustness"
    raise ValueError(
        "predictive_utility_mode must be one of "
        f"{list(PREDICTIVE_UTILITY_MODES)!r}, got: {mode!r}"
    )


def canonical_predictive_confidence_source(source: str | None) -> str:
    """Normalize predictive confidence source names used by dispatch policies."""
    key = str(source or "p_event_times_selection_weight").strip().lower().replace("_", "-")
    aliases = {
        "p-event": "p-event",
        "pevent": "p-event",
        "p-event-times-selection-weight": "p-event-times-selection-weight",
        "p-event-x-selection-weight": "p-event-times-selection-weight",
        "pevent-times-selection-weight": "p-event-times-selection-weight",
        "p-event-selection-weight": "p-event-times-selection-weight",
        "selection-weight": "selection-weight",
        "selectionweight": "selection-weight",
        "risk-conf": "risk-conf",
        "riskconf": "risk-conf",
    }
    if key not in aliases:
        raise ValueError(
            "predictive_confidence_source must be one of ['p_event', 'selection_weight', "
            "'risk_conf', 'p_event_times_selection_weight'], "
            f"got: {source!r}"
        )
    return aliases[key]


def _clip01(value: float) -> float:
    """Clamp a numeric value to the inclusive probability range [0, 1]."""
    try:
        value_f = float(value)
    except Exception:
        return 0.0
    if not np.isfinite(value_f):
        return 0.0
    return float(min(max(value_f, 0.0), 1.0))


def _num(task: dict, key: str, default: float = 0.0) -> float:
    """Coerce a task metric to a finite float with a caller-provided default."""
    try:
        value = float(task.get(key, default))
    except Exception:
        value = float(default)
    return float(value) if np.isfinite(value) else float(default)


def _has_num(task: dict, key: str) -> bool:
    """Return whether a task row contains a finite numeric value for a metric."""
    if key not in task:
        return False
    try:
        return bool(np.isfinite(float(task.get(key))))
    except Exception:
        return False


def predictive_confidence_components(
    task: dict,
    *,
    predictive_confidence_source: str = "p_event_times_selection_weight",
) -> dict[str, float | str | None]:
    """Compute the probability and selection-weight components behind predictive confidence."""
    source = canonical_predictive_confidence_source(predictive_confidence_source)
    p_event = _clip01(_num(task, "p_event", 0.0)) if _has_num(task, "p_event") else None
    selection_weight = (
        _clip01(_num(task, "selection_weight", 1.0)) if _has_num(task, "selection_weight") else None
    )
    risk_conf = _clip01(_num(task, "risk_conf", 0.0)) if _has_num(task, "risk_conf") else None
    support_confidence = None
    if _has_num(task, "support"):
        support = max(_num(task, "support", 0.0), 0.0)
        support_confidence = _clip01(support / (support + 1.0)) if support > 0.0 else 0.0

    def fallback() -> float:
        """Return the configured fallback confidence when component estimation is unavailable."""
        for candidate in (risk_conf, support_confidence):
            if candidate is not None:
                return float(candidate)
        return 0.0

    if source == "p-event":
        raw = float(p_event if p_event is not None else fallback())
    elif source == "selection-weight":
        raw = float(selection_weight if selection_weight is not None else fallback())
    elif source == "risk-conf":
        raw = float(risk_conf if risk_conf is not None else fallback())
    else:
        if p_event is not None and selection_weight is not None:
            raw = float(_clip01(p_event * selection_weight))
        elif p_event is not None:
            raw = float(p_event)
        elif selection_weight is not None:
            raw = float(selection_weight)
        else:
            raw = float(fallback())

    return {
        "source": str(source),
        "p_event": p_event,
        "selection_weight": selection_weight,
        "risk_conf": risk_conf,
        "support_confidence": support_confidence,
        "raw_confidence": float(_clip01(raw)),
    }


def compute_predictive_confidence(
    task: dict,
    *,
    predictive_confidence_source: str = "p_event_times_selection_weight",
    predictive_confidence_power: float = 1.0,
) -> float:
    """Compute the scalar confidence value used to rank predictive opportunities."""
    components = predictive_confidence_components(
        task,
        predictive_confidence_source=predictive_confidence_source,
    )
    try:
        power = float(predictive_confidence_power)
    except Exception:
        power = 1.0
    if not np.isfinite(power) or power <= 0.0:
        power = 1.0
    raw = _clip01(float(components["raw_confidence"]))
    return float(_clip01(raw ** power))


def _predictive_delta_j(task: dict) -> float:
    """Return the best available predictive benefit value from a task row."""
    for key in ("predicted_deltaJ", "predicted_delta_j", "deltaJ", "delta_j"):
        if _has_num(task, key):
            return float(max(_num(task, key, 0.0), 0.0))
    return 0.0


def annotate_predictive_utility_fields(
    task: dict,
    *,
    predictive_utility_mode: str = "legacy",
    predictive_confidence_source: str = "p_event_times_selection_weight",
    predictive_confidence_power: float = 1.0,
    is_direct_detection_task_fn: Callable[[dict], bool] | None = None,
) -> dict:
    """Attach calibrated predictive utility fields without changing reactive rows.

    The default `legacy` mode only annotates diagnostics. The experimental modes
    replace `utility`/`score` for predictive rows so the existing selection and
    dispatch stages rank by the requested deterministic or Bernoulli value.
    """
    row = dict(task)
    if is_direct_detection_task_fn is not None and bool(is_direct_detection_task_fn(row)):
        return row

    mode = canonical_predictive_utility_mode(predictive_utility_mode)
    components = predictive_confidence_components(
        row,
        predictive_confidence_source=predictive_confidence_source,
    )
    try:
        power = float(predictive_confidence_power)
    except Exception:
        power = 1.0
    if not np.isfinite(power) or power <= 0.0:
        power = 1.0
    raw_confidence = _clip01(float(components["raw_confidence"]))
    confidence = _clip01(raw_confidence ** power)
    if mode == "stl_robustness":
        delta_j = _num(
            row,
            "predictive_stl_U",
            _num(row, "utility", _num(row, "score", _num(row, "predicted_deltaJ", 0.0))),
        )
    else:
        delta_j = _predictive_delta_j(row)
    expected_delta_j = float(confidence * delta_j)

    components_public = dict(components)
    components_public["confidence_power"] = float(power)
    components_public["calibrated_confidence"] = float(confidence)

    row["predictive_utility_mode"] = str(mode)
    row["predictive_confidence_source"] = str(components["source"])
    row["predictive_confidence_power"] = float(power)
    row["predictive_confidence_raw"] = float(raw_confidence)
    row["predictive_confidence"] = float(confidence)
    row["confidence"] = float(confidence)
    row["confidence_components"] = components_public
    row["predictive_raw_deltaJ"] = float(delta_j)
    row["bernoulli_expected_deltaJ"] = float(expected_delta_j)
    row["predictive_expected_deltaJ"] = float(expected_delta_j)

    if mode == "deltaJ":
        row["utility"] = float(delta_j)
        row["score"] = float(delta_j)
    elif mode == "bernoulli_expected_deltaJ":
        row["utility"] = float(expected_delta_j)
        row["score"] = float(expected_delta_j)
    elif mode == "stl_robustness":
        stl_u = float(delta_j)
        row["predictive_stl_U"] = stl_u
        row["predicted_deltaJ"] = stl_u
        row["utility"] = stl_u
        row["score"] = stl_u

    variants = row.get("predictive_action_variants")
    if isinstance(variants, list) and variants:
        annotated_variants = []
        for variant in variants:
            variant_row = dict(row)
            variant_row.update(dict(variant))
            variant_row.pop("predictive_action_variants", None)
            annotated_variant = annotate_predictive_utility_fields(
                variant_row,
                predictive_utility_mode=mode,
                predictive_confidence_source=str(components["source"]),
                predictive_confidence_power=float(power),
                is_direct_detection_task_fn=None,
            )
            annotated_variants.append(
                {
                    key: value
                    for key, value in annotated_variant.items()
                    if key
                    in {
                        "mode",
                        "action",
                        "utility",
                        "score",
                        "predicted_deltaJ",
                        "deltaJ_per_cost",
                        "cost_eta",
                        "p_event",
                        "risk_conf",
                        "selection_weight",
                        "predictive_utility_mode",
                        "predictive_confidence_source",
                        "predictive_confidence_power",
                        "predictive_confidence_raw",
                        "predictive_confidence",
                        "confidence",
                        "confidence_components",
                        "predictive_raw_deltaJ",
                        "bernoulli_expected_deltaJ",
                        "predictive_expected_deltaJ",
                        "predictive_stl_U",
                        "stl_summary",
                    }
                }
            )
        row["predictive_action_variants"] = annotated_variants

    return row


def _predictive_opportunity_key(task: dict) -> str:
    """Return the stable deduplication key for a predictive opportunity."""
    raw = task.get("predictive_opportunity_key")
    key = str(raw).strip() if raw is not None else ""
    return key


def _predictive_candidate_priority(task: dict) -> tuple[float, float, float, float, float]:
    """Build the priority tuple used to keep the best duplicate predictive candidate."""
    def _num(key: str, default: float = 0.0) -> float:
        """Coerce a task metric to a finite float with a caller-provided default."""
        try:
            value = float(task.get(key, default))
        except Exception:
            value = float(default)
        return value if np.isfinite(value) else float(default)

    utility = _num("utility", _num("score", 0.0))
    predicted_delta_j = _num("predicted_deltaJ", 0.0)
    confidence = max(_num("p_event", 0.0), 0.0) * max(_num("selection_weight", 1.0), 0.0)
    eta_s = max(_num("eta_s", 0.0), 0.0)
    event_t = _num(
        "forecast_event_time",
        _num("required_arrival_by_t", _num("event_time", _num("time", 0.0))),
    )
    return (
        float(utility),
        float(predicted_delta_j),
        float(confidence),
        float(-eta_s),
        float(-event_t),
    )


def _merge_predictive_action_variants(existing: dict, replacement: dict) -> list[dict]:
    """Merge predictive action variants while keeping the strongest utility candidate."""
    merged: dict[str, dict] = {}
    for row in (existing, replacement):
        for variant in list(row.get("predictive_action_variants", []) or []):
            variant_row = dict(variant)
            mode_key = str(variant_row.get("mode", "")).strip().lower()
            if not mode_key:
                continue
            prior = merged.get(mode_key)
            if prior is None:
                merged[mode_key] = variant_row
                continue
            candidate = dict(prior)
            def _metric(payload: dict, key: str, default: float = 0.0) -> float:
                """Read a finite numeric metric from a task row for duplicate resolution."""
                try:
                    value = float(payload.get(key, default))
                except Exception:
                    value = float(default)
                return value if np.isfinite(value) else float(default)

            if (
                _metric(variant_row, "utility", _metric(variant_row, "score", 0.0)),
                _metric(variant_row, "predicted_deltaJ", 0.0),
                _metric(variant_row, "p_event", 0.0),
                -_metric(variant_row, "cost_eta", 0.0),
            ) > (
                _metric(candidate, "utility", _metric(candidate, "score", 0.0)),
                _metric(candidate, "predicted_deltaJ", 0.0),
                _metric(candidate, "p_event", 0.0),
                -_metric(candidate, "cost_eta", 0.0),
            ):
                merged[mode_key] = variant_row
    return [merged[key] for key in sorted(merged.keys())]


def _dedupe_predictive_candidate_tasks(candidate_tasks: list[dict]) -> list[dict]:
    """Collapse duplicate predictive candidates before dispatch admission."""
    result: list[dict] = []
    predictive_index_by_key: dict[str, int] = {}
    for task in candidate_tasks:
        row = dict(task)
        opportunity_key = _predictive_opportunity_key(row)
        if not opportunity_key:
            result.append(row)
            continue
        owner = str(row.get("predictive_source_robot_id", row.get("robot_id", ""))).strip()
        if opportunity_key not in predictive_index_by_key:
            row["predictive_opportunity_member_count"] = 1
            row["predictive_opportunity_member_robot_ids"] = [owner] if owner else []
            predictive_index_by_key[opportunity_key] = len(result)
            result.append(row)
            continue
        existing_idx = predictive_index_by_key[opportunity_key]
        existing = dict(result[existing_idx])
        member_count = int(existing.get("predictive_opportunity_member_count", 1)) + 1
        member_robot_ids = list(existing.get("predictive_opportunity_member_robot_ids", []))
        if owner and owner not in member_robot_ids:
            member_robot_ids.append(owner)
        replacement = row
        if _predictive_candidate_priority(existing) >= _predictive_candidate_priority(row):
            replacement = existing
        merged_variants = _merge_predictive_action_variants(existing, row)
        replacement["predictive_opportunity_member_count"] = int(member_count)
        replacement["predictive_opportunity_member_robot_ids"] = sorted(
            rid for rid in member_robot_ids if str(rid).strip()
        )
        replacement["predictive_action_variants"] = merged_variants
        replacement["predictive_mode_variant_count"] = int(len(merged_variants))
        result[existing_idx] = replacement
    return result


def run_task_location_estimation(
    *,
    taskgen: Any,
    robots: dict,
    now_t: float,
    enable_patrolling: bool,
    enable_predictive_patrol_tasks: bool,
    include_fallback_patrol: bool,
    enable_model_scored_deterring: bool,
    model_deterring_window_s: float,
    model_deterring_risk_threshold: float,
    model_deterring_risk_scale: float,
    model_deterring_min_recent_points: int,
    model_deterring_field_threshold: float | None,
    model_deterring_min_persistence_replans: int,
    model_deterring_persistence_max_gap_s: float,
    model_deterring_score_margin: float,
    model_deterring_repeat_block_window_s: float,
    model_deterring_repeat_block_radius_m: float,
    model_deterring_max_eta_s: float,
    model_deterring_busy_min_support_override: int,
    model_deterring_busy_risk_override: float,
    enable_predicted_deltaJ_gate: bool,
    min_predicted_deltaJ_for_model_deterring: float,
    model_deterring_gate_policy: str,
    model_deterring_sprt_alpha: float,
    model_deterring_sprt_beta: float,
    model_deterring_sprt_patch_radius_m,
    model_deterring_min_sprt_margin: float,
    model_deterring_chance_threshold: float,
    model_deterring_min_deltaJ_per_cost: float,
    model_deterring_min_selection_weight: float,
    preventive_capacity_remaining_by_robot: dict,
    preventive_capacity_ready_by_robot: dict,
    task_replan_period_s: float,
    busy_deterring_robots: set[str],
    recent_deterrences: list[dict],
    profiles: dict,
    use_live_robot_pose_for_task_planning: bool,
    pose: dict,
    rng: Any,
    patrol_hotspot_filter_mode: str,
    patrol_hotspot_score_percentile: float,
    patrol_hotspot_keep_top_k,
    patrol_feedback_inhibition_retention: float,
    patrol_scoring_mode: str,
    patrol_shared_detection_range_m,
    patrol_shared_detection_prob_per_step: float,
    patrol_shared_detection_dwell_s: float,
    patrol_shared_followup_success_prob: float,
    patrol_shared_response_eta_decay_s,
    enable_predictive_lead_time: bool,
    predictive_timing_mode: str,
    predictive_lead_time_min_s: float,
    predictive_lead_time_max_eta_s: float,
    predictive_lead_time_buffer_s: float,
    predictive_lead_time_risk_power: float,
    forecast_horizon_s: float,
    value_weight_fn: Callable[[float, float], float],
    deterring_modes: dict,
    travel_time_fn: Callable[[str, float, float], float] | None = None,
    predictive_utility_mode: str = "legacy",
    stl_hab=None,
    stl_spec_params=None,
    stl_dynamics=None,
    stl_cell_polys=None,
    stl_local_cell_ids_by_robot: dict | None = None,
    stl_last_service_t_by_cell: dict | None = None,
    stl_mode_to_id: dict | None = None,
    stl_cell_id_for_xy_fn: Callable[[float, float], int | None] | None = None,
) -> None:
    """Run task generation for the current production frame and return the updated task table."""
    if not enable_patrolling:
        return
    taskgen.periodic_patrolling(
        robots=robots,
        now_t=now_t,
        hotspot_top_k=5,
        enable_predictive_patrol_tasks=bool(enable_predictive_patrol_tasks),
        include_fallback_patrol=include_fallback_patrol,
        enable_model_scored_deterring=bool(enable_model_scored_deterring),
        deterring_window_s=float(model_deterring_window_s),
        deterring_risk_threshold=float(model_deterring_risk_threshold),
        deterring_risk_scale=float(model_deterring_risk_scale),
        deterring_min_recent_points=int(model_deterring_min_recent_points),
        deterring_field_threshold=model_deterring_field_threshold,
        deterring_min_persistence_replans=int(model_deterring_min_persistence_replans),
        deterring_persistence_max_gap_s=float(model_deterring_persistence_max_gap_s),
        deterring_score_margin=float(model_deterring_score_margin),
        deterring_repeat_block_window_s=float(model_deterring_repeat_block_window_s),
        deterring_repeat_block_radius_m=float(model_deterring_repeat_block_radius_m),
        deterring_max_eta_s=float(model_deterring_max_eta_s),
        deterring_busy_min_support_override=int(model_deterring_busy_min_support_override),
        deterring_busy_risk_override=float(model_deterring_busy_risk_override),
        enable_predicted_deltaJ_gate=bool(enable_predicted_deltaJ_gate),
        min_predicted_deltaJ_for_model_deterring=float(min_predicted_deltaJ_for_model_deterring),
        model_deterring_gate_policy=str(model_deterring_gate_policy),
        model_deterring_sprt_alpha=float(model_deterring_sprt_alpha),
        model_deterring_sprt_beta=float(model_deterring_sprt_beta),
        model_deterring_sprt_patch_radius_m=model_deterring_sprt_patch_radius_m,
        model_deterring_min_sprt_margin=float(model_deterring_min_sprt_margin),
        model_deterring_chance_threshold=float(model_deterring_chance_threshold),
        model_deterring_min_deltaJ_per_cost=float(model_deterring_min_deltaJ_per_cost),
        model_deterring_min_selection_weight=float(model_deterring_min_selection_weight),
        preventive_capacity_remaining_by_robot=preventive_capacity_remaining_by_robot,
        preventive_capacity_ready_by_robot=preventive_capacity_ready_by_robot,
        replan_interval_s=float(task_replan_period_s),
        busy_deterring_robots=busy_deterring_robots,
        recent_deterrence_events=list(recent_deterrences),
        profiles=profiles,
        robot_poses=(pose if bool(use_live_robot_pose_for_task_planning) else None),
        rng=rng,
        patrol_hotspot_filter_mode=patrol_hotspot_filter_mode,
        patrol_hotspot_score_percentile=float(patrol_hotspot_score_percentile),
        patrol_hotspot_keep_top_k=patrol_hotspot_keep_top_k,
        patrol_feedback_inhibition_retention=float(patrol_feedback_inhibition_retention),
        patrol_scoring_mode=str(patrol_scoring_mode),
        patrol_shared_detection_range_m=patrol_shared_detection_range_m,
        patrol_shared_detection_prob_per_step=float(patrol_shared_detection_prob_per_step),
        patrol_shared_detection_dwell_s=float(patrol_shared_detection_dwell_s),
        patrol_shared_followup_success_prob=float(patrol_shared_followup_success_prob),
        patrol_shared_response_eta_decay_s=patrol_shared_response_eta_decay_s,
        enable_predictive_lead_time=bool(enable_predictive_lead_time),
        predictive_timing_mode=str(predictive_timing_mode),
        predictive_lead_time_min_s=float(predictive_lead_time_min_s),
        predictive_lead_time_max_eta_s=float(predictive_lead_time_max_eta_s),
        predictive_lead_time_buffer_s=float(predictive_lead_time_buffer_s),
        predictive_lead_time_risk_power=float(predictive_lead_time_risk_power),
        horizon_s=float(forecast_horizon_s),
        spinup_by_type={"UAV": 8.0, "UGV": 0.0},
        weight_fn=value_weight_fn,
        deterring_modes=deterring_modes,
        travel_time_fn=travel_time_fn,
        predictive_utility_mode=str(predictive_utility_mode),
        stl_hab=stl_hab,
        stl_spec_params=stl_spec_params,
        stl_dynamics=stl_dynamics,
        stl_cell_polys=stl_cell_polys,
        stl_local_cell_ids_by_robot=stl_local_cell_ids_by_robot,
        stl_last_service_t_by_cell=stl_last_service_t_by_cell,
        stl_mode_to_id=stl_mode_to_id,
        stl_cell_id_for_xy_fn=stl_cell_id_for_xy_fn,
    )


def build_task_dispatch_candidate_buffer(
    *,
    now_t: float,
    active_tasks: list[dict],
    completed_tasks: list[dict],
    consumed_task_keys: set,
    taskgen: Any,
    robot_ids: Iterable[str],
    task_buffer_key_fn: Callable[[dict], Any],
    is_direct_detection_task_fn: Callable[[dict], bool],
    cluster_direct_detection_candidate_tasks_fn: Callable[[list[dict]], list[dict]],
    predictive_owner_override_id: str | None = None,
    predictive_utility_mode: str = "legacy",
    predictive_confidence_source: str = "p_event_times_selection_weight",
    predictive_confidence_power: float = 1.0,
) -> dict:
    """Build the deduplicated candidate task buffer consumed by dispatch."""
    seen_keys = {task_buffer_key_fn(t) for t in active_tasks}
    seen_keys |= {task_buffer_key_fn(t) for t in completed_tasks}
    seen_keys |= set(consumed_task_keys)
    active_load = {rid: 0 for rid in robot_ids}
    active_patrol_load = {rid: 0 for rid in robot_ids}
    active_model_det_load = {rid: 0 for rid in robot_ids}
    for tr in active_tasks:
        if str(tr.get("state", "")).strip().lower() != "active":
            continue
        ridp = tr.get("assigned_primary")
        if ridp not in active_load:
            continue
        active_load[ridp] += 1
        if str(tr.get("type", "")).strip().lower() == "patrolling":
            active_patrol_load[ridp] += 1
        if (
            str(tr.get("type", "")).strip().lower() == "deterring"
            and tr.get("mode") not in (None, "", "none")
        ):
            active_model_det_load[ridp] += 1

    candidate_tasks = []
    recent_rows = taskgen.rows()[-200:]
    for task in recent_rows:
        if (not np.isfinite(task.get("x", float("nan")))) or (not np.isfinite(task.get("y", float("nan")))):
            continue
        key = task_buffer_key_fn(task)
        if key in seen_keys:
            continue
        row = dict(task)
        if is_direct_detection_task_fn(row):
            row["last_detection_t"] = float(row.get("last_detection_t", row.get("time", now_t)))
            row["merged_detection_count"] = int(row.get("merged_detection_count", 1))
            row["cluster_refresh_count"] = int(row.get("cluster_refresh_count", 0))
        elif predictive_owner_override_id is not None:
            row["predictive_source_robot_id"] = str(row.get("robot_id", "")).strip()
        candidate_tasks.append(row)
    candidate_tasks = cluster_direct_detection_candidate_tasks_fn(candidate_tasks)
    candidate_tasks = _dedupe_predictive_candidate_tasks(candidate_tasks)
    if predictive_owner_override_id is not None:
        override_id = str(predictive_owner_override_id).strip()
        if override_id:
            for row in candidate_tasks:
                if _predictive_opportunity_key(row):
                    row["robot_id"] = override_id

    candidate_tasks = [
        annotate_predictive_utility_fields(
            row,
            predictive_utility_mode=str(predictive_utility_mode),
            predictive_confidence_source=str(predictive_confidence_source),
            predictive_confidence_power=float(predictive_confidence_power),
            is_direct_detection_task_fn=is_direct_detection_task_fn,
        )
        for row in candidate_tasks
    ]

    return {
        "candidate_tasks": candidate_tasks,
        "recent_rows": recent_rows,
        "seen_keys": seen_keys,
        "active_load": active_load,
        "active_patrol_load": active_patrol_load,
        "active_model_det_load": active_model_det_load,
    }


def extract_task_candidates_from_sestpp(
    *,
    estimation_kwargs: dict[str, Any],
    buffer_kwargs: dict[str, Any],
) -> dict:
    """Run SESTPP-driven task extraction, then materialize the extracted candidate buffer."""
    run_task_location_estimation(**dict(estimation_kwargs))
    return build_task_dispatch_candidate_buffer(**dict(buffer_kwargs))
