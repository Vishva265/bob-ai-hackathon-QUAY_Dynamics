"""Demo reset isolation and UTC transactions must not corrupt real work."""
import gzip
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing

import pytest
from scripts import prepare_hackathon as demo
from app.synthetic.simulator import parse


@pytest.fixture
def seed(tmp_path,monkeypatch):
    root=tmp_path/'project';target=root/'demo/seed';target.mkdir(parents=True)
    database=tmp_path/'seed.sqlite'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE demo_value(value INTEGER NOT NULL)')
        db.execute('INSERT INTO demo_value VALUES (42)')
    (target/'operations.sqlite.gz').write_bytes(gzip.compress(database.read_bytes(),mtime=0))
    metadata={'database_sha256':hashlib.sha256(database.read_bytes()).hexdigest(),'synthetic':True}
    (target/'metadata.json').write_text(json.dumps(metadata))
    (target/'checksums.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()}))
    monkeypatch.setattr(demo,'ROOT',root)
    return root


def test_reset_archives_only_own_demo_and_restores_seed(seed):
    home=seed/'artifacts/presentation'
    other=seed/'artifacts/operations.db';other.parent.mkdir();other.write_bytes(b'original user data')
    demo.prepare(home)
    with closing(sqlite3.connect(home/'operations.db')) as db:
        db.execute('UPDATE demo_value SET value=7');db.commit()
    branches=home/'live-demo';branches.mkdir();(branches/'session.db').write_bytes(b'private approved plan')
    demo.prepare(home,reset=True)
    with closing(sqlite3.connect(home/'operations.db')) as db:assert db.execute('SELECT value FROM demo_value').fetchone()==(42,)
    archives=list((home/'archives').iterdir());assert len(archives)==1
    with closing(sqlite3.connect(archives[0]/'operations.db')) as db:assert db.execute('SELECT value FROM demo_value').fetchone()==(7,)
    assert (archives[0]/'live-demo/session.db').read_bytes()==b'private approved plan'
    assert other.read_bytes()==b'original user data'


@pytest.mark.parametrize('relative',['..','artifacts','backend/unrelated'])
def test_reset_rejects_outside_or_shared_directory(seed,relative):
    with pytest.raises(ValueError,match='dedicated'):demo.prepare(seed/relative,reset=True)


def test_reset_refuses_unmarked_or_running_directory(seed):
    home=seed/'artifacts/demo';home.mkdir(parents=True);(home/'unrelated.txt').write_text('preserve')
    with pytest.raises(ValueError,match='nonempty'):demo.prepare(home,reset=True)
    assert (home/'unrelated.txt').read_text()=='preserve'
    (home/'running.json').write_text('{}')
    with pytest.raises(ValueError,match='Stop'):demo.prepare(home,reset=True)


def test_corrupt_bundle_fails_before_existing_demo_is_archived(seed):
    home=seed/'artifacts/demo';demo.prepare(home)
    before=(home/'operations.db').read_bytes()
    (seed/'demo/seed/operations.sqlite.gz').write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='checksum'):demo.prepare(home,reset=True)
    assert (home/'operations.db').read_bytes()==before
    assert not (home/'archives').exists()


def test_utc_parse_accepts_in_memory_orm_instants_and_rejects_naive():
    instant=datetime(2026,9,13,tzinfo=timezone.utc)
    assert parse(instant)==parse('2026-09-13T00:00:00Z')
    with pytest.raises(ValueError,match='UTC'):parse(datetime(2026,9,13))


def test_checksum_manifest_cannot_escape_seed(seed):
    target=seed/'demo/seed';(target/'checksums.json').write_text(json.dumps({'../../outside':'0'*64}))
    with pytest.raises(ValueError,match='checksum'):demo.verify_seed(target)
