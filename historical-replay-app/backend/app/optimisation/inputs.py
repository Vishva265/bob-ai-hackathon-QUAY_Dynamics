"""Snapshot only known source inputs; predictions remain model-backed evidence."""
from datetime import timedelta
from sqlalchemy import select
from app import models as m
from app.services.operations import record
from app.synthetic.simulator import parse


def enrich_inputs(session, snapshot, forecast, policy):
    origin = parse(snapshot['as_of'])
    snapshot['optimisation_policy'] = policy.model_dump()
    snapshot['tide_observations'] = [record(r) for r in session.scalars(select(m.TideObservation).where(
        m.TideObservation.port_id.in_(snapshot['port_ids']), m.TideObservation.timestamp <= origin,
        m.TideObservation.timestamp >= origin-timedelta(hours=72)).order_by(m.TideObservation.id))]
    snapshot['routing_ports'] = [record(r) for r in session.scalars(select(m.Port).where(m.Port.id.in_(snapshot['port_ids'])).order_by(m.Port.id))]
    snapshot['known_call_observations'] = [record(r) for r in session.scalars(select(m.VesselCallObservation).where(
        m.VesselCallObservation.timestamp <= origin).order_by(m.VesselCallObservation.id))]
    snapshot['prediction_risk'] = {p.call_id: dict(lower=p.lower, upper=p.upper, prediction=p.prediction,
        model_version=p.model_version) for p in forecast.waiting_predictions}
    return snapshot


def prepare(data):
    """Expose future approved assignments to reassignment only when requested."""
    import copy
    data = copy.deepcopy(data)
    if data.get('_prepared'):
        return data
    policy = OptimisationPolicy.model_validate(data.get('optimisation_policy', {}))
    data['previous_assignments'] = list(data['commitments'])
    origin = parse(data['as_of'])
    progress = {c['call_id']: c for c in data['carry_in'] if parse(c['known_at']) == origin
                and c.get('remaining_unload_moves') is not None and c.get('remaining_load_moves') is not None}
    confirmed = [a['id'] for a in data['commitments'] if parse(a['start']) < origin and
        a['call_id'] in progress and progress[a['call_id']]['berth_id'] == a['berth_id']]
    data['commitments'] = [a for a in data['commitments'] if a['id'] not in confirmed]
    if policy.replan_approved:
        freeze = parse(data['as_of']) + timedelta(minutes=policy.freeze_minutes)
        data['released_commitment_ids'] = confirmed + [a['id'] for a in data['commitments'] if parse(a['start']) >= freeze]
        data['commitments'] = [a for a in data['commitments'] if parse(a['start']) < freeze]
    else:
        data['released_commitment_ids'] = confirmed
    data['confirmed_started_commitment_ids'] = confirmed
    data['_prepared'] = True
    return data


from app.optimisation.config import OptimisationPolicy
