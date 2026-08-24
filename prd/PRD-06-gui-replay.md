# PRD-06 - Live GUI and Replay Viewer

> Written after the fact. This file was a stub of `TODO` headings when stage 6
> was implemented, so the requirements below come from book ch.7 (which makes a
> replay viewer a submission requirement) and from the stage brief. The design
> decisions are recorded here because there was no PRD to take them from.

## Goal

Two things a marker can look at, and one of them is a proof.

1. A **replay viewer** that re-derives the SHA-256 commit of every sealed
   record in a played series and reports `Verified OK` or `TAMPERED`.
2. A **live GUI** showing the board, this agent's own position, barriers and
   its belief about the opponent as a heatmap, updating while a series runs.

Both must screenshot cleanly, because that is the graded artefact.

## In scope

- `uoh_mh01 replay --game-id <id>` - per-sub-game verification table, series
  verdict, non-zero exit on `TAMPERED` so it is usable as a check.
- `uoh_mh01 gui` - live viewer, polling the snapshot a running peer publishes.
- `uoh_mh01 gui --game-id <id> --sub-game N` - the same viewer over a finished
  series, with playback controls.
- `--screenshot <path>` on both, writing a PNG.

## Out of scope

- Rendering the OPPONENT's position. It is not known, and a viewer that implied
  otherwise would misrepresent the protocol. The heatmap is belief.
- Any interaction with a running game. The viewer observes and nothing else.

## Design decisions taken in the PRD's absence

**The verifier reuses `infra/audit.py` rather than re-hashing.** `verify_revealed`
is called with a `ReceivedCommitLog` built from the artifact's own stored
commits, so the comparison, the step-0 rule and the verdict floor all come from
the module that already gets them right. A second SHA-256 implementation would
prove nothing about the first if it agreed, and would report an honest series as
tampered if it did not.

**What a replay proves is narrower than what the live audit proves, and the
report says so.** Live, a revealed record is checked against the commit that
actually *arrived over the wire*. A replay has only the file, so it proves the
artifact is internally consistent - nothing has been EDITED since it was
written. It cannot prove the opponent played honestly; only the live audit
recorded in the log can. Deleting a whole record is likewise not detectable from
the artifact alone (see `test_a_wholly_removed_record_is_the_honest_limit_of_this_check`).

**Step 0 is verified but not counted.** It is disclosure-only and never
transmitted as a turn, so it is checked for self-consistency and excluded from
the played-step floor. Including it would make every honest series expect one
more step than it played and replay as `TAMPERED`.

**The live viewer is a separate process reading a file.** The peer writes
`logs/live_state.json` when something a viewer would notice changes; the GUI
polls it. Tk wants the main thread and a `mainloop` while the peer is an asyncio
server, so the alternative is a thread bridge - but the real reason is that **a
counted series must not be endangered by the viewer**. A GUI that crashes,
blocks on a redraw or is closed mid-game cannot affect a game it is not part of,
and `LiveStatePublisher.publish` swallows its own failures.

**The heat is normalised against the current peak, and the peak is shown.** A
belief map is a distribution over every reachable cell, so absolute
probabilities paint a uniform near-black board. Scaling against the maximum
shows the shape of the belief, at the cost of frames not being comparable to
each other - so the absolute peak is printed in the HUD.

**The heat layer is named for what it actually is.** Live it is belief about the
opponent. In a replay it is this agent's own transmitted scent field, because
that is what the log contains: belief is internal state and was never sealed.
Labelling both "belief" would be false in one of them.

**Drawing decisions live in `gui/scene.py`, which imports no Tk.** The painter
may not compute a colour or a label of its own, so the viewer's behaviour is
testable on a machine with no display.

## Acceptance criteria

- [x] Every sealed record is re-hashed and compared to its stored commit.
- [x] An edited payload or an edited commit is reported as `TAMPERED`, naming
      the sub-game and the failing step.
- [x] Step 0 is verified self-consistently and excluded from the played-step
      count; a tampered step 0 still fails.
- [x] The hashing is `domain/crypto.commit_of` via `infra/audit.verify_revealed`,
      not a second implementation.
- [x] The verifier exits non-zero on `TAMPERED`.
- [x] Run against the real `ali-ahm1-vs-uoh-mh01` artifacts: 6 sub-games, 207
      sealed steps, `Verified OK`.
- [x] GUI shows grid, own position, barriers, belief heatmap, turn indicator,
      current sub-game and role.
- [x] GUI updates live during a series.
- [x] Both produce a PNG in `docs/screenshots/`.
- [x] The viewer cannot fail a game.

## Depends on

- PRD-03 (the sealed chain and `infra/audit.py`)
- PRD-04 (the belief map)
