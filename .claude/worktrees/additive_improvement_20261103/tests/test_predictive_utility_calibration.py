import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import DeterrentSystem as ds
from experiments.run_predictive_utility_calibration_compare import build_analysis_outputs
import experiments.run_current_vs_main_benchmark as bench
import testbench.run_testbench as testbench_runner
from planner_task_extraction import (
    annotate_predictive_utility_fields,
    build_task_dispatch_candidate_buffer,
)
from planner_task_selection import select_preassignment_task_candidates


class PredictiveUtilityCalibrationConfigTests(unittest.TestCase):
    def test_config_loads_and_contains_required_systems(self):
        config_path = Path("testbench/thesis_compare_predictive_utility_calibration_24h.json")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        systems = {str(system["key"]): dict(system.get("params") or {}) for system in config["systems"]}

        self.assertIn("unc", systems)
        self.assertIn("unc_deltaJ", systems)
        self.assertIn("bern_product_p10", systems)
        self.assertEqual(systems["unc_deltaJ"]["predictive_utility_mode"], "deltaJ")
        self.assertEqual(systems["bern_product_p10"]["predictive_utility_mode"], "bernoulli_expected_deltaJ")
        self.assertIn("native_predictive_confidence_mean", config["outputs"]["metrics"])
        self.assertIn("native_predictive_success_ratio", config["outputs"]["metrics"])
        self.assertIn("native_predictive_confidence_mean", testbench_runner.METRIC_LIBRARY)
        self.assertIn("native_predictive_success_ratio", testbench_runner.METRIC_LIBRARY)


class PredictiveUtilityPropagationTests(unittest.TestCase):
    def test_predictive_utility_mode_controls_utility_value(self):
        task = {
            "type": "deterring",
            "origin": "model_hotspot",
            "mode": "laser",
            "predicted_deltaJ": 10.0,
            "p_event": 0.5,
            "selection_weight": 0.8,
            "utility": -1.0,
            "score": -1.0,
        }

        deterministic = annotate_predictive_utility_fields(task, predictive_utility_mode="deltaJ")
        bernoulli = annotate_predictive_utility_fields(
            task,
            predictive_utility_mode="bernoulli_expected_deltaJ",
            predictive_confidence_source="p_event_times_selection_weight",
            predictive_confidence_power=1.0,
        )

        self.assertAlmostEqual(deterministic["utility"], 10.0)
        self.assertAlmostEqual(bernoulli["predictive_confidence"], 0.4)
        self.assertAlmostEqual(bernoulli["bernoulli_expected_deltaJ"], 4.0)
        self.assertAlmostEqual(bernoulli["utility"], 4.0)

    def test_stl_robustness_overwrites_stale_legacy_utility(self):
        task = {
            "type": "deterring",
            "origin": "model_hotspot",
            "mode": "laser",
            "predictive_stl_U": 2.5,
            "predicted_deltaJ": 99.0,
            "utility": -10.0,
            "score": -20.0,
            "p_event": 0.5,
            "selection_weight": 0.5,
        }

        annotated = annotate_predictive_utility_fields(task, predictive_utility_mode="stl_robustness")

        self.assertAlmostEqual(annotated["predictive_stl_U"], 2.5)
        self.assertAlmostEqual(annotated["predicted_deltaJ"], 2.5)
        self.assertAlmostEqual(annotated["utility"], 2.5)
        self.assertAlmostEqual(annotated["score"], 2.5)

    def test_legacy_habituation_mode_preserves_task_generator_fields(self):
        task = {
            "type": "deterring",
            "origin": "model_hotspot",
            "mode": "laser",
            "predicted_deltaJ": 7.5,
            "utility": 3.5,
            "score": 3.5,
            "habituation_eta_at_plan": 0.5,
            "p_event": 0.5,
            "selection_weight": 0.5,
        }

        annotated = annotate_predictive_utility_fields(
            task,
            predictive_utility_mode="legacy_habituation",
        )

        self.assertEqual(annotated["predictive_utility_mode"], "legacy_habituation")
        self.assertAlmostEqual(annotated["predicted_deltaJ"], 7.5)
        self.assertAlmostEqual(annotated["utility"], 3.5)
        self.assertAlmostEqual(annotated["score"], 3.5)
        self.assertAlmostEqual(annotated["habituation_eta_at_plan"], 0.5)

    def test_confidence_survives_extraction_and_selection(self):
        predictive_row = {
            "robot_id": "r1",
            "type": "deterring",
            "origin": "model_hotspot",
            "mode": "laser",
            "x": 1.0,
            "y": 2.0,
            "time": 10.0,
            "predicted_deltaJ": 20.0,
            "p_event": 0.5,
            "selection_weight": 0.5,
            "risk_conf": 0.75,
            "predictive_opportunity_key": "predictive:deterring:model_hotspot:cluster:A:t10",
        }
        fake_taskgen = SimpleNamespace(rows=lambda: [predictive_row])
        buffer = build_task_dispatch_candidate_buffer(
            now_t=10.0,
            active_tasks=[],
            completed_tasks=[],
            consumed_task_keys=set(),
            taskgen=fake_taskgen,
            robot_ids=["r1"],
            task_buffer_key_fn=lambda row: (row.get("type"), row.get("origin"), row.get("x"), row.get("y"), row.get("time")),
            is_direct_detection_task_fn=lambda row: False,
            cluster_direct_detection_candidate_tasks_fn=lambda rows: list(rows),
            predictive_utility_mode="bernoulli_expected_deltaJ",
            predictive_confidence_source="p_event_times_selection_weight",
            predictive_confidence_power=2.0,
        )
        selected = select_preassignment_task_candidates(
            candidate_tasks=buffer["candidate_tasks"],
            selection_policy="pass_through",
            selection_limit=0,
            is_direct_detection_task_fn=lambda row: False,
        )
        task = selected["selected_candidate_tasks"][0]

        self.assertEqual(task["predictive_utility_mode"], "bernoulli_expected_deltaJ")
        self.assertAlmostEqual(task["predictive_confidence"], 0.0625)
        self.assertAlmostEqual(task["bernoulli_expected_deltaJ"], 1.25)
        self.assertIn("confidence_components", task)

    def test_missing_confidence_fields_do_not_crash(self):
        task = annotate_predictive_utility_fields(
            {
                "type": "deterring",
                "origin": "model_hotspot",
                "mode": "laser",
                "predicted_deltaJ": 7.0,
            },
            predictive_utility_mode="bernoulli_expected_deltaJ",
            predictive_confidence_source="p_event_times_selection_weight",
        )
        self.assertEqual(task["predictive_confidence"], 0.0)
        self.assertEqual(task["utility"], 0.0)


