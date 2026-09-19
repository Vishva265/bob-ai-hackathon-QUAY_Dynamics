import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';

const ui=process.env.QUAY_TEST_UI||'http://127.0.0.1:5173';
const browser=await chromium.launch();
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await fs.mkdir('artifacts/enhancements',{recursive:true});
try{
  const auth=await context.request.post(ui+'/api/v1/auth/session',{
    data:{key:process.env.OPERATOR_API_KEY||'quay-local-demo-only-operator-key-2026'}});
  expect(auth.ok()).toBeTruthy();
  await page.goto(ui+'/#data-lab');
  await page.getByRole('button',{name:'Load example',exact:true}).waitFor({timeout:120000});
  await page.getByRole('button',{name:'Load example',exact:true}).click();
  await page.getByRole('button',{name:'Validate data',exact:true}).click();
  await expect(page.getByText('1 rows validated. Ready to simulate.')).toBeVisible();
  await page.getByRole('button',{name:'Run simulation',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Simulation results',exact:true})).toBeVisible({timeout:120000});
  await page.screenshot({path:'artifacts/enhancements/data-lab.png',fullPage:true});
  await page.getByRole('button',{name:'BOB Operations Copilot',exact:true}).click();
  await page.getByRole('button',{name:'How does MCP connect IBM Bob?',exact:true}).click();
  await page.getByRole('button',{name:'Ask copilot',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Retrieved sources',exact:true})).toBeVisible({timeout:30000});
  await expect(page.locator('.copilot-direct')).toContainText('[1]');
  await page.screenshot({path:'artifacts/enhancements/copilot-rag.png',fullPage:true});
  await page.getByRole('button',{name:'Historical AIS replay',exact:true}).click();
  await expect(page.getByRole('heading',{name:'2021 LA/LB Historical Replay',exact:true})).toBeVisible({timeout:30000});
  await expect(page.getByRole('table',{name:'Historical replay evaluation metrics'})).toBeVisible();
  await page.screenshot({path:'artifacts/enhancements/historical-replay.png',fullPage:true});
  expect(errors).toEqual([]);
  console.log(JSON.stringify({data_lab:true,rag_citations:true,historical_replay:true,browser_errors:errors}));
}finally{await browser.close()}
