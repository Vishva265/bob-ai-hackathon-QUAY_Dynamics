// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {setDemoContext} from '../api';
import {HistoricalReplay} from './HistoricalReplay';

afterEach(()=>{cleanup();vi.unstubAllGlobals();setDemoContext(null)});

it('does not imply that real AIS exists before the NOAA workflow runs',async()=>{
  const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({available:false,
    cutoff:'2021-09-13T00:00:00Z',message:'Download and prepare NOAA AIS data, then run the historical replay.',
    documentation:'docs/historical-replay.md'}),{status:200,headers:{'Content-Type':'application/json'}}));
  vi.stubGlobal('fetch',fetcher);render(<HistoricalReplay/>);
  await waitFor(()=>expect(screen.getByText('Historical replay is ready for NOAA input')).toBeInTheDocument());
  expect(screen.getByText(/No sample or substitute AIS records are bundled/)).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith('/api/v1/historical-replay',expect.anything());
});

it('presents real replay evidence and its leakage boundary',async()=>{
  const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({available:true,plan:{run_id:'replay-1',as_of:'2021-09-13T00:00:00Z',end:'2021-09-16T00:00:00Z',status:'succeeded',solver_status:'FEASIBLE',schedule_source:'cp_sat',assignments:[],shifts:[],data_policy:{}},evaluation:{metrics:{queue_count_mae:34.305556,vessel_waiting_time_mae_hours:28.130834,waiting_time_compared_vessels:4,congestion_precision:1,congestion_recall:.666667,congestion_f1:.8,congestion_warning_lead_time_hours:0,total_actual_vessel_waiting_hours:4285.285833,actual_mean_berth_utilization:1,planned_mean_berth_utilization:.795751,planned_crane_utilization:.6741,constraint_violations:35,unscheduled_calls:35},interpretation:[]},hourly_comparison:[{timestamp:'2021-09-13T00:00:00Z',predicted_queue_count:5,predicted_berth_utilization:.88,predicted_congestion_level:'CRITICAL',actual_queue_count:26,actual_berth_utilization:1,actual_congestion_level:'CRITICAL'}]}),{status:200,headers:{'Content-Type':'application/json'}}));
  vi.stubGlobal('fetch',fetcher);render(<HistoricalReplay/>);
  await waitFor(()=>expect(screen.getByText('2021 LA/LB Historical Replay')).toBeInTheDocument());
  expect(screen.getByText('Severe congestion detected in matched hours')).toBeInTheDocument();
  expect(screen.getByText('Hidden truth revealed only for evaluation')).toBeInTheDocument();
  expect(screen.getByRole('note')).toHaveTextContent('No invented AIS records');
  expect(screen.getByRole('table',{name:'Historical replay evaluation metrics'})).toBeInTheDocument();
});

it('keeps deferred, excluded known and unknown calls distinct and searchable',async()=>{
  const calls=[['One','PROPOSED',2],['Two','DEFERRED',72],['Three','NOT_MODELLED',null],['Four','UNKNOWN_AT_CUTOFF',null]].map(([name,status,wait],i)=>({call_id:`call-${i}`,vessel_name:name,terminal_id:'LA_APM',actual_arrival:'2021-09-12T00:00:00Z',actual_berth_start:null,proposed_start:null,proposed_berth_id:null,actual_window_wait_hours:4,proposed_window_wait_hours:wait,window_wait_change_hours:wait===null?null:Number(wait)-4,status,known_at_cutoff:status!=='UNKNOWN_AT_CUTOFF',modelled_at_cutoff:status==='PROPOSED'||status==='DEFERRED'}));
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({available:true,plan:{run_id:'replay',as_of:'2021-09-13T00:00:00Z',end:'2021-09-16T00:00:00Z',assignments:[],shifts:[]},vessel_comparison:calls}))));
  const {default:userEvent}=await import('@testing-library/user-event');render(<HistoricalReplay/>);
  await screen.findByRole('table',{name:'Actual and proposed vessel comparison'});
  await userEvent.selectOptions(screen.getByLabelText('Replay call status'),'NOT_MODELLED');
  expect(screen.getByText('Three')).toBeInTheDocument();expect(screen.queryByText('Two')).not.toBeInTheDocument();
  expect(screen.getByText('Observed; berth identity unresolved')).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText('Replay call status'),'DEFERRED');
  expect(screen.getByText('Two')).toBeInTheDocument();expect(screen.getByText('72h')).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText('Find replay vessel'),'absent');
  expect(screen.getByText('No calls match this filter.')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Download comparison CSV'})).toBeDisabled();
});
