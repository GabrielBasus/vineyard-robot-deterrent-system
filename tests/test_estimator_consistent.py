"""Tests for the truth-consistent planner estimator (estimator_mode="consistent")."""

import json
import math
import os
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

import DeterrentSystem as ds
from planner_task_estimation import cell_exposure_rate
from Robot import Robot
from SESTPP import ConsistentOnlineSESTPP, OnlineSESTPP, SESTPPForecastState, canonical_estimator_mode
from ZonePartitioner import point_in_polygon, point_to_poly_distance

REFERENCE_PATH = Path(__file__).resolve().parent / "data" / "estimator_legacy_reference.json"

# Truth parameters used for the oracle tests (planner params set equal).
ALPHA, SIGMA, OMEGA, BETA_DEFAULT = 0.3, 12.0, 600.0, 0.25
MODES = {
    "laser": {"beta": 0.45, "sigma": 10.0, "omega": 400.0},
    "formation": {"beta": 0.30, "sigma": 18.0, "omega": 800.0},
}


def _ladder_params(system, *, T_end, seed, **overrides):
    from experiments.run_plan_completion import _ladder_params as build

    params = build(system, True, 2e-5)
    params.update(T_end=float(T_end), seed=int(seed))
    params.update(overrides)
    return params


def _run(params):
    last = None
    for frame in ds.run_simulation_frames_persistent(**params):
        last = frame
    return (last or {}).get("metrics_compact") or (last or {}).get("metrics") or {}


def _value_map(xs, ys):
    xx, yy = np.meshgrid(xs, ys, indexing="xy")
    return 1.0 + 0.5 * np.sin(xx / 17.0) ** 2 + 0.3 * np.exp(-((yy - 30.0) ** 2) / 200.0)


def _truth_intensity(x, y, t, *, mu, w_node, parents, deterrences):
    """Truth intensity formula [mu w + sum alpha/omega e^{-dt/omega} N] exp(-S)."""
    exc = 0.0
    for (xi, yi, ti) in parents:
        dt = t - ti
        if dt < 0:
            continue
        exc += (ALPHA / OMEGA * math.exp(-dt / OMEGA)
                * math.exp(-0.5 * ((x - xi) ** 2 + (y - yi) ** 2) / SIGMA ** 2) / (2.0 * math.pi * SIGMA ** 2))
    s, _, _ = ds._truth_suppression_contributions(
        x, y, t, deterrences, beta_true=BETA_DEFAULT, sigma_true=SIGMA, omega_true=OMEGA,
    )
    return (mu * w_node + exc) * math.exp(-s), s


class EstimatorModeBasics(unittest.TestCase):
    def test_canonical_mode(self):
        self.assertEqual(canonical_estimator_mode(None), "legacy")
        self.assertEqual(canonical_estimator_mode(" Consistent "), "consistent")
        with self.assertRaises(ValueError):
            canonical_estimator_mode("bogus")
        self.assertEqual(OnlineSESTPP.estimator_mode, "legacy")
        with self.assertRaises(NotImplementedError):
            OnlineSESTPP(0, 10, 0, 10, 5, 5).forecast_state()

    def test_planner_mapping_mirrors_truth_mapping(self):
        from action_schema import make_detection_action, make_deterring_mode_action

        for mode_dep in (True, False):
            dd = make_detection_action(service_time_s=5.0)
            truth = ds._resolve_truth_deterrence_event_params(
                dd, use_mode_dependent_truth_suppression=mode_dep,
                beta_true=BETA_DEFAULT, sigma_true=SIGMA, omega_true=OMEGA)
            planner = ds._resolve_planner_deterrence_event_params(
                "direct_detection", dict(dd.params), planner_deterring_modes=None,
                use_mode_dependent_truth_suppression=mode_dep,
                planner_beta=BETA_DEFAULT, planner_sigma=SIGMA, planner_omega=OMEGA)
            self.assertEqual(truth, planner)
            for mode in MODES:
                act = make_deterring_mode_action(mode, MODES, service_time_s=5.0)
                truth = ds._resolve_truth_deterrence_event_params(
                    act, use_mode_dependent_truth_suppression=mode_dep,
                    beta_true=BETA_DEFAULT, sigma_true=SIGMA, omega_true=OMEGA)
                for pmodes in (None, MODES):
                    planner = ds._resolve_planner_deterrence_event_params(
                        mode, dict(act.params), planner_deterring_modes=pmodes,
                        use_mode_dependent_truth_suppression=mode_dep,
                        planner_beta=BETA_DEFAULT, planner_sigma=SIGMA, planner_omega=OMEGA)
                    self.assertEqual(truth, planner)


