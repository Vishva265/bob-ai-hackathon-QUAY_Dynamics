import {useEffect,useRef,useState} from 'react';
import {Download,FlaskConical,Upload} from 'lucide-react';
import {request} from '../api';
import type {Dashboard,Metrics} from '../types';
import {number,utc} from '../selectors';
import {Panel,ReasonList} from './Primitives';

type Validation={valid:boolean;accepted_rows:number;errors:{row:number;field:string;message:string}[];preview:Record<string,unknown>[]};
type Result={persisted:false;source_run_id:string;uploaded_calls:number;solver_status:string;baseline:Metrics;metrics:Metrics;assignments:{call_id:string;berth_id:string;start:string;waiting_minutes:number}[];diagnostics:{unscheduled_call_ids:string[]};assumptions:string[]};

export function DataLab({data,port}:{data:Dashboard;port:string}){
  const [content,setContent]=useState(''),[format,setFormat]=useState<'csv'|'json'>('csv');
  const [validation,setValidation]=useState<Validation|null>(null),[result,setResult]=useState<Result|null>(null);
  const [pending,setPending]=useState(''),[error,setError]=useState('');
  const abort=useRef<AbortController|null>(null);
  useEffect(()=>{abort.current?.abort();setValidation(null);setResult(null);setError('');setPending('')},[data.run.id,port]);
  useEffect(()=>()=>abort.current?.abort(),[]);
  function change(value:string){setContent(value);setValidation(null);setResult(null);setError('')}
  function example(){
    const terminal=data.inventory.terminals.find(t=>port==='all'||t.port_id===port);
    if(!terminal)return;
    const eta=new Date(new Date(data.run.as_of).getTime()+12*3600000).toISOString();
    const row={id:'LAB-CALL-01',terminal_id:terminal.id,scheduled_eta:eta,length_m:180,draft_m:8,capacity_teu:2000,onboard_teu:600,unload_moves:200,load_moves:100,priority:3,cargo_type:'general',teu_per_move:1.5,max_cranes:3,required_equipment:'panamax_sts'};
    change(format==='json'?JSON.stringify([row],null,2):Object.keys(row).join(',')+'\n'+Object.values(row).join(','));
  }
  async function upload(file?:File){
    if(!file)return;
    if(file.size>250000){setError('Choose a CSV or JSON file smaller than 250 KB.');return}
    setFormat(file.name.toLowerCase().endsWith('.json')?'json':'csv');
    try{change(await file.text())}catch{setError('Unable to read the selected file.')}
  }
  async function run(simulate:boolean){
    const controller=new AbortController();abort.current=controller;setPending(simulate?'Solving baseline and uploaded demand…':'Validating rows…');setError('');setResult(null);
    const body={source_run_id:data.run.id,content,format,time_limit_seconds:2};
    try{
      const checked=await request<Validation>('/data-lab/validate',body,controller.signal);
      if(controller.signal.aborted)return;
      setValidation(checked);
      if(simulate&&checked.valid){const output=await request<Result>('/data-lab/simulate',body,controller.signal);if(!controller.signal.aborted)setResult(output)}
    }catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'Unable to test data.')}
    finally{if(!controller.signal.aborted)setPending('')}
  }
  function download(){
    const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='quay-data-lab-result.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <div className="data-lab"><div className="context-notice"><FlaskConical/><span>Add your own vessel calls to this plan and compare scheduling outcomes. Simulations are unsaved and preserve existing commitments.</span></div>
    <Panel title="Test your data" eyebrow="CSV / JSON · VALIDATE → SIMULATE → COMPARE">
      <p>Source: {data.scenario_name} · {utc(data.run.as_of,true)} UTC. Up to 100 new calls within the next 72 hours.</p>
      <div className="lab-controls"><label>Input format<select aria-label="Input format" disabled={!!pending} value={format} onChange={e=>{setFormat(e.target.value as 'csv'|'json');change('')}}><option value="csv">CSV</option><option value="json">JSON</option></select></label>
        <label className="button secondary"><Upload size={16}/> Upload file<input aria-label="Upload vessel data" type="file" accept=".csv,.json,text/csv,application/json" disabled={!!pending} onChange={e=>void upload(e.target.files?.[0])}/></label>
        <button className="button secondary" disabled={!!pending} onClick={example}>Load example</button></div>
      <label htmlFor="lab-data">Vessel-call data<textarea id="lab-data" className="lab-editor" rows={10} maxLength={250000} disabled={!!pending} value={content} onChange={e=>change(e.target.value)} placeholder="Load an example, upload a CSV/JSON file, or paste vessel-call data."/></label>
      <details><summary>Fields and accepted terminal IDs</summary><p>Required: id, terminal_id, scheduled_eta, length_m, draft_m, capacity_teu, onboard_teu, unload_moves, load_moves. Optional: priority, cargo_type, teu_per_move, max_cranes, required_equipment. ETAs need a timezone. Existing call IDs cannot be replaced.</p><p>{data.inventory.terminals.map(t=>t.id).join(', ')}</p></details>
      <div className="lab-controls"><button className="button secondary" disabled={!!pending||!content.trim()} onClick={()=>void run(false)}>Validate data</button><button className="button primary" disabled={!!pending||!content.trim()} onClick={()=>void run(true)}>Run simulation</button><span role="status">{pending}</span></div>
      {error&&<div className="error-banner" role="alert">{error}</div>}
      {validation&&<div aria-live="polite">{validation.valid?<p className="context-notice">{validation.accepted_rows} rows validated. Ready to simulate.</p>:<div className="table-scroll"><table><caption>Correct these validation errors</caption><thead><tr><th>Row</th><th>Field</th><th>Error</th></tr></thead><tbody>{validation.errors.map((e,i)=><tr key={i}><td>{e.row||'File'}</td><td>{e.field}</td><td>{e.message}</td></tr>)}</tbody></table></div>}</div>}
    </Panel>
    {result&&<Panel title="Simulation results" eyebrow={`${result.solver_status} · UNSAVED WHAT-IF`}><div className="lab-controls"><p role="status">{result.metrics.validation_passed?'Schedule passed feasibility checks.':'No certified feasible schedule. Inspect deferrals and constraints.'}</p><button className="button secondary" onClick={download}><Download size={16}/> Download result</button></div><div className="table-scroll"><table><thead><tr><th>All-demand metric</th><th>Baseline</th><th>With uploaded calls</th></tr></thead><tbody>{(['average_wait_hours','maximum_wait_hours','served_vessels','deferred_vessels'] as const).map(key=><tr key={key}><td>{key.replaceAll('_',' ')}</td><td>{number(result.baseline[key])}</td><td>{number(result.metrics[key])}</td></tr>)}</tbody></table></div><p>Baseline feasibility: {result.baseline.validation_passed?'passed':'not certified'}. Served averages can cover different vessel sets.</p><h3>Uploaded vessel assignments</h3><div className="table-scroll"><table><thead><tr><th>Call</th><th>Berth</th><th>Start UTC</th><th>Wait</th></tr></thead><tbody>{result.assignments.map(a=><tr key={a.call_id}><td>{a.call_id}</td><td>{a.berth_id}</td><td>{utc(a.start,true)}</td><td>{number(a.waiting_minutes/60)}h</td></tr>)}</tbody></table></div>{!result.assignments.length&&<p>No uploaded calls received an assignment. Inspect deferred calls in the downloaded result.</p>}<ReasonList items={result.assumptions}/></Panel>}
  </div>
}
