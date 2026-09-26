"""Export the best saved K=400 sorties-first ALNS endpoint as the canonical Q2 result."""
from __future__ import annotations

import json

from src.experiments.q2_alns import load_routes
from src.experiments.q2_full import (BASELINE, DEM, OUT, export_rows, inputs,
                                    validate_solution)
import src.experiments.q2_full as q2_full


def main():
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, _ = inputs()
    pool_path = OUT / "candidate_pool_k400.json"
    routes, _, _ = load_routes(pool_path, cargos, aircrafts, nodes, DEM, meta,
                               full_charge, BASELINE, 400, 4000)
    report_path = OUT / "alns_sortie_k400_seed20260929.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["cargo_metadata"] = meta
    solution = {"selected": report["chosen"],
                "delivery_times": report["delivery_times"],
                "metrics": report["metrics"]}
    validation = validate_solution(solution, routes, cargos, meta, aircrafts, drones,
                                   batteries, nodes, full_charge)
    if validation["status"] != "PASS":
        raise ValueError(f"Stored K=400 result failed revalidation: {validation}")
    report["validation"] = validation
    target_dir = OUT
    target_dir.mkdir(parents=True, exist_ok=True)
    q2_full.OUT = target_dir
    export_rows(report, cargos, routes)
    print(json.dumps({"status": "exported", "directory": str(target_dir),
                      "sorties": len(report["chosen"]), "cargo_count": len(report["delivery_times"]),
                      "validation": validation["status"],
                      "checks": validation["checks"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
