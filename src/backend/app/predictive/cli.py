"""Train versioned models or forecast from validated synthetic observation data."""
import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.predictive.inference import InferenceEngine
from app.predictive.registry import ModelRegistry
from app.predictive.training import train_pipeline
from app.synthetic.files import read_dataset
from app.synthetic.simulator import parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    train = commands.add_parser('train')
    infer = commands.add_parser('infer')
    for command in (train, infer):
        command.add_argument('--dataset', type=Path, required=True)
        command.add_argument('--model-directory', type=Path, default=Path(get_settings().model_directory))
    train.add_argument('--holidays', type=Path, help='JSON object: port IDs to ISO local holiday dates')
    infer.add_argument('--as-of', required=True)
    infer.add_argument('--port-id', action='append')
    infer.add_argument('--model-version')
    infer.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tables, manifest, validation = read_dataset(args.dataset)
    if args.command == 'train':
        holidays = json.loads(args.holidays.read_text(encoding='utf-8')) if args.holidays else None
        if holidays is not None:
            from datetime import date
            if not isinstance(holidays, dict) or any(p not in {r['id'] for r in tables['ports']} for p in holidays):
                raise ValueError('Holiday calendar must map known port IDs to dates')
            for dates in holidays.values():
                if not isinstance(dates, list):
                    raise ValueError('Holiday dates must be lists of ISO dates')
                for value in dates:
                    date.fromisoformat(value)
        metadata, path = train_pipeline(tables, manifest, args.model_directory, holidays, progress=lambda message: print(message, flush=True))
        print(json.dumps(dict(model_version=metadata['model_version'], files=str(path), evaluation=metadata['evaluation'], source_validation=validation), indent=2))
    else:
        engine = InferenceEngine(ModelRegistry(args.model_directory), args.model_version)
        result = engine.forecast(tables, parse(args.as_of), args.port_id, observation_cutoff=manifest['epoch'])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        print(json.dumps(dict(model_version=result['model_version'], congestion_buckets=len(result['congestion']), vessel_predictions=len(result['waiting']), output=str(args.output)), indent=2))


if __name__ == '__main__':
    main()
