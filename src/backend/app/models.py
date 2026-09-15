"""Normalized ORM mappings, separating observed operations from generated plans."""
from sqlalchemy import (Column, Float, ForeignKey, Integer, JSON, String, UniqueConstraint, CheckConstraint)
from sqlalchemy.orm import DeclarativeBase, relationship

from app.synthetic.storage import database_schema, UTCInstant


metadata, source_tables, _ = database_schema()
# Real operational vessels may make many visits; the simulator's one-visit rule
# is a generation assumption, not an application constraint.
for constraint in list(source_tables['vessel_calls'].constraints):
    if isinstance(constraint, UniqueConstraint):
        source_tables['vessel_calls'].constraints.remove(constraint)


class Base(DeclarativeBase):
    metadata = metadata


class OptimisationJobLease(Base):
    __tablename__ = 'optimisation_job_leases'
    id = Column(String(80), primary_key=True)
    owner = Column(String(64), nullable=False)
    expires_at = Column(UTCInstant(), nullable=False, index=True)


class LiveDemoSession(Base):
    __tablename__ = 'live_demo_sessions'
    id = Column(String(160), primary_key=True)
    port_id = Column(ForeignKey('ports.id'), nullable=False)
    created_at = Column(UTCInstant(), nullable=False)
    clock = Column(UTCInstant(), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False)
    latest_run_id = Column(String(160), nullable=True)  # belongs to isolated branch
    initial_run_id = Column(String(160), nullable=True)
    active_event_id = Column(String(160), nullable=True)
    settings = Column(JSON, nullable=False)
    __table_args__ = (CheckConstraint('revision >= 1'),)


class LiveDemoEvent(Base):
    __tablename__ = 'live_demo_events'
    id = Column(String(160), primary_key=True)
    session_id = Column(ForeignKey('live_demo_sessions.id'), nullable=False)
    sequence = Column(Integer, nullable=False)
    kind = Column(String(40), nullable=False)
    status = Column(String(32), nullable=False)
    stage_revision = Column(Integer, nullable=False)
    created_at = Column(UTCInstant(), nullable=False)
    updated_at = Column(UTCInstant(), nullable=False)
    operational_time = Column(UTCInstant(), nullable=False)
    payload = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    error = Column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint('session_id', 'sequence'), CheckConstraint('sequence >= 1 AND stage_revision >= 1'))


class BerthClosureWindow(Base):
    __tablename__ = 'berth_closure_windows'
    id = Column(String(160), primary_key=True)
    berth_id = Column(ForeignKey('berths.id'), nullable=False)
    start = Column(UTCInstant(), nullable=False)
    end = Column(UTCInstant(), nullable=False)
    __table_args__ = (CheckConstraint('"end" > "start"'),)


class YardCapacityObservation(Base):
    __tablename__ = 'yard_capacity_observations'
    id = Column(String(160), primary_key=True)
    terminal_id = Column(ForeignKey('terminals.id'), nullable=False)
    timestamp = Column(UTCInstant(), nullable=False)
    capacity_teu = Column(Float, nullable=False)
    __table_args__ = (UniqueConstraint('terminal_id', 'timestamp'), CheckConstraint('capacity_teu > 0'))


class LiveDemoReceipt(Base):
    __tablename__ = 'live_demo_receipts'
    event_id = Column(String(160), primary_key=True)
    run_id = Column(ForeignKey('optimisation_runs.id'), nullable=False)
    clock = Column(UTCInstant(), nullable=False)
    result = Column(JSON, nullable=False)


class KnownStormAdvisory(Base):
    __tablename__ = 'known_storm_advisories'
    id = Column(String(160), primary_key=True)
    port_id = Column(ForeignKey('ports.id'), nullable=False)
    known_at = Column(UTCInstant(), nullable=False)
    start = Column(UTCInstant(), nullable=False)
    end = Column(UTCInstant(), nullable=False)
    cancelled_at = Column(UTCInstant(), nullable=True)
    __table_args__ = (CheckConstraint('"end" > "start" AND start >= known_at'),)


class YardReconciliation(Base):
    __tablename__ = 'yard_reconciliations'
    snapshot_id = Column(ForeignKey('yard_snapshots.id'), primary_key=True)
    known_at = Column(UTCInstant(), nullable=False)


