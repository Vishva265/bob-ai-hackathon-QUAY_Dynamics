"""Workspace entry point: python backend/scripts/demo_data.py generate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.synthetic.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
