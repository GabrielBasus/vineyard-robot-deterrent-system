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
        type(self).instances.append(self)

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


class ExcludingRecordingPartitioner(RecordingPartitioner):
    def __init__(self, *args, **kwargs):
        self.excluded_ids = set()
        super().__init__(*args, **kwargs)
        self.all_ids = self.ids[:]
        self.exclusion_snapshots = []

    def set_excluded_ids(self, excluded_ids):
        self.excluded_ids = {str(rid) for rid in (excluded_ids or [])}
        self.ids = [rid for rid in self.all_ids if rid not in self.excluded_ids]
        self.exclusion_snapshots.append(set(self.excluded_ids))


class RecordingMonitor:
    instances = []

    def __init__(self, cells, params):
        self.cells = list(cells)
        self.params = params
        RecordingMonitor.instances.append(self)

    def record(self, *args, **kwargs):
        return None

    def robustness(self):
        return {"global": 0.0}


class ZonePartitioningHealthSyncTests(unittest.TestCase):
    def _drain(self, frames):
        for _frame in frames:
            pass

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

    def test_no_trigger_does_not_recompute_or_rebuild_monitors(self):
        RecordingPartitioner.instances = []
        RecordingMonitor.instances = []

        with (
            patch.object(ds, "ZonePartitioner", RecordingPartitioner),
            patch.object(ds, "RobotMonitor", RecordingMonitor),
            patch.object(ds, "mon", None),
        ):
            frames = ds.run_simulation_frames_persistent(
                W=80.0,
                H=60.0,
                NX=8,
                NY=6,
                Nrobots=2,
                uav_fraction=0.0,
                T_end=3.0,
                dt=1.0,
                fps=1,
                seed=123,
                health_threshold=0.01,
                health_retire_threshold=0.0,
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
            self._drain(frames)

        partitioner = RecordingPartitioner.instances[0]
        self.assertEqual(partitioner.recompute_count, 1)
        self.assertEqual(len(RecordingMonitor.instances), 2)

    def test_threshold_event_repartitions_once_while_health_remains_low(self):
        RecordingPartitioner.instances = []

        with patch.object(ds, "ZonePartitioner", RecordingPartitioner), patch.object(ds, "mon", None):
            frames = ds.run_simulation_frames_persistent(
                W=80.0,
                H=60.0,
                NX=8,
                NY=6,
                Nrobots=2,
                uav_fraction=0.0,
                T_end=3.0,
                dt=1.0,
                fps=1,
                seed=123,
                health_threshold=0.25,
                health_retire_threshold=0.0,
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
            self._drain(frames)

        partitioner = RecordingPartitioner.instances[0]
        self.assertEqual(partitioner.recompute_count, 2)

    def test_retired_robot_is_excluded_from_recomputed_partition(self):
        ExcludingRecordingPartitioner.instances = []

        with patch.object(ds, "ZonePartitioner", ExcludingRecordingPartitioner), patch.object(ds, "mon", None):
            frames = ds.run_simulation_frames_persistent(
                W=80.0,
                H=60.0,
                NX=8,
                NY=6,
                Nrobots=2,
                uav_fraction=0.0,
                T_end=1.0,
                dt=1.0,
                fps=1,
                seed=123,
                health_threshold=0.25,
                health_retire_threshold=0.15,
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
            frames = list(frames)

        partitioner = ExcludingRecordingPartitioner.instances[0]
        changed_rid = partitioner.all_ids[0]
        self.assertIn(changed_rid, partitioner.excluded_ids)
        self.assertNotIn(changed_rid, partitioner.ids)
        last = frames[-1] if frames else {}
        command_ids = {
            cmd.get("robot_id")
            for cmd in last.get("motion_commands", [])
        }
        self.assertNotIn(changed_rid, command_ids)
        self.assertNotIn(changed_rid, last.get("poses", {}))
        self.assertNotIn(changed_rid, last.get("robot_states", {}))
        self.assertNotIn(changed_rid, last.get("motion_graph_states", {}))

    def test_retired_robot_returns_after_recharge_time(self):
        ExcludingRecordingPartitioner.instances = []

        with patch.object(ds, "ZonePartitioner", ExcludingRecordingPartitioner), patch.object(ds, "mon", None):
            frames = ds.run_simulation_frames_persistent(
                W=80.0,
                H=60.0,
                NX=8,
                NY=6,
                Nrobots=2,
                uav_fraction=0.0,
                T_end=3.0,
                dt=1.0,
                fps=1,
                seed=123,
                health_threshold=0.25,
                health_retire_threshold=0.15,
                health_recharge_time_s=2.0,
                health_recovered_value=1.0,
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
            last = None
            for frame in frames:
                last = frame

        partitioner = ExcludingRecordingPartitioner.instances[0]
        changed_rid = partitioner.all_ids[0]
        self.assertIn(changed_rid, partitioner.ids)
        self.assertNotIn(changed_rid, partitioner.excluded_ids)
        self.assertEqual(partitioner.recompute_health_snapshots[-1][changed_rid], 1.0)
        metrics = (last or {}).get("metrics_compact") or (last or {}).get("metrics") or {}
        self.assertEqual(metrics.get("health_retirement_total"), 1)
        self.assertEqual(metrics.get("health_return_total"), 1)
        self.assertEqual(metrics.get("retired_robot_count"), 0)


if __name__ == "__main__":
    unittest.main()
