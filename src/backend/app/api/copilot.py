from typing import Annotated
from fastapi import APIRouter,Depends,Request,Query
from app.copilot.retrieval import search
from sqlalchemy.orm import Session
from app.copilot.schemas import CopilotInput,CopilotOut,ToolInput,ToolName
from app.services.copilot import CopilotService
from app.repositories.copilot import CopilotTools
from app.schemas import ErrorResponse
from app.copilot.provider import provider_status
from sqlalchemy import select
from app import models as m


def readonly_session(request:Request):
    engine=getattr(getattr(request,'state',None),'engine',request.app.state.engine)
    with engine.connect() as connection:
        sqlite=connection.dialect.name=='sqlite'
        try:
            connection.exec_driver_sql('PRAGMA query_only=ON' if sqlite else 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            if sqlite:connection.exec_driver_sql('BEGIN')
            with Session(bind=connection,autoflush=False) as session:yield session
        finally:
            connection.rollback()
            if sqlite:
                connection.exec_driver_sql('PRAGMA query_only=OFF')
                connection.commit()


ReadDB=Annotated[Session,Depends(readonly_session,scope='function')]
router=APIRouter(tags=['copilot'],responses={c:{'model':ErrorResponse} for c in (404,409,422,503)})


@router.post('/copilot/query',response_model=CopilotOut)
@router.post('/copilot/ask',response_model=CopilotOut)
def query(payload:CopilotInput,db:ReadDB):
    return CopilotService(db).query(payload)


@router.get('/copilot/status')
def status():
    return dict(provider_status(), mcp={'implemented':True,'transport':'stdio','server':'quay-operations','authentication':'same operator key as dashboard'},
                retrieval={'method':'BM25 + character TF-IDF','citations':True,'local':True})


@router.get('/copilot/knowledge')
def knowledge(q: str = Query(min_length=2,max_length=1000), limit: int = Query(default=4,ge=1,le=8)):
    return {'query':q, 'sources':search(q,limit), 'method':'BM25 + character TF-IDF'}


@router.get('/copilot/tools')
def tools():
    return {'mode':'read_only','tools':[{'name':name,'writes_operational_data':False} for name in ToolName.__args__]}


@router.get('/copilot/runs')
def runs(db:ReadDB):
    rows=db.scalars(select(m.OptimisationRun).order_by(m.OptimisationRun.created_at.desc()).limit(40))
    return {'runs':[{'run_id':r.id,'as_of':r.as_of,'port_ids':r.input_snapshot['port_ids'],
                    'scenario':bool(r.scenario_id),'status':r.status} for r in rows]}


@router.post('/copilot/tools/{name}')
def retrieve(name:ToolName,payload:ToolInput,db:ReadDB):
    return CopilotTools(db).retrieve(name,payload)
