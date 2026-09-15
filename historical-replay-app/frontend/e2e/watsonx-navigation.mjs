// Read-only presentation/development critical views; no mocked provider identity.
import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
const ui=process.env.COPILOT_TEST_UI||'http://127.0.0.1:5173';
await fs.mkdir('artifacts/copilot',{recursive:true});
const browser=await chromium.launch(),page=await browser.newPage();
const errors=[],views=[];page.on('pageerror',error=>errors.push(error.message));
try{
  if(process.env.OPERATOR_API_KEY){
    const auth=await page.request.post(ui+'/api/v1/auth/session',{data:{key:process.env.OPERATOR_API_KEY}});
    expect(auth.ok()).toBeTruthy();
  }
  await page.goto(ui+'/#copilot');
  await expect(page.getByRole('button',{name:'Ask copilot',exact:true})).toBeVisible({timeout:120000});
  const checks=[
    ['Executive overview','.command-banner'],
    ['Congestion heatmap','.heat-cell'],
    ['Berth planning','.vessel-block'],
    ['Port network map','.leaflet-container'],
    ['Supervisor shift plan','[role="tab"]'],
    ['BOB Operations Copilot','#copilot-question'],
  ];
  for(const [name,selector] of checks){
    await page.getByRole('navigation').getByRole('button',{name,exact:true}).click();
    await expect(page.getByRole('heading',{level:1,name,exact:true})).toBeVisible();
    await expect(page.locator(selector).first()).toBeVisible({timeout:120000});
    views.push(name);
  }
  expect(errors).toEqual([]);
  await fs.writeFile('artifacts/copilot/navigation-browser.json',JSON.stringify({result:'PASS',ui,views,errors},null,2));
  console.log('PASS: six views including BOB Copilot render from the real backend; no operational writes.');
}finally{await browser.close();}
