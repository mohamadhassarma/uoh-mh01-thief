"""Load config/<role>/game.toml — the private, per-peer config — and merge
it with the signed config/game.json contract.

Overlay rule (mandatory): where a key exists in BOTH files, the signed
game.json value always wins. The private TOML can never weaken or dilute a
signed condition. This is enforced generically by `overlay_signed_contract`,
a recursive merge where the signed dict wins at every overlapping path, not
by trusting the TOML author to avoid touching signed fields.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PeerConfigError(Exception):
    """Raised when config/<role>/game.toml is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class PeerConfig:
    role: str
    group_id: str
    group_name: str
    my_port: int
    opponent_url: str
    turn_timeout_seconds: float


def _load_toml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except OSError as exc:
        raise PeerConfigError(f"could not read peer config at {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PeerConfigError(f"peer config at {path} is not valid TOML: {exc}") from exc


def _load_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PeerConfigError(f"could not read signed contract at {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PeerConfigError(f"signed contract at {path} is not valid JSON: {exc}") from exc


def overlay_signed_contract(private: dict[str, Any], signed: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `signed` on top of `private`. At every path present
    in both, `signed`'s value wins outright (dicts recurse; anything else —
    scalars, lists — is replaced, not merged). Keys only in `private` are
    kept; keys only in `signed` are added. This is the one place the
    mandatory overlay rule is enforced, so it applies uniformly no matter
    what either file happens to contain, now or after future negotiation.
    """
    merged = dict(private)
    for key, signed_value in signed.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(signed_value, dict):
            merged[key] = overlay_signed_contract(merged[key], signed_value)
        else:
            merged[key] = signed_value
    return merged


def _require(d: dict[str, Any], path: str) -> Any:
    """Fetch a dotted path (e.g. 'network.my_port'), failing loudly if any
    segment is missing."""
    node: Any = d
    walked: list[str] = []
    for segment in path.split("."):
        walked.append(segment)
        if not isinstance(node, dict) or segment not in node:
            raise PeerConfigError(f"config/<role>/game.toml: missing required field '{'.'.join(walked)}'")
        node = node[segment]
    return node


def _require_str(d: dict[str, Any], path: str) -> str:
    value = _require(d, path)
    if not isinstance(value, str) or not value:
        raise PeerConfigError(f"config/<role>/game.toml: '{path}' must be a non-empty string, got {value!r}")
    return value


def _require_positive_int(d: dict[str, Any], path: str) -> int:
    value = _require(d, path)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PeerConfigError(f"config/<role>/game.toml: '{path}' must be a positive integer, got {value!r}")
    return value


def _require_positive_number(d: dict[str, Any], path: str) -> float:
    value = _require(d, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise PeerConfigError(f"config/<role>/game.toml: '{path}' must be a positive number, got {value!r}")
    return value


def parse_peer_config(role: str, private: dict[str, Any], signed: dict[str, Any]) -> PeerConfig:
    """Build a validated PeerConfig from already-parsed TOML/JSON dicts, with
    the signed contract's overlay rule applied first."""
    effective = overlay_signed_contract(private, signed)

    return PeerConfig(
        role=role,
        group_id=_require_str(effective, "game.group_id"),
        group_name=_require_str(effective, "game.group_name"),
        my_port=_require_positive_int(effective, "network.my_port"),
        opponent_url=_require_str(effective, "network.opponent_url"),
        turn_timeout_seconds=_require_positive_number(effective, "network.turn_timeout_seconds"),
    )


def load_peer_config(role: str, toml_path: str | Path, json_path: str | Path) -> PeerConfig:
    """Load config/<role>/game.toml and config/game.json from disk and
    return the validated, overlaid PeerConfig."""
    private = _load_toml(toml_path)
    signed = _load_json(json_path)
    return parse_peer_config(role, private, signed)
