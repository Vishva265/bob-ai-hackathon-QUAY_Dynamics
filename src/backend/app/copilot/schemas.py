from typing import Literal
from pydantic import Field, field_validator
from app.schemas import DTO, Identifier, UTC

Intent = Literal['auto','forecast','vessel_risk','assignment','scenario_comparison','arrival_what_if','routing','shift_summary','plan_summary']
ToolName = Literal['forecast_data','optimisation_results','vessel_details','recommendations','shift_plans','scenario_comparisons']


class ToolInput(DTO):
    run_id: Identifier | None = None
    port_id: Identifier | None = None
    terminal_id: Identifier | None = None
    call_id: Identifier | None = None
    compare_run_id: Identifier | None = None
    shift_index: int = Field(default=0, ge=0, le=8)
    arrival_delay_hours: float | None = Field(default=None, gt=0, le=48)


class CopilotInput(ToolInput):
    question: str = Field(min_length=1, max_length=1000, pattern=r'\S')
    intent: Intent = 'auto'
    # Deliberately untrusted: never interpreted, echoed or sent to a provider.
    context_notes: str | None = Field(default=None, max_length=8000)
    # Accepted for client compatibility, NEVER used as operational evidence.
    # Trusted context is retrieved by run/port/terminal/call IDs on the server.
    operational_context: dict[str, str | float | int | bool | None] | None = Field(default=None, max_length=32)

    @field_validator('operational_context')
    @classmethod
    def bounded_context(cls, value):
        if value and any(len(k) > 100 or (isinstance(v, str) and len(v) > 1000) for k, v in value.items()):
            raise ValueError('Context keys/strings exceed the allowed limit')
        return value


class Evidence(DTO):
    id: str
    label: str
    value: float | int | str | bool | None
    unit: str
    tool: ToolName
    record_id: str
    field: str
    source_run_id: str
    shift_index: int | None = Field(default=None, ge=0, le=8)


class SuggestedAction(DTO):
    text: str
    human_approval_required: bool = True
    executable: bool = False


class CopilotOut(DTO):
    direct_answer: str
    supporting_figures: list[Evidence]
    data_timestamp: UTC
    generated_at: UTC
    optimisation_run_id: str
    forecast_run_id: str
    model_version: str | None
    comparison_run_id: str | None = None
    hypothetical_run_id: str | None = None
    confidence: str
    assumptions: list[str]
    suggested_action: SuggestedAction | None = None
    reasons: list[str]
    tools_used: list[ToolName]
    mode: Literal['template','watsonx','template-fallback']
    provider: Literal['template','watsonx','template-fallback'] = 'template'
    model: str | None = None
    success: Literal[True] = True
    question: str = ''
    answer: str = ''
    provider_status: str
    intent: str
    plan_modified: Literal[False] = False
