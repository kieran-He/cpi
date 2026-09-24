"""Complete candidate enumeration and exact P1 set-partition solve."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from src.data.q1_inputs import Aircraft, Cargo, Node
from src.models.q1_physics import round_trip


@dataclass(frozen=True)
class Candidate:
    cargoes: tuple[Cargo, ...]
    aircraft: Aircraft
    mass_kg: float
    volume_m3: float
    round_trip_time_s: float
    operation_time_s: float
    energy_kwh: float
    return_soc: float


def enumerate_candidates(cargoes: list[Cargo], aircrafts: dict[str, Aircraft], origin: Node, destination: Node, dem_path: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for size in range(1, len(cargoes) + 1):
        for subset in combinations(cargoes, size):
            mass = sum(c.mass_kg for c in subset)
            volume = sum(c.volume_m3 for c in subset)
            for model_id in sorted(aircrafts):
                aircraft = aircrafts[model_id]
                if mass > aircraft.payload_capacity_kg + 1e-12 or volume > aircraft.loading_volume_m3 + 1e-12:
                    continue
                outbound, inbound = round_trip(origin, destination, aircraft, mass, dem_path)
                energy = outbound.energy_kwh + inbound.energy_kwh
                soc = 1.0 - energy / aircraft.usable_energy_kwh
                if soc + 1e-12 < aircraft.reserve_fraction:
                    continue
                distance_range_fraction = outbound.distance_m / (
                    aircraft.unloaded_range_m - (aircraft.unloaded_range_m-aircraft.full_range_m)*(mass/aircraft.payload_capacity_kg)**1.5
                ) + inbound.distance_m / aircraft.unloaded_range_m
                if distance_range_fraction > 1.0 + 1e-12:
                    continue
                handover = aircraft.base_handover_time_s + size * aircraft.handover_time_per_box_s
                round_trip_time = outbound.flight_time_s + inbound.flight_time_s + handover
                operation_time = round_trip_time + aircraft.prep_time_s + size * aircraft.loading_time_per_box_s
                candidates.append(Candidate(tuple(subset), aircraft, mass, volume, round_trip_time, operation_time, energy, soc))
    return candidates


def solve_exact_set_partition(cargoes: list[Cargo], candidates: list[Candidate]) -> tuple[list[Candidate], dict[str, object]]:
    if not candidates:
        raise ValueError("No feasible batching candidates generated")
    row_index = {cargo.cargo_id: i for i, cargo in enumerate(cargoes)}
    matrix = lil_matrix((len(cargoes), len(candidates)), dtype=float)
    for j, candidate in enumerate(candidates):
        for cargo in candidate.cargoes:
            matrix[row_index[cargo.cargo_id], j] = 1.0
    result = milp(
        c=np.ones(len(candidates)),
        integrality=np.ones(len(candidates)),
        bounds=Bounds(np.zeros(len(candidates)), np.ones(len(candidates))),
        constraints=LinearConstraint(matrix.tocsr(), np.ones(len(cargoes)), np.ones(len(cargoes))),
        options={"disp": False},
    )
    if result.status != 0 or result.x is None:
        raise RuntimeError(f"Exact set-partition MILP did not prove optimality: status={result.status}; {result.message}")
    selected = [candidate for value, candidate in zip(result.x, candidates) if value > 0.5]
    return selected, {"solver": "scipy.optimize.milp (HiGHS)", "status": int(result.status), "message": str(result.message),
                      "objective_sorties": int(round(float(result.fun))), "mip_gap": getattr(result, "mip_gap", None),
                      "mip_node_count": getattr(result, "mip_node_count", None)}
