// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {fixture} from '../testing/fixture';
import {setDemoContext} from '../api';
import type {LiveState,DemoResult} from '../live';
import {LiveOperations} from './LiveOperations';

afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();vi.useRealTimers();setDemoContext(null)});
function state():LiveState{return {session:{id:'demo-a',port_id:'P01',clock:'2026-09-13T00:15:00Z',revision:2,status:'READY',latest_run_id:'run-new',initial_run_id:'run-old',active_event_id:null,settings:{}},events:[],connection:'SSE connected',error:null,pending:false,inject:vi.fn().mockResolvedValue(undefined),retry:vi.fn().mockResolvedValue(undefined)}}
function props(live=state()){return {data:fixture(),port:'all',live,onAttach:vi.fn(),onLeave:vi.fn(),onReview:vi.fn(),onApprove:vi.fn(),busy:false}}

it('creates an isolated session using the selected API port and source',async()=>{
  const p=props();p.live.session=null;const response={...state().session,id:'created-demo'};
  const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));vi.stubGlobal('fetch',fetcher);
  render(<LiveOperations {...p}/>);await userEvent.click(screen.getByRole('button',{name:'Start live demo'}));
  await waitFor(()=>expect(p.onAttach).toHaveBeenCalledWith(response));
  expect(fetcher.mock.calls[0][0]).toBe('/api/v1/live-demo/sessions');
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({source_run_id:p.data.run.id,port_id:p.data.inventory.routing_ports[0].id,seed:42});
});

it('connects compound failure, event injection and clock controls to backend actions',async()=>{
  const p=props();render(<LiveOperations {...p}/>);
  await userEvent.click(screen.getByRole('button',{name:'Storm + Crane Failure'}));
  expect(p.live.inject).toHaveBeenCalledWith({kind:'storm_crane_failure',duration_hours:8,advance_minutes:15});
  await userEvent.click(screen.getByRole('button',{name:'Advance 15 minutes'}));expect(p.live.inject).toHaveBeenCalledWith({kind:'clock_tick',advance_minutes:15});
  await userEvent.selectOptions(screen.getByLabelText('Affected resource or vessel'),p.data.inventory.calls[0].id);
  await userEvent.click(screen.getByRole('button',{name:'Inject event & replan'}));
  expect(p.live.inject).toHaveBeenLastCalledWith(expect.objectContaining({kind:'eta_delay',call_id:p.data.inventory.calls[0].id,hours:6}));
  expect(screen.getByRole('button',{name:'Recover & replan'})).toBeDisabled();
});

it('shows actual returned metrics including negatives and retains approval gates',async()=>{
  const p=props();const result={new_run_id:'run-new',old_run_id:'run-old',new_plan_id:'plan-new',plan_status:'DRAFT',schedule_status:'succeeded',solver_status:'FEASIBLE',approval_required:true,
    forecast_runtime_ms:1250,optimisation_runtime_ms:2500,solver_runtime_ms:1000,plan_change_count:3,ongoing_operation_count:2,frozen_assignment_count:4,
    forecast_run_id:'forecast-real',model_version:'model-real',event_effect:{warning_lead_hours:6,storm_start:'2026-09-13T06:15:00Z',storm_end:'2026-09-13T14:15:00Z',crane_ids:['C1']},
    metrics:{waiting_hours_avoided:-2,cost_improvement_usd:-15,emissions_improvement_tonnes_co2:-.5,congestion_reduction_vessel_hours:-4,deferred_vessels:1,certified:true},plan_changes:[],changed_risks:[],unresolved_conflicts:[],assumptions:['Trusted result assumption']} satisfies DemoResult;
  p.live.events=[{id:'event-real',session_id:'demo-a',sequence:1,kind:'storm_crane_failure',status:'SUCCEEDED',stage_revision:5,operational_time:'2026-09-13T00:15:00Z',payload:{},result,error:null}];
  const view=render(<LiveOperations {...p}/>);expect(screen.getByText('1.3 s')).toBeInTheDocument();expect(screen.getByText('-2 h')).toBeInTheDocument();expect(screen.getByText('-4 vessel-h')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Approve reviewed live draft'})).toBeDisabled();
  await userEvent.click(screen.getByRole('button',{name:'Review live draft'}));expect(p.onReview).toHaveBeenCalledOnce();
  p.data.run.plan!.status='REVIEWED';view.rerender(<LiveOperations {...p}/>);await userEvent.click(screen.getByRole('button',{name:'Approve reviewed live draft'}));expect(p.onApprove).toHaveBeenCalledOnce();
  expect(screen.getByText(/No approved plan was replaced automatically/)).toBeInTheDocument();
});

it('auto advances even when SSE session updates rerender the screen',()=>{
  vi.useFakeTimers();const p=props();const view=render(<LiveOperations {...p}/>);fireEvent.click(screen.getByLabelText('Auto advance every 30s'));
  vi.advanceTimersByTime(15000);p.live.session={...p.live.session!,revision:3};view.rerender(<LiveOperations {...p}/>);
  vi.advanceTimersByTime(15000);expect(p.live.inject).toHaveBeenCalledWith({kind:'clock_tick',advance_minutes:15});
});
