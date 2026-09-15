import {chromium, expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';

const browser = await chromium.launch();
const checks = [], errors = [];
const context = await browser.newContext({viewport:{width:1440,height:1000}});
const page = await context.newPage();
page.on('pageerror', error => errors.push(error.message));
const views = ['Executive overview','Congestion heatmap','Berth planning','Port network map','Supervisor shift plan','Scenario simulator','Port Operations Copilot','Live operations demo'];
try {
  await page.goto('http://127.0.0.1:5173');
  await page.locator('.command-banner').waitFor({timeout:120000});
  for (const width of [1440,768,390,360]) {
    await page.setViewportSize({width,height:1000});
    for (const name of views) {
      if (width <= 650) await page.getByRole('button',{name:'Toggle navigation'}).click();
      await page.getByRole('navigation').getByRole('button',{name,exact:true}).click();
      await expect(page.getByRole('heading',{name,exact:true,level:1})).toBeVisible();
      await page.locator('main .loading').waitFor({state:'hidden',timeout:120000});
      const overflow = await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
      expect(overflow,`${name} overflows at ${width}px`).toBe(false);
      const axe = await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
      expect(axe.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),`${name} accessibility at ${width}px`).toEqual([]);
      checks.push({view:name,width,overflow,accessibility:'PASS'});
    }
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.route('**/api/v1/dashboard?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'DATABASE_UNAVAILABLE',message:'Database is unavailable'}})}));
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.locator('.api-status')).toContainText('API unavailable');
  await expect(page.getByRole('alert')).toContainText('Showing previously loaded run');
  await page.unroute('**/api/v1/dashboard?*');
  await page.getByRole('button',{name:'Retry loading'}).click();
  await expect(page.locator('.api-status')).toContainText('API connected',{timeout:120000});
  checks.push({check:'Failed refresh labels cached values and retry recovers',result:'PASS'});

  const secureContext = await browser.newContext({viewport:{width:390,height:844}});
  const secure = await secureContext.newPage();
  secure.on('pageerror',error=>errors.push(error.message));
  await secure.goto('http://127.0.0.1:5174');
  await expect(secure.getByRole('alert')).toContainText('Operator access required',{timeout:120000});
  await secure.getByRole('button',{name:'Operator access',exact:true}).click();
  await secure.getByLabel('Operator access key').fill('wrong');
  await secure.getByRole('button',{name:'Unlock operations'}).click();
  await expect(secure.getByRole('dialog').getByRole('alert')).toContainText('Invalid operator access key');
  await expect(secure.getByLabel('Operator access key')).toHaveValue('');
  await secure.getByLabel('Operator access key').fill(process.env.E2E_OPERATOR_KEY);
  await secure.getByRole('button',{name:'Unlock operations'}).click();
  await expect(secure.locator('.api-status')).toContainText('API connected',{timeout:120000});
  const cookies = await secureContext.cookies();
  expect(cookies.find(c=>c.name==='port_operator')?.httpOnly).toBe(true);
  expect(await secure.evaluate(()=>Object.keys(localStorage))).toEqual([]);
  await secure.getByRole('button',{name:'Operator access',exact:true}).click();
  await expect(secure.getByRole('button',{name:'Lock operations'})).toBeVisible();
  const axe = await new AxeBuilder({page:secure}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
  expect(axe.violations.map(v=>v.id)).toEqual([]);
  await secure.getByRole('button',{name:'Lock operations'}).click();
  await expect(secure.locator('.api-status')).toContainText('API unavailable');
  await expect(secure.getByRole('alert')).toContainText('Operator access required');
  checks.push({check:'Real login, invalid key, HttpOnly cookie, logout and mobile access dialog',result:'PASS'});
  expect(errors).toEqual([]);
  await fs.writeFile('artifacts/readiness-browser.json',JSON.stringify({result:'PASS',checks,errors},null,2));
  console.log(`PASS: ${checks.length} responsive, accessibility, recovery and authentication checks.`);
} catch(error) {
  await fs.writeFile('artifacts/readiness-browser.json',JSON.stringify({result:'FAIL',checks,errors,failure:String(error)},null,2));
  throw error;
} finally { await browser.close(); }