def mapped(name, table):
    return type(name, (Base,), {'__tablename__': table, '__table__': metadata.tables[table]})


Port = mapped('Port', 'ports')
Terminal = mapped('Terminal', 'terminals')
Berth = mapped('Berth', 'berths')
Crane = mapped('Crane', 'cranes')
Vessel = mapped('Vessel', 'vessels')
VesselCall = mapped('VesselCall', 'vessel_calls')
YardSnapshot = mapped('YardSnapshot', 'yard_snapshots')
WeatherObservation = mapped('WeatherObservation', 'weather')
TideObservation = mapped('TideObservation', 'tides')
DisruptionEvent = mapped('DisruptionEvent', 'disruptions')
CallOutcome = mapped('CallOutcome', 'call_outcomes')
ObservedCraneAssignment = mapped('ObservedCraneAssignment', 'crane_assignments')
CraneAvailability = mapped('CraneAvailability', 'crane_availability')
BerthCargoCompatibility = mapped('BerthCargoCompatibility', 'berth_cargo_compatibility')

Port.terminals = relationship(Terminal, back_populates='port')
Terminal.port = relationship(Port, back_populates='terminals')
Terminal.berths = relationship(Berth, back_populates='terminal')
Terminal.calls = relationship(VesselCall, back_populates='terminal')
Terminal.yard_snapshots = relationship(YardSnapshot, back_populates='terminal')
Berth.terminal = relationship(Terminal, back_populates='berths')
Berth.cranes = relationship(Crane, back_populates='berth')
Berth.cargo_compatibilities = relationship(BerthCargoCompatibility)
Crane.berth = relationship(Berth, back_populates='cranes')
Vessel.calls = relationship(VesselCall, back_populates='vessel')
VesselCall.vessel = relationship(Vessel, back_populates='calls')
VesselCall.terminal = relationship(Terminal, back_populates='calls')
VesselCall.outcome = relationship(CallOutcome, uselist=False)
YardSnapshot.terminal = relationship(Terminal, back_populates='yard_snapshots')
WeatherObservation.port = relationship(Port)
TideObservation.port = relationship(Port)
DisruptionEvent.port = relationship(Port)


class ForecastRun(Base):
    __tablename__ = 'forecast_runs'
    id = Column(String(160), primary_key=True)
    as_of = Column(UTCInstant(), nullable=False)
    horizon_hours = Column(Integer, nullable=False)
    method = Column(String(64), nullable=False)
    quality = Column(String(64), nullable=False)
    created_at = Column(UTCInstant(), nullable=False)
    input_hash = Column(String(64), nullable=False)
    buckets = relationship('CongestionForecast', back_populates='run')
    model_version = Column(String(64), nullable=True)
    predictive_buckets = relationship('PredictiveCongestion', back_populates='run')
    waiting_predictions = relationship('VesselWaitingPrediction', back_populates='run')
    __table_args__ = (CheckConstraint('horizon_hours = 72'),)


class CongestionForecast(Base):
    __tablename__ = 'congestion_forecasts'
    id = Column(String(160), primary_key=True)
    run_id = Column(ForeignKey('forecast_runs.id'), nullable=False, index=True)
    port_id = Column(ForeignKey('ports.id'), nullable=False, index=True)
    berth_id = Column(ForeignKey('berths.id'), nullable=False)
    timestamp = Column(UTCInstant(), nullable=False, index=True)
    demand_moves = Column(Float, nullable=False)
    capacity_moves = Column(Float, nullable=False)
    pressure_ratio = Column(Float, nullable=True)
    alert = Column(Integer, nullable=False)
    reasons = Column(JSON, nullable=False)
    run = relationship(ForecastRun, back_populates='buckets')
    port = relationship(Port)
    berth = relationship(Berth)
    __table_args__ = (UniqueConstraint('run_id', 'berth_id', 'timestamp'),
                      CheckConstraint('demand_moves >= 0 AND capacity_moves >= 0 AND pressure_ratio >= 0'))


