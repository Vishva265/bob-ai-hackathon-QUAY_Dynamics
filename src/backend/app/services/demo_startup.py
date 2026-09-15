"""Opt-in, non-destructive demo bootstrap; never seed production implicitly."""
from pathlib import Path
from sqlalchemy import select, func
from app import models as m
from app.database import ROOT, session_factory
from app.observability import logger
from app.synthetic.files import read_dataset
from app.synthetic.simulator import generate, parse
from app.services.seed import seed_tables
from app.services.planning import PlanningService
from app.schemas import OptimisationInput
from app.predictive.registry import ModelRegistry

def seed_demo(engine, settings):
    if settings.app_env == 'production':
        raise ValueError('Demo bootstrap is forbidden in production')
    with session_factory(engine)() as db:
        if db.scalar(select(func.count()).select_from(m.Port)):
            logger.info('demo_seed_skipped_existing_data')
            return {'seeded': False, 'reason': 'existing_data'}
    if settings.demo_dataset_directory:
        location = Path(settings.demo_dataset_directory)
        tables, manifest, _ = read_dataset(location if location.is_absolute() else ROOT/location)
    else:
        tables, manifest = generate(seed=42, scenario='storm_crane_breakdown', history_days=60, upcoming_days=7)
    registry = ModelRegistry(settings.model_directory)
    if settings.demo_train_on_start and not registry.exists():
        from app.predictive.training import train_pipeline
        train_pipeline(tables, manifest, settings.model_directory,
            progress=lambda message: logger.info('demo_training_progress', extra={'fields': {'stage': message}}))
    with session_factory(engine).begin() as db:
        result = seed_tables(db, tables, manifest)
        run = PlanningService(db).run(OptimisationInput(as_of=parse(manifest['epoch']),
            predictor='ml' if registry.exists() else 'baseline', time_limit_seconds=2))
        result.update(seeded=True, run_id=run.id, predictor='ml' if registry.exists() else 'baseline')
    logger.info('demo_seed_completed', extra={'fields': {'run_id': run.id, 'predictor': result['predictor']}})
    return result
