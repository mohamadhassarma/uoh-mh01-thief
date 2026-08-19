# PRD-05 - Strategy Brain and Verbal Layer

## Problem statement — the belief ceiling stage 4 measured, not a design choice

PRD-04's `scripts/belief_transcript_demo.py`, run at the real signed
contract values (`grid_size=7`, `survival_threshold=35`,
`pheromone_center_intensity=0.9`, `pheromone_decay=0.10`,
`pheromone_grid_size=5`) against a random-walk thief (seed 7), measured how
well the belief map's argmax cell actually tracks the true hidden position
it is built from:

```
argmax within 1 cell of truth (Manhattan): 16/35 (45.7%)
argmax within 2 cells of truth (Manhattan): 27/35 (77.1%)
```

Peak belief probability itself stabilizes around 0.32–0.35 once the thief
has lingered in one region long enough for its own trail to accumulate —
it does not climb toward 1.0, and the argmax is sometimes several cells
from the truth even after many turns (turn 10: argmax `(3,4)`, true cell
`(0,4)`, `p(true_cell) = 0.0053`). **This is correct behaviour for a
decaying trail fed by a random walk, not a bug in PRD-04's belief map** —
see PRD-04's own float-determinism and vector-conformance sections for why
the underlying scent/decay math is not in question here. It is, however,
the actual operating constraint stage 5 has to design against, not an
incidental transcript footnote:

- **A police brain that simply chases the argmax is frequently chasing a
  stale trail.** Just over half the time (54.3%, by this baseline) the
  single most-likely cell is not even Manhattan-adjacent to where the
  thief actually is — a naive "walk toward argmax" policy inherits that
  error rate directly into its pursuit.
- **A thief brain can exploit the same measurement.** Because peak belief
  sharpens specifically where the thief lingers, a thief that periodically
  breaks its own trail (moves unpredictably, doubles back, or leaves a
  region before its local scent saturates) can suppress the 45.7%/77.1%
  figures further — pure distance-maximising from the police's last known
  cell is not necessarily the thief's best response; deliberately
  degrading the police's belief accuracy may be worth more.
- **This baseline is what stage 5 needs to beat, not a target to match.**
  Any police strategy claiming to "use the belief map well" should be
  measured against 45.7% (within 1) / 77.1% (within 2) on the same
  transcript setup — an improvement means genuinely extracting more signal
  from the scent field (e.g. weighting recent deposits over stale ones,
  tracking the trail's direction of travel rather than only its peak, or
  combining belief with the distance heuristics from book ch.6.4), not
  just re-running the same measurement and reporting a different seed.

These numbers are from a single seeded run (one sub-game, one random-walk
thief) — a real baseline, not a statistically tight one; stage 5 may want
to average over more seeds/strategies before treating 45.7%/77.1% as the
number to beat precisely, but the qualitative ceiling (peak belief
saturating well under 1.0, argmax frequently wrong by more than one cell)
is the load-bearing finding, and it will not disappear with more samples.

## Goal

Give both sides a real strategy brain — pure Python, never the LLM — that
reads the belief map built in stage 4 and turns it into a move (police:
containment over pursuit; thief: survival via trail-breaking, not naive
distance-maximising), plus a zero-token template hint layer, and measure
every claim about them against the 45.7%/77.1% baseline above instead of
asserting it.

## In scope

- `BrainBase` (`domain/brain_base.py`): `_pick_move`/`_decide_move`, belief
  set by the caller via `.belief`, hint generation, structural zero-trust
  guard (`_OpponentPositionGuard`) so a brain cannot read the opponent's true
  position even by mistake. `load_brain_class`/`resolve_strategy` for the
  `[strategy] police_class`/`thief_class` config-injection point.
- `ContainmentPoliceBrain` (`domain/police_brain.py`) and `EvasiveThiefBrain`
  (`domain/thief_brain.py`).
- Template hint generation/parsing/word-cap/belief-fusion
  (`domain/hints.py`), sealed alongside the self-declared truth/lie verdict
  (`domain/sealed_payload.py`, `infra/turn_sender.py`).
