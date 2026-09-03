import argparse
import unittest

from experiments.run_habituation_stl_fair_tuning import (
    DEFAULT_SYSTEMS,
    FIXED_CUE_SYSTEMS,
    RESERVED_SYSTEMS,
    _confirm_source_args,
    _selection_to_trial,
    build_cue_mode_trial_plan,
    build_structural_trial_plan,
    build_trial_plan,
    parse_args,
    select_best_cue_modes,
    select_best_trials,
)


def _args(**overrides):
    base = {
        "systems": list(DEFAULT_SYSTEMS),
        "trial_budget": 5,
        "budget_values": [3, 4, 6],
        "score_margin_values": [0.05, 0.10],
        "max_eta_values": [90.0, 120.0],
        "horizon_values": [240.0, 300.0, 420.0],
        "reservation_fraction_values": [0.10, 0.25, 0.40],
        "fixed_cue_values": ["formation", "laser", "biosonic"],
        "fixed_cue_mode": "laser",
        "selection_habituation_condition": "hab_on",
        "selection_metric": "value_weighted_exposure",
        "guardrail_max_predictive_expired_fraction": None,
        "guardrail_min_coverage_robustness": None,
        "guardrail_max_mean_response_time_s": None,
        "guardrail_penalty": 1.0e9,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class BuildStructuralTrialPlanTests(unittest.TestCase):
    def test_returns_tuple_of_trials_and_struct_samples(self):
        args = _args(trial_budget=3)
        result = build_structural_trial_plan(args)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_each_system_gets_exactly_trial_budget_structural_trials(self):
        args = _args(trial_budget=4)
        trials, _ = build_structural_trial_plan(args)
        counts = {s: 0 for s in DEFAULT_SYSTEMS}
        for trial in trials:
            counts[trial["baseline"]] += 1
        self.assertEqual(set(counts.values()), {4})

    def test_all_systems_explore_the_same_structural_grid_points(self):
        """The same N struct_combos are assigned to every system at the same struct_index."""
        args = _args(trial_budget=6)
        trials, struct_samples = build_structural_trial_plan(args)

        # For each struct_index, all systems must have identical non-cue, non-rho overrides
        for struct_idx in range(1, 7):
            slice_ = [t for t in trials if t["struct_index"] == struct_idx]
            self.assertEqual(len(slice_), len(DEFAULT_SYSTEMS))
            ref = {
                k: v
                for k, v in slice_[0]["overrides"].items()
                if k not in {"reservation_fraction", "predictive_fixed_deterring_mode"}
            }
            for trial in slice_[1:]:
                got = {
                    k: v
                    for k, v in trial["overrides"].items()
                    if k not in {"reservation_fraction", "predictive_fixed_deterring_mode"}
                }
                self.assertEqual(got, ref, msg=f"struct_index={struct_idx} mismatch")

    def test_reservation_fraction_present_iff_reserved(self):
        args = _args(trial_budget=3)
        trials, _ = build_structural_trial_plan(args)
        for trial in trials:
            has_rho = "reservation_fraction" in trial["overrides"]
            self.assertEqual(has_rho, trial["baseline"] in RESERVED_SYSTEMS)

    def test_fixed_cue_systems_use_default_cue_in_structural_trials(self):
        """Structural trials must not sweep cue modes — that is the cue-mode phase's job."""
        args = _args(trial_budget=4, fixed_cue_mode="biosonic")
        trials, _ = build_structural_trial_plan(args)
        for trial in trials:
            if trial["baseline"] in FIXED_CUE_SYSTEMS:
                self.assertEqual(
                    trial["overrides"]["predictive_fixed_deterring_mode"],
                    "biosonic",
                    msg=f"Expected default cue for {trial['baseline']}, got "
                    f"{trial['overrides']['predictive_fixed_deterring_mode']}",
                )
            else:
                self.assertNotIn("predictive_fixed_deterring_mode", trial["overrides"])

    def test_struct_samples_length_matches_trial_budget(self):
        args = _args(trial_budget=7)
        _, struct_samples = build_structural_trial_plan(args)
        self.assertEqual(len(struct_samples), 7)

    def test_backward_compat_alias_returns_flat_list(self):
        """build_trial_plan must return list[dict] not a tuple, for downstream compatibility."""
        args = _args(trial_budget=3)
        result = build_trial_plan(args)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        self.assertIsInstance(result[0], dict)


class BuildCueModePlanTests(unittest.TestCase):
    def _struct_combo(self):
        return {
            "reservation_fraction": 0.25,
            "budget_per_robot_per_hr": 4,
            "score_margin": 0.05,
            "max_eta_s": 90.0,
            "horizon_s": 300.0,
        }

    def test_only_fixed_cue_systems_get_cue_trials(self):
        args = _args()
        trials = build_cue_mode_trial_plan(args, self._struct_combo())
        baselines = {t["baseline"] for t in trials}
        self.assertEqual(baselines, FIXED_CUE_SYSTEMS & set(DEFAULT_SYSTEMS))

    def test_every_cue_mode_appears_once_per_fixed_cue_system(self):
        args = _args()
        trials = build_cue_mode_trial_plan(args, self._struct_combo())
        for baseline in FIXED_CUE_SYSTEMS:
            system_trials = [t for t in trials if t["baseline"] == baseline]
            cues = [t["overrides"]["predictive_fixed_deterring_mode"] for t in system_trials]
            self.assertEqual(sorted(cues), sorted(args.fixed_cue_values))

    def test_structural_params_are_fixed_at_selected_combo(self):
        args = _args()
        combo = self._struct_combo()
        trials = build_cue_mode_trial_plan(args, combo)
        for trial in trials:
            ov = trial["overrides"]
            self.assertEqual(ov["model_deterring_budget_per_robot_per_hr"], combo["budget_per_robot_per_hr"])
            self.assertEqual(ov["forecast_horizon_s"], combo["horizon_s"])
            self.assertEqual(ov["model_deterring_score_margin"], combo["score_margin"])

    def test_reserved_fixed_cue_systems_include_rho(self):
        args = _args()
        combo = self._struct_combo()
        trials = build_cue_mode_trial_plan(args, combo)
        for trial in trials:
            if trial["baseline"] in RESERVED_SYSTEMS:
                self.assertIn("reservation_fraction", trial["overrides"])
            else:
                self.assertNotIn("reservation_fraction", trial["overrides"])


class SelectBestTrialsTests(unittest.TestCase):
    def _make_summaries(self, scores_by_system_and_trial):
        """scores_by_system_and_trial: {(baseline, struct_index): score}"""
        rows = []
        for (baseline, struct_idx), score in scores_by_system_and_trial.items():
            rows.append(
                {
                    "baseline": baseline,
                    "trial_id": f"{baseline}_struct_{struct_idx:03d}",
                    "trial_index": struct_idx,
                    "struct_index": struct_idx,
                    "habituation_condition": "hab_on",
                    "selection_score": float(score),
                    "mean_response_time_s_mean": 1.0,
                }
            )
        return rows

    def test_all_reserved_systems_get_the_same_struct_index(self):
        """Core correctness invariant: B3 and B4 (and other reserved) must share struct_index."""
        args = _args(
            systems=[
                "B2_res_deltaJ_fixedcue",
                "B3_res_stl_nohab_fixedcue",
                "B4_res_stl_full_multicue",
                "B5_res_habcue_multicue",
            ]
        )
        # struct_index=2 is best on average for reserved systems; each system individually
        # would pick different indices if selection were independent.
        summaries = self._make_summaries(
            {
                ("B2_res_deltaJ_fixedcue", 1): 100.0,
                ("B2_res_deltaJ_fixedcue", 2): 90.0,   # B2 best at 2
                ("B3_res_stl_nohab_fixedcue", 1): 80.0,  # B3 individually best at 1
                ("B3_res_stl_nohab_fixedcue", 2): 95.0,
                ("B4_res_stl_full_multicue", 1): 110.0,
                ("B4_res_stl_full_multicue", 2): 85.0,  # B4 best at 2
                ("B5_res_habcue_multicue", 1): 120.0,
                ("B5_res_habcue_multicue", 2): 88.0,   # B5_res best at 2
            }
        )
        # joint mean at idx=1: (100+80+110+120)/4 = 102.5
        # joint mean at idx=2: (90+95+85+88)/4   = 89.5  ← best joint
        selected = select_best_trials(summaries, args)
        struct_indices = {
            str(row["baseline"]): int(row["struct_index"]) for row in selected
        }
        self.assertEqual(struct_indices["B2_res_deltaJ_fixedcue"], 2)
        self.assertEqual(struct_indices["B3_res_stl_nohab_fixedcue"], 2)
        self.assertEqual(struct_indices["B4_res_stl_full_multicue"], 2)
        self.assertEqual(struct_indices["B5_res_habcue_multicue"], 2)

    def test_joint_selection_overrides_individually_optimal(self):
        """B3 would individually pick idx=1 (score=80), but the joint winner is idx=2."""
        args = _args(
            systems=[
                "B3_res_stl_nohab_fixedcue",
                "B4_res_stl_full_multicue",
            ]
        )
        summaries = self._make_summaries(
            {
                ("B3_res_stl_nohab_fixedcue", 1): 80.0,
                ("B3_res_stl_nohab_fixedcue", 2): 95.0,
                ("B4_res_stl_full_multicue", 1): 110.0,
                ("B4_res_stl_full_multicue", 2): 85.0,
            }
        )
        selected = select_best_trials(summaries, args)
        b3 = next(r for r in selected if r["baseline"] == "B3_res_stl_nohab_fixedcue")
        b4 = next(r for r in selected if r["baseline"] == "B4_res_stl_full_multicue")
        # joint mean at 1: (80+110)/2=95, at 2: (95+85)/2=90 → joint best=2
        self.assertEqual(b3["struct_index"], 2)
        self.assertEqual(b4["struct_index"], 2)

    def test_non_reserved_systems_select_independently(self):
        args = _args(systems=["B1_greedy_fixedcue", "B5_greedy_habcue"])
        summaries = self._make_summaries(
            {
                ("B1_greedy_fixedcue", 1): 200.0,
                ("B1_greedy_fixedcue", 2): 150.0,   # B1 best at 2
                ("B5_greedy_habcue", 1): 120.0,     # B5 best at 1
                ("B5_greedy_habcue", 2): 180.0,
            }
        )
        selected = select_best_trials(summaries, args)
        b1 = next(r for r in selected if r["baseline"] == "B1_greedy_fixedcue")
        b5 = next(r for r in selected if r["baseline"] == "B5_greedy_habcue")
        self.assertEqual(b1["struct_index"], 2)
        self.assertEqual(b5["struct_index"], 1)

    def test_uses_selection_condition_only(self):
        args = _args(systems=["B1_greedy_fixedcue"])
        rows = [
            {
                "baseline": "B1_greedy_fixedcue",
                "trial_id": "B1_greedy_fixedcue_struct_001",
                "trial_index": 1,
                "struct_index": 1,
                "habituation_condition": "hab_off",
                "selection_score": -100.0,
                "mean_response_time_s_mean": 1.0,
            },
            {
                "baseline": "B1_greedy_fixedcue",
                "trial_id": "B1_greedy_fixedcue_struct_002",
                "trial_index": 2,
                "struct_index": 2,
                "habituation_condition": "hab_on",
                "selection_score": 10.0,
                "mean_response_time_s_mean": 5.0,
            },
            {
                "baseline": "B1_greedy_fixedcue",
                "trial_id": "B1_greedy_fixedcue_struct_003",
                "trial_index": 3,
                "struct_index": 3,
                "habituation_condition": "hab_on",
                "selection_score": 20.0,
                "mean_response_time_s_mean": 1.0,
            },
        ]
        selected = select_best_trials(rows, args)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["trial_id"], "B1_greedy_fixedcue_struct_002")


