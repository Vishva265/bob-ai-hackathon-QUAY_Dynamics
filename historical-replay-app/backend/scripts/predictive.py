"""Root-workspace entry point for predictive training and inference."""

from _bootstrap import prepare_environment

prepare_environment()

from app.predictive.cli import main

if __name__ == '__main__':
    main()