class PredictiveCongestion(Base):
    __tablename__ = 'predictive_congestion'
    id = Column(String(160), primary_key=True)
    run_id = Column(ForeignKey('forecast_runs.id'), nullable=False, index=True)
    port_id = Column(ForeignKey('ports.id'), nullable=False, index=True)
    terminal_id = Column(ForeignKey('terminals.id'), nullable=True, index=True)
    scope = Column(String(16), nullable=False)
    scope_id = Column(String(160), nullable=False)
    timestamp = Column(UTCInstant(), nullable=False, index=True)
    prediction = Column(Float, nullable=False)
    lower = Column(Float, nullable=False)
    upper = Column(Float, nullable=False)
    level = Column(String(16), nullable=False)
    level_probabilities = Column(JSON, nullable=False)
    factors = Column(JSON, nullable=False)
    model_version = Column(String(64), nullable=False)
    prediction_timestamp = Column(UTCInstant(), nullable=False)
    uncertainty_method = Column(String(64), nullable=False)
    nominal_coverage = Column(Float, nullable=False)
    quality = Column(String(64), nullable=False)
    run = relationship(ForecastRun, back_populates='predictive_buckets')
    port = relationship(Port)
    terminal = relationship(Terminal)
    __table_args__ = (UniqueConstraint('run_id', 'scope', 'scope_id', 'timestamp'),
        CheckConstraint("scope IN ('port', 'terminal') AND level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')"),
        CheckConstraint("(scope = 'port' AND terminal_id IS NULL AND scope_id = port_id) OR (scope = 'terminal' AND terminal_id IS NOT NULL AND scope_id = terminal_id)"),
        CheckConstraint('prediction >= 0 AND prediction <= 1 AND lower >= 0 AND upper <= 1 AND lower <= prediction AND upper >= prediction'))


class VesselWaitingPrediction(Base):
    __tablename__ = 'vessel_waiting_predictions'
    id = Column(String(160), primary_key=True)
    run_id = Column(ForeignKey('forecast_runs.id'), nullable=False, index=True)
    call_id = Column(ForeignKey('vessel_calls.id'), nullable=False, index=True)
    port_id = Column(ForeignKey('ports.id'), nullable=False)
    terminal_id = Column(ForeignKey('terminals.id'), nullable=False)
    scheduled_eta = Column(UTCInstant(), nullable=False)
    prediction = Column(Float, nullable=False)
    lower = Column(Float, nullable=False)
    upper = Column(Float, nullable=False)
    factors = Column(JSON, nullable=False)
    model_version = Column(String(64), nullable=False)
    prediction_timestamp = Column(UTCInstant(), nullable=False)
    uncertainty_method = Column(String(64), nullable=False)
    nominal_coverage = Column(Float, nullable=False)
    quality = Column(String(64), nullable=False)
    run = relationship(ForecastRun, back_populates='waiting_predictions')
    call = relationship(VesselCall)
    __table_args__ = (UniqueConstraint('run_id', 'call_id'),
        CheckConstraint('prediction >= 0 AND lower >= 0 AND lower <= prediction AND upper >= prediction'))


