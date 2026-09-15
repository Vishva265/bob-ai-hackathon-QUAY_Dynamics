"""Snapshot validation, deterministic comparisons, persistence and read models."""
import copy
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from app import models as m
from app.errors import DomainError
from app.recommendations.engine import RecommendationEngine, ENGINE_VERSION
from app.recommendations.schemas import RecommendationPolicy, WhatIfInput
from app.repositories.recommendations import RecommendationRepository
from app.services.context import apply_overrides, fingerprint
from app.services.operations import record
from app.synthetic.simulator import parse


class RecommendationService:
    def __init__(self, session):
        self.session, self.repo = session, RecommendationRepository(session)

    def policy(self):
        try:
            return RecommendationPolicy.configured()
        except (OSError, ValueError) as exc:
            raise DomainError('INVALID_RECOMMENDATION_CONFIGURATION', str(exc), 503) from exc

    def run(self, payload):
        source = self.repo.get(m.OptimisationRun, payload.source_run_id)
        if source.status != 'succeeded':
            raise DomainError('SOURCE_PLAN_UNAVAILABLE', 'A successfully validated executable source plan is required')
        policy = payload.policy or self.policy()
        data = apply_overrides(copy.deepcopy(source.input_snapshot))
        call_ids = {c['id'] for c in data['calls']}
        terminal_ids = {t['id'] for t in data['terminals']}
        selected = [payload.call_id] if isinstance(payload, WhatIfInput) else payload.call_ids
        unknown = (set(selected or []) | {v.call_id for v in payload.voyages})-call_ids
        if unknown:
            raise DomainError('CALL_OUTSIDE_SOURCE_PLAN', 'Unknown calls or calls without source-plan observations', details=sorted(unknown))
        unknown = ({t.terminal_id for t in payload.tariffs} | set(getattr(payload, 'candidate_terminal_ids', None) or []))-terminal_ids
        if unknown:
            raise DomainError('TERMINAL_OUTSIDE_SOURCE_PLAN', 'Receiving capacity must be included in the source multi-port run', details=sorted(unknown))
        if any(v.position_as_of > parse(source.as_of) for v in payload.voyages):
            raise DomainError('FUTURE_VESSEL_POSITION', 'Position observations after the planning origin cannot be used')
        assignments = []
        for row in self.repo.assignments(source.id):
            if not row.execution_profile or not row.completion_time:
                raise DomainError('LEGACY_SOURCE_PLAN', 'Regenerate the source plan with executable crane profiles before comparing alternatives')
            a = record(row)
            a['crane_ids'] = sorted({c for s in row.execution_profile['segments'] for c in s['crane_ids']})
            assignments.append(a)
        version = next((v['model_version'] for v in data.get('prediction_risk', {}).values()), source.forecast.model_version or 'unversioned_baseline')
        engine = RecommendationEngine(data, assignments, policy, payload.voyages, payload.tariffs, version,
            source.diagnostics.get('yard_planning_capacity_teu'), source.diagnostics.get('gate_plan'))
        if selected is None:
            by_call = {a['call_id']: a for a in assignments}
            selected = sorted(c['id'] for c in data['calls'] if
                (engine.r.release(c) < 288 or c['id'] in by_call or c['id'] in engine.fixed) and (
                data.get('prediction_risk', {}).get(c['id'], {}).get('prediction', 0) > policy.severe_wait_hours or
                by_call.get(c['id'], {}).get('waiting_minutes', 0)/60 > policy.severe_wait_hours or
                (c['id'] not in by_call and c['id'] not in engine.fixed)))
        now = datetime.now(timezone.utc)
        run_id = str(uuid4())
        results = []
        for cid in sorted(selected):
            result = engine.evaluate(cid, getattr(payload, 'candidate_terminal_ids', None))
            result.update(id=str(uuid4()), run_id=run_id)
            results.append(result)
        summary = dict(engine_version=ENGINE_VERSION, vessels_evaluated=len(results), recommended_actions=dict(Counter(r['recommended_action'] for r in results)),
            rejected_options=sum(not o['eligible'] for r in results for o in r['options'][1:]),
            distant_diversions_rejected=sum('DIVERSION_DISTANCE_EXCEEDS_NEARBY_PORT_LIMIT' in o['rejection_codes'] for r in results for o in r['options']),
            provisional_hours_saved=sum(r['expected_hours_saved'] or 0 for r in results),
            provisional_cost_change_usd=sum(r['estimated_cost_change_usd'] or 0 for r in results),
            provisional_co2_change_tonnes=sum(r['estimated_emissions_change_tonnes'] or 0 for r in results),
            aggregate_is_executable=False, capacity_is_reserved=False)
        snapshot = payload.model_dump(mode='json')
        snapshot['engine_version'] = ENGINE_VERSION
        snapshot['source_input_hash'] = fingerprint(source.input_snapshot)
        run = self.repo.add(m.RecommendationRun(id=run_id, source_run_id=source.id, as_of=source.as_of, created_at=now,
            input_hash=fingerprint(dict(request=snapshot, policy=policy.model_dump())), model_version=version,
            input_snapshot=snapshot, policy=policy.model_dump(), summary=summary,
            source_revision=data.get('state_revision', 1)))
        for result in results:
            self.repo.add(m.RecommendationDecision(id=result['id'], run_id=run.id, call_id=result['call_id'],
                port_id=result['port_id'], action=result['recommended_action'], expires_at=parse(result['expires_at']), result=result))
        return run

    def output_decision(self, row, state_changed=False):
        result = copy.deepcopy(row.result)
        result['is_expired'] = datetime.now(timezone.utc) >= parse(row.expires_at)
        # Conditional proposals always require refresh, a joint replan and
        # approval. A fresh recommendation alone is never an execution order.
        result['operationally_actionable'] = False
        if result['is_expired']:
            result['risks_and_assumptions'].append('Expired source-time recommendation: historical what-if only; refresh operational inputs before approval.')
        if state_changed:
            result['risks_and_assumptions'].append('Operational state changed since the source plan; receiving capacity must be recomputed.')
        return result

    def output(self, run_id):
        run = self.repo.get(m.RecommendationRun, run_id)
        state = self.session.get(m.PlanningState, 1)
        changed = bool(state and state.revision != run.source_revision)
        results = [self.output_decision(r, changed) for r in self.repo.decisions(run.id)]
        return dict(id=run.id, source_run_id=run.source_run_id, as_of=run.as_of, created_at=run.created_at,
            input_hash=run.input_hash, model_version=run.model_version, source_state_changed=changed,
            policy=run.policy, summary=dict(run.summary, expired_recommendations=sum(r['is_expired'] for r in results)),
            recommendations=results)

    def list(self, limit, cursor, run_id=None, port_id=None, call_id=None, action=None):
        filters = dict(run_id=run_id, port_id=port_id, call_id=call_id, action=action)
        conditions = [getattr(m.RecommendationDecision, key) == value for key, value in filters.items() if value is not None]
        page = self.repo.page(m.RecommendationDecision, conditions, limit, cursor, filters)
        state = self.session.get(m.PlanningState, 1)
        page['items'] = [self.output_decision(r, bool(state and state.revision != r.run.source_revision)) for r in page['items']]
        return page
