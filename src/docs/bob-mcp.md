# IBM Bob and MCP

QUAY exposes a real stdio MCP server backed by the authenticated API used by
the dashboard. IBM Bob is the development assistant/MCP client. The in-app
copilot separately supports IBM watsonx.ai / Granite; enabling MCP does not
claim that a live Granite response or Bob sign-in has been verified.

## Start

From src, run npm run demo. In a second terminal install the optional adapter:

```powershell
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-mcp.txt
```

Open the repository root in IBM Bob. The project .bob/mcp.json registers
quay-operations. Enable MCP in Bob settings and restart that server. If your
client uses another working directory, set cwd to the repository root or use
an absolute path to src/backend/scripts/start_mcp.py. Bob account sign-in is
handled by Bob; no cloud account or API key is needed to run the local MCP server.

## Tools and evidence

Call list_operation_runs, then ask_operations with a returned run_id. The
get_operational_evidence tool wraps forecast_data, optimisation_results,
vessel_details, recommendations, shift_plans and scenario_comparisons. These
are the same six authenticated backend tools used by the web copilot.
search_knowledge returns local hybrid retrieval with source/line citations.
get_historical_replay reads the integrated NOAA replay and evaluation.
get_integration_status reports the app's configuration, not a claimed cloud login.

## Configuration

QUAY_API_URL defaults to http://127.0.0.1:8000/api/v1. QUAY_OPERATOR_KEY must
match the running app. The tracked Bob config contains only the published
local demo key. Use environment variables or a private global Bob configuration
for real credentials. For an isolated live session, set QUAY_DEMO_ID to the
32-character demo value in the dashboard URL. Remote API URLs require HTTPS.

The server exposes only read tools, refuses redirects, and uses bounded network
timeouts. All operational scope checks and operator authentication remain in
the API. Tool output is operational evidence, never an instruction to dispatch.

## Retrieval

The copilot combines structured persisted operational tools with BM25 and
character TF-IDF retrieval across allowlisted project documents. Documentation
answers cite exact source paths and line numbers. Uploaded notes are excluded
from policy retrieval and provider input. Missing evidence remains explicit.

Official setup reference: https://bob.ibm.com/docs/ide/configuration/mcp/mcp-in-bob
