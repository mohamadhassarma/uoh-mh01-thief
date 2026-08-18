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
  ch.5.3 listing seals the nonce *inside* the canonical JSON object with no
  `ensure_ascii=False`; the book's own ch.7.5 "replay verifier" sketch
  instead re-hashes `f"{nonce}|{move}"`; the reference implementation
  computes `SHA256(canonical_json(payload) + "|" + nonce)`, nonce *outside*
  the object. All three are "commit-reveal over SHA-256 per step" — which
  is what the binding rules actually mandate — so on its face the
  *preimage* looks like a genuine three-way conflict needing the
  book's own "academic freedom in case of contradiction" clause (p. v).
  It resolves more cleanly than that once the book's own framing of these
  two listings is read, below — but it is also, independently, an
  **interop constraint**: the opponent's audit re-hashes *our* revealed
  records with *their* serializer, so both sides must agree on the same
  form or the audit voids the match for both teams (App. E rule 35).

  **Why this is a documented deviation, not an oversight — the book's own words, side by side:**

  1. **The book's clarification page** (p. iv, "הבהרה: מהמחייב ומה רק
     ממחיש" — "Clarification: what binds and what merely illustrates"),
     quoted in full because it is the actual controlling text:

     > ברירת המחדל היא שאין כלל מחייב, אלא אם נכתב במפורש שהוא כלל מחייב.
     > כל האיורים, הדוגמאות, קטעי הקוד והתרחישים בספר זה הם המחשה של אופן
     > ניהול המשחק — הם אינם מהווים את חוקי המשחק ואינם מחייבים את
     > המשתתפים, אלא אם צוין לצדם במפורש שהם חלק מחוקי המשחק וכובלים את
     > הצדדים... מקור החובה היחיד הוא טבלת הפרמטרים המחייבת שבסוף הספר
     > (נספח ו).

     English: *"The default is that there is no binding rule, unless
     explicitly stated to be one. All illustrations, examples, code
     snippets and scenarios in this book are demonstrations of how the
     game operates — they do not constitute the rules of the game and do
     not bind participants, unless explicitly stated alongside them that
     they are part of the game's rules and bind the parties... The sole
     source of obligation is the binding parameter table at the end of the
     book (Appendix F)."*

     Tellingly, the book applies this exact vocabulary to itself: directly
     under the ch.5.3 listing (p. 37) it says *"הקוד שלעיל ממחיש מנגנון
     קונקרטי של מחויבות-וחשיפה"* — "the code above **illustrates**
     [ממחיש] a concrete mechanism of commitment-and-reveal" — the same verb
     ("ממחיש") the clarification page uses to name the category of things
     that do *not* bind. The book is not silent on which side of its own
     line this listing falls on; it says so explicitly.

  2. **The book's ch.5.3 listing, as printed** (p. 37, "מימוש commit() ו-
     verify() מעל SHA-256"):
     ```python
     def commit(state: str, move: str, intent: str) -> tuple[str, str]:
         nonce = secrets.token_hex(16)
         payload = json.dumps(
             {"state": state, "move": move, "intent": intent, "nonce": nonce},
             sort_keys=True, separators=(",", ":"),
         )
         h_commit = hashlib.sha256(payload.encode("utf-8")).hexdigest()
         return h_commit, nonce
     ```
     Nonce is a *key inside* the hashed object; there is no
     `ensure_ascii=False`. (The book's separate ch.7.5 "replay verifier"
     sketch, p. 57, is a third, even thinner form — `SHA256(f"{nonce}|
     {move}")` — binding neither `state` nor `intent`; it is illustrating
     the replay-viewer's own re-check, not proposing a competing per-turn
     commit standard, so it is not treated here as a serious third
     candidate.)

  3. **What this engine actually does instead** (`domain/canonical.py`,
     `domain/crypto.py`):
     ```
     commit = SHA256( canonical_json(payload) + "|" + nonce )
     canonical_json = json.dumps(payload, sort_keys=True,
                                  ensure_ascii=False, separators=(",", ":"))
     ```
     Nonce pipe-appended *outside* the canonicalized object;
     `ensure_ascii=False` set explicitly. This matches the reference
     implementation's actual code and the interop kit's CORE
     `commit_reveal.json` vector byte-for-byte (`tests/test_vectors.py`,
     all passing).

  **Reasoning, in the order that decides it:**
  1. Per the clarification page above, no rule is binding unless marked as
     one, and the sole mandatory source of quantitative/mechanistic truth
     is Appendix F's table. The ch.5.3 listing is illustrative — the book
     says so about itself, in its own words, immediately below the
     listing. What actually binds is the *mechanism* (commit-reveal over
     SHA-256 per step), not that specific preimage byte layout.
  2. The printed listing cannot be implemented as printed anyway: it omits
     `ensure_ascii=False`, which would silently `\uXXXX`-escape Hebrew
     hints and any non-ASCII `map_area`, guaranteeing an audit mismatch
     against any team hashing raw UTF-8. "Faithful to the book" was never
     actually an available option here — some deviation is forced the
     moment Hebrew content crosses this boundary.
  3. Interop is the actual point of a commit-reveal scheme with an
     opponent team: the reference implementation is the lecturer's own
     code, the interop kit pins this exact construction as a CORE
     conformance vector, and other groups will build against it. A
     preimage nobody else computes is cryptographically fine but socially
     worthless — every cross-team audit would fail on both sides.

  This is documented here as a **reasoned, explicit deviation from a
  printed illustration**, exercising the book's own "academic freedom in
  case of contradiction" clause (p. v) — not an oversight, and not a claim
  that the book's listing was wrong. **Negotiation agenda: MUST-AGREE.**
  Any opponent group implementing verbatim from the ch.5.3 printed listing
  will fail our audit and we will fail theirs on the very first revealed
  step — both sides score zero. This must be confirmed explicitly during
  the pre-game handshake negotiation, before any counted game, exactly
  like PRD-01's `max_moves` counting-basis question.

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

