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


if __name__ == "__main__":
    unittest.main()