class PredictiveUtilityTelemetryTests(unittest.TestCase):
    def test_runtime_metrics_structured_includes_calibration_fields(self):
        frames = ds.run_simulation_frames_persistent(
            W=80.0,
            H=80.0,
            NX=12,
            NY=12,
            Nrobots=2,
            T_end=2.0,
            dt=1.0,
            fps=1,
            use_ground_truth=False,
            detect_rate_per_robot=0.0,
            report_metrics_end=False,
            telemetry_clear_on_start=False,
            telemetry_prompt_save=False,
            predictive_utility_mode="bernoulli_expected_deltaJ",
            predictive_confidence_source="p_event",
            predictive_confidence_power=0.5,
        )
        frame = next(frames)
        metrics = frame["metrics_structured"]

        self.assertEqual(metrics["predictive_utility_mode"], "bernoulli_expected_deltaJ")
        self.assertEqual(metrics["predictive_confidence_source"], "p-event")
        self.assertTrue(math.isfinite(metrics["predictive_confidence_power"]))
        self.assertIn("predictive_confidence_mean", metrics)
        self.assertIn("predictive_success_ratio", metrics)

    def test_benchmark_collector_exports_new_native_metrics(self):
        collector = bench.BenchmarkCollector(sample_every_s=10.0)
        collector.consume(
            {
                "t": 0.0,
                "poses": {"r1": (0.0, 0.0)},
                "tasks_active": [],
                "tasks_done": [],
                "metrics_compact": {
                    "predictive_confidence_mean": 0.42,
                    "predictive_success_ratio": 0.7,
                    "predictive_false_positive_ratio": 0.3,
                },
            }
        )
        summary = collector.finalize()
        self.assertAlmostEqual(summary["native_predictive_confidence_mean"], 0.42)
        self.assertAlmostEqual(summary["native_predictive_success_ratio"], 0.7)
        self.assertAlmostEqual(summary["native_predictive_false_positive_ratio"], 0.3)


class PredictiveUtilityRunnerTests(unittest.TestCase):
    def test_analysis_outputs_and_plots_generate_from_existing_csvs(self):
        config = {
            "outputs": {"outdir": "unused"},
            "systems": [
                {
                    "key": "unc",
                    "title": "UNC",
                    "params": {"dispatch_policy": "unc", "predictive_utility_mode": "legacy"},
                },
                {
                    "key": "bern_product_p10",
                    "title": "Bernoulli",
                    "params": {
                        "dispatch_policy": "unc",
                        "predictive_utility_mode": "bernoulli_expected_deltaJ",
                        "predictive_confidence_source": "p_event_times_selection_weight",
                        "predictive_confidence_power": 1.0,
                    },
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            pd.DataFrame(
                [
                    {
                        "system": "unc",
                        "seed": 123,
                        "native_value_weighted_exposure": 10.0,
                        "native_mean_response_time_s": 5.0,
                        "native_predictive_completion_ratio": 0.5,
                        "native_predictive_confidence_mean": 0.3,
                        "native_predictive_success_ratio": 0.4,
                        "native_predictive_false_positive_ratio": 0.6,
                        "native_robot_predictive_fraction_mean": 0.2,
                        "native_urgent_reactive_override_total": 1.0,
                    },
                    {
                        "system": "bern_product_p10",
                        "seed": 123,
                        "native_value_weighted_exposure": 8.0,
                        "native_mean_response_time_s": 4.0,
                        "native_predictive_completion_ratio": 0.7,
                        "native_predictive_confidence_mean": 0.6,
                        "native_predictive_success_ratio": 0.5,
                        "native_predictive_false_positive_ratio": 0.5,
                        "native_robot_predictive_fraction_mean": 0.3,
                        "native_urgent_reactive_override_total": 0.0,
                    },
                ]
            ).to_csv(outdir / "per_run_metrics.csv", index=False)
            pd.DataFrame(
                [
                    {"system": "unc", "seed": 123, "t": 0.0, "native_robot_predictive_fraction_mean": 0.1},
                    {"system": "bern_product_p10", "seed": 123, "t": 0.0, "native_robot_predictive_fraction_mean": 0.2},
                ]
            ).to_csv(outdir / "per_run_timeseries.csv", index=False)

            outputs = build_analysis_outputs(config, outdir)

            self.assertTrue(outputs["mode_summary_csv"].exists())
            self.assertTrue(outputs["confidence_source_summary_csv"].exists())
            self.assertTrue(outputs["ranking_csv"].exists())
            self.assertTrue(outputs["final_metrics_plot"].exists())
            self.assertTrue(outputs["confidence_success_plot"].exists())
            self.assertTrue(outputs["predictive_share_plot"].exists())


if __name__ == "__main__":
    unittest.main()
