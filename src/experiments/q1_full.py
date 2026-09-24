"""Full Q1 experiment CLI. Run from the repository root with uv.

Example: uv run --locked python -m src.experiments.q1_full --scenario baseline
Limits: --time-limit 120 --max-solves 10; ``--time-limit 0`` disables the
per-MILP time limit. Resume with the same limits and --resume.
No 27-scenario run is started by importing this module. A checkpoint only proves
work whose individual MILP status is `optimal`; timeout incumbents stay tentative.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import scipy

from src.data.q1_inputs import load_q1_inputs
from src.models.q1_full import (OBJECTIVES, Batch, Scenario, all_scenarios, enumerate_area,
                                load_full_inputs, make_geometries, max_safe_payload, nondominated,
                                representative, solve_partition, validate_selected)

ROOT = Path(__file__).resolve().parents[2]
DEM = ROOT / "questions" / "Data" / "Zhenlong Township Geospatial Data" / "Geospatial Data for Zhenlong Township and Surrounding Areas" / "Digital Elevation Model (DEM) Data" / "30 m DEM for Zhenlong Township and Surrounding Areas.tif"
ALGORITHM_VERSION = "q1-exact-epsilon-certificate-v2"
# New proof semantics must never read or rewrite the old fingerprint's directory.
CHECKPOINT_DIR = ROOT / "results" / "checkpoints" / "q1_full_cert_v2"
P1_CHECKPOINT_DIR = ROOT / "results" / "checkpoints" / "q1_full_p1_cert_v2"
P1_EVIDENCE_DIR = ROOT / "results" / "logs" / "q1_full_p1_gate_cert_v2"
TABLE_DIR = ROOT / "results" / "tables"


def emit(event: str, **values: object) -> None:
    print(json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def atomic_json(path: Path, payload: dict) -> None:
    """Checksummed envelope, fsync then replace; no partially-written checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"payload_sha256": hashlib.sha256(canonical(payload)).hexdigest(), "payload": payload}
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with tmp.open("wb") as stream:
            stream.write(canonical(envelope))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _time_limit_only_fingerprint_change(old: dict, new: dict) -> bool:
    """Allow the controlled migration from bounded to unlimited MILP runs."""
    if old.get("algorithm") != new.get("algorithm"):
        return False
    if old.get("python") != new.get("python") or old.get("scipy") != new.get("scipy"):
        return False
    old_files, new_files = old.get("files"), new.get("files")
    if not isinstance(old_files, dict) or not isinstance(new_files, dict) or set(old_files) != set(new_files):
        return False
    changed = {name for name in old_files if old_files[name] != new_files[name]}
    return changed and changed <= {
        "src\\models\\q1_full.py",
        "src\\experiments\\q1_full.py",
    }


def read_checkpoint(path: Path, fingerprint: dict, *, allow_time_limit_migration: bool = False) -> dict:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    if hashlib.sha256(canonical(payload)).hexdigest() != envelope["payload_sha256"]:
        raise ValueError(f"Checkpoint checksum mismatch: {path}")
    if payload["fingerprint"] != fingerprint:
        if not allow_time_limit_migration or not _time_limit_only_fingerprint_change(payload["fingerprint"], fingerprint):
            raise ValueError(f"Checkpoint inputs/code/environment changed: {path}")
        payload["fingerprint"] = fingerprint
        atomic_json(path, payload)
    return payload


def make_fingerprint(inputs: list[Path]) -> dict:
    protected = [DEM, ROOT / "analysis" / "problems" / "Q1.md", ROOT / "uv.lock",
                 ROOT / "src" / "models" / "q1_full.py", ROOT / "src" / "experiments" / "q1_full.py",
                 ROOT / "src" / "data" / "q1_inputs.py", ROOT / "src" / "models" / "q1_physics.py"]
    return {"algorithm": ALGORITHM_VERSION,
            "files": {str(p.relative_to(ROOT)): file_hash(p) for p in inputs + protected},
            "python": sys.version, "scipy": scipy.__version__}


