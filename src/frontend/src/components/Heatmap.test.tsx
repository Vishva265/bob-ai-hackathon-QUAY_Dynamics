// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it} from 'vitest';
import {Heatmap} from './Heatmap';
import {fixture} from '../testing/fixture';
import type {Forecast} from '../types';

afterEach(cleanup);
it('shows loading evidence and unavailable forecasts without presenting stale detail',()=>{
  const d=fixture();const {rerender}=render(<Heatmap data={d} port="all" loading/>);
  expect(screen.getByRole('status')).toHaveTextContent('Loading forecast evidence');
  rerender(<Heatmap data={d} port="all"/>);expect(screen.getByText(/No hourly operational forecasts/)).toBeVisible();
});
function payload(){
  const d=fixture();
  const f:Forecast={id:'f',run_id:'forecast-run',scope:'terminal',scope_id:'T',port_id:'P01',terminal_id:'T',berth_id:null,timestamp:'2026-09-14T06:00:00Z',berth_utilisation:1/3,queue_length:1,average_wait_hours:19.2,yard_occupancy:.36,crane_utilisation:.364,congestion_probability:.079,probability_lower:0,probability_upper:.7,probability_basis:'trained_scope_model',prediction_timestamp:'2026-09-13T00:00:00Z',congestion_severity:'HIGH',confidence_level:'LOW',confidence_reasons:['Wide model event-error band','Persisted weather/yard assumptions exceed observation-age limit at target hour'],main_causes:[{code:'KNOWN_CRANE_DOWNTIME',message:'known crane downtime'}],is_hotspot:true,first_expected_hotspot_time:null,expected_hotspot_duration_hours:0,model_version:'test-v1',explanation:{forecast_run_id:'forecast-run',input_hash:'recorded-hash',projection_method:'fifo_quarter_hour_v1',severity_explanation:'Stored operational severity is HIGH. Predicted average wait of 19.2h exceeds the recorded 12h threshold.',triggered_thresholds:[],confidence_explanation:'Confidence is LOW because: Wide model event-error band; persisted weather/yard assumptions are stale.',inputs:[{kind:'crane',label:'Scheduled/known input: crane downtime',source_type:'SCHEDULED',source_timestamp:null,effective_timestamp:null,start:'2026-09-14T00:00:00Z',end:'2026-09-15T00:00:00Z',age_hours:null,freshness:'NOT_APPLICABLE',values:{crane_id:'C1'},assumptions:[]},{kind:'weather',label:'Future weather assumption: latest observed conditions persist',source_type:'FORECAST_ASSUMPTION',source_timestamp:'2026-09-13T00:00:00Z',effective_timestamp:null,start:null,end:null,age_hours:30,freshness:'STALE',values:{wind_mps:16},assumptions:['Persistence assumption']}],operator_interpretation:'Crane downtime and persisted weather reduce usable capacity. Review the recorded forecast.',supervisor_action:'Run rolling replan',action_reason:'Known downtime coincides with predicted severe waiting.',human_approval_required:true,plan_status:'APPROVED',assumptions:['Synthetic snapshot'],missing_provenance:[]}};
  d.forecast_rows=[f,{...f,id:'f2',timestamp:'2026-09-14T07:00:00Z'}];return d;
}
it('separates probability, impact and confidence and explains recorded inputs without modifying a plan',async()=>{
  const d=payload(),before=structuredClone(d);render(<Heatmap data={d} port="all"/>);
  await userEvent.click(screen.getAllByRole('button',{name:/Test terminal/})[0]);
  expect(screen.getByText(/Congestion event probability:/)).toHaveTextContent('7.9%');
  expect(screen.getByRole('heading',{name:/Operational severity: HIGH/})).toBeVisible();
  expect(screen.getByText(/19.2h exceeds the recorded 12h/)).toBeVisible();
  expect(screen.getByRole('heading',{name:/Forecast confidence: LOW CONFIDENCE/})).toBeVisible();
  expect(screen.getByText(/it does not cancel the alert/)).toBeVisible();
  expect(screen.getByText('Scheduled/known input: crane downtime')).toBeVisible();
  expect(screen.getByText('FORECAST_ASSUMPTION')).toBeVisible();
  expect(screen.getByText(/not a calibrated probability confidence interval/)).toBeVisible();
  for(const label of ['Predicted berth utilisation','Predicted queue length','Predicted average wait','Predicted yard occupancy','Predicted crane utilisation'])expect(screen.getByText(label)).toBeVisible();
  expect(d).toEqual(before);
});
it('preserves keyboard navigation, hover selection and selection reset after scope changes',async()=>{
  render(<Heatmap data={payload()} port="all"/>);const buttons=screen.getAllByRole('button',{name:/Test terminal/});
  await userEvent.hover(buttons[0]);expect(screen.getByText(/UTC \/ \+30h/)).toBeVisible();
  await userEvent.click(buttons[0]);await userEvent.keyboard('{ArrowRight}');expect(buttons[1]).toHaveFocus();
  expect(screen.getByText(/UTC \/ \+31h/)).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText('Heatmap row scope'),'port');expect(screen.getByText(/No hourly operational forecasts/)).toBeVisible();
});
it('makes missing provenance explicit and never fabricates thresholds or uncertainty',async()=>{
  const d=payload();d.forecast_rows[0]={...d.forecast_rows[0],explanation:null,probability_lower:undefined,probability_upper:undefined};
  render(<Heatmap data={d} port="all"/>);await userEvent.click(screen.getAllByRole('button',{name:/Test terminal/})[0]);
  expect(screen.getByText(/Input provenance unavailable/)).toBeVisible();expect(screen.getByText(/No range has been inferred/)).toBeVisible();
  expect(screen.getByText(/Exact thresholds cannot be explained/)).toBeVisible();
  expect(within(screen.getByText(/Predicted outcomes/).parentElement!).queryByText(/12h threshold/)).toBeNull();
});
