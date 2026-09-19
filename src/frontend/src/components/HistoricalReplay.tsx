import {useEffect,useState} from 'react';
import {Anchor,Clock3,Database,History,LoaderCircle,ShieldCheck,TriangleAlert} from 'lucide-react';
import {CartesianGrid,Legend,Line,LineChart,ResponsiveContainer,Tooltip,XAxis,YAxis} from 'recharts';
import {requestControl} from '../api';
import {number,utc} from '../selectors';
import {Panel} from './Primitives';
import type {HistoricalReplayResult,Severity} from '../types';

const congestionScore:Record<Severity,number>={LOW:0,MEDIUM:1,HIGH:2,CRITICAL:3};
const congestionLabels=['Low','Medium','High','Critical'];

export function HistoricalReplay({port='all',onOpenPlan}:{port?:string;onOpenPlan?:()=>void}={}){
  const [result,setResult]=useState<HistoricalReplayResult|null>(null),[error,setError]=useState<string|null>(null);
  const [filter,setFilter]=useState('all'),[query,setQuery]=useState(''),[page,setPage]=useState(0);
  useEffect(()=>{const abort=new AbortController();requestControl<HistoricalReplayResult>('/historical-replay',undefined,abort.signal).then(r=>{if(!abort.signal.aborted)setResult(r)}).catch(e=>{if(!abort.signal.aborted)setError(e instanceof Error?e.message:'Replay status unavailable')});return()=>abort.abort()},[]);
  useEffect(()=>setPage(0),[filter,query,port]);
  if(error)return <div className="error-banner"><TriangleAlert size={18}/>{error}</div>;
  if(!result)return <div className="loading"><LoaderCircle className="spin"/><p>Loading replay evidence...</p></div>;
  if(!result.available)return <Panel eyebrow="REAL DATA NOT PREPARED" title="Historical replay is ready for NOAA input"><div className="context-notice"><Database size={20}/><span>{result.message} No sample or substitute AIS records are bundled.</span></div><p>From the main src folder, run:</p><pre><code>{`backend/.venv/Scripts/python.exe backend/scripts/download_real_data.py
backend/.venv/Scripts/python.exe backend/scripts/prepare_ais_data.py
backend/.venv/Scripts/python.exe backend/scripts/run_historical_replay.py
backend/.venv/Scripts/python.exe backend/scripts/evaluate_replay.py`}</code></pre><p>Replay cutoff: {result.cutoff}. See <code>{result.documentation}</code> for PowerShell, Bash, data lineage and manual AccessAIS instructions.</p></Panel>;

  const metrics=result.evaluation?.metrics,plan=result.plan!,hours=result.hourly_comparison||[];
  const vessels=(result.vessel_comparison||[]).filter(v=>(filter==='all'||v.status===filter)&&(!query||`${v.call_id} ${v.vessel_name} ${v.terminal_id}`.toLowerCase().includes(query.toLowerCase())));
  const summary=result.comparison_summary;
  const pages=Math.max(1,Math.ceil(vessels.length/15)),currentPage=Math.min(page,pages-1);
  const exportCsv=()=>{
    if(!vessels.length)return;
    const columns=Object.keys(vessels[0]) as (keyof typeof vessels[number])[];
    const quote=(value:unknown)=>`"${String(value??'').replaceAll('"','""')}"`;
    const csv=[columns.map(quote).join(','),...vessels.map(v=>columns.map(c=>quote(v[c])).join(','))].join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='quay-2021-actual-vs-proposed.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const chart=hours.map(row=>({...row,label:utc(row.timestamp,true),predicted_congestion_score:congestionScore[row.predicted_congestion_level],actual_congestion_score:congestionScore[row.actual_congestion_level]}));
  const warned=hours.some(row=>congestionScore[row.predicted_congestion_level]>=2&&congestionScore[row.actual_congestion_level]>=2);
  const queueBias=hours.length?hours.reduce((sum,row)=>sum+row.predicted_queue_count-row.actual_queue_count,0)/hours.length:0;
  const queueSummary=hours.length?`Mean queue bias: ${number(queueBias,2)} vessels (predicted minus observed).`:'Evaluation has not been generated.';
  const metricRows=[
    ['Congestion F1',number(metrics?.congestion_f1,2),'Balance of precision and recall'],
    ['Precision',number(metrics?.congestion_precision,2),'Share of warnings matching observed congestion'],
    ['Recall',number(metrics?.congestion_recall,2),'Share of congested hours detected'],
    ['Queue MAE',`${number(metrics?.queue_count_mae,2)} vessels`,'Mean absolute queue error'],
    ['Waiting MAE',metrics?.vessel_waiting_time_mae_hours==null?'N/A':`${number(metrics.vessel_waiting_time_mae_hours,2)}h`,`${metrics?.waiting_time_compared_vessels||0} matched vessels`],
    ['Actual waiting',`${number(metrics?.total_actual_vessel_waiting_hours,0)}h`,'AIS-derived crisis severity'],
    ['Warning lead time',metrics?.congestion_warning_lead_time_hours==null?'N/A':`${number(metrics.congestion_warning_lead_time_hours,1)}h`,'Zero means congestion was already present at warning time'],
    ['Schedule validation',metrics?metrics.constraint_violations===0?'Passed':'Failed':'Pending','Calibrated berth, crane and yard constraints'],
  ];

  return <div className="historical-replay">
    <section className="historical-hero" aria-labelledby="historical-verdict-title">
      <div><p className="eyebrow">REAL NOAA AIS / LEAKAGE-CONTROLLED VALIDATION</p><h2 id="historical-verdict-title">2021 LA/LB Historical Replay</h2><p>Compare observed 2021 operations with QUAY's proposed 72-hour plan. The proposal uses only information available at the replay cutoff.</p>{onOpenPlan&&<button className="button secondary" onClick={onOpenPlan}>Open 2021 proposed plan</button>}</div>
      <div className="historical-verdict"><span>RESULT</span><strong>{!metrics?'Evaluation pending':warned?'Severe congestion detected in matched hours':'Congestion warning was incomplete'}</strong><p>{queueSummary} Unseen future arrivals have no schedule feed.</p></div>
    </section>

    {summary&&<Panel eyebrow="IDENTICAL KNOWN DEMAND · 13–16 SEP UTC" title="Actual operations vs proposed plan">
      <div className="historical-metric-grid">
        <article><span>Actual waiting · modelled calls</span><strong>{number(summary.known_actual_window_wait_hours,1)}h</strong><small>Observed within the 72-hour window</small></article>
        <article><span>Proposed waiting · same calls</span><strong>{number(summary.known_proposed_window_wait_hours,1)}h</strong><small>Includes deferred backlog to horizon end</small></article>
        <article><span>Assigned / modelled calls</span><strong>{summary.proposed_calls} / {summary.known_calls}</strong><small>{summary.deferred_calls} calls deferred</small></article>
        <article><span>Unknown future arrivals</span><strong>{summary.unknown_future_calls}</strong><small>Visible in actual outcomes; absent from proposal</small></article>
      </div><p className="panel-footnote">{summary.basis} {summary.excluded_known_calls||0} additional pre-cutoff observed calls have unresolved berth identity and no comparable proposal. Actual berth times and terminal attribution are derived from AIS. The original terminal's operating plan was not supplied.</p>
    </Panel>}

    {!!result.vessel_comparison?.length&&<Panel eyebrow="EVERY CALL · ACTUAL AND PROPOSED SIDE BY SIDE" title="Vessel comparison">
      <div className="replay-controls"><label>Find vessel or terminal<input aria-label="Find replay vessel" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Vessel, call ID or terminal"/></label><label>Planning visibility<select aria-label="Replay call status" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All calls</option><option value="PROPOSED">Proposed assignments</option><option value="DEFERRED">Deferred known calls</option><option value="NOT_MODELLED">Observed but not modelled</option><option value="UNKNOWN_AT_CUTOFF">Unknown at cutoff</option></select></label><button className="button secondary" disabled={!vessels.length} onClick={exportCsv}>Download comparison CSV</button></div>
      <div className="table-scroll"><table aria-label="Actual and proposed vessel comparison"><thead><tr><th>Vessel / visibility</th><th>Actual terminal / berth start UTC</th><th>Proposed berth / start UTC</th><th>Actual wait in 72h</th><th>Proposed wait in 72h</th><th>Change</th></tr></thead><tbody>{vessels.slice(currentPage*15,(currentPage+1)*15).map(v=><tr key={v.call_id}><td><strong>{v.vessel_name}</strong><small className="subline">{v.call_id}</small><small className="subline">{v.status.replaceAll('_',' ')}</small></td><td>{v.terminal_id}<small className="subline">{v.actual_berth_start?utc(v.actual_berth_start,true):'Berth start not observed'}</small></td><td>{v.proposed_berth_id||'No assignment'}<small className="subline">{v.proposed_start?utc(v.proposed_start,true):v.status==='DEFERRED'?'Deferred; remains in backlog':v.status==='NOT_MODELLED'?'Observed; berth identity unresolved':'Arrival unknown at cutoff'}</small></td><td>{number(v.actual_window_wait_hours,1)}h</td><td>{v.proposed_window_wait_hours===null?'Not comparable':`${number(v.proposed_window_wait_hours,1)}h`}</td><td>{v.window_wait_change_hours===null?'—':`${v.window_wait_change_hours>0?'+':''}${number(v.window_wait_change_hours,1)}h`}</td></tr>)}</tbody></table>{!vessels.length&&<p>No calls match this filter.</p>}</div>
      <div className="replay-pagination"><button className="button secondary" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous</button><span>{vessels.length} calls · Page {currentPage+1} of {pages}</span><button className="button secondary" disabled={currentPage+1>=pages} onClick={()=>setPage(currentPage+1)}>Next</button></div><p className="panel-footnote">Wait columns use the same 72-hour window. Missing berth starts remain unobserved. Deferred calls accumulate proposed waiting to the window's end.</p>
    </Panel>}

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

    <Panel eyebrow="PREDICTION VS WITHHELD TRUTH" title="Proposed backlog vs observed congestion" className="historical-chart-panel">
      {chart.length?<><div className="historical-chart chart" role="img" aria-label="Predicted and actual queue count and congestion level over the 72-hour replay"><ResponsiveContainer width="100%" height="100%"><LineChart data={chart} margin={{top:15,right:28,left:4,bottom:14}} accessibilityLayer><CartesianGrid stroke="#e3e9ed" vertical={false}/><XAxis dataKey="label" interval={11} tick={{fontSize:9}}/><YAxis yAxisId="queue" tick={{fontSize:9}} label={{value:'Vessels',angle:-90,position:'insideLeft',fontSize:9}}/><YAxis yAxisId="level" orientation="right" domain={[0,3]} ticks={[0,1,2,3]} tickFormatter={v=>congestionLabels[Number(v)]} tick={{fontSize:9}}/><Tooltip/><Legend wrapperStyle={{fontSize:10}}/><Line yAxisId="queue" type="monotone" dataKey="predicted_queue_count" name="Proposed known backlog" stroke="#25858c" strokeWidth={2.5} dot={false} isAnimationActive={false}/><Line yAxisId="queue" type="monotone" dataKey="actual_queue_count" name="Actual queue" stroke="#c87135" strokeWidth={2.5} dot={false} isAnimationActive={false}/><Line yAxisId="level" type="stepAfter" dataKey="predicted_congestion_score" name="Proposed congestion" stroke="#4b65a5" strokeDasharray="6 4" dot={false} isAnimationActive={false}/><Line yAxisId="level" type="stepAfter" dataKey="actual_congestion_score" name="Actual congestion" stroke="#9b3f46" strokeDasharray="2 4" dot={false} isAnimationActive={false}/></LineChart></ResponsiveContainer></div><p className="panel-footnote">The queue lines show magnitude. The stepped lines map Low, Medium, High and Critical to the right axis. Actual outcomes were withheld until evaluation.</p></>:<p className="historical-empty-chart">Run <code>evaluate_replay.py</code> to generate the hourly predicted-versus-actual comparison.</p>}
    </Panel>

    <Panel eyebrow="OBSERVED AIS PROXY VS PROPOSED RESOURCE USE" title="Berth utilisation comparison">
      {chart.length?<div className="historical-chart chart" role="img" aria-label="Actual and proposed berth utilisation over the 72-hour replay"><ResponsiveContainer width="100%" height="100%"><LineChart data={chart.map(r=>({...r,actual_percent:r.actual_berth_utilization*100,proposed_percent:r.predicted_berth_utilization*100}))} margin={{top:15,right:24,left:4,bottom:14}} accessibilityLayer><CartesianGrid stroke="#e3e9ed" vertical={false}/><XAxis dataKey="label" interval={11} tick={{fontSize:9}}/><YAxis domain={[0,100]} unit="%" tick={{fontSize:9}}/><Tooltip formatter={value=>`${number(Number(value),1)}%`}/><Legend wrapperStyle={{fontSize:10}}/><Line type="stepAfter" dataKey="actual_percent" name="Actual AIS berth proxy" stroke="#c87135" strokeWidth={2.5} dot={false} isAnimationActive={false}/><Line type="stepAfter" dataKey="proposed_percent" name="Proposed berth utilisation" stroke="#25858c" strokeWidth={2.5} dot={false} isAnimationActive={false}/></LineChart></ResponsiveContainer></div>:<p>Hourly utilisation is available after replay evaluation.</p>}
      <p className="panel-footnote">Actual utilisation is a capped spatial occupancy proxy. Proposed utilisation uses calibrated berth capacity. Lower occupancy alone does not establish a better plan.</p>
    </Panel>

    {hours.length>0&&<Panel eyebrow="ALL NINE SHIFTS · SAME EIGHT-HOUR WINDOWS" title="Shift-by-shift comparison">
      <div className="table-scroll"><table aria-label="Historical actual and proposed shift comparison"><thead><tr><th>Shift / start UTC</th><th>Actual mean queue</th><th>Proposed mean queue</th><th>Actual berth proxy</th><th>Proposed berth use</th><th>Proposed moves</th></tr></thead><tbody>{plan.shifts.map(shift=>{
        const bucket=hours.filter(h=>h.timestamp>=shift.start&&h.timestamp<shift.end);
        const mean=(key:'actual_queue_count'|'predicted_queue_count'|'actual_berth_utilization'|'predicted_berth_utilization')=>bucket.length?bucket.reduce((s,h)=>s+h[key],0)/bucket.length:null;
        const actualBerth=mean('actual_berth_utilization'),proposedBerth=mean('predicted_berth_utilization');
        return <tr key={shift.shift_index}><td>Shift {shift.shift_index+1}<small className="subline">{utc(shift.start,true)}</small></td><td>{number(mean('actual_queue_count'),1)}</td><td>{number(mean('predicted_queue_count'),1)}</td><td>{number(actualBerth===null?null:actualBerth*100,1)}%</td><td>{number(proposedBerth===null?null:proposedBerth*100,1)}%</td><td>{number(shift.tasks.reduce((s,t)=>s+t.planned_moves,0),0)}</td></tr>;
      })}</tbody></table></div><p className="panel-footnote">Queues include actual later arrivals; the proposal has only demand known at cutoff. Crane, workload and staffing figures describe the calibrated proposal.</p>
    </Panel>}

    <section className="evidence-card-grid" aria-label="Replay data provenance">
      <article className="real"><div><Database size={19}/><span>REAL</span></div><h3>NOAA AIS</h3><p>Vessel identity, timestamp, position, speed, course, navigation status and dimensions when present.</p></article>
      <article className="derived"><div><History size={19}/><span>DERIVED</span></div><h3>Calculated from AIS</h3><p>Zone entry and exit, arrival and departure, waiting time, queue counts, occupancy proxy and congestion labels.</p></article>
      <article className="calibrated"><div><ShieldCheck size={19}/><span>CALIBRATED</span></div><h3>Deterministic assumptions</h3><p>Terminal attribution, cranes, workload, yard and staffing. Calibrated from published capacity information with seed 42.</p></article>
    </section>

    <div className="historical-two-column">
      <Panel eyebrow="WHAT QUAY LEARNED" title="The missing signal is the forward vessel schedule" className="historical-insight"><p>AIS detects vessels once they become observable. It cannot reveal unknown future arrivals before the cutoff. Pairing AIS with a vessel schedule feed would give the forecast earlier demand visibility.</p><p>The optimizer attempts to schedule the known backlog. Deferred known calls remain in its queue forecast; unseen post-cutoff arrivals are included only in evaluation. QUAY exposes that boundary instead of inventing demand.</p></Panel>
      <Panel eyebrow="MODEL EVALUATION" title="Replay scorecard"><div className="table-scroll"><table aria-label="Historical replay evaluation metrics"><thead><tr><th>Metric</th><th>Result</th><th>Meaning</th></tr></thead><tbody>{metricRows.map(([metric,value,meaning])=><tr key={metric}><td>{metric}</td><td><strong>{value}</strong></td><td>{meaning}</td></tr>)}</tbody></table></div></Panel>
    </div>

    <div className="historical-limitation" role="note"><ShieldCheck size={21}/><div><strong>Evidence boundary</strong><p>No invented AIS records. No post-cutoff future data. Crane, yard and staffing inputs are calibrated assumptions, not 2021 terminal records.</p></div></div>

    <Panel eyebrow="72-HOUR OPERATIONS PLAN" title={`${plan.assignments.length} assignments across ${plan.shifts.length} shifts`}><p className="historical-plan-meta"><Anchor size={17}/> Solver: {plan.solver_status} / schedule: {plan.schedule_source} / constraint violations: {metrics?.constraint_violations} / unscheduled calls: {metrics?.unscheduled_calls}</p><div className="table-scroll"><table><thead><tr><th>Call</th><th>Berth</th><th>Start UTC</th><th>Wait</th><th>Cranes</th></tr></thead><tbody>{plan.assignments.slice(0,30).map(a=><tr key={a.call_id}><td>{a.call_id}</td><td>{a.berth_id}</td><td>{utc(a.start,true)}</td><td>{number(a.waiting_minutes/60)}h</td><td>{a.crane_ids.join(', ')}</td></tr>)}</tbody></table></div><p className="panel-footnote"><Clock3 size={14}/> Plan horizon {utc(plan.as_of,true)} to {utc(plan.end,true)} UTC. Showing the first 30 assignments. Some assignments use the 120-hour computation tail beyond this view's 72-hour window.</p></Panel>

    {result.evaluation?.interpretation?.length?<Panel title="Evaluation notes"><ul>{result.evaluation.interpretation.map(note=><li key={note}>{note}</li>)}</ul>{plan.data_policy&&<ul>{Object.values(plan.data_policy).map(value=><li key={value}>{value}</li>)}</ul>}</Panel>:null}
  </div>;
}
