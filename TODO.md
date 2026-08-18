# TODO ג€” Thief agent

## Now (Stage 1: base logic)
- [ ] Load and validate `config/game.json` against the mandatory parameter table
- [ ] Board representation, 7x7, index-0, origin top-left
- [ ] Legal move set: N/S/E/W/STAY ג€” reject diagonals
- [ ] Barrier placement rules (police only, adjacent-or-own cell, irreversible)
- [ ] Capture detection by coordinate overlap
- [ ] Trapped-thief detection (no legal move => captured)
- [ ] Scoring table: capture 20/5, survival 5/10, technical loss 0/0
- [ ] Run a full match in a single process without crashing
- [ ] `pytest` covering rules and scoring

## Blocked / needs negotiation with opponent group
- [ ] Agree `config/game.json` byte-for-byte with opponent group
- [ ] Agree `axis_origin_corner` and `axis_start_index`
- [ ] Agree `map_area` and `hint_max_words`
- [ ] Agree the counting basis for `max_moves` (per-player vs combined) — see
      PRD-01 "Open questions"; this engine currently assumes per-player
- [ ] Agree who moves first (`FIRST_MOVER`) — see PRD-01 "Open questions"
- [ ] Find or agree a trigger condition for `tie_score` — none is implemented

## Known limitations
- [ ] `axis_origin_corner` and `axis_start_index` are negotiable per the
      mandatory parameter table, but this engine currently only implements
      `"top-left"` / `0`. Any other agreed value requires implementation work
      in `board.py`'s move deltas (and revisiting `config.py`'s validation)
      before it can be used — it is not a config error, just unbuilt.

## Admin
- [ ] Fill team member IDs in `config/thief/game.toml`
- [ ] Verify `.gitignore` blocks `credentials.json` and `token.json`
- [ ] Each team member submits separately on Moodle
- [ ] Word template -> `uoh-mh01-exYY.pdf` (do not move or edit fields)