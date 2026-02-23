# telemetry_sim.py
#
# Lightweight telemetry/monitoring for the Python simulation version of the
# vineyard deterrent system.
#
# Features:
#   - Record robot poses, zones, tasks, messages, and hotspots.
#   - Export to CSV at the end of the run (export_csv).
#   - Incremental "live" CSV flush (flush_live) for a separate dashboard.
#
# The API is intentionally simple so it can be swapped later with a ROS
# telemetry class (TelemetryROS) using the same method names.
#
# Typical usage inside your simulation:
#
#   from telemetry_sim import TelemetrySim
#   mon = TelemetrySim(enabled=True)
#
#   # after building robots, zones, and initial pose:
#   for r in robots_def:
#       rid = r['id']
#       mon.set_zone(rid, robots[rid].zone_polygon, t=0.0)
#       x0, y0 = pose[rid]
#       mon.pose(t=0.0, rid=rid, x=x0, y=y0)
#
#   # when detections / tasks / messages happen:
#   mon.event_task('spawn', task_dict)
#   mon.event_task('assign', task_dict)
#   mon.event_task('complete', task_dict)
#   mon.message(t, kind='boundary_event', source=src_id, target=dst_id, data=payload)
#
#   # each simulation step, before yielding a frame:
#   for rid in robots:
#       x, y = pose[rid]
#       mon.pose(t, rid, x, y)
#       hs = robots[rid].m.hotspots(top_k=3, merge_radius=20.0, use_excess=True,
#                                   mask_poly=robots[rid].zone_polygon)
#       mon.hotspots(t, rid, hs)
#
#   # periodically (for live dashboard):
#   mon.flush_live('telemetry_live')   # appends to CSVs incrementally
#
#   # at the end:
#   mon.export_csv('telemetry_out')    # writes full CSVs from buffers

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, List, Optional, Sequence, Tuple
import csv
import os
import shutil
import time

Point = Tuple[float, float]
Poly = List[Point]


# ---------------------- data rows for CSV/logging ---------------------- #

@dataclass
class PoseRow:
    t: float
    rid: str
    x: float
    y: float


@dataclass
class ZoneRow:
    t: float
    rid: str
    poly: str  # serialized "x1 y1|x2 y2|..."


@dataclass
class TaskRow:
    t: float
    event: str          # 'spawn' | 'assign' | 'complete' | 'cancel'
    id: str
    rid_primary: Optional[str]
    rid_secondary: Optional[str]
    type: str
    x: float
    y: float
    score: float
    extra: str          # any extra fields packed as str(dict)


@dataclass
class MessageRow:
    t: float
    kind: str           # 'boundary_event' | 'debug' | ...
    source: str
    target: str
    data: str           # stringified payload


@dataclass
class HotspotRow:
    t: float
    rid: str
    rank: int
    x: float
    y: float
    score: float


@dataclass
class RobotDiagRow:
    t: float
    rid: str
    battery: float
    state: str
    task: str
    goal_x: float
    goal_y: float
    eff_goal_x: float
    eff_goal_y: float
    dist_to_goal: float
    lane_cur: float
    lane_tgt: float
    at_headland: int


def _ser_poly(poly: Optional[Poly]) -> str:
    """Serialize polygon to a compact string: 'x1 y1|x2 y2|...'."""
    if not poly:
        return ""
    return "|".join(f"{float(x):.3f} {float(y):.3f}" for x, y in poly)


# ------------------------------ Telemetry ------------------------------ #

