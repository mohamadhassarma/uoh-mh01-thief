"""Test-only runner, NOT part of the shipped CLI: plays a series exactly
like `python -m uoh_mh01 peer`, except one role's strategy blocks for
`--stall-seconds` on its `--stall-turn`'th own action.

Used by test_symmetric_timeouts.py to deliberately reproduce, under the
REAL signed contract values (no artificially shrunk timeouts), a peer that
is genuinely too slow to respond within watchdog_timeout_sec — PRD-03
"Symmetric timeout outcomes". `time.sleep` (not `asyncio.sleep`) is
deliberate: it blocks this peer's WHOLE event loop, including its own
FastMCP server, faithfully simulating a CPU-starved process rather than
just a slow callback.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uoh_mh01.domain.config import load_config  # noqa: E402
from uoh_mh01.domain.state import Side  # noqa: E402
from uoh_mh01.domain.strategies import make_random_strategy  # noqa: E402
from uoh_mh01.infra.series import run_series  # noqa: E402
from uoh_mh01.shared.peer_config import load_peer_config  # noqa: E402


def _stalling(base_strategy, stall_turn: int, stall_seconds: float):
    def strategy(state, role):
        # `state` is an OwnGameState now, which has no `whose_turn`: a strategy
        # is only ever called when it IS my turn, so the check is redundant.
        # `step_number` counts MY OWN actions taken so far, so I am about to
        # take my `stall_turn`'th one when it equals stall_turn - 1.
        if state.step_number == stall_turn - 1:
            time.sleep(stall_seconds)
        return base_strategy(state, role)

    return strategy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--peer-config", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--stall-turn", type=int, default=0)
    parser.add_argument("--stall-seconds", type=float, default=0.0)
    args = parser.parse_args()

    role = Side(args.role)
    config = load_config(args.config)
    peer_config = load_peer_config(role.value, args.peer_config, args.config)
    strategy = make_random_strategy(random.Random(args.seed))
    if args.stall_turn > 0 and args.stall_seconds > 0:
        strategy = _stalling(strategy, args.stall_turn, args.stall_seconds)

    summaries = asyncio.run(run_series(role, config, peer_config, strategy=strategy, out_dir=args.log_dir))
    for summary in summaries:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
