"""Migrate and seed a dedicated operational DB from a simulator scenario directory."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.services.seed import seed_tables
from app.synthetic.files import read_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--database-url', default=None)
    args = parser.parse_args()
    tables, manifest, _ = read_dataset(args.dataset)
    engine = make_engine(args.database_url or get_settings().database_url)
    try:
        migrate(engine)
        with session_factory(engine).begin() as session:
            result = seed_tables(session, tables, manifest)
        print(json.dumps(result, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