class TelemetrySim:
    """
    Pure-Python telemetry helper for the simulator.

    Methods:
        - pose(t, rid, x, y)
        - set_zone(rid, poly, t=0.0)
        - event_task(event, task_dict)
        - hotspots(t, rid, hs)
        - message(t, kind, source, target, data)
        - export_csv(out_dir)
        - flush_live(out_dir, min_interval_s=0.5)
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

        self._poses: List[PoseRow] = []
        self._zones: List[ZoneRow] = []
        self._tasks: List[TaskRow] = []
        self._msgs:  List[MessageRow] = []
        self._hots:  List[HotspotRow] = []
        self._rdiag: List[RobotDiagRow] = []

        # for incremental flush
        self._last_flush = 0.0

    # -------- zones & poses -------- #

    def pose(self, t: float, rid: str, x: float, y: float) -> None:
        """Record robot pose at time t."""
        if not self.enabled:
            return
        self._poses.append(PoseRow(t=float(t), rid=str(rid),
                                   x=float(x), y=float(y)))

    def set_zone(self, rid: str, poly: Optional[Poly], t: float = 0.0) -> None:
        """Record the polygon zone for robot rid (e.g., after partitioning)."""
        if not self.enabled:
            return
        self._zones.append(ZoneRow(t=float(t), rid=str(rid),
                                   poly=_ser_poly(poly)))

    # -------- tasks -------- #

    def event_task(self, event: str, tr: Dict[str, Any]) -> None:
        """
        Record a task event.

        event:
            'spawn'   - created
            'assign'  - assigned to robot(s)
            'complete' - finished
            'cancel'  - dropped

        tr: task dict that you already use elsewhere; fields pulled:
            id, type, x, y, score, assigned_primary, assigned_secondary, time
        """
        if not self.enabled:
            return

        core_keys = {
            "time",
            "id",
            "assigned_primary",
            "assigned_secondary",
            "type",
            "x",
            "y",
            "score",
        }
        extra = {k: v for k, v in tr.items() if k not in core_keys}

        row = TaskRow(
            t=float(tr.get("time", 0.0)),
            event=str(event),
            id=str(tr.get("id", "")),
            rid_primary=tr.get("assigned_primary"),
            rid_secondary=tr.get("assigned_secondary"),
            type=str(tr.get("type", "")),
            x=float(tr.get("x", 0.0)),
            y=float(tr.get("y", 0.0)),
            score=float(tr.get("score", 0.0)),
            extra=str(extra),
        )
        self._tasks.append(row)

    # -------- messages (e.g., boundary events) -------- #

    def message(self, t: float, kind: str, source: str, target: str, data: Any) -> None:
        """Record a message between robots (or system-level)."""
        if not self.enabled:
            return
        self._msgs.append(
            MessageRow(
                t=float(t),
                kind=str(kind),
                source=str(source),
                target=str(target),
                data=str(data),
            )
        )

    # -------- hotspots (SESTPP view) -------- #

    def hotspots(self, t: float, rid: str, hs: Sequence[Dict[str, Any]] | None) -> None:
        """
        Record up to a few hotspots from a robot's SESTPP model.

        hs: sequence of dicts with at least 'x', 'y', 'score'.
        """
        if not self.enabled or not hs:
            return

        for rank, h in enumerate(hs, start=1):
            self._hots.append(
                HotspotRow(
                    t=float(t),
                    rid=str(rid),
                    rank=int(rank),
                    x=float(h.get("x", 0.0)),
                    y=float(h.get("y", 0.0)),
                    score=float(h.get("score", 0.0)),
                )
            )

    def robot_diag(
        self,
        t: float,
        rid: str,
        battery: float,
        state: str,
        task: str,
        goal_x: float,
        goal_y: float,
        eff_goal_x: float,
        eff_goal_y: float,
        dist_to_goal: float,
        lane_cur: float,
        lane_tgt: float,
        at_headland: int,
    ) -> None:
        if not self.enabled:
            return
        self._rdiag.append(
            RobotDiagRow(
                t=float(t),
                rid=str(rid),
                battery=float(battery),
                state=str(state),
                task=str(task),
                goal_x=float(goal_x),
                goal_y=float(goal_y),
                eff_goal_x=float(eff_goal_x),
                eff_goal_y=float(eff_goal_y),
                dist_to_goal=float(dist_to_goal),
                lane_cur=float(lane_cur),
                lane_tgt=float(lane_tgt),
                at_headland=int(at_headland),
            )
        )

    # -------- export / live flush -------- #

    def export_csv(self, out_dir: str) -> None:
        """Write all buffered telemetry to CSV files in out_dir."""
        if not self.enabled:
            return

        os.makedirs(out_dir, exist_ok=True)
        self._write_csv(os.path.join(out_dir, "robot_poses.csv"), self._poses, PoseRow)
        self._write_csv(os.path.join(out_dir, "zones.csv"),       self._zones, ZoneRow)
        self._write_csv(os.path.join(out_dir, "tasks.csv"),       self._tasks, TaskRow)
        self._write_csv(os.path.join(out_dir, "messages.csv"),    self._msgs,  MessageRow)
        self._write_csv(os.path.join(out_dir, "hotspots.csv"),    self._hots,  HotspotRow)
        self._write_csv(os.path.join(out_dir, "robot_diagnostics.csv"), self._rdiag, RobotDiagRow)

    def flush_live(self, out_dir: str, min_interval_s: float = 0.5) -> None:
        """
        Append buffered telemetry to CSVs, then clear buffers.

        Call this in your simulation loop (e.g., every step or every few steps).
        min_interval_s throttles disk writes to avoid overdoing I/O.
        """
        if not self.enabled:
            return

        now = time.time()
        if (now - self._last_flush) < min_interval_s:
            return
        self._last_flush = now

        os.makedirs(out_dir, exist_ok=True)
        self._append_csv(os.path.join(out_dir, "robot_poses.csv"), self._poses, PoseRow, clear=True)
        self._append_csv(os.path.join(out_dir, "zones.csv"),       self._zones, ZoneRow, clear=True)
        self._append_csv(os.path.join(out_dir, "tasks.csv"),       self._tasks, TaskRow, clear=True)
        self._append_csv(os.path.join(out_dir, "messages.csv"),    self._msgs,  MessageRow, clear=True)
        self._append_csv(os.path.join(out_dir, "hotspots.csv"),    self._hots,  HotspotRow, clear=True)
        self._append_csv(os.path.join(out_dir, "robot_diagnostics.csv"), self._rdiag, RobotDiagRow, clear=True)

    def prepare_live_dir(
        self,
        out_dir: str,
        clear_existing: bool = True,
        prompt_save_existing: bool = False,
        backup_on_save: bool = True,
    ) -> None:
        """
        Prepare live telemetry directory at the start of a run.

        Behavior:
        - If clear_existing=False: ensure directory exists, do nothing else.
        - If clear_existing=True and files exist:
            - If prompt_save_existing=True: ask user whether to save previous run.
            - If save requested and backup_on_save=True: move directory to timestamped backup.
            - Otherwise: remove known telemetry CSVs in-place.
        """
        if not self.enabled:
            return

        os.makedirs(out_dir, exist_ok=True)
        known_files = [
            "robot_poses.csv",
            "zones.csv",
            "tasks.csv",
            "messages.csv",
            "hotspots.csv",
            "robot_diagnostics.csv",
        ]
        existing = [f for f in known_files if os.path.exists(os.path.join(out_dir, f))]
        if not clear_existing or not existing:
            return

        save_existing = False
        if prompt_save_existing:
            try:
                ans = input(
                    f"Telemetry folder '{out_dir}' has previous data. Save backup before overwrite? [y/N]: "
                ).strip().lower()
                save_existing = ans in ("y", "yes")
            except Exception:
                save_existing = False

        if save_existing and backup_on_save:
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = f"{out_dir}_backup_{ts}"
            # Move full folder so all prior artifacts are preserved.
            shutil.move(out_dir, backup_dir)
            os.makedirs(out_dir, exist_ok=True)
            print(f"[telemetry] previous run moved to: {backup_dir}")
            return

        for fname in existing:
            try:
                os.remove(os.path.join(out_dir, fname))
            except OSError:
                pass
        print(f"[telemetry] cleared existing CSVs in: {out_dir}")

    # -------- internal CSV helpers -------- #

    @staticmethod
    def _write_csv(path: str, rows: List[Any], row_cls: Any) -> None:
        field_names = [f.name for f in fields(row_cls)]
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(field_names)
            for r in rows:
                w.writerow([getattr(r, name) for name in field_names])

    @staticmethod
    def _append_csv(path: str, rows: List[Any], row_cls: Any, clear: bool = False) -> None:
        if not rows:
            return
        field_names = [f.name for f in fields(row_cls)]
        file_exists = os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow(field_names)
            for r in rows:
                w.writerow([getattr(r, name) for name in field_names])
        if clear:
            rows.clear()


# Optional: small helper to print a quick snapshot in the console
def brief_console_dump(mon: TelemetrySim, last_t: float | None = None, max_tasks: int = 10) -> str:
    """
    Create a short human-readable summary of latest poses and recent tasks.

    last_t: if provided, show only data with t >= last_t
    """
    if not mon.enabled:
        return "(telemetry disabled)"

    latest_pose: Dict[str, PoseRow] = {}
    for p in mon._poses:
        if last_t is not None and p.t < last_t:
            continue
        latest_pose[p.rid] = p

    # group hotspots by rid
    latest_hots: Dict[str, List[HotspotRow]] = {}
    for h in mon._hots:
        if last_t is not None and h.t < last_t:
            continue
        latest_hots.setdefault(h.rid, []).append(h)

    # recent tasks
    recent_tasks = [tr for tr in mon._tasks if last_t is None or tr.t >= last_t]
    recent_tasks = recent_tasks[-max_tasks:]

    lines: List[str] = []
    lines.append("== TelemetrySim brief ==")
    for rid, p in latest_pose.items():
        lines.append(f"pose[{rid}] t={p.t:.1f} -> ({p.x:.1f}, {p.y:.1f})")
        hs = latest_hots.get(rid, [])[:3]
        if hs:
            hs_str = ", ".join(f"({h.x:.1f},{h.y:.1f}) s={h.score:.3g}" for h in hs)
            lines.append(f"  hotspots: {hs_str}")

    if recent_tasks:
        lines.append("-- recent tasks --")
        for tr in recent_tasks:
            lines.append(
                f"{tr.t:.1f} {tr.event} {tr.type}#{tr.id[:6]} "
                f"@({tr.x:.1f},{tr.y:.1f}) -> P:{tr.rid_primary} S:{tr.rid_secondary}"
            )

    return "\n".join(lines)
