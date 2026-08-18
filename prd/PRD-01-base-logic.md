# PRD-01 — Base Game Logic

## Goal

Build the physical core of the Police/Thief pursuit game as a single-process,
single-machine engine, with no networking, no cryptographic verification, and
no intelligence beyond a placeholder move-picker. The rulebook's rationale for
starting here: if two agents cannot move correctly on a local board, there is
no reason to connect them over a network. This engine is shared, byte-for-byte
logic — both the police and thief repos run the identical package so that a
match is deterministic and replayable, and neither side can quietly diverge
from the other's understanding of the rules.

## In scope

- A square grid of side `grid_size`, 0-indexed, origin at the top-left
  corner, row increasing downward — exactly as `config/game.json` declares
  under `axis_origin_corner` / `axis_start_index`.
- The five-move set `N, S, E, W, STAY`, orthogonal only.
- Barrier placement by the police, on its own cell or an orthogonal
  neighbour, up to `max_barriers`, irreversible once placed.
- Capture detection by coordinate overlap (see "Open questions" for exactly
  how this is scoped).
- Capture by barrier landing on the thief's cell.
- Capture by entrapment (thief surrounded on all four orthogonal sides).
- Survival scoring once the thief has survived `survival_threshold` of its
  own valid steps.
- A match-length ceiling, `max_moves`, enforced as an independent counter
  from `survival_threshold` (see "Open questions" — these are two distinct
  mandatory parameters that happen to share a default value, not the same
  parameter under two names).
- Technical loss on an illegal move or illegal barrier placement.
- Every quantitative value read from `config/game.json` at load time through
  a single validated, typed, frozen config object — never hard-coded.
- A deterministic move log sufficient to reconstruct a match (a prerequisite
  for stage 6's replay viewer).
- A placeholder move-selection function (first-legal or uniformly-random
  among legal actions) purely so a full match can be played end-to-end today.
  This is explicitly **not** the strategy brain — that is stage 5 (PRD-05).

## Out of scope (later stages)

FastMCP / networking (stage 2), Commit-Reveal / SHA-256 verification and the
audit log (stage 3), pheromones / scent field / belief map (stage 4), the real
strategy brain and the LLM trash-talk layer (stage 5), GUI and replay viewer
(stage 6), public tunnel / Gatekeeper / Gmail reporting (stage 7).

## Data model

- **Position** — a `(row, col)` pair.
- **Board** — `grid_size` plus an immutable set of barrier cells. Placing a
  barrier returns a *new* Board; nothing ever removes a barrier.
- **GameConfig** — a frozen, validated view of `config/game.json`, split into
  `BoardConfig`, `MovementConfig`, `ScoringConfig`. This is the only place
  that ever reads the raw JSON.
- **MatchState** — immutable: board, both agents' positions, whose turn it
  is, the round counter, barriers placed so far, the thief's own survived-step
  counter, each side's own action counter (for the per-player `max_moves`
  ceiling), and the move log.
  Every action (`apply_move`, `apply_barrier`) takes a `MatchState` and
  returns a *new* one plus one appended `LogEntry` — nothing is mutated in
  place. This is what makes deterministic replay-from-log possible later:
  replay is just folding the same two reducers over a saved log, starting
  from the same initial state.
- **TerminalCondition** — `capture_landing`, `capture_barrier`,
  `capture_entrapment`, `survival`, `technical_loss`, `tie`. Scoring maps each
  of these to a `(police_score, thief_score)` pair from `ScoringConfig`.

## Terminal conditions

1. **Capture by landing** — the two agents' coordinates coincide after a move.
   Scores `capture_cop` / `capture_thief`.
2. **Capture by barrier** — a barrier is placed exactly on the thief's current
   cell. Same scoring, in the same moment.
3. **Capture by entrapment** — at the start of the thief's turn, all four of
   its orthogonal neighbours are off-board or barriers. The thief never gets
   to act that turn. Same scoring. STAY is deliberately not treated as an
   escape from entrapment — see "Open questions".
4. **Survival** — the thief completes `survival_threshold` of its *own*
   valid steps without ever being captured. Scores `survival_cop` /
   `survival_thief`.
