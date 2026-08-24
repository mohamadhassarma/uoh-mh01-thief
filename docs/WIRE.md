# WIRE.md — the in-game turn-exchange contract

Status: **partially implemented.** This documents the TARGET contract,
extracted from the two external sources, and §9 tracks exactly how far the
implementation has got. The message shape, the state model and the audit now
conform; the transport does not yet. `tests/test_turn_conformance.py` pins the
whole contract — 16 cases pass, 2 remain `xfail(strict=True)` for the
transport.

## Sources and authority

| Source | Local copy | Version pinned |
|---|---|---|
| Professor's reference implementation | `_reference/ref_impl` | `github.com/rmisegal/Game-P2P-Cop-Chase` tag **v3.0.0** (`960499f`) |
| Student interop kit | `_reference/interop_kit` | `github.com/Imreec/copthief-league-protocol` main, 2026-08-13 (`ad65576`) |

**Where the two disagree, the reference implementation wins.** Disagreements are
listed explicitly in [§8](#8-where-the-two-sources-disagree).

---

## 1. The four MCP tools

| Tool | Argument name | Returns | Required? |
|---|---|---|---|
| `negotiate` | `message` | `{"ok": True}` | REQUIRED |
| `receive_turn` | `message` | `{"ok": True}` | REQUIRED |
| `submit_audit` | **`payload`** | `{"ok": True}` | REQUIRED |
| `receive_control` | `message` | `{"ok": True}` | OPTIONAL |

- Reference: `ref_impl/src/police_thief/infra/mcp_server.py:51-73` — all four
  handlers are three lines: put on a queue, return `{"ok": True}`.
- Kit: `interop_kit/SPEC.md:1004-1009` (the tool table),
  `interop_kit/sparring/transport/client.py:24`.

**The `payload`/`message` asymmetry is load-bearing**, not an inconsistency.
`ref_impl/src/police_thief/infra/mcp_client.py:37-38` encodes it in one
expression; the kit repeats it at `sparring/transport/client.py:99`.

**Every handler acknowledges only.** No tool returns game data. A handler that
does work before returning can deadlock two peers that are each awaiting the
other inside a handler (`interop_kit/sparring/transport/server.py:5-8`).

---

## 2. TurnMessage

`ref_impl/src/police_thief/domain/protocol.py:12-40`. Ten keys, six required.

| # | Field | Type | Required | Reference line |
|---|---|---|---|---|
| 1 | `step` | non-negative `int` | **REQ** | `protocol.py:20` |
| 2 | `sender` | `"police"` \| `"thief"` | **REQ** | `protocol.py:21` |
| 3 | `hint` | `str`, ≤ `hint_max_words` words, may lie | **REQ** | `protocol.py:22` |
| 4 | `smell_grid` | `dict` `"r,c"` → number | **REQ** | `protocol.py:23` |
| 5 | `commit` | 64-char **lowercase** hex | **REQ** | `protocol.py:24` |
| 6 | `timestamp` | non-empty ISO-8601 `str` | **REQ** | `protocol.py:25` |
| 7 | `barrier_placed` | `[r, c]` \| `null` | opt | `protocol.py:26` |
| 8 | `capture_claim` | `[r, c]` \| `null` (police only) | opt | `protocol.py:27` |
| 9 | `claim_response` | `{"claim": [r,c], "caught": bool}` \| `null` | opt | `protocol.py:28` |
| 10 | `win_claim` | `{"type": "survival"}` \| `null` | opt | `protocol.py:29` |

Kit agreement: `interop_kit/vectors/turn_message.json` → `turn_message.required`
lists exactly fields 1–6 and `.optional` exactly 7–10.

### 2.1 What is NOT on this wire — the load-bearing omission

**The mover's move, direction and position are absent.** They are sealed inside
`commit` and disclosed only at the end-of-game audit
(`ref_impl/src/police_thief/domain/protocol.py:16-18`: *"True position/move/verdict
are NOT here in the clear; they are sealed inside `commit`"*).

The only knowledge a peer ever gains about its opponent is: the NL hint, the
smell grid, declared barriers, and claims — `ref_impl/src/police_thief/peer/turn_handler.py:4-7`.
The receiver never reconstructs the opponent's board position; it diffuses its
belief grid and absorbs the smell (`turn_handler.py:45-49`).

Also not on this wire (`interop_kit/SPEC.md:1015-1023`): no step-0 tool, no
step-0 turn (the spec declaration rides in `negotiate` under `identity`, and the
sealed step-0 record is disclosed inside `submit_audit`), and no `hello`.

### 2.2 `step` is a ROUND

`interop_kit/SPEC.md:1025-1027` and `vectors/turn_message.json` →
`turn_message.field_notes.step`: each peer numbers its OWN chain `1..max_steps`;
a step is one action from **each** side, so `max_steps: 35` means 35 moves each.
The reference maps `max_steps` from `survival_threshold`
(`ref_impl/src/police_thief/shared/config.py:55`).

---

## 3. Inbound validation — decided BEFORE any state change

`interop_kit/vectors/turn_message.json` → `validation` (7 cases) and
`validate_before_applying`. An inbound turn is adversarial input; a partially
applied bad turn cannot be rolled back.

| Case | Verdict |
|---|---|
| Full ten-key set, nulls explicit | accept |
| Unknown extra key present | **accept** — ignored (the extension seam) |
| `timestamp: ""` | refuse — required non-empty str |
| `commit` key missing | refuse — never defaulted |
| `commit` uppercase hex | refuse — compared as a string, case is a divergence |
| `smell_grid` value stringified (`"0.9"`) | refuse — required dict of `"r,c"` → number |
| `step` negative | refuse — required non-negative int |

⚠️ The empty-`timestamp` refusal is called out in the fixture as load-bearing:
the kit's own sparring peer sends `timestamp: ""`, so **every one of its turns is
rejected by a strictly conformant receiver.** A pair may agree to tolerate it, but
both must.

---

## 4. Transport model: symmetric push, then poll your own inbox

`interop_kit/SPEC.md:1011-1013`: *"Each side CALLS the other's `receive_turn`
with its own turn and polls its own inbox for the other's. Neither peer can be
purely passive."*

Reference mechanics:

- **Inboxes** — four `queue.Queue`s (`agreements`, `turns`, `audits`, `controls`),
  filled by the MCP tools, drained by the runtime
  (`ref_impl/src/police_thief/infra/mcp_server.py:37-44`).
- **Send** — `send_turn(message)` pushes and returns `None`; it does **not**
  return the opponent's move (`mcp_client.py:64-65`).
- **Receive** — `poll_turn(timeout)` pops from *my own* `turns` queue, returning
  `dict | None` (`mcp_client.py:67-71`).
- **Retry** — `_call_with_retry` loops until a deadline, sleeping `retry_interval`
  (default **1.0 s**) between attempts, then raises `SimulationError`
  (`mcp_client.py:42-55`). Default `connect_timeout` **60 s**; `submit_audit`
  **10 s**; `receive_control` **2 s** (`mcp_client.py:24-32`).

### 4.1 The turn loop

`ref_impl/src/police_thief/peer/runtime.py:101-129`:

```
timeout = network.turn_timeout_seconds
poll    = network.poll_interval_seconds   # default 0.5
deadline = now + timeout
while result is None:
    broadcast status; drain control channel
    incoming = transport.poll_turn(poll)
    if incoming is None:
        if now > deadline: result = ("timeout", my_role)   # opponent silent
        continue
    deadline = now + timeout                               # reset on every turn
    outcome = handler.process(TurnMessage.from_dict(incoming))
    ...  -> win / caught / else take my turn (compute, seal, send)
```

- **Thief moves first**, unconditionally, before the loop
  (`runtime.py:92-93`).
- A silent opponent yields `("timeout", my_role)` — the waiting side claims it
  (`runtime.py:116`).
- Being caught still sends a final mandatory message before settling
  (`runtime.py:126`, `peer/turn_sender.py:72-77`).

### 4.2 Handshake cadence: once per SUB-GAME, not once per series

`interop_kit/sparring/netplay.py:9`: *"**The handshake runs per sub-game**, and
a greeting that fails the pairing check is refused on the record rather than
accepted."* Confirmed by the loop itself (`netplay.py:119-127`): `handshake(...)`
is called inside `for n in range(1, sub_games + 1)`.

Costed us a live series. Negotiating once and playing all six sub-games off
that agreement produced a clean sub-game 1 and then, for sub-game 2,
`SPAR-N09: handshake budget exhausted; our counterpart never arrived` — they
were waiting for a greeting we were never going to send. Nothing in a
same-implementation test can catch this: if both peers greet once, both agree.

What varies per greeting, and what must not:

| Field | Per sub-game | Why |
|---|---|---|
| `role` | **varies** | roles alternate (`role_for(natural, n)`) |
| `sub_game_number` | **varies** | it is the pairing check (SPAR-N06) |
| `nonce`, `signature` | **varies** | fresh each greeting |
| `terms` | fixed | a difference is mid-series drift, not renegotiation |
| `game_id`, `game_uid` | fixed | see below |
| opponent `group_id` | fixed | one series, one opponent (`netplay.py:132-140`) |

`game_uid` is safe to pin across re-negotiation because its derivation reads
**only** the flat negotiated terms and the two sorted group ids — never the
nonce, the signature, the role or the sub-game number
(`domain/game_ids.py:19-41`). `game_id` is a pure function of the same sorted
group ids, so it cannot vary per sub-game either.

From sub-game 2 onward the greeting **declares** the derived `game_uid`
(SPEC §7.3, `sparring/negotiate.py:60-68`); first contact cannot, because the
derivation needs the opponent's group id that first contact is what supplies.
If both sides declare and the two derivations differ, refuse (SPAR-N10) — it
is the only moment a wrong-input uid can surface, since the uid never crosses
the wire again. **Omission never refuses**, in either direction.

Tolerance, per the standing rule: a peer that greets only **once** per series
is also legal, and silence at a later sub-game boundary falls back to the
pinned agreement rather than failing.

---

## 5. `submit_audit` — AuditPayload

`ref_impl/src/police_thief/domain/protocol.py:68-81`. Three required keys:

| Field | Type | Line |
|---|---|---|
| `sender` | `"police"` \| `"thief"` | `protocol.py:72` |
| `records` | `[{"payload": {...}, "nonce": str, "commit": str}]` | `protocol.py:73` |
| `result_claim` | `"capture"` \| `"survival"` \| `"timeout"` | `protocol.py:74` |

Kit agreement: `vectors/turn_message.json` → `audit_payload.required`.

**`result_claim` is the LEAGUE's vocabulary, not ours.** Our engine
distinguishes three capture families internally - `capture_landing`,
`capture_barrier`, `capture_entrapment` - matching the three the interop SPEC
names (SPEC.md:153-190: co-location, rule 46, rule 47). The league has one word
for all three: SPEC.md says they all "settle CAPTURE" and puts the distinction
in `claim_response`, and the reference emits a single `"capture"`
(`ref_impl domain/scoring.py:13`, `peer/runtime.py:122`/`:127`).
`domain/scoring.to_wire_result` is the only sanctioned way to produce this
string; `.value` on a TerminalCondition is not. We shipped `capture_landing`
here for six sub-games against a live opponent before this was caught - a
conforming peer scores an unrecognised result 0/0 to both sides
(`ref_impl domain/scoring.py:25-31`), so two honest peers would have described
one sub-game two ways.

**Open divergence, not yet resolved.** We also emit `"technical_loss"` and
`"tie"`, which are NOT in the reference's result vocabulary (its non-terminal
strings are `timeout`, `tamper_forfeit` and `stopped`; in the book,
`technical_loss` is a *scoring config key*, not a result). Both score 0/0 on
either reading, so this is a labelling question rather than a scoring one, and
mapping ours onto theirs needs a decision we have not made: our TECHNICAL_LOSS
covers watchdog timeouts, turn-budget overruns and protocol divergence, which
the reference would split between `timeout` and `tamper_forfeit`. Neither
string has ever actually been emitted in a real series.

**`records` is the FULL sealed chain including payloads and nonces**, so the
opponent re-hashes every step with its own serializer
(`vectors/turn_message.json` → `audit_payload.field_notes.records`). The
verifier is `ref_impl/src/police_thief/domain/crypto.py:49-65`, which reads
`record["payload"]`, `record["nonce"]`, `record["commit"]` and returns
`{"passed", "verified_steps", "failed_steps"}`.

Exchange is push-then-poll like turns, and **best-effort**: the send failure is
suppressed because the opponent may exit right after reading its inbox, and their
payload may already be sitting in ours (`mcp_client.py:99-108`). Skipped entirely
for `timeout`/`stopped` results (`peer/summary.py:11,49`). A failed audit is a
`tamper_forfeit` won by the honest peer (`summary.py:54-57`).

---

## 6. `receive_control` — ControlMessage

`ref_impl/src/police_thief/domain/protocol.py:43-65`.

| Field | Type | Default | Line |
|---|---|---|---|
| `kind` | `"enable"` \| `"status"` \| `"restart"` \| `"quit"` | — | `protocol.py:52` |
| `sender` | `"police"` \| `"thief"` | — | `protocol.py:53` |
| `sub_game_number` | `int` | `1` | `protocol.py:54` |
| `status` | `str` (`WAITING`/`THINKING`/`PLAYING`/`PAUSED`/…) | `""` | `protocol.py:55` |
| `step_budget` | `float` | `0.0` | `protocol.py:56` |
| `payload` | `dict \| None` | `None` | `protocol.py:57` |

Optional and **opt-in**: active only once *both* peers send `kind="enable"`
(`peer/control_link.py:32-35`). Not part of the sealed game record
(`protocol.py:45-48`). Polled non-blocking via `poll_control()` →
`get_nowait()` (`mcp_client.py:80-85`); sent best-effort with errors suppressed
so a departed opponent never stalls the loop (`mcp_client.py:73-78`).

`ControlMessage.from_dict` **filters unknown keys** (`protocol.py:62-65`) — unlike
`TurnMessage.from_dict`, see §8.

---

## 7. Canonical serialization and the commit

`ref_impl/src/police_thief/domain/crypto.py:20-31`:

```python
canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
commit    = sha256(f"{canonical}|{nonce}").hexdigest()
```

A **single** `|` separator (`interop_kit/SPEC.md:242-245` spells this out; both
`||` and bare concatenation fail every handshake with nothing to debug).
`ensure_ascii=False` is mandatory — the opponent re-hashes your revealed `hint`
text at audit, so escaping non-ASCII fails every non-ASCII step and costs both
sides the match (`interop_kit/SPEC.md:81,86-90`). Floats must use shortest
round-trip repr (`SPEC.md:91-96`).

**The TurnMessage itself is never hashed.** `commit` on the wire is the hash of a
*different, private* structure — the sealed step record built by
`ref_impl/src/police_thief/peer/sealing.py:66-91`, whose payload carries
`step`, `state`, `position`, `move`, `intent`, `verdict`, `hint`,
`prompt_discussion`, `model`, `tokens_step`, `tokens_total`,
`response_seconds`, `random_move`.

---

## 8. Where the two sources disagree

| # | Point | Reference (**authoritative**) | Kit | Note |
|---|---|---|---|---|
| 1 | Unknown keys on an inbound TurnMessage | **Refused.** `from_dict` does `cls(**data)` → `TypeError` (`protocol.py:34-40`) | **Tolerated and ignored** — `from_dict` filters to known fields (`sparring/proto/messages.py:33-35`); `vectors/turn_message.json` marks the unknown-key case `accept` | Direct contradiction. The kit's spec calls tolerance "the extension seam"; the reference implements strict rejection. Following the reference means **any extra key we send is fatal.** |
| 2 | `smell_grid` / `timestamp` optionality | **Required** — no dataclass default (`protocol.py:23,25`) | Implementation gives both defaults (`messages.py:22-23`), but its own vector lists both as required | The kit's *code* is looser than the kit's own *spec*. Spec and reference agree; the kit's code is the outlier. |
| 3 | Empty `timestamp` | Would be accepted by the dataclass (type only) | Vector explicitly **refuses** it, and notes the kit's own peer emits `""` | The kit is stricter here than the reference. The kit's own sparring peer violates its own vector. |

Points 1 and 3 mean the kit's sparring peer and a strictly-reference-conformant
receiver **cannot complete a series against each other** without a mutually
agreed tolerance. That is a property of the external sources, not of our code.

---

## 9. Migration state — COMPLETE

Pinned in `tests/test_turn_conformance.py` (19 passing, **zero** `xfail`) and
`tests/test_series_handshake.py` (11 passing).

### The message-shape layer

- `infra/turn_message.py` — the ten-key `TurnMessage`, `WIRE_FIELDS`, and
  `validate_turn_message(message, *, strict=True)` implementing §3's refusal
  table.
- `infra/turn_message_builders.py` — `build_turn_message()` (emit: exactly the
  contract, real timestamp, strictly self-validated before it can reach the
  wire) and `parse_turn_message()` (receive: unknown keys ignored, empty
  timestamp accepted).
- `infra/protocol_errors.py` — `ProtocolError` extracted so both schemas raise
  the **same** class without an import cycle.

Asymmetric strictness (§4) is implemented and each tolerance is justified
inline against the source line it deviates from.

### The state model and the audit

- `domain/own_state.py` — `OwnGameState` holds MY position only; the opponent
  is a belief grid and nothing else. `own_view()` projects the simulator's
  omniscient `MatchState` down to one side so brains see the same restricted
  surface in both paths. `_OpponentPositionGuard` is deleted: a type without
  the field beats a guard on a type that has it.
- `infra/turn_receiver.py` — gutted to four jobs: record the commit, note a
  declared barrier, fold hint+smell into belief, resolve claims.
- `domain/terminal_detect.py` — peer path resolves capture via
  `capture_claim`/`claim_response` and survival via `win_claim`. Entrapment
  and capture-by-barrier are RETAINED but gated to the simulator (PRD-01).
- `infra/audit.py` — the opponent reveals `[{payload, nonce, commit}]` and we
  re-hash against the commit that arrived LIVE. `sender_position` and the
  opponent-side payload reconstruction are deleted, along with the counter
  divergence check that only the mirror made possible. A pass additionally
  requires `verified_steps > 0` **and** `verified_steps == steps played` — "no
  failures" is vacuously true of an audit that verified nothing.
- **Step 0 is disclosure-only.** `_SealingMixin.seal_step_zero()` seals the
  host-spec declaration (rule #53) before the first move of every sub-game, so
  it rides in the reveal and is re-hashable. It is never transmitted as a turn,
  so `verify_revealed` checks it for self-consistency only and excludes it from
  the played-step count (§2.1, kit SPEC §7.5 `not_on_this_wire`).

### The transport

- `infra/mcp_server.py` — all four tools are ack-only: one `append`, then
  `{"ok": True}`. Nothing validates or computes inside a handler.
- `infra/inboxes.py` — the four queues plus `poll`/`poll_now`. `drain_stale()`
  clears **controls only**; dropping turns, audits or agreements would discard
  an opponent's legitimately-early next-sub-game message that nothing can
  re-request.
- `infra/mcp_client.py` — every send returns `None`; `submit_audit` takes
  `payload`, the other three take `message`.
- `infra/match_loop.py` — polls its own turns inbox; control traffic is
  fire-and-forget so advisory sends can never sit on the critical path.
- `infra/series_handshake.py` — the per-sub-game handshake of §4.2, with the
  series identity pinned from the first agreement.

### Verified against a foreign implementation

A full six-sub-game series against the interop kit's sparring peer
(`--scent-model multiplicative_book_v1`) settles clean in both directions: all
six audits Verified OK on their side, `passed: True` with `failed_steps: []`
and `reason: None` on ours, our `verified_steps` equal to their sealed step
count in every sub-game, and both sides independently deriving the identical
`game_uid`.
