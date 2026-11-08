import unittest

from action_schema import task_action
from system_stage_helpers import build_motion_command


class MotionCommandActionTests(unittest.TestCase):
    def test_motion_command_exposes_action_metadata(self):
        task = {
            "id": 17,
            "type": "deterring",
            "origin": "model_hotspot",
            "mode": "laser",
        }
        task["action"] = task_action(
            task,
            deterring_modes={"laser": {"beta": 0.45, "omega": 400.0, "sigma": 10.0}},
            default_service_time_s=6.0,
        )
        command = build_motion_command(
            robot_id="r1",
            pose=(1.0, 2.0),
            goal=(3.0, 4.0),
            effective_goal=(3.0, 4.0),
            command_type="move",
            source="policy_task",
            assigned_task=task,
        ).to_public_dict()
        self.assertEqual(command["assigned_task_stream"], "predictive")
        self.assertEqual(command["assigned_action_kind"], "deterring")
        self.assertEqual(command["assigned_action_name"], "laser")
        self.assertEqual(command["assigned_action_service_time_s"], 6.0)


if __name__ == "__main__":
    unittest.main()
