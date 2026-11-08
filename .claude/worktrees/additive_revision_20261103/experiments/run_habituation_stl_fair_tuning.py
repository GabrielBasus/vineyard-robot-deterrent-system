from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics as stats
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import experiments.run_habituation_stl_production_ladder as ladder
from experiments.habituation_stl_selected_configs import SYSTEM_ALIASES
from planner_profiles import get_planner_profile_values


DEFAULT_SYSTEMS = [
    "B1_greedy_fixedcue",
    "B2_res_deltaJ_fixedcue",
    "B3_res_stl_nohab_multicue",
    "B4_res_stl_full_multicue",
    "B5_greedy_habcue",
    "B5_res_habcue_multicue",
]

# Systems that use reserved-dispatch (share reservation_fraction, horizon, budget, etc.)
RESERVED_SYSTEMS = {
    "B2_res_deltaJ_fixedcue",
    "B3_res_stl_nohab_multicue",
    "B4_res_stl_full_multicue",
    "B5_res_habcue_multicue",
}

# Systems whose only system-specific tunable is predictive_fixed_deterring_mode
FIXED_CUE_SYSTEMS = {
    "B1_greedy_fixedcue",
    "B2_res_deltaJ_fixedcue",
}

LOWER_IS_BETTER = {
    "value_weighted_exposure",
    "mean_response_time_s",
    "predictive_expired_fraction",
    "travel_distance_total",
}

CONFIRM_RUNTIME_ARG_KEYS = {
    "outdir",
    "phase",
    "dry_run",
    "selection_path",
    "confirm_duration_s",
    "confirm_num_runs",
    "confirm_seed_start",
    "max_workers",
    # mismatch args: always take the CLI value, not the frozen tuning-protocol value
    "truth_habituation_t_rec_s",
    "truth_habituation_kappa",
    "truth_habituation_gamma",
    "truth_habituation_update_model",
    "planner_habituation_t_rec_s",
    "planner_habituation_kappa",
    "planner_habituation_gamma",
    "planner_habituation_update_model",
    # systems filter: let the caller narrow the system set at confirm time
    "systems",
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, restval="")
        writer.writeheader()
        writer.writerows(rows)


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8")


def _token(value: Any) -> str:
    text = str(value)
    return (
        text.replace("-", "m")
        .replace(".", "p")
        .replace("+", "")
        .replace(" ", "")
        .replace(":", "")
        .replace("/", "_")
        .replace("\\", "_")
    )


