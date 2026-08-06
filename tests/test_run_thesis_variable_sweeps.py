import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import experiments.run_thesis_variable_sweeps as sweeps


class SweepConfigBuilderTests(unittest.TestCase):
    def _system_map(self, config: dict) -> dict[str, dict]:
        return {str(system["key"]): dict(system) for system in config["systems"]}

    def test_reservation_fraction_config_uses_unc_reference_and_only_varies_rho(self):
        config = sweeps.build_testbench_config("reservation_fraction", "nominal", smoke=False)
        systems = self._system_map(config)
        self.assertEqual(config["outputs"]["reference_system"], "unc")
        self.assertEqual(set(systems.keys()), {"unc", "res_rho_0p00", "res_rho_0p10", "res_rho_0p25", "res_rho_0p40"})
        rho_values = {
            float(system["params"]["reservation_fraction"])
            for key, system in systems.items()
            if key != "unc"
        }
        self.assertEqual(rho_values, {0.0, 0.10, 0.25, 0.40})
        for key, system in systems.items():
            if key == "unc":
                self.assertEqual(system["params"]["dispatch_policy"], "unc")
                continue
            self.assertEqual(system["params"]["dispatch_policy"], "res")
            self.assertNotIn("reservation_window_s", system["params"])
            self.assertNotIn("reactive_override_slack_s", system["params"])
            self.assertNotIn("tau_service_s", system["params"])

    def test_reservation_window_config_only_varies_window(self):
        config = sweeps.build_testbench_config("reservation_window_s", "low", smoke=False)
        systems = self._system_map(config)
        self.assertEqual(config["scenario"]["Nrobots"], 8)
        self.assertEqual(
            {
                float(system["params"]["reservation_window_s"])
                for key, system in systems.items()
                if key != "unc"
            },
            {120.0, 300.0, 600.0, 1200.0},
        )
        for key, system in systems.items():
            if key == "unc":
                continue
            self.assertEqual(float(system["params"]["reservation_fraction"]), 0.25)
            self.assertNotIn("reactive_override_slack_s", system["params"])
            self.assertNotIn("tau_service_s", system["params"])

    def test_tau_service_config_only_varies_service_time(self):
        config = sweeps.build_testbench_config("tau_service_s", "high", smoke=True)
        systems = self._system_map(config)
        self.assertEqual(config["scenario"]["Nrobots"], 3)
        self.assertEqual(config["scenario"]["duration_s"], 300.0)
        self.assertEqual(
            {
                float(system["params"]["tau_service_s"])
                for key, system in systems.items()
                if key != "unc"
            },
            {10.0, 20.0, 35.0, 50.0},
        )
        for key, system in systems.items():
            if key == "unc":
                continue
            self.assertEqual(float(system["params"]["reservation_fraction"]), 0.25)
            self.assertNotIn("reservation_window_s", system["params"])
            self.assertNotIn("reactive_override_slack_s", system["params"])


class SweepSummaryTests(unittest.TestCase):
    def test_summary_and_manifest_preserve_regime_defaults_and_promising_logic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = sweeps.build_sweep_spec(
                "reservation_window_s",
                "low",
                smoke=True,
                outdir_root=Path(tmpdir),
            )
            summary_df = pd.DataFrame(
                [
                    {
                        "metric": "native_value_weighted_exposure",
                        "label": "Exposure",
                        "goal": "lower",
                        "winner": "res_tw_120",
                    },
                    {
                        "metric": "native_mean_response_time_s",
                        "label": "Response",
                        "goal": "lower",
                        "winner": "unc",
                    },
                    {
                        "metric": "native_predictive_completed_fraction",
                        "label": "Predictive Completion Fraction",
                        "goal": "higher",
                        "winner": "res_tw_600",
                    },
                    {
                        "metric": "native_robot_predictive_fraction_mean",
                        "label": "Predictive Time Fraction",
                        "goal": "higher",
                        "winner": "res_tw_120",
                    },
                ]
            )
            per_run_df = pd.DataFrame(
                [
                    {
                        "system": "unc",
                        "seed": 123,
                        "native_mean_response_time_s": 20.0,
                        "native_reactive_completed_fraction": 0.80,
                        "native_robot_predictive_fraction_mean": 0.10,
                    },
                    {
                        "system": "res_tw_120",
                        "seed": 123,
                        "native_mean_response_time_s": 21.0,
                        "native_reactive_completed_fraction": 0.78,
                        "native_robot_predictive_fraction_mean": 0.20,
                    },
                    {
                        "system": "res_tw_600",
                        "seed": 123,
                        "native_mean_response_time_s": 25.0,
                        "native_reactive_completed_fraction": 0.70,
                        "native_robot_predictive_fraction_mean": 0.25,
                    },
                ]
            )

            row = sweeps.build_sweep_result_summary(
                spec=spec,
                summary_df=summary_df,
                per_run_df=per_run_df,
                thresholds=sweeps.ACCEPTANCE_THRESHOLDS,
            )
            self.assertEqual(row["family"], "reservation_window_s")
            self.assertEqual(row["regime"], "low")
            self.assertEqual(row["best_exposure_system"], "res_tw_120")
            self.assertEqual(row["best_response_system"], "unc")
            self.assertEqual(row["promising_systems"], ["res_tw_120"])

            manifest = sweeps.build_suite_manifest(
                specs=[spec],
                thresholds=sweeps.ACCEPTANCE_THRESHOLDS,
                summary_rows=[row],
                outdir=Path(tmpdir),
            )
            self.assertEqual(manifest["acceptance_thresholds"]["max_response_regression_pct"], 10.0)
            self.assertEqual(manifest["fixed_defaults"]["reservation_window_s"], 600.0)
            self.assertEqual(manifest["sweeps"][0]["regime"], "low")
            self.assertEqual(manifest["sweeps"][0]["swept_parameters"], ["reservation_window_s"])