5. **Technical loss** — either side attempts an illegal move or an illegal
   barrier placement. Both sides score `technical_loss` (`TODO.md` is
   explicit that this is a `0/0` pair, not just zero for the offending side).
6. **Tie** — `tie_score` is implemented as a reachable, scoreable terminal
   condition, but nothing in the engine ever triggers it. See "Open
   questions" — this was a deliberate choice, not an oversight.

There is also a seventh, *unscoreable* outcome: if the match-length ceiling
`max_moves` is reached without any of the above having fired, the engine
raises `UndefinedOutcomeError` instead of guessing a score. See "Open
questions" below.

## Acceptance criteria

- [x] A full match runs to a terminal state without crashing (`pytest`, and
      `python -m uoh_mh01 selftest`).
- [x] Every diagonal move attempt is rejected — enforced structurally: the
      `Direction` type has exactly five members and cannot represent a
      diagonal at all.
- [x] A barrier is irreversible for the rest of the match (`Board` has no
      remove operation; covered by `test_barrier_placement_is_irreversible`).
- [x] All terminal conditions produce the correct score pair
      (`test_scoring.py`, plus end-to-end checks in `test_match.py`).
- [x] All numeric game values are read from `config/game.json` — no
      hard-coded numbers (enforced by `test_no_magic_numbers.py`'s static
      AST check over the domain package).
- [x] `pytest` is green (74/74).

## Open questions

These are genuine rulebook gaps. Each was raised with the group lead before
implementation and resolved with an explicit, provisional decision — not
guessed silently. All are on the agenda for opponent-group negotiation before
`config/game.json` is finalised.

1. **Turn order.** The rulebook does not say who moves first. Implemented as
   one named constant, `match.FIRST_MOVER = Side.POLICE`, not scattered
   through the code, explicitly marked provisional.

