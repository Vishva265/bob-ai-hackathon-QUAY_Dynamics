"""Single source of truth for CSV fields, units, references and seed schema."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    kind: str
    unit: str
    description: str
    reference: str | None = None
    nullable: bool = False


def f(kind, unit, description, reference=None, nullable=False):
    return Field(kind, unit, description, reference, nullable)


ID = f('str', 'identifier', 'Deterministic primary key, unique within this table.')
TIME = lambda description: f('time', 'UTC RFC3339', description)
REF = lambda table, description: f('str', 'identifier', description, table)
NUM = lambda unit, description: f('float', unit, description)
INT = lambda unit, description: f('int', unit, description)

SCHEMA = {
    'ports': {
        'id': ID, 'name': f('str', 'text', 'Fictional demo port name.'),
        'latitude': NUM('degrees north', 'Map latitude; fictional infrastructure near a coastal location.'),
        'longitude': NUM('degrees east', 'Map longitude.'),
        'timezone': f('str', 'IANA timezone', 'Display timezone only; storage is always UTC.'),
    },
    'terminals': {
        'id': ID, 'port_id': REF('ports', 'Owning port.'),
        'name': f('str', 'text', 'Terminal name, unique within port.'),
        'yard_capacity_teu': NUM('TEU', 'Hard maximum terminal yard inventory.'),
        'initial_yard_teu': NUM('TEU', 'Inventory at simulation start.'),
        'gate_capacity_teu_per_hour': NUM('TEU/hour', 'Maximum truck/rail outflow; slowed by congestion events.'),
    },
    'berths': {
        'id': ID, 'terminal_id': REF('terminals', 'Owning terminal.'),
        'length_m': NUM('m', 'Maximum supported vessel length.'),
        'depth_m': NUM('m chart datum', 'Water depth before tide adjustment.'),
        'under_keel_clearance_m': NUM('m', 'Required depth margin below vessel draft.'),
        'equipment': f('str', 'enum', 'panamax_sts or super_post_panamax_sts.'),
        'max_cranes': INT('cranes', 'Maximum simultaneous assigned cranes.'),
    },
    'berth_cargo_compatibility': {
        'id': ID, 'berth_id': REF('berths', 'Compatible berth.'),
        'cargo_type': f('str', 'enum', 'general, reefer or hazardous; one row per supported type.'),
    },
    'cranes': {
        'id': ID, 'berth_id': REF('berths', 'Fixed home berth; demo cranes do not transfer.'),
        'equipment': f('str', 'enum', 'Equipment class; matches home berth.'),
        'productivity_moves_per_hour': NUM('moves/hour', 'Unimpeded single-crane handling rate.'),
    },
    'vessels': {
        'id': ID, 'name': f('str', 'text', 'Fictional vessel; one visit per generated vessel.'),
        'size_class': f('str', 'enum', 'feeder, panamax or ultra_large.'),
        'length_m': NUM('m', 'Vessel length overall.'),
        'draft_m': NUM('m', 'Operating draft for its generated visit.'),
        'capacity_teu': INT('TEU', 'Nominal onboard container capacity.'),
        'required_equipment': f('str', 'enum', 'Minimum STS reach class.'),
        'max_cranes': INT('cranes', 'Maximum useful assigned crane count.'),
    },
    'vessel_calls': {
        'id': ID, 'vessel_id': REF('vessels', 'Visiting vessel.'),
        'terminal_id': REF('terminals', 'Requested terminal; compatible berths exist there.'),
        'period': f('str', 'enum', 'historical or upcoming based on scheduled ETA.'),
        'scheduled_eta': TIME('Published ETA, hour-aligned.'),
        'priority': INT('rank 1..5', '1 is highest; same-terminal queue dispatch uses priority then actual arrival.'),
        'cargo_type': f('str', 'enum', 'general, reefer or hazardous.'),
        'onboard_teu': INT('TEU', 'Onboard load, at most vessel capacity.'),
        'unload_moves': INT('container moves', 'Requested discharge containers.'),
        'load_moves': INT('container moves', 'Requested load containers.'),
        'teu_per_move': NUM('TEU/move', 'Mean size of handled containers, between 1 and 2.'),
    },
    'weather': {
        'id': ID, 'port_id': REF('ports', 'Observed port.'),
        'timestamp': TIME('Hourly interval start; conditions apply for one hour.'),
        'period': f('str', 'enum', 'historical_observation or simulated_future_truth, never a real forecast.'),
        'wind_mps': NUM('m/s', 'Wind; >=20 closes handling and >=10 reduces productivity.'),
        'rain_mm_per_hour': NUM('mm/hour', 'Rain reduces handling, bounded multiplier.'),
        'visibility_m': NUM('m', 'Visibility; below 500 blocks vessel movement.'),
    },
    'tides': {
        'id': ID, 'port_id': REF('ports', 'Observed port.'),
        'timestamp': TIME('Hourly interval start.'),
        'height_m': NUM('m chart datum', 'Signed semidiurnal tide height; negative height is valid.'),
    },
    'crane_availability': {
        'id': ID, 'crane_id': REF('cranes', 'Affected crane.'),
        'start': TIME('Unavailable interval start, inclusive.'),
        'end': TIME('Unavailable interval end, exclusive.'),
        'reason': f('str', 'enum', 'maintenance or breakdown; available outside listed intervals.'),
        'disruption_id': f('str', 'identifier', 'Breakdown event; null for planned maintenance.', 'disruptions', True),
    },
    'disruptions': {
        'id': ID, 'port_id': REF('ports', 'Affected port.'),
        'terminal_id': f('str', 'identifier', 'Affected terminal if scoped.', 'terminals', True),
        'crane_id': f('str', 'identifier', 'Affected crane for breakdown.', 'cranes', True),
        'call_id': f('str', 'identifier', 'Affected call for late arrival.', 'vessel_calls', True),
        'kind': f('str', 'enum', 'late_arrival, crane_breakdown, storm, yard_congestion or arrival_surge.'),
        'start': TIME('Event start.'), 'end': TIME('Event end, exclusive.'),
        'value': NUM('kind-dependent', 'Delay hours, unavailable-crane fraction=1, storm wind m/s, gate capacity fraction, or extra-call count.'),
    },
    'call_outcomes': {
        'id': ID, 'call_id': REF('vessel_calls', 'Completed visit.'),
        'berth_id': REF('berths', 'Actual compatible berth.'),
        'period': f('str', 'enum', 'historical or simulated_future_truth; future labels are NOT observed training data.'),
        'actual_arrival': TIME('ETA plus generated late-arrival delay.'),
        'berth_start': TIME('Actual berth entry after queue and weather checks.'),
        'service_completion': TIME('End of last handling interval.'),
        'departure': TIME('Berth released after completion and safe weather/tide.'),
        'waiting_hours': NUM('hours', 'berth_start minus actual_arrival.'),
        'assigned_cranes': INT('cranes', 'Fixed reserved bundle; outages pause affected units.'),
        'crane_hours': NUM('crane-hours', 'Sum active crane count times productive interval fraction.'),
    },
    'crane_assignments': {
        'id': ID, 'call_id': REF('vessel_calls', 'Served visit.'),
        'crane_id': REF('cranes', 'Reserved crane, compatible with outcome berth.'),
        'start': TIME('Reservation start, includes outages.'),
        'end': TIME('Reservation released on service completion.'),
    },
    'handling_log': {
        'id': ID, 'call_id': REF('vessel_calls', 'Active visit.'),
        'timestamp': TIME('One-hour handling interval start.'),
        'active_cranes': INT('cranes', 'Reserved units available during this interval.'),
        'base_rate': NUM('moves/hour', 'Sum productivity of active cranes.'),
        'weather_factor': NUM('ratio', 'Wind/rain productivity multiplier in [0,1].'),
        'yard_factor': NUM('ratio', '1 - 0.75 * occupancy_fraction^3 before this call handles.'),
        'coordination_factor': NUM('ratio', 'active_cranes^-0.18, or 0 for no cranes; diminishing returns.'),
        'productive_fraction': NUM('hours', 'Working fraction within the hour, 0..1; capacity/demand limited.'),
        'handled_moves': NUM('moves', 'base_rate * factors * productive_fraction.'),
        'inbound_teu': NUM('TEU', 'Discharged portion of handled_moves times mean container size.'),
        'outbound_teu': NUM('TEU', 'Loaded portion of handled_moves times mean container size.'),
    },
    'yard_snapshots': {
        'id': ID, 'terminal_id': REF('terminals', 'Terminal yard.'),
        'timestamp': TIME('One-hour interval start.'),
        'opening_teu': NUM('TEU', 'Inventory carried from previous closing or initial inventory.'),
        'gate_outbound_teu': NUM('TEU', 'Truck/rail removal during interval before vessel handling.'),
        'inbound_teu': NUM('TEU', 'Total vessel discharges in interval.'),
        'outbound_teu': NUM('TEU', 'Total vessel loadings in interval.'),
        'closing_teu': NUM('TEU', 'Opening - gate_outbound + inbound - outbound; cannot exceed capacity.'),
        'queued_vessels': INT('vessels', 'Arrived but unberthed calls at dispatch for this terminal.'),
    },
}

ENUMS = {
    ('berths', 'equipment'): {'panamax_sts', 'super_post_panamax_sts'},
    ('cranes', 'equipment'): {'panamax_sts', 'super_post_panamax_sts'},
    ('vessels', 'required_equipment'): {'panamax_sts', 'super_post_panamax_sts'},
    ('vessels', 'size_class'): {'feeder', 'panamax', 'ultra_large'},
    ('berth_cargo_compatibility', 'cargo_type'): {'general', 'reefer', 'hazardous'},
    ('vessel_calls', 'cargo_type'): {'general', 'reefer', 'hazardous'},
    ('vessel_calls', 'period'): {'historical', 'upcoming'},
    ('call_outcomes', 'period'): {'historical', 'simulated_future_truth'},
    ('weather', 'period'): {'historical_observation', 'simulated_future_truth'},
    ('crane_availability', 'reason'): {'maintenance', 'breakdown'},
    ('disruptions', 'kind'): {'late_arrival', 'crane_breakdown', 'storm', 'yard_congestion', 'arrival_surge'},
}
