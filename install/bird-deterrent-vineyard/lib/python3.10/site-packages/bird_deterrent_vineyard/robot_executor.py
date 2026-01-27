from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

Point = Tuple[float, float]


@dataclass
class ActiveTask:
    tid: str
    task_type: str
    goal: Point
    assigned_role: str  # "primary" or "secondary"
    start_t: float


class RobotExecutor(Node):
    """Executor node that accepts assigned tasks and carries them out.

    Subscribes:
    - /deterrent/tasks (std_msgs/String with JSON)

    Publishes:
    - /deterrent/task_status (std_msgs/String with JSON)
    - /deterrent/robot_pose (std_msgs/String with JSON)
    """

    def __init__(self) -> None:
        super().__init__("robot_executor")

        self.declare_parameter("robot_id", "r1")
        self.declare_parameter("robot_type", "UGV")
        self.declare_parameter("start_x", 0.0)
        self.declare_parameter("start_y", 0.0)
        self.declare_parameter("speed_mps", 2.5)
        self.declare_parameter("arrival_radius_m", 3.0)
        self.declare_parameter("hold_time_s", 20.0)
        self.declare_parameter("tick_s", 0.2)

        self.rid = str(self.get_parameter("robot_id").value)
        self.rtype = str(self.get_parameter("robot_type").value)
        self.pose: Point = (
            float(self.get_parameter("start_x").value),
            float(self.get_parameter("start_y").value),
        )

        self.speed_mps = float(self.get_parameter("speed_mps").value)
        self.arrival_radius_m = float(self.get_parameter("arrival_radius_m").value)
        self.hold_time_s = float(self.get_parameter("hold_time_s").value)

        self.active: Optional[ActiveTask] = None
        self._hold_until: float = -1.0

        self.status_pub = self.create_publisher(String, "/deterrent/task_status", 20)
        self.pose_pub = self.create_publisher(String, "/deterrent/robot_pose", 20)
        self.tasks_sub = self.create_subscription(String, "/deterrent/tasks", self._on_task, 50)

        tick_s = float(self.get_parameter("tick_s").value)
        self.tick_timer = self.create_timer(tick_s, self._on_tick)

        self.get_logger().info(f"Robot executor ready for {self.rid} ({self.rtype}).")

    # ----------------- ROS callbacks ----------------- #

    def _on_task(self, msg: String) -> None:
        try:
            task = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("Ignoring task: invalid JSON.")
            return

        role = None
        if task.get("assigned_primary") == self.rid:
            role = "primary"
        elif task.get("assigned_secondary") == self.rid:
            role = "secondary"

        if role is None:
            return

        tid = str(task.get("id", ""))
        goal = (float(task.get("x", self.pose[0])), float(task.get("y", self.pose[1])))
        task_type = str(task.get("type", "unknown"))
        now_t = time.time()

        if self.active is not None:
            # Simple policy: ignore new tasks while busy.
            self._publish_status("reject_busy", tid, task_type, goal, now_t, extra={"active": self.active.tid})
            return

        self.active = ActiveTask(tid=tid, task_type=task_type, goal=goal, assigned_role=role, start_t=now_t)
        self._hold_until = -1.0
        self._publish_status("accept", tid, task_type, goal, now_t, extra={"role": role})

    def _on_tick(self) -> None:
        now_t = time.time()

        if self.active is None:
            self._publish_pose(now_t)
            return

        if self._hold_until > now_t:
            self._publish_pose(now_t)
            return

        tid = self.active.tid
        goal = self.active.goal
        task_type = self.active.task_type

        self.pose = self._step_toward(self.pose, goal, dt=self.tick_timer.timer_period_ns / 1e9)
        self._publish_pose(now_t)

        if self._distance(self.pose, goal) <= self.arrival_radius_m:
            if task_type == "deterring":
                if self._hold_until < 0.0:
                    self._hold_until = now_t + self.hold_time_s
                    self._publish_status("arrived_hold", tid, task_type, goal, now_t)
                elif now_t >= self._hold_until:
                    self._publish_status("complete", tid, task_type, goal, now_t)
                    self.active = None
                    self._hold_until = -1.0
            else:
                self._publish_status("complete", tid, task_type, goal, now_t)
                self.active = None
                self._hold_until = -1.0

    # ----------------- motion helpers ----------------- #

    def _step_toward(self, pose: Point, goal: Point, dt: float) -> Point:
        px, py = pose
        gx, gy = goal
        dx = gx - px
        dy = gy - py
        dist = math.hypot(dx, dy)
        if dist <= 1e-6:
            return goal

        step = self.speed_mps * dt
        if step >= dist:
            return goal

        ux = dx / dist
        uy = dy / dist
        return (px + ux * step, py + uy * step)

    @staticmethod
    def _distance(a: Point, b: Point) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    # ----------------- publishing helpers ----------------- #

    def _publish_pose(self, now_t: float) -> None:
        payload = {"t": now_t, "rid": self.rid, "x": self.pose[0], "y": self.pose[1]}
        self.pose_pub.publish(String(data=json.dumps(payload)))

    def _publish_status(
        self,
        event: str,
        tid: str,
        task_type: str,
        goal: Point,
        now_t: float,
        extra: Optional[Dict] = None,
    ) -> None:
        payload = {
            "t": now_t,
            "event": event,
            "rid": self.rid,
            "task_id": tid,
            "type": task_type,
            "x": goal[0],
            "y": goal[1],
        }
        if extra:
            payload["extra"] = extra
        self.status_pub.publish(String(data=json.dumps(payload)))


def main(args: Optional[List[str]] = None) -> None:
    rclpy.init(args=args)
    node = RobotExecutor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
