"""Decisions 17-18: per-robot information sets, neighbor delay and drop."""

import os
import unittest

import numpy as np

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

import DeterrentSystem as ds
from habituation_stl.habituation import HabituationField
from random_streams import CoupledRandomStreams, RELAY_KIND_INTERVENTION
from robot_information import PerRobotHabituation, RobotHabituationState


def _b5c_params(T_end, seed=200, mu=1e-4, **over):
    from experiments.run_plan_completion import build_params

    p = build_params("B5_c", True, mu, T_end)
    p["seed"] = int(seed)
    p.update(over)
    return p


class _FakeRobot:
    def __init__(self):
        self.boundary = []
        self.interventions = []

    def ingest_boundary_event(self, **kw):
        self.boundary.append(kw)

    def ingest_intervention_event(self, *a, **kw):
        self.interventions.append((a, kw))


def _mult(h, c, m):
    h.apply(c, m)


class RelayDelayDrop(unittest.TestCase):
    def _bus(self, delay=0.0, drop=0.0):
        robots = {"r0": _FakeRobot(), "r1": _FakeRobot(), "r2": _FakeRobot()}
        streams = CoupledRandomStreams(5) if drop > 0 else None
        return robots, ds.EventBus(robots, neighbor_delay_s=delay, neighbor_drop_prob=drop, relay_streams=streams)

    def test_default_is_immediate(self):
        robots, bus = self._bus()
        bus.send_boundary_events([{"target_robot": "r1", "x": 1.0, "y": 2.0, "t": 3.0}], source_id="r0")
        self.assertEqual(len(robots["r1"].boundary), 1)
        self.assertFalse(robots["r1"].boundary[0]["delayed"])
        self.assertEqual(bus.deliver_due(1e9), 0)

    def test_delay_delivers_at_event_time_plus_d(self):
        robots, bus = self._bus(delay=120.0)
        bus.send_boundary_events([{"target_robot": "r1", "x": 1.0, "y": 2.0, "t": 10.0}], source_id="r0")
        self.assertEqual(robots["r1"].boundary, [])
        self.assertEqual(bus.deliver_due(129.0), 0)
        self.assertEqual(bus.deliver_due(130.0), 1)
        self.assertTrue(robots["r1"].boundary[0]["delayed"])
        self.assertEqual(robots["r1"].boundary[0]["t"], 10.0)

    def test_drop_is_keyed_by_message_and_recipient(self):
        _, bus = self._bus(drop=0.3)
        u = [bus.relay_streams.relay_uniform(RELAY_KIND_INTERVENTION, (k,), "r1") for k in range(4000)]
        self.assertAlmostEqual(float(np.mean(np.asarray(u) < 0.3)), 0.3, delta=0.03)
        # same message id and recipient -> same draw (habituation and SESTPP parts share a fate)
        self.assertEqual(bus.relay_streams.relay_uniform(RELAY_KIND_INTERVENTION, (7,), "r1"),
                         CoupledRandomStreams(5).relay_uniform(RELAY_KIND_INTERVENTION, (7,), "r1"))

    def test_habituation_relay_complete_and_dropped_together(self):
        robots, bus = self._bus(drop=0.5)
        got = []
        bus.habituation_apply_fn = lambda rid, t, c, m: got.append((rid, t, c, m))
        for aid in range(200):
            bus.relay_habituation(t=float(aid), cell=1, mode=2, action_id=aid, source_id="r0")
        recipients = {g[0] for g in got}
        self.assertEqual(recipients, {"r1", "r2"})          # every other robot, never the source
        self.assertEqual(bus.relay_sent_by_kind["habituation"], 400)
        self.assertEqual(bus.relay_dropped_by_kind["habituation"] + len(got), 400)
        for (rid, t, _c, _m) in got:
            u = bus.relay_streams.relay_uniform(RELAY_KIND_INTERVENTION, (int(t),), rid)
            self.assertGreaterEqual(u, 0.5)


