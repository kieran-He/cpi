# Q1+Q2 Simulation Paper (LaTeX)

This is the Q1+Q2 body segment of a larger simulated, combined mathematical-modeling manuscript. It is not an official contest submission. For fidelity to the supplied template, the cover retains the Huawei Cup name and contest logos; university, team number, and team-member fields remain blank because no team identity was provided. The template's university-specific seal is omitted to avoid implying an affiliation. The source skeleton was adapted only in this project copy; the Q1 checkpoint and root template remain unchanged. The abstract, keywords, synthesis, and overall conclusion are intentionally deferred until Q3–Q4 are integrated.

## Files

- `HuaweiCup23_LaTeX_Template.tex` — Q1+Q2 section source and build entry point, including the retained simulation cover.
- `figs/` — PDF figures embedded in the manuscript.
- `latex-project.json` — template provenance and hash bindings for the included figures.
- `build/` — generated LaTeX build artifacts.

Q1 figure masters remain under `../figures/Q1_Paper/`; Q2 figure masters remain under `../figures/Q2_Paper/`, copied from the repository-level `figures/q2/` exports. The Q2 set contains 11 data plots, the Q2 workflow, and the overall question roadmap. The source model, data, and computational validation remain in the repository-level `src/`, `results/`, and `analysis/` directories.

Build with the math-modeling LaTeX helper and XeLaTeX. The current artifact is a partial manuscript, so full-paper checks for abstract, keywords, Q3–Q4 coverage, synthesis, and final conclusion are deferred. The Q2 recommendation is a validated heuristic result within the recorded candidate-route pool, not a global-optimality proof. Numerical results are conditional on the energy convention stated in the manuscript.
