"""Series artifacts on disk -> `result_<game_id>.json` -> (optionally) the
lecturer's inbox. The one place the four PRD-07 pieces are wired together.

The build and the send are separate functions on purpose. Building is safe,
repeatable and touches no credential; sending is neither. A single
`report(send=True)` that did both would make the dangerous half reachable by
a default argument.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..domain.config import GameConfig
from ..infra.gatekeeper_runner import Gatekeeper
from ..infra.gmail_sender import (
    UNREACHABLE_ADDRESS,
    NotACountedRunError,
    build_message,
    resolve_recipient,
    send,
)
from . import ledger
from .result_artifact import build_result
from .series_reader import UNCLAIMED, load_series, sub_game_rows

logger = logging.getLogger(__name__)

# The hint provider is `template` (PRD-05): the move is always pure Python and
# the trash talk is generated offline, so this series genuinely consumed zero
# LLM tokens. Reported as 0 because it IS 0, not as a placeholder for unknown —
# an unknown count is UNCLAIMED (None), and the two must not be confused.
OWN_TOKENS_TOTAL = 0


def build(
    logs_dir: Path, game_id: str, config: GameConfig, *, ledger_path: Path = ledger.LEDGER_PATH
) -> dict[str, Any]:
    """Aggregate a played series into the result artifact (nothing written)."""
    declaration, logs = load_series(logs_dir, game_id)
    own_gid = declaration["groups"]["mine"]["group_id"]
    opponent_gid = declaration["groups"]["opponent"]["group_id"]
    rows = sub_game_rows(declaration, logs, config, own_tokens=OWN_TOKENS_TOTAL)
    return build_result(
        declaration,
        rows,
        config,
        first_meeting=ledger.is_first_meeting(opponent_gid, path=ledger_path),
        games_played_including_this={
            own_gid: ledger.counted_games_played(path=ledger_path) + 1,
            # Their standing is their own claim about themselves. A live rival
            # stamped with 0 is a fabricated declaration, not a default.
            opponent_gid: declaration["groups"]["opponent"].get("counted_games_played", UNCLAIMED),
        },
    )


def write(result: dict[str, Any], logs_dir: Path) -> Path:
    """Write the artifact and return its path. These exact bytes are what gets
    attached to the email — the attachment is never re-serialized."""
    path = logs_dir / f"result_{result['game_id']}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def send_report(
    result_path: Path,
    result: dict[str, Any],
    config: GameConfig,
    *,
    counted: bool,
    sender: str,
    to: str | None = None,
    service=None,
) -> dict[str, Any]:
    """Mail the artifact.

    `resolve_recipient` is the single gate and it runs FIRST, before any
    credential is touched: it refuses a counted report aimed away from the
    lecturer, and a practice report aimed at them. A practice run with no
    explicit `--to` has nowhere to go at all.
    """
    recipient = resolve_recipient(counted=counted, override=to)
    if recipient == UNREACHABLE_ADDRESS:
        raise NotACountedRunError(
            "this is not a counted series: warm-ups owe no report to anyone (App. E rule 52 / book ch.9.2.1), "
            f"so the recipient resolves to {UNREACHABLE_ADDRESS!r}, which is not a deliverable address at all. "
            "Pass --to <your own address> to exercise the real send path."
        )
    if service is None:
        from ..infra.gmail_auth import gmail_service

        service = gmail_service()
    message = build_message(result_path, recipient=recipient, sender=sender, game_id=result["game_id"])
    gatekeeper = Gatekeeper(config.gatekeeper, service="gmail")
    sent = gatekeeper.execute(send, service, message)
    logger.info("sent %s to %s (message id %s)", result_path.name, recipient, sent.get("id"))
    return sent