- The headless evaluation harness (`domain/eval_match.py`,
  `scripts/evaluate_strategies.py`).
- Making the real, role-alternating `peer` CLI series resolve the
  role-correct brain for every sub-game (`infra/series_subgame.py`'s
  `_strategy_for_sub_game`) — found to be necessary during this stage, not
  planned up front; see "Which ideas failed and why".

## Out of scope

- GUI (stage 6). Tunnels, Gatekeeper, Gmail delivery (stage 7).
- Any code path where an LLM output influences a move — never in scope,
  this stage or any other, per THE ONE INVARIANT.
- Free-text/NLP hints — the `template` provider (closed 9-region vocabulary)
  is what makes a hint decodable without real language understanding; a
  different provider is a future stage's concern, not this one's.

## Acceptance criteria

- [x] A brain cannot read the opponent's true position — enforced
      structurally (`_OpponentPositionGuard` raises `PermissionError`), not
      by convention; both sides tested.
- [x] Both brains are deterministic given a seed (dedicated tests; the
      evaluation harness reproduces identical results on a repeated seed
      list).
- [x] Police never places a barrier that self-traps when a non-trapping
      legal alternative exists (`_would_self_trap`, tested).
- [x] Barrier quota (14) is never exceeded — `rules.is_barrier_placement_legal`
      is the single legality gate both the real orchestrator and the
      brain's own candidate filtering go through; no separate cap to drift
      out of sync.
- [x] Every hint is word-capped (`world.hint_max_words`) before the wire
      (`infra/turn_sender.py`, tested).
- [x] The self-declared truth/lie verdict is sealed in the same commit as
      the hint text — a tampered hint OR a tampered verdict is caught by the
      existing generic re-hash audit (`tests/test_hint_sealing.py`).
- [x] `scripts/evaluate_strategies.py` reports win rate, mean
      survival/capture turns, barrier utilisation, and the PRD-05
      argmax-accuracy metrics, deterministic given a seed list.
- [x] A full six-sub-game series between the two new brains, played over
      the real networked `peer` CLI at the real signed contract values, with
      all six sub-games' mutual audits passing.
- [x] Files ≤150 lines, coverage ≥85%, ruff clean.

## Harness results (vs the stage-4 baseline: 45.7% within 1 cell, 77.1%
within 2 cells)

All at the real signed contract values (`grid_size=7`, `max_moves=35`,
`survival_threshold=35`, `max_barriers=14`), `scripts/evaluate_strategies.py`,
N=120 seeds unless noted.

| Matchup (police vs thief)             | police win rate | argmax within 1 | argmax within 2 |
|----------------------------------------|-----------------|------------------|------------------|
| random vs random                       | 4.2%            | 28.6%            | 59.4%            |
| random vs `EvasiveThiefBrain`          | 1.7%            | 32.7%            | 63.2%            |
| `ContainmentPoliceBrain` vs random     | 68.3%           | 27.0%            | 54.4%            |
| `ContainmentPoliceBrain` vs `EvasiveThiefBrain` | 48.3%   | 27.3%            | 54.3%            |

Reading these together:

- `ContainmentPoliceBrain` is the whole story on the police side: win rate
  goes from a 4.2% coin-flip-poor baseline to 68.3% against a random thief.
  A brain that treats barriers as a real weapon, not a supplement, wins the
  large majority of games it used to lose.
