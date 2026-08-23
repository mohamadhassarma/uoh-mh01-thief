"""The settlement consensus signature, against the ported CORE vector.

The one thing these must prove is that we did NOT reuse the wire
canonicaliser. `report_consensus.json` ships `compact_form_sha256` precisely
so a team can check that — it is the hash the COMPACT form produces, and it is
different. A test suite that only asserted "our hash matches the vector's
signature" would still pass if someone later swapped the serializer, as long
as they swapped the expected value too; asserting against BOTH fields makes
the two forms provably distinct in this repo.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from uoh_mh01.domain.canonical import canonical_json
from uoh_mh01.report.consensus import (
    CONSENSUS_KEY,
    consensus_json,
    consensus_signature,
    sign_then_insert,
    symmetric_scope,
    verify_signed,
)

VECTOR = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "vectors" / "report_consensus.json").read_text(encoding="utf-8")
)
CASES = list(enumerate(VECTOR["vectors"], start=1))


def _ids(case):
    return f"vector{case[0]}"


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_signature_reproduces_the_vector(case):
    _, vector = case
    assert consensus_signature(vector["report"]) == vector["signature"]


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_sign_then_insert_reproduces_the_vectors_signed_report(case):
    _, vector = case
    assert sign_then_insert(vector["report"]) == vector["signed_report"]


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_verification_pops_the_key_reserializes_and_matches(case):
    _, vector = case
    assert verify_signed(vector["signed_report"])


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_the_compact_wire_form_does_not_reproduce_this_signature(case):
    """The whole trap, pinned. If someone reuses domain/canonical.py here, the
    signature silently becomes `compact_form_sha256` — internally consistent,
    locally green, and rejected by the opponent at settlement."""
    _, vector = case
    compact = hashlib.sha256(canonical_json(vector["report"]).encode("utf-8")).hexdigest()
    assert compact == vector["compact_form_sha256"], "our wire canonicaliser is not the kit's compact form"
    assert compact != vector["signature"], "the two forms must not coincide"


def test_the_serialization_is_spaced_not_compact():
    payload = {"b": 1, "a": [1, 2]}
    assert consensus_json(payload) == '{"a": [1, 2], "b": 1}'
    assert canonical_json(payload) == '{"a":[1,2],"b":1}'


def test_the_signature_key_is_the_hebrew_one_both_authorities_use():
    assert VECTOR["signature_key"] == CONSENSUS_KEY


def test_a_document_with_no_signature_does_not_verify():
    assert not verify_signed({"game_id": "a-vs-b"})


def test_a_tampered_body_does_not_verify():
    signed = sign_then_insert({"game_id": "a-vs-b", "score": 20})
    signed["score"] = 25
    assert not verify_signed(signed)


def test_symmetric_scope_excludes_everything_two_honest_peers_differ_on():
    """Timestamps and per-peer token counts legitimately differ between the two
    sides, so hashing them could never produce equal signatures."""
    row = {
        "sub_game_number": 1,
        "roles": {"a": "police", "b": "thief"},
        "result": "survival",
        "winner_group": "b",
        "score": {"a": 5, "b": 10},
        "started_at": "2026-08-23T20:01:44+00:00",
        "ended_at": "2026-08-23T20:04:02+00:00",
        "tokens": {"a": 0, "b": 4711},
        "github_commit": {"a": "abc", "b": "def"},
        "audit": {"log_verified": True},
    }
    scope = symmetric_scope("a-vs-b", {"total_score": {"a": 5, "b": 10}}, [row])
    assert set(scope["sub_games"][0]) == {"sub_game_number", "roles", "result", "winner_group", "score"}
    # The same sub-game seen from the other peer — different clock, different
    # token count — must hash identically.
    other = {**row, "started_at": "2026-08-23T20:01:45+00:00", "tokens": {"a": 9, "b": 1}}
    assert consensus_signature(scope) == consensus_signature(
        symmetric_scope("a-vs-b", {"total_score": {"a": 5, "b": 10}}, [other])
    )
