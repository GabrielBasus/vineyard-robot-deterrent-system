from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    x: float
    y: float
    kind: str
    lane_index: int | None = None

    def point(self) -> tuple[float, float]:
        return (float(self.x), float(self.y))


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    start_node_id: str
    end_node_id: str
    length_m: float
    kind: str


@dataclass(frozen=True)
class ReservationWindow:
    robot_id: str
    start_t: float
    end_t: float


@dataclass
class GraphRoutePlan:
    planner_mode: str
    route_node_ids: list[str] = field(default_factory=list)
    route_waypoints: list[tuple[float, float]] = field(default_factory=list)
    arrival_times_s: list[float] = field(default_factory=list)
    active_waypoint_index: int = 0
    blocked: bool = False
    wait_reason: str | None = None
    route_status: str = "idle"
    total_length_m: float = 0.0
    total_time_s: float = 0.0
    current_node_id: str | None = None
    next_node_id: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "planner_mode": str(self.planner_mode),
            "route_node_ids": [str(node_id) for node_id in self.route_node_ids],
            "route_waypoints": [
                (float(point[0]), float(point[1]))
                for point in self.route_waypoints
            ],
            "arrival_times_s": [float(t_s) for t_s in self.arrival_times_s],
            "active_waypoint_index": int(self.active_waypoint_index),
            "blocked": bool(self.blocked),
            "wait_reason": (None if self.wait_reason is None else str(self.wait_reason)),
            "route_status": str(self.route_status),
            "total_length_m": float(self.total_length_m),
            "total_time_s": float(self.total_time_s),
            "current_node_id": (None if self.current_node_id is None else str(self.current_node_id)),
            "next_node_id": (None if self.next_node_id is None else str(self.next_node_id)),
        }


@dataclass
class GraphRobotState:
    goal_node_id: str | None = None
    goal_xy: tuple[float, float] | None = None
    last_plan_t: float = -1.0e18
    plan: GraphRoutePlan = field(default_factory=lambda: GraphRoutePlan(planner_mode="graph"))

    def clear(self) -> None:
        self.goal_node_id = None
        self.goal_xy = None
        self.last_plan_t = -1.0e18
        self.plan = GraphRoutePlan(planner_mode="graph")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "goal_node_id": (None if self.goal_node_id is None else str(self.goal_node_id)),
            "goal_xy": (
                None
                if self.goal_xy is None
                else (float(self.goal_xy[0]), float(self.goal_xy[1]))
            ),
            "last_plan_t": float(self.last_plan_t),
            "plan": self.plan.to_public_dict(),
        }


