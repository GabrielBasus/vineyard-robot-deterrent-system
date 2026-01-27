from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from .core_imports import import_core_modules

zone_partitioner_mod, sestpp_mod, robot_mod, task_mod = import_core_modules()

Point = Tuple[float, float]
Poly = List[Point]

ZonePartitioner = zone_partitioner_mod.ZonePartitioner
point_in_polygon = zone_partitioner_mod.point_in_polygon
polygon_centroid = zone_partitioner_mod.polygon_centroid

OnlineSESTPP = sestpp_mod.OnlineSESTPP
Robot = robot_mod.Robot
RobotProfile = robot_mod.RobotProfile
TaskGenerator = task_mod.TaskGenerator
TaskAssigner = task_mod.TaskAssigner


@dataclass
class RobotSeed:
    rid: str
    anchor: Point
    health: float
    rtype: str


class CentralCoordinator(Node):
    """Central node that computes zones, SESTPP, and tasks.

    Interfaces (JSON-over-std_msgs/String for now):
    - Subscribes:  /deterrent/detections
      Example:
        {"x": 10.0, "y": 12.0, "t": 1700000000.0}

    - Publishes:   /deterrent/tasks
      Example:
        {"id": "task-1", "type": "deterring", "x": 10.0, "y": 12.0,
         "time": 1700000000.0, "assigned_primary": "r1",
         "assigned_secondary": null, "score": 0.42}

    - Publishes:   /deterrent/zones
      Example:
        {"t": 1700000000.0, "zones": {"r1": [[...], ...]},
         "neighbors": {"r1": ["r2"]}}
    """

    def __init__(self) -> None:
        super().__init__("central_coordinator")

        # ---- Parameters ----
        self.declare_parameter("field_width", 500.0)
        self.declare_parameter("field_height", 400.0)
        self.declare_parameter("robot_ids", ["r1", "r2", "r3"])  # type: ignore[arg-type]
        self.declare_parameter("robot_types", ["UGV", "UGV", "UAV"])  # type: ignore[arg-type]
        self.declare_parameter("robot_anchors", [50.0, 50.0, 200.0, 80.0, 350.0, 300.0])  # type: ignore[arg-type]
        self.declare_parameter("robot_healths", [0.9, 0.8, 0.95])  # type: ignore[arg-type]
        self.declare_parameter("partition_types", ["UGV"])  # type: ignore[arg-type]

        self.declare_parameter("nx", 120)
        self.declare_parameter("ny", 96)
        self.declare_parameter("sigma", 16.0)
        self.declare_parameter("omega", 700.0)
        self.declare_parameter("mu_base", 1e-4)
        self.declare_parameter("bg_ema", 3e-4)

        self.declare_parameter("zone_scale", 15000.0)
        self.declare_parameter("zone_gamma", 1.5)
        self.declare_parameter("zone_mode", "direct")

        self.declare_parameter("task_replan_period_s", 5.0)
        self.declare_parameter("hotspot_top_k", 6)
        self.declare_parameter("hotspot_spacing_m", 25.0)
        self.declare_parameter("min_hotspot_score", 1e-4)
        self.declare_parameter("patrol_cooldown_s", 20.0)

        # ---- Core state ----
        self.W = float(self.get_parameter("field_width").value)
        self.H = float(self.get_parameter("field_height").value)

        seeds = self._build_robot_seeds()
        self.robot_seeds = seeds

        self.profiles = self._make_profiles(seeds)
        self.partitioner = ZonePartitioner(
            self.W,
            self.H,
            robots_def=[{"id": s.rid, "anchor": s.anchor, "health": s.health} for s in seeds],
            profiles=self.profiles,
            mode=str(self.get_parameter("zone_mode").value),
            scale=float(self.get_parameter("zone_scale").value),
            gamma=float(self.get_parameter("zone_gamma").value),
            partition_types=tuple(self.get_parameter("partition_types").value),
        )

        self.robots: Dict[str, Robot] = {}
        self._rebuild_robots_from_partition()

        self.taskgen = TaskGenerator(
            merge_radius_m=max(8.0, 0.5 * float(self.get_parameter("sigma").value)),
            patrol_cooldown_s=float(self.get_parameter("patrol_cooldown_s").value),
        )
        self.assigner = TaskAssigner(self.robots, self.profiles, params={"uav_spinup_s": 8.0})

        self.next_task_id = 1
        self._published_task_keys: set[tuple] = set()

        # ---- ROS interfaces ----
        tasks_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        zones_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        status_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self.tasks_pub = self.create_publisher(String, "/deterrent/tasks", tasks_qos)
        self.zones_pub = self.create_publisher(String, "/deterrent/zones", zones_qos)
        self.status_pub = self.create_publisher(String, "/deterrent/system_status", status_qos)

        self.detections_sub = self.create_subscription(String, "/deterrent/detections", self._on_detection, 50)
        self.task_status_sub = self.create_subscription(String, "/deterrent/task_status", self._on_task_status, 50)

        replan_period = float(self.get_parameter("task_replan_period_s").value)
        self.replan_timer = self.create_timer(replan_period, self._on_replan_timer)

        self._publish_zones(now=time.time())
        self.get_logger().info("Central coordinator ready.")

    # ----------------- setup helpers ----------------- #

    def _build_robot_seeds(self) -> List[RobotSeed]:
        ids: List[str] = list(self.get_parameter("robot_ids").value)
        types: List[str] = list(self.get_parameter("robot_types").value)
        anchors_flat: List[float] = list(self.get_parameter("robot_anchors").value)
        healths: List[float] = list(self.get_parameter("robot_healths").value)

        if len(types) != len(ids):
            raise ValueError("robot_types must have the same length as robot_ids.")
        if len(healths) != len(ids):
            raise ValueError("robot_healths must have the same length as robot_ids.")
        if len(anchors_flat) != 2 * len(ids):
            raise ValueError("robot_anchors must be a flat [x1,y1,x2,y2,...] list.")

        seeds: List[RobotSeed] = []
        for i, rid in enumerate(ids):
            ax = float(anchors_flat[2 * i])
            ay = float(anchors_flat[2 * i + 1])
            seeds.append(RobotSeed(rid=rid, anchor=(ax, ay), health=float(healths[i]), rtype=str(types[i])))
        return seeds

    def _make_profiles(self, seeds: List[RobotSeed]) -> Dict[str, RobotProfile]:
        profiles: Dict[str, RobotProfile] = {}
        for s in seeds:
            if s.rtype.upper() == "UAV":
                profiles[s.rid] = RobotProfile(
                    id=s.rid,
                    type="UAV",
                    speed_mps=12.0,
                    endurance_min=12.0,
                    battery=0.9,
                    health=s.health,
                    has_deterrent=True,
                    deterrent_eff=1.0,
                )
            else:
                profiles[s.rid] = RobotProfile(
                    id=s.rid,
                    type="UGV",
                    speed_mps=2.6,
                    endurance_min=150.0,
                    battery=0.9,
                    health=s.health,
                    has_deterrent=True,
                    deterrent_eff=0.7,
                )
        return profiles

    def _rebuild_robots_from_partition(self) -> None:
        nx = int(self.get_parameter("nx").value)
        ny = int(self.get_parameter("ny").value)
        sigma = float(self.get_parameter("sigma").value)
        omega = float(self.get_parameter("omega").value)
        mu_base = float(self.get_parameter("mu_base").value)
        bg_ema = float(self.get_parameter("bg_ema").value)

        cells = self.partitioner.cells_for_ids()
        id_to_cell = {rid: cells[i] for i, rid in enumerate(self.partitioner.ids)}

        alpha_in = 0.6 / omega
        alpha_cross = 0.4 * alpha_in

        robots: Dict[str, Robot] = {}
        for s in self.robot_seeds:
            rid = s.rid
            model = OnlineSESTPP(
                0.0,
                self.W,
                0.0,
                self.H,
                nx,
                ny,
                sigma=sigma,
                omega=omega,
                alpha_in=alpha_in,
                alpha_cross=alpha_cross,
                mu_base=mu_base,
                bg_ema=bg_ema,
            )

            neighbors = self.partitioner.neighbors_for_id(rid)
            zone = id_to_cell.get(rid, [])
            robots[rid] = Robot(rid, model, zone, neighbors, border_radius_m=max(10.0, 1.5 * sigma))

        self.robots = robots
        self.assigner = TaskAssigner(self.robots, self.profiles, params={"uav_spinup_s": 8.0})

    # ----------------- ROS callbacks ----------------- #

    def _on_detection(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("Ignoring detection: invalid JSON.")
            return

        x = float(data.get("x"))
        y = float(data.get("y"))
        t = float(data.get("t", time.time()))

        owner = self._zone_owner(x, y)
        if owner is None:
            owner = self._nearest_robot(x, y)

        boundary_events = self.robots[owner].ingest_detection(x, y, t)
        self._relay_boundary_events(boundary_events, source_id=owner)
        self.taskgen.on_detection(owner, x, y, t)

        self._publish_status({"event": "detection", "owner": owner, "x": x, "y": y, "t": t})

    def _on_task_status(self, msg: String) -> None:
        # For now we only log it; you can later use this to close tasks centrally.
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("Ignoring task_status: invalid JSON.")
            return
        self.get_logger().info(f"Task status: {data}")

    def _on_replan_timer(self) -> None:
        now_t = time.time()

        self.taskgen.periodic_patrolling(
            self.robots,
            now_t=now_t,
            hotspot_top_k=int(self.get_parameter("hotspot_top_k").value),
            include_fallback_patrol=False,
            deterring_window_s=0.0,
            min_hotspot_score=float(self.get_parameter("min_hotspot_score").value),
            hotspot_spacing_m=float(self.get_parameter("hotspot_spacing_m").value),
        )

        rows = self.taskgen.rows()
        if not rows:
            return

        published = 0
        for task in rows:
            assignment = self.assigner.assign_task(task)
            if assignment is None:
                continue

            task_msg = dict(assignment["task"])
            task_msg["id"] = f"task-{self.next_task_id}"
            self.next_task_id += 1
            task_msg["assigned_primary"] = assignment["primary"]
            task_msg["assigned_secondary"] = assignment["secondary"]

            # Lightweight dedupe to avoid republishing the same task every cycle.
            key = (
                task_msg["assigned_primary"],
                task_msg["type"],
                round(float(task_msg["x"]), 1),
                round(float(task_msg["y"]), 1),
                round(float(task_msg["time"]), 0),
            )
            if key in self._published_task_keys:
                continue
            self._published_task_keys.add(key)

            self.tasks_pub.publish(String(data=json.dumps(task_msg)))
            published += 1

        self.taskgen.clear()

        if published:
            self._publish_status({"event": "replan", "published_tasks": published, "t": now_t})

    # ----------------- core logic helpers ----------------- #

    def _zone_owner(self, x: float, y: float) -> Optional[str]:
        cells = self.partitioner.cells_for_ids()
        for i, rid in enumerate(self.partitioner.ids):
            poly = cells[i]
            if poly and point_in_polygon(x, y, poly):
                return rid
        return None

    def _nearest_robot(self, x: float, y: float) -> str:
        best_rid = self.robot_seeds[0].rid
        best_d = float("inf")
        for s in self.robot_seeds:
            d = math.hypot(x - s.anchor[0], y - s.anchor[1])
            if d < best_d:
                best_d = d
                best_rid = s.rid
        return best_rid

    def _relay_boundary_events(self, events: List[Dict], source_id: str) -> None:
        for ev in events:
            rid = ev.get("target_robot")
            if rid in self.robots and rid != source_id:
                self.robots[rid].ingest_boundary_event(
                    x=float(ev["x"]),
                    y=float(ev["y"]),
                    t=float(ev["t"]),
                    weight=float(ev.get("weight", 0.35)),
                    sigma=ev.get("sigma"),
                    omega=ev.get("omega"),
                )

    def _publish_zones(self, now: float) -> None:
        cells = self.partitioner.cells_for_ids()
        zones = {rid: cells[i] for i, rid in enumerate(self.partitioner.ids)}
        neighbors = {s.rid: self.partitioner.neighbors_for_id(s.rid) for s in self.robot_seeds}

        payload = {"t": now, "zones": zones, "neighbors": neighbors}
        self.zones_pub.publish(String(data=json.dumps(payload)))

    def _publish_status(self, payload: Dict) -> None:
        self.status_pub.publish(String(data=json.dumps(payload)))


def main(args: Optional[List[str]] = None) -> None:
    rclpy.init(args=args)
    node = CentralCoordinator()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
