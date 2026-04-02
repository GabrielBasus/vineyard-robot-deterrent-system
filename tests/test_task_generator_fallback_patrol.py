import unittest

from Robot import Robot, RobotProfile
from SESTPP import OnlineSESTPP
from TaskGenerator import TaskGenerator
from TaskGenerator_lab import TaskGenerator as TaskGeneratorLab


class TaskGeneratorFallbackPatrolTests(unittest.TestCase):
    def setUp(self):
        self.zone = [
            (0.0, 0.0),
            (40.0, 0.0),
            (40.0, 40.0),
            (0.0, 40.0),
        ]

    def _build_model(self):
        return OnlineSESTPP(
            x_min=0.0,
            x_max=40.0,
            y_min=0.0,
            y_max=40.0,
            nx=41,
            ny=41,
            sigma=2.0,
            omega=60.0,
            omega_inhib=60.0,
            alpha_in=1.0,
            alpha_cross=0.0,
            alpha_inhib=1.0,
            mu_base=1.0e-6,
            bg_ema=0.0,
        )

    def _profiles(self):
        return {
            "r1": RobotProfile(
                id="r1",
                type="UAV",
                speed_mps=5.0,
                endurance_min=30.0,
                battery=1.0,
                health=1.0,
                has_deterrent=True,
                deterrent_eff=1.0,
            )
        }

    def _fallback_positions(self, generator_cls):
        robot = Robot("r1", self._build_model(), self.zone, [])
        taskgen = generator_cls(merge_radius_m=20.0, patrol_cooldown_s=0.0)
        positions = []
        for now_t in range(5):
            taskgen.clear()
            taskgen.periodic_patrolling(
                robots={"r1": robot},
                now_t=float(now_t),
                hotspot_top_k=1,
                include_fallback_patrol=True,
                enable_model_scored_deterring=False,
                min_hotspot_score=1.0e9,
                patrol_hotspot_filter_mode="absolute",
                horizon_s=60.0,
                profiles=self._profiles(),
                spinup_by_type={"UAV": 0.0},
            )
            rows = taskgen.rows()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["type"], "patrolling")
            self.assertEqual(row["origin"], "fallback")
            positions.append((float(row["x"]), float(row["y"])))
        return positions

    def test_fallback_patrol_uses_distinct_coverage_points(self):
        centroid = (20.0, 20.0)
        for generator_cls in (TaskGenerator, TaskGeneratorLab):
            with self.subTest(generator=generator_cls.__module__):
                positions = self._fallback_positions(generator_cls)
                rounded = [(round(x, 3), round(y, 3)) for (x, y) in positions]
                unique_positions = set(rounded)
                centroid_hits = sum(pos == centroid for pos in rounded)

                self.assertGreaterEqual(len(unique_positions), 4, msg=rounded)
                self.assertLessEqual(centroid_hits, 1, msg=rounded)
                self.assertNotEqual(rounded[0], centroid, msg=rounded)


if __name__ == "__main__":
    unittest.main()