class ConsistentIntensityOracle(unittest.TestCase):
    """Planner params == truth params and every event observed => identical intensity."""

    def _build(self):
        m = ConsistentOnlineSESTPP(0.0, 120.0, 0.0, 80.0, 61, 41,
                                   alpha=ALPHA, sigma=SIGMA, omega=OMEGA, mu_init=3e-6)
        m.set_value_map(_value_map(m.xs, m.ys))
        m.set_background_rate(3e-6, freeze=True)
        return m

    def _scenario(self, m):
        rng = np.random.default_rng(5)
        parents, deterrences = [], []
        t = 0.0
        modes = [("direct_detection", BETA_DEFAULT, SIGMA, OMEGA)] + [
            (k, v["beta"], v["sigma"], v["omega"]) for k, v in MODES.items()
        ]
        for step in range(60):
            t += float(rng.uniform(1.0, 40.0))
            m.advance_to(t)
            x, y = float(rng.uniform(0, 120)), float(rng.uniform(0, 80))
            if step % 3 == 0:
                m.add_local_event(x, y, t=t)          # own detection
            else:
                m.add_cross_event(x, y, weight=1.0, t=t)  # relayed detection
            parents.append((x, y, t))
            if step % 4 == 1:
                mode, beta, sig, om = modes[step % len(modes)]
                eta = float(rng.uniform(0.3, 1.0))
                xz, yz = float(rng.uniform(0, 120)), float(rng.uniform(0, 80))
                m.add_intervention_event(xz, yz, weight=eta * beta, sigma=sig, omega_inhib=om,
                                         mode=mode, action_id=step, t=t)
                deterrences.append({"x": xz, "y": yz, "t": t, "beta": beta, "sigma": sig,
                                    "omega": om, "eta": eta, "mode": mode})
        # One late-stamped (t < t_now) event of each kind.
        t_late = t - 7.5
        m.advance_to(t + 3.0)
        m.add_cross_event(60.0, 40.0, weight=1.0, t=t_late)
        parents.append((60.0, 40.0, t_late))
        m.add_intervention_event(50.0, 35.0, weight=0.2, sigma=15.0, omega_inhib=500.0,
                                 mode="laser", action_id=999, t=t_late)
        deterrences.append({"x": 50.0, "y": 35.0, "t": t_late, "beta": 0.2, "sigma": 15.0,
                            "omega": 500.0, "eta": 1.0, "mode": "laser"})
        m.advance_to(t + 45.0)
        return parents, deterrences

    def test_grid_intensity_equals_truth_formula(self):
        m = self._build()
        parents, deterrences = self._scenario(m)
        rng = np.random.default_rng(11)
        checked = 0
        for _ in range(200):
            iy, ix = int(rng.integers(0, m.ny)), int(rng.integers(0, m.nx))
            x, y = float(m.xs[ix]), float(m.ys[iy])
            lam_truth, s_truth = _truth_intensity(
                x, y, m.t_now, mu=3e-6, w_node=float(m.value_map[iy, ix]),
                parents=parents, deterrences=deterrences)
            self.assertLessEqual(abs(m.lam[iy, ix] - lam_truth), 1e-9 * abs(lam_truth))
            # Suppression exponent identical to the truth's S.
            self.assertLessEqual(abs(m.suppression_S[iy, ix] - s_truth), 1e-9 * max(abs(s_truth), 1e-300))
            # Off-grid evaluator agrees too.
            self.assertLessEqual(abs(m.intensity_at(x, y) - lam_truth), 1e-9 * abs(lam_truth))
            checked += 1
        self.assertEqual(checked, 200)

    def test_backward_compatible_decomposition_and_forecast_state(self):
        m = self._build()
        self._scenario(m)
        mult = m.time_multiplier(m.t_now)
        self.assertEqual(mult, 1.0)
        np.testing.assert_allclose(m.mu * mult + m.trigger_mass - m.inhib_mass, m.lam, rtol=1e-12, atol=0.0)
        fs = m.forecast_state()
        self.assertIsInstance(fs, SESTPPForecastState)
        np.testing.assert_allclose(
            (fs.background_density + fs.excitation_density) * np.exp(-fs.suppression_S), fs.intensity,
            rtol=1e-12, atol=0.0)
        S_terms = np.zeros_like(fs.suppression_S)
        xx, yy = np.meshgrid(fs.xs, fs.ys, indexing="xy")
        for term in fs.suppression_terms:
            S_terms += term.value(xx, yy, fs.t)
        np.testing.assert_allclose(S_terms, fs.suppression_S, rtol=1e-9, atol=1e-12)
        self.assertEqual(fs.dA, m.dx * m.dy)
        self.assertEqual(fs.excitation_omega, OMEGA)
        cp = fs.copy()
        cp.excitation_density[:] = 0.0
        self.assertGreater(float(fs.excitation_density.sum()), 0.0)
        # Consumers integrate lam as a density.
        poly = [(0.0, 0.0), (60.0, 0.0), (60.0, 40.0), (0.0, 40.0)]
        e0 = cell_exposure_rate(m, poly)
        inside = np.array([[point_in_polygon(float(x), float(y), poly) for x in m.xs] for y in m.ys])
        self.assertAlmostEqual(e0, float(np.sum(m.lam[inside]) * m.dA), delta=1e-12 * max(e0, 1e-300))

    def test_background_estimator_is_gamma_poisson_posterior(self):
        m = ConsistentOnlineSESTPP(0.0, 100.0, 0.0, 100.0, 21, 21, alpha=0.0, sigma=SIGMA,
                                   omega=OMEGA, mu_init=1e-5, mu_prior_count=2.0, detection_prob=0.5)
        mask = np.zeros((21, 21), bool)
        mask[5:15, 5:15] = True
        rng = np.random.default_rng(3)
        mu_true, n_det = 4e-5, 0
        for _ in range(2000):
            m.accumulate_detection_exposure(mask, 1.0)
            k = rng.poisson(0.5 * mu_true * mask.sum() * m.dA)
            for _ in range(int(k)):
                m.add_local_event(50.0, 50.0, t=m.t_now)
                n_det += 1
            m.advance_time(1.0)
        exposure = 0.5 * 2000.0 * mask.sum() * m.dA
        expected = (2.0 + n_det) / (2.0 / 1e-5 + exposure)
        self.assertAlmostEqual(m.mu_rate, expected, delta=1e-9 * expected)
        self.assertLess(abs(m.mu_rate - mu_true) / mu_true, 0.1)
        np.testing.assert_allclose(m.mu, m.mu_rate * m.value_map)


