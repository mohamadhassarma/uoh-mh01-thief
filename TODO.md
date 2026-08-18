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

## Blocked / needs negotiation with opponent group
- [ ] Agree `config/game.json` byte-for-byte with opponent group — **now includes the
      `num_games: 1 -> 6` change**; must be re-verified byte-identical with the thief
      repo (not yet mirrored — stage 2's original commit/mirror rule still applies) and
      with any opponent group before a real series.
- [ ] Agree `axis_origin_corner` and `axis_start_index`
- [ ] Agree `map_area` and `hint_max_words`
- [ ] Agree the counting basis for `max_moves` (per-player vs combined) — see
      PRD-01 "Open questions"; this engine currently assumes per-player
- [ ] Agree who moves first (`FIRST_MOVER`) — see PRD-01 "Open questions"
- [ ] Find or agree a trigger condition for `tie_score` — none is implemented
- [ ] Agree the commit-reveal preimage form (PRD-03): this engine will adopt the
      reference's `SHA256(canonical(payload)|nonce)`, one of three inconsistent forms
      the v3.0.0 release itself publishes — see PRD-03's "three-competing-constructions"
      section. A mismatched opponent form voids every audit.
- [ ] Agree the series tie-rule behaviour (PRD-07): `series_add` (this project's
      documented choice) vs `series_replace` vs `per_subgame` (the reference's own) —
      invisible until a real series ties, then a scoring contradiction under rule 35.
- [ ] Declare turn order explicitly in first contact, independent of any wire-shape
      lock — the interop kit documents two conformant peers deadlocking despite a fully
      matching handshake because turn order was never actually pinned by any hash
      (SPEC §7, "What the wire_shape lock does not cover").
- [ ] Role-alternation convention for a `num_games`-sub-game series (odd/even swap) —
      needs explicit confirmation with the opponent group, not just this repo's own
      reading of the reference/book.

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
- [ ] The interop kit's test vectors (`vectors/canonical_json.json`,
      `commit_reveal.json`, `terms_signature.json`, `game_uid.json`, …) have NOT yet
      been ported into this repo's test suite — that is stage-3 implementation work
      (PRD-03 depends on it), not done in this documentation/corrections round.
- [ ] PRD-03 and PRD-07 are design documents only as of this round — no handshake, no
      real commit-reveal, no series loop, no `result_<game_id>.json`, no Gmail/tunnel
      code exists yet. Implementing them is future work.

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
