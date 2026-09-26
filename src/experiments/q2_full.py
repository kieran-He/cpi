"""Reproducible Q2 candidate-route and resource scheduling experiment."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
from copy import copy
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from src.models.q1_full import load_full_inputs
from src.models.q2_scheduling import Route, Stop, build_route, make_pool, solve

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/"questions"/"Data"/"Basic Data for Drone-Based Emergency Supply Transport"
DEM=ROOT/"questions"/"Data"/"Zhenlong Township Geospatial Data"/"Geospatial Data for Zhenlong Township and Surrounding Areas"/"Digital Elevation Model (DEM) Data"/"30 m DEM for Zhenlong Township and Surrounding Areas.tif"
BASELINE=ROOT/"results"/"tables"/"q1_full_baseline_batches.csv"
OUT=ROOT/"results"/"q2"

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def inputs():
    origin,areas,groups,aircrafts,paths=load_full_inputs(ROOT)
    wb=load_workbook(DATA/"Supply Demand and Delivery Deadlines.xlsx",read_only=True,data_only=True)
    ws=wb["Cargo Box List"]; rows=ws.iter_rows(values_only=True); header=next(rows); h={str(v).strip():i for i,v in enumerate(header)}
    cargo_order=[]; meta={}
    for row in rows:
        if row[h["Cargo Box ID"]] is None: continue
        cid=str(row[h["Cargo Box ID"]]); cargo_order.append(cid)
        initial=str(row[h["Required in Initial Delivery"]]).strip().lower() in ("yes","y","true","1")
        supply=str(row[h["Supply Type"]]).strip().lower()
        desired=float(row[h["Desired Delivery Time (s)"]]); initial_deadline=row[h["Initial-Delivery Deadline (s)"]]
        hard=[]
        if supply=="medical": hard.append(desired)
        if initial:
            if initial_deadline is None: raise ValueError(f"Missing initial deadline: {cid}")
            hard.append(float(initial_deadline))
        meta[cid]={"desired":desired,"priority":float(row[h["Emergency Priority Factor"]]),
                   "hard_deadline":min(hard) if hard else None,"initial":initial,"supply_type":supply}
    wb.close()
    cargo_map={c.cargo_id:c for items in groups.values() for c in items}
    cargos=[cargo_map[cid] for cid in cargo_order]
    wb=load_workbook(DATA/"Transport Drone Data.xlsx",read_only=True,data_only=True); ws=wb["Data"]
    drones={g:[] for g in aircrafts}; batteries={}; full_charge={}
    for row in ws.iter_rows(values_only=True):
        row=tuple(row)
        if "Drone ID" in row and "Model ID" in row:
            cols={"id":row.index("Drone ID"),"model":row.index("Model ID")}; section="drones"; continue
        if "Total Number of Shared Battery Packs" in row and "Equivalent Full Charging Time (s)" in row:
            cols={"model":row.index("Model ID"),"count":row.index("Total Number of Shared Battery Packs"),"charge":row.index("Equivalent Full Charging Time (s)")}; section="batteries"; continue
        if "Model ID" in row and "Maximum Cargo Mass (kg)" in row: section=None; continue
        if not row or not any(x is not None for x in row) or "cols" not in locals() or section is None: continue
        if section=="drones" and len(row)>max(cols.values()) and row[cols["id"]] is not None and row[cols["model"]] in aircrafts:
            model=str(row[cols["model"]]); drones[model].append(str(row[cols["id"]]))
        elif section=="batteries" and len(row)>max(cols.values()) and row[cols["model"]] in aircrafts:
            model=str(row[cols["model"]]); n=int(row[cols["count"]]); full_charge[model]=float(row[cols["charge"]])
            batteries[model]=[(f"{model}-BAT-{k:02d}",full_charge[model]) for k in range(1,n+1)]
    wb.close()
    nodes={"O01":origin,**areas}
    return cargos,meta,nodes,aircrafts,drones,batteries,full_charge,paths

def lex_solve(routes,cargos,meta,aircrafts,drones,batteries,primary,limits=None):
    hierarchy=[primary]+[m for m in ("late","makespan","energy","sorties") if m!=primary]
    bounds=dict(limits or {}); last=None; proof=[]
    for objective in hierarchy:
        last=solve(routes,cargos,meta,aircrafts,drones,batteries,objective,bounds)
        proof.append({"objective":objective,"status":last["status"],"solver_status":last["solver_status"],
                      "dual_bound":last.get("dual_bound"),"gap":last.get("gap"),"nvar":last["nvar"],"nrow":last["nrow"]})
        if last["status"]!="optimal": break
        value=last["metrics"][objective]
        bounds[objective]=value if objective=="sorties" else value+1e-7*max(1.,abs(value))
    if last is not None: last["lex_proof"]=proof; last["epsilon_bounds"]=bounds
    return last

def write_json(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp"); tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8"); tmp.replace(path)

def validate_solution(result,routes,cargos,meta,aircrafts,drones,batteries,
                      nodes=None, full_charge=None):
    chosen=result.get("selected",[]); ids=[cid for r in chosen for cid in r["cargo_ids"]]
    checks={"cargo_unique_and_complete":len(ids)==len(cargos) and set(ids)=={c.cargo_id for c in cargos} and len(ids)==len(set(ids)),
            "compatible_resources":True,"hard_deadlines":True,"route_soc_and_energy":True,
            "route_physics_recomputed":nodes is not None and full_charge is not None,
            "delivery_offsets_consistent":True,
            "drone_intervals_nonoverlap":True,"battery_charge_intervals_nonoverlap":True}
    by_id={r.route_id:r for r in routes}; cargo_map={c.cargo_id:c for c in cargos}; geom_cache={}
    drone_intervals={}; battery_intervals={}
    for row in chosen:
        route=by_id[row["route_id"]]; model=row["model"]
        checks["compatible_resources"] &= model == route.model == row["model"]
        if nodes is not None and full_charge is not None:
            stops=tuple(Stop(s.area, tuple(s.cargo_ids)) for s in route.stops)
            rebuilt=build_route(model,stops,cargo_map,aircrafts[model],nodes,DEM,geom_cache,
                                meta,full_charge[model],hard_at_zero=False)
            checks["route_physics_recomputed"] &= rebuilt is not None
            if rebuilt is not None:
                tol=1e-7
                checks["route_physics_recomputed"] &= (
                    abs(rebuilt.mass-route.mass)<=tol and abs(rebuilt.volume-route.volume)<=tol
                    and abs(rebuilt.energy-route.energy)<=tol
                    and abs(rebuilt.return_s-route.return_s)<=tol
                    and abs(rebuilt.prep_s-route.prep_s)<=tol
                    and abs(rebuilt.drone_duration-route.drone_duration)<=tol
                    and abs(rebuilt.battery_duration-route.battery_duration)<=tol
                    and abs(rebuilt.return_soc-route.return_soc)<=tol
                    and dict(rebuilt.delivery_offsets).keys()==dict(route.delivery_offsets).keys()
                    and all(abs(dict(rebuilt.delivery_offsets)[c]-dict(route.delivery_offsets)[c])<=tol
                            for c in dict(rebuilt.delivery_offsets)))
        checks["compatible_resources"] &= row["drone_id"] in drones[model] and row["battery_id"] in {b for b,_ in batteries[model]}
        checks["route_soc_and_energy"] &= route.return_soc+1e-9>=aircrafts[model].reserve_fraction and route.energy<=(1-aircrafts[model].reserve_fraction)*aircrafts[model].usable_energy_kwh+1e-8
        drone_intervals.setdefault(row["drone_id"],[]).append((row["start_s"],row["start_s"]+route.drone_duration))
        battery_intervals.setdefault(row["battery_id"],[]).append((row["start_s"],row["start_s"]+route.battery_duration))
        for cid in row["cargo_ids"]:
            deadline=meta[cid]["hard_deadline"]
            expected=row["start_s"]+dict(route.delivery_offsets)[cid]
            actual=result["delivery_times"].get(cid,math.inf)
            checks["delivery_offsets_consistent"] &= abs(expected-actual)<=1e-6
            if deadline is not None: checks["hard_deadlines"] &= actual<=deadline+1e-6
    for groups,key in ((drone_intervals,"drone_intervals_nonoverlap"),(battery_intervals,"battery_charge_intervals_nonoverlap")):
        for spans in groups.values():
            spans.sort()
            checks[key] &= all(a[1]<=b[0]+1e-6 for a,b in zip(spans,spans[1:]))
    checks={k:bool(v) for k,v in checks.items()}
    if not all(checks.values()): raise ValueError(f"Q2 selected-schedule validation failed: {checks}")
    return {"status":"PASS","checks":checks,"selected_sorties":len(chosen),"unique_cargo_count":len(set(ids))}

def main():
    raise SystemExit(
        "The full-instance exact MILP is disabled. Use `python -m src.experiments.q2_alns` "
        "for the bounded ALNS workflow; use `analysis/validation/q2_miniature_milp.py` "
        "for the exact small-instance cross-check."
    )
    p=argparse.ArgumentParser()
    p.add_argument("--p1-check",action="store_true",help="run a real-data three-box end-to-end slice")
    p.add_argument("--pool-cap",type=int,default=150); p.add_argument("--proposal-cap",type=int,default=1500)
    p.add_argument("--resume",action="store_true")
    args=p.parse_args(); started=time.time()
    cargos,meta,nodes,aircrafts,drones,batteries,full_charge,input_paths=inputs()
    if args.p1_check:
        cargos=[c for c in cargos if c.service_area_id=="S001"][:3]
        keep={c.cargo_id for c in cargos}; meta={k:v for k,v in meta.items() if k in keep}
    print(json.dumps({"event":"inputs_loaded","cargo_count":len(cargos),"drones":{k:len(v) for k,v in drones.items()},
                      "batteries":{k:len(v) for k,v in batteries.items()},"utc":datetime.now(timezone.utc).isoformat()},ensure_ascii=False),flush=True)
    routes,pool=make_pool(cargos,aircrafts,nodes,DEM,meta,full_charge,BASELINE,args.pool_cap,args.proposal_cap)
    OUT.mkdir(parents=True,exist_ok=True)
    write_json(OUT/("p1_pool.json" if args.p1_check else "candidate_pool.json"),{"routes":[r.to_json() for r in routes],"summary":pool})
    print(json.dumps({"event":"pool_ready","route_count":len(routes),
                      "counts_by_model":pool["counts_by_model"],"proposals_by_model":pool["proposals_by_model"],
                      "rejected":pool["rejected"]},ensure_ascii=False),flush=True)
    if args.p1_check:
        # Keep actual heterogeneous resources and solve a compact slice, with hard windows intact.
        result=lex_solve(routes,cargos,meta,aircrafts,drones,batteries,"energy")
        validation=validate_solution(result,routes,cargos,meta,aircrafts,drones,batteries,nodes,full_charge)
        payload={"experiment":"q2-real-data-p1-slice","input_sha256":{str(x.relative_to(ROOT)):sha(x) for x in input_paths+[DEM,BASELINE]},
                 "route_count":len(routes),"pool":pool,"solve":result,"validation":validation,"elapsed_s":time.time()-started,
                 "python":sys.version,"generated_utc":datetime.now(timezone.utc).isoformat()}
        write_json(OUT/"p1_slice.json",payload)
        print(json.dumps({"event":"p1_complete","status":result["status"],"metrics":result.get("metrics"),
                          "elapsed_s":payload["elapsed_s"]},ensure_ascii=False),flush=True)
        return
    # Full experiment: four exact lexicographic endpoints followed by endpoint-derived epsilon grid.
    endpoints={}; solve_records=[]
    for target in ("late","makespan","energy","sorties"):
        rec=lex_solve(routes,cargos,meta,aircrafts,drones,batteries,target)
        endpoints[target]=rec; solve_records.append({"kind":"endpoint","target":target,"record":rec})
        write_json(OUT/"solve_checkpoint.json",{"endpoints":endpoints,"records":solve_records})
        print(json.dumps({"event":"endpoint","target":target,"status":rec["status"],"metrics":rec.get("metrics"),"vars":rec.get("nvar"),"rows":rec.get("nrow")},ensure_ascii=False),flush=True)
    if any(r["status"]!="optimal" for r in endpoints.values()):
        raise RuntimeError("At least one endpoint lacks an optimal certificate; refusing to claim a full experiment")
    levels={k:sorted({round(e["metrics"][k],8) for e in endpoints.values()}) for k in ("makespan","energy","sorties")}
    points=[]
    from itertools import product
    for t,e,n in product(levels["makespan"],levels["energy"],levels["sorties"]):
        rec=lex_solve(routes,cargos,meta,aircrafts,drones,batteries,"late",{"makespan":t,"energy":e,"sorties":n})
        if rec["status"]=="optimal": points.append(rec)
        solve_records.append({"kind":"epsilon","bounds":{"makespan":t,"energy":e,"sorties":n},"record":rec})
        write_json(OUT/"solve_checkpoint.json",{"endpoints":endpoints,"records":solve_records})
        print(json.dumps({"event":"epsilon","bounds":{"makespan":t,"energy":e,"sorties":n},"status":rec["status"],"metrics":rec.get("metrics")},ensure_ascii=False),flush=True)
    unique={tuple(round(p["metrics"][k],7) for k in ("late","makespan","energy","sorties")):p for p in points}
    vals=list(unique.values())
    nondom=[p for p in vals if not any(all(q["metrics"][k]<=p["metrics"][k]+1e-7 for k in p["metrics"]) and any(q["metrics"][k]<p["metrics"][k]-1e-7 for k in p["metrics"]) for q in vals)]
    chosen=min(nondom,key=lambda p:(p["metrics"]["late"],p["metrics"]["makespan"],p["metrics"]["energy"],p["metrics"]["sorties"]))
    validation=validate_solution(chosen,routes,cargos,meta,aircrafts,drones,batteries,nodes,full_charge)
    report={"status":"complete_pool_optimal","pool":pool,"route_count":len(routes),"input_sha256":{str(x.relative_to(ROOT)):sha(x) for x in input_paths+[DEM,BASELINE]},
            "endpoints":{k:{"status":v["status"],"metrics":v.get("metrics"),"dual_bound":v.get("dual_bound"),"gap":v.get("gap"),"lex_proof":v.get("lex_proof")} for k,v in endpoints.items()},
            "sampled_nondominated_count":len(nondom),"chosen_metrics":chosen["metrics"],"chosen":chosen["selected"],
            "delivery_times":chosen["delivery_times"],"cargo_metadata":meta,"validation":validation,"solve_count":len(solve_records),"elapsed_s":time.time()-started,
            "scope":"Optimal only within the deterministic finite candidate-route pool; the sampled epsilon set is not the full Pareto frontier.",
            "generated_utc":datetime.now(timezone.utc).isoformat()}
    write_json(OUT/"full_report.json",report); write_json(OUT/"solve_records.json",solve_records)
    export_rows(report,cargos,routes)
    print(json.dumps({"event":"full_complete","status":report["status"],"metrics":chosen["metrics"],"routes":len(chosen["selected"]),"elapsed_s":report["elapsed_s"]},ensure_ascii=False),flush=True)

def export_rows(report,cargos,routes=None):
    OUT.mkdir(parents=True,exist_ok=True); selected=report["chosen"]
    with (OUT/"sorties.csv").open("w",newline="",encoding="utf-8-sig") as f:
        cols=["Sortie ID","Drone ID","Model ID","Battery ID","Start Time (s)","Service Area Visit Order","Return to O01 Time (s)","Sortie Energy (kWh)"]
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for i,r in enumerate(sorted(selected,key=lambda x:(x["start_s"],x["route_id"])),1):
            w.writerow({"Sortie ID":f"Q2-{i:03d}","Drone ID":r["drone_id"],"Model ID":r["model"],"Battery ID":r["battery_id"],"Start Time (s)":r["start_s"],"Service Area Visit Order":"-".join(["O01",*r["stops"],"O01"]),"Return to O01 Time (s)":r["return_s"],"Sortie Energy (kWh)":r["energy_kwh"]})
    with (OUT/"deliveries.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=["Cargo Box ID","Sortie ID","Service Area ID","Delivery Completion Time (s)"]);w.writeheader()
        for i,r in enumerate(sorted(selected,key=lambda x:(x["start_s"],x["route_id"])),1):
            for cid in r["cargo_ids"]: w.writerow({"Cargo Box ID":cid,"Sortie ID":f"Q2-{i:03d}","Service Area ID":next(c.service_area_id for c in cargos if c.cargo_id==cid),"Delivery Completion Time (s)":report["delivery_times"][cid]})
    with (OUT/"resource_timeline.csv").open("w",newline="",encoding="utf-8-sig") as f:
        cols=["Sortie ID","Resource Type","Resource ID","Model ID","Occupied From (s)","Occupied Until (s)","Return Time (s)","Charge Start (s)","Battery Ready (s)"]
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for i,r in enumerate(sorted(selected,key=lambda x:(x["start_s"],x["route_id"])),1):
            sid=f"Q2-{i:03d}"; ret=r["return_s"]; ready=r["start_s"]+r["battery_duration_s"]
            w.writerow({"Sortie ID":sid,"Resource Type":"drone","Resource ID":r["drone_id"],"Model ID":r["model"],"Occupied From (s)":r["start_s"],"Occupied Until (s)":r["return_s"],"Return Time (s)":ret,"Charge Start (s)":"","Battery Ready (s)":""})
            w.writerow({"Sortie ID":sid,"Resource Type":"battery","Resource ID":r["battery_id"],"Model ID":r["model"],"Occupied From (s)":r["start_s"],"Occupied Until (s)":ready,"Return Time (s)":ret,"Charge Start (s)":ret,"Battery Ready (s)":ready})
    route_by_id={r.route_id:r for r in (routes or [])}
    with (OUT/"route_map.csv").open("w",newline="",encoding="utf-8-sig") as f:
        cols=["Sortie ID","Sequence","Node","Cargo Box IDs","Start Time (s)","Return Time (s)","Drone ID","Battery ID"]
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for i,r in enumerate(sorted(selected,key=lambda x:(x["start_s"],x["route_id"])),1):
            sid=f"Q2-{i:03d}"
            w.writerow({"Sortie ID":sid,"Sequence":0,"Node":"O01","Cargo Box IDs":"","Start Time (s)":r["start_s"],"Return Time (s)":r["return_s"],"Drone ID":r["drone_id"],"Battery ID":r["battery_id"]})
            route=route_by_id.get(r["route_id"])
            if route is not None and [stop.area for stop in route.stops] != r["stops"]:
                raise ValueError(f"Saved route stop order disagrees for {r['route_id']}")
            for seq,area in enumerate(r["stops"],1):
                cargo_ids = route.stops[seq-1].cargo_ids if route is not None else ()
                w.writerow({"Sortie ID":sid,"Sequence":seq,"Node":area,"Cargo Box IDs":",".join(cargo_ids),"Start Time (s)":r["start_s"],"Return Time (s)":r["return_s"],"Drone ID":r["drone_id"],"Battery ID":r["battery_id"]})
            w.writerow({"Sortie ID":sid,"Sequence":len(r["stops"])+1,"Node":"O01","Cargo Box IDs":"","Start Time (s)":r["start_s"],"Return Time (s)":r["return_s"],"Drone ID":r["drone_id"],"Battery ID":r["battery_id"]})
    late=[max(0.0,report["delivery_times"][c.cargo_id]-report.get("cargo_metadata",{}).get(c.cargo_id,{}).get("desired",0.0)) for c in cargos if c.cargo_id in report["delivery_times"]]
    with (OUT/"timeliness_summary.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=["Metric","Value","Unit"]);w.writeheader()
        w.writerows([{"Metric":"cargo_count","Value":len(cargos),"Unit":"boxes"},
                     {"Metric":"delivered_count","Value":len(report["delivery_times"]),"Unit":"boxes"},
                     {"Metric":"hard_deadline_count","Value":sum(1 for c in cargos if report.get("cargo_metadata",{}).get(c.cargo_id,{}).get("hard_deadline") is not None),"Unit":"boxes"},
                     {"Metric":"hard_deadline_pass_count","Value":sum(1 for c in cargos if report.get("cargo_metadata",{}).get(c.cargo_id,{}).get("hard_deadline") is not None and report["delivery_times"].get(c.cargo_id,float("inf"))<=report["cargo_metadata"][c.cargo_id]["hard_deadline"]+1e-6),"Unit":"boxes"},
                     {"Metric":"weighted_lateness","Value":report["metrics"]["late"],"Unit":"priority·s"},
                     {"Metric":"unweighted_lateness_sum","Value":sum(late),"Unit":"s"},
                     {"Metric":"on_time_desired_count","Value":sum(1 for c in cargos if c.cargo_id in report["delivery_times"] and report["delivery_times"][c.cargo_id]<=report.get("cargo_metadata",{}).get(c.cargo_id,{}).get("desired",float("inf"))+1e-6),"Unit":"boxes"}])
    # Fill the supplied workbook copy and preserve all untouched sheets/structure.
    template=ROOT/"questions"/"Results Submission Template.xlsx"
    wb=load_workbook(template)
    try:
        mappings={
            "Q2_Transport Sorties":(["Sortie ID","Drone ID","Model ID","Battery ID","Start Time (s)","Service Area Visit Order","Return to O01 Time (s)","Sortie Energy (kWh)"],[]),
            "Q2_Box Deliveries":(["Cargo Box ID","Sortie ID","Service Area ID","Delivery Completion Time (s)"],[])}
        sortie_rows=[]; delivery_rows=[]; sorted_sel=sorted(selected,key=lambda x:(x["start_s"],x["route_id"]))
        for i,r in enumerate(sorted_sel,1):
            sid=f"Q2-{i:03d}"
            sortie_rows.append([sid,r["drone_id"],r["model"],r["battery_id"],r["start_s"],"-".join(["O01",*r["stops"],"O01"]),r["return_s"],r["energy_kwh"]])
            for cid in r["cargo_ids"]:
                delivery_rows.append([cid,sid,next(c.service_area_id for c in cargos if c.cargo_id==cid),report["delivery_times"][cid]])
        for name,(headers,_) in mappings.items():
            if name not in wb.sheetnames: raise ValueError(f"Template is missing sheet {name}")
            ws=wb[name]
            actual=tuple(ws.cell(1,j).value for j in range(1,len(headers)+1))
            if actual!=tuple(headers): raise ValueError(f"Unexpected template headers in {name}: {actual}")
            for row in range(2,ws.max_row+1):
                for col in range(1,len(headers)+1): ws.cell(row,col).value=None
        for name,rows in (("Q2_Transport Sorties",sortie_rows),("Q2_Box Deliveries",delivery_rows)):
            ws=wb[name]
            for ri,row in enumerate(rows,2):
                for ci,value in enumerate(row,1):
                    cell=ws.cell(ri,ci)
                    if ri>2 and ws.cell(2,ci).has_style: cell._style=copy(ws.cell(2,ci)._style)
                    cell.value=value
        target=OUT/"Q2_Results_Submission_Template.xlsx"; tmp=target.with_suffix(".tmp.xlsx")
        wb.save(tmp); check=load_workbook(tmp,read_only=True,data_only=False)
        try:
            if check.sheetnames!=wb.sheetnames: raise ValueError("Template sheet topology changed")
            if check["Q2_Transport Sorties"].max_row!=len(sortie_rows)+1 or check["Q2_Box Deliveries"].max_row!=len(delivery_rows)+1:
                raise ValueError("Template output row count mismatch")
        finally: check.close()
        tmp.replace(target)
    finally: wb.close()

if __name__=="__main__": main()
