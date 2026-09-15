import {chromium,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
await fs.mkdir('artifacts/live-demo-browser',{recursive:true});
function sourceDigest(){const result=spawnSync('python',['-c',`import sqlite3,json,hashlib,sys
c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
d={}
for (name,) in c.execute("select name from sqlite_master where type='table' order by name"):
 if name.startswith('live_demo_'):continue
 rows=c.execute('select * from "'+name+'"').fetchall()
 d[name]=hashlib.sha256(json.dumps(sorted(rows,key=str),default=str).encode()).hexdigest()
print(json.dumps(d))`,process.env.E2E_DATABASE_PATH||'artifacts/dashboard.db'],{encoding:'utf8'});if(result.status)throw Error(result.stderr);return JSON.parse(result.stdout)}
const before=sourceDigest();const browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();
const errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>{window.liveSse=[];const Native=window.EventSource;window.EventSource=class extends Native{constructor(...args){super(...args);this.addEventListener('operation',e=>window.liveSse.push(JSON.parse(e.data)))}}});
try{
  await page.goto('http://127.0.0.1:5173/#live');await page.getByRole('button',{name:'Start live demo',exact:true}).waitFor({timeout:120000});
  const created=page.waitForResponse(r=>r.url().endsWith('/live-demo/sessions')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Start live demo',exact:true}).click();const session=await (await created).json();expect(session.id).toMatch(/^[a-f0-9]{32}$/);
  await expect(page.locator('.live-clock')).toContainText('SSE connected',{timeout:120000});checks.push('Isolated session starts and SSE connects.');
  await page.getByRole('button',{name:'Storm + Crane Failure',exact:true}).click();
  await expect(page.locator('.live-event-status')).toContainText('SUCCEEDED',{timeout:120000});await page.locator('.live-metrics').waitFor({timeout:120000});
  await expect(page.getByText('Published storm warning: 6 hours ahead')).toBeVisible();
  const storm=(await page.evaluate(()=>window.liveSse)).findLast(e=>e.kind==='storm_crane_failure'&&e.status==='SUCCEEDED');expect(storm?.result.changed_risks.length).toBeGreaterThan(0);expect(storm.result.plan_change_count).toBeGreaterThan(0);expect(storm.result.plan_status).toBe('DRAFT');
  expect(storm.result.operational_plan_replaced).toBe(false);checks.push('Persisted failure produces forecast risks, measured metrics and rolling draft through SSE.');
  await expect(page.locator('.api-status')).toContainText('API connected',{timeout:120000});
  await expect(page.getByRole('button',{name:'Approve reviewed live draft'})).toBeDisabled();
  await page.screenshot({path:'docs/screenshots/live-operations.png',fullPage:true});
  const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();const violations=axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.failureSummary)}));
  await page.getByRole('button',{name:'Recover & replan'}).click();await expect(page.locator('.live-event-status')).toContainText('storm crane recovery · SUCCEEDED',{timeout:120000});
  const recovery=(await page.evaluate(()=>window.liveSse)).findLast(e=>e.kind==='storm_crane_recovery'&&e.status==='SUCCEEDED');expect(recovery.result.plan_status).toBe('DRAFT');expect(recovery.result.operational_plan_replaced).toBe(false);checks.push('Recovery observations trigger another forecast and draft; approval remains gated.');
  // A complete recovered draft requires two explicit operator actions.
  expect(recovery.result.metrics.deferred_vessels).toBe(0);
  const planUrl='http://127.0.0.1:8000/api/v1/live-demo/'+session.id+'/plans/'+recovery.result.new_plan_id;
  await expect(page.getByRole('button',{name:'Review live draft'})).toBeEnabled({timeout:120000});
  const reviewed=page.waitForResponse(r=>new URL(r.url()).pathname===new URL(planUrl+'/review').pathname&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Review live draft'}).click();expect((await reviewed).status()).toBe(200);
  await expect(page.getByRole('button',{name:'Approve reviewed live draft'})).toBeEnabled({timeout:120000});
  const approved=page.waitForResponse(r=>new URL(r.url()).pathname===new URL(planUrl+'/approve').pathname&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Approve reviewed live draft'}).click();expect((await approved).status()).toBe(200);
  expect((await (await context.request.get(planUrl)).json()).status).toBe('APPROVED');
  checks.push('The complete recovery draft is reviewed and approved through two working operator controls.');
  // Inspect a second view while the global SSE subscriber remains mounted.
  await page.getByRole('button',{name:'Berth planning',exact:true}).click();await expect(page.locator('.live-global-notice')).toContainText('SSE connected');await expect(page.locator('h1')).toHaveText('Berth planning');
  const clockResponse=await context.request.get('http://127.0.0.1:8000/api/v1/live-demo/'+session.id);const clock=await clockResponse.json();
  await context.request.post('http://127.0.0.1:8000/api/v1/live-demo/'+session.id+'/events',{data:{kind:'clock_tick',expected_revision:clock.revision,advance_minutes:15}});
  await expect.poll(async()=>new URL(page.url()).searchParams.get('run'),{timeout:120000}).not.toBe(recovery.result.new_run_id);
  expect((await (await context.request.get(planUrl)).json()).status).toBe('APPROVED');
  const postApproval=(await page.evaluate(()=>window.liveSse)).findLast(e=>e.kind==='clock_tick'&&e.status==='SUCCEEDED');
  expect(postApproval.result.plan_status).toBe('DRAFT');expect(postApproval.result.operational_plan_replaced).toBe(false);
  checks.push('Replanning after approval preserves the approved plan and creates a separate draft.');
  checks.push('An external event refreshes the berth dashboard without leaving its view.');
  await page.getByRole('button',{name:'Live operations demo',exact:true}).click();await page.setViewportSize({width:390,height:844});await expect(page.locator('.sidebar')).not.toBeInViewport();
  await page.screenshot({path:'artifacts/live-demo-browser/mobile.png',fullPage:true});const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  await page.getByRole('button',{name:'Leave live demo'}).click();await expect(page.getByRole('button',{name:'Start live demo',exact:true})).toBeVisible({timeout:120000});expect(new URL(page.url()).searchParams.has('demo')).toBe(false);
  const after=sourceDigest();expect(after).toEqual(before);expect(errors).toEqual([]);expect(violations).toEqual([]);expect(overflow).toBe(false);
  const events=await page.evaluate(()=>window.liveSse);await fs.writeFile('artifacts/live-demo-browser/results.json',JSON.stringify({checks,errors,violations,mobileOverflow:overflow,sourceUnchanged:true,sourceBefore:before,sourceAfter:after,session,storm,recovery,postApproval,sseStatuses:[...new Set(events.map(e=>e.status))]},null,2));
  console.log('PASS: event → persisted state → forecasts → rolling draft → SSE → dashboard; recovery, approval gates, original-data preservation, accessibility and mobile layout.');
}finally{await browser.close()}