class SweepRunnerIntegrationTests(unittest.TestCase):
    def test_main_writes_expected_suite_artifacts(self):
        def fake_run_testbench_config(config_path: Path, *, current_repo: Path, main_repo: Path, max_workers: int) -> int:
            del current_repo, main_repo, max_workers
            config = json.loads(Path(config_path).read_text(encoding="utf-8"))
            outdir = Path(config["outputs"]["outdir"])
            outdir.mkdir(parents=True, exist_ok=True)
            systems = list(config["systems"])
            reference = str(config["outputs"]["reference_system"])
            system_order = [str(system["key"]) for system in systems]
            summary_df = pd.DataFrame(
                [
                    {
                        "metric": "native_value_weighted_exposure",
                        "label": "Value-Weighted Exposure",
                        "goal": "lower",
                        "winner": system_order[1],
                    },
                    {
                        "metric": "native_mean_response_time_s",
                        "label": "Mean Response Time (s)",
                        "goal": "lower",
                        "winner": reference,
                    },
                    {
                        "metric": "native_predictive_completed_fraction",
                        "label": "Predictive Completion Fraction",
                        "goal": "higher",
                        "winner": system_order[1],
                    },
                    {
                        "metric": "native_robot_predictive_fraction_mean",
                        "label": "Mean Predictive Time Fraction",
                        "goal": "higher",
                        "winner": system_order[1],
                    },
                ]
            )
            summary_df.to_csv(outdir / "summary_by_metric.csv", index=False)
            advantage_df = pd.DataFrame([{"Metric": "Exposure", f"{system_order[1]} vs {reference} advantage %": "1.0"}])
            advantage_df.to_csv(outdir / "advantage_vs_reference.csv", index=False)
            per_run_rows = []
            for offset, system_key in enumerate(system_order):
                per_run_rows.append(
                    {
                        "system": system_key,
                        "seed": 123,
                        "native_mean_response_time_s": 20.0 + offset,
                        "native_reactive_completed_fraction": 0.80 - (0.01 * offset),
                        "native_robot_predictive_fraction_mean": 0.10 + (0.05 * offset),
                    }
                )
            pd.DataFrame(per_run_rows).to_csv(outdir / "per_run_metrics.csv", index=False)
            pd.DataFrame([{"system": reference, "t": 0.0, "active_tasks": 0.0}]).to_csv(
                outdir / "per_run_timeseries.csv",
                index=False,
            )
            pd.DataFrame([{"system": system_order[1], "metric_wins": 2}]).to_csv(outdir / "system_scoreboard.csv", index=False)
            (outdir / "report.md").write_text("# Fake Testbench Report\n", encoding="utf-8")
            (outdir / "testbench_manifest.json").write_text(json.dumps({"config": config["metadata"]}, indent=2), encoding="utf-8")
            return 0

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            current_repo = root / "current"
            main_repo = root / "main"
            current_repo.mkdir()
            main_repo.mkdir()

            with patch(
                "experiments.run_thesis_variable_sweeps._run_testbench_config",
                side_effect=fake_run_testbench_config,
            ):
                rc = sweeps.main(
                    [
                        "--outdir",
                        str(root / "results"),
                        "--current-repo",
                        str(current_repo),
                        "--main-repo",
                        str(main_repo),
                        "--smoke",
                        "--skip-interactions",
                        "--family",
                        "reservation_fraction",
                        "--regime",
                        "nominal",
                    ]
                )

            outdir = root / "results"
            self.assertEqual(rc, 0)
            self.assertTrue((outdir / "sweep_overview.csv").exists())
            self.assertTrue((outdir / "suite_manifest.json").exists())
            self.assertTrue((outdir / "report.md").exists())
            generated_config = outdir / "generated_configs" / "thesis_sweep_reservation_fraction_smoke_nominal.json"
            self.assertTrue(generated_config.exists())
            per_sweep_outdir = outdir / "thesis_sweep_reservation_fraction_smoke_nominal"
            self.assertTrue((per_sweep_outdir / "summary_by_metric.csv").exists())
            self.assertTrue((per_sweep_outdir / "advantage_vs_reference.csv").exists())
            self.assertTrue((per_sweep_outdir / "best_setting_by_metric.csv").exists())


if __name__ == "__main__":
    unittest.main()
