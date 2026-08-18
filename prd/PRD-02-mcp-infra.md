# PRD-02 — Basic FastMCP Infrastructure

## Goal

Split the single-process engine from stage 1 into two genuinely independent
OS processes that exchange purely geometric information over localhost. No
strategy, no cryptography, no natural language — the agents still speak in
numeric coordinates only, exactly as stage 1's domain layer already models
them. The point of this stage is proving the distributed *shape* of the
system works — turn-taking, timeouts, a formal state machine, two processes
that never touch each other's memory — before stage 3 adds the cryptographic
trust layer on top of it.

## In scope

- Two peers, each simultaneously a FastMCP **server** (exposing one tool the
  opponent calls) and a FastMCP **client** (calling the opponent's tool).
  No central server, no judge.
- Loading `config/<role>/game.toml` (new this stage) and enforcing the
  mandatory overlay rule against the signed `config/game.json`.
- A formal turn-protocol state machine with the exact transition table
  given below, rejecting any illegal transition immediately.
- Three independently-tracked timeouts (`response_timeout_sec`,
  `turn_timeout_seconds`, `watchdog_timeout_sec`) and a freeze-detection
  watchdog, so a silent opponent produces a controlled `TECHNICAL_LOSS`
  instead of a hang.
- A single Orchestrator/runtime object (`PeerRuntime` +
  `orchestrator.run_peer`) that is the sole entry point wiring the MCP
  transport to the domain engine — no decision logic, no low-level
  transport code of its own.
- `python -m uoh_mh01 peer --role {police,thief}`, runnable in two separate
  terminals, playing a full match to a terminal state over real localhost
  HTTP.
- A complete, timestamped match log at `logs/<role>_match.json` for stage
  6's replay viewer.
- Placeholder commit/verify functions that traverse the COMMITTING and
  VERIFYING phases without any real cryptography, clearly named and
  guarded by a test that fails on purpose if they're removed without
  replacement.

## Out of scope (later stages)

Commit-Reveal hashing, SHA-256, nonces (stage 3, PRD-03). Pheromones, scent
fields, belief maps (stage 4). Any LLM call, trash talk, verbal hints
(stage 5). GUI, replay viewer (stage 6). ngrok / public tunnels, Gatekeeper
rate limiting, Gmail (stage 7).

## Architecture

### Process separation (mandatory rules #1/#2)

Each peer is a single Python process started via `python -m uoh_mh01 peer`.
It loads `config/game.json` and its OWN `config/<role>/game.toml` only —
never the other role's directory. The only channel between the two
processes is the MCP transport: `infra/mcp_client.py` on one side calling
into `infra/mcp_server.py` on the other, over real HTTP on localhost. There
is no shared module holding live state, no shared file (each writes its own
`logs/<role>_match.json`), no global registry, and no object ever passed
directly between the two runtimes — `PeerRuntime` instances live in
different OS processes and cannot reference each other's memory even by
accident. `tests/test_integration_two_peers.py` spawns both peers as real
`subprocess.Popen` processes (not simulated in-process) specifically to
prove this, not just assert it.

### Configuration and the overlay rule

`shared/peer_config.py` loads `config/<role>/game.toml` with `tomllib` and
merges it with the parsed `config/game.json` via
`overlay_signed_contract(private, signed)` — a recursive dict merge where,
at every path present in both, the SIGNED value wins outright (private-only
keys are kept, signed-only keys are added). This is enforced generically,
not by trusting the TOML author to avoid touching signed fields: even a
private config that tries to redefine a real signed field under the same
path (e.g. `network_and_league.response_timeout_sec`) loses to the signed
value, and `tests/test_peer_config.py` proves this with a constructed
collision, not just a docstring claim.

`domain/config.py` gained a `NetworkConfig` (`response_timeout_sec`,
`watchdog_timeout_sec`) this stage — these are signed values needed for
stage 2's timeout logic, parsed the same validated way as every other
game.json field. `PeerConfig` (from the TOML side) carries `my_port`,
`opponent_url`, `turn_timeout_seconds`, `group_id`, `group_name`.

### The tool contract

One tool, `submit_move`, exposed by each peer's FastMCP server
(`infra/mcp_server.py`) and called by the opponent's FastMCP client
(`infra/mcp_client.py`). Pure geometric data, matching `move_set` and
barrier targets exactly as domain/ already represents them — nothing about
strategy or scoring crosses the wire:

```
submit_move(
    role: str,             # the MOVER's role: "police" | "thief"
    turn_number: int,
    action_type: str,      # "move" | "barrier"
    direction: str | None,     # required if action_type == "move"
    target_row: int | None,    # required if action_type == "barrier"
    target_col: int | None,    # required if action_type == "barrier"
) -> {
    "accepted": bool,
    "reason": str | None,
    "terminal": { "condition": str, "police_score": int,
                  "thief_score": int, "offending_side": str | None } | None,
}
```

The receiving side independently re-validates the move against its OWN copy
of `domain.rules` before applying it — it never trusts the sender's claim
that a move is legal. If its own check disagrees, it rejects
(`accepted: false`) and both sides converge on a symmetric technical loss.

### The state machine (mandatory rules #4/#5)

```
WAITING_FOR_OPPONENT -> {COMPUTING_MOVE}
COMPUTING_MOVE       -> {COMMITTING, TECHNICAL_LOSS}
COMMITTING           -> {AWAITING_REVEAL}
AWAITING_REVEAL      -> {VERIFYING, TECHNICAL_LOSS}
VERIFYING            -> {WAITING_FOR_OPPONENT}
TECHNICAL_LOSS       -> {}   (terminal)
```

Implemented exactly as given, in `infra/state_machine.py` — no edges added
or removed. Every legal transition succeeds; every illegal one raises
`IllegalTransitionError` immediately rather than leaving the machine in an
undefined state (`tests/test_state_machine.py` exercises all 7 legal and
all 20 illegal edges individually).

**This one state machine belongs to ONE side's own active-turn protocol —
not to "the match" as a whole.** See "Architecture decisions" below for why
that's the reading this implementation settled on, and what it implies.

### Timeouts and the watchdog (mandatory rules #6/#7)

Three distinct values, three distinct layers, never conflated:

| Value | Source | Scope | Enforced by |
|---|---|---|---|
| `response_timeout_sec` (30) | signed | one single network request | `mcp_client.send_move`, via `watchdog.call_with_timeout` |
| `turn_timeout_seconds` (180) | private | this peer's own patience for one whole turn | loaded but not yet independently enforced this stage — see "Open questions" |
| `watchdog_timeout_sec` (60) | signed | freeze detection across the whole match | `infra.watchdog.FreezeWatchdog`, checked every loop iteration and used as the retry ceiling for a slow-to-start opponent |

`call_with_timeout` wraps every network operation in `asyncio.wait_for` and
converts ANY failure — a real timeout or an underlying exception — into one
uniform `OpponentUnresponsiveError`, because FastMCP's own failure modes for
a dead opponent are not one consistent type (see "Architecture decisions").
`FreezeWatchdog.heartbeat()` is called after every state-machine transition
and every applied move; `assert_alive()` is checked at the top of every loop
iteration and raises `FreezeDetected` if too much wall-clock time has passed
with no progress at all — independent of whether the stuck code path went
through `call_with_timeout` in the first place.

### The Orchestrator (mandatory rule #3)

`orchestrator.PeerRuntime` is the sole owner of this peer's live match
state, state machine, and watchdog. `orchestrator.run_peer` is the sole
entry point: it starts the FastMCP server, drives `PeerRuntime.run_match()`,
and writes the log — it contains no decision logic (that's
`domain/strategies.py`, unchanged from stage 1) and no low-level transport
code (that's `infra/mcp_client.py` / `infra/mcp_server.py`). `domain/`
itself was not touched for transport reasons — it stayed importable and
testable with zero network dependency; `orchestrator.py` only calls its
existing pure functions (`apply_move`, `apply_barrier`, `next_turn`,
`actions_taken_by`, `is_thief_trapped`, `score_for`) as the same building
blocks stage 1's `domain.match.run_match` used, just invoked once per
network exchange instead of in one tight in-process loop.

## Architecture decisions

These are judgement calls made where the task text left real design space,
each reasoned from the given transition table and rules rather than
guessed — flagged here for review rather than asked about mid-task, since
none of them contradict anything explicit and all are contained,
revisable decisions within this codebase (not the signed contract).

1. **COMMITTING and VERIFYING are pure local computation; AWAITING_REVEAL is
   the one real network call.** The transition table itself is the
   evidence: `COMMITTING -> {AWAITING_REVEAL}` and `VERIFYING ->
   {WAITING_FOR_OPPONENT}` have no `TECHNICAL_LOSS` edge, while
   `COMPUTING_MOVE` and `AWAITING_REVEAL` both do. A phase that can fail
   from network trouble needs a failure edge; a phase that never touches
   the network doesn't. So `_stage3_placeholder_commit` is a local,
   never-failing function (build the payload shape), the actual
   `submit_move` call happens once, from AWAITING_REVEAL, and
   `_stage3_placeholder_verify` is a local, never-failing check of the
   response. This reading also explains why `VERIFYING` has no failure
   edge in stage 2 (nothing to fail — it's a placeholder), which is exactly
   the gap flagged in "Open questions" below for stage 3.

2. **Turn-passing is implicit in the message itself, not a separate
   notification.** There is no `your_turn` tool — receiving a `submit_move`
   call at all IS how a peer learns it's now active. Each side maintains
   its own local `domain.MatchState`, applies every move (its own AND the
   opponent's) to that same copy, and `WAITING_FOR_OPPONENT`'s only
   outgoing edge (`-> COMPUTING_MOVE`) means the passive side's own state
   machine never transitions at all while idly serving as a listener —
   processing an incoming call updates `MatchState`, not the recipient's
   `Phase`.

3. **Apply-then-notify, not notify-then-apply.** A peer applies its own
   decided move to its own state — and hands `whose_turn` to the opponent —
   *before* sending it, not after getting the opponent's acknowledgement.
   This was found the hard way during manual two-terminal testing: the
   first working version applied locally only after a successful response,
   which left a real race window where a fast opponent's reply could reach
   this side's server before `whose_turn` had actually flipped, and get
   wrongly rejected as "not your turn yet". Applying first (mirroring
   exactly what the receiving side already does: apply, flip, then
   respond/notify) closes it. If sending then fails, the score is
   unaffected either way (this side's own outcome was already legitimately
   decided under its own copy of the rules) — the peer just couldn't
   deliver a courtesy notification, which is logged and otherwise ignored.

4. **A connection failure is not the same as a slow response, and gets
   different handling.** Observed empirically (see below): connecting to an
   opponent whose server hasn't started listening yet fails FAST — not
   after the full `response_timeout_sec`. Left alone, this makes the two
   terminals fragile to ordinary startup-order variance. The fix: retry at
   a steady ~1s cadence, bounded by `watchdog_timeout_sec` rather than
   `response_timeout_sec` — which is exactly what "freeze detection before
   intervention" (rule #7) already means: don't intervene (declare a loss)
   on the very first failed attempt.

## FastMCP: the actual API found (not what was assumed going in)

FastMCP 3.4.7 was installed fresh for this stage (not previously a
dependency). Its API differs from older FastMCP tutorials in ways worth
recording:

- Server: `FastMCP(name)`, `@mcp.tool` (bare decorator works for both sync
  and async functions — sync tools run in a thread pool by default).
  Serving: `await mcp.run_http_async(transport="http", host=..., port=...,
  show_banner=False)`. Default `streamable_http_path` is `/mcp`, matching
  `config/<role>/game.toml`'s existing `opponent_url =
  "http://127.0.0.1:PORT/mcp"` convention exactly — no extra `path=`
  argument needed.
- Client: `async with fastmcp.Client(url, timeout=...) as client: result =
  await client.call_tool(name, kwargs, timeout=...)`. The deserialized
  return value is on `result.data` (not the raw MCP content blocks).
- **Failure modes for a dead opponent are not one consistent exception.** A
  failure during the initial connect surfaces as a plain `RuntimeError`
  ("Client failed to connect: All connection attempts failed"); a failure
  or timeout during an in-flight call surfaces as
  `mcp.shared.exceptions.McpError`. Neither is guaranteed. This is exactly
  why `watchdog.call_with_timeout` catches `Exception` broadly and
  re-raises one project-owned `OpponentUnresponsiveError`, instead of
  pattern-matching FastMCP's own exception types.
- A tool function that raises surfaces on the client as
  `fastmcp.exceptions.ToolError` (message: `"Error calling tool 'X':
  <original message>"`) when `raise_on_error=True` (the default), or as a
  `CallToolResult` with `is_error=True` when `raise_on_error=False`. Not
  used directly in this codebase (the tool contract expresses rejection
  through `accepted: false` in a normal return value, not by raising), but
  worth recording since it shaped that choice — an application-level
  rejection (illegal move) is not the same kind of event as a transport
  error, so it shouldn't look like one on the wire.

## Acceptance criteria

- [x] Two independent processes play a full match over real localhost HTTP,
      each computing the outcome from its own copy of the rules
      (`tests/test_integration_two_peers.py`, and the manual two-terminal
      run in the report).
- [x] Both processes agree on the same terminal condition, score, and full
      move sequence (asserted directly, not just eyeballed).
- [x] Every legal state transition succeeds; every illegal one raises
      immediately (`tests/test_state_machine.py`, all 7 legal + 20 illegal
      edges).
- [x] A silent/dead opponent produces `TECHNICAL_LOSS`, not a hang
      (`tests/test_orchestrator.py`, wrapped in an outer timeout as a
      test-correctness safety net).
- [x] The overlay rule is enforced in code and proven with a constructed
      collision, not just documented (`tests/test_peer_config.py`).
- [x] The COMMITTING/VERIFYING placeholders are clearly named, TODO'd for
      stage 3, and guarded by a test that fails on purpose if they
      disappear without replacement (`test_stage3_placeholders_still_present`).
- [x] `logs/<role>_match.json` records every action, every phase
      transition, timestamps, and the final terminal condition/score.
- [x] `domain/` remains importable and fully testable with zero network
      dependency (stage 1's 82 domain tests still pass unmodified).
- [x] `pytest` is green (142/142, including one real dual-subprocess run).

## Open questions

Carried forward from stage 1's running list, plus what stage 2 surfaced.
All flagged for opponent-group negotiation or for stage 3 to resolve
consciously, not silently.

8. **RESOLVED (Stage 2 corrections B3).** `turn_timeout_seconds` is now
   independently enforced — see "Stage 2 corrections" below.

9. **RESOLVED (Stage 2 corrections B1).** An entrapped side now declares
   entrapment explicitly via the same `submit_move` tool
   (`action_type == "declare_terminal"`) — see "Stage 2 corrections" below.

10. **RESOLVED (Stage 2 corrections B1/B2).** The max_moves ceiling is now
    declared and confirmed the same way as entrapment (B1); a sender that
    somehow violates its own budget anyway is caught by the independent
    counter check (B2) as an explicit divergence, not a generic rejection.

11. **RESOLVED, partially (Stage 2 corrections B3).** Graceful shutdown is
    now bounded polling on an in-flight-request counter plus a short fixed
    flush pause, replacing the blind 0.5s sleep — see "Stage 2 corrections"
    below for what is and isn't actually fixed by this.

## Stage 2 corrections (protocol intake + B1/B2/B3)

This section documents the second review round: two external sources were
studied (see PLAN.md "Revision" for the full sourcing and authority
ordering — the official reference implementation and the student interop
kit), and three concrete gaps in this PRD's own design were corrected. All
of it is implemented as of this round; `pytest` is green at 163/163
(up from 142), coverage 91% (bar: 85%), `ruff` clean against the
reference-aligned rule set (see TODO.md for the 6 remaining pre-existing
findings in code untouched this round).

### B1 — terminal conditions are DECLARED, never inferred from silence

**The problem, found independently by two sources.** This project's own
stage-2 design let one side privately decide a terminal condition
(`_finish` was called directly, synchronously, the instant a capture or
survival was locally detected) and separately let entrapment go completely
uncommunicated (PRD-02's own item 9 above). The interop kit's SPEC §3.1 and
§5c document the SAME class of bug reproduced *live*, three times, with no
fault injected, between two independently-written peers: a capture the
thief alone can observe (a barrier landing on its own cell, or having no
legal move left) settles as `capture` on the thief's side and `timeout` on
the police side, because the police never learns what happened — "two
honest peers... have just described one sub-game two ways", which is
exactly the contradictory-report shape App. E rule 35 zeroes for **both**
teams. This independently confirmed the concern was real, not
hypothetical.

**The fix.** Every terminal condition this peer detects on its own side —
capture (landing/barrier), survival, entrapment, and the max_moves
ceiling — is now a **claim**, never an immediate, trusted fact:

- A claim that accompanies a real move (capture/survival) piggybacks on
  the existing `submit_move` call: `MoveRequest` gained
  `claimed_condition`/`claimed_offending_side` fields, and `MoveResponse`
  gained `claim_agreement: bool | None` — the receiver independently
  recomputes the SAME check from its own locally-mirrored state (never the
  sender's word) and reports whether it agrees.
- A claim with NO accompanying move (entrapment, the max_moves ceiling)
  reuses the same tool as an `action_type == "declare_terminal"` message
  (named `concede` in the first cut of this correction, renamed in round 2
  below) — a deliberate design choice to avoid a second tool, mirroring how
  the reference's own thief reuses its ordinary capture-claim vocabulary
  for a rule-46/47 ending rather than inventing a new message type (interop
  kit SPEC §3.1: "nothing new is registered; a thief that stays silent here
  is simply not conforming").
- **On agreement**, both sides settle on the same condition and the same
  (independently recomputed, never transmitted-and-trusted) score.
- **On disagreement**, `DisputedOutcomeError` is raised on both sides;
  `MatchLogRecorder` gained a `disputed: {"mine": ..., "theirs": ...}`
  field so both logs record BOTH claimed conditions. No resolution is
  invented — per the task's explicit instruction, that is the rulebook's
  mutual-audit territory (stage 3), not this stage's.
- **A claim that never gets confirmed (opponent goes silent) does not
  self-finalize.** This is a real, documented trade-off: previously
  (stage 2's first cut), a mover's own already-decided outcome survived
  even if the opponent then vanished (`i_am_already_done` bypassed the
  retry-failure branch). That bypass is now REMOVED — any claim, including
  a legitimate one, that can't get a response within
  `watchdog_timeout_sec` resolves to a symmetric, unscored
  `TECHNICAL_LOSS(offending=other_side)`, exactly like an ordinary silent
  opponent. The alternative (letting an unconfirmed win stand) would mean
  scoring a claim nobody ever verified, which is precisely what this
  correction exists to stop doing elsewhere in the protocol — watchdog
  TECHNICAL_LOSS remains reserved for genuine silence, never the normal
  path for a legitimate ending, but "genuine silence in response to my own
  claim" is still genuine silence.

Implementation: `domain/terminal_detect.py` (pure, side-independent
detection — `detect_pre_turn` for entrapment/ceiling,
`detect_from_last_action` for capture/survival, callable identically by
the claiming side and the verifying side), `infra/outcomes.py`
(`DisputedOutcomeError`), `infra/turn_sender.py` / `infra/turn_receiver.py`
(the declare/confirm exchange on both sides). Tests:
`tests/test_terminal_detect.py` (pure detection logic),
`tests/test_terminal_declaration.py` (confirm/dispute exchanges via
`receive_opponent_move` directly).

### B2 — closing the apply-then-notify divergence window

**The problem.** Stage 2's race fix (apply-then-notify, PRD-02
"Architecture decisions" #3) closed the turn-flip race but left a
different edge: if a peer's local apply succeeds and the subsequent send
then fails after all retries, that peer's local state has advanced and the
opponent's has not — and nothing detected this divergence if the opponent
later somehow came back into contact.

**The fix.** Every `MoveRequest` (move, barrier, AND declare_terminal) now
carries the sender's own local `police_actions_taken`/`thief_actions_taken`
— a monotonic per-side action count — as of after the message's own effect
(or unchanged, for a declare_terminal). The receiver, before committing
anything, computes what its OWN local state's counts would be after the same
message and REJECTS on any mismatch (`MoveResponse.divergence`), without
applying the action and without mutating its own state. A divergence
resolves to an unscored `TECHNICAL_LOSS(offending_side=None)` — no single
side is attributable at the point a divergence is merely detected, which
required relaxing `score_for`'s previous hard requirement that
`TECHNICAL_LOSS` always name an `offending_side` (it never actually needed
one for the score itself — only for logging).

This is deliberately a *detection*, not a recovery, mechanism — per the
task's own framing, "detect divergence rather than continuing blindly" —
there is no attempt here to resynchronize or replay; a diverged pair simply
stops with a clearly attributable cause in both logs, which is what stage
3's stronger cryptographic guarantees (and the interop kit's own
at-least-once delivery / commit-based deduplication guidance, SPEC §7.1)
are for.

### B3 — `turn_timeout_seconds`, enforced, and a real drain instead of a blind sleep

`turn_timeout_seconds` (private, per-peer) is now checked independently of
`watchdog_timeout_sec` (signed, shared) in two places:

- **My own active turn** is wrapped in its own `asyncio.wait_for(...,
  timeout=turn_timeout_seconds)`; exceeding it self-forfeits
  (`TECHNICAL_LOSS(offending_side=self.role)`) rather than continuing to
  retry against the looser `watchdog_timeout_sec` ceiling.
- **Passively waiting on the opponent** now also checks
  `turn_timeout_seconds` (via `min(watchdog_timeout_sec,
  turn_timeout_seconds)` bounding each wait cycle) and self-declares the
  opponent's `TECHNICAL_LOSS` the moment MY OWN patience — not the shared
  watchdog's — runs out. This matches the reference's own documented
  semantics ("pausing longer than turn_timeout_seconds hands the opponent
  a technical win") more precisely than stage 2's original design, which
  only had the shared, looser `watchdog_timeout_sec` doing this job.

**A real limitation, not silently smoothed over:** neither self-forfeit
path can transition the formal state machine — whatever `Phase` was
reached when the timeout or the passive-wait ceiling fires has no
`TECHNICAL_LOSS` edge from most nodes in the mandatory table (e.g.
`COMMITTING -> {AWAITING_REVEAL}` only). Rather than adding an edge the
given table doesn't list (which "Implemented exactly as given... no edges
added or removed" forbids), both self-forfeit paths call `_finish`
directly, without a `_transition` call — the same precedent stage 2's
original entrapment pre-check already established for exactly this kind
of "decision made outside an active turn cycle" case. See TODO.md "Known
limitations".

**Graceful shutdown** (`run_peer`'s teardown) no longer pays a blind,
unconditional 0.5s sleep. It now polls an `_in_flight` counter
(incremented/decremented around every `receive_opponent_move` call) up to
a 2s cap, then a brief fixed 0.1s pause. This is bounded and responsive —
typically resolves in ~20ms when nothing is in flight — but is still, and
remains, a heuristic: the actual HTTP transport flush cannot be directly
observed from application code. A real handshake (an explicit "goodbye,
here is my final state" exchange) is still stage-3-appropriate work.

### Round 2 corrections: vocabulary, the unconfirmed-claim path, and a real uncaught-freeze bug

A second review pass, after B1/B2/B3 above had already landed, found one
naming problem and one genuine bug that round 1 introduced the *conditions*
for without actually being the thing that triggered it.

**Renamed `concede` → `declare_terminal`.** Entrapment scores
`capture_cop`/`capture_thief` — the thief is CAUGHT, not conceding — and
the wire-level `action_type` string appears verbatim in the match log and
will appear in the future `log_<game_id>_gNN.json` audit artifact, where
both a grader and an opponent's own verifier read it. `"concede"` misdescribes
that outcome. Checked both external sources for an existing name to match
rather than inventing one: neither the reference implementation nor the
interop kit's SPEC has a generic action-type string for this at all — both
instead reuse *field-level* vocabulary on their existing move message
(`claim_response`, `win_claim`) rather than naming a distinct action type.
So `declare_terminal` (the condition itself travels in the already-existing
`claimed_condition` field, unchanged) is this project's own neutral
choice, documented as such — not adopted from either source, because
neither source had one to adopt.

**The unconfirmed-claim path, checked precisely.** Two cases, checked
separately as asked:

- **Declared and CONTESTED** (the opponent's independent recomputation
  disagrees with my claim) — confirmed correct as built: `DisputedOutcomeError`
  on both sides, both claims logged, no silent resolution. Unchanged.
- **Declared and then SILENCE** (the opponent stops responding after my
  claim) — checked against `infra/turn_sender.py::_send_and_resolve`: the
  `except OpponentUnresponsiveError` branch was ALREADY calling
  `self._finish(TECHNICAL_LOSS, offending_side=other_side(self.role))`
  before this round — silence already correctly resolved to a reportable,
  symmetric technical loss, blaming the silent party. That part was not
  broken. What WAS missing: the claim itself was being thrown away —
  `_finish` never recorded what the superseded claim had been, so the log
  a grader or opponent would read showed only `technical_loss`, with no
  trace that this side had actually detected (say) a capture the instant
  before the opponent went dark. Fixed: `_finish` gained an
  `unconfirmed_claim` parameter, `MatchLogRecorder` gained a matching
  field, and the silence branch now passes the superseded claim through —
  the score is still always the symmetric technical-loss pair, never the
  claimed outcome, but the claim is no longer lost from the audit record.

**The actual bug this pass found: `FreezeDetected` was never caught
anywhere.** Tracing "can a match end with no reportable terminal condition
at all" turned up a real gap, broader than the declared-then-silent case
above and present since round 1 (not introduced by it): `FreezeWatchdog.
assert_alive()` — checked at the top of every `run_match` loop iteration —
raises `FreezeDetected` when no heartbeat has landed for longer than
`watchdog_timeout_sec`, but `run_match`'s `try/except` never had a clause
for it. At DEFAULT config values (`turn_timeout_seconds` 180 >
`watchdog_timeout_sec` 60), a genuinely silent opponent on ITS OWN turn —
no claim in flight at all, just plain silence — is caught by neither the
active-turn budget (it isn't my turn) nor `_wait_for_opponent`'s own
`turn_timeout_seconds` check (the watchdog is the TIGHTER of the two at
those defaults, so the turn_timeout check never trips first), so
`FreezeDetected` fires and propagates as a bare, uncaught exception —
crashing the process instead of producing a `TECHNICAL_LOSS`. `run_match`
now catches `FreezeDetected` and resolves it to
`TECHNICAL_LOSS(offending_side=self.state.whose_turn)` — whichever side
currently holds the turn is the one that failed to act or respond within
every narrower timeout. This is the actual, concrete instance of "the
protocol didn't resolve" that rule #35 has no provision for; every code
path now reaches a `MatchOutcome` or one of the two explicitly-unscored,
still-reported exceptions (`UndefinedOutcomeError`, `DisputedOutcomeError`)
— never a bare crash.

Implementation: `orchestrator.py` (`run_match`'s new `except FreezeDetected`
clause, `_finish`'s new `unconfirmed_claim` parameter), `infra/match_log.py`
(`unconfirmed_claim` field), `infra/protocol.py` /
`infra/turn_sender.py` / `infra/turn_receiver.py` (the rename). Tests:
`tests/test_orchestrator.py::test_freeze_detected_with_no_narrower_timeout_still_resolves_to_technical_loss`
(reproduces the exact default-config-shaped scenario),
`tests/test_orchestrator.py::test_unconfirmed_claim_after_opponent_silence_is_recorded_in_the_log`.

### Updated acceptance criteria (round 2)

- [x] `action_type` is `declare_terminal`, not `concede`, everywhere on the
      wire and in the log; no test or doc references the old name as
      current (a few explicitly note it as the prior, renamed-from name).
- [x] A claim followed by genuine opponent silence resolves to a reportable
      `TECHNICAL_LOSS(offending=other_side)` — confirmed already correct,
      not re-fixed — AND the superseded claim is recorded in the log
      alongside it.
- [x] A test reproduces the DEFAULT-CONFIG-shaped freeze scenario
      (`turn_timeout_seconds` looser than `watchdog_timeout_sec`, opponent
      silent on its own turn) and asserts a `TECHNICAL_LOSS` outcome, not an
      unhandled `FreezeDetected` exception.
- [x] No test in the suite can end a `run_match()` call with neither a
      returned `MatchOutcome` nor one of the two explicitly-unscored raised
      exceptions (`UndefinedOutcomeError`, `DisputedOutcomeError`) —
      `FreezeDetected` is no longer one of the ways `run_match()` can exit.

### Updated acceptance criteria (Stage 2 corrections)

- [x] An entrapped thief's opponent learns the correct terminal condition
      and score — not a `FreezeDetected`-driven technical loss — verified
      directly (`tests/test_terminal_declaration.py`).
- [x] A deliberately constructed disagreement between two sides'
      independent recomputations raises `DisputedOutcomeError` on both
      sides, and both logs record both claimed conditions.
- [x] A deliberately wrong action-counter claim is rejected as a
      divergence, without mutating the receiver's state, before any claim
      comparison happens.
- [x] `turn_timeout_seconds` set strictly smaller than `watchdog_timeout_sec`
      produces a `TECHNICAL_LOSS` bounded by the SMALLER value, tested for
      both the active-turn and the passive-wait cases independently.
- [x] `orchestrator.py` is back under 150 lines (was 264; is 148); every
      other file touched this round is likewise under the budget except
      `domain/config.py` (176, untouched this round, flagged in TODO.md).
- [x] `ruff check` is clean against a rule selection matching the
      reference implementation's own `pyproject.toml`
      (`E,F,W,I,N,UP,B,C4,SIM`, `E501` ignored) for every file touched
      this round.
- [x] Test coverage is 91% (bar: 85%), using the same "omit
      subprocess-only-exercised entry points" convention the reference's
      own `pyproject.toml` uses.
