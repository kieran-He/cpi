"""Reproduce the two-box Q2 MILP sanity check and exact route-pattern enumeration.

This is a miniature implementation check, not a solver for the full 80-box case.
Requires scipy (tested with scipy.optimize.milp / HiGHS).
"""

from __future__ import annotations

import itertools
import time

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


# Preparation-start-to-return occupancy and preparation-start-to-delivery offsets.
ROUTES = (
    {
        "boxes": (0,), "duration": 5.0, "battery_duration": 7.0,
        "delivery": {0: 3.0}, "energy": 2.0,
    },
    {
        "boxes": (1,), "duration": 6.0, "battery_duration": 8.0,
        "delivery": {1: 4.0}, "energy": 2.0,
    },
    {
        "boxes": (0, 1),
        "duration": 7.0,
        "battery_duration": 9.0,
        "delivery": {0: 3.0, 1: 5.0},
        "energy": 8.0,
    },
)
DESIRED = (3.0, 3.0)
HARD_DEADLINE = (12.0, 12.0)
HORIZON = 30.0
BIG_M = 40.0

# Variable indices: x[0:3], s[3:6], d[6:8], late[8:10], T[10],
# and one precedence binary for each of the three route pairs at 11:14.
N_VARIABLES = 14
N_ROUTES = len(ROUTES)


def build_model():
    rows: list[dict[int, float]] = []
    lower: list[float] = []
    upper: list[float] = []

    def add(coefficients, lo=-np.inf, hi=np.inf):
        rows.append(coefficients)
        lower.append(lo)
        upper.append(hi)

    # Each of two boxes is covered exactly once.
    for box in range(2):
        add({p: 1.0 for p, route in enumerate(ROUTES) if box in route["boxes"]}, 1.0, 1.0)

    # Unselected routes have preparation start zero; selected starts are in [0, H].
    for p in range(N_ROUTES):
        add({3 + p: 1.0, p: -HORIZON}, hi=0.0)

    # Delivery-time equality, desired-time lateness, and hard delivery deadline.
    for box in range(2):
        equation = {6 + box: 1.0}
        for p, route in enumerate(ROUTES):
            if box in route["boxes"]:
                equation[p] = -route["delivery"][box]
                equation[3 + p] = -1.0
        add(equation, 0.0, 0.0)
        add({6 + box: 1.0, 8 + box: -1.0}, hi=DESIRED[box])
        add({6 + box: 1.0}, hi=HARD_DEADLINE[box])

    # Makespan is measured through return to base.
    for p, route in enumerate(ROUTES):
        add({10: 1.0, 3 + p: -1.0, p: -BIG_M}, lo=route["duration"] - BIG_M)

    # One compatible UAV and one compatible battery are available. Add the two
    # disjunctive rows for every route pair and each shared resource.
    pair_to_binary = {(0, 1): 11, (0, 2): 12, (1, 2): 13}
    for resource in ("UAV", "battery"):
        for p, q in itertools.combinations(range(N_ROUTES), 2):
            order = pair_to_binary[(p, q)]
            duration_key = "duration" if resource == "UAV" else "battery_duration"
            add(
                {3 + p: 1.0, 3 + q: -1.0, order: BIG_M, p: BIG_M, q: BIG_M},
                hi=3 * BIG_M - ROUTES[p][duration_key],
            )
            add(
                {3 + q: 1.0, 3 + p: -1.0, order: -BIG_M, p: BIG_M, q: BIG_M},
                hi=2 * BIG_M - ROUTES[q][duration_key],
            )

    matrix = lil_matrix((len(rows), N_VARIABLES), dtype=float)
    for row_index, coefficients in enumerate(rows):
        for column, value in coefficients.items():
            matrix[row_index, column] = value

    # A tiny deterministic tie-breaking term keeps the primary energy/sortie
    # preference while minimizing delivery, lateness, and makespan totals.
    objective = np.zeros(N_VARIABLES)
    for p, route in enumerate(ROUTES):
        objective[p] = route["energy"] + 0.01
    objective[6:11] = 0.001

    integrality = np.zeros(N_VARIABLES, dtype=int)
    integrality[:N_ROUTES] = 1
    integrality[11:] = 1
    variable_lower = np.zeros(N_VARIABLES)
    variable_upper = np.full(N_VARIABLES, np.inf)
    variable_upper[:N_ROUTES] = 1.0
    variable_upper[3:6] = HORIZON
    variable_upper[6:11] = HORIZON
    variable_upper[11:] = 1.0

    constraint = LinearConstraint(matrix.tocsr(), np.array(lower), np.array(upper))
    bounds = Bounds(variable_lower, variable_upper)
    return objective, integrality, bounds, constraint, len(rows)


