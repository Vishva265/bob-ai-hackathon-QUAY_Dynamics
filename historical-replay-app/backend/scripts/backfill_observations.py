"""Safely add observed events to a previously seeded application database."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import models as m
from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.services.observations import seed_observations
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
            provenance = session.get(m.SeedProvenance, 1)
            digest = hashlib.sha256(json.dumps(manifest.get('files', manifest), sort_keys=True).encode()).hexdigest()
            if not provenance or provenance.input_hash != digest:
                raise ValueError('Backfill requires the exact source manifest of this seeded DB')
            result = seed_observations(session, tables, manifest['epoch'])
        print(json.dumps(result, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
