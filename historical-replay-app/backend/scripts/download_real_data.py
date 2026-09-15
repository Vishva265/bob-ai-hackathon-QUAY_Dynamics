import argparse
import json
from pathlib import Path

from _bootstrap import PROJECT_ROOT, prepare_environment

prepare_environment()

from app.historical_replay.download import daily_urls, download


def main():
    parser = argparse.ArgumentParser(description="Download official NOAA Marine Cadastre daily AIS archives.")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/real/raw/noaa_ais")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 7))
    parser.add_argument("--list", action="store_true", help="Print exact source URLs without downloading.")
    args = parser.parse_args()
    if args.list:
        for _, _, url in daily_urls(): print(url)
        return
    result = download(args.output, args.overwrite, workers=args.workers)
    (args.output / "download_manifest.json").write_text(json.dumps({"source": "NOAA Marine Cadastre",
        "files": result}, indent=2) + "\n", encoding="utf-8")
    print(f"Ready: {len(result)} daily archives in {args.output.resolve()}")


if __name__ == "__main__": main()
