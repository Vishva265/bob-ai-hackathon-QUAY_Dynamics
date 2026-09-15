import {useEffect,useRef,useState} from 'react';
import {ShieldCheck,X} from 'lucide-react';
import {requestControl} from '../api';

export function OperatorAccess({onAuthenticated}:{onAuthenticated:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null);
  const [access,setAccess]=useState<{required:boolean;authenticated:boolean}|null>(null);
  const [key,setKey]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null);
  useEffect(()=>{requestControl<{required:boolean;authenticated:boolean}>('/auth/status').then(setAccess).catch(()=>setError('Access service unavailable. Retry when opening this panel.'))},[]);
  async function open(){dialog.current?.showModal();setError(null);try{setAccess(await requestControl('/auth/status'))}catch(e){setError(e instanceof Error?e.message:'Access service unavailable')}}
  async function login(){setBusy(true);setError(null);try{await requestControl('/auth/session',{key});setKey('');setAccess({required:true,authenticated:true});dialog.current?.close();onAuthenticated()}catch(e){setKey('');setError(e instanceof Error?e.message:'Access failed')}finally{setBusy(false)}}
  async function logout(){setBusy(true);try{await requestControl('/auth/logout',{});setAccess({required:true,authenticated:false});dialog.current?.close();onAuthenticated()}catch(e){setError(e instanceof Error?e.message:'Logout failed')}finally{setBusy(false)}}
  return <><button className="icon-button" aria-label="Operator access" title="Operator access" onClick={open}><ShieldCheck size={17}/></button><dialog className="access-dialog" ref={dialog} aria-labelledby="access-title" onClose={()=>setKey('')}><header><h2 id="access-title">Operator access</h2><button className="icon-button" aria-label="Close operator access" onClick={()=>dialog.current?.close()}><X size={18}/></button></header>{error&&<p role="alert">{error}</p>}{!access?<p role="status">Checking access configuration…</p>:!access.required?<p>This local demo requires no access key.</p>:access.authenticated?<><p>Operator session active. Approvals still require explicit review and supervisor attribution.</p><button className="button secondary" disabled={busy} onClick={logout}>Lock operations</button></>:<form onSubmit={e=>{e.preventDefault();login()}}><p>Enter the server-configured operator key. Access expires after two hours.</p><label>Operator access key<input aria-label="Operator access key" type="password" autoComplete="off" maxLength={512} value={key} onChange={e=>setKey(e.target.value)} required/></label><button className="button primary" disabled={busy||!key}>{busy?'Checking key…':'Unlock operations'}</button></form>}</dialog></>
}
