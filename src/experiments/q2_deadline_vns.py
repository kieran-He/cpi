"""Deadline-oriented route enrichment plus tabu-guided variable-neighborhood repair."""
from __future__ import annotations

import argparse
import itertools
import json
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix, vstack

from src.experiments.q2_alns import load_routes
from src.experiments.q2_full import BASELINE, DEM, OUT, inputs, sha, validate_solution
from src.models.q2_alns import _State, _destroy, _lex, _repair, schedule
from src.models.q2_scheduling import Route, Stop, build_route


def _route_json(route: Route) -> dict:
    return route.to_json()


def _make_deadline_routes(cargos, metadata, aircrafts, nodes, full_charge,
                          base_routes, proposal_cap: int):
    cargo_by_id = {c.cargo_id: c for c in cargos}
    urgent_by_area: dict[str, list[str]] = defaultdict(list)
    for c in cargos:
        deadline = metadata[c.cargo_id]["hard_deadline"]
        if deadline is not None and deadline <= 3600:
            urgent_by_area[c.service_area_id].append(c.cargo_id)
    areas = sorted(urgent_by_area)
    cache: dict = {}
    base_ids = {r.route_id for r in base_routes}
    generated: dict[str, Route] = {}
    proposals = 0
    urgent_ids = {c for values in urgent_by_area.values() for c in values}
    nonurgent = [c for c in cargos if c.cargo_id not in urgent_ids]

    def offer(model, stops):
        nonlocal proposals
        if proposals >= proposal_cap:
            return None
        proposals += 1
        route = build_route(model, tuple(stops), cargo_by_id, aircrafts[model],
                            nodes, DEM, cache, metadata, full_charge[model])
        if route is None or route.route_id in base_ids:
            return None
        generated[route.route_id] = route
        return route

    # Pair urgency-dense areas, exploring both visit orders and within-stop
    # service sequences. This deliberately targets route patterns absent from
    # the deterministic K=400 pool.
    # B is the bottleneck identified by the relaxed deadline audit, so reserve
    # the proposal budget for its route variants first.
    for model in sorted(aircrafts, key=lambda m: (m != "B", m)):
        for area_a, area_b in itertools.combinations(areas, 2):
            for count_a in range(1, len(urgent_by_area[area_a]) + 1):
                for cargos_a in itertools.combinations(urgent_by_area[area_a], count_a):
                    for count_b in range(1, len(urgent_by_area[area_b]) + 1):
                        for cargos_b in itertools.combinations(urgent_by_area[area_b], count_b):
                            for order in ((area_a, area_b), (area_b, area_a)):
                                for seq_a in itertools.permutations(cargos_a):
                                    for seq_b in itertools.permutations(cargos_b):
                                        if proposals >= proposal_cap:
                                            break
                                        first, second = ((Stop(area_a, seq_a), Stop(area_b, seq_b))
                                                         if order[0] == area_a else
                                                         (Stop(area_b, seq_b), Stop(area_a, seq_a)))
                                        route = offer(model, (first, second))
                                        if route is None:
                                            continue
                                        # Add later-deadline boxes at already
                                        # visited sites, preserving urgent-first
                                        # service order. Keep every feasible
                                        # intermediate route as a column.
                                        current = route
                                        for _ in range(3):
                                            best = None
                                            used = set(current.cargo_ids)
                                            for cargo in nonurgent:
                                                if cargo.cargo_id in used:
                                                    continue
                                                for si, stop in enumerate(current.stops):
                                                    if stop.area != cargo.service_area_id:
                                                        continue
                                                    candidate_stops = (current.stops[:si]
                                                        + (Stop(stop.area, stop.cargo_ids + (cargo.cargo_id,)),)
                                                        + current.stops[si + 1:])
                                                    candidate = offer(model, candidate_stops)
                                                    if candidate is None:
                                                        continue
                                                    key = (candidate.drone_duration-current.drone_duration,
                                                           candidate.energy-current.energy,
                                                           candidate.route_id)
                                                    if best is None or key < best[0]:
                                                        best = (key, candidate)
                                                if proposals >= proposal_cap:
                                                    break
                                            if best is None:
                                                break
                                            current = best[1]
                                        if proposals >= proposal_cap:
                                            break
                                    if proposals >= proposal_cap:
                                        break
                                if proposals >= proposal_cap:
                                    break
                            if proposals >= proposal_cap:
                                break
                        if proposals >= proposal_cap:
                            break
                    if proposals >= proposal_cap:
                        break
                if proposals >= proposal_cap:
                    break
            if proposals >= proposal_cap:
                break
        if proposals >= proposal_cap:
            break
    return list(generated.values()), {
        "urgent_area_count": len(areas), "urgent_cargo_count": len(urgent_ids),
        "proposals": proposals, "unique_routes_added": len(generated),
        "candidate_urgent_area_pairs": len(list(itertools.combinations(areas, 2))),
        "scope": "two urgent areas per route, both stop orders, urgent within-stop permutations, up to three later-deadline insertions at visited stops",
    }


