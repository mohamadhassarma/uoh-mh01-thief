"""ConfigError lives in its own module purely to avoid an import cycle
between config.py and config_validators.py."""

from __future__ import annotations


class ConfigError(Exception):
    """Raised when config/game.json is missing, malformed, or fails validation."""
