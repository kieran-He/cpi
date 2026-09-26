"""Publication-oriented English figures for Q1.

Run with:
    uv run --locked python -m src.visualization.q1_paper_figures

All plots use the validated Q1 CSV exports; no optimization is performed here.
The figure set is designed for a single-column/course-paper layout.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SKILL_ROOT = Path(os.environ.get(
    "MATH_MODELING_SKILL_ROOT",
    Path.home() / ".codex" / "skills" / "math-modeling",
))
FIGURE_TOOLS = SKILL_ROOT / "tools" / "figure" / "scripts"
if not (FIGURE_TOOLS / "export_figure.py").exists():
    raise FileNotFoundError(f"Figure skill tools not found: {FIGURE_TOOLS}")
sys.path.insert(0, str(FIGURE_TOOLS))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator

from export_figure import export_figure
from setup_style import setup_style
from visual_qa import audit_layout, print_report, render_preview

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "results" / "tables"
OUT = ROOT / "figures" / "q1_paper"
PREVIEW = OUT / "_preview"
REPORT = ROOT / "results" / "logs" / "q1_full_report_status.json"
PREVIEW_RESOLUTION = 150
# Target width for the five redesigned multi-panel figures: near full text width.

# Okabe-Ito-inspired, color-vision-safe palette; identities stay fixed across figures.
INK = "#202A35"
MUTED = "#667085"
GRID = "#E7EBF0"
BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
PURPLE = "#CC79A7"
PALETTE = {"FOD": BLUE, "HYG": ORANGE, "MED": PURPLE, "WAT": GREEN}
TYPE_NAMES = {"FOD": "Food", "HYG": "Hygiene", "MED": "Medical", "WAT": "Water"}
MODEL_MARKERS = {"A": "o", "B": "s", "C": "^"}
MODEL_COLORS = {"A": BLUE, "B": ORANGE, "C": GREEN}

CONTRACTS = {
    "q1_fig01_mass_profile": {
        "claim": "The 80-box demand uses four discrete payload masses.",
        "evidence": "Frequency of every original cargo-box mass.",
        "archetype": "quantitative grid", "chart_type": "discrete frequency dot plot",
        "source": ["q1_full_input_boxes.csv"], "size_inches": [3.5, 2.55],
    },
    "q1_fig02_mass_volume": {
        "claim": "Mass and volume are distinct loading dimensions across cargo classes.",
        "evidence": "All 80 original mass-volume pairs, grouped by cargo class.",
        "archetype": "quantitative grid", "chart_type": "categorical scatter plot",
        "source": ["q1_full_input_boxes.csv"], "size_inches": [3.5, 2.8],
    },
    "q1_fig03_area_demand": {
        "claim": "Cargo demand is concentrated unevenly across 15 service areas.",
        "evidence": "Exact box count for every service area.",
        "archetype": "quantitative grid", "chart_type": "ordered lollipop plot",
        "source": ["q1_full_input_areas.csv"], "size_inches": [3.5, 4.35],
    },
    "q1_fig04_candidate_reduction": {
        "claim": "Physical filtering and dominance screening reduce the enumerated batch pool.",
        "evidence": "Possible, physically feasible, and retained candidate counts in all 27 scenarios.",
        "archetype": "quantitative grid", "chart_type": "stage-wise profile with empirical IQR",
        "source": ["q1_full_scenario_status.csv"], "size_inches": [3.5, 3.15],
    },
    "q1_fig05_epsilon_certification": {
        "claim": "The exact Pareto front certifies every epsilon-grid record as feasible or infeasible.",
        "evidence": "Resolved epsilon records by primary objective across the 18 feasible scenarios.",
        "archetype": "quantitative grid", "chart_type": "horizontal stacked bars",
        "source": ["q1_full_epsilon_status.csv", "q1_full_scenario_status.csv"],
        "size_inches": [3.5, 2.85],
    },
    "q1_fig06_frontier_cardinality": {
        "claim": "The number of nondominated plans depends on the safety and energy parameters.",
        "evidence": "Exact Pareto-front cardinality over the 3 × 3 alpha-beta grid at each return reserve.",
        "archetype": "quantitative grid", "chart_type": "faceted annotated heatmap",
        "source": ["q1_full_pareto_sample.csv", "q1_full_scenario_status.csv"],
        "size_inches": [6.1, 2.45],
    },
    "q1_fig07_capacity_envelope": {
        "claim": "Maximum safe payload varies by service area and aircraft model.",
        "evidence": "All 45 model-area capacity calculations at the baseline parameters.",
        "archetype": "quantitative grid", "chart_type": "annotated capacity heatmap",
        "source": ["q1_full_baseline_capacity.csv"], "size_inches": [6.1, 2.55],
    },
    "q1_fig08_baseline_pareto": {
        "claim": "The baseline exact frontier exposes the trade-off among sorties, energy, and operation time.",
        "evidence": "All distinct nondominated objective vectors for the baseline scenario.",
        "archetype": "quantitative grid", "chart_type": "three pairwise objective scatter panels",
        "source": ["q1_full_pareto_sample.csv", "q1_full_formal_batches.csv"],
        "size_inches": [6.1, 4.0],
    },
    "q1_fig09_sortie_manifest": {
        "claim": "The representative plan partitions the 80 boxes into 18 physically defined sorties.",
        "evidence": "Cargo-class mass composition of each baseline sortie.",
        "archetype": "quantitative grid", "chart_type": "horizontal stacked bars",
        "source": ["q1_full_baseline_batches.csv", "q1_full_input_boxes.csv"],
        "size_inches": [6.1, 3.9],
    },
    "q1_fig10_energy_sensitivity": {
        "claim": "Energy assumptions and return reserve jointly affect energy and feasibility.",
        "evidence": "Representative-plan energy change versus baseline across all 27 parameter scenarios.",
        "archetype": "quantitative grid", "chart_type": "faceted diverging heatmap",
        "source": ["q1_full_sensitivity.csv"], "size_inches": [6.1, 2.5],
    },
}

CAPTIONS = {
    "q1_fig01_mass_profile": (
        "Frequency distribution of the 80 original cargo-box masses. Mass is discrete in the supplied data; "
        "points report exact counts rather than a fitted continuous density. Descriptive data only; no "
        "uncertainty intervals or inferential tests are applicable. Source: q1_full_input_boxes.csv."
    ),
    "q1_fig02_mass_volume": (
        "Mass-volume pairs for all 80 cargo boxes, with marker and color identifying cargo class. "
        "No jitter or smoothing is applied, so plotted coordinates remain the supplied values. "
        "Descriptive data only; no inferential fit is implied. Source: q1_full_input_boxes.csv."
    ),
    "q1_fig03_area_demand": (
        "Exact number of cargo boxes assigned to each of the 15 service areas, ordered by demand. "
        "Each dot is one area; labels give exact counts. No uncertainty interval is applicable. "
        "Source: q1_full_input_areas.csv."
    ),
    "q1_fig04_candidate_reduction": (
        "Candidate counts through the three enumeration stages for 27 parameter scenarios. Thin lines "
        "are individual scenarios; the dark line is the median and the shaded band is the empirical "
        "25th-75th percentile range across scenarios (not a confidence interval). The vertical axis is "
        "log-scaled. Source: q1_full_scenario_status.csv."
    ),
    "q1_fig05_epsilon_certification": (
        "Counts of epsilon-grid records certified feasible or infeasible by the exact subset Pareto DP, "
        "grouped by primary objective and pooled over 18 globally feasible parameter scenarios. The nine "
        "globally infeasible scenarios are excluded from this epsilon-grid summary. These are exact "
        "optimization certificates, not sampled observations. Source: q1_full_epsilon_status.csv."
    ),
    "q1_fig06_frontier_cardinality": (
        "Cardinality of the complete exact nondominated objective set for each (alpha, beta) combination, "
        "faceted by return reserve rho. Gray cells marked X are scenarios proven globally infeasible; "
        "integer annotations are exact front sizes. Source: q1_full_pareto_sample.csv and "
        "q1_full_scenario_status.csv."
    ),
    "q1_fig07_capacity_envelope": (
        "Maximum safe payload (kg) for each aircraft model and service area under the baseline parameter "
        "setting (rho=0.20, alpha=1.0, beta=1.0). Cell annotations are exact computed capacities; "
        "color encodes the same quantity. Source: q1_full_baseline_capacity.csv."
    ),
    "q1_fig08_baseline_pareto": (
        "Pairwise projections of every distinct objective vector on the complete baseline Pareto front. "
        "The star denotes the selected balanced representative; the diamond denotes the minimum-energy "
        "endpoint. Points are deterministic optimization plans, not replicates; no error bars or statistical "
        "tests apply. Source: q1_full_pareto_sample.csv and q1_full_formal_batches.csv."
    ),
    "q1_fig09_sortie_manifest": (
        "Mass composition by cargo class for each of the 18 sorties in the baseline representative plan. "
        "Stack segments sum to the exact sortie payload; all 80 boxes are assigned once. No uncertainty "
        "interval is applicable. Source: q1_full_baseline_batches.csv and q1_full_input_boxes.csv."
    ),
    "q1_fig10_energy_sensitivity": (
        "Change in representative total energy relative to the baseline plan across the full parameter "
        "grid, faceted by return reserve rho. Each feasible tile shows the exact energy difference in kWh; "
        "gray X tiles are scenarios proven globally infeasible. No statistical uncertainty is implied. "
        "Source: q1_full_sensitivity.csv."
    ),
}


def rows(filename: str) -> list[dict[str, str]]:
    path = TABLES / filename
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fval(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    if value == "":
        raise ValueError(f"Missing {key!r} in {row}")
    return float(value)


def scenario_rho(key: str) -> float:
    return float(key.split("_")[0][1:])


def cargo_class(box_id: str) -> str:
    parts = box_id.split("-")
    return parts[1] if len(parts) >= 3 else "UNK"


def style() -> None:
    setup_style(journal="nature", lang="en", use_sciplots=False)
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams.update({
        "font.size": 7.2,
        "axes.labelsize": 7.6,
        "axes.titlesize": 8.0,
        "xtick.labelsize": 6.6,
        "ytick.labelsize": 6.6,
        "legend.fontsize": 6.5,
        "axes.linewidth": 0.65,
        "lines.linewidth": 1.0,
        "lines.markersize": 4.0,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.unicode_minus": False,
    })


def finish(name: str, fig, size: tuple[float, float]) -> None:
    fig.set_size_inches(*size)
    fig.canvas.draw()
    preview = PREVIEW / f"{name}_preview.png"
    render_preview(fig, str(preview), dpi=PREVIEW_RESOLUTION)
    issues = audit_layout(fig)
    print_report(issues)
    failures = [message for severity, message in issues if severity == "FAIL"]
    if failures:
        raise RuntimeError(f"Visual QA failed for {name}: {failures}")
    # Vector outputs are .pdf and .svg; PNG is exported at 600 dpi.
    export_figure(fig, str(OUT / name), formats=["pdf", "svg", "png"],
                  size_inches=size, dpi=600, grayscale_preview=True, tight=True)
    plt.close(fig)


def clean_axis(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#98A2B3")
    ax.spines["bottom"].set_color("#98A2B3")
    ax.tick_params(length=2.5, width=0.6, color="#98A2B3", pad=2)
    ax.grid(axis="x", color=GRID, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)


def fig01_mass_profile() -> None:
    data = rows("q1_full_input_boxes.csv")
    if len(data) != 80:
        raise ValueError("Expected 80 original boxes")
    counts = Counter(fval(row, "Mass (kg)") for row in data)
    masses = sorted(counts)
    vals = [counts[m] for m in masses]
    fig, ax = plt.subplots(figsize=tuple(CONTRACTS["q1_fig01_mass_profile"]["size_inches"]),
                           layout="constrained")
    ax.vlines(masses, 0, vals, color="#A9C9DA", linewidth=2.0, zorder=2)
    ax.scatter(masses, vals, s=38, color=BLUE, edgecolor="white", linewidth=0.8, zorder=3)
    for x, y in zip(masses, vals):
        ax.annotate(f"{y}", (x, y), xytext=(0, 5), textcoords="offset points",
                    ha="center", va="bottom", fontsize=6.6, color=INK)
    ax.set(xlabel="Cargo-box mass (kg)", ylabel="Number of boxes", xlim=(0, 16), ylim=(0, max(vals) * 1.23))
    ax.set_xticks(masses)
    ax.grid(axis="y", color=GRID, linewidth=0.5)
    ax.grid(axis="x", visible=False)
    clean_axis(ax)
    finish("q1_fig01_mass_profile", fig, tuple(CONTRACTS["q1_fig01_mass_profile"]["size_inches"]))


def fig02_mass_volume() -> None:
    data = rows("q1_full_input_boxes.csv")
    if len(data) != 80:
        raise ValueError("Expected 80 mass-volume pairs")
    fig, ax = plt.subplots(figsize=tuple(CONTRACTS["q1_fig02_mass_volume"]["size_inches"]),
                           layout="constrained")
    for code in ("FOD", "HYG", "MED", "WAT"):
        subset = [row for row in data if cargo_class(row["Cargo Box ID"]) == code]
        ax.scatter([fval(r, "Mass (kg)") for r in subset],
                   [fval(r, "Volume (m³)") for r in subset],
                   s=25, marker={"FOD": "o", "HYG": "s", "MED": "D", "WAT": "^"}[code],
                   color=PALETTE[code], edgecolor="white", linewidth=0.4,
                   alpha=0.9, label=f"{TYPE_NAMES[code]} (n={len(subset)})", zorder=3)
    ax.set(xlabel="Cargo-box mass (kg)", ylabel="Cargo-box volume (m³)")
    ax.set_xticks(sorted({fval(r, "Mass (kg)") for r in data}))
    ax.legend(frameon=False, ncol=2, loc="upper right", handletextpad=0.35,
              columnspacing=0.9, borderaxespad=0.25)
    clean_axis(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.45)
    ax.grid(axis="x", visible=False)
    finish("q1_fig02_mass_volume", fig, tuple(CONTRACTS["q1_fig02_mass_volume"]["size_inches"]))


def fig03_area_demand() -> None:
    data = rows("q1_full_input_areas.csv")
    if len(data) != 15:
        raise ValueError("Expected 15 service areas")
    data.sort(key=lambda r: (fval(r, "Cargo count"), r["Service Area ID"]))
    labels = [r["Service Area ID"] for r in data]
    counts = [fval(r, "Cargo count") for r in data]
    y = np.arange(len(data))
    fig, ax = plt.subplots(figsize=tuple(CONTRACTS["q1_fig03_area_demand"]["size_inches"]),
                           layout="constrained")
    ax.hlines(y, 0, counts, color="#B7C8D3", linewidth=1.0, zorder=1)
    ax.scatter(counts, y, s=24, color=BLUE, edgecolor="white", linewidth=0.6, zorder=2)
    for xv, yv in zip(counts, y):
        ax.annotate(f"{int(xv)}", (xv, yv), xytext=(5, 0), textcoords="offset points",
                    va="center", fontsize=6.0, color=INK)
    ax.set(yticks=y, yticklabels=labels, xlabel="Cargo boxes (count)", ylabel="Service area",
           xlim=(0, max(counts) * 1.22), ylim=(-0.7, len(data) - 0.3))
    ax.grid(axis="x", color=GRID, linewidth=0.5)
    ax.grid(axis="y", visible=False)
    clean_axis(ax)
    finish("q1_fig03_area_demand", fig, tuple(CONTRACTS["q1_fig03_area_demand"]["size_inches"]))


def fig04_candidate_reduction() -> None:
    data = rows("q1_full_scenario_status.csv")
    if len(data) != 27:
        raise ValueError("Expected all 27 scenarios")
    stages = ["Candidates possible", "Candidates physical", "Candidates retained"]
    values = np.asarray([[fval(row, field) for field in stages] for row in data], dtype=float)
    x = np.arange(3)
    q25, med, q75 = np.percentile(values, [25, 50, 75], axis=0)
    fig, ax = plt.subplots(figsize=tuple(CONTRACTS["q1_fig04_candidate_reduction"]["size_inches"]),
                           layout="constrained")
    for line in values:
        ax.plot(x, line, color="#B8C2CC", alpha=0.34, linewidth=0.65,
                marker="o", markersize=2.2, zorder=1)
    ax.fill_between(x, q25, q75, color=BLUE, alpha=0.14, linewidth=0, zorder=2)
    ax.plot(x, med, color=BLUE, linewidth=1.8, marker="o", markersize=4.2,
            markeredgecolor="white", markeredgewidth=0.6, zorder=3)
    for xv, yv in zip(x, med):
        ax.annotate(f"{yv:,.0f}", (xv, yv), xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=6.1, color=INK)
    ax.set_xticks(x, ["All subsets\n× models", "Physical\nfeasibility", "Dominance\nretention"])
    ax.set_ylabel("Candidate combinations (count; log scale)")
    ax.set_yscale("log")
    ax.set_xlim(-0.18, 2.18)
    ax.grid(axis="y", which="major", color=GRID, linewidth=0.5)
    ax.grid(axis="x", visible=False)
    clean_axis(ax)
    finish("q1_fig04_candidate_reduction", fig,
           tuple(CONTRACTS["q1_fig04_candidate_reduction"]["size_inches"]))


def fig05_epsilon_certification() -> None:
    status = rows("q1_full_scenario_status.csv")
    formal = {r["Scenario"] for r in status if r["Report status"] == "formal_exact_pareto"}
    records = [r for r in rows("q1_full_epsilon_status.csv") if r["Scenario"] in formal]
    if len(formal) != 18 or not records:
        raise ValueError("Expected epsilon records for 18 feasible scenarios")
    objectives = ["N", "E", "T"]
    counts: dict[str, Counter] = {key: Counter() for key in objectives}
    for row in records:
        counts[row["Primary"]][row["Status"]] += 1
    resolved_statuses = [key for key in ("optimal", "infeasible")
                         if any(counts[obj][key] for obj in objectives)]
    unresolved = sum(counts[obj][key] for obj in objectives
                     for key in counts[obj] if key not in {"optimal", "infeasible"})
    if unresolved:
        raise ValueError(f"Unexpected unresolved epsilon records: {unresolved}")
    names = {"N": "Sorties", "E": "Energy", "T": "Operation time"}
    colors = {"optimal": BLUE, "infeasible": "#D7DEE5"}
    labels = {"optimal": "Feasible and optimal", "infeasible": "Certified infeasible"}
    fig, ax = plt.subplots(figsize=tuple(CONTRACTS["q1_fig05_epsilon_certification"]["size_inches"]),
                           layout="constrained")
    y = np.arange(len(objectives))
    left = np.zeros(len(objectives))
    for key in resolved_statuses:
        vals = np.asarray([counts[obj][key] for obj in objectives], dtype=float)
        ax.barh(y, vals, left=left, color=colors[key], height=0.56,
                edgecolor="white", linewidth=0.55, label=labels[key], zorder=2)
        for yi, start, value in zip(y, left, vals):
            if value >= 45:
                ax.text(start + value / 2, yi, f"{int(value):,}", ha="center", va="center",
                        color="white" if key == "optimal" else INK, fontsize=6.0, weight="bold")
        left += vals
    ax.set(yticks=y, yticklabels=[names[o] for o in objectives],
           xlabel="Certified epsilon-grid records (count)", ylabel="Primary objective")
    ax.invert_yaxis()
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.24),
              ncol=2, fontsize=5.8)
    ax.grid(axis="x", color=GRID, linewidth=0.5)
    clean_axis(ax)
    finish("q1_fig05_epsilon_certification", fig,
           tuple(CONTRACTS["q1_fig05_epsilon_certification"]["size_inches"]))


def fig06_frontier_cardinality() -> None:
    scenario_rows = rows("q1_full_scenario_status.csv")
    feasible = {r["Scenario"] for r in scenario_rows if r["Report status"] == "formal_exact_pareto"}
    sizes = Counter(r["Scenario"] for r in rows("q1_full_pareto_sample.csv"))
    alphas, betas, rhos = [0.9, 1.0, 1.1], [0.9, 1.0, 1.1], [0.2, 0.3, 0.4]
    if len(feasible) != 18:
        raise ValueError("Expected 18 feasible full Pareto fronts")
    matrices = []
    for rho in rhos:
        matrix = np.full((3, 3), np.nan)
        for i, alpha in enumerate(alphas):
            for j, beta in enumerate(betas):
                key = f"r{rho:.2f}_a{alpha:.1f}_b{beta:.1f}"
                if key in feasible:
                    matrix[i, j] = sizes[key]
        matrices.append(matrix)
    vmax = max(int(np.nanmax(m)) for m in matrices)
    fig, axes = plt.subplots(1, 3, figsize=tuple(CONTRACTS["q1_fig06_frontier_cardinality"]["size_inches"]),
                             layout="constrained", sharey=True)
    image = None
    for ax, rho, matrix in zip(axes, rhos, matrices):
        masked = np.ma.masked_invalid(matrix)
        image = ax.pcolormesh(np.arange(4) - 0.5, np.arange(4) - 0.5, masked,
                              cmap="viridis", vmin=1, vmax=vmax, shading="flat",
                              edgecolors="white", linewidth=0.45)
        ax.invert_yaxis()
        ax.set_yticks(range(3), [f"{a:.1f}" for a in alphas])
        if ax is axes[0]:
            ax.set_ylabel(r"$\alpha$", labelpad=2)
        else:
            ax.set_ylabel("")
        ax.set_title(rf"$\rho={rho:.1f}$", fontsize=7.0, pad=3)
        for i in range(3):
            for j in range(3):
                if np.isnan(matrix[i, j]):
                    ax.add_patch(plt.Rectangle((j - .5, i - .5), 1, 1,
                                               facecolor="#E7EBF0", edgecolor="white", linewidth=1))
                    ax.text(j, i, "X", ha="center", va="center", color="#667085", fontsize=8, weight="bold")
                else:
                    ax.text(j, i, f"{int(matrix[i, j])}", ha="center", va="center",
                            color="white", fontsize=6.7, weight="bold")
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
    for ax in axes:
        ax.set_xticks(range(3), [f"{b:.1f}" for b in betas])
        ax.set_xlabel(r"$\beta$", labelpad=2)
        ax.set_ylabel(r"$\alpha$", labelpad=2)
    cbar = fig.colorbar(image, ax=axes, fraction=0.035, pad=0.035)
    cbar.solids.set_rasterized(False)
    cbar.set_label("Nondominated plans (count)", fontsize=6.8, labelpad=5)
    cbar.ax.tick_params(labelsize=6.0, length=2)
    finish("q1_fig06_frontier_cardinality", fig,
           tuple(CONTRACTS["q1_fig06_frontier_cardinality"]["size_inches"]))


def fig07_capacity_envelope() -> None:
    data = rows("q1_full_baseline_capacity.csv")
    areas = sorted({r["Service Area ID"] for r in data})
    models = ["A", "B", "C"]
    matrix = np.full((len(models), len(areas)), np.nan)
    lookup = {(r["Service Area ID"], r["Model ID"]): r for r in data}
    for i, area in enumerate(areas):
        for j, model in enumerate(models):
            row = lookup[(area, model)]
            if row.get("Maximum Safe Payload (kg)", "") != "":
                matrix[j, i] = fval(row, "Maximum Safe Payload (kg)")
    if matrix.shape != (3, 15):
        raise ValueError(f"Expected transposed 3x15 capacity matrix, got {matrix.shape}")
    fig, ax = plt.subplots(figsize=tuple(CONTRACTS["q1_fig07_capacity_envelope"]["size_inches"]),
                           layout="constrained")
    masked = np.ma.masked_invalid(matrix)
    im = ax.pcolormesh(np.arange(16) - 0.5, np.arange(4) - 0.5, masked,
                       cmap="viridis", vmin=0, vmax=float(np.nanmax(matrix)),
                       shading="flat", edgecolors="white", linewidth=0.35)
    ax.set_xticks(range(len(areas)), [a.replace("Area-", "A") for a in areas], rotation=48, ha="right")
    ax.set_yticks(range(len(models)), [f"Model {m}" for m in models])
    ax.set_xlabel("Service area")
    ax.set_ylabel("Transport-drone model")
    for i in range(len(models)):
        for j in range(len(areas)):
            value = matrix[i, j]
            if np.isnan(value):
                label, color = "—", INK
            else:
                label = f"{value:.0f}" if abs(value - round(value)) < 0.01 else f"{value:.1f}"
                color = "white" if value > np.nanmax(matrix) * 0.52 else INK
                ax.text(j, i, label, ha="center", va="center", color=color, fontsize=6.1)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.025)
    cbar.solids.set_rasterized(False)
    cbar.set_label("Maximum safe payload (kg)", fontsize=6.8, labelpad=4)
    cbar.ax.tick_params(labelsize=6.0, length=2)
    ax.set_title("Baseline capacity envelope", loc="left", pad=4)
    finish("q1_fig07_capacity_envelope", fig,
           tuple(CONTRACTS["q1_fig07_capacity_envelope"]["size_inches"]))


def fig08_baseline_pareto() -> None:
    scenario = "r0.20_a1.0_b1.0"
    data = [r for r in rows("q1_full_pareto_sample.csv") if r["Scenario"] == scenario]
    batches = [r for r in rows("q1_full_formal_batches.csv") if r["Scenario"] == scenario]
    if not data or not batches:
        raise ValueError("Baseline Pareto front or representative batches missing")
    rep_ids = {r["Batch ID"] for r in batches}
    rep_point = None
    for r in data:
        chosen = set(filter(None, r["Selected batch IDs"].split(";")))
        if chosen == rep_ids:
            rep_point = r
            break
    if rep_point is None:
        raise ValueError("Representative batch set not found on exact baseline Pareto front")
    min_energy = min(data, key=lambda r: fval(r, "Energy (kWh)"))
    points = list({tuple(fval(r, k) for k in ("Sorties", "Energy (kWh)", "Operation Time (s)")): r
                   for r in data}.values())
    plan_specs = [
        ("Representative compromise", rep_point, ORANGE, "*", 90),
        ("Minimum-energy endpoint", min_energy, BLUE, "D", 34),
    ]
    axes_specs = [
        ("Energy (kWh)", "Sorties", "Energy [kWh]", "Sorties [count]"),
        ("Energy (kWh)", "Operation Time (s)", "Energy [kWh]", "Time [s]"),
        ("Sorties", "Operation Time (s)", "Sorties [count]", "Time [s]"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=tuple(CONTRACTS["q1_fig08_baseline_pareto"]["size_inches"]),
                             layout="constrained")
    for ax, (xkey, ykey, xlabel, ylabel) in zip(axes, axes_specs):
        for label, point, color, marker, size in plan_specs:
            ax.scatter(fval(point, xkey), fval(point, ykey), s=size, c=color, marker=marker,
                       edgecolor="white", linewidth=0.7, label=label, zorder=4)
        
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.margins(x=0.18, y=0.22)
        clean_axis(ax)
        ax.grid(axis="both", color=GRID, linewidth=0.42)
    axes[0].yaxis.set_major_locator(MaxNLocator(integer=True))
    axes[2].xaxis.set_major_locator(MaxNLocator(integer=True))
    from matplotlib.lines import Line2D
    legend_handles = [
        Line2D([], [], marker="*", linestyle="none", markersize=6, markerfacecolor=ORANGE,
               markeredgecolor="white", label="Balanced representative"),
        Line2D([], [], marker="D", linestyle="none", markersize=4, markerfacecolor=BLUE,
               markeredgecolor="white", label="Minimum-energy endpoint"),
    ]
    fig.legend(handles=legend_handles, loc="outside upper center", ncol=2,
               frameon=False, fontsize=6.0, handletextpad=0.35, columnspacing=0.8)
    finish("q1_fig08_baseline_pareto", fig,
           tuple(CONTRACTS["q1_fig08_baseline_pareto"]["size_inches"]))


def fig09_sortie_manifest() -> None:
    batches = rows("q1_full_baseline_batches.csv")
    boxes = rows("q1_full_input_boxes.csv")
    box_by_id = {r["Cargo Box ID"]: r for r in boxes}
    if len(batches) != 18 or len(box_by_id) != 80:
        raise ValueError("Expected 18 sorties and 80 unique boxes")
    batches.sort(key=lambda r: (r["Model ID"], r["Service Area ID"], r["Sortie ID"]))
    cargo_types = ["FOD", "HYG", "MED", "WAT"]
    composition = np.zeros((len(batches), len(cargo_types)))
    assigned = []
    for i, batch in enumerate(batches):
        ids = [s.strip() for s in batch["Cargo Box ID List"].split(",") if s.strip()]
        assigned.extend(ids)
        for box_id in ids:
            item = box_by_id[box_id]
            kind = cargo_class(box_id)
            composition[i, cargo_types.index(kind)] += fval(item, "Mass (kg)")
        if not np.isclose(composition[i].sum(), fval(batch, "Total Mass (kg)")):
            raise ValueError(f"Cargo-class mass does not reconcile for {batch['Sortie ID']}")
    if len(assigned) != 80 or len(set(assigned)) != 80:
        raise ValueError("Representative plan must assign each of 80 cargo boxes exactly once")
    fig, axes = plt.subplots(1, 2, figsize=tuple(CONTRACTS["q1_fig09_sortie_manifest"]["size_inches"]),
                             layout="constrained", sharex=True)
    maximum = float(composition.sum(axis=1).max())
    for ax, model in zip(axes, ("B", "C")):
        indices = [i for i, batch in enumerate(batches) if batch["Model ID"] == model]
        if len(indices) != 9:
            raise ValueError(f"Expected 9 sorties for model {model}, got {len(indices)}")
        y = np.arange(len(indices))
        left = np.zeros(len(indices))
        for j, kind in enumerate(cargo_types):
            vals = composition[indices, j]
            ax.barh(y, vals, left=left, color=PALETTE[kind], height=0.72,
                    edgecolor="white", linewidth=0.35, label=TYPE_NAMES[kind], zorder=2)
            left += vals
        totals = composition[indices].sum(axis=1)
        labels = [f"{batches[i]['Sortie ID']} | {batches[i]['Service Area ID']}"
                  for i in indices]
        for yi, total in zip(y, totals):
            ax.annotate(f"{total:.0f}", (total, yi), xytext=(3, 0), textcoords="offset points",
                        va="center", fontsize=6.0, color=INK)
        ax.set(yticks=y, yticklabels=labels, xlim=(0, maximum * 1.18), ylim=(-0.7, 8.7))
        ax.invert_yaxis()
        ax.set_title(f"Model {model} (n = 9)", fontsize=7.2, pad=3)
        ax.grid(axis="x", color=GRID, linewidth=0.5)
        clean_axis(ax)
        ax.tick_params(axis="y", labelsize=6.0, length=0, pad=2)
    axes[0].set_ylabel("Sortie | service area")
    for ax in axes:
        ax.set_xlabel("Cargo mass per sortie (kg)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=4, loc="outside lower center",
               fontsize=6.0, handlelength=0.9, handletextpad=0.3, columnspacing=0.8)
    finish("q1_fig09_sortie_manifest", fig,
           tuple(CONTRACTS["q1_fig09_sortie_manifest"]["size_inches"]))


def fig10_energy_sensitivity() -> None:
    data = rows("q1_full_sensitivity.csv")
    if len(data) != 27:
        raise ValueError("Expected 27 sensitivity scenarios")
    alpha_values, beta_values, rhos = [0.9, 1.0, 1.1], [0.9, 1.0, 1.1], [0.2, 0.3, 0.4]
    lookup = {row["Scenario"]: row for row in data}
    values = []
    for rho in rhos:
        matrix = np.full((3, 3), np.nan)
        for i, alpha in enumerate(alpha_values):
            for j, beta in enumerate(beta_values):
                key = f"r{rho:.2f}_a{alpha:.1f}_b{beta:.1f}"
                row = lookup[key]
                if row.get("Delta energy (kWh)", "") != "":
                    matrix[i, j] = fval(row, "Delta energy (kWh)")
        values.append(matrix)
    feasible_values = np.concatenate([m[np.isfinite(m)] for m in values])
    limit = max(abs(float(feasible_values.min())), abs(float(feasible_values.max())))
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)
    fig, axes = plt.subplots(1, 3, figsize=tuple(CONTRACTS["q1_fig10_energy_sensitivity"]["size_inches"]),
                             layout="constrained", sharey=True)
    image = None
    for ax, rho, matrix in zip(axes, rhos, values):
        masked = np.ma.masked_invalid(matrix)
        image = ax.pcolormesh(np.arange(4) - 0.5, np.arange(4) - 0.5, masked,
                              cmap="RdBu_r", norm=norm, shading="flat",
                              edgecolors="white", linewidth=0.45)
        ax.invert_yaxis()
        ax.set_yticks(range(3), [f"{a:.1f}" for a in alpha_values])
        if ax is axes[0]:
            ax.set_ylabel(r"$\alpha$", labelpad=2)
        else:
            ax.set_ylabel("")
        ax.set_title(rf"$\rho={rho:.1f}$", fontsize=7.0, pad=3)
        for i in range(3):
            for j in range(3):
                val = matrix[i, j]
                if np.isnan(val):
                    ax.add_patch(plt.Rectangle((j - .5, i - .5), 1, 1,
                                               facecolor="#E7EBF0", edgecolor="white", linewidth=1))
                    ax.text(j, i, "X", ha="center", va="center", color="#667085", fontsize=8, weight="bold")
                else:
                    color = "white" if abs(val) > 0.45 * limit else INK
                    ax.text(j, i, f"{val:+.1f}", ha="center", va="center",
                            color=color, fontsize=6.4, weight="bold")
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
    for ax in axes:
        ax.set_xticks(range(3), [f"{b:.1f}" for b in beta_values])
        ax.set_xlabel(r"$\beta$", labelpad=2)
        ax.set_ylabel(r"$\alpha$", labelpad=2)
    cbar = fig.colorbar(image, ax=axes, fraction=0.035, pad=0.035)
    cbar.solids.set_rasterized(False)
    cbar.set_label("Change in total energy (kWh)", fontsize=6.8, labelpad=5)
    cbar.ax.tick_params(labelsize=6.0, length=2)
    finish("q1_fig10_energy_sensitivity", fig,
           tuple(CONTRACTS["q1_fig10_energy_sensitivity"]["size_inches"]))


def write_catalog() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    contract = {}
    for key, value in CONTRACTS.items():
        contract[key] = {
            **value,
            "caption": CAPTIONS[key],
            "backend": "Python / Matplotlib",
            "formats": ["PDF vector", "SVG editable text", "PNG 600 dpi", "grayscale PNG"],
            "statistical_note": "Deterministic optimization outputs or complete descriptive records; no sampling-based CI or hypothesis tests.",
        }
    (OUT / "figure_contract_en.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    sections = [
        "# Q1 Paper Figures (English)",
        "",
        "Course-paper figure set sized for near-full text width. All chart text, filenames, and captions are in English.",
        "Every data figure is exported as editable-text SVG and PDF, 600-dpi PNG, and grayscale PNG.",
        "The charts use the complete exported records described in each caption; no observations are dropped.",
        "",
        "## Figure captions",
    ]
    categories = {
        "Raw inputs": list(CONTRACTS)[:3],
        "Modeling and proof process": list(CONTRACTS)[3:6],
        "Optimization results": list(CONTRACTS)[6:],
    }
    for title, keys in categories.items():
        sections.extend(["", f"### {title}"])
        for key in keys:
            sections.extend(["", f"**{key.removeprefix('q1_').replace('_', ' ').title()}.** {CAPTIONS[key]}"])
    sections.extend([
        "", "## Source-data profile",
        "- 80 cargo boxes; mass takes four discrete values (3, 6, 8, and 14 kg).",
        "- Box volume spans 0.012–0.035 m³; every mass-volume pair is shown without jitter.",
        "- 15 service areas; box counts range from 3 to 15, so all area-level observations are plotted directly.",
        "- 18 baseline sorties; the sortie manifest reconciles class-specific mass to sortie payload and confirms each of the 80 box IDs appears exactly once.",
        "- The baseline exact Pareto set contains two distinct objective vectors; these are deterministic plans, not repeated trials.",
        "- The 27 sensitivity scenarios contain 18 feasible exact fronts and 9 proven-infeasible cases.",
        "", "## Reproduction",
        "Run `uv run --locked python -m src.visualization.q1_paper_figures` from the repository root.",
        "The script reads `results/tables/q1_full_*.csv`; it does not modify source data or solve the optimization model.",
    ])
    (OUT / "FIGURE_CAPTIONS_EN.md").write_text("\n".join(sections) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build publication-ready English Q1 figures")
    parser.add_argument("--check-only", action="store_true", help="check source coverage without rendering")
    parser.add_argument("--figures", nargs="+", choices=CONTRACTS,
                        help="render only the selected figures (default: render all)")
    args = parser.parse_args()
    style()
    if args.check_only:
        required = {
            "q1_full_input_boxes.csv": 80,
            "q1_full_input_areas.csv": 15,
            "q1_full_scenario_status.csv": 27,
            "q1_full_sensitivity.csv": 27,
        }
        counts = {name: len(rows(name)) for name in required}
        for name, expected in required.items():
            if counts[name] != expected:
                raise ValueError(f"{name}: expected {expected} rows, got {counts[name]}")
        payload = json.loads(REPORT.read_text(encoding="utf-8"))["payload"]
        if payload.get("status") != "all_27_proven":
            raise ValueError("Q1 report gate is not all_27_proven")
        print(json.dumps({"source_rows": counts, "figure_count": len(CONTRACTS), "report_status": payload["status"]}))
        return
    OUT.mkdir(parents=True, exist_ok=True)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    write_catalog()
    builders = {
        "q1_fig01_mass_profile": fig01_mass_profile,
        "q1_fig02_mass_volume": fig02_mass_volume,
        "q1_fig03_area_demand": fig03_area_demand,
        "q1_fig04_candidate_reduction": fig04_candidate_reduction,
        "q1_fig05_epsilon_certification": fig05_epsilon_certification,
        "q1_fig06_frontier_cardinality": fig06_frontier_cardinality,
        "q1_fig07_capacity_envelope": fig07_capacity_envelope,
        "q1_fig08_baseline_pareto": fig08_baseline_pareto,
        "q1_fig09_sortie_manifest": fig09_sortie_manifest,
        "q1_fig10_energy_sensitivity": fig10_energy_sensitivity,
    }
    selected = args.figures or list(builders)
    for name in selected:
        builders[name]()
    print(json.dumps({"output_dir": str(OUT), "rendered": selected, "figure_count": len(CONTRACTS)}))


if __name__ == "__main__":
    main()
