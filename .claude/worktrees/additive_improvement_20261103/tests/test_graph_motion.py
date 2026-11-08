import unittest

import DeterrentSystem as ds
from graph_motion import GraphReservationTable, VineyardMotionGraph


class VineyardMotionGraphTests(unittest.TestCase):
    def setUp(self):
        self.graph = VineyardMotionGraph(
            W=240.0,
            H=96.0,
            row_spacing_m=4.8,
            row_width_m=3.2,
            headland_space_m=8.0,
            graph_row_node_spacing_m=12.0,
            graph_headland_node_spacing_m=8.0,
            graph_passing_bay_spacing_m=36.0,
        )

    def test_graph_generation_is_deterministic_and_inside_field(self):
        graph_b = VineyardMotionGraph(
            W=240.0,
            H=96.0,
            row_spacing_m=4.8,
            row_width_m=3.2,
            headland_space_m=8.0,
            graph_row_node_spacing_m=12.0,
            graph_headland_node_spacing_m=8.0,
            graph_passing_bay_spacing_m=36.0,
        )

        self.assertEqual(sorted(self.graph.nodes.keys()), sorted(graph_b.nodes.keys()))
        self.assertEqual(sorted(self.graph.edges.keys()), sorted(graph_b.edges.keys()))
        self.assertTrue(any(edge.kind == "headland" for edge in self.graph.edges.values()))
        self.assertFalse(any(edge.kind == "passing_bay" for edge in self.graph.edges.values()))
        for node in self.graph.nodes.values():
            self.assertGreaterEqual(node.x, 0.0)
            self.assertLessEqual(node.x, 240.0)
            self.assertGreaterEqual(node.y, 0.0)
            self.assertLessEqual(node.y, 96.0)

    def test_route_uses_legal_axis_aligned_segments(self):
        start_node_id = self.graph.nearest_node_id((18.0, 10.0))
        goal_node_id = self.graph.nearest_node_id((224.0, 78.0))
        plan = self.graph.plan_route(
            start_node_id=start_node_id,
            goal_node_id=goal_node_id,
            start_time_s=0.0,
            speed_mps=2.5,
            reservations=GraphReservationTable(),
            reservation_horizon_s=300.0,
            max_detour_ratio=2.0,
            wait_retry_period_s=10.0,
            node_hold_s=3.0,
        )

        self.assertFalse(plan.blocked)
        self.assertGreater(len(plan.route_waypoints), 2)
        self.assertTrue(any(abs(plan.route_waypoints[i + 1][1] - plan.route_waypoints[i][1]) > 1.0e-6 for i in range(len(plan.route_waypoints) - 1)))
        for first, second in zip(plan.route_waypoints, plan.route_waypoints[1:]):
            dx = abs(float(second[0]) - float(first[0]))
            dy = abs(float(second[1]) - float(first[1]))
            self.assertTrue(dx <= 1.0e-6 or dy <= 1.0e-6)

    def test_route_changes_rows_only_via_headlands(self):
        start_node_id = self.graph.nearest_node_id((18.0, 10.0))
        goal_node_id = self.graph.nearest_node_id((224.0, 78.0))
        plan = self.graph.plan_route(
            start_node_id=start_node_id,
            goal_node_id=goal_node_id,
            start_time_s=0.0,
            speed_mps=2.5,
            reservations=GraphReservationTable(),
            reservation_horizon_s=300.0,
            max_detour_ratio=2.0,
            wait_retry_period_s=10.0,
            node_hold_s=3.0,
        )

        self.assertFalse(plan.blocked)
        for first_node_id, second_node_id in zip(plan.route_node_ids, plan.route_node_ids[1:]):
            edge = self.graph.edges[(first_node_id, second_node_id)]
            first_node = self.graph.nodes[first_node_id]
            second_node = self.graph.nodes[second_node_id]
            if abs(first_node.y - second_node.y) <= 1.0e-6:
                continue
            self.assertIn(edge.kind, {"headland"})
            self.assertTrue(
                abs(first_node.x) <= 1.0e-6
                or abs(first_node.x - self.graph.W) <= 1.0e-6
                or abs(second_node.x) <= 1.0e-6
                or abs(second_node.x - self.graph.W) <= 1.0e-6
            )

    def test_reservations_prevent_conflicting_head_on_use(self):
        start_a = self.graph.nearest_node_id((20.0, 10.4))
        goal_a = self.graph.nearest_node_id((224.0, 10.4))
        reservations = GraphReservationTable()
        plan_a = self.graph.plan_route(
            start_node_id=start_a,
            goal_node_id=goal_a,
            start_time_s=0.0,
            speed_mps=2.6,
            reservations=reservations,
            reservation_horizon_s=200.0,
            max_detour_ratio=2.0,
            wait_retry_period_s=10.0,
            node_hold_s=3.0,
        )
        reservations.reserve_plan(
            robot_id="r1",
            plan=plan_a,
            node_hold_s=3.0,
            final_hold_s=12.0,
        )

        plan_b = self.graph.plan_route(
            start_node_id=goal_a,
            goal_node_id=start_a,
            start_time_s=0.0,
            speed_mps=2.6,
            reservations=reservations,
            reservation_horizon_s=200.0,
            max_detour_ratio=2.0,
            wait_retry_period_s=10.0,
            node_hold_s=3.0,
        )

        if plan_b.blocked:
            self.assertIn(plan_b.route_status, {"waiting", "blocked"})
            return

        for idx in range(len(plan_b.route_node_ids) - 1):
            self.assertFalse(
                reservations.edge_conflict(
                    plan_b.route_node_ids[idx],
                    plan_b.route_node_ids[idx + 1],
                    plan_b.arrival_times_s[idx],
                    plan_b.arrival_times_s[idx + 1],
                    ignore_robot_id="r2",
                )
            )


