import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import run_system_performance_check as perf


def _metrics_row(
    system: str,
    seed: int,
    *,
    completed_tasks_total: float,
    completed_deterring_total: float,
    completed_patrolling_total: float,
    completed_tasks_per_hour: float,
    mean_completion_latency_s: float,
    tasks_per_km_travel: float,
    mean_active_tasks: float,
    final_active_tasks: float,
) -> dict:
    return {
        "system": system,
        "seed": seed,
        "completed_tasks_total": completed_tasks_total,
        "completed_deterring_total": completed_deterring_total,
        "completed_patrolling_total": completed_patrolling_total,
        "completed_tasks_per_hour": completed_tasks_per_hour,
        "mean_completion_latency_s": mean_completion_latency_s,
        "tasks_per_km_travel": tasks_per_km_travel,
        "mean_active_tasks": mean_active_tasks,
        "final_active_tasks": final_active_tasks,
    }


class SummarizeSystemsTests(unittest.TestCase):
    def test_summary_picks_best_system_and_computes_advantage_vs_main(self):
        per_run_df = pd.DataFrame(
            [
                _metrics_row(
                    "proposed",
                    1000,
                    completed_tasks_total=14.0,
                    completed_deterring_total=6.0,
                    completed_patrolling_total=8.0,
                    completed_tasks_per_hour=14.0,
                    mean_completion_latency_s=18.0,
                    tasks_per_km_travel=4.2,
                    mean_active_tasks=1.2,
                    final_active_tasks=1.0,
                ),
                _metrics_row(
                    "proposed",
                    1001,
                    completed_tasks_total=13.0,
                    completed_deterring_total=5.0,
                    completed_patrolling_total=8.0,
                    completed_tasks_per_hour=13.0,
                    mean_completion_latency_s=19.0,
                    tasks_per_km_travel=4.0,
                    mean_active_tasks=1.1,
                    final_active_tasks=1.0,
                ),
                _metrics_row(
                    "prediction_only",
                    1000,
                    completed_tasks_total=11.0,
                    completed_deterring_total=4.0,
                    completed_patrolling_total=7.0,
                    completed_tasks_per_hour=11.0,
                    mean_completion_latency_s=24.0,
                    tasks_per_km_travel=3.4,
                    mean_active_tasks=1.6,
                    final_active_tasks=2.0,
                ),
                _metrics_row(
                    "prediction_only",
                    1001,
                    completed_tasks_total=10.0,
                    completed_deterring_total=4.0,
                    completed_patrolling_total=6.0,
                    completed_tasks_per_hour=10.0,
                    mean_completion_latency_s=25.0,
                    tasks_per_km_travel=3.3,
                    mean_active_tasks=1.5,
                    final_active_tasks=2.0,
                ),
                _metrics_row(
                    "main",
                    1000,
                    completed_tasks_total=9.0,
                    completed_deterring_total=3.0,
                    completed_patrolling_total=6.0,
                    completed_tasks_per_hour=9.0,
                    mean_completion_latency_s=27.0,
                    tasks_per_km_travel=3.0,
                    mean_active_tasks=2.0,
                    final_active_tasks=2.0,
                ),
                _metrics_row(
                    "main",
                    1001,
                    completed_tasks_total=8.0,
                    completed_deterring_total=3.0,
                    completed_patrolling_total=5.0,
                    completed_tasks_per_hour=8.0,
                    mean_completion_latency_s=28.0,
                    tasks_per_km_travel=2.9,
                    mean_active_tasks=2.1,
                    final_active_tasks=3.0,
                ),
                _metrics_row(
                    "reactive",
                    1000,
                    completed_tasks_total=7.0,
                    completed_deterring_total=3.0,
                    completed_patrolling_total=4.0,
                    completed_tasks_per_hour=7.0,
                    mean_completion_latency_s=33.0,
                    tasks_per_km_travel=2.5,
                    mean_active_tasks=2.4,
                    final_active_tasks=3.0,
                ),
                _metrics_row(
                    "reactive",
                    1001,
                    completed_tasks_total=6.0,
                    completed_deterring_total=2.0,
                    completed_patrolling_total=4.0,
                    completed_tasks_per_hour=6.0,
                    mean_completion_latency_s=34.0,
                    tasks_per_km_travel=2.4,
                    mean_active_tasks=2.5,
                    final_active_tasks=3.0,
                ),
            ]
        )

        summary = perf.summarize_systems(per_run_df)
        completed_row = summary.loc[summary["metric"] == "completed_tasks_total"].iloc[0]
        latency_row = summary.loc[summary["metric"] == "mean_completion_latency_s"].iloc[0]

        self.assertEqual(completed_row["winner"], "proposed")
        self.assertEqual(latency_row["winner"], "proposed")
        self.assertGreater(completed_row["proposed_advantage_vs_main_pct_mean"], 0.0)
        self.assertGreater(latency_row["proposed_advantage_vs_main_pct_mean"], 0.0)
        self.assertLess(completed_row["reactive_advantage_vs_main_pct_mean"], 0.0)


