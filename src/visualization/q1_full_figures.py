"""Q1 candidate figures from validated report CSVs; no optimizer calls.

Run after all 27 scenarios are formal:
    uv run --locked python -m src.visualization.q1_full_figures
Use --flow-only to draw the documented Q1-Q4 method dependency diagram.
Each planned figure has a claim, source and chart contract below. The three
categories are Q1 candidates only; they do not claim Q2-Q4 numerical results.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[2]
FIGURES = ROOT / "figures"
TABLES = ROOT / "results" / "tables"
REPORT_STATUS = ROOT / "results" / "logs" / "q1_full_report_status.json"
BLUE, ORANGE, GREEN, INK = "#0072B2", "#E69F00", "#009E73", "#222222"

# Five-point contract: claim, evidence, type, source, final size/export.
# Numeric panels use the actual row count and do not invent uncertainty bars.
CONTRACTS = {
    "raw_q1_box_mass": ("Cargo mass varies across the 80 original boxes", "all 80 box masses", "histogram", "q1_full_input_boxes.csv", (6.4, 3.7)),
    "raw_q1_mass_volume": ("Mass and volume are separate loading limits", "all 80 mass-volume pairs", "scatter", "q1_full_input_boxes.csv", (6.4, 4.1)),
    "raw_q1_area_demand": ("Box counts differ among the 15 areas", "all 15 area counts", "horizontal bars", "q1_full_input_areas.csv", (6.4, 5.2)),
    "process_q1_candidate_pruning": ("Physical filtering and dominance reduce the candidate pool", "27 scenario counts", "scatter", "q1_full_scenario_status.csv", (6.4, 4.1)),
    "process_q1_epsilon_status": ("The epsilon grid has explicitly certified solve outcomes", "all epsilon statuses", "stacked bars", "q1_full_epsilon_status.csv", (7.2, 4.1)),
    "process_q1_endpoint_shift": ("Single-objective energy endpoints respond to uncertainty", "27 energy endpoints", "dot plot", "q1_full_endpoints.csv", (6.4, 4.1)),
    "result_q1_pareto": ("Sampled Q1 tradeoffs are finite and non-exhaustive", "baseline proven Pareto sample", "scatter", "q1_full_pareto_sample.csv", (6.4, 4.1)),
    "result_q1_batch_load": ("The chosen baseline partitions cargo into physical sorties", "baseline formal batches", "strip plot", "q1_full_formal_batches.csv", (6.4, 4.1)),
    "result_q1_sensitivity": ("Representative energy and sortie counts shift by scenario", "27 formal representatives", "scatter", "q1_full_sensitivity.csv", (6.4, 4.1)),
    "flow_overall_model": ("Q1 feeds Q2, Q3 and Q4 in the documented model chain", "Q1 code and Q1-Q4 model documents", "method flow", "analysis/problems/Q1.md-Q4.md", (8.0, 5.0)),
}


def _skill_root() -> Path:
    root = Path(os.environ.get("MATH_MODELING_SKILL_ROOT", Path.home() / ".codex" / "skills" / "math-modeling"))
    if not (root / "tools" / "figure" / "scripts" / "export_figure.py").exists():
        raise FileNotFoundError("Set MATH_MODELING_SKILL_ROOT to the installed math-modeling skill directory")
    return root


def _export(fig, name: str) -> None:
    skill = _skill_root()
    sys.path.insert(0, str(skill / "tools" / "figure" / "scripts"))
    from export_figure import export_figure
    size = CONTRACTS[name][4]
    export_figure(fig, basename=str(FIGURES / name), formats=["svg", "png"],
                  size_inches=size, dpi=300, grayscale_preview=True, tight=False)
    plt.close(fig)


def _rows(name: str) -> list[dict]:
    path = TABLES / name
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _num(row: dict, key: str) -> float:
    value = row.get(key)
    if value in (None, ""):
        raise ValueError(f"Missing {key} in report CSV")
    return float(value)


def _style() -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.labelsize": 9,
                         "xtick.labelsize": 7, "ytick.labelsize": 7,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": False, "svg.fonttype": "none"})


def _new(name: str):
    fig, ax = plt.subplots(figsize=CONTRACTS[name][4], layout="constrained")
    return fig, ax


def raw_figures() -> None:
    boxes = _rows("q1_full_input_boxes.csv")
    areas = _rows("q1_full_input_areas.csv")
    if len(boxes) != 80 or len(areas) != 15:
        raise ValueError("Raw CSV audit must contain 80 boxes and 15 areas")
    mass = [_num(r, "Mass (kg)") for r in boxes]
    volume = [_num(r, "Volume (m³)") for r in boxes]

    name = "raw_q1_box_mass"; fig, ax = _new(name)
    ax.hist(mass, bins="auto", color=BLUE, edgecolor="white", linewidth=.5)
    ax.set(xlabel="Box mass (kg)", ylabel="Boxes (count)")
    _export(fig, name)

    name = "raw_q1_mass_volume"; fig, ax = _new(name)
    ax.scatter(mass, volume, s=18, color=BLUE, alpha=.65, edgecolor="none")
    ax.set(xlabel="Box mass (kg)", ylabel="Box volume (m³)")
    _export(fig, name)

    name = "raw_q1_area_demand"; fig, ax = _new(name)
    labels = [r["Service Area ID"] for r in areas]
    counts = [_num(r, "Cargo count") for r in areas]
    ax.barh(labels[::-1], counts[::-1], color=BLUE)
    ax.set(xlabel="Boxes (count)", ylabel="Service area")
    ax.set_xlim(left=0)
    _export(fig, name)


def process_figures() -> None:
    status = _rows("q1_full_scenario_status.csv")
    eps = _rows("q1_full_epsilon_status.csv")
    endpoints = _rows("q1_full_endpoints.csv")
    if len(status) != 27 or len(eps) < 27 * 363 or len(endpoints) != 27 * 3:
        raise ValueError("Process CSVs do not cover 27 full scenarios")

    name = "process_q1_candidate_pruning"; fig, ax = _new(name)
    x = [_num(r, "Candidates physical") for r in status]
    y = [_num(r, "Candidates retained") for r in status]
    ax.scatter(x, y, color=ORANGE, s=23)
    lim = max(x + y) * 1.02
    ax.plot([0, lim], [0, lim], color=INK, lw=.7, ls="--", label="No deletion")
    ax.set(xlabel="Physically feasible candidates", ylabel="After same-subset dominance")
    ax.legend(frameon=False)
    _export(fig, name)

    name = "process_q1_epsilon_status"; fig, ax = _new(name)
    count = defaultdict(Counter)
    for row in eps:
        count[row["Scenario"]][row["Status"]] += 1
    keys = sorted(count)
    left = np.zeros(len(keys))
    for label, color in (("optimal", BLUE), ("infeasible", ORANGE), ("time_limit_or_unknown", "#777777")):
        values = np.array([count[k][label] for k in keys])
        if values.any():
            ax.barh(range(len(keys)), values, left=left, color=color, label=label)
        left += values
    ax.set(yticks=range(0, len(keys), 3), yticklabels=[keys[i] for i in range(0, len(keys), 3)],
           xlabel="Epsilon MILPs (count)", ylabel="Scenario")
    ax.legend(frameon=False, fontsize=7)
    _export(fig, name)

    name = "process_q1_endpoint_shift"; fig, ax = _new(name)
    vals = [r for r in endpoints if r["Primary"] == "E"]
    colors = {"0.2": BLUE, "0.3": ORANGE, "0.4": GREEN}
    for rho, color in colors.items():
        group = [r for r in vals if abs(float(r["Scenario"].split("_")[0][1:]) - float(rho)) < 1e-8]
        ax.scatter([_num(r, "Energy (kWh)") for r in group],
                   [r["Scenario"] for r in group], s=18, color=color, label=f"rho={rho}")
    ax.set(xlabel="Minimum energy endpoint (kWh)", ylabel="Scenario")
    ax.tick_params(axis="y", labelsize=5.5)
    ax.legend(frameon=False)
    _export(fig, name)


def result_figures() -> None:
    status = _rows("q1_full_scenario_status.csv")
    if len(status) != 27 or any(r["Formal"].lower() != "true" for r in status):
        raise ValueError("Result figures require 27 formally validated scenarios")
    pareto = [r for r in _rows("q1_full_pareto_sample.csv") if r["Scenario"] == "r0.20_a1.0_b1.0"]
    sorties = [r for r in _rows("q1_full_formal_batches.csv") if r["Scenario"] == "r0.20_a1.0_b1.0"]
    sensitivity = _rows("q1_full_sensitivity.csv")
    if not pareto or not sorties or len(sensitivity) != 27:
        raise ValueError("Missing formal baseline Pareto, batches or sensitivity rows")

    name = "result_q1_pareto"; fig, ax = _new(name)
    scatter = ax.scatter([_num(r, "Energy (kWh)") for r in pareto],
                         [_num(r, "Operation Time (s)") for r in pareto],
                         c=[_num(r, "Sorties") for r in pareto], cmap="viridis", s=26)
    fig.colorbar(scatter, ax=ax, label="Sorties (count)")
    ax.set(xlabel="Total energy (kWh)", ylabel="Cumulative operation time (s)")
    _export(fig, name)

    name = "result_q1_batch_load"; fig, ax = _new(name)
    model_colors = {"A": BLUE, "B": ORANGE, "C": GREEN}
    for model, color in model_colors.items():
        subset = [r for r in sorties if r["Model ID"] == model]
        ax.scatter([_num(r, "Total Mass (kg)") for r in subset],
                   [_num(r, "Return SOC (%)") for r in subset],
                   s=22, color=color, label=f"Model {model}")
    ax.set(xlabel="Sortie payload (kg)", ylabel="Return SOC (%)")
    ax.legend(frameon=False)
    _export(fig, name)

    name = "result_q1_sensitivity"; fig, ax = _new(name)
    for rho, color in ((.2, BLUE), (.3, ORANGE), (.4, GREEN)):
        subset = [r for r in sensitivity if abs(float(r["Scenario"].split("_")[0][1:]) - rho) < 1e-8]
        ax.scatter([_num(r, "Delta energy (kWh)") for r in subset],
                   [_num(r, "Delta sorties") for r in subset], color=color, s=25,
                   label=f"rho={rho:.1f}")
    ax.axvline(0, lw=.7, color=INK, ls="--")
    ax.set(xlabel="Change in total energy vs baseline (kWh)", ylabel="Change in sorties (count)")
    ax.legend(frameon=False)
    _export(fig, name)


def flow_figure() -> None:
    for question in range(1, 5):
        if not (ROOT / "analysis" / "problems" / f"Q{question}.md").exists():
            raise FileNotFoundError(f"Q{question} model document missing")
    if not (ROOT / "src" / "models" / "q1_full.py").exists():
        raise FileNotFoundError("Q1 implementation missing")
    name = "flow_overall_model"
    fig, ax = _new(name)
    ax.set(xlim=(0, 10), ylim=(-.9, 7))
    ax.axis("off")
    nodes = [
        ("Inputs", "Annex workbooks + DEM", 5, 6.2, BLUE),
        ("Q1 implemented", "Capacity, batching, epsilon", 5, 5.15, GREEN),
        ("Q2 model", "Transport scheduling", 5, 4.1, "#8A8A8A"),
        ("Q3 model", "Relay + transport joint plan", 5, 3.05, "#8A8A8A"),
        ("Q4 model", "Fixed-plan resource groups", 5, 2.0, "#8A8A8A"),
        ("Validation", "Physical / timing / communication / inventory", 5, .95, ORANGE),
        ("Outputs", "Tables, evidence, paper draft", 5, -.1, BLUE),
    ]
    for title, subtitle, x, y, color in nodes:
        ax.add_patch(FancyBboxPatch((x - 2.5, y - .35), 5., .78, boxstyle="round,pad=.08",
                                    fc="white", ec=color, lw=1.15))
        ax.text(x, y + .12, title, ha="center", va="center", fontsize=9, color=INK, weight="bold")
        ax.text(x, y - .16, subtitle, ha="center", va="center", fontsize=7, color=INK)
    for a, b in zip(nodes, nodes[1:]):
        ax.add_patch(FancyArrowPatch((5, a[3] - .45), (5, b[3] + .52),
                                     arrowstyle="-|>", mutation_scale=9, lw=.9, color=INK))
    ax.text(.1, -.72, "Q2-Q4: documented models; numerical implementations pending", fontsize=7, color="#666666")
    _export(fig, name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Q1 report-CSV figures and documented overall model flow")
    parser.add_argument("--flow-only", action="store_true")
    parser.add_argument("--check-only", action="store_true", help="validate source rows without rendering")
    args = parser.parse_args()
    _style()
    if args.check_only:
        if len(_rows("q1_full_input_boxes.csv")) != 80 or len(_rows("q1_full_input_areas.csv")) != 15:
            raise ValueError("Input-audit CSV row count mismatch")
        print(json.dumps({"raw_boxes": 80, "areas": 15, "figure_contracts": len(CONTRACTS)}))
        return
    if not args.flow_only:
        envelope = json.loads(REPORT_STATUS.read_text(encoding="utf-8"))
        if envelope["payload"].get("status") != "all_27_formal_sampled":
            raise ValueError("Q1 result figures require a validated 27-scenario report")
    FIGURES.mkdir(parents=True, exist_ok=True)
    flow_figure()
    if not args.flow_only:
        raw_figures(); process_figures(); result_figures()
    contract_path = FIGURES / "q1_full_figure_contract.json"
    contract_path.write_text(json.dumps({key: {"claim": value[0], "evidence": value[1],
                                              "chart_type": value[2], "source": value[3],
                                              "size_inches": value[4], "backend": "Python Matplotlib",
                                              "formats": ["SVG", "PNG 300 DPI", "grayscale preview"]}
                                         for key, value in CONTRACTS.items()}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