class GraphReservationTable:
    def __init__(self) -> None:
        self.node_windows: dict[str, list[ReservationWindow]] = {}
        self.edge_windows: dict[tuple[str, str], list[ReservationWindow]] = {}

    @staticmethod
    def _overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> bool:
        return max(float(start_a), float(start_b)) < min(float(end_a), float(end_b))

    def _has_conflict(
        self,
        windows: Sequence[ReservationWindow],
        start_t: float,
        end_t: float,
        *,
        ignore_robot_id: str | None = None,
    ) -> bool:
        for window in windows:
            if ignore_robot_id is not None and str(window.robot_id) == str(ignore_robot_id):
                continue
            if self._overlap(start_t, end_t, window.start_t, window.end_t):
                return True
        return False

    def node_conflict(
        self,
        node_id: str,
        start_t: float,
        end_t: float,
        *,
        ignore_robot_id: str | None = None,
    ) -> bool:
        return self._has_conflict(
            self.node_windows.get(str(node_id), ()),
            start_t,
            end_t,
            ignore_robot_id=ignore_robot_id,
        )

    def edge_conflict(
        self,
        start_node_id: str,
        end_node_id: str,
        start_t: float,
        end_t: float,
        *,
        ignore_robot_id: str | None = None,
    ) -> bool:
        edge_key = (str(start_node_id), str(end_node_id))
        reverse_key = (str(end_node_id), str(start_node_id))
        return (
            self._has_conflict(
                self.edge_windows.get(edge_key, ()),
                start_t,
                end_t,
                ignore_robot_id=ignore_robot_id,
            )
            or self._has_conflict(
                self.edge_windows.get(reverse_key, ()),
                start_t,
                end_t,
                ignore_robot_id=ignore_robot_id,
            )
        )

    def reserve_plan(
        self,
        *,
        robot_id: str,
        plan: GraphRoutePlan,
        node_hold_s: float,
        final_hold_s: float,
    ) -> None:
        if len(plan.route_node_ids) <= 0:
            return
        node_hold = max(float(node_hold_s), 0.25)
        final_hold = max(float(final_hold_s), node_hold)
        if len(plan.arrival_times_s) != len(plan.route_node_ids):
            return
        for index, node_id in enumerate(plan.route_node_ids):
            center_t = float(plan.arrival_times_s[index])
            if index == len(plan.route_node_ids) - 1:
                start_t = center_t - 0.5 * node_hold
                end_t = center_t + final_hold
            else:
                start_t = center_t - 0.5 * node_hold
                end_t = center_t + 0.5 * node_hold
            self.node_windows.setdefault(str(node_id), []).append(
                ReservationWindow(str(robot_id), float(start_t), float(end_t))
            )
        for index in range(len(plan.route_node_ids) - 1):
            edge_key = (str(plan.route_node_ids[index]), str(plan.route_node_ids[index + 1]))
            self.edge_windows.setdefault(edge_key, []).append(
                ReservationWindow(
                    str(robot_id),
                    float(plan.arrival_times_s[index]),
                    float(plan.arrival_times_s[index + 1]),
                )
            )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "node_windows": {
                str(node_id): [
                    {
                        "robot_id": str(window.robot_id),
                        "start_t": float(window.start_t),
                        "end_t": float(window.end_t),
                    }
                    for window in windows
                ]
                for node_id, windows in self.node_windows.items()
            },
            "edge_windows": {
                f"{start}->{end}": [
                    {
                        "robot_id": str(window.robot_id),
                        "start_t": float(window.start_t),
                        "end_t": float(window.end_t),
                    }
                    for window in windows
                ]
                for (start, end), windows in self.edge_windows.items()
            },
        }


