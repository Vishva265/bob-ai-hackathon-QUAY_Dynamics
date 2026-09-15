"""Intent routing and canonical explanations. Does not persist any system state."""
import re
from datetime import datetime,timezone
from app.copilot.schemas import CopilotInput,CopilotOut,Evidence,SuggestedAction
from app.copilot.provider import explain
from app.repositories.copilot import CopilotTools,identifier
from app.synthetic.simulator import parse,stamp

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


def fmt(value):return f'{value:,.2f}'.rstrip('0').rstrip('.') if isinstance(value,(float,int)) else str(value)


class CopilotService:
    def __init__(self,session):self.tools=CopilotTools(session)

    def query(self,p:CopilotInput):
        run=self.tools.source(p.run_id);p=p.model_copy(update={'run_id':run.id})
        question=p.question.casefold();intent=p.intent;figures=[];used=[];reasons=[]
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
        if re.search(r'\b(approve|override|execute|delete|insert|update|ignore)\b',question):intent='read_only_refusal'
        if intent=='auto':
            if re.search(r'late|six hours|arrives? .*hours?',question):intent='arrival_what_if'
            elif re.search(r'rerout|routing|diversion|recommend.*reject',question):intent='routing'
            elif re.search(r'moved|reassign|why.*berth',question):intent='assignment'
            elif re.search(r'changed|after.*breakdown|comparison',question):intent='scenario_comparison'
            elif re.search(r'summari[sz]e.*(?:72|next three days)',question):intent='plan_summary'
            elif re.search(r'next shift|supervisor|summari[sz]e.*shift',question):intent='shift_summary'
            elif re.search(r'at risk|most.*risk|risky',question):intent='vessel_risk'
            elif re.search(r'congest|hotspot|forecast',question):intent='forecast'
            else:intent='unsupported'
        # IDs are resolved from question tokens only; source display names are never instructions.
        inventory=tool('vessel_details') if intent in ('vessel_risk','assignment','routing','arrival_what_if') else None
        if inventory and not p.call_id and intent!='vessel_risk':
            matches=[v['call_id'] for v in inventory['vessels'] if re.search(r'(?<![\w.:-])'+re.escape(v['call_id'].casefold())+r'(?![\w.:-])',question)]
            if len(matches)==1:p=p.model_copy(update={'call_id':matches[0]})
        if intent=='forecast':
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
        elif intent in ('assignment','routing') and not p.call_id:answer='Select a vessel call or include its exact call ID so the answer can cite the stored result.'
        elif intent=='read_only_refusal':answer='The copilot cannot approve, execute or override operations. It can explain trusted forecasts, schedules and comparisons; use the audited supervisor workflow for operational decisions.'
        elif intent=='unsupported':answer='Ask about congestion, vessel risk, berth assignment, breakdown comparison, a late-arrival what-if, routing, or the next supervisor shift. I cannot support this question with the six trusted tools.'
        confidence='LOW' if run.forecast.model_version else 'UNAVAILABLE'
        assumptions.append('Synthetic-trained forecasts have LOW operational confidence.' if run.forecast.model_version else 'No trained model version is attached; only stored planning/baseline evidence is available.')
        # Refusals remain deterministic; no provider can reinterpret an operational command.
        provider=explain(intent,p.question,answer,figures,reasons,assumptions) if intent!='read_only_refusal' else None
        final_answer=provider.answer if provider else answer
        return CopilotOut(direct_answer=final_answer,answer=final_answer,question=p.question,
            supporting_figures=provider.evidence if provider else figures,data_timestamp=parse(run.as_of),generated_at=datetime.now(timezone.utc),
            optimisation_run_id=run.id,forecast_run_id=run.forecast_run_id,model_version=run.forecast.model_version,
            comparison_run_id=comparison,hypothetical_run_id=hypothetical,confidence=confidence,assumptions=assumptions,
            suggested_action=action,reasons=reasons,tools_used=used,mode=provider.provider if provider else 'template',
            provider=provider.provider if provider else 'template',model=provider.model if provider else None,
            provider_status=provider.status if provider else 'not_needed',intent=intent)
