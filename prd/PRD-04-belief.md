# PRD-04 - Pheromones, Scent Field and Belief Map

## Goal
> TODO — stage 4. Not yet designed or implemented.

## In scope
> TODO

## Out of scope
> TODO

## Acceptance criteria
- [ ] TODO

## Depends on
> TODO

## Pheromone formula — recorded early, in stage 3, not yet implemented

PRD-03's pre-game handshake must exchange and hash-lock the full pheromone
emission/decay model before a series opens (book ch.4, verified directly
against the PDF) — even though the model itself belongs to this stage and is
not implemented yet. `shared/locked_model.py::SCENT_MODEL_DOC` is that hook,
built during stage 3 purely so the handshake has something real to carry in
its `negotiate` EXTRAS (never inside signed `terms` — a doc hash is not
itself a contract value, mirroring the interop kit's own `locked_model`
pattern, SPEC §7); `scent_model_sha256()` is checked for byte-identical
equality between both peers in `infra/negotiation.py::verify_peer_message`.

The book's own binding formula (ch.4):

```
tau(t+1) = max(0, (1 - rho) * tau(t) + delta_tau)
```

— multiplicative decay applied to the existing scent value `tau(t)` each
round, with `rho` the decay rate and `delta_tau` the fresh deposit. This is
the formula actually declared and hashed
(`SCENT_MODEL_DOC["formula"]`), together with a worked numeric example
(`center_intensity_before=0.9`, `decay_rate=0.1` →
`after_one_round_of_decay=0.81`) taken directly from the book. It was chosen
over the reference implementation's own (differing, subtractive) pheromone
update because the book's text is the binding source and the two disagree —
this stage does not resolve that disagreement further, it only records which
formula is locked for hashing purposes; the actual scent-field
implementation, its data structure, its interaction with the belief map, and
any consequences of this formula choice are entirely deferred to this
stage's real design work.