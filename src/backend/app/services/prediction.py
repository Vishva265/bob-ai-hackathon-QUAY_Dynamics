"""Operational DB adapter for point-in-time model inference and persisted output."""
from uuid import uuid4

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.errors import DomainError
from app.predictive.inference import InferenceEngine
from app.predictive.registry import ModelRegistry, ModelArtifactError
from app.repositories.operations import Repository
from app.services.operations import record


class PredictionService:
    def __init__(self, session):
        self.session, self.repo = session, Repository(session)
        self.registry = ModelRegistry(get_settings().model_directory)

    def enrich(self, run, snapshot):
        from app.services.context import apply_overrides
        try:
            engine = InferenceEngine(self.registry)
            calibration_end = max(r['splits']['validation']['label_known_end'] for r in engine.metadata['evaluation'].values())
            import pandas as pd
            if pd.Timestamp(run.as_of) <= pd.Timestamp(calibration_end):
                raise DomainError('MODEL_LOOKAHEAD', 'Use an as_of after this model training/calibration period', 409)
            tables = {name: [dict(row) for row in self.session.execute(select(table)).mappings()]
                      for name, table in m.source_tables.items()}
            tables['carry_in_operations'] = [record(r) for r in self.repo.all(m.CarryInOperation)]
            tables['vessel_call_observations'] = [record(r) for r in self.repo.all(m.VesselCallObservation)]
            data = apply_overrides(snapshot)
            # Restore model-facing calendars with observed recovery, rather than
            # consulting a simulator's estimated repair end. Historical imported
            # repairs are facts; subsequent active failures persist until observed.
            selected_cranes={c['id'] for c in data['cranes']}
            origin=pd.Timestamp(run.as_of)
            provenance=self.session.get(m.SeedProvenance,1)
            repairs=[record(r) for r in self.repo.all(m.CraneRestorationObservation,m.CraneRestorationObservation.timestamp<=run.as_of)]
            availability=[]
            for row in tables['crane_availability']:
                row=dict(row)
                if row['crane_id'] in selected_cranes and row['reason']=='breakdown':
                    start,end=pd.Timestamp(row['start']),pd.Timestamp(row['end'])
                    if start>origin:continue
                    recovery=sorted(pd.Timestamp(r['timestamp']) for r in repairs if r['crane_id']==row['crane_id'] and pd.Timestamp(r['timestamp'])>=start)
                    if recovery:row['end']=recovery[0].isoformat()
                    elif not provenance or end>pd.Timestamp(provenance.epoch):row['end']=(origin+pd.Timedelta(hours=168)).isoformat()
                availability.append(row)
            tables['crane_availability']=availability
            tables['yard_reconciliations']=[record(r) for r in self.session.scalars(select(m.YardReconciliation).order_by(m.YardReconciliation.snapshot_id))]
            closures=list(data.get('berth_closures',[]))
            for event in data['disruptions']:
                if event['kind']=='storm':
                    closures.extend(dict(berth_id=b['id'],start=event['start'],end=event['end']) for b in data['berths']
                        if next(t for t in data['terminals'] if t['id']==b['terminal_id'])['port_id']==event['port_id'])
            for i,closure in enumerate(closures):
                for crane in data['cranes']:
                    if crane['berth_id']==closure['berth_id']:
                        tables['crane_availability'].append(dict(id=f'known-closure-{i}-{crane["id"]}',crane_id=crane['id'],
                            start=closure['start'],end=closure['end'],reason='maintenance',disruption_id=None))
            # Override only selected scope; retain observed history for rolling statistics.
            for key, source in [('vessel_calls', 'calls'), ('terminals', 'terminals')]:
                overrides = {r['id']: r for r in data[source]}
                tables[key] = [overrides.get(r['id'], r) for r in tables[key]]
            for item in data['overrides']:
                if item['kind'] == 'crane_outage':
                    tables['crane_availability'].append(dict(id='scenario-'+str(uuid4()), crane_id=item['crane_id'],
                        start=item['start'], end=item['end'], reason='maintenance', disruption_id=None))
                elif item['kind'] == 'storm':
                    # Explicit known future storm closes each crane during that interval.
                    bids = {b['id'] for b in data['berths'] if next(t for t in data['terminals'] if t['id'] == b['terminal_id'])['port_id'] == item['port_id']}
                    for crane in data['cranes']:
                        if crane['berth_id'] in bids:
                            tables['crane_availability'].append(dict(id='storm-'+crane['id'], crane_id=crane['id'],
                                start=item['start'], end=item['end'], reason='maintenance', disruption_id=None))
            result = engine.forecast(tables, run.as_of, data['port_ids'])
            run.method = 'chronological_ml_v1'
            run.quality = engine.metadata['quality']
            run.model_version = result['model_version']
            for row in result['congestion']:
                row = dict(row)
                row.pop('as_of')
                self.session.add(m.PredictiveCongestion(id=str(uuid4()), run_id=run.id,
                    scope_id=row['terminal_id'] or row['port_id'], **row))
            for row in result['waiting']:
                row = dict(row)
                row.pop('as_of')
                self.session.add(m.VesselWaitingPrediction(id=str(uuid4()), run_id=run.id, **row))
        except ModelArtifactError as error:
            raise DomainError('MODEL_UNAVAILABLE', str(error), 503) from error
        except ValueError as error:
            raise DomainError('INVALID_PREDICTION_INPUTS', str(error), 422) from error

    def congestion(self, limit, cursor, run_id=None, port_id=None, terminal_id=None, scope=None, start=None, end=None):
        return self._list(m.PredictiveCongestion, limit, cursor, dict(run_id=run_id, port_id=port_id,
            terminal_id=terminal_id, scope=scope), start, end)

    def metadata(self):
        try:
            _, metadata = self.registry.load()
            from app.schemas import ModelMetadataOut
            return {name: metadata[name] for name in ModelMetadataOut.model_fields}
        except ModelArtifactError as error:
            raise DomainError('MODEL_UNAVAILABLE', str(error), 503) from error

    def waiting(self, limit, cursor, run_id=None, call_id=None, port_id=None, terminal_id=None):
        return self._list(m.VesselWaitingPrediction, limit, cursor, dict(run_id=run_id, call_id=call_id,
            port_id=port_id, terminal_id=terminal_id))

    def _list(self, model, limit, cursor, filters, start=None, end=None):
        conditions = []
        resources = dict(run_id=m.ForecastRun, port_id=m.Port, terminal_id=m.Terminal, call_id=m.VesselCall)
        for key, value in filters.items():
            if value is not None:
                if key in resources:
                    self.repo.get(resources[key], value)
                conditions.append(getattr(model, key) == value)
        if start and end and end <= start:
            raise DomainError('INVALID_WINDOW', 'end must follow start')
        if start:
            conditions.append(model.timestamp >= start)
        if end:
            conditions.append(model.timestamp < end)
        return self.repo.page(model, conditions, limit, cursor, dict(entity=model.__tablename__, **filters, start=start, end=end))
