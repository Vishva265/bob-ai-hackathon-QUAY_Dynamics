"""Transparent baselines persist and infer through the same sklearn interface."""
import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin, ClassifierMixin


class RollingWaiting(RegressorMixin, BaseEstimator):
    def fit(self, X, y):
        self.fallback_ = float(np.mean(y))
        return self

    def predict(self, X):
        return np.where(X.historical_wait_missing.to_numpy() > 0, self.fallback_, X.waiting_avg_7d.to_numpy())


class RollingCongestion(ClassifierMixin, BaseEstimator):
    def fit(self, X, y):
        self.classes_ = np.arange(4)
        return self

    def predict_proba(self, X):
        return X[[f'rolling_level_{i}' for i in range(4)]].to_numpy()

    def predict(self, X):
        return self.predict_proba(X).argmax(axis=1)


def probabilities(model, X):
    raw = model.predict_proba(X)
    output = np.zeros((len(X), 4))
    for i, label in enumerate(model.classes_):
        output[:, int(label)] = raw[:, i]
    # Some ensembles accumulate binary floating-point rounding beyond one
    # (for example 1.0000000000000004).  Preserve their relative probabilities
    # while returning a valid distribution for calibration metrics/inference.
    output = np.clip(output, 0., 1.)
    total = output.sum(axis=1, keepdims=True)
    return np.divide(output, total, out=np.full_like(output, .25), where=total > 0)


def positive_probability(model, X):
    return probabilities(model, X)[:, 2:].sum(axis=1)
