import argparse
from pathlib import Path

from _bootstrap import PROJECT_ROOT, prepare_environment

prepare_environment()

from app.historical_replay.replay import run_replay


def main():
    parser = argparse.ArgumentParser(description="Create the cutoff database and run the existing 72-hour optimizer.")
    parser.add_argument("--processed", type=Path, default=PROJECT_ROOT / "data/real/processed/la_lb_2021")
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "artifacts/historical-replay/operations.db")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "artifacts/historical-replay")
    parser.add_argument("--time-limit", type=float, default=10)
    args = parser.parse_args(); result = run_replay(args.processed, args.database, args.output, args.time_limit)
    print(f'Replay {result["status"]}: {len(result["assignments"])} assignments, {len(result["shifts"])} shifts')


if __name__ == "__main__": main()
