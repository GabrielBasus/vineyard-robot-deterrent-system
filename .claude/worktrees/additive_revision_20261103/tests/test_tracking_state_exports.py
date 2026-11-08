import unittest

import DeterrentSystem as ds


class TrackingStateExportTests(unittest.TestCase):
    def test_tracking_state_is_exposed_when_enabled(self):
        frames = ds.run_simulation_frames_persistent(
            T_end=2.0,
            dt=1.0,
            fps=1,
            Nrobots=2,
            NX=12,
            NY=10,
            warmup_s=0.0,
            emit_tracking_state=True,
            tracking_include_arrays=False,
            tracking_preview_limit=10,
            tracking_capture_frame_locals=False,
            telemetry_clear_on_start=False,
            telemetry_prompt_save=False,
            report_metrics_end=False,
        )

        snapshot = next(frames)

        tracking_state = snapshot.get("tracking_state")
        self.assertIsInstance(tracking_state, dict)
        self.assertIn("demo_links", tracking_state)
        self.assertIn("runtime_state", tracking_state)
        self.assertIn("robots", tracking_state["runtime_state"])
        self.assertIn("taskgen", tracking_state["runtime_state"])

        system_state_structured = snapshot.get("system_state_structured")
        self.assertIsInstance(system_state_structured, dict)
        self.assertIn("tracking", system_state_structured)
        motion_commands = snapshot.get("motion_commands")
        self.assertIsInstance(motion_commands, list)
        self.assertGreater(len(motion_commands), 0)
        self.assertIn("assigned_action_kind", motion_commands[0])
        self.assertIn("assigned_action_name", motion_commands[0])
        self.assertIn("assigned_action_service_time_s", motion_commands[0])
        self.assertEqual(
            sorted(tracking_state["demo_links"].keys()),
            ["active_task_ids_by_robot", "current_task_ids_by_robot", "queued_task_ids_by_robot"],
        )


if __name__ == "__main__":
    unittest.main()