class VesselCallObservation(Base):
    __tablename__ = 'vessel_call_observations'
    id = Column(String(160), primary_key=True)
    call_id = Column(ForeignKey('vessel_calls.id'), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    timestamp = Column(UTCInstant(), nullable=False, index=True)
    berth_id = Column(ForeignKey('berths.id'), nullable=True)
    call = relationship(VesselCall)
    berth = relationship(Berth)
    __table_args__ = (UniqueConstraint('call_id', 'kind'),
        CheckConstraint("kind IN ('arrival', 'berth_start', 'departure')"),
        CheckConstraint("kind = 'arrival' OR berth_id IS NOT NULL"))


class Scenario(Base):
    __tablename__ = 'scenarios'
    id = Column(String(160), primary_key=True)
    name = Column(String(120), nullable=False)
    as_of = Column(UTCInstant(), nullable=False)
    overrides = Column(JSON, nullable=False)
    created_at = Column(UTCInstant(), nullable=False)


class OptimisationRun(Base):
    __tablename__ = 'optimisation_runs'
    id = Column(String(160), primary_key=True)
    forecast_run_id = Column(ForeignKey('forecast_runs.id'), nullable=False)
    scenario_id = Column(ForeignKey('scenarios.id'), nullable=True)
    as_of = Column(UTCInstant(), nullable=False)
    end = Column(UTCInstant(), nullable=False)
    status = Column(String(32), nullable=False)
    solver_status = Column(String(32), nullable=False)
    created_at = Column(UTCInstant(), nullable=False)
    runtime_ms = Column(Integer, nullable=False)
    input_snapshot = Column(JSON, nullable=False)
    diagnostics = Column(JSON, nullable=False)
    forecast = relationship(ForecastRun)
    scenario = relationship(Scenario)
    assignments = relationship('BerthAssignment', back_populates='run')
    plan = relationship('SupervisorPlan', back_populates='run', uselist=False)
    __table_args__ = (CheckConstraint('"end" > as_of AND runtime_ms >= 0'),)


class BerthAssignment(Base):
    __tablename__ = 'berth_assignments'
    id = Column(String(160), primary_key=True)
    run_id = Column(ForeignKey('optimisation_runs.id'), nullable=False, index=True)
    call_id = Column(ForeignKey('vessel_calls.id'), nullable=False)
    berth_id = Column(ForeignKey('berths.id'), nullable=False)
    start = Column(UTCInstant(), nullable=False)
    end = Column(UTCInstant(), nullable=False)
    waiting_minutes = Column(Integer, nullable=False)
    planned_moves = Column(Integer, nullable=False)
    completion_time = Column(UTCInstant(), nullable=True)
    execution_profile = Column(JSON, nullable=True)
    superseded_at = Column(UTCInstant(), nullable=True)
    reasons = Column(JSON, nullable=False)
    run = relationship(OptimisationRun, back_populates='assignments')
    call = relationship(VesselCall)
    berth = relationship(Berth)
    cranes = relationship('CraneAssignment', back_populates='assignment')
    __table_args__ = (UniqueConstraint('run_id', 'call_id'), CheckConstraint('"end" > "start" AND waiting_minutes >= 0 AND planned_moves > 0'))


class CraneAssignment(Base):
    __tablename__ = 'plan_crane_assignments'
    id = Column(String(160), primary_key=True)
    assignment_id = Column(ForeignKey('berth_assignments.id'), nullable=False, index=True)
    crane_id = Column(ForeignKey('cranes.id'), nullable=False)
    start = Column(UTCInstant(), nullable=False)
    end = Column(UTCInstant(), nullable=False)
    assignment = relationship(BerthAssignment, back_populates='cranes')
    crane = relationship(Crane)
    __table_args__ = (UniqueConstraint('assignment_id', 'crane_id', 'start', name='uq_plan_crane_assignments_segment'), CheckConstraint('"end" > "start"'),)


class RoutingRecommendation(Base):
    __tablename__ = 'routing_recommendations'
    id = Column(String(160), primary_key=True)
    run_id = Column(ForeignKey('optimisation_runs.id'), nullable=False, index=True)
    call_id = Column(ForeignKey('vessel_calls.id'), nullable=False)
    kind = Column(String(32), nullable=False)
    alternate_port_id = Column(ForeignKey('ports.id'), nullable=True)
    adjusted_eta = Column(UTCInstant(), nullable=True)
    reasons = Column(JSON, nullable=False)
    run = relationship(OptimisationRun)
    call = relationship(VesselCall)
    alternate_port = relationship(Port)


class SupervisorPlan(Base):
    __tablename__ = 'supervisor_plans'
    id = Column(String(160), primary_key=True)
    run_id = Column(ForeignKey('optimisation_runs.id'), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default='DRAFT')
    revision = Column(Integer, nullable=False, default=1)
    approved_by = Column(String(120), nullable=True)
    approved_at = Column(UTCInstant(), nullable=True)
    run = relationship(OptimisationRun, back_populates='plan')
    shifts = relationship('SupervisorShiftPlan', back_populates='plan', order_by='SupervisorShiftPlan.shift_index')
    publication = relationship('PlanPublication', uselist=False, back_populates='plan', foreign_keys='PlanPublication.plan_id')

    @property
    def document(self):
        return self.publication.document if self.publication else None

    @property
    def previous_plan_id(self):
        return self.publication.previous_plan_id if self.publication else None

    @property
    def reviewed_by(self):
        return self.publication.reviewed_by if self.publication else None

    @property
    def reviewed_at(self):
        return self.publication.reviewed_at if self.publication else None


class SupervisorShiftPlan(Base):
    __tablename__ = 'supervisor_shift_plans'
    id = Column(String(160), primary_key=True)
    plan_id = Column(ForeignKey('supervisor_plans.id'), nullable=False, index=True)
    shift_index = Column(Integer, nullable=False)
    start = Column(UTCInstant(), nullable=False)
    end = Column(UTCInstant(), nullable=False)
    tasks = Column(JSON, nullable=False)
    details = Column(JSON, nullable=True)
    plan = relationship(SupervisorPlan, back_populates='shifts')
    __table_args__ = (UniqueConstraint('plan_id', 'shift_index'), CheckConstraint('shift_index BETWEEN 0 AND 8 AND "end" > "start"'))


class ApprovalEvent(Base):
    __tablename__ = 'approval_events'
    id = Column(String(160), primary_key=True)
    plan_id = Column(ForeignKey('supervisor_plans.id'), nullable=False)
    actor = Column(String(120), nullable=False)
    occurred_at = Column(UTCInstant(), nullable=False)
    revision = Column(Integer, nullable=False)


class PlanPublication(Base):
    __tablename__ = 'plan_publications'
    plan_id = Column(ForeignKey('supervisor_plans.id'), primary_key=True)
    previous_plan_id = Column(ForeignKey('supervisor_plans.id'), nullable=True)
    document = Column(JSON, nullable=False)
    generated_at = Column(UTCInstant(), nullable=False)
    reviewed_by = Column(String(120), nullable=True)
    reviewed_at = Column(UTCInstant(), nullable=True)
    plan = relationship(SupervisorPlan, back_populates='publication', foreign_keys=[plan_id])


class PlanStateEvent(Base):
    __tablename__ = 'plan_state_events'
    id = Column(String(160), primary_key=True)
    plan_id = Column(ForeignKey('supervisor_plans.id'), nullable=False, index=True)
    from_state = Column(String(32), nullable=True)
    to_state = Column(String(32), nullable=False)
    revision = Column(Integer, nullable=False)
    actor = Column(String(120), nullable=False)
    timestamp = Column(UTCInstant(), nullable=False)
    note = Column(String(1000), nullable=False)


class OperationalUpdateEvent(Base):
    __tablename__ = 'operational_update_events'
    id = Column(String(160), primary_key=True)
    base_plan_id = Column(ForeignKey('supervisor_plans.id'), nullable=False, index=True)
    state_revision = Column(Integer, nullable=False)
    actor = Column(String(120), nullable=False)
    timestamp = Column(UTCInstant(), nullable=False)
    changes = Column(JSON, nullable=False)


class CraneRestorationObservation(Base):
    __tablename__ = 'crane_restoration_observations'
    id = Column(String(160), primary_key=True)
    crane_id = Column(ForeignKey('cranes.id'), nullable=False, index=True)
    timestamp = Column(UTCInstant(), nullable=False)
    actor = Column(String(120), nullable=False)


class SeedProvenance(Base):
    __tablename__ = 'seed_provenance'
    id = Column(Integer, primary_key=True)
    scenario = Column(String(64), nullable=False)
    epoch = Column(UTCInstant(), nullable=False)
    input_hash = Column(String(64), nullable=False)


class CarryInOperation(Base):
    __tablename__ = 'carry_in_operations'
    id = Column(String(160), primary_key=True)
    call_id = Column(ForeignKey('vessel_calls.id'), nullable=False, unique=True)
    berth_id = Column(ForeignKey('berths.id'), nullable=False)
    known_at = Column(UTCInstant(), nullable=False)
    started_at = Column(UTCInstant(), nullable=False)
    remaining_moves = Column(Float, nullable=False)
    crane_ids = Column(JSON, nullable=False)
    remaining_unload_moves = Column(Integer, nullable=True)
    remaining_load_moves = Column(Integer, nullable=True)
    call = relationship(VesselCall)
    berth = relationship(Berth)
    __table_args__ = (CheckConstraint('remaining_moves >= 0 AND known_at >= started_at'),)


class PlanningState(Base):
    __tablename__ = 'planning_state'
    id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False)
    __table_args__ = (CheckConstraint('revision >= 1'),)


