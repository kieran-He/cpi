"""Audit whether the route-cover lower bound can satisfy Q2 hard windows.

This is a bounded diagnostic on a frozen K=400 candidate pool. It enumerates
all minimum 18-route exact covers, then checks a necessary B-fleet start-deadline
condition with an exact two-drone DFS. Battery constraints are omitted in that
DFS, so a failure is already sufficient to reject the route cover.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix, vstack

from src.experiments.q2_full import BASELINE, DEM, OUT, inputs, sha
from src.models.q2_scheduling import make_pool


def drone_start_feasible(jobs: list[tuple[float, float]], drone_count: int) -> bool:
    """Exact DFS for start deadlines on identical drones, ignoring battery limits."""
    if not jobs:
        return True

    @lru_cache(None)
    def visit(mask: int, ready: tuple[float, ...]) -> bool:
        if mask == (1 << len(jobs)) - 1:
            return True
        for j, (latest_start, duration) in enumerate(jobs):
            if mask & (1 << j):
                continue
            for machine, available in enumerate(ready):
                if available > latest_start + 1e-7:
                    continue
                nxt = list(ready)
                nxt[machine] = available + duration
                if visit(mask | (1 << j), tuple(sorted(round(x, 6) for x in nxt))):
                    return True
        return False

    return visit(0, tuple([0.0] * drone_count))


def main():
    started = time.monotonic()
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, paths = inputs()
    routes, summary = make_pool(cargos, aircrafts, nodes, DEM, meta, full_charge,
                                BASELINE, pool_cap=400, proposal_cap=4000)
    pool_path = OUT / "candidate_pool_k400.json"
    pool_path.write_text(json.dumps({"routes": [r.to_json() for r in routes],
                                     "summary": summary}, ensure_ascii=False),
                         encoding="utf-8")
    cargo_ids = sorted(c.cargo_id for c in cargos)
    cargo_index = {cid: i for i, cid in enumerate(cargo_ids)}
    cover = lil_matrix((len(cargo_ids), len(routes)))
    for j, route in enumerate(routes):
        for cid in route.cargo_ids:
            cover[cargo_index[cid], j] = 1
    cover = cover.tocsr()
    integrality = np.ones(len(routes))
    bounds = Bounds(np.zeros(len(routes)), np.ones(len(routes)))

    minimum = milp(integrality=integrality, c=np.ones(len(routes)), bounds=bounds,
                   constraints=LinearConstraint(cover, np.ones(len(cargo_ids)),
                                                np.ones(len(cargo_ids))),
                   options={"time_limit": 30})
    if minimum.x is None or not minimum.success:
        raise RuntimeError(f"Could not certify route-cover lower bound: {minimum.message}")
    lower_bound = int(round(minimum.fun))

    # Enumerate every cover at the lower-bound cardinality. A count row plus
    # one no-good row after each solution makes exhaustion explicit.
    count_row = lil_matrix((1, len(routes))); count_row[0, :] = 1
    cuts = []
    covers = []
    enumeration_termination_status = None
    enumeration_termination_message = None
    while True:
        matrix = vstack([cover, count_row.tocsr(), *[row for row, _ in cuts]]).tocsr()
        lower = np.r_[np.ones(len(cargo_ids)), -np.inf,
                      np.full(len(cuts), -np.inf)]
        upper = np.r_[np.ones(len(cargo_ids)), lower_bound,
                      np.array([rhs for _, rhs in cuts])]
        solved = milp(integrality=integrality, c=np.ones(len(routes)), bounds=bounds,
                      constraints=LinearConstraint(matrix, lower, upper),
                      options={"time_limit": 30})
        # Do not mistake a time limit or solver error for exhaustion. The
        # enumeration is complete only when the added no-good cuts make the
        # exact-cover model provably infeasible.
        if solved.status == 2:  # scipy.optimize.milp: proven infeasible
            enumeration_termination_status = int(solved.status)
            enumeration_termination_message = str(solved.message)
            break
        if solved.x is None:
            raise RuntimeError(
                "Lower-bound cover enumeration stopped without a solution "
                f"or infeasibility proof (status={solved.status}: {solved.message})"
            )
        selected = np.flatnonzero(solved.x > .5)
        if len(selected) != lower_bound:
            raise RuntimeError("Unexpected route-cover cardinality during enumeration")
        covers.append(selected)
        row = lil_matrix((1, len(routes))); row[0, selected] = 1
        cuts.append((row.tocsr(), lower_bound - 1))
        if len(covers) > 10000:
            raise RuntimeError("Too many lower-bound covers; enumeration cap reached")

    checks = []
    for indices in covers:
        chosen = [routes[j] for j in indices]
        urgent_b = []
        for route in chosen:
            if route.model != "B":
                continue
            hard_latest = [meta[cid]["hard_deadline"] - dict(route.delivery_offsets)[cid]
                           for cid in route.cargo_ids
                           if meta[cid]["hard_deadline"] is not None
                           and meta[cid]["hard_deadline"] <= 3600]
            if hard_latest:
                urgent_b.append((min(hard_latest), route.drone_duration, route.route_id))
        feasible = drone_start_feasible([(latest, duration)
                                         for latest, duration, _ in urgent_b],
                                        len(drones["B"]))
        checks.append({"route_ids": [r.route_id for r in chosen],
                       "routes_by_model": {m: sum(r.model == m for r in chosen)
                                           for m in sorted(aircrafts)},
                       "B_hard_3600_routes": len(urgent_b),
                       "B_hard_latest_starts_s": [round(x[0], 6) for x in sorted(urgent_b)],
                       "B_drone_only_feasible": feasible})

    all_infeasible = bool(checks) and all(not row["B_drone_only_feasible"] for row in checks)
    report = {
        "status": "18_sortie_cover_infeasible_under_candidate_pool" if all_infeasible
                  else "18_sortie_cover_requires_full_schedule_review",
        "pool_cap_per_model": 400, "proposal_cap_per_model": 4000,
        "route_count": len(routes), "counts_by_model": summary["counts_by_model"],
        "candidate_pool_sha256": sha(pool_path),
        "coverage_lower_bound": lower_bound,
        "minimum_covers_enumerated": len(checks),
        "enumeration_termination_status": enumeration_termination_status,
        "enumeration_termination_message": enumeration_termination_message,
        "enumeration_exhaustive": enumeration_termination_status == 2,
        "all_18_covers_fail_B_drone_only_start_deadline_test": all_infeasible,
        "B_drone_count": len(drones["B"]), "cover_checks": checks,
        "input_sha256": {str(p): sha(p) for p in paths + [DEM, BASELINE]},
        "scope": "Candidate-pool route-cover lower bound and a relaxed B-drone test only; not a proof over routes outside K=400.",
        "elapsed_s": time.monotonic() - started,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "sortie_lower_bound.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    tmp.replace(target)
    print(json.dumps({k: report[k] for k in ("status", "route_count", "coverage_lower_bound",
                                             "minimum_covers_enumerated",
                                             "all_18_covers_fail_B_drone_only_start_deadline_test",
                                             "elapsed_s")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
