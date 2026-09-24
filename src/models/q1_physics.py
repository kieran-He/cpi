"""Q1 physical calculations using the explicitly conditional Q1 baseline."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.transform import rowcol

from src.data.q1_inputs import Aircraft, Node

G_M_S2 = 9.81


@dataclass(frozen=True)
class Leg:
    distance_m: float
    terrain_max_m: float
    cruise_altitude_m: float
    climb_m: float
    descent_m: float
    flight_time_s: float
    horizontal_energy_kwh: float
    climb_energy_kwh: float
    payload_kg: float
    sampled_cells: int

    @property
    def energy_kwh(self) -> float:
        return self.horizontal_energy_kwh + self.climb_energy_kwh


def _supercover_cells(c0: float, r0: float, c1: float, r1: float) -> set[tuple[int, int]]:
    """Grid cells traversed by a segment in pixel coordinates (including corner touches)."""
    # Rasterio's inverse affine maps coordinates into cells whose boundaries
    # are integer column/row values (indexing uses floor).
    x0, y0, x1, y1 = c0, r0, c1, r1
    ix, iy = math.floor(x0), math.floor(y0)
    ex, ey = math.floor(x1), math.floor(y1)
    dx, dy = x1 - x0, y1 - y0
    sx = 1 if dx > 0 else (-1 if dx < 0 else 0)
    sy = 1 if dy > 0 else (-1 if dy < 0 else 0)
    tdx = abs(1.0 / dx) if dx else math.inf
    tdy = abs(1.0 / dy) if dy else math.inf
    next_x = ((ix + 1 - x0) / dx if dx > 0 else (x0 - ix) / -dx) if dx else math.inf
    next_y = ((iy + 1 - y0) / dy if dy > 0 else (y0 - iy) / -dy) if dy else math.inf
    cells = {(ix, iy), (ex, ey)}
    while (ix, iy) != (ex, ey):
        if abs(next_x - next_y) < 1e-12:
            cells.update({(ix + sx, iy), (ix, iy + sy)})
            ix += sx; iy += sy
            next_x += tdx; next_y += tdy
        elif next_x < next_y:
            ix += sx; next_x += tdx
        else:
            iy += sy; next_y += tdy
        cells.add((ix, iy))
    return cells


def route_geometry(src: Node, dst: Node, dem_path: str) -> tuple[float, float, int]:
    # UTM zone is selected from the verified longitude, not inferred from degree deltas.
    zone = int((src.longitude_deg + 180.0) // 6.0) + 1
    metric_crs = CRS.from_epsg((32600 if src.latitude_deg >= 0 else 32700) + zone)
    to_metric = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True)
    to_dem = Transformer.from_crs(metric_crs, "EPSG:4326", always_xy=True)
    x0, y0 = to_metric.transform(src.longitude_deg, src.latitude_deg)
    x1, y1 = to_metric.transform(dst.longitude_deg, dst.latitude_deg)
    distance = math.hypot(x1 - x0, y1 - y0)
    with rasterio.open(dem_path) as ds:
        if ds.crs is None:
            raise ValueError("DEM has no CRS")
        pixel_to_dem = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
        # Dense projected-line nodes plus exact grid traversal between consecutive nodes
        # conservatively collect the raster cells crossed by the projected straight route.
        p0 = to_metric.transform(*px_lonlat(ds, 0, 0))
        p1 = to_metric.transform(*px_lonlat(ds, 1, 0))
        p2 = to_metric.transform(*px_lonlat(ds, 0, 1))
        cell_m = min(math.dist(p0, p1), math.dist(p0, p2))
        n = max(1, math.ceil(distance / max(cell_m / 4.0, 1.0)))
        cells: set[tuple[int, int]] = set()
        for k in range(n + 1):
            f = k / n
            lon, lat = to_dem.transform(x0 + f * (x1 - x0), y0 + f * (y1 - y0))
            colf, rowf = (~ds.transform) * (lon, lat)
            cells.add((math.floor(colf), math.floor(rowf)))
        # For each successive sampled point, include every crossed raster cell.
        coords = []
        for k in range(n + 1):
            f = k / n
            lon, lat = to_dem.transform(x0 + f * (x1 - x0), y0 + f * (y1 - y0))
            coords.append((~ds.transform) * (lon, lat))
        for a, b in zip(coords, coords[1:]):
            cells.update(_supercover_cells(a[0], a[1], b[0], b[1]))
        values = []
        for col, row in cells:
            if not (0 <= col < ds.width and 0 <= row < ds.height):
                raise ValueError(f"Route intersects DEM boundary/outside cell ({col},{row})")
            value = float(ds.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
            if ds.nodata is not None and math.isclose(value, ds.nodata, rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"Route intersects DEM NoData cell ({col},{row})")
            if not math.isfinite(value):
                raise ValueError(f"Route intersects non-finite DEM cell ({col},{row})")
            values.append(value)
        return distance, max(values), len(cells)


def px_lonlat(ds: rasterio.io.DatasetReader, col: float, row: float) -> tuple[float, float]:
    return ds.transform * (col, row)


def leg(src: Node, dst: Node, aircraft: Aircraft, payload_kg: float, dem_path: str) -> Leg:
    if not (0 <= payload_kg <= aircraft.payload_capacity_kg):
        raise ValueError(f"Payload {payload_kg} kg outside model {aircraft.model_id} capacity")
    distance, terrain_max, sampled_cells = route_geometry(src, dst, dem_path)
    source_op = src.elevation_m if src.node_id == "O01" else src.elevation_m + 30.0
    dest_op = dst.elevation_m if dst.node_id == "O01" else dst.elevation_m + 30.0
    cruise_alt = terrain_max + 50.0
    climb = max(0.0, cruise_alt - source_op)
    descent = max(0.0, cruise_alt - dest_op)
    loaded_range = aircraft.unloaded_range_m - (aircraft.unloaded_range_m - aircraft.full_range_m) * (payload_kg / aircraft.payload_capacity_kg) ** 1.5
    if loaded_range <= 0:
        raise ValueError(f"Non-positive modeled range for aircraft {aircraft.model_id}")
    flight_time = climb / aircraft.ascent_speed_m_s + distance / aircraft.cruise_speed_m_s + descent / aircraft.descent_speed_m_s
    horizontal = aircraft.usable_energy_kwh * distance / loaded_range
    ascent = (aircraft.empty_mass_kg + payload_kg) * G_M_S2 * climb / (3.6e6 * aircraft.ascent_efficiency)
    return Leg(distance, terrain_max, cruise_alt, climb, descent, flight_time, horizontal, ascent, payload_kg, sampled_cells)


def round_trip(src: Node, dst: Node, aircraft: Aircraft, payload_kg: float, dem_path: str) -> tuple[Leg, Leg]:
    return leg(src, dst, aircraft, payload_kg, dem_path), leg(dst, src, aircraft, 0.0, dem_path)
