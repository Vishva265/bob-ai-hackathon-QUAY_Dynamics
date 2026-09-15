"""Chronological evaluation, validation-only selection/calibration, immutable bundle."""
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (mean_absolute_error, mean_squared_error, precision_score,
    recall_score, f1_score, roc_auc_score, confusion_matrix, brier_score_loss)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from app.predictive.datasets import build_training_rows, chronological_splits
from app.predictive.features import FEATURES, FEATURE_VERSION, LEVELS, UNITS
from app.predictive.estimators import RollingWaiting, RollingCongestion, probabilities

TRAINING_CONFIG = dict(seed=42, iterations=120, max_leaf_nodes=15, early_stopping=False,
                       train_fraction=.70, validation_fraction=.15, nominal_coverage=.90,
                       waiting_selection='validation_mae_plus_0.1_rmse')


def waiting_metrics(y, predicted):
    predicted = np.maximum(0, predicted)
    return dict(mae=float(mean_absolute_error(y, predicted)), rmse=float(np.sqrt(mean_squared_error(y, predicted))))


def congestion_threshold(y, predicted):
    """Choose an operating point from validation-selection data only."""
    actual = np.asarray(y) >= 2
    probability = predicted[:, 2:].sum(axis=1)
    candidates = np.linspace(.1, .9, 81)
    return float(max(candidates, key=lambda value: (
        f1_score(actual, probability >= value, zero_division=0),
        -abs(value-.5))))


def congestion_metrics(y, predicted, threshold=.5):
    actual = np.asarray(y) >= 2
    probability = predicted[:, 2:].sum(axis=1)
    binary = probability >= threshold
    return dict(precision=float(precision_score(actual, binary, zero_division=0)),
        recall=float(recall_score(actual, binary, zero_division=0)),
        f1=float(f1_score(actual, binary, zero_division=0)),
        roc_auc=float(roc_auc_score(actual, probability)) if len(np.unique(actual)) == 2 else None,
        confusion_matrix=confusion_matrix(actual, binary, labels=[False, True]).tolist(),
        brier_score=float(brier_score_loss(actual, probability)),
        positive_rate=float(actual.mean()), level_macro_f1=float(f1_score(y, predicted.argmax(axis=1), labels=[0, 1, 2, 3], average='macro', zero_division=0)),
        level_confusion_matrix=confusion_matrix(y, predicted.argmax(axis=1), labels=[0, 1, 2, 3]).tolist())


def quantile_radius(residuals, coverage=.9):
    """Finite-sample split-conformal quantile; time dependence limits coverage claims."""
    residuals = np.sort(np.asarray(residuals))
    if not len(residuals):
        raise ValueError('Calibration residuals required')
    rank = min(len(residuals), int(np.ceil((len(residuals)+1)*coverage)))
    return float(residuals[rank-1])