class RecommendationRun(Base):
    __tablename__ = 'recommendation_runs'
    id = Column(String(160), primary_key=True)
    source_run_id = Column(ForeignKey('optimisation_runs.id'), nullable=False, index=True)
    as_of = Column(UTCInstant(), nullable=False)
    created_at = Column(UTCInstant(), nullable=False)
    input_hash = Column(String(64), nullable=False)
    model_version = Column(String(64), nullable=False)
    input_snapshot = Column(JSON, nullable=False)
    policy = Column(JSON, nullable=False)
    summary = Column(JSON, nullable=False)
    source_revision = Column(Integer, nullable=False)
    source = relationship(OptimisationRun)
    decisions = relationship('RecommendationDecision', back_populates='run')


class RecommendationDecision(Base):
    __tablename__ = 'recommendation_decisions'
    id = Column(String(160), primary_key=True)
    run_id = Column(ForeignKey('recommendation_runs.id'), nullable=False, index=True)
    call_id = Column(ForeignKey('vessel_calls.id'), nullable=False, index=True)
    port_id = Column(ForeignKey('ports.id'), nullable=False)
    action = Column(String(40), nullable=False)
    expires_at = Column(UTCInstant(), nullable=False)
    result = Column(JSON, nullable=False)
    run = relationship(RecommendationRun, back_populates='decisions')
    call = relationship(VesselCall)
    __table_args__ = (UniqueConstraint('run_id', 'call_id'),
        CheckConstraint("action IN ('KEEP_CURRENT_PLAN', 'SLOW_STEAM_OR_DELAY_ARRIVAL', 'EARLIER_ARRIVAL', 'ALTERNATE_TERMINAL', 'ALTERNATE_PORT')"))


