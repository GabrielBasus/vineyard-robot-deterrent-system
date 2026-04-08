from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable


_BIG_COUNT = 1_000_000
_BIG_FLOAT = 1.0e12


@dataclass(frozen=True)
class SimplificationStage:
    key: str
    title: str
    module_name: str
    description: str
    added_back: tuple[str, ...] = field(default_factory=tuple)
    overrides: Dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "module_name": self.module_name,
            "description": self.description,
            "added_back": list(self.added_back),
            "overrides": dict(self.overrides),
        }


SIMPLIFICATION_STAGE_ORDER = (
    "s0_simple_tasks_core",
    "s1_main_core",
    "s1_risk_open_core",
    "s1_capacity_aware_selection_core",
    "s2_direct_conflict",
    "s3_persistence",
    "s4_capacity_budget",
    "s5_current_thesis_profile",
)


_S0_SIMPLE_TASKS_CORE = {
    "simple_task_management": True,
    "task_replan_period_s": 45.0,
    "task_max_age_s": 300.0,
    "max_active_tasks_per_robot": 1,
    "max_active_patrolling_per_robot": 1,
    "max_active_model_deterring_per_robot": 1,
    "assigner_w_load": 0.0,
    "report_metrics_end": False,
}

_S1_MAIN_CORE = {
    "planner_profile": "",
    "preventive_policy": "heuristic",
    "use_split_task_extraction_selection_pipeline": True,
    "preassignment_selection_policy": "pass_through",
    "preassignment_selection_limit": 0,
    "model_deterring_window_s": 120.0,
    "enable_predicted_deltaJ_gate": False,
    "min_predicted_deltaJ_for_model_deterring": 0.0,
    "model_deterring_gate_policy": "heuristic",
    "model_deterring_chance_threshold": 0.0,
    "model_deterring_min_deltaJ_per_cost": 0.0,
    "model_deterring_min_selection_weight": 0.0,
    "model_deterring_capacity_rho_max": 1.0,
    "model_deterring_capacity_history_window_s": 3600.0,
    "model_deterring_capacity_min_completed_tasks": _BIG_COUNT,
    "model_deterring_capacity_fallback_budget_per_hr": float(_BIG_COUNT),
    "model_deterring_budget_per_robot_per_hr": _BIG_COUNT,
    "model_deterring_budget_mode": "count_per_hour",
    "model_deterring_budget_utility_per_robot_per_hr": _BIG_FLOAT,
    "model_deterring_global_admission_cap_per_cycle": _BIG_COUNT,
    "model_deterring_require_idle_robot_for_admission": False,
    "model_deterring_prefer_idle_robots_for_assignment": False,
    "model_deterring_busy_fallback_p_event_min": 0.0,
    "model_deterring_busy_fallback_deltaJ_per_cost_min": 0.0,
    "model_deterring_busy_fallback_eta_s_max": _BIG_FLOAT,
    "protect_direct_detection_from_model_deterring": False,
    "protect_active_model_deterring_persistence": False,
    "model_deterring_min_persistence_lifetime_s": 0.0,
    "model_deterring_persistence_eta_multiplier": 0.0,
    "model_deterring_persistence_buffer_s": 0.0,
    "model_deterring_max_persistence_lifetime_s": 0.0,
    "model_deterring_lock_near_goal_radius_m": 0.0,
    "protect_active_model_deterring_goal_preemption": False,
    "protect_locked_model_deterring_from_patrol_assignment": False,
    "max_active_tasks_per_robot": 1,
    "max_active_patrolling_per_robot": 1,
    "max_active_model_deterring_per_robot": 1,
    "assigner_w_load": 0.0,
    "report_metrics_end": False,
}

_S2_DIRECT_CONFLICT = dict(
    _S1_MAIN_CORE,
    protect_direct_detection_from_model_deterring=True,
    model_deterring_direct_conflict_radius_m=35.0,
    model_deterring_direct_conflict_window_s=120.0,
)

_S1_RISK_OPEN_CORE = dict(
    _S1_MAIN_CORE,
    model_deterring_risk_threshold=0.0,
    model_deterring_risk_scale=1.0e-4,
)

_S3_PERSISTENCE = dict(
    _S2_DIRECT_CONFLICT,
    protect_active_model_deterring_persistence=True,
    model_deterring_min_persistence_lifetime_s=180.0,
    model_deterring_persistence_eta_multiplier=2.0,
    model_deterring_persistence_buffer_s=60.0,
    model_deterring_max_persistence_lifetime_s=420.0,
    model_deterring_lock_near_goal_radius_m=10.0,
    protect_active_model_deterring_goal_preemption=True,
    protect_locked_model_deterring_from_patrol_assignment=True,
)

_S1_CAPACITY_AWARE_SELECTION_CORE = dict(
    _S1_RISK_OPEN_CORE,
    preassignment_selection_policy="capacity_aware_greedy",
)

