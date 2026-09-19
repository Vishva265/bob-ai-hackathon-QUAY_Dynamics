"""Intent routing and canonical explanations. Does not persist any system state."""
import re
from datetime import datetime,timezone
from app.copilot.schemas import CopilotInput,CopilotOut,Evidence,SuggestedAction
from app.copilot.provider import explain
from app.repositories.copilot import CopilotTools,identifier
from app.synthetic.simulator import parse,stamp
from app.copilot.retrieval import search

CAUSES={
 'KNOWN_CRANE_DOWNTIME':'Known crane downtime removes productive capacity.',
 'WIND_OR_STORM_REDUCES_PRODUCTIVITY':'Wind or storm restrictions reduce handling productivity.',
 'BERTH_UTILISATION':'Projected berth utilisation exceeds its configured alert threshold.',
 'CRANE_UTILISATION':'Projected crane utilisation exceeds its configured alert threshold.',
 'YARD_OCCUPANCY':'Projected yard occupancy exceeds its configured alert threshold.',
 'PROJECTED_QUEUE':'Scheduled workload exceeds immediately compatible dispatch capacity.',
 'ARRIVAL_SURGE':'Scheduled arrival workload increases rapidly.',
 'LOW_CONFIDENCE':'Forecast uncertainty requires operator review.',
 'TERMINAL_MODEL_PRIOR':'Local resource projections use a shared terminal model probability.',
 'QUEUE_WAIT_USES_ELAPSED_TIME_WITHOUT_VESSEL_MODEL':'Some queue waits use elapsed time because vessel-model evidence is unavailable.',
 'SHIFT_START_RECONCILIATION':'Reconcile ETAs, berths, yard stock and crane calendars before dispatch.',
 'OBSERVED_PROGRESS_PRESERVED':'Observed started operations retain their berth and resource ownership.',
 'REOPTIMISED_REMAINING_HORIZON':'The remaining horizon was reoptimised under the configured objective.',
}


def fmt(value):return 'unavailable' if value is None else f'{value:,.2f}'.rstrip('0').rstrip('.') if isinstance(value,(float,int)) else str(value)


def infer_intent(question: str) -> str:
    text = re.sub(r'([?.!])(?=\w)', r'\1 ', question.casefold())
    if re.search(r'\bignore\b.*\b(?:instructions|rules)\b', text) or re.search(r'^\s*(?:(?:please|can you|could you|would you)\s+)?(?:approve|override|execute|delete|insert|update)\b', text):
        return 'read_only_refusal'
    if re.search(r'\b(?:actual|observed|2021|historical)\b', text) and re.search(r'\b(?:plan|proposed|compare|comparison|difference|versus|vs|waiting|wait|perform|better|improve)\b', text):
        return 'historical_comparison'
    if re.search(r'\b(?:fcfs|baseline|first.come|savings|saved|improvement|benefit)\b', text) or re.search(r'\b(?:optimi[sz]ed|proposed)\b.*\b(?:better|compare|versus|vs)\b', text):
        return 'baseline_comparison'
    if re.search(r'\b(?:how does|how do|how (?:can|to)|explain how|documentation|confidence|limitations|mcp|watsonx|granite|historical replay|upload|rag|what is (?:quay|ais|cp.sat|a forecast|a berth|a crane|fcfs)|meaning|algorithm|technology)\b', text):
        return 'knowledge'
    if re.search(r'\b(?:summari[sz]e|summary|overview|recap)\b', text) and re.search(r'\b(?:72|seventy[- ]two|three days|next\s+3\s+days)\b', text):
        return 'plan_summary'
    if re.search(r'\b(?:next|upcoming|current)\s+shift\b|\bsupervisor\s+shift\b|\bshift\s+(?:summary|handover|plan)\b', text):
        return 'shift_summary'
    if re.search(r'\bshift\b', text):
        return 'shift_summary'
    if re.search(r'\b(?:what (?:happens|if)|if|suppose|eta change)\b', text) and re.search(r'\b(?:late|delay(?:ed)?|arrives?\b.*\b(?:hours?|h)|six hours|6\s*h)\b', text):
        return 'arrival_what_if'
    if re.search(r'\b(?:rerout(?:e|ing)?|routing|diversion|alternate route|alternate routing|alternative route)\b', text):
        return 'routing'
    if re.search(r'\b(?:moved|move|assigned|assignment|reassign(?:ed)?)\b.*\bberth\b|\bwhy\b.*\bberth\b', text):
        return 'assignment'
    if re.search(r'\b(?:when|where|status|details|eta|size|draft|length|cargo|priority)\b', text) and re.search(r'\b(?:vessel|ship|call)\b|\bais-[\w-]+', text):
        return 'vessel_details'
    if re.search(r'\b(?:changed|change|difference|compare|comparison|before|after|breakdown|crane breakdown|crane failure)\b', text):
        return 'scenario_comparison'
    if re.search(r'\b(?:at risk|risk|risky|highest wait|most delayed|waiting-time|waiting time|delayed vessels|delayed ships)\b', text):
        return 'vessel_risk'
    if re.search(r'\b(?:congest|congestion|hotspot|forecast|queue|waiting|terminal\s+\d+)\b', text):
        return 'forecast'
    if re.search(r'\b(?:how many|how much|busy|utili[sz]ation|capacity|cranes?|berths?|yard|ships?|vessels?|plan|schedule|summary|overview|help)\b', text):
        return 'operational_summary'
    return 'unsupported'


