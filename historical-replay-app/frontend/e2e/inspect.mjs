import {chromium} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
await fs.mkdir('docs/screenshots',{recursive:true});await fs.mkdir('artifacts/dashboard',{recursive:true});
const browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:5173');await page.locator('.command-banner').waitFor({timeout:120000});await page.evaluate(()=>document.fonts.ready);
const views=[['Executive overview','overview'],['Congestion heatmap','heatmap'],['Berth planning','timeline'],['Port network map','map'],['Supervisor shift plan','shifts'],['Scenario simulator','scenario']];const checks=[];
for(const [name,id] of views){await page.getByRole('navigation').getByRole('button',{name,exact:true}).click();await page.getByRole('heading',{level:1,name,exact:true}).waitFor();if(id==='map')await page.locator('.leaflet-container').waitFor();await page.waitForTimeout(500);await page.screenshot({path:`docs/screenshots/${id}.png`,fullPage:true});const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();checks.push({view:id,violations:result.violations.map(v=>({id:v.id,impact:v.impact,description:v.description,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary})).slice(0,12)}))});}
await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Toggle navigation'}).click();await page.getByRole('navigation').getByRole('button',{name:'Executive overview',exact:true}).click();await page.waitForTimeout(300);await page.screenshot({path:'docs/screenshots/mobile.png',fullPage:true});
checks.push({view:'mobile',horizontalOverflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
await fs.writeFile('artifacts/dashboard/inspection.json',JSON.stringify({errors,checks},null,2));console.log(JSON.stringify({errors,checks},null,2));await browser.close();
