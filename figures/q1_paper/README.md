# Q1 Paper-Figure Gallery

English-language, single-column/course-paper figure set for the Q1 analysis.
Each figure is available as a 600-dpi PNG preview, SVG, and PDF. Grayscale PNGs
are included as print-safety previews. Full captions, source data, and caveats
are documented in [FIGURE_CAPTIONS_EN.md](FIGURE_CAPTIONS_EN.md).

| Figure | Preview (PNG) | SVG | PDF |
|---|---|---|---|
| 01 · Cargo-mass profile | [PNG](q1_fig01_mass_profile.png) | [SVG](q1_fig01_mass_profile.svg) | [PDF](q1_fig01_mass_profile.pdf) |
| 02 · Cargo mass–volume profile | [PNG](q1_fig02_mass_volume.png) | [SVG](q1_fig02_mass_volume.svg) | [PDF](q1_fig02_mass_volume.pdf) |
| 03 · Service-area demand | [PNG](q1_fig03_area_demand.png) | [SVG](q1_fig03_area_demand.svg) | [PDF](q1_fig03_area_demand.pdf) |
| 04 · Candidate reduction | [PNG](q1_fig04_candidate_reduction.png) | [SVG](q1_fig04_candidate_reduction.svg) | [PDF](q1_fig04_candidate_reduction.pdf) |
| 05 · Epsilon-grid certification | [PNG](q1_fig05_epsilon_certification.png) | [SVG](q1_fig05_epsilon_certification.svg) | [PDF](q1_fig05_epsilon_certification.pdf) |
| 06 · Pareto-front cardinality | [PNG](q1_fig06_frontier_cardinality.png) | [SVG](q1_fig06_frontier_cardinality.svg) | [PDF](q1_fig06_frontier_cardinality.pdf) |
| 07 · Safe-payload capacity | [PNG](q1_fig07_capacity_envelope.png) | [SVG](q1_fig07_capacity_envelope.svg) | [PDF](q1_fig07_capacity_envelope.pdf) |
| 08 · Baseline Pareto trade-offs | [PNG](q1_fig08_baseline_pareto.png) | [SVG](q1_fig08_baseline_pareto.svg) | [PDF](q1_fig08_baseline_pareto.pdf) |
| 09 · Representative sortie manifest | [PNG](q1_fig09_sortie_manifest.png) | [SVG](q1_fig09_sortie_manifest.svg) | [PDF](q1_fig09_sortie_manifest.pdf) |
| 10 · Energy sensitivity | [PNG](q1_fig10_energy_sensitivity.png) | [SVG](q1_fig10_energy_sensitivity.svg) | [PDF](q1_fig10_energy_sensitivity.pdf) |

## Reproduction

From the repository root, run:

```powershell
uv run --locked python -m src.visualization.q1_paper_figures
```

The generator reads the existing `results/tables/q1_full_*.csv` exports and
does not run or modify the optimization experiments.