def _exact_cover_probe(routes, cargos, metadata, time_limit_s=45):
    cargo_ids = [c.cargo_id for c in cargos]
    idx = {cid: i for i, cid in enumerate(cargo_ids)}
    cover = lil_matrix((len(cargo_ids), len(routes)))
    for j, route in enumerate(routes):
        for cid in route.cargo_ids:
            cover[idx[cid], j] = 1
    cover = cover.tocsr()
    count = lil_matrix((1, len(routes))); count[0, :] = 1
    urgent_b = lil_matrix((1, len(routes)))
    for j, route in enumerate(routes):
        if route.model == "B" and any(metadata[cid]["hard_deadline"] is not None
            and metadata[cid]["hard_deadline"] <= 3600 for cid in route.cargo_ids):
            urgent_b[0, j] = 1
    matrix = vstack([cover, count.tocsr(), urgent_b.tocsr()]).tocsr()
    lower = np.r_[np.ones(len(cargo_ids)), -np.inf, -np.inf]
    upper = np.r_[np.ones(len(cargo_ids)), 18, 4]
    res = milp(c=np.ones(len(routes)), integrality=np.ones(len(routes)),
        bounds=Bounds(np.zeros(len(routes)), np.ones(len(routes))),
        constraints=LinearConstraint(matrix, lower, upper),
        options={"time_limit": time_limit_s})
    selected = None
    if res.x is not None and res.fun is not None and round(res.fun) <= 18:
        selected = [routes[j] for j in np.flatnonzero(res.x > .5)]
    return {"status": int(res.status), "message": str(res.message),
            "objective": None if res.fun is None else float(res.fun),
            "cover_at_most_18_with_at_most_4_B_urgent_routes": selected is not None,
            "selected_route_ids": [] if selected is None else [r.route_id for r in selected]}, selected


