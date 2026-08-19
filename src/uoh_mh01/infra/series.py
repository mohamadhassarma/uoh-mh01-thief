"""`run_series`: the real stage-3 entry point. Plays a full `num_games`-
sub-game series against one opponent — handshake once, then each sub-game
with role alternation, real commit-reveal, a mutual audit, and the three
per-series/per-sub-game JSON artifacts (PRD-03).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from ..domain.state import Side
from ..shared.peer_config import PeerConfig
from .artifacts import build_declaration, write_json
from .mcp_client import send_negotiate
from .mcp_server import build_server
from .negotiation import build_negotiate_message, game_ids, verify_peer_message
from .series_runtime import SeriesRuntime
from .series_subgame import play_one_sub_game

logger = logging.getLogger(__name__)


async def run_series(
    role: Side,
    config,
    peer_config: PeerConfig,
    *,
    strategy=None,
    seed: int | str | None = None,
    out_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Returns one summary dict per sub-game played:
    `{"sub_game_number", "role", "terminal_condition", "police_score",
    "thief_score", "offending_side", "undefined_outcome", "disputed"}`.
    Raises `infra.negotiation.NegotiationRefusedError` if the handshake itself
    fails — the series never starts playing on a terms mismatch.

    `strategy`, if given, is used AS-IS for every sub-game regardless of role
    alternation (only test callers that need one fixed, role-agnostic
    strategy — e.g. the stalling-peer test runner — should pass this).
    Otherwise (the real `peer` CLI path) `seed` plus `peer_config`'s
    `[strategy] police_class`/`thief_class` are used to resolve a FRESH,
    role-correct brain for each sub-game (PRD-05) — required because role
    alternation means this process plays police in some sub-games and thief
    in others, and a role-specific brain must only ever run for its own
    role."""
    out_dir = Path(out_dir or "logs")
    natural_role = role
    series_runtime = SeriesRuntime()
    server = build_server(series_runtime, name=f"uoh-mh01-{role.value}")
    server_task = asyncio.create_task(
        server.run_http_async(transport="http", host="127.0.0.1", port=peer_config.my_port, show_banner=False, log_level="warning")
    )

    started_at = _now_iso()
    try:
        my_msg = build_negotiate_message(natural_role, config, peer_config, sub_game_number=1)
        series_runtime.set_negotiate_message(my_msg)
        theirs = await send_negotiate(
            peer_config.opponent_url,
            my_msg,
            response_timeout_sec=config.network.response_timeout_sec,
            watchdog_timeout_sec=config.network.watchdog_timeout_sec,
        )
        verify_peer_message(my_msg, theirs)
        game_id, game_uid = game_ids(my_msg, theirs)
        logger.info("handshake agreed: game_id=%s game_uid=%s", game_id, game_uid)

        summaries = []
        for sub_game_number in range(1, config.network.num_games + 1):
            summaries.append(
                await play_one_sub_game(
                    series_runtime,
                    sub_game_number,
                    natural_role,
                    config,
                    peer_config,
                    strategy,
                    seed,
                    game_id,
                    game_uid,
                    my_msg,
                    theirs,
                    out_dir,
                )
            )

        write_json(
            out_dir / f"declaration_{game_id}.json",
            build_declaration(
                game_id=game_id,
                game_uid=game_uid,
                num_sub_games=config.network.num_games,
                groups={"mine": my_msg.identity, "opponent": theirs.identity},
                started_at=started_at,
                ended_at=_now_iso(),
            ),
        )
        return summaries
    finally:
        deadline = asyncio.get_event_loop().time() + 2.0
        while server_task and not server_task.done() and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.02)
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, Exception):
            logger.debug("server task raised during shutdown", exc_info=True)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
