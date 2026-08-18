# TODO — Thief agent

## Now (Stage 1: base logic) — done
- [x] Load and validate `config/game.json` against the mandatory parameter table
- [x] Board representation, 7x7, index-0, origin top-left
- [x] Legal move set: N/S/E/W/STAY — reject diagonals
- [x] Barrier placement rules (police only, adjacent-or-own cell, irreversible)
- [x] Capture detection by coordinate overlap
- [x] Trapped-thief detection (no legal move => captured)
- [x] Scoring table: capture 20/5, survival 5/10, technical loss 0/0
- [x] Run a full match in a single process without crashing
- [x] `pytest` covering rules and scoring

## Now (Stage 2: FastMCP infrastructure) — done
- [x] `config/<role>/game.toml` loader with the signed-contract overlay rule
- [x] Turn-protocol state machine (formal, illegal transitions raise)
- [x] Three-tier timeout/watchdog handling — dead opponent -> TECHNICAL_LOSS, not a hang
- [x] Orchestrator wiring MCP transport to the domain engine, no decision logic of its own
- [x] `python -m uoh_mh01 peer --role {police,thief}`, two real processes, one full match
- [x] `logs/<role>_match.json` — complete, timestamped move + phase-transition log
- [x] `pytest` covering config overlay, state machine, watchdog, protocol, and a real
      dual-subprocess integration run

## Now (Stage 2 corrections — protocol intake + B1/B2/B3) — done
- [x] Studied the reference implementation and the interop kit; findings recorded in
      PLAN.md, PRD-03, PRD-07 (see those files' "Sources and their authority" sections)
- [x] `config/game.json`: `network_and_league.num_games` 1 -> 6 (book-mandated)
- [x] B1: terminal conditions (entrapment, the max_moves ceiling, and — uniformly —
      capture/survival too) are now DECLARED and independently re-verified via a
      declare/confirm exchange (`action_type == "declare_terminal"` reuses
      `submit_move`'s wire shape), never inferred from silence or trusted from a claim.
      A genuine disagreement raises `DisputedOutcomeError` and both sides log BOTH
      claimed conditions — never silently resolved. See `domain/terminal_detect.py`,
      `infra/turn_sender.py`, `infra/turn_receiver.py`, `infra/outcomes.py`.
- [x] B2: every wire message now carries the sender's own post-action
      `police_actions_taken`/`thief_actions_taken`; the receiver rejects any message
      whose counters don't match its own local recount as a `divergence` (scored as an
      unscored TECHNICAL_LOSS with no attributable offending side).
- [x] B3: `turn_timeout_seconds` is now independently enforced — both for my own active
      turn (wrapped in its own `asyncio.wait_for`) and for how long I'll passively wait
      on a silent opponent — distinct from and can fire before `watchdog_timeout_sec`.
      The fixed 0.5s shutdown sleep was replaced with bounded polling on an in-flight
      request counter (still a heuristic for the actual transport flush, now bounded
      and responsive instead of a blind unconditional wait).
- [x] Split `orchestrator.py` into `PeerRuntime` (core) plus `infra/turn_sender.py` /
      `infra/turn_receiver.py` mixins, `infra/outcomes.py`, `infra/peer_entrypoint.py`,
      `infra/stage3_placeholders.py`, and split `infra/protocol.py`'s response half into
      `infra/protocol_response.py` — brings `orchestrator.py` back under the ~150-line
      quality-bar budget (was 264, now 148); `domain/config.py` (176 lines) is the one
      file still over the budget — untouched this round, flagged below.
- [x] `ruff` added as a dev dependency, configured to match the reference's own
      `pyproject.toml` rule selection (`E,F,W,I,N,UP,B,C4,SIM`, `E501` ignored, 120-col);
      all findings in code touched this round fixed. 6 pre-existing findings remain in
      untouched stage-1/2 code — see "Known limitations".
- [x] `pytest-cov` added; coverage 91% overall (bar: 85%), using the same
      subprocess-execution `omit` list the reference's own `pyproject.toml` uses for
      `__main__.py`/`mcp_server.py`/`mcp_client.py` (plus `peer_entrypoint.py`, for the
      same reason: only exercised end-to-end via the real dual-subprocess test).
- [x] 163/163 tests pass (up from 142), including the real dual-subprocess integration
      run under the new declare/confirm protocol.

## Now (Stage 2 corrections, round 2 — book verification + real fixes) — done
- [x] Cloned the reference repo to `C:\dev\uni\_reference\ref_impl` (OUTSIDE both project
      repos) specifically to get `docs/police_thief_p2p.pdf` on disk; `.gitignore` now
      guards `police_thief_p2p.pdf`/`**/police_thief_p2p.pdf` by name (not `*.pdf` —
      the eventual `uoh-mh01-exYY.pdf` submission legitimately belongs in this repo).
- [x] Verified rule #53's exact wording directly against the book PDF (not against
      any assertion) — see PRD-03 "The step-0 declaration": it requires the commit hash
      to be recorded and UPDATED every SUB-GAME (code may change between sub-games),
      not once per series as this PRD's first draft had assumed. PRD-03 corrected.
