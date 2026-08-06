from collections import deque
from ZonePartitioner import point_in_polygon, point_to_poly_distance

from dataclasses import dataclass
from typing import Any

from tracking_export import export_tracking_value

@dataclass
class RobotProfile:
    id: str
    type: str                 # 'UAV' or 'UGV' (extend as needed)
    speed_mps: float          # ground/air speed used for ETA
    endurance_min: float      # minutes available at target
    battery: float            # 0..1
    health: float             # 0..1 (can reuse your health score)
    has_deterrent: bool       # can perform deterring
    deterrent_eff: float = 1.0  # efficacy weight (e.g., UAV=1.0, UGV horn=0.6)


class SlidingWindowTimeTracker:
    """Tracks reactive/predictive/idle allocation over a rolling time window."""

    VALID_STREAMS = ("reactive", "predictive", "idle")

    def __init__(self, window_s: float):
        self.window_s = max(float(window_s), 1.0e-9)
        self._segments = deque()
        self._totals = {stream: 0.0 for stream in self.VALID_STREAMS}

    def set_window(self, window_s: float, *, now_t: float | None = None):
        self.window_s = max(float(window_s), 1.0e-9)
        if now_t is not None:
            self._prune(float(now_t))

    def record(self, start_t: float, end_t: float, stream: str):
        stream_key = str(stream).strip().lower()
        if stream_key not in self._totals:
            raise ValueError(
                f"stream must be one of {list(self.VALID_STREAMS)}, got: {stream!r}"
            )
        start_t = float(start_t)
        end_t = float(end_t)
        if end_t <= start_t:
            return
        self._prune(end_t)
        segment = [start_t, end_t, stream_key]
        self._segments.append(segment)
        self._totals[stream_key] += (end_t - start_t)
        self._prune(end_t)

    def totals(self, now_t: float) -> dict[str, float]:
        self._prune(float(now_t))
        return {stream: float(value) for stream, value in self._totals.items()}

    def fractions(self, now_t: float) -> dict[str, float]:
        totals = self.totals(float(now_t))
        denom = max(float(self.window_s), 1.0e-9)
        return {
            stream: float(min(max(value / denom, 0.0), 1.0))
            for stream, value in totals.items()
        }

    def predictive_share(self, now_t: float) -> float:
        return float(self.fractions(float(now_t)).get("predictive", 0.0))

    def to_tracking_dict(self, *, now_t: float | None = None, max_items: int = 20) -> dict[str, Any]:
        if now_t is not None:
            self._prune(float(now_t))
        preview_limit = max(int(max_items), 0)
        return {
            "window_s": float(self.window_s),
            "totals": {stream: float(value) for stream, value in self._totals.items()},
            "fractions": (
                self.fractions(float(now_t))
                if now_t is not None else
                {
                    stream: float(min(max(value / max(float(self.window_s), 1.0e-9), 0.0), 1.0))
                    for stream, value in self._totals.items()
                }
            ),
            "segments_total": int(len(self._segments)),
            "segments_preview": [
                {
                    "start_t": float(seg[0]),
                    "end_t": float(seg[1]),
                    "stream": str(seg[2]),
                }
                for seg in list(self._segments)[-preview_limit:]
            ],
        }

    def _prune(self, now_t: float):
        cutoff_t = float(now_t) - float(self.window_s)
        while self._segments:
            start_t, end_t, stream_key = self._segments[0]
            if end_t <= cutoff_t:
                self._totals[stream_key] = max(
                    0.0,
                    float(self._totals.get(stream_key, 0.0)) - float(end_t - start_t),
                )
                self._segments.popleft()
                continue
            if start_t < cutoff_t < end_t:
                removed = float(cutoff_t - start_t)
                self._totals[stream_key] = max(
                    0.0,
                    float(self._totals.get(stream_key, 0.0)) - removed,
                )
                self._segments[0][0] = float(cutoff_t)
            break

