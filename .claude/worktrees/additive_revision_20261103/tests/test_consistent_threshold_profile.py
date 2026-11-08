import json
import unittest
from pathlib import Path

from planner_profiles import (
    CONSISTENT_THRESHOLD_MAPPING,
    PLANNER_PROFILES,
    get_planner_profile_values,
    resolve_planner_profile_for_estimator,
)

BASE = "thesis_calibrated_selective_proposed"
CONSISTENT = "thesis_calibrated_selective_proposed_consistent"
UNMAPPED = "thesis_calibrated_selective_proposed_unmapped"
ESTIMATOR_UNIT_KEYS = (
    "model_deterring_risk_scale",
    "model_deterring_risk_threshold",
    "model_deterring_busy_risk_override",
    "stl_E_star",
    "stl_kernel_self",
    "min_hotspot_score",
    "patrol_cost_weight",
    "deterring_cost_multiplier",
)
PROVENANCE = Path(__file__).resolve().parent.parent / "docs" / "consistent_threshold_mapping.json"


class ConsistentThresholdProfileTests(unittest.TestCase):
    def test_consistent_estimator_selects_mapped_profile(self):
        self.assertEqual(resolve_planner_profile_for_estimator(BASE, "consistent"), CONSISTENT)
        self.assertEqual(resolve_planner_profile_for_estimator("thesis_selective", "Consistent"), CONSISTENT)

    def test_legacy_estimator_keeps_legacy_profile(self):
        self.assertEqual(resolve_planner_profile_for_estimator(BASE, "legacy"), BASE)
        self.assertEqual(resolve_planner_profile_for_estimator(BASE, None), BASE)
        self.assertEqual(resolve_planner_profile_for_estimator("", "consistent"), "")

    def test_explicit_profile_overrides_automatic_choice(self):
        self.assertEqual(resolve_planner_profile_for_estimator(UNMAPPED, "consistent"), UNMAPPED)
        self.assertEqual(resolve_planner_profile_for_estimator(CONSISTENT, "legacy"), CONSISTENT)
        self.assertEqual(resolve_planner_profile_for_estimator("thesis_confirm", "consistent"), "thesis_confirm")

    def test_legacy_profile_unchanged(self):
        values = get_planner_profile_values(BASE)
        for key in ESTIMATOR_UNIT_KEYS:
            self.assertNotIn(key, values)
        self.assertEqual(values["model_deterring_score_margin"], 0.10)
        self.assertEqual(values["model_deterring_busy_fallback_p_event_min"], 0.95)
        self.assertEqual(values["model_deterring_busy_fallback_deltaJ_per_cost_min"], 1.0e6)
        self.assertEqual(get_planner_profile_values(UNMAPPED), values)

    def test_consistent_profile_is_legacy_plus_mapped_values(self):
        base = get_planner_profile_values(BASE)
        consistent = get_planner_profile_values(CONSISTENT)
        self.assertTrue(CONSISTENT_THRESHOLD_MAPPING)
        for key, value in consistent.items():
            if key in CONSISTENT_THRESHOLD_MAPPING:
                self.assertEqual(value, CONSISTENT_THRESHOLD_MAPPING[key])
            else:
                self.assertEqual(value, base[key])
        self.assertIn("rationale", PLANNER_PROFILES[CONSISTENT])

    def test_profile_matches_recorded_provenance(self):
        payload = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        self.assertEqual(payload["dev_seeds"], list(range(200, 210)))
        recorded = payload["profile_values"]
        self.assertEqual(set(recorded), set(CONSISTENT_THRESHOLD_MAPPING))
        for key, value in recorded.items():
            self.assertAlmostEqual(CONSISTENT_THRESHOLD_MAPPING[key], value, places=12)


class ConsistentProfileSimulationTests(unittest.TestCase):
    """The simulator resolves the mapped profile in consistent mode and passes its values on."""

    def _captured_estimation_kwargs(self, estimator_mode, **extra):
        import os
        import sys
        from unittest import mock

        os.environ.setdefault("DETERRENT_TELEMETRY", "0")
        import DeterrentSystem as ds
        import planner_task_extraction as pte
        from experiments import run_habituation_stl_production_ladder as ladder

        argv = ["ladder", "--nx", "30", "--ny", "24", "--nrobots", "4", "--warmup-s", "0",
                "--mu-true", "1e-4", "--duration-s", "40"]
        with mock.patch.object(sys, "argv", argv):
            args = ladder.parse_args()
        params = ladder._common_params(args)
        params.update(ladder._system_params(args)["B1_greedy_fixedcue"])
        params.update(ladder._habituation_params(True, args))
        params.pop("habituation_condition", None)
        params.update(seed=200, estimator_mode=estimator_mode, **extra)
        captured = []
        original = pte.run_task_location_estimation

        def spy(**kwargs):
            captured.append(kwargs)
            return original(**kwargs)

        with mock.patch.object(pte, "run_task_location_estimation", spy):
            for _ in ds.run_simulation_frames_persistent(**params):
                pass
        self.assertTrue(captured)
        return captured[0]

    def test_consistent_mode_uses_mapped_values(self):
        kw = self._captured_estimation_kwargs("consistent")
        for key in ("min_hotspot_score", "patrol_cost_weight", "deterring_cost_multiplier"):
            if key in CONSISTENT_THRESHOLD_MAPPING:
                self.assertAlmostEqual(kw[key], CONSISTENT_THRESHOLD_MAPPING[key])
        if "model_deterring_risk_scale" in CONSISTENT_THRESHOLD_MAPPING:
            self.assertAlmostEqual(kw["model_deterring_risk_scale"],
                                   CONSISTENT_THRESHOLD_MAPPING["model_deterring_risk_scale"])

    def test_legacy_mode_and_opt_out_keep_legacy_values(self):
        for kw in (self._captured_estimation_kwargs("legacy"),
                   self._captured_estimation_kwargs("consistent", planner_profile=UNMAPPED)):
            self.assertEqual(kw["min_hotspot_score"], 1.0e-4)
            self.assertEqual(kw["patrol_cost_weight"], 1.0)
            self.assertEqual(kw["deterring_cost_multiplier"], 1.0)
            self.assertEqual(kw["model_deterring_risk_scale"], 1.0e-4)
            self.assertEqual(kw["model_deterring_risk_threshold"], 0.35)


if __name__ == "__main__":
    unittest.main()
