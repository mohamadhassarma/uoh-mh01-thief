# PLAN ג€” Development Plan (Thief agent)

Development follows the seven-stage priority ladder from Ch. 10.3 of the rulebook.
Each stage gets its own PRD file, is built and tested in isolation, and is verified
end-to-end before the next stage is added. This keeps the failure surface at any
moment confined to the most recently added layer.

| # | Stage | PRD | Status |
|---|-------|-----|--------|
| 1 | Base game logic (single process, local board) | `prd/PRD-01-base-logic.md` | Not started |
| 2 | Basic FastMCP infrastructure over localhost | `prd/PRD-02-mcp-infra.md` | Not started |
| 3 | Commit-Reveal integrity (SHA-256) + audit log | `prd/PRD-03-commit-reveal.md` | Not started |
| 4 | Pheromones, scent field, belief map | `prd/PRD-04-belief.md` | Not started |
| 5 | Strategy brain + verbal layer (LLM) | `prd/PRD-05-strategy.md` | Not started |
| 6 | GUI + Replay viewer | `prd/PRD-06-gui-replay.md` | Not started |
| 7 | Public tunnel, Gatekeeper, Gmail reporting | `prd/PRD-07-live-league.md` | Not started |

## Definition of done per stage

A stage is done when: its PRD acceptance criteria all pass, `pytest` is green,
and the full system still runs end-to-end from the previous stages.