import unittest

from DeterrentSystem import (
    _build_dispatch_order_preview,
    _ordered_dispatch_candidates,
    _select_patrol_replacement_task,
)


def _task(
    *,
    task_type,
    origin,
    mode=None,
    score=0.0,
    utility=None,
    predicted_deltaJ=0.0,
    deltaJ_per_cost=0.0,
    eta_s=0.0,
    p_event=0.0,
    selection_weight=1.0,
    support=0,
    time=0.0,
    assigned_primary=None,
    state=None,
    task_id=None,
):
    return {
        "id": task_id,
        "type": str(task_type),
        "origin": str(origin),
        "mode": mode,
        "score": float(score),
        "utility": float(score if utility is None else utility),
        "predicted_deltaJ": float(predicted_deltaJ),
        "deltaJ_per_cost": float(deltaJ_per_cost),
        "eta_s": float(eta_s),
        "p_event": float(p_event),
        "selection_weight": float(selection_weight),
        "support": int(support),
        "time": float(time),
        "assigned_primary": assigned_primary,
        "state": state,
    }


class DispatchPriorityOrderingTests(unittest.TestCase):
    def test_direct_detection_stays_first_and_preventive_beats_low_patrol(self):
        direct_detection = _task(
            task_type="deterring",
            origin="detection",
            mode=None,
            score=0.0,
            utility=0.0,
            eta_s=2.0,
            time=10.0,
        )
        low_patrol = _task(
            task_type="patrolling",
            origin="hotspot",
            score=2.0,
            utility=2.0,
            eta_s=20.0,
            time=10.0,
        )
        high_preventive = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            score=14.0,
            utility=14.0,
            predicted_deltaJ=25.0,
            deltaJ_per_cost=5.0,
            eta_s=6.0,
            p_event=0.9,
            time=10.0,
        )

        ordered = _ordered_dispatch_candidates([low_patrol, high_preventive, direct_detection])
        self.assertEqual(ordered[0]["origin"], "detection")
        self.assertEqual(ordered[1]["origin"], "model_hotspot")
        self.assertEqual(ordered[2]["origin"], "hotspot")

        preview = _build_dispatch_order_preview([low_patrol, high_preventive, direct_detection], preview_limit=3)
        self.assertEqual(preview[0]["ordering_bucket"], "direct_detection")
        self.assertEqual(preview[1]["ordering_bucket"], "regular_competition")

        active_tasks = [
            _task(
                task_type="patrolling",
                origin="hotspot",
                score=1.0,
                utility=1.0,
                eta_s=18.0,
                assigned_primary="r1",
                state="active",
                task_id=101,
            )
        ]
        replacement = _select_patrol_replacement_task(active_tasks, "r1", ordered[1])
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement["id"], 101)

    def test_weaker_preventive_does_not_displace_existing_patrol(self):
        active_tasks = [
            _task(
                task_type="patrolling",
                origin="hotspot",
                score=6.0,
                utility=6.0,
                eta_s=4.0,
                assigned_primary="r1",
                state="active",
                task_id=202,
            )
        ]
        weak_preventive = _task(
            task_type="deterring",
            origin="model_detection_cluster",
            mode="formation",
            score=2.0,
            utility=2.0,
            predicted_deltaJ=3.0,
            deltaJ_per_cost=1.0,
            eta_s=12.0,
        )

        replacement = _select_patrol_replacement_task(active_tasks, "r1", weak_preventive)
        self.assertIsNone(replacement)

    def test_regular_order_uses_eta_after_value_and_delta_terms(self):
        slower = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            score=10.0,
            utility=10.0,
            predicted_deltaJ=12.0,
            deltaJ_per_cost=3.0,
            eta_s=14.0,
        )
        faster = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="biosonic",
            score=10.0,
            utility=10.0,
            predicted_deltaJ=12.0,
            deltaJ_per_cost=3.0,
            eta_s=5.0,
        )

        ordered = _ordered_dispatch_candidates([slower, faster])
        self.assertEqual(ordered[0]["mode"], "biosonic")
        self.assertEqual(ordered[1]["mode"], "laser")


if __name__ == "__main__":
    unittest.main()
