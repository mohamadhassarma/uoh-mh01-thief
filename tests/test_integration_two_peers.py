"""End-to-end integration test: spawns BOTH peers as real, separate OS
processes (not simulated in-process) and lets them play a full
`num_games`-sub-game series over real localhost HTTP — handshake, role
alternation, real commit-reveal, and a mutual audit each sub-game. This is
the only test in the suite that actually exercises FastMCP transport and
the full stage-3 protocol end to end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_config_json(path: Path, *, num_games: int) -> None:
    raw = json.loads((REPO_ROOT / "config" / "game.json").read_text(encoding="utf-8"))
    raw["network_and_league"]["num_games"] = num_games
    # Small enough that a random-strategy sub-game (with real network round
    # trips for every action, over `num_games` sub-games) finishes quickly —
    # this test is about the SERIES protocol, not about exercising the real
    # contract's full 35-round length.
    raw["movement_and_barriers"]["max_moves"] = 8
    raw["movement_and_barriers"]["survival_threshold"] = 6
    # Tight retry/wait ceilings so any genuine bug that causes retrying-
    # forever fails FAST (a few seconds) instead of silently burning up to
    # watchdog_timeout_sec on every retry loop in the process (of which
    # there are several: send_with_retry, send_negotiate, send_audit_reveal,
    # wait_for_audit_of_opponent) across every sub-game.
    raw["network_and_league"]["response_timeout_sec"] = 8
    raw["network_and_league"]["watchdog_timeout_sec"] = 12
    path.write_text(json.dumps(raw), encoding="utf-8")


def _write_peer_toml(path: Path, *, my_port: int, opponent_port: int, group_id: str) -> None:
    path.write_text(
        f"""\
version = "1.10"

[game]
group_name = "Integration-Test-{group_id}"
group_id = "{group_id}"
members = ["a", "b"]
repos = {{ cop = "https://example.invalid/{group_id}-police", thief = "https://example.invalid/{group_id}-thief" }}

[network]
my_port = {my_port}
opponent_url = "http://127.0.0.1:{opponent_port}/mcp"
turn_timeout_seconds = 30
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


def _strip_timestamps(records: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k not in ("started_at", "ended_at")} for r in records]


def test_two_real_subprocesses_play_a_full_series_with_role_alternation_and_clean_audits(tmp_path):
    # Distinct from config/{police,thief}/game.toml's real 8801/8802 so this
    # never collides with a peer a human might be running manually.
    police_port, thief_port = 18801, 18802
    num_games = 4  # small but enough to exercise every odd/even role combination

    config_json = tmp_path / "game.json"
    _write_config_json(config_json, num_games=num_games)

    police_dir, thief_dir = tmp_path / "police", tmp_path / "thief"
    police_dir.mkdir()
    thief_dir.mkdir()
    police_toml, thief_toml = police_dir / "game.toml", thief_dir / "game.toml"
    _write_peer_toml(police_toml, my_port=police_port, opponent_port=thief_port, group_id="alpha")
    _write_peer_toml(thief_toml, my_port=thief_port, opponent_port=police_port, group_id="bravo")

    # Two genuinely separate OS processes. No shared module, no shared
    # file: each reads only its OWN game.toml and writes only into its OWN
    # log directory. The signed config/game.json is the only thing they
    # read in common — the explicitly-allowed exception (read-only).
    police_proc = subprocess.Popen(
        _peer_command("police", config_json, police_toml, police_dir, seed=11),
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    thief_proc = subprocess.Popen(
        _peer_command("thief", config_json, thief_toml, thief_dir, seed=22),
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    assert police_proc.pid != thief_proc.pid

    try:
        police_out, _ = police_proc.communicate(timeout=120)
        thief_out, _ = thief_proc.communicate(timeout=120)
    finally:
        for proc in (police_proc, thief_proc):
            if proc.poll() is None:
                proc.kill()

    assert police_proc.returncode == 0, f"police process failed:\n{police_out}\n---THIEF---\n{thief_out}"
    assert thief_proc.returncode == 0, f"thief process failed:\n{thief_out}\n---POLICE---\n{police_out}"

    game_id = "-vs-".join(sorted(["alpha", "bravo"]))

    police_decl = json.loads((police_dir / f"declaration_{game_id}.json").read_text(encoding="utf-8"))
    thief_decl = json.loads((thief_dir / f"declaration_{game_id}.json").read_text(encoding="utf-8"))
    assert police_decl["game_uid"] == thief_decl["game_uid"]
    assert police_decl["num_sub_games"] == num_games

    seen_roles = {"police": [], "thief": []}
    for sub_game_number in range(1, num_games + 1):
        suffix = f"{game_id}_g{sub_game_number:02d}.json"
        police_log = json.loads((police_dir / f"log_{suffix}").read_text(encoding="utf-8"))
        thief_log = json.loads((thief_dir / f"log_{suffix}").read_text(encoding="utf-8"))

        assert police_log["game_uid"] == police_decl["game_uid"] == thief_log["game_uid"]
        # Roles are complementary and alternate: odd = natural, even = swapped.
        assert {police_log["summary"]["role"], thief_log["summary"]["role"]} == {"police", "thief"}
        seen_roles["police"].append(police_log["summary"]["role"] == "police")
        # Both sides independently reached, and agree on, the same terminal condition.
        assert police_log["summary"]["result"] == thief_log["summary"]["result"]
        assert police_log["summary"]["result"] not in (None, "undefined", "disputed")
        # Each side's own mutual audit of the OTHER found no tampering.
        if not (police_log["summary"]["audit"]["passed"] and thief_log["summary"]["audit"]["passed"]):
            import os

            dump_dir = os.environ.get("AUDIT_DEBUG_DIR")
            if dump_dir:
                Path(dump_dir).mkdir(parents=True, exist_ok=True)
                (Path(dump_dir) / f"police_g{sub_game_number:02d}.json").write_text(json.dumps(police_log, indent=2), encoding="utf-8")
                (Path(dump_dir) / f"thief_g{sub_game_number:02d}.json").write_text(json.dumps(thief_log, indent=2), encoding="utf-8")
        assert police_log["summary"]["audit"]["passed"] is True, sub_game_number
        assert thief_log["summary"]["audit"]["passed"] is True, sub_game_number
        assert police_log["summary"]["audit"]["failed_steps"] == []

        police_config = json.loads((police_dir / f"config_{suffix}").read_text(encoding="utf-8"))
        thief_config = json.loads((thief_dir / f"config_{suffix}").read_text(encoding="utf-8"))
        assert police_config["config_sha256"] == thief_config["config_sha256"]

    # Role alternation actually happened: police-repo process played police
    # on some sub-games and thief on others.
    assert True in seen_roles["police"] and False in seen_roles["police"]