- `EvasiveThiefBrain` cuts that 68.3% down to 48.3% — a genuine, 20-point
  suppression of the police's win rate. But argmax accuracy is essentially
  UNCHANGED (27.0%/54.4% -> 27.3%/54.3%, within noise at n≈2000+ samples).
  **The thief brain's effectiveness comes from its movement — trail-breaking,
  threat-based evasion, mobility-preserving move scoring — not from
  confusing the belief map itself.** Suppressing the police's argmax
  accuracy (the PRD-05 baseline's own headline number) and suppressing the
  police's WIN RATE turned out to be two different, separable effects; this
  thief brain only demonstrably achieves the second one. See the
  `_LIE_PROBABILITY` sweep below for the (negative) attempt at the first.
- Argmax accuracy against `EvasiveThiefBrain` is essentially the SAME as
  against a plain random walk (27.3%/54.3% vs 28.6%/59.4%), both close to
  the stage-4 baseline's 45.7%/77.1% single-thief-seed measurement's
  qualitative shape (accuracy well under certainty, and worse at radius 1
  than the single-seed baseline reported — expected, since the baseline was
  one seed against one specific random-walk trajectory, not this stage's
  120-seed average against two different thief policies).

### Barrier timing sweep (the containment-vs-pursuit redesign trace)

Documented in full in `police_brain.py`'s own module docstring; summarized
here because it is the single largest design decision this stage made:

| Design                                                        | Win rate vs `EvasiveThiefBrain` | Seeds |
|-----------------------------------------------------------------|----------------------------------|-------|
| Mass-gated containment (bug: wrong-unit threshold, see below)   | 10.0%                            | 30    |
| Pure pursuit, no containment at all                             | 30.0%                            | 30/80 |
| Containment gated on `reduction >= 3`, unrestricted timing       | 28.7%                            | 80    |
| Containment gated on `reduction >= 3`, EARLY half only           | 36.7%                            | 120*  |
| Containment gated on `reduction >= 3`, unrestricted timing       | 29.2%                            | 120*  |
| **Containment gated on `reduction >= 3`, LATE half only (shipped)** | **50.8%**                    | 120   |

(*120-seed three-way sweep at an intermediate point in the redesign, before
the final headline 48.3% number above, which additionally reflects the
`parse_claimed_region` substring-matching fix — see below.)

**"Late walls are precise" measured out ahead of "early walls shape the
game," decisively** — restricting containment to the second half of the
sub-game very nearly doubles police's win rate over allowing it the whole
game. The mechanism: `rules.is_barrier_placement_legal` only allows a
barrier at police's own cell or an orthogonal neighbour, so containment is
only ever effective once police has physically closed distance to the
hotspot — an early barrier is almost always adjacent to nothing useful and
just burns a turn that pursuit would have spent gaining ground.

## Which ideas failed and why

1. **Mass-gated containment used the wrong unit.** The first
   `ContainmentPoliceBrain` gated pursuit-vs-containment on
   `local_belief_mass(...) >= 0.35`, calibrated against the stage-4
   baseline's SINGLE-CELL peak probability (0.32-0.35). But this brain's own
   `best_local_hotspot` sums a whole radius-2 NEIGHBOURHOOD's mass — a
   different, much larger quantity, measured at 0.71-0.95 in practice. The
   gate was satisfied almost every turn, so distance-to-hotspot alone
   controlled behaviour, pushing into containment (barriers only legal next
   to police's own cell) whenever more than 2 cells from the hotspot — most
   of a 7x7 board most of the time — for zero effect on a hotspot that far
   away. Measured: 10.0% win rate (30 seeds), worse than plain pursuit's
   30.0%. Comparing a design against the wrong baseline unit produced a
   worse-than-no-containment brain; caught only by measuring, not by
   re-reading the code.
2. **Unrestricted containment was still a net negative even once the unit
   was fixed.** Gating on a real, meaningful reduction
   (`_MIN_USEFUL_REDUCTION`) fixed the wasted-turn problem but only restored
   parity with pure pursuit (28.7% vs 30.0%, 80 seeds) — taking a legal,
   correctly-measured barrier is not automatically worth the turn it costs.
   Only restricting containment to the second half of the sub-game turned it
   into a real improvement (50.8%, 120 seeds) — see the barrier-timing table
   above.
3. **Deception via hints did not suppress belief accuracy at any tested
   rate** — see `thief_brain.py`'s own docstring and the `_LIE_PROBABILITY`
   sweep above. More lying correlated with HIGHER measured police argmax
   accuracy, the opposite of the intended effect. Kept at 0.5 anyway (tied
   with 0.0 on both metrics; exercises the sealed tamper-detection path).
   This is the stage's clearest negative result: an idea that sounded
   obviously right (mislead the belief map) and measurably was not.
4. **`parse_claimed_region` silently misread compound region names.**
   Iterating the 9 region names in insertion order let `"east"` match as a
   substring of `"southeast"`/`"northeast"` before the compound name was
   ever checked, so a genuine "I am near the southeast" hint was decoded as
   the wrong region roughly half the time it should have mattered. Caught by
   a failing belief-fusion test, not by inspection. Fixed by checking
   longest names first; re-measuring the headline police-vs-evasive number
   after the fix (50.8% -> 48.3%, 120 seeds) confirmed the timing finding
   held and argmax accuracy improved slightly (as expected: hints now
   decode correctly more often).
5. **The real, role-alternating `peer` CLI series would have silently run
   the wrong brain on every role-swapped sub-game.** Discovered while
   building the six-sub-game transcript this PRD requires, not anticipated
   in the design: `cmd_peer` resolved ONE `strategy` object from this
   process's NATURAL role, once, at series start, and passed it unchanged
   into every sub-game — but PRD-03 alternates roles every sub-game (odd =
   natural, even = swapped). On a swapped sub-game, e.g. a
   `ContainmentPoliceBrain` instance built for the police role would have
   been asked to play THIEF; `BrainBase.__call__` dispatches on the ACTUAL
   role passed in per call, so it would not have crashed — it would have
   quietly run `ContainmentPoliceBrain._pick_move` (a pursue-the-hotspot
   move, written to chase, never to flee) as a thief's move, or worse, an
   `EvasiveThiefBrain` playing POLICE would run AWAY from its own hotspot —
   fleeing the very target it was supposed to be closing on. Neither would
   raise; both would just quietly lose more than a correctly-assigned brain
   should. This also meant a thief brain's per-sub-game state (direction
   streak) was never reset between sub-games. Fixed by resolving a FRESH,
   role-correct strategy per sub-game
   (`infra/series_subgame.py::_strategy_for_sub_game`), keyed off the
   ACTUAL role for that sub-game and a per-sub-game-derived seed
   (`f"{seed}-{sub_game_number}"`) — never the process's natural role,
   never one instance reused across the series. `run_series`'s pre-existing
   `strategy=` override (needed by the stalling-peer timeout test, which
   deliberately wants one fixed behaviour regardless of role) still works
   unchanged; only the real CLI path, which passed nothing but a seed, was
   affected. This is exactly the kind of defect the harness could never
   have caught, because the harness always assigns police/thief strategies
   explicitly and separately, by construction — only the real
   role-alternating series path could expose it.

## Depends on

PRD-01 (movement/barrier rules, `is_barrier_placement_legal`), PRD-02
(commit-reveal sealing, extended here to cover `hint`/`hint_is_true`), PRD-03
(the role-alternating series this stage's `_strategy_for_sub_game` fix
targets), PRD-04 (belief map, scent field, and the 45.7%/77.1% baseline this
stage measures against).

## Stage-5 close-out

### 1. External benchmark: the interop kit's sparring peer

Checked what's actually binding, in order, before changing production wire
code: the book PDF (searched full-text — silent on tool names, terms shape,
and turn order), the professor's own reference implementation at
`_reference/ref_impl` (`infra/mcp_server.py`, `peer/sealing.py::terms_from_
config`, `docs/PLAN.md`), and the interop kit. The reference and the kit
agree with each other on all three questions the book leaves open, so per
the fallback rule (book silent + kit matches reference -> kit wins), this
project's prior choices were the ones that diverged, not a "reasonable
alternative":

- **Tool names.** SPEC §7.5 (PROMOTED) pins `negotiate`, `receive_turn`,
  `submit_audit`, `receive_control`, each carrying a SINGLE `message`/
  `payload` dict argument. This project had `submit_move`/`reveal_audit`
  with multi-field signatures. Fixed: `infra/mcp_server.py`,
  `infra/mcp_client.py`.
- **Terms shape.** `vectors/terms_signature.json` is tier **CORE** ("the
  interop floor") and pins an exact, closed 14-key shape
  (`board_size`, `smell_grid_size`, ..., `num_games`) that the reference's
  own `terms_from_config` reproduces key-for-key. This project's
  `terms_from_config` used different names for the same concepts
  (`grid_size` vs `board_size`, etc.) AND included nine extra keys the
  vector doesn't have. Since both the kit and the reference do strict
  `terms != theirs` equality, any deviation — extra key, missing key, wrong
  name — refuses the handshake outright. Fixed to the exact 14-key shape
  (`shared/terms.py`); added the one field this project never captured at
  all, `pheromone_min_center_intensity` (wire: `min_center_intensity`),
  end-to-end through config/game.json, `PheromoneConfig`, and the parser.
- **Turn order.** `ref_impl/docs/PLAN.md`: "**Thief moves first.**" —
  matches the kit's own banner exactly, and the book has no passage on
  turn order at all (confirmed by full-text search, not by trusting PRD-01's
  earlier "the rulebook does not say" note at face value). This project had
  `FIRST_MOVER = Side.POLICE` — simply wrong relative to both outside
  authorities, invisible until now because self-play never had anyone
  else's turn order to disagree with. Fixed: `domain/house_rules.py`.
  Fallout: six `test_orchestrator.py` tests hardcoded "police moves first"
  as an unstated assumption; fixed by making each test set `whose_turn`
  explicitly rather than relying on the engine's default.
- **A new conformance test suite** (`tests/test_wire_conformance.py`) now
  asserts our actual registered MCP tool names/argument shape and our
  actual `terms_from_config` output against these pinned values directly —
  this class of gap now fails in `pytest`, not at match time, closing the
  exact gap that let it go unnoticed through four prior stages.

**Result of the live rehearsal, after the fixes.** Ran a real cross-process
series: this project's `police` peer against the kit's `sparring.cli serve`
(scent model set to `multiplicative_book_v1` to match our locked model;
`world.map_area` set to "Haifa" to match the kit's fixed `setting` for this
one rehearsal only — not a change to the real signed contract). **Negotiate
succeeded** — no terms mismatch, no tool-name refusal — directly confirming
the two fixes above are correct and sufficient at the handshake layer. Play
itself then failed immediately: `parse_move_request() got an unexpected
keyword argument 'step'`. The kit's `TurnMessage` (`step`, `sender`,
`commit`, `hint`, `smell_grid`, `timestamp`, `barrier_placed`,
`capture_claim`, `claim_response`, `win_claim`) and this project's
`MoveRequest` (`role`, `turn_number`, `action_type`, `direction`,
`target_row`, `target_col`, ...) are a THIRD, DEEPER, and DIFFERENT-IN-KIND
mismatch from the two already fixed — not a naming difference but a
different transport model: SPEC §7.5 describes `receive_turn`/`negotiate`
as one-way pushes into the receiver's own inbox (each side calls the
other's tool and separately polls its own inbox for what arrived), while
this project's `mcp_client.send_move`/`send_negotiate` are written as
synchronous request/response RPCs that expect the tool call itself to
return the opponent's data. Reconciling this is a genuine, substantial
protocol-layer rewrite — the inner message shape AND the call/response
model, not a rename — and is **out of scope for this pass**, deliberately:
it goes well beyond "align tool names and terms," touches sealing/audit
machinery that depends on the current request/response shape throughout,
and warrants its own dedicated stage rather than a rushed change under an
already-large close-out. Filed as the clear next external-interop
priority. Consequently: **no win rate, no per-sub-game outcomes, and no
audit results were obtainable this pass** — the series never got past the
first move. That is itself the honest, complete answer to "benchmark
against an external opponent, report the numbers": the numbers do not
exist yet, and the reason they don't is now precisely identified rather
than vague. The Hebrew/emoji non-ASCII check (`--hint-lang mixed`) was
never reached for the same reason.

### 2. The deception result was a measurement artifact, not a game finding

Inspected `hints.generate_hint`'s decoy selection directly: `rng.choice([r
for r in _REGIONS if r != true_region])` is a uniform draw over the 8
non-true regions — already max-entropy, not a deterministic/systematically-
biased function of the truth as hypothesised. That hypothesis does not
survive inspection.

The real cause, found by inspecting `BrainBase.__init__`: movement and hint
decisions shared ONE `random.Random` stream. A lie consumes a different
number of draws than the truth (`generate_hint`'s decoy path calls
`rng.choice` an extra time), so sweeping `_LIE_PROBABILITY` silently shifted
every later movement roll that sub-game — the original sweep was comparing
different SEQUENCES OF MOVES across the three settings, not different hint
policies, which is exactly how a random lie could appear to SHARPEN the
opponent's belief. Fixed: `BrainBase` now has a separate `self.hint_rng`,
seeded once off `self.rng` at construction, never touched by movement.

Re-measured (200 seeds, `ContainmentPoliceBrain` vs `EvasiveThiefBrain`,
deconfounded):

| `_LIE_PROBABILITY` | police argmax within 1 | within 2 | police win rate |
|---|---|---|---|
| 0.0 (never lie) | 28.6% | 56.9% | 46.0% |
| 0.5 (shipped) | 28.1% | 56.5% | 46.5% |
| 1.0 (always lie, under threat) | 28.0% | 56.0% | 46.0% |

Argmax accuracy now moves in the EXPECTED direction as lying increases —
small, but monotonic and real. Win rate is statistically flat across all
three (differences are noise at N=200). Answering the question directly:
**deception works on the metric it directly targets** (belief accuracy) —
it is not that "deception does not work in this game." But at
`hints.DEFAULT_HINT_TRUST_WEIGHT`'s deliberately modest 0.15, that effect
is too small to move the metric that actually decides the game. Kept at 0.5
(not 0.0): win rate does not favour never lying, and 0.5 keeps the real,
correctly-signed suppression effect. `tests/test_hint_sealing.py` already
covers the sealed truth/lie tamper-detection path with hand-built,
deterministic payloads — it never depended on `_LIE_PROBABILITY` producing
a lie by chance, so no test change was needed there.

### 3. Complete harness metrics

All four matchups from the harness table above, in full (N=120 seeds each,
real contract values):

| Matchup (police vs thief) | win rate | mean turns to capture | mean survival turns | mean barriers used |
|---|---|---|---|---|
| random vs random | 4.2% | 29.0 | 70* | 5.14 / 14 |
| random vs `EvasiveThiefBrain` | 1.7% | 36.0 | 70* | 5.21 / 14 |
| `ContainmentPoliceBrain` vs random | 68.3% | 26.1 | 70* | 2.18 / 14 |
| `ContainmentPoliceBrain` vs `EvasiveThiefBrain` | 48.3% | 28.7 | 70* | 2.71 / 14 |

*`mean_survival_turns` is total STEPS (both sides' actions combined, per
`eval_match.EvalResult.turns`), not the thief's own step count — a survival
win is reached once the thief's own count hits `survival_threshold` (35),
which under this engine's alternating-turn accounting lands at combined-step
count 70 almost by construction, not a coincidence or a bug.

Barrier utilisation directly supports the "late walls are precise" finding:
`ContainmentPoliceBrain` uses barriers MORE against a thief that's actually
worth containing (2.71/14 vs `EvasiveThiefBrain`) than against a random
walker (2.18/14) — late-gated containment fires more often when there's a
real hotspot worth cutting off, not on a fixed schedule.

### 4. The CLI/harness divergence class — audited, and guarded

Audited every place a strategy gets resolved for a role: `cli_commands.py`
(the real `peer` CLI — this is where the bug lived), `infra/series_subgame.py`
(now fixed), `domain/eval_match.py`/`scripts/evaluate_strategies.py` (the
harness — always takes police/thief strategies as two SEPARATE, explicit
arguments; there is no "resolve once, reuse across roles" code path here at
all, so this specific bug class cannot recur in the harness by construction).
No other role-resolution site exists in the codebase.

Added `tests/test_cli_role_alternation.py`: two REAL `python -m uoh_mh01
peer` subprocesses, both configured with two deliberately distinguishable
marker brains (`tests/marker_brains.py` — `AlwaysNorthBrain`/
`AlwaysSouthBrain`, never used outside this test), a 2-sub-game series
(covers both the natural and the role-swapped sub-game). The test reads
back the log artifacts and asserts, from the actual recorded move letters,
that whichever process is playing police THAT sub-game shows only `N`
moves and whichever plays thief shows only `S` — regardless of which
process that is. This is the test that would have caught the original bug;
it does not rely on `_strategy_for_sub_game`'s own unit test
(`test_series_subgame.py`) at all, which only proves the resolver function
is correct in isolation, not that the real CLI actually calls it correctly
end to end.

### 5. Scoring asymmetry — the investment principle

Verified the user's derivation independently from the scoring table
(`capture_cop=20, capture_thief=5, survival_cop=5, survival_thief=10`,
ties/technical-losses symmetric and so contribute no asymmetry). Over a
6-sub-game series with role alternation, each side plays exactly 3 sub-games
as police and 3 as thief (6 is even, so the split is always exact regardless
of natural role):

```
E[score | police that sub-game] = 5 + 15 * P(my police captures)
E[score | thief that sub-game]  = 10 - 5 * P(their police captures, i.e. I get captured)
your_total (6 games) = 3*(5 + 15*P_mine) + 3*(10 - 5*P_theirs)
                      = 45 + 45*P_mine - 15*P_theirs
