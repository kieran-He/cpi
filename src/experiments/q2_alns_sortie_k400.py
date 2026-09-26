"""Run a time-bounded sorties-first ALNS search on the frozen K=400 pool."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from src.experiments.q2_alns import load_routes
from src.experiments.q2_full import BASELINE, DEM, OUT, inputs, sha, validate_solution
from src.models.q2_alns import run_alns


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--time-limit", type=float, required=True)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    started = time.monotonic()
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, paths = inputs()
    pool_path = OUT / "candidate_pool_k400.json"
    routes, _, _ = load_routes(pool_path, cargos, aircrafts, nodes, DEM, meta,
                               full_charge, BASELINE, 400, 4000)
    result = run_alns(routes, cargos, meta, drones, batteries,
                      time_limit_s=args.time_limit, iterations=args.iterations,
                      seed=args.seed, objective="sorties")
    validation = (validate_solution(result, routes, cargos, meta, aircrafts,
                                    drones, batteries, nodes, full_charge)
                  if result["status"] == "feasible_heuristic" else None)
    report = {
        "status": result["status"], "method": "ALNS_sorties_first_K400",
        "objective_order": result.get("objective_order"),
        "metrics": result.get("metrics"), "chosen": result.get("selected"),
        "delivery_times": result.get("delivery_times"),
        "iterations": result.get("iterations"), "seed": result.get("seed"),
        "solver_elapsed_s": result.get("elapsed_s"),
        "elapsed_s": time.monotonic() - started,
        "time_limit_s": args.time_limit, "iterations_cap": args.iterations,
        "pool_cap_per_model": 400, "proposal_cap_per_model": 4000,
        "route_count": len(routes), "candidate_pool_sha256": sha(pool_path),
        "input_sha256": {str(p): sha(p) for p in paths + [DEM, BASELINE]},
        "validation": validation,
        "scope": "Heuristic sorties-first endpoint over the K=400 candidate pool; no global optimality certificate.",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    target = OUT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                      encoding="utf-8")
    print(json.dumps({"status": report["status"], "metrics": report["metrics"],
                      "iterations": report["iterations"], "validation": validation,
                      "elapsed_s": report["elapsed_s"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
