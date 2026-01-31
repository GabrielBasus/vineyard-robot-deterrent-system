from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import rclpy
from rclpy.node import Node
from bird_deterrent_vineyard_msgs.msg import RobotPose, Task, TaskStatus

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
    - /deterrent/tasks (bird_deterrent_vineyard/Task)

    Publishes:
    - /deterrent/task_status (bird_deterrent_vineyard/TaskStatus)
    - /deterrent/robot_pose (bird_deterrent_vineyard/RobotPose)
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

        self.status_pub = self.create_publisher(TaskStatus, "/deterrent/task_status", 20)
        self.pose_pub = self.create_publisher(RobotPose, "/deterrent/robot_pose", 20)
        self.tasks_sub = self.create_subscription(Task, "/deterrent/tasks", self._on_task, 50)

        tick_s = float(self.get_parameter("tick_s").value)
        self.tick_timer = self.create_timer(tick_s, self._on_tick)

        self.get_logger().info(f"Robot executor ready for {self.rid} ({self.rtype}).")

    # ----------------- ROS callbacks ----------------- #

    def _on_task(self, msg: Task) -> None:
        role = None
        if msg.assigned_primary == self.rid:
            role = "primary"
        elif msg.assigned_secondary == self.rid:
            role = "secondary"

        if role is None:
            return

        tid = str(msg.id)
        goal = (float(msg.x), float(msg.y))
        task_type = str(msg.type)
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
        pose_msg = RobotPose()
        pose_msg.t = float(now_t)
        pose_msg.robot_id = str(self.rid)
        pose_msg.x = float(self.pose[0])
        pose_msg.y = float(self.pose[1])
        self.pose_pub.publish(pose_msg)

    def _publish_status(
        self,
        event: str,
        tid: str,
        task_type: str,
        goal: Point,
        now_t: float,
        extra: Optional[Dict] = None,
    ) -> None:
        status = TaskStatus()
        status.t = float(now_t)
        status.event = str(event)
        status.robot_id = str(self.rid)
        status.task_id = str(tid)
        status.type = str(task_type)
        status.x = float(goal[0])
        status.y = float(goal[1])
        status.role = str(extra.get("role", "")) if extra else ""
        status.extra = str(extra) if extra else ""
        self.status_pub.publish(status)


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