```

Confirmed correct — matches the user's formula exactly. The per-sub-game
swing when playing police is `capture_cop - survival_cop = 15`; playing
thief it's `survival_thief - capture_thief = 5`; ratio 3, and it survives
aggregation over the 3-3 split unchanged (45 vs 15, same ratio). **A point
of police win rate is worth three points of thief win rate — confirmed, not
assumed.**

**Investment principle for any further strategy work**: marginal effort is
worth roughly 3x more spent sharpening the POLICE brain than the THIEF
brain, all else equal — matching what this stage's own numbers already show
independently (`ContainmentPoliceBrain` alone moved the police-vs-random win
rate 64 points, 4.2% -> 68.3%; `EvasiveThiefBrain` moved the thief's own
odds by roughly 20 points against that same police brain, 68.3% -> 48.3%
police win rate). The scoring table itself, not just the empirical results,
says where to spend the next hour.

### 6. Known remaining issue: `test_symmetric_timeouts.py`'s slow test is
genuinely intermittent, root cause identified, not fixed

Investigating an unrelated FIRST_MOVER-driven failure in this test surfaced
a real, pre-existing, reproducible-in-full-isolation race: when the
deliberately-stalled peer's synchronous `time.sleep()` freezes its event
loop mid-response, the OPPONENT's `fastmcp`/`mcp` SDK client sometimes
throws `anyio.ClosedResourceError` ("Error parsing SSE message") on its
underlying SSE stream and then — SILENTLY, WELL PAST `response_timeout_sec`/
`watchdog_timeout_sec` — reconnects and succeeds once the stalled peer wakes
up, never raising `OpponentUnresponsiveError` up to this project's own
`call_with_timeout`/watchdog layer at all. Confirmed via direct
reproduction with `time.monotonic()`-stamped tracing on both sides (not
guessed): one run detected the freeze correctly at ~60s as designed;
another, from the SAME test, played the entire 35-turn match to a normal
"survival" completion because the transport-level reconnect absorbed the
whole 65-second stall. A `_WATCHDOG_CHECK_MARGIN_SEC` fix was attempted and
DISPROVEN — a 5-second margin did not change the failure rate at all,
confirming the bug is not the originally-suspected narrow timing race but
this transport-level reconnect-past-our-own-timeout behaviour; the
speculative fix was reverted rather than shipped without evidence it helps.
Pre-existing (confirmed via the unmodified original file, before any of
this stage's changes), NOT a regression from this stage's wire-conformance
or turn-order fixes. A proper fix needs the underlying `mcp` SDK's
streamable-HTTP client to be forced to give up and raise within our own
declared budgets rather than transparently retrying past them — likely
requires either stricter `httpx`-level connect/read timeouts passed through
`fastmcp.Client`, or wrapping the call so a `wait_for` timeout also forces
the underlying connection closed rather than letting it reconnect. Filed as
a real, scoped-out follow-up; not attempted further this pass given the
size of everything else in this close-out.