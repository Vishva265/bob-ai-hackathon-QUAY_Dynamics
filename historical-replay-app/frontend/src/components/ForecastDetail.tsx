import type {Forecast,ForecastSource} from '../types';
import {number,utc} from '../selectors';
import {Badge,ReasonList} from './Primitives';

function time(value:string|null|undefined){return value?`${utc(value,true)} UTC`:'Unavailable'}
const units:Record<string,string>={closing_teu:'TEU',capacity_teu:'TEU',wind_mps:'m/s',rain_mm_per_hour:'mm/h'};
function Source({source:s}:{source:ForecastSource}){
  return <li className="forecast-source"><strong>{s.label}</strong><span className="source-type">{s.source_type}</span>
    <p>Source timestamp: {time(s.source_timestamp)}{s.effective_timestamp&&<> · Known at: {time(s.effective_timestamp)}</>}</p>
    {(s.start||s.end)&&<p>Input window: {time(s.start)} → {s.end?time(s.end):'End unknown'}</p>}
    <p>Freshness at forecast hour: {s.freshness.replaceAll('_',' ')}{s.age_hours!==null&&<> · Age: {number(s.age_hours)}h</>}</p>
    <dl className="source-values">{Object.entries(s.values).map(([k,v])=><div key={k}><dt>{k.replaceAll('_',' ')}</dt><dd>{typeof v==='number'?`${number(v)} ${units[k]||''}`:String(v)}</dd></div>)}</dl>
    {s.assumptions.length>0&&<ReasonList items={s.assumptions}/>}</li>
}
export function ForecastDetail({forecast:f}:{forecast:Forecast}){
  const e=f.explanation,band=Number.isFinite(f.probability_lower)&&Number.isFinite(f.probability_upper);
  return <div className="forecast-explanation">
    <section aria-labelledby="outcomes-heading"><h3 id="outcomes-heading">Forecast snapshot · Predicted outcomes</h3>
      <p>These are future resource projections. Utilisation, queue and yard stock use a deterministic FIFO projection; average wait also uses vessel waiting predictions. They are not observations or an optimised schedule.</p>
      <dl className="forecast-outcomes">{[['Predicted berth utilisation',`${number(f.berth_utilisation*100)}%`],['Predicted queue length',`${number(f.queue_length)} vessels`],['Predicted average wait',`${number(f.average_wait_hours)}h`],['Predicted yard occupancy',`${number(f.yard_occupancy*100)}%`],['Predicted crane utilisation',`${number(f.crane_utilisation*100)}%`]].map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      <small>Projection method: {e?.projection_method||'Unavailable'}</small></section>
    <section aria-labelledby="signal-heading"><h3 id="signal-heading">Model signal</h3>
      <p className="forecast-signal">Congestion event probability: <strong>{number(f.congestion_probability*100)}%</strong></p>
      <p>This is the model’s estimated probability of its congestion-event target. It is not the confidence level and not the probability that every displayed operational value is correct.</p>
      {f.probability_basis==='terminal_model_prior'&&<p className="forecast-attention">This berth inherits its terminal’s model probability; it is not a calibrated berth-level prediction.</p>}
      <p>Model version: <strong>{f.model_version||'Unavailable'}</strong> · Generated: {time(f.prediction_timestamp)}</p>
      {band?<p>Model event-error band: <strong>{number(f.probability_lower!*100)}%–{number(f.probability_upper!*100)}%</strong>. This is not a calibrated probability confidence interval or a waiting-time range.</p>:<p>Uncertainty band: unavailable. No range has been inferred.</p>}</section>
    <section aria-labelledby="severity-heading"><h3 id="severity-heading">Operational severity: <Badge level={f.congestion_severity}/></h3>
      <p>{e?.severity_explanation||'The stored severity is available; its rule provenance has not been supplied. Exact thresholds cannot be explained for this response.'}</p>
      <p>Severity expresses operational impact using resource-projection rules and model signals. It is a separate measure from the congestion event probability.</p></section>
    <section aria-labelledby="confidence-heading"><h3 id="confidence-heading">Forecast confidence: <Badge level={`${f.confidence_level} CONFIDENCE`}/></h3>
      <p>{e?.confidence_explanation||`Forecast confidence is ${f.confidence_level}. Recorded reasons are listed below.`}</p><ReasonList items={f.confidence_reasons}/>
      {f.confidence_level==='LOW'&&<p className="forecast-attention">Low confidence means operator review is required; it does not cancel the alert.</p>}</section>
    <section aria-labelledby="inputs-heading"><h3 id="inputs-heading">Known inputs and assumptions</h3>
      <p>These source conditions feed the forecast. Persistence assumptions and scenario overrides are not future observations.</p>
      {e?.inputs.length?<ul className="forecast-sources">{e.inputs.map((s,i)=><Source key={`${s.kind}-${i}`} source={s}/>)}</ul>:<p role="status">Input provenance unavailable. Recorded cause names do not establish an observation timestamp or an input window.</p>}
      {e?.missing_provenance.length?<ReasonList items={e.missing_provenance}/>:null}</section>
    <section aria-labelledby="interpretation-heading"><h3 id="interpretation-heading">Why this needs attention</h3>
      <p>{e?.operator_interpretation||'A detailed operator interpretation is unavailable. Review the stored causes and confidence reasons before acting.'}</p>
      <details><summary>Recorded operational causes</summary><ReasonList items={f.main_causes}/></details></section>
    <section className="forecast-action" aria-labelledby="action-heading"><h3 id="action-heading">Recommended supervisor action</h3><strong>{e?.supervisor_action||'Review before next shift'}</strong>
      <p>{e?.action_reason||'Explanation provenance is missing. Obtain current input data and rule evidence before changing the plan.'}</p>
      <p>Human approval: {e?.human_approval_required===false?'not required for monitoring':'required before replacing an approved plan or dispatching a change'}. Plan state: {e?.plan_status||'Unavailable'}.</p><p>This guidance does not modify assignments or approve a plan.</p></section>
    <details className="forecast-audit"><summary>Forecast provenance and assumptions</summary><p>Forecast run: {e?.forecast_run_id||f.run_id||'Unavailable'} · Input hash: {e?.input_hash||'Unavailable'}</p>
      {e?.assumptions.length?<ReasonList items={e.assumptions}/>:<p>Recorded run assumptions unavailable.</p>}</details>
  </div>
}
