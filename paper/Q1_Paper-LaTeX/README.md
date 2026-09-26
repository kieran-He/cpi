# Q1 Simulation Paper (LaTeX)

This is the Q1 body segment of a larger simulated, combined mathematical-modeling manuscript. It is not an official contest submission. For fidelity to the supplied template, the cover retains the Huawei Cup name and contest logos; university, team number, and team-member fields remain blank because no team identity was provided. The template's university-specific seal is omitted to avoid implying an affiliation. The source skeleton was adapted only in this project copy; the root template remains unchanged. The abstract, keywords, overall introduction, and overall conclusion are intentionally deferred until Q2–Q4 are integrated.

## Files

- `HuaweiCup23_LaTeX_Template.tex` — current Q1 section source and build entry point, including the retained simulation cover.
- `figs/` — PDF figures embedded in the manuscript.
- `latex-project.json` — template provenance and hash bindings for the included figures.
- `build/` — generated LaTeX build artifacts.

Figure masters remain under `../figures/Q1_Paper/`, copied from the repository's `figures/q1_paper/` outputs. The source model, data, and computational validation remain in the repository-level `src/`, `results/`, and `analysis/` directories.

Build with the math-modeling LaTeX helper and XeLaTeX. The current artifact is a partial manuscript, so full-paper checks for abstract, keywords, and all-question coverage are deferred. Numerical results are conditional on the energy convention stated in the manuscript.