def exact_enumeration():
    # The exact coverage equations admit only the combined route or both
    # singleton routes. Evaluate both orders for the singleton pair.
    candidates = []
    combined = ROUTES[2]
    combined_deliveries = (3.0, 5.0)
    combined_lateness = (0.0, 2.0)
    combined_makespan = 7.0
    combined_objective = (
        combined["energy"]
        + 0.01
        + 0.001 * (sum(combined_deliveries) + sum(combined_lateness) + combined_makespan)
    )
    candidates.append((combined_objective, "combined", combined_deliveries, combined_makespan))

    for order in ((0, 1), (1, 0)):
        starts = [0.0, 0.0]
        starts[order[1]] = ROUTES[order[0]]["battery_duration"]
        deliveries = [0.0, 0.0]
        for route_index in order:
            box = ROUTES[route_index]["boxes"][0]
            deliveries[box] = starts[route_index] + ROUTES[route_index]["delivery"][box]
        lateness = [max(0.0, deliveries[c] - DESIRED[c]) for c in range(2)]
        makespan = max(starts[p] + ROUTES[p]["duration"] for p in order)
        if any(deliveries[c] > HARD_DEADLINE[c] for c in range(2)):
            continue
        objective = (
            sum(ROUTES[p]["energy"] for p in order)
            + 0.01 * len(order)
            + 0.001 * (sum(deliveries) + sum(lateness) + makespan)
        )
        candidates.append((objective, f"singletons {order}", tuple(deliveries), makespan))
    return candidates


def main():
    objective, integrality, bounds, constraint, row_count = build_model()
    start = time.perf_counter()
    result = milp(
        objective,
        integrality=integrality,
        bounds=bounds,
        constraints=constraint,
        options={"mip_rel_gap": 0.0, "disp": False},
    )
    elapsed = time.perf_counter() - start
    enumeration = exact_enumeration()
    best_exact = min(enumeration, key=lambda item: item[0])

    if result.status != 0:
        raise RuntimeError(f"MILP did not prove optimality: status={result.status}: {result.message}")
    if abs(result.fun - best_exact[0]) > 1e-8:
        raise AssertionError(f"MILP {result.fun} != exact enumeration {best_exact[0]}")
    if any(result.x[6 + c] > HARD_DEADLINE[c] + 1e-8 for c in range(2)):
        raise AssertionError("MILP solution violates a hard deadline")

    selected = [p for p in range(N_ROUTES) if result.x[p] > 0.5]
    print(f"scipy={scipy.__version__}")
    print(f"candidate_routes={N_ROUTES} variables={N_VARIABLES} constraints={row_count}")
    print(f"status=optimal message={result.message}")
    print(f"selected_routes={selected}")
    print(f"starts={result.x[3:6].tolist()}")
    print(f"deliveries={result.x[6:8].tolist()} lateness={result.x[8:10].tolist()}")
    print(f"makespan={result.x[10]:.6f}")
    print(f"incumbent={result.fun:.6f} dual_bound={result.mip_dual_bound:.6f} gap={result.mip_gap:.6f}")
    print(f"elapsed_seconds={elapsed:.6f}")
    print("exact_enumeration:")
    for value, pattern, deliveries, makespan in enumeration:
        print(f"  {pattern}: deliveries={deliveries} makespan={makespan:.1f} objective={value:.6f}")
    print(f"best_exact={best_exact[1]} objective={best_exact[0]:.6f}")


if __name__ == "__main__":
    main()
