"""Strict threshold rules; confidence is an attention category, not coverage."""
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

RULES = ('BERTH_UTILISATION', 'YARD_OCCUPANCY', 'WAITING_TIME',
         'CRANE_UTILISATION', 'ARRIVAL_SURGE', 'LOW_CONFIDENCE')


class AlertRules(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    berth_utilisation: float = Field(default=.85, ge=0, le=1)
    yard_occupancy: float = Field(default=.90, ge=0, le=1)
    waiting_hours: float = Field(default=8, ge=0)
    crane_utilisation: float = Field(default=.95, ge=0, le=1)
    arrival_workload_ratio: float = Field(default=1.5, ge=1)
    arrival_min_increase_moves: float = Field(default=500, ge=0)
    arrival_window_hours: int = Field(default=3, ge=1, le=24)
    maximum_uncertainty_width: float = Field(default=.5, ge=0, le=1)
    maximum_observation_age_hours: float = Field(default=6, ge=0)
    enabled: list[str] = Field(default_factory=lambda: list(RULES))

    @classmethod
    def configured(cls):
        path = os.getenv('ALERT_RULES_FILE')
        if not path:
            return cls()
        root = Path(__file__).resolve().parents[3]
        return cls.model_validate(json.loads((root / path).read_text(encoding='utf-8')))

    def model_post_init(self, context):
        if len(set(self.enabled)) != len(self.enabled) or set(self.enabled) - set(RULES):
            raise ValueError('enabled must contain unique supported rule codes')


def evaluate(row, rules):
    """Values equal to thresholds do not trigger an 'above' rule."""
    found = []
    for code, field, threshold, unit in [
        ('BERTH_UTILISATION', 'berth_utilisation', rules.berth_utilisation, 'fraction'),
        ('YARD_OCCUPANCY', 'yard_occupancy', rules.yard_occupancy, 'fraction'),
        ('WAITING_TIME', 'average_wait_hours', rules.waiting_hours, 'hours'),
        ('CRANE_UTILISATION', 'crane_utilisation', rules.crane_utilisation, 'fraction')]:
        if code in rules.enabled and row[field] > threshold:
            found.append(dict(code=code, message=f'{field} exceeds configured threshold',
                              evidence=dict(value=row[field], threshold=threshold, unit=unit)))
    if ('ARRIVAL_SURGE' in rules.enabled and row['arrival_workload_ratio'] > rules.arrival_workload_ratio
            and row['arrival_workload_increase_moves'] > rules.arrival_min_increase_moves):
        found.append(dict(code='ARRIVAL_SURGE', message='Scheduled arrival workload rises rapidly',
            evidence=dict(value=row['arrival_workload_ratio'], threshold=rules.arrival_workload_ratio,
                          increase_moves=row['arrival_workload_increase_moves'],
                          minimum_increase_moves=rules.arrival_min_increase_moves, window_hours=rules.arrival_window_hours)))
    if 'LOW_CONFIDENCE' in rules.enabled and row['confidence_level'] == 'LOW':
        found.append(dict(code='LOW_CONFIDENCE', message='Operator review required for forecast uncertainty or data limitations',
                          evidence=dict(reasons=row['confidence_reasons'])))
    return found


def hotspot_windows(rows):
    """Contiguous hourly physical hotspots; attention-only alerts are excluded."""
    windows = []
    for row in rows:
        if not row['is_hotspot']:
            continue
        from datetime import timedelta
        end = row['timestamp'] + timedelta(hours=1)
        if windows and windows[-1]['end'] == row['timestamp']:
            windows[-1]['end'] = end
            windows[-1]['duration_hours'] += 1
        else:
            windows.append(dict(start=row['timestamp'], end=end, duration_hours=1))
    return windows
