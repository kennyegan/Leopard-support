import {test,expect,Page} from '@playwright/test';
import {writeFileSync,mkdirSync} from 'node:fs';

test.skip(process.env.DIAGNOSTIC_E2E!=='1','Intent-aware v3 acceptance suite');
test.setTimeout(120000);
async function send(page:Page,text:string) {
 const response=page.waitForResponse(r=>/\/api\/sessions\/[^/]+\/messages$/.test(r.url())&&r.request().method()==='POST');
 await page.getByLabel('Your message',{exact:true}).fill(text);
 await page.getByRole('button',{name:'Send',exact:true}).click();
 const result=await (await response).json();
 await expect(page.locator('.message.assistant').last()).toContainText(result.text);
 expect(result.response_kind).not.toBe('service_error');
 return result;
}
function save(name:string,trace:unknown[]) {
 mkdirSync('../../docs/diagnostic/results',{recursive:true});
 writeFileSync(`../../docs/diagnostic/results/${process.env.LIVE_PROVIDER==='1'?'live':'offline'}-${name}.json`,JSON.stringify(trace,null,2));
}
test.beforeEach(async({page,request})=>{
 const h=await (await request.get('/api/health')).json();
 expect(h.corpus_version).toBe('synthetic-2026-10-v3');
 expect(h.provider).toBe(process.env.LIVE_PROVIDER==='1'?'openrouter':'scripted');
 await page.goto('/');
});

test('Autodesk request through download, installation, launch and refresh',async({page})=>{
 const trace=[];
 try {
  trace.push(await send(page,'i need to download auto desk'));
  expect(trace.at(-1).question_field).toBe('system_or_app');
  await expect(page.locator('.message.assistant').last()).toContainText('Which one');
  trace.push(await send(page,'AutoCAD on Windows for a student'));
  expect(trace.at(-1).sources[0].id).toBe('autodesk-education');
  await expect(page.locator('.message.assistant').last().locator('li').first()).toBeInViewport();
  await expect(page.locator('.message.assistant').last().getByRole('group',{name:'Problem resolution'})).toHaveCount(0);
  await expect(page.locator('.message.assistant').last().getByRole('link',{name:/Autodesk Education/})).toHaveAttribute('href','https://www.autodesk.com/education/edu-software/overview');
  await page.screenshot({path:`../../docs/diagnostic/results/${process.env.LIVE_PROVIDER==='1'?'live':'offline'}-autodesk-start.png`,fullPage:true});
  await expect(page.getByRole('button',{name:'AutoCAD',exact:true})).toBeDisabled();
  trace.push(await send(page,'I can access the download'));
  expect(trace.at(-1).progress.current).toBe(2);
  trace.push(await send(page,'Download complete'));
  expect(trace.at(-1).progress.current).toBe(3);
  await expect(page.locator('.message.assistant').last()).toContainText('installer');
  await page.reload();
  await expect(page.locator('.message.assistant').last()).toContainText('installer');
  trace.push(await send(page,'Installed and opens'));
  expect(trace.at(-1).state.outcome).toBe('resolved');
  expect(trace.at(-1).steps).toEqual([]);
  await page.screenshot({path:`../../docs/diagnostic/results/${process.env.LIVE_PROVIDER==='1'?'live':'offline'}-autodesk-done.png`,fullPage:true});
 } finally {save('autodesk',trace);}
});

test('Wi-Fi observation selects a device check instead of repeating the guide',async({page})=>{
 const trace=[];
 try {
  trace.push(await send(page,'My home Wi-Fi keeps disconnecting on my laptop'));
  expect(trace.at(-1).sources[0].id).toBe('general-wifi');
  expect(trace.at(-1).response_kind).toBe('check');
  trace.push(await send(page,'Only this laptop has the problem. My phone works on the same network.'));
  expect(trace.at(-1).sources[0].id).toBe('general-wifi-alternate');
  expect(trace.at(-1).state.failures).toBe(0);
  expect(trace.at(-1).state.details.affected_scope).toBe('one_device');
  trace.push(await send(page,"It's working now"));
  expect(trace.at(-1).state.outcome).toBe('resolved');
 } finally {save('wifi',trace);}
});

test('exact reported detour and blocked access have useful outcomes',async({page})=>{
 test.skip(process.env.LIVE_PROVIDER==='1','Offline adversarial path; live budget reserved for completion journeys');
 const trace=[];
 trace.push(await send(page,'i need to download auto desk'));
 trace.push(await send(page,'Laptop'));
 trace.push(await send(page,"I'm not sure"));
 for(const r of trace) {
  expect(['error_text','symptom','device']).not.toContain(r.question_field);
  expect(r.sources.some((s:{id:string})=>s.id.startsWith('general-app'))).toBe(false);
 }
 await expect(page.getByRole('link',{name:/Autodesk Education/}).first()).toBeVisible();
 await page.getByRole('button',{name:'New conversation'}).click();
 trace.push(await send(page,'I need to download AutoCAD on Windows for a student'));
 trace.push(await send(page,'Access not approved'));
 expect(trace.at(-1).rule).toBe('step_blocked');
 await expect(page.getByLabel('Ticket draft',{exact:true})).toContainText('Access not approved');
 await page.getByLabel('Ticket draft',{exact:true}).fill('Synthetic AutoCAD education access is blocked. Please confirm the correct route.');
 await page.getByRole('button',{name:'Save draft',exact:true}).click();
 await expect(page.getByText('Draft saved with privacy filtering.')).toBeVisible();
 await page.reload();
 await expect(page.getByLabel('Ticket draft',{exact:true})).toHaveValue('Synthetic AutoCAD education access is blocked. Please confirm the correct route.');
 save('detour-blocker',trace);
});
