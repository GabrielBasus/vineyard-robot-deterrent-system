import unittest
from unittest.mock import patch

import DeterrentSystem as ds


class RecordingPartitioner:
    instances = []

    def __init__(
        self,
        W,
        H,
        robots_def,
        profiles,
        mode="direct",
        scale=15000.0,
        gamma=1.5,
        partition_types=("UGV",),
    ):
        self.W = float(W)
        self.H = float(H)
        self.ids = [r["id"] for r in robots_def if profiles[r["id"]].type in partition_types]
        self.anchors = {r["id"]: tuple(r["anchor"]) for r in robots_def if r["id"] in self.ids}
        self.healths = {r["id"]: float(r["health"]) for r in robots_def if r["id"] in self.ids}
        self.profiles = profiles
        self.recompute_health_snapshots = []
        self.recompute_count = 0
        self.cells = self._build_cells()
        RecordingPartitioner.instances.append(self)

    def _build_cells(self):
        if not self.ids:
            return []
        width = self.W / float(len(self.ids))
        cells = []
        for idx, _rid in enumerate(self.ids):
            x0 = idx * width
            x1 = self.W if idx == len(self.ids) - 1 else (idx + 1) * width
            cells.append([(x0, 0.0), (x1, 0.0), (x1, self.H), (x0, self.H)])
        return cells

    def update_anchor(self, rid, xy):
        if rid in self.anchors:
            self.anchors[rid] = (float(xy[0]), float(xy[1]))

    def set_health(self, rid, h):
        if rid in self.healths:
            self.healths[rid] = float(h)

    def recompute(self, force=False):
        self.recompute_count += 1
        self.recompute_health_snapshots.append(dict(self.healths))
        if self.recompute_count == 1 and self.ids:
            # Simulate live robot health changing after the initial partition is built.
            # The partitioner's cached health is intentionally left stale here.
            self.profiles[self.ids[0]].health = 0.1
        self.cells = self._build_cells()
        return True

    def cells_for_ids(self):
        return self.cells

    def neighbors_for_id(self, rid):
        return []


class ZonePartitioningHealthSyncTests(unittest.TestCase):
    def test_production_repartition_syncs_live_profile_health_before_recompute(self):
        RecordingPartitioner.instances = []

        with patch.object(ds, "ZonePartitioner", RecordingPartitioner), patch.object(ds, "mon", None):
            frames = ds.run_simulation_frames_persistent(
                W=80.0,
                H=60.0,
                NX=8,
                NY=6,
                Nrobots=2,
                uav_fraction=0.0,
                T_end=0.0,
                dt=1.0,
                fps=1,
                seed=123,
                health_threshold=0.25,
                use_ground_truth=False,
                detect_rate_per_robot=0.0,
                simulation_mode="reactive",
                enable_patrolling=False,
                enable_intervention_feedback=False,
                include_fallback_patrol=False,
                enable_model_scored_deterring=False,
                telemetry_clear_on_start=False,
                telemetry_prompt_save=False,
                report_metrics_end=False,
            )
            next(frames)

        self.assertEqual(len(RecordingPartitioner.instances), 1)
        partitioner = RecordingPartitioner.instances[0]
        self.assertGreaterEqual(len(partitioner.recompute_health_snapshots), 2)

        changed_rid = partitioner.ids[0]
        self.assertGreater(partitioner.recompute_health_snapshots[0][changed_rid], 0.25)
        self.assertEqual(partitioner.recompute_health_snapshots[1][changed_rid], 0.1)


if __name__ == "__main__":
    unittest.main()
