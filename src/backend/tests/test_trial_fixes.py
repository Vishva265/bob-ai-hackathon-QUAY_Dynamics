import csv
from datetime import timedelta

import pytest

from app.historical_replay.config import CUTOFF, iso
from app.historical_replay.replay import vessel_comparison
from app.services.copilot import infer_intent
from test_operations_api import api, source
from test_copilot import run, query, snapshot, offline_explanations


@pytest.mark.parametrize('question,intent', [
    ('How busy are the cranes?', 'operational_summary'),
    ('How many ships can we handle?', 'operational_summary'),
    ('Show the current yard utilisation', 'operational_summary'),
    ('What is the current queue?', 'forecast'),
    ('Tell me about the technology behind this app', 'knowledge'),
    ('When will this ship finish?', 'vessel_details'),
    ('Show shift 4 handover', 'shift_summary'),
    ('Is the optimized plan better than FCFS?', 'baseline_comparison'),
    ('Compare actual 2021 waiting with the proposed plan', 'historical_comparison'),
    ('How do I approve a plan?', 'knowledge'),
    ('Please approve this plan', 'read_only_refusal'),
    ('Which ships are most delayed?', 'vessel_risk'),
])
def test_natural_question_routing(question, intent):
    assert infer_intent(question) == intent


def test_free_form_answers_are_grounded_and_do_not_modify_data(api, run):
    before = snapshot(api)
    summary = query(api, run, 'How busy are the cranes?')
    assert summary['intent'] == 'operational_summary'
    assert summary['supporting_figures']
    for figure in summary['supporting_figures']:
        assert figure['value'] == run['metrics'][figure['field'].split('.')[1]]
    baseline = query(api, run, 'Is our plan better than FCFS?')
    assert baseline['intent'] == 'baseline_comparison'
    assert 'defers' in baseline['answer']
    call_id = run['assignments'][0]['call_id']
    vessel = query(api, run, f'When will vessel {call_id} finish?')
    assert vessel['intent'] == 'vessel_details'
    assert 'Proposed berth' in vessel['answer']
    assert query(api, run, 'Show shift 4 handover')['answer'].startswith('Shift 4')
    assert 'shifts 1 through 9' in query(api, run, 'Show shift 15')['answer']
    assert '2021 LA/LB dataset' in query(api, run, 'Compare actual 2021 waiting with proposed plan')['answer']
    assert snapshot(api) == before


def test_historical_comparison_retains_deferred_and_unknown_calls(tmp_path):
    def write(name, fields, data):
        with (tmp_path/name).open('w', newline='', encoding='utf-8') as handle:
            writer=csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader();writer.writerows(data)
    write('vessel_calls.csv', ['id','vessel_id'], [dict(id='served',vessel_id='v1'),dict(id='deferred',vessel_id='v2'),dict(id='future',vessel_id='v3')])
    write('vessels.csv', ['id','name'], [dict(id='v1',name='One'),dict(id='v2',name='Two'),dict(id='v3',name='Three')])
    fields=['call_id','actual_arrival','berth_start','departure','waiting_hours','terminal_id']
    write('actual_outcomes.csv', fields, [
        dict(call_id='served',actual_arrival=iso(CUTOFF-timedelta(hours=10)),berth_start=iso(CUTOFF+timedelta(hours=4)),departure='',waiting_hours=14,terminal_id='LA_APM'),
        dict(call_id='deferred',actual_arrival=iso(CUTOFF-timedelta(hours=5)),berth_start='',departure='',waiting_hours='',terminal_id='LA_APM'),
        dict(call_id='future',actual_arrival=iso(CUTOFF+timedelta(hours=3)),berth_start='',departure='',waiting_hours='',terminal_id='LA_APM'),
    ])
    plan=dict(assignments=[dict(call_id='served',berth_id='LA_APM-B1',start=iso(CUTOFF+timedelta(hours=2)),end=iso(CUTOFF+timedelta(hours=8)),waiting_minutes=720)], diagnostics=dict(unscheduled_call_ids=['deferred']))
    compared={r['call_id']:r for r in vessel_comparison(tmp_path,plan)}
    assert compared['served']['actual_window_wait_hours']==4
    assert compared['served']['proposed_window_wait_hours']==2
    assert compared['served']['window_wait_change_hours']==-2
    assert compared['deferred']['status']=='DEFERRED'
    assert compared['deferred']['proposed_window_wait_hours']==72
    assert compared['deferred']['actual_wait_censored']
    assert compared['future']['status']=='UNKNOWN_AT_CUTOFF'
    assert compared['future']['proposed_window_wait_hours'] is None
