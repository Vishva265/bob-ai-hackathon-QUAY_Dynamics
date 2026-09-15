"""Validated HTTP DTOs with explicit units and UTC instants."""
from datetime import timezone
from typing import Annotated, Literal

from pydantic import (AwareDatetime, BaseModel, ConfigDict, Field, AfterValidator,
                      create_model, model_validator)

from app.synthetic.schema import SCHEMA, ENUMS
from app.early_warning.rules import AlertRules
from app.optimisation.config import OptimisationPolicy

UTC = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]
Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_.:-]+$')]
Quantity = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class DTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='forbid', allow_inf_nan=False)


def source_response(name, table):
    fields = {}
    for key, spec in SCHEMA[table].items():
        kind = {'str': str, 'int': int, 'float': float, 'time': UTC}[spec.kind]
        if (table, key) in ENUMS:
            kind = Literal[tuple(sorted(ENUMS[(table, key)]))]
        if spec.nullable:
            kind = kind | None
        fields[key] = (kind, Field(description=f'{spec.description} Unit: {spec.unit}.'))
    return create_model(name, __base__=DTO, **fields)


PortOut = source_response('PortOut', 'ports')
TerminalOut = source_response('TerminalOut', 'terminals')
BerthOut = source_response('BerthOut', 'berths')
CraneOut = source_response('CraneOut', 'cranes')
CallOut = source_response('CallOut', 'vessel_calls')
YardOut = source_response('YardOut', 'yard_snapshots')
WeatherOut = source_response('WeatherOut', 'weather')
TideOut = source_response('TideOut', 'tides')
DisruptionOut = source_response('DisruptionOut', 'disruptions')


class PortPage(DTO):
    items: list[PortOut]
    next_cursor: str | None


class CallPage(DTO):
    items: list[CallOut]
    next_cursor: str | None


class CallCreate(DTO):
    id: Identifier | None = None
    vessel_id: Identifier
    terminal_id: Identifier
    scheduled_eta: UTC
    priority: int = Field(default=3, ge=1, le=5)
    cargo_type: Literal['general', 'reefer', 'hazardous'] = 'general'
    onboard_teu: int = Field(ge=0)
    unload_moves: int = Field(ge=0)
    load_moves: int = Field(ge=0)
    teu_per_move: float = Field(default=1.5, ge=1, le=2)

    @model_validator(mode='after')
    def demand(self):
        if self.unload_moves + self.load_moves == 0:
            raise ValueError('At least one container move is required')
        return self


class ForecastInput(DTO):
    as_of: UTC
    horizon_hours: Literal[72] = 72
    port_ids: list[Identifier] | None = Field(default=None, min_length=1, max_length=50)
    predictor: Literal['auto', 'baseline', 'ml'] = 'auto'


class OptimisationInput(ForecastInput):
    forecast_run_id: Identifier | None = None
    time_limit_seconds: float = Field(default=5, ge=.1, le=10)
    policy: OptimisationPolicy | None = None


class IntervalOverride(DTO):
    start: UTC
    end: UTC

    @model_validator(mode='after')
    def interval(self):
        if self.end <= self.start:
            raise ValueError('end must follow start')
        return self


class ArrivalChange(DTO):
    kind: Literal['arrival_change']
    call_id: Identifier
    scheduled_eta: UTC


class CraneOutage(IntervalOverride):
    kind: Literal['crane_outage']
    crane_id: Identifier


class StormOverride(IntervalOverride):
    kind: Literal['storm']
    port_id: Identifier


class YardOverride(DTO):
    kind: Literal['yard_capacity']
    terminal_id: Identifier
    capacity_teu: Quantity


Override = Annotated[ArrivalChange | CraneOutage | StormOverride | YardOverride, Field(discriminator='kind')]


class ScenarioInput(ForecastInput):
    name: str = Field(min_length=1, max_length=120)
    overrides: list[Override] = Field(min_length=1, max_length=100)
    time_limit_seconds: float = Field(default=5, ge=.1, le=10)
    policy: OptimisationPolicy | None = None


class ApprovalInput(DTO):
    actor: str = Field(min_length=1, max_length=120, pattern=r'\S')
    expected_revision: int = Field(ge=1)


class Reason(DTO):
    code: str
    message: str
    evidence: dict


class ForecastOut(DTO):
    id: str
    run_id: str
    port_id: str
    berth_id: str
    timestamp: UTC
    demand_moves: float
    capacity_moves: float
    pressure_ratio: float | None
    alert: bool
    reasons: list[Reason]


class ForecastPage(DTO):
    items: list[ForecastOut]
    next_cursor: str | None