- [x] Checked the unconfirmed-claim path precisely, as two separate cases: CONTESTED
      (confirmed already correct, unchanged) vs SILENT (confirmed the TECHNICAL_LOSS
      resolution was already correct, but found the claim itself was being dropped from
      the log — fixed via `MatchLogRecorder.unconfirmed_claim`).
- [x] Found and fixed a real, independent bug while checking the above: `FreezeDetected`
      (the watchdog's own top-of-loop check) was never caught anywhere in `run_match`,
      so a genuinely silent opponent on ITS OWN turn, at DEFAULT config values
      (`turn_timeout_seconds` 180 > `watchdog_timeout_sec` 60), crashed the process with
      an unhandled exception instead of producing a `TECHNICAL_LOSS`. This was present
      since round 1, not introduced by it. Fixed: `run_match` now catches it and resolves
      to `TECHNICAL_LOSS(offending_side=self.state.whose_turn)`. See PRD-02 "Round 2
      corrections" for the full trace of why this specific gap existed.
- [x] Renamed `action_type == "concede"` to `"declare_terminal"` everywhere (wire,
      code, docs) — entrapment is a CAPTURE, not a concession, and the string crosses
      the wire into the audit log and (later) the result artifact. Neither the reference
      nor the interop kit's SPEC name this concept as an action type of their own (both
      reuse field-level vocabulary instead), so this is this project's own neutral
      choice, documented as such.
- [x] 165/165 tests pass (up from 163); `ruff` still clean against the reference-aligned
      rule set (same 6 pre-existing findings, none new).

## Now (Stage 3: commit-reveal, handshake, audit, artifacts, series) — implementation done, not yet committed
- [x] `domain/canonical.py`, `domain/crypto.py`, `domain/game_ids.py` — canonical JSON,
      commit-reveal (`SHA256(canonical_json(payload)+"|"+nonce)`), `game_id`/`game_uid`
      derivation. All four relevant interop-kit CORE vectors (canonical_json,
      commit_reveal, terms_signature, game_uid) ported as data-only fixtures and
      reproduced byte-for-byte (`tests/test_vectors.py`).
- [x] Capture-symmetry superseded: capture-by-landing is now gated on `actor is
      Side.POLICE`; a thief walking onto the police is an ordinary move. New negotiable
      house rule `CAPTURE_CLAIM_MECHANIC` signed into `terms` alongside `FIRST_MOVER`.
      See PRD-01 "Open questions" #4 and PRD-03.
- [x] Pre-game handshake (`infra/negotiation.py`): mutual signed `terms`, `game_id`/
      `game_uid` derived from the flat negotiated terms (never the whole config), refuse
      on any mismatch (terms, signature, sub_game_number, role, pheromone-model hash).
