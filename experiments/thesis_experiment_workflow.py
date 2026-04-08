from __future__ import annotations

from typing import Dict, List


EXPERIMENT_STAGE_ORDER = [
    "model_calibration",
    "field_divergence_lab",
    "field_divergence_confirm",
    "assignment_tuning",
    "assignment_method_comparison",
    "robot_scaling",
]


_STAGES: Dict[str, dict] = {
    "model_calibration": {
        "title": "Model Calibration",
        "runner": "run_sestpp_calibration_sweep.py",
        "depends_on": [],
        "optional": False,
        "order_note": "Freeze the intervention-aware SESTPP settings that every downstream stage will reuse.",
        "question": "Which intervention-aware SESTPP hyperparameters best calibrate the proposed field before any planner conclusions are made?",
        "metrics": [
            (
                "proposed_field_logloss_mean / proposed_field_brier_mean / proposed_nll_mean",
                "Primary calibration errors for the proposed model; lower is better.",
            ),
            (
                "logloss_improvement_pct_mean / brier_improvement_pct_mean / nll_improvement_pct_mean",
                "Matched-seed improvement over prediction-only; positive values indicate a better calibrated proposed field.",
            ),
            (
                "*_ci95",
                "Ranking stability across seeds; wide intervals mean the selected configuration is not yet defensible.",
            ),
        ],
        "failure": [
            "No configuration shows stable paired improvement over prediction-only on the main calibration metrics.",
            "The nominal winner still worsens log loss, Brier score, or NLL once CI95 uncertainty is considered.",
        ],
        "confirm_protocol": [],
    },
    "field_divergence_lab": {
        "title": "Field Divergence Lab",
        "runner": "compare_field_divergence_lab.py",
        "depends_on": ["model_calibration"],
        "optional": False,
        "order_note": "Run a diagnostic single-seed or small-scale lab check before claiming robust downstream planner effects.",
        "question": "Does the calibrated proposed field diverge from prediction-only strongly enough to survive local hotspot filtering and patrol generation?",
        "metrics": [
            (
                "suppressed_area_fraction_mean",
                "Minimum evidence that the proposed field is meaningfully different from prediction-only.",
            ),
            (
                "local_hotspots_score_filtered_overlap_mean / local_hotspots_spaced_overlap_mean",
                "Whether filtering and thinning preserve the upstream field difference.",
            ),
            (
                "raw_patrol_candidate_overlap_mean / selected_patrol_overlap_mean / patrol_overlap_mean",
                "Whether task generation, assignment, and queueing collapse the divergence before execution.",
            ),
        ],
        "failure": [
            "suppressed_area_fraction_mean stays below the field-divergence floor, so downstream planner interpretation is not justified.",
            "Any downstream overlap metric rises above the collapse threshold, indicating the planner pipeline is washing out the field difference.",
        ],
        "confirm_protocol": [],
    },
    "field_divergence_confirm": {
        "title": "Field Divergence Confirm",
        "runner": "run_field_divergence_confirm_lab.py",
        "depends_on": ["field_divergence_lab"],
        "optional": False,
        "order_note": "Only advance once the same-seed proposed-vs-prediction comparisons remain favorable across seeds with defensible CI95 bounds.",
        "question": "Across matched seeds, is the proposed-vs-prediction field separation robust enough to support downstream planner claims?",
        "metrics": [
            (
                "final_exposure_improve_pct / final_response_improve_pct",
                "Pairwise proposed-vs-prediction end-of-run deltas on the same seeds.",
            ),
            (
                "suppressed_area_fraction_mean and pipeline-overlap means with CI95",
                "Aggregate evidence that divergence survives filtering, candidate generation, selection, and active patrol execution.",
            ),
            (
                "acceptance status table",
                "PASS/FAIL/WARN summary for whether each CI95 interval stays on the accepted side of its threshold.",
            ),
        ],
        "failure": [
            "CI95 stays fully on the rejected side of a required acceptance threshold.",
            "CI95 straddles a threshold for a required claim, leaving the confirm stage inconclusive and blocking downstream interpretation.",
            "Pairwise exposure or response deltas are not robust when proposed is matched directly against prediction-only on the same seeds.",
        ],
        "confirm_protocol": [
            "Pair proposed and prediction-only runs on the same seed and summarize those deltas, not unmatched aggregate means.",
            "Report mean and CI95 for the paired deltas and the aggregate acceptance metrics in the confirm README/CSV outputs.",
            "Treat threshold-straddling CI95 intervals as inconclusive confirmation rather than a pass.",
        ],
    },
    "assignment_tuning": {
        "title": "Planner / Assignment Tuning",
        "runner": "run_assignment_tuning_sweep_lab.py",
        "depends_on": ["field_divergence_confirm"],
        "optional": False,
        "order_note": "Tune dispatch and gating only after the field-divergence mechanism is confirmed, otherwise planner fixes may optimize around a model artifact.",
        "question": "Which planner, assignment, and gating settings preserve exposure gains without unacceptable response, communication, or solver regressions?",
        "metrics": [
            (
                "exp_improve_pct_mean / resp_improve_pct_mean / comm_increase_pct_mean",
                "Primary proposed-vs-prediction tradeoff metrics for selecting viable planner settings.",
            ),
            (
                "failures_mean / runtime_ms_mean",
                "Operational guardrails for solver feasibility and runtime stability.",
            ),
            (
                "proposed_yield_ratio_model_scored_mean / proposed_queue_depth_total_mean / proposed_stale_task_evictions_count_mean",
                "Checks that model-scored deterring remains productive and the planner is not saturating the queue.",
            ),
        ],
        "failure": [
            "Any candidate produces assignment solver failures or other infeasible behavior.",
            "Communication cost rises sharply without corresponding exposure gain, or response time regresses enough to negate the exposure benefit.",
            "Model-scored deterring yield collapses or queue pressure becomes unstable in the finalist settings.",
        ],
        "confirm_protocol": [],
    },
    "assignment_method_comparison": {
        "title": "Assignment-Method Comparison",
        "runner": "run_assignment_method_comparison_lab.py / plot_assignment_method_comparison_lab.py",
        "depends_on": ["assignment_tuning"],
        "optional": True,
        "order_note": "Use this as an optional solver-ablation stage if method choice still matters after the main tuning sweep.",
        "question": "If solver choice is still open, does another assignment method outperform the tuned default without breaking feasibility, response, or communication?",
        "metrics": [
            (
                "proposed-minus-prediction exposure / response / communication by method",
                "Method-level tradeoffs after controlling for baseline pairing.",
            ),
            (
                "assignment_solver_failures / assignment_solver_runtime_ms",
                "Feasibility and computational cost checks for each method.",
            ),
            (
                "winner-selection manifest rule",
                "Documents the tie-break order used if the stage remains relevant.",
            ),
        ],
        "failure": [
            "A method shows infeasible or unstable assignments.",
            "No method improves the pairwise exposure-response tradeoff enough to justify replacing the tuned default.",
        ],
        "confirm_protocol": [],
    },
    "robot_scaling": {
        "title": "Robot Scaling / Long-Horizon Confirmation",
        "runner": "run_robot_scaling_experiment.py",
        "depends_on": ["assignment_tuning"],
        "optional": False,
        "order_note": "Finish with the tuned planner on matched proposed-vs-prediction pairs to confirm that gains scale with fleet size and horizon.",
        "question": "With the tuned planner fixed, do proposed-vs-prediction gains persist or grow as robot count and horizon increase?",
        "metrics": [
            (
                "delta_exp_improve_pct_mean with CI95",
                "Exposure improvement should grow or at least remain clearly positive as robot count rises.",
            ),
            (
                "delta_resp_improve_pct_mean with CI95",
                "Response improvement should not collapse as more robots are added.",
            ),
            (
                "delta_comm_increase_pct_mean with CI95",
                "Communication growth should remain controlled rather than exploding with fleet size.",
            ),
            (
                "delta_model_done_gain_mean with CI95",
                "Completed model-scored deterring gain should rise once planner bottlenecks are removed.",
            ),
        ],
        "failure": [
            "Exposure improvement fails to grow or loses its positive trend as robot count rises.",
            "Response degrades enough to indicate a scaling collapse.",
            "Communication overhead becomes uncontrolled relative to the exposure benefit.",
            "Model-scored deterring gain stays flat or negative after planner bottlenecks were expected to be removed.",
        ],
        "confirm_protocol": [
            "Pair proposed and prediction-only runs on the same scenario, robot count, and seed before computing deltas.",
            "Report CI95 on every scaling delta so trend claims are supported by uncertainty bounds rather than single averages.",
            "Treat flat or negative paired scaling trends as failed long-horizon confirmation, even if one operating point looks favorable.",
        ],
    },
}


