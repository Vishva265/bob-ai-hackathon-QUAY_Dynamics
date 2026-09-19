import {useState} from 'react';
import {Check,Download,FileCheck,ShieldCheck,TriangleAlert} from 'lucide-react';
import type {Dashboard,Reason} from '../types';
import {callName,number,portOf,utc} from '../selectors';
import {Badge,Empty,Panel,ReasonList} from './Primitives';

const decisionEffects:Record<string,string>={
  FORECAST_CONGESTION:'Reduce avoidable queue exposure before the forecast hotspot.',
  ARRIVAL_SURGE:'Sequence arrivals against confirmed berth and crane capacity.',
  BERTH_UTILISATION:'Protect a compatible berth window and prevent overlapping work.',
  CRANE_UTILISATION:'Confirm crane ownership so planned handling remains executable.',
  YARD_OCCUPANCY:'Keep container staging below the certified safe yard limit.',
  LOW_CONFIDENCE:'Reconcile fresh observations before changing the approved plan.',
  SHIFT_START_RECONCILIATION:'Start the shift from confirmed ETAs, inventory and resource status.'
};

function priority(r:Reason){
  const code=String(r.code||'');
  return (code==='FORECAST_CONGESTION'?50:0)+(code==='ARRIVAL_SURGE'?45:0)+
    (code==='YARD_OCCUPANCY'?40:0)+(code==='BERTH_UTILISATION'?35:0)+
    (code==='CRANE_UTILISATION'?30:0)+(code==='LOW_CONFIDENCE'?10:0);
}
function affected(r:Reason){
  const ids=[r.call_id,r.scope_id,r.terminal_id,r.berth_id].filter(Boolean).map(String);
  return ids.length?[...new Set(ids)].join(' · '):'Full shift scope';
}
function decisionText(r:Reason){return String(r.action||r.message||r.code||'Review recorded operating condition')}

type Props={readOnly?:boolean;data:Dashboard;port:string;busy:boolean;actor:string;setActor:(v:string)=>void;onReview:()=>void;onApprove:()=>void;onDraft:()=>void;onExport:(f:'json'|'csv'|'html')=>void;onAck:(id:string,rev:number)=>void;onVessel:(id:string)=>void};

