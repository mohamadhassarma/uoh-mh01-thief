"""Dotted-path validators for peer_config.py, split out purely to keep that
file under the project's ~150-line budget.
"""

from __future__ import annotations

from typing import Any

from .peer_config_errors import PeerConfigError


def require(d: dict[str, Any], path: str) -> Any:
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


def require_str(d: dict[str, Any], path: str) -> str:
    value = require(d, path)
    if not isinstance(value, str) or not value:
        raise PeerConfigError(f"config/<role>/game.toml: '{path}' must be a non-empty string, got {value!r}")
    return value


def require_positive_int(d: dict[str, Any], path: str) -> int:
    value = require(d, path)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PeerConfigError(f"config/<role>/game.toml: '{path}' must be a positive integer, got {value!r}")
    return value


def require_positive_number(d: dict[str, Any], path: str) -> float:
    value = require(d, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise PeerConfigError(f"config/<role>/game.toml: '{path}' must be a positive number, got {value!r}")
    return value


def optional_str(d: dict[str, Any], path: str) -> str | None:
    node: Any = d
    for segment in path.split("."):
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    if not isinstance(node, str) or not node:
        raise PeerConfigError(f"config/<role>/game.toml: '{path}' must be a non-empty string, got {node!r}")
    return node


def optional_str_list(d: dict[str, Any], path: str) -> tuple[str, ...]:
    node: Any = d
    for segment in path.split("."):
        if not isinstance(node, dict) or segment not in node:
            return ()
        node = node[segment]
    if not isinstance(node, list) or not all(isinstance(v, str) for v in node):
        raise PeerConfigError(f"config/<role>/game.toml: '{path}' must be a list of strings, got {node!r}")
    return tuple(node)


def optional_str_dict(d: dict[str, Any], path: str) -> dict[str, str]:
    node: Any = d
    for segment in path.split("."):
        if not isinstance(node, dict) or segment not in node:
            return {}
        node = node[segment]
    if not isinstance(node, dict) or not all(isinstance(v, str) for v in node.values()):
        raise PeerConfigError(f"config/<role>/game.toml: '{path}' must be an object of strings, got {node!r}")
    return dict(node)
