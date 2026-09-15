"""Validated read-only publication of the offline hackathon benchmark."""
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.errors import DomainError
from app.schemas import DTO, UTC


class EvaluationRow(DTO):
    model_config={'extra':'allow'}
    scenario_id: Literal['normal_operations','arrival_surge','storm_crane_breakdown']
    strategy_id: Literal['fcfs','berth_only','berth_crane','predictive_routing']
    scenario: str
    strategy: str
    cohort_vessels: int = Field(ge=0)
    served_vessels: int = Field(ge=0)
    deferred_vessels: int = Field(ge=0)
    average_wait_hours: float | None = Field(ge=0)
    p90_wait_hours: float | None = Field(ge=0)
    maximum_wait_hours: float | None = Field(ge=0)
    total_delay_hours: float = Field(ge=0)
    berth_utilisation: float = Field(ge=0,le=1)
    crane_utilisation: float = Field(ge=0,le=1)
    estimated_cost_savings_usd: float
    estimated_emissions_savings_tonnes_co2: float
    solver_runtime_ms: int = Field(ge=0)
    validation_passed: Literal[True]

    @model_validator(mode='after')
    def accounts_for_demand(self):
        if self.served_vessels+self.deferred_vessels!=self.cohort_vessels:
            raise ValueError('Served and deferred counts do not account for demand')
        return self


class EvaluationPublication(DTO):
    model_config={'extra':'allow'}
    schema_version: Literal['strategy-evaluation-v1']
    synthetic: Literal[True]
    real_world_validated: Literal[False]
    generated_at: UTC
    model_version: str
    rows: list[EvaluationRow] = Field(min_length=12,max_length=12)

    @model_validator(mode='after')
    def paired_design(self):
        keys={(r.scenario_id,r.strategy_id) for r in self.rows}
        if len(keys)!=12:raise ValueError('Duplicate or missing strategy comparisons')
        for scenario in {r.scenario_id for r in self.rows}:
            if len({r.cohort_vessels for r in self.rows if r.scenario_id==scenario})!=1:
                raise ValueError('Unpaired vessel cohorts')
        return self


def directory():
    root=Path(__file__).resolve().parents[3]
    return (root/os.getenv('EVALUATION_DIRECTORY','artifacts/evaluation')).resolve()


def latest():
    try:
        path=directory()/'summary.json'
        if path.stat().st_size>8*1024*1024:raise ValueError('Oversized evaluation publication')
        return EvaluationPublication.model_validate_json(path.read_text(encoding='utf-8'))
    except FileNotFoundError as e:
        raise DomainError('EVALUATION_NOT_READY','Run backend/scripts/evaluate.py to publish the benchmark',404) from e
    except (ValueError,OSError,json.JSONDecodeError) as e:
        raise DomainError('EVALUATION_INVALID','Stored evaluation publication failed validation; regenerate it',503) from e
