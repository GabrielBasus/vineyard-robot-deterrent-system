import argparse
import json
import tempfile
from pathlib import Path
import unittest

from experiments.habituation_stl_selected_configs import load_selected_config_overrides
import experiments.run_habituation_stl_kappa_sweep as kappa_sweep
import experiments.run_habituation_stl_load_sweep as load_sweep
import experiments.run_habituation_stl_production_ladder as ladder


class HabituationStlSelectedConfigSweepTests(unittest.TestCase):
    def test_loader_filters_selected_configs_by_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selected_configs.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "baseline": "B1_greedy_fixedcue",
                            "overrides": {"model_deterring_budget_per_robot_per_hr": 6},
                        },
                        {
                            "baseline": "B4_res_stl_full_multicue",
                            "overrides": {"reservation_fraction": 0.4},
                        },
                    ]
                ),
                encoding="utf-8",
            )

            overrides = load_selected_config_overrides(
                path,
                systems=["B4_res_stl_full_multicue"],
            )

        self.assertEqual(overrides, {"B4_res_stl_full_multicue": {"reservation_fraction": 0.4}})

    def test_ladder_applies_selected_overrides_per_baseline(self):
        args = argparse.Namespace(
            outdir="",
            duration_s=900.0,
            num_runs=1,
            seed_start=123,
            max_workers=1,
            nx=60,
            ny=48,
            nrobots=4,
            warmup_s=0.0,
            task_replan_period_s=45.0,
            reservation_fraction=0.25,
            mu_true=2.0e-5,
            alpha_true=0.3,
            beta_true=0.25,
            sigma_true=12.0,
            omega_true=600.0,
            deterrence_beta_scale=4.0,
            deterrence_sigma_scale=4.0,
            deterrence_omega_scale=3.0,
            fixed_cue_mode="laser",
            habituation_kappa=0.5,
            truth_habituation_t_rec_s=None,
            truth_habituation_kappa=None,
            truth_habituation_gamma=None,
            truth_habituation_update_model=None,
            planner_habituation_t_rec_s=None,
            planner_habituation_kappa=None,
            planner_habituation_gamma=None,
            planner_habituation_update_model=None,
            stl_e_star=5.0,
            stl_t_cov_s=1200.0,
            stl_w_s=600.0,
            stl_eta_min=0.4,
            stl_horizon_s=300.0,
            stl_theta=12.0,
            systems=["B1_greedy_fixedcue", "B4_res_stl_full_multicue"],
            selected_config_overrides={
                "B1_greedy_fixedcue": {
                    "model_deterring_budget_per_robot_per_hr": 6,
                    "predictive_fixed_deterring_mode": "formation",
                },
                "B4_res_stl_full_multicue": {
                    "reservation_fraction": 0.4,
                    "forecast_horizon_s": 420.0,
                    "stl_horizon_s": 420.0,
                },
            },
        )

        jobs = ladder._build_jobs(args)
        by_baseline = {job["baseline"]: job["params"] for job in jobs}

        self.assertEqual(
            by_baseline["B1_greedy_fixedcue"]["model_deterring_budget_per_robot_per_hr"],
            6,
        )
        self.assertEqual(by_baseline["B1_greedy_fixedcue"]["predictive_fixed_deterring_mode"], "formation")
        self.assertEqual(by_baseline["B4_res_stl_full_multicue"]["reservation_fraction"], 0.4)
        self.assertEqual(by_baseline["B4_res_stl_full_multicue"]["forecast_horizon_s"], 420.0)

    def test_load_sweep_base_args_carry_selected_overrides(self):
        args = argparse.Namespace(
            mu_true_placeholder=2.0e-5,
            nx=60,
            ny=48,
            nrobots=4,
            duration_s=900.0,
            num_runs=2,
            seed_start=100,
            max_workers=1,
            systems=["B4_res_stl_full_multicue"],
            selected_config_overrides={"B4_res_stl_full_multicue": {"reservation_fraction": 0.4}},
            reservation_fraction=0.25,
            deterrence_beta_scale=4.0,
            deterrence_sigma_scale=4.0,
            deterrence_omega_scale=3.0,
            habituation_kappa=0.5,
        )

        base = load_sweep._base_ladder_args(args)

        self.assertEqual(base.selected_config_overrides, args.selected_config_overrides)

    def test_kappa_sweep_base_args_carry_selected_overrides(self):
        args = argparse.Namespace(
            kappa_placeholder=0.5,
            mu_true=2.0e-5,
            nx=60,
            ny=48,
            nrobots=4,
            duration_s=900.0,
            num_runs=2,
            seed_start=100,
            max_workers=1,
            systems=["B4_res_stl_full_multicue"],
            selected_config_overrides={"B4_res_stl_full_multicue": {"reservation_fraction": 0.4}},
            reservation_fraction=0.25,
            deterrence_beta_scale=4.0,
            deterrence_sigma_scale=4.0,
            deterrence_omega_scale=3.0,
        )

        base = kappa_sweep._base_ladder_args(args)

        self.assertEqual(base.selected_config_overrides, args.selected_config_overrides)


if __name__ == "__main__":
    unittest.main()
