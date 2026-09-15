import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ObjectiveWeights(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    waiting: float = Field(default=30, ge=0, le=100000)
    departure_delay: float = Field(default=10, ge=0, le=100000)
    yard_congestion: float = Field(default=1, ge=0, le=100000)
    crane_overtime: float = Field(default=5, ge=0, le=100000)
    unused_berth_capacity: float = Field(default=.1, ge=0, le=100000)
    priority_delay: float = Field(default=30, ge=0, le=100000)
    reassignment: float = Field(default=20, ge=0, le=100000)
    rerouting: float = Field(default=1, ge=0, le=100000)
    emissions: float = Field(default=5, ge=0, le=100000)
    prediction_risk: float = Field(default=10, ge=0, le=100000)
    fairness_delay: float = Field(default=100, ge=0, le=100000)
    deferral: float = Field(default=100000, ge=1, le=1000000)


class OptimisationPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    weights: ObjectiveWeights = Field(default_factory=ObjectiveWeights)
    allow_deferral: bool = True
    allow_rerouting: bool = False
    replan_approved: bool = False
    freeze_minutes: int = Field(default=120, ge=0, le=4320)
    yard_safe_fraction: float = Field(default=.90, ge=.4, le=1)
    yard_productivity_min_fraction: float = Field(default=.60, ge=.4, le=1)
    yard_productivity_headroom_fraction: float = Field(default=.05, ge=0, le=.2)
    yard_congestion_fraction: float = Field(default=.75, ge=0, le=1)
    berth_entry_buffer_minutes: int = Field(default=15, ge=15, le=120, multiple_of=15)
    berth_exit_buffer_minutes: int = Field(default=15, ge=15, le=120, multiple_of=15)
    alongside_clearance_m: float = Field(default=.3, ge=0, le=3)
    target_turnaround_hours: float = Field(default=24, gt=0, le=120)
    fair_wait_threshold_hours: float = Field(default=24, ge=1, le=120)
    prediction_reference_wait_hours: float = Field(default=8, gt=0, le=120)
    regular_crane_hours_per_day: float = Field(default=16, gt=0, le=24)
    transit_speed_knots: float = Field(default=18, gt=0, le=30)
    waiting_cost_usd_per_hour: float = Field(default=1000, ge=0, le=1000000)
    departure_delay_cost_usd_per_hour: float = Field(default=400, ge=0, le=1000000)
    crane_overtime_cost_usd_per_hour: float = Field(default=100, ge=0, le=10000)
    deferral_cost_usd: float = Field(default=50000, ge=0, le=10000000)
    reroute_fixed_cost_usd: float = Field(default=2000, ge=0, le=10000000)
    reroute_cost_usd_per_nm: float = Field(default=5, ge=0, le=10000)
    waiting_co2_tonnes_per_hour: float = Field(default=.8, ge=0, le=100)
    sailing_co2_tonnes_per_nm: float = Field(default=.02, ge=0, le=10)
    max_candidates_per_call: int = Field(default=30, ge=10, le=250)
    yard_capacity_certificates: dict[str, float] = Field(default_factory=dict)

    @classmethod
    def configured(cls):
        path = os.getenv('OPTIMISATION_POLICY_FILE')
        if not path:
            return cls()
        return cls.model_validate(json.loads((Path(__file__).resolve().parents[3] / path).read_text()))