class GraphMotionRuntimeTests(unittest.TestCase):
    def test_graph_mode_commands_and_tracking_export_route_state(self):
        frames = ds.run_simulation_frames_persistent(
            T_end=5.0,
            dt=5.0,
            fps=1,
            Nrobots=2,
            NX=24,
            NY=12,
            warmup_s=0.0,
            emit_tracking_state=True,
            tracking_include_arrays=False,
            tracking_preview_limit=15,
            tracking_capture_frame_locals=False,
            telemetry_clear_on_start=False,
            telemetry_prompt_save=False,
            report_metrics_end=False,
            idle_roam_enabled=True,
            idle_roam_interval_s=0.0,
            motion_planning_mode="graph",
        )

        snapshot = next(frames)
        self.assertIn("motion_graph_states", snapshot)
        self.assertIn("motion_graph_reservations", snapshot)
        self.assertTrue(snapshot["motion_graph_states"])

        command = snapshot["motion_commands"][0]
        self.assertEqual(command["planner_mode"], "graph")
        self.assertIn("route_node_ids", command)
        self.assertIn("route_waypoints", command)
        self.assertGreaterEqual(len(command["route_waypoints"]), 1)

        tracking_state = snapshot["tracking_state"]
        self.assertIn("graph_motion_states", tracking_state["runtime_state"])
        self.assertIn("graph_reservations", tracking_state["runtime_state"])

    def test_command_only_graph_mode_honors_route_progress_feedback(self):
        def motion_state_callback(payload):
            return {
                "poses": payload["poses"],
                "route_progress": {
                    str(robot_id): {
                        "active_waypoint_index": 2,
                        "route_status": "external_progress",
                    }
                    for robot_id in payload["poses"].keys()
                },
            }

        frames = ds.run_simulation_frames_persistent(
            T_end=10.0,
            dt=5.0,
            fps=1,
            Nrobots=2,
            NX=24,
            NY=12,
            warmup_s=0.0,
            emit_tracking_state=False,
            telemetry_clear_on_start=False,
            telemetry_prompt_save=False,
            report_metrics_end=False,
            idle_roam_enabled=True,
            idle_roam_interval_s=0.0,
            motion_planning_mode="graph",
            motion_orchestration_mode="command_only",
            graph_replan_period_s=60.0,
            motion_state_callback=motion_state_callback,
        )

        next(frames)
        second_snapshot = next(frames)
        command = second_snapshot["motion_commands"][0]

        self.assertEqual(command["planner_mode"], "graph")
        self.assertGreaterEqual(len(command["route_waypoints"]), 3)
        self.assertEqual(command["active_waypoint_index"], 2)


if __name__ == "__main__":
    unittest.main()
