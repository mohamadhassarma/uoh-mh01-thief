import json

import pytest

from uoh_mh01.infra.artifacts import (
    LogArtifactBuilder,
    build_config_artifact,
    build_declaration,
    write_json,
)


def test_declaration_carries_the_book_app_f_table_20_link_grammar():
    doc = build_declaration(
        game_id="alpha-vs-bravo", game_uid="uid-1", num_sub_games=6, groups={"a": {}, "b": {}}, started_at="t0", ended_at="t1"
    )
    assert doc["links"]["declaration"] == "declaration_alpha-vs-bravo.json"
    assert doc["links"]["config"] == "config_alpha-vs-bravo_g<NN>.json"
    assert doc["links"]["log"] == "log_alpha-vs-bravo_g<NN>.json"
    assert doc["links"]["result"] == "result_alpha-vs-bravo.json"
    assert doc["num_sub_games"] == 6


def test_config_artifact_name_is_zero_padded_and_self_hashing():
    doc = build_config_artifact(game_id="alpha-vs-bravo", game_uid="uid-1", sub_game_number=3, terms={"a": 1})
    assert doc["config_name"] == "config_alpha-vs-bravo_g03.json"
    assert len(doc["config_sha256"]) == 64  # a real sha256 hex digest, not a placeholder


def test_config_artifact_hash_changes_if_terms_change():
    a = build_config_artifact(game_id="g", game_uid="u", sub_game_number=1, terms={"a": 1})
    b = build_config_artifact(game_id="g", game_uid="u", sub_game_number=1, terms={"a": 2})
    assert a["config_sha256"] != b["config_sha256"]


def test_log_artifact_builder_records_and_reports_audit():
    builder = LogArtifactBuilder(
        game_id="alpha-vs-bravo", game_uid="uid-1", sub_game_number=1, role="police", group_id="alpha",
        opponent_group_id="bravo", started_at="2026-08-23T22:41:00+00:00",
    )
    builder.add_record(1, {"step": 1}, "nonce1", "commit1")
    doc = builder.build(
        result="capture_landing", winner_role="police", offending_side=None, steps=1,
        audit_of_opponent_passed=True, audit_verified_steps=1, audit_failed_steps=[],
    )
    assert doc["summary"]["result"] == "capture_landing"
    assert doc["summary"]["offending_side"] is None
    assert doc["summary"]["audit"]["passed"] is True
    assert doc["records"][0]["commit"] == "commit1"


def test_write_json_round_trips_and_preserves_native_utf8(tmp_path):
    path = tmp_path / "out.json"
    write_json(path, {"hint": "אני ליד הכיכר"})
    raw_bytes = path.read_bytes()
    assert "אני".encode() in raw_bytes  # native UTF-8 on disk, not \uXXXX-escaped
    assert json.loads(path.read_text(encoding="utf-8"))["hint"] == "אני ליד הכיכר"


def test_started_at_is_the_caller_s_timestamp_not_the_construction_moment():
    """The builder is constructed at the END of a sub-game, so anything it
    stamps itself is an end time wearing a start time's name. Every sub-game in
    the ali-ahm1 series reported a duration of about 100 microseconds because of
    exactly that.
    """
    began = "2026-08-23T22:41:00+00:00"
    doc = LogArtifactBuilder(
        game_id="alpha-vs-bravo", game_uid="uid-1", sub_game_number=1, role="police", group_id="alpha",
        opponent_group_id="bravo", started_at=began,
    ).build(
        result="capture_landing", winner_role="police", offending_side=None, steps=1,
        audit_of_opponent_passed=True, audit_verified_steps=1, audit_failed_steps=[],
    )
    summary = doc["summary"]
    assert summary["started_at"] == began
    assert summary["ended_at"] > began, "ended_at must be stamped at build time, not carried in"


def test_the_builder_refuses_to_invent_a_start_time():
    """No `default_factory`: a caller that does not know when the sub-game began
    must fail loudly rather than be handed the current moment."""
    with pytest.raises(TypeError, match="started_at"):
        LogArtifactBuilder(
            game_id="alpha-vs-bravo", game_uid="uid-1", sub_game_number=1, role="police", group_id="alpha",
            opponent_group_id="bravo",
        )
