import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from app.schemas import DTO, Identifier, UTC

Action = Literal['KEEP_CURRENT_PLAN', 'SLOW_STEAM_OR_DELAY_ARRIVAL', 'EARLIER_ARRIVAL', 'ALTERNATE_TERMINAL', 'ALTERNATE_PORT']


class RecommendationPolicy(DTO):
    severe_wait_hours: float = Field(default=8, ge=0, le=120)
    maximum_diversion_nm: float = Field(default=400, gt=0, le=2000)
    minimum_diversion_hours_saved: float = Field(default=4, ge=0, le=120)
    minimum_net_benefit_usd: float = Field(default=1000, ge=0, le=1000000)
    minimum_conservative_hours_saved: float = Field(default=0, ge=0, le=120)
    time_value_usd_per_hour: float = Field(default=1000, ge=0, le=100000)
    carbon_value_usd_per_tonne: float = Field(default=50, ge=0, le=10000)
    uncertainty_cost_usd_per_hour: float = Field(default=100, ge=0, le=100000)
    fuel_price_usd_per_tonne: float = Field(default=700, gt=0, le=10000)
    reference_fuel_tonnes_per_nm: float = Field(default=.05, gt=0, le=10)
    reference_speed_knots: float = Field(default=18, gt=0, le=30)
    anchorage_fuel_tonnes_per_hour: float = Field(default=.15, ge=0, le=10)
    co2_tonnes_per_fuel_tonne: float = Field(default=3.1, gt=0, le=5)
    terminal_transfer_nm: float = Field(default=5, ge=0, le=50)
    uncertainty_fallback_hours: float = Field(default=24, gt=0, le=120)
    expiry_minutes: int = Field(default=60, ge=1, le=240)
    maximum_position_age_hours: float = Field(default=4, gt=0, le=24)
    search_step_minutes: int = Field(default=60, ge=15, le=120, multiple_of=15)

    @classmethod
    def configured(cls):
        path = os.getenv('RECOMMENDATION_POLICY_FILE')
        return cls.model_validate(json.loads((Path(__file__).resolve().parents[3]/path).read_text())) if path else cls()


class VoyageInput(DTO):
    call_id: Identifier
    position_as_of: UTC
    remaining_distance_nm: float = Field(ge=0, le=10000)
    planned_speed_knots: float = Field(default=18, gt=0, le=30)
    minimum_speed_knots: float = Field(default=10, gt=0, le=30)
    maximum_speed_knots: float = Field(default=22, gt=0, le=30)
    eta_uncertainty_hours: float = Field(default=2, ge=0, le=72)
    customer_deadline: UTC
    source_label: str = Field(min_length=3, max_length=240)

    @model_validator(mode='after')
    def speed_limits(self):
        if not self.minimum_speed_knots <= self.planned_speed_knots <= self.maximum_speed_knots:
            raise ValueError('minimum <= planned <= maximum speed is required')
        if self.customer_deadline <= self.position_as_of:
            raise ValueError('Customer deadline must follow position observation')
        return self


class TerminalTariff(DTO):
    terminal_id: Identifier
    port_call_usd: float = Field(ge=0, le=1000000)
    handling_usd_per_move: float = Field(ge=0, le=1000)
    inland_usd_per_teu: float = Field(ge=0, le=10000)
    inland_hours: float = Field(ge=0, le=240)
    inland_uncertainty_hours: float = Field(default=2, ge=0, le=72)
    inland_co2_tonnes_per_teu: float = Field(ge=0, le=1)
    handling_co2_tonnes_per_move: float = Field(default=.001, ge=0, le=1)
    cargo_booking_confirmed: bool = False
    source_label: str = Field(min_length=3, max_length=240)


class RecommendationInput(DTO):
    source_run_id: Identifier
    call_ids: list[Identifier] | None = Field(default=None, min_length=1, max_length=500)
    voyages: list[VoyageInput] = Field(default_factory=list, max_length=500)
    tariffs: list[TerminalTariff] = Field(default_factory=list, max_length=200)
    policy: RecommendationPolicy | None = None

    @model_validator(mode='after')
    def unique_keys(self):
        for values in (self.call_ids or [], [v.call_id for v in self.voyages], [t.terminal_id for t in self.tariffs]):
            if len(values) != len(set(values)):
                raise ValueError('Duplicate call or terminal inputs are not allowed')
        return self


class WhatIfInput(RecommendationInput):
    call_id: Identifier
    candidate_terminal_ids: list[Identifier] | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def single_call(self):
        if self.call_ids is not None:
            raise ValueError('Use call_id for a single-vessel what-if')
        ids = self.candidate_terminal_ids or []
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate candidate terminals are not allowed')
        return self


class Outcome(DTO):
    terminal_id: Identifier
    berth_id: Identifier
    arrival: UTC
    berth_start: UTC
    service_completion: UTC
    departure: UTC
    expected_delivery: UTC
    delivery_lower: UTC
    delivery_upper: UTC
    planned_wait_hours: float
    raw_model_wait_hours: float | None
    wait_lower_hours: float
    wait_upper_hours: float
    waiting_basis: str
    sailing_hours: float
    sailing_difference_hours: float
    diversion_distance_nm: float
    speed_knots: float
    total_cost_usd: float
    total_co2_tonnes: float
    cost_breakdown: dict[str, float]
    emissions_breakdown: dict[str, float]
    customer_deadline: UTC
    deadline_lateness_hours: float
    deadline_worst_lateness_hours: float
    uncertainty_hours: float
    model_version: str
    capacity_checked: bool
    execution_profile: dict


class ComparisonOption(DTO):
    action: Action
    terminal_id: Identifier | None
    feasible: bool
    eligible: bool
    rejection_codes: list[str]
    evidence: dict
    outcome: Outcome | None
    expected_hours_saved: float | None
    conservative_hours_saved: float | None
    estimated_cost_change_usd: float | None
    estimated_emissions_change_tonnes: float | None
    estimated_net_benefit_usd: float | None


class RecommendationOut(DTO):
    id: Identifier
    run_id: Identifier
    call_id: Identifier
    port_id: Identifier
    recommended_action: Action
    current_plan_outcome: Outcome | None
    recommended_plan_outcome: Outcome | None
    expected_hours_saved: float | None
    estimated_cost_change_usd: float | None
    estimated_emissions_change_tonnes: float | None
    confidence_level: Literal['LOW', 'MEDIUM', 'HIGH']
    main_reasons: list[dict] = Field(min_length=3, max_length=3)
    risks_and_assumptions: list[str]
    expires_at: UTC
    operator_approval_required: bool
    independent_what_if: bool
    is_expired: bool
    operationally_actionable: bool
    options: list[ComparisonOption]


class RecommendationRunOut(DTO):
    id: Identifier
    source_run_id: Identifier
    as_of: UTC
    created_at: UTC
    input_hash: str
    model_version: str
    source_state_changed: bool
    policy: RecommendationPolicy
    summary: dict
    recommendations: list[RecommendationOut]


class RecommendationPage(DTO):
    items: list[RecommendationOut]
    next_cursor: str | None
