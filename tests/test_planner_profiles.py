import unittest

from planner_profiles import (
    apply_planner_profile_defaults,
    canonicalize_planner_profile_name,
    get_planner_profile_details,
    get_planner_profile_values,
)


class PlannerProfileTests(unittest.TestCase):
    def test_aliases_resolve_to_thesis_confirm(self):
        self.assertEqual(canonicalize_planner_profile_name("thesis_confirm"), "thesis_confirm")
        self.assertEqual(canonicalize_planner_profile_name("post_fix"), "thesis_confirm")
        self.assertEqual(canonicalize_planner_profile_name("post-fix"), "thesis_confirm")

    def test_thesis_confirm_values_are_conservative_post_fix_defaults(self):
        values = get_planner_profile_values("thesis_confirm")
        self.assertEqual(values["assigner_w_task_value"], 0.20)
        self.assertEqual(values["model_deterring_window_s"], 120.0)
        self.assertEqual(values["model_deterring_min_persistence_replans"], 3)
        self.assertEqual(values["model_deterring_max_eta_s"], 90.0)
        self.assertEqual(values["model_deterring_score_margin"], 0.20)
        self.assertEqual(values["model_deterring_budget_per_robot_per_hr"], 3)
        self.assertEqual(values["model_deterring_gate_policy"], "heuristic")
        self.assertEqual(values["model_deterring_chance_threshold"], 0.25)
        self.assertEqual(values["model_deterring_min_deltaJ_per_cost"], 0.25)

        details = get_planner_profile_details("thesis_confirm")
        self.assertIn("rationale", details)
        self.assertIn("model_deterring_score_margin", details["rationale"])

    def test_profile_defaults_respect_explicit_overrides(self):
        target = {
            "planner_profile": "post_fix",
            "assigner_w_task_values": "0.0",
            "gate_policies": "",
            "chance_threshold_values": "",
        }
        profile_name, values = apply_planner_profile_defaults(
            target,
            target["planner_profile"],
            dest_map={
                "assigner_w_task_value": "assigner_w_task_values",
                "model_deterring_gate_policy": "gate_policies",
                "model_deterring_chance_threshold": "chance_threshold_values",
            },
            protected_dests={"assigner_w_task_values"},
            stringify=True,
        )

        self.assertEqual(profile_name, "thesis_confirm")
        self.assertEqual(values["model_deterring_gate_policy"], "heuristic")
        self.assertEqual(target["assigner_w_task_values"], "0.0")
        self.assertEqual(target["gate_policies"], "heuristic")
        self.assertEqual(target["chance_threshold_values"], "0.25")

    def test_calibrated_selective_profile_aliases_and_values(self):
        self.assertEqual(
            canonicalize_planner_profile_name("thesis_selective"),
            "thesis_calibrated_selective_proposed",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("selective-proposed"),
            "thesis_calibrated_selective_proposed",
        )

        values = get_planner_profile_values("thesis_calibrated_selective_proposed")
        self.assertTrue(values["use_frozen_calibration"])
        self.assertEqual(values["preventive_policy"], "heuristic")
        self.assertEqual(values["model_deterring_gate_policy"], "heuristic")
        self.assertFalse(values["enable_predicted_deltaJ_gate"])
        self.assertTrue(values["protect_direct_detection_from_model_deterring"])

        details = get_planner_profile_details("thesis_calibrated_selective_proposed")
        self.assertIn("rationale", details)
        self.assertIn("use_frozen_calibration", details["rationale"])

    def test_thesis_dispatch_profile_aliases_and_values(self):
        self.assertEqual(
            canonicalize_planner_profile_name("res_0p25"),
            "thesis_dispatch_res_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("dispatch_unc"),
            "thesis_dispatch_unc",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("thesis_res_rand_0p25"),
            "thesis_dispatch_res_rand_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_soft_0p25"),
            "thesis_dispatch_res_soft_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_adaptive_0p25"),
            "thesis_dispatch_res_adaptive_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_adaptive_leadtime_0p25"),
            "thesis_dispatch_res_adaptive_leadtime_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_feasible_0p25"),
            "thesis_dispatch_res_feasible_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_idle_feasible_0p25"),
            "thesis_dispatch_res_idle_feasible_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_confidence_0p25"),
            "thesis_dispatch_res_confidence_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_idle_feasible_confidence_0p25"),
            "thesis_dispatch_res_idle_feasible_confidence_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_risk_adjusted_0p25"),
            "thesis_dispatch_res_risk_adjusted_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_time_score_0p25"),
            "thesis_dispatch_res_time_score_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_time_score_v2_0p25"),
            "thesis_dispatch_res_time_score_v2_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_deferred_time_score_0p25"),
            "thesis_dispatch_res_deferred_time_score_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("res_centralized_global_0p25"),
            "thesis_dispatch_res_centralized_global_0p25",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("reactive_first"),
            "thesis_dispatch_reactive_first",
        )
        self.assertEqual(
            canonicalize_planner_profile_name("dispatch_reactive_first"),
            "thesis_dispatch_reactive_first",
        )

        reactive_first_values = get_planner_profile_values("thesis_dispatch_reactive_first")
        self.assertEqual(reactive_first_values["dispatch_policy"], "reactive-first")
        self.assertEqual(reactive_first_values["reservation_fraction"], 0.0)
        self.assertEqual(reactive_first_values["reservation_window_s"], 600.0)
        self.assertEqual(reactive_first_values["reactive_override_slack_s"], 90.0)
        self.assertEqual(reactive_first_values["predictive_selection_policy"], "utility")

        res_values = get_planner_profile_values("thesis_dispatch_res_0p25")
        self.assertEqual(res_values["dispatch_policy"], "res")
        self.assertEqual(res_values["reservation_fraction"], 0.25)
        self.assertEqual(res_values["reservation_window_s"], 600.0)
        self.assertEqual(res_values["reactive_override_slack_s"], 90.0)
        self.assertEqual(res_values["predictive_selection_policy"], "utility")

        rand_values = get_planner_profile_values("thesis_dispatch_res_rand_0p25")
        self.assertEqual(rand_values["dispatch_policy"], "res")
        self.assertEqual(rand_values["reservation_fraction"], 0.25)
        self.assertEqual(rand_values["predictive_selection_policy"], "random")

        soft_values = get_planner_profile_values("thesis_dispatch_res_soft_0p25")
        self.assertEqual(soft_values["dispatch_policy"], "res-soft")
        self.assertEqual(soft_values["reservation_fraction"], 0.25)
        self.assertEqual(soft_values["reservation_softening_alpha"], 2.0)

        adaptive_values = get_planner_profile_values("thesis_dispatch_res_adaptive_0p25")
        self.assertEqual(adaptive_values["dispatch_policy"], "res-adaptive")
        self.assertEqual(adaptive_values["reservation_fraction"], 0.25)
        self.assertEqual(adaptive_values["reservation_softening_alpha"], 2.0)
        self.assertEqual(adaptive_values["reservation_age_softening_beta"], 2.0)
        self.assertEqual(adaptive_values["reservation_age_gate"], 0.5)

        adaptive_leadtime_values = get_planner_profile_values("thesis_dispatch_res_adaptive_leadtime_0p25")
        self.assertEqual(adaptive_leadtime_values["dispatch_policy"], "res-adaptive")
        self.assertEqual(adaptive_leadtime_values["reservation_fraction"], 0.25)
        self.assertEqual(adaptive_leadtime_values["reservation_age_softening_beta"], 5.0)
        self.assertEqual(adaptive_leadtime_values["reservation_age_gate"], 0.25)
        self.assertTrue(adaptive_leadtime_values["enable_predictive_lead_time"])
        self.assertEqual(adaptive_leadtime_values["predictive_timing_mode"], "arrival_offset")

        feasible_values = get_planner_profile_values("thesis_dispatch_res_feasible_0p25")
        self.assertEqual(feasible_values["dispatch_policy"], "res-feasible")
        self.assertEqual(feasible_values["predictive_selection_policy"], "utility")
        self.assertTrue(feasible_values["enable_predictive_lead_time"])
        self.assertEqual(feasible_values["predictive_slack_min_s"], 15.0)

        idle_feasible_values = get_planner_profile_values("thesis_dispatch_res_idle_feasible_0p25")
        self.assertEqual(idle_feasible_values["dispatch_policy"], "res-idle-feasible")
        self.assertEqual(idle_feasible_values["reactive_pressure_max_for_predictive"], 0.5)
        self.assertEqual(idle_feasible_values["predictive_slack_min_s"], 15.0)

        confidence_values = get_planner_profile_values("thesis_dispatch_res_confidence_0p25")
        self.assertEqual(confidence_values["dispatch_policy"], "res-confidence")
        self.assertEqual(confidence_values["predictive_selection_policy"], "confidence-weighted")
        self.assertEqual(confidence_values["predictive_confidence_source"], "p_event_times_selection_weight")
        self.assertEqual(confidence_values["predictive_deadline_weight"], 2.0)

        idle_conf_values = get_planner_profile_values("thesis_dispatch_res_idle_feasible_confidence_0p25")
        self.assertEqual(idle_conf_values["dispatch_policy"], "res-idle-feasible-confidence")
        self.assertEqual(idle_conf_values["predictive_selection_policy"], "confidence-weighted")
        self.assertEqual(idle_conf_values["predictive_confidence_min"], 0.25)
        self.assertEqual(idle_conf_values["reactive_pressure_max_for_predictive"], 0.5)

        risk_values = get_planner_profile_values("thesis_dispatch_res_risk_adjusted_0p25")
        self.assertEqual(risk_values["dispatch_policy"], "res-risk-adjusted")
        self.assertEqual(risk_values["reservation_fraction"], 0.25)
        self.assertEqual(risk_values["predictive_selection_policy"], "risk-adjusted")
        self.assertEqual(risk_values["predictive_confidence_min"], 0.25)
        self.assertEqual(risk_values["predictive_cost_ratio_min"], 1.0)
        self.assertEqual(risk_values["risk_adjusted_reservation_alpha"], 2.0)
        self.assertEqual(risk_values["risk_adjusted_reservation_beta"], 2.0)

        time_score_values = get_planner_profile_values("thesis_dispatch_res_time_score_0p25")
        self.assertEqual(time_score_values["dispatch_policy"], "res")
        self.assertEqual(time_score_values["predictive_selection_policy"], "time-aware")
        self.assertTrue(time_score_values["enable_predictive_lead_time"])
        self.assertEqual(time_score_values["predictive_timing_mode"], "arrival_offset")
        self.assertEqual(time_score_values["predictive_time_score_deadline_scale_s"], 120.0)
        self.assertEqual(time_score_values["predictive_time_score_reactive_pressure_weight"], 5.0)
        self.assertEqual(time_score_values["predictive_time_score_infeasible_penalty"], 25.0)

        time_score_v2_values = get_planner_profile_values("thesis_dispatch_res_time_score_v2_0p25")
        self.assertEqual(time_score_v2_values["dispatch_policy"], "res")
        self.assertEqual(time_score_v2_values["predictive_selection_policy"], "time-aware-v2")
        self.assertTrue(time_score_v2_values["enable_predictive_lead_time"])
        self.assertEqual(time_score_v2_values["predictive_timing_mode"], "arrival_offset")
        self.assertEqual(time_score_v2_values["predictive_expiry_grace_s"], 0.0)
        self.assertEqual(time_score_v2_values["predictive_time_score_deadline_scale_s"], 120.0)
        self.assertEqual(time_score_v2_values["predictive_time_score_reactive_pressure_weight"], 5.0)
        self.assertEqual(time_score_v2_values["predictive_time_score_infeasible_penalty"], 25.0)

        deferred_values = get_planner_profile_values("thesis_dispatch_res_deferred_time_score_0p25")
        self.assertEqual(deferred_values["dispatch_policy"], "res")
        self.assertEqual(deferred_values["predictive_selection_policy"], "time-aware")
        self.assertTrue(deferred_values["defer_predictive_action_selection"])
        self.assertEqual(deferred_values["assignment_switch_penalty"], 1.0)

        centralized_values = get_planner_profile_values("thesis_dispatch_res_centralized_global_0p25")
        self.assertEqual(centralized_values["dispatch_policy"], "res")
        self.assertEqual(centralized_values["predictive_planning_topology"], "centralized_global")
        self.assertEqual(centralized_values["zone_assignment_mode"], "soft")
        self.assertTrue(centralized_values["defer_predictive_action_selection"])


if __name__ == "__main__":
    unittest.main()
