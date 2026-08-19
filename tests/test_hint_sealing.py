"""PRD-05 section C: the hint text AND the self-declared truth/lie verdict
are both part of the sealed record, so "lying about whether you lied" is
caught by the SAME commit-reveal mechanism as everything else — no new
sanction path, just consequence of sealing the verdict at all."""

from __future__ import annotations

from uoh_mh01.domain.crypto import seal, verify
from uoh_mh01.domain.sealed_payload import build_move_payload


def _payload(hint: str, hint_is_true: bool | None) -> dict:
    return build_move_payload(
        step=1, role="thief", action_type="move", detail="N", state="grid=7x7;self=[3, 3];barriers=[]",
        hint=hint, hint_is_true=hint_is_true,
    )


def test_hint_and_verdict_are_part_of_the_sealed_payload():
    payload = _payload("I am near the center.", True)
    assert payload["hint"] == "I am near the center."
    assert payload["hint_is_true"] is True


def test_honest_reveal_verifies():
    payload = _payload("I am near the center.", True)
    sealed = seal(payload)
    assert verify(payload, sealed["nonce"], sealed["commit"])


def test_revealing_a_different_verdict_than_what_was_sealed_fails_verification():
    # Sent live with verdict True, but the sender later tries to reveal
    # (i.e. claim it sealed) verdict False for the SAME nonce/commit — this
    # is exactly "lying about whether you lied", and it must fail exactly
    # like any other tampered field.
    sent_payload = _payload("I am near the center.", True)
    sealed = seal(sent_payload)
    tampered_reveal = _payload("I am near the center.", False)
    assert not verify(tampered_reveal, sealed["nonce"], sealed["commit"])


def test_revealing_a_different_hint_text_than_what_was_sealed_fails_verification():
    sent_payload = _payload("I am near the center.", True)
    sealed = seal(sent_payload)
    tampered_reveal = _payload("I am near the west.", True)
    assert not verify(tampered_reveal, sealed["nonce"], sealed["commit"])


def test_default_hint_is_true_is_none_and_still_seals_consistently():
    payload = _payload("", None)
    sealed = seal(payload)
    assert verify(payload, sealed["nonce"], sealed["commit"])
