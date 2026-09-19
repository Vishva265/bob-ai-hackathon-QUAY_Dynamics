"""Live protocol test: initialize stdio, discover tools, and compare with REST."""
import asyncio
import json
import os
from pathlib import Path
import sys

import requests
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    environment=dict(os.environ)
    environment.setdefault('QUAY_OPERATOR_KEY','quay-local-demo-only-operator-key-2026')
    environment.setdefault('QUAY_API_URL','http://127.0.0.1:8000/api/v1')
    params=StdioServerParameters(command=sys.executable,args=['-m','app.mcp.server'],
        cwd=str(Path(__file__).resolve().parents[1]),env=environment)
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools=await session.list_tools()
            assert len(tools.tools)==6
            assert all(t.annotations.readOnlyHint for t in tools.tools)
            async def call(name,arguments):
                result=await session.call_tool(name,arguments)
                assert not result.isError,result.content
                return json.loads(result.content[0].text)
            runs=await call('list_operation_runs',{})
            run_id=next(r['run_id'] for r in runs['runs'] if not r['scenario'])
            evidence=await call('get_operational_evidence',{'tool':'vessel_details','run_id':run_id})
            base=environment['QUAY_API_URL']
            demo=environment.get('QUAY_DEMO_ID')
            if demo:base+='/live-demo/'+demo
            response=requests.post(base+'/copilot/tools/vessel_details',json={'run_id':run_id},
                headers={'X-Operator-Key':environment['QUAY_OPERATOR_KEY']},timeout=30)
            response.raise_for_status()
            assert evidence==response.json()
            knowledge=await call('search_knowledge',{'question':'How does MCP connect IBM Bob?'})
            assert knowledge['sources'][0]['source']=='docs/bob-mcp.md'
            answer=await call('ask_operations',{'question':'How does MCP connect IBM Bob?','run_id':run_id})
            assert answer['knowledge_sources'] and not answer['plan_modified']
            replay=await call('get_historical_replay',{})
            assert replay['available'] and len(replay['hourly_comparison'])==72
            print(json.dumps({'protocol':'stdio','tools':len(tools.tools),'run_id':run_id,
                'rest_evidence_identical':True,'knowledge_citations':True,'historical_replay':True}))


if __name__=='__main__':
    asyncio.run(main())
