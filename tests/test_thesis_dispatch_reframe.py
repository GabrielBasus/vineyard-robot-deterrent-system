import unittest

import numpy as np

import DeterrentSystem as ds
from action_schema import task_action, task_action_kind, task_action_name


_DETER_MODES = {
    "formation": {"beta": 0.30, "omega": 800.0, "sigma": 18.0},
    "laser": {"beta": 0.45, "omega": 400.0, "sigma": 10.0},
    "biosonic": {"beta": 0.25, "omega": 600.0, "sigma": 20.0},
}


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
    merged_detection_count=1,
):
    task = {
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
        "merged_detection_count": int(merged_detection_count),
    }
    task["action"] = task_action(
        task,
        deterring_modes=_DETER_MODES,
        default_service_time_s=20.0,
    )
    return task


class ThesisDispatchHelperTests(unittest.TestCase):
    def test_dispatch_policy_settings_accept_res_rand_alias(self):
        settings = ds._resolve_dispatch_policy_settings(
            dispatch_policy="res-rand",
            reservation_fraction=0.25,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=1.0,
            predictive_selection_policy="utility",
        )
        self.assertEqual(settings["dispatch_policy"], "res")
        self.assertEqual(settings["predictive_selection_policy"], "random")

    def test_dispatch_policy_settings_accept_soft_reserved_policy(self):
        settings = ds._resolve_dispatch_policy_settings(
            dispatch_policy="res-soft",
            reservation_fraction=0.25,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="utility",
        )
        self.assertEqual(settings["dispatch_policy"], "res-soft")
        self.assertEqual(settings["reservation_softening_alpha"], 2.0)

    def test_dispatch_policy_settings_accept_reactive_first_policy(self):
        settings = ds._resolve_dispatch_policy_settings(
            dispatch_policy="reactive-first",
            reservation_fraction=0.0,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=1.0,
            predictive_selection_policy="utility",
        )
        self.assertEqual(settings["dispatch_policy"], "reactive-first")

    def test_dispatch_policy_settings_accept_adaptive_reserved_policy(self):
        settings = ds._resolve_dispatch_policy_settings(
            dispatch_policy="res-adaptive",
            reservation_fraction=0.25,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            reservation_age_softening_beta=2.0,
            reservation_age_gate=0.5,
            predictive_selection_policy="utility",
        )
        self.assertEqual(settings["dispatch_policy"], "res-adaptive")
        self.assertEqual(settings["reservation_age_softening_beta"], 2.0)
        self.assertEqual(settings["reservation_age_gate"], 0.5)

    def test_dispatch_policy_settings_accept_next_formulation_policies(self):
        feasible = ds._resolve_dispatch_policy_settings(
            dispatch_policy="res-feasible",
            reservation_fraction=0.25,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="utility",
        )
        idle_feasible = ds._resolve_dispatch_policy_settings(
            dispatch_policy="res-idle-feasible",
            reservation_fraction=0.25,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="utility",
        )
        confidence = ds._resolve_dispatch_policy_settings(
            dispatch_policy="res-confidence",
            reservation_fraction=0.25,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="confidence-weighted",
        )
        idle_confidence = ds._resolve_dispatch_policy_settings(
            dispatch_policy="res-idle-feasible-confidence",
            reservation_fraction=0.25,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="confidence-weighted",
        )
        self.assertEqual(feasible["dispatch_policy"], "res-feasible")
        self.assertEqual(idle_feasible["dispatch_policy"], "res-idle-feasible")
        self.assertEqual(confidence["dispatch_policy"], "res-confidence")
        self.assertEqual(confidence["predictive_selection_policy"], "confidence-weighted")
        self.assertEqual(idle_confidence["dispatch_policy"], "res-idle-feasible-confidence")

        risk_adjusted = ds._resolve_dispatch_policy_settings(
            dispatch_policy="res-opportunity-cost",
            reservation_fraction=0.25,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="utility",
        )
        self.assertEqual(risk_adjusted["dispatch_policy"], "res-risk-adjusted")
        self.assertEqual(risk_adjusted["predictive_selection_policy"], "risk-adjusted")

    def test_dispatch_policy_settings_accept_time_aware_selection(self):
        settings = ds._resolve_dispatch_policy_settings(
            dispatch_policy="res",
            reservation_fraction=0.25,
            reservation_window_s=600.0,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="time-aware",
        )
        self.assertEqual(settings["dispatch_policy"], "res")
        self.assertEqual(settings["predictive_selection_policy"], "time-aware")

    def test_reactive_override_slack_uses_task_age_and_eta(self):
        reactive_task = _task(task_type="deterring", origin="detection", time=25.0, eta_s=12.0)
        slack = ds._reactive_override_slack_seconds(
            reactive_task,
            now_t=50.0,
            reactive_override_slack_s=60.0,
            eta_s=float(reactive_task["eta_s"]),
        )
        self.assertAlmostEqual(slack, 23.0)

    def test_predictive_task_expiry_uses_deadline_slack_with_eta(self):
        predictive_task = _task(
            task_type="patrolling",
            origin="hotspot",
            time=100.0,
            eta_s=20.0,
        )
        predictive_task["required_arrival_by_t"] = 150.0
        predictive_task["event_time"] = 150.0

        self.assertFalse(
            ds._predictive_task_has_expired(
                predictive_task,
                now_t=110.0,
                eta_s=15.0,
                predictive_expiry_grace_s=0.0,
            )
        )
        self.assertTrue(
            ds._predictive_task_has_expired(
                predictive_task,
                now_t=140.0,
                eta_s=15.0,
                predictive_expiry_grace_s=0.0,
            )
        )

    def test_reserved_policy_prefers_predictive_when_share_below_target(self):
        reactive_task = _task(task_type="deterring", origin="detection", time=50.0, eta_s=5.0)
        predictive_task = _task(
            task_type="patrolling",
            origin="fallback",
            score=10.0,
            utility=10.0,
            predicted_deltaJ=20.0,
            deltaJ_per_cost=4.0,
            eta_s=4.0,
        )
        selected, urgent = ds._select_dispatch_policy_task(
            [reactive_task, predictive_task],
            dispatch_policy="res",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=1.0,
            predictive_selection_policy="utility",
            now_t=60.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertFalse(urgent)
        self.assertEqual(selected["type"], "patrolling")

    def test_reactive_first_policy_keeps_reactive_first(self):
        reactive_task = _task(task_type="deterring", origin="detection", time=20.0, eta_s=6.0)
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            score=100.0,
            utility=100.0,
            predicted_deltaJ=100.0,
            deltaJ_per_cost=50.0,
            eta_s=1.0,
        )
        selected, urgent = ds._select_dispatch_policy_task(
            [predictive_task, reactive_task],
            dispatch_policy="reactive-first",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=1.0,
            predictive_selection_policy="utility",
            now_t=25.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertFalse(urgent)
        self.assertEqual(selected["origin"], "detection")

    def test_unconstrained_policy_uses_mixed_greedy_ordering(self):
        reactive_task = _task(
            task_type="deterring",
            origin="detection",
            score=1.0,
            utility=1.0,
            time=20.0,
            eta_s=6.0,
        )
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            score=100.0,
            utility=100.0,
            predicted_deltaJ=100.0,
            deltaJ_per_cost=50.0,
            eta_s=1.0,
            p_event=0.9,
            selection_weight=1.0,
        )

        selected, urgent = ds._select_dispatch_policy_task(
            [predictive_task, reactive_task],
            dispatch_policy="unc",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=1.0,
            predictive_selection_policy="utility",
            now_t=25.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )

        self.assertFalse(urgent)
        self.assertEqual(selected["origin"], "model_hotspot")
        self.assertEqual(task_action_name(selected), "laser")

    def test_unconstrained_policy_still_honors_urgent_reactive_override(self):
        reactive_task = _task(
            task_type="deterring",
            origin="detection",
            score=1.0,
            utility=1.0,
            time=0.0,
            eta_s=20.0,
        )
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            score=100.0,
            utility=100.0,
            predicted_deltaJ=100.0,
            deltaJ_per_cost=50.0,
            eta_s=1.0,
            p_event=0.9,
        )

        selected, urgent = ds._select_dispatch_policy_task(
            [predictive_task, reactive_task],
            dispatch_policy="unc",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=10.0,
            reservation_softening_alpha=1.0,
            predictive_selection_policy="utility",
            now_t=20.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )

        self.assertTrue(urgent)
        self.assertEqual(selected["origin"], "detection")

    def test_urgent_reactive_override_beats_predictive_claim(self):
        reactive_task = _task(task_type="deterring", origin="detection", time=0.0, eta_s=20.0)
        predictive_task = _task(
            task_type="patrolling",
            origin="fallback",
            score=10.0,
            utility=10.0,
            predicted_deltaJ=20.0,
            deltaJ_per_cost=4.0,
            eta_s=1.0,
        )
        selected, urgent = ds._select_dispatch_policy_task(
            [reactive_task, predictive_task],
            dispatch_policy="res",
            predictive_share=0.0,
            reservation_fraction=0.40,
            reactive_override_slack_s=10.0,
            reservation_softening_alpha=1.0,
            predictive_selection_policy="utility",
            now_t=20.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertTrue(urgent)
        self.assertEqual(selected["origin"], "detection")

    def test_soft_reserved_policy_relaxes_predictive_claim_under_reactive_pressure(self):
        reactive_tasks = [
            _task(task_type="deterring", origin="detection", time=50.0 + idx, eta_s=5.0)
            for idx in range(4)
        ]
        predictive_task = _task(
            task_type="patrolling",
            origin="fallback",
            score=10.0,
            utility=10.0,
            predicted_deltaJ=20.0,
            deltaJ_per_cost=4.0,
            eta_s=2.0,
        )
        hard_selected, hard_urgent = ds._select_dispatch_policy_task(
            reactive_tasks + [predictive_task],
            dispatch_policy="res",
            predictive_share=0.10,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="utility",
            now_t=60.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        soft_selected, soft_urgent = ds._select_dispatch_policy_task(
            reactive_tasks + [predictive_task],
            dispatch_policy="res-soft",
            predictive_share=0.10,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="utility",
            now_t=60.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertFalse(hard_urgent)
        self.assertFalse(soft_urgent)
        self.assertEqual(hard_selected["type"], "patrolling")
        self.assertEqual(soft_selected["origin"], "detection")

    def test_adaptive_reserved_policy_blocks_predictive_claim_when_reactive_age_grows(self):
        reactive_tasks = [
            _task(task_type="deterring", origin="detection", time=0.0 + idx, eta_s=4.0)
            for idx in range(2)
        ]
        predictive_task = _task(
            task_type="patrolling",
            origin="fallback",
            score=10.0,
            utility=10.0,
            predicted_deltaJ=20.0,
            deltaJ_per_cost=4.0,
            eta_s=2.0,
        )
        soft_selected, _soft_urgent = ds._select_dispatch_policy_task(
            reactive_tasks + [predictive_task],
            dispatch_policy="res-soft",
            predictive_share=0.10,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="utility",
            now_t=60.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        adaptive_selected, adaptive_urgent = ds._select_dispatch_policy_task(
            reactive_tasks + [predictive_task],
            dispatch_policy="res-adaptive",
            predictive_share=0.10,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            reservation_age_softening_beta=2.0,
            reservation_age_gate=0.5,
            predictive_selection_policy="utility",
            now_t=60.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertFalse(adaptive_urgent)
        self.assertEqual(soft_selected["type"], "patrolling")
        self.assertEqual(adaptive_selected["origin"], "detection")

    def test_adaptive_reserved_policy_accounts_for_eta_in_age_gate(self):
        reactive_task = _task(
            task_type="deterring",
            origin="detection",
            time=50.0,
            eta_s=35.0,
        )
        predictive_task = _task(
            task_type="patrolling",
            origin="fallback",
            score=10.0,
            utility=10.0,
            predicted_deltaJ=20.0,
            deltaJ_per_cost=4.0,
            eta_s=2.0,
        )
        selected, urgent = ds._select_dispatch_policy_task(
            [reactive_task, predictive_task],
            dispatch_policy="res-adaptive",
            predictive_share=0.10,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            reservation_age_softening_beta=5.0,
            reservation_age_gate=0.25,
            predictive_selection_policy="utility",
            now_t=60.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertFalse(urgent)
        self.assertEqual(selected["origin"], "detection")

    def test_feasible_policy_blocks_infeasible_predictive_claims(self):
        reactive_task = _task(task_type="deterring", origin="detection", time=10.0, eta_s=4.0)
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            score=12.0,
            utility=12.0,
            predicted_deltaJ=30.0,
            deltaJ_per_cost=5.0,
            eta_s=5.0,
            time=10.0,
        )
        predictive_task["required_arrival_by_t"] = 20.0
        predictive_task["event_time"] = 20.0
        selected, urgent = ds._select_dispatch_policy_task(
            [reactive_task, predictive_task],
            dispatch_policy="res-feasible",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="utility",
            predictive_slack_min_s=15.0,
            now_t=18.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertFalse(urgent)
        self.assertEqual(selected["origin"], "detection")

    def test_idle_feasible_policy_blocks_predictive_claim_when_robot_busy_or_pressure_high(self):
        reactive_tasks = [
            _task(task_type="deterring", origin="detection", time=40.0 + idx, eta_s=4.0)
            for idx in range(2)
        ]
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            score=12.0,
            utility=12.0,
            predicted_deltaJ=30.0,
            deltaJ_per_cost=5.0,
            eta_s=2.0,
            time=10.0,
        )
        predictive_task["required_arrival_by_t"] = 80.0
        predictive_task["event_time"] = 80.0
        selected, urgent = ds._select_dispatch_policy_task(
            reactive_tasks + [predictive_task],
            dispatch_policy="res-idle-feasible",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="utility",
            predictive_slack_min_s=15.0,
            reactive_pressure_max_for_predictive=0.5,
            robot_is_idle=False,
            now_t=20.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertFalse(urgent)
        self.assertEqual(selected["origin"], "detection")

    def test_confidence_policy_prefers_higher_confidence_predictive_task(self):
        lower_conf = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="formation",
            utility=4.0,
            predicted_deltaJ=40.0,
            deltaJ_per_cost=2.0,
            eta_s=2.0,
            p_event=0.2,
            selection_weight=0.4,
            time=10.0,
        )
        higher_conf = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=3.0,
            predicted_deltaJ=15.0,
            deltaJ_per_cost=2.0,
            eta_s=2.0,
            p_event=0.95,
            selection_weight=0.95,
            time=10.0,
        )
        for task in (lower_conf, higher_conf):
            task["required_arrival_by_t"] = 120.0
            task["event_time"] = 120.0
        selected, urgent = ds._select_dispatch_policy_task(
            [lower_conf, higher_conf],
            dispatch_policy="res-confidence",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="confidence-weighted",
            predictive_confidence_source="p_event_times_selection_weight",
            predictive_deadline_weight=2.0,
            predictive_eta_penalty_weight=0.1,
            now_t=20.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertFalse(urgent)
        self.assertEqual(selected["mode"], "laser")

    def test_idle_feasible_confidence_policy_filters_low_confidence_tasks(self):
        reactive_task = _task(task_type="deterring", origin="detection", time=10.0, eta_s=4.0)
        low_conf = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=12.0,
            predicted_deltaJ=30.0,
            deltaJ_per_cost=4.0,
            eta_s=1.0,
            p_event=0.2,
            selection_weight=0.3,
            time=10.0,
        )
        low_conf["required_arrival_by_t"] = 90.0
        low_conf["event_time"] = 90.0
        selected, urgent = ds._select_dispatch_policy_task(
            [reactive_task, low_conf],
            dispatch_policy="res-idle-feasible-confidence",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="confidence-weighted",
            predictive_slack_min_s=15.0,
            reactive_pressure_max_for_predictive=0.8,
            predictive_confidence_min=0.25,
            predictive_confidence_source="p_event_times_selection_weight",
            robot_is_idle=True,
            now_t=20.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )
        self.assertFalse(urgent)
        self.assertEqual(selected["origin"], "detection")

    def test_risk_adjusted_policy_rejects_low_confidence_high_delta_j(self):
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=500.0,
            predicted_deltaJ=500.0,
            deltaJ_per_cost=100.0,
            eta_s=2.0,
            p_event=0.10,
            selection_weight=1.0,
            time=10.0,
        )
        predictive_task["required_arrival_by_t"] = 120.0
        predictive_task["event_time"] = 120.0

        selected, urgent = ds._select_dispatch_policy_task(
            [predictive_task],
            dispatch_policy="res-risk-adjusted",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="risk-adjusted",
            predictive_confidence_min=0.25,
            now_t=20.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )

        self.assertFalse(urgent)
        self.assertIsNone(selected)

    def test_risk_adjusted_policy_selects_high_confidence_high_delta_j_under_low_pressure(self):
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=80.0,
            predicted_deltaJ=100.0,
            deltaJ_per_cost=25.0,
            eta_s=2.0,
            p_event=0.90,
            selection_weight=0.90,
            time=10.0,
        )
        predictive_task["required_arrival_by_t"] = 140.0
        predictive_task["event_time"] = 140.0

        selected, urgent = ds._select_dispatch_policy_task(
            [predictive_task],
            dispatch_policy="res-risk-adjusted",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="risk-adjusted",
            predictive_confidence_min=0.25,
            predictive_cost_ratio_min=1.0,
            now_t=20.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )

        self.assertFalse(urgent)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["origin"], "model_hotspot")
        self.assertGreater(selected["predictive_risk_adjusted_utility"], 0.0)

    def test_risk_adjusted_policy_rejects_predictive_when_reactive_age_is_high(self):
        reactive_task = _task(task_type="deterring", origin="detection", time=20.0, eta_s=0.0)
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=80.0,
            predicted_deltaJ=100.0,
            deltaJ_per_cost=25.0,
            eta_s=2.0,
            p_event=0.90,
            selection_weight=0.90,
            time=20.0,
        )
        predictive_task["required_arrival_by_t"] = 160.0
        predictive_task["event_time"] = 160.0

        selected, urgent = ds._select_dispatch_policy_task(
            [reactive_task, predictive_task],
            dispatch_policy="res-risk-adjusted",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=120.0,
            reservation_softening_alpha=2.0,
            reservation_age_gate=0.25,
            predictive_selection_policy="risk-adjusted",
            now_t=60.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )

        self.assertFalse(urgent)
        self.assertEqual(selected["origin"], "detection")

    def test_risk_adjusted_policy_keeps_urgent_reactive_override(self):
        reactive_task = _task(task_type="deterring", origin="detection", time=0.0, eta_s=20.0)
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=80.0,
            predicted_deltaJ=100.0,
            deltaJ_per_cost=25.0,
            eta_s=1.0,
            p_event=0.95,
            selection_weight=0.95,
            time=10.0,
        )
        predictive_task["required_arrival_by_t"] = 140.0
        predictive_task["event_time"] = 140.0

        selected, urgent = ds._select_dispatch_policy_task(
            [reactive_task, predictive_task],
            dispatch_policy="res-risk-adjusted",
            predictive_share=0.0,
            reservation_fraction=0.40,
            reactive_override_slack_s=10.0,
            reservation_softening_alpha=1.0,
            predictive_selection_policy="risk-adjusted",
            now_t=20.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )

        self.assertTrue(urgent)
        self.assertEqual(selected["origin"], "detection")

    def test_risk_adjusted_rho_eff_moves_with_pressure_age_and_confidence(self):
        base = ds._effective_risk_adjusted_reservation_fraction(
            reservation_fraction=0.25,
            mean_predictive_confidence=0.8,
            reactive_pressure=0.0,
            reactive_age_norm=0.0,
            risk_adjusted_reservation_alpha=2.0,
            risk_adjusted_reservation_beta=2.0,
        )
        higher_pressure = ds._effective_risk_adjusted_reservation_fraction(
            reservation_fraction=0.25,
            mean_predictive_confidence=0.8,
            reactive_pressure=0.75,
            reactive_age_norm=0.0,
            risk_adjusted_reservation_alpha=2.0,
            risk_adjusted_reservation_beta=2.0,
        )
        higher_age = ds._effective_risk_adjusted_reservation_fraction(
            reservation_fraction=0.25,
            mean_predictive_confidence=0.8,
            reactive_pressure=0.0,
            reactive_age_norm=0.75,
            risk_adjusted_reservation_alpha=2.0,
            risk_adjusted_reservation_beta=2.0,
        )
        higher_confidence = ds._effective_risk_adjusted_reservation_fraction(
            reservation_fraction=0.25,
            mean_predictive_confidence=0.9,
            reactive_pressure=0.0,
            reactive_age_norm=0.0,
            risk_adjusted_reservation_alpha=2.0,
            risk_adjusted_reservation_beta=2.0,
        )

        self.assertLess(higher_pressure, base)
        self.assertLess(higher_age, base)
        self.assertGreater(higher_confidence, base)

    def test_risk_adjusted_policy_missing_confidence_fields_do_not_crash(self):
        predictive_task = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=80.0,
            predicted_deltaJ=100.0,
            deltaJ_per_cost=25.0,
            eta_s=2.0,
            time=10.0,
        )
        predictive_task.pop("p_event", None)
        predictive_task.pop("selection_weight", None)
        predictive_task.pop("risk_conf", None)
        predictive_task.pop("support", None)
        predictive_task["required_arrival_by_t"] = 140.0
        predictive_task["event_time"] = 140.0

        selected, urgent = ds._select_dispatch_policy_task(
            [predictive_task],
            dispatch_policy="res-risk-adjusted",
            predictive_share=0.0,
            reservation_fraction=0.25,
            reactive_override_slack_s=90.0,
            reservation_softening_alpha=2.0,
            predictive_selection_policy="risk-adjusted",
            now_t=20.0,
            eta_seconds_fn=lambda task: float(task.get("eta_s", 0.0)),
            rng=np.random.default_rng(123),
        )

        self.assertFalse(urgent)
        self.assertIsNone(selected)

    def test_time_aware_policy_recomputes_predictive_score_at_dispatch_time(self):
        loose_but_high_static = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="formation",
            utility=6.0,
            predicted_deltaJ=40.0,
            deltaJ_per_cost=2.0,
            eta_s=2.0,
            p_event=0.9,
            selection_weight=0.9,
            time=10.0,
        )
        tighter_window = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=5.0,
            predicted_deltaJ=35.0,
            deltaJ_per_cost=2.0,
            eta_s=2.0,
            p_event=0.9,
            selection_weight=0.9,
            time=10.0,
        )
        loose_but_high_static["required_arrival_by_t"] = 220.0
        loose_but_high_static["event_time"] = 220.0
        tighter_window["required_arrival_by_t"] = 70.0
        tighter_window["event_time"] = 70.0
        selected = ds._select_predictive_task_for_policy(
            [loose_but_high_static, tighter_window],
            predictive_selection_policy="time-aware",
            rng=np.random.default_rng(123),
            now_t=40.0,
            reactive_pressure=0.0,
            predictive_confidence_source="p_event_times_selection_weight",
            predictive_deadline_weight=2.0,
            predictive_eta_penalty_weight=0.1,
            predictive_time_score_deadline_scale_s=120.0,
            predictive_time_score_reactive_pressure_weight=5.0,
            predictive_time_score_infeasible_penalty=25.0,
        )
        self.assertEqual(selected["mode"], "laser")

    def test_time_aware_v2_uses_predicted_delta_j_instead_of_frozen_high_utility(self):
        stale_high_utility = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="formation",
            utility=40.0,
            predicted_deltaJ=5.0,
            deltaJ_per_cost=1.0,
            eta_s=2.0,
            p_event=0.95,
            selection_weight=0.95,
            time=10.0,
        )
        stronger_delta_j = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=8.0,
            predicted_deltaJ=18.0,
            deltaJ_per_cost=2.0,
            eta_s=2.0,
            p_event=0.95,
            selection_weight=0.95,
            time=10.0,
        )
        for task in (stale_high_utility, stronger_delta_j):
            task["required_arrival_by_t"] = 100.0
            task["event_time"] = 100.0
            task["forecast_event_time"] = 100.0

        selected_v1 = ds._select_predictive_task_for_policy(
            [stale_high_utility, stronger_delta_j],
            predictive_selection_policy="time-aware",
            rng=np.random.default_rng(123),
            now_t=20.0,
            reactive_pressure=0.0,
            predictive_confidence_source="p_event_times_selection_weight",
            predictive_deadline_weight=2.0,
            predictive_eta_penalty_weight=0.1,
            predictive_time_score_deadline_scale_s=120.0,
            predictive_time_score_reactive_pressure_weight=5.0,
            predictive_time_score_infeasible_penalty=25.0,
        )
        selected_v2 = ds._select_predictive_task_for_policy(
            [stale_high_utility, stronger_delta_j],
            predictive_selection_policy="time-aware-v2",
            rng=np.random.default_rng(123),
            now_t=20.0,
            reactive_pressure=0.0,
            predictive_confidence_source="p_event_times_selection_weight",
            predictive_deadline_weight=2.0,
            predictive_eta_penalty_weight=0.1,
            predictive_time_score_deadline_scale_s=120.0,
            predictive_time_score_reactive_pressure_weight=5.0,
            predictive_time_score_infeasible_penalty=25.0,
        )
        self.assertEqual(selected_v1["mode"], "formation")
        self.assertEqual(selected_v2["mode"], "laser")

    def test_time_aware_selection_can_choose_faster_resolved_mode(self):
        slower_high_value = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="formation",
            utility=18.0,
            predicted_deltaJ=18.0,
            deltaJ_per_cost=2.0,
            eta_s=20.0,
            p_event=0.9,
            selection_weight=0.9,
            time=10.0,
        )
        faster_lower_value = _task(
            task_type="deterring",
            origin="model_hotspot",
            mode="laser",
            utility=16.0,
            predicted_deltaJ=16.0,
            deltaJ_per_cost=2.0,
            eta_s=2.0,
            p_event=0.9,
            selection_weight=0.9,
            time=10.0,
        )
        slower_high_value["required_arrival_by_t"] = 40.0
        slower_high_value["event_time"] = 40.0
        faster_lower_value["required_arrival_by_t"] = 40.0
        faster_lower_value["event_time"] = 40.0
        selected = ds._select_predictive_task_for_policy(
            [slower_high_value, faster_lower_value],
            predictive_selection_policy="time-aware",
            rng=np.random.default_rng(123),
            now_t=20.0,
            reactive_pressure=0.0,
            predictive_confidence_source="p_event_times_selection_weight",
            predictive_deadline_weight=2.0,
            predictive_eta_penalty_weight=0.1,
            predictive_time_score_deadline_scale_s=120.0,
            predictive_time_score_reactive_pressure_weight=5.0,
            predictive_time_score_infeasible_penalty=25.0,
        )
        self.assertEqual(selected["mode"], "laser")

    def test_random_predictive_selection_is_seeded(self):
        candidates = [
            _task(task_type="patrolling", origin="fallback", score=1.0),
            _task(task_type="patrolling", origin="fallback", score=2.0),
            _task(task_type="patrolling", origin="fallback", score=3.0),
        ]
        first = ds._select_predictive_task_for_policy(
            candidates,
            predictive_selection_policy="random",
            rng=np.random.default_rng(42),
        )
        second = ds._select_predictive_task_for_policy(
            candidates,
            predictive_selection_policy="random",
            rng=np.random.default_rng(42),
        )
        self.assertEqual(first["score"], second["score"])


