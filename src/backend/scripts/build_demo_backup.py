"""Generate a standalone recorded presentation: local assets, no API or scripts."""
from pathlib import Path
import html
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]


def main():
    backup = ROOT/'demo/backup'
    assets = backup/'assets'
    assets.mkdir(parents=True,exist_ok=True)
    recorded = ROOT/'demo/recorded'
    shutil.copytree(recorded,backup/'outputs',dirs_exist_ok=True)
    images = [('overview.png','Current operations'),('heatmap.png','Hourly early warnings'),
        ('live-operations.png','Persisted storm and rolling draft'),('timeline.png','Timed berth/crane allocation'),
        ('shifts.png','Nine-shift supervisor plan'),('evaluation.png','Measured strategy comparison')]
    demo_names={'overview.png':'normal','heatmap.png':'warning','live-operations.png':'storm',
        'timeline.png':'allocation','shifts.png':'shifts','evaluation.png':'evaluation'}
    for filename,_ in images:
        captured=ROOT/'docs/screenshots/demo'/f'{demo_names[filename]}.png'
        shutil.copy2(captured if captured.exists() else ROOT/'docs/screenshots'/filename,assets/filename)
    summary=json.loads((recorded/'summary.json').read_text())
    routing=json.loads((recorded/'routing.json').read_text())
    decision=routing['recommendations'][0]
    live=json.loads((recorded/'live-results.json').read_text())
    storm=live['storm']['result']
    escape=lambda value:html.escape(str(value))
    rows=''.join('<tr>'+''.join(f'<td>{escape(value)}</td>' for value in
        [r['scenario'],r['strategy'],f"{r['average_wait_hours']:.2f}",f"{r['p90_wait_hours']:.2f}",
         r['served_vessels'],r['deferred_vessels'],f"{r['estimated_cost_savings_usd']:,.0f}",f"{r['estimated_emissions_savings_tonnes_co2']:.2f}"])
        +'</tr>' for r in summary['rows'])
    rejects=sorted({code for o in decision['options'] for code in o['rejection_codes']})
    reasons=''.join('<li>'+escape(r.get('message',r))+'</li>' for r in decision['main_reasons'])
    sections=[]
    for index,(filename,title) in enumerate(images,1):
        sections.append(f'<section id="step{index}"><p class="eyebrow">RECORDED STEP {index}</p><h2>{title}</h2><img src="assets/{filename}" alt="Actual seeded QUAY: {title}" loading="lazy"></section>')
    sections.insert(4,f'''<section id="routing"><p class="eyebrow">RECORDED RESPONSIBLE ROUTING</p><h2>{escape(decision['recommended_action'].replace('_',' '))}</h2><p>Vessel {escape(decision['call_id'])}. Source {escape(routing['source_run_id'])}; {escape(routing['as_of'])} UTC; model {escape(routing['model_version'])}. LOW confidence. Historical, expired and unapproved; no receiving capacity is reserved.</p><ul>{reasons}</ul><p>Rejected alternatives: {escape(', '.join(rejects))}.</p><a href="outputs/routing.json">Inspect every option and end-to-end impact</a></section>''')
    text=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>QUAY — recorded hackathon backup</title><style>
    :root{{color-scheme:light;font:16px/1.65 system-ui,sans-serif;color:#18343b;background:#edf3f3}}body{{margin:0}}main{{max-width:1150px;margin:auto;padding:32px 20px}}h1{{font-size:clamp(2rem,5vw,3.5rem);line-height:1.1}}h2{{line-height:1.2}}a{{color:#095b60}}nav{{display:flex;flex-wrap:wrap;gap:16px}}section{{background:white;border:1px solid #c8d8d8;border-radius:14px;padding:24px;margin:24px 0}}img{{width:100%;height:auto;border:1px solid #d1dddd;border-radius:8px}}.warning{{background:#fff1d5;border-left:5px solid #94620c;padding:18px}}.eyebrow{{font-size:.8rem;letter-spacing:.12em;font-weight:700}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;min-width:950px}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #d6e1e1;font-variant-numeric:tabular-nums}}th{{background:#eef5f5}}code{{word-break:break-all}}@media print{{nav{{display:none}}section{{break-inside:avoid}}}}
    </style><main><p class="eyebrow">QUAY · OPERATIONS INTELLIGENCE</p><h1>Evidence before action.</h1><p class="warning"><strong>Recorded synthetic demonstration — services may be offline.</strong> These are actual screenshots and persisted outputs, not live telemetry or real-world validated savings. Source datasets use seed 42 and fixed UTC clocks. No network requests, external fonts or interactive fake controls.</p>
    <nav aria-label="Recorded demo steps"><a href="#step1">Current operations</a><a href="#step2">Early warning</a><a href="#step3">Storm event</a><a href="#step4">Berth/crane changes</a><a href="#routing">Routing gates</a><a href="#step5">Shift plan</a><a href="#metrics">Measured impact</a></nav>
    <section><h2>Thirty-second pitch</h2><p>Ports discover congestion too late. QUAY forecasts pressure for 72 hours, then allocates compatible berths, cranes and yard capacity using mathematical optimisation. Disruptions create fresh drafts while ongoing work stays fixed. Supervisors receive nine handovers and retain approval authority. Synthetic evaluations show scheduling trade-offs; real AIS and terminal-system validation are next.</p><p>Recorded incident: {escape(storm['forecast_runtime_ms']/1000)}s forecast; {escape(storm['optimisation_runtime_ms']/1000)}s engine; {escape(storm['plan_change_count'])} plan changes. The receipt says operational_plan_replaced=false, approval_required=true and plan_status=DRAFT. These scoped live values differ from the frozen network benchmark below.</p><a href="outputs/live-results.json">Persisted event and recovery receipts</a></section>
    {''.join(sections)}<section id="metrics"><h2>All four strategies, all three scenarios</h2><p>Frozen publication {escape(summary['generated_at'])}; model {escape(summary['model_version'])}. Served averages exclude deferred calls; total-delay accounting retains their 120h lower bounds. Berth starts can occur after 72h. Proxy savings are hypothetical and configurable.</p><div class="scroll" tabindex="0"><table><thead><tr><th>Scenario</th><th>Strategy</th><th>Mean wait h</th><th>P90 h</th><th>Served</th><th>Deferred</th><th>Cost proxy savings USD</th><th>CO₂ proxy savings t</th></tr></thead><tbody>{rows}</tbody></table></div><p class="warning">Maximum waits increased. Predictive/routing scheduling had no incremental primary benefit over joint berth/crane scheduling. No reroutes were approved or executed. Surge waiting MAE is 42.03h; confidence remains LOW. No live AIS/TOS integration or real operational validation is claimed.</p><p><a href="outputs/hackathon-evaluation.md">Full report</a> · <a href="outputs/strategy-comparison.csv">All metrics CSV</a> · <a href="outputs/summary.json">Dashboard-ready evidence</a> · <a href="outputs/supervisor-plan.html">Printable supervisor plan</a> · <a href="outputs/supervisor-plan.json">Plan JSON</a> · <a href="outputs/supervisor-plan.csv">Plan CSV</a></p></section></main></html>'''
    (backup/'index.html').write_text(text,encoding='utf-8')
    shutil.copytree(backup,ROOT/'frontend/public/demo-backup',dirs_exist_ok=True)
    print('Generated standalone disk/browser backup and dashboard-served copy.')


if __name__=='__main__':main()
