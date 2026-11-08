"""Common-random-number coupling of exogenous truth randomness (plan Sections 4 and 6).

(a) random_stream_mode="legacy" reproduces pre-change results exactly.
(b) random_stream_mode="coupled": two different policies with the same seed see the
    same background candidate stream and the same thinning uniforms per event id.
(c) offspring of the same accepted parent id are identical across policies.
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

import DeterrentSystem as ds
from experiments import run_habituation_stl_production_ladder as ladder
from random_streams import CoupledRandomStreams

# Confirmatory ladder configuration
# (results/testbench/habituation_stl_revised_confirm_with_b2_1800s_10seed/ladder_manifest.json).
CONFIRM_ARGV = [
    "ladder",
    "--nx", "60", "--ny", "48", "--nrobots", "4", "--warmup-s", "0",
    "--mu-true", "2e-05",
    "--deterrence-beta-scale", "4.0",
    "--deterrence-sigma-scale", "4.0",
    "--deterrence-omega-scale", "3.0",
]


def _ladder_params(system: str, duration_s: float, seed: int, **overrides) -> dict:
    with mock.patch.object(sys, "argv", CONFIRM_ARGV + ["--duration-s", str(duration_s)]):
        args = ladder.parse_args()
    jobs = [job for job in ladder._build_jobs(args) if job["system"] == system]
    assert len(jobs) >= 1, system
    params = dict(jobs[0]["params"])
    params.pop("habituation_condition", None)
    params["seed"] = int(seed)
    params.update(overrides)
    return params


def _run_metrics(params: dict) -> dict:
    last = None
    for frame in ds.run_simulation_frames_persistent(**params):
        last = frame
    return dict((last or {}).get("metrics_compact") or (last or {}).get("metrics") or {})


class LegacyModeReproductionTests(unittest.TestCase):
    # Reference values produced by the pre-change code (commit 72ba259), seed 125, T_end=120 s.
    REFERENCE_120S = {
        "B1_greedy_fixedcue_hab_on": {
            "value_weighted_exposure": 2923.945357461836,
            "truth_candidate_events": 1329,
            "truth_suppressed_events": 31,
        },
        "B4_res_stl_full_multicue_hab_on": {
            "value_weighted_exposure": 3017.557339366104,
            "truth_candidate_events": 1341,
            "truth_suppressed_events": 0,
        },
    }

    def test_legacy_mode_matches_pre_change_short_runs(self):
        for system, ref in self.REFERENCE_120S.items():
            with self.subTest(system=system):
                metrics = _run_metrics(_ladder_params(system, 120.0, 125))
                for key, value in ref.items():
                    self.assertEqual(metrics[key], value, key)

    @unittest.skipUnless(os.environ.get("RUN_SLOW_REPRO") == "1", "set RUN_SLOW_REPRO=1 (about 3 min)")
    def test_legacy_mode_matches_stored_confirmatory_run(self):
        # per_run_metrics.csv: B4_res_stl_full_multicue_hab_off, seed 125, 1800 s.
        metrics = _run_metrics(_ladder_params("B4_res_stl_full_multicue_hab_off", 1800.0, 125))
        self.assertEqual(metrics["value_weighted_exposure"], 37086.52794501342)


class CoupledStreamTests(unittest.TestCase):
    SEED = 125
    T_END = 300.0
    _traces = None

    @classmethod
    def _coupled_traces(cls):
        if cls._traces is None:
            traces = {}
            for system in ("B1_greedy_fixedcue_hab_on", "B4_res_stl_full_multicue_hab_on"):
                trace = []
                params = _ladder_params(
                    system, cls.T_END, cls.SEED, random_stream_mode="coupled", truth_stream_trace=trace
                )
                metrics = _run_metrics(params)
                traces[system] = (trace, metrics)
            cls._traces = traces
        return cls._traces

    def test_background_candidate_streams_identical(self):
        (tr_a, _), (tr_b, _) = self._coupled_traces().values()

        def background(trace):
            return [
                (rec["id"], rec["x"], rec["y"], rec["t"])
                for rec in trace
                if rec["kind"] == "candidate" and rec["origin"] == "background"
            ]

        bg_a, bg_b = background(tr_a), background(tr_b)
        self.assertGreater(len(bg_a), 1000)
        self.assertEqual(bg_a, bg_b)

    def test_thinning_uniforms_identical_for_shared_ids(self):
        (tr_a, _), (tr_b, _) = self._coupled_traces().values()
        u_a = {rec["id"]: rec["u"] for rec in tr_a if rec["kind"] == "candidate"}
        u_b = {rec["id"]: rec["u"] for rec in tr_b if rec["kind"] == "candidate"}
        shared = set(u_a) & set(u_b)
        self.assertGreater(len(shared), 1000)
        self.assertTrue(any(len(eid) > 2 for eid in shared), "expected shared offspring ids")
        for eid in shared:
            self.assertEqual(u_a[eid], u_b[eid], eid)
        # The policies must actually differ in suppression for the test to be meaningful.
        p_a = {rec["id"]: rec["p_keep"] for rec in tr_a if rec["kind"] == "candidate"}
        p_b = {rec["id"]: rec["p_keep"] for rec in tr_b if rec["kind"] == "candidate"}
        self.assertTrue(any(p_a[eid] != p_b[eid] for eid in shared))

    def test_offspring_identical_for_shared_accepted_parents(self):
        (tr_a, _), (tr_b, _) = self._coupled_traces().values()
        off_a = {rec["parent"]: rec["children"] for rec in tr_a if rec["kind"] == "offspring"}
        off_b = {rec["parent"]: rec["children"] for rec in tr_b if rec["kind"] == "offspring"}
        shared = set(off_a) & set(off_b)
        self.assertGreater(len(shared), 100)
        self.assertTrue(any(off_a[pid] for pid in shared))
        for pid in shared:
            self.assertEqual(off_a[pid], off_b[pid], pid)

    def test_keyed_streams_are_policy_free_functions_of_seed_and_id(self):
        s1, s2 = CoupledRandomStreams(7), CoupledRandomStreams(7)
        s2.policy_rng.random(10)  # policy draws must not perturb truth draws
        self.assertEqual(s1.thinning_uniform((3, 1)), s2.thinning_uniform((3, 1)))
        self.assertEqual(s1.detection_uniform((3, 1, 0), "r2"), s2.detection_uniform((3, 1, 0), "r2"))
        self.assertNotEqual(s1.thinning_uniform((3, 1)), s1.thinning_uniform((3, 1, 0)))
        self.assertEqual(s1.background_rng.random(), s2.background_rng.random())


class TruthOptionFlagTests(unittest.TestCase):
    def _small(self, **overrides):
        params = dict(
            W=120.0, H=120.0, NX=24, NY=24, Nrobots=2, uav_fraction=0.0, seed=11, dt=1.0, T_end=60.0,
            warmup_s=20.0, mu_true=2e-4, alpha_true=0.3, use_ground_truth=True,
            telemetry_clear_on_start=False, telemetry_prompt_save=False, report_metrics_end=False,
        )
        params.update(overrides)
        return _run_metrics(params)

    def test_flags_run_in_both_stream_modes(self):
        for mode in ("legacy", "coupled"):
            with self.subTest(mode=mode):
                metrics = self._small(
                    random_stream_mode=mode,
                    truth_deterrence_memory="complete",
                    truth_background_timing="continuous",
                    truth_excitation_sigma=12.0,
                    truth_excitation_omega=600.0,
                )
                self.assertGreater(metrics["truth_candidate_events"], 0)

    def test_coupled_mode_is_deterministic(self):
        a = self._small(random_stream_mode="coupled")
        b = self._small(random_stream_mode="coupled")
        self.assertEqual(a["value_weighted_exposure"], b["value_weighted_exposure"])

    def test_invalid_flag_values_rejected(self):
        with self.assertRaises(ValueError):
            self._small(random_stream_mode="bogus")
        with self.assertRaises(ValueError):
            self._small(truth_deterrence_memory="bogus")
        with self.assertRaises(ValueError):
            self._small(truth_background_timing="bogus")


if __name__ == "__main__":
    unittest.main()
