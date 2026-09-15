"""Exercise all seven explanations against the running demo and prove no DB writes."""
import argparse,json,sqlite3,hashlib
from pathlib import Path
from urllib.request import Request,urlopen


def fingerprint(path):
    with sqlite3.connect(f'file:{Path(path).resolve().as_posix()}?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        data={t:sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM "'+t.replace('"','""')+'"')) for t in tables}
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--base-url',default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--database',default='artifacts/dashboard.db');parser.add_argument('--output',default='artifacts/copilot-demo.json');args=parser.parse_args()
    with sqlite3.connect(f'file:{Path(args.database).resolve().as_posix()}?mode=ro',uri=True) as db:
        row=db.execute("SELECT r.id,r.input_snapshot FROM optimisation_runs r JOIN scenarios s ON s.id=r.scenario_id WHERE lower(s.name) LIKE '%storm%' ORDER BY r.created_at DESC LIMIT 1").fetchone()
        if not row:parser.error('Seed the named storm dashboard scenario first.')
        run,data=row[0],json.loads(row[1]);frozen={c['call_id'] for c in data['carry_in']+data['commitments']}
        calls=[c for c in data['calls'] if c['terminal_id'].startswith('P01-') and c['id'] not in frozen]
        call=next(c['id'] for c in calls if c['scheduled_eta']<'2026-09-15T00:00:00Z')
        assigned=db.execute('SELECT call_id FROM berth_assignments WHERE run_id=? LIMIT 1',(run,)).fetchone()[0]
        decision=db.execute('SELECT d.call_id FROM recommendation_decisions d JOIN recommendation_runs r ON r.id=d.run_id WHERE r.source_run_id=? LIMIT 1',(run,)).fetchone()
        comparison=db.execute("SELECT r.id FROM optimisation_runs r JOIN scenarios s ON s.id=r.scenario_id WHERE r.id<>? AND s.name='Control-room what-if' ORDER BY r.created_at DESC LIMIT 1",(run,)).fetchone()
    questions=[('terminal','Why will Terminal 2 become congested?',{'port_id':'P01'}),
        ('risk','Which vessels are most at risk?',{}),('assignment','Why was this vessel moved to berth B4?',{'call_id':assigned}),
        ('breakdown','What changed after the crane breakdown?',{'run_id':comparison[0],'compare_run_id':run} if comparison else {}),
        ('late_arrival','What happens if this vessel arrives six hours late?',{'call_id':call}),
        ('routing','Why is rerouting recommended or rejected?',{'call_id':decision[0] if decision else call}),
        ('shift','Summarise the next shift for the supervisor.',{})]
    before=fingerprint(args.database);results=[]
    for name,question,context in questions:
        payload=dict(run_id=run,question=question);payload.update(context)
        with urlopen(Request(args.base_url+'/copilot/query',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST'),timeout=180) as response:
            result=json.load(response)
        assert result['plan_modified'] is False and result['optimisation_run_id']==payload['run_id']
        results.append(dict(name=name,request=payload,response=result))
        print(name+': '+result['direct_answer'])
    after=fingerprint(args.database);assert before==after,'Database changed during verification; use an isolated demo with no concurrent writers.'
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(result='PASS',database_unchanged=True,before_hash=before,after_hash=after,examples=results),indent=2),encoding='utf-8')
    print('PASS: seven explanations; every database table unchanged. '+str(output.resolve()))


if __name__=='__main__':main()
