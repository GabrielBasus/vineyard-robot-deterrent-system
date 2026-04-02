import math
import unittest

import numpy as np

from SESTPP import OnlineSESTPP


class OnlineSESTPPInterventionModeTests(unittest.TestCase):
    def _build_model(self, **overrides):
        params = {
            "x_min": 0.0,
            "x_max": 40.0,
            "y_min": 0.0,
            "y_max": 40.0,
            "nx": 41,
            "ny": 41,
            "sigma": 2.0,
            "omega": 120.0,
            "omega_inhib": 60.0,
            "alpha_in": 0.5,
            "alpha_cross": 0.2,
            "alpha_inhib": 1.0,
            "mu_base": 0.0,
            "bg_ema": 1.0e-6,
        }
        params.update(overrides)
        return OnlineSESTPP(**params)

    def test_mode_channels_decay_with_their_own_omega(self):
        model = self._build_model()
        model.add_intervention_event(20.0, 20.0, sigma=2.0, omega_inhib=10.0, mode="fast")
        model.add_intervention_event(20.0, 20.0, sigma=2.0, omega_inhib=100.0, mode="slow")

        fast0 = float(np.sum(model.inhib_channels["fast"]))
        slow0 = float(np.sum(model.inhib_channels["slow"]))
        model.advance_time(10.0)
        fast1 = float(np.sum(model.inhib_channels["fast"]))
        slow1 = float(np.sum(model.inhib_channels["slow"]))

        self.assertAlmostEqual(fast0, 1.0, places=12)
        self.assertAlmostEqual(slow0, 1.0, places=12)
        self.assertAlmostEqual(fast1, math.exp(-1.0), places=12)
        self.assertAlmostEqual(slow1, math.exp(-0.1), places=12)
        self.assertLess(fast1, slow1)
        np.testing.assert_allclose(
            model.inhib_mass,
            model.inhib_channels["fast"] + model.inhib_channels["slow"],
        )

    def test_sigma_changes_spatial_footprint(self):
        model = self._build_model()
        model.add_intervention_event(20.0, 20.0, sigma=1.5, omega_inhib=60.0, mode="narrow")
        model.add_intervention_event(20.0, 20.0, sigma=6.0, omega_inhib=60.0, mode="wide")

        iy, ix = model.world_to_idx(20.0, 20.0)
        yy, xx = np.indices(model.inhib_mass.shape, dtype=float)
        dist2 = ((xx - ix) * model.dx) ** 2 + ((yy - iy) * model.dy) ** 2

        narrow = model.inhib_channels["narrow"]
        wide = model.inhib_channels["wide"]
        narrow_second_moment = float(np.sum(narrow * dist2))
        wide_second_moment = float(np.sum(wide * dist2))

        self.assertGreater(float(narrow[iy, ix]), float(wide[iy, ix]))
        self.assertGreater(wide_second_moment, narrow_second_moment)

    def test_lambda_is_clipped_nonnegative_under_strong_inhibition(self):
        model = self._build_model(mu_base=0.02, alpha_in=0.25, alpha_inhib=4.0)
        model.add_local_event(10.0, 10.0)
        model.add_intervention_event(10.0, 10.0, weight=100.0, sigma=3.0, omega_inhib=30.0, mode="strong")

        self.assertTrue(np.all(model.lam >= 0.0))
        for _ in range(5):
            model.advance_time(10.0)
            self.assertTrue(np.all(model.lam >= 0.0))

    def test_legacy_callers_use_default_channel(self):
        model = self._build_model()
        model.add_intervention_event(15.0, 15.0, weight=2.0, sigma=3.0, omega_inhib=45.0)

        self.assertIn(model.default_intervention_mode, model.inhib_channels)
        np.testing.assert_allclose(
            model.inhib_mass,
            model.inhib_channels[model.default_intervention_mode],
        )
        self.assertAlmostEqual(model.inhib_channel_omegas[model.default_intervention_mode], 45.0)


if __name__ == "__main__":
    unittest.main()