- [x] Pheromone/scent-model hash exchanged in `negotiate`'s EXTRAS (never inside signed
      `terms`) via `shared/locked_model.py` — book's ch.4 multiplicative formula recorded
      and hashed now, actual model deferred to PRD-04.
- [x] Real per-turn commit-reveal wired into the existing turn loop (stage 2's unhashed
      placeholders deleted outright), plus the mutual post-sub-game audit
      (`infra/audit.py`) that re-hashes against what was *received live*, never against a
      copy the revealer could rewrite after the fact.
- [x] Three of the four standardized JSON artifacts (`declaration` once per series,
      `config`/`log` once per sub-game) — `infra/artifacts.py`. The fourth (`result`) is
      PRD-07's.
- [x] `num_games`-sub-game series loop with role alternation (odd=natural, even=swapped)
      over ONE long-lived FastMCP server per process for the whole series
      (`infra/series_runtime.py::SeriesRuntime`, `infra/series.py::run_series`).
- [x] Found and fixed four real concurrency bugs surfaced by real dual-subprocess stress
      testing (missing retry on the audit-reveal call; cross-sub-game audit
      misattribution; a submit_move startup race between sub-games; and, found in a
      later stress batch, `SeriesRuntime`'s audit state being tracked in a single
      "current" slot instead of keyed per sub-game, which could both wrongly time out a
      still-in-flight audit from the previous sub-game and, worse, cross-contaminate the
      next sub-game's result). Full debugging history in PRD-03's "Work in progress"
      section. 15/15 and 20/20 clean stress-test batches after the final fix.
- [x] Commit-reveal preimage: the book's own ch.5.3 printed listing (nonce inside the
      object, no `ensure_ascii=False`) was verified directly against the PDF and found to
      contradict the reference/interop-kit form already implemented. Kept the
      reference/kit form as a documented, reasoned deviation — see PRD-03's "Commit
      preimage" section for the full side-by-side citation (book clarification page,
      ch.5.3 listing as printed, chosen construction, reasoning).
- [ ] Not yet done this round: PRD-03/PRD-07's own coverage/ruff/line-budget recheck
      against the new files; a transcript at the real contract's `num_games=6`/
      `max_moves=35`/`survival_threshold=35` values (the stress-tested integration test
      uses shrunk values for speed); mirroring anything to the thief repo (deliberately
      deferred — this stage was police-repo-only throughout, per instruction).

## Blocked / needs negotiation with opponent group
- [ ] Agree `config/game.json` byte-for-byte with opponent group — **now includes the
      `num_games: 1 -> 6` change**; must be re-verified byte-identical with the thief
      repo (not yet mirrored — stage 2's original commit/mirror rule still applies) and
      with any opponent group before a real series.
- [ ] Agree `axis_origin_corner` and `axis_start_index`
- [ ] Agree `map_area` and `hint_max_words`
- [ ] Agree the counting basis for `max_moves` (per-player vs combined) — see
      PRD-01 "Open questions"; this engine currently assumes per-player
- [ ] Agree who moves first (`FIRST_MOVER`) — see PRD-01 "Open questions". Now a
      signed handshake term (`shared/terms.py`), so a mismatched opponent refuses
      cleanly instead of disagreeing mid-match.
- [x] Trigger condition for `tie_score` — found (book ch.9 "Tie Rule", App. F table 17
      row 5): fires on the *cumulative score across a whole series* between a pair of
      teams, not per sub-game. See PRD-01 "Open questions" #6 and PRD-07's "tie-rule
      contradiction" (book/reference disagree on the mechanics of applying it —
      `series_add` is this project's documented choice, still MUST-AGREE with any
      opponent before a real series ties).
- [ ] **MUST-AGREE — agree the commit-reveal preimage form (PRD-03).** This engine
      adopts the reference/interop-kit form,
      `SHA256(canonical_json(payload)+"|"+nonce)` with `ensure_ascii=False`, as a
      documented, reasoned deviation from the book's own ch.5.3 printed listing (which
      puts the nonce inside the object and omits `ensure_ascii=False`) — see PRD-03's
      "Commit preimage" section for the full citation (book clarification page, listing
      as printed, chosen construction, reasoning, side by side). Any opponent group
      implementing verbatim from the printed listing fails our audit and we fail
      theirs, on the very first revealed step, before any counted game.
