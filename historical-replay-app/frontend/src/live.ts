import {useCallback,useEffect,useRef,useState} from 'react';
import {API_BASE,requestControl} from './api';
export type DemoSession={id:string;port_id:string;clock:string;revision:number;status:string;latest_run_id:string;initial_run_id:string;active_event_id:string|null;settings:Record<string,unknown>};
export type DemoEvent={id:string;session_id:string;sequence:number;kind:string;status:string;stage_revision:number;operational_time:string;payload:Record<string,unknown>;result:DemoResult|null;error:{code:string;message:string}|null};
export type DemoResult={new_run_id:string;old_run_id:string;new_plan_id:string;plan_status:string;schedule_status:string;solver_status:string;approval_required:boolean;
  forecast_runtime_ms:number;optimisation_runtime_ms:number;solver_runtime_ms:number;plan_change_count:number;ongoing_operation_count:number;frozen_assignment_count:number;
  forecast_run_id:string;model_version:string;event_effect:{storm_start?:string;storm_end?:string;warning_lead_hours?:number;crane_ids?:string[]};
  metrics:{waiting_hours_avoided:number|null;cost_improvement_usd:number|null;emissions_improvement_tonnes_co2:number|null;congestion_reduction_vessel_hours:number|null;deferred_vessels:number;certified:boolean};
  plan_changes:{call_id:string;changed_fields:string[];before:{berth_id:string;start:string}|null;after:{berth_id:string;start:string}|null;reason:{message:string}}[];
  changed_risks:{scope:string;scope_id:string;old_severity:string;new_severity:string;old_peak_queue:number;new_peak_queue:number;old_peak_wait_hours:number;new_peak_wait_hours:number;added_cause_codes:string[]}[];
  unresolved_conflicts:{code:string;message:string}[];assumptions:string[]};

export function useLiveDemo(id:string|null,onResult:(run:string)=>void){
  const [session,setSession]=useState<DemoSession|null>(null),[events,setEvents]=useState<DemoEvent[]>([]),[connection,setConnection]=useState('Offline'),[error,setError]=useState<string|null>(null),[pending,setPending]=useState(false);
  const callback=useRef(onResult);callback.current=onResult;const handled=useRef(new Set<string>());
  useEffect(()=>{
    setSession(null);setEvents([]);setError(null);handled.current.clear();if(!id){setConnection('Offline');return}
    let disposed=false,connected=false;const abort=new AbortController();
    function receive(event:DemoEvent){if(disposed)return;setEvents(old=>{const current=old.find(e=>e.id===event.id);if(current&&current.stage_revision>event.stage_revision)return old;return [event,...old.filter(e=>e.id!==event.id)].sort((a,b)=>b.sequence-a.sequence).slice(0,50)});
      if(event.status==='SUCCEEDED'&&event.result&&!handled.current.has(event.id)){handled.current.add(event.id);callback.current(event.result.new_run_id)}
      if(event.status==='FAILED')setError(event.error?.message||'Event failed; inspect the persisted record and retry.');}
    async function refresh(initial=false){try{
      const [state,history]=await Promise.all([requestControl<DemoSession>(`/live-demo/${id}`,undefined,abort.signal),requestControl<{items:DemoEvent[]}>(`/live-demo/${id}/events`,undefined,abort.signal)]);
      if(disposed)return;setSession(state);if(initial){history.items.filter(e=>e.status==='SUCCEEDED').forEach(e=>handled.current.add(e.id));setEvents(history.items)}else history.items.slice().reverse().forEach(receive);
    }catch(e){if(!disposed)setError(e instanceof Error?e.message:'Unable to load live session')}}
    refresh(true);setConnection('Connecting SSE');
    const stream=typeof EventSource==='undefined'?null:new EventSource(`${API_BASE}/live-demo/${id}/stream`);
    if(stream){stream.onopen=()=>{connected=true;if(!disposed)setConnection('SSE connected')};stream.onerror=()=>{connected=false;if(!disposed)setConnection('Reconnecting SSE; polling backup')};
      stream.addEventListener('session',event=>{if(!disposed)setSession(JSON.parse((event as MessageEvent).data))});
      stream.addEventListener('operation',event=>receive(JSON.parse((event as MessageEvent).data)));}
    const timer=setInterval(()=>{if(!connected)refresh()},3000);
    return()=>{disposed=true;abort.abort();stream?.close();clearInterval(timer)};
  },[id]);
  const inject=useCallback(async(body:Record<string,unknown>)=>{
    if(!id||!session||pending||session.status!=='READY')return;setPending(true);setError(null);
    try{const event=await requestControl<DemoEvent>(`/live-demo/${id}/events`,{...body,expected_revision:session.revision});setEvents(old=>[event,...old]);
      const state=await requestControl<DemoSession>(`/live-demo/${id}`);setSession(state);
    }catch(e){setError(e instanceof Error?e.message:'Event injection failed')}finally{setPending(false)}
  },[id,session,pending]);
  const retry=useCallback(async(event:DemoEvent)=>{
    if(!id||!session)return;setPending(true);setError(null);try{await requestControl(`/live-demo/${id}/events/${event.id}/retry`,{actor:'Demo operator',expected_revision:session.revision});setSession(await requestControl(`/live-demo/${id}`))}catch(e){setError(e instanceof Error?e.message:'Retry failed')}finally{setPending(false)}
  },[id,session]);
  return {session,events,connection,error,pending,inject,retry};
}
export type LiveState=ReturnType<typeof useLiveDemo>;
