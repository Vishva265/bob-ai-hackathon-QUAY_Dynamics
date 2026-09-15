"""Run a live demo through the actual HTTP API and print measured results."""
import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def request(base,path,body=None):
    data=json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json'}),timeout=180) as response:
        return json.load(response)


def run():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--session-id');parser.add_argument('--source-run-id');parser.add_argument('--port-id',default='P01')
    parser.add_argument('--seed',type=int,default=42);parser.add_argument('--recover',action='store_true')
    parser.add_argument('--kind',default='storm_crane_failure',choices=['storm_crane_failure','clock_tick','eta_delay','early_arrival',
        'crane_breakdown','crane_recovery','severe_wind','yard_capacity_reduction','berth_closure','priority_arrival'])
    for field in ('call-id','crane-id','berth-id','terminal-id'):parser.add_argument('--'+field)
    parser.add_argument('--advance-minutes',type=int,default=15);parser.add_argument('--hours',type=float,default=6)
    parser.add_argument('--wind-mps',type=float,default=18);parser.add_argument('--capacity-pct',type=float,default=75)
    parser.add_argument('--output',default='artifacts/live-demo-api.json')
    args=parser.parse_args();base=args.base_url.rstrip('/')
    session=request(base,'/live-demo/'+args.session_id) if args.session_id else request(base,'/live-demo/sessions',
        {'port_id':args.port_id,'source_run_id':args.source_run_id,'seed':args.seed,'time_limit_seconds':2})
    path='/live-demo/'+session['id'];results=[]
    for kind in ([args.kind,'storm_crane_recovery'] if args.recover else [args.kind]):
        session=request(base,path)
        payload=dict(kind=kind,expected_revision=session['revision'],advance_minutes=args.advance_minutes,hours=args.hours,
            wind_mps=args.wind_mps,capacity_pct=args.capacity_pct)
        payload.update({f:getattr(args,f) for f in ('call_id','crane_id','berth_id','terminal_id') if getattr(args,f)})
        queued=request(base,path+'/events',payload);deadline=time.monotonic()+180;last=None
        while time.monotonic()<deadline:
            event=next(e for e in request(base,path+'/events')['items'] if e['id']==queued['id'])
            if event['status']!=last:print(f"event {event['sequence']}: {event['status']}",flush=True);last=event['status']
            if event['status'] in ('SUCCEEDED','FAILED'):break
            time.sleep(.5)
        else:raise RuntimeError('Event timed out; its persisted log remains available for inspection.')
        results.append(event)
        if event['status']=='FAILED':raise RuntimeError(json.dumps(event['error']))
        r=event['result'];print(json.dumps({k:r[k] for k in ['forecast_runtime_ms','optimisation_runtime_ms','solver_runtime_ms',
            'solver_status','plan_change_count','metrics','approval_required','new_plan_id']},indent=2),flush=True)
    session=request(base,path);output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'session':session,'events':results},indent=2),encoding='utf-8')
    print('Dashboard: http://127.0.0.1:5173/?demo='+session['id']+'&run='+session['latest_run_id']+'#live')
    print('Saved '+str(output.resolve()))


if __name__=='__main__':run()
