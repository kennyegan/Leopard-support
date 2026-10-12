/** Actual quick-reply interaction using an already authenticated synthetic browser fixture. */
import {chromium} from '../../apps/web/node_modules/playwright/index.mjs';
import {writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const browser=await chromium.launch({channel:process.env.PILOT_BROWSER_CHANNEL||'chrome',headless:true});
const evidence={mode:'local-qualification',checks:[]};
try {
 const context=await browser.newContext({ignoreHTTPSErrors:true,reducedMotion:'reduce',baseURL:'https://localhost:3443',storageState:fileURLToPath(new URL('../../.runtime/pilot/browser-state.json',import.meta.url))});
 const health=await (await context.request.get('/api/health')).json();
 assert(health.provider==='scripted'||(process.env.PILOT_LIVE_BROWSER==='1'&&health.ai_requests_remaining>=2));
 evidence.health=health;
 const page=await context.newPage();await page.goto('/');
 const me=await (await context.request.get('/api/auth/me')).json();
 await page.evaluate(key=>localStorage.removeItem(key),`techspot.pilot.session.${me.user_id}`);
 await page.reload();
 await page.getByLabel('Your message',{exact:true}).fill('Install AutoCAD on Windows using education access');
 const first=page.waitForResponse(r=>/\/api\/sessions\/[^/]+\/messages$/.test(r.url())&&r.request().method()==='POST');
 await page.getByRole('button',{name:'Send ↗',exact:true}).click();
 const response=await first;assert.equal(response.status(),200);
 const a=await response.json();assert.equal(a.state.active_node,'check-1');
 const second=page.waitForResponse(r=>/\/api\/sessions\/[^/]+\/messages$/.test(r.url())&&r.request().method()==='POST');
 await page.getByRole('button',{name:'I can access the download',exact:true}).click();
 const reply=await second;assert.equal(reply.status(),200);
 const b=await reply.json();assert.equal(b.state.active_node,'check-2');assert.equal(b.state.outcome,'open');
 await page.getByRole('button',{name:'Download complete',exact:true}).waitFor();
 assert(await page.getByRole('button',{name:'I can access the download',exact:true}).isDisabled());
 evidence.turns=[a,b];evidence.passed=true;
 evidence.checks.push('actual quick-reply click advances one source-defined node','prior quick-reply is disabled after new response','intermediate action remains unresolved');
} catch(error){evidence.passed=false;evidence.error=String(error);throw error;}
finally {await writeFile(new URL('../../docs/pilot/results/browser-quick-reply.json',import.meta.url),JSON.stringify(evidence,null,2)+'\n');await browser.close();}
