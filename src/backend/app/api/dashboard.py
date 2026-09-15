from fastapi import APIRouter
from app.api.operations import DB
from app.schemas import Identifier,OptimisationOut,ErrorResponse
from app.services.dashboard import DashboardService,DashboardOut,DashboardScenarioInput

router=APIRouter(tags=['dashboard'],responses={c:{'model':ErrorResponse} for c in (404,409,422,503)})


@router.get('/dashboard',response_model=DashboardOut)
def dashboard(db:DB,run_id:Identifier|None=None,include_explanations:bool=False,
    include_berths:bool=False):
    return DashboardService(db).output(run_id, include_explanations, include_berths)


@router.post('/dashboard/scenarios',response_model=OptimisationOut,status_code=201)
def simulate(payload:DashboardScenarioInput,db:DB):
    service=DashboardService(db)
    run=service.simulate(payload)
    from app.services.planning import PlanningService
    return PlanningService(db).output(run)
