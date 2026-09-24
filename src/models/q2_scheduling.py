"""Candidate-sortie pool and resource-constrained Q2 MILP."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, vstack

from src.data.q1_inputs import Aircraft, Cargo, Node
from src.models.q1_physics import G_M_S2, Leg, route_geometry


@dataclass(frozen=True)
class Stop:
    area: str
    cargo_ids: tuple[str, ...]


@dataclass(frozen=True)
class Route:
    route_id: str
    model: str
    stops: tuple[Stop, ...]
    cargo_ids: tuple[str, ...]
    mass: float
    volume: float
    energy: float
    return_s: float
    prep_s: float
    delivery_offsets: tuple[tuple[str, float], ...]
    drone_duration: float
    battery_duration: float
    return_soc: float

    def to_json(self) -> dict:
        return {"route_id": self.route_id, "model": self.model,
                "stops": [{"area": s.area, "cargo_ids": list(s.cargo_ids)} for s in self.stops],
                "cargo_ids": list(self.cargo_ids), "mass_kg": self.mass, "volume_m3": self.volume,
                "energy_kwh": self.energy, "return_s": self.return_s, "prep_s": self.prep_s,
                "delivery_offsets_s": dict(self.delivery_offsets), "drone_duration_s": self.drone_duration,
                "battery_duration_s": self.battery_duration, "return_soc": self.return_soc}


def route_id(model: str, stops: tuple[Stop, ...]) -> str:
    raw = json.dumps([model, [[s.area, list(s.cargo_ids)] for s in stops]], separators=(",", ":"))
    return "Q2-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def build_route(model: str, stops: tuple[Stop, ...], cargos: dict[str, Cargo], aircraft: Aircraft,
                nodes: dict[str, Node], dem: Path, geom_cache: dict, metadata: dict,
                full_charge_s: float, *, hard_at_zero: bool = True) -> Route | None:
    if not stops or any(not s.cargo_ids for s in stops):
        return None
    ids = [c for s in stops for c in s.cargo_ids]
    if len(ids) != len(set(ids)) or any(c not in cargos or cargos[c].service_area_id != s.area
                                         for s in stops for c in s.cargo_ids):
        return None
    mass = math.fsum(cargos[c].mass_kg for c in ids)
    volume = math.fsum(cargos[c].volume_m3 for c in ids)
    if mass > aircraft.payload_capacity_kg + 1e-9 or volume > aircraft.loading_volume_m3 + 1e-9:
        return None
    prep = aircraft.prep_time_s + len(ids) * aircraft.loading_time_per_box_s
    t = energy = distance_fraction = 0.0
    payload = mass
    prev = "O01"
    offsets = []
    for stop in stops:
        cur = stop.area
        key = (prev, cur, model, round(payload, 9))
        if key not in geom_cache:
            gkey = (prev, cur)
            if gkey not in geom_cache:
                geom_cache[gkey] = route_geometry(nodes[prev], nodes[cur], str(dem))
            distance, terrain, cells = geom_cache[gkey]
            src, dst = nodes[prev], nodes[cur]
            source_op = src.elevation_m if src.node_id == "O01" else src.elevation_m + 30.
            dest_op = dst.elevation_m if dst.node_id == "O01" else dst.elevation_m + 30.
            cruise = terrain + 50.; climb=max(0.,cruise-source_op); descent=max(0.,cruise-dest_op)
            loaded_range=aircraft.unloaded_range_m-(aircraft.unloaded_range_m-aircraft.full_range_m)*(payload/aircraft.payload_capacity_kg)**1.5
            seg=Leg(distance,terrain,cruise,climb,descent,
                    climb/aircraft.ascent_speed_m_s+distance/aircraft.cruise_speed_m_s+descent/aircraft.descent_speed_m_s,
                    aircraft.usable_energy_kwh*distance/loaded_range,
                    (aircraft.empty_mass_kg+payload)*G_M_S2*climb/(3.6e6*aircraft.ascent_efficiency),payload,cells)
            geom_cache[key]=seg
        else: seg = geom_cache[key]
        t += seg.flight_time_s; energy += seg.energy_kwh
        loaded_range = aircraft.unloaded_range_m - (aircraft.unloaded_range_m-aircraft.full_range_m)*(payload/aircraft.payload_capacity_kg)**1.5
        distance_fraction += seg.distance_m / loaded_range
        t += aircraft.base_handover_time_s
        for cid in stop.cargo_ids:
            t += aircraft.handover_time_per_box_s
            offsets.append((cid, prep + t))
            payload -= cargos[cid].mass_kg
        prev = cur
    key = (prev, "O01", model, 0.0)
    if key not in geom_cache:
        gkey=(prev,"O01")
        if gkey not in geom_cache: geom_cache[gkey]=route_geometry(nodes[prev],nodes["O01"],str(dem))
        distance,terrain,cells=geom_cache[gkey]; src,dst=nodes[prev],nodes["O01"]
        source_op=src.elevation_m+30.; dest_op=dst.elevation_m; cruise=terrain+50.
        climb=max(0.,cruise-source_op); descent=max(0.,cruise-dest_op)
        seg=Leg(distance,terrain,cruise,climb,descent,
                climb/aircraft.ascent_speed_m_s+distance/aircraft.cruise_speed_m_s+descent/aircraft.descent_speed_m_s,
                aircraft.usable_energy_kwh*distance/aircraft.unloaded_range_m,
                aircraft.empty_mass_kg*G_M_S2*climb/(3.6e6*aircraft.ascent_efficiency),0.,cells)
        geom_cache[key]=seg
    else: seg=geom_cache[key]
    t += seg.flight_time_s; energy += seg.energy_kwh
    distance_fraction += seg.distance_m / aircraft.unloaded_range_m
    if energy > (1-aircraft.reserve_fraction)*aircraft.usable_energy_kwh + 1e-9 or distance_fraction > 1+1e-9:
        return None
    soc = 1-energy/aircraft.usable_energy_kwh
    if soc + 1e-10 < aircraft.reserve_fraction:
        return None
    offsets_map = dict(offsets)
    if hard_at_zero and any(offsets_map[c] > metadata[c]["hard_deadline"] + 1e-9
                            for c in ids if metadata[c]["hard_deadline"] is not None):
        return None
    charge = full_charge_s * (.65*(.90-soc)/.90+.35 if soc < .90 else .35*(1-soc)/.10)
    dronedur = prep + t
    return Route(route_id(model, stops), model, stops, tuple(ids), mass, volume, energy, t, prep,
                 tuple(offsets), dronedur, dronedur+charge, soc)


def _make_pool_v0(cargos_list: list[Cargo], aircrafts: dict[str, Aircraft], nodes: dict[str, Node], dem: Path,
              metadata: dict, full_charge: dict[str, float], baseline_csv: Path,
              pool_cap: int = 150, proposal_cap: int = 1500) -> tuple[list[Route], dict]:
    """Deterministic bounded neighborhood expansion; proposals are counted pre-screen."""
    import csv
    cargos = {c.cargo_id: c for c in cargos_list}
    row_order = {c.cargo_id: i for i, c in enumerate(cargos_list)}
    cache: dict = {}
    accepted: dict[str, list[Route]] = {g: [] for g in aircrafts}
    seen: set[str] = set(); rejected = {"physical_or_hard_window": 0, "duplicate": 0}
    for model in sorted(aircrafts):
        def add(stops):
            route = build_route(model, tuple(stops), cargos, aircrafts[model], nodes, dem, cache,
                                metadata, full_charge[model])
            if route is None:
                rejected["physical_or_hard_window"] += 1; return None
            if route.route_id in seen:
                rejected["duplicate"] += 1; return None
            seen.add(route.route_id); accepted[model].append(route); return route
        # Recompute unpruned single-box seeds for every aircraft type.
        for c in cargos_list:
            add((Stop(c.service_area_id, (c.cargo_id,)),))
        # Revalidate all Q1 representative batches, preserving their assigned type.
        with baseline_csv.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row["Model ID"] != model: continue
                raw_ids = tuple(x.strip() for x in row["Cargo Box ID List"].split(","))
                if not set(raw_ids).issubset(cargos):
                    continue
                ids = tuple(sorted(raw_ids, key=row_order.get))
                add((Stop(row["Service Area ID"], ids),))
        # Stable neighborhood: insert a cargo into an existing stop or create a stop.
        # A parent in each objective queue is expanded round-robin.
        cursors = [0, 0, 0]; queues = [[], [], []]
        for r in accepted[model]:
            queues[0].append(r); queues[1].append(r); queues[2].append(r)
        proposals = 0; expanded = set(); turns = 0
        while len(accepted[model]) < pool_cap and proposals < proposal_cap:
            queue_ix = turns % 3; turns += 1
            q = queues[queue_ix]
            while cursors[queue_ix] < len(q) and q[cursors[queue_ix]].route_id in expanded:
                cursors[queue_ix] += 1
            if cursors[queue_ix] >= len(q):
                if all(cursors[k] >= len(queues[k]) for k in range(3)): break
                continue
            parent = q[cursors[queue_ix]]; cursors[queue_ix] += 1
            if parent.route_id in expanded: continue
            expanded.add(parent.route_id)
            used = set(parent.cargo_ids)
            for c in cargos_list:
                if c.cargo_id in used: continue
                generated = []
                for pos, stop in enumerate(parent.stops):
                    if stop.area == c.service_area_id:
                        seq = tuple(sorted((*stop.cargo_ids, c.cargo_id), key=row_order.get))
                        generated.append(parent.stops[:pos]+(Stop(stop.area, seq),)+parent.stops[pos+1:])
                for pos in range(len(parent.stops)+1):
                    generated.append(parent.stops[:pos]+(Stop(c.service_area_id, (c.cargo_id,)),)+parent.stops[pos:])
                for candidate_stops in generated:
                    if proposals >= proposal_cap: break
                    proposals += 1
                    route = add(candidate_stops)
                    if route is not None:
                        # newly accepted routes are queued in each objective's order;
                        # sorting is deferred deterministically at every expansion frontier.
                        queues[0].append(route); queues[1].append(route); queues[2].append(route)
                if len(accepted[model]) >= pool_cap or proposals >= proposal_cap: break
        # Ensure capacity limit is respected (seeds may exceed only if data changed).
        if len(accepted[model]) > pool_cap:
            # Seeds are mandatory per spec; fail explicitly rather than silently trim.
            raise ValueError(f"Mandatory seeds exceed pool capacity for model {model}")
    routes = sorted((r for g in accepted for r in accepted[g]), key=lambda r: r.route_id)
    cover = {c: sum(c in r.cargo_ids for r in routes) for c in cargos}
    if any(n == 0 for n in cover.values()):
        raise ValueError(f"Candidate pool does not cover cargo: {[c for c,n in cover.items() if n==0]}")
    summary = {"pool_cap_per_model": pool_cap, "proposal_cap_per_model": proposal_cap,
               "counts_by_model": {g: len(v) for g,v in accepted.items()},
               "proposals_by_model": proposals, "cover_count_by_cargo": cover,
               "rejected": rejected, "route_scope": "deterministic bounded insertion neighborhood; pool-limited"}
    return routes, summary


def make_pool(cargos_list: list[Cargo], aircrafts: dict[str, Aircraft], nodes: dict[str, Node], dem: Path,
              metadata: dict, full_charge: dict[str, float], baseline_csv: Path,
              pool_cap: int = 150, proposal_cap: int = 1500) -> tuple[list[Route], dict]:
    """Bounded deterministic route pool with objective queues and all contract operators."""
    import csv, heapq
    cargos={c.cargo_id:c for c in cargos_list}; order={c.cargo_id:i for i,c in enumerate(cargos_list)}
    accepted={g:[] for g in aircrafts}; seen=set(); cache={}
    rejected={"duplicate":0,"physical":0,"hard_window_at_zero":0,"pool_capacity":0}; proposal_counts={}
    seed_audit=[]; proposal_audit=[]; queue_audit=[]; operator_counts={}
    for model in sorted(aircrafts):
        proposals=0
        def add(stops, count_proposal=False, operator="seed", parent_id=None):
            nonlocal proposals
            stops=tuple(stops)
            if count_proposal:
                if proposals>=proposal_cap: return None
                proposals+=1
            if not stops or any(not s.cargo_ids for s in stops): return None
            ident=route_id(model,stops)
            audit={"model":model,"route_id":ident,"operator":operator,"parent_route_id":parent_id,
                   "cargo_ids":[c for s in stops for c in s.cargo_ids],"stops":[s.area for s in stops]}
            if count_proposal: operator_counts[f"{model}:{operator}"]=operator_counts.get(f"{model}:{operator}",0)+1
            if count_proposal and len(accepted[model])>=pool_cap:
                rejected["pool_capacity"]+=1; audit.update(status="not_retained",reason="pool_capacity_reached")
                proposal_audit.append(audit); return None
            route=build_route(model,stops,cargos,aircrafts[model],nodes,dem,cache,metadata,full_charge[model],hard_at_zero=False)
            if route is None:
                rejected["physical"]+=1; audit.update(status="rejected",reason="physical_infeasible")
                (proposal_audit if count_proposal else seed_audit).append(audit); return None
            offsets=dict(route.delivery_offsets)
            violated=[cid for cid in route.cargo_ids if metadata[cid]["hard_deadline"] is not None and offsets[cid]>metadata[cid]["hard_deadline"]+1e-9]
            if violated:
                rejected["hard_window_at_zero"]+=1; audit.update(status="rejected",reason="hard_window_at_start_zero",violating_cargo_ids=violated)
                (proposal_audit if count_proposal else seed_audit).append(audit); return None
            if ident in seen:
                rejected["duplicate"]+=1; audit.update(status="rejected",reason="duplicate")
                (proposal_audit if count_proposal else seed_audit).append(audit); return None
            seen.add(ident); accepted[model].append(route); audit.update(status="accepted",reason=None)
            (proposal_audit if count_proposal else seed_audit).append(audit); return route
        for c in cargos_list: add((Stop(c.service_area_id,(c.cargo_id,)),),operator="single_box_seed")
        with baseline_csv.open(encoding="utf-8-sig",newline="") as stream:
            for row in csv.DictReader(stream):
                if row["Model ID"]!=model: continue
                ids=tuple(x.strip() for x in row["Cargo Box ID List"].split(","))
                if set(ids).issubset(cargos): add((Stop(row["Service Area ID"],tuple(sorted(ids,key=order.get))),),operator="q1_representative_seed")
        def keys(r):
            off=dict(r.delivery_offsets)
            late=math.fsum(metadata[c]["priority"]*max(0.,off[c]-metadata[c]["desired"]) for c in r.cargo_ids)
            n=len(r.cargo_ids)
            return ((late,r.return_s,r.energy,-n,r.route_id),
                    (r.energy,late,r.return_s,-n,r.route_id),
                    (-n,late,r.energy,r.return_s,r.route_id))
        queues=[[],[],[]]
        for r in accepted[model]:
            for k,key in enumerate(keys(r)): heapq.heappush(queues[k],(key,r.route_id,r))
        expanded=set(); turns=0; round_num=0
        def offer(stops,operator,parent):
            r=add(stops,True,operator,parent.route_id)
            if r:
                for k,key in enumerate(keys(r)): heapq.heappush(queues[k],(key,r.route_id,r))
            return r
        while len(accepted[model])<pool_cap and proposals<proposal_cap:
            qi=turns%3; turns+=1
            while queues[qi] and queues[qi][0][1] in expanded: heapq.heappop(queues[qi])
            if not queues[qi]:
                if all(not q or all(e[1] in expanded for e in q) for q in queues): break
                continue
            _,_,parent=heapq.heappop(queues[qi]); expanded.add(parent.route_id); round_num+=1
            queue_audit.append({"model":model,"round":round_num,
                                "queue":["timeliness","energy","sorties"][qi],
                                "route_id":parent.route_id,"queue_key":list(keys(parent)[qi])})
            used=set(parent.cargo_ids)
            # 1) Cargo-row order: remove and insert into same-area stops / new positions.
            for c in cargos_list:
                if c.cargo_id in used and len(parent.cargo_ids)>1:
                    si=next(i for i,s in enumerate(parent.stops) if c.cargo_id in s.cargo_ids); stop=parent.stops[si]
                    remain=tuple(x for x in stop.cargo_ids if x!=c.cargo_id)
                    offer(parent.stops[:si]+((Stop(stop.area,remain),) if remain else ())+parent.stops[si+1:],"remove_cargo",parent)
                elif c.cargo_id not in used:
                    for si,stop in enumerate(parent.stops):
                        if stop.area==c.service_area_id:
                            ids=tuple(sorted((*stop.cargo_ids,c.cargo_id),key=order.get))
                            offer(parent.stops[:si]+(Stop(stop.area,ids),)+parent.stops[si+1:],"insert_same_area",parent)
                    for pos in range(len(parent.stops)+1):
                        offer(parent.stops[:pos]+(Stop(c.service_area_id,(c.cargo_id,)),)+parent.stops[pos:],"insert_new_stop",parent)
                if proposals>=proposal_cap or len(accepted[model])>=pool_cap: break
            if proposals>=proposal_cap or len(accepted[model])>=pool_cap: break
            # 2) Candidate-ID ordered migration and same-area exchange across route pairs.
            peers=sorted((r for r in accepted[model] if r.route_id!=parent.route_id),key=lambda r:r.route_id)
            for peer in peers:
                for cid in sorted(parent.cargo_ids,key=order.get):
                    if len(parent.cargo_ids)>1:
                        si=next(i for i,s in enumerate(parent.stops) if cid in s.cargo_ids); stop=parent.stops[si]
                        left=tuple(x for x in stop.cargo_ids if x!=cid)
                        offer(parent.stops[:si]+((Stop(stop.area,left),) if left else ())+parent.stops[si+1:],"migrate_remove",parent)
                        for pi,pstop in enumerate(peer.stops):
                            if pstop.area==cargos[cid].service_area_id:
                                ids=tuple(sorted((*pstop.cargo_ids,cid),key=order.get))
                                offer(peer.stops[:pi]+(Stop(pstop.area,ids),)+peer.stops[pi+1:],"migrate_insert",parent)
                    for did in sorted(peer.cargo_ids,key=order.get):
                        if cargos[cid].service_area_id!=cargos[did].service_area_id: continue
                        pi=next(i for i,s in enumerate(parent.stops) if cid in s.cargo_ids)
                        qi2=next(i for i,s in enumerate(peer.stops) if did in s.cargo_ids)
                        ps,qs=parent.stops[pi],peer.stops[qi2]
                        pa=tuple(sorted((*[v for v in ps.cargo_ids if v!=cid],did),key=order.get))
                        qa=tuple(sorted((*[v for v in qs.cargo_ids if v!=did],cid),key=order.get))
                        offer(parent.stops[:pi]+(Stop(ps.area,pa),)+parent.stops[pi+1:],"exchange_parent",parent)
                        offer(peer.stops[:qi2]+(Stop(qs.area,qa),)+peer.stops[qi2+1:],"exchange_peer",parent)
                        if proposals>=proposal_cap: break
                    if proposals>=proposal_cap: break
                if proposals>=proposal_cap or len(accepted[model])>=pool_cap: break
            if proposals>=proposal_cap or len(accepted[model])>=pool_cap: break
            # 3) Stop-sequence position swaps and insertions in ascending order.
            for i in range(len(parent.stops)):
                for j in range(i+1,len(parent.stops)):
                    seq=list(parent.stops); seq[i],seq[j]=seq[j],seq[i]; offer(tuple(seq),"stop_swap",parent)
                for j in range(len(parent.stops)):
                    if i==j: continue
                    seq=list(parent.stops); item=seq.pop(i); seq.insert(j,item); offer(tuple(seq),"stop_reinsert",parent)
                if proposals>=proposal_cap: break
            if proposals>=proposal_cap or len(accepted[model])>=pool_cap: break
            # 4) Merge disjoint candidates in ascending candidate-ID order.
            for peer in sorted((r for r in accepted[model] if r.route_id>parent.route_id),key=lambda r:r.route_id):
                if set(parent.cargo_ids).isdisjoint(peer.cargo_ids): offer(parent.stops+peer.stops,"merge_disjoint",parent)
                if proposals>=proposal_cap or len(accepted[model])>=pool_cap: break
        if len(accepted[model])>pool_cap: raise ValueError(f"Mandatory seeds exceed pool capacity for model {model}")
        proposal_counts[model]=proposals
    routes=sorted((r for group in accepted.values() for r in group),key=lambda r:r.route_id)
    cover={cid:sum(cid in r.cargo_ids for r in routes) for cid in cargos}
    if any(n==0 for n in cover.values()): raise ValueError(f"Candidate pool does not cover cargo: {[c for c,n in cover.items() if n==0]}")
    summary={"pool_cap_per_model":pool_cap,"proposal_cap_per_model":proposal_cap,
             "counts_by_model":{g:len(v) for g,v in accepted.items()},"proposals_by_model":proposal_counts,
             "cover_count_by_cargo":cover,"rejected":rejected,
             "proposal_counts_by_operator":operator_counts,
             "generation_audit":{"seed_recalculations":seed_audit,"proposals":proposal_audit,"queue_expansions":queue_audit},
             "seed_policy":"q2-seed-v2-all-model-singletons-plus-q1-representative-batches",
             "route_scope":"deterministic bounded insertion/removal/migration/exchange/stop-order/merge neighborhood; pool-limited"}
    return routes,summary


class MilpBuilder:
    def __init__(self): self.rows=[]; self.cols=[]; self.vals=[]; self.lb=[]; self.ub=[]; self.names=[]
    def var(self, name, lb=0., ub=np.inf, integer=False):
        j=len(self.names); self.names.append(name); self.lb.append(lb); self.ub.append(ub); return j
    def constraint(self, coeff: dict[int,float], lo=-np.inf, hi=np.inf):
        i=len(self.lbrows); self.lbrows.append(lo); self.ubrows.append(hi)
        for j,v in coeff.items():
            if v: self.rows.append(i); self.cols.append(j); self.vals.append(v)
    lbrows=[]; ubrows=[]


def solve(routes: list[Route], cargos: list[Cargo], metadata: dict, aircrafts: dict[str, Aircraft],
          drones: dict[str, list[str]], batteries: dict[str, list[tuple[str,float]]],
          primary: str, eps: dict[str,float] | None = None) -> dict:
    """Sparse MILP with exact resource disjunctions for selected route pairs."""
    if primary not in ("late", "makespan", "energy", "sorties"): raise ValueError(primary)
    eps=eps or {}; b=MilpBuilder(); b.lbrows=[]; b.ubrows=[]
    R=len(routes); route_idx={r.route_id:i for i,r in enumerate(routes)}
    x=[b.var(f"x:{r.route_id}",0,1,True) for r in routes]
    starts=[b.var(f"s:{r.route_id}",0,1e9) for r in routes]
    ys={}; zs={}
    for i,r in enumerate(routes):
        for u in drones[r.model]: ys[i,u]=b.var(f"y:{i}:{u}",0,1,True)
        for bat,_ in batteries[r.model]: zs[i,bat]=b.var(f"z:{i}:{bat}",0,1,True)
    deliveries={c.cargo_id:b.var(f"d:{c.cargo_id}",0,1e9) for c in cargos}
    late={c.cargo_id:b.var(f"late:{c.cargo_id}",0,1e9) for c in cargos}
    makespan=b.var("makespan",0,1e9)
    durs_u=[r.drone_duration for r in routes]; durs_b=[r.battery_duration for r in routes]
    cargo_sets=[set(r.cargo_ids) for r in routes]
    dmax=max([*durs_u,*durs_b],default=1); H=80*dmax; M=H+dmax
    for j in starts: b.ub[j]=H
    for i,r in enumerate(routes):
        b.constraint({starts[i]:1,x[i]:-H},hi=0)
        b.constraint({**{ys[i,u]:1 for u in drones[r.model]},x[i]:-1},lo=0,hi=0)
        b.constraint({**{zs[i,bat]:1 for bat,_ in batteries[r.model]},x[i]:-1},lo=0,hi=0)
        b.constraint({makespan:1,starts[i]:-1,x[i]:-M},lo=r.prep_s+r.return_s-M,hi=np.inf)
    for c in cargos:
        matching=[i for i,r in enumerate(routes) if c.cargo_id in r.cargo_ids]
        b.constraint({x[i]:1 for i in matching},lo=1,hi=1)
        expr={deliveries[c.cargo_id]:1}
        for i in matching:
            offset=dict(routes[i].delivery_offsets)[c.cargo_id]
            expr[starts[i]]=expr.get(starts[i],0)-1; expr[x[i]]=expr.get(x[i],0)-offset
        b.constraint(expr,lo=0,hi=0)
        b.constraint({late[c.cargo_id]:1,deliveries[c.cargo_id]:-1},lo=-metadata[c.cargo_id]["desired"])
        md=metadata[c.cargo_id]["hard_deadline"]
        if md is not None: b.constraint({deliveries[c.cargo_id]:1},hi=md)
    # Pairwise disjunction for common UAV and battery. M is from a conservative finite horizon.
    for resource_map, duration, prefix in ((drones,durs_u,"u"),(batteries,durs_b,"b")):
        for model, resources in resource_map.items():
            model_routes=[i for i,r in enumerate(routes) if r.model==model]
            for resource in resources:
                rid=resource if prefix=="u" else resource[0]
                assigns=ys if prefix=="u" else zs
                for p,q in combinations(model_routes,2):
                    # Routes sharing any cargo cannot both be selected because of exact
                    # cover. Their resource precedence disjunction is redundant and omitted.
                    if not cargo_sets[p].isdisjoint(cargo_sets[q]):
                        continue
                    order=b.var(f"ord:{prefix}:{rid}:{p}:{q}",0,1,True)
                    ap,aq=assigns[p,rid],assigns[q,rid]
                    # s_p - s_q + M*a + M*y_p + M*y_q <= 3M-Dp
                    b.constraint({starts[p]:1,starts[q]:-1,order:M,ap:M,aq:M},hi=3*M-duration[p])
                    # s_q - s_p - M*a + M*y_p + M*y_q <= 2M-Dq
                    b.constraint({starts[q]:1,starts[p]:-1,order:-M,ap:M,aq:M},hi=2*M-duration[q])
    # Objectives / epsilon bounds. Solver uses a single primary objective per call.
    exprs={"late":{late[c.cargo_id]:metadata[c.cargo_id]["priority"] for c in cargos},
           "makespan":{makespan:1}, "energy":{x[i]:r.energy for i,r in enumerate(routes)},
           "sorties":{j:1 for j in x}}
    for name,value in eps.items(): b.constraint(exprs[name],hi=value)
    A=coo_matrix((b.vals,(b.rows,b.cols)),shape=(len(b.lbrows),len(b.names))).tocsc()
    cvec=np.zeros(len(b.names));
    for j,v in exprs[primary].items(): cvec[j]=v
    result=milp(cvec,integrality=np.array([1 if n.startswith(("x:","y:","z:","ord:")) else 0 for n in b.names]),
                bounds=Bounds(np.asarray(b.lb),np.asarray(b.ub)),
                constraints=LinearConstraint(A,np.asarray(b.lbrows),np.asarray(b.ubrows)),
                options={"disp":False,"mip_rel_gap":0.0})
    if result.x is None:
        return {"status":"infeasible" if result.status==2 else "no_incumbent","solver_status":int(result.status),
                "message":str(result.message),"dual_bound":getattr(result,"mip_dual_bound",None),"gap":getattr(result,"mip_gap",None),"nvar":len(b.names),"nrow":len(b.lbrows)}
    chosen=[i for i,j in enumerate(x) if result.x[j]>.5]
    selected=[]; delivery_times={}
    for i in chosen:
        r=routes[i]
        u=next(u for (k,u),j in ys.items() if k==i and result.x[j]>.5)
        bat=next((bat for (k,bat),j in zs.items() if k==i and result.x[j]>.5),None)
        selected.append({"route_id":r.route_id,"model":r.model,"cargo_ids":list(r.cargo_ids),"stops":[s.area for s in r.stops],
                         "drone_id":u,"battery_id":bat,"start_s":float(result.x[starts[i]]),
                         "takeoff_s":float(result.x[starts[i]]+r.prep_s),"return_s":float(result.x[starts[i]]+r.prep_s+r.return_s),
                         "energy_kwh":r.energy,"return_soc":r.return_soc,"drone_duration_s":r.drone_duration,"battery_duration_s":r.battery_duration})
        for cid,off in r.delivery_offsets: delivery_times[cid]=float(result.x[starts[i]]+off)
    metrics={"late":sum(metadata[c.cargo_id]["priority"]*max(0,delivery_times[c.cargo_id]-metadata[c.cargo_id]["desired"]) for c in cargos),
             "makespan":max((r["return_s"] for r in selected),default=0.),"energy":sum(routes[i].energy for i in chosen),"sorties":len(chosen)}
    return {"status":"optimal" if result.status==0 and (result.mip_gap is None or result.mip_gap<=1e-9) else "feasible_or_unproven",
            "solver_status":int(result.status),"message":str(result.message),"dual_bound":float(result.mip_dual_bound) if result.mip_dual_bound is not None else None,
            "gap":float(result.mip_gap) if result.mip_gap is not None else None,"nvar":len(b.names),"nrow":len(b.lbrows),
            "metrics":metrics,"selected":selected,"delivery_times":delivery_times}