def fit_models(waiting, congestion, progress=None):
    split_data = {task: chronological_splits(rows) for task, rows in [('waiting', waiting), ('congestion', congestion)]}
    models = {
        'waiting': {
            'rolling_average': RollingWaiting(),
            'linear': make_pipeline(StandardScaler(), Ridge(alpha=10)),
            'hist_gradient_boosting': HistGradientBoostingRegressor(max_iter=120, max_leaf_nodes=15, min_samples_leaf=15, l2_regularization=2, early_stopping=False, random_state=42),
        },
        'congestion': {
            'rolling_average': RollingCongestion(),
            'logistic': make_pipeline(StandardScaler(), LogisticRegression(C=.5, max_iter=1500, random_state=42)),
            'hist_gradient_boosting': HistGradientBoostingClassifier(max_iter=120, max_leaf_nodes=15, min_samples_leaf=50, l2_regularization=2, early_stopping=False, random_state=42),
        },
    }
    reports, selected, fitted = {}, {}, {}
    for task, candidates in models.items():
        train, validation, test = (split_data[task][n] for n in ['train', 'validation', 'test'])
        val_origins = sorted(validation.origin.unique())
        if len(val_origins) < 2:
            raise ValueError('At least two validation origins are required')
        calibration_start = val_origins[len(val_origins)//2]
        selection = validation[(validation.origin < calibration_start) & (validation.label_known_at < calibration_start)]
        calibration = validation[validation.origin >= calibration_start]
        if 'call_id' in validation:
            selection = selection[~selection.call_id.isin(set(calibration.call_id))]
        if len(selection) < 20 or len(calibration) < 20:
            raise ValueError('Insufficient independent validation selection/calibration rows')
        metrics, thresholds = {}, {}
        for name, model in candidates.items():
            if progress:
                progress(f'fit {task}/{name} train={len(train)} validation={len(validation)} test={len(test)}')
            model.fit(train[FEATURES], train.target)
            predict = model.predict if task == 'waiting' else lambda X, estimator=model: probabilities(estimator, X)
            if task == 'waiting':
                metrics[name] = {label: waiting_metrics(part.target, predict(part[FEATURES]))
                                 for label, part in [('selection', selection), ('validation', validation), ('test', test)]}
            else:
                threshold = congestion_threshold(selection.target, predict(selection[FEATURES]))
                thresholds[name] = threshold
                metrics[name] = {label: congestion_metrics(part.target, predict(part[FEATURES]), threshold)
                                 for label, part in [('selection', selection), ('validation', validation), ('test', test)]}
                for result in metrics[name].values():
                    result['decision_threshold'] = threshold
        # MAE alone made two effectively tied models hinge on a few minutes while
        # ignoring a multi-hour RMSE gap.  Select on the declared validation-only
        # composite so ordinary error and costly misses both matter.
        winner = min(candidates, key=lambda n: metrics[n]['selection']['mae']+.1*metrics[n]['selection']['rmse']) if task == 'waiting' else max(candidates, key=lambda n: (metrics[n]['selection']['f1'], -(metrics[n]['selection']['brier_score'])))
        model = candidates[winner]
        selected[task], fitted[task] = winner, model
        if task == 'waiting':
            predicted = np.maximum(0, model.predict(calibration[FEATURES]))
            radius = quantile_radius(np.abs(calibration.target-predicted))
            by_lead = {}
            for lower, upper in ((0, 24), (24, 48), (48, 72)):
                mask = (calibration.lead_hours >= lower) & (calibration.lead_hours < upper)
                if mask.sum() >= 30:
                    by_lead[str(lower)] = quantile_radius(np.abs(calibration.target[mask]-predicted[mask]))
            test_prediction = np.maximum(0, model.predict(test[FEATURES]))
            radii = np.array([by_lead.get(str(min(48, int(h//24)*24)), radius) for h in test.lead_hours])
            interval = dict(method='validation_residual_split_conformal', nominal_coverage=.9, radius_hours=radius,
                by_lead=by_lead, test_coverage=float(((test.target >= np.maximum(0, test_prediction-radii)) & (test.target <= test_prediction+radii)).mean()),
                test_mean_width_hours=float((test_prediction+radii-np.maximum(0, test_prediction-radii)).mean()))
        else:
            p = probabilities(model, calibration[FEATURES])[:, 2:].sum(axis=1)
            radius = quantile_radius(np.abs((calibration.target.to_numpy() >= 2).astype(float)-p))
            interval = dict(method='validation_binary_residual_band', nominal_coverage=.9, radius=radius,
                            decision_threshold=thresholds[winner],
                            threshold_selection='maximum F1 on pre-calibration validation-selection window',
                            interpretation='Predictive event-error band, not a confidence interval for true probability')
        reports[task] = dict(selected=winner, metrics=metrics, uncertainty=interval,
            splits={name: dict(rows=len(part), origin_start=part.origin.min().isoformat(), origin_end=part.origin.max().isoformat(), label_known_end=part.label_known_at.max().isoformat(),
                              unique_targets=int(part.call_id.nunique()) if 'call_id' in part else None) for name, part in split_data[task].items()},
            validation_selection_end=selection.origin.max().isoformat(), calibration_origin_start=calibration_start.isoformat(),
            calibration_rows=len(calibration))
        # Freeze predictions for external audit; test results do not feed fitting/selection.
        audit = test[['origin', 'target_time', 'target']].copy()
        if 'call_id' in test:
            audit['call_id'] = test.call_id
        else:
            audit['scope'], audit['entity_id'] = test.scope, test.entity_id
        audit['prediction'] = test_prediction if task == 'waiting' else probabilities(model, test[FEATURES])[:, 2:].sum(axis=1)
        fitted[task+'_audit'] = audit
    fitted['reference'] = {task: split_data[task]['train'][FEATURES].median().to_dict() for task in models}
    return fitted, reports, selected


def train_pipeline(tables, manifest, model_directory, holidays=None, progress=print):
    identity = dict(source=manifest.get('files', manifest), config=TRAINING_CONFIG, feature_version=FEATURE_VERSION,
                    sklearn=sklearn.__version__, holidays=holidays)
    version = 'ml-v1-'+hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    root = Path(model_directory)
    destination = root/version
    if destination.exists():
        raise ValueError(f'Model version {version} already exists; immutable versions are never overwritten')
    waiting, congestion = build_training_rows(tables, manifest, holidays, progress)
    if progress:
        progress(f'features_complete waiting={len(waiting)} congestion={len(congestion)}')
    with threadpool_limits(limits=1):
        fitted, reports, selected = fit_models(waiting, congestion, progress)
    root.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f'Model version {version} already exists; immutable versions are never overwritten')
    import tempfile
    stage = Path(tempfile.mkdtemp(prefix='.training-', dir=root))
    try:
        for task in ['waiting', 'congestion']:
            fitted.pop(task+'_audit').to_csv(stage/f'{task}_test_predictions.csv', index=False)
        bundle = dict(models={task: fitted[task] for task in ['waiting', 'congestion']}, reference=fitted['reference'],
                      uncertainty={task: reports[task]['uncertainty'] for task in reports})
        joblib.dump(bundle, stage/'models.joblib', compress=3)
        files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.iterdir()}
        metadata = dict(model_version=version, feature_version=FEATURE_VERSION, features=FEATURES, units=UNITS,
            trained_at=datetime.now(timezone.utc).isoformat(), source_scenario=manifest['scenario'], source_seed=manifest.get('seed'),
            observation_cutoff=manifest['epoch'], source_hash=hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            config=TRAINING_CONFIG, selected_models=selected, evaluation=reports, files=files,
            dependencies=dict(python=platform.python_version(), sklearn=sklearn.__version__, numpy=np.__version__, pandas=pd.__version__, joblib=joblib.__version__),
            labels=dict(levels=LEVELS, congestion_event='HIGH or CRITICAL', queue_high=2, queue_critical=4, yard_high=.85, yard_critical=.95, utilisation_high=.95),
            assumptions=['Synthetic scheduled calls published seven days ahead; no publication/change logs exist',
                'Weather and tide use last observed values; no future truth forecasts',
                'Ongoing breakdowns persist conservatively until observed repaired',
                'Aggregate inventory/outflow proxy substitutes for missing individual container dwell events',
                'No holiday calendar supplied means missing indicator, not an invented holiday',
                'Validation residual bands have no guaranteed coverage under temporal dependence or domain shift'],
            quality='synthetic_chronologically_evaluated', holidays=holidays,
            dataset_rows=dict(waiting=len(waiting), congestion=len(congestion)),
            score_review=dict(unrealistically_perfect=any(r['metrics'][r['selected']]['test'].get('roc_auc', 0) == 1. for r in [reports['congestion']]),
                note='Report scores without tuning labels or changing test data. Investigate simulator/features if near-perfect.' ))
        (stage/'metadata.json').write_text(json.dumps(metadata, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        stage.rename(destination)
        pointer = root/'.active.tmp'
        pointer.write_text(json.dumps(dict(model_version=version, metadata_sha256=hashlib.sha256((destination/'metadata.json').read_bytes()).hexdigest()))+'\n', encoding='utf-8')
        pointer.replace(root/'active.json')
        return metadata, destination
    finally:
        if stage.exists():
            import shutil
            shutil.rmtree(stage)