class ForecastRunOut(DTO):
    id: str
    as_of: UTC
    horizon_hours: int
    method: str
    quality: str
    created_at: UTC
    input_hash: str
    bucket_count: int
    model_version: str | None
    predictive_bucket_count: int
    waiting_prediction_count: int


class EarlyWarningInput(ForecastInput):
    predictor: Literal['ml'] = 'ml'
    rules: AlertRules | None = None


class HotspotWindow(DTO):
    start: UTC
    end: UTC
    duration_hours: int


class EntityHotspotSummary(DTO):
    scope: Literal['port', 'terminal', 'berth']
    scope_id: str
    port_id: str
    first_expected_hotspot_time: UTC | None
    expected_hotspot_duration_hours: int
    total_hotspot_hours: int
    windows: list[HotspotWindow]
    peak_queue_length: Quantity
    peak_wait_hours: Quantity
    low_confidence_hours: int


class EarlyWarningRunOut(ForecastRunOut):
    operational_bucket_count: int
    projection_method: str
    rules: AlertRules
    summaries: list[EntityHotspotSummary]
    alert_counts: dict[str, int]
    assumptions: list[str]


class ForecastThreshold(DTO):
    code: str
    metric: str
    value: Quantity
    threshold: Quantity
    unit: str
    alert_enabled: bool | None
    explanation: str


class ForecastSource(DTO):
    kind: str
    label: str
    source_type: Literal['OBSERVED', 'SCHEDULED', 'FORECAST_ASSUMPTION', 'SCENARIO_OVERRIDE']
    source_timestamp: UTC | None = None
    effective_timestamp: UTC | None = None
    start: UTC | None = None
    end: UTC | None = None
    age_hours: Quantity | None = None
    freshness: Literal['FRESH', 'STALE', 'NOT_APPLICABLE', 'UNKNOWN']
    values: dict
    assumptions: list[str]


class ForecastExplanation(DTO):
    forecast_run_id: str
    input_hash: str
    projection_method: str | None
    severity_explanation: str
    triggered_thresholds: list[ForecastThreshold]
    confidence_explanation: str
    inputs: list[ForecastSource]
    operator_interpretation: str
    supervisor_action: Literal['Monitor', 'Review before next shift', 'Run rolling replan', 'Escalate for approval']
    action_reason: str
    human_approval_required: bool
    plan_status: str | None
    assumptions: list[str]
    missing_provenance: list[str]


