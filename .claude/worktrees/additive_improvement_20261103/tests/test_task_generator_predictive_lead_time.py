import unittest

from TaskGenerator import TaskGenerator


class TaskGeneratorPredictiveLeadTimeTests(unittest.TestCase):
    def test_predictive_lead_time_fields_cover_intervention_delay(self):
        taskgen = TaskGenerator()
        taskgen.configure_predictive_lead_time(
            enable_predictive_lead_time=True,
            predictive_lead_time_min_s=30.0,
            predictive_lead_time_max_eta_s=120.0,
            predictive_lead_time_buffer_s=15.0,
            predictive_lead_time_risk_power=1.0,
        )

        task = taskgen._apply_predictive_lead_time_fields(
            {
                "type": "deterring",
                "origin": "model_hotspot",
                "mode": "laser",
                "time": 100.0,
                "eta_s": 20.0,
                "p_event": 0.75,
                "action": {
                    "kind": "deterring",
                    "name": "laser",
                    "params": {},
                    "service_time_s": 20.0,
                },
            },
            replan_interval_s=45.0,
        )

        self.assertGreater(task["event_time"], task["time"])
        self.assertAlmostEqual(task["required_arrival_by_t"], task["event_time"])
        self.assertGreaterEqual(task["lead_time_s"], task["predictive_required_lead_time_s"])
        self.assertGreaterEqual(task["predictive_deadline_slack_s"], 0.0)

    def test_direct_detection_tasks_do_not_get_predictive_lead_time_fields(self):
        taskgen = TaskGenerator()
        taskgen.configure_predictive_lead_time(enable_predictive_lead_time=True)
        task = taskgen._apply_predictive_lead_time_fields(
            {
                "type": "deterring",
                "origin": "detection",
                "time": 50.0,
                "eta_s": 5.0,
                "action": {
                    "kind": "deterring",
                    "name": "direct_detection",
                    "params": {},
                    "service_time_s": 20.0,
                },
            },
            replan_interval_s=10.0,
        )
        self.assertNotIn("event_time", task)
        self.assertNotIn("lead_time_s", task)

    def test_forecast_horizon_timing_mode_separates_event_time_from_required_lead(self):
        taskgen = TaskGenerator()
        taskgen.configure_predictive_lead_time(
            enable_predictive_lead_time=True,
            predictive_timing_mode="forecast_horizon",
            predictive_lead_time_min_s=30.0,
            predictive_lead_time_max_eta_s=120.0,
            predictive_lead_time_buffer_s=15.0,
            predictive_lead_time_risk_power=1.0,
        )

        task = taskgen._apply_predictive_lead_time_fields(
            {
                "type": "patrolling",
                "origin": "hotspot",
                "time": 100.0,
                "eta_s": 20.0,
                "p_event": 0.75,
                "selection_weight": 0.8,
                "action": {
                    "kind": "patrolling",
                    "name": "patrolling",
                    "params": {},
                    "service_time_s": 20.0,
                },
            },
            replan_interval_s=45.0,
            forecast_horizon_s=300.0,
        )

        self.assertEqual(task["predictive_timing_mode"], "forecast_horizon")
        self.assertAlmostEqual(task["release_time"], 100.0)
        self.assertAlmostEqual(task["forecast_event_time"], 400.0)
        self.assertAlmostEqual(task["required_arrival_by_t"], task["forecast_event_time"])
        self.assertAlmostEqual(task["lead_time_s"], 300.0)
        self.assertGreater(task["predictive_deadline_slack_s"], 0.0)

    def test_arrival_offset_timing_mode_stays_close_to_required_arrival_lead(self):
        taskgen = TaskGenerator()
        taskgen.configure_predictive_lead_time(
            enable_predictive_lead_time=True,
            predictive_timing_mode="arrival_offset",
            predictive_lead_time_min_s=30.0,
            predictive_lead_time_max_eta_s=120.0,
            predictive_lead_time_buffer_s=15.0,
            predictive_lead_time_risk_power=1.0,
        )

        task = taskgen._apply_predictive_lead_time_fields(
            {
                "type": "deterring",
                "origin": "model_hotspot",
                "mode": "laser",
                "time": 100.0,
                "eta_s": 20.0,
                "p_event": 0.75,
                "selection_weight": 0.8,
                "action": {
                    "kind": "deterring",
                    "name": "laser",
                    "params": {},
                    "service_time_s": 20.0,
                },
            },
            replan_interval_s=45.0,
            forecast_horizon_s=300.0,
        )

        required_lead_s = 45.0 + 20.0 + 20.0 + 15.0
        useful_margin_cap_s = min((45.0 + 120.0 + 20.0 + 15.0) - required_lead_s, 15.0 + 0.5 * 20.0)
        expected_offset_s = required_lead_s + 0.8 * useful_margin_cap_s

        self.assertEqual(task["predictive_timing_mode"], "arrival_offset")
        self.assertAlmostEqual(task["forecast_event_time"], 100.0 + expected_offset_s)
        self.assertAlmostEqual(task["predictive_event_offset_s"], expected_offset_s)
        self.assertAlmostEqual(task["predictive_offset_margin_s"], expected_offset_s - required_lead_s)
        self.assertLess(task["predictive_event_offset_s"], 300.0)
        self.assertGreaterEqual(task["predictive_deadline_slack_s"], 0.0)

    def test_predictive_opportunity_key_is_mode_agnostic(self):
        taskgen = TaskGenerator()
        base = {
            "type": "deterring",
            "origin": "model_hotspot",
            "x": 10.0,
            "y": 20.0,
            "time": 100.0,
            "cluster_key": ("r1", 2, 3),
            "forecast_event_time": 150.0,
        }
        laser = dict(base, mode="laser")
        formation = dict(base, mode="formation")
        self.assertEqual(
            taskgen._predictive_opportunity_key(laser),
            taskgen._predictive_opportunity_key(formation),
        )

    def test_add_preserves_predictive_action_variants(self):
        taskgen = TaskGenerator()
        taskgen.configure_actions(
            deterring_modes={
                "laser": {"beta": 0.4, "omega": 400.0, "sigma": 10.0},
                "formation": {"beta": 0.3, "omega": 800.0, "sigma": 18.0},
            },
            tau_service_s=20.0,
        )
        added = taskgen._add(
            {
                "robot_id": "r1",
                "type": "deterring",
                "origin": "model_hotspot",
                "mode": "laser",
                "x": 10.0,
                "y": 20.0,
                "time": 100.0,
                "predictive_action_variants": [
                    {
                        "mode": "laser",
                        "utility": 8.0,
                        "predicted_deltaJ": 12.0,
                        "action": {"kind": "deterring", "name": "laser", "params": {}, "service_time_s": 20.0},
                    },
                    {
                        "mode": "formation",
                        "utility": 7.0,
                        "predicted_deltaJ": 11.0,
                        "action": {"kind": "deterring", "name": "formation", "params": {}, "service_time_s": 20.0},
                    },
                ],
                "predictive_mode_variant_count": 2,
                "predictive_generation_best_mode": "laser",
            }
        )
        self.assertTrue(added)
        row = taskgen.rows()[-1]
        self.assertEqual(row["predictive_mode_variant_count"], 2)
        self.assertEqual(row["predictive_generation_best_mode"], "laser")
        self.assertEqual(
            sorted(variant["mode"] for variant in row["predictive_action_variants"]),
            ["formation", "laser"],
        )


if __name__ == "__main__":
    unittest.main()
