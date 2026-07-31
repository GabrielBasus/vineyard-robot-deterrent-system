import math
import unittest

import DeterrentSystem as ds
from action_schema import make_detection_action, make_deterring_mode_action


class GroundTruthHabituationWiringTests(unittest.TestCase):
    def test_truth_event_params_preserve_habituation_mode_when_using_shared_suppression_params(self):
        action = make_deterring_mode_action(
            "laser",
            {"laser": {"beta": 0.45, "sigma": 10.0, "omega": 400.0}},
            service_time_s=5.0,
        )

        mode, beta, sigma, omega = ds._resolve_truth_deterrence_event_params(
            action,
            use_mode_dependent_truth_suppression=False,
            beta_true=0.25,
            sigma_true=12.0,
            omega_true=600.0,
        )

        self.assertEqual(mode, "laser")
        self.assertEqual(beta, 0.25)
        self.assertEqual(sigma, 12.0)
        self.assertEqual(omega, 600.0)

    def test_truth_event_params_keep_direct_detection_identity(self):
        action = make_detection_action(service_time_s=5.0)

        mode, beta, sigma, omega = ds._resolve_truth_deterrence_event_params(
            action,
            use_mode_dependent_truth_suppression=True,
            beta_true=0.25,
            sigma_true=12.0,
            omega_true=600.0,
        )

        self.assertEqual(mode, "direct_detection")
        self.assertEqual(beta, 0.25)
        self.assertEqual(sigma, 12.0)
        self.assertEqual(omega, 600.0)

    def _run_probe(self, *, enable_habituation):
        last = None
        for frame in ds.run_simulation_frames_persistent(
            W=120,
            H=120,
            NX=24,
            NY=20,
            Nrobots=3,
            T_end=180,
            dt=1,
            fps=1,
            seed=222,
            use_ground_truth=True,
            mu_true=0.00008,
            alpha_true=0.0,
            detect_range_m=500.0,
            bird_detection_prob=1.0,
            task_replan_period_s=10.0,
            arrival_radius_m=5.0,
            hold_time_s=5.0,
            tau_service_s=5.0,
            simulation_mode="reactive",
            enable_patrolling=False,
            enable_model_scored_deterring=False,
            dispatch_policy="react",
            enable_habituation=enable_habituation,
            habituation_kappa=0.5,
            habituation_T_rec_s=100000.0,
            telemetry_clear_on_start=False,
            telemetry_prompt_save=False,
            report_metrics_end=False,
            emit_tracking_state=True,
            tracking_include_arrays=False,
            tracking_preview_limit=200,
        ):
            last = frame
        metrics = (last or {}).get("metrics_compact") or {}
        runtime = (((last or {}).get("tracking_state") or {}).get("runtime_state") or {})
        events = runtime.get("recent_deterrences") or []
        if isinstance(events, dict):
            events = events.get("items") or []
        return metrics, events

    def test_completed_deterrences_feed_habituation_eta_into_truth_suppression_events(self):
        off_metrics, off_events = self._run_probe(enable_habituation=False)
        on_metrics, on_events = self._run_probe(enable_habituation=True)

        self.assertGreater(off_metrics["truth_candidate_events"], 0)
        self.assertGreater(on_metrics["truth_candidate_events"], 0)
        self.assertGreater(len(off_events), 0)
        self.assertGreater(len(on_events), 0)

        off_etas = [float(event.get("eta", 1.0)) for event in off_events]
        on_etas = [float(event.get("eta", 1.0)) for event in on_events]
        self.assertTrue(all(math.isclose(eta, 1.0) for eta in off_etas))
        self.assertLess(min(on_etas), 1.0)
        self.assertLess(on_metrics["habituation_eta_at_apply_mean"], 1.0)
        self.assertLess(on_metrics["habituation_eta_min"], 1.0)
        self.assertTrue(math.isfinite(on_metrics["truth_suppression_rate"]))


if __name__ == "__main__":
    unittest.main()
