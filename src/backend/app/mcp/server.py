"""stdio MCP server sharing the authenticated REST tools used by the dashboard."""
import os
import re
from urllib.parse import urlsplit

import requests
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from app.copilot.schemas import ToolName, ToolInput, CopilotInput

mcp = FastMCP('quay-operations')
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


def api(path, body=None, *, scoped=True):
    base = os.getenv('QUAY_API_URL', 'http://127.0.0.1:8000/api/v1').rstrip('/')
    url = urlsplit(base)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('QUAY_API_URL must be an HTTP(S) API origin/path without credentials or query parameters.')
    if url.scheme != 'https' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Remote QUAY_API_URL requires HTTPS.')
    demo_id = os.getenv('QUAY_DEMO_ID', '')
    if demo_id and not re.fullmatch('[a-f0-9]{32}', demo_id):
        raise ValueError('QUAY_DEMO_ID must be the 32-character ID from the dashboard URL.')
    if scoped and demo_id:
        base += '/live-demo/' + demo_id
    key = os.getenv('QUAY_OPERATOR_KEY', '')
    headers = {'X-Operator-Key': key} if key else {}
    try:
        response = requests.request('GET' if body is None else 'POST', base+path,
            json=body, headers=headers, timeout=(5, 120), allow_redirects=False)
    except requests.RequestException as error:
        raise RuntimeError('QUAY is unavailable. Start npm run demo and check QUAY_API_URL.') from error
    if response.status_code == 401:
        raise RuntimeError('Operator authentication required. Set QUAY_OPERATOR_KEY to the dashboard operator key.')
    if response.status_code != 200:
        raise RuntimeError(f'QUAY rejected the request (HTTP {response.status_code}); check scope and API validation.')
    return response.json()


@mcp.tool(annotations=READ)
def get_integration_status() -> dict:
    """Check the running app's actual watsonx provider and retrieval configuration."""
    return api('/copilot/status')


@mcp.tool(annotations=READ)
def list_operation_runs() -> dict:
    """List persisted run IDs and UTC origins. Pass a run_id to keep answers reproducible."""
    return api('/copilot/runs')


@mcp.tool(annotations=READ)
def get_operational_evidence(tool: ToolName, run_id: str, port_id: str | None = None,
        terminal_id: str | None = None, call_id: str | None = None,
        compare_run_id: str | None = None, shift_index: int = 0) -> dict:
    """Read the SAME registered tools used by QUAY: forecasts, schedules, vessels,
    routing, shifts, scenario comparisons or historical comparisons. No writes."""
    payload = ToolInput(run_id=run_id, port_id=port_id, terminal_id=terminal_id,
                        call_id=call_id, compare_run_id=compare_run_id, shift_index=shift_index)
    return api('/copilot/tools/'+tool, payload.model_dump(mode='json'))


@mcp.tool(annotations=READ)
def ask_operations(question: str, run_id: str, port_id: str | None = None,
                   terminal_id: str | None = None, call_id: str | None = None) -> dict:
    """Ask the web app's grounded copilot. Returns cited records, source time, model
    confidence and documentation sources. Cannot approve or change plans."""
    payload = CopilotInput(question=question, run_id=run_id, port_id=port_id,
                           terminal_id=terminal_id, call_id=call_id)
    return api('/copilot/ask', payload.model_dump(mode='json'))


@mcp.tool(annotations=READ)
def search_knowledge(question: str, limit: int = 4) -> dict:
    """Search QUAY's local documentation with hybrid retrieval and source/line citations."""
    from urllib.parse import urlencode
    if not 2 <= len(question) <= 1000 or not 1 <= limit <= 8:
        raise ValueError('Question must be 2..1000 characters and limit 1..8.')
    return api('/copilot/knowledge?'+urlencode({'q':question, 'limit':limit}))


@mcp.tool(annotations=READ)
def get_historical_replay() -> dict:
    """Read the real NOAA AIS replay plan and withheld-outcome evaluation, if prepared."""
    return api('/historical-replay', scoped=False)


if __name__ == '__main__':
    mcp.run(transport='stdio')
