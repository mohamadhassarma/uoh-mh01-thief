# PRD-05 - Strategy Brain and Verbal Layer

## Problem statement — the belief ceiling stage 4 measured, not a design choice

PRD-04's `scripts/belief_transcript_demo.py`, run at the real signed
contract values (`grid_size=7`, `survival_threshold=35`,
`pheromone_center_intensity=0.9`, `pheromone_decay=0.10`,
`pheromone_grid_size=5`) against a random-walk thief (seed 7), measured how
well the belief map's argmax cell actually tracks the true hidden position
it is built from:

```
argmax within 1 cell of truth (Manhattan): 16/35 (45.7%)
argmax within 2 cells of truth (Manhattan): 27/35 (77.1%)
```

Peak belief probability itself stabilizes around 0.32–0.35 once the thief
has lingered in one region long enough for its own trail to accumulate —
it does not climb toward 1.0, and the argmax is sometimes several cells
from the truth even after many turns (turn 10: argmax `(3,4)`, true cell
`(0,4)`, `p(true_cell) = 0.0053`). **This is correct behaviour for a
decaying trail fed by a random walk, not a bug in PRD-04's belief map** —
see PRD-04's own float-determinism and vector-conformance sections for why
the underlying scent/decay math is not in question here. It is, however,
the actual operating constraint stage 5 has to design against, not an
incidental transcript footnote:

- **A police brain that simply chases the argmax is frequently chasing a
  stale trail.** Just over half the time (54.3%, by this baseline) the
  single most-likely cell is not even Manhattan-adjacent to where the
  thief actually is — a naive "walk toward argmax" policy inherits that
  error rate directly into its pursuit.
- **A thief brain can exploit the same measurement.** Because peak belief
  sharpens specifically where the thief lingers, a thief that periodically
  breaks its own trail (moves unpredictably, doubles back, or leaves a
  region before its local scent saturates) can suppress the 45.7%/77.1%
  figures further — pure distance-maximising from the police's last known
  cell is not necessarily the thief's best response; deliberately
  degrading the police's belief accuracy may be worth more.
- **This baseline is what stage 5 needs to beat, not a target to match.**
  Any police strategy claiming to "use the belief map well" should be
  measured against 45.7% (within 1) / 77.1% (within 2) on the same
  transcript setup — an improvement means genuinely extracting more signal
  from the scent field (e.g. weighting recent deposits over stale ones,
  tracking the trail's direction of travel rather than only its peak, or
  combining belief with the distance heuristics from book ch.6.4), not
  just re-running the same measurement and reporting a different seed.

These numbers are from a single seeded run (one sub-game, one random-walk
thief) — a real baseline, not a statistically tight one; stage 5 may want
to average over more seeds/strategies before treating 45.7%/77.1% as the
number to beat precisely, but the qualitative ceiling (peak belief
saturating well under 1.0, argmax frequently wrong by more than one cell)
is the load-bearing finding, and it will not disappear with more samples.

## Goal
> TODO

## In scope
> TODO

## Out of scope
> TODO

## Acceptance criteria
- [ ] TODO

## Depends on
> TODO