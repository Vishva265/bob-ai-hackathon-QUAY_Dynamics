"""Canonical CSV export/import, field dictionary, lineage and SHA-256 checksums."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from .schema import SCHEMA
from .simulator import parse
from .validation import DataValidationError, validate


def csv_bytes(table, rows):
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=list(SCHEMA[table]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode('utf-8')


def data_dictionary():
    lines = ['# Synthetic operations data dictionary', '',
        'Generated from `backend/app/synthetic/schema.py`; CSV UTF-8, empty = SQL NULL.',
        'All instants are UTC, all operational intervals are half-open. IDs are stable',
        'strings, NOT IMO numbers. All data is synthetic. Floats retain full precision.', '',
        'Canonical tables live at dataset root. `historical/` contains pre-cutoff',
        'schedule/observations and completed outcomes. `upcoming/vessel_calls.csv`',
        'is the separate 7-day published schedule with no actual outcomes.',
        '`simulated_future/` contains future truth, including carry-over historical',
        'calls completed after the epoch; exclude these labels from training.', '',
        'Each scenario is a separate database/dataset. Joining across scenarios',
        'requires the scenario directory/manifest key, since common IDs are reused.', '']
    for table, fields in SCHEMA.items():
        lines += [f'## {table}.csv', '', '| Field | Type | Unit | Meaning / relationship |',
                  '| --- | --- | --- | --- |']
        for key, field in fields.items():
            meaning = field.description
            if field.reference:
                meaning += f' FK -> {field.reference}.id.'
            if field.nullable:
                meaning += ' Nullable.'
            lines.append(f'| {key} | {field.kind} | {field.unit} | {meaning} |')
        lines.append('')
    return '\n'.join(lines)


def export_dataset(directory, tables, manifest):
    report = validate(tables, manifest)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        marker = directory/'manifest.json'
        if not marker.exists():
            raise ValueError('Refusing to overwrite a directory without a demo manifest')
        old = json.loads(marker.read_text(encoding='utf-8'))
        if not old.get('synthetic') or old.get('scenario') != manifest['scenario']:
            raise ValueError('Refusing to overwrite an unrelated dataset')
    artifacts = {f'{name}.csv': (name, rows) for name, rows in tables.items()}
    artifacts.update({
        'historical/vessel_calls.csv': ('vessel_calls', [r for r in tables['vessel_calls'] if r['period'] == 'historical']),
        'upcoming/vessel_calls.csv': ('vessel_calls', [r for r in tables['vessel_calls'] if r['period'] == 'upcoming']),
        'historical/call_outcomes.csv': ('call_outcomes', [r for r in tables['call_outcomes'] if r['period'] == 'historical']),
        'simulated_future/call_outcomes.csv': ('call_outcomes', [r for r in tables['call_outcomes'] if r['period'] == 'simulated_future_truth']),
        'historical/weather.csv': ('weather', [r for r in tables['weather'] if r['period'] == 'historical_observation']),
        'simulated_future/weather.csv': ('weather', [r for r in tables['weather'] if r['period'] == 'simulated_future_truth']),
    })
    manifest = dict(manifest, row_counts={k: len(r) for k, r in tables.items()}, validation=report,
                    files={}, dictionary_sha256=hashlib.sha256(data_dictionary().encode()).hexdigest())
    # Build all files before publication. Manifest is replaced last as completion marker.
    with TemporaryDirectory(prefix='.port-demo-', dir=directory.parent) as staging:
        staging = Path(staging)
        for filename, (table, rows) in artifacts.items():
            payload = csv_bytes(table, rows)
            path = staging/filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            manifest['files'][filename] = dict(table=table, rows=len(rows), bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest())
        (staging/'data_dictionary.md').write_text(data_dictionary(), encoding='utf-8', newline='\n')
        (staging/'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n', encoding='utf-8', newline='\n')
        for filename in [*artifacts, 'data_dictionary.md', 'manifest.json']:
            dest = directory/filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging/filename, dest)
    return manifest


def read_dataset(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('synthetic'):
        raise ValueError('Only synthetic datasets can be seeded with this tool')
    if hashlib.sha256((directory/'data_dictionary.md').read_bytes()).hexdigest() != manifest['dictionary_sha256']:
        raise DataValidationError(['Data dictionary checksum mismatch'])
    if not {f'{name}.csv' for name in SCHEMA} <= set(manifest['files']):
        raise DataValidationError(['Manifest missing canonical table checksums'])
    for filename, info in manifest['files'].items():
        path = (directory/filename).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError('Manifest file outside dataset directory')
        if hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            raise DataValidationError([f'{filename}: checksum mismatch'])
    tables = {}
    for name, fields in SCHEMA.items():
        with (directory/f'{name}.csv').open(encoding='utf-8', newline='') as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(fields):
                raise DataValidationError([f'{name}: CSV field mismatch'])
            rows = []
            for raw in reader:
                row = {}
                for key, field in fields.items():
                    value = raw[key]
                    try:
                        if value == '' and field.nullable:
                            value = None
                        elif field.kind == 'int':
                            value = int(value)
                        elif field.kind == 'float':
                            value = float(value)
                        elif field.kind == 'time':
                            parse(value)
                    except (TypeError, ValueError) as error:
                        raise DataValidationError([f'{name}/{key}: invalid CSV value']) from error
                    row[key] = value
                rows.append(row)
        tables[name] = rows
    report = validate(tables, manifest)
    if manifest['row_counts'] != {k: len(r) for k, r in tables.items()}:
        raise DataValidationError(['Manifest row counts mismatch'])
    return tables, manifest, report
