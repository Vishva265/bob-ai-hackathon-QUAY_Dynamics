import argparse
from pathlib import Path

from _bootstrap import PROJECT_ROOT, prepare_environment

prepare_environment()

from app.historical_replay.prepare import prepare, derive


def main():
    parser = argparse.ArgumentParser(description="Filter and derive LA/LB operations from supplied NOAA AIS archives.")
    parser.add_argument("--raw", type=Path, default=PROJECT_ROOT / "data/real/raw/noaa_ais")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/real/processed/la_lb_2021")
    parser.add_argument('--staging', type=Path, help='Reuse an existing filtered AIS SQLite file instead of rereading raw ZIPs.')
    args = parser.parse_args(); print(derive(args.staging,args.output) if args.staging else prepare(args.raw, args.output))


if __name__ == "__main__": main()