class ThesisDispatchRuntimeTests(unittest.TestCase):
    def _last_frame(self, **kwargs):
        sim_kwargs = {
            "T_end": 20.0,
            "dt": 1.0,
            "fps": 1,
            "Nrobots": 2,
            "NX": 12,
            "NY": 10,
            "task_replan_period_s": 5.0,
            "warmup_s": 0.0,
            "telemetry_clear_on_start": False,
            "telemetry_prompt_save": False,
            "report_metrics_end": False,
            "motion_orchestration_mode": "local",
            "simulation_mode": "proposed",
        }
        sim_kwargs.update(kwargs)
        frames = ds.run_simulation_frames_persistent(**sim_kwargs)
        last = None
        for frame in frames:
            last = frame
        self.assertIsNotNone(last)
        return last

    def test_react_policy_blocks_predictive_admissions_but_keeps_generation(self):
        last = self._last_frame(dispatch_policy="react")
        metrics = dict(last["metrics_compact"])
        dispatch = dict(last["dispatch_structured"])
        self.assertGreater(metrics["predictive_generated_total"], 0)
        self.assertEqual(metrics["predictive_admitted_total"], 0)
        self.assertGreaterEqual(dispatch["rejected_counts"]["policy_blocked_predictive"], 0)

    def test_reserved_policy_emits_stream_and_time_allocation_metrics(self):
        last = self._last_frame(dispatch_policy="res", reservation_fraction=0.25)
        metrics = dict(last["metrics_compact"])
        task_stage = dict(last["task_generation_structured"])
        dispatch = dict(last["dispatch_structured"])
        motion = dict(last["motion_execution_structured"])
        self.assertIn("candidate_stream_counts", task_stage)
        self.assertIn("accepted_stream_counts", dispatch)
        self.assertIn("robot_predictive_share_snapshot", dispatch)
        self.assertIn("dispatched_stream_counts_this_step", motion)
        self.assertIn("predictive_completed_total", metrics)
        self.assertIn("robot_idle_fraction_mean", metrics)
        self.assertIn("robot_predictive_fraction_mean", metrics)
        self.assertIn("reactive_load_factor_estimate", metrics)
        self.assertIn("reactive_mean_response_time_s", metrics)

    def test_soft_reserved_policy_emits_softening_alpha(self):
        last = self._last_frame(
            dispatch_policy="res-soft",
            reservation_fraction=0.25,
            reservation_softening_alpha=2.0,
        )
        metrics = dict(last["metrics_compact"])
        dispatch = dict(last["dispatch_structured"])
        self.assertEqual(metrics["dispatch_policy"], "res-soft")
        self.assertEqual(metrics["reservation_softening_alpha"], 2.0)
        self.assertEqual(dispatch["dispatch_policy"], "res-soft")
        self.assertEqual(dispatch["reservation_softening_alpha"], 2.0)

    def test_adaptive_reserved_policy_emits_age_controls(self):
        last = self._last_frame(
            dispatch_policy="res-adaptive",
            reservation_fraction=0.25,
            reservation_softening_alpha=2.0,
            reservation_age_softening_beta=2.0,
            reservation_age_gate=0.5,
        )
        metrics = dict(last["metrics_compact"])
        dispatch = dict(last["dispatch_structured"])
        self.assertEqual(metrics["dispatch_policy"], "res-adaptive")
        self.assertEqual(metrics["reservation_age_softening_beta"], 2.0)
        self.assertEqual(metrics["reservation_age_gate"], 0.5)
        self.assertEqual(dispatch["dispatch_policy"], "res-adaptive")
        self.assertEqual(dispatch["reservation_age_softening_beta"], 2.0)
        self.assertEqual(dispatch["reservation_age_gate"], 0.5)

    def test_runtime_snapshot_preserves_canonical_action_metadata(self):
        direct_last = self._last_frame(
            dispatch_policy="unc",
            T_end=12.0,
            task_replan_period_s=1.0,
            detect_range_m=1000.0,
            bird_detection_prob=1.0,
            per_robot_cooldown_s=0.0,
            mu_true=0.01,
            max_detections_per_step=1,
            enable_direct_detection_task_clustering=False,
            simulation_mode="reactive",
            Nrobots=1,
            W=20.0,
            H=20.0,
            NX=4,
            NY=4,
            arrival_radius_m=1000.0,
        )
        patrol_last = self._last_frame(
            T_end=10.0,
            simulation_mode="prediction_only",
        )
        model_last = self._last_frame(
            T_end=20.0,
            dispatch_policy="unc",
            model_deterring_risk_threshold=0.0,
            model_deterring_score_margin=-1.0,
            model_deterring_min_deltaJ_per_cost=0.0,
            model_deterring_min_selection_weight=0.0,
            model_deterring_capacity_rho_max=1.0,
            model_deterring_budget_per_robot_per_hr=100,
            model_deterring_budget_mode="count_per_hour",
        )
        direct_rows = list(direct_last.get("tasks_active", [])) + list(direct_last.get("tasks_done", []))
        patrol_previews = (
            list(patrol_last.get("task_generation_structured", {}).get("candidate_preview", []))
            + list(patrol_last.get("dispatch_structured", {}).get("accepted_preview", []))
        )
        model_previews = (
            list(model_last.get("task_generation_structured", {}).get("candidate_preview", []))
            + list(model_last.get("dispatch_structured", {}).get("accepted_preview", []))
        )
        self.assertTrue(any(task_action_name(tr) == "direct_detection" for tr in direct_rows))
        self.assertTrue(any(row.get("action", {}).get("kind") == "patrolling" for row in patrol_previews))
        self.assertTrue(
            any(
                row.get("action", {}).get("kind") == "deterring"
                and row.get("action", {}).get("name") != "direct_detection"
                for row in model_previews
            )
        )
        self.assertTrue(any(row.get("action", {}).get("name") == "direct_detection" for row in direct_last.get("dispatch_structured", {}).get("accepted_preview", [])))

    def test_tau_service_alias_shortens_deterring_completion_and_falls_back_to_hold_time(self):
        common_kwargs = dict(
            T_end=3.0,
            dt=1.0,
            fps=1,
            Nrobots=1,
            W=20.0,
            H=20.0,
            NX=4,
            NY=4,
            task_replan_period_s=1.0,
            arrival_radius_m=1000.0,
            hold_time_s=3.0,
            warmup_s=0.0,
            telemetry_clear_on_start=False,
            telemetry_prompt_save=False,
            report_metrics_end=False,
            motion_orchestration_mode="local",
            simulation_mode="reactive",
            detect_range_m=1000.0,
            bird_detection_prob=1.0,
            mu_true=0.01,
            per_robot_cooldown_s=0.0,
            max_detections_per_step=1,
            enable_direct_detection_task_clustering=False,
            include_fallback_patrol=False,
        )
        shorter = self._last_frame(tau_service_s=1.0, **common_kwargs)
        fallback = self._last_frame(**common_kwargs)
        explicit_match = self._last_frame(tau_service_s=3.0, **common_kwargs)

        self.assertEqual(fallback["metrics_compact"]["tau_service_s"], 3.0)
        self.assertEqual(explicit_match["metrics_compact"]["tau_service_s"], 3.0)
        self.assertGreater(
            shorter["metrics_compact"]["reactive_completed_total"],
            fallback["metrics_compact"]["reactive_completed_total"],
        )
        self.assertEqual(
            fallback["metrics_compact"]["reactive_completed_total"],
            explicit_match["metrics_compact"]["reactive_completed_total"],
        )

    def test_predictive_lead_time_preview_fields_appear_when_enabled(self):
        lead_time_last = self._last_frame(
            T_end=10.0,
            simulation_mode="prediction_only",
            enable_predictive_lead_time=True,
            predictive_lead_time_min_s=30.0,
            predictive_lead_time_max_eta_s=120.0,
            predictive_lead_time_buffer_s=15.0,
            predictive_lead_time_risk_power=1.0,
        )
        preview = list(lead_time_last.get("task_generation_structured", {}).get("candidate_preview", []))
        predictive_rows = [row for row in preview if row.get("stream") == "predictive"]
        self.assertTrue(predictive_rows)
        self.assertTrue(any(row.get("event_time") is not None for row in predictive_rows))
        self.assertTrue(any(row.get("lead_time_s") is not None for row in predictive_rows))
        self.assertIn("predictive_deadline_feasible_fraction", lead_time_last["metrics_compact"])

    def test_deferred_predictive_action_selection_keeps_candidates_multi_mode_but_admits_concrete_actions(self):
        last = self._last_frame(
            T_end=20.0,
            dispatch_policy="res",
            predictive_selection_policy="time-aware",
            defer_predictive_action_selection=True,
            assignment_switch_penalty=1.0,
            model_deterring_risk_threshold=0.0,
            model_deterring_score_margin=-1.0,
            model_deterring_min_deltaJ_per_cost=0.0,
            model_deterring_min_selection_weight=0.0,
            model_deterring_capacity_rho_max=1.0,
            model_deterring_budget_per_robot_per_hr=100,
            model_deterring_budget_mode="count_per_hour",
        )
        candidate_preview = list(last.get("task_generation_structured", {}).get("candidate_preview", []))
        predictive_candidates = [
            row for row in candidate_preview
            if row.get("stream") == "predictive" and row.get("type") == "deterring"
        ]
        self.assertTrue(any(int(row.get("predictive_mode_variant_count", 0)) >= 2 for row in predictive_candidates))

        accepted_preview = list(last.get("dispatch_structured", {}).get("accepted_preview", []))
        predictive_accepted = [
            row for row in accepted_preview
            if row.get("stream") == "predictive" and row.get("type") == "deterring"
        ]
        self.assertTrue(
            any(
                row.get("predictive_dispatch_resolved_mode") not in (None, "", "none")
                and row.get("action", {}).get("name") == row.get("predictive_dispatch_resolved_mode")
                for row in predictive_accepted
            )
        )

    def test_centralized_predictive_topology_emits_global_predictive_candidates(self):
        last = self._last_frame(
            T_end=20.0,
            dispatch_policy="res",
            predictive_selection_policy="time-aware",
            predictive_planning_topology="centralized_global",
            zone_assignment_mode="soft",
            defer_predictive_action_selection=True,
            assignment_switch_penalty=1.0,
            model_deterring_risk_threshold=0.0,
            model_deterring_score_margin=-1.0,
            model_deterring_min_deltaJ_per_cost=0.0,
            model_deterring_min_selection_weight=0.0,
            model_deterring_capacity_rho_max=1.0,
            model_deterring_budget_per_robot_per_hr=100,
            model_deterring_budget_mode="count_per_hour",
        )
        metrics = dict(last["metrics_compact"])
        preview = list(last.get("task_generation_structured", {}).get("candidate_preview", []))
        predictive = [row for row in preview if row.get("stream") == "predictive"]
        self.assertEqual(metrics["predictive_planning_topology"], "centralized_global")
        self.assertTrue(any(row.get("robot_id") == "global" for row in predictive))
        self.assertIn("centralized_global_opportunity_count_total", metrics)
        self.assertIn("cross_zone_assignment_total", metrics)


if __name__ == "__main__":
    unittest.main()
