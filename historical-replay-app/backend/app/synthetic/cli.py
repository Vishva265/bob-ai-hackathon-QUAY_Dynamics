"""Usage: python -m app.synthetic.cli generate|validate|seed."""
import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
import os

from .files import data_dictionary, export_dataset, read_dataset
from .simulator import SCENARIOS, generate
from .storage import seed_database
from .validation import DataValidationError
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[3]


def main(argv=None):
    load_dotenv(ROOT/'.env')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    generator = commands.add_parser('generate', help='Regenerate all named scenarios as CSV')
    generator.add_argument('--seed', type=int, default=int(os.getenv('SYNTHETIC_SEED', '42')))
    generator.add_argument('--epoch', default=os.getenv('SYNTHETIC_EPOCH', '2026-09-13T00:00:00Z'))
    generator.add_argument('--history-days', type=int, default=60)
    generator.add_argument('--upcoming-days', type=int, default=7)
    generator.add_argument('--output', type=Path, default=ROOT/'artifacts'/'demo')
    generator.add_argument('--scenario', choices=['all', *SCENARIOS], default='all')
    generator.add_argument('--seed-databases', action='store_true', help='Seed one dedicated SQLite demo.db per scenario')
    generator.add_argument('--replace-demo', action='store_true', help='Replace owned demo DB rows; never unrelated databases')
    for name in ('validate', 'seed'):
        p = commands.add_parser(name)
        p.add_argument('dataset', type=Path, help='Scenario directory containing manifest.json')
        if name == 'seed':
            p.add_argument('--database-url', required=True, help='Dedicated SQLite or postgresql+psycopg URL')
            p.add_argument('--replace-demo', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'generate':
            if args.history_days < 60 or args.upcoming_days < 7:
                raise ValueError('Demo CLI requires at least 60 historical days and 7 upcoming days')
            scenarios = SCENARIOS if args.scenario == 'all' else [args.scenario]
            summaries = {}
            args.output.mkdir(parents=True, exist_ok=True)
            for scenario in scenarios:
                print(f'Generating {SCENARIOS[scenario]}...', flush=True)
                tables, manifest = generate(args.seed, args.epoch, args.history_days, args.upcoming_days, scenario)
                directory = (args.output/scenario).resolve()
                manifest = export_dataset(directory, tables, manifest)
                # Verify exported bytes/CSV round-trip rather than only in-memory rows.
                tables, _, report = read_dataset(directory)
                calls = {r['id']: r for r in tables['vessel_calls']}
                terminal_capacities = {t['id']: t['yard_capacity_teu'] for t in tables['terminals']}
                outcomes = [r for r in tables['call_outcomes'] if calls[r['call_id']]['period'] == 'upcoming']
                target = 'P01-T01'
                target_ids = {c['id'] for c in tables['vessel_calls'] if c['period'] == 'upcoming' and c['terminal_id'] == target}
                target_outcomes = [o for o in outcomes if o['call_id'] in target_ids]
                summary = dict(location=str(directory), row_counts=manifest['row_counts'], validation=report,
                    historical_calls=manifest['files']['historical/vessel_calls.csv']['rows'],
                    upcoming_calls=manifest['files']['upcoming/vessel_calls.csv']['rows'],
                    upcoming_mean_wait_hours=sum(o['waiting_hours'] for o in outcomes)/len(outcomes),
                    target_terminal_mean_wait_hours=sum(o['waiting_hours'] for o in target_outcomes)/len(target_outcomes),
                    max_yard_occupancy=max(r['closing_teu']/terminal_capacities[r['terminal_id']] for r in tables['yard_snapshots']))
                if args.seed_databases:
                    url = 'sqlite:///' + (directory/'demo.db').as_posix()
                    summary['database'] = seed_database(url, tables, manifest, args.replace_demo)
                summaries[scenario] = summary
                print(json.dumps(summary, indent=2), flush=True)
            (args.output/'summary.json').write_text(json.dumps(summaries, indent=2, sort_keys=True)+'\n', encoding='utf-8', newline='\n')
            (args.output/'data_dictionary.md').write_text(data_dictionary(), encoding='utf-8', newline='\n')
        else:
            tables, manifest, report = read_dataset(args.dataset)
            if args.command == 'seed':
                report = seed_database(args.database_url, tables, manifest, args.replace_demo)
            print(json.dumps(report, indent=2))
    except (ValueError, OSError, DataValidationError) as error:
        parser.exit(1, f'{error}\n')
    except SQLAlchemyError as error:
        parser.exit(1, f'Database seeding failed ({type(error).__name__}); check the dedicated database connection/schema.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
