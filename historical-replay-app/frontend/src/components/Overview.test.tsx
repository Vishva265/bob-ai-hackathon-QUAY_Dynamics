// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,within} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {Overview} from './Overview';
import {fixture} from '../testing/fixture';
import type {Forecast} from '../types';

afterEach(cleanup);
it('does not display savings or comparison figures from an infeasible schedule',()=>{
  const d=fixture();d.run.status='failed';d.run.solver_status='INFEASIBLE';
  render(<Overview data={d} port="all" onView={vi.fn()} onVessel={vi.fn()}/>);
  expect(screen.getByText('No schedule comparison available.')).toBeInTheDocument();
  expect(screen.queryByText('Estimated planning cost saved')).not.toBeInTheDocument();
});
it('displays the API utilisation percentages without rounding the raw fraction first',()=>{
  const d=fixture();d.forecast_rows=[{id:'row',scope:'port',scope_id:'P01',port_id:'P01',timestamp:d.run.as_of,
    berth_utilisation:.876,crane_utilisation:.944,yard_occupancy:.913,congestion_probability:.65,
    average_wait_hours:5,queue_length:1,congestion_severity:'HIGH',is_hotspot:0,confidence_level:'LOW',
    terminal_id:null,berth_id:null,confidence_reasons:[],main_causes:[],first_expected_hotspot_time:null,
    expected_hotspot_duration_hours:0,model_version:'test',prediction_timestamp:d.run.as_of} as Forecast];
  render(<Overview data={d} port="all" onView={vi.fn()} onVessel={vi.fn()}/>);
  for(const [label,value] of [['Berth utilisation','88%'],['Crane utilisation','94%'],['Yard occupancy','91%']]){
    const card=screen.getAllByText(label).find(el=>el.closest('article'))!.closest('article')!;expect(within(card).getByText(value)).toBeInTheDocument();
  }
});
