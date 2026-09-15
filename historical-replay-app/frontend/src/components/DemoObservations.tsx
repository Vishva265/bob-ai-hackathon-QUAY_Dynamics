import type {Dashboard} from '../types';
import {number,utc} from '../selectors';
import {Panel} from './Primitives';

export function DemoObservations({data,port}:{data:Dashboard;port:string}){
  const rows=data.inventory.terminals.filter(t=>port==='all'||t.port_id===port).map(t=>{
    const yard=data.inventory.yards.find(y=>y.terminal_id===t.id);
    const queue=yard&&Number.isFinite(Number(yard.queued_vessels))?Number(yard.queued_vessels):null;
    const future=data.forecast_rows.filter(f=>f.scope==='terminal'&&f.scope_id===t.id&&f.timestamp>data.run.as_of&&f.queue_length>0).sort((a,b)=>a.timestamp.localeCompare(b.timestamp))[0];
    return {terminal:t,yard,queue,future};
  });
  const observed=rows.every(r=>r.queue!==null)?rows.reduce((sum,r)=>sum+r.queue!,0):null;
  return <Panel title={observed===0?'No observed queue. Pressure ahead.':'Observed operations and future pressure.'} eyebrow="LAST OBSERVATION ≠ FORECAST">
    <p>Last observed queue: <strong>{observed===null?'Unavailable':`${number(observed,0)} vessels`}</strong>. Future risks remain visible even while the last observed yard queues are clear.</p>
    <div className="table-scroll" tabIndex={0}><table><thead><tr><th>Terminal</th><th>Observation UTC</th><th>Observed queue</th><th>Yard occupancy</th><th>First projected queue UTC</th><th>Predicted wait</th></tr></thead><tbody>{rows.map(r=><tr key={r.terminal.id}><td>{r.terminal.name}</td><td>{r.yard?utc(String(r.yard.timestamp),true):'Unavailable'}</td><td>{r.queue===null?'Unavailable':`${r.queue} vessels`}</td><td>{r.yard?`${number(Number(r.yard.closing_teu)/r.terminal.yard_capacity_teu*100)}%`:'Unavailable'}</td><td>{r.future?utc(r.future.timestamp,true):'No queue projected'}</td><td>{r.future?`${number(r.future.average_wait_hours)}h · ${r.future.confidence_level} confidence`:'—'}</td></tr>)}</tbody></table></div>
    <p className="panel-footnote">Synthetic observations use their recorded UTC timestamp; these are not live AIS measurements. Forecast queues are hourly projections and never relabelled as current observations.</p>
  </Panel>;
}
