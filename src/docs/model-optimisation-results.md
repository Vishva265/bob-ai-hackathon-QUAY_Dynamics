# Congestion model optimisation results

## Reproducible out-of-time evaluation

This run (`ml-v1-5825ca03a783e310`) was trained on the seeded Normal
Operations synthetic dataset (seed 42; 60 historical days; 7 upcoming days).
Training used a purged chronological split: 53,790 training rows, 11,022
validation rows and 12,672 untouched out-of-time (OOT) rows. Thresholds were
chosen in the pre-calibration part of validation only. The OOT rows were never
used in fitting, threshold selection or hyperparameter selection.

| Candidate | Optimisation | Accuracy | Precision | Recall | F1 | ROC-AUC | Brier score ↓ | OOT assessment |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Rolling Average | Historical congestion-level distribution | 70.3% | 52.9% | 70.1% | 0.602 | 0.789 | 0.166 | Strong benchmark, but no current-condition learning |
| Regularized Logistic | Standardised operational features; validation-set threshold 0.31 | **74.9%** | 59.2% | **71.1%** | **0.646** | **0.814** | **0.150** | Best all-round OOT profile |
| HistGradientBoosting | 350 boosted trees, 63-leaf capacity, regularisation; threshold 0.45 | **75.6%** | **63.5%** | 56.6% | 0.598 | 0.801 | 0.172 | Highest accuracy and precision; misses more events |
| Extra Trees | 300 decorrelated trees, class balancing; threshold 0.37 | 71.4% | 54.3% | 70.4% | 0.613 | 0.809 | 0.155 | Recall-oriented challenger |

**Presentation takeaway:** the regularized logistic candidate offers the
strongest balanced OOT operating profile: **74.9% accuracy, 0.646 F1, 0.814
ROC-AUC and 0.150 Brier score**. HistGradientBoosting is the precision-first
option when false alarms are especially costly.

## What changed

- Increased gradient-boosting capacity while retaining regularisation, so it
  can model workload, weather, availability and lead-time interactions.
- Added an Extra Trees challenger to test non-linear threshold effects.
- Kept the rolling baseline and logistic model as controls.
- Normalised ensemble probability vectors before calibration scoring, preventing
  harmless floating-point sums above one from invalidating Brier calculations.

The training protocol initially selected HistGradientBoosting from the
validation-selection window (F1 0.740). The final OOT benchmark favoured the
logistic model on balanced performance. This disagreement is useful evidence of
temporal variation, not permission to tune against the OOT holdout. Before a
production promotion, repeat this chronological backtest over several rolling
time windows and select using the predeclared business objective.

All results are synthetic and chronologically evaluated; they are not a claim
of real-port performance.
