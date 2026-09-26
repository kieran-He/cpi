"""Targeted ALNS endpoint that minimizes feasible sortie count first."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from src.experiments.q2_alns import load_routes
from src.experiments.q2_full import (BASELINE, DEM, OUT, inputs, sha,
                                    validate_solution)
from src.models.q2_alns import run_alns


def main():
    started = time.monotonic()
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, paths = inputs()
    pool_path = OUT / "candidate_pool_k225.json"
    routes, summary, _ = load_routes(pool_path, cargos, aircrafts, nodes, DEM,
                                     meta, full_charge, BASELINE, 225, 2250)
    result = run_alns(routes, cargos, meta, drones, batteries,
                      time_limit_s=300, iterations=5000, seed=20260927,
                      objective="sorties")
    validation = None
    if result["status"] == "feasible_heuristic":
        validation = validate_solution(result, routes, cargos, meta, aircrafts,
                                       drones, batteries, nodes, full_charge)
    report = {
        "status": result["status"], "method": "ALNS_sorties_first",
        "objective_order": result.get("objective_order"),
        "metrics": result.get("metrics"), "chosen": result.get("selected"),
        "delivery_times": result.get("delivery_times"),
        "pareto_archive": result.get("pareto_archive"),
        "iterations": result.get("iterations"), "seed": result.get("seed"),
        "solver_elapsed_s": result.get("elapsed_s"),
        "elapsed_s": time.monotonic() - started,
        "pool_cap_per_model": 225, "proposal_cap_per_model": 2250,
        "route_count": len(routes), "pool_summary": summary,
        "candidate_pool_sha256": sha(pool_path),
        "input_sha256": {str(p): sha(p) for p in paths + [DEM, BASELINE]},
        "validation": validation,
        "scope": "Heuristic minimum-sortie endpoint; no global optimality certificate.",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    target = OUT / "alns_sortie_endpoint.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    tmp.replace(target)
    print(json.dumps({"status": report["status"], "metrics": report["metrics"],
                      "iterations": report["iterations"], "validation": validation,
                      "elapsed_s": report["elapsed_s"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