def get_stage_info(stage_key: str) -> dict:
    if stage_key not in _STAGES:
        raise KeyError(f"Unknown stage key: {stage_key}")
    info = dict(_STAGES[stage_key])
    info["key"] = stage_key
    info["order"] = EXPERIMENT_STAGE_ORDER.index(stage_key) + 1
    info["total"] = len(EXPERIMENT_STAGE_ORDER)
    return info


def stage_manifest(stage_key: str) -> dict:
    info = get_stage_info(stage_key)
    return {
        "stage_key": info["key"],
        "stage_title": info["title"],
        "stage_order": info["order"],
        "stage_total": info["total"],
        "runner": info["runner"],
        "depends_on": list(info["depends_on"]),
        "optional": bool(info["optional"]),
        "order_note": info["order_note"],
        "question": info["question"],
    }


def render_execution_order_lines(header: str = "## Experiment Execution Order") -> List[str]:
    lines = [header, ""]
    for idx, stage_key in enumerate(EXPERIMENT_STAGE_ORDER, start=1):
        info = get_stage_info(stage_key)
        lines.append(
            f"{idx}. **{info['title']}** (`{info['runner']}`): {info['order_note']}"
        )
    return lines


def render_execution_order_markdown(header: str = "## Experiment Execution Order") -> str:
    return "\n".join(render_execution_order_lines(header=header))


def render_stage_readme_lines(stage_key: str, *, substage: str = "") -> List[str]:
    info = get_stage_info(stage_key)
    dep_titles = [get_stage_info(dep)["title"] for dep in info["depends_on"]]
    dependency_text = ", ".join(dep_titles) if dep_titles else "None"
    lines = [
        "## Thesis Workflow Stage",
        f"- Stage {info['order']} of {info['total']}: {info['title']}",
        f"- Runner: `{info['runner']}`",
        f"- Depends on: {dependency_text}",
    ]
    if substage:
        lines.append(f"- Sweep substage: `{substage}`")
    if info["optional"]:
        lines.append("- Relevance: optional; run this only if solver choice is still a thesis question after tuning.")
    else:
        lines.append("- Relevance: required for the staged thesis evaluation flow.")
    lines.extend(
        [
            "",
            "## Stage Question",
            f"- {info['question']}",
            "",
            "## Metrics That Matter",
        ]
    )
    for metric_name, desc in info["metrics"]:
        lines.append(f"- `{metric_name}`: {desc}")
    lines.extend(["", "## What Counts As Failure"])
    for failure in info["failure"]:
        lines.append(f"- {failure}")
    if info["confirm_protocol"]:
        lines.extend(["", "## Confirm Protocol"])
        for note in info["confirm_protocol"]:
            lines.append(f"- {note}")
    return lines
