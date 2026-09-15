"""Portable JSON, comprehensive CSV, and standalone browser-printable HTML."""
import csv
import html
import io
import json
from app.schemas import PlanOut


def csv_cell(value):
    if value is None:
        return ''
    if isinstance(value,(list,dict)):
        return json.dumps(value, separators=(',',':'),ensure_ascii=False)
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r')):
        return "'"+value
    return value


def rows(plan):
    yield dict(row_type='PLAN', data={k:v for k,v in plan.items() if k != 'shifts'})
    for key, category in [('changes_compared_with_approved_plan','MATERIAL_CHANGE'), ('unresolved_conflicts','CONFLICT'), ('assumptions','ASSUMPTION')]:
        for item in (plan.get('document') or {}).get(key,[]):
            yield dict(row_type=category, data=item)
    for shift in plan['shifts']:
        common = dict(shift_index=shift['shift_index'], shift_start=shift['start'], shift_end=shift['end'])
        d = shift['details'] or {}
        yield dict(common,row_type='SHIFT_SUMMARY', planned_moves=d.get('planned_container_moves'), confidence=d.get('confidence'),data={'assumptions':d.get('assumptions',[])})
        for key,category in [('incoming','INCOMING'),('waiting','WAITING'),('berthing','BERTHING'),('departing','DEPARTING'),
            ('berth_assignments','BERTH_ASSIGNMENT'),('crane_allocation','CRANE_ALLOCATION'), ('projected_yard_occupancy','YARD_PROJECTION'),
            ('weather_constraints','WEATHER_CONSTRAINT'),('tide_constraints','TIDE_CONSTRAINT'),('maintenance_and_equipment_restrictions','EQUIPMENT_RESTRICTION'),
            ('high_risk_handoffs','HIGH_RISK_HANDOFF'),('congestion_alerts','ALERT'),('required_supervisor_actions','SUPERVISOR_ACTION'),
            ('plan_changes_requiring_approval','PENDING_CHANGE'),('approved_diversions_or_arrival_changes','APPROVED_CHANGE'),('contingency_actions','CONTINGENCY'),('handover_notes','HANDOVER')]:
            for item in d.get(key,[]):
                fields = {k:item.get(k) for k in ('call_id','vessel_name','port_id','terminal_id','berth_id','start','completion_time','departure','crane_ids')} if isinstance(item,dict) else {}
                yield dict(common, row_type=category, **fields, data=item)
        for task in shift['tasks']:
            yield dict(common,row_type='CRANE_SEGMENT' if task['task_type']=='container_handling' else 'WAIT_TASK',
                call_id=task['call_id'],berth_id=task['berth_id'],crane_ids=task['crane_ids'],start=task['start'],
                completion_time=task['end'],planned_moves=task['planned_moves'],data=task)


def csv_export(plan):
    stream=io.StringIO(newline='')
    columns=['row_type','shift_index','shift_start','shift_end','call_id','vessel_name','port_id','terminal_id','berth_id',
        'crane_ids','start','completion_time','departure','planned_moves','confidence','data']
    writer=csv.DictWriter(stream,fieldnames=columns)
    writer.writeheader()
    for row in rows(plan):
        writer.writerow({k:csv_cell(v) for k,v in row.items()})
    return stream.getvalue().encode('utf-8-sig')