def _sample_evenly(items: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    """Select an exact-size deterministic subset, repeating only if the budget exceeds the grid."""
    if budget <= 0:
        raise ValueError("trial budget must be positive")
    if not items:
        raise ValueError("cannot sample an empty tuning grid")
    if len(items) < budget:
        repeats: list[dict[str, Any]] = []
        while len(repeats) < budget:
            repeats.extend(items)
        return repeats[:budget]
    if len(items) == budget:
        return list(items)
    if budget == 1:
        return [items[len(items) // 2]]
    idxs = sorted({round(i * (len(items) - 1) / (budget - 1)) for i in range(budget)})
    sampled = [items[int(idx)] for idx in idxs]
    cursor = 0
    while len(sampled) < budget:
        if items[cursor] not in sampled:
            sampled.append(items[cursor])
        cursor += 1
    return sampled[:budget]


def _base_ladder_args(
    args: argparse.Namespace, *, duration_s: float, num_runs: int, seed_start: int
) -> argparse.Namespace:
    return argparse.Namespace(
        outdir="",
        merge_existing_raw=False,
        duration_s=float(duration_s),
        num_runs=int(num_runs),
        seed_start=int(seed_start),
        max_workers=int(args.max_workers),
        nx=int(args.nx),
        ny=int(args.ny),
        nrobots=int(args.nrobots),
        warmup_s=float(args.warmup_s),
        task_replan_period_s=float(args.task_replan_period_s),
        reservation_fraction=float(args.reservation_fraction),
        mu_true=float(args.mu_true),
        alpha_true=float(args.alpha_true),
        beta_true=float(args.beta_true),
        sigma_true=float(args.sigma_true),
        omega_true=float(args.omega_true),
        deterrence_beta_scale=float(args.deterrence_beta_scale),
        deterrence_sigma_scale=float(args.deterrence_sigma_scale),
        deterrence_omega_scale=float(args.deterrence_omega_scale),
        fixed_cue_mode=str(args.fixed_cue_mode),
        habituation_kappa=float(args.habituation_kappa),
        truth_habituation_t_rec_s=args.truth_habituation_t_rec_s,
        truth_habituation_kappa=args.truth_habituation_kappa,
        truth_habituation_gamma=args.truth_habituation_gamma,
        truth_habituation_update_model=args.truth_habituation_update_model,
        planner_habituation_t_rec_s=args.planner_habituation_t_rec_s,
        planner_habituation_kappa=args.planner_habituation_kappa,
        planner_habituation_gamma=args.planner_habituation_gamma,
        planner_habituation_update_model=args.planner_habituation_update_model,
        stl_e_star=float(args.stl_e_star),
        stl_t_cov_s=float(args.stl_t_cov_s),
        stl_w_s=float(args.stl_w_s),
        stl_eta_min=float(args.stl_eta_min),
        stl_horizon_s=float(args.stl_horizon_s),
        stl_theta=float(args.stl_theta),
        systems=[],
    )


def _confirm_source_args(
    args: argparse.Namespace, tuning_args: dict[str, Any] | None
) -> argparse.Namespace:
    if not tuning_args:
        return args
    merged = dict(vars(args))
    merged.update(tuning_args)
    for key in CONFIRM_RUNTIME_ARG_KEYS:
        if hasattr(args, key):
            merged[key] = getattr(args, key)
    return argparse.Namespace(**merged)


def _system_params(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    systems = ladder._system_params(args)
    systems["B5_res_habcue_multicue"] = {
        **ladder._proposed_generation_params(),
        **ladder._reserved_dispatch_params(args),
        "predictive_fixed_deterring_mode": None,
        "predictive_utility_mode": "legacy_habituation",
    }
    return systems


def _materialized_common_params(base_args: argparse.Namespace) -> dict[str, Any]:
    common = ladder._common_params(base_args)
    profile_name = str(common.get("planner_profile") or "")
    if profile_name:
        common.update(get_planner_profile_values(profile_name))
    common["planner_profile"] = ""
    return common


def _trial_overrides(combo: dict[str, Any], *, reserved: bool) -> dict[str, Any]:
    """Build parameter overrides from a structural combo. Does NOT set cue mode."""
    horizon_s = float(combo["horizon_s"])
    out: dict[str, Any] = {
        "model_deterring_budget_per_robot_per_hr": int(combo["budget_per_robot_per_hr"]),
        "model_deterring_score_margin": float(combo["score_margin"]),
        "model_deterring_max_eta_s": float(combo["max_eta_s"]),
        "predictive_lead_time_max_eta_s": float(combo["max_eta_s"]),
        "forecast_horizon_s": horizon_s,
        "stl_horizon_s": horizon_s,
    }
    if reserved:
        out["reservation_fraction"] = float(combo["reservation_fraction"])
    return out


def build_structural_trial_plan(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build structural tuning trials shared across all systems.

    The same N structural configs (rho × budget × margin × eta × horizon) are evaluated
    by every system. Fixed-cue systems receive the default cue mode (args.fixed_cue_mode)
    as a proxy during this phase; cue mode is optimised separately in build_cue_mode_trial_plan.

    Using the same structural configs for all systems guarantees that the jointly-selected
    config gives B3 and B4 (and the other reserved systems) identical reservation_fraction,
    forecast_horizon_s, budget, margin, and max_eta_s, making the hab_off null check valid.

    Returns:
        (trials, struct_samples) — struct_samples[i-1] is the combo for struct_index i.
    """
    struct_grid = [
        {
            "reservation_fraction": float(rho),
            "budget_per_robot_per_hr": int(budget),
            "score_margin": float(score_margin),
            "max_eta_s": float(max_eta_s),
            "horizon_s": float(horizon_s),
        }
        for rho, budget, score_margin, max_eta_s, horizon_s in itertools.product(
            args.reservation_fraction_values,
            args.budget_values,
            args.score_margin_values,
            args.max_eta_values,
            args.horizon_values,
        )
    ]
    struct_samples = _sample_evenly(struct_grid, int(args.trial_budget))

    trials: list[dict[str, Any]] = []
    for baseline in args.systems:
        canonical = SYSTEM_ALIASES.get(baseline, baseline)
        reserved = canonical in RESERVED_SYSTEMS
        for struct_idx, struct_combo in enumerate(struct_samples, start=1):
            trial_id = f"{canonical}_struct_{struct_idx:03d}"
            overrides = _trial_overrides(struct_combo, reserved=reserved)
            if canonical in FIXED_CUE_SYSTEMS:
                overrides["predictive_fixed_deterring_mode"] = str(args.fixed_cue_mode)
            trials.append(
                {
                    "trial_id": trial_id,
                    "trial_index": struct_idx,
                    "struct_index": struct_idx,
                    "baseline": canonical,
                    "reserved_dispatch": bool(reserved),
                    "overrides": overrides,
                }
            )

    return trials, struct_samples


def build_cue_mode_trial_plan(
    args: argparse.Namespace,
    struct_combo: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build cue-mode trials for fixed-cue systems at the jointly-selected structural config.

    Each fixed-cue system evaluates every cue mode independently with the chosen structural
    parameters held fixed. Selection is then per-system (not joint), because cue mode is
    the only genuinely system-specific tunable.
    """
    trials: list[dict[str, Any]] = []
    for baseline in args.systems:
        canonical = SYSTEM_ALIASES.get(baseline, baseline)
        if canonical not in FIXED_CUE_SYSTEMS:
            continue
        reserved = canonical in RESERVED_SYSTEMS
        for cue_idx, cue in enumerate(args.fixed_cue_values, start=1):
            trial_id = f"{canonical}_cue_{cue}"
            overrides = _trial_overrides(struct_combo, reserved=reserved)
            overrides["predictive_fixed_deterring_mode"] = str(cue)
            trials.append(
                {
                    "trial_id": trial_id,
                    "trial_index": cue_idx,
                    "struct_index": 0,
                    "baseline": canonical,
                    "reserved_dispatch": bool(reserved),
                    "overrides": overrides,
                }
            )
    return trials


# Backward-compatible alias so downstream code that calls build_trial_plan still works.
def build_trial_plan(args: argparse.Namespace) -> list[dict[str, Any]]:
    trials, _ = build_structural_trial_plan(args)
    return trials


def _build_jobs_for_trial(
    base_args: argparse.Namespace,
    trial: dict[str, Any],
    *,
    phase: str,
    habituation_conditions: list[str],
) -> list[dict[str, Any]]:
    common = _materialized_common_params(base_args)
    systems = _system_params(base_args)
    baseline = SYSTEM_ALIASES.get(str(trial["baseline"]), str(trial["baseline"]))
    if baseline not in systems:
        raise ValueError(f"Unknown baseline {baseline!r}. Expected one of: {sorted(systems)}")

    jobs: list[dict[str, Any]] = []
    for seed in range(
        int(base_args.seed_start), int(base_args.seed_start) + int(base_args.num_runs)
    ):
        for hab_enabled in (True, False):
            hab_params = ladder._habituation_params(hab_enabled, base_args)
            if str(hab_params["habituation_condition"]) not in habituation_conditions:
                continue
            params = dict(common)
            params.update(systems[baseline])
            params.update(hab_params)
            params.update(dict(trial["overrides"]))
            system = f"{baseline}_{hab_params['habituation_condition']}"
            jobs.append(
                {
                    "system": system,
                    "baseline": baseline,
                    "habituation_condition": hab_params["habituation_condition"],
                    "seed": seed,
                    "params": params,
                    "trial_id": str(trial["trial_id"]),
                    "trial_index": int(trial["trial_index"]),
                    "struct_index": int(trial.get("struct_index", 0)),
                    "phase": str(phase),
                }
            )
    return jobs


def _run_one(job: dict[str, Any]) -> dict[str, Any]:
    row = ladder._run_one(job)
    row["phase"] = str(job["phase"])
    row["trial_id"] = str(job["trial_id"])
    row["trial_index"] = int(job["trial_index"])
    row["struct_index"] = int(job.get("struct_index", 0))
    for key, value in dict(job["params"]).items():
        if key in {
            "reservation_fraction",
            "model_deterring_budget_per_robot_per_hr",
            "model_deterring_score_margin",
            "model_deterring_max_eta_s",
            "predictive_lead_time_max_eta_s",
            "forecast_horizon_s",
            "stl_horizon_s",
            "predictive_utility_mode",
            "dispatch_policy",
            "predictive_fixed_deterring_mode",
            "stl_active_clauses",
        }:
            row[f"config_{key}"] = value
    return row


def _run_jobs(
    jobs: list[dict[str, Any]], raw_dir: Path, *, max_workers: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    max_workers = max(1, min(int(max_workers), len(jobs))) if jobs else 1
    print(f"[fair-tuning] jobs={len(jobs)} max_workers={max_workers}", flush=True)
    if max_workers == 1:
        for idx, job in enumerate(jobs, start=1):
            print(
                f"[fair-tuning] start {idx}/{len(jobs)} {job['trial_id']} "
                f"{job['system']} seed={job['seed']}",
                flush=True,
            )
            row = _run_one(job)
            rows.append(row)
            _write_raw_row(row, raw_dir)
            print(
                f"[fair-tuning] done {idx}/{len(jobs)} {row['trial_id']} "
                f"{row['system']} seed={row['seed']} Jexp={row['value_weighted_exposure']:.3f}",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_run_one, job): job for job in jobs}
            for idx, future in enumerate(as_completed(future_map), start=1):
                row = future.result()
                rows.append(row)
                _write_raw_row(row, raw_dir)
                print(
                    f"[fair-tuning] done {idx}/{len(jobs)} {row['trial_id']} "
                    f"{row['system']} seed={row['seed']} Jexp={row['value_weighted_exposure']:.3f}",
                    flush=True,
                )
    print(f"[fair-tuning] phase elapsed={time.time() - started:.1f}s", flush=True)
    return rows


def _write_raw_row(row: dict[str, Any], raw_dir: Path) -> None:
    filename = (
        f"{_token(row.get('phase'))}_{_token(row.get('trial_id'))}_"
        f"{_token(row.get('habituation_condition'))}_seed_{int(row['seed'])}.json"
    )
    _json_dump(raw_dir / filename, row)


def _load_raw_rows(raw_dir: Path, *, phase: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        if phase is not None and str(row.get("phase")) != str(phase):
            continue
        rows.append(row)
    return rows


def _selection_penalty(summary: dict[str, Any], args: argparse.Namespace) -> float:
    penalty = 0.0
    scale = float(args.guardrail_penalty)
    expired = _safe_float(summary.get("predictive_expired_fraction_mean"))
    cov = _safe_float(summary.get("stl_robustness_cov_mean"))
    response = _safe_float(summary.get("mean_response_time_s_mean"))
    if args.guardrail_max_predictive_expired_fraction is not None and math.isfinite(expired):
        excess = max(0.0, expired - float(args.guardrail_max_predictive_expired_fraction))
        penalty += scale * excess
    if args.guardrail_min_coverage_robustness is not None and math.isfinite(cov):
        shortfall = max(0.0, float(args.guardrail_min_coverage_robustness) - cov)
        penalty += scale * shortfall
    if args.guardrail_max_mean_response_time_s is not None and math.isfinite(response):
        excess = max(0.0, response - float(args.guardrail_max_mean_response_time_s))
        penalty += scale * excess
    return float(penalty)


def summarize_trials(
    rows: list[dict[str, Any]], args: argparse.Namespace
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["baseline"]), str(row["trial_id"]), str(row["habituation_condition"]))
        groups.setdefault(key, []).append(row)

    out: list[dict[str, Any]] = []
    metric_fields = list(ladder.METRIC_FIELDS)
    config_fields = sorted(k for row in rows for k in row if k.startswith("config_"))
    for (baseline, trial_id, hab), sub in sorted(groups.items()):
        summary: dict[str, Any] = {
            "baseline": baseline,
            "trial_id": trial_id,
            "trial_index": int(sub[0].get("trial_index", 0)),
            "struct_index": int(sub[0].get("struct_index", 0)),
            "habituation_condition": hab,
            "n": len(sub),
        }
        for key in config_fields:
            summary[key] = sub[0].get(key, "")
        for field in metric_fields:
            vals = [_safe_float(row.get(field)) for row in sub]
            vals = [v for v in vals if math.isfinite(v)]
            summary[f"{field}_mean"] = float(stats.mean(vals)) if vals else float("nan")
            summary[f"{field}_sd"] = float(stats.pstdev(vals)) if len(vals) > 1 else 0.0
        if hab == str(args.selection_habituation_condition):
            metric = str(args.selection_metric)
            base_score = _safe_float(summary.get(f"{metric}_mean"))
            if not math.isfinite(base_score):
                base_score = float("inf")
            if metric not in LOWER_IS_BETTER:
                base_score = -base_score
            summary["selection_penalty"] = _selection_penalty(summary, args)
            summary["selection_score"] = float(base_score + summary["selection_penalty"])
        else:
            summary["selection_penalty"] = float("nan")
            summary["selection_score"] = float("nan")
        out.append(summary)
    return out


def select_best_structural_combo(
    summaries: list[dict[str, Any]],
    args: argparse.Namespace,
    struct_samples: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    """Joint structural selection for reserved-dispatch systems.

    Finds the struct_index whose mean selection score is lowest across all reserved systems.
    Prefers indices where all reserved systems have complete data. Returns the struct_combo
    and the winning struct_index (1-based).
    """
    sel_hab = str(args.selection_habituation_condition)
    reserved_systems = {SYSTEM_ALIASES.get(s, s) for s in args.systems if SYSTEM_ALIASES.get(s, s) in RESERVED_SYSTEMS}

    joint: dict[int, list[float]] = {}
    for row in summaries:
        if str(row.get("habituation_condition")) != sel_hab:
            continue
        baseline = SYSTEM_ALIASES.get(str(row["baseline"]), str(row["baseline"]))
        if baseline not in reserved_systems:
            continue
        struct_idx = int(row.get("struct_index", 0))
        if struct_idx <= 0:
            continue
        score = _safe_float(row.get("selection_score"))
        if math.isfinite(score):
            joint.setdefault(struct_idx, []).append(score)

    if not joint:
        raise ValueError("No valid structural trial scores found for reserved systems")

    n_reserved = len(reserved_systems)
    complete = {idx: s for idx, s in joint.items() if len(s) >= n_reserved}
    candidates = complete if complete else joint

    best_idx = min(candidates, key=lambda idx: float(stats.mean(candidates[idx])))
    return struct_samples[best_idx - 1], best_idx


def select_best_cue_modes(
    summaries: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, str]:
    """Per-system cue mode selection for fixed-cue systems from the cue-phase summaries.

    Selection is independent per system (cue mode is the only system-specific tunable).
    Returns {baseline: cue_mode_string}.
    """
    sel_hab = str(args.selection_habituation_condition)
    best: dict[str, tuple[float, str]] = {}
    for row in summaries:
        if str(row.get("habituation_condition")) != sel_hab:
            continue
        baseline = str(row["baseline"])
        if baseline not in FIXED_CUE_SYSTEMS:
            continue
        cue_mode = str(row.get("config_predictive_fixed_deterring_mode", ""))
        score = _safe_float(row.get("selection_score"))
        if not math.isfinite(score) or not cue_mode:
            continue
        prev = best.get(baseline)
        if prev is None or score < prev[0]:
            best[baseline] = (score, cue_mode)
    return {b: cue for b, (_, cue) in best.items()}


def select_best_trials(
    trial_summaries: list[dict[str, Any]],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    """Return the selected summary row for each system.

    Reserved-dispatch systems (B2, B3, B4, B5_res) are assigned the struct_index whose
    mean selection score is lowest across the entire reserved group.  This forces B3 and B4
    to share the same reservation_fraction, horizon, budget, margin, and max_eta_s, so that
    the hab_off null check is interpretable and the mechanism comparison is valid.

    Non-reserved systems (B1, B5_greedy) select independently because they do not share
    reservation_fraction with the reserved group.
    """
    sel_hab = str(args.selection_habituation_condition)
    reserved_systems = {SYSTEM_ALIASES.get(s, s) for s in args.systems if SYSTEM_ALIASES.get(s, s) in RESERVED_SYSTEMS}

    # Collect per-(baseline, struct_index) scores for the reserved group
    joint: dict[int, list[float]] = {}
    for row in trial_summaries:
        if str(row.get("habituation_condition")) != sel_hab:
            continue
        baseline = SYSTEM_ALIASES.get(str(row["baseline"]), str(row["baseline"]))
        if baseline not in reserved_systems:
            continue
        struct_idx = int(row.get("struct_index", row.get("trial_index", 0)))
        score = _safe_float(row.get("selection_score"))
        if math.isfinite(score):
            joint.setdefault(struct_idx, []).append(score)

    n_reserved = len(reserved_systems)
    complete = {idx: s for idx, s in joint.items() if len(s) >= n_reserved}
    candidates = complete if complete else joint
    best_joint_idx: int | None = (
        min(candidates, key=lambda idx: float(stats.mean(candidates[idx])))
        if candidates
        else None
    )

    result: list[dict[str, Any]] = []
    for baseline in args.systems:
        canonical_baseline = SYSTEM_ALIASES.get(baseline, baseline)
        matching = [
            row
            for row in trial_summaries
            if SYSTEM_ALIASES.get(str(row["baseline"]), str(row["baseline"])) == canonical_baseline
            and str(row.get("habituation_condition")) == sel_hab
        ]
        if not matching:
            continue

        if canonical_baseline in reserved_systems and best_joint_idx is not None:
            at_joint = [
                row
                for row in matching
                if int(row.get("struct_index", row.get("trial_index", 0))) == best_joint_idx
            ]
            if at_joint:
                result.append(at_joint[0])
                continue

        # Non-reserved or fallback: independent best
        finite = [r for r in matching if math.isfinite(_safe_float(r.get("selection_score")))]
        if finite:
            best_row = min(
                finite,
                key=lambda r: (
                    _safe_float(r.get("selection_score")),
                    _safe_float(r.get("mean_response_time_s_mean", float("inf"))),
                ),
            )
            result.append(best_row)

    return result


def _selection_to_trial(selection: dict[str, Any]) -> dict[str, Any]:
    numeric_keys = {
        "reservation_fraction": "config_reservation_fraction",
        "model_deterring_budget_per_robot_per_hr": "config_model_deterring_budget_per_robot_per_hr",
        "model_deterring_score_margin": "config_model_deterring_score_margin",
        "model_deterring_max_eta_s": "config_model_deterring_max_eta_s",
        "predictive_lead_time_max_eta_s": "config_predictive_lead_time_max_eta_s",
        "forecast_horizon_s": "config_forecast_horizon_s",
        "stl_horizon_s": "config_stl_horizon_s",
    }
    overrides: dict[str, Any] = {}
    for target, source in numeric_keys.items():
        value = selection.get(source, "")
        if value == "" or value is None:
            continue
        fval = _safe_float(value)
        if math.isfinite(fval):
            overrides[target] = (
                int(fval) if target.endswith("_per_robot_per_hr") else float(fval)
            )
    cue = selection.get("config_predictive_fixed_deterring_mode", "")
    if cue not in ("", None):
        overrides["predictive_fixed_deterring_mode"] = str(cue)
    return {
        "trial_id": f"{selection['baseline']}_selected",
        "trial_index": int(selection.get("trial_index", 0)),
        "baseline": str(selection["baseline"]),
        "reserved_dispatch": SYSTEM_ALIASES.get(str(selection["baseline"]), str(selection["baseline"])) in RESERVED_SYSTEMS,
        "overrides": overrides,
        "selected_from_trial_id": str(selection["trial_id"]),
        "tuning_selection_score": _safe_float(selection.get("selection_score")),
    }


def _comparison_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparisons = [
        ("B4_vs_B1", "B4_res_stl_full_multicue", "B1_greedy_fixedcue"),
        ("B4_vs_B2", "B4_res_stl_full_multicue", "B2_res_deltaJ_fixedcue"),
        ("B4_vs_B3", "B4_res_stl_full_multicue", "B3_res_stl_nohab_multicue"),
        ("B4_vs_B5_greedy", "B4_res_stl_full_multicue", "B5_greedy_habcue"),
        ("B4_vs_B5_res", "B4_res_stl_full_multicue", "B5_res_habcue_multicue"),
        ("B3_vs_B2", "B3_res_stl_nohab_multicue", "B2_res_deltaJ_fixedcue"),
    ]
    out = []
    for hab in ("hab_on", "hab_off"):
        for label, system, reference in comparisons:
            deltas = ladder._paired_deltas(rows, system, reference, hab, "value_weighted_exposure")
            if not deltas:
                continue
            lo, hi = ladder._ci95(deltas)
            out.append(
                {
                    "comparison": label,
                    "habituation_condition": hab,
                    "system": system,
                    "reference": reference,
                    "metric": "value_weighted_exposure",
                    "mean_system_minus_reference": float(stats.mean(deltas)),
                    "ci95_lo": lo,
                    "ci95_hi": hi,
                    "seeds_system_lower": sum(1 for d in deltas if d < 0.0),
                    "paired_seed_count": len(deltas),
                }
            )
    return out


def _write_report(
    outdir: Path,
    args: argparse.Namespace,
    selected: list[dict[str, Any]],
    confirm_rows: list[dict[str, Any]],
    *,
    tuning_args: dict[str, Any] | None = None,
    best_struct_combo: dict[str, Any] | None = None,
    best_cue_modes: dict[str, str] | None = None,
) -> None:
    tuning_args = dict(tuning_args or vars(args))
    tune_seed_start = int(tuning_args.get("tune_seed_start", args.tune_seed_start))
    tune_num_runs = int(tuning_args.get("tune_num_runs", args.tune_num_runs))
    trial_budget = int(tuning_args.get("trial_budget", args.trial_budget))
    selection_metric = str(tuning_args.get("selection_metric", args.selection_metric))
    selection_condition = str(
        tuning_args.get("selection_habituation_condition", args.selection_habituation_condition)
    )
    lines = [
        "# Habituation STL Fair Tuning Protocol",
        "",
        "Two-phase design: (1) joint structural search across all systems on tuning seeds, "
        "(2) per-system cue-mode search for fixed-cue systems at the selected structural config. "
        "Winners are frozen and evaluated on held-out confirmation seeds.",
        "",
        "## Protocol",
        "",
        f"- Tuning seeds: {tune_seed_start}-{tune_seed_start + tune_num_runs - 1}",
        f"- Confirmation seeds: {args.confirm_seed_start}-{args.confirm_seed_start + args.confirm_num_runs - 1}",
        f"- Structural configs per system: {trial_budget}",
        f"- Selection metric: `{selection_metric}` under `{selection_condition}`",
        "",
        "### Structural phase",
        "All systems evaluate the same N structural configs "
        "(reservation_fraction × budget × score_margin × max_eta_s × forecast_horizon_s). "
        "Fixed-cue systems use the default cue mode as a proxy. "
        "The config with the lowest mean score across all reserved-dispatch systems "
        "(B2, B3, B4, B5_res) is selected jointly, guaranteeing identical structural "
        "parameters for all reserved-system comparisons.",
        "",
        "### Cue-mode phase",
        "Fixed-cue systems (B1, B2) independently evaluate all cue modes at the "
        "selected structural config. Selection is per-system (cue mode is the only "
        "system-specific tunable). B3 is multicue and excluded from this phase.",
        "",
        "### Validity invariant",
        "B4 − B3 under hab_off must be near zero. If it is not, the configs are not "
        "comparable and the mechanism comparison is invalid. This design enforces identical "
        "structural configs for B3 and B4, so the invariant should hold.",
        "",
    ]
    if best_struct_combo:
        lines += [
            "## Selected Structural Config (shared by all systems)",
            "",
            f"```json\n{json.dumps(best_struct_combo, indent=2, sort_keys=True)}\n```",
            "",
        ]
    if best_cue_modes:
        lines += [
            "## Selected Cue Modes (per fixed-cue system)",
            "",
        ]
        for baseline, cue in sorted(best_cue_modes.items()):
            lines.append(f"- `{baseline}`: `{cue}`")
        lines.append("")

    lines += [
        "## Final Selected Configs",
        "",
        "| Baseline | Selected trial | Selection score | Overrides |",
        "|---|---|---:|---|",
    ]
    for row in selected:
        trial = dict(row) if "overrides" in row else _selection_to_trial(row)
        lines.append(
            f"| {trial['baseline']} | {trial.get('selected_from_trial_id', trial['trial_id'])} | "
            f"{trial['tuning_selection_score']:.3f} | `{json.dumps(trial['overrides'], sort_keys=True)}` |"
        )
    if confirm_rows:
        lines.extend(
            [
                "",
                "## Held-Out Confirmation Comparisons",
                "",
                "| Comparison | Habituation | Mean delta | 95% CI | Seeds improved |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for row in _comparison_summary(confirm_rows):
            lines.append(
                f"| {row['comparison']} | {row['habituation_condition']} | "
                f"{row['mean_system_minus_reference']:.3f} | "
                f"[{row['ci95_lo']:.3f}, {row['ci95_hi']:.3f}] | "
                f"{row['seeds_system_lower']}/{row['paired_seed_count']} |"
            )
        lines.extend(["", "Negative deltas are better because lower exposure is better."])
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            "- `tuning_structural_trials.csv`: all per-seed structural phase rows.",
            "- `tuning_structural_summary.csv`: mean metrics and selection scores from structural phase.",
            "- `tuning_cue_trials.csv`: all per-seed cue-mode phase rows.",
            "- `tuning_cue_summary.csv`: mean metrics and selection scores from cue-mode phase.",
            "- `tuning_trials.csv`: combined structural + cue rows.",
            "- `selected_configs.json`: frozen winners (structural config + per-system cue mode).",
            "- `confirm_per_run_metrics.csv`: held-out confirmation rows, if confirmation was run.",
            "- `confirm_summary_by_system.csv`: held-out summary by system, if confirmation was run.",
            "- `confirm_comparisons.csv`: held-out paired exposure comparisons, if confirmation was run.",
        ]
    )
    (outdir / "FAIR_TUNING_PROTOCOL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_tune(args: argparse.Namespace) -> list[dict[str, Any]]:
    outdir = Path(args.outdir).resolve()
    tune_raw = outdir / "tuning_raw"
    outdir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: structural grid search ──────────────────────────────────────
    struct_trials, struct_samples = build_structural_trial_plan(args)

    _json_dump(
        outdir / "tuning_protocol.json",
        {
            "args": vars(args),
            "systems": list(args.systems),
            "trial_budget": int(args.trial_budget),
            "structural_trial_count": len(struct_trials),
            "struct_samples": struct_samples,
        },
    )
    if bool(args.dry_run):
        print(f"[fair-tuning] dry run wrote {outdir / 'tuning_protocol.json'}", flush=True)
        return []

    base_args = _base_ladder_args(
        args,
        duration_s=float(args.tune_duration_s),
        num_runs=int(args.tune_num_runs),
        seed_start=int(args.tune_seed_start),
    )

    struct_jobs: list[dict[str, Any]] = []
    for trial in struct_trials:
        struct_jobs.extend(
            _build_jobs_for_trial(
                base_args,
                trial,
                phase="tune_struct",
                habituation_conditions=[str(args.selection_habituation_condition)],
            )
        )

    print(
        f"[fair-tuning] Phase 1: structural search "
        f"({len(struct_trials)} trials × {args.tune_num_runs} seeds = {len(struct_jobs)} jobs)",
        flush=True,
    )
    struct_rows = _run_jobs(struct_jobs, tune_raw, max_workers=int(args.max_workers))
    struct_rows = sorted(
        struct_rows, key=lambda r: (str(r["baseline"]), int(r["trial_index"]), int(r["seed"]))
    )
    _write_csv(struct_rows, outdir / "tuning_structural_trials.csv")

    struct_summaries = summarize_trials(struct_rows, args)
    _write_csv(struct_summaries, outdir / "tuning_structural_summary.csv")

    best_struct_combo, best_struct_idx = select_best_structural_combo(
        struct_summaries, args, struct_samples
    )
    print(
        f"[fair-tuning] Joint structural selection: struct_index={best_struct_idx} "
        f"config={json.dumps(best_struct_combo, sort_keys=True)}",
        flush=True,
    )

    # ── Phase 2: cue-mode search for fixed-cue systems ───────────────────────
    cue_trials = build_cue_mode_trial_plan(args, best_struct_combo)

    cue_jobs: list[dict[str, Any]] = []
    for trial in cue_trials:
        cue_jobs.extend(
            _build_jobs_for_trial(
                base_args,
                trial,
                phase="tune_cue",
                habituation_conditions=[str(args.selection_habituation_condition)],
            )
        )

    print(
        f"[fair-tuning] Phase 2: cue-mode search "
        f"({len(cue_trials)} trials × {args.tune_num_runs} seeds = {len(cue_jobs)} jobs)",
        flush=True,
    )
    cue_rows = _run_jobs(cue_jobs, tune_raw, max_workers=int(args.max_workers))
    cue_rows = sorted(
        cue_rows, key=lambda r: (str(r["baseline"]), int(r["trial_index"]), int(r["seed"]))
    )
    _write_csv(cue_rows, outdir / "tuning_cue_trials.csv")
    _write_csv(struct_rows + cue_rows, outdir / "tuning_trials.csv")

    cue_summaries = summarize_trials(cue_rows, args)
    _write_csv(cue_summaries, outdir / "tuning_cue_summary.csv")

    best_cue_modes = select_best_cue_modes(cue_summaries, args)
    print(
        f"[fair-tuning] Per-system cue selection: {json.dumps(best_cue_modes, sort_keys=True)}",
        flush=True,
    )

    # ── Assemble final selected configs ──────────────────────────────────────
    # Use structural selection rows, patched with the optimised cue mode for fixed-cue systems.
    struct_selected = select_best_trials(struct_summaries, args)
    final_selected: list[dict[str, Any]] = []
    for row in struct_selected:
        row = dict(row)
        baseline = str(row["baseline"])
        if baseline in best_cue_modes:
            row["config_predictive_fixed_deterring_mode"] = best_cue_modes[baseline]
        final_selected.append(row)

    _write_csv(final_selected, outdir / "selected_configs.csv")
    _json_dump(
        outdir / "selected_configs.json",
        [_selection_to_trial(row) for row in final_selected],
    )
    _write_report(
        outdir,
        args,
        [_selection_to_trial(r) for r in final_selected],
        [],
        tuning_args=vars(args),
        best_struct_combo=best_struct_combo,
        best_cue_modes=best_cue_modes,
    )
    print(
        f"[fair-tuning] selected {len(final_selected)} configs -> {outdir / 'selected_configs.json'}",
        flush=True,
    )
    return final_selected


def run_confirm(
    args: argparse.Namespace, selected_rows: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    outdir = Path(args.outdir).resolve()
    confirm_raw = outdir / "confirm_raw"
    tuning_args = None
    if selected_rows is None:
        selected_path = Path(args.selection_path or outdir / "selected_configs.json").resolve()
        selected_trials = json.loads(selected_path.read_text(encoding="utf-8"))
        protocol_path = selected_path.parent / "tuning_protocol.json"
        if protocol_path.exists():
            try:
                tuning_args = json.loads(protocol_path.read_text(encoding="utf-8")).get("args")
            except Exception:
                tuning_args = None
    else:
        selected_trials = [_selection_to_trial(row) for row in selected_rows]
        tuning_args = vars(args)
    if bool(args.dry_run):
        print("[fair-tuning] dry run skipped confirmation", flush=True)
        return []

    confirm_source_args = _confirm_source_args(args, tuning_args)
    base_args = _base_ladder_args(
        confirm_source_args,
        duration_s=float(args.confirm_duration_s),
        num_runs=int(args.confirm_num_runs),
        seed_start=int(args.confirm_seed_start),
    )
    systems_filter = set(getattr(confirm_source_args, "systems", None) or [])
    if systems_filter:
        # Resolve aliases in both directions: the filter may use canonical names while
        # selected_configs.json may store legacy names (e.g. B3_res_stl_nohab_fixedcue).
        canonical_filter = {SYSTEM_ALIASES.get(s, s) for s in systems_filter}
        selected_trials = [
            t for t in selected_trials
            if SYSTEM_ALIASES.get(str(t["baseline"]), str(t["baseline"])) in canonical_filter
        ]
    jobs: list[dict[str, Any]] = []
    for trial in selected_trials:
        jobs.extend(
            _build_jobs_for_trial(
                base_args,
                trial,
                phase="confirm",
                habituation_conditions=["hab_on", "hab_off"],
            )
        )
    rows = _run_jobs(jobs, confirm_raw, max_workers=int(args.max_workers))
    rows = sorted(
        rows,
        key=lambda r: (str(r["baseline"]), str(r["habituation_condition"]), int(r["seed"])),
    )
    _write_csv(rows, outdir / "confirm_per_run_metrics.csv")
    _write_csv(ladder._summarize(rows), outdir / "confirm_summary_by_system.csv")
    _write_csv(ladder._advantage_rows(rows), outdir / "confirm_advantage_vs_reference.csv")
    _write_csv(ladder._habituation_delta_rows(rows), outdir / "confirm_habituation_on_vs_off.csv")
    _write_csv(_comparison_summary(rows), outdir / "confirm_comparisons.csv")
    ladder._write_markdown_summary(rows, outdir)
    selected_for_report = selected_rows if selected_rows is not None else selected_trials
    _write_report(outdir, args, selected_for_report, rows, tuning_args=tuning_args)
    print(f"[fair-tuning] confirmation wrote {outdir}", flush=True)
    return rows


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fair tuning wrapper for the habituation/STL production ladder. Two-phase design: "
            "(1) joint structural search (same N configs for all systems, joint selection for "
            "reserved-dispatch systems), (2) per-system cue-mode search at the selected structural "
            "config. Winners are confirmed on held-out seeds."
        )
    )
    parser.add_argument("--outdir", default="results/testbench/habituation_stl_fair_tuning")
    parser.add_argument("--phase", choices=["tune", "confirm", "tune_confirm"], default="tune_confirm")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selection-path", default=None)
    parser.add_argument("--systems", nargs="*", default=DEFAULT_SYSTEMS)
    # trial_budget = number of structural configs evaluated per system
    parser.add_argument("--trial-budget", type=int, default=18)
    parser.add_argument("--selection-metric", default="value_weighted_exposure")
    parser.add_argument(
        "--selection-habituation-condition", default="hab_on", choices=["hab_on", "hab_off"]
    )
    parser.add_argument("--guardrail-max-predictive-expired-fraction", type=float, default=None)
    parser.add_argument("--guardrail-min-coverage-robustness", type=float, default=None)
    parser.add_argument("--guardrail-max-mean-response-time-s", type=float, default=None)
    parser.add_argument("--guardrail-penalty", type=float, default=1.0e9)
    parser.add_argument("--budget-values", nargs="+", type=int, default=[3, 4, 6])
    parser.add_argument("--score-margin-values", nargs="+", type=float, default=[0.05, 0.10])
    parser.add_argument("--max-eta-values", nargs="+", type=float, default=[90.0, 120.0])
    parser.add_argument("--horizon-values", nargs="+", type=float, default=[240.0, 300.0, 420.0])
    parser.add_argument(
        "--reservation-fraction-values", nargs="+", type=float, default=[0.10, 0.25, 0.40]
    )
    parser.add_argument(
        "--fixed-cue-values", nargs="+", default=["formation", "laser", "biosonic"]
    )
    parser.add_argument("--tune-duration-s", type=float, default=900.0)
    # ≥10 seeds required for adequate STL variance in structural selection
    parser.add_argument("--tune-num-runs", type=int, default=10)
    parser.add_argument("--tune-seed-start", type=int, default=100)
    parser.add_argument("--confirm-duration-s", type=float, default=1800.0)
    parser.add_argument("--confirm-num-runs", type=int, default=10)
    parser.add_argument("--confirm-seed-start", type=int, default=125)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--nx", type=int, default=60)
    parser.add_argument("--ny", type=int, default=48)
    parser.add_argument("--nrobots", type=int, default=4)
    parser.add_argument("--warmup-s", type=float, default=0.0)
    parser.add_argument("--task-replan-period-s", type=float, default=45.0)
    parser.add_argument("--reservation-fraction", type=float, default=0.25)
    parser.add_argument("--mu-true", type=float, default=2.0e-5)
    parser.add_argument("--alpha-true", type=float, default=0.3)
    parser.add_argument("--beta-true", type=float, default=0.25)
    parser.add_argument("--sigma-true", type=float, default=12.0)
    parser.add_argument("--omega-true", type=float, default=600.0)
    parser.add_argument("--deterrence-beta-scale", type=float, default=4.0)
    parser.add_argument("--deterrence-sigma-scale", type=float, default=4.0)
    parser.add_argument("--deterrence-omega-scale", type=float, default=3.0)
    parser.add_argument("--fixed-cue-mode", default="laser")
    parser.add_argument("--habituation-kappa", type=float, default=0.5)
    parser.add_argument("--truth-habituation-t-rec-s", type=float, default=None)
    parser.add_argument("--truth-habituation-kappa", type=float, default=None)
    parser.add_argument("--truth-habituation-gamma", type=float, default=None)
    parser.add_argument("--truth-habituation-update-model", default=None)
    parser.add_argument("--planner-habituation-t-rec-s", type=float, default=None)
    parser.add_argument("--planner-habituation-kappa", type=float, default=None)
    parser.add_argument("--planner-habituation-gamma", type=float, default=None)
    parser.add_argument("--planner-habituation-update-model", default=None)
    parser.add_argument("--stl-e-star", type=float, default=5.0)
    parser.add_argument("--stl-t-cov-s", type=float, default=1200.0)
    parser.add_argument("--stl-w-s", type=float, default=600.0)
    parser.add_argument("--stl-eta-min", type=float, default=0.4)
    parser.add_argument("--stl-horizon-s", type=float, default=300.0)
    parser.add_argument("--stl-theta", type=float, default=12.0)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    selected_rows: list[dict[str, Any]] | None = None
    if args.phase in {"tune", "tune_confirm"}:
        selected_rows = run_tune(args)
    if args.phase in {"confirm", "tune_confirm"}:
        run_confirm(args, selected_rows=selected_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
