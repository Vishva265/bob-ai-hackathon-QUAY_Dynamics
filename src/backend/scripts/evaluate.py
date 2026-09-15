"""Regenerate paired strategy evidence and pitch-ready charts, without DB writes."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.evaluation.benchmark import EvaluationConfig, benchmark


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--output',type=Path,default=Path('artifacts/evaluation'))
    parser.add_argument('--repeats',type=int)
    parser.add_argument('--solver-seconds',type=float)
    args=parser.parse_args()
    raw=json.loads(args.config.read_text()) if args.config else {}
    if args.repeats is not None:raw['repeats']=args.repeats
    if args.solver_seconds is not None:raw['solver_seconds']=args.solver_seconds
    config=EvaluationConfig.model_validate(raw)
    root=Path(__file__).resolve().parents[2]
    output=(root/args.output).resolve()
    if not output.is_relative_to(root):raise ValueError('Evaluation output must be inside this workspace')
    bundle=benchmark(root,output,config)
    from app.evaluation.reporting import publish
    publish(bundle,output,root/'docs')
    print(f'Evaluation, raw schedules, forecast scores, CSV/JSON and SVG/PNG charts: {output}')


if __name__=='__main__':main()
