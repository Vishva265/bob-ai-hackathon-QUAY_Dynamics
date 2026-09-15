import argparse
import json
from pathlib import Path

from _bootstrap import PROJECT_ROOT, prepare_environment

prepare_environment()

from app.historical_replay.replay import evaluate


def main():
    parser = argparse.ArgumentParser(description="Compare the cutoff plan with post-cutoff AIS-derived truth.")
    parser.add_argument("--processed", type=Path, default=PROJECT_ROOT / "data/real/processed/la_lb_2021")
    parser.add_argument("--artifacts", type=Path, default=PROJECT_ROOT / "artifacts/historical-replay")
    args = parser.parse_args(); print(json.dumps(evaluate(args.processed, args.artifacts), indent=2))


if __name__ == "__main__": main()
