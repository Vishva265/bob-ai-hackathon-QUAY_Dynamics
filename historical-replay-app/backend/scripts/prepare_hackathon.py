"""Verify and materialise an isolated local demo; reset archives its previous state."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]


def verify_seed(seed):
    files = json.loads((seed/'checksums.json').read_text(encoding='utf-8'))
    for filename, expected in files.items():
        path = (seed/filename).resolve()
        if not path.is_relative_to(seed.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Demo seed checksum failed: '+filename)
    return json.loads((seed/'metadata.json').read_text(encoding='utf-8'))


def prepare(home, reset=False):
    home = Path(home).resolve()
    intended = (ROOT/'artifacts').resolve()
    if not home.is_relative_to(intended) or home == intended:
        raise ValueError('DEMO_HOME must be a dedicated directory inside this workspace artifacts directory')
    # Verify before changing existing demo state.
    metadata = verify_seed(ROOT/'demo/seed')
    home.mkdir(parents=True,exist_ok=True)
    if (home/'running.json').exists():
        raise ValueError('Stop the demo launcher before preparing/resetting this demo directory')
    marker = home/'demo-state.json'
    existing_state = None
    if marker.exists():
        old = json.loads(marker.read_text())
        if old.get('schema_version') != 'quay-local-demo-v1':
            raise ValueError('Refusing to replace an unrelated directory')
        if old.get('seed',{}).get('database_sha256') != metadata['database_sha256'] and not reset:
            raise ValueError('The portable demo seed changed; run npm run demo:reset before starting')
        existing_state = old
    elif any(home.iterdir()):
        raise ValueError('Refusing to seed a nonempty directory without a demo marker')
    database = home/'operations.db'
    if reset and database.exists():
        archive = (home/'archives'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')).resolve()
        names = ['operations.db','operations.db-wal','operations.db-shm','live-demo','demo-state.json']
        if not archive.is_relative_to(home):
            raise ValueError('Reset archive must stay inside this demo directory')
        for name in names:
            source=home/name
            if source.exists() and not source.resolve().is_relative_to(home):
                raise ValueError('Reset source must stay inside this demo directory')
        archive.mkdir(parents=True)
        # The Node launcher checks both listener ports before allowing reset.
        for name in names:
            source = home/name
            if source.exists():shutil.move(str(source),str(archive/name))
    if not database.exists():
        staged = home/'operations.db.new'
        with gzip.open(ROOT/'demo/seed/operations.sqlite.gz','rb') as source, staged.open('wb') as target:
            shutil.copyfileobj(source,target)
        if hashlib.sha256(staged.read_bytes()).hexdigest() != metadata['database_sha256']:
            raise ValueError('Decompressed demo database checksum failed')
        with closing(sqlite3.connect(staged)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Seeded demo database failed integrity/reference validation')
        staged.replace(database)
    # A prepared, matching demo needs no marker rewrite. Rewriting it causes an
    # unnecessary Windows sharing violation if Explorer, an editor, or a prior
    # launcher still has the state file open; the marker itself is immutable
    # metadata for this seed and database.
    if existing_state is not None and not reset:
        return existing_state
    # Marker is retained so subsequent reset is scoped to this dedicated state.
    state = dict(schema_version='quay-local-demo-v1',database=str(database),seed=metadata,
        prepared_at=datetime.now(timezone.utc).isoformat(),isolated=True)
    marker.write_text(json.dumps(state,indent=2)+'\n')
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',type=Path,default=ROOT/'artifacts/hackathon-demo')
    parser.add_argument('--reset',action='store_true')
    args=parser.parse_args()
    print(json.dumps(prepare(args.home,args.reset),indent=2))


if __name__ == '__main__':main()
