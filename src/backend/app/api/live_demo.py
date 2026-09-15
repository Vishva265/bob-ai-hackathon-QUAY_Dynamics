"""Thin live-demo HTTP/SSE adapters. All state and scheduling stay in services."""
import asyncio
import re
from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Request, Header, Query
from fastapi.responses import StreamingResponse
from app.database import session_factory
from app.errors import DomainError
from app.live.schemas import StartInput, EventInput, SessionOut, EventOut
from app.schemas import ApprovalInput, ErrorResponse

router=APIRouter(tags=['live operations demo'],responses={c:{'model':ErrorResponse} for c in (404,409,422,503)})


def manager(request):return request.app.state.live_demo


def demo_context(request:Request,demo_id:str):
    request.state.engine=manager(request).branch(demo_id)
    request.state.sessions=session_factory(request.state.engine)


@router.post('/live-demo/sessions',response_model=SessionOut,status_code=201)
def start(payload:StartInput,request:Request):return manager(request).start(payload)


@router.get('/live-demo/{demo_id}',response_model=SessionOut)
def session(demo_id:str,request:Request):return manager(request).get(demo_id)


@router.get('/live-demo/{demo_id}/events')
def events(demo_id:str,request:Request,limit:Annotated[int,Query(ge=1,le=100)]=50):
    return {'items':manager(request).events(demo_id,limit)}


@router.post('/live-demo/{demo_id}/events',response_model=EventOut,status_code=202)
def inject(demo_id:str,payload:EventInput,request:Request,background:BackgroundTasks):
    service=manager(request);event=service.enqueue(demo_id,payload)
    background.add_task(service.process,event.id)
    return event


@router.post('/live-demo/{demo_id}/events/{event_id}/retry',response_model=EventOut,status_code=202)
def retry(demo_id:str,event_id:str,payload:ApprovalInput,request:Request,background:BackgroundTasks):
    service=manager(request);event=service.retry(demo_id,event_id,payload.expected_revision)
    background.add_task(service.process,event.id)
    return event


@router.get('/live-demo/{demo_id}/stream')
async def stream(demo_id:str,request:Request,after:str='0.0',last_event_id:Annotated[str|None,Header()]=None,
                 once:bool=False):
    service=manager(request);service.get(demo_id)
    cursor=last_event_id or after
    if not re.fullmatch(r'\d{1,9}\.\d{1,9}',cursor):raise DomainError('INVALID_EVENT_CURSOR','SSE cursor must be sequence.stage',422)
    async def updates():
        position=tuple(map(int,cursor.split('.')))
        while not await request.is_disconnected():
            current=await asyncio.to_thread(service.get,demo_id)
            yield 'event: session\ndata: '+current.model_dump_json()+'\n\n'
            rows=await asyncio.to_thread(service.events,demo_id,100)
            for row in reversed(rows):
                next_position=(row.sequence,row.stage_revision)
                if next_position>position:
                    position=next_position
                    yield f'id: {row.sequence}.{row.stage_revision}\nevent: operation\ndata: '+row.model_dump_json()+'\n\n'
            if once:return
            yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(updates(),media_type='text/event-stream',headers={
        'Cache-Control':'no-cache','X-Accel-Buffering':'no','Connection':'keep-alive'})