class EarlyWarningRun(Base):
    __tablename__ = 'early_warning_runs'
    id = Column(ForeignKey('forecast_runs.id'), primary_key=True)
    rules = Column(JSON, nullable=False)
    projection_method = Column(String(64), nullable=False)
    summaries = Column(JSON, nullable=False)
    alert_counts = Column(JSON, nullable=False)
    assumptions = Column(JSON, nullable=False)


class OperationalForecast(Base):
    __tablename__ = 'operational_forecasts'
    id = Column(String(160), primary_key=True)
    run_id = Column(ForeignKey('early_warning_runs.id'), nullable=False, index=True)
    scope = Column(String(16), nullable=False)
    scope_id = Column(String(160), nullable=False)
    port_id = Column(ForeignKey('ports.id'), nullable=False)
    terminal_id = Column(ForeignKey('terminals.id'), nullable=True)
    berth_id = Column(ForeignKey('berths.id'), nullable=True)
    timestamp = Column(UTCInstant(), nullable=False)
    berth_utilisation = Column(Float, nullable=False)
    queue_length = Column(Float, nullable=False)
    average_wait_hours = Column(Float, nullable=False)
    yard_occupancy = Column(Float, nullable=False)
    crane_utilisation = Column(Float, nullable=False)
    congestion_probability = Column(Float, nullable=False)
    probability_lower = Column(Float, nullable=False)
    probability_upper = Column(Float, nullable=False)
    probability_basis = Column(String(32), nullable=False)
    congestion_severity = Column(String(16), nullable=False)
    confidence_level = Column(String(16), nullable=False)
    confidence_reasons = Column(JSON, nullable=False)
    main_causes = Column(JSON, nullable=False)
    arrival_workload_ratio = Column(Float, nullable=False)
    arrival_workload_increase_moves = Column(Float, nullable=False)
    is_hotspot = Column(Integer, nullable=False)
    first_expected_hotspot_time = Column(UTCInstant(), nullable=True)
    expected_hotspot_duration_hours = Column(Integer, nullable=False)
    model_version = Column(String(64), nullable=False)
    prediction_timestamp = Column(UTCInstant(), nullable=False)
    __table_args__ = (
        UniqueConstraint('run_id', 'scope', 'scope_id', 'timestamp'),
        CheckConstraint("scope IN ('port', 'terminal', 'berth')"),
        CheckConstraint("(scope = 'port' AND scope_id = port_id AND terminal_id IS NULL AND berth_id IS NULL) OR (scope = 'terminal' AND scope_id = terminal_id AND berth_id IS NULL) OR (scope = 'berth' AND scope_id = berth_id AND terminal_id IS NOT NULL)"),
        CheckConstraint('berth_utilisation BETWEEN 0 AND 1 AND yard_occupancy BETWEEN 0 AND 1 AND crane_utilisation BETWEEN 0 AND 1'),
        CheckConstraint('queue_length >= 0 AND average_wait_hours >= 0 AND arrival_workload_ratio >= 0 AND arrival_workload_increase_moves >= 0'),
        CheckConstraint('probability_lower >= 0 AND probability_upper <= 1 AND probability_lower <= congestion_probability AND congestion_probability <= probability_upper'),
        CheckConstraint("congestion_severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL') AND confidence_level IN ('LOW', 'MEDIUM', 'HIGH')"),
        CheckConstraint('expected_hotspot_duration_hours BETWEEN 0 AND 72 AND is_hotspot IN (0, 1)'),
    )


