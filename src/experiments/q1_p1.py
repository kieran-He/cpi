"""Run the real-data Q1 P1 vertical slice from the project root.

Command: python -m src.experiments.q1_p1
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyproj
import rasterio
import scipy

from src.data.q1_inputs import load_q1_inputs
from src.models.q1_batching import enumerate_candidates, solve_exact_set_partition
from src.models.q1_physics import round_trip

ROOT = Path(__file__).resolve().parents[2]
DEM = ROOT / "questions" / "Data" / "Zhenlong Township Geospatial Data" / "Geospatial Data for Zhenlong Township and Surrounding Areas" / "Digital Elevation Model (DEM) Data" / "30 m DEM for Zhenlong Township and Surrounding Areas.tif"
CSV_OUT = ROOT / "results" / "tables" / "q1_p1_batches.csv"
JSON_OUT = ROOT / "results" / "logs" / "q1_p1_validation.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    inputs = load_q1_inputs(ROOT)
    origin = inputs["nodes"]["O01"]
    destination = inputs["nodes"]["S001"]
    cargoes = inputs["cargos"]
    aircrafts = inputs["aircraft"]
    candidates = enumerate_candidates(cargoes, aircrafts, origin, destination, str(DEM))
    selected, solver = solve_exact_set_partition(cargoes, candidates)

    # Independent post-solve validation from selected rows and raw input objects.
    coverage = {cargo.cargo_id: 0 for cargo in cargoes}
    rows = []
    audit = []
    for index, candidate in enumerate(selected, 1):
        for cargo in candidate.cargoes:
            coverage[cargo.cargo_id] += 1
        outbound, inbound = round_trip(origin, destination, candidate.aircraft, candidate.mass_kg, str(DEM))
        recalculated_energy = outbound.energy_kwh + inbound.energy_kwh
        recalculated_soc = 1.0 - recalculated_energy / candidate.aircraft.usable_energy_kwh
        assert abs(recalculated_energy - candidate.energy_kwh) < 1e-12
        assert abs(recalculated_soc - candidate.return_soc) < 1e-12
        assert candidate.mass_kg <= candidate.aircraft.payload_capacity_kg + 1e-12
        assert candidate.volume_m3 <= candidate.aircraft.loading_volume_m3 + 1e-12
        assert recalculated_soc + 1e-12 >= candidate.aircraft.reserve_fraction
        assert outbound.payload_kg == candidate.mass_kg and inbound.payload_kg == 0.0
        assert outbound.distance_m / (candidate.aircraft.unloaded_range_m - (candidate.aircraft.unloaded_range_m-candidate.aircraft.full_range_m)*(candidate.mass_kg/candidate.aircraft.payload_capacity_kg)**1.5) + inbound.distance_m / candidate.aircraft.unloaded_range_m <= 1.0 + 1e-12
        ids = sorted(c.cargo_id for c in candidate.cargoes)
        rows.append({
            "Sortie ID": f"P1-{index:02d}", "Service Area ID": "S001", "Model ID": candidate.aircraft.model_id,
            "Cargo Box ID List": ", ".join(ids), "Total Mass (kg)": candidate.mass_kg,
            "Total Volume (m³)": candidate.volume_m3, "Round-Trip Time (s)": candidate.round_trip_time_s,
            "Sortie Energy (kWh)": candidate.energy_kwh, "Return SOC (%)": 100.0 * candidate.return_soc,
        })
        audit.append({
            "sortie_id": f"P1-{index:02d}", "cargo_ids": ids, "outbound_payload_kg": outbound.payload_kg,
            "return_payload_kg": inbound.payload_kg, "outbound_range_fraction": outbound.distance_m / (
                candidate.aircraft.unloaded_range_m - (candidate.aircraft.unloaded_range_m-candidate.aircraft.full_range_m)*(candidate.mass_kg/candidate.aircraft.payload_capacity_kg)**1.5
            ), "return_range_fraction": inbound.distance_m / candidate.aircraft.unloaded_range_m,
            "outbound_distance_m": outbound.distance_m, "return_distance_m": inbound.distance_m,
            "outbound_terrain_max_m": outbound.terrain_max_m, "return_terrain_max_m": inbound.terrain_max_m,
            "outbound_dem_cells_sampled": outbound.sampled_cells, "return_dem_cells_sampled": inbound.sampled_cells,
            "outbound_energy_kwh": outbound.energy_kwh, "return_energy_kwh": inbound.energy_kwh,
            "energy_kwh_recomputed": recalculated_energy, "return_soc_percent_recomputed": 100.0 * recalculated_soc,
            "round_trip_flight_and_handover_s": candidate.round_trip_time_s,
            "total_operation_time_s_including_prep_loading": candidate.operation_time_s,
        })
    if any(count != 1 for count in coverage.values()):
        raise AssertionError(f"Set partition coverage failed: {coverage}")

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    with rasterio.open(DEM) as ds:
        dem_info = {"driver": ds.driver, "width": ds.width, "height": ds.height, "bands": ds.count,
                    "dtype": ds.dtypes[0], "nodata": ds.nodata, "crs": ds.crs.to_string(),
                    "transform": list(ds.transform), "bounds": [ds.bounds.left, ds.bounds.bottom, ds.bounds.right, ds.bounds.top],
                    "resolution_degrees": list(ds.res), "area_or_point": ds.tags().get("AREA_OR_POINT")}
    total_mass = sum(c.mass_kg for c in cargoes)
    total_volume = sum(c.volume_m3 for c in cargoes)
    report = {
        "status": "P1_SLICE_EXECUTED_NOT_INDEPENDENTLY_REVIEWED",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "reproduction_command": f'"{sys.executable}" -m src.experiments.q1_p1',
        "scope": {"origin": "O01", "destination": "S001", "cargo_ids": [c.cargo_id for c in cargoes],
                  "total_cargo_rows_in_source": inputs["all_cargo_count"], "candidate_count": len(candidates),
                  "selected_sorties": len(selected), "objective": "minimize number of sorties", "pareto_or_sensitivity_run": False},
        "source_field_audit": {"dispatch_workbook": {"coordinate_fields": ["Longitude (degrees)", "Latitude (degrees)"], "elevation_field": "Elevation (m)"},
                                "cargo_sheet": "Cargo Box List", "cargo_fields": ["Cargo Box ID", "Service Area ID", "Mass per Box (kg)", "Volume per Box (m³)"],
                                "aircraft_sheet": "Data", "units": {"mass": "kg", "volume": "m^3", "distance": "m", "speed": "m/s", "energy": "kWh", "time": "s", "return_reserve": "fraction from source percent"},
                                "cargo_values": [{"id": c.cargo_id, "mass_kg": c.mass_kg, "volume_m3": c.volume_m3} for c in cargoes],
                                "nodes": {k: {"longitude_deg": v.longitude_deg, "latitude_deg": v.latitude_deg, "elevation_m": v.elevation_m} for k, v in {"O01": origin, "S001": destination}.items()},
                                "aircraft_model_ids": sorted(aircrafts),
                                "aircraft_parameters": {model: {"payload_capacity_kg": a.payload_capacity_kg, "loading_volume_m3": a.loading_volume_m3,
                                    "unloaded_range_m": a.unloaded_range_m, "full_range_m": a.full_range_m,
                                    "usable_energy_kwh": a.usable_energy_kwh, "return_reserve_fraction": a.reserve_fraction,
                                    "cruise_speed_m_s": a.cruise_speed_m_s, "ascent_speed_m_s": a.ascent_speed_m_s,
                                    "descent_speed_m_s": a.descent_speed_m_s, "ascent_efficiency": a.ascent_efficiency,
                                    "preparation_time_s": a.prep_time_s, "loading_time_per_box_s": a.loading_time_per_box_s,
                                    "base_handover_time_s": a.base_handover_time_s, "handover_time_per_box_s": a.handover_time_per_box_s}
                                    for model, a in aircrafts.items()}},
        "dem": dem_info,
        "coordinate_method": {"projected_crs": "UTM zone derived from origin longitude, WGS84 / UTM zone 49N (EPSG:32649)",
                              "distance": "Euclidean distance between projected endpoints; raster route sampled along projected straight segment, including crossed cells"},
        "energy_model": {"source": "analysis/problems/Q1.md conditional baseline", "alpha": 1.0, "beta": 1.0,
                         "formula_horizontal": "E_use * d / L(q)", "formula_ascent": "(M+q)*9.81*h/(3.6e6*eta_up)",
                         "return_payload_kg": 0.0, "reserve_source": "Minimum Return Battery Level (%) from aircraft workbook"},
        "solver": solver,
        "validation": {"box_exactly_once": coverage, "all_boxes_covered_once": True, "mass_kg_total": total_mass,
                       "volume_m3_total": total_volume, "physical_checks_pass": True,
                       "outbound_uses_batch_payload_return_uses_zero": True,
                       "route_leg_audit": audit, "max_single_box_mass_kg": max(c.mass_kg for c in cargoes),
                       "empty_payload_round_trip_by_model": {},
                       "candidate_enumeration_complete": True,
                       "candidate_theoretical_upper_bound": (2 ** len(cargoes) - 1) * len(aircrafts),
                       "feasible_candidates_enumerated": len(candidates)},
        "runtime": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
                    "scipy": scipy.__version__, "rasterio": rasterio.__version__, "pyproj": pyproj.__version__},
        "inputs_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in inputs["input_paths"] + [DEM]},
        "outputs": {"csv": str(CSV_OUT.relative_to(ROOT))},
    }
    # Explicitly audit empty-payload reachability per model using the same physical function.
    for model_id, aircraft in aircrafts.items():
        out, back = round_trip(origin, destination, aircraft, 0.0, str(DEM))
        empty_energy = out.energy_kwh + back.energy_kwh
        empty_soc = 1.0 - empty_energy / aircraft.usable_energy_kwh
        report["validation"]["empty_payload_round_trip_by_model"][model_id] = {
            "energy_kwh": empty_energy, "return_soc_percent": 100 * empty_soc,
            "reserve_fraction": aircraft.reserve_fraction, "feasible": empty_soc + 1e-12 >= aircraft.reserve_fraction,
        }
    report["validation"]["physical_checks_pass"] = True  # Reaching here means every explicit assertion above passed.
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "csv": str(CSV_OUT.relative_to(ROOT)), "json": str(JSON_OUT.relative_to(ROOT)),
                      "candidates": len(candidates), "selected_sorties": len(selected), "cargo_ids": [c.cargo_id for c in cargoes],
                      "solver": solver}, ensure_ascii=False))


if __name__ == "__main__":
    main()