class OperationalForecastOut(DTO):
    id: str
    run_id: str
    scope: Literal['port', 'terminal', 'berth']
    scope_id: str
    port_id: str
    terminal_id: str | None
    berth_id: str | None
    timestamp: UTC
    berth_utilisation: float = Field(ge=0, le=1)
    queue_length: Quantity
    average_wait_hours: Quantity
    yard_occupancy: float = Field(ge=0, le=1)
    crane_utilisation: float = Field(ge=0, le=1)
    congestion_probability: float = Field(ge=0, le=1)
    probability_lower: float = Field(ge=0, le=1)
    probability_upper: float = Field(ge=0, le=1)
    probability_basis: Literal['trained_scope_model', 'terminal_model_prior']
    congestion_severity: Literal['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
    confidence_level: Literal['LOW', 'MEDIUM', 'HIGH']
    confidence_reasons: list[str]
    main_causes: list[Reason]
    arrival_workload_ratio: Quantity
    arrival_workload_increase_moves: Quantity
    is_hotspot: bool
    first_expected_hotspot_time: UTC | None
    expected_hotspot_duration_hours: int
    model_version: str
    prediction_timestamp: UTC
    explanation: ForecastExplanation | None = None


class OperationalForecastPage(DTO):
    items: list[OperationalForecastOut]
    next_cursor: str | None


class AlertOut(DTO):
    id: str
    active_key: str | None
    scope: Literal['port', 'terminal', 'berth']
    scope_id: str
    port_id: str
    terminal_id: str | None
    berth_id: str | None
    rule_code: str
    state: Literal['OPEN', 'ACKNOWLEDGED', 'RESOLVED']
    revision: int
    opened_at: UTC
    updated_at: UTC
    first_run_id: str
    last_run_id: str
    expected_start: UTC
    expected_end: UTC
    duration_hours: int
    evidence: dict
    acknowledged_by: str | None
    acknowledged_at: UTC | None
    resolved_at: UTC | None


class AlertPage(DTO):
    items: list[AlertOut]
    next_cursor: str | None


class AlertEventOut(DTO):
    id: str
    alert_id: str
    run_id: str
    action: str
    actor: str | None
    occurred_at: UTC
    revision: int
    evidence: dict


class AlertEventPage(DTO):
    items: list[AlertEventOut]
    next_cursor: str | None


class OperationalFactor(DTO):
    feature: str
    observed_value: float
    reference_value: float
    contribution: float
    contribution_unit: Literal['hours', 'probability']
    feature_unit: str
    method: Literal['one_feature_to_training_median']


class PredictionOut(DTO):
    id: str
    run_id: str
    prediction: Quantity
    lower: Quantity
    upper: Quantity
    uncertainty_method: str
    nominal_coverage: float
    factors: list[OperationalFactor]
    model_version: str
    prediction_timestamp: UTC
    quality: str


class CongestionPredictionOut(PredictionOut):
    port_id: str
    terminal_id: str | None
    scope: Literal['port', 'terminal']
    scope_id: str
    timestamp: UTC
    level: Literal['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
    level_probabilities: dict[str, float]


class CongestionPredictionPage(DTO):
    items: list[CongestionPredictionOut]
    next_cursor: str | None


class WaitingPredictionOut(PredictionOut):
    call_id: str
    port_id: str
    terminal_id: str
    scheduled_eta: UTC


class WaitingPredictionPage(DTO):
    items: list[WaitingPredictionOut]
    next_cursor: str | None


class ModelMetadataOut(DTO):
    model_version: str
    feature_version: str
    trained_at: UTC
    observation_cutoff: UTC
    quality: str
    selected_models: dict[str, str]
    dataset_rows: dict[str, int]
    evaluation: dict
    labels: dict
    assumptions: list[str]


class PlannedCraneOut(DTO):
    id: str
    crane_id: str
    start: UTC
    end: UTC


class AssignmentOut(DTO):
    id: str
    call_id: str
    berth_id: str
    start: UTC
    end: UTC
    waiting_minutes: int
    planned_moves: int
    completion_time: UTC | None = None
    execution_profile: dict | None = None
    superseded_at: UTC | None = None
    reasons: list[Reason]
    cranes: list[PlannedCraneOut]


class RecommendationOut(DTO):
    id: str
    call_id: str
    kind: str
    alternate_port_id: str | None
    adjusted_eta: UTC | None
    reasons: list[Reason]


class ShiftTaskOut(DTO):
    call_id: str
    berth_id: str
    crane_ids: list[str]
    start: UTC
    end: UTC
    planned_moves: Quantity
    task_type: Literal['container_handling', 'wait_for_resources_or_weather', 'await_departure_confirmation']
    owner_role: str
    handover_required: bool


class ShiftOut(DTO):
    id: str
    shift_index: int
    start: UTC
    end: UTC
    tasks: list[ShiftTaskOut]
    details: dict | None = None


class PlanOut(DTO):
    id: str
    run_id: str
    status: Literal['DRAFT', 'REVIEWED', 'APPROVED', 'SUPERSEDED']
    revision: int
    approved_by: str | None
    approved_at: UTC | None
    shifts: list[ShiftOut]
    previous_plan_id: str | None = None
    reviewed_by: str | None = None
    reviewed_at: UTC | None = None
    document: dict | None = None


class OptimisationOut(DTO):
    id: str
    forecast_run_id: str
    scenario_id: str | None
    as_of: UTC
    end: UTC
    status: str
    solver_status: str
    created_at: UTC
    runtime_ms: int
    diagnostics: dict
    assignments: list[AssignmentOut]
    recommendations: list[RecommendationOut]
    plan: PlanOut | None
    metrics: dict | None = None
    objective_breakdown: dict | None = None
    comparison: dict | None = None
    schedule_source: str | None = None
    solver_runtime_ms: int | None = None


class ResourceOut(DTO):
    id: str
    resource_type: Literal['berth', 'crane', 'yard']
    terminal_id: str
    capacity: float
    unit: str
    unavailable_intervals: list[dict]


class ResourcePage(DTO):
    items: list[ResourceOut]
    next_cursor: str | None
    start: UTC
    end: UTC


class YardOccupancyOut(DTO):
    terminal_id: str
    inventory_teu: Quantity
    capacity_teu: Quantity
    utilisation: Quantity
    observed_at: UTC


class PortStatus(DTO):
    port: PortOut
    as_of: UTC
    terminals: int
    berths: int
    cranes: int
    upcoming_calls_72h: int
    yard_snapshots: list[YardOut]
    weather: WeatherOut | None
    tide: TideOut | None
    disruptions: list[DisruptionOut]
    missing_observations: list[str]
    yard_occupancy: list[YardOccupancyOut]


class ErrorDetail(DTO):
    field: str
    reason: str


class ErrorInfo(DTO):
    code: str
    message: str
    details: list[ErrorDetail]
    request_id: str | None


class ErrorResponse(DTO):
    error: ErrorInfo
