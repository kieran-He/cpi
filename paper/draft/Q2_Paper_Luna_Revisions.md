# Q2 paper revision log

Applied the independent editorial and evidence review to the Q2 fragment and synchronized Q1+Q2 manuscript.

- Paired the initial-pool model and stop-count plots side by side; redrew them at the matching half-page size with 7–8 pt labels. Resized the other Q2 plots and workflow to the reviewed page proportions.
- Corrected repeated-area route-map export to attach cargo IDs by stop sequence and raise on mismatched stop order. Regenerated the baseline, 25-sortie endpoint, and 24-sortie schedule route maps; refreshed the equivalent K=400 copy.
- Audited all route-map stops against the stored route records and delivery CSVs: 39, 25, 24, and 24 sorties passed; the two K=400 exports each preserve the single repeated-area visit. Q2-003 now shows S011-FOD-01 at its first S011 stop and S011-WAT-01 at its second.
- Corrected schedule/map captions to cite `resource_timeline.csv` and `sorties.csv`; clarified that the map plots all selected legs and overlapping lines do not identify route order. The workflow now shows deadline-directed enrichment and tabu-guided VNS. The archive caption states that its 2D projection encodes energy and omits sortie count. The comparison caption gives both lexicographic orders.
- Preserved Q1's `\mathcal P` notation and Q2's `\mathcal R`, all pool and heuristic limits, and existing Q1 section text. Kept Q2 limitations and the reproducibility note together.
- Converted the paired route-pool panels to standard `subcaption` subfigures so each chart has a recognized subfigure caption; captions are ragged-right to avoid underfull-box warnings while retaining the side-by-side layout.

## Build and visual review

- XeLaTeX build and publish succeeded with no warnings or issues; the combined manuscript is 21 pages. The published artifact is `paper/Q1_Q2_Paper.pdf` and its build manifest is `paper/Q1_Q2_Paper.build.json`.
- Rendered and visually inspected PDF pages 12, 18, and 19, adjacent Q2 workflow/route-pool pages, and the final limitations/reproducibility page. The pool charts are legible at paired size, affected pages contain no clipped figures or split limitations/reproducibility block, and the cited page gaps are reduced by the resized/grouped figures.
- Validation with `--contest generic --questions q1 q2` confirmed 21 A4 pages, no blank pages, all fonts embedded, and figure coverage for both questions. It still reports three issues: missing abstract environment, missing keywords command, and minimum embedded bitmap resolution of 116 DPI (below the validator's 300 DPI threshold). These were reported without modifying Q1 content or other manuscript content.
