from uoh_mh01.domain.crypto import seal
from uoh_mh01.infra.audit import ReceivedCommitLog, verify_revealed


def _sealed(step: int, text: str) -> dict:
    payload = {"step": step, "detail": text}
    sealed = seal(payload)
    return {"step": step, "payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"]}


def test_honest_reveal_passes_with_all_steps_verified():
    records = [_sealed(1, "N"), _sealed(2, "E")]
    received = ReceivedCommitLog()
    for r in records:
        received.record(r["step"], r["payload"], r["commit"])

    result = verify_revealed([{"step": r["step"], "nonce": r["nonce"]} for r in records], received)

    assert result.passed is True
    assert result.verified_steps == 2
    assert result.failed_steps == ()


def test_wrong_nonce_fails_that_step():
    records = [_sealed(1, "N")]
    received = ReceivedCommitLog()
    received.record(1, records[0]["payload"], records[0]["commit"])

    result = verify_revealed([{"step": 1, "nonce": "0" * 32}], received)

    assert result.passed is False
    assert result.failed_steps == (1,)


def test_a_step_never_revealed_is_a_failure_not_silently_skipped():
    records = [_sealed(1, "N"), _sealed(2, "E")]
    received = ReceivedCommitLog()
    for r in records:
        received.record(r["step"], r["payload"], r["commit"])

    # Only step 1 revealed — step 2's commit was received live but never
    # explained. A disclosure that quietly drops a step must fail, exactly
    # like one that fails to re-hash.
    result = verify_revealed([{"step": 1, "nonce": records[0]["nonce"]}], received)

    assert result.passed is False
    assert 2 in result.failed_steps


def test_a_step_revealed_with_no_corresponding_live_receipt_fails():
    received = ReceivedCommitLog()  # nothing was ever received live
    result = verify_revealed([{"step": 1, "nonce": "0" * 32}], received)
    assert result.passed is False
    assert result.failed_steps == (1,)
