"""Portable Bob launcher; keep stdout exclusively for MCP protocol messages."""
import os
from pathlib import Path
import subprocess

backend = Path(__file__).resolve().parents[1]
python = backend / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
if not python.exists():
    raise SystemExit('Run npm run demo from src, then install backend/requirements-mcp.txt.')
raise SystemExit(subprocess.call([str(python), '-m', 'app.mcp.server'], cwd=backend))
