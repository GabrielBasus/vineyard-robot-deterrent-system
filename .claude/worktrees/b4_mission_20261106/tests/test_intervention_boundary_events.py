import unittest

from DeterrentSystem import EventBus as ProductionEventBus
from labs.DeterrentSystem_assignment_lab import EventBus as LabEventBus
from DeterrentSystem_simple_tasks import EventBus as SimpleEventBus
from Robot import Robot


EVENT_BUS_CLASSES = (
    ProductionEventBus,
    SimpleEventBus,
    LabEventBus,
)


class CaptureModel:
    def __init__(self, *, sigma=99.0, omega_inhib=999.0):
        self.t_now = 0.0
        self.sigma = float(sigma)
        self.omega_inhib = float(omega_inhib)
        self.intervention_calls = []

    def advance_time(self, dt):
        if dt > 0.0:
            self.t_now += float(dt)

    def add_intervention_event(self, x, y, weight=1.0, sigma=None, omega_inhib=None, *, mode=None):
        self.intervention_calls.append({
            "x": float(x),
            "y": float(y),
            "weight": float(weight),
            "sigma": None if sigma is None else float(sigma),
            "omega_inhib": None if omega_inhib is None else float(omega_inhib),
            "mode": mode,
        })


class InterventionBoundaryRelayTests(unittest.TestCase):
    def setUp(self):
        self.zone = [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
        ]

    def _build_robot(self, robot_id, model, neighbors):
        return Robot(robot_id, model, self.zone, neighbors, border_radius_m=1.0)

    def test_completed_laser_boundary_relay_preserves_local_sigma_and_omega(self):
        x = 9.5
        y = 5.0
        t = 123.0
        beta = 2.5
        sigma = 7.0
        omega_inhib = 180.0
        action_id = 42

        for bus_cls in EVENT_BUS_CLASSES:
            with self.subTest(event_bus=bus_cls.__module__):
                source_model = CaptureModel(sigma=1.0, omega_inhib=10.0)
                target_model = CaptureModel(sigma=99.0, omega_inhib=999.0)
                source = self._build_robot("r1", source_model, ["r2"])
                target = self._build_robot("r2", target_model, [])
                bus = bus_cls({"r1": source, "r2": target})

                source.ingest_intervention_event(
                    x,
                    y,
                    t,
                    weight=beta,
                    sigma=sigma,
                    omega_inhib=omega_inhib,
                    mode="laser",
                    beta=beta,
                    action_id=action_id,
                )
                events = source.intervention_boundary_events(
                    x,
                    y,
                    t,
                    weight=beta,
                    mode="laser",
                    sigma=sigma,
                    omega_inhib=omega_inhib,
                    beta=beta,
                    action_id=action_id,
                )

                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["mode"], "laser")
                self.assertAlmostEqual(events[0]["weight"], beta)
                self.assertAlmostEqual(events[0]["beta"], beta)
                self.assertAlmostEqual(events[0]["sigma"], sigma)
                self.assertAlmostEqual(events[0]["omega_inhib"], omega_inhib)
                self.assertEqual(events[0]["action_id"], action_id)

                bus.send_intervention_events(events, source_id="r1")

                self.assertEqual(len(source_model.intervention_calls), 1)
                self.assertEqual(len(target_model.intervention_calls), 1)
                local = source_model.intervention_calls[-1]
                remote = target_model.intervention_calls[-1]
                self.assertEqual(remote["mode"], local["mode"])
                self.assertAlmostEqual(remote["weight"], local["weight"])
                self.assertAlmostEqual(remote["sigma"], local["sigma"])
                self.assertAlmostEqual(remote["omega_inhib"], local["omega_inhib"])
                self.assertAlmostEqual(remote["sigma"], sigma)
                self.assertAlmostEqual(remote["omega_inhib"], omega_inhib)
                self.assertEqual(bus.intervention_msg_count, 1)
                self.assertEqual(bus.intervention_msg_dropped_debounce, 0)

    def test_intervention_debounce_keeps_distinct_modes_and_actions(self):
        for bus_cls in EVENT_BUS_CLASSES:
            with self.subTest(event_bus=f"{bus_cls.__module__}:modes"):
                target_model = CaptureModel()
                source = self._build_robot("r1", CaptureModel(), [])
                target = self._build_robot("r2", target_model, [])
                bus = bus_cls({"r1": source, "r2": target})
                events = [
                    {
                        "target_robot": "r2",
                        "x": 10.0,
                        "y": 10.0,
                        "t": 100.0,
                        "weight": 1.0,
                        "mode": "laser",
                        "sigma": 4.0,
                        "omega_inhib": 30.0,
                        "action_id": 10,
                    },
                    {
                        "target_robot": "r2",
                        "x": 10.2,
                        "y": 10.2,
                        "t": 101.0,
                        "weight": 1.0,
                        "mode": "horn",
                        "sigma": 6.0,
                        "omega_inhib": 45.0,
                        "action_id": 11,
                    },
                    {
                        "target_robot": "r2",
                        "x": 10.1,
                        "y": 10.1,
                        "t": 102.0,
                        "weight": 1.0,
                        "mode": "laser",
                        "sigma": 4.0,
                        "omega_inhib": 30.0,
                        "action_id": 10,
                    },
                ]

                bus.send_intervention_events(
                    events,
                    source_id="r1",
                    min_interval_s=10.0,
                    spatial_quant_m=5.0,
                )

                self.assertEqual(len(target_model.intervention_calls), 2)
                self.assertEqual(
                    [call["mode"] for call in target_model.intervention_calls],
                    ["laser", "horn"],
                )
                self.assertEqual(bus.intervention_msg_count, 2)
                self.assertEqual(bus.intervention_msg_dropped_debounce, 1)

            with self.subTest(event_bus=f"{bus_cls.__module__}:actions"):
                target_model = CaptureModel()
                source = self._build_robot("r1", CaptureModel(), [])
                target = self._build_robot("r2", target_model, [])
                bus = bus_cls({"r1": source, "r2": target})
                events = [
                    {
                        "target_robot": "r2",
                        "x": 12.0,
                        "y": 12.0,
                        "t": 200.0,
                        "weight": 1.0,
                        "mode": "laser",
                        "sigma": 5.0,
                        "omega_inhib": 35.0,
                        "action_id": 20,
                    },
                    {
                        "target_robot": "r2",
                        "x": 12.2,
                        "y": 12.2,
                        "t": 201.0,
                        "weight": 1.0,
                        "mode": "laser",
                        "sigma": 5.0,
                        "omega_inhib": 35.0,
                        "action_id": 21,
                    },
                ]

                bus.send_intervention_events(
                    events,
                    source_id="r1",
                    min_interval_s=10.0,
                    spatial_quant_m=5.0,
                )

                self.assertEqual(len(target_model.intervention_calls), 2)
                self.assertEqual(bus.intervention_msg_count, 2)
                self.assertEqual(bus.intervention_msg_dropped_debounce, 0)


if __name__ == "__main__":
    unittest.main()
