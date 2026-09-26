"""Create auditable Q2 raw-data, search-process, and final-result figures."""
from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "q2"
FIG = ROOT / "figures"
PREVIEW = OUT / "figure_previews"
FIG_Q2 = FIG / "q2"
SKILL = Path(r"C:\Users\Administrator\.codex\skills\math-modeling")
sys.path.insert(0, str(SKILL / "tools" / "figure" / "scripts"))
sys.path.insert(0, str(ROOT))
from export_figure import export_figure
from src.experiments.q2_full import inputs
from utils.plot_style import apply_publication_style


def save(fig, name, size=(6.2, 3.8)):
    FIG.mkdir(parents=True, exist_ok=True)
    FIG_Q2.mkdir(parents=True, exist_ok=True)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    export_figure(fig, str(FIG / name), formats=["pdf", "svg", "png"], dpi=300,
                  size_inches=size, grayscale_preview=False, tight=True)
    with Image.open(FIG / f"{name}.png") as image:
        grayscale = image.convert("L")
        grayscale.save(PREVIEW / f"{name}_grayscale.png", dpi=(300, 300))
    for suffix in ("pdf", "svg", "png"):
        shutil.copy2(FIG / f"{name}.{suffix}", FIG_Q2 / f"{name}.{suffix}")
    plt.close(fig)


