"""PRD-05's mandatory evaluation harness: play N sub-games between any two
named brains at the real signed contract values, across a deterministic
seed list, headless (no network, no crypto — domain.eval_match), and
report win rate, survival/capture turns, barrier utilisation, and the
argmax-accuracy metrics PRD-05's own baseline was measured with.

Every strategy claim in the PRD-05 report is a number this script produced,
not an intuition — see PRD-05 "Harness results".
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from uoh_mh01.domain.brain_base import load_brain_class
from uoh_mh01.domain.config import parse_config
from uoh_mh01.domain.eval_match import EvalResult, play_one_game
from uoh_mh01.domain.strategies import make_random_strategy

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_strategy(spec: str, rng: random.Random):
    if spec == "random":
        return make_random_strategy(rng)
    return load_brain_class(spec)(rng)


def run(config, police_spec: str, thief_spec: str, seeds: list[int]) -> list[EvalResult]:
    """Deterministic given `seeds`: each seed derives its own police/thief
    RNGs, fresh brain instances every game, no shared mutable state between
    games."""
    results = []
    for seed in seeds:
        police_strategy = _build_strategy(police_spec, random.Random(f"{seed}-police"))
        thief_strategy = _build_strategy(thief_spec, random.Random(f"{seed}-thief"))
        results.append(play_one_game(config, police_strategy, thief_strategy))
    return results


def summarize(results: list[EvalResult]) -> dict:
    n = len(results)
    police_wins = sum(r.winner == "police" for r in results)
    thief_wins = sum(r.winner == "thief" for r in results)
    other = n - police_wins - thief_wins
    capture_turns = [r.turns for r in results if r.winner == "police"]
    survival_turns = [r.turns for r in results if r.winner == "thief"]
    barriers = [r.barriers_used for r in results]
    all_distances = [d for r in results for d in r.police_argmax_distances]
    within_1 = sum(d <= 1 for d in all_distances)
    within_2 = sum(d <= 2 for d in all_distances)
    total_samples = len(all_distances)

    return {
        "games": n,
        "police_win_rate": police_wins / n,
        "thief_win_rate": thief_wins / n,
        "other_rate": other / n,
        "mean_turns_to_capture": statistics.mean(capture_turns) if capture_turns else None,
        "mean_survival_turns": statistics.mean(survival_turns) if survival_turns else None,
        "mean_barriers_used": statistics.mean(barriers),
        "argmax_within_1_pct": 100 * within_1 / total_samples if total_samples else None,
        "argmax_within_2_pct": 100 * within_2 / total_samples if total_samples else None,
        "argmax_samples": total_samples,
    }


def _print_summary(label: str, summary: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"games={summary['games']}  police_win_rate={summary['police_win_rate']:.3f}  "
          f"thief_win_rate={summary['thief_win_rate']:.3f}  other_rate={summary['other_rate']:.3f}")
    print(f"mean_turns_to_capture={summary['mean_turns_to_capture']}  "
          f"mean_survival_turns={summary['mean_survival_turns']}")
    print(f"mean_barriers_used={summary['mean_barriers_used']:.2f} / 14")
    print(f"argmax_within_1={summary['argmax_within_1_pct']:.1f}%  "
          f"argmax_within_2={summary['argmax_within_2_pct']:.1f}%  (n={summary['argmax_samples']} samples)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_ROOT / "config" / "game.json"))
    parser.add_argument("--police-brain", default="random", help="'random' or 'package.module:ClassName'")
    parser.add_argument("--thief-brain", default="random")
    parser.add_argument("--num-games", type=int, default=30)
    parser.add_argument("--seed-start", type=int, default=1)
    args = parser.parse_args()

    raw = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config = parse_config(raw)
    seeds = list(range(args.seed_start, args.seed_start + args.num_games))

    results = run(config, args.police_brain, args.thief_brain, seeds)
    label = f"police={args.police_brain} vs thief={args.thief_brain} (seeds {seeds[0]}..{seeds[-1]})"
    _print_summary(label, summarize(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
