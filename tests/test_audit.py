"""The mutual audit, reshaped to the contract (docs/WIRE.md §5).

The opponent reveals its FULL chain — `[{payload, nonce, commit}]` — and we
re-hash each record against the commit that arrived LIVE, never against the
`commit` field inside the revealed record (which the revealer controls).
"""

from uoh_mh01.domain.crypto import seal
from uoh_mh01.domain.sealed_payload import build_audit_payload
from uoh_mh01.infra.audit import ReceivedCommitLog, verify_revealed


def _sealed(step: int, text: str) -> dict:
    payload = {"step": step, "detail": text}
    sealed = seal(payload)
    return {"payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"]}


def _live_log(records: list[dict]) -> ReceivedCommitLog:
    """Only the COMMIT crosses the wire during play — that is all we keep."""
    received = ReceivedCommitLog()
    for r in records:
        received.record(r["payload"]["step"], r["commit"])
    return received


def test_honest_full_chain_reveal_passes_with_all_steps_verified():
    records = [_sealed(1, "N"), _sealed(2, "E")]
    result = verify_revealed(records, _live_log(records))

    assert result.passed is True
    assert result.verified_steps == 2
    assert result.failed_steps == ()


def test_wrong_nonce_fails_that_step():
    records = [_sealed(1, "N")]
    tampered = [{**records[0], "nonce": "0" * 32}]

    result = verify_revealed(tampered, _live_log(records))

    assert result.passed is False
    assert result.failed_steps == (1,)


def test_a_rewritten_payload_fails_even_with_a_matching_inline_commit():
    """The load-bearing case for the whole reshape: the revealer rewrites the
    payload AND the `commit` field beside it so they are self-consistent.
    Verifying against the record's own commit would pass; verifying against
    the commit that actually arrived live catches it (WARNINGS §5d)."""
    honest = _sealed(1, "N")
    forged_payload = {"step": 1, "detail": "E"}
    forged = seal(forged_payload)
    rewritten = [{"payload": forged_payload, "nonce": forged["nonce"], "commit": forged["commit"]}]

    result = verify_revealed(rewritten, _live_log([honest]))

    assert result.passed is False
    assert result.failed_steps == (1,)


def test_a_step_never_revealed_is_a_failure_not_silently_skipped():
    records = [_sealed(1, "N"), _sealed(2, "E")]

    # Only step 1 revealed — step 2's commit was received live but never
    # explained. A disclosure that quietly drops a step must fail.
    result = verify_revealed(records[:1], _live_log(records))

    assert result.passed is False
    assert 2 in result.failed_steps


def test_a_step_revealed_with_no_corresponding_live_receipt_fails():
    result = verify_revealed([_sealed(1, "N")], ReceivedCommitLog())
    assert result.passed is False
    assert result.failed_steps == (1,)


def test_audit_payload_is_exactly_the_contract_three_keys():
    payload = build_audit_payload(sender="police", records=[], result_claim="survival")
    assert set(payload) == {"sender", "records", "result_claim"}


# --- the verdict floor (PRD-06 hardening) -------------------------------------


def test_an_empty_reveal_against_an_empty_log_does_not_pass():
    """The exact vacuous-green that hid a real bug: both peers crashed on every
    turn, sealed nothing, exchanged empty reveals, and each reported
    `passed=True, verified_steps=0`. Nothing failed because nothing happened."""
    result = verify_revealed([], ReceivedCommitLog())

    assert result.passed is False
    assert result.verified_steps == 0
    assert "no steps verified" in result.reason


def test_a_reveal_explaining_only_some_played_steps_does_not_pass():
    records = [_sealed(1, "N"), _sealed(2, "E"), _sealed(3, "S")]
    live = _live_log(records)

    # Reveal step 1 honestly; simply never mention 2 and 3.
    result = verify_revealed(records[:1], live)

    assert result.passed is False
    assert result.reason is not None


def test_an_explicit_steps_played_count_is_honoured():
    records = [_sealed(1, "N")]
    result = verify_revealed(records, _live_log(records), steps_played=4)

    assert result.passed is False
    assert result.verified_steps == 1
    assert "4 were played" in result.reason


def test_a_clean_full_reveal_still_passes_with_no_reason():
    records = [_sealed(1, "N"), _sealed(2, "E")]
    result = verify_revealed(records, _live_log(records))

    assert result.passed is True
    assert result.reason is None


def test_a_revealed_step_zero_is_accepted_without_a_live_commit():
    """Cross-team regression, found live against the interop kit's sparring
    peer. Step 0 is the disclosure-only spec record: it is never transmitted as
    a turn (SPEC §7.5 `not_on_this_wire`), so no live commit for it can exist.
    We were failing the opponent's whole audit over it."""
    play = [_sealed(1, "N"), _sealed(2, "E")]
    step_zero = _sealed(0, "spec")

    result = verify_revealed([step_zero, *play], _live_log(play))

    assert result.passed is True
    assert result.failed_steps == ()
    assert result.verified_steps == 2  # step 0 is not a played step


def test_a_self_inconsistent_step_zero_still_fails():
    play = [_sealed(1, "N")]
    forged = {**_sealed(0, "spec"), "commit": "f" * 64}

    result = verify_revealed([forged, *play], _live_log(play))

    assert result.passed is False
    assert 0 in result.failed_steps
