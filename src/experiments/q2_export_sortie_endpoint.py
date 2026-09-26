"""Export the saved sorties-first ALNS endpoint to its own workbook and tables."""
from __future__ import annotations

import json

from src.experiments.q2_alns import load_routes
from src.experiments.q2_full import BASELINE, DEM, OUT, export_rows, inputs
import src.experiments.q2_full as q2_full


def main():
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, _ = inputs()
    pool_path = OUT / "candidate_pool_k225.json"
    routes, _, _ = load_routes(pool_path, cargos, aircrafts, nodes, DEM, meta,
                               full_charge, BASELINE, 225, 2250)
    source = OUT / "alns_sortie_endpoint.json"
    report = json.loads(source.read_text(encoding="utf-8"))
    report["cargo_metadata"] = meta
    target_dir = OUT / "sortie_endpoint"
    target_dir.mkdir(parents=True, exist_ok=True)
    q2_full.OUT = target_dir
    export_rows(report, cargos, routes)
    print(json.dumps({"status": "exported", "directory": str(target_dir),
                      "sorties": len(report["chosen"]),
                      "files": ["sorties.csv", "deliveries.csv", "resource_timeline.csv",
                                "route_map.csv", "timeliness_summary.csv",
                                "Q2_Results_Submission_Template.xlsx"]}, ensure_ascii=False))


if __name__ == "__main__":
    import json
    main()
