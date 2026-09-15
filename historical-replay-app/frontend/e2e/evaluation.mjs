import {chromium,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';

const browser=await chromium.launch();
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();const errors=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));
try{
  const api=await context.request.get('http://127.0.0.1:8000/api/v1/evaluation/latest');
  expect(api.status()).toBe(200);const evidence=await api.json();expect(evidence.rows).toHaveLength(12);
  expect(evidence.synthetic).toBe(true);expect(evidence.real_world_validated).toBe(false);
  await page.goto('http://127.0.0.1:5173/#evaluation');
  await expect(page.getByRole('heading',{level:1,name:'Strategy evaluation'})).toBeVisible();
  await page.getByLabel('Evaluation scenario').waitFor({timeout:120000});
  for(const scenario of ['normal_operations','arrival_surge','storm_crane_breakdown']){
    await page.getByLabel('Evaluation scenario').selectOption(scenario);
    const rows=page.getByRole('table').first().locator('tbody tr');await expect(rows).toHaveCount(4);
    const source=evidence.rows.filter(r=>r.scenario_id===scenario);
    for(let i=0;i<4;i++){
      await expect(rows.nth(i)).toContainText(source[i].strategy);
      await expect(rows.nth(i).locator('td').nth(1)).toHaveText(`${source[i].served_vessels} / ${source[i].cohort_vessels}`);
      await expect(rows.nth(i).locator('td').nth(2)).toHaveText(String(source[i].deferred_vessels));
    }
    checks.push(`${scenario}: rendered counts match persisted API evidence`);
  }
  const download=page.waitForEvent('download');await page.getByRole('link',{name:'Download report'}).click();
  const file=await download;await file.saveAs('artifacts/evaluation/browser-report.md');
  expect(await fs.readFile('artifacts/evaluation/browser-report.md','utf8')).toContain('not real-world validated savings');
  checks.push('Working report download retains the simulation qualification');
  await fs.mkdir('docs/screenshots',{recursive:true});
  for(const width of [1440,768,390,360]){
    await page.setViewportSize({width,height:1000});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
    const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
    expect(axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);
    checks.push(`${width}px: accessibility and no horizontal overflow`);
  }
  await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'docs/screenshots/evaluation.png',fullPage:true});
  await page.route('**/api/v1/evaluation/latest',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Stored evaluation failed validation'}})}));
  await page.reload();await expect(page.getByRole('alert')).toContainText('Stored evaluation failed validation');
  await page.unroute('**/api/v1/evaluation/latest');await page.getByRole('button',{name:'Retry evaluation'}).click();
  await expect(page.getByLabel('Evaluation scenario')).toBeVisible();checks.push('Unavailable publication shows an error and retry recovers');
  expect(errors).toEqual([]);await fs.writeFile('artifacts/evaluation/browser-verification.json',JSON.stringify({result:'PASS',checks,errors},null,2));
  console.log('PASS: evaluation evidence, scenario selector, report download, responsive accessibility and failure recovery');
}finally{await browser.close()}
