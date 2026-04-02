import unittest

import DeterrentSystem as production_ds
import DeterrentSystem_assignment_lab as assignment_lab_ds
import DeterrentSystem_simple_tasks as simple_ds


MODULES = (
    ("production", production_ds),
    ("assignment_lab", assignment_lab_ds),
    ("simple_tasks", simple_ds),
)


class GroundTruthDetectionNoiseTests(unittest.TestCase):
    def _run_last_metrics(self, module, *, bird_detection_prob: float) -> dict:
        if getattr(module, "mon", None) is not None:
            module.mon.enabled = False

        frames = module.run_simulation_frames_persistent(
            W=8.0,
            H=8.0,
            NX=8,
            NY=8,
            Nrobots=1,
            uav_fraction=0.0,
            seed=123,
            dt=1.0,
            T_end=1.0,
            simulation_mode="reactive",
            enable_patrolling=False,
            include_fallback_patrol=False,
            enable_model_scored_deterring=False,
            use_ground_truth=True,
            mu_true=0.4,
            alpha_true=0.0,
            beta_true=0.0,
            detect_range_m=1.0e9,
            bird_detection_prob=float(bird_detection_prob),
            telemetry_clear_on_start=False,
            telemetry_prompt_save=False,
            report_metrics_end=False,
        )
        last = None
        for snap in frames:
            last = snap
        self.assertIsNotNone(last)
        return dict(last["metrics"])

    def test_zero_detection_probability_creates_only_false_negatives(self):
        for label, module in MODULES:
            with self.subTest(module=label):
                metrics = self._run_last_metrics(module, bird_detection_prob=0.0)
                self.assertGreater(metrics["truth_accepted_events"], 0)
                self.assertGreater(metrics["truth_detection_opportunities"], 0)
                self.assertEqual(metrics["truth_detections_observed"], 0)
                self.assertEqual(metrics["truth_detections_missed_range"], 0)
                self.assertEqual(
                    metrics["truth_detections_missed_false_negative"],
                    metrics["truth_detection_opportunities"],
                )

    def test_unit_detection_probability_observes_every_in_range_truth_event(self):
        for label, module in MODULES:
            with self.subTest(module=label):
                metrics = self._run_last_metrics(module, bird_detection_prob=1.0)
                self.assertGreater(metrics["truth_accepted_events"], 0)
                self.assertGreater(metrics["truth_detection_opportunities"], 0)
                self.assertEqual(metrics["truth_detections_missed_range"], 0)
                self.assertEqual(metrics["truth_detections_missed_false_negative"], 0)
                self.assertEqual(
                    metrics["truth_detections_observed"],
                    metrics["truth_detection_opportunities"],
                )


if __name__ == "__main__":
    unittest.main()
