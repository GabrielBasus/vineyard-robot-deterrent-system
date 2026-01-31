from __future__ import annotations

"""Helpers to import the legacy Core simulation modules.

The Core folder lives one level above the ROS workspace:
  vineyard-robot-deterrent-ROS/Core

We add it to sys.path at runtime so the ROS nodes can reuse the existing
ZonePartitioner, SESTPP, Robot, and TaskGenerator logic.
"""

from pathlib import Path
import sys
from typing import Iterable


def _candidate_core_paths() -> Iterable[Path]:
    here = Path(__file__).resolve()

    # ros2_ws/src/bird_deterrent_vineyard/bird_deterrent_vineyard
    # -> ros2_ws -> vineyard-robot-deterrent-ROS -> Core
    yield here.parents[5] / "Core"
    yield here.parents[4] / "Core"

    # Also try relative to the current working directory.
    yield Path.cwd().resolve().parent / "Core"
    yield Path.cwd().resolve() / "Core"


def ensure_core_on_path() -> Path:
    """Return the resolved Core path after adding it to sys.path.

    Raises:
        FileNotFoundError: if the Core folder cannot be located.
    """
    for core_path in _candidate_core_paths():
        if core_path.exists() and core_path.is_dir():
            core_str = str(core_path)
            if core_str not in sys.path:
                sys.path.insert(0, core_str)
            return core_path
    raise FileNotFoundError("Could not locate the Core folder for imports.")


def import_core_modules():
    """Import and return the core modules used by the ROS nodes."""
    ensure_core_on_path()

    # Import locally so ensure_core_on_path runs first.
    import ZonePartitioner as zone_partitioner  # type: ignore
    import SESTPP as sestpp  # type: ignore
    import Robot as robot_mod  # type: ignore
    import TaskGenerator as task_mod  # type: ignore

    return zone_partitioner, sestpp, robot_mod, task_mod
