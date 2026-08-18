# Ported interop-kit vectors

Data files copied verbatim (not code) from the student interop/conformance
kit [`Imreec/copthief-league-protocol`](https://github.com/Imreec/copthief-league-protocol),
`vectors/{canonical_json,commit_reveal,terms_signature,game_uid}.json` — the
four `status: "CORE"` fixtures relevant to stage 3 (PRD-03). Per the kit's
own integrity boundary: only the vector *data* is ported; `tests/test_vectors.py`
contains this project's own, independently-written checks against them —
none of the kit's verification code is copied in.
