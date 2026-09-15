import type {ReactNode} from 'react';
import {ArrowUpRight,LoaderCircle} from 'lucide-react';
import type {Reason,Severity} from '../types';
import {number} from '../selectors';
export function Badge({level}:{level:string|null}){const style=level?.endsWith(' CONFIDENCE')?level.split(' ')[0].toLowerCase()+'-confidence':level?.toLowerCase()||'unknown';return <span className={`badge ${style}`}><span aria-hidden="true" className="status-dot"/>{level||'Unavailable'}</span>}
export function Panel({title,eyebrow,action,children,className=''}:{title:string;eyebrow?:string;action?:ReactNode;children:ReactNode;className?:string}){return <section className={`panel ${className}`}><header className="panel-heading"><div>{eyebrow&&<p className="eyebrow">{eyebrow}</p>}<h2>{title}</h2></div>{action}</header>{children}</section>}
export function Empty({children}:{children:ReactNode}){return <div className="empty">{children}</div>}
export function Loading(){return <div className="loading" role="status"><LoaderCircle className="spin" size={30}/><h2>Preparing your command centre</h2><p>Loading persisted forecasts, resources and supervisor plans…</p></div>}
function reasonText(r:Reason|string):string{
  if(typeof r==='string')return r;
  const context=[r.scope_id||r.call_id||r.crane_id||r.terminal_id||r.port_id,r.code||r.trigger].filter(Boolean).join(' · ');
  if(r.rule_code)return `${r.scope_id||r.port_id} — ${String(r.rule_code).replaceAll('_',' ')} · ${r.state}. Expected ${r.expected_start} · ${number(Number(r.duration_hours))}h episode. Inspect current forecast evidence before acknowledging.`;
  if(r.action||r.message)return `${context?context+' — ':''}${r.action||r.message}${r.unavailable_hours!==undefined?` (${number(Number(r.unavailable_hours))}h unavailable)`:''}`;
  if(r.expected_moves_per_crane_hour!==undefined){const segments=r.segments as {crane_ids:string[]}[];return `${context} — ${number(Number(r.planned_moves),0)} moves · ${number(Number(r.crane_hours))} crane-hours · ${number(Number(r.expected_moves_per_crane_hour))} expected moves/crane-hour · ${Math.max(0,...segments.map(s=>s.crane_ids.length))} peak cranes. Timed segments remain in the plan export.`}
  if(r.peak_occupancy_fraction!==undefined)return `${context} — Opening ${number(Number(r.opening_teu),0)}, closing ${number(Number(r.closing_teu),0)}, peak ${number(Number(r.peak_teu),0)} TEU (${number(Number(r.peak_occupancy_fraction)*100)}%); safe planning capacity ${number(Number(r.safe_planning_capacity_teu),0)} TEU.`;
  if(r.wind_mps!==undefined)return `${context} — Observed wind ${number(Number(r.wind_mps))}m/s, visibility ${number(Number(r.visibility_m),0)}m, rain ${number(Number(r.rain_mm_per_hour))}mm/h at ${r.timestamp}. Known closure intervals: ${JSON.stringify(r.closed_intervals)}.`;
  if(r.minimum_height_m!==undefined)return `${context} — Projected tide band ${number(Number(r.minimum_height_m))} to ${number(Number(r.maximum_height_m))}m. ${r.supervisor_action} Movement thresholds: ${(r.movement_requirements as Reason[]).map(m=>`${m.call_id}: ${number(Number(m.required_tide_height_m))}m minimum`).join('; ')}.`;
  return Object.entries(r).map(([k,v])=>`${k.replaceAll('_',' ')}: ${typeof v==='object'?JSON.stringify(v):v}`).join(' · ');
}
export function ReasonList({items}:{items:(Reason|string)[]}){return items.length?<ul className="reason-list" tabIndex={0}>{items.map((r,i)=><li key={i}>{reasonText(r)}</li>)}</ul>:<Empty>No restrictions or actions recorded.</Empty>}
export function TextAction({children,onClick}:{children:ReactNode;onClick:()=>void}){return <button className="text-action" onClick={onClick}>{children}<ArrowUpRight size={15}/></button>}
export const severityLabel=(v:Severity)=>({LOW:'Low',MEDIUM:'Elevated',HIGH:'High',CRITICAL:'Critical'})[v];
