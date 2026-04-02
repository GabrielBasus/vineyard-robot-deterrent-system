import copy
import unittest

import numpy as np

from Robot import Robot, RobotProfile
from SESTPP import OnlineSESTPP
from TaskGenerator import TaskGenerator, estimate_counterfactual_reduction


class TaskGeneratorCounterfactualScoringTests(unittest.TestCase):
    def setUp(self):
        self.zone = [
            (0.0, 0.0),
            (40.0, 0.0),
            (40.0, 40.0),
            (0.0, 40.0),
        ]

    def _build_model(self, **overrides):
        params = {
            "x_min": 0.0,
            "x_max": 40.0,
            "y_min": 0.0,
            "y_max": 40.0,
            "nx": 41,
            "ny": 41,
            "sigma": 2.0,
            "omega": 60.0,
            "omega_inhib": 60.0,
            "alpha_in": 1.0,
            "alpha_cross": 0.0,
            "alpha_inhib": 1.0,
            "mu_base": 1.0e-6,
            "bg_ema": 0.0,
        }
        params.update(overrides)
        return OnlineSESTPP(**params)

    def _stamp_events(self, model, points):
        for x, y in points:
            model.add_local_event(x, y)

    def _test_profiles(self):
        return {
            "r1": RobotProfile(
                id="r1",
                type="UAV",
                speed_mps=5.0,
                endurance_min=30.0,
                battery=1.0,
                health=1.0,
                has_deterrent=True,
                deterrent_eff=1.0,
            )
        }

    def _test_deterring_modes(self):
        return {
            "test_mode": {
                "beta": 0.5,
                "omega": 60.0,
                "sigma": 2.0,
                "w_eta": 1.0,
                "fixed_cost": 0.0,
            }
        }

    def _counterfactual_summary(self, model, x=20.0, y=20.0, *, beta=0.5, sigma=2.0, omega=60.0, horizon_s=60.0):
        return estimate_counterfactual_reduction(
            model,
            x,
            y,
            beta_u=beta,
            sigma_u=sigma,
            omega_u=omega,
            horizon_s=horizon_s,
            mask_poly=self.zone,
            weight_fn=lambda _x, _y: 1.0,
        )

    def _generate_deterring_task(self, *, event_points, recent_points=None, robot_pose=(20.0, 20.0), deterring_modes=None):
        model = self._build_model()
        self._stamp_events(model, event_points)
        robot = Robot("r1", model, self.zone, [])
        for x, y in (recent_points if recent_points is not None else event_points):
            robot.recent_events.append((float(x), float(y), 0.0))

        taskgen = TaskGenerator(merge_radius_m=4.0, patrol_cooldown_s=0.0)
        profiles = self._test_profiles()
        if deterring_modes is None:
            deterring_modes = self._test_deterring_modes()

        taskgen.periodic_patrolling(
            robots={"r1": robot},
            now_t=0.0,
            hotspot_top_k=1,
            include_fallback_patrol=False,
            enable_model_scored_deterring=True,
            deterring_window_s=30.0,
            deterring_risk_threshold=0.0,
            deterring_min_recent_points=1,
            deterring_field_threshold=-1.0,
            deterring_min_persistence_replans=1,
            deterring_repeat_block_window_s=0.0,
            deterring_max_eta_s=1.0e9,
            enable_predicted_deltaJ_gate=False,
            model_deterring_gate_policy="heuristic",
            min_hotspot_score=1.0e9,
            patrol_hotspot_filter_mode="absolute",
            horizon_s=60.0,
            profiles=profiles,
            robot_poses={"r1": robot_pose},
            spinup_by_type={"UAV": 0.0},
            deterring_modes=deterring_modes,
            weight_fn=lambda _x, _y: 1.0,
        )
        rows = taskgen.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["type"], "deterring")
        return row

    def _weighted_positive_excess(self, model):
        baseline = model.mu * model.time_multiplier(model.t_now)
        return float(np.sum(np.clip(model.lam - baseline, 0.0, None)) * model.dx * model.dy)

    def _realized_suppression(self, model, *, beta=0.5, sigma=2.0, omega=60.0, horizon_s=60.0, dt=1.0):
        no_action = copy.deepcopy(model)
        with_action = copy.deepcopy(model)
        with_action.add_intervention_event(20.0, 20.0, weight=beta, sigma=sigma, omega_inhib=omega, mode="test_mode")

        realized = 0.0
        steps = int(horizon_s / dt)
        for _ in range(steps):
            realized += max(
                self._weighted_positive_excess(no_action) - self._weighted_positive_excess(with_action),
                0.0,
            ) * dt
            no_action.advance_time(dt)
            with_action.advance_time(dt)
        return float(realized)

    def test_higher_local_risk_yields_higher_predicted_deltaj(self):
        low_model = self._build_model()
        high_model = self._build_model()
        self._stamp_events(low_model, [(20.0, 20.0)] * 2)
        self._stamp_events(high_model, [(20.0, 20.0)] * 2 + [(14.0, 20.0)] * 2 + [(26.0, 20.0)] * 2)

        low_summary = self._counterfactual_summary(low_model, beta=0.1, sigma=4.0)
        high_summary = self._counterfactual_summary(high_model, beta=0.1, sigma=4.0)

        self.assertGreater(
            high_summary["predicted_reduction_raw"],
            low_summary["predicted_reduction_raw"],
        )

    def test_higher_eta_lowers_utility_but_not_raw_predicted_deltaj(self):
        near_task = self._generate_deterring_task(
            event_points=[(20.0, 20.0)] * 3,
            robot_pose=(20.0, 20.0),
        )
        far_task = self._generate_deterring_task(
            event_points=[(20.0, 20.0)] * 3,
            robot_pose=(0.0, 0.0),
        )

        self.assertAlmostEqual(
            near_task["predicted_deltaJ"],
            far_task["predicted_deltaJ"],
            places=10,
        )
        self.assertGreater(far_task["cost_eta"], near_task["cost_eta"])
        self.assertLess(far_task["utility"], near_task["utility"])
        self.assertAlmostEqual(near_task["score"], near_task["utility"], places=10)
        self.assertAlmostEqual(far_task["score"], far_task["utility"], places=10)

    def test_larger_sigma_only_helps_when_there_is_risk_in_the_footprint(self):
        center_model = self._build_model()
        spread_model = self._build_model()
        self._stamp_events(center_model, [(20.0, 20.0)] * 4)
        self._stamp_events(spread_model, [(14.0, 20.0)] * 4 + [(26.0, 20.0)] * 4)

        center_narrow = self._counterfactual_summary(center_model, sigma=1.5)
        center_wide = self._counterfactual_summary(center_model, sigma=6.0)
        spread_narrow = self._counterfactual_summary(spread_model, sigma=1.5)
        spread_wide = self._counterfactual_summary(spread_model, sigma=6.0)

        self.assertGreaterEqual(
            center_narrow["predicted_reduction_raw"],
            center_wide["predicted_reduction_raw"],
        )
        self.assertGreater(
            spread_wide["predicted_reduction_raw"],
            spread_narrow["predicted_reduction_raw"],
        )

    def test_predicted_reduction_tracks_realized_suppression_in_small_run(self):
        model = self._build_model(omega=60.0, omega_inhib=60.0, alpha_inhib=1.0)
        self._stamp_events(model, [(20.0, 20.0)] * 2)

        summary = self._counterfactual_summary(
            model,
            beta=0.35,
            sigma=2.0,
            omega=60.0,
            horizon_s=60.0,
        )
        predicted = float(summary["predicted_reduction_raw"])
        realized = self._realized_suppression(
            model,
            beta=0.35,
            sigma=2.0,
            omega=60.0,
            horizon_s=60.0,
            dt=1.0,
        )

        rel_err = abs(predicted - realized) / max(realized, 1.0e-9)
        debug_summary = {
            "predicted_deltaJ": predicted,
            "realized_suppression": realized,
            "relative_error": rel_err,
            "available_weighted_integral": float(summary["available_weighted_integral"]),
            "suppression_weighted_integral": float(summary["suppression_weighted_integral"]),
        }

        self.assertGreater(predicted, 0.0, msg=str(debug_summary))
        self.assertGreater(realized, 0.0, msg=str(debug_summary))
        self.assertLess(rel_err, 0.15, msg=str(debug_summary))

    def test_hotspot_origin_can_generate_without_recent_detection_support(self):
        model = self._build_model()
        self._stamp_events(model, [(20.0, 20.0)] * 6)
        robot = Robot("r1", model, self.zone, [])
        taskgen = TaskGenerator(merge_radius_m=4.0, patrol_cooldown_s=0.0)

        for now_t in (0.0, 10.0):
            taskgen.clear()
            robot.recent_events.clear()
            taskgen.periodic_patrolling(
                robots={"r1": robot},
                now_t=now_t,
                hotspot_top_k=1,
                include_fallback_patrol=False,
                enable_model_scored_deterring=True,
                deterring_window_s=0.0,
                deterring_risk_threshold=0.0,
                deterring_min_recent_points=5,
                deterring_field_threshold=-1.0,
                deterring_min_persistence_replans=2,
                deterring_repeat_block_window_s=0.0,
                deterring_max_eta_s=1.0e9,
                enable_predicted_deltaJ_gate=False,
                model_deterring_gate_policy="heuristic",
                min_hotspot_score=0.0,
                patrol_hotspot_filter_mode="absolute",
                horizon_s=60.0,
                profiles=self._test_profiles(),
                robot_poses={"r1": (20.0, 20.0)},
                spinup_by_type={"UAV": 0.0},
                deterring_modes=self._test_deterring_modes(),
                weight_fn=lambda _x, _y: 1.0,
            )

        rows = taskgen.rows()
        self.assertEqual(len(rows), 1, msg=str(rows))
        row = rows[0]
        self.assertEqual(row["type"], "deterring")
        self.assertEqual(row["origin"], "model_hotspot")
        self.assertEqual(row["support"], 0)
        self.assertGreaterEqual(row["persistence"], 2)
        self.assertGreater(taskgen.diag_counts.get("model_deterring_candidates_model_hotspot", 0), 0)
        self.assertGreater(taskgen.diag_counts.get("model_deterring_generated_model_hotspot", 0), 0)
        self.assertEqual(taskgen.diag_counts.get("model_deterring_generated_model_detection_cluster", 0), 0)

    def test_direct_detection_enqueue_behavior_is_unchanged(self):
        taskgen = TaskGenerator(merge_radius_m=4.0, patrol_cooldown_s=0.0)
        taskgen.on_detection("r1", 12.0, 18.0, 5.0)

        rows = taskgen.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["type"], "deterring")
        self.assertEqual(row["origin"], "detection")
        self.assertIsNone(row["mode"])
        self.assertEqual(row["support"], 0)
        self.assertAlmostEqual(row["predicted_deltaJ"], 0.0)


if __name__ == "__main__":
    unittest.main()
