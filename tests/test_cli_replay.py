"""The `replay` command's output and exit status.

The exit code matters as much as the text: a verifier that prints TAMPERED but
exits 0 cannot be used as a check by anything except a human reading carefully.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uoh_mh01.__main__ import main
from uoh_mh01.domain.crypto import seal

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_GAME_ID = "ali-ahm1-vs-uoh-mh01"


def _series(tmp_path: Path, *, tamper: bool = False) -> str:
    game_id = "them-vs-us"
    (tmp_path / f"declaration_{game_id}.json").write_text(
        json.dumps({"game_id": game_id, "game_uid": "uid-1234"}), encoding="utf-8"
    )
    records = []
    for step in (1, 2):
        payload = {"step": step, "role": "police", "action_type": "move", "detail": "N"}
        sealed = seal(payload)
        records.append({"payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"], "step": step})
    if tamper:
        records[0]["payload"]["detail"] = "S"
    (tmp_path / f"log_{game_id}_g01.json").write_text(
        json.dumps(
            {
                "game_id": game_id,
                "game_uid": "uid-1234",
                "summary": {"sub_game_number": 1, "role": "police", "group_id": "uoh-mh01", "result": "survival"},
                "records": records,
            }
        ),
        encoding="utf-8",
    )
    return game_id


def test_an_intact_series_prints_verified_ok_and_exits_zero(tmp_path, capsys):
    game_id = _series(tmp_path)
    code = main(["replay", "--game-id", game_id, "--log-dir", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 0
    assert "SERIES VERDICT: Verified OK" in out
    assert "TAMPERED" not in out


def test_a_tampered_series_says_so_and_exits_non_zero(tmp_path, capsys):
    """Usable as a check, not just a display."""
    game_id = _series(tmp_path, tamper=True)
    code = main(["replay", "--game-id", game_id, "--log-dir", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 1
    assert "SERIES VERDICT: TAMPERED" in out
    assert "failed steps: [1]" in out, "it must say WHICH step"


def test_a_missing_series_is_reported_without_a_traceback(tmp_path, capsys):
    code = main(["replay", "--game-id", "no-such-game", "--log-dir", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 2
    assert "cannot replay" in captured.err
    assert "Traceback" not in captured.err


def test_the_report_is_pure_ascii(tmp_path, capsys):
    """It is graded from a screenshot and this console is cp1255, where a
    non-ASCII character crashes the command before it prints anything."""
    game_id = _series(tmp_path)
    main(["replay", "--game-id", game_id, "--log-dir", str(tmp_path)])
    assert capsys.readouterr().out.isascii()


def test_the_report_explains_the_step_zero_rule(tmp_path, capsys):
    """A reader looking at "35 records, 34 re-hashed" must not have to guess
    where the missing one went."""
    game_id = _series(tmp_path)
    main(["replay", "--game-id", game_id, "--log-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "Step-0" in out
    assert "disclosure-only" in out


@pytest.mark.skipif(
    not (REPO_ROOT / "logs" / f"declaration_{REAL_GAME_ID}.json").is_file(),
    reason="the ali-ahm1 artifacts are not in this checkout",
)
def test_the_real_played_series_verifies_through_the_cli(capsys):
    """The screenshot in docs/screenshots is of this exact command."""
    code = main(["replay", "--game-id", REAL_GAME_ID, "--log-dir", str(REPO_ROOT / "logs")])
    out = capsys.readouterr().out

    assert code == 0
    assert "SERIES VERDICT: Verified OK" in out
    assert "sealed steps re-hashed (SHA-256)" in out
