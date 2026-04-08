import inspect
import unittest
from pathlib import Path

import pandas as pd

import labs.assignment_methods_lab as aml
import labs.DeterrentSystem_assignment_lab as ds
import experiments.run_assignment_tuning_sweep_lab as tuning
from config_loader import _flatten_mapping, _load_yaml_mapping, parse_args_with_config


ROOT = Path(__file__).resolve().parents[1]


def _build_request(score_map: dict[tuple[str, int], float], robots: list[str], capacity: dict[str, int], tasks: list[dict]):
    def score_fn(rid: str, tidx: int) -> float:
        return float(score_map.get((rid, tidx), float("-inf")))

    def eligible_fn(rid: str, tidx: int) -> bool:
        return (rid, tidx) in score_map

    return aml.AssignmentRequest(
        tasks=tasks,
        robots=robots,
        capacity_by_robot=capacity,
        score_fn=score_fn,
        eligible_fn=eligible_fn,
        task_type_fn=lambda j: str(tasks[j].get("type", "")).strip().lower(),
    )


class AssignmentMethodMigrationTests(unittest.TestCase):
    def test_hungarian_beats_frozen_greedy_on_counterexample(self):
        tasks = [{"type": "patrolling"}, {"type": "patrolling"}]
        robots = ["r1", "r2"]
        capacity = {"r1": 1, "r2": 1}
        score_map = {
            ("r1", 0): 10.0,
            ("r1", 1): 9.0,
            ("r2", 0): 8.0,
            ("r2", 1): 0.0,
        }

        req = _build_request(score_map, robots, capacity, tasks)
        greedy = aml.solve_assignment("frozen_greedy", req)
        hungarian = aml.solve_assignment("hungarian", req)

        self.assertEqual(greedy.primary_by_task_idx, {0: "r1", 1: "r2"})
        self.assertEqual(hungarian.primary_by_task_idx, {0: "r2", 1: "r1"})
        self.assertLess(
            float(greedy.debug.get("objective_utility", float("-inf"))),
            float(hungarian.debug.get("objective_utility", float("-inf"))),
        )

    def test_hungarian_respects_one_to_one_and_infeasible_pairs(self):
        tasks = [{"type": "patrolling"}, {"type": "deterring"}, {"type": "patrolling"}]
        robots = ["r1", "r2"]
        capacity = {"r1": 1, "r2": 1}
        score_map = {
            ("r1", 0): 7.0,
            ("r1", 1): 6.0,
            ("r2", 1): 8.0,
            ("r2", 2): 5.0,
        }

        req = _build_request(score_map, robots, capacity, tasks)
        result = aml.solve_assignment("hungarian", req)
        assigned = dict(result.primary_by_task_idx)

        self.assertEqual(len(assigned), len(set(assigned.keys())))
        self.assertEqual(len(set(assigned.values())), len(assigned))
        self.assertLessEqual(len(assigned), sum(capacity.values()))
        for tidx, rid in assigned.items():
            self.assertIn((rid, tidx), score_map)
        used_by_robot: dict[str, int] = {}
        for rid in assigned.values():
            used_by_robot[rid] = used_by_robot.get(rid, 0) + 1
        for rid, used in used_by_robot.items():
            self.assertLessEqual(used, capacity[rid])

    def test_current_defaults_and_configs_resolve_to_hungarian(self):
        sig = inspect.signature(ds.run_simulation_frames_persistent)
        self.assertEqual(sig.parameters["assignment_method"].default, "hungarian")

        parser = tuning.build_parser()
        args_default, _ = parse_args_with_config(
            parser,
            aliases=tuning.ASSIGNMENT_TUNING_CONFIG_ALIASES,
            argv=[],
        )
        self.assertEqual(args_default.methods, "hungarian")

        args_cfg, _ = parse_args_with_config(
            tuning.build_parser(),
            aliases=tuning.ASSIGNMENT_TUNING_CONFIG_ALIASES,
            argv=["--config", str(ROOT / "configs" / "run_assignment_tuning_sweep_lab.yaml")],
        )
        self.assertEqual(args_cfg.methods, "hungarian")

        expected_values = {
            ROOT / "configs" / "compare_field_divergence_lab.yaml": {"planner.assignment_method": "hungarian"},
            ROOT / "configs" / "run_assignment_tuning_sweep_lab.yaml": {"runner.methods": ["hungarian"]},
            ROOT / "configs" / "run_field_divergence_confirm_lab.yaml": {"planner.assignment_method": "hungarian"},
            ROOT / "configs" / "run_field_divergence_filter_sweep_lab.yaml": {"planner.assignment_method": "hungarian"},
        }
        for path, expected in expected_values.items():
            flat = _flatten_mapping(_load_yaml_mapping(path))
            for key, value in expected.items():
                self.assertEqual(flat.get(key), value, msg=f"{path.name}::{key}")

    def test_hungarian_only_method_delta_helper_returns_empty_schema(self):
        runs_df = pd.DataFrame(
            [
                {
                    "scenario_id": "S1",
                    "baseline": "prediction_only",
                    "seed": 2000,
                    "run_idx": 0,
                    "assignment_method": "hungarian",
                    "value_weighted_exposure": 10.0,
                    "mean_response_time_s": 20.0,
                    "boundary_message_count": 5.0,
                },
                {
                    "scenario_id": "S1",
                    "baseline": "proposed",
                    "seed": 2000,
                    "run_idx": 0,
                    "assignment_method": "hungarian",
                    "value_weighted_exposure": 9.0,
                    "mean_response_time_s": 18.0,
                    "boundary_message_count": 7.0,
                },
            ]
        )

        deltas_df = tuning.build_method_deltas_vs_frozen(runs_df)
        self.assertTrue(deltas_df.empty)
        self.assertEqual(list(deltas_df.columns), tuning.METHOD_DELTA_COLUMNS)


if __name__ == "__main__":
    unittest.main()
