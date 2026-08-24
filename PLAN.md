# PLAN — Development Plan (Thief agent)

Development follows the seven-stage priority ladder from Ch. 10.3 of the rulebook.
Each stage gets its own PRD file, is built and tested in isolation, and is verified
end-to-end before the next stage is added. This keeps the failure surface at any
moment confined to the most recently added layer.

| # | Stage | PRD | Status |
|---|-------|-----|--------|
| 1 | Base game logic (single process, local board) | `prd/PRD-01-base-logic.md` | Done |
| 2 | Basic FastMCP infrastructure over localhost | `prd/PRD-02-mcp-infra.md` | Done |
| 3 | Commit-Reveal integrity (SHA-256) + audit log | `prd/PRD-03-commit-reveal.md` | Done |
| 4 | Pheromones, scent field, belief map | `prd/PRD-04-belief.md` | Done |
| 5 | Strategy brain + verbal layer | `prd/PRD-05-strategy.md` | Done |
| 6 | GUI + Replay viewer | `prd/PRD-06-gui-replay.md` | Done |
| 7 | Public tunnel, Gatekeeper, Gmail reporting | `prd/PRD-07-live-league.md` | Done |

All seven stages are implemented, committed, and have been exercised against
real opponents in live series - not only against our own two peers.

Two caveats recorded rather than smoothed over:

- **Stage 5's "verbal layer" is deliberately not an LLM.** Hints are
  template-generated and cost zero tokens (`domain/hints.py`, PRD-05 section
  C). Being template-based is what makes a hint *decodable* by the receiver,
  which is what lets `belief.apply_hint` be called with a real claim instead
  of remaining a theoretical hook. This was a decision, not an omission.
- **PRD-03 and PRD-07 still have unticked acceptance-criteria boxes** even
  though the work behind them is done and in production use. By the
  definition below, that is the paperwork lagging the code; the boxes should
  be walked through and ticked before submission.

## Definition of done per stage

A stage is done when: its PRD acceptance criteria all pass, `pytest` is green,
and the full system still runs end-to-end from the previous stages.

## Revision (Stage 2 corrections — protocol intake)

Two external sources were studied against the ladder above: the official
reference implementation ([`rmisegal/Game-P2P-Cop-Chase`](https://github.com/rmisegal/Game-P2P-Cop-Chase),
code v3.0.0) and the student interop kit ([`Imreec/copthief-league-protocol`](https://github.com/Imreec/copthief-league-protocol)).
Both surfaced real machinery this ladder had not yet placed anywhere. Rather
than adding new stages (the seven-stage ladder is the rulebook's own
structure — see Ch. 10.3 — and is not ours to renumber), each new item is
folded into the *existing* stage whose PRD already owns the closest concern.
That placement is a judgment call, recorded here so it can be revisited:

| New item | Lands in | Why here, not elsewhere |
|---|---|---|
| Pre-game handshake: mutual SHA-256 signatures over the shared terms, `game_id`/`game_uid` derivation, refuse-on-mismatch | Stage 3 (PRD-03) | Same SHA-256 machinery as commit-reveal itself; nothing before this point needs it, and stage 4+ all assume it already happened |
| Step-0 sealed declaration: host hardware (CPU/RAM/GPU/OS) + this build's commit hash | Stage 3 (PRD-03) | It is itself a sealed record under the same commit-reveal scheme, sent before the first real move |
| Real per-step commit-reveal (replacing stage 2's unhashed placeholder) | Stage 3 (PRD-03) | This is literally what PRD-03 was always for |
| Terminal-condition declare/confirm exchange for a capture only the thief can observe (rule 46/47 entrapment) | Stage 2 (PRD-02), retrofitted | Already needed at stage 2's protocol layer, independent of any cryptography — see "Stage 2 corrections" below and the interop kit's §3.1/§5c. Not deferred to stage 3, because stage 2's own zero-trust design was already broken without it |
| `num_games = 6` sub-game series with role alternation (odd sub-games natural role, even sub-games swapped) | Stage 3 (PRD-03) | The series loop and the per-sub-game sealed log are one unit of work — running the existing single-match loop N times with a role swap between them |
| `declaration_<game_id>.json` (once per series) and `config_<game_id>_gNN.json` / `log_<game_id>_gNN.json` (once per sub-game) | Stage 3 (PRD-03) | These are the declaration/config/log halves of the four-artifact set — direct outputs of the handshake and the sealed per-step log this stage already owns |
| `result_<game_id>.json` (aggregated series result), its consensus signature, the diversity reward, and league standings fields | Stage 7 (PRD-07) | This is league *reporting*, not gameplay integrity — it depends on a finished, audited series existing first, and PRD-07 already owns Gmail reporting |
| Friendlies-before-counted-game discipline; the counted-games ledger | Stage 7 (PRD-07) | Same reasoning: this governs when a report is sent and to whom, which is PRD-07's territory |

No stage was renumbered and no stage's original scope shrank — this table
only says which PRD documents which new piece, so nothing gets built twice
or built nowhere.

`config/game.json`'s `network_and_league.num_games` has been changed from the
scaffold's demo value `1` to the book-mandated `6`, effective immediately
(it is a signed value, not stage-gated) — see TODO.md "Blocked / needs
negotiation": this must still be re-agreed byte-for-byte with any opponent
group before a real series.

## Role alternation — the engineering answer (stage 3, PRD-03)

TODO.md's open question about role alternation had two genuinely separate
parts that were conflated in early planning; stage 3 answers one of them
concretely and leaves the other open:

- **How role alternation works mechanically, once a series is running** —
  now implemented and stress-tested (`infra/series.py::run_series`): ONE
  long-lived process (`SeriesRuntime`, one FastMCP server for the whole
  series) plays all `num_games` sub-games back to back, with `PeerRuntime`
  constructed fresh per sub-game and handed `natural_role` on odd sub-games
  / the swapped role on even ones. This is settled engineering, not a
  negotiation item — it is purely how *this repo's own process* behaves
  once launched.
- **Which of our two repos (police, thief) is the thing that actually gets
  launched for a given sub-game, in a real counted series against another
  group** — still genuinely open, and still belongs to the professor, not a
  guess. See TODO.md "Open questions for the professor" — the interop kit's
  own completed-campaign playbook assumes a single codebase that can play
  either role via a flag, which does not map cleanly onto this course's
  mandatory two-separate-repos submission structure. Stage 3 does not
  resolve this; it only means that *whichever* repo/process is chosen for a
  given sub-game, that process's own role-alternation behavior across the
  series it plays is now implemented and correct.
