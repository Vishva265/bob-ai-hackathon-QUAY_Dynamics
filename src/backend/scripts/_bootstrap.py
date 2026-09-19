"""Make historical replay scripts safe to run from any working directory."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
VENV_PYTHON = BACKEND_ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def prepare_environment() -> None:
    """Re-run with the project interpreter, then expose the backend package."""
    current = os.path.normcase(str(Path(sys.executable).resolve()))
    expected = os.path.normcase(str(VENV_PYTHON.resolve())) if VENV_PYTHON.exists() else None
    if expected and current != expected:
        completed = subprocess.run(
            [str(VENV_PYTHON), str(Path(sys.argv[0]).resolve()), *sys.argv[1:]],
            cwd=PROJECT_ROOT,
            check=False,
        )
        raise SystemExit(completed.returncode)
    if not expected:
        raise SystemExit(
            "Project virtual environment not found. Create backend/.venv and install "
            "backend/requirements.txt before running this command."
        )
    sys.path.insert(0, str(BACKEND_ROOT))
