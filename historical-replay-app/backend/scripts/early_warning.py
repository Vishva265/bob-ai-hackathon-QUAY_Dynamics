"""Run and persist the complete 72-hour forecast, projection and alert process."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models as m
from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.errors import DomainError
from app.schemas import EarlyWarningInput, EarlyWarningRunOut
from app.services.early_warning import EarlyWarningService
from sqlalchemy.exc import SQLAlchemyError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', help='UTC origin; defaults to imported demo observation cutoff')
    parser.add_argument('--port-id', action='append', help='Repeat to select ports; default all')
    parser.add_argument('--rules', type=Path, help='Validated JSON rule configuration override')
    parser.add_argument('--output', type=Path, default=Path('artifacts/early-warning/latest-summary.json'))
    args = parser.parse_args()
    engine = make_engine(get_settings().database_url)
    try:
        migrate(engine)
        with session_factory(engine).begin() as session:
            provenance = session.get(m.SeedProvenance, 1)
            origin = args.as_of or (provenance.epoch if provenance else None)
            if origin is None:
                parser.error('--as-of is required when no demo seed provenance exists')
            rules = json.loads(args.rules.read_text(encoding='utf-8')) if args.rules else None
            payload = EarlyWarningInput(as_of=origin, port_ids=args.port_id, rules=rules)
            service = EarlyWarningService(session)
            result = service.output(service.run(payload).id)
            validated = EarlyWarningRunOut.model_validate(result)
            document = validated.model_dump(mode='json')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
        print(f"72-hour early warning | origin {document['as_of']} | run {document['id']}")
        print(f"{document['operational_bucket_count']} hourly buckets | model {document['model_version']}")
        for summary in document['summaries']:
            if summary['scope'] == 'port':
                first = summary['first_expected_hotspot_time'] or 'none'
                print(f"{summary['scope_id']}: first {first}, duration {summary['expected_hotspot_duration_hours']}h, total {summary['total_hotspot_hours']}h; "
                      f"peak queue {summary['peak_queue_length']:.1f}, wait {summary['peak_wait_hours']:.1f}h; review {summary['low_confidence_hours']}h")
        for scope in ['terminal', 'berth']:
            selected = [s for s in document['summaries'] if s['scope'] == scope]
            print(f"{scope.title()} hotspots: {sum(s['total_hotspot_hours'] > 0 for s in selected)}/{len(selected)}")
        print(f"Alerts: {document['alert_counts']} | saved {args.output.resolve()}")
    except SQLAlchemyError:
        parser.exit(1, 'Forecast failed: database unavailable or conflicting transaction; check DATABASE_URL and readiness.\n')
    except (DomainError, ValueError, OSError) as exc:
        parser.exit(1, f'Forecast failed: {exc}\n')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
