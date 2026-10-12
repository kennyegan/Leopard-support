/** Local container qualification with a clearly labeled synthetic OIDC issuer. */
import {chromium} from '../../apps/web/node_modules/playwright/index.mjs';
import {writeFile, mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const output=new URL('../../docs/pilot/results/',import.meta.url);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({channel:process.env.PILOT_BROWSER_CHANNEL || 'chrome',headless:true,args:['--host-resolver-rules=MAP issuer 127.0.0.1','--no-proxy-server']});
const evidence={mode:'local-qualification',provider:'scripted',checks:[],trajectories:[]};
async function signIn(identity){
 const context=await browser.newContext({ignoreHTTPSErrors:true,reducedMotion:'reduce',baseURL:'https://localhost:3443'});
 const page=await context.newPage();
 await page.goto('/');
 await page.getByRole('link',{name:/sign in/i}).click();
 try {await page.getByRole('heading',{name:'Local test identity provider'}).waitFor({timeout:10000});} catch(error){console.error('Issuer start page:',await page.locator('body').innerText());throw error;}
 await page.getByLabel('Test identity').selectOption(identity);
 await page.getByRole('button',{name:'Continue with test identity'}).click();
 try {await page.waitForURL('https://localhost:3443/');} catch(error) {console.error('Sign-in page:',await page.locator('body').innerText());throw error;}
 await page.getByText('Local qualification').waitFor();
 const me=await (await context.request.get('/api/auth/me')).json();
 return {context,page,csrf:me.csrf_token};
}
async function post(who,path,data){return who.context.request.post(path,{data,headers:{Origin:'https://localhost:3443','X-CSRF-Token':who.csrf}});}
try{
 const anon=await browser.newContext({ignoreHTTPSErrors:true,reducedMotion:'reduce',baseURL:'https://localhost:3443'});
 assert.equal((await anon.request.post('/api/sessions',{data:{}})).status(),401);
 evidence.checks.push('anonymous API closed');
 const alice=await signIn('alice');
 const health=await (await alice.context.request.get('/api/health')).json();
 evidence.provider=health.provider;
 evidence.health=health;
 assert(health.provider==='scripted'||process.env.PILOT_LIVE_BROWSER==='1','Explicit live browser flag required');
 evidence.checks.push('real HTTPS browser OIDC code/PKCE sign-in using local issuer');
 const cookies=await alice.context.cookies();
 const login=cookies.find(c=>c.name==='__Host-techspot');
 assert(login?.secure&&login?.httpOnly&&login?.sameSite==='Lax');
 evidence.checks.push('secure HttpOnly SameSite cookie');
 await alice.page.screenshot({path:fileURLToPath(new URL('pilot-signed-in.png',output)),fullPage:true});
 const me=await (await alice.context.request.get('/api/auth/me')).json();
 const storageKey=`techspot.pilot.session.${me.user_id}`;
 await alice.page.getByLabel('Your message',{exact:true}).waitFor();
 let sid;
 const steps=[];
 for(const text of ['I need to download Autodesk','AutoCAD on Windows for a student','yes','Download complete','Installed and opens']){
  await alice.page.getByLabel('Your message',{exact:true}).fill(text);
  const response=alice.page.waitForResponse(r=>/\/api\/sessions\/[^/]+\/messages$/.test(r.url())&&r.request().method()==='POST');
  await alice.page.getByRole('button',{name:'Send ↗',exact:true}).click();
  const r=await response;
  assert.equal(r.status(),200,await r.text());steps.push(await r.json());
  sid=await alice.page.evaluate(key=>localStorage.getItem(key),storageKey);
  assert(sid);
  await alice.page.getByLabel('Your message',{exact:true}).waitFor({state:'visible'});
  if(steps.length===1){
   const rating=alice.page.waitForResponse(r=>r.url().endsWith('/api/feedback')&&r.request().method()==='POST');
   await alice.page.getByRole('button',{name:'Yes',exact:true}).last().click();
   assert.equal((await rating).status(),200);
  }
 }
 assert.equal(steps.at(-1).state.outcome,'resolved');
 assert.equal(steps[0].question_field,'system_or_app');
 assert.equal(steps[2].state.outcome,'open');
 evidence.trajectories.push({name:'installation',session_id:sid,turns:steps});
 evidence.checks.push('actual composer typing and question feedback through browser');
 await alice.page.getByRole('button',{name:'Thumbs up',exact:true}).last().click();
 const bob=await signIn('bob');
 await bob.context.storageState({path:fileURLToPath(new URL('../../.runtime/pilot/browser-state.json',import.meta.url))});
 assert.equal((await bob.context.request.get(`/api/sessions/${sid}`)).status(),404);
 assert.equal((await bob.context.request.get(`/api/sessions/${sid}/snapshots`)).status(),404);
 evidence.checks.push('cross-user history and snapshots denied through ingress');
 assert.equal((await alice.context.request.post('/api/sessions',{data:{}})).status(),403);
 evidence.checks.push('CSRF required');
 assert.equal((await post(alice,'/api/sessions',{mode:'baseline'})).status(),403);
 evidence.checks.push('baseline rejected');
 const popup=await alice.context.newPage();
 await popup.goto(steps[1].sources[0].href);
 assert.match(await popup.locator('body').innerText(),/synthetic-2026-10-v4/);
 evidence.checks.push('authenticated source rendering pins version');
 // Restore the API-created trajectory in the actual chat UI, then reload.
 await alice.page.evaluate(({key,value})=>localStorage.setItem(key,value),{key:`techspot.pilot.session.${me.user_id}`,value:sid});
 await alice.page.reload();
 await alice.page.getByText("Glad that worked.",{exact:false}).waitFor();
 await alice.page.screenshot({path:fileURLToPath(new URL('pilot-resolved.png',output)),fullPage:true});
 evidence.checks.push('browser refresh restores owned conversation');
 await alice.context.grantPermissions(['clipboard-read','clipboard-write']);
 await alice.page.getByLabel('Your message',{exact:true}).fill('I would like to speak to a person');
 await alice.page.getByRole('button',{name:'Send ↗',exact:true}).click();
 await alice.page.getByLabel('Ticket draft',{exact:true}).waitFor();
 const edited='Synthetic qualification ticket: please review the completed installation.';
 await alice.page.getByLabel('Ticket draft',{exact:true}).fill(edited);
 const save=alice.page.waitForResponse(r=>r.url().endsWith(`/api/sessions/${sid}/ticket`)&&r.request().method()==='PUT');
 await alice.page.getByRole('button',{name:'Save draft',exact:true}).click();
 assert.equal((await save).status(),200);
 await alice.page.getByRole('button',{name:'Copy draft',exact:true}).click();
 await alice.page.getByText('Draft copied. Nothing was submitted.',{exact:true}).waitFor();
 assert.equal(await alice.page.evaluate(()=>navigator.clipboard.readText()),edited);
 await alice.page.reload();
 assert.equal(await alice.page.getByLabel('Ticket draft',{exact:true}).inputValue(),edited);
 const history=await (await alice.context.request.get(`/api/sessions/${sid}`)).json();
 assert(history.feedback.some(f=>f.kind==='question'&&f.value==='yes'));
 assert(history.feedback.some(f=>f.kind==='rating'&&f.value==='yes'));
 evidence.checks.push('question/answer feedback persists; ticket edit/save/copy and refresh work');
 await alice.page.setViewportSize({width:390,height:844});
 assert(await alice.page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 await alice.page.screenshot({path:fileURLToPath(new URL('pilot-mobile-ticket.png',output)),fullPage:true});
 evidence.checks.push('390px mobile layout has no horizontal overflow');
 const deleted=await alice.context.request.delete(`/api/sessions/${sid}`,{headers:{Origin:'https://localhost:3443','X-CSRF-Token':alice.csrf}});
 assert.equal(deleted.status(),200,await deleted.text());
 assert.equal((await alice.context.request.get(`/api/sessions/${sid}`)).status(),404);
 evidence.checks.push('owned deletion through restricted runtime role');
 await post(alice,'/api/auth/logout',{});
 assert.equal((await alice.context.request.get('/api/auth/me')).status(),401);
 evidence.checks.push('logout revokes login');
 evidence.passed=true;
} catch(error){evidence.passed=false;evidence.error=String(error);throw error;}
finally{await writeFile(new URL('container-browser.json',output),JSON.stringify(evidence,null,2)+'\n');await browser.close();}
