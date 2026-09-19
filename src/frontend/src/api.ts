export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/,'');
let demoContext:string|null=null;
let historicalContext=false;
export function setHistoricalContext(active:boolean){historicalContext=active}
export function setDemoContext(id:string|null){demoContext=id}
export function scopedApiBase(){return API_BASE+(historicalContext?'/historical':demoContext?`/live-demo/${encodeURIComponent(demoContext)}`:'')}
export class ApiError extends Error {constructor(message:string,public status:number){super(message)}}
export async function request<T>(path:string,body?:unknown,signal?:AbortSignal):Promise<T> {
  const response=await fetch(scopedApiBase()+path,{credentials:'include',signal,method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){const data=await response.json().catch(()=>null);throw new ApiError(data?.error?.message||`API request failed (${response.status})`,response.status)}
  return response.json();
}
export async function downloadPlan(id:string,format:'json'|'csv'|'html') {
  const response=await fetch(`${scopedApiBase()}/plans/${encodeURIComponent(id)}/export?format=${format}`,{credentials:'include'});
  if(!response.ok){const data=await response.json().catch(()=>null);throw new ApiError(data?.error?.message||'Export failed',response.status)}
  const url=URL.createObjectURL(await response.blob());const anchor=document.createElement('a');anchor.href=url;anchor.download=`operations-plan-${id}.${format}`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export async function requestControl<T>(path:string,body?:unknown,signal?:AbortSignal):Promise<T>{
  const response=await fetch(API_BASE+path,{credentials:'include',signal,method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){const data=await response.json().catch(()=>null);throw new ApiError(data?.error?.message||`API request failed (${response.status})`,response.status)}
  return response.json();
}
