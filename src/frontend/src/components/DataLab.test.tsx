// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {DataLab} from './DataLab';
import {fixture} from '../testing/fixture';

afterEach(()=>{cleanup();vi.unstubAllGlobals()});

it('loads a scoped example, validates it and submits to the simulation API',async()=>{
  const data=fixture();
  const fetcher=vi.fn(async(url:string)=>new Response(JSON.stringify(url.endsWith('/validate')?
    {valid:true,accepted_rows:1,errors:[],preview:[]}:
    {source_run_id:data.run.id,persisted:false,uploaded_calls:1,solver_status:'FEASIBLE',baseline:data.run.metrics,
      metrics:{...data.run.metrics,validation_passed:true},assignments:[],diagnostics:{unscheduled_call_ids:['LAB-CALL-01']},assumptions:['Unsaved test.']})));
  vi.stubGlobal('fetch',fetcher);
  render(<DataLab data={data} port="P01"/>);
  await userEvent.click(screen.getByRole('button',{name:'Load example'}));
  expect((screen.getByLabelText('Vessel-call data') as HTMLTextAreaElement).value).toContain('LAB-CALL-01,T,');
  await userEvent.click(screen.getByRole('button',{name:'Run simulation'}));
  await screen.findByText('Schedule passed feasibility checks.');
  expect(fetcher.mock.calls.map(c=>c[0])).toEqual(['/api/v1/data-lab/validate','/api/v1/data-lab/simulate']);
});

it('shows row errors and blocks the solver for invalid input',async()=>{
  const fetcher=vi.fn(async()=>new Response(JSON.stringify({valid:false,accepted_rows:0,
    errors:[{row:1,field:'draft_m',message:'Draft must be positive.'}],preview:[]})));
  vi.stubGlobal('fetch',fetcher);
  render(<DataLab data={fixture()} port="all"/>);
  await userEvent.click(screen.getByRole('button',{name:'Load example'}));
  await userEvent.click(screen.getByRole('button',{name:'Run simulation'}));
  await screen.findByText('Draft must be positive.');
  expect(fetcher).toHaveBeenCalledTimes(1);
});
