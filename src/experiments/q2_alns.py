"""Run the bounded Q2 ALNS experiment on the frozen candidate-route pool."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from src.experiments.q2_full import BASELINE, DEM, OUT, inputs, sha, validate_solution, export_rows
import src.experiments.q2_full as q2_full
from src.models.q2_scheduling import Route, Stop, make_pool
from src.models.q2_alns import run_alns


def load_routes(path, cargos, aircrafts, nodes, dem, meta, full_charge, baseline,
                pool_cap, proposal_cap):
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        routes = []
        for raw in payload["routes"]:
            routes.append(Route(
                route_id=raw["route_id"], model=raw["model"],
                stops=tuple(Stop(s["area"], tuple(s["cargo_ids"])) for s in raw["stops"]),
                cargo_ids=tuple(raw["cargo_ids"]), mass=raw["mass_kg"], volume=raw["volume_m3"],
                energy=raw["energy_kwh"], return_s=raw["return_s"], prep_s=raw["prep_s"],
                delivery_offsets=tuple(sorted(raw["delivery_offsets_s"].items())),
                drone_duration=raw["drone_duration_s"], battery_duration=raw["battery_duration_s"],
                return_soc=raw["return_soc"],
            ))
        return routes, payload["summary"], "reused_frozen_pool"
    routes, summary = make_pool(cargos, aircrafts, nodes, dem, meta, full_charge,
                                baseline, pool_cap, proposal_cap)
    return routes, summary, "generated"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--time-limit", type=float, default=900.0,
                        help="ALNS wall-clock limit in seconds")
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--pool-cap", type=int, default=150)
    parser.add_argument("--proposal-cap", type=int, default=1500)
    args = parser.parse_args()
    started = time.monotonic()
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, input_paths = inputs()
    pool_path = OUT / "candidate_pool.json"
    routes, pool, pool_origin = load_routes(pool_path, cargos, aircrafts, nodes,
                                           DEM, meta, full_charge, BASELINE,
                                           args.pool_cap, args.proposal_cap)
    OUT.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"event": "alns_start", "cargo_count": len(cargos),
                      "route_count": len(routes), "pool_origin": pool_origin,
                      "time_limit_s": args.time_limit, "iterations_cap": args.iterations,
                      "seed": args.seed}, ensure_ascii=False), flush=True)
    result = run_alns(routes, cargos, meta, drones, batteries,
                      time_limit_s=args.time_limit, iterations=args.iterations, seed=args.seed)
    if result["status"] != "feasible_heuristic":
        report = {"status": result["status"], "method": "ALNS", "pool": pool,
                  "route_count": len(routes), "pool_origin": pool_origin,
                  "result": result, "elapsed_s": time.monotonic() - started,
                  "generated_utc": datetime.now(timezone.utc).isoformat()}
        target = OUT / "alns_report.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"event": "alns_failed", "status": result["status"],
                          "elapsed_s": report["elapsed_s"]}, ensure_ascii=False), flush=True)
        raise SystemExit(2)

    validation = validate_solution(result, routes, cargos, meta, aircrafts, drones, batteries,
                                   nodes, full_charge)
    report = {
        "status": "feasible_heuristic", "method": "adaptive_large_neighborhood_search",
        "pool": pool, "pool_origin": pool_origin, "route_count": len(routes),
        "candidate_pool_sha256": sha(pool_path), "cargo_metadata": meta,
        "input_sha256": {str(p): sha(p) for p in input_paths},
        "metrics": result["metrics"], "chosen": result["selected"],
        "delivery_times": result["delivery_times"], "validation": validation,
        "iterations": result["iterations"], "seed": result["seed"],
        "elapsed_s": time.monotonic() - started,
        "pareto_archive": result["pareto_archive"],
        "scope": "Feasible heuristic solution; no global or candidate-pool optimality certificate.",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    target = OUT / "alns_report.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(target)
    baseline_dir = OUT / "baseline_lateness"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    q2_full.OUT = baseline_dir
    export_rows(report, cargos, routes)
    print(json.dumps({"event": "alns_complete", "status": report["status"],
                      "metrics": report["metrics"], "iterations": report["iterations"],
                      "archive_count": len(report["pareto_archive"]),
                      "validation": validation, "elapsed_s": report["elapsed_s"]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