class VineyardMotionGraph:
    def __init__(
        self,
        *,
        W: float,
        H: float,
        row_spacing_m: float,
        row_width_m: float,
        headland_space_m: float,
        graph_row_node_spacing_m: float,
        graph_headland_node_spacing_m: float,
        graph_passing_bay_spacing_m: float,
    ) -> None:
        self.W = float(W)
        self.H = float(H)
        self.row_spacing_m = float(row_spacing_m)
        self.row_width_m = float(row_width_m)
        self.headland_space_m = float(headland_space_m)
        self.graph_row_node_spacing_m = max(float(graph_row_node_spacing_m), 1.0)
        self.graph_headland_node_spacing_m = max(float(graph_headland_node_spacing_m), 1.0)
        self.graph_passing_bay_spacing_m = max(float(graph_passing_bay_spacing_m), 1.0)
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[tuple[str, str], GraphEdge] = {}
        self.adjacency: dict[str, list[tuple[str, GraphEdge]]] = {}
        self.lane_centers_y = self._free_lane_centers()
        self._build_graph()

    def _row_bands(self) -> list[tuple[float, float]]:
        if self.row_spacing_m <= 0.0:
            return []
        bands: list[tuple[float, float]] = []
        index = 0
        while True:
            y = self.headland_space_m + index * self.row_spacing_m
            if y - 0.5 * self.row_width_m > (self.H - self.headland_space_m):
                break
            bands.append((y - 0.5 * self.row_width_m, y + 0.5 * self.row_width_m))
            index += 1
        return bands

    def _free_lane_centers(self) -> list[float]:
        row_bands = self._row_bands()
        if not row_bands:
            return [0.5 * self.H]
        centers: list[float] = []
        previous = 0.0
        for band_start, band_end in row_bands:
            if band_start > previous:
                centers.append(0.5 * (previous + band_start))
            previous = band_end
        if self.H > previous:
            centers.append(0.5 * (previous + self.H))
        return [float(center) for center in centers]

    @staticmethod
    def _sample_positions(start: float, end: float, spacing: float) -> list[float]:
        start_f = float(start)
        end_f = float(end)
        if end_f < start_f:
            start_f, end_f = end_f, start_f
        spacing_f = max(float(spacing), 1.0)
        positions = [start_f]
        cursor = start_f
        while (cursor + spacing_f) < end_f:
            cursor += spacing_f
            positions.append(cursor)
        if positions[-1] != end_f:
            positions.append(end_f)
        return sorted({round(float(position), 6) for position in positions})

    def _add_node(self, node_id: str, x: float, y: float, kind: str, lane_index: int | None = None) -> None:
        self.nodes[str(node_id)] = GraphNode(str(node_id), float(x), float(y), str(kind), lane_index)
        self.adjacency.setdefault(str(node_id), [])

    def _add_edge(self, start_node_id: str, end_node_id: str, kind: str) -> None:
        start_node = self.nodes[str(start_node_id)]
        end_node = self.nodes[str(end_node_id)]
        length_m = math.hypot(float(end_node.x) - float(start_node.x), float(end_node.y) - float(start_node.y))
        edge = GraphEdge(
            edge_id=f"{start_node.node_id}->{end_node.node_id}",
            start_node_id=str(start_node.node_id),
            end_node_id=str(end_node.node_id),
            length_m=float(length_m),
            kind=str(kind),
        )
        self.edges[(edge.start_node_id, edge.end_node_id)] = edge
        self.adjacency.setdefault(edge.start_node_id, []).append((edge.end_node_id, edge))

    def _build_graph(self) -> None:
        row_x_positions = self._sample_positions(
            self.headland_space_m,
            max(self.headland_space_m, self.W - self.headland_space_m),
            self.graph_row_node_spacing_m,
        )
        extra_lane_x_positions = [
            x
            for x in self._sample_positions(
                self.headland_space_m,
                max(self.headland_space_m, self.W - self.headland_space_m),
                self.graph_passing_bay_spacing_m,
            )
            if x not in {row_x_positions[0], row_x_positions[-1]}
        ]
        row_x_positions = sorted({*row_x_positions, *extra_lane_x_positions})

        headland_y_positions = self._sample_positions(0.0, self.H, self.graph_headland_node_spacing_m)
        headland_y_positions = sorted({*headland_y_positions, *(round(y, 6) for y in self.lane_centers_y)})

        lane_node_ids: dict[tuple[int, float], str] = {}
        for lane_index, lane_y in enumerate(self.lane_centers_y):
            for x_index, lane_x in enumerate(row_x_positions):
                node_id = f"lane:{lane_index}:{x_index}"
                self._add_node(node_id, lane_x, lane_y, "lane", lane_index)
                lane_node_ids[(lane_index, round(float(lane_x), 6))] = node_id

        left_headland_ids: dict[float, str] = {}
        right_headland_ids: dict[float, str] = {}
        for headland_index, headland_y in enumerate(headland_y_positions):
            left_node_id = f"headland:left:{headland_index}"
            right_node_id = f"headland:right:{headland_index}"
            self._add_node(left_node_id, 0.0, headland_y, "headland_left")
            self._add_node(right_node_id, self.W, headland_y, "headland_right")
            left_headland_ids[round(float(headland_y), 6)] = left_node_id
            right_headland_ids[round(float(headland_y), 6)] = right_node_id

        for lane_index, lane_y in enumerate(self.lane_centers_y):
            for idx in range(len(row_x_positions) - 1):
                start_node_id = lane_node_ids[(lane_index, round(float(row_x_positions[idx]), 6))]
                end_node_id = lane_node_ids[(lane_index, round(float(row_x_positions[idx + 1]), 6))]
                self._add_edge(start_node_id, end_node_id, "lane")
                self._add_edge(end_node_id, start_node_id, "lane")

            left_lane_node_id = lane_node_ids[(lane_index, round(float(row_x_positions[0]), 6))]
            right_lane_node_id = lane_node_ids[(lane_index, round(float(row_x_positions[-1]), 6))]
            left_headland_node_id = left_headland_ids[round(float(lane_y), 6)]
            right_headland_node_id = right_headland_ids[round(float(lane_y), 6)]
            self._add_edge(left_lane_node_id, left_headland_node_id, "turn")
            self._add_edge(left_headland_node_id, left_lane_node_id, "turn")
            self._add_edge(right_lane_node_id, right_headland_node_id, "turn")
            self._add_edge(right_headland_node_id, right_lane_node_id, "turn")

        for y_index in range(len(headland_y_positions) - 1):
            left_start = left_headland_ids[round(float(headland_y_positions[y_index]), 6)]
            left_end = left_headland_ids[round(float(headland_y_positions[y_index + 1]), 6)]
            right_start = right_headland_ids[round(float(headland_y_positions[y_index]), 6)]
            right_end = right_headland_ids[round(float(headland_y_positions[y_index + 1]), 6)]
            self._add_edge(left_start, left_end, "headland")
            self._add_edge(left_end, left_start, "headland")
            self._add_edge(right_start, right_end, "headland")
            self._add_edge(right_end, right_start, "headland")

    def node_point(self, node_id: str) -> tuple[float, float]:
        return self.nodes[str(node_id)].point()

    def nearest_node_id(
        self,
        point_xy: tuple[float, float],
        *,
        allowed_node_ids: Iterable[str] | None = None,
    ) -> str:
        x, y = float(point_xy[0]), float(point_xy[1])
        candidates = (
            [self.nodes[str(node_id)] for node_id in allowed_node_ids if str(node_id) in self.nodes]
            if allowed_node_ids is not None
            else list(self.nodes.values())
        )
        if not candidates:
            raise ValueError("Graph has no nodes to snap against.")
        return min(
            candidates,
            key=lambda node: math.hypot(float(node.x) - x, float(node.y) - y),
        ).node_id

    def nodes_in_polygon(
        self,
        polygon: Sequence[tuple[float, float]] | None,
        *,
        point_in_polygon_fn,
    ) -> list[str]:
        if not polygon:
            return list(self.nodes.keys())
        return [
            node_id
            for node_id, node in self.nodes.items()
            if point_in_polygon_fn(float(node.x), float(node.y), polygon)
        ]

    def _heuristic_distance(self, start_node_id: str, goal_node_id: str) -> float:
        start_node = self.nodes[str(start_node_id)]
        goal_node = self.nodes[str(goal_node_id)]
        return math.hypot(float(goal_node.x) - float(start_node.x), float(goal_node.y) - float(start_node.y))

    def shortest_path(self, start_node_id: str, goal_node_id: str) -> tuple[list[str], float]:
        start = str(start_node_id)
        goal = str(goal_node_id)
        queue: list[tuple[float, float, str]] = [(self._heuristic_distance(start, goal), 0.0, start)]
        best_dist: dict[str, float] = {start: 0.0}
        parents: dict[str, str | None] = {start: None}
        while queue:
            _priority, dist_so_far, node_id = heapq.heappop(queue)
            if node_id == goal:
                break
            if dist_so_far > best_dist.get(node_id, float("inf")) + 1.0e-9:
                continue
            for neighbor_id, edge in self.adjacency.get(node_id, ()):
                candidate_dist = float(dist_so_far) + float(edge.length_m)
                if candidate_dist + 1.0e-9 >= best_dist.get(neighbor_id, float("inf")):
                    continue
                best_dist[neighbor_id] = candidate_dist
                parents[neighbor_id] = node_id
                heapq.heappush(
                    queue,
                    (
                        candidate_dist + self._heuristic_distance(neighbor_id, goal),
                        candidate_dist,
                        neighbor_id,
                    ),
                )
        if goal not in parents:
            return [], float("inf")
        path: list[str] = []
        cursor: str | None = goal
        while cursor is not None:
            path.append(cursor)
            cursor = parents.get(cursor)
        path.reverse()
        return path, float(best_dist.get(goal, float("inf")))

    def _build_plan(
        self,
        node_ids: list[str],
        start_time_s: float,
        speed_mps: float,
        *,
        blocked: bool = False,
        wait_reason: str | None = None,
        route_status: str = "active",
    ) -> GraphRoutePlan:
        if not node_ids:
            return GraphRoutePlan(
                planner_mode="graph",
                blocked=bool(blocked),
                wait_reason=wait_reason,
                route_status=str(route_status),
            )
        speed = max(float(speed_mps), 1.0e-6)
        arrival_times = [float(start_time_s)]
        total_length_m = 0.0
        for index in range(len(node_ids) - 1):
            edge = self.edges[(str(node_ids[index]), str(node_ids[index + 1]))]
            total_length_m += float(edge.length_m)
            arrival_times.append(arrival_times[-1] + float(edge.length_m) / speed)
        active_waypoint_index = 0 if len(node_ids) <= 1 else 1
        next_node_id = None if len(node_ids) <= 1 else str(node_ids[1])
        return GraphRoutePlan(
            planner_mode="graph",
            route_node_ids=[str(node_id) for node_id in node_ids],
            route_waypoints=[self.node_point(node_id) for node_id in node_ids],
            arrival_times_s=[float(value) for value in arrival_times],
            active_waypoint_index=int(active_waypoint_index),
            blocked=bool(blocked),
            wait_reason=wait_reason,
            route_status=str(route_status),
            total_length_m=float(total_length_m),
            total_time_s=float(arrival_times[-1] - float(start_time_s)),
            current_node_id=str(node_ids[0]),
            next_node_id=next_node_id,
        )

    def _timed_path_with_reservations(
        self,
        start_node_id: str,
        goal_node_id: str,
        *,
        start_time_s: float,
        speed_mps: float,
        reservations: GraphReservationTable,
        reservation_horizon_s: float,
        node_hold_s: float,
        ignore_robot_id: str | None,
    ) -> tuple[list[str], list[float], float]:
        speed = max(float(speed_mps), 1.0e-6)
        horizon_s = max(float(reservation_horizon_s), 0.0)
        node_hold = max(float(node_hold_s), 0.25)
        time_bucket_s = max(0.5, 0.5 * node_hold)
        start = str(start_node_id)
        goal = str(goal_node_id)
        queue: list[tuple[float, float, str, int]] = []
        start_key = (start, 0)
        heapq.heappush(queue, (self._heuristic_distance(start, goal) / speed, 0.0, start, 0))
        best_time: dict[tuple[str, int], float] = {start_key: 0.0}
        parents: dict[tuple[str, int], tuple[str, int] | None] = {start_key: None}
        abs_times: dict[tuple[str, int], float] = {start_key: float(start_time_s)}

        final_key: tuple[str, int] | None = None
        while queue:
            _priority, rel_time_s, node_id, bucket = heapq.heappop(queue)
            state_key = (node_id, bucket)
            if rel_time_s > best_time.get(state_key, float("inf")) + 1.0e-9:
                continue
            if node_id == goal:
                final_key = state_key
                break
            for neighbor_id, edge in self.adjacency.get(node_id, ()):
                travel_time_s = float(edge.length_m) / speed
                next_rel_time_s = float(rel_time_s) + travel_time_s
                if next_rel_time_s > horizon_s + 1.0e-9:
                    continue
                depart_t = float(start_time_s) + float(rel_time_s)
                arrive_t = float(start_time_s) + float(next_rel_time_s)
                if reservations.edge_conflict(
                    node_id,
                    neighbor_id,
                    depart_t,
                    arrive_t,
                    ignore_robot_id=ignore_robot_id,
                ):
                    continue
                if reservations.node_conflict(
                    neighbor_id,
                    arrive_t - 0.5 * node_hold,
                    arrive_t + 0.5 * node_hold,
                    ignore_robot_id=ignore_robot_id,
                ):
                    continue
                next_bucket = int(math.floor(next_rel_time_s / time_bucket_s))
                next_key = (neighbor_id, next_bucket)
                if next_rel_time_s + 1.0e-9 >= best_time.get(next_key, float("inf")):
                    continue
                best_time[next_key] = float(next_rel_time_s)
                parents[next_key] = state_key
                abs_times[next_key] = float(arrive_t)
                heuristic_s = self._heuristic_distance(neighbor_id, goal) / speed
                heapq.heappush(
                    queue,
                    (
                        next_rel_time_s + heuristic_s,
                        next_rel_time_s,
                        neighbor_id,
                        next_bucket,
                    ),
                )
        if final_key is None:
            return [], [], float("inf")

        route_keys: list[tuple[str, int]] = []
        cursor: tuple[str, int] | None = final_key
        while cursor is not None:
            route_keys.append(cursor)
            cursor = parents.get(cursor)
        route_keys.reverse()
        node_ids = [node_id for node_id, _bucket in route_keys]
        arrival_times_s = [float(start_time_s)] + [float(abs_times[key]) for key in route_keys[1:]]
        total_time_s = float(arrival_times_s[-1] - float(start_time_s))
        return node_ids, arrival_times_s, total_time_s

    def select_wait_plan(
        self,
        *,
        start_node_id: str,
        start_time_s: float,
        speed_mps: float,
        reservations: GraphReservationTable,
        wait_retry_period_s: float,
        node_hold_s: float,
        ignore_robot_id: str | None,
    ) -> GraphRoutePlan:
        wait_window_s = max(float(wait_retry_period_s), 1.0)
        start = str(start_node_id)
        if not reservations.node_conflict(
            start,
            float(start_time_s),
            float(start_time_s) + wait_window_s,
            ignore_robot_id=ignore_robot_id,
        ):
            plan = self._build_plan(
                [start],
                start_time_s,
                speed_mps,
                blocked=True,
                wait_reason="reservation_conflict",
                route_status="waiting",
            )
            plan.arrival_times_s = [float(start_time_s)]
            plan.total_time_s = float(wait_window_s)
            plan.next_node_id = None
            return plan

        speed = max(float(speed_mps), 1.0e-6)
        best_neighbor: tuple[str, float] | None = None
        for neighbor_id, edge in self.adjacency.get(start, ()):
            travel_time_s = float(edge.length_m) / speed
            depart_t = float(start_time_s)
            arrive_t = depart_t + travel_time_s
            if reservations.edge_conflict(
                start,
                neighbor_id,
                depart_t,
                arrive_t,
                ignore_robot_id=ignore_robot_id,
            ):
                continue
            if reservations.node_conflict(
                neighbor_id,
                arrive_t - 0.5 * node_hold_s,
                arrive_t + wait_window_s,
                ignore_robot_id=ignore_robot_id,
            ):
                continue
            if best_neighbor is None or float(edge.length_m) < best_neighbor[1]:
                best_neighbor = (str(neighbor_id), float(edge.length_m))
        if best_neighbor is None:
            return self._build_plan(
                [start],
                start_time_s,
                speed_mps,
                blocked=True,
                wait_reason="reservation_conflict",
                route_status="blocked",
            )
        plan = self._build_plan(
            [start, best_neighbor[0]],
            start_time_s,
            speed_mps,
            blocked=True,
            wait_reason="reservation_conflict",
            route_status="waiting",
        )
        plan.total_time_s = max(float(plan.total_time_s), wait_window_s)
        return plan

    def plan_route(
        self,
        *,
        start_node_id: str,
        goal_node_id: str,
        start_time_s: float,
        speed_mps: float,
        reservations: GraphReservationTable,
        reservation_horizon_s: float,
        max_detour_ratio: float,
        wait_retry_period_s: float,
        node_hold_s: float,
        ignore_robot_id: str | None = None,
    ) -> GraphRoutePlan:
        start = str(start_node_id)
        goal = str(goal_node_id)
        if start == goal:
            return self._build_plan(
                [start],
                start_time_s,
                speed_mps,
                blocked=False,
                wait_reason=None,
                route_status="at_goal",
            )

        baseline_nodes, baseline_length_m = self.shortest_path(start, goal)
        if not baseline_nodes:
            return self.select_wait_plan(
                start_node_id=start,
                start_time_s=start_time_s,
                speed_mps=speed_mps,
                reservations=reservations,
                wait_retry_period_s=wait_retry_period_s,
                node_hold_s=node_hold_s,
                ignore_robot_id=ignore_robot_id,
            )
        baseline_time_s = float(baseline_length_m) / max(float(speed_mps), 1.0e-6)
        timed_nodes, timed_arrivals, timed_total_s = self._timed_path_with_reservations(
            start,
            goal,
            start_time_s=start_time_s,
            speed_mps=speed_mps,
            reservations=reservations,
            reservation_horizon_s=reservation_horizon_s,
            node_hold_s=node_hold_s,
            ignore_robot_id=ignore_robot_id,
        )
        if not timed_nodes:
            return self.select_wait_plan(
                start_node_id=start,
                start_time_s=start_time_s,
                speed_mps=speed_mps,
                reservations=reservations,
                wait_retry_period_s=wait_retry_period_s,
                node_hold_s=node_hold_s,
                ignore_robot_id=ignore_robot_id,
            )
        if (
            math.isfinite(float(max_detour_ratio))
            and float(max_detour_ratio) > 0.0
            and timed_total_s > (baseline_time_s * float(max_detour_ratio))
        ):
            return self.select_wait_plan(
                start_node_id=start,
                start_time_s=start_time_s,
                speed_mps=speed_mps,
                reservations=reservations,
                wait_retry_period_s=wait_retry_period_s,
                node_hold_s=node_hold_s,
                ignore_robot_id=ignore_robot_id,
            )
        plan = self._build_plan(
            timed_nodes,
            start_time_s,
            speed_mps,
            blocked=False,
            wait_reason=None,
            route_status="active",
        )
        plan.arrival_times_s = [float(value) for value in timed_arrivals]
        plan.total_time_s = float(timed_total_s)
        plan.total_length_m = float(
            sum(
                self.edges[(timed_nodes[index], timed_nodes[index + 1])].length_m
                for index in range(len(timed_nodes) - 1)
            )
        )
        plan.current_node_id = str(timed_nodes[0])
        plan.next_node_id = (None if len(timed_nodes) <= 1 else str(timed_nodes[1]))
        plan.active_waypoint_index = 0 if len(timed_nodes) <= 1 else 1
        return plan


