#!/usr/bin/env python3
"""Print the slowest cumulative functions from the indoor coarse profile."""

import argparse
import pstats
from pathlib import Path


DEFAULT_PROFILE = Path("/tmp/indoors_coarse.prof")
DEFAULT_LIMIT = 80


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print cumulative-time cProfile stats for indoor coarse generation."
    )
    parser.add_argument(
        "profile",
        nargs="?",
        default=DEFAULT_PROFILE,
        type=Path,
        help=f"Path to a cProfile .prof file. Default: {DEFAULT_PROFILE}",
    )
    parser.add_argument(
        "-n",
        "--limit",
        default=DEFAULT_LIMIT,
        type=int,
        help=f"Number of functions to print. Default: {DEFAULT_LIMIT}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.profile.exists():
        raise SystemExit(f"Profile file does not exist: {args.profile}")

    stats = pstats.Stats(str(args.profile))
    stats.strip_dirs().sort_stats("cumulative").print_stats(args.limit)


if __name__ == "__main__":
    main()
