import unittest

from action_schema import (
    ActionSpec,
    make_detection_action,
    make_deterring_mode_action,
    make_patrol_action,
    task_action,
    task_action_kind,
    task_action_name,
    task_action_service_time_s,
)


_DETER_MODES = {
    "laser": {"beta": 0.45, "omega": 400.0, "sigma": 10.0},
    "formation": {"beta": 0.30, "omega": 800.0, "sigma": 18.0},
}


class ActionSchemaTests(unittest.TestCase):
    def test_make_detection_action(self):
        action = make_detection_action(7.5)
        self.assertEqual(
            action,
            ActionSpec(
                kind="deterring",
                name="direct_detection",
                params={},
                service_time_s=7.5,
            ),
        )

    def test_make_deterring_mode_action_uses_mode_params(self):
        action = make_deterring_mode_action("laser", _DETER_MODES, 12.0)
        self.assertEqual(action.kind, "deterring")
        self.assertEqual(action.name, "laser")
        self.assertEqual(action.params, _DETER_MODES["laser"])
        self.assertEqual(action.service_time_s, 12.0)

    def test_make_patrol_action_maps_origin_to_name(self):
        self.assertEqual(make_patrol_action("fallback").name, "fallback_patrol")
        self.assertEqual(make_patrol_action("hotspot").name, "hotspot_patrol")

    def test_task_action_reconstructs_direct_detection(self):
        task = {"type": "deterring", "origin": "detection", "mode": None}
        action = task_action(task, deterring_modes=_DETER_MODES, default_service_time_s=9.0)
        self.assertEqual(action.kind, "deterring")
        self.assertEqual(action.name, "direct_detection")
        self.assertEqual(action.service_time_s, 9.0)

    def test_task_action_reconstructs_model_deterring(self):
        task = {"type": "deterring", "origin": "model_hotspot", "mode": "laser"}
        action = task_action(task, deterring_modes=_DETER_MODES, default_service_time_s=11.0)
        self.assertEqual(action.kind, "deterring")
        self.assertEqual(action.name, "laser")
        self.assertEqual(action.params, _DETER_MODES["laser"])
        self.assertEqual(action.service_time_s, 11.0)

    def test_task_action_reconstructs_patrol(self):
        task = {"type": "patrolling", "origin": "fallback"}
        action = task_action(task, deterring_modes=_DETER_MODES, default_service_time_s=99.0)
        self.assertEqual(action.kind, "patrolling")
        self.assertEqual(action.name, "fallback_patrol")
        self.assertEqual(action.service_time_s, 0.0)

    def test_task_action_accessors_are_compatibility_stable(self):
        task = {"type": "deterring", "origin": "model_hotspot", "mode": "formation"}
        self.assertEqual(task_action_kind(task, _DETER_MODES, 13.0), "deterring")
        self.assertEqual(task_action_name(task, _DETER_MODES, 13.0), "formation")
        self.assertEqual(task_action_service_time_s(task, _DETER_MODES, 13.0), 13.0)


if __name__ == "__main__":
    unittest.main()
