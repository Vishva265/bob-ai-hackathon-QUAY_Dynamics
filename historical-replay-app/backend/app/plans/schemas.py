from typing import Annotated, Literal
from pydantic import Field, model_validator
from app.schemas import DTO, UTC, Identifier, Quantity, ApprovalInput


class ReviewInput(ApprovalInput):
    note: str = Field(default='', max_length=1000)


class EtaUpdate(DTO):
    kind: Literal['eta']
    call_id: Identifier
    scheduled_eta: UTC


class ArrivalUpdate(DTO):
    kind: Literal['arrival']
    call_id: Identifier
    timestamp: UTC


class WeatherUpdate(DTO):
    kind: Literal['weather']
    port_id: Identifier
    timestamp: UTC
    wind_mps: float = Field(ge=0, le=100)
    rain_mm_per_hour: float = Field(ge=0, le=500)
    visibility_m: float = Field(ge=0, le=100000)


class CraneUpdate(DTO):
    kind: Literal['crane_availability']
    crane_id: Identifier
    start: UTC
    end: UTC
    reason: Literal['maintenance', 'breakdown']

    @model_validator(mode='after')
    def window(self):
        if self.end <= self.start:
            raise ValueError('Outage end must follow start')
        return self


class YardUpdate(DTO):
    kind: Literal['yard']
    terminal_id: Identifier
    timestamp: UTC
    opening_teu: Quantity
    gate_outbound_teu: Quantity
    inbound_teu: Quantity
    outbound_teu: Quantity
    closing_teu: Quantity
    queued_vessels: int = Field(ge=0, le=10000)

    @model_validator(mode='after')
    def balance(self):
        if abs(self.opening_teu-self.gate_outbound_teu+self.inbound_teu-self.outbound_teu-self.closing_teu) > .01:
            raise ValueError('Observed yard quantities must conserve TEU')
        return self


class CraneRestoration(DTO):
    kind: Literal['crane_restored']
    crane_id: Identifier
    timestamp: UTC


class ProgressUpdate(DTO):
    kind: Literal['progress']
    call_id: Identifier
    berth_id: Identifier
    actual_arrival: UTC
    started_at: UTC
    observed_at: UTC
    completed_unload_moves: int = Field(ge=0)
    completed_load_moves: int = Field(ge=0)
    crane_ids: list[Identifier] = Field(min_length=1, max_length=12)
    departure_at: UTC | None = None

    @model_validator(mode='after')
    def precedence(self):
        if not self.actual_arrival <= self.started_at <= self.observed_at:
            raise ValueError('arrival <= berth start <= observation is required')
        if self.departure_at and not self.started_at <= self.departure_at <= self.observed_at:
            raise ValueError('Departure must follow berth start and precede observation')
        if len(self.crane_ids) != len(set(self.crane_ids)):
            raise ValueError('Duplicate cranes are invalid')
        return self


class YardCapacityUpdate(DTO):
    kind: Literal['yard_capacity']
    terminal_id: Identifier
    timestamp: UTC
    capacity_teu: float = Field(gt=0, le=10000000)


class BerthClosureUpdate(DTO):
    kind: Literal['berth_closure']
    berth_id: Identifier
    start: UTC
    end: UTC

    @model_validator(mode='after')
    def window(self):
        if self.end <= self.start:
            raise ValueError('Closure end must follow start')
        return self


class PriorityArrivalUpdate(DTO):
    kind: Literal['priority_arrival']
    call_id: Identifier
    timestamp: UTC
    priority: int = Field(default=5, ge=1, le=5)


Change = Annotated[EtaUpdate | ArrivalUpdate | WeatherUpdate | CraneUpdate | CraneRestoration | YardUpdate | ProgressUpdate |
                   YardCapacityUpdate | BerthClosureUpdate | PriorityArrivalUpdate, Field(discriminator='kind')]


class ReplanInput(DTO):
    as_of: UTC
    expected_revision: int = Field(ge=1)
    expected_state_revision: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=120, pattern=r'\S')
    changes: list[Change] = Field(default_factory=list, max_length=100)
    predictor: Literal['auto', 'baseline', 'ml'] = 'auto'
    time_limit_seconds: float = Field(default=5, ge=.1, le=10)

    @model_validator(mode='after')
    def unique_changes(self):
        keys = [(c.kind, getattr(c, 'call_id', None) or getattr(c, 'port_id', None) or
                 getattr(c, 'terminal_id', None) or getattr(c, 'crane_id', None) or getattr(c, 'berth_id', None)) for c in self.changes]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate updates for the same entity/kind are invalid')
        for c in self.changes:
            t = getattr(c, 'timestamp', None) or getattr(c, 'observed_at', None)
            if t and t > self.as_of:
                raise ValueError('Observations after planning origin are invalid')
            if c.kind == 'progress' and c.observed_at != self.as_of:
                raise ValueError('Progress must be confirmed at the replanning origin')
            if c.kind == 'crane_availability' and c.reason == 'breakdown' and c.start > self.as_of:
                raise ValueError('Breakdowns must be observed by the planning origin; use scenarios for hypothetical future failures')
        return self
