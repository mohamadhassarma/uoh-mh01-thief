"""PRD-03 "Symmetric timeout outcomes": a timing-out peer must produce a
SYMMETRIC result — both sides agreeing on the SAME terminal condition and
the SAME offending party. Never one side reading survival while the other
reads technical loss.

Two fast, deterministic unit tests exercise the fix directly
(`receive_opponent_move`'s idempotent replay and post-finish rejection).
The third, slow test reproduces the original failure end to end, over two
real subprocesses, at the REAL signed contract values (no shrunk
timeouts) — a genuinely stalled peer, not an artificially tight budget.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

from uoh_mh01.domain.board import Direction
from uoh_mh01.domain.match import MoveAction
from uoh_mh01.domain.scoring import TerminalCondition
from uoh_mh01.domain.state import Side
from uoh_mh01.infra.protocol_builders import action_to_request
from uoh_mh01.orchestrator import PeerRuntime
from uoh_mh01.shared.peer_config import PeerConfig

REPO_ROOT = Path(__file__).resolve().parents[1]


def _peer_config(role: str = "police") -> PeerConfig:
    return PeerConfig(
        role=role, group_id="test-group", group_name="Test Group",
        my_port=8801, opponent_url="http://127.0.0.1:8802/mcp", turn_timeout_seconds=180,
    )


async def test_duplicate_commit_is_replayed_not_reapplied(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.THIEF)

    request = action_to_request(
        MoveAction(Direction.W), Side.THIEF, runtime.state.turn_number,
        police_actions_taken=0, thief_actions_taken=1, commit="fixed-test-commit-abc",
    )
    first = await runtime.receive_opponent_move(request)
    state_after_first = runtime.state

    # A retry of the IDENTICAL commit (what send_with_retry does after a
    # lost/delayed response) must get back the SAME answer, not be
    # re-evaluated against the now-advanced state.
    second = await runtime.receive_opponent_move(request)

    assert second == first
    assert runtime.state is state_after_first


async def test_message_after_self_declared_finish_is_rejected_not_reapplied(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.THIEF)
    runtime._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=Side.THIEF)  # simulate a timeout self-declare
    original_state = runtime.state
    original_outcome = runtime.outcome

    request = action_to_request(
        MoveAction(Direction.W), Side.THIEF, runtime.state.turn_number,
        police_actions_taken=0, thief_actions_taken=1, commit="late-arriving-commit",
    )
    response = await runtime.receive_opponent_move(request)

    assert response.accepted is False
    assert "already finished" in response.reason
    assert runtime.state is original_state
    assert runtime.outcome is original_outcome


def _write_config_json(path: Path) -> None:
    raw = json.loads((REPO_ROOT / "config" / "game.json").read_text(encoding="utf-8"))
    raw["network_and_league"]["num_games"] = 1  # one sub-game is enough to exercise the race
    path.write_text(json.dumps(raw), encoding="utf-8")  # response_timeout_sec/watchdog_timeout_sec: UNCHANGED (30/60)


def _write_peer_toml(path: Path, *, my_port: int, opponent_port: int, group_id: str) -> None:
    path.write_text(
        f"""\
version = "1.10"

[game]
group_name = "Symmetric-Timeout-{group_id}"
group_id = "{group_id}"

[network]
my_port = {my_port}
opponent_url = "http://127.0.0.1:{opponent_port}/mcp"
turn_timeout_seconds = 180
""",
        encoding="utf-8",
    )


def test_a_genuinely_stalled_peer_produces_a_symmetric_technical_loss(tmp_path):
    """Reproduces the originally-observed asymmetric split
    (police=technical_loss / thief=survival) directly: police's strategy
    blocks for 65s on its very first action — comfortably past the REAL
    watchdog_timeout_sec=60 from config/game.json, unmodified — while thief
    sits in _wait_for_opponent. Before the fix, thief self-declared a
    timeout technical loss at t~60s, and police's later-arriving move (sent
    at t~65s) was freshly re-evaluated as an ordinary move and accepted,
    diverging from thief's already-finished outcome. After the fix, police's
    late move is rejected as "already finished," and police correctly
    self-blames — both sides land on the SAME condition and the SAME party.
    """
    police_port, thief_port = 38801, 38802
    config_json = tmp_path / "game.json"
    _write_config_json(config_json)

    police_dir, thief_dir = tmp_path / "police", tmp_path / "thief"
    police_dir.mkdir()
    thief_dir.mkdir()
    police_toml, thief_toml = police_dir / "game.toml", thief_dir / "game.toml"
    _write_peer_toml(police_toml, my_port=police_port, opponent_port=thief_port, group_id="alpha")
    _write_peer_toml(thief_toml, my_port=thief_port, opponent_port=police_port, group_id="bravo")

    runner = str(Path(__file__).resolve().parent / "_stalling_peer_runner.py")
    police_proc = subprocess.Popen(
        [sys.executable, runner, "--role", "police", "--config", str(config_json), "--peer-config", str(police_toml),
         "--log-dir", str(police_dir), "--seed", "11", "--stall-turn", "1", "--stall-seconds", "65"],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    thief_proc = subprocess.Popen(
        [sys.executable, runner, "--role", "thief", "--config", str(config_json), "--peer-config", str(thief_toml),
         "--log-dir", str(thief_dir), "--seed", "22"],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    try:
        police_out, _ = police_proc.communicate(timeout=180)
        thief_out, _ = thief_proc.communicate(timeout=180)
    finally:
        for proc in (police_proc, thief_proc):
            if proc.poll() is None:
                proc.kill()

    assert police_proc.returncode == 0, f"police process failed:\n{police_out}\n---THIEF---\n{thief_out}"
    assert thief_proc.returncode == 0, f"thief process failed:\n{thief_out}\n---POLICE---\n{police_out}"

    game_id = "-vs-".join(sorted(["alpha", "bravo"]))
    suffix = f"{game_id}_g01.json"
    police_log = json.loads((police_dir / f"log_{suffix}").read_text(encoding="utf-8"))
    thief_log = json.loads((thief_dir / f"log_{suffix}").read_text(encoding="utf-8"))

    assert police_log["summary"]["result"] == "technical_loss", police_log["summary"]
    assert thief_log["summary"]["result"] == "technical_loss", thief_log["summary"]
    # Both sides must blame the SAME party (the one that was actually slow).
    assert police_log["summary"].get("offending_side") == thief_log["summary"].get("offending_side")