def snap_point_to_graph(
    graph: VineyardMotionGraph,
    point_xy: tuple[float, float],
    *,
    anchor_snap_radius_m: float,
    allowed_node_ids: Iterable[str] | None = None,
) -> str:
    node_id = graph.nearest_node_id(point_xy, allowed_node_ids=allowed_node_ids)
    node = graph.nodes[str(node_id)]
    dist_m = math.hypot(float(node.x) - float(point_xy[0]), float(node.y) - float(point_xy[1]))
    if dist_m <= max(float(anchor_snap_radius_m), 0.0):
        return str(node_id)
    return str(node_id)


def infer_active_waypoint_index(
    pose_xy: tuple[float, float],
    plan: GraphRoutePlan,
    *,
    reach_tol_m: float,
) -> int:
    if len(plan.route_waypoints) <= 1:
        if not plan.route_waypoints:
            return 0
        wx, wy = plan.route_waypoints[0]
        return 1 if math.hypot(float(wx) - float(pose_xy[0]), float(wy) - float(pose_xy[1])) <= float(reach_tol_m) else 0
    current_index = max(1, int(plan.active_waypoint_index))
    px, py = float(pose_xy[0]), float(pose_xy[1])
    while current_index < len(plan.route_waypoints):
        wx, wy = plan.route_waypoints[current_index]
        if math.hypot(float(wx) - px, float(wy) - py) > float(reach_tol_m):
            break
        current_index += 1
    return min(current_index, len(plan.route_waypoints))
