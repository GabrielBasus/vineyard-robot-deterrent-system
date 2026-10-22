"""Decisions 9-11, 13-15, 22 and 29: service and mechanism metrics, persistent state,
demand switch and disturbance injections."""

import json
import math
import os
import re
import tempfile
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

import DeterrentSystem as ds

ROOT = Path(__file__).resolve().parents[1]


def _b5c_params(T_end, seed=200, mu=1e-4, **over):
    from experiments.run_plan_completion import build_params

    p = build_params("B5_c", True, mu, T_end)
    p["seed"] = int(seed)
    p.update(over)
    return p


def _run(params, keep_locals=False):
    gen = ds.run_simulation_frames_persistent(**params)
    last = None
    L = None
    for fr in gen:
        last = fr
        if keep_locals:
            L = gen.gi_frame.f_locals
    return last["metrics_compact"], L


class ServiceAndMechanism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state_path = os.path.join(cls.tmp.name, "hab_end.json")
        cls.m, cls.L = _run(_b5c_params(600.0, outcome_window_boundaries_s=[300.0],
                                        save_final_hab_state_path=cls.state_path), keep_locals=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_decision11_no_double_counting_of_waiting_reactive_tasks(self):
        # Verification (decision 11): every reactive candidate key is offered exactly once.
        m, L = self.m, self.L
        counts = L["reactive_generated_key_counts"]
        self.assertGreater(len(counts), 10)
        self.assertEqual(max(counts.values()), 1)
        self.assertEqual(m["reactive_generated_total"], m["reactive_generated_distinct_total"])
        self.assertEqual(m["reactive_generated_repeat_offers_total"], 0)
        self.assertEqual(m["reactive_unfinished_total"], m["reactive_unfinished_distinct_total"])

    def test_decision9_10_response_time_and_unfinished(self):
        m, L = self.m, self.L
        ages = np.asarray(L["reactive_completion_ages_s"], float)
        self.assertAlmostEqual(m["reactive_age_at_completion_mean_s"], float(np.mean(ages)), places=12)
        self.assertTrue(math.isfinite(m["reactive_mean_response_time_s"]))   # secondary: bird-event latency
        dl = float(L["reactive_service_deadline_s"])
        t_end = float(L["t"])
        unfinished = [k for k in L["reactive_generated_distinct_keys"] if k not in L["reactive_completed_keys"]]
        over = [t_end - (L["reactive_generated_distinct_keys"][k] + dl) for k in unfinished]
        over = [o for o in over if o > 0]
        self.assertEqual(m["reactive_unfinished_overdue_total"], len(over))
        self.assertAlmostEqual(m["reactive_unfinished_overdue_time_s"], float(sum(over)), places=6)
        # completed-overdue is separate and only covers completed tasks
        self.assertAlmostEqual(m["reactive_overdue_time_completed_s"],
                               float(np.sum(np.maximum(ages - dl, 0.0))), places=6)

    def test_decision13_motion_time(self):
        m = self.m
        parts = sum(m[f"motion_time_{s}_s"] for s in ("reactive", "predictive", "deviation", "no_task"))
        self.assertAlmostEqual(m["motion_time_total_s"], parts, places=9)
        self.assertGreater(m["motion_time_total_s"], 0.0)
        self.assertLessEqual(m["motion_time_total_s"], 4 * 601.0)
        self.assertEqual(m["motion_time_deviation_s"], 0.0)            # B5 makes no plan deviations
        self.assertAlmostEqual(sum(m["motion_time_by_robot_s"].values()), m["motion_time_total_s"], places=9)

    def test_decision14_15_application_and_reuse(self):
        m, L = self.m, self.L
        log = L["cue_application_log"]
        n = len(log)
        self.assertGreater(n, 0)
        self.assertEqual(m["eta_at_application_all_count"], n)
        self.assertEqual(m["eta_at_application_reactive_count"] + m["eta_at_application_predictive_count"]
                         + m["eta_at_application_deviation_count"], n)
        self.assertAlmostEqual(m["eta_truth_at_application_all_mean"], float(np.mean([r[4] for r in log])), places=12)
        self.assertEqual(m["cue_reuse_all_count"] + m["cue_reuse_all_without_reuse"], n)
        # brute force reuse intervals
        iv, en = [], []
        for i, r in enumerate(log):
            nxt = [s for s in log[i + 1:] if (s[1], s[2]) == (r[1], r[2])]
            if nxt:
                iv.append(nxt[0][0] - r[0])
                en.append(nxt[0][4])
        self.assertAlmostEqual(m["cue_reuse_all_interval_mean_s"], float(np.mean(iv)), places=9)
        self.assertAlmostEqual(m["cue_reuse_all_interval_median_s"], float(np.median(iv)), places=9)
        self.assertAlmostEqual(m["cue_reuse_all_eta_truth_at_reuse_mean"], float(np.mean(en)), places=12)

    def test_decision22_outcome_windows_partition_the_run(self):
        m = self.m
        w = m["outcome_windows"]
        self.assertEqual([(x["start_s"], x["end_s"]) for x in w], [(0.0, 300.0), (300.0, 600.0)])
        self.assertEqual(sum(x["reactive_generated_distinct_total"] for x in w), m["reactive_generated_distinct_total"])
        self.assertEqual(sum(x["reactive_unfinished_total"] for x in w), m["reactive_unfinished_distinct_total"])
        self.assertAlmostEqual(sum(x["value_weighted_exposure"] for x in w), m["value_weighted_exposure"], places=6)
        self.assertEqual(m["outcome_window1_reactive_missed_total"], w[1]["reactive_missed_total"])

    def test_decision22_save_and_load_hab_state(self):
        saved = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertTrue(np.array_equal(np.asarray(saved["truth_eta"]), self.L["truth_hab"].eta))
        self.assertTrue(np.array_equal(np.asarray(saved["planner_eta"]), self.L["planner_hab"].eta))
        self.assertLess(float(np.min(saved["truth_eta"])), 1.0)
        gen = ds.run_simulation_frames_persistent(**_b5c_params(30.0, initial_hab_state_path=self.state_path))
        next(gen)
        L = gen.gi_frame.f_locals
        exp_truth = L["truth_hab"].copy()
        exp_truth.eta = np.asarray(saved["truth_eta"], float)
        exp_truth.recover(float(L["dt"]))      # first step recovers once
        self.assertEqual(len(L["cue_application_log"]), 0)
        np.testing.assert_array_equal(L["truth_hab"].eta, exp_truth.eta)
        exp_pl = L["planner_hab"].copy()
        exp_pl.eta = np.asarray(saved["planner_eta"], float)
        exp_pl.recover(float(L["dt"]))
        np.testing.assert_array_equal(L["planner_hab"].eta, exp_pl.eta)
        gen.close()


class DemandSwitchAndDisturbances(unittest.TestCase):
    def test_mu_step_reproduces_paper_load_switch_exactly(self):
        for mu_a, mu_b in ((2e-5, 1e-4), (1e-4, 2e-5), (1e-4, 4e-4), (4e-4, 1e-4), (2e-5, 4e-4), (4e-4, 2e-5)):
            gen = ds.run_simulation_frames_persistent(**_b5c_params(
                5.0, mu=mu_a, mu_step_time_s=2700.0, mu_step_factor=mu_b / mu_a))
            next(gen)
            L = gen.gi_frame.f_locals
            self.assertEqual(L["_mu_true_at"](2699.0), mu_a)
            self.assertEqual(L["_mu_true_at"](2700.0), mu_b)       # bit-exact switch
            self.assertEqual(L["_truth_background_rate_at"](2700.0), mu_b)
            self.assertEqual(L["planner_mu_init"], mu_a)            # planner prior: pre-switch rate
            gen.close()

    def test_planner_is_not_told_the_demand_change_or_burst(self):
        import habituation_stl.scenario_rollout as sr

        gen = ds.run_simulation_frames_persistent(**_b5c_params(40.0))
        for _ in range(30):
            next(gen)
        L = dict(gen.gi_frame.f_locals)
        fc0, _ = sr.planner_forecast_from_sim_locals(L, t0=float(L["t"]), horizon_s=300.0)
        L2 = dict(L)
        L2.update(mu_step_time_s=0.0, mu_step_factor=5.0, mu_true=5.0 * float(L["mu_true"]),
                  arrival_burst={"start_s": 0.0, "duration_s": 1e9, "factor": 2.0},
                  _mu_true_at=lambda _t: 1.0, _truth_background_rate_at=lambda _t: 1.0)
        fc1, _ = sr.planner_forecast_from_sim_locals(L2, t0=float(L["t"]), horizon_s=300.0)
        for attr in ("bg_node_rate", "legacy_trigger_mass"):
            np.testing.assert_array_equal(np.asarray(getattr(fc0, attr)), np.asarray(getattr(fc1, attr)))
        gen.close()
        # Static: no planner-side module reads the truth demand schedule or the injections.
        planner_files = ["TaskGenerator.py", "planner_task_estimation.py", "planner_task_extraction.py",
                         "planner_task_selection.py", "planner_dispatch.py", "planner_task_generation.py",
                         "habituation_stl/plan_procedure.py", "habituation_stl/task_value.py"]
        for f in planner_files:
            text = (ROOT / f).read_text(encoding="utf-8")
            for name in ("mu_step", "_mu_true_at", "arrival_burst", "_truth_background_rate_at",
                         "travel_speed_error"):
                self.assertNotIn(name, text, msg=f"{f} reads {name}")
        # scenario_rollout reads the demand schedule only in its truth (oracle / full-observability) builders
        text = (ROOT / "habituation_stl/scenario_rollout.py").read_text(encoding="utf-8")
        fns = re.findall(r"\ndef (\w+)\(", text)
        users = set()
        for name in fns:
            body = text.split(f"\ndef {name}(", 1)[1].split("\ndef ", 1)[0]
            if "mu_step" in body or "_mu_true_at" in body:
                users.add(name)
        self.assertLessEqual(users, {"snapshot_from_sim_locals", "truth_forecast_from_sim_locals"})

    def test_arrival_burst_multiplies_truth_background_in_window(self):
        burst = {"start_s": 100.0, "duration_s": 300.0, "factor": 2.0}
        gen = ds.run_simulation_frames_persistent(**_b5c_params(5.0, mu=1e-4, arrival_burst=burst))
        next(gen)
        f = gen.gi_frame.f_locals["_truth_background_rate_at"]
        self.assertEqual(f(99.0), 1e-4)
        self.assertEqual(f(100.0), 2e-4)
        self.assertEqual(f(399.0), 2e-4)
        self.assertEqual(f(400.0), 1e-4)
        gen.close()
        m0, _ = _run(_b5c_params(300.0, mu=1e-4))
        m1, _ = _run(_b5c_params(300.0, mu=1e-4, arrival_burst=burst))
        self.assertGreater(m1["truth_candidate_events"], m0["truth_candidate_events"])

    def test_travel_speed_error_slows_truth_motion_only(self):
        err = 0.2
        gen = ds.run_simulation_frames_persistent(**_b5c_params(200.0, travel_speed_error=err))
        prev = None
        max_ratio = 0.0
        moved = False
        for _ in gen:
            L = gen.gi_frame.f_locals
            pose = {r: tuple(v) for r, v in L["pose"].items()}
            if prev is not None:
                for r, (x, y) in pose.items():
                    d = math.hypot(x - prev[r][0], y - prev[r][1])
                    v = float(L["profiles"][r].speed_mps) * float(L["dt"])
                    max_ratio = max(max_ratio, d / v)
                    moved = moved or d > 0
            prev = pose
        self.assertTrue(moved)
        self.assertLessEqual(max_ratio, 1.0 - err + 1e-9)
        self.assertGreater(max_ratio, 1.0 - err - 1e-6)
        # Planner ETAs and rollouts read profiles[rid].speed_mps, which stays nominal.
        gen0 = ds.run_simulation_frames_persistent(**_b5c_params(5.0))
        next(gen0)
        nominal = {r: p.speed_mps for r, p in gen0.gi_frame.f_locals["profiles"].items()}
        gen0.close()
        self.assertEqual({r: p.speed_mps for r, p in L["profiles"].items()}, nominal)


if __name__ == "__main__":
    unittest.main()