class AlertWatermark(Base):
    """Per-entity transaction lock and chronological alert reconciliation guard."""
    __tablename__ = 'alert_watermarks'
    id = Column(String(180), primary_key=True)
    as_of = Column(UTCInstant(), nullable=False)
    revision = Column(Integer, nullable=False)
    __table_args__ = (CheckConstraint('revision >= 0'),)


class CongestionAlert(Base):
    __tablename__ = 'congestion_alerts'
    id = Column(String(160), primary_key=True)
    active_key = Column(String(240), nullable=True, unique=True)
    scope = Column(String(16), nullable=False)
    scope_id = Column(String(160), nullable=False)
    port_id = Column(ForeignKey('ports.id'), nullable=False)
    terminal_id = Column(ForeignKey('terminals.id'), nullable=True)
    berth_id = Column(ForeignKey('berths.id'), nullable=True)
    rule_code = Column(String(32), nullable=False)
    state = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    opened_at = Column(UTCInstant(), nullable=False)
    updated_at = Column(UTCInstant(), nullable=False)
    first_run_id = Column(ForeignKey('early_warning_runs.id'), nullable=False)
    last_run_id = Column(ForeignKey('early_warning_runs.id'), nullable=False)
    expected_start = Column(UTCInstant(), nullable=False)
    expected_end = Column(UTCInstant(), nullable=False)
    duration_hours = Column(Integer, nullable=False)
    evidence = Column(JSON, nullable=False)
    acknowledged_by = Column(String(120), nullable=True)
    acknowledged_at = Column(UTCInstant(), nullable=True)
    resolved_at = Column(UTCInstant(), nullable=True)
    __table_args__ = (
        CheckConstraint("state IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')"),
        CheckConstraint("(state = 'RESOLVED' AND active_key IS NULL AND resolved_at IS NOT NULL) OR (state != 'RESOLVED' AND active_key IS NOT NULL AND resolved_at IS NULL)"),
        CheckConstraint('revision >= 1 AND duration_hours BETWEEN 1 AND 72 AND expected_end > expected_start'),
        CheckConstraint("scope IN ('port', 'terminal', 'berth')"),
    )


class AlertEvent(Base):
    __tablename__ = 'alert_events'
    id = Column(String(160), primary_key=True)
    alert_id = Column(ForeignKey('congestion_alerts.id'), nullable=False, index=True)
    run_id = Column(ForeignKey('early_warning_runs.id'), nullable=False)
    action = Column(String(32), nullable=False)
    actor = Column(String(120), nullable=True)
    occurred_at = Column(UTCInstant(), nullable=False)
    revision = Column(Integer, nullable=False)
    evidence = Column(JSON, nullable=False)


for table, cols in [(source_tables['vessel_calls'], ('terminal_id', 'scheduled_eta')),
                    (source_tables['weather'], ('port_id', 'timestamp')),
                    (source_tables['tides'], ('port_id', 'timestamp')),
                    (source_tables['yard_snapshots'], ('terminal_id', 'timestamp'))]:
    from sqlalchemy import Index
    Index(f'ix_{table.name}_lookup', *(table.c[c] for c in cols))

for table_name, columns in [
    ('supervisor_plans', ['status', 'approved_at']), ('optimisation_runs', ['created_at']),
    ('operational_forecasts', ['run_id', 'port_id', 'timestamp']),
    ('crane_availability', ['crane_id', 'start', 'end']),
    ('crane_restoration_observations', ['crane_id', 'timestamp']),
    ('berth_closure_windows', ['berth_id', 'start', 'end']),
    ('yard_capacity_observations', ['terminal_id', 'timestamp']),
    ('live_demo_events', ['session_id', 'sequence']),
]:
    Index('ix_'+table_name+'_readiness', *(Base.metadata.tables[table_name].c[c] for c in columns))
