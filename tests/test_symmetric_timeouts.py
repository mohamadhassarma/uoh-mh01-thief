"""PRD-03 "Symmetric timeout outcomes": a timing-out peer must produce a
SYMMETRIC result — both sides agreeing on the SAME terminal condition and
the SAME offending party. Never one side reading survival while the other
reads technical loss.

One fast, deterministic unit test covers a late message arriving after this
side already settled. The slow test reproduces the original failure end to end,
over two real subprocesses, at the REAL signed contract values (no shrunk
timeouts) — a genuinely stalled peer, not an artificially tight budget.

The old duplicate-replay unit test moved to test_claim_protocol.py: with
ack-only tools there is no response to replay, so a retried commit is now
dropped at PROCESSING time instead.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from uoh_mh01.domain.scoring import TerminalCondition
from uoh_mh01.domain.state import Side
from uoh_mh01.infra.turn_message_builders import build_turn_message
from uoh_mh01.orchestrator import PeerRuntime
from uoh_mh01.shared.peer_config import PeerConfig

REPO_ROOT = Path(__file__).resolve().parents[1]


def _peer_config(role: str = "police") -> PeerConfig:
    return PeerConfig(
        role=role, group_id="test-group", group_name="Test Group",
        my_port=8801, opponent_url="http://127.0.0.1:8802/mcp", turn_timeout_seconds=180,
    )


async def test_a_late_turn_after_i_already_settled_does_not_overwrite_my_outcome(config_factory):
    """A message that arrives after this side has already declared a timeout
    must not silently rewrite an outcome already returned to my own caller."""
    config = config_factory(grid_size=5, thief_start=(2, 2))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())
    runtime.whose_turn = Side.THIEF
    runtime._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=Side.THIEF)
    original_state, original_outcome = runtime.state, runtime.outcome

    late = build_turn_message(
        step=1, sender="thief", hint="too late", smell_grid={}, commit="c" * 64,
        win_claim={"type": "survival"},
    ).to_wire()
    await runtime.receive_opponent_turn(late)

    assert runtime.outcome is original_outcome
    assert runtime.state is original_state


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
# PRIVATE per-peer budget, deliberately NOT a signed contract value (the signed
# response_timeout_sec=30 / watchdog_timeout_sec=60 in game.json are untouched).
# Shortened from 180 because ack-only tools changed the endgame: a peer can no
# longer be TOLD by the transport that its opponent already settled — every
# handler returns {{"ok": True}} regardless — so it must wait out this budget.
# At 180 the stalled peer alone added 3 minutes to the run.
turn_timeout_seconds = 30
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
