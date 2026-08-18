# PRD-04 — Pheromones, Scent Field and Belief Map

## Status

Implemented. `domain/scent.py` (emission + decay), `domain/belief.py`
(Bayesian belief map + hint-fusion interface), wired into the per-turn wire
message and the sealed commit-reveal record.

## Goal

Give both peers the one information channel the game actually provides
about a hidden opponent: a decaying scent field, transmitted each turn and
fused into a probabilistic belief map over the board — replacing the exact
geometric facts stages 1–3 exchanged with something genuinely uncertain,
per Dec-POMDP's own `Ωᵢ`/`O` observation model (book ch.1).

## In scope

- **Scent emission and decay** (`domain/scent.py`), per the book's own ch.4.3
  formula — see "The book's decay formula" below for the full verification
  and "The interop kit's disputed kernel" for what the printed formula
  leaves under-specified and how it is resolved.
- **Belief map** (`domain/belief.py`): a normalized probability distribution
  over every board cell, updated from the opponent's transmitted scent field
  each turn, masked to reachable (non-barrier, in-bounds) cells at every
  step — never *usually* masked, structurally so (see "Belief map design").
- **Hint-fusion interface, not hint decoding**: `belief.HintClaim` and
  `belief.apply_hint` give a future strategy module a place to fold in an
  *already-parsed and already-weighted* opponent claim. Parsing free-language
  text into a claimed cell, and deciding how much to trust/discount/invert
  a given hint, are both stage 5's job — this stage only has to not assume
  a hint is truthful, which it doesn't (weight defaults to 0 — ignored).
