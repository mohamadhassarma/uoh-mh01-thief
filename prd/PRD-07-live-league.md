# PRD-07 — Tunnel, Gatekeeper and Gmail Reporting

## Status

Not yet implemented. Promoted from stub to real PRD during the stage-2
corrections round, alongside PRD-03 — see PLAN.md "Revision (Stage 2
corrections)" for why the fourth standardized artifact (`result`), the
consensus signature, the diversity reward, and the friendlies-before-
counted-game discipline all land here rather than in PRD-03.

## Sources and their authority

Same three-source order as PRD-03: the book and its binding parameter
table win; the official reference
([`rmisegal/Game-P2P-Cop-Chase`](https://github.com/rmisegal/Game-P2P-Cop-Chase))
is second and read-only, never copied in; the student interop kit
([`Imreec/copthief-league-protocol`](https://github.com/Imreec/copthief-league-protocol))
is third, a conformance aid whose choices this project adopts as its own
documented decisions, not inherited authority.

## Goal

Make a played, audited series (PRD-03's output) reportable to the league:
tunnel this peer's MCP server publicly (ngrok or equivalent), rate-limit
outbound calls through a Gatekeeper, aggregate a series into the fourth
standardized artifact (`result_<game_id>.json`) with its own consensus
signature, and mail that result to the lecturer under the book's reporting
rules — but only for a genuinely counted, fully-settled series, never a
friendly and never a partially-failed one.

## In scope

- **`result_<game_id>.json`** — the aggregated series result: per-sub-game
  rows (`sub_game_number`, roles, result, winner, score, `github_commit`,
  `tokens`, per-sub-game audit outcome), and a `final_result` block
  (`total_score`, `sub_games_won`, `ties`, `winner_group`, `series_tie`,
  `tokens_total_series`). **Derived, never separately declared** — the
  totals must be the plain sum of the per-sub-game rows the two peers
  already agree on from PRD-03's audited sub-games; a second, independently
  computed total is a second source of truth that will eventually disagree
  with the first (interop kit SPEC §6).

- **The tie-rule contradiction — named and resolved, not silently picked.**
  The book and the reference genuinely disagree about where App. F's
  `tie_score` (2) lands on a tied series, and the interop kit documents
  three live behaviours in the wild:
  | Behaviour | Source | A 25–25 series totals |
  |---|---|---|
  | `series_add` | book's ch.9 *כלל התיקו* / App. F table 17 row 5, read literally ("accumulated score ... ends in a tie"), plus the interop kit's own documented choice | 27 / 27 |
  | `series_replace` | an alternative reading of the same book passage | 2 / 2 |
  | `per_subgame` | the reference implementation's own `emit.py` (its published sample result sums tied *rows* at 2/2 each, with no series-level adjustment at all) | 25 / 25, with each tied row separately paying 2 |

  **This project adopts `series_add`**, matching the interop kit's own
  documented choice, for the same reasons it gives: (1) App. E rule 35
  charges *both* teams for a contradictory report, so holding a reading
  alone risks an innocent opponent, and every league implementation the kit
  observed sums additively; (2) the alternative ordering argument — a
  fought 25–25 series paying only 2 while a single narrow 20–5 win pays 20
  would rank one clean win above six hard-fought draws, which inverts what
  the tie rule is plainly for. **This must still be declared to any
  opponent before the first counted window** (the interop kit's own
  observation: this contradiction is invisible in testing and in most
  series, and surfaces exactly once — the one time a real series ties).

- **The consensus signature — a second, different serialization.** Unlike
  every per-step commit in PRD-03 (compact form, `separators=(",", ":")`),
  the `result`'s `mutual_agreement.sha256` uses `sort_keys=True,
  ensure_ascii=False` with **default (spaced) separators**, and is computed
  **before** the signature field itself is inserted (sign-then-insert) —
  verification means: pop the signature key, re-serialize with the spaced
  form, re-hash, compare. This is a real, separate construction from
  PRD-03's — the interop kit is explicit that this is the release's fourth
  distinct serialization variant (after the three competing commit forms
  documented in PRD-03), pinned as-is because it is what the lecturer's own
  tooling computes.

  **Consensus scope** — what actually goes under that hash — is the
  trimmed, two-team-agreed object: `game_id`, an `aggregate` block
  (`total_score`, `sub_games_won`, `ties`, `winner_group`, `series_tie`),
  and `sub_games` rows trimmed to only `sub_game_number`, `roles`,
  `result`, `winner_group`, `score` — deliberately excluding anything
  either side could legitimately compute differently (timestamps, token
  counts). A whole-body-minus-signature scope can never produce equal
  hashes between two honest, conformant teams, by construction.

- **The diversity reward and league fields.** App. F: 10 points for a
  **win** against a group not previously played (not merely for meeting
  one) — `diversity_reward_applied` is therefore *derived*: `true` for the
  winner of a genuinely first counted meeting, `false` otherwise, both
  sides computing it from the same agreed outcome. It is applied by the
  league table from this flag and is explicitly **not** baked into
  `total_score` itself. `games_played_including_this` is each team's own,
  unverifiable claim about its own standing — legitimately `null` when this
  team cannot know the opponent's count, which is not the same claim as
  `0`.

- **Friendlies-before-counted-game discipline.** Only the **first** meeting
  between two groups counts (App. E rule 52); warm-ups are explicitly
  permitted and recommended (book ch.9.2.1) and owe **no report to
  anyone** — a practice run must not touch the lecturer's address at all,
  under any flag. The counted-games ledger (which pairings have already
  played a counted series) must be **committed to the repo**, not merely
  held in memory or a gitignored file — an uncommitted ledger cannot prove
  a repeat pairing to a grader re-cloning the repo, and a ledger that never
  advances makes the *next* counted series against the same opponent
  falsely declare `first_meeting_between_groups: true`, which is a
  rules-37/38 project-fatal false declaration produced entirely by
  accident.

- **The lecturer's address must be structurally unreachable outside a
  counted run**, not merely unconfigured behind a boolean flag — a
  practice run should have nowhere to send mail even if every other gate
  were accidentally bypassed. `email.mode` cannot rely on Gmail's
  drafts API as the safety gate: rule 30's granted OAuth scope is
  **send-only**, which cannot create drafts, so a gate that depends on
  drafting depends on a permission this project doesn't actually have.

- **Report format, sent literally twice per the book's own contradiction.**
  Rule 34 requires the final report as an attached JSON file; the book's
  own Appendix A listing and the reference implementation both send a
  plain text body instead. Rather than picking a side of a documented book
  self-contradiction, send **both**: the canonical `result` JSON as the
  email body **and** the same file as the single named attachment — the
  emailed body bytes must be the exact canonical bytes that were hashed,
  never a pretty-printed re-serialization (a real, observed near-failure
  in a past course iteration per the interop kit).

- **Gatekeeper / rate limiting**, per `config/game.json`'s existing
  `rate_limiter_gatekeeper` section (already signed, already present, not
  yet enforced by any code): a token-bucket limiter in front of outbound
  calls (LLM, Gmail), with retry-backoff and a circuit breaker on repeated
  failure — the book's own stated answer to a runaway loop, not human
  review.

## Out of scope

`declaration_<game_id>.json`, `config_<game_id>_gNN.json`,
`log_<game_id>_gNN.json` — PRD-03. The public tunnel's actual transport
mechanics (ngrok process management) are implementation detail of this
stage, not separately specified here.

## Acceptance criteria

- [ ] `result_<game_id>.json` is derived entirely from PRD-03's per-sub-game
      agreed rows — no separately-declared total exists anywhere in the
      code.
- [ ] The chosen tie-rule behaviour (`series_add`) is a single named
      constant, documented exactly like PRD-01's `MAX_MOVES_COUNTING_BASIS`,
      flagged for opponent-group negotiation before any counted series.
- [ ] The consensus signature is computed with the spaced serialization and
      sign-then-insert ordering, verified against the interop kit's
      `report_consensus.json` vector (ported as a fixture, not imported).
- [ ] A practice/friendly run cannot reach the lecturer's configured
      address under any code path, tested by construction (e.g. the
      recipient the run resolves to for a non-counted run is not a valid
      email at all, not merely "sending disabled").
- [ ] The counted-games ledger is a committed file, and a test asserts a
      counted run's settlement path always advances it.
- [ ] `diversity_reward_applied` is asserted to be derived from the match
      outcome, never independently settable.

## Depends on

PRD-03 — this stage has nothing to aggregate or report until a full,
audited, multi-sub-game series exists.

## Open questions

1. Exact tunnel provider and its failure semantics (`406`/`502`/`530`/
   `404 ERR_NGROK_3200` — the interop kit's own LEAGUE-OPS taxonomy) are
   not yet chosen for this project.
2. Whether this project will register any of the interop kit's `PROPOSED`
   extensions (declaring the derived `game_uid` at handshake time, per its
   §7.3) — worth doing given the real, silently-invisible failure mode it
   closes, but not decided here.
3. Contacting the interop kit's authors for friendly/warm-up games before
   any counted series — see TODO.md.
