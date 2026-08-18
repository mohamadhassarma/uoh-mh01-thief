"""Isolated to avoid an import cycle between peer_config.py and
peer_config_validators.py.
"""

from __future__ import annotations


class PeerConfigError(Exception):
    """Raised when config/<role>/game.toml is missing, malformed, or fails validation."""