def main():
    FIG.mkdir(exist_ok=True)
    apply_publication_style(language="en", width="report")
    baseline_report = json.loads((OUT / "alns_report.json").read_text(encoding="utf-8"))
    endpoint_path = OUT / "alns_sortie_k400_seed20260929.json"
    report = (json.loads(endpoint_path.read_text(encoding="utf-8"))
              if endpoint_path.exists()
              else baseline_report)
    sens = json.loads((OUT / "alns_sensitivity.json").read_text(encoding="utf-8"))
    pool = json.loads((OUT / "candidate_pool_k400.json").read_text(encoding="utf-8"))
    cargos, meta, nodes, aircrafts, drones, batteries, full_charge, paths = inputs()
    cmap = {c.cargo_id: c for c in cargos}
    colors = {"A": "#0072B2", "B": "#E69F00", "C": "#009E73"}
    with (OUT / "cargo_profile.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["cargo_id", "area", "mass_kg", "volume_m3",
                                         "desired_s", "priority", "hard_deadline_s", "supply_type"])
        w.writeheader()
        for c in cargos:
            m = meta[c.cargo_id]
            w.writerow({"cargo_id": c.cargo_id, "area": c.service_area_id,
                        "mass_kg": c.mass_kg, "volume_m3": c.volume_m3,
                        "desired_s": m["desired"], "priority": m["priority"],
                        "hard_deadline_s": m["hard_deadline"], "supply_type": m["supply_type"]})

    # Raw inputs: deadline distribution, load-size relationship, area demand.
    fig, ax = plt.subplots()
    desired = np.array([meta[c.cargo_id]["desired"] / 3600 for c in cargos])
    desired_values, desired_counts = np.unique(desired, return_counts=True)
    ax.bar(desired_values, desired_counts, width=.62, color="#4477AA", edgecolor="white")
    for x, n in zip(desired_values, desired_counts):
        ax.text(x, n + .6, f"{n}", ha="center", va="bottom", fontsize=8)
    ax.set(xlabel="Desired delivery time (h)", ylabel="Cargo boxes",
           title="Requested delivery times")
    ax.tick_params(labelsize=7.5)
    ax.xaxis.label.set_size(8); ax.yaxis.label.set_size(8); ax.title.set_size(9)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "raw_q2_desired_windows", size=(5.0, 3.2))

    mass = np.array([c.mass_kg for c in cargos]); volume = np.array([c.volume_m3 for c in cargos])
    priority = np.array([meta[c.cargo_id]["priority"] for c in cargos])
    p1, p2 = np.quantile(priority, [1 / 3, 2 / 3])
    group_labels = ["Low priority", "Medium priority", "High priority"]
    fig, axes = plt.subplots(1, 3, figsize=(6.2, 2.8), sharex=True, sharey=True)
    color_list = ["#0072B2", "#E69F00", "#CC79A7"]
    for group, (axp, color) in enumerate(zip(axes, color_list)):
        grouped = Counter((c.mass_kg, c.volume_m3)
                          for c in cargos
                          if (meta[c.cargo_id]["priority"] <= p1 if group == 0 else
                              p1 < meta[c.cargo_id]["priority"] <= p2 if group == 1 else
                              meta[c.cargo_id]["priority"] > p2))
        points = sorted(grouped.items())
        xs, ys, sizes = [], [], []
        for (m, v), count in points:
            xs.append(m); ys.append(v); sizes.append(8 * count)
        # Keep labels legible when several exact mass-volume pairs lie on
        # the same horizontal band. Leader lines preserve the true coordinates.
        crowded = (len(points) > 1 and
                   max(v for (_, v), _ in points) - min(v for (_, v), _ in points) <= .004)
        offsets = [(7, -16), (7, -7), (7, 3), (7, 13), (7, 22)]
        for i, ((m, v), count) in enumerate(points):
            offset = offsets[i % len(offsets)] if crowded else (7, 5)
            axp.annotate(str(count), (m, v), xytext=offset, textcoords="offset points",
                         fontsize=7, ha="left", va="center",
                         arrowprops={"arrowstyle": "-", "lw": .45, "color": "#555555"}
                         if crowded else None)
        axp.scatter(xs, ys, s=sizes, color=color, edgecolors="black", linewidths=.45, alpha=.82)
        axp.set_title(f"{group_labels[group]} (n={sum(grouped.values())})")
        axp.spines[["top", "right"]].set_visible(False)
        axp.set_xlabel("Mass (kg)")
        axp.tick_params(labelsize=7)
        axp.xaxis.label.set_size(8); axp.title.set_size(8)
    axes[0].set_ylabel("Volume (m³)")
    axes[0].yaxis.label.set_size(8)
    axes[0].set_xlim(float(mass.min()) - 3.0, float(mass.max()) + 2.5)
    axes[0].set_ylim(float(volume.min()) - .003, float(volume.max()) + .003)
    save(fig, "raw_q2_mass_volume_priority", size=(5.1, 2.8))

    fig, ax = plt.subplots()
    area_count = Counter(c.service_area_id for c in cargos)
    areas = sorted(area_count, key=lambda a: (-area_count[a], a))
    ax.barh(areas[::-1], [area_count[a] for a in areas[::-1]], color="#66CCEE")
    for i, area in enumerate(areas[::-1]):
        ax.text(area_count[area] + .12, i, str(area_count[area]), va="center", fontsize=7)
    ax.set(xlabel="Cargo boxes", ylabel="Service area",
           title="Cargo demand by service area")
    ax.tick_params(labelsize=7.5)
    ax.xaxis.label.set_size(8); ax.yaxis.label.set_size(8); ax.title.set_size(9)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "raw_q2_area_demand", size=(4.8, 3.1))

    # Process: finite candidate pool composition, route structure, and ALNS trade-offs.
    fig, ax = plt.subplots()
    pool_counts = pool["summary"]["counts_by_model"]
    proposed = pool["summary"]["proposals_by_model"]
    x = np.arange(len(pool_counts)); models = list(sorted(pool_counts))
    ax.bar(x, [pool_counts[m] for m in models], color=[colors[m] for m in models], width=.62)
    ax2 = ax.twinx()
    ax2.plot(x, [proposed[m] for m in models], color="#333333", marker="D", ls="--", lw=1.2)
    for i, m in enumerate(models): ax.text(i, pool_counts[m] + 8, str(pool_counts[m]), ha="center", fontsize=7.5)
    ax.set(xticks=x, xticklabels=models, xlabel="Aircraft model", ylabel="Retained candidates (bars)",
           title="Initial $K=400$ pool and proposals")
    # Add headroom above the 400-candidate bars. Axis labels identify both
    # series, so a separate legend is unnecessary and would crowd this panel.
    ax.set_ylim(0, 600)
    ax2.set_ylim(0, 2600)
    ax2.set_ylabel("Route proposals (line)", fontsize=7.5)
    ax.tick_params(labelsize=7.5); ax2.tick_params(labelsize=7)
    ax.xaxis.label.set_size(8); ax.yaxis.label.set_size(7.5); ax.title.set_size(8.5)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "process_q2_pool_by_model", size=(3.25, 2.35))

    fig, ax = plt.subplots()
    stops = Counter(len(r["stops"]) for r in pool["routes"])
    xs = sorted(stops)
    bars = ax.bar(xs, [stops[k] for k in xs], color="#AA3377", width=.72)
    for bar, k in zip(bars, xs):
        if stops[k] > 20:
            ax.annotate(f"{stops[k]:,}", (bar.get_x() + bar.get_width()/2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha="center",
                        va="bottom", fontsize=7)
        else:
            # Call out rare route structures instead of letting the linear
            # scale hide them against the much larger one- and two-stop counts.
            ax.annotate(f"{stops[k]:,}", (bar.get_x() + bar.get_width()/2, bar.get_height()),
                        xytext=(0, 28), textcoords="offset points", ha="center",
                        va="bottom", fontsize=7, color="#7A174F",
                        arrowprops={"arrowstyle": "-", "lw": .55, "color": "#7A174F"})
    ax.set(xlabel="Service-area stops per route", ylabel="Candidate routes",
           title="Route stops in the initial pool")
    ax.set_xticks(xs)
    ax.tick_params(labelsize=7.5)
    ax.xaxis.label.set_size(8); ax.yaxis.label.set_size(8); ax.title.set_size(8.5)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "process_q2_route_stop_counts", size=(3.25, 2.35))

    fig, ax = plt.subplots()
    archive = report.get("pareto_archive") or baseline_report["pareto_archive"]
    al = [p["metrics"]["late"] for p in archive]
    am = [p["metrics"]["makespan"] / 3600 for p in archive]
    ae = [p["metrics"]["energy"] for p in archive]
    e1, e2 = np.quantile(ae, [1/3, 2/3])
    egroup = np.where(np.asarray(ae) <= e1, 0, np.where(np.asarray(ae) <= e2, 1, 2))
    ecolors = ["#009E73", "#E69F00", "#D55E00"]
    for group, label in enumerate(("Lower energy", "Medium energy", "Higher energy")):
        mask = egroup == group
        ax.scatter(np.asarray(al)[mask], np.asarray(am)[mask], color=ecolors[group],
                   label=label, s=48, edgecolors="white", linewidths=.4)
    ax.scatter([report["metrics"]["late"]], [report["metrics"]["makespan"] / 3600],
               marker="*", s=160, color="black", label="Recommended")
    ax.set(xlabel="Priority-weighted lateness (priority·s)", ylabel="Makespan (h)",
           title="Heuristic schedule archive")
    ax.tick_params(labelsize=8)
    ax.xaxis.label.set_size(8.5); ax.yaxis.label.set_size(8.5); ax.title.set_size(9)
    ax.legend(frameon=False, loc="best", title="Energy encoded by color", fontsize=7.5,
              title_fontsize=7.5)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "process_q2_pareto_archive", size=(5.0, 3.4))

    fig, axes = plt.subplots(2, 2, figsize=(6.2, 3.8))
    labels = ["Late", "Makespan", "Energy", "Sorties"]
    keys = ["late", "makespan", "energy", "sorties"]
    units = ["priority·s", "s", "kWh", "count"]
    for ax, key, label, unit in zip(axes.flat, keys, labels, units):
        vals = [baseline_report["metrics"][key], report["metrics"][key]]
        bars = ax.bar([0,1], vals, color=["#4477AA", "#EE6677"], width=.64,
                      edgecolor="black", linewidth=.5)
        ax.bar([0], [vals[0]], color="none", hatch="///", edgecolor="black", width=.64)
        for bar, value in zip(bars, vals):
            ax.annotate(f"{value:,.1f}" if key != "sorties" else f"{value:.0f}",
                        (bar.get_x()+bar.get_width()/2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=7)
        ax.set(xticks=[0,1], xticklabels=["Late\nfirst", "Sorties\nfirst"],
               title=label, ylabel=unit)
        ax.set_ylim(0, max(vals) * 1.22 if max(vals) > 0 else 1)
        ax.spines[["top","right"]].set_visible(False)
    save(fig, "process_q2_objective_tradeoff", size=(5.4, 3.5))

    fig, ax = plt.subplots()
    timeline = report["chosen"]
    drone_ids = sorted({r["drone_id"] for r in timeline})
    y = {d: i for i, d in enumerate(drone_ids)}
    for r in timeline:
        ax.barh(y[r["drone_id"]], (r["return_s"]-r["start_s"])/3600,
                left=r["start_s"]/3600, color=colors[r["model"]], alpha=.8, height=.68)
    ax.set(yticks=range(len(drone_ids)), yticklabels=drone_ids, xlabel="Time (h)",
           ylabel="Drone")
    ax.set_ylim(-.65, len(drone_ids) + .35)
    handles = [plt.Line2D([0],[0], color=colors[m], lw=5, label=f"Model {m}") for m in models]
    ax.legend(handles=handles, frameon=False, ncol=3, loc="upper center",
              bbox_to_anchor=(.5, 1.0))
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "process_q2_drone_schedule", size=(5.7, 3.5))

    # Results: per-cargo timeliness, physical route map, and fleet/resource load.
    dtime = report["delivery_times"]
    ordered = sorted(cargos, key=lambda c: dtime[c.cargo_id])
    fig, ax = plt.subplots()
    xx = np.arange(1, len(ordered)+1)
    delivery_h = np.array([dtime[c.cargo_id] / 3600 for c in ordered])
    desired_h = np.array([meta[c.cargo_id]["desired"] / 3600 for c in ordered])
    ax.plot(xx, delivery_h, color="#0072B2", lw=1.5, label="Actual delivery")
    ax.scatter(xx, desired_h, color="#D55E00", marker=".", s=16,
               label="Desired time", zorder=3)
    hard_x=[]; hard_y=[]
    for i,c in enumerate(ordered):
        if meta[c.cargo_id]["hard_deadline"] is not None:
            hard_x.append(i+1); hard_y.append(meta[c.cargo_id]["hard_deadline"]/3600)
    if hard_x: ax.scatter(hard_x, hard_y, marker="v", s=18, color="#CC3311", label="Hard deadline")
    ax.set(xlabel="Cargo boxes sorted by actual delivery", ylabel="Time (h)",
           title="Delivery times and hard deadlines")
    ax.legend(frameon=False, ncol=3); ax.spines[["top", "right"]].set_visible(False)
    save(fig, "result_q2_delivery_windows", size=(6.2, 3.8))

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(6.2, 4.4), sharex=True,
                                 height_ratios=[1, 1])
    route_count=Counter(r["model"] for r in timeline)
    energy_by_model=defaultdict(float)
    for r in timeline: energy_by_model[r["model"]]+=r["energy_kwh"]
    x=np.arange(len(models)); width=.36
    ax.bar(x,[route_count[m] for m in models],width=.55,color="#4477AA")
    ax.set(ylabel="Sorties",title="Fleet allocation and energy use")
    ax2.bar(x,[energy_by_model[m] for m in models],width=.55,color="#EE6677")
    ax2.set(xticks=x,xticklabels=models,xlabel="Aircraft model",ylabel="Energy (kWh)")
    for a in (ax,ax2): a.spines[["top","right"]].set_visible(False)
    save(fig,"result_q2_fleet_energy",size=(4.5,3.4))

    fig, ax = plt.subplots()
    ax.set_title("Selected sorties over service areas")
    lon0=np.mean([n.longitude_deg for n in nodes.values()]); lat0=np.mean([n.latitude_deg for n in nodes.values()])
    scale_x=np.cos(np.deg2rad(lat0))*111320; scale_y=110540
    xy={k:((n.longitude_deg-lon0)*scale_x/1000,(n.latitude_deg-lat0)*scale_y/1000) for k,n in nodes.items()}
    ax.scatter([xy[k][0] for k in nodes],[xy[k][1] for k in nodes],s=25,color="#555555",zorder=4)
    for k,(x0,y0) in xy.items(): ax.text(x0,y0,k,fontsize=5,ha="left",va="bottom")
    for i,r in enumerate(timeline):
        seq=["O01",*r["stops"],"O01"]
        for a,b in zip(seq,seq[1:]):
            ax.plot([xy[a][0],xy[b][0]],[xy[a][1],xy[b][1]],color=colors[r["model"]],alpha=.2,lw=.7)
    ax.set(xlabel="Local east displacement (km)",ylabel="Local north displacement (km)")
    ax.set_aspect("equal",adjustable="datalim"); ax.spines[["top","right"]].set_visible(False)
    handles=[plt.Line2D([0],[0],color=colors[m],lw=2,label=f"Model {m}") for m in models]
    ax.legend(handles=handles,frameon=False,ncol=3)
    save(fig,"result_q2_routes_map",size=(5.5,4.0))

    flow = [
        ("Input", "Cargo, fleet, terrain,\nQ1 flight physics"),
        ("Route pool", "Insert, merge, swap;\nscreen route physics"),
        ("Initial schedule", "Greedy repair under\nhard time windows"),
        ("ALNS", "Destroy and repair;\nadaptive acceptance"),
        ("Deadline enrichment", "Add time-targeted\nroutes"),
        ("Tabu VNS", "Explore route\ncombinations"),
        ("Resource schedule", "Assign drones/batteries;\nresolve conflicts"),
        ("Audit and report", "Check coverage, SOC,\nwindows, objectives"),
    ]
    fig, ax = plt.subplots(figsize=(6.2,3.6)); ax.axis("off")
    positions=[(.12,.65),(.37,.65),(.62,.65),(.87,.65),
               (.87,.35),(.62,.35),(.37,.35),(.12,.35)]
    for i,((head,body),(x0,y0)) in enumerate(zip(flow,positions)):
        ax.text(x0,y0,f"{head}\n{body}",ha="center",va="center",fontsize=8.0,
                bbox={"boxstyle":"round,pad=.32","facecolor":"#EAF2F8" if i%2==0 else "#EEF7F2","edgecolor":"#4477AA"})
    for start,end in [(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7)]:
        x1,y1=positions[start]; x2,y2=positions[end]
        if y1 == y2:
            ax.annotate("",xy=(x2-.11 if x2>x1 else x2+.11,y2),xytext=(x1+.11 if x2>x1 else x1-.11,y1),
                        arrowprops={"arrowstyle":"->","lw":1.2,"color":"#555555"})
        else:
            ax.annotate("",xy=(x2,y2+.08),xytext=(x1,y1-.08),
                        arrowprops={"arrowstyle":"->","lw":1.2,"color":"#555555"})
    save(fig,"flow_q2_model",size=(6.2,2.8))

    overall = [
        ("Q1 · completed", "Terrain-aware leg physics\nand feasible cargo batches"),
        ("Q2 · completed", "Multi-stop route pool\nand fleet scheduling"),
        ("Q3 · planned", "Communication relay\ncoverage and scheduling"),
        ("Q4 · planned", "Independent service-area groups\nand resource demand"),
    ]
    fig, ax = plt.subplots(figsize=(7.4,3.2)); ax.axis("off")
    positions=[(.27,.68),(.73,.68),(.27,.33),(.73,.33)]
    for i,((head,body),(x,y)) in enumerate(zip(overall,positions)):
        planned=i>=2
        ax.text(x,y,f"{head}\n{body}",ha="center",va="center",fontsize=8.5,
                bbox={"boxstyle":"round,pad=.60","facecolor":"#F5F5F5" if planned else ("#EAF2F8" if i==0 else "#EEF7F2"),
                      "edgecolor":"#666666" if planned else "#4477AA","linestyle":"--" if planned else "-"})
    ax.text(.5,.94,"Shared problem data  →  question-specific models  →  auditable outputs",
            ha="center",va="center",fontsize=8.5,color="#333333")
    ax.set_title("Overall problem decomposition and manuscript scope",pad=10)
    save(fig,"flow_overall_model",size=(7.4,3.2))

    captions = {
        "flow_overall_model": "Question-level roadmap. Q1 and Q2 are the completed sections in this working manuscript; dashed Q3 and Q4 cards identify planned sections, not completed results. Each question has its own model and validation outputs.",
        "raw_q2_desired_windows": "Exact frequency of the 80 requested delivery times, expressed in hours. Bars represent supplied time values; no fitted distribution is used. Source: Q2 cargo attachment.",
        "raw_q2_mass_volume_priority": "Mass–volume combinations grouped by emergency priority. Bubble area is proportional to the number of boxes at an exact mass–volume pair; labels give counts. Source: Q2 cargo attachment.",
        "raw_q2_area_demand": "Cargo-box count for each of the 15 service areas, sorted by demand. Labels report exact counts. Source: Q2 cargo attachment.",
        "process_q2_pool_by_model": "Retained route candidates and generated route proposals by aircraft model in the initial K=400-per-model pool, before the deadline-directed extension. Source: candidate_pool_k400.json.",
        "process_q2_route_stop_counts": "Number of candidate routes by service-area stop count in the initial K=400-per-model pool. Source: candidate_pool_k400.json.",
        "process_q2_pareto_archive": "Two-dimensional projection of the incomplete heuristic nondominated archive: horizontal and vertical axes show weighted lateness and makespan, color encodes energy, and sortie count is omitted. The archive does not establish a full Pareto frontier. Source: alns_report.json and alns_sortie_k400_seed20260929.json.",
        "process_q2_objective_tradeoff": "Objective values for the 39-sortie late-first baseline and the 24-sortie sortie-first recommendation; axes are separate by objective. Source: alns_report.json and alns_sortie_k400_seed20260929.json.",
        "process_q2_drone_schedule": "Preparation-to-return intervals for the eight drones in the recommended schedule. Bars identify aircraft model; battery recharge intervals are reported in resource_timeline.csv. Source: alns_sortie_k400_seed20260929.json.",
        "result_q2_delivery_windows": "Actual delivery times, desired delivery times, and applicable hard deadlines for all 80 boxes under the recommended schedule. Hard constraints apply only to medical cargo and initial-delivery cargo. Source: alns_sortie_k400_seed20260929.json and Q2 cargo attachment.",
        "result_q2_fleet_energy": "Number of sorties and modeled energy by aircraft model in the 24-sortie recommendation. Energy values follow the conditional Q1 physics convention. Source: alns_sortie_k400_seed20260929.json.",
        "result_q2_routes_map": "All selected sortie legs projected in a local east–north coordinate frame. Line color identifies aircraft model; straight legs are schematic, and overlapping lines do not identify itinerary or route order. Use sorties.csv for each itinerary and its stop sequence. Source: alns_sortie_k400_seed20260929.json and Q2 node attachment.",
        "flow_q2_model": "Q2 solution chain from input data and base route generation through initial scheduling, ALNS improvement, deadline-directed route enrichment, tabu-guided variable-neighborhood search, resource scheduling, and independent audit. Source: Q2 model and experiment implementation."
    }
    (FIG / "q2_paper_figure_captions.json").write_text(
        json.dumps(captions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"figure_logical_count":len(captions),"sensitivity_runs":len(sens["runs"]),
                      "cargo_count":len(cargos),"archive_size":len(archive),
                      "pool_counts":pool_counts},ensure_ascii=False))


if __name__ == "__main__":
    main()
