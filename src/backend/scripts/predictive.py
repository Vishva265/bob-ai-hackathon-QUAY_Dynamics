"""Root-workspace entry point for predictive training and inference."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.predictive.cli import main

if __name__ == '__main__':
    main()
