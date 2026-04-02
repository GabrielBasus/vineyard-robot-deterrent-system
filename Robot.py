from collections import deque
from ZonePartitioner import point_in_polygon, point_to_poly_distance

from dataclasses import dataclass

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

class Robot:
    def __init__(self, robot_id, model, zone_polygon, neighbors, border_radius_m=40.0):
        self.robot_id = robot_id
        self.m = model
        self.zone_polygon = zone_polygon
        self.neighbors = neighbors[:]
        self.border_radius_m = float(border_radius_m)
        self.recent_events = deque(maxlen=1000)  # (x,y,t)

    def update_zone(self, poly): self.zone_polygon = poly
    def update_neighbors(self, neighbors, border_radius_m=None):
        self.neighbors = neighbors[:]
        if border_radius_m is not None: self.border_radius_m = float(border_radius_m)

    def advance_time(self, dt): self.m.advance_time(dt)

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
