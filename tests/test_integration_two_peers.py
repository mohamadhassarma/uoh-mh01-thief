"""End-to-end integration test: spawns BOTH peers as real, separate OS
processes (not simulated in-process) and lets them play a full match over
real localhost HTTP. This is the only test in the suite that actually
exercises FastMCP transport end to end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_JSON = REPO_ROOT / "config" / "game.json"


def _write_peer_toml(path: Path, *, my_port: int, opponent_port: int, group_id: str) -> None:
    path.write_text(
        f"""\
version = "1.10"

[game]
group_name = "Integration Test"
group_id = "{group_id}"
sub_game_number = 1
members = ["a", "b"]

[network]
my_port = {my_port}
opponent_url = "http://127.0.0.1:{opponent_port}/mcp"
turn_timeout_seconds = 30
""",
        encoding="utf-8",
    )


def _peer_command(role: str, peer_toml: Path, log_path: Path, seed: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uoh_mh01",
        "peer",
        "--role",
        role,
        "--config",
        str(CONFIG_JSON),
        "--peer-config",
        str(peer_toml),
        "--log",
        str(log_path),
        "--seed",
        str(seed),
    ]


def _strip_timestamps(entries: list[dict]) -> list[dict]:
    return [{k: v for k, v in entry.items() if k != "timestamp"} for entry in entries]


def test_two_real_subprocesses_play_a_full_match_and_agree(tmp_path):
    # Ports distinct from the real config/{police,thief}/game.toml defaults
    # (8801/8802) so this never collides with a peer a human might be
    # running manually at the same time.
    police_port, thief_port = 18801, 18802

    police_dir = tmp_path / "police"
    thief_dir = tmp_path / "thief"
    police_dir.mkdir()
    thief_dir.mkdir()

    police_toml = police_dir / "game.toml"
    thief_toml = thief_dir / "game.toml"
    _write_peer_toml(police_toml, my_port=police_port, opponent_port=thief_port, group_id="integration-test")
    _write_peer_toml(thief_toml, my_port=thief_port, opponent_port=police_port, group_id="integration-test")

    police_log = police_dir / "police_match.json"
    thief_log = thief_dir / "thief_match.json"

    # Two genuinely separate OS processes. No shared module, no shared
    # file: each reads only its OWN game.toml (in its own directory) and
    # writes only its OWN log (in its own directory). The signed
    # config/game.json is the only thing they read in common — that is the
    # explicitly-allowed exception (it's read-only), not a violation of the
    # Zero-Trust "no shared state" rule.
    police_proc = subprocess.Popen(
        _peer_command("police", police_toml, police_log, seed=11),
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    thief_proc = subprocess.Popen(
        _peer_command("thief", thief_toml, thief_log, seed=22),
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert police_proc.pid != thief_proc.pid  # genuinely separate processes

    try:
        police_out, _ = police_proc.communicate(timeout=90)
        thief_out, _ = thief_proc.communicate(timeout=90)
    finally:
        for proc in (police_proc, thief_proc):
            if proc.poll() is None:
                proc.kill()

    assert police_proc.returncode == 0, f"police process failed:\n{police_out}"
    assert thief_proc.returncode == 0, f"thief process failed:\n{thief_out}"

    police_result = json.loads(police_log.read_text(encoding="utf-8"))
    thief_result = json.loads(thief_log.read_text(encoding="utf-8"))

    # Each process only ever knew about itself.
    assert police_result["role"] == "police"
    assert thief_result["role"] == "thief"

    # Both processes independently reached a terminal condition, and it's
    # the SAME one — this is the actual point of the exercise: two
    # processes, no shared memory, each computing from its own copy of the
    # rules, converging on an identical outcome purely through the MCP
    # exchange.
    assert police_result["terminal"] is not None
    assert police_result["terminal"] == thief_result["terminal"]

    # And the full move sequence agrees too (ignoring wall-clock timestamps,
    # which are never expected to match between two independently-timed
    # processes).
    assert _strip_timestamps(police_result["moves"]) == _strip_timestamps(thief_result["moves"])
