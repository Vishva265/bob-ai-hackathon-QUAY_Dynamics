// Real isolated demo API + Chromium. No operational writes or model inference changes.
import {chromium,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';

const ui=process.env.FORECAST_TEST_UI||'http://127.0.0.1:5195';
const api=process.env.FORECAST_TEST_API||'http://127.0.0.1:8055';
const seed=JSON.parse(await fs.readFile('demo/seed/metadata.json','utf8'));
const out='artifacts/forecast-explanations-browser';await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch();
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));
const authentication=await context.request.post(api+'/api/v1/auth/session',{data:{key:'quay-local-demo-only-operator-key-2026'}});
expect(authentication.ok()).toBeTruthy();
try{
  for(const [label,id] of [['normal',seed.normal_run_id],['storm',seed.storm_run_id]]){
    const response=await context.request.get(api+'/api/v1/dashboard?run_id='+id);
    expect(response.ok()).toBeTruthy();const data=await response.json();
    const before=structuredClone(data.run);
    const row=data.forecast_rows.find(r=>r.scope==='terminal'&&r.confidence_level==='LOW'&&r.congestion_severity==='HIGH'&&r.main_causes.some(c=>c.code==='WAITING_TIME'&&c.evidence.threshold!==undefined));
    expect(row).toBeTruthy();
    await page.goto(ui+'/?run='+id+'#heatmap');
    await expect(page.getByRole('heading',{level:1,name:'Congestion heatmap'})).toBeVisible({timeout:120000});
    await page.getByLabel('Port scope').selectOption(row.port_id);
    await page.getByLabel('Heatmap row scope').selectOption('terminal');
    const name=data.inventory.terminals.find(t=>t.id===row.scope_id).name;
    const index=(Date.parse(row.timestamp)-Date.parse(data.run.as_of))/3600000;
    const target=page.locator('.heat-row.scope-terminal').filter({has:page.locator('.heat-name',{hasText:name})}).locator('button.heat-cell').nth(index);
    await target.click();const detail=page.locator('#heat-detail');
    for(const title of ['Forecast snapshot · Predicted outcomes','Model signal','Known inputs and assumptions','Why this needs attention','Recommended supervisor action'])await expect(detail.getByRole('heading',{name:title,exact:true})).toBeVisible();
    await expect(detail.getByRole('heading',{name:'Operational severity: HIGH',exact:true})).toBeVisible();
    await expect(detail.getByRole('heading',{name:'Forecast confidence: LOW CONFIDENCE',exact:true})).toBeVisible();
    await expect(detail.getByText('Congestion event probability:',{exact:false})).toContainText((row.congestion_probability*100).toLocaleString('en-GB',{maximumFractionDigits:1})+'%');
    await expect(detail).toContainText(row.explanation.severity_explanation);
    await expect(detail).toContainText('it does not cancel the alert');
    await expect(detail).toContainText('FORECAST_ASSUMPTION');
    await expect(detail).toContainText('OBSERVED');
    if(label==='storm'){
      const restricted=data.forecast_rows.find(r=>r.scope==='terminal'&&r.explanation.inputs.some(s=>s.source_type==='SCENARIO_OVERRIDE'));
      expect(restricted).toBeTruthy();checks.push('Storm inputs explicitly carry SCENARIO_OVERRIDE provenance.');
    }
    for(const width of [1440,390]){
      await page.setViewportSize({width,height:1000});await detail.scrollIntoViewIfNeeded();
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
      expect(overflow).toBeFalsy();
      const audit=await new AxeBuilder({page}).include('#heat-detail').withTags(['wcag2a','wcag2aa']).analyze();
      expect(audit.violations).toEqual([]);
      await page.screenshot({path:`${out}/${label}-${width}.png`,fullPage:true});
      checks.push(`${label}: ${width}px panel has no page overflow and passes WCAG AA.`);
    }
    await page.setViewportSize({width:1440,height:1000});
    // Keep the pointer away: resizing/scrolling can legitimately trigger hover
    // while testing keyboard focus. Exercise those interactions separately.
    await page.mouse.move(5,5);await target.focus();await expect(target).toBeFocused();await page.keyboard.press('ArrowRight');
    await expect(detail.locator('.eyebrow')).toContainText('+'+(index+1)+'h');
    await target.hover();await expect(detail.locator('.eyebrow')).toContainText('+'+index+'h');
    const after=await (await context.request.get(api+'/api/v1/dashboard?run_id='+id)).json();
    expect(after.run).toEqual(before);checks.push(`${label}: stored values, explanation evidence, keyboard/hover selection and plan immutability passed.`);
  }
  // Explicit legacy/missing-provenance state; intercept only this test's response.
  await page.route('**/api/v1/dashboard?*',async route=>{
    const response=await route.fetch();const data=await response.json();
    for(const row of data.forecast_rows){row.explanation=null;delete row.probability_lower;delete row.probability_upper;}
    await route.fulfill({response,json:data});
  });
  await page.goto(ui+'/?run='+seed.normal_run_id+'#heatmap');
  await expect(page.locator('button.heat-cell').first()).toBeVisible({timeout:120000});
  await page.locator('button.heat-cell').first().click();
  await expect(page.locator('#heat-detail')).toContainText('Input provenance unavailable');
  await expect(page.locator('#heat-detail')).toContainText('No range has been inferred');
  checks.push('Missing provenance/band shown explicitly with no invented data.');
  await page.unroute('**/api/v1/dashboard?*');
  await page.route('**/api/v1/dashboard?*',async route=>{await new Promise(resolve=>setTimeout(resolve,1000));await route.continue()});
  await page.getByRole('button',{name:'Refresh dashboard',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Loading forecast evidence',exact:true})).toBeVisible();
  await expect(page.locator('button.heat-cell').first()).toBeVisible({timeout:120000});
  checks.push('Actual dashboard refresh exposes loading evidence, then restores the persisted matrix.');
  expect(errors).toEqual([]);
  await fs.writeFile(out+'/verification.json',JSON.stringify({result:'PASS',checks,errors},null,2));
  console.log('PASS: '+checks.length+' browser checks; normal/storm, desktop/mobile, evidence, immutability, interactions and unavailable state.');
}catch(error){await fs.writeFile(out+'/verification.json',JSON.stringify({result:'FAIL',checks,errors,failure:String(error)},null,2));await page.screenshot({path:out+'/failure.png',fullPage:true});throw error}
finally{await browser.close()}
