"""Adaptive large-neighborhood search for Q2 route selection and sortie scheduling.

The candidate pool keeps the Q1-derived physical checks. This module replaces the
full-size disjunctive MILP with feasible list scheduling inside an ALNS search.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from src.models.q2_scheduling import Route


@dataclass
class _State:
    routes: list[Route]
    result: dict


def _hard_slack(route: Route, metadata: dict) -> float:
    deadlines = [metadata[c]["hard_deadline"] - dict(route.delivery_offsets)[c]
                 for c in route.cargo_ids if metadata[c]["hard_deadline"] is not None]
    return min(deadlines, default=math.inf)


def _desired_slack(route: Route, metadata: dict) -> float:
    offsets = dict(route.delivery_offsets)
    return min((metadata[c]["desired"] - offsets[c] for c in route.cargo_ids), default=math.inf)


def _schedule_once(routes: list[Route], cargos: list, metadata: dict,
                   drones: dict, batteries: dict, policy: int, rng: random.Random,
                   deadline: float | None = None) -> dict | None:
    selected: list[dict] = []
    delivery_times: dict[str, float] = {}
    by_model: dict[str, list[Route]] = {}
    for route in routes:
        by_model.setdefault(route.model, []).append(route)

    for model, model_routes in by_model.items():
        drone_ready = {u: 0.0 for u in drones[model]}
        battery_ready = {b: 0.0 for b, _ in batteries[model]}

        def route_key(route: Route):
            hard = _hard_slack(route, metadata)
            desired = _desired_slack(route, metadata)
            priority = math.fsum(metadata[c]["priority"] for c in route.cargo_ids)
            if policy == 0:
                return (hard, desired, -priority, -len(route.cargo_ids), route.route_id)
            if policy == 1:
                return (hard, -len(route.cargo_ids), desired, -route.battery_duration, route.route_id)
            if policy == 2:
                return (hard, desired, -route.battery_duration, -priority, route.route_id)
            if policy == 3:
                return (hard, desired, rng.random(), route.route_id)
            return (hard, -route.battery_duration, desired, -priority, route.route_id)

        for route in sorted(model_routes, key=route_key):
            if deadline is not None and time.monotonic() >= deadline:
                return None
            options = []
            offsets = dict(route.delivery_offsets)
            for drone in drones[model]:
                for battery, _ in batteries[model]:
                    if deadline is not None and time.monotonic() >= deadline:
                        return None
                    start = max(drone_ready[drone], battery_ready[battery])
                    violated = [(c, start + offsets[c] - metadata[c]["hard_deadline"])
                                for c in route.cargo_ids
                                if metadata[c]["hard_deadline"] is not None
                                and start + offsets[c] > metadata[c]["hard_deadline"] + 1e-7]
                    if violated:
                        continue
                    weighted_late = math.fsum(
                        metadata[c]["priority"] * max(0.0, start + offsets[c] - metadata[c]["desired"])
                        for c in route.cargo_ids)
                    finish = start + route.prep_s + route.return_s
                    # Minimize immediate lateness and completion while balancing both resources.
                    balance = max(drone_ready[drone], battery_ready[battery])
                    options.append(((weighted_late, finish, balance, drone, battery),
                                    drone, battery, start))
            if not options:
                return None
            _, drone, battery, start = min(options, key=lambda x: x[0])
            return_time = start + route.prep_s + route.return_s
            drone_until = start + route.drone_duration
            battery_until = start + route.battery_duration
            drone_ready[drone] = drone_until
            battery_ready[battery] = battery_until
            selected.append({
                "route_id": route.route_id, "model": route.model,
                "cargo_ids": list(route.cargo_ids), "stops": [s.area for s in route.stops],
                "drone_id": drone, "battery_id": battery, "start_s": start,
                "takeoff_s": start + route.prep_s, "return_s": return_time,
                "energy_kwh": route.energy, "return_soc": route.return_soc,
                "drone_duration_s": route.drone_duration,
                "battery_duration_s": route.battery_duration,
            })
            for cid, offset in route.delivery_offsets:
                delivery_times[cid] = start + offset

    delivered = [c for row in selected for c in row["cargo_ids"]]
    if len(delivered) != len(set(delivered)):
        return None
    metrics = {
        "late": math.fsum(metadata[c]["priority"] * max(0.0, delivery_times[c] - metadata[c]["desired"])
                          for c in delivery_times),
        "makespan": max((r["return_s"] for r in selected), default=0.0),
        "energy": math.fsum(r.energy for r in routes),
        "sorties": len(routes),
    }
    return {"status": "feasible_heuristic", "solver_status": None,
            "message": "ALNS with hard-window-feasible list scheduling; no global optimality certificate",
            "dual_bound": None, "gap": None, "nvar": None, "nrow": None,
            "metrics": metrics, "selected": selected, "delivery_times": delivery_times}


def schedule(routes: list[Route], cargos: list, metadata: dict, drones: dict,
             batteries: dict, seed: int = 0, deadline: float | None = None) -> dict | None:
    """Try several deadline-aware list orders and keep the best feasible schedule."""
    best = None
    for policy in range(5):
        if deadline is not None and time.monotonic() >= deadline:
            break
        result = _schedule_once(routes, cargos, metadata, drones, batteries,
                                policy, random.Random(seed + policy), deadline)
        if result is not None and (best is None or tuple(result["metrics"][k] for k in
                ("late", "makespan", "energy", "sorties")) < tuple(best["metrics"][k] for k in
                ("late", "makespan", "energy", "sorties"))):
            best = result
    return best


def _candidate_options(cargo_id: str, remaining: set[str], by_cargo: dict[str, list[Route]]) -> list[Route]:
    return [r for r in by_cargo[cargo_id] if set(r.cargo_ids).issubset(remaining)]


def _repair(base: list[Route], all_cargos: list, metadata: dict, drones: dict,
            batteries: dict, by_cargo: dict[str, list[Route]], rng: random.Random,
            deadline: float, top_k: int = 8, randomized: bool = True) -> _State | None:
    chosen = list(base)
    covered = {c for r in chosen for c in r.cargo_ids}
    remaining = {c.cargo_id for c in all_cargos} - covered
    current = schedule(chosen, all_cargos, metadata, drones, batteries,
                       rng.randrange(1 << 30), deadline) if chosen else None
    if chosen and current is None:
        return None

    while remaining and time.monotonic() < deadline:
        option_map = {cid: _candidate_options(cid, remaining, by_cargo) for cid in remaining}
        # Cover the most constrained box first; break ties by hard deadline and priority.
        def cargo_key(cid):
            cands = option_map[cid]
            hard = [metadata[cid]["hard_deadline"] - dict(r.delivery_offsets)[cid]
                    for r in cands if metadata[cid]["hard_deadline"] is not None]
            slack = min(hard, default=metadata[cid]["desired"])
            return (len(cands), slack, -metadata[cid]["priority"], cid)
        cargo = min(remaining, key=cargo_key)
        options = option_map[cargo]
        if not options:
            return None
        # Route-level greedy insertion: serve more uncovered boxes with low energy and tight windows.
        def route_rank(r: Route):
            offsets = dict(r.delivery_offsets)
            hard_slack = min((metadata[c]["hard_deadline"] - offsets[c] for c in r.cargo_ids
                              if metadata[c]["hard_deadline"] is not None), default=math.inf)
            late0 = math.fsum(metadata[c]["priority"] * max(0., offsets[c] - metadata[c]["desired"])
                              for c in r.cargo_ids)
            gain = len(r.cargo_ids)
            jitter = rng.random()
            return (-gain, late0, hard_slack, r.energy / max(1, gain), r.battery_duration, jitter, r.route_id)
        options.sort(key=route_rank)
        # Randomized regret repair: sample within a bounded high-quality window so
        # repeated repairs do not collapse to the same deterministic cover.
        window = min(len(options), max(top_k, 32))
        try_order = options[:window]
        if randomized and len(try_order) > 1 and rng.random() < .70:
            first = rng.choice(try_order)
            try_order = [first] + [r for r in try_order if r.route_id != first.route_id]
        # Try alternatives until a deadline-feasible partial schedule is found.
        inserted = False
        for route in try_order:
            trial = chosen + [route]
            trial_schedule = schedule(trial, all_cargos, metadata, drones, batteries,
                                      rng.randrange(1 << 30), deadline)
            if time.monotonic() >= deadline:
                return None
            if trial_schedule is not None:
                chosen.append(route)
                remaining.difference_update(route.cargo_ids)
                current = trial_schedule
                inserted = True
                break
        if not inserted:
            return None
    if remaining or current is None:
        return None
    return _State(chosen, current)


def _initial(routes: list[Route], cargos: list, metadata: dict, drones: dict,
             batteries: dict, rng: random.Random, deadline: float,
             attempts: int = 20,
             objective_order: tuple[str, ...] = ("late", "makespan", "energy", "sorties")) -> _State | None:
    by_cargo = {c.cargo_id: [] for c in cargos}
    for route in routes:
        for cid in route.cargo_ids:
            by_cargo[cid].append(route)
    for candidates in by_cargo.values():
        candidates.sort(key=lambda r: (len(r.cargo_ids), r.energy, r.battery_duration, r.route_id))

    best = None
    for attempt in range(attempts):
        if time.monotonic() >= deadline:
            break
        state = _repair([], cargos, metadata, drones, batteries, by_cargo,
                        random.Random(rng.randrange(1 << 30)), deadline,
                        top_k=8 + attempt % 8, randomized=(attempt > 0))
        if state is not None and (best is None or _lex(state, objective_order) < _lex(best, objective_order)):
            best = state
    if best is not None:
        return best
    # Last-resort singleton covers with randomized model choice.
    singles = {c.cargo_id: [r for r in by_cargo[c.cargo_id] if len(r.cargo_ids) == 1]
               for c in cargos}
    if all(singles.values()) and time.monotonic() < deadline:
        for _ in range(100):
            selected = [rng.choice(singles[c.cargo_id]) for c in cargos]
            if time.monotonic() >= deadline:
                break
            result = schedule(selected, cargos, metadata, drones, batteries,
                              rng.randrange(1 << 30), deadline)
            if result is not None:
                return _State(selected, result)
    return None


def _dominates(a: dict, b: dict, tol: float = 1e-8) -> bool:
    keys = ("late", "makespan", "energy", "sorties")
    return (all(a[k] <= b[k] + tol for k in keys)
            and any(a[k] < b[k] - tol for k in keys))


def _lex(state: _State, objective_order: tuple[str, ...] = ("late", "makespan", "energy", "sorties")):
    m = state.result["metrics"]
    return tuple(m[k] for k in objective_order)


def _prune_archive(archive: list[_State], limit: int = 50) -> list[_State]:
    if len(archive) <= limit:
        return archive
    keys = ("late", "makespan", "energy", "sorties")
    keep = {min(range(len(archive)), key=lambda i: archive[i].result["metrics"][k])
            for k in keys}
    spans = {k: max(1e-12, max(s.result["metrics"][k] for s in archive)
                    - min(s.result["metrics"][k] for s in archive)) for k in keys}
    crowd = [0.0] * len(archive)
    for key in keys:
        order = sorted(range(len(archive)), key=lambda i: archive[i].result["metrics"][key])
        crowd[order[0]] = crowd[order[-1]] = math.inf
        lo, hi = archive[order[0]].result["metrics"][key], archive[order[-1]].result["metrics"][key]
        if hi > lo:
            for j in range(1, len(order)-1):
                before = archive[order[j-1]].result["metrics"][key]
                after = archive[order[j+1]].result["metrics"][key]
                crowd[order[j]] += (after-before)/spans[key]
    extra = sorted((i for i in range(len(archive)) if i not in keep),
                   key=lambda i: crowd[i], reverse=True)
    chosen = list(keep)
    chosen.extend(i for i in extra if len(chosen) < limit)
    return [archive[i] for i in chosen[:limit]]


def _destroy(state: _State, operator: str, rng: random.Random, count: int,
             metadata: dict) -> list[Route]:
    routes = list(state.routes)
    count = min(max(1, count), max(1, len(routes) - 1))
    if operator == "random":
        return rng.sample(routes, count)
    metrics = state.result["metrics"]
    delivery = state.result["delivery_times"]
    if operator == "worst":
        total_late = max(1.0, metrics["late"])
        total_energy = max(1e-9, metrics["energy"])
        total_battery = max(1.0, math.fsum(r.battery_duration for r in routes))
        total_boxes = max(1, sum(len(r.cargo_ids) for r in routes))
        def damage(r):
            late = math.fsum(metadata[c]["priority"] * max(0., delivery[c] - metadata[c]["desired"])
                             for c in r.cargo_ids)
            return (late / total_late + .2 * r.energy / total_energy
                    + .1 * r.battery_duration / total_battery
                    - .05 * len(r.cargo_ids) / total_boxes)
        return sorted(routes, key=damage, reverse=True)[:count]
    # Related removal: remove routes with similar service areas and deadline pressure.
    seed = rng.choice(routes)
    seed_areas = {s.area for s in seed.stops}
    seed_slack = _hard_slack(seed, metadata)
    def related(r):
        shared = len(seed_areas.intersection(s.area for s in r.stops))
        slack = _hard_slack(r, metadata)
        deadline_distance = abs(slack - seed_slack) if math.isfinite(slack) and math.isfinite(seed_slack) else 1e9
        model_penalty = 0 if r.model == seed.model else 2
        return (-shared + model_penalty + deadline_distance / 3600., r.route_id)
    return [seed] + [r for r in sorted((x for x in routes if x != seed), key=related)[:count - 1]]


def run_alns(routes: list[Route], cargos: list, metadata: dict, drones: dict,
             batteries: dict, *, time_limit_s: float = 900.0, iterations: int = 5000,
             seed: int = 20260924, objective: str = "lateness") -> dict:
    """Run deadline-bounded ALNS, retaining a Pareto archive and lexicographic recommendation."""
    if time_limit_s <= 0 or iterations <= 0:
        raise ValueError("time_limit_s and iterations must be positive")
    if objective not in {"lateness", "sorties"}:
        raise ValueError("objective must be 'lateness' or 'sorties'")
    objective_order = (("late", "makespan", "energy", "sorties") if objective == "lateness"
                       else ("sorties", "late", "makespan", "energy"))
    started = time.monotonic(); deadline = started + time_limit_s
    rng = random.Random(seed)
    by_cargo = {c.cargo_id: [] for c in cargos}
    for route in routes:
        for cid in route.cargo_ids:
            by_cargo[cid].append(route)
    uncovered = [cid for cid, options in by_cargo.items() if not options]
    if uncovered:
        raise ValueError(f"Candidate pool misses cargo: {uncovered}")

    current = _initial(routes, cargos, metadata, drones, batteries, rng,
                       min(deadline, started + time_limit_s * .1),
                       objective_order=objective_order)
    if current is None:
        return {"status": "no_feasible_initial_solution", "elapsed_s": time.monotonic() - started,
                "iterations": 0, "message": "ALNS could not construct a hard-window-feasible complete schedule"}
    best = current
    archive = [current]
    operators = ["random", "worst", "related"]
    weights = {name: 1.0 for name in operators}; reward_sum = {name: 0.0 for name in operators}
    uses = {name: 0 for name in operators}; temp = .12
    done = 0

    for iteration in range(iterations):
        if time.monotonic() >= deadline:
            break
        op = rng.choices(operators, weights=[weights[o] for o in operators], k=1)[0]
        uses[op] += 1
        removal_count = min(len(current.routes) - 1,
                            max(1, int(rng.uniform(.18, .42) * len(current.routes))))
        removed = _destroy(current, op, rng, removal_count, metadata)
        removed_ids = {r.route_id for r in removed}
        partial = [r for r in current.routes if r.route_id not in removed_ids]
        candidate = _repair(partial, cargos, metadata, drones, batteries, by_cargo,
                            rng, deadline, top_k=8)
        score = 0.0
        if candidate is not None:
            candidate_key = _lex(candidate, objective_order)
            current_key = _lex(current, objective_order)
            best_key = _lex(best, objective_order)
            if candidate_key < best_key:
                best = candidate; score = 5.0
            if not any(old.result["metrics"] == candidate.result["metrics"]
                       or _dominates(old.result["metrics"], candidate.result["metrics"])
                       for old in archive):
                archive = [old for old in archive if not _dominates(candidate.result["metrics"], old.result["metrics"])]
                archive.append(candidate)
                archive = _prune_archive(archive, 50)
                score = max(score, 2.0)
            if candidate_key <= current_key:
                current = candidate; score = max(score, 3.0)
            else:
                a, b = candidate.result["metrics"], current.result["metrics"]
                if objective == "sorties":
                    delta = (2.0 * max(0, a["sorties"] - b["sorties"])
                             + .15 * max(0., a["late"] - b["late"]) / max(1., b["late"])
                             + .08 * max(0., a["makespan"] - b["makespan"]) / max(1., b["makespan"])
                             + .04 * max(0., a["energy"] - b["energy"]) / max(1., b["energy"]))
                else:
                    keys = ("late", "makespan", "energy", "sorties")
                    scale = (max(1., a["late"], b["late"]), max(1., a["makespan"], b["makespan"]),
                             max(1., a["energy"], b["energy"]), max(1., a["sorties"], b["sorties"]))
                    delta = math.fsum(max(0., a[k] - b[k]) / s for k, s in zip(keys, scale))
                if rng.random() < math.exp(-delta / max(temp, .005)):
                    current = candidate; score = max(score, 1.0)
        reward_sum[op] += score
        done = iteration + 1
        temp = max(.005, temp * .999)
        if done % 50 == 0:
            for name in operators:
                if uses[name]: weights[name] = max(.15, .6 * weights[name] + .4 * reward_sum[name] / uses[name])
                reward_sum[name] = 0.0; uses[name] = 0

    recommended = min(archive, key=lambda s: _lex(s, objective_order))
    return {
        "status": "feasible_heuristic", "objective": objective,
        "objective_order": list(objective_order), "elapsed_s": time.monotonic() - started,
        "iterations": done, "seed": seed,
        "operator_weights_final": weights,
        "metrics": recommended.result["metrics"],
        "selected": recommended.result["selected"],
        "delivery_times": recommended.result["delivery_times"],
        "pareto_archive": [{"metrics": s.result["metrics"], "selected": s.result["selected"],
                            "delivery_times": s.result["delivery_times"]} for s in archive],
        "message": "Feasible ALNS schedule; metrics are heuristic and carry no global optimality certificate",
    }
