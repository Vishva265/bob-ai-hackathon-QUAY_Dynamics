import {useEffect,useState} from 'react';
import {Anchor,Clock3,Database,History,LoaderCircle,ShieldCheck,TriangleAlert} from 'lucide-react';
import {CartesianGrid,Legend,Line,LineChart,ResponsiveContainer,Tooltip,XAxis,YAxis} from 'recharts';
import {requestControl} from '../api';
import {number,utc} from '../selectors';
import {Panel} from './Primitives';
import type {HistoricalReplayResult,Severity} from '../types';

const congestionScore:Record<Severity,number>={LOW:0,MEDIUM:1,HIGH:2,CRITICAL:3};
const congestionLabels=['Low','Medium','High','Critical'];

export function HistoricalReplay(){
  const [result,setResult]=useState<HistoricalReplayResult|null>(null),[error,setError]=useState<string|null>(null);
  useEffect(()=>{requestControl<HistoricalReplayResult>('/historical-replay').then(setResult).catch(e=>setError(e instanceof Error?e.message:'Replay status unavailable'))},[]);
  if(error)return <div className="error-banner"><TriangleAlert size={18}/>{error}</div>;
  if(!result)return <div className="loading"><LoaderCircle className="spin"/><p>Loading replay evidence...</p></div>;
  if(!result.available)return <Panel eyebrow="REAL DATA NOT PREPARED" title="Historical replay is ready for NOAA input"><div className="context-notice"><Database size={20}/><span>{result.message} No sample or substitute AIS records are bundled.</span></div><p>From the isolated application folder, run:</p><pre><code>{`backend/.venv/Scripts/python.exe backend/scripts/download_real_data.py
backend/.venv/Scripts/python.exe backend/scripts/prepare_ais_data.py
backend/.venv/Scripts/python.exe backend/scripts/run_historical_replay.py
backend/.venv/Scripts/python.exe backend/scripts/evaluate_replay.py`}</code></pre><p>Replay cutoff: {result.cutoff}. See <code>{result.documentation}</code> for PowerShell, Bash, data lineage and manual AccessAIS instructions.</p></Panel>;

  const metrics=result.evaluation?.metrics,plan=result.plan!,hours=result.hourly_comparison||[];
  const chart=hours.map(row=>({...row,label:utc(row.timestamp,true),predicted_congestion_score:congestionScore[row.predicted_congestion_level],actual_congestion_score:congestionScore[row.actual_congestion_level]}));
  const warned=hours.some(row=>congestionScore[row.predicted_congestion_level]>=2&&congestionScore[row.actual_congestion_level]>=2);
  const metricRows=[
    ['Congestion F1',number(metrics?.congestion_f1,2),'Good directional warning'],
    ['Precision',number(metrics?.congestion_precision,2),'When QUAY warned, it was right'],
    ['Recall',number(metrics?.congestion_recall,2),'Some congested hours were missed'],
    ['Queue MAE',`${number(metrics?.queue_count_mae,2)} vessels`,'Queue size was underpredicted'],
    ['Waiting MAE',metrics?.vessel_waiting_time_mae_hours==null?'N/A':`${number(metrics.vessel_waiting_time_mae_hours,2)}h`,`${metrics?.waiting_time_compared_vessels||0} matched vessels`],
    ['Actual waiting',`${number(metrics?.total_actual_vessel_waiting_hours,0)}h`,'AIS-derived crisis severity'],
  ];

  return <div className="historical-replay">
    <section className="historical-hero" aria-labelledby="historical-verdict-title">
      <div><p className="eyebrow">REAL NOAA AIS / LEAKAGE-CONTROLLED VALIDATION</p><h2 id="historical-verdict-title">2021 LA/LB Historical Replay</h2><p>QUAY generated a 72-hour operations plan using only information available at the replay cutoff, then compared it with withheld AIS outcomes.</p></div>
      <div className="historical-verdict"><span>RESULT</span><strong>{warned?'Severe congestion correctly warned':'Congestion warning was incomplete'}</strong><p>Queue size was underpredicted because future AIS-only arrivals had no schedule feed.</p></div>
    </section>

    <section className="leakage-timeline" aria-label="Historical replay leakage-control timeline">
      <article className="observed"><span>1</span><div><strong>10-12 Sep</strong><small>AIS observed and available to QUAY</small></div></article>
      <article className="cutoff"><span>2</span><div><strong>13 Sep, 00:00 UTC</strong><small>Replay cutoff and plan generation</small></div></article>
      <article className="withheld"><span>3</span><div><strong>13-16 Sep</strong><small>Hidden truth revealed only for evaluation</small></div></article>
    </section>

    <div className="historical-metric-grid">
      <article><span>Congestion F1</span><strong>{number(metrics?.congestion_f1,2)}</strong><small>directional warning quality</small></article>
      <article><span>Warning precision</span><strong>{number(metrics?.congestion_precision,2)}</strong><small>share of warnings that were right</small></article>
      <article><span>Queue-count MAE</span><strong>{number(metrics?.queue_count_mae,2)}</strong><small>vessels per hourly bucket</small></article>
      <article><span>Actual waiting</span><strong>{number(metrics?.total_actual_vessel_waiting_hours,0)}h</strong><small>total AIS-derived waiting</small></article>
    </div>

    <Panel eyebrow="PREDICTION VS WITHHELD TRUTH" title="Did QUAY see the crisis coming?" className="historical-chart-panel">
      {chart.length?<><div className="historical-chart chart" role="img" aria-label="Predicted and actual queue count and congestion level over the 72-hour replay"><ResponsiveContainer width="100%" height="100%"><LineChart data={chart} margin={{top:15,right:28,left:4,bottom:14}} accessibilityLayer><CartesianGrid stroke="#e3e9ed" vertical={false}/><XAxis dataKey="label" interval={11} tick={{fontSize:9}}/><YAxis yAxisId="queue" tick={{fontSize:9}} label={{value:'Vessels',angle:-90,position:'insideLeft',fontSize:9}}/><YAxis yAxisId="level" orientation="right" domain={[0,3]} ticks={[0,1,2,3]} tickFormatter={v=>congestionLabels[Number(v)]} tick={{fontSize:9}}/><Tooltip/><Legend wrapperStyle={{fontSize:10}}/><Line yAxisId="queue" type="monotone" dataKey="predicted_queue_count" name="Predicted queue" stroke="#25858c" strokeWidth={2.5} dot={false} isAnimationActive={false}/><Line yAxisId="queue" type="monotone" dataKey="actual_queue_count" name="Actual queue" stroke="#c87135" strokeWidth={2.5} dot={false} isAnimationActive={false}/><Line yAxisId="level" type="stepAfter" dataKey="predicted_congestion_score" name="Predicted congestion" stroke="#4b65a5" strokeDasharray="6 4" dot={false} isAnimationActive={false}/><Line yAxisId="level" type="stepAfter" dataKey="actual_congestion_score" name="Actual congestion" stroke="#9b3f46" strokeDasharray="2 4" dot={false} isAnimationActive={false}/></LineChart></ResponsiveContainer></div><p className="panel-footnote">The queue lines show magnitude. The stepped lines map Low, Medium, High and Critical to the right axis. Actual outcomes were withheld until evaluation.</p></>:<p className="historical-empty-chart">Run <code>evaluate_replay.py</code> to generate the hourly predicted-versus-actual comparison.</p>}
    </Panel>

    <section className="evidence-card-grid" aria-label="Replay data provenance">
      <article className="real"><div><Database size={19}/><span>REAL</span></div><h3>NOAA AIS</h3><p>Vessel identity, timestamp, position, speed, course, navigation status and dimensions when present.</p></article>
      <article className="derived"><div><History size={19}/><span>DERIVED</span></div><h3>Calculated from AIS</h3><p>Zone entry and exit, arrival and departure, waiting time, queue counts, occupancy proxy and congestion labels.</p></article>
      <article className="calibrated"><div><ShieldCheck size={19}/><span>CALIBRATED</span></div><h3>Deterministic assumptions</h3><p>Terminal attribution, cranes, workload, yard and staffing. Calibrated from published capacity information with seed 42.</p></article>
    </section>

    <div className="historical-two-column">
      <Panel eyebrow="WHAT QUAY LEARNED" title="The missing signal is the forward vessel schedule" className="historical-insight"><p>AIS detects vessels once they become observable. It cannot reveal unknown future arrivals before the cutoff. Pairing AIS with a vessel schedule feed would give the forecast earlier demand visibility.</p><p>The optimizer correctly plans the known backlog, while unseen post-cutoff arrivals dominate the 2021 queue growth. QUAY exposes that boundary instead of inventing demand.</p></Panel>
      <Panel eyebrow="MODEL EVALUATION" title="Replay scorecard"><div className="table-scroll"><table aria-label="Historical replay evaluation metrics"><thead><tr><th>Metric</th><th>Result</th><th>Meaning</th></tr></thead><tbody>{metricRows.map(([metric,value,meaning])=><tr key={metric}><td>{metric}</td><td><strong>{value}</strong></td><td>{meaning}</td></tr>)}</tbody></table></div></Panel>
    </div>

    <div className="historical-limitation" role="note"><ShieldCheck size={21}/><div><strong>Evidence boundary</strong><p>No invented AIS records. No post-cutoff future data. Crane, yard and staffing inputs are calibrated assumptions, not 2021 terminal records.</p></div></div>

    <Panel eyebrow="72-HOUR OPERATIONS PLAN" title={`${plan.assignments.length} assignments across ${plan.shifts.length} shifts`}><p className="historical-plan-meta"><Anchor size={17}/> Solver: {plan.solver_status} / schedule: {plan.schedule_source} / constraint violations: {metrics?.constraint_violations} / unscheduled calls: {metrics?.unscheduled_calls}</p><div className="table-scroll"><table><thead><tr><th>Call</th><th>Berth</th><th>Start UTC</th><th>Wait</th><th>Cranes</th></tr></thead><tbody>{plan.assignments.slice(0,30).map(a=><tr key={a.call_id}><td>{a.call_id}</td><td>{a.berth_id}</td><td>{utc(a.start,true)}</td><td>{number(a.waiting_minutes/60)}h</td><td>{a.crane_ids.join(', ')}</td></tr>)}</tbody></table></div><p className="panel-footnote"><Clock3 size={14}/> Plan horizon {utc(plan.as_of,true)} to {utc(plan.end,true)} UTC. Showing the first 30 assignments.</p></Panel>

    {result.evaluation?.interpretation?.length?<Panel title="Evaluation notes"><ul>{result.evaluation.interpretation.map(note=><li key={note}>{note}</li>)}</ul>{plan.data_policy&&<ul>{Object.values(plan.data_policy).map(value=><li key={value}>{value}</li>)}</ul>}</Panel>:null}
  </div>;
}
