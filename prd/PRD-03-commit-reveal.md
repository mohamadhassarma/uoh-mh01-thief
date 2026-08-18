# PRD-03 — Commit-Reveal Integrity (SHA-256)

## Status

Not yet implemented. This document is the design promoted from stub to real
PRD during the stage-2 corrections round — see PLAN.md "Revision (Stage 2
corrections)" for why the pre-game handshake, the step-0 declaration, the
sub-game series loop, and three of the four standardized artifacts land
here rather than elsewhere.

## Sources and their authority, for everything below

Three sources were consulted, in this order of authority (lower always wins
a genuine conflict; a lower source may still resolve a genuine gap the
higher source leaves open — that is a documented choice, not an override):

1. **The book** (rulebook + Appendix F's binding parameter table) — the sole
   source of truth for anything it actually fixes.
2. **The official reference implementation**, [`rmisegal/Game-P2P-Cop-Chase`](https://github.com/rmisegal/Game-P2P-Cop-Chase)
   (code v3.0.0) — "a learning aid, not a submission skeleton" per its own
   README; read and reused for understanding, never copied in, and never
   trusted over the book.
3. **The student interop kit**, [`Imreec/copthief-league-protocol`](https://github.com/Imreec/copthief-league-protocol) —
   not a specification, a *conformance aid* pinning byte-level constructions
   the book leaves as prose. Where it makes a choice the book leaves open,
   adopting that choice here is OUR decision, recorded as such below, not an
   inherited authority.

Every construction below was verified directly against the kit's `SPEC.md`
and cross-checked against the reference's actual source
(`domain/crypto.py`, `domain/game_ids.py`, `domain/negotiation.py`,
`peer/sealing.py`, `peer/handshake.py`) — both agree on every item this PRD
adopts.

## Goal

Replace stage 2's unhashed placeholder commit/verify
(`_stage3_placeholder_commit` / `_stage3_placeholder_verify` in
`orchestrator.py`) with real SHA-256 commit-reveal sealing, add the
pre-game handshake that must precede the first move, and run a full
`num_games`-sub-game series with role alternation instead of stage 2's
single one-off match — producing three of the four standardized JSON
artifacts (`declaration`, `config`, `log`) along the way. The fourth
(`result`) is PRD-07's, once a series' worth of these exists to aggregate.

## In scope

- **Canonical JSON.** Every hash in this stage is `SHA-256` over the UTF-8
  bytes of `json.dumps(obj, sort_keys=True, ensure_ascii=False,
  separators=(",", ":"))`. Three details are load-bearing (interop kit
  SPEC §2, matching the reference's `_canonical` helper verbatim in both
  `domain/crypto.py` and `domain/game_ids.py`):
  - `ensure_ascii=False` — non-ASCII (Hebrew hints, emoji, non-English
    `map_area`) goes on the wire as raw UTF-8, never `\uXXXX`-escaped. This
    is the single most likely silent break: the opponent re-hashes our
    *revealed* hint text at audit time with their own serializer, and an
    escaped string hashes differently.
  - Floats use Python's own shortest-round-trip `repr` (`0.1`, not
    `0.10000000000000001`) — relevant the moment `pheromones.*` values or a
    sealed hardware `ram_gb` cross this boundary.
  - Sorted keys, no whitespace. Construction order in our own code is
    irrelevant; canonicalization sorts it.

- **The commit-reveal construction — and the three-competing-constructions
  problem.** The v3.0.0 release itself is internally inconsistent about
  this, and the interop kit documents it explicitly (SPEC §3): the book's
  ch.5 listing seals the nonce *inside* the canonical JSON object; the
  book's own audit-chapter snippet instead re-hashes `f"{nonce}|{move}"`;
  the reference implementation computes `SHA256(canonical_json(payload) +
  "|" + nonce)`. All three are "commit-reveal over SHA-256 per step" —
  which is what the binding rules actually mandate — so the *preimage* is
  formally open, but it is an **interop constraint**: the opponent's audit
  re-hashes *our* revealed records with *their* serializer, so both sides
  must agree on the same form or the audit voids the match for both teams
  (App. E rule 35). **This engine adopts the reference's form**:
  ```
  commit = SHA256( canonical_json(payload) + "|" + nonce )
  ```
  for three reasons, in the order that decides them: (1) it is what the
  lecturer's own tooling and most teams will build against; (2) of the
  three, it is the only one that is cryptographically sufficient — the
  audit-snippet form hashes only `nonce` and `move`, binding neither
  `state` nor `intent`, so a record's position or bluff verdict could be
  rewritten after the fact without changing that hash; (3) it matches the
  agreement-signature construction below, so there is exactly one hash
  shape in this codebase, not two. This is a provisional, documented
  choice, not a rulebook requirement — flagged for opponent-group
  negotiation exactly like PRD-01's `max_moves` basis was.

- **The pre-game handshake.** Before the first real move of sub-game 1,
  each peer:
  1. Extracts the flat, must-agree subset of `config/game.json` into a
     `terms` dict (board, movement, scoring, pheromones, `num_games`, axes,
     `map_area`, `hint_max_words` — the book's App. F table; the reference's
     `terms_from_config` is the worked example).
  2. Signs it: `signature = SHA256(canonical_json(terms) + "|" + nonce)`
     with a fresh random nonce, and sends `{terms, nonce, signature,
     identity}` to the opponent (`identity` — group id/name/members/repos/
     MCP URLs/hardware — is exchanged but NOT covered by the signature,
     since it legitimately differs per side).
  3. Verifies the opponent's message: `terms` must be value-equal to its own
     (not just similar — a byte-for-byte match after canonicalization), and
     the opponent's `signature` must re-verify against the opponent's own
     `nonce` over those terms. A mismatch on either refuses to play.
  4. Derives, from the now-confirmed-shared `terms` and the two group ids —
     **with no further round-trip needed**, since both sides now hold
     identical inputs:
     ```
     game_id  = "-vs-".join(sorted([group_a, group_b]))
     game_uid = str(UUID(bytes = SHA256(canonical_json(terms) + "|" + "|".join(sorted([group_a, group_b])))[:16]))
     ```
     **Both must be derived from the flat `terms`, never from the whole
     `config/game.json`.** The interop kit documents a real, silent cross-
     team failure mode here (SPEC §4, WARNINGS §2): a `game_uid` derived
     from the wrong (but still deterministic) input is internally
     self-consistent across all four of one team's own artifacts and looks
     completely healthy — only the *cross-team* join fails, and nothing on
     either side has a reason to notice until the two final reports are
     diffed. `tests/test_game_ids.py` (stage 3) must assert the derivation
     uses the extracted `terms`, not `raw_config`, specifically to catch
     this class of bug, not just a general "ids match" test.
  5. Names itself first only inside its own log, never in `game_id` —
     always sorting the pair — for the same reason: naming order is
     invisible until diffed against the opponent's copy.

- **The step-0 declaration, once PER SUB-GAME, not once per series.**
  Rule #53 was verified directly against the book PDF (`docs/police_thief_p2p.pdf`
  in the reference repo, Table 12, cross-referenced from ch.5) rather than
  taken on trust; its exact text (Hebrew, translated here) is:

  > **53. MANDATORY** — record in the step-zero declaration the commit hash
  > (`commit hash`) that was played; changing code between games is
  > permitted, but every game the commit hash must be updated to match.
  > Source: Chapter 5.

  Two consequences this PRD's first draft got wrong and now corrects:
  (1) "every game" (כל משחק) means every **sub-game**, not once at series
  start — each of the `num_games` sub-games seals its OWN step-0 record with
  whatever commit was actually running for THAT sub-game, since the rule
  explicitly permits code to change between sub-games; (2) this step-0
  record therefore belongs inside each sub-game's own `log_<game_id>_gNN.json`,
  sealed the same way as every per-step record
  (`{"payload": {...}, **commit_reveal_seal(payload)}`) — it is NOT a
  once-per-series fact that belongs only in `declaration_<game_id>.json`
  (which still separately carries the static, once-per-series identity and
  hardware spec). The commit hash itself is read via `git rev-parse HEAD`
  at process start, never hand-typed, so a code change between sub-games is
  reflected automatically rather than relying on someone remembering to
  update it.

- **The `num_games`-sub-game series with role alternation.** A single
  invocation now plays `network_and_league.num_games` (6, post the stage-2
  corrections fix to `config/game.json`) sub-games against the same
  opponent and then stops — not stage 2's single one-off match. **Role
  alternation**: a peer plays its config-natural role on odd sub-games and
  the opposite role on even ones (both reference README and interop kit
  agree on this; the reference's own reason — "so the peers stay
  consistent, when A is cop, B is thief" — is the one adopted here).
  Architecturally this means `PeerRuntime` can no longer assume a fixed
  `self.role` for the process's whole lifetime — the per-sub-game loop must
  construct (or reconfigure) a fresh `PeerRuntime` per sub-game with the
  alternated role, mirroring stage 2's existing pattern of "one
  `PeerRuntime`, one match" but now inside an outer loop. This is a real
  architectural consequence, not a cosmetic one: every place stage 2 wrote
  "PeerRuntime is the sole owner of this peer's live match state" (rule #3)
  now means *one sub-game's* state, not the whole series'.

- **Real per-step commit-reveal**, replacing
  `_stage3_placeholder_commit`/`_stage3_placeholder_verify` (which
  `tests/test_orchestrator.py::test_stage3_placeholders_still_present`
  currently guards specifically so this can't happen silently). Each side
  seals its own turn record before sending the reveal; nonces are withheld
  until the post-sub-game mutual audit.

- **The mutual post-game audit**, per sub-game: each side reveals its own
  full sealed record list; the *opponent* re-hashes every record with its
  own canonical-JSON serializer and re-verifies
  `SHA256(canonical(payload)|nonce) == commit`. A failure is
  `tamper_forfeit`ish — the specific sanction is an open question below,
  since App. E rule 35 already zeroes a *contradictory-report* pair via a
  separate mechanism (the stage-2-corrections declare/confirm exchange),
  and this PRD must not silently invent a second, overlapping penalty path.

- **Three of the four standardized artifacts**, all sharing one `game_uid`:
  `declaration_<game_id>.json` (written once, at series start — identity,
  hardware, `num_games`, start/end times), `config_<game_id>_gNN.json`
  (the exact agreed config actually played for sub-game `NN`, plus its own
  `config_sha256`), `log_<game_id>_gNN.json` (the full sealed per-step
  record list for sub-game `NN`, its summary, and the mutual audit result).
  Filenames follow the book's App. F table and the kit's pinned grammar
  (`<artifact>_<game_id>.json` for match-level files,
  `<artifact>_<game_id>_g<NN>.json`, zero-padded, for per-sub-game files).

- **Test vectors.** Per the interop kit's own integrity boundary ("port
  their VECTORS into our test suite as fixtures and write our own checks
  against them — do NOT copy their implementation code"), stage 3's test
  suite must include fixtures derived from `vectors/canonical_json.json`,
  `vectors/commit_reveal.json`, `vectors/terms_signature.json`, and
  `vectors/game_uid.json`, checked against THIS codebase's own
  independently-written canonicalization/commit/signature/id functions —
  not against imported kit code. This is TODO.md work for when stage 3's
  implementation actually starts, not done in this corrections round.

## Out of scope (later stages / already covered)

- The terminal-condition declare/confirm exchange for entrapment and the
  max_moves ceiling — already retrofitted into stage 2 (PRD-02 "Stage 2
  corrections" B1), not deferred here, because it was a protocol-layer gap
  independent of any cryptography.
- `result_<game_id>.json`, its consensus signature (a *second*,
  differently-serialized hash — see PRD-07), the diversity reward, and
  league standings fields — PRD-07.
- Pheromones/scent/belief (stage 4). LLM trash-talk (stage 5). GUI/replay
  (stage 6). Tunnels/Gatekeeper/Gmail (stage 7).

## Acceptance criteria

- [ ] Two peers complete a full pre-game handshake; a deliberately mismatched
      `terms` value on one side causes both to refuse before any move.
- [ ] Both peers derive an identical `game_id` and `game_uid` with no
      further round-trip after the handshake, verified directly against
      the interop kit's `game_uid.json` vector's construction (not its
      code).
- [ ] `game_uid` is asserted to be a function of the extracted `terms`, with
      a test that would fail if it were accidentally derived from the raw
      `config/game.json` instead (per WARNINGS §2's documented failure
      mode).
- [ ] A full `num_games`-sub-game series plays end to end over two real
      subprocesses, roles alternating each sub-game, and both sides'
      artifacts agree.
- [ ] Every sealed per-step record's commit re-verifies against its own
      later-revealed `(payload, nonce)` — self-audit — and the *opponent's*
      re-hash of our revealed records matches ours — cross-audit — using
      each side's own independently-written canonicalizer.
- [ ] `_stage3_placeholder_commit`/`_stage3_placeholder_verify` are deleted
      and `test_stage3_placeholders_still_present` is deleted alongside
      them (that test failing on `main` is the correct, expected signal
      that this stage has landed).
- [ ] `declaration_<game_id>.json`, `config_<game_id>_gNN.json`, and
      `log_<game_id>_gNN.json` are written with the book's/kit's pinned
      filename grammar and validated against `tools/check_artifacts.py`
      from the interop kit run as an external check (not vendored in).
- [ ] The stage-3 test suite includes fixtures ported from
      `vectors/canonical_json.json`, `vectors/commit_reveal.json`,
      `vectors/terms_signature.json`, `vectors/game_uid.json`, checked
      against this codebase's own functions.

## Depends on

Stage 2 (PRD-02) — the state machine, the timeout/watchdog layer, the
`submit_move`/`declare_terminal` protocol, and the terminal declare/confirm
exchange all carry forward unchanged; this stage only replaces the placeholder
commit/verify calls and adds the handshake and series loop around the
existing per-sub-game match loop.

## Open questions

1. What exactly does a failed cross-audit resolve to, given rule 35's
   contradictory-report mechanism already exists at the protocol layer
   (PRD-02 "Stage 2 corrections" B1)? Does a tamper finding *replace* a
   sub-game's already-agreed terminal condition, or does it only ever
   apply to a case the declare/confirm exchange had already left disputed?
   Needs resolving before implementation, not guessed.
2. The reference's `num_games` selector in its GUI (1–6, overriding the
   config default at runtime) vs. this project's headless-only,
   config-driven `num_games` — is a runtime override needed, or is
   config-only sufficient for this course's grading path? Flagged, not
   decided.
3. `turn_timeout_seconds`'s interaction with a full N-sub-game series: does
   the private per-turn budget reset every sub-game, or accumulate? PRD-02
   only ever specified it per-turn within one match; extending to a series
   is new ground.
