"""Small structural checks for the isolated full Q1 implementation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data.q1_inputs import Cargo
import src.experiments.q1_full as experiment
from src.experiments.q1_full import (_jobs, _levels, _refine_levels, _reuse_certificate,
                                     _limits_contain, atomic_json, read_checkpoint, run_scenario)
from src.models.q1_full import Batch, Geometry, Scenario, max_safe_payload, solve_partition
from src.data.q1_inputs import Aircraft


class Q1FullStructureTests(unittest.TestCase):
    def test_global_epsilon_couples_two_areas(self) -> None:
        cargoes = [Cargo("a", "S001", 1., .01), Cargo("b", "S002", 1., .01)]
        batches = [
            Batch("a-fast", "S001", "A", 1, ("a",), 1., .01, 5., 1., 1., .8),
            Batch("a-slow", "S001", "B", 1, ("a",), 1., .01, 1., 8., 8., .8),
            Batch("b-fast", "S002", "A", 1, ("b",), 1., .01, 5., 1., 1., .8),
            Batch("b-slow", "S002", "B", 1, ("b",), 1., .01, 1., 8., 8., .8),
        ]
        result = solve_partition(cargoes, batches, "T", {"E": 6.}, 10.)
        self.assertEqual(result["status"], "optimal")
        self.assertEqual(result["metrics"], {"N": 2, "E": 6., "T": 9.})
        self.assertEqual(len(result["selected"]), 2)

    def test_epsilon_base_grid_has_363_jobs(self) -> None:
        endpoints = [{"metrics": {"N": 2, "E": 10., "T": 20.}},
                     {"metrics": {"N": 3, "E": 8., "T": 25.}},
                     {"metrics": {"N": 4, "E": 12., "T": 15.}}]
        grid = _jobs(_levels(endpoints), "base")
        self.assertEqual(len(grid), 363)
        self.assertEqual({job["primary"] for job in grid}, {"N", "E", "T"})
        for primary in ("N", "E", "T"):
            subset = [job for job in grid if job["primary"] == primary]
            self.assertEqual(len(subset), 121)
            for i, earlier in enumerate(subset):
                for later in subset[i + 1:]:
                    if all(later["limits"][key] >= earlier["limits"][key] for key in earlier["limits"]):
                        self.assertEqual(later["limits"], earlier["limits"])

    def test_exact_infeasible_certificate_only_for_tighter_limits(self) -> None:
        state = {"endpoints": {}, "epsilon_plan": [{"id": "wide", "primary": "N", "limits": {"E": 8., "T": 8.}}],
                 "epsilon_results": {"wide": {"status": "infeasible", "solver_status": 2,
                                                "selected": [], "metrics": None, "dual_bound": None, "gap": None}}}
        tight = _reuse_certificate({"id": "tight", "primary": "N", "limits": {"E": 7., "T": 7.}}, state)
        self.assertEqual(tight["status"], "infeasible")
        self.assertTrue(tight["reused"])
        self.assertEqual(tight["proof_source"], "wide")
        self.assertIsNone(_reuse_certificate({"id": "not-contained", "primary": "N",
                                              "limits": {"E": 7., "T": 9.}}, state))
        self.assertIsNone(_reuse_certificate({"id": "wrong-primary", "primary": "E",
                                              "limits": {"N": 7., "T": 7.}}, state))
        self.assertFalse(_limits_contain({"E": 7., "T": 7.}, {"E": 7., "T": 8.}))

    def test_optimal_certificate_requires_original_solution_feasible(self) -> None:
        endpoint = {"status": "optimal", "selected": ["batch"],
                    "metrics": {"N": 1, "E": 5., "T": 9.}, "primary_dual_bound": 1.}
        state = {"endpoints": {"N": endpoint}, "epsilon_plan": [], "epsilon_results": {}}
        proven = _reuse_certificate({"id": "yes", "primary": "N", "limits": {"E": 5., "T": 10.}}, state)
        self.assertEqual(proven["status"], "optimal")
        self.assertEqual(proven["dual_bound"], 1.)
        self.assertEqual(proven["gap"], 0.)
        self.assertEqual(proven["proof_source"], "endpoint:N")
        self.assertIsNone(_reuse_certificate({"id": "no", "primary": "N", "limits": {"E": 4.9, "T": 10.}}, state))

    def test_timeout_is_not_a_certificate(self) -> None:
        state = {"endpoints": {}, "epsilon_plan": [{"id": "timeout", "primary": "N", "limits": {"E": 8., "T": 8.}}],
                 "epsilon_results": {"timeout": {"status": "time_limit_or_unknown", "solver_status": 1,
                                                   "selected": ["batch"], "metrics": {"N": 1, "E": 5., "T": 5.},
                                                   "dual_bound": 0., "gap": .5}}}
        self.assertIsNone(_reuse_certificate({"id": "next", "primary": "N", "limits": {"E": 7., "T": 7.}}, state))

    def test_first_unproven_epsilon_pauses_and_resume_retries(self) -> None:
        aircraft = Aircraft("A", 10., 25., .06, 12., 25000., 20000., 4.5, .2,
                            300., 30., 150., 30., 3., 2.5, .72)
        groups = {"S001": [Cargo("box", "S001", 1., .01)]}
        geometry = {"S001": Geometry(1000., 0., 1, 0., 0., 0., 0.)}
        original = experiment.solve_partition
        calls = [0]
        def one_timeout(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 10:  # Nine endpoint lexicographic calls, then first epsilon.
                return {"status": "time_limit_or_unknown", "solver_status": 1,
                        "selected": [], "metrics": None, "dual_bound": .5, "gap": .5,
                        "primary": args[2], "limits": args[3]}
            return original(*args, **kwargs)
        with tempfile.TemporaryDirectory() as temp, patch.object(experiment, "solve_partition", side_effect=one_timeout), \
             patch.object(experiment, "_reuse_certificate", return_value=None), patch.object(experiment, "emit"):
            checkpoint_dir = Path(temp)
            first = run_scenario(Scenario(.2, 1., 1.), groups, {"A": aircraft}, geometry, {"algorithm": "test"},
                                 time_limit_s=10., max_solves=100, resume=False,
                                 checkpoint_dir=checkpoint_dir, publish=False)
            self.assertEqual(first["status"], "incomplete_epsilon")
            self.assertEqual(len(first["epsilon_results"]), 1)
            self.assertEqual(next(iter(first["epsilon_results"].values()))["status"], "time_limit_or_unknown")
            self.assertNotIn("representative", first)
            resumed = run_scenario(Scenario(.2, 1., 1.), groups, {"A": aircraft}, geometry, {"algorithm": "test"},
                                   time_limit_s=20., max_solves=1, resume=True,
                                   checkpoint_dir=checkpoint_dir, publish=False)
            self.assertEqual(resumed["status"], "paused_limit")
            self.assertEqual(len(resumed["retry_history"]), 1)
            self.assertEqual(next(iter(resumed["epsilon_results"].values()))["status"], "optimal")

    def test_all_scenarios_command_stops_after_unproven_scenario(self) -> None:
        with patch.object(experiment.sys, "argv", ["q1_full.py", "--scenario", "all", "--max-scenarios", "2"]), \
             patch.object(experiment, "load_full_inputs", return_value=(None, {"S001": None}, {"S001": [1]}, {}, [])), \
             patch.object(experiment, "make_fingerprint", return_value={"algorithm": "test"}), \
             patch.object(experiment, "make_geometries", return_value={}), \
             patch.object(experiment, "run_scenario", return_value={"status": "incomplete_epsilon"}) as runner, \
             patch.object(experiment, "emit"):
            with self.assertRaises(SystemExit) as caught:
                experiment.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(runner.call_count, 1)

    def test_one_refinement_pass_adds_midpoints_only_where_new_point_lies(self) -> None:
        initial = {"N": [1., 2., 3.], "E": [1., 2., 3.], "T": [1., 2., 3.]}
        front = [{"selected": ["new"], "metrics": {"N": 2, "E": 1.4, "T": 2.4}}]
        refined = _refine_levels(initial, front, set())
        self.assertEqual(refined["N"], initial["N"])
        self.assertEqual(refined["E"], [1., 1.5, 2., 3.])
        self.assertEqual(refined["T"], [1., 2., 2.5, 3.])
        self.assertGreater(len(_jobs(refined, "refine", initial)), 0)

    def test_payload_root_and_rho_monotonicity(self) -> None:
        aircraft = Aircraft("A", 10., 25., .06, 12., 25000., 20000., 4.5, .2,
                            300., 30., 150., 30., 3., 2.5, .72)
        geom = Geometry(9000., 0., 1, 0., 0., 0., 0.)
        status20, q20 = max_safe_payload(aircraft, geom, Scenario(.2, 1., 1.))
        status30, q30 = max_safe_payload(aircraft, geom, Scenario(.3, 1., 1.))
        self.assertEqual(status20, "energy_bound")
        self.assertIsNotNone(q20)
        self.assertTrue(status30 == "unreachable_empty" or q30 <= q20)

    def test_checkpoint_rejects_tampering_and_changed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            atomic_json(path, {"fingerprint": {"input": "abc"}, "status": "paused"})
            self.assertEqual(read_checkpoint(path, {"input": "abc"})["status"], "paused")
            with self.assertRaises(ValueError):
                read_checkpoint(path, {"input": "changed"})
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["status"] = "complete_sampled"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_checkpoint(path, {"input": "abc"})


if __name__ == "__main__":
    unittest.main()
