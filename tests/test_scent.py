"""PRD-04 conformance: this project's own `domain/scent.py` checked against
the interop kit's PROMOTED `multiplicative_book_v1` vector *data*
(tests/fixtures/vectors/scent_book_v3.json — no kit code imported), plus the
float-determinism requirement PRD-04 calls out explicitly: the same field
computed twice in one process, and once more in a fresh subprocess, must
serialize to byte-identical JSON.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from uoh_mh01.domain.board import Board, Position
from uoh_mh01.domain.canonical import canonical_json
from uoh_mh01.domain.scent import advance_field, deserialize_field, emit, serialize_field
from uoh_mh01.shared.locked_model import SCENT_MODEL_DOC, scent_model_sha256

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vectors"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_emit_vectors_reproduce_the_kernel(config):
    data = _load("scent_book_v3.json")
    for case in data["emit"]:
        board = Board(grid_size=7)
        got = serialize_field(emit(Position(*case["center"]), board, config.pheromones))
        assert got == case["field"], case["note"]


def test_scalar_pure_decay_vector(config):
    trace = _load("scent_book_v3.json")["scalar_traces"]["pure_decay"]
    result = advance_field({Position(0, 0): trace["tau"]}, {}, config.pheromones)
    assert result[Position(0, 0)] == trace["after"]


def test_scalar_clamp_vector_enforces_the_upper_bound(config):
    trace = _load("scent_book_v3.json")["scalar_traces"]["clamp"]
    result = advance_field({Position(0, 0): trace["tau"]}, {Position(0, 0): trace["delta"]}, config.pheromones)
    assert result[Position(0, 0)] == trace["after"]


def test_scalar_chain_vector_from_an_empty_start(config):
    chain = _load("scent_book_v3.json")["scalar_traces"]["chain"]
    field: dict = {}
    for step in chain["steps"]:
        field = advance_field(field, {Position(0, 0): step["delta"]}, config.pheromones)
        assert field[Position(0, 0)] == step["tau"]
    # The fork: the SAME turn-2 predecessor (tau=0.758), a different deposit.
    predecessor = chain["steps"][1]["tau"]
    forked = advance_field({Position(0, 0): predecessor}, {Position(0, 0): 0.14}, config.pheromones)
    assert forked[Position(0, 0)] == chain["fork_at_turn_3_with_delta_0_14"]


def test_field_walk_vector_three_full_turns_of_a_moving_agent(config_factory):
    data = _load("scent_book_v3.json")["field_walk"]
    config = config_factory(grid_size=data["board_size"])
    board = Board(grid_size=data["board_size"])
    field: dict = {}
    for turn in data["turns"]:
        deposit = emit(Position(*turn["center"]), board, config.pheromones)
        field = advance_field(field, deposit, config.pheromones)
        assert serialize_field(field) == turn["field"], f"turn {turn['turn']}"


def test_deserialize_field_round_trips_through_serialize(config):
    board = Board(grid_size=7)
    field = emit(Position(3, 3), board, config.pheromones)
    wire = serialize_field(field)
    assert deserialize_field(wire) == field


def test_locked_scent_model_matches_the_kit_promoted_hash():
    # tests/fixtures/vectors/README.md's own integrity boundary: check
    # against the kit's PUBLISHED hash value, not against imported kit code.
    # Interop kit vectors/locked_model.json registers `multiplicative_book_v1`
    # (status PROMOTED) under this exact sha256 — reproducing it byte-for-byte
    # is a real, independent conformance signal that our canonical_json and
    # doc construction match a real external implementation's.
    assert SCENT_MODEL_DOC["params"]["kernel"] == _load("scent_book_v3.json")["kernel"]
    assert scent_model_sha256() == "934c220d5bf62acaa3297c6c9d723ea954c220260b02292ca17f6d5daef9f4d9"


def test_same_field_computed_twice_in_process_is_byte_identical(config):
    board = Board(grid_size=7)
    field_a = advance_field({}, emit(Position(3, 3), board, config.pheromones), config.pheromones)
    field_b = advance_field({}, emit(Position(3, 3), board, config.pheromones), config.pheromones)
    assert canonical_json(serialize_field(field_a)) == canonical_json(serialize_field(field_b))


def test_same_field_computed_in_a_fresh_subprocess_is_byte_identical(config, tmp_path):
    # PRD-04's own determinism requirement: not just "same process, twice" —
    # a genuinely separate Python process must serialize to the exact same
    # bytes, since this crosses the wire and gets sealed into a commit hash.
    board = Board(grid_size=7)
    field = advance_field({}, emit(Position(3, 3), board, config.pheromones), config.pheromones)
    here_bytes = canonical_json(serialize_field(field)).encode("utf-8")

    script = tmp_path / "compute_field.py"
    script.write_text(
        "from uoh_mh01.domain.board import Board, Position\n"
        "from uoh_mh01.domain.canonical import canonical_json\n"
        "from uoh_mh01.domain.scent import advance_field, emit, serialize_field\n"
        "from uoh_mh01.domain.config_models import PheromoneConfig\n"
        "pheromones = PheromoneConfig(center_intensity=0.9, decay=0.1, grid_size=5, min_center_intensity=0.5)\n"
        "board = Board(grid_size=7)\n"
        "field = advance_field({}, emit(Position(3, 3), board, pheromones), pheromones)\n"
        "print(canonical_json(serialize_field(field)), end='')\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(script)], capture_output=True, check=True)
    assert result.stdout == here_bytes
