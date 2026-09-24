"""Full Q1 model. The existing P1 modules are imported, never changed.

Planning assumptions: the Q1 document's energy split is conditional; alpha/beta
are diagnostic multipliers. Only identical cargo subsets may lose dominated
aircraft choices. Global epsilon constraints couple service areas, so epsilon
MILPs must use the full 80-box incidence matrix. A solver time limit is a
reporting limit, never permission to relabel a feasible incumbent as optimal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
from openpyxl import load_workbook
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix, vstack

from src.data.q1_inputs import Aircraft, Cargo, Node, _column_map, _sheet_rows, load_q1_inputs
from src.models.q1_physics import G_M_S2, route_geometry

OBJECTIVES = ("N", "E", "T")
TOL = 1e-8


@dataclass(frozen=True)
class Scenario:
    rho: float
    alpha: float
    beta: float

    @property
    def key(self) -> str:
        return f"r{self.rho:.2f}_a{self.alpha:.1f}_b{self.beta:.1f}"


@dataclass(frozen=True)
class Geometry:
    distance_m: float
    terrain_max_m: float
    sampled_cells: int
    outbound_climb_m: float
    outbound_descent_m: float
    inbound_climb_m: float
    inbound_descent_m: float


@dataclass(frozen=True)
class Batch:
    batch_id: str
    area_id: str
    model_id: str
    mask: int
    cargo_ids: tuple[str, ...]
    mass_kg: float
    volume_m3: float
    energy_kwh: float
    operation_time_s: float
    round_trip_time_s: float
    return_soc: float


def all_scenarios() -> list[Scenario]:
    return [Scenario(r, a, b) for r, a, b in product((.2, .3, .4), (.9, 1., 1.1), (.9, 1., 1.1))]


def load_full_inputs(root: Path) -> tuple[Node, dict[str, Node], dict[str, list[Cargo]], dict[str, Aircraft], list[Path]]:
    """Reuse verified P1 workbook column/parser logic while reading all rows."""
    p1 = load_q1_inputs(root)  # Also verifies the original three-box P1 slice.
    node_path, cargo_path, aircraft_path = p1["input_paths"]
    wb = load_workbook(node_path, read_only=True, data_only=True)
    nodes: dict[str, Node] = {}
    area_ids = [f"S{i:03d}" for i in range(1, 16)]
    columns: dict[str, int] | None = None
    try:
        for row in wb["Data"].iter_rows(values_only=True):
            vals = tuple(row)
            if "Dispatch Center ID" in vals or "Service Area ID" in vals:
                columns = {
                    "id": vals.index("Dispatch Center ID") if "Dispatch Center ID" in vals else vals.index("Service Area ID"),
                    "lon": next((i for i, v in enumerate(vals) if isinstance(v, str) and v.startswith("Longitude")), -1),
                    "lat": next((i for i, v in enumerate(vals) if isinstance(v, str) and v.startswith("Latitude")), -1),
                    "elev": vals.index("Elevation (m)") if "Elevation (m)" in vals else -1,
                }
                if min(columns.values()) < 0:
                    raise ValueError("Malformed node heading")
                continue
            if columns is None or columns["id"] >= len(vals):
                continue
            ident = vals[columns["id"]]
            if isinstance(ident, str) and (ident == "O01" or ident in area_ids):
                if ident in nodes:
                    raise ValueError(f"Duplicate node {ident}")
                nodes[ident] = Node(ident, float(vals[columns["lon"]]), float(vals[columns["lat"]]), float(vals[columns["elev"]]))
    finally:
        wb.close()
    if set(nodes) != {"O01", *area_ids}:
        raise ValueError(f"Expected O01 and S001-S015; got {sorted(nodes)}")

    headings, rows = _sheet_rows(cargo_path, "Cargo Box List")
    cols = _column_map(headings, ("Cargo Box ID", "Service Area ID", "Mass per Box (kg)", "Volume per Box (m³)"), cargo_path.name)
    groups: dict[str, list[Cargo]] = {area: [] for area in area_ids}
    seen: set[str] = set()
    for row in rows:
        ident, area = str(row[cols["Cargo Box ID"]]), str(row[cols["Service Area ID"]])
        if ident in seen or area not in groups:
            raise ValueError(f"Duplicate cargo or unknown area: {ident}/{area}")
        seen.add(ident)
        mass, volume = float(row[cols["Mass per Box (kg)"]]), float(row[cols["Volume per Box (m³)"]])
        if not (math.isfinite(mass) and math.isfinite(volume) and mass > 0 and volume > 0):
            raise ValueError(f"Invalid cargo quantity: {ident}")
        groups[area].append(Cargo(ident, area, mass, volume))
    if len(seen) != 80 or any(not v for v in groups.values()):
        raise ValueError(f"Expected 80 boxes across 15 nonempty areas; got {len(seen)}")
    for boxes in groups.values():
        boxes.sort(key=lambda c: c.cargo_id)
    return nodes["O01"], {k: nodes[k] for k in area_ids}, groups, p1["aircraft"], [node_path, cargo_path, aircraft_path]


def make_geometries(origin: Node, areas: dict[str, Node], dem_path: Path) -> dict[str, Geometry]:
    geometries = {}
    for area, dst in areas.items():
        out_d, out_z, out_n = route_geometry(origin, dst, str(dem_path))
        in_d, in_z, in_n = route_geometry(dst, origin, str(dem_path))
        if abs(out_d - in_d) > 1e-5 or abs(out_z - in_z) > 1e-5:
            raise ValueError(f"Route geometry differs by direction: {area}")
        cruise = out_z + 50.0
        dst_alt = dst.elevation_m + 30.0
        geometries[area] = Geometry(out_d, out_z, max(out_n, in_n),
                                    max(0., cruise - origin.elevation_m), max(0., cruise - dst_alt),
                                    max(0., cruise - dst_alt), max(0., cruise - origin.elevation_m))
    return geometries


def range_m(aircraft: Aircraft, payload: float) -> float:
    return aircraft.unloaded_range_m - (aircraft.unloaded_range_m - aircraft.full_range_m) * (payload / aircraft.payload_capacity_kg) ** 1.5


def flight_energy(aircraft: Aircraft, geom: Geometry, payload: float, scenario: Scenario) -> tuple[float, float, float]:
    """Return energy, flight time, range-fraction for loaded outbound/empty inbound."""
    if not 0 <= payload <= aircraft.payload_capacity_kg + TOL:
        raise ValueError("Payload outside aircraft capacity")
    d = geom.distance_m
    horizontal = aircraft.usable_energy_kwh * d * (1. / range_m(aircraft, payload) + 1. / aircraft.unloaded_range_m)
    ascent = G_M_S2 / (3.6e6 * aircraft.ascent_efficiency) * (
        (aircraft.empty_mass_kg + payload) * geom.outbound_climb_m + aircraft.empty_mass_kg * geom.inbound_climb_m)
    time = ((geom.outbound_climb_m + geom.inbound_climb_m) / aircraft.ascent_speed_m_s
            + 2. * d / aircraft.cruise_speed_m_s
            + (geom.outbound_descent_m + geom.inbound_descent_m) / aircraft.descent_speed_m_s)
    fraction = d / range_m(aircraft, payload) + d / aircraft.unloaded_range_m
    return scenario.alpha * horizontal + scenario.beta * ascent, time, fraction


def max_safe_payload(aircraft: Aircraft, geom: Geometry, scenario: Scenario) -> tuple[str, float | None]:
    """Energy-only continuous boundary per Q1; volume remains a batch constraint."""
    limit = (1. - scenario.rho) * aircraft.usable_energy_kwh
    def feasible(q: float) -> bool:
        energy, _, _ = flight_energy(aircraft, geom, q, scenario)
        return energy <= limit + 1e-10
    if not feasible(0.):
        return "unreachable_empty", None
    if feasible(aircraft.payload_capacity_kg):
        return "capacity_bound", aircraft.payload_capacity_kg
    lo, hi = 0., aircraft.payload_capacity_kg
    for _ in range(54):
        mid = (lo + hi) / 2.
        if feasible(mid):
            lo = mid
        else:
            hi = mid
    if not feasible(lo):
        raise AssertionError("Payload root failed feasibility recheck")
    return "energy_bound", lo


def enumerate_area(area: str, cargoes: list[Cargo], aircrafts: dict[str, Aircraft], geom: Geometry,
                   scenario: Scenario) -> tuple[list[Batch], dict[str, int]]:
    """Enumerate all nonempty local subsets, then Pareto-delete only within a subset.

    Q2 must regenerate its own unpruned archive if aircraft availability matters.
    """
    n = len(cargoes)
    if n > 15:
        raise ValueError(f"Unexpected >15 cargoes in {area}")
    masses = [0.] * (1 << n)
    volumes = [0.] * (1 << n)
    counts = [0] * (1 << n)
    for mask in range(1, 1 << n):
        bit = mask & -mask
        i = bit.bit_length() - 1
        prev = mask ^ bit
        masses[mask] = masses[prev] + cargoes[i].mass_kg
        volumes[mask] = volumes[prev] + cargoes[i].volume_m3
        counts[mask] = counts[prev] + 1
    physical = 0
    retained: list[Batch] = []
    energy_cache: dict[tuple[str, float], tuple[float, float, float]] = {}
    for mask in range(1, 1 << n):
        subset: list[Batch] = []
        mass, volume, count = masses[mask], volumes[mask], counts[mask]
        ids = tuple(cargoes[i].cargo_id for i in range(n) if mask & (1 << i))
        for model, aircraft in sorted(aircrafts.items()):
            if mass > aircraft.payload_capacity_kg + TOL or volume > aircraft.loading_volume_m3 + TOL:
                continue
            cache_key = (model, mass)
            if cache_key not in energy_cache:
                energy_cache[cache_key] = flight_energy(aircraft, geom, mass, scenario)
            energy, flight_time, range_fraction = energy_cache[cache_key]
            soc = 1. - energy / aircraft.usable_energy_kwh
            if soc + 1e-10 < scenario.rho or range_fraction > 1. + 1e-10:
                continue
            hand = aircraft.base_handover_time_s + count * aircraft.handover_time_per_box_s
            round_trip = flight_time + hand
            operation = round_trip + aircraft.prep_time_s + count * aircraft.loading_time_per_box_s
            subset.append(Batch(f"{area}|{model}|{mask:05d}", area, model, mask, ids, mass, volume,
                                energy, operation, round_trip, soc))
        physical += len(subset)
        for candidate in subset:
            if not any(other.batch_id != candidate.batch_id and
                       other.energy_kwh <= candidate.energy_kwh + 1e-10 and
                       other.operation_time_s <= candidate.operation_time_s + 1e-8 and
                       (other.energy_kwh < candidate.energy_kwh - 1e-10 or
                        other.operation_time_s < candidate.operation_time_s - 1e-8 or
                        other.batch_id < candidate.batch_id)
                       for other in subset):
                retained.append(candidate)
    return retained, {"possible": len(aircrafts) * ((1 << n) - 1), "physical": physical,
                      "retained": len(retained), "dominated_removed": physical - len(retained)}


def incidence(cargoes: list[Cargo], batches: list[Batch]) -> csc_matrix:
    idx = {c.cargo_id: i for i, c in enumerate(cargoes)}
    rr, cc = [], []
    for j, batch in enumerate(batches):
        for cargo_id in batch.cargo_ids:
            rr.append(idx[cargo_id]); cc.append(j)
    return csc_matrix((np.ones(len(rr)), (rr, cc)), shape=(len(cargoes), len(batches)))


def objectives(batches: list[Batch]) -> dict[str, np.ndarray]:
    return {"N": np.ones(len(batches)), "E": np.array([b.energy_kwh for b in batches]),
            "T": np.array([b.operation_time_s for b in batches])}


def metrics(selected: list[Batch]) -> dict[str, float]:
    return {"N": len(selected), "E": math.fsum(b.energy_kwh for b in selected),
            "T": math.fsum(b.operation_time_s for b in selected)}


def solve_partition(cargoes: list[Cargo], batches: list[Batch], primary: str,
                    limits: dict[str, float] | None, time_limit_s: float | None) -> dict:
    """One exact MILP call; ``None`` or ``0`` means no solver time limit."""
    if primary not in OBJECTIVES or (time_limit_s is not None and time_limit_s < 0):
        raise ValueError("Invalid primary objective or time limit")
    if not batches:
        return {"status": "infeasible", "selected": [], "metrics": None, "dual_bound": None, "gap": None}
    matrix = incidence(cargoes, batches)
    vectors = objectives(batches)
    limits = limits or {}
    constraints = [matrix]
    lower = [np.ones(len(cargoes))]
    upper = [np.ones(len(cargoes))]
    for name, value in limits.items():
        if name not in OBJECTIVES or not math.isfinite(value):
            raise ValueError(f"Invalid epsilon bound: {name}={value}")
        constraints.append(csc_matrix(vectors[name].reshape(1, -1)))
        lower.append(np.array([-np.inf])); upper.append(np.array([value]))
    mat = vstack(constraints, format="csc")
    options = {"disp": False, "mip_rel_gap": 0.0}
    if time_limit_s not in (None, 0):
        options["time_limit"] = time_limit_s
    res = milp(c=vectors[primary], integrality=np.ones(len(batches)),
               bounds=Bounds(np.zeros(len(batches)), np.ones(len(batches))),
               constraints=LinearConstraint(mat, np.concatenate(lower), np.concatenate(upper)),
               options=options)
    selected: list[Batch] = []
    actual = None
    if res.x is not None and np.all(np.isfinite(res.x)) and np.max(np.abs(res.x - np.rint(res.x))) < 1e-6:
        selected = [b for v, b in zip(res.x, batches) if v > .5]
        counts = {c.cargo_id: 0 for c in cargoes}
        for batch in selected:
            for ident in batch.cargo_ids:
                counts[ident] += 1
        actual = metrics(selected)
        if any(v != 1 for v in counts.values()) or any(actual[k] > bound + 1e-6 * max(1., abs(bound)) for k, bound in limits.items()):
            selected = []; actual = None
    status = "optimal" if res.status == 0 and actual is not None else (
        "infeasible" if res.status == 2 else "time_limit_or_unknown")
    if res.status == 0 and actual is None:
        status = "invalid_incumbent"
    return {"status": status, "solver_status": int(res.status), "message": str(res.message),
            "selected": [b.batch_id for b in selected], "metrics": actual,
            "dual_bound": finite_or_none(getattr(res, "mip_dual_bound", None)),
            "gap": finite_or_none(getattr(res, "mip_gap", None)),
            "node_count": finite_or_none(getattr(res, "mip_node_count", None)),
            "primary": primary, "limits": limits}


def finite_or_none(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def validate_selected(ids: list[str], batch_map: dict[str, Batch], cargoes: list[Cargo],
                      aircrafts: dict[str, Aircraft], geoms: dict[str, Geometry], scenario: Scenario) -> dict[str, float]:
    """Recalculate physical and coverage checks from selected batch records."""
    counts = {c.cargo_id: 0 for c in cargoes}
    selected = []
    for ident in ids:
        b = batch_map[ident]
        a = aircrafts[b.model_id]
        e, t, fraction = flight_energy(a, geoms[b.area_id], b.mass_kg, scenario)
        if abs(e - b.energy_kwh) > 1e-8 or fraction > 1. + 1e-10 or 1. - e / a.usable_energy_kwh < scenario.rho - 1e-10:
            raise AssertionError(f"Physical validation failed: {ident}")
        if b.mass_kg > a.payload_capacity_kg + TOL or b.volume_m3 > a.loading_volume_m3 + TOL:
            raise AssertionError(f"Capacity validation failed: {ident}")
        if abs(t + a.base_handover_time_s + len(b.cargo_ids) * a.handover_time_per_box_s + a.prep_time_s + len(b.cargo_ids) * a.loading_time_per_box_s - b.operation_time_s) > 1e-7:
            raise AssertionError(f"Time validation failed: {ident}")
        for cid in b.cargo_ids:
            counts[cid] += 1
        selected.append(b)
    if any(v != 1 for v in counts.values()):
        raise AssertionError("Cargo coverage is not exactly once")
    return metrics(selected)


def nondominated(solutions: list[dict]) -> list[dict]:
    """Finite sampled nondominated set; integer N is compared exactly."""
    by_id: dict[tuple[str, ...], dict] = {}
    for solution in solutions:
        if solution.get("status") == "optimal" and solution.get("metrics") is not None:
            key = tuple(sorted(solution["selected"]))
            by_id[key] = solution
    vals = list(by_id.values())
    def le(a: dict, b: dict) -> bool:
        return a["N"] <= b["N"] and a["E"] <= b["E"] + 1e-8 and a["T"] <= b["T"] + 1e-6
    def strict(a: dict, b: dict) -> bool:
        return a["N"] < b["N"] or a["E"] < b["E"] - 1e-8 or a["T"] < b["T"] - 1e-6
    front = [x for x in vals if not any(le(y["metrics"], x["metrics"]) and strict(y["metrics"], x["metrics"]) for y in vals if y is not x)]
    # Equal objective triples represent one sampled Pareto point; keep a stable ID.
    unique: list[dict] = []
    for x in sorted(front, key=lambda item: tuple(sorted(item["selected"]))):
        m = x["metrics"]
        if not any(m["N"] == y["metrics"]["N"] and abs(m["E"] - y["metrics"]["E"]) <= 1e-8 and
                   abs(m["T"] - y["metrics"]["T"]) <= 1e-6 for y in unique):
            unique.append(x)
    return sorted(unique, key=lambda x: (x["metrics"]["N"], x["metrics"]["E"], x["metrics"]["T"], tuple(sorted(x["selected"]))))


def representative(front: list[dict], ideals: dict[str, float]) -> tuple[dict, dict[str, float]]:
    if not front:
        raise ValueError("No proven sampled solutions")
    ceilings = {j: max(x["metrics"][j] for x in front) for j in OBJECTIVES}
    def distance(x: dict) -> float:
        return math.sqrt(sum(((x["metrics"][j] - ideals[j]) / (ceilings[j] - ideals[j])) ** 2
                             for j in OBJECTIVES if ceilings[j] > ideals[j] + TOL))
    chosen = min(front, key=lambda x: (round(distance(x), 9), x["metrics"]["N"],
                                       x["metrics"]["E"], x["metrics"]["T"], tuple(sorted(x["selected"]))))
    return chosen, ceilings
