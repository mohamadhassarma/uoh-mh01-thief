"""`run_series`: the real stage-3 entry point. Plays a full `num_games`-
sub-game series against one opponent — a handshake PER SUB-GAME (see
infra/series_handshake.py for why that moved), role alternation, real
commit-reveal, a mutual audit, and the three per-series/per-sub-game JSON
artifacts (PRD-03).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from ..domain.state import Side, other_side
from ..shared.peer_config import PeerConfig
from .artifacts import build_declaration, write_json
from .mcp_pool import close_all
from .mcp_server import build_server
from .series_handshake import SeriesIdentity, negotiate_sub_game
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
    Raises `infra.negotiation.NegotiationRefusedError` if the FIRST handshake
    fails — the series never starts playing on a terms mismatch — or if a
    later re-negotiation contradicts the series it is re-affirming.

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
    server = build_server(series_runtime.inboxes, name=f"uoh-mh01-{role.value}")
    server_task = asyncio.create_task(
        server.run_http_async(
            transport="http", host="127.0.0.1", port=peer_config.my_port, show_banner=False, log_level="warning"
        )
    )

    started_at = _now_iso()
    series: SeriesIdentity | None = None
    try:
        summaries = []
        for sub_game_number in range(1, config.network.num_games + 1):
            sub_game_role = natural_role if sub_game_number % 2 == 1 else other_side(natural_role)
            # Greet for THIS sub-game, declaring the pinned uid from sub-game 2
            # onward. Series identity is fixed by the first agreement and is
            # only ever re-affirmed here, never re-derived.
            series, my_msg, theirs = await negotiate_sub_game(
                series_runtime, sub_game_number, sub_game_role, config, peer_config, series=series
            )
            if sub_game_number == 1:
                # ONCE, PRE-SERIES, from the first negotiation. Written before
                # a single move is played so that a series which breaks at
                # sub-game 2 still leaves a declaration behind — which is
                # exactly what did NOT happen when the handshake lived outside
                # the loop and this write lived after it.
                _write_declaration(out_dir, series, config, started_at, ended_at="")
            summaries.append(
                await play_one_sub_game(
                    series_runtime,
                    sub_game_number,
                    sub_game_role,
                    config,
                    peer_config,
                    strategy,
                    seed,
                    series,
                    my_msg,
                    theirs,
                    out_dir,
                )
            )

        # Not a second declaration: the same file, re-stamped with the end time
        # now that one is known. Every other field is byte-identical.
        _write_declaration(out_dir, series, config, started_at, ended_at=_now_iso())
        return summaries
    finally:
        # The pooled outbound connections are held for the whole series
        # (infra/mcp_pool.py); this is the one place that closes them.
        await close_all()
        deadline = asyncio.get_event_loop().time() + 2.0
        while server_task and not server_task.done() and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.02)
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, Exception):
            logger.debug("server task raised during shutdown", exc_info=True)


def _write_declaration(out_dir: Path, series: SeriesIdentity, config, started_at: str, *, ended_at: str) -> None:
    """Always from `series.my_first_msg`/`their_first_msg` — the FIRST
    agreement — never from whichever sub-game happens to be current. The
    per-sub-game greetings differ in `role`, `nonce` and `sub_game_number`,
    none of which belongs in a series-level declaration."""
    write_json(
        out_dir / f"declaration_{series.game_id}.json",
        build_declaration(
            game_id=series.game_id,
            game_uid=series.game_uid,
            num_sub_games=config.network.num_games,
            groups={"mine": series.my_first_msg.identity, "opponent": series.their_first_msg.identity},
            started_at=started_at,
            ended_at=ended_at,
        ),
    )


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