2. **`max_moves` vs. `survival_threshold`.** These are two independent
   mandatory parameters (Appendix F: `max_moves` is a "step ceiling," a
   *minimum*; `survival_threshold` is "steps the thief must survive," also a
   *minimum*). They currently share the same default value (35), which reads
   as redundant but is not — an opponent group could raise one without the
   other. Implemented as two independent counters: `thief_survived_steps`
   (increments only on the thief's own uncaptured moves) and, per side,
   `police_actions_taken` / `thief_actions_taken`.

   The **counting basis** for `max_moves` — combined actions by both sides,
   vs. actions per player — is not defined in the rulebook either.

   **This started as a combined-actions reading, and empirical testing forced
   a correction.** Under "combined actions by both sides" (each side's move or
   barrier placement counted against one shared total), the real
   `config/game.json` values (`max_moves=35`, `survival_threshold=35`) put the
   ceiling at roughly 17–18 rounds — well under half of the ~35 rounds the
   thief needs to accumulate 35 of its *own* survived steps. Under placeholder
   random self-play, **9 of 11 seeds tried hit the `max_moves` ceiling before
   any other terminal condition could fire** (`UndefinedOutcomeError`, not a
   score). That is not a corner case; it means the `survival_cop` (5) and
   `survival_thief` (10) rows of the mandatory scoring table were dead —
   structurally unscoreable in any match played under the default contract
   values. An interpretation of an ambiguous rule that renders a mandatory
   scoring row unreachable is the wrong interpretation, so this was corrected
   rather than left as the initial provisional default.

   The engine now reads `max_moves` as **per-player**: each side has its own
   independent budget of `max_moves` actions (`match.MAX_MOVES_COUNTING_BASIS`).
   The ceiling is checked at the *start* of each side's turn, against that
   side's own action count so far — not after every action against a shared
   total — which is what makes it possible for the ceiling and
   `survival_threshold` to coincide exactly rather than one firing a half-round
   ahead of the other. At the contract's default values (`max_moves=35`,
   `survival_threshold=35`, police moving first), the thief takes its 35th
   action in the same round police is about to take its 36th — the survival
   check (which runs immediately after the thief's move, before the next
   turn's ceiling check) fires first, so `SURVIVAL` is reached and
   `UndefinedOutcomeError` never triggers at these defaults. It becomes
   reachable again only if the two parameters are ever negotiated apart (e.g.
   `max_moves` raised without `survival_threshold`, or vice versa) — which is
   exactly the scenario clause 3 below still needs to handle without guessing.

   This is still flagged as **provisional and negotiable**, not settled — an
   opponent group could reasonably argue for the combined-actions reading
   instead. But between the two, per-player is the one that doesn't
   contradict the signed scoring contract, so it is the default this engine
   ships with. See `test_max_moves_...` in `tests/test_match.py` for the
   regression coverage.

3. **What happens when `max_moves` is reached with nothing else having
   fired.** Not defined anywhere in the rulebook. The engine deliberately does
   **not** resolve this to a tie, a technical loss, or anything else — it
   raises `UndefinedOutcomeError` with a message pointing back here. This is
   intentional: a made-up trigger would silently poison the scoring table.
   The CLI (`selftest`) surfaces this distinctly from a crash.

   With the per-player counting basis from clause 2 above, this error is
   **structurally unreachable at the contract's current default values** —
   `SURVIVAL` fires first, every time, because the two thresholds coincide.
   It becomes reachable again only if `max_moves` and `survival_threshold`
   are ever negotiated to different values. That dependency is itself a
   reason clause 2's counting-basis choice belongs on the opponent
   negotiation agenda, not just a footnote: whichever side proposes changing
   one of these two numbers needs to understand it can silently resurrect
   this code path.

4. **Capture symmetry.** Rule text literally describes only "the police lands
   on the thief's cell." The PRD/TODO stubs more generically say "capture by
   coordinate overlap." Resolved as: **any** coordinate overlap after either
   side's move is a capture, regardless of who moved onto whom — otherwise a
   legal, permanent same-cell state would exist that no later stage (belief
   map, replay, audit log) could sensibly model. This is an engineering
   judgement call, not a rulebook requirement, and is flagged as provisional.

   A secondary distinction was preserved deliberately: capture *detection*
   (`rules.is_capture_state`, symmetric, pure) is kept separate from a
   capture *claim* (`LogEntry.capture_claimed_by_police`, set only when the
   police's own move or barrier produced the overlap). The rulebook's
   Commit-Reveal mechanism (stage 3) gives the police — and only the police —
   a cryptographic duty to truthfully claim a capture; there is no equivalent
   mechanism for the thief. Collapsing detection and claim into one concept
   now would make stage 3 harder to build correctly later.

5. **Entrapment vs. STAY.** STAY is always a legal move in isolation, which
   would make entrapment unreachable if it counted as an escape. Resolved by
   reading the entrapment rule as intentionally structural — "all
   orthogonally adjacent cells are barriers and/or board edges" — independent
   of whether STAY is separately legal. Not flagged as provisional; this
   reading is what the rule text already says, not a judgement call.

6. **Tie trigger.** `tie_score` exists in the scoring table with no defined
   trigger condition anywhere found in the rulebook excerpts available. Per
   explicit instruction, no trigger was invented. `scoring.score_for` can
   still produce a `(tie_score, tie_score)` pair on request
   (`test_tie_is_reachable_and_scores_the_tie_pair`), but nothing in
   `match.run_match` ever reaches it. Needs a rulebook citation or an
   opponent-negotiated house rule before stage 2.

7. **Axis orientation generality.** `axis_origin_corner` and
   `axis_start_index` are marked *negotiable* in the mandatory parameter
   table — the rulebook only requires both sides to agree on a value, not
   that the value be top-left/0. This is therefore not a rulebook gap at all;
   it is a stage-1 scope decision: the engine only *implements* the
   top-left/0 orientation so far, and rejects any other agreed value at
   config-load time. The rejection is deliberately framed as an **engine
   limitation** ("not yet implemented"), not a config validation failure
   ("invalid value") — `config.py`'s error messages say so explicitly, and
   `TODO.md`'s "Known limitations" section tracks it. If a future negotiated
   contract picks a different orientation, `config.py`'s validation and
   `board.py`'s move deltas both need revisiting together before that
   contract can run.
