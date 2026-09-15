"""Compatibility facade for executable optimisation and productive-slot readers."""
import math
from datetime import timedelta


from app.synthetic.simulator import parse

SLOT_MINUTES = 15
SLOTS = 288
COMPLETION_SLOTS = 480  # 72-hour arrival selection plus a 48-hour reservation tail.


def slot(value, as_of, ceil=False):
    number = (parse(value)-as_of).total_seconds()/900
    return math.ceil(number) if ceil else math.floor(number)


def merged(intervals):
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def productive_slots(data, assignment):
    """Executable profiles expose only productive slots, excluding outage pauses."""
    if assignment.get('execution_profile'):
        return assignment['execution_profile']['productive_slots']
    as_of = parse(data['as_of'])
    begin, end = parse(assignment['start']), parse(assignment['end'])
    carried = assignment['call_id'] in {c['call_id'] for c in data['carry_in']}
    berth = next(b for b in data['berths'] if b['id'] == assignment['berth_id'])
    pid = next(t['port_id'] for t in data['terminals'] if t['id'] == berth['terminal_id'])
    slots = []
    for i in range(COMPLETION_SLOTS):
        tick = as_of+timedelta(minutes=i*15)
        if not begin <= tick < end:
            continue
        paused = carried and (
            any(a['crane_id'] in assignment['crane_ids'] and parse(a['start']) <= tick < parse(a['end']) for a in data['availability'])
            or any(e['kind'] == 'storm' and e['port_id'] == pid and parse(e['start']) <= tick < parse(e['end']) for e in data['disruptions']))
        if not paused:
            slots.append(i)
    return slots


from app.optimisation.engine import schedule as schedule
from app.optimisation.validation import validate_schedule as validate_schedule