class SelectBestCueModesTests(unittest.TestCase):
    def test_picks_lowest_score_cue_per_system(self):
        args = _args()
        summaries = [
            {
                "baseline": "B3_res_stl_nohab_fixedcue",
                "trial_id": "B3_res_stl_nohab_fixedcue_cue_formation",
                "habituation_condition": "hab_on",
                "selection_score": 200.0,
                "config_predictive_fixed_deterring_mode": "formation",
            },
            {
                "baseline": "B3_res_stl_nohab_fixedcue",
                "trial_id": "B3_res_stl_nohab_fixedcue_cue_laser",
                "habituation_condition": "hab_on",
                "selection_score": 150.0,
                "config_predictive_fixed_deterring_mode": "laser",
            },
            {
                "baseline": "B3_res_stl_nohab_fixedcue",
                "trial_id": "B3_res_stl_nohab_fixedcue_cue_biosonic",
                "habituation_condition": "hab_on",
                "selection_score": 180.0,
                "config_predictive_fixed_deterring_mode": "biosonic",
            },
            {
                "baseline": "B1_greedy_fixedcue",
                "trial_id": "B1_greedy_fixedcue_cue_biosonic",
                "habituation_condition": "hab_on",
                "selection_score": 90.0,
                "config_predictive_fixed_deterring_mode": "biosonic",
            },
            {
                "baseline": "B1_greedy_fixedcue",
                "trial_id": "B1_greedy_fixedcue_cue_laser",
                "habituation_condition": "hab_on",
                "selection_score": 120.0,
                "config_predictive_fixed_deterring_mode": "laser",
            },
        ]
        best = select_best_cue_modes(summaries, args)
        self.assertEqual(best["B3_res_stl_nohab_fixedcue"], "laser")
        self.assertEqual(best["B1_greedy_fixedcue"], "biosonic")

    def test_ignores_non_selection_habituation_condition(self):
        args = _args()
        summaries = [
            {
                "baseline": "B1_greedy_fixedcue",
                "trial_id": "B1_greedy_fixedcue_cue_formation",
                "habituation_condition": "hab_off",
                "selection_score": 1.0,  # would win if hab_off were considered
                "config_predictive_fixed_deterring_mode": "formation",
            },
            {
                "baseline": "B1_greedy_fixedcue",
                "trial_id": "B1_greedy_fixedcue_cue_laser",
                "habituation_condition": "hab_on",
                "selection_score": 500.0,
                "config_predictive_fixed_deterring_mode": "laser",
            },
        ]
        best = select_best_cue_modes(summaries, args)
        self.assertEqual(best.get("B1_greedy_fixedcue"), "laser")

    def test_only_fixed_cue_systems_included(self):
        args = _args()
        summaries = [
            {
                "baseline": "B4_res_stl_full_multicue",
                "trial_id": "B4_res_stl_full_multicue_cue_laser",
                "habituation_condition": "hab_on",
                "selection_score": 10.0,
                "config_predictive_fixed_deterring_mode": "laser",
            },
        ]
        best = select_best_cue_modes(summaries, args)
        self.assertNotIn("B4_res_stl_full_multicue", best)


