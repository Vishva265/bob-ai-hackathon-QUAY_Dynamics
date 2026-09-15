from typing import Literal
from pydantic import Field, model_validator
from app.schemas import DTO, Identifier, UTC

EventKind = Literal['eta_delay', 'early_arrival', 'crane_breakdown', 'crane_recovery', 'severe_wind',
                    'yard_capacity_reduction', 'berth_closure', 'priority_arrival', 'clock_tick',
                    'storm_crane_failure', 'storm_crane_recovery']


class StartInput(DTO):
    port_id: Identifier = 'P01'
    source_run_id: Identifier | None = None
    seed: int = Field(default=42, ge=0, le=2147483647)
    time_limit_seconds: float = Field(default=2, ge=.1, le=5)


class EventInput(DTO):
    kind: EventKind
    expected_revision: int = Field(ge=1)
    advance_minutes: int = Field(default=15, ge=15, le=240, multiple_of=15)
    call_id: Identifier | None = None
    crane_id: Identifier | None = None
    berth_id: Identifier | None = None
    terminal_id: Identifier | None = None
    hours: float = Field(default=6, gt=0, le=48)
    duration_hours: int = Field(default=8, ge=1, le=48)
    wind_mps: float = Field(default=18, ge=10, le=45)
    capacity_pct: float = Field(default=75, ge=20, lt=100)
    actor: str = Field(default='Demo operator', min_length=1, max_length=120, pattern=r'\S')

    @model_validator(mode='after')
    def entity(self):
        field = {'eta_delay':'call_id','early_arrival':'call_id','priority_arrival':'call_id',
                 'crane_breakdown':'crane_id','crane_recovery':'crane_id','berth_closure':'berth_id',
                 'yard_capacity_reduction':'terminal_id'}.get(self.kind)
        if field and not getattr(self, field):
            raise ValueError(f'{field} is required for {self.kind}')
        return self


class SessionOut(DTO):
    id: str
    port_id: str
    created_at: UTC
    clock: UTC
    revision: int
    status: str
    latest_run_id: str | None
    initial_run_id: str | None
    active_event_id: str | None
    settings: dict


class EventOut(DTO):
    id: str
    session_id: str
    sequence: int
    kind: str
    status: str
    stage_revision: int
    created_at: UTC
    updated_at: UTC
    operational_time: UTC
    payload: dict
    result: dict | None
    error: dict | None
