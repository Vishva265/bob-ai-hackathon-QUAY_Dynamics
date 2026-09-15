# Trusted portable synthetic seed

`operations.sqlite.gz` is a gzip-compressed, related SQLAlchemy/Alembic SQLite
snapshot copied from the audited seed-42 Normal Operations simulator database.
It contains four ports, 60 historical days and a separate seven-day published
schedule. Future actual outcomes/weather are excluded by the original importer.
Packaging adds a complete, independently validated and approved P01 normal plan,
a named P02 storm/crane what-if, forecasts and two conditional routing decisions.
The preset is hypothetical; live incidents are injected separately at P01.

The original normal and storm databases were preserved. `metadata.json` retains
source hash, UTC epoch, model version and run IDs. `checksums.json` verifies the
compressed snapshot and complete frozen model bundle before materialisation;
the decompressed database hash, integrity and foreign keys are checked too.

The models were produced by the project's trusted local training pipeline and
are LOW confidence. Metadata and chronological test outputs are shipped intact.
Only load this repository-owned bundle, using the pinned dependency versions.
No AIS, real vessel identity, customer contracts, private access key or validated
operational savings is contained in this seed.

Startup needs this tracked directory, not ignored `artifacts/`. The launcher
materialises it under `artifacts/hackathon-demo/`. Reset archives only that local
state; replay has fixed underlying data, while newly executed runs have new IDs.
Maintainer packaging command: `backend/scripts/package_hackathon.py` after the
audited normal dataset/model are available. Packaging is an offline preparation
step and is unnecessary on a clean demo installation.