class CopilotService:
    def __init__(self,session):self.tools=CopilotTools(session)

    def query(self,p:CopilotInput):
        run=self.tools.source(p.run_id);p=p.model_copy(update={'run_id':run.id})
        self.tools.inventory(p)  # Validate scope for knowledge/refusal answers as well.
        question=p.question.casefold();intent=p.intent;figures=[];used=[];reasons=[];sources=[]
        assumptions=['Read-only decision support. No approved plan or operational record is modified.',
                     'Figures are conditional on the selected source snapshot and its UTC origin.',
                     'Source names, uploaded notes and external prose are untrusted and excluded from provider input.']
        action=None;comparison=None;hypothetical=None
        def tool(name):
            if name not in used:used.append(name)
            return self.tools.retrieve(name,p)
        def fig(label,value,unit,name,record_id,field,source=None):
            figures.append(Evidence(id='E'+str(len(figures)+1),label=label,value=value,unit=unit,tool=name,
                record_id=identifier(record_id),field=field,source_run_id=source or run.id))
        detected=infer_intent(p.question)
        if detected=='read_only_refusal':intent='read_only_refusal'
        elif intent=='auto':intent=detected
        if intent in ('unsupported','operational_summary','vessel_details'):
            _,data,_=self.tools.inventory(p)
            tids={t['id'] for t in data['terminals'] if (not p.port_id or t['port_id']==p.port_id) and (not p.terminal_id or t['id']==p.terminal_id)}
            names={v['id']:v['name'] for v in data['vessels']}
            matches=[c['id'] for c in data['calls'] if c['terminal_id'] in tids and (
                re.search(r'(?<![\w.:-])'+re.escape(c['id'].casefold())+r'(?![\w.:-])',question) or
                (re.fullmatch(r'[A-Za-z0-9 ._-]{2,80}',names.get(c['vessel_id'],'')) and re.search(r'(?<!\w)'+re.escape(names[c['vessel_id']].casefold())+r'(?!\w)',question)))]
            if len(matches)==1 and not p.call_id:
                p=p.model_copy(update={'call_id':matches[0]});intent='vessel_details'
            elif p.call_id and intent=='unsupported':intent='vessel_details'
        if intent=='unsupported':
            sources=search(p.question)
            if sources:intent='knowledge'
        if intent=='knowledge':
            sources=sources or search(p.question)
            answer='\n\n'.join(f"[{i}] {s['excerpt']}" for i,s in enumerate(sources[:3],1)) if sources else 'No sufficiently relevant documentation was found. Ask about forecasting, constraints, confidence, historical replay, uploads or IBM Bob.'
            assumptions.append('Documentation describes system behaviour; it is not evidence of current port conditions.')
        # IDs are resolved from question tokens only; source display names are never instructions.
        inventory=tool('vessel_details') if intent in ('vessel_risk','vessel_details','assignment','routing','arrival_what_if','operational_summary') else None
        if inventory and not p.call_id and intent!='vessel_risk':
            matches=[v['call_id'] for v in inventory['vessels'] if re.search(r'(?<![\w.:-])'+re.escape(v['call_id'].casefold())+r'(?![\w.:-])',question)]
            if len(matches)==1:p=p.model_copy(update={'call_id':matches[0]})
        if intent=='shift_summary':
            match=re.search(r'\bshift\s*(\d+)\b', question)
            if match:
                index=int(match[1])-1
                if 0<=index<=8:p=p.model_copy(update={'shift_index':index})
                else:intent='shift_clarification'
        if intent=='historical_comparison':
            r=tool('historical_comparison')
            if not r['available']:answer='Select the 2021 LA/LB dataset in the plan dropdown to compare observed AIS operations with the proposed plan. Synthetic FCFS results do not represent actual 2021 operations.'
            else:
                s=r['summary']
                answer=f"For the same {s['known_calls']} modelled calls known at cutoff, actual waiting within the 72-hour window is {fmt(s['known_actual_window_wait_hours'])} hours and proposed waiting is {fmt(s['known_proposed_window_wait_hours'])} hours. The proposal assigns {s['proposed_calls']} calls and defers {s['deferred_calls']}; {s['unknown_future_calls']} future calls were unknown at the cutoff. Another {s['excluded_known_calls']} observed calls have unresolved berth identity and are not modelled."
                for key,unit in [('known_actual_window_wait_hours','hours'),('known_proposed_window_wait_hours','hours'),('known_calls','calls'),('proposed_calls','calls'),('deferred_calls','calls'),('unknown_future_calls','calls'),('excluded_known_calls','calls')]:fig(key.replace('_',' ').title(),s[key],unit,'historical_comparison',run.id,'summary.'+key)
                assumptions.append('Actual AIS-derived operations are compared with a calibrated proposal, not the original terminal operating plan. Deferred known calls remain in proposed waiting totals. Unknown arrivals cannot be compared with missing proposals.')
                reasons=['Waiting totals cover identical known calls and the same 72-hour horizon; this does not establish realised operational savings.']
                assumptions.append('Historical comparison totals cover the full LA/LB replay, including when a specific terminal or vessel context is selected.')
        elif intent in ('operational_summary','baseline_comparison'):
            r=tool('optimisation_results');m=r['metrics']
            if intent=='baseline_comparison':
                b=r['baseline']
                if not b:answer='No stored FCFS comparison is available for this run.'
                else:
                    answer=f"FCFS mean served wait is {fmt(b.get('average_wait_hours'))} hours versus {fmt(m.get('average_wait_hours'))} hours proposed. FCFS serves {fmt(b.get('served_vessels'))} and defers {fmt(b.get('deferred_vessels'))}; the proposal serves {fmt(m.get('served_vessels'))} and defers {fmt(m.get('deferred_vessels'))}."
                    for side,values in [('baseline',b),('metrics',m)]:
                        for key in ('average_wait_hours','maximum_wait_hours','served_vessels','deferred_vessels','estimated_cost_usd','estimated_emissions_tonnes_co2'):
                            if key in values:fig(side.title()+' '+key.replace('_',' '),values[key],'hours' if 'wait' in key else 'vessels' if 'vessels' in key else 'USD' if 'usd' in key else 'tonnes CO2','optimisation_results',run.id,side+'.'+key)
                    assumptions.append('FCFS is a simulated baseline, not observed actual operations. Served sets can differ; compare deferrals as well as average waits. Costs and emissions are planning proxies.')
            else:
                berth=fmt(100*m['berth_utilisation'])+'%' if m.get('berth_utilisation') is not None else 'unavailable'
                crane=fmt(100*m['crane_utilisation'])+'%' if m.get('crane_utilisation') is not None else 'unavailable'
                answer=f"Selected plan: {r['plan_status'] or 'unpublished'}; solver {r['solver_status']}. There are {len(inventory['vessels'])} stored calls in the selected scope, including calls outside the planning window. Across the full plan, {fmt(m.get('served_vessels'))} pending vessels are scheduled, {fmt(m.get('fixed_vessels'))} existing operations are preserved and {fmt(m.get('deferred_vessels'))} vessels are deferred; mean served wait is {fmt(m.get('average_wait_hours'))} hours. Berth utilisation is {berth} and crane utilisation is {crane}."
                for key,unit in [('served_vessels','vessels'),('fixed_vessels','vessels'),('deferred_vessels','vessels'),('average_wait_hours','hours'),('maximum_wait_hours','hours'),('berth_utilisation','fraction'),('crane_utilisation','fraction')]:
                    if key in m:fig(key.replace('_',' ').title(),m[key],unit,'optimisation_results',run.id,'metrics.'+key)
                assumptions.append('Aggregate schedule metrics cover the full selected run, even when vessel context is filtered to a terminal or port.')
            reasons=['Feasibility validation passed.' if m.get('validation_passed') else 'The schedule has not passed feasibility validation.']
        elif intent=='vessel_details':
            v=next((v for v in inventory['vessels'] if v['call_id']==p.call_id),None)
            if not v:answer='Select a vessel call or include its exact call ID to inspect its ETA, workload and proposed berth times.'
            else:
                r=tool('optimisation_results');a=next((a for a in r['assignments'] if a['call_id']==p.call_id),None)
                answer=f"{v['call_id']} has scheduled ETA {v['scheduled_eta']} at {v['terminal_id']}, priority {v['priority']}, length {fmt(v['length_m'])}m and draft {fmt(v['draft_m'])}m. Workload: {fmt(v['unload_moves'])} unload and {fmt(v['load_moves'])} load moves."
                if a:answer+=f" Proposed berth {a['berth_id']}, start {a['start']}, completion {a['completion_time']}; planned wait {fmt(a['waiting_minutes']/60)} hours."
                else:answer+=' No certified proposed assignment is stored; this call remains unresolved or deferred.'
                for key,unit in [('scheduled_eta','UTC'),('terminal_id','identifier'),('priority','priority'),('length_m','metres'),('draft_m','metres'),('unload_moves','moves'),('load_moves','moves')]:fig(key.replace('_',' ').title(),v[key],unit,'vessel_details',v['call_id'],key)
        if intent=='forecast':
            if not p.terminal_id:
                _,data,_=self.tools.inventory(p)
                exact=[t['id'] for t in data['terminals'] if re.search(r'(?<![\w.:-])'+re.escape(t['id'].casefold())+r'(?![\w.:-])',question)]
                if len(exact)==1:
                    p=p.model_copy(update={'terminal_id':exact[0]})
                    self.tools.inventory(p)
            if not p.terminal_id:
                match=re.search(r'terminal\s+(\d+)\b',question)
                if match:
                    _,data,_=self.tools.inventory(p)
                    matches=[t['id'] for t in data['terminals'] if t['id'].endswith(f'-T{int(match[1]):02}') and (not p.port_id or t['port_id']==p.port_id)]
                    if len(matches)==1:p=p.model_copy(update={'terminal_id':matches[0]})
                    else:intent='terminal_clarification'
            if intent=='forecast':
                result=tool('forecast_data');rows=result['rows']
                if not rows:answer='No persisted hourly operational forecast exists for this scope. Run the forecast process before asking for a congestion explanation.'
                else:
                    hotspots=[r for r in rows if r['is_hotspot']];row=hotspots[0] if hotspots else max(rows,key=lambda r:r['average_wait_hours'])
                    answer=f"{row['scope_id']} is forecast {row['congestion_severity']} at {row['timestamp']}: projected queue {fmt(row['queue_length'])} vessels and mean wait {fmt(row['average_wait_hours'])} hours."
                    if not hotspots:answer='No hotspot is flagged. '+answer
                    for k,label,unit in [('berth_utilisation','Berth utilisation','fraction'),('queue_length','Projected queue','vessels'),
                        ('average_wait_hours','Projected mean wait','hours'),('yard_occupancy','Yard occupancy','fraction'),
                        ('crane_utilisation','Crane utilisation','fraction'),('congestion_probability','Congestion probability','fraction'),
                        ('arrival_workload_ratio','Arrival workload ratio','ratio'),('arrival_workload_increase_moves','Arrival workload increase','container moves')]:
                        fig(label,row[k],unit,'forecast_data',row['id'],k)
                    reasons=[CAUSES[c] for c in row['cause_codes'] if c in CAUSES][:5]
                    answer+=' '+' '.join(reasons[:3])
                    assumptions.append('Operational utilisation and queue projections are distinct from model congestion probability; these are associations, not a proven causal decomposition.')
                    action=SuggestedAction(text='Inspect compatible capacity and known restrictions; request a constrained operational replan before changing arrivals or assignments.')
        elif intent=='vessel_risk':
            rows=sorted([v for v in inventory['vessels'] if v['prediction'] is not None],key=lambda v:(-v['prediction'],v['call_id']))[:5]
            answer='Highest predicted waits: '+', '.join(f"{r['call_id']} ({fmt(r['prediction'])}h)" for r in rows)+'.' if rows else 'No persisted vessel waiting-time predictions exist for this scope; no model-based risk ranking can be supported.'
            for r in rows:
                for k,label in [('prediction','Predicted wait'),('lower','Uncertainty lower'),('upper','Uncertainty upper')]:fig(r['call_id']+' '+label,r[k],'hours','vessel_details',r['call_id'],k)
            reasons=['Ranking uses stored waiting-time predictions, with uncertainty bounds shown for each vessel.'] if rows else []
            if not rows:
                result=tool('optimisation_results')
                allowed={v['call_id'] for v in inventory['vessels']}
                planned=sorted([a for a in result['assignments'] if a['call_id'] in allowed],key=lambda a:-a['waiting_minutes'])[:5]
                if planned:
                    answer='No trained vessel waiting predictions are attached. Highest stored planned waits: '+', '.join(f"{a['call_id']} ({fmt(a['waiting_minutes']/60)}h)" for a in planned)+f". The full run also has {fmt(result['metrics'].get('deferred_vessels'))} deferred vessels; those have no accepted berth assignment."
                    for a in planned:fig(a['call_id']+' Planned wait',a['waiting_minutes'],'minutes','optimisation_results',a['call_id'],'waiting_minutes')
                    reasons=['This is a schedule-based review order, not a model risk prediction. Inspect deferred calls as well as assigned vessels.']
            action=SuggestedAction(text='Review the highest-risk calls and their compatible capacity; obtain supervisor approval for any arrival or routing change.') if rows else None
        elif intent=='assignment' and p.call_id:
            result=tool('optimisation_results');a=next((a for a in result['assignments'] if a['call_id']==p.call_id),None)
            old=next((a for a in result['baseline_assignments'] if a['call_id']==p.call_id),None)
            changes=[c for c in result['changes'] if c.get('call_id')==p.call_id]
            if not a:answer=f'{p.call_id} has no certified assignment in this run; check unresolved allocation conflicts.'
            else:
                answer=f"{p.call_id} is assigned to {a['berth_id']}, starting {stamp(parse(a['start']))}, completing {stamp(parse(a['completion_time']))}."
                if changes:
                    reasons=[CAUSES.get(c.get('reason_code'),'A material change is recorded; inspect the published plan change details.') for c in changes]
                elif old and old['berth_id']!=a['berth_id']:
                    answer+=f" FCFS used {old['berth_id']}; this is a baseline comparison, not proof of a change to an approved plan."
                else:answer+=' No material approved-plan reassignment reason is recorded for this call.'
                reasons+=['The certified schedule respects berth compatibility, tide, crane calendars and safe yard capacity.' if result['metrics'].get('validation_passed') else 'This run is not feasibility-validated; recorded allocations must not be treated as executable.',
                          'The configured objective balances waiting, priority delay, resource pressure and reassignment; a solver-specific marginal causal attribution is unavailable.']
                for k,label,unit in [('berth_id','Assigned berth','identifier'),('waiting_minutes','Planned wait','minutes'),('planned_moves','Remaining moves','container moves')]:fig(label,a[k],unit,'optimisation_results',p.call_id,k)
                v=next(v for v in inventory['vessels'] if v['call_id']==p.call_id)
                for k in ('length_m','draft_m'):fig(k.replace('_',' '),v[k],'metres','vessel_details',p.call_id,k)
                named=re.search(r'\bberth\s+([a-z0-9_.:-]+)',question)
                if named and named[1].upper() not in (a['berth_id'].upper(),a['berth_id'].split('-')[-1].upper()):answer+=' The berth in your question does not match the stored assignment.'
        elif intent=='routing' and p.call_id:
            result=tool('recommendations');r=next((r for r in result['decisions'] if r['call_id']==p.call_id),None)
            if not r:answer='No audited routing comparison exists for this call and source run. Supply voyage/customer inputs and run the responsible-routing comparison first.'
            else:
                answer=f"The audited action for {p.call_id} is {r['action'].replace('_',' ')}."
                if r['expired']:answer+=' This historical recommendation has expired and is not actionable.'
                for k,label,unit in [('expected_hours_saved','End-to-end hours saved','hours'),('estimated_cost_change_usd','Estimated cost change','USD'),('estimated_emissions_change_tonnes','Emissions proxy change','tonnes CO2')]:fig(label,r[k],unit,'recommendations',result['recommendation_run_id'],k)
                rejection=sorted({c for o in r['options'] for c in o['rejection_codes']})
                reasons=['Hard compatibility and receiving capacity are evaluated before the end-to-end benefit threshold.',
                         'Recorded rejection gates: '+', '.join(c.replace('_',' ') for c in rejection)] if rejection else ['The audited result passed the engine eligibility gates; proposals remain conditional and unreserved.']
                if rejection:answer+=' Recorded alternative rejection gates: '+', '.join(c.replace('_',' ') for c in rejection[:6])+'.'
                assumptions.append('Voyage, inland transport, deadlines, costs and emissions are explicit scenario inputs/proxies; receiving capacity is unreserved.')
                action=SuggestedAction(text='Refresh voyage and customer inputs, recompute receiving capacity and jointly replan; obtain supervisor approval before any diversion or arrival change.')
        elif intent=='plan_summary':
            result=tool('optimisation_results')
            shifts=[self.tools.shift_plans(p.model_copy(update={'shift_index':i})) for i in range(9)]
            if 'shift_plans' not in used:used.append('shift_plans')
            available=[s for s in shifts if s['available']]
            if not available:
                answer='No persisted detailed 72-hour supervisor publication exists. Generate a supervisor plan first.'
            else:
                answer=f"The 72-hour publication contains {len(available)} eight-hour shifts from {available[0]['start']} to {available[-1]['end']}. Plan state {result['plan_status']}; solver status {result['solver_status']}."
                for s in available:
                    answer+=f" Shift {s['shift_index']+1}: {fmt(s['planned_container_moves'])} planned container moves, {s['alert_count']} alerts and {s['handoff_count']} high-risk handoffs."
                    fig(f"Shift {s['shift_index']+1} planned moves",s['planned_container_moves'],'container moves','shift_plans',s['plan_id'],'planned_container_moves')
                    figures[-1]=figures[-1].model_copy(update={'shift_index':s['shift_index']})
                reasons=['Counts use the selected scope; shared restrictions and alerts cover the publication.']
                action=SuggestedAction(text='Review all shift restrictions and handoffs; obtain supervisor approval before dispatching a draft or changed plan.')
        elif intent=='shift_summary':
            r=tool('shift_plans')
            if not r['available']:answer='No persisted detailed shift publication exists. Generate a supervisor plan first.'
            else:
                answer=f"Shift {r['shift_index']+1} ({r['scope']}), {r['start']} to {r['end']}: {r['counts']['incoming']} incoming, {r['counts']['waiting']} waiting, {r['counts']['berthing']} berthing and {r['counts']['departing']} departing vessels; {fmt(r['planned_container_moves'])} planned moves. Plan state {r['status']}, revision {r['revision']}."
                for k,v in r['counts'].items():fig(k.title()+' vessels',v,'vessels','shift_plans',r['plan_id'],'counts.'+k)
                fig('Planned container moves',r['planned_container_moves'],'container moves','shift_plans',r['plan_id'],'planned_container_moves')
                fig('Congestion alerts',r['alert_count'],'alerts','shift_plans',r['plan_id'],'alert_count')
                fig('High-risk handoffs',r['handoff_count'],'handoffs','shift_plans',r['plan_id'],'handoff_count')
                reasons=[CAUSES[c] for c in r['action_codes'] if c in CAUSES]
                assumptions.append('Vessel counts and moves use the requested port/terminal scope, including vessels continuing across shifts; action codes, alerts and equipment restrictions cover the full publication.')
                action=SuggestedAction(text='Reconcile actual conditions, review shift restrictions and handoffs; supervisor review and approval are required before dispatching a draft or changed plan.')
        elif intent in ('scenario_comparison','arrival_what_if'):
            if intent=='arrival_what_if':
                delay=p.arrival_delay_hours
                if delay is None:
                    match=re.search(r'(\d+(?:\.\d+)?)\s*(?:hours?|h)\b',question)
                    delay=float(match[1]) if match else 6 if 'six hours' in question else None
                if not p.call_id or delay is None:
                    intent='arrival_clarification';answer='Select a vessel call and specify a positive delay in hours for a constrained arrival what-if.'
                else:p=CopilotInput.model_validate(dict(p.model_dump(),arrival_delay_hours=delay))
            if intent in ('scenario_comparison','arrival_what_if'):
                r=tool('scenario_comparisons')
                if not r.get('available',True):answer='Select a before run with the same UTC origin and port scope. FCFS versus optimised results under identical breakdown conditions do not establish what changed after the breakdown.'
                else:
                    comparison=r['before_run_id'];hypothetical=r.get('hypothetical_run_id')
                    answer=f"Mean served wait changes from {fmt(r['before']['average_wait_hours'])} to {fmt(r['after']['average_wait_hours'])} hours; deferred vessels from {fmt(r['before']['deferred_vessels'])} to {fmt(r['after']['deferred_vessels'])}."
                    for side,source in [('before',comparison),('after',hypothetical or run.id)]:
                        for k,label,unit in [('average_wait_hours','Mean served wait','hours'),('maximum_wait_hours','Maximum wait','hours'),('deferred_vessels','Deferred vessels','vessels'),('estimated_cost_usd','Planning cost','USD'),('estimated_emissions_tonnes_co2','Emissions proxy','tonnes CO2')]:fig(side.title()+' '+label,r[side].get(k),unit,'scenario_comparisons',source,side+'.'+k,source)
                    assumptions.append('Mean waits may cover different served sets. Compare deferrals and cost proxies; changes are not automatically attributable to one disruption.')
                    if hypothetical:
                        answer=f"A hypothetical ETA change from {r['original_eta']} to {r['changed_eta']} was solved {r['solver_status']} against a freshly solved matched baseline, without saving either schedule. "+answer
                        a=r['call_assignment'];answer+=f" This vessel's hypothetical berth is {a['berth_id']}, starting {a['start']}." if a else ' The vessel has no accepted hypothetical assignment.'
                        assumptions+=['What-if uses current observed resources/approved commitments and source scenario conditions; source model priors are reused, not retrained for the changed ETA.',
                                      'All approved reservations are retained. A delayed approved or started call cannot be changed by this tool. Solver has a two-second solve limit plus preprocessing.']
                        if not r['after'].get('validation_passed') or not r['before'].get('validation_passed'):
                            answer+=' At least one comparison schedule is not feasibility-validated; treat it as an unresolved hypothetical, not an executable plan.'
                        reasons=['Recorded solver conflict: '+c.replace('_',' ') for c in r['conflict_codes']]
                        action=SuggestedAction(text='Inspect this hypothetical comparison; use the operational replan workflow with fresh observations and human approval before changing the vessel ETA or schedule.')
        if intent=='terminal_clarification':answer='Terminal 2 exists in multiple ports. Select its port or exact terminal ID before requesting an explanation.'
        elif intent=='shift_clarification':answer='The plan contains shifts 1 through 9. Choose one of those shifts for its handover details.'
        elif intent in ('assignment','routing') and not p.call_id:answer='Select a vessel call or include its exact call ID so the answer can cite the stored result.'
        elif intent=='read_only_refusal':answer='The copilot cannot approve, execute or override operations. It can explain trusted forecasts, schedules and comparisons; use the audited supervisor workflow for operational decisions.'
        elif intent=='unsupported':answer='I could not find evidence for this question in the selected plan or project documentation. I can answer ordinary questions about vessel ETAs, crane and berth utilisation, waiting, shifts, FCFS savings, the 2021 actual-versus-proposed comparison and how QUAY works. Include a vessel call ID or select context for a specific vessel.'
        confidence='LOW' if run.forecast.model_version else 'UNAVAILABLE'
        assumptions.append('Synthetic-trained forecasts have LOW operational confidence.' if run.forecast.model_version else 'No trained model version is attached; only stored planning/baseline evidence is available.')
        # Refusals remain deterministic; no provider can reinterpret an operational command.
        provider=explain(intent,p.question,answer,figures,reasons,assumptions) if intent not in ('read_only_refusal','knowledge') else None
        final_answer=provider.answer if provider else answer
        return CopilotOut(direct_answer=final_answer,answer=final_answer,question=p.question,
            supporting_figures=provider.evidence if provider else figures,data_timestamp=parse(run.as_of),generated_at=datetime.now(timezone.utc),
            optimisation_run_id=run.id,forecast_run_id=run.forecast_run_id,model_version=run.forecast.model_version,
            comparison_run_id=comparison,hypothetical_run_id=hypothetical,confidence=confidence,assumptions=assumptions,
            suggested_action=action,reasons=reasons,tools_used=used,mode=provider.provider if provider else 'template',
            provider=provider.provider if provider else 'template',model=provider.model if provider else None,
            provider_status=provider.status if provider else 'not_needed',intent=intent,knowledge_sources=sources)
