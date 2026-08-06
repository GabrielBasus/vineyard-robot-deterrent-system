import unittest
from types import SimpleNamespace

from planner_task_extraction import _dedupe_predictive_candidate_tasks, build_task_dispatch_candidate_buffer


class PredictiveOpportunityDedupingTests(unittest.TestCase):
    def test_dedupes_predictive_candidates_by_opportunity_key(self):
        first = {
            "type": "deterring",
            "origin": "model_hotspot",
            "mode": "laser",
            "robot_id": "r2",
            "predictive_opportunity_key": "predictive:deterring:model_hotspot:cluster:A:t100",
            "utility": 8.0,
            "predicted_deltaJ": 12.0,
            "p_event": 0.7,
            "selection_weight": 0.8,
            "eta_s": 5.0,
            "forecast_event_time": 100.0,
            "predictive_action_variants": [
                {"mode": "laser", "utility": 8.0, "predicted_deltaJ": 12.0, "p_event": 0.7, "cost_eta": 5.0},
            ],
        }
        second = {
            "type": "deterring",
            "origin": "model_hotspot",
            "mode": "formation",
            "robot_id": "r1",
            "predictive_opportunity_key": "predictive:deterring:model_hotspot:cluster:A:t100",
            "utility": 10.0,
            "predicted_deltaJ": 14.0,
            "p_event": 0.9,
            "selection_weight": 0.9,
            "eta_s": 4.0,
            "forecast_event_time": 100.0,
            "predictive_action_variants": [
                {"mode": "formation", "utility": 10.0, "predicted_deltaJ": 14.0, "p_event": 0.9, "cost_eta": 4.0},
                {"mode": "laser", "utility": 7.0, "predicted_deltaJ": 11.0, "p_event": 0.8, "cost_eta": 5.0},
            ],
        }
        reactive = {
            "type": "deterring",
            "origin": "detection",
            "robot_id": "r3",
            "utility": 1.0,
        }

        deduped = _dedupe_predictive_candidate_tasks([first, second, reactive])

        self.assertEqual(len(deduped), 2)
        predictive = next(row for row in deduped if row.get("origin") == "model_hotspot")
        self.assertEqual(predictive["mode"], "formation")
        self.assertEqual(predictive["predictive_opportunity_member_count"], 2)
        self.assertEqual(predictive["predictive_opportunity_member_robot_ids"], ["r1", "r2"])
        self.assertEqual(predictive["predictive_mode_variant_count"], 2)
        self.assertEqual(
            sorted(variant["mode"] for variant in predictive["predictive_action_variants"]),
            ["formation", "laser"],
        )

    def test_non_predictive_rows_without_opportunity_key_are_preserved(self):
        first = {"type": "patrolling", "origin": "fallback", "robot_id": "r1"}
        second = {"type": "patrolling", "origin": "fallback", "robot_id": "r2"}

        deduped = _dedupe_predictive_candidate_tasks([first, second])

        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["robot_id"], "r1")
        self.assertEqual(deduped[1]["robot_id"], "r2")

class CentralizedPredictiveOwnerOverrideTests(unittest.TestCase):
    def test_build_buffer_can_rewrite_predictive_owner_to_global(self):
        predictive_row = {
            "robot_id": "r1",
            "type": "deterring",
            "origin": "model_hotspot",
            "mode": "laser",
            "x": 1.0,
            "y": 2.0,
            "time": 10.0,
            "predictive_opportunity_key": "predictive:deterring:model_hotspot:cluster:A:t10",
        }
        direct_row = {
            "robot_id": "r2",
            "type": "deterring",
            "origin": "detection",
            "x": 3.0,
            "y": 4.0,
            "time": 10.0,
        }
        fake_taskgen = SimpleNamespace(rows=lambda: [predictive_row, direct_row])
        buffer = build_task_dispatch_candidate_buffer(
            now_t=10.0,
            active_tasks=[],
            completed_tasks=[],
            consumed_task_keys=set(),
            taskgen=fake_taskgen,
            robot_ids=["r1", "r2"],
            task_buffer_key_fn=lambda row: (row.get("type"), row.get("origin"), row.get("x"), row.get("y"), row.get("time")),
            is_direct_detection_task_fn=lambda row: str(row.get("origin")) == "detection",
            cluster_direct_detection_candidate_tasks_fn=lambda rows: list(rows),
            predictive_owner_override_id="global",
        )
        predictive = next(row for row in buffer["candidate_tasks"] if row.get("origin") == "model_hotspot")
        direct = next(row for row in buffer["candidate_tasks"] if row.get("origin") == "detection")
        self.assertEqual(predictive["robot_id"], "global")
        self.assertEqual(predictive["predictive_source_robot_id"], "r1")
        self.assertEqual(direct["robot_id"], "r2")


if __name__ == "__main__":
    unittest.main()
