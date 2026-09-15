"""Point-in-time training rows with explicit label availability and purged splits."""
from datetime import timedelta

import numpy as np
import pandas as pd

from app.predictive.features import FeatureBuilder, FEATURES


def build_training_rows(tables, manifest, holidays=None, progress=None):
    cutoff = pd.Timestamp(manifest['epoch'])
    start = min(pd.Timestamp(y['timestamp']) for y in tables['yard_snapshots'])
    # Seven-day warmup. Last origin's entire 72-hour outcome window must be historical.
    origins = pd.date_range(start+timedelta(days=7), cutoff-timedelta(hours=72), freq='24h')
    if len(origins) < 20:
        raise ValueError('Training requires at least 30 days of history; use the default 60-day dataset')
    builder = FeatureBuilder(tables, holidays)
    congestion, waiting = [], []
    scopes = [(None, p['id']) for p in tables['ports']]+[(t['id'], None) for t in tables['terminals']]
    for i, origin in enumerate(origins):
        for terminal_id, port_id in scopes:
            for h in range(72):
                bucket = origin+timedelta(hours=h)
                target = builder.target_level(bucket, terminal_id, port_id)
                if target is None:
                    continue
                congestion.append(dict(builder.row(origin, bucket, terminal_id, port_id), origin=origin,
                    target_time=bucket, label_known_at=bucket+timedelta(hours=1), target=target,
                    scope='terminal' if terminal_id else 'port', entity_id=terminal_id or port_id))
        candidates = builder.calls[(builder.calls.scheduled_eta >= origin) & (builder.calls.scheduled_eta < origin+timedelta(hours=72))]
        outcomes = builder.outcomes.set_index('call_id')
        for call in candidates.to_dict('records'):
            if call['id'] not in outcomes.index:
                continue
            outcome = outcomes.loc[call['id']]
            # Future truth (including historical ETAs that arrived/berthed after cutoff) isn't a label.
            if outcome.berth_start >= cutoff or outcome.actual_arrival >= cutoff:
                continue
            waiting.append(dict(builder.row(origin, call['scheduled_eta'], call['terminal_id'], call=call),
                origin=origin, target_time=call['scheduled_eta'], label_known_at=outcome.berth_start,
                target=(outcome.berth_start-outcome.actual_arrival).total_seconds()/3600,
                call_id=call['id']))
        builder._cache.clear()
        if progress:
            progress(f'feature_origin {i+1}/{len(origins)} {origin.isoformat()}')
    return pd.DataFrame(waiting), pd.DataFrame(congestion)


def chronological_splits(rows):
    origins = sorted(rows.origin.unique())
    validation_start = origins[int(len(origins)*.70)]
    test_start = origins[int(len(origins)*.85)]
    masks = {
        'train': (rows.origin < validation_start) & (rows.label_known_at < validation_start),
        'validation': (rows.origin >= validation_start) & (rows.origin < test_start) & (rows.label_known_at < test_start),
        'test': rows.origin >= test_start,
    }
    result = {name: rows[mask].reset_index(drop=True) for name, mask in masks.items()}
    for name, part in result.items():
        if len(part) < 20:
            raise ValueError(f'Insufficient {name} rows after purging overlapping labels')
        if not np.isfinite(part[FEATURES].to_numpy()).all() or (part.target < 0).any():
            raise ValueError(f'Invalid {name} features or targets')
    # The same vessel target must not occur in more than one split.
    if 'call_id' in rows:
        for left, right in [('train', 'validation'), ('train', 'test'), ('validation', 'test')]:
            duplicates = set(result[left].call_id) & set(result[right].call_id)
            if duplicates:
                result[left] = result[left][~result[left].call_id.isin(duplicates)].reset_index(drop=True)
    assert result['train'].label_known_at.max() < result['validation'].origin.min()
    assert result['validation'].label_known_at.max() < result['test'].origin.min()
    return result
