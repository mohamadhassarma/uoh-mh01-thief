"""PRD-05 close-out: the real, role-alternating `peer` CLI series must run
the ROLE-CORRECT brain on every sub-game, not just once from the process's
natural role. This was a genuine bug found via a live rehearsal — see
`infra/series_subgame.py::_strategy_for_sub_game` and its unit-level
coverage in `test_series_subgame.py` — but that test never drives the REAL
subprocess CLI path the bug actually lived in. This test does: two real
`python -m uoh_mh01 peer` subprocesses, both configured with two
DISTINGUISHABLE marker brains (`tests/marker_brains.py`), and the log
artifacts alone must prove the correct brain ran each sub-game regardless
of which process embodied which role that sub-game.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_config_json(path: Path) -> None:
    raw = json.loads((REPO_ROOT / "config" / "game.json").read_text(encoding="utf-8"))
    raw["network_and_league"]["num_games"] = 2  # odd + even sub-game is enough to prove alternation
    raw["movement_and_barriers"]["max_moves"] = 3
    raw["movement_and_barriers"]["survival_threshold"] = 3
    raw["network_and_league"]["response_timeout_sec"] = 8
    raw["network_and_league"]["watchdog_timeout_sec"] = 12
    # Mid-board starts (not the real contract's corner starts): N/S must
    # stay legal for a few real turns so the marker brains' distinguishing
    # move is never masked by a STAY fallback near a board edge.
    raw["board_and_agents"]["cop_start"] = [3, 0]
    raw["board_and_agents"]["thief_start"] = [3, 6]
    path.write_text(json.dumps(raw), encoding="utf-8")


def _write_peer_toml(path: Path, *, my_port: int, opponent_port: int, group_id: str) -> None:
    path.write_text(
        f"""\
version = "1.10"

[game]
group_name = "Role-Alternation-{group_id}"
group_id = "{group_id}"

[network]
my_port = {my_port}
opponent_url = "http://127.0.0.1:{opponent_port}/mcp"
turn_timeout_seconds = 30

[strategy]
police_class = "tests.marker_brains:AlwaysNorthBrain"
thief_class = "tests.marker_brains:AlwaysSouthBrain"
""",
        encoding="utf-8",
    )


def _peer_command(role: str, config_json: Path, peer_toml: Path, log_dir: Path, seed: int) -> list[str]:
    return [
        sys.executable, "-m", "uoh_mh01", "peer",
        "--role", role,
        "--config", str(config_json),
        "--peer-config", str(peer_toml),
        "--log-dir", str(log_dir),
        "--seed", str(seed),
    ]


def _own_move_letters(log: dict) -> list[str]:
    """The directions THIS side's own sealed records actually claim to have
    moved — `payload.detail` for every `action_type == "move"` record."""
    return [r["payload"]["detail"] for r in log["records"] if r["payload"]["action_type"] == "move"]


def test_real_cli_series_runs_the_role_correct_brain_every_sub_game(tmp_path):
    police_port, thief_port = 18841, 18842
    config_json = tmp_path / "game.json"
    _write_config_json(config_json)

    police_dir, thief_dir = tmp_path / "police", tmp_path / "thief"
    police_dir.mkdir()
    thief_dir.mkdir()
    police_toml, thief_toml = police_dir / "game.toml", thief_dir / "game.toml"
    _write_peer_toml(police_toml, my_port=police_port, opponent_port=thief_port, group_id="alpha")
    _write_peer_toml(thief_toml, my_port=thief_port, opponent_port=police_port, group_id="bravo")

    police_proc = subprocess.Popen(
        _peer_command("police", config_json, police_toml, police_dir, seed=1),
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    thief_proc = subprocess.Popen(
        _peer_command("thief", config_json, thief_toml, thief_dir, seed=2),
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        police_out, _ = police_proc.communicate(timeout=90)
        thief_out, _ = thief_proc.communicate(timeout=90)
    finally:
        for proc in (police_proc, thief_proc):
            if proc.poll() is None:
                proc.kill()

    assert police_proc.returncode == 0, f"police process failed:\n{police_out}\n---THIEF---\n{thief_out}"
    assert thief_proc.returncode == 0, f"thief process failed:\n{thief_out}\n---POLICE---\n{police_out}"

    game_id = "-vs-".join(sorted(["alpha", "bravo"]))
    for sub_game_number in (1, 2):
        suffix = f"{game_id}_g{sub_game_number:02d}.json"
        police_log = json.loads((police_dir / f"log_{suffix}").read_text(encoding="utf-8"))
        thief_log = json.loads((thief_dir / f"log_{suffix}").read_text(encoding="utf-8"))

        # Whichever PROCESS is playing POLICE this sub-game must show only
        # 'N' moves (AlwaysNorthBrain); whichever plays THIEF, only 'S'
        # (AlwaysSouthBrain) — regardless of which process that is.
        police_side_log = police_log if police_log["summary"]["role"] == "police" else thief_log
        thief_side_log = thief_log if thief_log["summary"]["role"] == "thief" else police_log
        assert police_side_log is not thief_side_log, "exactly one side must be playing each role"

        police_moves = _own_move_letters(police_side_log)
        thief_moves = _own_move_letters(thief_side_log)
        assert police_moves and all(m == "N" for m in police_moves), (sub_game_number, police_moves)
        assert thief_moves and all(m == "S" for m in thief_moves), (sub_game_number, thief_moves)
