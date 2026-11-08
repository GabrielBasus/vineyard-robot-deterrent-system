import unittest

from Robot import Robot, SlidingWindowTimeTracker


class SlidingWindowTimeTrackerTests(unittest.TestCase):
    def test_tracker_prunes_partial_segments_and_reports_fractions(self):
        tracker = SlidingWindowTimeTracker(window_s=10.0)
        tracker.record(0.0, 5.0, "reactive")
        tracker.record(5.0, 10.0, "idle")
        self.assertEqual(
            tracker.fractions(10.0),
            {"reactive": 0.5, "predictive": 0.0, "idle": 0.5},
        )

        tracker.record(10.0, 15.0, "predictive")
        frac = tracker.fractions(15.0)
        self.assertAlmostEqual(frac["reactive"], 0.0)
        self.assertAlmostEqual(frac["idle"], 0.5)
        self.assertAlmostEqual(frac["predictive"], 0.5)

    def test_robot_wrapper_exposes_predictive_share(self):
        robot = Robot("r1", model=None, zone_polygon=[], neighbors=[])
        robot.configure_dispatch_time_tracker(20.0, now_t=0.0)
        robot.record_dispatch_time(0.0, 5.0, "reactive")
        robot.record_dispatch_time(5.0, 15.0, "predictive")
        alloc = robot.dispatch_time_allocation(15.0)
        self.assertAlmostEqual(alloc["reactive"], 0.25)
        self.assertAlmostEqual(alloc["predictive"], 0.50)
        self.assertAlmostEqual(alloc["idle"], 0.0)
        self.assertAlmostEqual(robot.predictive_share(15.0), 0.50)


if __name__ == "__main__":
    unittest.main()
