import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from calibration_config import load_frozen_sestpp_calibration
from DeterrentSystem import (
    _resolve_calibration_runtime_overrides,
    _resolve_preventive_policy_settings,
    run_baseline_suite,
)
from planner_profiles import get_planner_profile_values


class CalibrationPipelineTests(unittest.TestCase):
    def _write_calibration_artifacts(self, root: Path) -> tuple[Path, Path]:
        ranking_path = root / "ranking.csv"
        ranking_path.write_text(
            "\n".join(
                [
                    "config_id,rank,model_alpha_inhib,model_omega_inhib,model_mu_base,model_bg_ema,proposed_field_logloss_mean,proposed_field_brier_mean,proposed_nll_mean,nll_improvement_pct_mean",
                    "cfg_top,1,0.61,910.0,2.5e-06,0.002,0.11,0.07,0.21,12.5",
                    "cfg_alt,2,0.44,780.0,3.0e-06,0.005,0.18,0.10,0.25,7.0",
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
                    },
                    "best_config_id": "cfg_top",
                    "best_config": {
                        "config_id": "cfg_top",
                        "rank": 1,
                        "model_alpha_inhib": 0.61,
                        "model_omega_inhib": 910.0,
                        "model_mu_base": 2.5e-06,
                        "model_bg_ema": 0.002,
                        "proposed_field_logloss_mean": 0.11,
                    },
                }
            ),
            encoding="utf-8",
        )
        return ranking_path, manifest_path

    def test_load_frozen_calibration_uses_top_ranked_csv_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ranking_path, _manifest_path = self._write_calibration_artifacts(Path(tmpdir))
            cfg = load_frozen_sestpp_calibration(ranking_path=ranking_path)

        self.assertEqual(cfg.config_id, "cfg_top")
        self.assertAlmostEqual(cfg.model_alpha_inhib, 0.61)
        self.assertAlmostEqual(cfg.model_omega_inhib, 910.0)
        self.assertAlmostEqual(cfg.model_mu_base, 2.5e-06)
        self.assertAlmostEqual(cfg.model_bg_ema, 0.002)
        self.assertEqual(cfg.summary_metrics["rank"], 1)

    def test_load_frozen_calibration_supports_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _ranking_path, manifest_path = self._write_calibration_artifacts(Path(tmpdir))
            cfg = load_frozen_sestpp_calibration(manifest_path=manifest_path, config_id="cfg_alt")

        self.assertEqual(cfg.config_id, "cfg_alt")
        self.assertAlmostEqual(cfg.model_alpha_inhib, 0.44)
        self.assertEqual(cfg.source_type, "ranking_csv")

    def test_runtime_calibration_override_applies_selected_parameters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ranking_path, _manifest_path = self._write_calibration_artifacts(Path(tmpdir))
            resolved = _resolve_calibration_runtime_overrides(
                simulation_mode="proposed",
                use_frozen_calibration=True,
                calibration_ranking_path=str(ranking_path),
                calibration_manifest_path=None,
                calibration_config_id=None,
                planner_profile="",
                planner_profile_values={},
                alpha_inhib=0.10,
                omega_inhib=100.0,
                mu_base=9.0e-06,
                bg_ema=0.03,
            )

        self.assertTrue(resolved["use_frozen_calibration"])
        self.assertEqual(resolved["selected_calibration_config_id"], "cfg_top")
        self.assertEqual(resolved["selected_calibration_source"], "argument")
        self.assertAlmostEqual(resolved["alpha_inhib"], 0.61)
        self.assertAlmostEqual(resolved["omega_inhib"], 910.0)
        self.assertAlmostEqual(resolved["mu_base"], 2.5e-06)
        self.assertAlmostEqual(resolved["bg_ema"], 0.002)

    def test_selective_profile_now_resolves_back_to_heuristic_for_proposed_mode(self):
        profile = "thesis_calibrated_selective_proposed"
        values = get_planner_profile_values(profile)
        resolved = _resolve_preventive_policy_settings(
            simulation_mode="proposed",
            preventive_policy=None,
            planner_profile=profile,
            planner_profile_values=values,
            enable_model_scored_deterring=False,
            enable_predicted_deltaJ_gate=False,
            model_deterring_gate_policy="heuristic",
        )

        self.assertEqual(resolved["preventive_policy"], "heuristic")
        self.assertEqual(resolved["preventive_policy_source"], f"profile:{profile}")
        self.assertTrue(resolved["enable_model_scored_deterring"])
        self.assertFalse(resolved["enable_predicted_deltaJ_gate"])
        self.assertEqual(resolved["model_deterring_gate_policy"], "heuristic")
        self.assertFalse(resolved["selective_preventive_enabled"])

    def test_prediction_only_profile_does_not_auto_enable_selective_gate_or_calibration(self):
        profile = "thesis_calibrated_selective_proposed"
        values = get_planner_profile_values(profile)
        policy_resolved = _resolve_preventive_policy_settings(
            simulation_mode="prediction_only",
            preventive_policy=None,
            planner_profile=profile,
            planner_profile_values=values,
            enable_model_scored_deterring=False,
            enable_predicted_deltaJ_gate=False,
            model_deterring_gate_policy="heuristic",
        )
        calib_resolved = _resolve_calibration_runtime_overrides(
            simulation_mode="prediction_only",
            use_frozen_calibration=False,
            calibration_ranking_path=None,
            calibration_manifest_path=None,
            calibration_config_id=None,
            planner_profile=profile,
            planner_profile_values=values,
            alpha_inhib=0.10,
            omega_inhib=100.0,
            mu_base=9.0e-06,
            bg_ema=0.03,
        )

        self.assertEqual(policy_resolved["preventive_policy"], "off")
        self.assertFalse(policy_resolved["selective_preventive_enabled"])
        self.assertFalse(calib_resolved["use_frozen_calibration"])
        self.assertEqual(calib_resolved["selected_calibration_config_id"], "")
        self.assertAlmostEqual(calib_resolved["alpha_inhib"], 0.10)
        self.assertAlmostEqual(calib_resolved["omega_inhib"], 100.0)

    def test_run_baseline_suite_keeps_proposed_only_overrides_on_proposed_baseline(self):
        captured = []

        def fake_run_metrics_experiments(**sim_kwargs):
            captured.append(dict(sim_kwargs))
            selected_config = "cfg_top" if bool(sim_kwargs.get("use_frozen_calibration")) else ""
            preventive_policy = str(sim_kwargs.get("preventive_policy", ""))
            return {
                "num_runs": 1,
                "runs": [
                    {
                        "preventive_policy": preventive_policy,
                        "preventive_policy_source": "argument" if preventive_policy else "legacy",
                        "selected_calibration_config_id": selected_config,
                        "selected_calibration_source": "argument" if selected_config else "disabled",
                        "selective_preventive_enabled": int(preventive_policy == "sprt_capacity"),
                        "use_frozen_calibration": int(bool(selected_config)),
                    }
                ],
                "summary": {
                    "value_weighted_exposure": {"mean": 1.0, "var": 0.0},
                },
                "time_summary": [],
                "config_summary": {},
            }

        with patch("DeterrentSystem.run_metrics_experiments", side_effect=fake_run_metrics_experiments):
            result = run_baseline_suite(
                num_runs=1,
                seed_start=100,
                report_each_run=False,
                collect_time_metrics=False,
                planner_profile="thesis_calibrated_selective_proposed",
                proposed_preventive_policy="sprt_capacity",
                use_frozen_calibration=True,
                calibration_manifest_path="results/sestpp_calibration_sweep/sestpp_calibration_sweep_manifest.json",
            )

        self.assertEqual(len(captured), 3)
        self.assertEqual([call["simulation_mode"] for call in captured], ["reactive", "prediction_only", "proposed"])
        self.assertNotIn("preventive_policy", captured[0])
        self.assertNotIn("preventive_policy", captured[1])
        self.assertFalse(captured[0].get("use_frozen_calibration", False))
        self.assertFalse(captured[1].get("use_frozen_calibration", False))
        self.assertEqual(captured[2]["preventive_policy"], "sprt_capacity")
        self.assertTrue(captured[2]["use_frozen_calibration"])

        comparison = result["comparison"].set_index("baseline")
        self.assertEqual(comparison.loc["reactive", "selected_calibration_config_id"], "")
        self.assertEqual(comparison.loc["prediction_only", "selected_calibration_config_id"], "")
        self.assertEqual(comparison.loc["proposed", "selected_calibration_config_id"], "cfg_top")
        self.assertEqual(comparison.loc["proposed", "preventive_policy"], "sprt_capacity")


if __name__ == "__main__":
    unittest.main()
