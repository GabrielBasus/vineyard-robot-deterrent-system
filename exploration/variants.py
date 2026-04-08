from __future__ import annotations


EXPLORATION_VARIANTS = {
    "row_local_priority_queue": {
        "title": "Row-Block Local Priority Queue",
        "description": (
            "Whole-row partitioning with live-pose row ownership and per-robot local "
            "priority queues instead of global assignment."
        ),
        "overrides": {
            "simple_task_management": False,
            "use_row_block_partitioning": True,
            "use_local_priority_queue": True,
            "update_zone_anchors_from_pose": True,
            "zone_repartition_period_s": 60.0,
            "zone_repartition_on_health": True,
            "local_queue_distance_weight": 0.05,
            "local_queue_deterring_bonus": 8.0,
            "local_queue_direct_detection_bonus": 10.0,
            "local_queue_patrolling_bonus": 1.0,
            "local_queue_age_weight": 0.01,
            "local_queue_preempt_margin": 0.25,
            "max_active_tasks_per_robot": 3,
            "max_active_patrolling_per_robot": 2,
            "max_active_model_deterring_per_robot": 1,
            "task_replan_period_s": 30.0,
            "task_max_age_s": 240.0,
            "uav_fraction": 0.0,
        },
    },
    "row_local_priority_queue_frequent_repartition": {
        "title": "Frequent Repartition + Near-Task Bias",
        "description": (
            "Same local row queues, but zones are recomputed aggressively from live pose "
            "and queue scoring penalizes distance more strongly."
        ),
        "overrides": {
            "simple_task_management": False,
            "use_row_block_partitioning": True,
            "use_local_priority_queue": True,
            "update_zone_anchors_from_pose": True,
            "zone_repartition_period_s": 15.0,
            "zone_repartition_on_health": True,
            "local_queue_distance_weight": 0.10,
            "local_queue_deterring_bonus": 8.0,
            "local_queue_direct_detection_bonus": 10.0,
            "local_queue_patrolling_bonus": 1.0,
            "local_queue_age_weight": 0.015,
            "local_queue_preempt_margin": 0.10,
            "max_active_tasks_per_robot": 2,
            "max_active_patrolling_per_robot": 1,
            "max_active_model_deterring_per_robot": 1,
            "task_replan_period_s": 15.0,
            "task_max_age_s": 180.0,
            "uav_fraction": 0.0,
        },
    },
}


def variant_names() -> tuple[str, ...]:
    return tuple(EXPLORATION_VARIANTS.keys())