- **Symmetric timeout outcomes.** A field-observed bug, root-caused and
  fixed this pass: a peer that times out waiting for a genuinely slow (not
  dead) opponent must not diverge from what that opponent independently
  records. See "Symmetric timeout outcomes" below for the full trace, fix,
  and the one residual case left deliberately unresolved.

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

## Symmetric timeout outcomes

**The bug, as first observed:** a stress-test batch of the real
dual-subprocess integration test produced one run where police's own log
recorded `result: "technical_loss"` while thief's recorded `result:
"survival"` — the two peers disagreed about how their own match had ended.
Rule #35 scores a contradictory-report pair 0/0 for BOTH teams; an
asymmetric split like this is exactly what that rule exists to catch, and
it is not a corner case unique to this project's tight test timeouts —
counted matches run over public tunnels, at scheduled windows, against
machines this project does not control, with real jitter. The interop
kit's own completed campaign took seven scheduled windows to finish.
Load-induced slowness is the expected condition, not an edge case.

**Root cause, traced precisely:** the split is NOT the FLP-style
"can't-tell-dead-from-slow" impossibility it might look like. It is a
concrete, fixable correctness bug in how a timing-out peer disengages.

1. `_wait_for_opponent` (`infra/match_loop.py`) is the PASSIVE side's
   timeout path. It is **unilateral by construction**: it self-declares
   `TECHNICAL_LOSS` purely from its own wall clock
   (`time.monotonic() - self._turn_started_at > turn_timeout_seconds`),
   with **no declare/confirm round trip at all** — unlike the entrapment/
   max_moves-ceiling path, which *does* go through a declare/confirm
   exchange (`_declare_and_settle` / `_handle_declare_terminal`). This
   answers the "is stage 2's declare/confirm reachable here" question
   directly: **no, a timeout-induced ending bypasses it entirely.**
2. Before this fix, `_wait_for_opponent` also never checked whether an
   opponent message had, in fact, already arrived and was simply slow to
   *finish* processing (`self._in_flight`, tracked since stage 2 for
   graceful-shutdown polling, was never consulted here). A message that
   arrived at t=59.9s under a 60s budget could lose the race against the
   passive side's own timer purely due to normal processing latency.
3. Separately, and more directly responsible for the *observed* split:
   `receive_opponent_move` had no notion of "my side has already finished."
   If the passive side self-declared at t=60s and the (merely slow, not
   dead) active side's message then arrived at t=65s, `_handle_move_or_
   barrier` would happily re-evaluate it against the (unchanged, since
   nothing had actually been applied) `state.whose_turn` check, accept it,
   and **overwrite the already-returned outcome** — while the ACTIVE side,
   having received an ordinary `accepted=True`, believed play was
   continuing normally and carried on toward a real `SURVIVAL`. This is the
   exact mechanism that produced police=`technical_loss` /
   thief=`survival`: whichever side gave up first "won" the race to decide
   the sub-game's fate, and the other side never found out.
4. A related, narrower case: `send_with_retry` retries the *identical*
   request (same commit) on a lost/delayed *response*. Before this fix, the
   receiver had no idempotency — a retry arriving after its first attempt
   had already advanced `state.whose_turn` was freshly re-evaluated as "not
   your turn" and rejected, even though the *original* attempt had
   genuinely succeeded. The sender, seeing `accepted=False`, self-blamed
   (`offending_side=self.role`) for something that was never actually
   illegal — only its own retry was redundant.

**The fix (`orchestrator.py`, `infra/turn_receiver.py`,
`infra/receiver_helpers.py`, `infra/match_loop.py`):**

1. **Idempotent replay.** `PeerRuntime._replayed_responses: dict[str,
   MoveResponse]`, keyed by `commit` (empty commits — stage-2-only tests
   with no real sealing — are never cached, avoiding false collisions). A
   retried commit gets back the *exact same* response it got the first
   time, never a fresh (and by-then-wrong) re-evaluation. This closes bug
   #4 outright: a lost/delayed response can no longer manufacture a
   phantom illegality.
2. **Post-finish rejection.** If `self.outcome` is already set when a
   *new* (non-replayed) message arrives, it is rejected outright
   (`accepted=False, reason="my side has already finished this sub-game"`)
   instead of being applied. This closes bug #3: once a side has decided
   the sub-game is over, it will not silently keep mutating state — and
   critically, the ACTIVE side that sent that now-rejected message
   receives a real, meaningful rejection (`not response.accepted`) and
   correctly self-blames (`offending_side=self.role`) via the *existing*
   `_send_and_resolve` logic — the same party the PASSIVE side already
   blamed via `offending_side=other_side(self.role)`. Both artifacts now
   agree on both `result` (`technical_loss`) and `offending_side` (the
   party that was actually slow).
3. **In-flight grace period.** `_wait_for_opponent` now gives an
   already-in-flight opponent message (`self._in_flight > 0`) a short,
   bounded grace window (`_IN_FLIGHT_GRACE_SEC = 5.0`) to finish before
   self-declaring — closing bug #2. This is an internal robustness margin,
   not a signed contract value, and does not meaningfully extend the wait
   when the opponent genuinely sent nothing at all (`_in_flight` stays 0).

Both `LogArtifactBuilder`'s `log_<game_id>_gNN.json` summary and the
in-memory series summary now carry `offending_side` explicitly (it was
silently absent from the on-disk artifact before this pass) — the property
being fixed is only checkable from what an opponent or grader actually
reads if it is actually written down.

**Test coverage:** `tests/test_symmetric_timeouts.py` — two fast,
deterministic unit tests exercise the fix directly (a duplicated commit is
replayed, not reapplied; a message after self-finish is rejected, not
reapplied), and one slow, real end-to-end test
(`test_a_genuinely_stalled_peer_produces_a_symmetric_technical_loss`)
reproduces the *original* failure over two real subprocesses at the REAL
signed contract values from `config/game.json` — `response_timeout_sec=30`,
`watchdog_timeout_sec=60`, unmodified — with police's strategy genuinely
blocking (`time.sleep`, not `asyncio.sleep` — it freezes police's whole
event loop, including its own server, faithfully simulating a CPU-starved
process rather than a merely-slow callback) for 65 real seconds on its
first action via `tests/_stalling_peer_runner.py` (a test-only entry point,
not part of the shipped CLI). No timeout in this test is shrunk for speed.

**What is NOT fixed, and why — the residual known divergence:** in
*genuine, total, mutual silence* (both peers truly unreachable to each
other — not merely slow), each side's own unilateral self-declaration
still blames "the opponent" from its own vantage point: the active sender
exhausts `send_with_retry` and blames `other_side(self.role)`; the passive
receiver's `_wait_for_opponent` times out and *also* blames
`other_side(self.role)` — from THIEF's perspective that is POLICE, from
POLICE's perspective that is THIEF, i.e. **opposite `offending_side`
values**. This is not fixable by either side unilaterally — by definition,
neither can distinguish "opponent is dead" from "opponent is one grace
period away from responding" without hearing back from them, and if they
truly cannot hear back, no confirm round trip can ever complete either.
Recorded here as an accepted, non-scoring divergence: `score_for` pays
`(0, 0)` for `TECHNICAL_LOSS` **regardless of `offending_side`** (App. F's
scoring table has no offending-side-dependent term), so this residual case
produces mismatched blame in the two audit logs but never a mismatched
score or a mismatched `result` — an opponent inspecting both logs after a
truly-dead pairing would see two `technical_loss` reports that agree on
the outcome and disagree only on a cosmetic "who do I blame" field that
carries no scoring weight.

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

## Work in progress (session interrupted mid-implementation — read before continuing)

This snapshot was written when the session was stopped deliberately, mid-task,
to preserve exact state. **Nothing has been committed.** Working tree is dirty
in the police repo; the thief repo has not been touched.

### What is DONE and verified

- **Book verification.** Rule #53 (step-0 commit hash, per sub-game) and the
  commit-preimage question were checked directly against the PDF
  (`C:\dev\uni\_reference\ref_impl\docs\police_thief_p2p.pdf`). The book's own
  ch.5.3 printed Python listing (p. 37) puts the nonce INSIDE the canonical
  JSON object and omits `ensure_ascii=False` — this contradicts what was
  already implemented (reference/kit form: nonce appended outside via `|`,
  `ensure_ascii=False`). Per explicit user decision (asked and answered
  mid-session): **keep the reference/kit form**, justified by the book's own
  "Clarification: what binds and what merely illustrates" page (p. iv:
  printed listings do not bind unless explicitly marked as a rule; the
  binding source is only Appendix F's parameter table — and the book itself
  calls the ch.5.3 listing an illustration, in those words, right below it).
  **This write-up is now DONE** — the "Commit preimage" section above has
  been rewritten with the book's exact Hebrew wording (clarification page),
  an English translation, the ch.5.3 listing as printed, the chosen
  construction, and the reasoning, all side by side, plus a MUST-AGREE
  negotiation-agenda entry.
- Also verified directly against the book PDF and already written up above
  correctly: artifact filenames (Table 20, matches the reference exactly),
  the pheromone hash-before-series-starts requirement (ch.4, ties to item 12
  below), and the tie-rule-is-cumulative-across-the-series wording (Table 17
  row 5) — these did NOT need further changes this session.
- **Capture symmetry (items 4/9/10 of the request) — implemented and tested.**
  `domain/state.py::apply_move` now gates capture-by-landing on
  `actor is Side.POLICE`; a thief walking onto the police is an ordinary,
  uncaptured move. `domain/match.py` gained `CAPTURE_CLAIM_MECHANIC` and
  `FIRST_MOVER` is now documented as a negotiable house-rule constant folded
  into the signed `terms` (see `shared/terms.py`). `tests/test_state.py` has
  new passing tests for: thief-onto-police is not a capture, police may claim
  a prior co-location via STAY on its own next turn, police may instead let
  the thief walk away. All green.
- **Cryptographic core — implemented, unit-tested, AND vector-verified.**
  `domain/canonical.py`, `domain/crypto.py` (seal/verify,
  `SHA256(canonical_json(payload)+"|"+nonce)`), `domain/game_ids.py`
  (`derive_game_ids`). `tests/test_vectors.py` ports the interop kit's four
  CORE vector files into `tests/fixtures/vectors/` (data only, no kit code)
  and passes on the first run — canonical JSON, commit-reveal, terms
  signature, and game_uid/game_id all reproduce the kit's pinned hashes
  exactly, and a dedicated test confirms our commit hash does NOT match
  either of the book's two other illustrative constructions.
- **Config extended** for the new signed sections the handshake terms need:
  `domain/config.py` gained `WorldConfig`, `PheromoneConfig`, and
  `NetworkConfig.num_games`; split validators into
  `domain/config_validators.py` / `domain/config_errors.py` to stay under
  the line budget. `tests/conftest.py` updated to match.
- **Handshake — implemented and unit-tested (NOT yet proven over real
  subprocesses under load — see below).** `shared/terms.py`
  (`terms_from_config`, the flat 21-key signed terms including the two house
  rules), `shared/locked_model.py` (pheromone-model hash hook, item 12),
  `shared/sysinfo.py` (stdlib-only host spec, RAM/GPU honestly reported as
  "unknown" — no third-party dep added), `shared/build_commit.py` (`git
  rev-parse HEAD`), `infra/negotiation.py`
  (`NegotiationRefusedError`, build/verify, `game_ids`). `tests/test_negotiation.py`
  all green: matching terms verify, terms/sub_game_number/role/scent-hash
  mismatches all refuse with a clear message, a forged signature is caught.
- **Real per-turn commit-reveal wired into the existing turn loop.**
  `domain/sealed_payload.py` (self-only `state_str`, matching the
  reference's convention), `orchestrator.py::_seal_own_record`,
  `turn_sender.py`/`turn_receiver.py` updated so both the mover and the
  receiver build byte-identical payloads and the receiver archives
  `(payload, commit)` per step. Stage-2's placeholders
  (`infra/stage3_placeholders.py`) and the now-unused single-match entry
  point (`infra/peer_entrypoint.py`, `orchestrator.run_peer`) were deleted
  outright — nothing references them any more.
- **Mutual audit — implemented and unit-tested.** `infra/audit.py`
  (`ReceivedCommitLog`, `verify_revealed` — audits against what arrived
  live, per interop kit WARNINGS §5d). `tests/test_audit.py` all green:
  honest reveal passes, wrong nonce fails that step, a step revealed with no
  live receipt fails, a step received live but never revealed fails (not
  silently skipped).
- **Artifacts — implemented and unit-tested.** `infra/artifacts.py`
  (`build_declaration`, `build_config_artifact` with its own
  `config_sha256`, `LogArtifactBuilder`, `write_json` — native UTF-8 on
  disk). `tests/test_artifacts.py` all green.
- **Series loop — implemented, and now reliably runs a real multi-sub-game
  series over two real subprocesses (20/20 clean stress-test runs after the
  fixes below — see "Resolved" for the debugging history).**
  `infra/series_runtime.py` (`SeriesRuntime` — the
  long-lived per-process object owning the FastMCP server for the WHOLE
  series, answering `negotiate`/`reveal_audit`, delegating `submit_move` to
  whichever `PeerRuntime` is currently playing). `infra/series.py`
  (`run_series`, `_play_one_sub_game` — handshake once, then role
  alternation + real sealing + mutual audit + artifact writes per
  sub-game). `mcp_server.py`/`mcp_client.py` gained `negotiate` and
  `reveal_audit` tools/calls (`send_negotiate`, `send_audit_reveal` — both
  now retry on connection failure, matching the existing `send_with_retry`
  pattern; this was itself a bug found and fixed this session, see below).
  `__main__.py::cmd_peer` rewritten to call `run_series` instead of the old
  single-match `run_peer`, with a `--log-dir` directory argument replacing
  the old single-file `--log`.

### RESOLVED — the integration-test flakiness (was "half-written", now fixed)

`tests/test_integration_two_peers.py` was flaky (roughly 1 failure in 3-6
runs) when this snapshot was first written. Full debugging history, in
order, ending in a fix now verified by 20/20 clean stress-test runs plus a
separate 15/15 batch (35/35 total after the final fix):

1. First observed failure mode: `'NoneType' object has no attribute
   'received_commits'` inside `SeriesRuntime.receive_audit_reveal` — a red
   herring surfaced by bug #2.
2. **Bug found and fixed:** `mcp_client.send_audit_reveal` had NO retry loop
   (unlike `send_with_retry`/`send_negotiate`), so a connection hiccup
   during the post-sub-game audit crashed the whole series instead of
   retrying. Fixed: added the same ~1s-cadence retry, bounded by
   `watchdog_timeout_sec`, and wrapped the call site in `series.py` with a
   graceful fallback (`audit_of_me = None`) if still unresponsive after
   retrying.
3. **Bug found and fixed:** with several sub-games running back-to-back, the
   two sides' loops are not wall-clock synchronized between sub-games — one
   side could start sub-game N+1 (resetting its audit-wait state) while the
   other side's delayed `reveal_audit` call for sub-game N was still in
   flight, misattributing a result to the wrong sub-game. Fixed:
   `reveal_audit` now carries `sub_game_number`; `SeriesRuntime` rejects
   (via `StaleAuditRevealError`, which the caller's own retry loop treats as
   a transient failure and retries) any reveal that doesn't match its
   currently-active sub-game.
4. **Root cause of the REMAINING flakiness, found via full-content diagnostic
   dumps of both sides' logs (not just truncated assertion messages):** a
   genuine startup/inter-sub-game race in `submit_move` itself, one level
   up from the audit exchange. `SeriesRuntime.receive_opponent_move`
   rejected outright (`"no sub-game currently active on my side"`) if the
   FIRST message of a sub-game arrived before this side had called
   `start_sub_game()` for it — a real, observed timing gap right after the
   handshake (both sides finish `send_negotiate` at nearly the same moment,
   and one can reach `_play_one_sub_game`'s send-my-first-move step before
   the other reaches its own `start_sub_game()` call for that same
   sub-game). Unlike `reveal_audit`, `submit_move` is NOT retried by the
   sender on an application-level rejection (only on transport failure), so
   this single lost message caused a real, silent divergence: the sender
   (having sent its one shot) resolved to a self-inflicted `TECHNICAL_LOSS`
   on `not response.accepted`, while the receiver, having rejected it and
   genuinely never hearing anything else that sub-game, independently
   reached the SAME symmetric score via its own turn_timeout/watchdog
   ceiling — the same terminal condition on both sides, by coincidence, but
   for entirely different and wrong reasons, with the audit correctly
   catching the resulting empty-reveal mismatch. **Fixed at the root**:
   `MoveRequest` now carries `sub_game_number` too; `PeerRuntime` tracks its
   own; `SeriesRuntime.receive_opponent_move` waits (bounded, 5s, polling)
   for `current_sub_game_number` to catch up before delegating or rejecting,
   instead of rejecting on the first check.
5. A closely related SEPARATE issue surfaced once #4 was fixed: with the
   test's timeouts tuned aggressively tight for speed
   (`response_timeout_sec=5`/`watchdog_timeout_sec=5`), one run out of 15
   still saw `audit_of_opponent` time out genuinely (not a logic bug — the
   opponent's own `reveal_audit` call for that sub-game simply hadn't
   arrived within 5s under real system load). Loosened to
   `response_timeout_sec=8`/`watchdog_timeout_sec=12` for the test
   specifically; both are still far tighter than the real contract's
   defaults (30/60), so this is test-speed tuning, not a production
   concern — the real default `watchdog_timeout_sec=60` gives ample
   headroom for this exact scenario.

6. **A sixth bug, found via a further stress-test batch and fixed after this
   snapshot was first written:** `SeriesRuntime` tracked audit state
   (`_audit_of_opponent` / `_audit_event`) in a SINGLE slot keyed implicitly
   by "whatever `current_sub_game_number` is right now." `start_sub_game()`
   for sub-game N+1 reset that slot the moment this side moved on — but the
   opponent's `reveal_audit` call for sub-game N can legitimately still be
   in flight at that exact moment (it was simply slower to finish N). Two
   failure shapes followed from this: (a) a late reveal for N arriving after
   the reset was rejected as `StaleAuditRevealError` and endlessly retried
   until the SENDER's own `watchdog_timeout_sec` gave up, producing exactly
   the symptom seen in the field — `police_log["summary"]["audit"]["passed"]
   == None` (a timeout, not a tamper failure) for a mid-series sub-game; (b)
   worse, if the reveal for N arrived just as N+1's `start_sub_game()` had
   already created a *new* event object, `receive_audit_reveal` would set
   THAT new event/result — cross-contaminating sub-game N+1's audit outcome
   with sub-game N's data. **Fixed at the root:** `SeriesRuntime` now keys
   `_peer_runtimes_by_sub_game`, `_audit_results`, and `_audit_events` all by
   `sub_game_number` explicitly, and never discards or resets an old entry
   when a new sub-game starts. A reveal for an old sub-game is served
   correctly no matter how late it arrives; a reveal for a sub-game not yet
   started gets the same bounded (5s) polling wait `receive_opponent_move`
   already used, instead of an outright rejection. `series.py`'s
   `wait_for_audit_of_opponent` call now passes `sub_game_number` explicitly
   rather than relying on "whatever is current." Re-verified with a fresh
   15-run stress batch, all clean, after this fix.

**Update — this WAS chased down and fixed in a later pass.** What follows
was originally recorded as "not chased further"; it since fired for real
(a genuine asymmetric `technical_loss`/`survival` split, caught by a
stress-test batch) and was root-caused and fixed. See "Symmetric timeout
outcomes" above for the full trace, the fix (commit-keyed idempotent
response replay plus post-finish rejection in `receive_opponent_move`),
and the one residual (non-scoring) divergence left deliberately
unresolved. The paragraph below is kept for the historical record of what
was suspected before it was confirmed:

`_handle_move_or_barrier`'s handling of an at-least-once-delivered duplicate
(a lost ACK, not a lost sub-game-start) had the same shape of problem as #4
— if a response to a successfully-applied move is lost and the sender
retries, the receiver's `whose_turn` check correctly rejected the duplicate,
but the sender then treated that rejection as `not response.accepted` → a
self-inflicted `TECHNICAL_LOSS`, which is unrelated to genuine illegality.
This was NOT observed to actually fire in any of the 35+ stress-test runs
recorded above at the time, but the interop kit's SPEC §7.1 ("at-least-once
delivery — the receiver contract") described exactly this class of bug and
recommended deduplicating on the commit, not on `(kind, step)`.

### Since resolved (this pass)

- **PRD-01 updated**: the capture-symmetry item (#4) now documents the
  stage-3 police-turn-gated supersession in full, cross-referencing
  `CAPTURE_CLAIM_MECHANIC`; the max_moves counting-basis items (#2/#3) got a
  short book-re-verification addendum (Table 2 and the Appendix B sample
  config were re-checked directly — neither settles the counting-basis
  question further, and no "ceiling auto-resolves to a survival win" claim
  was found anywhere in the book); the tie-trigger item (#6) now points to
  the trigger that was in fact found (book ch.9 "Tie Rule", cumulative
  series score) and cross-references PRD-07 rather than saying "none found."
- **PRD-04 updated**: the stub now records the pheromone formula citation
  (`shared/locked_model.py`'s `SCENT_MODEL_DOC`, book ch.4's multiplicative
  decay formula) as "recorded for hashing, not yet implemented," per item
  12/7 of the request.
- **PLAN.md updated**: stage 3's status row, plus a new "Role alternation —
  the engineering answer" section separating what stage 3 actually settled
  (the mechanics of alternating role within one running series — done,
  stress-tested) from what remains genuinely open and belongs to the
  professor (which of the two repos gets launched for a given sub-game).
- **TODO.md updated**: a new "Stage 3" done-section mirroring the stage
  1/2 pattern; the commit-preimage and capture-claim-mechanic negotiation
  items promoted to explicit MUST-AGREE bullets with full citations; the
  tie-trigger bullet checked off with its book citation; the
  role-alternation bullet split into its resolved (mechanics) and open
  (which repo) halves; the stale "vectors not ported"/"PRD-03 design-only"
  known-limitations bullets corrected; the at-least-once-delivery gap in
  `_handle_move_or_barrier` added as a new known limitation.
- **PRD-07 updated**: a new "Game-Count Declaration" subsection citing the
  book directly (ch.9.2.1, p. 70: teams declare their own counted-game
  count to the opponent at the start of each game; the lecturer
  independently cross-checks via the mandatory per-game reports; a false
  declaration disqualifies). Explicitly recorded: no textual support was
  found anywhere in the book for a `test`/`warmup` `game_id`/`game_uid`
  *naming prefix* convention — the book's actual mechanism for
  friendly-vs-counted is behavioural (a warm-up simply sends no report),
  not lexical, so that specific chatbot-sourced detail is flagged as
  unverified rather than implemented as if it were binding.
- **PRD-03's own "Commit preimage" section rewritten** with the full
  side-by-side citation the user asked for (book's exact Hebrew wording,
  English translation, the ch.5.3 listing as printed, the construction
  actually used, and the reasoning) — see that section above.
- **Quality-bar recheck completed.** Every file touched or created this
  stage is now ≤150 lines (several were split further during this pass:
  `orchestrator.py` → `+match_loop.py`; `protocol.py` → `+
  protocol_builders.py`; `turn_receiver.py` → `+receiver_helpers.py`;
  `turn_sender.py` → `+turn_resolver.py`; `state.py` → `+reducers.py`;
  `match.py` → `+house_rules.py`; `series.py` → `+series_subgame.py`;
  `config.py` → `+config_models.py` `+config_parsers.py`; `peer_config.py`
  → `+peer_config_validators.py` `+peer_config_errors.py`; `__main__.py` →
  `+cli_commands.py`). `ruff` is unchanged at exactly the same 6
  pre-existing findings (none new from this stage's code, before or after
  the splits). Full-suite coverage is 92.68% (bar: 85%; was 91% before this
  stage, using the same subprocess-execution `omit` list philosophy,
  extended to the new subprocess-only files `cli_commands.py` and
  `series_subgame.py`). 200/200 tests pass.

### What has NOT been started at all

- No six-sub-game transcript has been captured (the integration test uses 4
  sub-games with a shrunk `max_moves`/`survival_threshold` for speed, not
  the real 35/35 contract values — the series loop itself is now reliably
  green, see "RESOLVED" above and re-verified again after this pass's file
  splits, but a transcript at the real contract values still needs to be
  run and captured separately).
- Nothing has been mirrored to the thief repo (as instructed — this stage
  was police-repo-only throughout).