class ConsistentRobotWiring(unittest.TestCase):
    def test_robot_routes_to_consistent_model(self):
        m = ConsistentOnlineSESTPP(0.0, 100.0, 0.0, 100.0, 21, 21, alpha=ALPHA, sigma=SIGMA,
                                   omega=OMEGA, mu_init=1e-5)
        zone = [(0.0, 0.0), (50.0, 0.0), (50.0, 100.0), (0.0, 100.0)]
        rob = Robot("r0", m, zone, ["r1"])
        self.assertEqual(rob.estimator_mode, "consistent")
        self.assertEqual(rob.ingest_detection(20.0, 20.0, 5.0), [])
        self.assertEqual(m.local_detection_count, 1)
        rob.ingest_boundary_event(60.0, 20.0, 6.0, weight=1.0)
        self.assertEqual(len(m.excitation_events), 2)
        rob.ingest_intervention_event(20.0, 20.0, 7.0, weight=0.3, sigma=10.0, omega_inhib=400.0,
                                      mode="laser", action_id=4)
        self.assertEqual(m.intervention_history[-1].action_id, 4)
        self.assertEqual(m.intervention_history[-1].amplitude, 0.3)
        self.assertEqual(m.intervention_history[-1].tau, 7.0)


class LegacyUnchanged(unittest.TestCase):
    def test_legacy_metrics_match_reference(self):
        reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
        for system, ref_metrics in reference.items():
            metrics = _run(_ladder_params(system, T_end=240.0, seed=7))
            mismatches = {
                key: (val, metrics.get(key))
                for key, val in ref_metrics.items()
                if not (isinstance(metrics.get(key), (int, float)) and float(metrics.get(key)) == float(val))
            }
            self.assertEqual(mismatches, {}, msg=f"{system} legacy metrics changed")


class ConsistentRelay(unittest.TestCase):
    def test_every_intervention_reaches_every_affected_robot(self):
        captured = []
        original = ds.EventBus

        class CapturingBus(original):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured.append(self)

        ds.EventBus = CapturingBus
        try:
            metrics = _run(_ladder_params("B4_res_stl_full_multicue", T_end=300.0, seed=11,
                                          estimator_mode="consistent"))
        finally:
            ds.EventBus = original
        self.assertTrue(math.isfinite(float(metrics["value_weighted_exposure"])))
        bus = captured[-1]
        self.assertEqual(bus.estimator_mode, "consistent")
        log = bus.consistent_intervention_log
        self.assertGreater(len(log), 0)
        self.assertEqual(bus.intervention_msg_dropped_debounce, 0)
        self.assertEqual(bus.intervention_msg_dropped_low_weight, 0)
        for entry in log:
            x, y, sig = entry["x"], entry["y"], entry["sigma"]
            for rid, robot in bus.robots.items():
                polys = entry["regions"][str(rid)]
                affected = any(
                    point_in_polygon(x, y, [tuple(p) for p in poly])
                    or point_to_poly_distance((x, y), [tuple(p) for p in poly]) <= 3.0 * sig
                    for poly in polys if poly
                )
                received = [
                    term for term in robot.m.intervention_history
                    if term.action_id == entry["action_id"] and term.tau == entry["t"]
                ]
                if affected or rid == entry["source_id"]:
                    self.assertEqual(len(received), 1, msg=f"{rid} missed {entry['action_id']}")
                    self.assertEqual(received[0].amplitude, entry["amplitude"])
                    self.assertEqual(received[0].sigma, sig)
                    self.assertEqual(received[0].omega, entry["omega"])
                else:
                    self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