def write_csv_atomic(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _endpoint_record(groups, area_batches, target: str, area: str, state: dict,
                     save, budget: list[int], limit: float) -> dict | None:
    """Lexicographic scalar endpoint: primary, then the other two objectives."""
    order = [target, *[j for j in OBJECTIVES if j != target]]
    limits: dict[str, float] = {}
    record = None
    for step, objective in enumerate(order):
        key = f"{area}:{target}:{step}"
        if key in state["endpoint_steps"]:
            record = state["endpoint_steps"][key]
        else:
            if budget[0] <= 0:
                return None
            record = solve_partition(groups[area], area_batches[area], objective, limits, limit)
            budget[0] -= 1
            state["endpoint_steps"][key] = record
            save()
            emit("endpoint_step", area=area, target=target, step=step, status=record["status"],
                 bound=record.get("dual_bound"), gap=record.get("gap"))
        if record["status"] != "optimal":
            return record
        # A floating epsilon on the prior optimum is needed for numerics; N remains integer.
        value = record["metrics"][objective]
        limits[objective] = value if objective == "N" else value + 1e-8 * max(1., abs(value))
    return record


def _levels(endpoints: list[dict]) -> dict[str, list[float]]:
    out = {}
    for j in OBJECTIVES:
        vals = [item["metrics"][j] for item in endpoints]
        lo, hi = min(vals), max(vals)
        out[j] = [lo + (hi - lo) * k / 10. for k in range(11)]
    return out


def _jobs(levels: dict[str, list[float]], stage: str, initial: dict[str, list[float]] | None = None) -> list[dict]:
    jobs = []
    for primary in OBJECTIVES:
        secondaries = [j for j in OBJECTIVES if j != primary]
        a, b = secondaries
        for i, j in product(range(len(levels[a])), range(len(levels[b]))):
            va, vb = levels[a][i], levels[b][j]
            if initial is not None and any(abs(va - x) <= 1e-10 for x in initial[a]) and any(abs(vb - x) <= 1e-10 for x in initial[b]):
                continue
            jobs.append({"id": f"{stage}:{primary}:{i:02d}:{j:02d}", "stage": stage,
                         "primary": primary, "limits": {a: va, b: vb}})
    # Any coordinatewise-wider job precedes a tighter job for the same primary.
    # Incomparable pairs may appear in either order; containment is checked anew
    # before every certificate reuse.
    def widest_first(job: dict) -> tuple:
        secondary = [j for j in OBJECTIVES if j != job["primary"]]
        return (OBJECTIVES.index(job["primary"]),
                -job["limits"][secondary[0]], -job["limits"][secondary[1]], job["id"])
    jobs.sort(key=widest_first)
    return jobs


def _limits_contain(wide: dict[str, float], tight: dict[str, float]) -> bool:
    """True only when the wide feasible set contains the tight one exactly."""
    return (set(wide).issubset(tight) and
            all(math.isfinite(value) and key in OBJECTIVES and value >= tight[key]
                for key, value in wide.items()) and
            all(math.isfinite(value) and key in OBJECTIVES for key, value in tight.items()))


def _certificate_sources(primary: str, state: dict) -> list[dict]:
    sources = []
    endpoint = state["endpoints"].get(primary)
    if endpoint is not None and endpoint["status"] == "optimal":
        lower = endpoint.get("primary_dual_bound")
        value = endpoint["metrics"][primary]
        if lower is not None and math.isclose(lower, value, abs_tol=1e-7, rel_tol=1e-7):
            sources.append({"id": f"endpoint:{primary}", "root": f"endpoint:{primary}",
                            "primary": primary, "limits": {}, "status": "optimal",
                            "selected": endpoint["selected"], "metrics": endpoint["metrics"],
                            "dual_bound": lower, "gap": 0.0, "solver_status": 0})
    plan = {job["id"]: job for job in state["epsilon_plan"]}
    for identifier, result in state["epsilon_results"].items():
        job = plan.get(identifier)
        if job is None or job["primary"] != primary:
            continue
        status = result["status"]
        if status not in ("optimal", "infeasible") or result.get("solver_status") != (0 if status == "optimal" else 2):
            continue
        if status == "optimal":
            m, bound, gap = result.get("metrics"), result.get("dual_bound"), result.get("gap")
            if m is None or bound is None or gap is None or not math.isclose(gap, 0., abs_tol=1e-7):
                continue
            if not math.isclose(m[primary], bound, abs_tol=1e-7, rel_tol=1e-7):
                continue
        sources.append({"id": identifier, "root": result.get("root_proof_source", identifier),
                        "primary": primary, "limits": job["limits"], "status": status,
                        "selected": result.get("selected", []), "metrics": result.get("metrics"),
                        "dual_bound": result.get("dual_bound"), "gap": result.get("gap"),
                        "solver_status": result["solver_status"]})
    return sources


def _reuse_certificate(job: dict, state: dict) -> dict | None:
    """Reuse only an already proved *same-primary* superset result.

    Infeasible(wide) implies infeasible(tight). Optimal(wide) proves
    optimal(tight) only when the wide optimum's incumbent satisfies tight.
    Timeout/unknown results are never sources. Raw MILP bounds/gaps propagate
    unchanged, with both immediate and root proof provenance recorded.
    """
    primary, tight = job["primary"], job["limits"]
    if primary not in OBJECTIVES or primary in tight:
        raise ValueError("Malformed epsilon job")
    optimal = []
    infeasible = []
    for source in _certificate_sources(primary, state):
        if not _limits_contain(source["limits"], tight):
            continue
        if source["status"] == "infeasible":
            infeasible.append(source)
        elif all(source["metrics"][name] <= value for name, value in tight.items()):
            optimal.append(source)
    if optimal and infeasible:
        raise ValueError(f"Conflicting optimal/infeasible proof certificates for {job['id']}")
    source = (optimal or infeasible or [None])[0]
    if source is None:
        return None
    result = {"status": source["status"], "solver_status": source["solver_status"],
              "message": f"Certified by {source['id']} through epsilon containment",
              "selected": list(source["selected"]), "metrics": source["metrics"],
              "dual_bound": source["dual_bound"], "gap": source["gap"], "node_count": 0,
              "primary": primary, "limits": tight, "reused": True,
              "proof_source": source["id"], "root_proof_source": source["root"],
              "certificate_limits": source["limits"]}
    return result


def _refine_levels(initial: dict[str, list[float]], front: list[dict], endpoint_ids: set[tuple[str, ...]]) -> dict[str, list[float]]:
    """One midpoint pass for intervals containing a newly sampled ND solution."""
    levels = {}
    novel = [x for x in front if tuple(sorted(x["selected"])) not in endpoint_ids]
    for objective in OBJECTIVES:
        old = initial[objective]
        midpoints = []
        for left, right in zip(old, old[1:]):
            if right - left <= 1e-10:
                continue
            if any(left + 1e-9 < x["metrics"][objective] < right - 1e-9 for x in novel):
                midpoints.append((left + right) / 2.)
        levels[objective] = sorted(set(old + midpoints))
    return levels


def _finalize(state: dict, all_batches: dict[str, Batch], cargoes: list,
              aircrafts, geoms, scenario: Scenario) -> None:
    endpoints = list(state["endpoints"].values())
    proven = endpoints + [v for v in state["epsilon_results"].values() if v["status"] == "optimal"]
    front = nondominated(proven)
    ideals = {j: state["endpoints"][j]["metrics"][j] for j in OBJECTIVES}
    chosen, ceilings = representative(front, ideals)
    for x in front:
        validate_selected(x["selected"], all_batches, cargoes, aircrafts, geoms, scenario)
    incomplete = [key for key, v in state["epsilon_results"].items() if v["status"] not in ("optimal", "infeasible")]
    state["pareto_sample"] = [{"selected": x["selected"], "metrics": x["metrics"]} for x in front]
    state["ideal"] = ideals
    state["sample_upper"] = ceilings
    state["representative"] = chosen["selected"] if not incomplete else None
    state["tentative_representative"] = chosen["selected"] if incomplete else None
    state["status"] = "complete_sampled" if not incomplete else "incomplete_epsilon"


def _publish_baseline(state: dict, batch_map: dict[str, Batch], scenario: Scenario) -> None:
    if scenario != Scenario(.2, 1., 1.) or state["status"] != "complete_sampled":
        return
    rows = []
    for i, ident in enumerate(sorted(state["representative"]), 1):
        b = batch_map[ident]
        rows.append({"Sortie ID": f"Q1-{i:03d}", "Service Area ID": b.area_id, "Model ID": b.model_id,
                     "Cargo Box ID List": ", ".join(b.cargo_ids), "Total Mass (kg)": b.mass_kg,
                     "Total Volume (m³)": b.volume_m3, "Round-Trip Time (s)": b.round_trip_time_s,
                     "Sortie Energy (kWh)": b.energy_kwh, "Return SOC (%)": 100 * b.return_soc})
    write_csv_atomic(TABLE_DIR / "q1_full_baseline_batches.csv", list(rows[0]), rows)
    capacity_rows = [{"Scenario": scenario.key, **record} for record in state["capacity"]]
    write_csv_atomic(TABLE_DIR / "q1_full_baseline_capacity.csv", list(capacity_rows[0]), capacity_rows)


def run_scenario(scenario: Scenario, groups, aircrafts, geoms, fingerprint: dict,
                 *, time_limit_s: float, max_solves: int, resume: bool,
                 checkpoint_dir: Path = CHECKPOINT_DIR, publish: bool = True) -> dict:
    path = checkpoint_dir / f"{scenario.key}.json"
    if path.exists() and not resume:
        raise FileExistsError(f"Checkpoint exists; use --resume: {path}")
    state = read_checkpoint(
        path,
        fingerprint,
        allow_time_limit_migration=resume and time_limit_s in (None, 0),
    ) if path.exists() else {
        "schema": 2, "scenario": {"rho": scenario.rho, "alpha": scenario.alpha, "beta": scenario.beta},
        "fingerprint": fingerprint, "status": "started", "capacity": [], "candidate_counts": {},
        "endpoint_steps": {}, "endpoints": {}, "epsilon_plan": [], "epsilon_results": {}}
    if state["scenario"] != {"rho": scenario.rho, "alpha": scenario.alpha, "beta": scenario.beta}:
        raise ValueError("Scenario mismatch in checkpoint")
    def save() -> None:
        state["updated_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_json(path, state)
    if state["status"] in ("complete_sampled", "infeasible"):
        emit("scenario_cached", scenario=scenario.key, status=state["status"])
        return state
    if resume and state["status"] == "endpoint_unproven":
        failed = state["failed_endpoint"]
        for step in range(3):
            key = f"{failed['area']}:{failed['target']}:{step}"
            if key in state["endpoint_steps"] and state["endpoint_steps"][key]["status"] != "optimal":
                state.setdefault("retry_history", []).append({"step": key, "result": state["endpoint_steps"].pop(key)})
                break
    if resume and state["status"] == "incomplete_epsilon":
        for key in list(state["epsilon_results"]):
            if state["epsilon_results"][key]["status"] not in ("optimal", "infeasible"):
                state.setdefault("retry_history", []).append({"step": key, "result": state["epsilon_results"].pop(key)})

    # Recreate candidates deterministically on resume. Hashes forbid stale reuse.
    area_batches = {}
    capacity = []
    counts = {}
    for area in sorted(groups):
        for model, aircraft in sorted(aircrafts.items()):
            status, payload = max_safe_payload(aircraft, geoms[area], scenario)
            capacity.append({"Service Area ID": area, "Model ID": model,
                             "Status": status, "Maximum Safe Payload (kg)": payload})
        area_batches[area], counts[area] = enumerate_area(area, groups[area], aircrafts, geoms[area], scenario)
        emit("enumerated", scenario=scenario.key, area=area, **counts[area])
    state["capacity"], state["candidate_counts"] = capacity, counts
    cargoes = [c for area in sorted(groups) for c in groups[area]]
    batches = [b for area in sorted(groups) for b in area_batches[area]]
    batch_map = {b.batch_id: b for b in batches}
    if len(batch_map) != len(batches):
        raise AssertionError("Duplicate candidate ID")
    candidate_digest = hashlib.sha256(canonical([b.batch_id for b in batches])).hexdigest()
    if "candidate_digest" in state and state["candidate_digest"] != candidate_digest:
        raise ValueError("Regenerated candidate IDs differ from checkpoint")
    state["candidate_digest"] = candidate_digest
    uncovered = sorted({c.cargo_id for c in cargoes} - {i for b in batches for i in b.cargo_ids})
    if uncovered:
        state["status"] = "infeasible"; state["uncovered_cargo_ids"] = uncovered
        save(); emit("scenario_infeasible", scenario=scenario.key, uncovered=uncovered)
        return state
    save()
    budget = [max_solves]

    for target in OBJECTIVES:
        if target in state["endpoints"]:
            continue
        chosen_ids = []
        area_status = {}
        for area in sorted(groups):
            record = _endpoint_record(groups, area_batches, target, area, state, save, budget, time_limit_s)
            if record is None:
                state["status"] = "paused_limit"; save(); return state
            area_status[area] = {k: record.get(k) for k in ("status", "dual_bound", "gap", "message")}
            if record["status"] != "optimal":
                state["status"] = "endpoint_unproven"
                state["failed_endpoint"] = {"area": area, "target": target, **area_status[area]}
                save(); return state
            chosen_ids.extend(record["selected"])
        exact_metrics = validate_selected(chosen_ids, batch_map, cargoes, aircrafts, geoms, scenario)
        primary_dual_bound = math.fsum(state["endpoint_steps"][f"{area}:{target}:0"]["dual_bound"] for area in sorted(groups))
        state["endpoints"][target] = {"status": "optimal", "selected": sorted(chosen_ids),
                                      "metrics": exact_metrics, "primary_dual_bound": primary_dual_bound,
                                      "area_status": area_status}
        save(); emit("endpoint_complete", scenario=scenario.key, target=target, metrics=exact_metrics)

    if not state["epsilon_plan"]:
        initial = _levels(list(state["endpoints"].values()))
        state["epsilon_initial_levels"] = initial
        state["epsilon_plan"] = _jobs(initial, "base")
        state["epsilon_stage"] = "base"
        save()
    while True:
        pending = [job for job in state["epsilon_plan"] if job["id"] not in state["epsilon_results"]]
        for job in pending:
            result = _reuse_certificate(job, state)
            if result is None:
                if budget[0] <= 0:
                    state["status"] = "paused_limit"; save(); return state
                result = solve_partition(cargoes, batches, job["primary"], job["limits"], time_limit_s)
                budget[0] -= 1
                result.update({"reused": False, "proof_source": job["id"],
                               "root_proof_source": job["id"], "certificate_limits": job["limits"]})
            if result["metrics"] is not None:
                validate_selected(result["selected"], batch_map, cargoes, aircrafts, geoms, scenario)
            state["epsilon_results"][job["id"]] = result
            save()
            if not result["reused"] or result["status"] not in ("optimal", "infeasible"):
                emit("epsilon_solved", scenario=scenario.key, job=job["id"], status=result["status"],
                     reused=result["reused"], proof_source=result["proof_source"],
                     objective=result["metrics"], bound=result.get("dual_bound"), gap=result.get("gap"))
            if result["status"] not in ("optimal", "infeasible"):
                # Stop at the first unproven MILP. The incumbent and original
                # dual bound remain checkpointed for review; --resume retries
                # exactly this job after a larger per-MILP time limit.
                state["status"] = "incomplete_epsilon"
                state["failed_epsilon"] = {"job": job["id"], "status": result["status"],
                                           "bound": result.get("dual_bound"), "gap": result.get("gap")}
                save()
                emit("epsilon_paused_unproven", scenario=scenario.key, job=job["id"],
                     status=result["status"], bound=result.get("dual_bound"), gap=result.get("gap"))
                return state
        if state["epsilon_stage"] == "base":
            proven = list(state["endpoints"].values()) + list(state["epsilon_results"].values())
            front = nondominated(proven)
            endpoint_ids = {tuple(sorted(x["selected"])) for x in state["endpoints"].values()}
            refined = _refine_levels(state["epsilon_initial_levels"], front, endpoint_ids)
            state["epsilon_refined_levels"] = refined
            state["epsilon_plan"].extend(_jobs(refined, "refine", state["epsilon_initial_levels"]))
            state["epsilon_stage"] = "refine"
            save(); emit("epsilon_refinement_planned", scenario=scenario.key,
                         extra_jobs=len(state["epsilon_plan"]) - len(state["epsilon_results"]))
            continue
        break
    _finalize(state, batch_map, cargoes, aircrafts, geoms, scenario)
    save()
    if publish:
        _publish_baseline(state, batch_map, scenario)
    emit("scenario_complete", scenario=scenario.key, status=state["status"],
         sampled_nondominated=len(state["pareto_sample"]))
    return state


def self_check() -> None:
    """New-code P1 gate: real three-box slice through all full-run stages.

    Baseline plus a diagnostic scenario exercise rho, alpha and beta plumbing.
    The 11x11 epsilon grid and one refinement pass are executed in dedicated
    P1 checkpoints. No official 80-box scenario checkpoint or table is touched.
    """
    p1 = load_q1_inputs(ROOT)
    full_origin, full_areas, full_groups, full_aircrafts, input_paths = load_full_inputs(ROOT)
    if sum(map(len, full_groups.values())) != 80 or len(full_areas) != 15:
        raise AssertionError("Full input loader did not read 15 areas and 80 boxes")
    origin, dest = p1["nodes"]["O01"], p1["nodes"]["S001"]
    if full_origin != origin or full_areas["S001"] != dest or full_aircrafts != p1["aircraft"]:
        raise AssertionError("Full loader differs from P1 inputs")
    geometries = make_geometries(origin, {"S001": dest}, DEM)
    cargoes = [c for c in full_groups["S001"] if c.cargo_id in {x.cargo_id for x in p1["cargos"]}]
    if len(cargoes) != 3:
        raise AssertionError("P1 cargo IDs not found in full loader")
    fingerprint = make_fingerprint(input_paths)
    fingerprint_id = hashlib.sha256(canonical(fingerprint)).hexdigest()[:12]
    p1_checkpoint_dir = P1_CHECKPOINT_DIR / fingerprint_id
    p1_evidence = P1_EVIDENCE_DIR / f"{fingerprint_id}.json"
    reports = {}
    for scenario in (Scenario(.2, 1., 1.), Scenario(.3, .9, 1.1)):
        state = run_scenario(scenario, {"S001": cargoes}, full_aircrafts, geometries, fingerprint,
                             time_limit_s=30., max_solves=2000, resume=True,
                             checkpoint_dir=p1_checkpoint_dir, publish=False)
        if state["status"] != "complete_sampled" or len(state["capacity"]) != 3:
            raise AssertionError(f"P1 full-code gate incomplete: {scenario.key}: {state['status']}")
        if len(state["epsilon_results"]) < 363:
            raise AssertionError("11x11 epsilon calls per main objective not completed")
        candidates, counts = enumerate_area("S001", cargoes, full_aircrafts, geometries["S001"], scenario)
        if scenario == Scenario(.2, 1., 1.) and counts["physical"] != 21:
            raise AssertionError(f"P1 candidate comparison changed: {counts}")
        candidate_map = {c.batch_id: c for c in candidates}
        final_metrics = validate_selected(state["representative"], candidate_map, cargoes,
                                          full_aircrafts, geometries, scenario)
        for target in OBJECTIVES:
            if state["endpoints"][target]["status"] != "optimal":
                raise AssertionError(f"Endpoint unproven: {target}")
        reports[scenario.key] = {"status": state["status"], "capacity": state["capacity"],
                                 "candidate_counts": state["candidate_counts"],
                                 "endpoints": {k: v["metrics"] for k, v in state["endpoints"].items()},
                                 "epsilon_solved": len(state["epsilon_results"]),
                                 "epsilon_reused": sum(bool(v.get("reused")) for v in state["epsilon_results"].values()),
                                 "sampled_nondominated": len(state["pareto_sample"]),
                                 "representative_ids": state["representative"],
                                 "representative_metrics": final_metrics,
                                 "checkpoint": str((p1_checkpoint_dir / f"{scenario.key}.json").relative_to(ROOT))}
    evidence = {"status": "AUTHOR_CHECK_ONLY_INDEPENDENT_P1_PENDING",
                "scope": "S001 first three actual boxes; baseline and rho=.30, alpha=.9, beta=1.1",
                "input_fingerprint": fingerprint, "scenarios": reports,
                "command": "uv run --locked python -m src.experiments.q1_full --p1-check",
                "formal_80_box_results_created": False}
    atomic_json(p1_evidence, evidence)
    emit("self_check_pass", evidence=str(p1_evidence.relative_to(ROOT)), scenarios=list(reports))


def main() -> None:
    parser = argparse.ArgumentParser(description="Q1 full exact batching and sampled epsilon experiment")
    parser.add_argument("--scenario", default="all", help="all, baseline, or r0.20_a1.0_b1.0 etc")
    parser.add_argument("--time-limit", type=float, default=120., help="seconds per MILP call; 0 means unlimited")
    parser.add_argument("--max-solves", type=int, default=100000, help="MILP calls per scenario this invocation")
    parser.add_argument("--max-scenarios", type=int, default=27, help="scenario count this invocation")
    parser.add_argument("--resume", action="store_true", help="resume only matching checksummed checkpoints")
    parser.add_argument("--p1-check", "--self-check", action="store_true", dest="self_check",
                        help="run two real 3-box scenarios through all full-run stages, P1 evidence only")
    args = parser.parse_args()
    if args.self_check:
        self_check(); return
    if args.time_limit < 0 or args.max_solves < 1 or args.max_scenarios < 1:
        parser.error("time-limit must be non-negative; other limits must be positive")
    scenarios = all_scenarios()
    if args.scenario == "baseline":
        scenarios = [Scenario(.2, 1., 1.)]
    elif args.scenario != "all":
        scenarios = [s for s in scenarios if s.key == args.scenario]
        if not scenarios:
            parser.error("Unknown scenario key")
    origin, areas, groups, aircrafts, paths = load_full_inputs(ROOT)
    fingerprint = make_fingerprint(paths)
    emit("input_loaded", cargoes=sum(map(len, groups.values())), areas=len(areas), scenario_count=len(scenarios))
    geoms = make_geometries(origin, areas, DEM)
    for scenario in scenarios[:args.max_scenarios]:
        result = run_scenario(scenario, groups, aircrafts, geoms, fingerprint, time_limit_s=args.time_limit,
                              max_solves=args.max_solves, resume=args.resume)
        if result["status"] in ("incomplete_epsilon", "endpoint_unproven", "paused_limit"):
            emit("run_paused", scenario=scenario.key, status=result["status"],
                 reason="increase the MILP limit or resume after review")
            raise SystemExit(2)


if __name__ == "__main__":
    main()
