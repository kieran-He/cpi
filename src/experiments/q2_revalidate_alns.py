"""Independently recheck and refresh exports for a stored Q2 ALNS result."""
from __future__ import annotations

import json

from src.experiments.q2_alns import load_routes
import src.experiments.q2_full as q2_full
from src.experiments.q2_full import (BASELINE, DEM, OUT, export_rows, inputs, sha,
                                    validate_solution)


def main():
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, paths = inputs()
    pool_path = OUT / "candidate_pool.json"
    routes, pool, _ = load_routes(pool_path, cargos, aircrafts, nodes, DEM, meta,
                                  full_charge, BASELINE, 150, 1500)
    report_path = OUT / "alns_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = {"selected": report["chosen"], "delivery_times": report["delivery_times"],
              "metrics": report["metrics"]}
    validation = validate_solution(result, routes, cargos, meta, aircrafts,
                                   drones, batteries, nodes, full_charge)
    report["validation"] = validation
    report["cargo_metadata"] = meta
    report["candidate_pool_sha256"] = sha(pool_path)
    report["input_sha256"] = {str(p): sha(p) for p in paths + [DEM, BASELINE]}
    tmp = report_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    tmp.replace(report_path)
    baseline_dir = OUT / "baseline_lateness"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    q2_full.OUT = baseline_dir
    export_rows(report, cargos, routes)
    print(json.dumps({"status": "PASS", "validation": validation,
                      "route_pool_sha256": report["candidate_pool_sha256"],
                      "outputs": ["results/q2/baseline_lateness/sorties.csv",
                                  "results/q2/baseline_lateness/deliveries.csv",
                                  "results/q2/baseline_lateness/resource_timeline.csv",
                                  "results/q2/baseline_lateness/route_map.csv",
                                  "results/q2/baseline_lateness/timeliness_summary.csv",
                                  "results/q2/baseline_lateness/Q2_Results_Submission_Template.xlsx"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
