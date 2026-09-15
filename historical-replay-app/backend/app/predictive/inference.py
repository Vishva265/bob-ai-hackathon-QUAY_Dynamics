"""Deterministic batch inference and numerical local sensitivity explanations."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from app.predictive.estimators import probabilities
from app.predictive.features import FeatureBuilder, LEVELS, UNITS


class InferenceEngine:
    def __init__(self, registry, version=None):
        self.bundle, self.metadata = registry.load(version)
        # A verified legacy artifact keeps its recorded feature order. Current
        # feature builders still supply those fields, while newer derived fields
        # are deliberately excluded from the older estimator.
        self.features = self.metadata['features']

    def factors(self, task, X, point):
        """One feature at a time replaced by train median; signed model sensitivity.

        These values are neither causal attribution nor an additive SHAP decomposition.
        """
        model = self.bundle['models'][task]
        changes = np.zeros((len(X), len(self.features)))
        for i, name in enumerate(self.features):
            counterfactual = X.copy()
            counterfactual[name] = self.bundle['reference'][task][name]
            alternate = np.maximum(0, model.predict(counterfactual)) if task == 'waiting' else probabilities(model, counterfactual)[:, 2:].sum(axis=1)
            changes[:, i] = point-alternate
        output = []
        for row_number in range(len(X)):
            indices = np.argsort(-np.abs(changes[row_number]), kind='stable')[:5]
            output.append([dict(feature=self.features[i], observed_value=float(X.iloc[row_number, i]),
                reference_value=float(self.bundle['reference'][task][self.features[i]]), contribution=float(changes[row_number, i]),
                contribution_unit='hours' if task == 'waiting' else 'probability', feature_unit=UNITS[self.features[i]],
                method='one_feature_to_training_median') for i in indices if abs(changes[row_number, i]) > 1e-10])
        return output

    def predict(self, task, rows, explain=True):
        if not rows:
            return []
        X = pd.DataFrame(rows)[self.features]
        if not np.isfinite(X.to_numpy()).all():
            raise ValueError('Inference requires finite operational features')
        with threadpool_limits(limits=1):
            model = self.bundle['models'][task]
            if task == 'waiting':
                point = np.maximum(0, model.predict(X))
            else:
                probs = probabilities(model, X)
                point = probs[:, 2:].sum(axis=1)
            factors = self.factors(task, X, point) if explain else [[] for _ in rows]
        now = datetime.now(timezone.utc).isoformat()
        uncertainty = self.bundle['uncertainty'][task]
        results = []
        for i, value in enumerate(point):
            radius = uncertainty['radius'] if task == 'congestion' else uncertainty['by_lead'].get(str(min(48, int(rows[i]['lead_hours']//24)*24)), uncertainty['radius_hours'])
            output = dict(prediction=float(value), lower=max(0., float(value-radius)), upper=float(value+radius) if task == 'waiting' else min(1., float(value+radius)),
                uncertainty_method=uncertainty['method'], nominal_coverage=.9, factors=factors[i],
                model_version=self.metadata['model_version'], prediction_timestamp=now,
                quality=self.metadata['quality'])
            if task == 'congestion':
                output['level'] = LEVELS[int(probs[i].argmax())]
                output['level_probabilities'] = {name: float(probs[i, j]) for j, name in enumerate(LEVELS)}
            results.append(output)
        return results

    def forecast(self, tables, as_of, port_ids=None, observation_cutoff=None, explain=True):
        origin = pd.Timestamp(as_of)
        calibration_end = max(pd.Timestamp(r['splits']['validation']['label_known_end']) for r in self.metadata['evaluation'].values())
        if origin <= calibration_end:
            raise ValueError('as_of must be after this model training/calibration label period')
        builder = FeatureBuilder(tables, self.metadata.get('holidays'), observation_cutoff)
        ports = sorted(set(port_ids or builder.ports))
        if not ports or any(p not in builder.ports for p in ports):
            raise ValueError('Select existing ports')
        rows, keys = [], []
        for port_id in ports:
            scopes = [(None, port_id)]+[(t, None) for t in builder.scope(port_id=port_id)]
            for terminal_id, pid in scopes:
                for h in range(72):
                    bucket = origin+timedelta(hours=h)
                    rows.append(builder.row(origin, bucket, terminal_id, pid))
                    keys.append(dict(scope='terminal' if terminal_id else 'port', port_id=port_id,
                        terminal_id=terminal_id, timestamp=bucket.isoformat(), as_of=origin.isoformat()))
        congestion = [dict(key, **prediction) for key, prediction in zip(keys, self.predict('congestion', rows, explain))]
        waiting_rows, waiting_keys = [], []
        observation_time = min(origin, pd.Timestamp(observation_cutoff)-pd.Timedelta(microseconds=1)) if observation_cutoff else origin
        for call in builder.calls[(builder.calls.port_id.isin(ports)) & (builder.calls.scheduled_eta >= origin) &
                                  (builder.calls.scheduled_eta < origin+timedelta(hours=72))].to_dict('records'):
            # Calls already observed berthed aren't scheduled waiting-time predictions.
            observed = builder.outcomes[(builder.outcomes.call_id == call['id']) & (builder.outcomes.berth_start <= observation_time)] if len(builder.outcomes) else builder.outcomes
            carries = {c['call_id'] for c in tables.get('carry_in_operations', []) if pd.Timestamp(c['known_at']) <= origin}
            if len(observed) or call['id'] in carries:
                continue
            waiting_rows.append(builder.row(origin, call['scheduled_eta'], call['terminal_id'], call=call))
            waiting_keys.append(dict(call_id=call['id'], port_id=call['port_id'], terminal_id=call['terminal_id'],
                scheduled_eta=call['scheduled_eta'].isoformat(), as_of=origin.isoformat()))
        waiting = [dict(key, **prediction) for key, prediction in zip(waiting_keys, self.predict('waiting', waiting_rows, explain))]
        return dict(model_version=self.metadata['model_version'], as_of=origin.isoformat(), congestion=congestion, waiting=waiting,
                    assumptions=self.metadata['assumptions'])
