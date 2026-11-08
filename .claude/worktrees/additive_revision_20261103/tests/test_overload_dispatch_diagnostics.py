"""Tests for the overload dispatch diagnostic knobs in _select_dispatch_policy_task."""
import unittest

import numpy as np

import DeterrentSystem as ds


def _reactive(task_id, *, time, eta_s, merged_detection_count=1):
    return {
        "id": task_id,
        "type": "deterring",
        "origin": "detection",
        "score": 1.0,
        "utility": 1.0,
        "time": float(time),
        "eta_s": float(eta_s),
        "merged_detection_count": int(merged_detection_count),
        "state": "active",
    }


def _select(tasks, now_t, **kwargs):
    return ds._select_dispatch_policy_task(
        tasks,
        dispatch_policy="res",
        predictive_share=1.0,
        reservation_fraction=0.25,
        reactive_override_slack_s=90.0,
        reservation_softening_alpha=1.0,
        predictive_selection_policy="utility",
        now_t=float(now_t),
        eta_seconds_fn=lambda task: float(task["eta_s"]),
        rng=np.random.default_rng(0),
        **kwargs,
    )


class OverloadDispatchDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        # At t=100 both tasks are urgent (slack <= 0).
        # far_old: slack = 90 - 100 - 60 = -70 (most overdue)
        # near_new: slack = 90 - 50 - 45 = -5 (nearest)
        self.far_old = _reactive("far_old", time=0.0, eta_s=60.0)
        self.near_new = _reactive("near_new", time=50.0, eta_s=45.0)

    def test_default_override_picks_most_overdue(self):
        selected, urgent = _select([self.near_new, self.far_old], 100.0)
        self.assertTrue(urgent)
        self.assertEqual(selected["id"], "far_old")

    def test_explicit_most_overdue_matches_default(self):
        selected, urgent = _select(
            [self.near_new, self.far_old], 100.0, reactive_override_target="most_overdue"
        )
        self.assertTrue(urgent)
        self.assertEqual(selected["id"], "far_old")

    def test_nearest_overdue_picks_smallest_eta(self):
        selected, urgent = _select(
            [self.far_old, self.near_new], 100.0, reactive_override_target="nearest_overdue"
        )
        self.assertTrue(urgent)
        self.assertEqual(selected["id"], "near_new")

    def test_nearest_overdue_tie_breaks_on_support_then_age(self):
        a = _reactive("a", time=10.0, eta_s=30.0, merged_detection_count=1)
        b = _reactive("b", time=20.0, eta_s=30.0, merged_detection_count=3)
        c = _reactive("c", time=5.0, eta_s=30.0, merged_detection_count=3)
        selected, _urgent = _select([a, b, c], 100.0, reactive_override_target="nearest_overdue")
        self.assertEqual(selected["id"], "c")

    def test_support_first_vs_eta_first_non_urgent(self):
        # Non-urgent at t=10: slack = 90 - age - eta > 0 for both.
        supported_far = _reactive("supported_far", time=5.0, eta_s=40.0, merged_detection_count=3)
        single_near = _reactive("single_near", time=5.0, eta_s=5.0, merged_detection_count=1)
        selected, urgent = _select([single_near, supported_far], 10.0)
        self.assertFalse(urgent)
        self.assertEqual(selected["id"], "supported_far")
        selected, urgent = _select(
            [single_near, supported_far], 10.0, reactive_priority_key="eta_first"
        )
        self.assertFalse(urgent)
        self.assertEqual(selected["id"], "single_near")

    def test_invalid_modes_raise(self):
        with self.assertRaises(ValueError):
            _select([self.far_old], 100.0, reactive_override_target="bogus")
        with self.assertRaises(ValueError):
            _select([self.far_old], 100.0, reactive_priority_key="bogus")


if __name__ == "__main__":
    unittest.main()
