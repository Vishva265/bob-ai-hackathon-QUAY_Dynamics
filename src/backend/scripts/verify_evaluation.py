"""Independently recompute published metrics from raw vessel and forecast audits."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, mean_absolute_error, mean_squared_error


def equal(a,b):
    assert abs(a-b)<=max(1e-8,abs(b)*1e-10),(a,b)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path('artifacts/evaluation'))
    args=parser.parse_args();folder=args.directory
    summary=json.loads((folder/'summary.json').read_text());p=summary['config']['policy']
    assert summary['synthetic'] and not summary['real_world_validated']
    raw={n:json.loads((folder/f'{n}-raw.json').read_text()) for n in summary['lineage']}
    for row in summary['rows']:
        item=raw[row['scenario_id']][row['scenario_id']+'__'+row['strategy_id']]
        first=item['repetitions'][0];vessels=first['vessel_metrics']
        assert len(vessels)==row['cohort_vessels']==row['served_vessels']+row['deferred_vessels']
        waits=[v['wait_hours'] for v in vessels if v['served']]
        equal(float(np.mean(waits)),row['average_wait_hours'])
        equal(float(np.quantile(waits,.9)),row['p90_wait_hours']);equal(max(waits),row['maximum_wait_hours'])
        equal(sum(v['wait_hours'] for v in vessels),row['total_delay_hours'])
        cost=(sum(v['wait_hours'] for v in vessels)*p['waiting_cost_usd_per_hour']+
              sum(v['departure_delay_hours'] for v in vessels)*p['departure_delay_cost_usd_per_hour']+
              row['crane_overtime_hours']*p['crane_overtime_cost_usd_per_hour']+
              row['deferred_vessels']*p['deferral_cost_usd'])
        # No routing proposals were dispatched in the published experiment.
        assert row['number_of_reroutes']==0
        equal(cost,row['estimated_cost_usd'])
        equal(sum(v['emissions_tonnes_co2'] for v in vessels),row['estimated_emissions_tonnes_co2'])
        assert all(v['wait_is_lower_bound'] for v in vessels if not v['served'])
        assert row['plan_stability']['frozen_changed']==0
        assert row['yard_overflow_terminal_hours']==0 and row['yard_safe_capacity_exceedance_terminal_hours']==0
        baseline=next(r for r in summary['rows'] if r['scenario_id']==row['scenario_id'] and r['strategy_id']=='fcfs')
        equal(baseline['estimated_cost_usd']-row['estimated_cost_usd'],row['estimated_cost_savings_usd'])
        equal(baseline['estimated_emissions_tonnes_co2']-row['estimated_emissions_tonnes_co2'],row['estimated_emissions_savings_tonnes_co2'])
    for scenario,score in summary['forecast_scores'].items():
        w=pd.read_csv(folder/f'{scenario}-waiting-forecast-audit.csv').dropna(subset=['actual_wait_hours'])
        equal(mean_absolute_error(w.actual_wait_hours,w.prediction),score['waiting']['mae'])
        equal(np.sqrt(mean_squared_error(w.actual_wait_hours,w.prediction)),score['waiting']['rmse'])
        c=pd.read_csv(folder/f'{scenario}-congestion-forecast-audit.csv').dropna(subset=['actual_level'])
        equal(f1_score(c.actual_level>=2,c.prediction>=.5,zero_division=0),score['congestion']['f1'])
    result={'result':'PASS','strategy_rows_verified':len(summary['rows']),
        'forecasts_verified':len(summary['forecast_scores']),'censoring_cost_savings_frozen_and_capacity_checks':'PASS'}
    (folder/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