def _vns(routes, initial_routes, cargos, metadata, drones, batteries,
         time_limit_s, seed, max_iterations):
    rng = random.Random(seed)
    deadline = time.monotonic() + time_limit_s
    by_cargo = {c.cargo_id: [] for c in cargos}
    for route in routes:
        for cid in route.cargo_ids:
            by_cargo[cid].append(route)
    for rows in by_cargo.values():
        rows.sort(key=lambda r: (-len(r.cargo_ids), r.drone_duration,
                                 r.energy, r.route_id))
    initial_schedule = schedule(initial_routes, cargos, metadata, drones, batteries,
                                seed, deadline)
    if initial_schedule is None:
        raise RuntimeError("Saved feasible incumbent failed to schedule in VNS initialization")
    current = _State(list(initial_routes), initial_schedule)
    best = current
    neighborhoods = [1, 2, 3, 4, 6, 8, 10]
    operators = ["random", "related", "worst", "critical"]
    current_k = 0
    tabu = set()
    tabu_queue = deque()
    archive = {tuple(sorted(r.route_id for r in current.routes)): current}
    iterations = 0
    while iterations < max_iterations and time.monotonic() < deadline:
        k = neighborhoods[current_k]
        operator = operators[iterations % len(operators)]
        if operator == "critical":
            def urgency(route):
                vals = [metadata[cid]["hard_deadline"] - dict(route.delivery_offsets)[cid]
                        for cid in route.cargo_ids if metadata[cid]["hard_deadline"] is not None]
                return (min(vals, default=float("inf")), route.route_id)
            removed = sorted(current.routes, key=urgency)[:k]
        else:
            removed = _destroy(current, operator, rng, k, metadata)
        removed_ids = {r.route_id for r in removed}
        candidate = _repair([r for r in current.routes if r.route_id not in removed_ids],
            cargos, metadata, drones, batteries, by_cargo, rng, deadline,
            top_k=32, randomized=True)
        iterations += 1
        if candidate is None or time.monotonic() >= deadline:
            current_k = min(current_k + 1, len(neighborhoods) - 1)
            if current_k == len(neighborhoods) - 1 and iterations % 25 == 0:
                current = best
            continue
        signature = tuple(sorted(r.route_id for r in candidate.routes))
        score = _lex(candidate, ("sorties", "late", "makespan", "energy"))
        current_score = _lex(current, ("sorties", "late", "makespan", "energy"))
        if signature in tabu and score >= _lex(best, ("sorties", "late", "makespan", "energy")):
            current_k = min(current_k + 1, len(neighborhoods) - 1)
            continue
        if signature not in tabu:
            tabu.add(signature); tabu_queue.append(signature)
            while len(tabu) > 500:
                tabu.discard(tabu_queue.popleft())
        archive[signature] = candidate
        if score < _lex(best, ("sorties", "late", "makespan", "energy")):
            best = candidate
        if score < current_score:
            current = candidate
            current_k = 0
        else:
            current_k = min(current_k + 1, len(neighborhoods) - 1)
            if current_k == len(neighborhoods) - 1 and iterations % 25 == 0:
                current = best
    return best, {"iterations": iterations, "tabu_signatures": len(tabu),
                   "archive_size": len(archive), "elapsed_s": time_limit_s-(deadline-time.monotonic())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--time-limit", type=float, default=600)
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260930)
    parser.add_argument("--route-proposal-cap", type=int, default=7000)
    args = parser.parse_args()
    started = time.monotonic()
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, paths = inputs()
    pool_path = OUT / "candidate_pool_k400.json"
    base_routes, _, _ = load_routes(pool_path, cargos, aircrafts, nodes, DEM,
        meta, full_charge, BASELINE, 400, 4000)
    new_routes, gen_audit = _make_deadline_routes(cargos, meta, aircrafts,
        nodes, full_charge, base_routes, args.route_proposal_cap)
    routes = base_routes + new_routes
    cover_audit, cover_solution = _exact_cover_probe(routes, cargos, meta)

    prior = json.loads((OUT / "alns_sortie_k400_seed20260929.json").read_text(encoding="utf-8"))
    route_by_id = {r.route_id: r for r in routes}
    initial_routes = [route_by_id[r["route_id"]] for r in prior["chosen"]]
    best, vns_audit = _vns(routes, initial_routes, cargos, meta, drones, batteries,
                           args.time_limit, args.seed, args.iterations)
    chosen = best.result["selected"]
    result = {"status": "feasible_heuristic", "selected": chosen,
              "metrics": best.result["metrics"], "delivery_times": best.result["delivery_times"]}
    validation = validate_solution(result, routes, cargos, meta, aircrafts,
        drones, batteries, nodes, full_charge)
    report = {
        "status": "feasible_heuristic", "method": "deadline_route_enrichment_tabu_VNS",
        "objective_order": ["sorties", "late", "makespan", "energy"],
        "metrics": best.result["metrics"], "chosen": chosen,
        "delivery_times": best.result["delivery_times"], "validation": validation,
        "route_generation": gen_audit, "candidate_route_count": len(routes),
        "exact_cover_probe": cover_audit, "vns": vns_audit, "seed": args.seed,
        "input_sha256": {str(p): sha(p) for p in paths+[DEM, BASELINE]},
        "base_pool_sha256": sha(pool_path),
        "scope": "Time-window targeted two-stop route enrichment plus tabu-guided VNS; heuristic result over the resulting finite pool.",
        "elapsed_s": time.monotonic()-started,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    target = OUT / "alns_deadline_vns.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                      encoding="utf-8")
    print(json.dumps({"status": report["status"], "metrics": report["metrics"],
        "validation": validation["status"], "new_routes": len(new_routes),
        "cover_probe": cover_audit, "vns": vns_audit,
        "elapsed_s": report["elapsed_s"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
