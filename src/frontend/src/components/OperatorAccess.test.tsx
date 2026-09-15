// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {OperatorAccess} from './OperatorAccess';

afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()});
function dialogs(){Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(this:HTMLDialogElement){this.setAttribute('open','')}});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(this:HTMLDialogElement){this.removeAttribute('open')}})}
it('exchanges the key for an HTTP-only backend session and clears the input',async()=>{
  dialogs();const fetcher=vi.fn(async(url:RequestInfo|URL)=>new Response(JSON.stringify(String(url).endsWith('/auth/status')?{required:true,authenticated:false}:{authenticated:true})));vi.stubGlobal('fetch',fetcher);
  const done=vi.fn();render(<OperatorAccess onAuthenticated={done}/>);await userEvent.click(screen.getByRole('button',{name:'Operator access'}));
  await userEvent.type(await screen.findByLabelText('Operator access key'),'operator-test-key');await userEvent.click(screen.getByRole('button',{name:'Unlock operations'}));
  await waitFor(()=>expect(done).toHaveBeenCalledOnce());expect(screen.queryByLabelText('Operator access key')).not.toBeInTheDocument();
  const call=fetcher.mock.calls.find(([url])=>String(url).endsWith('/auth/session'));expect(call).toBeTruthy();expect(localStorage.getItem('operator-test-key')).toBeNull();
});
it('shows denied access and clears the rejected key',async()=>{
  dialogs();vi.stubGlobal('fetch',vi.fn(async(url:RequestInfo|URL)=>String(url).endsWith('/auth/status')?new Response(JSON.stringify({required:true,authenticated:false})):new Response(JSON.stringify({error:{message:'Invalid operator access key'}}),{status:401})));
  render(<OperatorAccess onAuthenticated={vi.fn()}/>);await userEvent.click(screen.getByRole('button',{name:'Operator access'}));await userEvent.type(await screen.findByLabelText('Operator access key'),'wrong');await userEvent.click(screen.getByRole('button',{name:'Unlock operations'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid operator access key');expect(screen.getByLabelText('Operator access key')).toHaveValue('');
});
