import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from calibration_config import load_frozen_sestpp_calibration
from DeterrentSystem import (
    _resolve_calibration_runtime_overrides,
    _resolve_preventive_policy_settings,
    run_baseline_suite,
    run_simulation_frames_persistent,
)
from diagnostics.diagnostic_sestpp_subsystem import SubsystemConfig, _model_intervention_replay_params
from experiments import compare_field_divergence_lab as compare_field_divergence_lab
from experiments import run_field_divergence_confirm_lab as run_field_divergence_confirm_lab
from experiments.run_sestpp_calibration_sweep import (
    _build_divergence_rerank_confirm_sim_kwargs,
    _rank_divergence_rerank_summary,
    _rank_feedback_summary,
    _rank_shared_summary,
    _resolve_divergence_rerank_confirm_context,
    _select_deployment_row,
)
from planner_profiles import get_planner_profile_values
from SESTPP import OnlineSESTPP
from demos import demo_systems as packaged_demo_systems


class CalibrationPipelineTests(unittest.TestCase):
    def _write_legacy_calibration_artifacts(self, root: Path) -> tuple[Path, Path]:
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

    def _write_full_calibration_artifacts(self, root: Path) -> tuple[Path, Path]:
        ranking_path = root / "ranking.csv"
        ranking_path.write_text(
            "\n".join(
                [
                    "config_id,rank,prediction_only_config_id,proposed_config_id,prediction_only_model_sigma,prediction_only_model_omega,prediction_only_model_alpha_in,prediction_only_model_alpha_cross,prediction_only_model_alpha_inhib,prediction_only_model_omega_inhib,prediction_only_model_mu_base,prediction_only_model_bg_ema,prediction_only_model_feedback_sigma_scale,prediction_only_model_feedback_omega_scale,proposed_model_sigma,proposed_model_omega,proposed_model_alpha_in,proposed_model_alpha_cross,proposed_model_alpha_inhib,proposed_model_omega_inhib,proposed_model_mu_base,proposed_model_bg_ema,proposed_model_feedback_sigma_scale,proposed_model_feedback_omega_scale,proposed_field_logloss_mean,proposed_field_brier_mean,proposed_nll_mean,nll_improvement_pct_mean",
                    "cfg_top,1,pred_top,prop_top,15.0,720.0,0.31,0.07,0.12,805.0,2.5e-06,0.002,1.00,1.00,13.0,640.0,0.27,0.03,0.61,910.0,8.5e-06,0.004,1.25,1.50,0.11,0.07,0.21,12.5",
                    "cfg_alt,2,pred_alt,prop_alt,14.0,680.0,0.28,0.05,0.10,780.0,3.0e-06,0.005,1.00,1.00,12.0,610.0,0.24,0.04,0.44,860.0,6.0e-06,0.006,0.80,0.90,0.18,0.10,0.25,7.0",
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
                        "prediction_only_config_id": "pred_top",
                        "proposed_config_id": "prop_top",
                        "prediction_only_model_sigma": 15.0,
                        "prediction_only_model_omega": 720.0,
                        "prediction_only_model_alpha_in": 0.31,
                        "prediction_only_model_alpha_cross": 0.07,
                        "prediction_only_model_alpha_inhib": 0.12,
                        "prediction_only_model_omega_inhib": 805.0,
                        "prediction_only_model_mu_base": 2.5e-06,
                        "prediction_only_model_bg_ema": 0.002,
                        "prediction_only_model_feedback_sigma_scale": 1.0,
                        "prediction_only_model_feedback_omega_scale": 1.0,
                        "proposed_model_sigma": 13.0,
                        "proposed_model_omega": 640.0,
                        "proposed_model_alpha_in": 0.27,
                        "proposed_model_alpha_cross": 0.03,
                        "proposed_model_alpha_inhib": 0.61,
                        "proposed_model_omega_inhib": 910.0,
                        "proposed_model_mu_base": 8.5e-06,
                        "proposed_model_bg_ema": 0.004,
                        "proposed_model_feedback_sigma_scale": 1.25,
                        "proposed_model_feedback_omega_scale": 1.50,
                        "proposed_field_logloss_mean": 0.11,
                    },
                    "best_models": {
                        "prediction_only": {
                            "model_sigma": 15.0,
                            "model_omega": 720.0,
                            "model_alpha_in": 0.31,
                            "model_alpha_cross": 0.07,
                            "model_alpha_inhib": 0.12,
                            "model_omega_inhib": 805.0,
                            "model_mu_base": 2.5e-06,
                            "model_bg_ema": 0.002,
                            "model_feedback_sigma_scale": 1.0,
                            "model_feedback_omega_scale": 1.0,
                        },
                        "proposed": {
                            "model_sigma": 13.0,
                            "model_omega": 640.0,
                            "model_alpha_in": 0.27,
                            "model_alpha_cross": 0.03,
                            "model_alpha_inhib": 0.61,
                            "model_omega_inhib": 910.0,
                            "model_mu_base": 8.5e-06,
                            "model_bg_ema": 0.004,
                            "model_feedback_sigma_scale": 1.25,
                            "model_feedback_omega_scale": 1.50,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return ranking_path, manifest_path

    def test_load_frozen_calibration_uses_top_ranked_csv_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ranking_path, _manifest_path = self._write_full_calibration_artifacts(Path(tmpdir))
            cfg = load_frozen_sestpp_calibration(ranking_path=ranking_path)

        self.assertEqual(cfg.config_id, "cfg_top")
        self.assertEqual(cfg.prediction_only_config_id, "pred_top")
        self.assertEqual(cfg.proposed_config_id, "prop_top")
        self.assertAlmostEqual(cfg.prediction_only.model_sigma, 15.0)
        self.assertAlmostEqual(cfg.prediction_only.model_omega, 720.0)
        self.assertAlmostEqual(cfg.prediction_only.model_alpha_in, 0.31)
        self.assertAlmostEqual(cfg.prediction_only.model_alpha_cross, 0.07)
        self.assertAlmostEqual(cfg.prediction_only.model_alpha_inhib, 0.12)
        self.assertAlmostEqual(cfg.prediction_only.model_omega_inhib, 805.0)
        self.assertAlmostEqual(cfg.prediction_only.model_mu_base, 2.5e-06)
        self.assertAlmostEqual(cfg.prediction_only.model_bg_ema, 0.002)
        self.assertAlmostEqual(cfg.proposed.model_sigma, 13.0)
        self.assertAlmostEqual(cfg.proposed.model_omega, 640.0)
        self.assertAlmostEqual(cfg.proposed.model_alpha_inhib, 0.61)
        self.assertAlmostEqual(cfg.proposed.model_feedback_sigma_scale, 1.25)
        self.assertAlmostEqual(cfg.proposed.model_feedback_omega_scale, 1.50)
        self.assertEqual(cfg.summary_metrics["rank"], 1)

    def test_load_frozen_calibration_backward_compatible_with_legacy_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ranking_path, _manifest_path = self._write_legacy_calibration_artifacts(Path(tmpdir))
            cfg = load_frozen_sestpp_calibration(ranking_path=ranking_path)

        self.assertIsNone(cfg.model_sigma)
        self.assertIsNone(cfg.model_omega)
        self.assertIsNone(cfg.model_alpha_in)
        self.assertIsNone(cfg.model_alpha_cross)
        self.assertAlmostEqual(cfg.model_feedback_sigma_scale, 1.0)
        self.assertAlmostEqual(cfg.model_feedback_omega_scale, 1.0)

    def test_load_frozen_calibration_supports_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _ranking_path, manifest_path = self._write_full_calibration_artifacts(Path(tmpdir))
            cfg = load_frozen_sestpp_calibration(manifest_path=manifest_path, config_id="cfg_alt")

        self.assertEqual(cfg.config_id, "cfg_alt")
        self.assertAlmostEqual(cfg.prediction_only.model_sigma, 14.0)
        self.assertAlmostEqual(cfg.proposed.model_alpha_inhib, 0.44)
        self.assertEqual(cfg.source_type, "ranking_csv")

    def test_runtime_calibration_override_applies_selected_parameters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ranking_path, _manifest_path = self._write_full_calibration_artifacts(Path(tmpdir))
            resolved = _resolve_calibration_runtime_overrides(
                simulation_mode="proposed",
                use_frozen_calibration=True,
                calibration_ranking_path=str(ranking_path),
                calibration_manifest_path=None,
                calibration_config_id=None,
                planner_profile="",
                planner_profile_values={},
                prediction_only_model_overrides=None,
                proposed_model_overrides=None,
                sigma=12.0,
                omega=600.0,
                alpha_in=None,
                alpha_cross=None,
                alpha_inhib=0.10,
                omega_inhib=100.0,
                mu_base=9.0e-06,
                bg_ema=0.03,
                model_feedback_sigma_scale=1.0,
                model_feedback_omega_scale=1.0,
            )

        self.assertTrue(resolved["use_frozen_calibration"])
        self.assertEqual(resolved["selected_calibration_config_id"], "cfg_top")
        self.assertEqual(resolved["selected_calibration_source"], "argument")
        self.assertAlmostEqual(resolved["sigma"], 13.0)
        self.assertAlmostEqual(resolved["omega"], 640.0)
        self.assertAlmostEqual(resolved["alpha_in"], 0.27)
        self.assertAlmostEqual(resolved["alpha_cross"], 0.03)
        self.assertAlmostEqual(resolved["alpha_inhib"], 0.61)
        self.assertAlmostEqual(resolved["omega_inhib"], 910.0)
        self.assertAlmostEqual(resolved["mu_base"], 8.5e-06)
        self.assertAlmostEqual(resolved["bg_ema"], 0.004)
        self.assertAlmostEqual(resolved["model_feedback_sigma_scale"], 1.25)
        self.assertAlmostEqual(resolved["model_feedback_omega_scale"], 1.50)

    def test_prediction_only_calibration_applies_prediction_only_block(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ranking_path, _manifest_path = self._write_full_calibration_artifacts(Path(tmpdir))
            resolved = _resolve_calibration_runtime_overrides(
                simulation_mode="prediction_only",
                use_frozen_calibration=True,
                calibration_ranking_path=str(ranking_path),
                calibration_manifest_path=None,
                calibration_config_id=None,
                planner_profile="",
                planner_profile_values={},
                prediction_only_model_overrides=None,
                proposed_model_overrides=None,
                sigma=12.0,
                omega=600.0,
                alpha_in=None,
                alpha_cross=None,
                alpha_inhib=0.10,
                omega_inhib=100.0,
                mu_base=9.0e-06,
                bg_ema=0.03,
                model_feedback_sigma_scale=1.0,
                model_feedback_omega_scale=1.0,
            )

        self.assertAlmostEqual(resolved["sigma"], 15.0)
        self.assertAlmostEqual(resolved["omega"], 720.0)
        self.assertAlmostEqual(resolved["alpha_in"], 0.31)
        self.assertAlmostEqual(resolved["alpha_cross"], 0.07)
        self.assertAlmostEqual(resolved["mu_base"], 2.5e-06)
        self.assertAlmostEqual(resolved["bg_ema"], 0.002)
        self.assertAlmostEqual(resolved["alpha_inhib"], 0.12)
        self.assertAlmostEqual(resolved["omega_inhib"], 805.0)
        self.assertAlmostEqual(resolved["model_feedback_sigma_scale"], 1.0)
        self.assertAlmostEqual(resolved["model_feedback_omega_scale"], 1.0)

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
            prediction_only_model_overrides=None,
            proposed_model_overrides=None,
            sigma=12.0,
            omega=600.0,
            alpha_in=None,
            alpha_cross=None,
            alpha_inhib=0.10,
            omega_inhib=100.0,
            mu_base=9.0e-06,
            bg_ema=0.03,
            model_feedback_sigma_scale=1.0,
            model_feedback_omega_scale=1.0,
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
        self.assertTrue(captured[1].get("use_frozen_calibration", False))
        self.assertEqual(captured[2]["preventive_policy"], "sprt_capacity")
        self.assertTrue(captured[2]["use_frozen_calibration"])

        comparison = result["comparison"].set_index("baseline")
        self.assertEqual(comparison.loc["reactive", "selected_calibration_config_id"], "")
        self.assertEqual(comparison.loc["prediction_only", "selected_calibration_config_id"], "cfg_top")
        self.assertEqual(comparison.loc["proposed", "selected_calibration_config_id"], "cfg_top")
        self.assertEqual(comparison.loc["proposed", "preventive_policy"], "sprt_capacity")

    def test_shared_stage_ranking_depends_on_prediction_only_metrics(self):
        summary_df = pd.DataFrame(
            [
                {
                    "config_id": "cfg_a",
                    "prediction_only_field_logloss_mean": 0.10,
                    "prediction_only_field_brier_mean": 0.20,
                    "prediction_only_nll_mean": 1.0,
                    "proposed_field_logloss_mean": 9.0,
                },
                {
                    "config_id": "cfg_b",
                    "prediction_only_field_logloss_mean": 0.30,
                    "prediction_only_field_brier_mean": 0.40,
                    "prediction_only_nll_mean": 2.0,
                    "proposed_field_logloss_mean": 0.01,
                },
            ]
        )

        ranked = _rank_shared_summary(summary_df)
        self.assertEqual(ranked.iloc[0]["config_id"], "cfg_a")

    def test_feedback_stage_ranking_prefers_guardrail_satisfying_configs(self):
        summary_df = pd.DataFrame(
            [
                {
                    "config_id": "cfg_fail",
                    "proposed_field_logloss_mean": 0.01,
                    "proposed_field_brier_mean": 0.01,
                    "proposed_nll_mean": 0.01,
                    "delta_field_logloss_proposed_minus_prediction_mean": 0.10,
                    "delta_field_brier_proposed_minus_prediction_mean": -0.01,
                    "delta_nll_proposed_minus_prediction_mean": -0.01,
                },
                {
                    "config_id": "cfg_pass",
                    "proposed_field_logloss_mean": 0.20,
                    "proposed_field_brier_mean": 0.20,
                    "proposed_nll_mean": 0.20,
                    "delta_field_logloss_proposed_minus_prediction_mean": -0.01,
                    "delta_field_brier_proposed_minus_prediction_mean": -0.01,
                    "delta_nll_proposed_minus_prediction_mean": -0.01,
                },
            ]
        )

        ranked = _rank_feedback_summary(summary_df)
        self.assertEqual(ranked.iloc[0]["config_id"], "cfg_pass")
        self.assertTrue(ranked.iloc[0]["guardrail_satisfied"])
        self.assertFalse(ranked.iloc[1]["guardrail_satisfied"])

    def test_divergence_rerank_prefers_candidates_with_stronger_field_divergence_evidence(self):
        summary_df = pd.DataFrame(
            [
                {
                    "config_id": "cfg_cal_top",
                    "calibration_rank": 1,
                    "suppressed_area_fraction_mean": 0.108,
                    "suppressed_area_fraction_lower_ci95": 0.082,
                    "final_response_improve_pct_mean": 4.0,
                    "final_exposure_improve_pct_mean": 1.0,
                },
                {
                    "config_id": "cfg_div_top",
                    "calibration_rank": 3,
                    "suppressed_area_fraction_mean": 0.112,
                    "suppressed_area_fraction_lower_ci95": 0.101,
                    "final_response_improve_pct_mean": -2.0,
                    "final_exposure_improve_pct_mean": 0.5,
                },
            ]
        )

        ranked = _rank_divergence_rerank_summary(summary_df)
        self.assertEqual(ranked.iloc[0]["config_id"], "cfg_div_top")
        self.assertTrue(ranked.iloc[0]["passes_divergence_floor_ci95"])
        self.assertFalse(ranked.iloc[1]["passes_divergence_floor_ci95"])

    def test_deployment_selection_prefers_divergence_rerank_result_when_present(self):
        calibration_ranking_df = pd.DataFrame(
            [
                {"config_id": "cfg_cal_top", "rank": 1},
                {"config_id": "cfg_cal_alt", "rank": 2},
            ]
        )
        divergence_summary_df = pd.DataFrame(
            [
                {"config_id": "cfg_div_top", "divergence_rerank_rank": 1, "calibration_rank": 2},
            ]
        )

        policy, row = _select_deployment_row(calibration_ranking_df, divergence_summary_df)
        self.assertEqual(policy, "divergence_rerank")
        self.assertEqual(row["config_id"], "cfg_div_top")

    def test_divergence_rerank_confirm_context_uses_confirm_yaml_settings(self):
        args = SimpleNamespace(
            divergence_rerank_confirm_config="configs/run_field_divergence_confirm_lab.yaml",
        )
        candidate = pd.Series(
            {
                "prediction_only_model_sigma": 12.0,
                "prediction_only_model_omega": 600.0,
                "prediction_only_model_omega_inhib": 800.0,
                "prediction_only_model_alpha_in": 0.20,
                "prediction_only_model_alpha_cross": 0.0,
                "prediction_only_model_alpha_inhib": 0.10,
                "prediction_only_model_mu_base": 5e-5,
                "prediction_only_model_bg_ema": 1e-7,
                "prediction_only_model_feedback_sigma_scale": 1.0,
                "prediction_only_model_feedback_omega_scale": 1.0,
                "proposed_model_sigma": 11.0,
                "proposed_model_omega": 550.0,
                "proposed_model_omega_inhib": 820.0,
                "proposed_model_alpha_in": 0.18,
                "proposed_model_alpha_cross": 0.02,
                "proposed_model_alpha_inhib": 0.90,
                "proposed_model_mu_base": 7e-5,
                "proposed_model_bg_ema": 2e-7,
                "proposed_model_feedback_sigma_scale": 0.625,
                "proposed_model_feedback_omega_scale": 2.0,
            }
        )

        context = _resolve_divergence_rerank_confirm_context(args)
        self.assertIsNotNone(context)
        self.assertEqual(context["config_path"], "configs/run_field_divergence_confirm_lab.yaml")
        self.assertEqual(context["args"].task_replan_period_s, 60.0)
        self.assertEqual(context["args"].patrol_hotspot_score_percentile, 97.0)
        self.assertEqual(context["args"].model_deterring_gate_policy, "sprt_capacity")

        sim_kwargs = _build_divergence_rerank_confirm_sim_kwargs(context["args"], candidate)
        self.assertFalse(sim_kwargs["use_frozen_calibration"])
        self.assertIsNone(sim_kwargs["calibration_manifest_path"])
        self.assertEqual(sim_kwargs["task_replan_period_s"], 60.0)
        self.assertEqual(sim_kwargs["patrol_hotspot_score_percentile"], 97.0)
        self.assertEqual(sim_kwargs["model_deterring_gate_policy"], "sprt_capacity")
        self.assertAlmostEqual(sim_kwargs["prediction_only_model_overrides"]["sigma"], 12.0)
        self.assertAlmostEqual(sim_kwargs["proposed_model_overrides"]["alpha_inhib"], 0.90)
        self.assertAlmostEqual(sim_kwargs["proposed_model_overrides"]["model_feedback_sigma_scale"], 0.625)
        self.assertAlmostEqual(sim_kwargs["proposed_model_overrides"]["model_feedback_omega_scale"], 2.0)

    def test_model_intervention_replay_uses_beta_true_and_scaled_kernel(self):
        cfg = SubsystemConfig(
            beta_true=0.40,
            intervention_sigma=12.0,
            intervention_omega=600.0,
            model_feedback_sigma_scale=1.25,
            model_feedback_omega_scale=1.50,
        )

        replay = _model_intervention_replay_params(cfg)
        self.assertAlmostEqual(replay["weight"], 0.40)
        self.assertAlmostEqual(replay["sigma"], 15.0)
        self.assertAlmostEqual(replay["omega_inhib"], 900.0)

    def test_runtime_honors_explicit_alpha_in_and_alpha_cross(self):
        captured = []

        class CaptureOnlineSESTPP(OnlineSESTPP):
            def __init__(self, *args, **kwargs):
                captured.append(dict(kwargs))
                super().__init__(*args, **kwargs)

        with patch("DeterrentSystem.OnlineSESTPP", CaptureOnlineSESTPP):
            list(
                run_simulation_frames_persistent(
                    seed=123,
                    T_end=0.0,
                    report_metrics_end=False,
                    telemetry_clear_on_start=False,
                    telemetry_prompt_save=False,
                    Nrobots=1,
                    alpha_in=0.123,
                    alpha_cross=0.456,
                )
            )

        self.assertTrue(captured)
        self.assertAlmostEqual(captured[0]["alpha_in"], 0.123)
        self.assertAlmostEqual(captured[0]["alpha_cross"], 0.456)

    def test_field_divergence_confirm_forwards_frozen_calibration(self):
        args = SimpleNamespace(
            hotspot_top_k=5,
            task_replan_period_s=60.0,
            assignment_method="hungarian",
            assignment_distance_cost_per_m=0.006,
            assignment_switch_penalty=1.0,
            assigner_w_task_value=0.0,
            patrol_min_hotspot_score=1e-4,
            patrol_hotspot_filter_mode="percentile",
            patrol_hotspot_score_percentile=97.0,
            patrol_hotspot_keep_top_k=6,
            model_deterring_window_s=90.0,
            model_deterring_min_persistence_replans=2,
            model_deterring_max_eta_s=120.0,
            model_deterring_score_margin=0.05,
            model_deterring_budget_per_robot_per_hr=4,
            model_deterring_budget_mode="count_per_hour",
            model_deterring_budget_utility_per_robot_per_hr=5.0,
            model_deterring_gate_policy="sprt_capacity",
            model_deterring_sprt_alpha=0.05,
            model_deterring_sprt_beta=0.20,
            model_deterring_chance_threshold=0.20,
            model_deterring_min_deltaj_per_cost=0.15,
            truth_beta_scale=1.0,
            truth_omega_scale=1.0,
            truth_sigma_scale=1.0,
            model_beta_scale=1.0,
            use_frozen_calibration=True,
            calibration_ranking_path="",
            calibration_manifest_path="results/sestpp_calibration_sweep/sestpp_calibration_sweep_manifest.json",
            calibration_config_id="cfg_top",
            t_end=600.0,
            dt=5.0,
        )

        sim_kwargs = run_field_divergence_confirm_lab._build_sim_kwargs(args)
        self.assertTrue(sim_kwargs["use_frozen_calibration"])
        self.assertIsNone(sim_kwargs["calibration_ranking_path"])
        self.assertEqual(
            sim_kwargs["calibration_manifest_path"],
            "results/sestpp_calibration_sweep/sestpp_calibration_sweep_manifest.json",
        )
        self.assertEqual(sim_kwargs["calibration_config_id"], "cfg_top")

    def test_field_divergence_configs_default_to_calibrated_manifest(self):
        root = Path(__file__).resolve().parents[1]
        compare_text = (root / "configs" / "compare_field_divergence_lab.yaml").read_text(encoding="utf-8")
        confirm_text = (root / "configs" / "run_field_divergence_confirm_lab.yaml").read_text(encoding="utf-8")

        for text in (compare_text, confirm_text):
            self.assertIn("use_frozen_calibration: true", text)
            self.assertIn(
                "manifest_path: results/sestpp_calibration_sweep/sestpp_calibration_sweep_manifest.json",
                text,
            )

    def test_compare_field_divergence_aliases_include_calibration_keys(self):
        self.assertEqual(
            compare_field_divergence_lab.FIELD_DIVERGENCE_CONFIG_ALIASES["calibration.use_frozen_calibration"],
            "use_frozen_calibration",
        )
        self.assertEqual(
            compare_field_divergence_lab.FIELD_DIVERGENCE_CONFIG_ALIASES["calibration.manifest_path"],
            "calibration_manifest_path",
        )

    def test_demo_systems_drops_manual_model_overrides_when_calibrated(self):
        config = deepcopy(packaged_demo_systems.DEFAULT_CONFIG)
        for system in config["systems"]:
            if system["key"] == "prediction_only":
                system["overrides"].update(
                    {
                        "sigma": 999.0,
                        "omega": 888.0,
                        "mu_base": 0.123,
                    }
                )
            elif system["key"] == "proposed":
                system["overrides"].update(
                    {
                        "alpha_inhib": 0.999,
                        "bg_ema": 0.456,
                        "model_feedback_sigma_scale": 9.0,
                    }
                )

        specs = packaged_demo_systems._resolve_system_specs(config)
        by_key = {spec.key: spec for spec in specs}

        self.assertTrue(by_key["prediction_only"].sim_kwargs["use_frozen_calibration"])
        self.assertTrue(by_key["proposed"].sim_kwargs["use_frozen_calibration"])
        self.assertNotIn("sigma", by_key["prediction_only"].sim_kwargs)
        self.assertNotIn("omega", by_key["prediction_only"].sim_kwargs)
        self.assertNotIn("mu_base", by_key["prediction_only"].sim_kwargs)
        self.assertNotIn("alpha_inhib", by_key["proposed"].sim_kwargs)
        self.assertNotIn("bg_ema", by_key["proposed"].sim_kwargs)
        self.assertNotIn("model_feedback_sigma_scale", by_key["proposed"].sim_kwargs)


if __name__ == "__main__":
    unittest.main()