class BuildSystemSpecsTests(unittest.TestCase):
    def test_build_system_specs_keeps_proposed_only_overrides_on_proposed_system(self):
        specs = perf.build_system_specs(
            planner_profile="thesis_confirm",
            proposed_preventive_policy="sprt_capacity",
            use_frozen_calibration=True,
            calibration_manifest_path="results/sestpp_calibration_sweep/sestpp_calibration_sweep_manifest.json",
            calibration_config_id="C37",
        )
        by_label = {spec.label: spec for spec in specs}

        self.assertEqual(by_label["proposed"].repo_key, "current")
        self.assertEqual(by_label["proposed"].params["simulation_mode"], "proposed")
        self.assertEqual(by_label["proposed"].params["planner_profile"], "thesis_confirm")
        self.assertEqual(by_label["proposed"].params["preventive_policy"], "sprt_capacity")
        self.assertTrue(by_label["proposed"].params["use_frozen_calibration"])
        self.assertEqual(by_label["proposed"].params["calibration_config_id"], "C37")

        self.assertEqual(by_label["prediction_only"].params["simulation_mode"], "prediction_only")
        self.assertEqual(by_label["prediction_only"].params["planner_profile"], "thesis_confirm")
        self.assertNotIn("preventive_policy", by_label["prediction_only"].params)
        self.assertEqual(by_label["main"].repo_key, "main")


class MainIntegrationTests(unittest.TestCase):
    def test_main_writes_expected_artifacts(self):
        def fake_run_worker_subprocess(*, system_label, repo, seed, params, out_json, out_csv):
            del repo, params, out_json, out_csv
            task_base = {
                "proposed": 13.0,
                "prediction_only": 11.0,
                "main": 9.0,
                "reactive": 7.0,
            }[system_label]
            latency_base = {
                "proposed": 18.0,
                "prediction_only": 24.0,
                "main": 28.0,
                "reactive": 33.0,
            }[system_label]
            offset = float(seed - 1000)
            return _metrics_row(
                system_label,
                seed,
                completed_tasks_total=task_base + offset,
                completed_deterring_total=max(1.0, task_base / 2.0),
                completed_patrolling_total=max(1.0, task_base / 2.0),
                completed_tasks_per_hour=task_base + offset,
                mean_completion_latency_s=latency_base + offset,
                tasks_per_km_travel=max(0.5, task_base / 3.0),
                mean_active_tasks=max(0.5, 5.0 - task_base / 4.0),
                final_active_tasks=max(0.0, 5.0 - task_base / 3.0),
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            current_repo = root / "current"
            main_repo = root / "main"
            outdir = root / "results"
            current_repo.mkdir()
            main_repo.mkdir()

            with patch("run_system_performance_check.bench._run_worker_subprocess", side_effect=fake_run_worker_subprocess):
                rc = perf.main(
                    [
                        "--current-repo",
                        str(current_repo),
                        "--main-repo",
                        str(main_repo),
                        "--outdir",
                        str(outdir),
                        "--num-runs",
                        "2",
                        "--seed-start",
                        "1000",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertTrue((outdir / "per_run_metrics.csv").exists())
            self.assertTrue((outdir / "summary_by_metric.csv").exists())
            self.assertTrue((outdir / "system_scoreboard.csv").exists())
            self.assertTrue((outdir / "summary_compare.png").exists())
            self.assertTrue((outdir / "report.md").exists())

            summary_df = pd.read_csv(outdir / "summary_by_metric.csv")
            self.assertIn("proposed", set(summary_df["winner"]))

            manifest = json.loads((outdir / "benchmark_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["systems"]), 4)


if __name__ == "__main__":
    unittest.main()
