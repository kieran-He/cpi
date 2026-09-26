# Q1 Paper Figures (English)

Course-paper figure set sized for near-full text width. All chart text, filenames, and captions are in English.
Every data figure is exported as editable-text SVG and PDF, 600-dpi PNG, and grayscale PNG.
The charts use the complete exported records described in each caption; no observations are dropped.

## Figure captions

### Raw inputs

**Fig01 Mass Profile.** Frequency distribution of the 80 original cargo-box masses. Mass is discrete in the supplied data; points report exact counts rather than a fitted continuous density. Descriptive data only; no uncertainty intervals or inferential tests are applicable. Source: q1_full_input_boxes.csv.

**Fig02 Mass Volume.** Mass-volume pairs for all 80 cargo boxes, with marker and color identifying cargo class. No jitter or smoothing is applied, so plotted coordinates remain the supplied values. Descriptive data only; no inferential fit is implied. Source: q1_full_input_boxes.csv.

**Fig03 Area Demand.** Exact number of cargo boxes assigned to each of the 15 service areas, ordered by demand. Each dot is one area; labels give exact counts. No uncertainty interval is applicable. Source: q1_full_input_areas.csv.

### Modeling and proof process

**Fig04 Candidate Reduction.** Candidate counts through the three enumeration stages for 27 parameter scenarios. Thin lines are individual scenarios; the dark line is the median and the shaded band is the empirical 25th-75th percentile range across scenarios (not a confidence interval). The vertical axis is log-scaled. Source: q1_full_scenario_status.csv.

**Fig05 Epsilon Certification.** Counts of epsilon-grid records certified feasible or infeasible by the exact subset Pareto DP, grouped by primary objective and pooled over 18 globally feasible parameter scenarios. The nine globally infeasible scenarios are excluded from this epsilon-grid summary. These are exact optimization certificates, not sampled observations. Source: q1_full_epsilon_status.csv.

**Fig06 Frontier Cardinality.** Cardinality of the complete exact nondominated objective set for each (alpha, beta) combination, faceted by return reserve rho. Gray cells marked X are scenarios proven globally infeasible; integer annotations are exact front sizes. Source: q1_full_pareto_sample.csv and q1_full_scenario_status.csv.

### Optimization results

**Fig07 Capacity Envelope.** Maximum safe payload (kg) for each aircraft model and service area under the baseline parameter setting (rho=0.20, alpha=1.0, beta=1.0). Cell annotations are exact computed capacities; color encodes the same quantity. Source: q1_full_baseline_capacity.csv.

**Fig08 Baseline Pareto.** Pairwise projections of every distinct objective vector on the complete baseline Pareto front. The star denotes the selected balanced representative; the diamond denotes the minimum-energy endpoint. Points are deterministic optimization plans, not replicates; no error bars or statistical tests apply. Source: q1_full_pareto_sample.csv and q1_full_formal_batches.csv.

**Fig09 Sortie Manifest.** Mass composition by cargo class for each of the 18 sorties in the baseline representative plan. Stack segments sum to the exact sortie payload; all 80 boxes are assigned once. No uncertainty interval is applicable. Source: q1_full_baseline_batches.csv and q1_full_input_boxes.csv.

**Fig10 Energy Sensitivity.** Change in representative total energy relative to the baseline plan across the full parameter grid, faceted by return reserve rho. Each feasible tile shows the exact energy difference in kWh; gray X tiles are scenarios proven globally infeasible. No statistical uncertainty is implied. Source: q1_full_sensitivity.csv.

## Source-data profile
- 80 cargo boxes; mass takes four discrete values (3, 6, 8, and 14 kg).
- Box volume spans 0.012–0.035 m³; every mass-volume pair is shown without jitter.
- 15 service areas; box counts range from 3 to 15, so all area-level observations are plotted directly.
- 18 baseline sorties; the sortie manifest reconciles class-specific mass to sortie payload and confirms each of the 80 box IDs appears exactly once.
- The baseline exact Pareto set contains two distinct objective vectors; these are deterministic plans, not repeated trials.
- The 27 sensitivity scenarios contain 18 feasible exact fronts and 9 proven-infeasible cases.

## Reproduction
Run `uv run --locked python -m src.visualization.q1_paper_figures` from the repository root.
The script reads `results/tables/q1_full_*.csv`; it does not modify source data or solve the optimization model.