_S4_CAPACITY_BUDGET = dict(
    _S3_PERSISTENCE,
    model_deterring_budget_per_robot_per_hr=4,
    model_deterring_budget_mode="count_per_hour",
    model_deterring_budget_utility_per_robot_per_hr=5.0,
    model_deterring_capacity_rho_max=0.85,
    model_deterring_capacity_min_completed_tasks=3,
    model_deterring_capacity_fallback_budget_per_hr=4.0,
    model_deterring_global_admission_cap_per_cycle=1,
    model_deterring_prefer_idle_robots_for_assignment=True,
    model_deterring_busy_fallback_p_event_min=0.95,
    model_deterring_busy_fallback_deltaJ_per_cost_min=2_000_000.0,
    model_deterring_busy_fallback_eta_s_max=1.25,
)


_STAGES: Dict[str, SimplificationStage] = {
    "s0_simple_tasks_core": SimplificationStage(
        key="s0_simple_tasks_core",
        title="Simple Tasks Core",
        module_name="DeterrentSystem_simple_tasks",
        description=(
            "Smallest end-to-end thesis-consistent branch already present in the repo: "
            "zone partitioning, SESTPP feedback, hotspot tasks, preventive tasks, and "
            "simple one-task-per-robot management."
        ),
        added_back=(),
        overrides=_S0_SIMPLE_TASKS_CORE,
    ),
    "s1_main_core": SimplificationStage(
        key="s1_main_core",
        title="Main Runtime Core",
        module_name="DeterrentSystem",
        description=(
            "Main runtime with the same stripped-down planner idea as stage 0: heuristic "
            "preventive admission, no protective dispatch heuristics, no capacity throttles, "
            "and minimal queueing."
        ),
        added_back=("Switch back to the main production runtime.",),
        overrides=_S1_MAIN_CORE,
    ),
    "s1_risk_open_core": SimplificationStage(
        key="s1_risk_open_core",
        title="Main Core With Risk Gate Open",
        module_name="DeterrentSystem",
        description=(
            "Same stripped-down main runtime as stage 1, but with the heuristic preventive "
            "risk threshold fixed at 0.0 so the model-scored preventive branch is active "
            "and can be debugged before later protection layers are added back."
        ),
        added_back=(
            "Keep the main runtime core.",
            "Force the heuristic preventive risk gate open (threshold 0.0, scale 1e-4).",
        ),
        overrides=_S1_RISK_OPEN_CORE,
    ),
    "s1_capacity_aware_selection_core": SimplificationStage(
        key="s1_capacity_aware_selection_core",
        title="Add Capacity-Aware Selection",
        module_name="DeterrentSystem",
        description=(
            "Keeps the risk-open main core but replaces pass-through pre-assignment "
            "admission with a capacity-aware greedy selector that reserves direct "
            "detections and then admits the best marginal-gain-per-cost tasks."
        ),
        added_back=(
            "Capacity-aware pre-assignment selection.",
            "Spatial redundancy penalty before assignment.",
        ),
        overrides=_S1_CAPACITY_AWARE_SELECTION_CORE,
    ),
    "s2_direct_conflict": SimplificationStage(
        key="s2_direct_conflict",
        title="Add Direct Conflict Guard",
        module_name="DeterrentSystem",
        description=(
            "Adds only the rule that model-scored preventive tasks must not conflict with "
            "active or recent direct-detection work."
        ),
        added_back=("Direct-detection conflict protection.",),
        overrides=_S2_DIRECT_CONFLICT,
    ),
    "s3_persistence": SimplificationStage(
        key="s3_persistence",
        title="Add Persistence Locks",
        module_name="DeterrentSystem",
        description=(
            "Adds preventive persistence so admitted model-scored tasks are not dropped "
            "immediately on the next replan."
        ),
        added_back=(
            "Protect active preventive tasks across replans.",
            "Allow preventive goal locks to survive patrol reassignment pressure.",
        ),
        overrides=_S3_PERSISTENCE,
    ),
    "s4_capacity_budget": SimplificationStage(
        key="s4_capacity_budget",
        title="Add Capacity And Budget",
        module_name="DeterrentSystem",
        description=(
            "Adds the throttling layer: per-robot preventive budgets, service-rate capacity "
            "gating, cycle admission caps, and strict busy-robot fallback."
        ),
        added_back=(
            "Preventive budgets.",
            "Capacity gating.",
            "Busy-robot fallback thresholds.",
        ),
        overrides=_S4_CAPACITY_BUDGET,
    ),
    "s5_current_thesis_profile": SimplificationStage(
        key="s5_current_thesis_profile",
        title="Current Thesis Profile",
        module_name="DeterrentSystem",
        description=(
            "Current thesis-facing proposed runtime: frozen calibration plus the named "
            "planner profile used for thesis confirmation work."
        ),
        added_back=(
            "Frozen calibration reuse.",
            "Current thesis planner profile.",
        ),
        overrides={
            "planner_profile": "thesis_calibrated_selective_proposed",
            "report_metrics_end": False,
        },
    ),
}


def get_stage(stage_key: str) -> SimplificationStage:
    if stage_key not in _STAGES:
        choices = ", ".join(SIMPLIFICATION_STAGE_ORDER)
        raise KeyError(f"Unknown simplification stage {stage_key!r}. Expected one of: {choices}")
    return _STAGES[stage_key]


def iter_stages(stage_keys: Iterable[str] | None = None) -> tuple[SimplificationStage, ...]:
    if stage_keys is None:
        stage_keys = SIMPLIFICATION_STAGE_ORDER
    return tuple(get_stage(key) for key in stage_keys)