class ChronologicalReconstruction(unittest.TestCase):
    def _template(self):
        return HabituationField(n_cells=3, n_modes=2, T_rec=600.0, kappa=0.5, gamma=0.2, eta0=1.0)

    def test_late_messages_equal_on_time_history(self):
        dt, D = 1.0, 40.0
        events = [(5.0, 0, 1), (12.0, 1, 0), (30.0, 0, 1), (31.0, 2, 1), (70.0, 0, 0), (71.0, 0, 1)]
        ref = self._template()
        late = RobotHabituationState(self._template(), update_fn=_mult, max_lag_s=D + dt)
        pending = []
        t = 0.0
        while t <= 150.0:
            ref.recover(dt)
            late.recover(dt, t)
            for (te, c, m) in events:
                if te == t:
                    ref.apply(c, m)
                    if c == 0:   # "own" completions applied immediately
                        late.apply(te, c, m)
                    else:        # relayed: arrives D later
                        pending.append((te + D, te, c, m))
            for item in [p for p in pending if p[0] <= t]:
                late.apply(item[1], item[2], item[3])
                pending.remove(item)
            t += dt
        np.testing.assert_allclose(late.field.eta, ref.eta, rtol=0, atol=1e-12)
        self.assertGreater(late.late_applied_total, 0)

    def test_instant_equals_shared_bitwise(self):
        tmpl = self._template()
        fleet = PerRobotHabituation(["a", "b"], tmpl, update_fn=_mult, max_lag_s=0.0)
        shared = tmpl.copy()
        for k in range(50):
            shared.recover(1.0)
            fleet.recover(1.0, float(k))
            if k % 7 == 0:
                shared.apply(k % 3, k % 2)
                fleet.apply("a", float(k), k % 3, k % 2)
                fleet.apply("b", float(k), k % 3, k % 2)
        self.assertTrue(np.array_equal(fleet.field("a").eta, shared.eta))
        self.assertTrue(np.array_equal(fleet.field("b").eta, shared.eta))


class PerRobotInSimulator(unittest.TestCase):
    def _trace(self, **over):
        gen = ds.run_simulation_frames_persistent(**_b5c_params(300.0, **over))
        frames = []
        last = None
        for fr in gen:
            L = gen.gi_frame.f_locals
            byr = L.get("planner_hab_by_robot")
            frames.append((np.array(L["planner_hab"].eta, copy=True),
                           None if byr is None else byr.snapshot()))
            last = fr
        return frames, last["metrics_compact"], gen

    def test_instant_complete_relay_per_robot_equals_shared(self):
        shared_frames, m_shared, _ = self._trace()
        pr_frames, m_pr, _ = self._trace(planner_hab_mode="per_robot")
        n_apps = int(m_pr["eta_at_application_all_count"])
        self.assertGreater(n_apps, 0)
        for (eta_s, _), (eta_p, byr) in zip(shared_frames, pr_frames):
            self.assertTrue(np.array_equal(eta_s, eta_p))
            for rid, eta_r in byr.items():
                self.assertTrue(np.array_equal(eta_r, eta_p), msg=rid)
        for key in ("value_weighted_exposure", "reactive_completed_total", "predictive_completed_total",
                    "eta_planner_at_application_all_mean"):
            self.assertEqual(m_shared[key], m_pr[key], msg=key)

    def test_delay_and_drop_run_and_diverge(self):
        frames, m, _ = self._trace(planner_hab_mode="per_robot", neighbor_delay_s=60.0, neighbor_drop_prob=0.3)
        self.assertGreater(m["relay_habituation_sent_total"], 0)
        self.assertGreater(m["relay_habituation_dropped_total"], 0)
        self.assertEqual(m["relay_habituation_delayed_total"],
                         m["relay_habituation_sent_total"] - m["relay_habituation_dropped_total"])
        diverged = any(not np.array_equal(eta_r, eta_s) for eta_s, byr in frames for eta_r in byr.values())
        self.assertTrue(diverged)


if __name__ == "__main__":
    unittest.main()
