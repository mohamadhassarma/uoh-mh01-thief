# PRD-01 ג€” Base Game Logic

## Goal
The physical core of the game, running in a **single process**, with no networking
and no intelligence. If two agents cannot move correctly on a local board, there is
no reason to connect them over a network.

## In scope
- Grid of size `grid_size` (default 7x7), index-0, origin top-left.
- Move set: N, S, E, W, STAY. Orthogonal only.
- Barrier placement by the police agent, up to `max_barriers`.
- Capture by coordinate overlap.
- Trapped thief (no legal move available) counts as captured.
- Barrier placed on the thief's own cell counts as capture in that same moment.
- Scoring per the scoring table.

## Out of scope (later stages)
FastMCP, Commit-Reveal, pheromones, belief map, LLM, GUI, tunnelling, Gmail.

## Acceptance criteria
- [ ] A full match runs to a terminal state without crashing.
- [ ] Every diagonal move attempt is rejected as illegal.
- [ ] A barrier is irreversible for the rest of the match.
- [ ] All four end conditions produce the correct score pair.
- [ ] All numeric values are read from `config/game.json` ג€” no hard-coded numbers.
- [ ] `pytest` is green.

## Notes
`config/game.json` is the single source of truth for every quantitative value.
Minimums may be raised by mutual agreement, never lowered.