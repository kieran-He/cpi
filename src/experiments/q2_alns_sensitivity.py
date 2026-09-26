"""Compare ALNS outcomes across smaller and larger candidate-route pools."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from src.experiments.q2_full import (BASELINE, DEM, OUT, inputs, sha,
                                     validate_solution)
from src.models.q2_scheduling import make_pool
from src.models.q2_alns import run_alns


def main():
    started = time.monotonic()
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, input_paths = inputs()
    runs = []
    for cap, seed in ((100, 20260925), (225, 20260926)):
        pool_started = time.monotonic()
        routes, summary = make_pool(cargos, aircrafts, nodes, DEM, meta, full_charge,
                                    BASELINE, cap, 10 * cap)
        pool_seconds = time.monotonic() - pool_started
        covered = set(c for r in routes for c in r.cargo_ids)
        if covered != {c.cargo_id for c in cargos}:
            raise ValueError(f"K={cap} candidate pool does not cover all cargo")
        pool_file = OUT / f"candidate_pool_k{cap}.json"
        pool_file.write_text(json.dumps({"routes": [r.to_json() for r in routes],
                                        "summary": summary}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        result = run_alns(routes, cargos, meta, drones, batteries,
                          time_limit_s=180.0, iterations=3000, seed=seed)
        validation = None
        if result["status"] == "feasible_heuristic":
            validation = validate_solution(result, routes, cargos, meta,
                                           aircrafts, drones, batteries, nodes, full_charge)
        runs.append({"pool_cap_per_model": cap, "proposal_cap_per_model": 10 * cap,
                     "route_count": len(routes), "pool_elapsed_s": pool_seconds,
                     "pool_summary": summary, "alns": result,
                     "validation": validation, "pool_file": str(pool_file)})
        print(json.dumps({"event": "sensitivity_run", "pool_cap": cap,
                          "route_count": len(routes), "metrics": result.get("metrics"),
                          "status": result["status"], "pool_elapsed_s": pool_seconds,
                          "alns_elapsed_s": result.get("elapsed_s"),
                          "validation": validation}, ensure_ascii=False), flush=True)
    report = {
        "status": "complete_heuristic_sensitivity",
        "baseline": "results/q2/alns_report.json (K=150, R=1500 per model)",
        "runs": runs,
        "input_sha256": {str(p): sha(p) for p in input_paths},
        "elapsed_s": time.monotonic() - started,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "interpretation": "Heuristic sensitivity only; candidate pools and ALNS seeds differ, so this is not an optimality comparison.",
    }
    target = OUT / "alns_sensitivity.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    tmp.replace(target)
    print(json.dumps({"event": "sensitivity_complete", "elapsed_s": report["elapsed_s"],
                      "runs": len(runs)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