- **Sealing**: the scent field is part of the sealed commit-reveal payload
  (`domain/sealed_payload.py::build_move_payload`'s `smell_grid` key), sent
  live alongside the move (this project's existing wire shape reveals the
  move live and withholds only the nonce until audit — see PRD-03 — so
  `smell_grid` follows the same pattern, not a new reveal phase). A grid
  that differs between what was sent live and what a dishonest sender later
  claims it sealed is caught by the existing mutual audit re-hash, with no
  new sanction path needed.
- **Wire fields**: `MoveRequest` gains `smell_grid: dict[str, float] | None`
  and `hint: str` (`infra/protocol.py`, `infra/protocol_builders.py`,
  `infra/mcp_server.py`'s `submit_move` tool signature). `hint` defaults to
  `""` — no strategy exists yet to populate it, but the wire and sealing
  plumbing exists now so stage 5 needs no protocol change to use it.
- **Locked-model declaration upgraded to the interop kit's real schema**:
  `shared/locked_model.py::SCENT_MODEL_DOC` now matches the kit's own
  4-key `{family, name, params, example}` doc shape (SPEC §7) instead of the
  ad-hoc `{family, name, formula, example}` shape recorded in stage 3 before
  this stage's model existed — see "Locked-model schema upgrade" below for
  why, and the vector check that resulted from it.

## Out of scope

Strategy and move selection (stage 5) — nothing in this stage reads the
belief map or a hint to make a decision; both are exposed for stage 5 to
consume. Lie detection (stage 5, explicitly — see "Hint fusion" above). LLM
anything (stage 5). GUI heatmap visualization (stage 6) — the belief map is
a plain `dict[Position, float]`, structured so a heatmap can render from it
without reshaping the data, per this stage's own requirement.

## The book's decay formula

Verified directly against the PDF (`docs/police_thief_p2p.pdf`, ch.4.3
"מודל הפליטה והדעיכה" / "Emission & Decay"), not taken on trust from the
stage-3 stub. **The formula already recorded matches exactly**:

```
tau(t+1) = max(0, (1 - rho) * tau(t) + delta_tau)
```

— multiplicative decay of the existing value, `rho` the decay rate
(`pheromone_decay` = 0.10), `delta_tau` the fresh deposit at that cell this
round. No difference found between what was recorded and what the PDF
prints; nothing to correct here.

The book's own figure 4 (the same page) prints a concrete 5×5 emission
kernel around a fresh deposit, centre 0.9: `0.90 / 0.62 (orthogonal) / 0.42
(diagonal) / 0.20 / 0.14 / 0.04` — this is the deposit shape `domain/scent.py`
implements verbatim (see below for why "verbatim," not "derived").

## The interop kit's disputed scent kernel (SPEC §5.1)

Read directly, not summarized from memory: `SPEC.md` §5.1 and its two
supporting vector files (`vectors/scent_book_v3.json`,
`vectors/locked_model.json`). The kit registers **two** named scent models
side by side — the reference implementation's own `subtractive_chebyshev_v1`
(§5, linear Chebyshev falloff, subtractive per-step decay, rounded to 3
places — a *different* model from the book's, not a formatting variant),
and the book's own `multiplicative_book_v1` (§5.1, **status: PROMOTED**,
i.e. byte-exact clean-room-reproduced by a second independent team). This
project already committed to the book's model in stage 3; the question this
stage had to answer was whether our implementation of it reproduces the
kit's vectors.

**The dispute, in the kit's own words**: one team ("anrbj666") read the
book's printed figure-4 kernel as an exact radial Gaussian; the kit's own
earlier position was that the values "match no clean formula." Both were
right, for a reason the kit's `closed_form_probe` makes precise: the
sigma-squared window that reproduces the printed 25 values under
round-to-2-decimal-places (`[1.3178, 1.3327]`) is **disjoint** from the
window that reproduces them under truncation (`[1.3436, 1.3538]`). Two
teams that each independently fit "a Gaussian" to the printed figure in
good faith land in different windows and get silently different, wrong
fields relative to each other — the shape genuinely is Gaussian-like, but
not *reproducibly* derivable from it. The kit's resolution, adopted here
unchanged: **pin the 25 printed values verbatim as a lookup table**, not a
formula (`domain/scent.py::_KERNEL`). I checked this personally against the
book PDF's own printed figure independently of the kit's vector file before
reading the kit's reasoning, and it is the same 25 numbers.

**Two further details the kit's vector pins that the book's printed prose
does not, both adopted here as reasoned deviations from the printed
(illustrative) formula, on PRD-03's own precedent for this exact class of
gap**:

1. **An upper clamp at `center_intensity` (0.9).** The book prints only
   `max(0, ...)` — no upper bound. Without one, a saturated cell that
   decays and is then redeposited on reaches `(1-0.1)*0.9 + 0.62 =
   1.4300000000000002`, outside the book's own declared `tau ∈ [0, 0.9]`
   range. `domain/scent.py::advance_field` clamps to `[0.0,
   center_intensity]`, matching the kit's own `clamp: [0.0, 0.9]`.
2. **Evaluation order is pinned bit-for-bit**: `(1 - rho) * tau + delta`,
   not the algebraically-identical `tau - rho * tau + delta` — the kit's
   own `ordering_probe` shows these are different IEEE-754 doubles on a
   real fraction of inputs, which matters here specifically because this
   model applies **no rounding** at all and is **not** re-derived by
   re-simulation on the receiver (`domain/scent.py::advance_field`'s
   docstring; see "Float determinism" below).

**Cadence**: once per full turn (after the acting side's own move, stay, or
barrier placement — whichever it takes, since all three still leave the
agent *somewhere*), not once per half-turn message; `infra/turn_sender.py`
calls `emit`+`advance_field` exactly once per own action, which is
naturally once per round for that side.

### Vector results — pass/fail, per vector

All ported as data-only fixtures (no kit code imported), per this project's
existing integrity boundary (PRD-03): `tests/fixtures/vectors/scent_book_v3.json`.

| Vector | Result |
|---|---|
| `emit` — centre deposit, 7×7 board | **PASS** — `test_emit_vectors_reproduce_the_kernel` |
| `emit` — corner deposit, clipped to bounds | **PASS** — same test, second case |
| `scalar_traces.pure_decay` (0.9 → 0.81) | **PASS** |
| `scalar_traces.clamp` (raw 1.43 → clamped 0.9) | **PASS** |
| `scalar_traces.chain` (3 full turns from empty, plus the turn-3 fork) | **PASS** |
| `field_walk` (3 full turns of a moving agent, 7×7, byte-exact) | **PASS** |
| `vectors/locked_model.json`'s registered `multiplicative_book_v1` SHA-256 | **PASS** — see below |

No vector failed. Nothing was adjusted to match a vector; the implementation
was written from the book PDF and the kit's SPEC prose, and the vectors then
checked it — the one place code changed *because of* a vector was the
locked-model doc schema (next section), which is a declared-format upgrade
with the kit's stated rationale, not a game-behaviour change.

## Locked-model schema upgrade, and an unplanned real-world check it enabled

Stage 3's `SCENT_MODEL_DOC` used an ad-hoc `{family, name, formula,
example}` shape, written before this stage's model existed. The kit's SPEC
§7 pins a specific 4-key schema instead
(`{family, name, params, example}`) precisely so that two teams
implementing the *same* model from the *same* book chapter produce
*comparable* hashes rather than refusing each other over field-set
differences alone. `shared/locked_model.py` now uses that schema, with
`params` populated field-for-field from the kit's own registered doc.

This is not merely cosmetic: `tests/test_scent.py::
test_locked_scent_model_matches_the_kit_promoted_hash` asserts our
`scent_model_sha256()` equals the kit's **published, PROMOTED**
hash for `multiplicative_book_v1`
(`934c220d5bf62acaa3297c6c9d723ea954c220260b02292ca17f6d5daef9f4d9`) — and
it passes. This project is not a counted participant in that external
league, so the hash match carries no protocol consequence here, but it is
a genuine, independently-checkable signal that this project's
`canonical_json` implementation and this doc's construction are
byte-for-byte compatible with a real external team's, not just internally
self-consistent.

## Belief map design (`domain/belief.py`)

Two invariants are enforced structurally, not just tested for:

- **Never on a barrier or off-board cell.** `reachable_cells(board)` is
  recomputed from the *current* board on every call (barriers can appear
  mid-match), and every belief-producing function renormalizes over exactly
  that set. There is no code path that can assign a barrier or off-board
  cell a nonzero belief, by construction.
- **Always a valid probability distribution.** Non-negative, sums to 1 over
  the reachable set.

**What is NOT book-mandated, and is this project's own design choice,
documented as such rather than attributed to App F**: App F fixes the
*physical* scent field's three parameters (centre intensity, decay rate,
field size) but says nothing about how confidence in a derived *belief*
should behave between observations. A plain Bayesian likelihood-multiply
update has no forgetting term — a cell driven toward zero by one
observation can never recover even if the opponent later moves back through
it. `decay_confidence` blends belief toward the uniform distribution by a
small fixed fraction (`_CONFIDENCE_BLEND = 0.05`) before each scent update,
and `update_from_scent`'s likelihood floor (`_LIKELIHOOD_FLOOR = 0.01`)
means an unscented reachable cell is discounted, never driven to exactly
zero. Both constants are tuning choices, not book values; `tests/
test_belief.py::test_no_cell_is_ever_permanently_ruled_out` is the
regression test for the property they exist to guarantee.

## Float determinism findings

This matters more here than almost anywhere else in the project: the scent
field crosses the wire, gets sealed into a commit hash, and — per the kit's
own model registration — is **not** re-derived by the receiver from a
shared simulation; each side computes and transmits its own. If two
computations of "the same" field diverge by even the last bit, the sealed
hash changes.

Checked directly, not assumed:

- **Same field, computed twice in the same process**: byte-identical
  canonical-JSON serialization (`test_same_field_computed_twice_in_process_
  is_byte_identical`). Expected — same interpreter, same arithmetic path —
  but not skipped, since a source of nondeterminism (e.g. iterating a
  `set`/plain `dict` in an order that happened to affect float summation
  order) would show up here first.
- **Same field, computed in a genuinely separate Python process**
  (`test_same_field_computed_in_a_fresh_subprocess_is_byte_identical`):
  spawns `sys.executable` as a real subprocess, computes the identical
  field from scratch, and compares raw stdout bytes against the in-process
  result. **Byte-identical.** Python's `json` module emits floats via the
  interpreter's own shortest-round-trip `repr` (IEEE-754 double,
  platform-independent for a fixed CPython build), and this project's
  evaluation order is pinned exactly as the kit's `ordering_probe` requires
  — so no float-serialization nondeterminism was found. Nothing to flag as
  a risk to audits; this is the finding, checked rather than presumed.

## Acceptance criteria

- [x] Decay over N steps matches the closed form to floating-point
      tolerance. **Tolerance stated: exact float equality (`==`).**
      Justified because evaluation order is pinned bit-for-bit (no
      rounding is ever applied, per the kit's own `rounding_decimals:
      null`), so two computations from the same inputs must produce the
      identical double, not merely a numerically close one — an `isclose`
      tolerance would silently mask a real evaluation-order regression.
- [x] Float determinism confirmed same-process and cross-subprocess — see
      above; no non-determinism found.
- [x] Belief mass never lands on barriers or off-board cells — structural,
      not spot-checked (`reachable_cells` masking).
- [x] Belief is a valid probability distribution — normalized,
      non-negative, checked on every belief-producing function's output.
- [x] Two peers observing the same emission history compute the same
      field — follows from `emit`/`advance_field` being pure functions of
      their arguments, confirmed by the determinism tests above.
- [x] Interop kit vectors for the pheromone construction — 7/7 pass (table
      above); none adjusted-to-pass.

## Depends on

Stage 3 (PRD-03): the handshake's `negotiate` EXTRAS carry
`scent_model_sha256`, refused on mismatch; the commit-reveal sealing
mechanism `smell_grid` now rides inside. Stage 1's `Board`/`Position` for
in-bounds/barrier queries. `GameConfig.pheromones` (`domain/config_models.
py::PheromoneConfig`) for `center_intensity`/`decay`/`grid_size` — all
three are fixed (`קבוע`) in App F table 16, so `domain/scent.py` asserts
rather than scales for a different `grid_size`/`center_intensity`.

## Open questions / negotiation items surfaced by this stage

- **Hint weighting/decoding is entirely deferred to stage 5** — not a gap
  in this stage, an explicit scope boundary (see "Out of scope"). No
  negotiation item yet, since no hint text is produced.
- **`smell_grid` sealing is a new field inside an already-agreed sealed
  payload shape**, not a new signed term — per PRD-03's own finding that
  "the exact key set... does not need to match across teams" (each side
  reveals its own full record and the other re-hashes it), this needs no
  new MUST-AGREE entry. Recorded here for completeness, not as a blocker.
- **The belief-confidence-decay blend (`_CONFIDENCE_BLEND`,
  `_LIKELIHOOD_FLOOR`) is purely local** — it never crosses the wire and
  is not observable by an opponent, so it needs no cross-team agreement
  either (unlike the *scent field* model, which does, and is already
  locked).
