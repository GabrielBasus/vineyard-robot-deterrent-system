import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import run_24h_experiment_parallel as runner


class _InlineFuture:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


class _InlineExecutor:
    def __init__(self, max_workers=None):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args, **kwargs):
        return _InlineFuture(fn(*args, **kwargs))


def _fake_baseline_suite_result(call_kwargs: dict) -> dict:
    proposed_policy = str(call_kwargs.get("proposed_preventive_policy") or "")
    use_frozen_calibration = bool(call_kwargs.get("use_frozen_calibration", False))
    calibration_config_id = str(call_kwargs.get("calibration_config_id") or "")

    comparison = pd.DataFrame(
        [
            {
                "baseline": "reactive",
                "num_runs": 1,
                "value_weighted_exposure_mean": 10.0,
                "mean_response_time_s_mean": 20.0,
                "tasks_per_unit_distance_mean": 1.0,
                "boundary_message_count_mean": 1.0,
                "preventive_policy": "",
                "selected_calibration_config_id": "",
            },
            {
                "baseline": "prediction_only",
                "num_runs": 1,
                "value_weighted_exposure_mean": 9.0,
                "mean_response_time_s_mean": 19.0,
                "tasks_per_unit_distance_mean": 1.1,
                "boundary_message_count_mean": 1.0,
                "preventive_policy": "",
                "selected_calibration_config_id": "",
            },
            {
                "baseline": "proposed",
                "num_runs": 1,
                "value_weighted_exposure_mean": 8.0,
                "mean_response_time_s_mean": 18.0,
                "tasks_per_unit_distance_mean": 1.2,
                "boundary_message_count_mean": 2.0,
                "preventive_policy": proposed_policy,
                "selected_calibration_config_id": calibration_config_id if use_frozen_calibration else "",
            },
        ]
    )

    def _run_metrics_row(baseline: str) -> dict:
        is_proposed = baseline == "proposed"
        return {
            "value_weighted_exposure": 1.0,
            "mean_response_time_s": 2.0,
            "response_samples": 1,
            "completed_tasks_total": 1,
            "travel_distance_by_type": {"UGV": 1.0, "UAV": 0.0},
            "energy_by_type": {"UGV": 1.0, "UAV": 0.0},
            "completed_tasks_by_type": {"deterring": 0, "patrolling": 1},
            "tasks_per_unit_distance": 1.0,
            "boundary_message_count": 1,
            "preventive_policy": proposed_policy if is_proposed else "",
            "preventive_policy_source": "argument" if is_proposed and proposed_policy else "legacy",
            "use_frozen_calibration": int(is_proposed and use_frozen_calibration),
            "selected_calibration_config_id": calibration_config_id if is_proposed and use_frozen_calibration else "",
            "selected_calibration_source": "argument" if is_proposed and use_frozen_calibration else "disabled",
        }

    baselines = {
        "reactive": {"runs": [_run_metrics_row("reactive")]},
        "prediction_only": {"runs": [_run_metrics_row("prediction_only")]},
        "proposed": {"runs": [_run_metrics_row("proposed")]},
    }
    return {
        "comparison": comparison,
        "comparison_over_time": pd.DataFrame(),
        "baselines": baselines,
    }


class Run24hExperimentParallelTests(unittest.TestCase):
    def _write_calibration_artifacts(self, root: Path) -> tuple[Path, Path]:
        ranking_path = root / "ranking.csv"
        ranking_path.write_text(
            "\n".join(
                [
                    "config_id,rank,model_alpha_inhib,model_omega_inhib,model_mu_base,model_bg_ema",
                    "C37,1,0.61,910.0,2.5e-06,0.002",
                    "C12,2,0.44,780.0,3.0e-06,0.005",
                ]
            ),
            encoding="utf-8",
        )
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "outputs": {
                        "ranking_csv": "ranking.csv",
                    }
                }
            ),
            encoding="utf-8",
        )
        return ranking_path, manifest_path

    def test_main_forwards_planner_and_calibration_controls_into_baseline_suite(self):
        captured = []

        def fake_run_baseline_suite(**kwargs):
            captured.append(dict(kwargs))
            return _fake_baseline_suite_result(kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _ranking_path, manifest_path = self._write_calibration_artifacts(root)
            config_path = root / "runner.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "runner:",
                        "  profile: fast",
                        "  num_runs: 1",
                        "  limit_settings: 1",
                        "  scenario_scope: s2",
                        "simulation:",
                        "  time_horizons_h: [24]",
                        "sweep:",
                        "  tune_preset: diagnostic_like",
                        "planner:",
                        "  profile: thesis_selective",
                        "  proposed_preventive_policy: heuristic",
                        "calibration:",
                        "  use_frozen_calibration: false",
                        f"  manifest_path: \"{manifest_path.as_posix()}\"",
                        "  config_id: C12",
                    ]
                ),
                encoding="utf-8",
            )

            prev_cwd = os.getcwd()
            os.chdir(root)
            try:
                with patch("run_24h_experiment_parallel.ProcessPoolExecutor", _InlineExecutor), patch(
                    "run_24h_experiment_parallel.as_completed",
                    side_effect=lambda futures: list(futures),
                ), patch(
                    "run_24h_experiment_parallel.ds.run_baseline_suite",
                    side_effect=fake_run_baseline_suite,
                ), patch.object(
                    pd.DataFrame,
                    "to_markdown",
                    lambda self, *args, **kwargs: "|mock|",
                ):
                    runner.main(
                        [
                            "--config",
                            str(config_path),
                            "--planner-profile",
                            "thesis_calibrated_selective_proposed",
                            "--proposed-preventive-policy",
                            "sprt_capacity",
                            "--calibration-config-id",
                            "C37",
                        ]
                    )
            finally:
                os.chdir(prev_cwd)

        self.assertEqual(len(captured), 1)
        forwarded = captured[0]
        self.assertEqual(forwarded["planner_profile"], "thesis_calibrated_selective_proposed")
        self.assertEqual(forwarded["proposed_preventive_policy"], "sprt_capacity")
        self.assertTrue(forwarded["use_frozen_calibration"])
        self.assertIsNone(forwarded["calibration_ranking_path"])
        self.assertEqual(Path(forwarded["calibration_manifest_path"]), manifest_path)
        self.assertEqual(forwarded["calibration_config_id"], "C37")


if __name__ == "__main__":
    unittest.main()