- [ ] **MUST-AGREE — agree the capture-claim mechanic (PRD-01 #4 / PRD-03).** Capture-
      by-landing is now police-turn-gated (`CAPTURE_CLAIM_MECHANIC =
      "police_turn_gated_claim"`, signed into `terms`): a thief walking onto the police
      is an ordinary move, and the police may claim a prior co-location via STAY on its
      own later turn. This is a signed handshake term, so an opponent whose own
      implementation names a *different* value for the same key refuses cleanly at
      negotiation — but only if their implementation exposes this as a comparable named
      value at all. An opponent built straight from the book's literal "police lands on
      thief's cell" text, with no equivalent concept in its own terms schema, may not
      produce a clean refusal — this still needs explicit human confirmation before a
      counted game, not reliance on the handshake alone to catch it.
- [ ] Agree the series tie-rule behaviour (PRD-07): `series_add` (this project's
      documented choice) vs `series_replace` vs `per_subgame` (the reference's own) —
      invisible until a real series ties, then a scoring contradiction under rule 35.
- [ ] Declare turn order explicitly in first contact, independent of any wire-shape
      lock — the interop kit documents two conformant peers deadlocking despite a fully
      matching handshake because turn order was never actually pinned by any hash
      (SPEC §7, "What the wire_shape lock does not cover").
- [ ] Role-alternation convention for a `num_games`-sub-game series (odd=natural,
      even=swapped) — the mechanics of alternating role *within a running series* are
      now implemented and stress-tested (`infra/series.py`; see PLAN.md "Role
      alternation — the engineering answer"), but the convention itself (odd/even, not
      e.g. alternating every other pair, or by explicit per-sub-game declaration) still
      needs explicit confirmation with the opponent group, not just this repo's own
      reading of the reference/book. Separately, and still unresolved: which of our two
      *repos* gets launched for a given sub-game in a real counted series — see "Open
      questions for the professor" below, unchanged by this stage's work.

## Known limitations
- [ ] `axis_origin_corner` and `axis_start_index` are negotiable per the
      mandatory parameter table, but this engine currently only implements
      `"top-left"` / `0`. Any other agreed value requires implementation work
      in `board.py`'s move deltas (and revisiting `config.py`'s validation)
      before it can be used — it is not a config error, just unbuilt.
- [ ] A divergence-detected TECHNICAL_LOSS, a turn_timeout_seconds self-forfeit, and the
      round-2 `FreezeDetected` catch-all all settle the match WITHOUT a corresponding
      state-machine transition (there is no edge to a terminal state from most nodes in
      the given table for any of the three) — this mirrors the existing precedent (the
      entrapment pre-check already worked this way in stage 2) rather than adding an
      edge the mandatory table doesn't list. See PRD-02 "Stage 2 corrections" B1/B3 and
      "Round 2 corrections".
- [ ] Graceful peer shutdown is now bounded polling on an in-flight-request counter
      plus a short fixed flush pause, not stage 2's blind fixed 0.5s sleep — but it is
      still a heuristic (the actual HTTP transport flush can't be directly observed).
      A real handshake is still stage-3-appropriate work, not done here.
- [ ] `domain/config.py` is 176 lines, over the ~150-line quality-bar budget this
      project otherwise now meets everywhere else in `src/`. Untouched this round
      (no Part B change touched it); a stage-3-adjacent cleanup task.
- [ ] 6 pre-existing `ruff` findings remain, all in stage-1/2 code untouched this round:
      5x `UP042` (`class X(str, Enum)` could modernize to `enum.StrEnum`, Python 3.11+)
      across `board.py`/`scoring.py`/`state.py`/`state_machine.py`, and 1x `N818`
      (`FreezeDetected` should be `FreezeDetectedError` by convention) in `watchdog.py`.
      Not fixed this round: touches five files' enum semantics for a stylistic
      preference, carries a small non-zero behavioural-change risk (`str()` on a
      `StrEnum` member differs from `str, Enum`'s default), and wasn't asked for.
- [x] The interop kit's four CORE test vectors (`canonical_json.json`,
      `commit_reveal.json`, `terms_signature.json`, `game_uid.json`) are now ported
      into `tests/fixtures/vectors/` (data only, no kit code) and all reproduce
      byte-for-byte (`tests/test_vectors.py`).
- [ ] PRD-07 remains a design document only — no `result_<game_id>.json`, consensus
      signature, diversity reward, counted-games ledger, Gatekeeper, or Gmail/tunnel
      code exists yet. PRD-03, by contrast, is now substantially implemented (real
      handshake, real per-turn commit-reveal, mutual audit, three of the four
      standardized artifacts, the `num_games`-sub-game series loop) — not committed yet,
      see PRD-03's "Work in progress" section for exact status.
- [x] FIXED: `_handle_move_or_barrier`'s at-least-once-delivery handling. A field-
      observed asymmetric-outcome bug (one side's log read `technical_loss`, the
      other's read `survival` for the SAME sub-game) was traced to exactly the
      predicted mechanism: a retried commit re-evaluated against advanced state
      instead of deduplicated, plus a timing-out side never rejecting a genuinely-
      new message that arrived after it had already self-finished. Fixed via
      commit-keyed idempotent response replay (`PeerRuntime._replayed_responses`)
      and post-finish rejection — see PRD-03 "Symmetric timeout outcomes" for the
      full root-cause trace, the fix, and the one residual (non-scoring) divergence
      left deliberately unresolved. `tests/test_symmetric_timeouts.py` covers it,
      including a real end-to-end reproduction at the unmodified `config/game.json`
      contract values (no shrunk timeouts).

## Open questions for the professor (recorded, NOT answered by guessing)

- [ ] **Which repo does a team actually launch during a counted series, and are both
      repos of a group ever running simultaneously against one opponent?** Our
      submission is two separate repos (police, thief); in a counted series, roles
      alternate across the six sub-games, so a single group must field BOTH roles
      across the series. It is unclear whether: (a) one repo's code is launched per
      sub-game, alternating which repo runs, or (b) both repos' processes run for the
      whole series and something else decides which one is "active" per sub-game, or
      (c) something else entirely. **Checked the interop kit's `docs/PAIRING-PLAYBOOK.md`
      for their own completed-campaign answer, per instruction, rather than guessing:**
      their playbook describes each TEAM (not each repo) running "its cop" or "its
      thief" per sub-game window, dialing the opponent's role-appropriate endpoint, with
      consecutive sub-games' processes able to briefly overlap during handoff (their
      tempo gate is "the previous log file exists", not "the previous process exited").
      **This does not fully resolve our specific question**: their campaign's "team"
      appears to be a single codebase capable of playing either role (like the reference
      implementation's own `--role` flag), not our course's mandatory TWO-SEPARATE-REPOS
      structure — so it is still unclear which of OUR two repos a launcher invokes per
      window, or whether our course's grader expects one "driver" script spanning both
      repos. Do not guess further; ask the professor directly.

## Admin
- [ ] Fill team member IDs in `config/thief/game.toml`
- [ ] Verify `.gitignore` blocks `credentials.json` and `token.json`
- [ ] Each team member submits separately on Moodle
- [ ] Word template -> `uoh-mh01-exYY.pdf` (do not move or edit fields)
- [ ] Contact the interop kit's authors (`Imreec/copthief-league-protocol`) about
      friendly/warm-up games before any counted series, per the kit's own
      `docs/PAIRING-PLAYBOOK.md` — not yet done.
- [ ] Set up a committed counted-games ledger (PRD-07) before any counted series is
      played — needed so a fresh clone can prove a pairing already happened (rule 52),
      not just this process's memory.