class SelectionToTrialTests(unittest.TestCase):
    def test_preserves_tuned_fixed_cue_mode(self):
        selection = {
            "baseline": "B2_res_deltaJ_fixedcue",
            "trial_id": "B2_res_deltaJ_fixedcue_struct_007",
            "trial_index": 7,
            "selection_score": 12.0,
            "config_predictive_fixed_deterring_mode": "biosonic",
        }
        selected = _selection_to_trial(selection)
        self.assertEqual(selected["overrides"]["predictive_fixed_deterring_mode"], "biosonic")


class ConfirmSourceArgsTests(unittest.TestCase):
    def test_confirm_reuses_saved_tuning_scenario_args(self):
        args = parse_args(
            [
                "--phase", "confirm",
                "--confirm-duration-s", "222",
                "--confirm-num-runs", "4",
                "--confirm-seed-start", "900",
                "--max-workers", "2",
            ]
        )
        tuning_args = {
            "nx": 72,
            "ny": 64,
            "nrobots": 5,
            "mu_true": 9.0e-5,
            "habituation_kappa": 0.7,
            "max_workers": 16,
            "confirm_duration_s": 999,
            "confirm_num_runs": 99,
            "confirm_seed_start": 99,
        }
        source = _confirm_source_args(args, tuning_args)
        self.assertEqual(source.nx, 72)
        self.assertEqual(source.ny, 64)
        self.assertEqual(source.nrobots, 5)
        self.assertEqual(source.mu_true, 9.0e-5)
        self.assertEqual(source.habituation_kappa, 0.7)
        # Runtime controls come from args, not tuning_args
        self.assertEqual(source.max_workers, 2)
        self.assertEqual(source.confirm_duration_s, 222)
        self.assertEqual(source.confirm_num_runs, 4)
        self.assertEqual(source.confirm_seed_start, 900)


class ParseArgsDefaultsTests(unittest.TestCase):
    def test_default_tune_num_runs_is_at_least_10(self):
        args = parse_args(["--dry-run", "--phase", "tune"])
        self.assertGreaterEqual(args.tune_num_runs, 10)

    def test_default_trial_budget_is_positive(self):
        args = parse_args(["--dry-run", "--phase", "tune"])
        self.assertGreater(args.trial_budget, 0)

    def test_fixed_cue_values_include_all_three_modes(self):
        args = parse_args(["--dry-run", "--phase", "tune"])
        self.assertEqual(sorted(args.fixed_cue_values), ["biosonic", "formation", "laser"])


if __name__ == "__main__":
    unittest.main()
