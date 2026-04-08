import math
import unittest

import pandas as pd

import experiments.run_current_vs_main_benchmark as bench


class BenchmarkCollectorTests(unittest.TestCase):
    def test_collector_tracks_distance_latency_and_backlog(self):
        collector = bench.BenchmarkCollector(sample_every_s=10.0)
        collector.consume(
            {
                "t": 0.0,
                "poses": {"r1": (0.0, 0.0), "r2": (0.0, 0.0)},
                "tasks_active": [{"id": 1, "type": "deterring", "time": 0.0, "x": 0.0, "y": 0.0}],
                "tasks_done": [],
            }
        )
        collector.consume(
            {
                "t": 10.0,
                "poses": {"r1": (10.0, 0.0), "r2": (0.0, 0.0)},
                "tasks_active": [],
                "tasks_done": [{"id": 1, "type": "deterring", "time": 0.0, "x": 0.0, "y": 0.0}],
            }
        )
        summary = collector.finalize()
        self.assertEqual(summary["completed_tasks_total"], 1)
        self.assertEqual(summary["completed_deterring_total"], 1)
        self.assertAlmostEqual(summary["mean_completion_latency_s"], 10.0)
        self.assertAlmostEqual(summary["total_robot_distance_m"], 10.0)
        self.assertAlmostEqual(summary["mean_active_tasks"], 0.5)
        self.assertEqual(summary["final_active_tasks"], 0)
        self.assertTrue(math.isfinite(summary["tasks_per_km_travel"]))


class SummarizeBenchmarkTests(unittest.TestCase):
    def test_summary_marks_current_as_winner_for_higher_and_lower_metrics(self):
        per_run_df = pd.DataFrame(
            [
                {
                    "system": "current",
                    "seed": 1000,
                    "completed_tasks_total": 12.0,
                    "completed_deterring_total": 5.0,
                    "completed_patrolling_total": 7.0,
                    "completed_tasks_per_hour": 12.0,
                    "mean_completion_latency_s": 20.0,
                    "tasks_per_km_travel": 4.0,
                    "mean_active_tasks": 1.5,
                    "final_active_tasks": 1.0,
                },
                {
                    "system": "current",
                    "seed": 1001,
                    "completed_tasks_total": 10.0,
                    "completed_deterring_total": 4.0,
                    "completed_patrolling_total": 6.0,
                    "completed_tasks_per_hour": 10.0,
                    "mean_completion_latency_s": 18.0,
                    "tasks_per_km_travel": 3.8,
                    "mean_active_tasks": 1.2,
                    "final_active_tasks": 1.0,
                },
                {
                    "system": "main",
                    "seed": 1000,
                    "completed_tasks_total": 8.0,
                    "completed_deterring_total": 3.0,
                    "completed_patrolling_total": 5.0,
                    "completed_tasks_per_hour": 8.0,
                    "mean_completion_latency_s": 30.0,
                    "tasks_per_km_travel": 2.5,
                    "mean_active_tasks": 2.5,
                    "final_active_tasks": 3.0,
                },
                {
                    "system": "main",
                    "seed": 1001,
                    "completed_tasks_total": 9.0,
                    "completed_deterring_total": 4.0,
                    "completed_patrolling_total": 5.0,
                    "completed_tasks_per_hour": 9.0,
                    "mean_completion_latency_s": 28.0,
                    "tasks_per_km_travel": 2.7,
                    "mean_active_tasks": 2.2,
                    "final_active_tasks": 2.0,
                },
            ]
        )
        summary = bench.summarize_benchmark(per_run_df)
        completed_row = summary.loc[summary["metric"] == "completed_tasks_total"].iloc[0]
        latency_row = summary.loc[summary["metric"] == "mean_completion_latency_s"].iloc[0]
        self.assertEqual(completed_row["winner"], "current")
        self.assertEqual(latency_row["winner"], "current")
        self.assertGreater(completed_row["current_advantage_pct_mean"], 0.0)
        self.assertGreater(latency_row["current_advantage_pct_mean"], 0.0)


class FilterKwargsTests(unittest.TestCase):
    def test_filter_supported_kwargs_drops_unknown_keys(self):
        def sample_fn(alpha, beta=0):
            return alpha + beta

        filtered = bench._filter_supported_kwargs(sample_fn, {"alpha": 1, "beta": 2, "gamma": 3})
        self.assertEqual(filtered, {"alpha": 1, "beta": 2})


if __name__ == "__main__":
    unittest.main()
