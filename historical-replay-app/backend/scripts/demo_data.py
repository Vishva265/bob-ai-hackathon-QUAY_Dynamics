"""Workspace entry point: python backend/scripts/demo_data.py generate."""

from _bootstrap import prepare_environment

prepare_environment()

from app.synthetic.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