export function Shifts({readOnly=false,data,port,busy,actor,setActor,onReview,onApprove,onDraft,onExport,onAck,onVessel}:Props){
  const [index,setIndex]=useState(0);
  const plan=data.run.plan;
  if(!plan)return <Empty>No supervisor plan exists for this run. Generate an operational draft first.</Empty>;
  const shift=plan.shifts[index],d=shift.details;
  const scope=(rows:Reason[])=>rows.filter(r=>port==='all'||r.port_id===port||portOf(data,String(r.terminal_id))===port||portOf(data,data.inventory.calls.find(c=>c.id===r.call_id)?.terminal_id||'')===port);
  const jobs=scope(d.berth_assignments);
  const actions=port==='all'?d.required_supervisor_actions:scope(d.required_supervisor_actions);
  const top=[...actions].sort((a,b)=>priority(b)-priority(a))
    .filter((r,i,all)=>all.findIndex(x=>String(x.code||x.message)===String(r.code||r.message))===i).slice(0,3);
  return <>
    <Panel title="A clear plan. A confident handover." eyebrow="ROLLING SUPERVISOR PUBLICATION" action={<Badge level={plan.status}/> }>
      <div className="plan-toolbar"><label>Supervisor name<input value={actor} onChange={e=>setActor(e.target.value)} maxLength={120} aria-label="Supervisor name" placeholder="Name recorded in the audit"/></label><div className="plan-actions"><button className="button secondary" onClick={onReview} disabled={readOnly||busy||!actor.trim()||!!data.run.scenario_id||plan.status!=='DRAFT'} title={data.run.scenario_id?'Scenario is read-only. Create an operational draft.':'Review the current draft revision'}><FileCheck size={16}/>Mark reviewed</button><button className="button primary" onClick={onApprove} disabled={readOnly||busy||!actor.trim()||!!data.run.scenario_id||plan.status!=='REVIEWED'} title="Approval requires REVIEWED, fresh inputs and complete feasible assignments"><ShieldCheck size={16}/>Approve plan</button><button className="button secondary" onClick={()=>onExport('json')} disabled={busy}><Download size={15}/>JSON</button><button className="button secondary" onClick={()=>onExport('csv')} disabled={busy}>CSV</button><button className="button secondary" onClick={()=>onExport('html')} disabled={busy}>Printable HTML</button></div></div>
      <div className="plan-meta"><span>Revision {plan.revision}</span><span>{plan.shifts.length} shifts · 8 hours each</span><span>Confidence {plan.document.confidence}</span><span>All times UTC</span></div>
      <div className="context-notice"><TriangleAlert size={17}/><span>{readOnly?'Historical replay: inspect and export the frozen proposal; actual AIS outcomes appear in Historical replay.':data.run.scenario_id?'This is a hypothetical scenario. Review and approval apply only to operational drafts.':'Review changes and reconcile current conditions before approving dispatch.'}</span><button className="text-action" disabled={readOnly||busy} onClick={onDraft}>Create operational draft →</button></div>
      <div className="shift-tabs" role="tablist" aria-label="Supervisor shifts">{plan.shifts.map(s=><button role="tab" tabIndex={index===s.shift_index?0:-1} onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?8:(index+(e.key==='ArrowRight'?1:8))%9;setIndex(next);document.getElementById(`shift-tab-${next}`)?.focus()}} aria-selected={index===s.shift_index} aria-controls="shift-content" id={`shift-tab-${s.shift_index}`} key={s.shift_index} onClick={()=>setIndex(s.shift_index)}><span>SHIFT {s.shift_index+1}</span><strong>{utc(s.start,true)}</strong><small>{number(s.details.planned_container_moves,0)} moves</small></button>)}</div>
    </Panel>
    <div id="shift-content" role="tabpanel" aria-labelledby={`shift-tab-${index}`}>
      <div className="shift-summary"><div><p className="eyebrow">SHIFT {index+1} · {utc(shift.start,true)}–{utc(shift.end,true)} UTC</p><h2>What the next supervisor needs to know</h2></div><div className="shift-counts">{[['Incoming',scope(d.incoming).length],['Waiting',scope(d.waiting).length],['Berthing',scope(d.berthing).length],['Departing',scope(d.departing).length]].map(([label,count])=><span key={label}><strong>{count}</strong>{label}</span>)}</div></div>
      <div className="overview-grid">
        <Panel title="Top decisions for this shift" eyebrow={`${top.length} OF ${actions.length} ACTIONS PRIORITISED`}>
          {top.length?<div className="decision-stack">{top.map((r,i)=><article className="decision-card" key={`${r.code||r.message}-${i}`}><span className="decision-rank">{i+1}</span><div><strong>{decisionText(r)}</strong><dl><dt>Affected</dt><dd>{affected(r)}</dd><dt>Decision deadline</dt><dd>{utc(String(r.deadline||r.expected_start||r.timestamp||shift.end),true)} UTC</dd><dt>Expected effect</dt><dd>{decisionEffects[String(r.code)]||'Preserve a safe, executable handover under the recorded constraints.'}</dd></dl></div></article>)}</div>:<Empty>No supervisor decisions recorded for this shift.</Empty>}
          <details><summary>All {actions.length} recorded actions and evidence</summary><ReasonList items={actions}/></details>
          <div className="handover-box"><h3>Shift handover notes</h3><ReasonList items={d.handover_notes}/></div>
        </Panel>
        <Panel title="Vessels & resource allocation" eyebrow={`${jobs.length} BERTHED IN SELECTED SCOPE`}><div className="table-scroll"><table><thead><tr><th>Vessel / berth</th><th>Start → completion UTC</th><th>Moves</th></tr></thead><tbody>{jobs.map(a=><tr key={String(a.call_id)}><td><button className="vessel-link" onClick={()=>onVessel(String(a.call_id))}>{callName(data,String(a.call_id))}</button><small className="subline">{String(a.berth_id)}</small></td><td>{utc(String(a.start))} → {a.completion_time?utc(String(a.completion_time),true):'Unresolved'}</td><td>{number(Number(a.planned_moves_in_shift),0)}</td></tr>)}</tbody></table></div>{!jobs.length&&<Empty>No berth assignments for this shift and scope.</Empty>}<details><summary>Crane allocations and expected productivity</summary><ReasonList items={d.crane_allocation}/></details></Panel>
      </div>
      <div className="overview-grid"><Panel title="Constraints & contingencies" eyebrow="KEEP THE HARD LIMITS VISIBLE">{[['Projected yard occupancy',scope(d.projected_yard_occupancy)],['Weather constraints',d.weather_constraints],['Tide constraints',d.tide_constraints],['Equipment restrictions',d.maintenance_and_equipment_restrictions],['High-risk handoffs',d.high_risk_handoffs],['Contingency actions',d.contingency_actions],['Approved arrival changes / diversions',d.approved_diversions_or_arrival_changes]].map(([title,items])=><details key={String(title)}><summary>{String(title)}</summary><ReasonList items={items as Reason[]}/></details>)}</Panel><Panel title="Congestion alerts" eyebrow="FORECAST EVIDENCE & ALERT LIFECYCLE"><ReasonList items={d.congestion_alerts}/>{data.alerts.filter(a=>a.state==='OPEN').slice(0,6).map(a=><div className="alert-action" key={a.id}><div><strong>{a.rule_code.replaceAll('_',' ')}</strong><small>{String(a.scope_id)} · {utc(a.expected_start,true)} UTC</small></div><button className="button secondary" disabled={readOnly||busy||!actor.trim()} onClick={()=>onAck(a.id,a.revision)}><Check size={14}/>Acknowledge</button></div>)}</Panel></div>
      <Panel title="Changes, conflicts & assumptions" eyebrow="COMPARED WITH THE PREVIOUSLY APPROVED PLAN"><details open={!!plan.document.unresolved_conflicts.length}><summary>{plan.document.unresolved_conflicts.length} unresolved conflicts</summary><ReasonList items={plan.document.unresolved_conflicts}/></details><details><summary>{plan.document.changes_compared_with_approved_plan.length} material schedule changes</summary><ReasonList items={plan.document.changes_compared_with_approved_plan}/></details><details><summary>Plan assumptions and confidence</summary><ReasonList items={plan.document.assumptions}/></details></Panel>
    </div>
  </>;
}
