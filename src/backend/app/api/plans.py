from typing import Literal
from fastapi import APIRouter, Response
from app import schemas as s, models as m
from app.api.operations import DB
from app.plans.schemas import ReviewInput, ReplanInput
from app.plans.exports import export
from app.repositories.operations import Repository
from app.services.supervisor_plans import SupervisorPlanService
from app.services.rolling_replanning import RollingReplanningService
from app.services.planning import PlanningService

router=APIRouter(tags=['supervisor plans'],responses={code:{'model':s.ErrorResponse} for code in (404,409,422,503)})


@router.get('/plans/state')
def operational_state(db:DB):
    return {'operational_state_revision':Repository(db).get(m.PlanningState,1).revision}


@router.get('/plans/{plan_id}',response_model=s.PlanOut)
def publication(plan_id:s.Identifier,db:DB):
    return SupervisorPlanService(db).get(plan_id)


@router.post('/plans/{plan_id}/review',response_model=s.PlanOut)
def review(plan_id:s.Identifier,payload:ReviewInput,db:DB):
    return SupervisorPlanService(db).review(plan_id,payload)


@router.post('/plans/{plan_id}/replan',response_model=s.OptimisationOut,status_code=201)
def replan(plan_id:s.Identifier,payload:ReplanInput,db:DB):
    run=RollingReplanningService(db).run(plan_id,payload)
    return PlanningService(db).output(run)


@router.get('/plans/{plan_id}/history')
def history(plan_id:s.Identifier,db:DB):
    return {'items':SupervisorPlanService(db).history(plan_id)}


@router.get('/plans/{plan_id}/export',response_class=Response,responses={200:{'content':{
    'application/json':{},'text/csv':{},'text/html':{}}}})
def download(plan_id:s.Identifier,db:DB,format:Literal['json','csv','html']='json'):
    plan=SupervisorPlanService(db).get(plan_id)
    content,media_type=export(plan,format)
    return Response(content,media_type=media_type,headers={'Content-Disposition':f'attachment; filename="plan-{plan_id}.{format}"'})