def printable(plan):
    escape=lambda value:html.escape(str(value if value is not None else 'Unresolved'))
    def table(items, fields):
        if not items:
            return '<p>None recorded.</p>'
        return '<table><thead><tr>'+''.join('<th>'+escape(label)+'</th>' for key,label in fields)+'</tr></thead><tbody>'+''.join(
            '<tr>'+''.join('<td>'+escape(item.get(key))+'</td>' for key,label in fields)+'</tr>' for item in items)+'</tbody></table>'
    doc=plan.get('document') or {}
    content=['<h1>72-hour port operations plan</h1>', '<p>Plan '+escape(plan['id'])+' · '+escape(plan['status'])+' · Revision '+str(plan['revision'])+'</p>',
        '<p>All times UTC. Forecast confidence: '+escape(doc.get('confidence'))+'. Source as-of: '+escape(doc.get('as_of'))+'.</p>',
        '<p>Reconcile current observations before dispatch. This publication does not override safety limits or operator approvals.</p>',
        '<h2>Material changes and conflicts</h2>',table(doc.get('changes_compared_with_approved_plan',[]),[('call_id','Vessel call'),('changed_fields','Changes'),('reason','Reason')]),
        table(doc.get('unresolved_conflicts',[]),[('call_id','Vessel call'),('code','Conflict'),('message','Operator attention')]),
        '<h2>Assumptions and confidence</h2><ul>'+''.join('<li>'+escape(a)+'</li>' for a in doc.get('assumptions',[]))+'</ul>']
    for shift in plan['shifts']:
        d=shift['details'] or {}
        content.extend(['<section><h2>Shift '+str(shift['shift_index']+1)+' · '+escape(shift['start'])+' → '+escape(shift['end'])+'</h2>',
            '<p>Planned moves: '+escape(round(d.get('planned_container_moves',0),2))+' · Confidence '+escape(d.get('confidence'))+'</p>'])
        for key,label in [('incoming','Incoming'),('waiting','Waiting'),('berthing','Berthing'),('departing','Departing')]:
            content.append('<h3>'+label+'</h3>'+table(d.get(key,[]),[('call_id','Call'),('vessel_name','Vessel'),('terminal_id','Terminal'),('scheduled_eta','ETA UTC')]))
        content.extend(['<h3>Berth assignments</h3>'+table(d.get('berth_assignments',[]),[('call_id','Call'),('berth_id','Berth'),('original_started_at','Actual start'),('start','Planned start'),('completion_time','Completion UTC'),('departure','Departure UTC'),('planned_moves_in_shift','Moves this shift')]),
            '<h3>Crane allocation and effective productivity</h3>'+table(d.get('crane_allocation',[]),[('call_id','Call'),('crane_hours','Crane-hours'),('planned_moves','Moves'),('expected_moves_per_crane_hour','Moves/crane-hour')]),
            table(shift['tasks'],[('call_id','Call'),('crane_ids','Cranes'),('start','Start UTC'),('end','End UTC'),('planned_moves','Moves'),('task_type','Activity')]),
            '<h3>Projected yard occupancy</h3>'+table(d.get('projected_yard_occupancy',[]),[('terminal_id','Terminal'),('opening_teu','Opening TEU'),('closing_teu','Closing TEU'),('peak_teu','Peak TEU'),('capacity_teu','Capacity TEU'),('peak_occupancy_fraction','Peak fraction')])])
        for key,label in [('weather_constraints','Weather'),('tide_constraints','Tide'),('maintenance_and_equipment_restrictions','Equipment restrictions'),
            ('high_risk_handoffs','High-risk handoffs'),('congestion_alerts','Congestion alerts'),('required_supervisor_actions','Supervisor actions'),
            ('plan_changes_requiring_approval','Changes requiring approval'),('approved_diversions_or_arrival_changes','Approved vessel changes'),('contingency_actions','Contingencies'),('handover_notes','Handover'),('assumptions','Shift assumptions')]:
            content.append('<h3>'+label+'</h3><ul>'+''.join('<li>'+escape(json.dumps(a,ensure_ascii=False) if isinstance(a,dict) else a)+'</li>' for a in d.get(key,[]))+'</ul>')
        content.append('</section>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>72-hour operations plan</title><style>'
        'body{font:12px Arial,sans-serif;color:#15212e;margin:24px}h1,h2,h3{color:#164966}table{border-collapse:collapse;width:100%;margin:8px 0}'
        'th,td{border:1px solid #bac8d1;padding:5px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#eaf1f5}'
        'li{margin:5px 0;overflow-wrap:anywhere}section{margin-top:28px}@page{size:A4 landscape;margin:12mm}'
        '@media print{section{break-before:page}thead{display:table-header-group}tr{break-inside:avoid}h2,h3{break-after:avoid}}'
        '</style></head><body>'+''.join(content)+'</body></html>').encode('utf-8')


def export(plan, format):
    value=PlanOut.model_validate(plan).model_dump(mode='json')
    if format=='json':
        return json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False).encode('utf-8'),'application/json'
    if format=='csv':
        return csv_export(value),'text/csv; charset=utf-8'
    if format=='html':
        return printable(value),'text/html; charset=utf-8'
    raise ValueError('Unsupported export format')
