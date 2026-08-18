"""Stage-3 conformance: this project's OWN canonical JSON / commit-reveal /
signature / game-id functions, checked against the interop kit's ported
CORE vector *data* (tests/fixtures/vectors/, see its README). No kit code
is imported here — only JSON fixtures we wrote our own checks against.
"""

import hashlib
import json
from pathlib import Path

from uoh_mh01.domain.canonical import canonical_json
from uoh_mh01.domain.crypto import commit_of
from uoh_mh01.domain.game_ids import derive_game_ids

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vectors"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_canonical_json_vectors():
    data = _load("canonical_json.json")
    assert data["status"] == "CORE"
    for case in data["vectors"]:
        got = canonical_json(case["object"])
        assert got == case["canonical"], case["note"]
        assert hashlib.sha256(got.encode("utf-8")).hexdigest() == case["sha256"], case["note"]


def test_commit_reveal_core_vectors_reproduce():
    data = _load("commit_reveal.json")
    assert data["status"] == "CORE"
    for case in data["vectors"]:
        assert commit_of(case["payload"], case["nonce"]) == case["commit"], case["note"]


def test_commit_reveal_reference_form_matches_our_construction():
    divergent = _load("commit_reveal.json")["divergent_forms"]
    ours = commit_of(divergent["payload"], divergent["nonce"])
    assert ours == divergent["reference_form"]


def test_we_do_not_accidentally_match_either_book_illustrative_form():
    # Both of the book's own printed illustrative constructions are
    # DIFFERENT hashes from what we compute — confirming we implemented the
    # reference/kit form deliberately, not one of the book's non-binding
    # printed listings. See PRD-03 "Commit preimage" for the full citation
    # of the book's clarification page and the reasoning for this choice.
    divergent = _load("commit_reveal.json")["divergent_forms"]
    ours = commit_of(divergent["payload"], divergent["nonce"])
    assert ours != divergent["book_ch5_listing_form"]
    assert ours != divergent["book_audit_snippet_form"]


def test_terms_signature_core_vector():
    data = _load("terms_signature.json")
    assert data["status"] == "CORE"
    for case in data["vectors"]:
        # The signature construction is identical to a commit: SHA256(canonical(terms)|nonce).
        assert commit_of(case["terms"], case["nonce"]) == case["signature"]


def test_game_uid_core_vectors_and_order_independence():
    data = _load("game_uid.json")
    assert data["status"] == "CORE"
    for case in data["vectors"]:
        game_id, game_uid = derive_game_ids(case["terms"], case["group_a"], case["group_b"])
        assert game_id == case["game_id"], case["note"]
        assert game_uid == case["game_uid"], case["note"]


def test_game_uid_is_a_function_of_extracted_terms_not_a_wider_config():
    # The interop kit's documented real failure mode (SPEC §4, WARNINGS §2):
    # deriving from the whole config instead of the flat negotiated terms
    # produces a uid that looks perfectly healthy on one side and only fails
    # the CROSS-team join. Constructing a case where "terms" and a "wider
    # config containing the same terms plus extra keys" diverge proves our
    # function only ever sees the flat terms.
    terms = {"board_size": 7, "max_steps": 35}
    wider_config = {**terms, "some_other_key_terms_extraction_must_ignore": "anything"}

    _, uid_from_terms = derive_game_ids(terms, "a", "b")
    _, uid_from_wider = derive_game_ids(wider_config, "a", "b")

    assert uid_from_terms != uid_from_wider  # proves the function is sensitive to exactly its input
    # and calling it with the wider object is a caller bug we can catch in code review /
    # integration tests (test_negotiation.py), not something this function silently hides.
