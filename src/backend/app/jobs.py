"""Committed, owner-checked leases serialize CPU-heavy operational jobs per DB."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import update, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from app.models import OptimisationJobLease as Lease
from app.errors import DomainError

class JobLock:
    def __init__(self, engine, seconds=900):
        self.engine, self.seconds = engine, seconds
        # The row is local to the database, so DSN aliases and credentials must
        # not create separate locks for the same operational state.
        self.id = 'port-operations'
        self.owner = uuid4().hex

    def acquire(self):
        now = datetime.now(timezone.utc)
        insert = sqlite_insert if self.engine.dialect.name == 'sqlite' else postgres_insert
        with self.engine.begin() as db:
            db.execute(insert(Lease).values(id=self.id, owner=self.owner, expires_at=now+timedelta(seconds=self.seconds)).on_conflict_do_nothing(index_elements=['id']))
            claimed = db.execute(update(Lease).where(Lease.id == self.id,
                (Lease.owner == self.owner) | (Lease.expires_at <= now)).values(owner=self.owner, expires_at=now+timedelta(seconds=self.seconds))).rowcount
        if claimed != 1:
            raise DomainError('OPTIMISATION_BUSY', 'An operational job is already running for this database; retry shortly', 409)
        return self

    def release(self):
        with self.engine.begin() as db:
            db.execute(delete(Lease).where(Lease.id == self.id, Lease.owner == self.owner))

    def renew(self):
        with self.engine.begin() as db:
            return db.execute(update(Lease).where(Lease.id == self.id, Lease.owner == self.owner).values(
                expires_at=datetime.now(timezone.utc)+timedelta(seconds=self.seconds))).rowcount == 1
