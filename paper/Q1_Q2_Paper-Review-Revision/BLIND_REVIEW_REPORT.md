# Blind review record: Q1–Q2 partial draft

**Scope:** Simulated Q1–Q2 manuscript only. This does not assess a complete contest submission. Three independent review rounds used the manuscript and traceable code/result files; a separate reviser edited only the review copy.

## Round 1

- **P1 — Q1 reserve sensitivity:** The original draft showed front cardinality and energy deltas but not resulting plan changes. **Addressed:** added feasible-scenario deltas for sorties, energy, operating time, and changed batch assignments, and summarized infeasible cases.
- **P1 — Q2 routes/resources:** The original draft lacked selected route and aircraft/drone/battery assignments. **Addressed:** added the 24-sortie manifest with stop sequence and cargo IDs by stop.
- **P2 — reproducibility and lower-bound evidence:** **Addressed:** added the VNS run settings and clarified that the route-cover lower bound and 28-cover deadline check apply only to the finite initial pool.
- **Final-template gaps:** retained as open integration items because this is an explicitly partial simulated draft.

## Round 2

- **P1 — schedule timing:** The manifest did not show start, takeoff, return, battery-ready, or per-cargo delivery times. **Addressed:** added a 24-row timing table and `q2_timing_supplement.csv` with one row per cargo box.
- **P2 — repeated stop:** Q2-003 visits S011 twice consecutively. **Not changed:** changing this would alter a selected route and require re-optimization. The exact route was preserved and flagged for team investigation.
- **Layout:** the dense route manifest was reflowed to occupy one full page; the timing table starts on the next page.

## Round 3

- **P0/P1:** none found in the revised Q1–Q2 partial scope.
- **P2 — team follow-up:** determine whether Q2-003’s repeated S011 visit reflects intended model behavior or should be merged and re-optimized before making an operational recommendation.
- **Whole-paper follow-up:** integrate Q3–Q4, write the final integrated abstract and conclusion, and complete official cover/template details before any submission use.

## Verification

- All 18 feasible Q1 sensitivity rows match `results/tables/q1_full_sensitivity.csv` at displayed precision; the other nine infeasible scenarios are described separately.
- The Q2 manifest has 24 routes and covers all 80 cargo IDs once. The timing supplement has 80 unique cargo rows; delivery times match `results/q2/deliveries.csv`, and route/resource timing matches `results/q2/alns_deadline_vns.json`.
- The revised PDF compiled with XeLaTeX to 18 A4 pages. The original `paper/Q1_Q2_Paper.pdf` was not modified.

Any adopted AI-assisted prose must be understood, verified, and expressed in the team’s own language under the 2026 Huawei Cup AI-tool rule. The review candidate is not an author-approved final paper.
