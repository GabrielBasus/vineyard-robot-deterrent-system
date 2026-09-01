import math
import statistics as stats
import unittest

from experiments.run_habituation_stl_production_ladder import METRIC_FIELDS, _ci95, _paired_deltas


class HabituationStlLadderReportingTests(unittest.TestCase):
    def test_paired_deltas_are_system_minus_reference_by_seed(self):
        rows = [
            {
                "baseline": "system",
                "habituation_condition": "hab_on",
                "seed": 1,
                "value_weighted_exposure": 90.0,
            },
            {
                "baseline": "reference",
                "habituation_condition": "hab_on",
                "seed": 1,
                "value_weighted_exposure": 100.0,
            },
            {
                "baseline": "system",
                "habituation_condition": "hab_on",
                "seed": 2,
                "value_weighted_exposure": 120.0,
            },
            {
                "baseline": "reference",
                "habituation_condition": "hab_on",
                "seed": 2,
                "value_weighted_exposure": 110.0,
            },
        ]

        self.assertEqual(
            _paired_deltas(
                rows,
                "system",
                "reference",
                "hab_on",
                "value_weighted_exposure",
            ),
            [-10.0, 10.0],
        )

    def test_ci95_uses_student_t_interval_for_ten_paired_values(self):
        values = [float(v) for v in range(1, 11)]

        lo, hi = _ci95(values)

        mean = float(stats.mean(values))
        expected_half_width = 2.262 * float(stats.stdev(values)) / math.sqrt(len(values))
        self.assertAlmostEqual(lo, mean - expected_half_width)
        self.assertAlmostEqual(hi, mean + expected_half_width)

    def test_ladder_exports_guardrail_and_mechanism_fields(self):
        required = {
            "mean_response_time_s",
            "predictive_completion_ratio",
            "predictive_expired_fraction",
            "predictive_deadline_feasible_fraction",
            "travel_distance_total",
            "tasks_per_unit_distance",
            "stl_robustness_cov",
            "habituation_eta_at_apply_mean",
            "habituation_variety_index",
            "truth_suppression_effect_sum",
        }

        self.assertTrue(required.issubset(set(METRIC_FIELDS)))


if __name__ == "__main__":
    unittest.main()
