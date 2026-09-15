import type {Dashboard,Forecast,Metrics,Severity} from './types';
export const LEVELS:Severity[]=['LOW','MEDIUM','HIGH','CRITICAL'];
export const number=(v:number|null|undefined,digits=1)=>v==null||!Number.isFinite(v)?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:digits}).format(v);
export const money=(v:number|null|undefined)=>v==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(v);
export const utc=(v:string,full=false)=>new Intl.DateTimeFormat('en-GB',{timeZone:'UTC',day:full?'2-digit':undefined,month:full?'short':undefined,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(v));
export const hours=(v:string,origin:string)=>(Date.parse(v)-Date.parse(origin))/3600000;
export const mean=(rows:number[])=>rows.length?rows.reduce((a,b)=>a+b,0)/rows.length:null;
export function worst(rows:Forecast[]):Severity|null{return rows.length?LEVELS[Math.max(...rows.map(r=>LEVELS.indexOf(r.congestion_severity)))]:null}
export function callName(data:Dashboard,id:string){const c=data.inventory.calls.find(c=>c.id===id);return data.inventory.vessels.find(v=>v.id===c?.vessel_id)?.name||id}
export function portOf(data:Dashboard,terminalId:string){return data.inventory.terminals.find(t=>t.id===terminalId)?.port_id}
export function queueHours(m:Metrics){return m.demand_average_wait_proxy_hours*(m.served_vessels+m.deferred_vessels)}
export function currentRows(data:Dashboard,port:string){return data.forecast_rows.filter(r=>r.scope==='port'&&r.timestamp===data.run.as_of&&(port==='all'||r.port_id===port))}
export function outlook(data:Dashboard,port:string){const grouped=new Map<string,Forecast[]>();data.forecast_rows.filter(r=>r.scope==='port'&&(port==='all'||r.port_id===port)).forEach(r=>grouped.set(r.timestamp,[...(grouped.get(r.timestamp)||[]),r]));return [...grouped].map(([timestamp,rows])=>({timestamp,probability:(mean(rows.map(r=>r.congestion_probability))||0)*100,wait:mean(rows.map(r=>r.average_wait_hours))}));}