class Robot:
    def __init__(self, robot_id, model, zone_polygon, neighbors, border_radius_m=40.0):
        self.robot_id = robot_id
        self.m = model
        self.zone_polygon = zone_polygon
        self.neighbors = neighbors[:]
        self.border_radius_m = float(border_radius_m)
        self.recent_events = deque(maxlen=1000)  # (x,y,t)
        self.dispatch_time_tracker: SlidingWindowTimeTracker | None = None

    def update_zone(self, poly): self.zone_polygon = poly
    
    def update_neighbors(self, neighbors, border_radius_m=None):
        self.neighbors = neighbors[:]
        if border_radius_m is not None: self.border_radius_m = float(border_radius_m)

    def advance_time(self, dt): self.m.advance_time(dt)

    def configure_dispatch_time_tracker(self, window_s: float, *, now_t: float = 0.0):
        if self.dispatch_time_tracker is None:
            self.dispatch_time_tracker = SlidingWindowTimeTracker(window_s)
        else:
            self.dispatch_time_tracker.set_window(window_s, now_t=now_t)

    def record_dispatch_time(self, start_t: float, end_t: float, stream: str):
        if self.dispatch_time_tracker is None:
            return
        self.dispatch_time_tracker.record(start_t, end_t, stream)

    def dispatch_time_allocation(self, now_t: float) -> dict[str, float]:
        if self.dispatch_time_tracker is None:
            return {"reactive": 0.0, "predictive": 0.0, "idle": 0.0}
        return self.dispatch_time_tracker.fractions(now_t)

    def predictive_share(self, now_t: float) -> float:
        if self.dispatch_time_tracker is None:
            return 0.0
        return float(self.dispatch_time_tracker.predictive_share(now_t))

    def ingest_detection(self, x: float, y: float, t: float):
        """Update SESTPP & history; return boundary events only."""
        self.m.advance_time(t - self.m.t_now)

        # if inside my zone, learn & retain
        if point_in_polygon(x, y, self.zone_polygon):
            self.m.add_local_event(x, y)
            self.recent_events.append((x, y, t))

        # boundary relays for neighbors
        boundary_events = []
        dist_edge = point_to_poly_distance((x, y), self.zone_polygon)
        if dist_edge <= self.border_radius_m and self.neighbors:
            for nbr in self.neighbors:
                boundary_events.append({
                    'target_robot': nbr, 'x': float(x), 'y': float(y), 't': float(t),
                    'weight': 0.35, 'sigma': self.m.sigma, 'omega': self.m.omega
                })
        return boundary_events

    def ingest_boundary_event(self, x, y, t, weight, sigma=None, omega=None):
        self.m.advance_time(t - self.m.t_now)
        self.m.add_cross_event(x, y, weight=weight, sigma=sigma, omega=omega)

    def ingest_intervention_event(
        self,
        x,
        y,
        t,
        weight=1.0,
        sigma=None,
        omega_inhib=None,
        *,
        mode=None,
        beta=None,
        action_id=None,
    ):
        self.m.advance_time(t - self.m.t_now)
        self.m.add_intervention_event(x, y, weight=weight, sigma=sigma, omega_inhib=omega_inhib, mode=mode)

    def intervention_boundary_events(
        self,
        x: float,
        y: float,
        t: float,
        weight=1.0,
        *,
        mode,
        sigma,
        omega_inhib,
        beta=None,
        action_id=None,
    ):
        boundary_events = []
        dist_edge = point_to_poly_distance((x, y), self.zone_polygon)
        if dist_edge <= self.border_radius_m and self.neighbors:
            for nbr in self.neighbors:
                event = {
                    'target_robot': nbr, 'x': float(x), 'y': float(y), 't': float(t),
                    'weight': float(weight),
                    'mode': mode,
                    'sigma': float(sigma),
                    'omega_inhib': float(omega_inhib),
                }
                if beta is not None:
                    event['beta'] = float(beta)
                if action_id is not None:
                    event['action_id'] = action_id
                boundary_events.append(event)
        return boundary_events

    def to_tracking_dict(self, *, include_arrays: bool = False, max_items: int = 50):
        recent_preview = list(self.recent_events)[-max(int(max_items), 0):]
        return {
            "robot_id": str(self.robot_id),
            "zone_polygon": [(float(x), float(y)) for (x, y) in self.zone_polygon],
            "neighbors": [str(nbr) for nbr in self.neighbors],
            "border_radius_m": float(self.border_radius_m),
            "recent_events_total": int(len(self.recent_events)),
            "recent_events_preview": recent_preview,
            "dispatch_time_tracker": (
                None
                if self.dispatch_time_tracker is None else
                self.dispatch_time_tracker.to_tracking_dict(max_items=max_items)
            ),
            "model": export_tracking_value(
                self.m,
                include_arrays=include_arrays,
                max_items=max_items,
            ),
        }
