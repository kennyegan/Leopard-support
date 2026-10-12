import {test,expect} from '@playwright/test';

test('ASK → ANSWER, source viewer, feedback and persistence',async({page,context})=>{
 await context.grantPermissions(['clipboard-read','clipboard-write']);
 await page.goto('/');
 await expect(page.getByText('DEMO — synthetic troubleshooting guides; not official TechSpot advice')).toBeVisible();
 await page.getByRole('button',{name:"Wi-Fi isn't working."}).click();
 await expect(page.getByText('Which operating system are you using?')).toBeVisible();
 await page.locator('#message').fill('macOS on demo-campus with a demo credential error');
 await page.getByRole('button',{name:'Send'}).click();
 await expect(page.getByText('Guide-backed steps')).toBeVisible();
 const source=page.locator('a.source').first();
 const href=await source.getAttribute('href');
 const sourcePage=await context.newPage();await sourcePage.goto(href!);
 await expect(sourcePage.getByText('This fictional guide is for local demonstration only.')).toBeVisible();
 await sourcePage.close();
 await page.getByRole('button',{name:'Thumbs up'}).click();
 await expect(page.getByText('Feedback saved. Thank you.')).toBeVisible();
 await page.reload();
 await expect(page.getByText('Guide-backed steps')).toBeVisible();
 await expect(page.locator('.message.user')).toHaveCount(2);
 await page.screenshot({path:'../../docs/mvp/results/chat-desktop.png',fullPage:true});
});

test('human handoff, privacy-filtered draft save and copy',async({page,context})=>{
 await context.grantPermissions(['clipboard-read','clipboard-write']);
 await page.goto('/');
 await page.getByRole('button',{name:'I want to talk to TechSpot staff.'}).click();
 await expect(page.getByRole('heading',{name:'Your editable ticket draft'})).toBeVisible();
 await page.getByLabel('Ticket draft').fill('Please review my demo issue. jane@example.com password=secret123');
 await page.getByRole('button',{name:'Save draft',exact:true}).click();
 await expect(page.getByLabel('Ticket draft')).toHaveValue('Please review my demo issue. [EMAIL] password [REDACTED]');
 await page.getByRole('button',{name:'Copy draft'}).click();
 await expect(page.getByText('Draft copied. Nothing was submitted.')).toBeVisible();
 expect(await page.evaluate(()=>navigator.clipboard.readText())).toContain('[EMAIL]');
 await page.reload();await expect(page.getByLabel('Ticket draft')).toContainText('[EMAIL]');
});

test('No twice produces handoff without repeating a guide',async({page})=>{
 await page.goto('/');
 await page.getByLabel('Your message').fill('My demo-campus Wi-Fi stopped working on macOS and reports a demo credential error.');
 await page.getByRole('button',{name:'Send'}).click();
 await expect(page.getByText('Guide-backed steps')).toHaveCount(1);
 await page.locator('.message.assistant').last().getByRole('button',{name:'No',exact:true}).click();
 await expect(page.getByText('Guide-backed steps')).toHaveCount(2);
 await page.locator('.message.assistant').last().getByRole('button',{name:'No',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your editable ticket draft'})).toBeVisible();
 await expect(page.getByLabel('Ticket draft')).toContainText('Unsuccessful solutions: 2');
});

test('baseline, mobile layout and service error state',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/');
 await page.getByLabel('Research mode').selectOption('baseline');
 await page.getByRole('button',{name:"Wi-Fi isn't working."}).click();
 await expect(page.getByText('Guide-backed steps')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.screenshot({path:'../../docs/mvp/results/chat-mobile.png',fullPage:true});
 await page.route('**/api/sessions/*/messages',route=>route.fulfill({status:503,body:'{}'}));
 await page.getByLabel('Your message').fill('Try again');await page.getByRole('button',{name:'Send'}).click();
 await expect(page.locator('.error[role="alert"]')).toContainText('unavailable');
});

test('quick reply, question usefulness and successful fix',async({page,request})=>{
 await page.goto('/');
 await page.getByLabel('Your message').fill('Demo-campus Wi-Fi has a demo credential error.');
 await page.getByRole('button',{name:'Send'}).click();
 await expect(page.getByText('Which operating system are you using?')).toBeVisible();
 await page.locator('.message.assistant').last().getByRole('button',{name:'Yes',exact:true}).click();
 await expect(page.getByText('Feedback saved. Thank you.')).toBeVisible();
 await page.getByRole('button',{name:'Windows',exact:true}).click();
 await expect(page.getByText('Guide-backed steps')).toBeVisible();
 await page.locator('.message.assistant').last().getByRole('button',{name:'Yes',exact:true}).click();
 await expect(page.getByText('Glad that worked. This issue is marked resolved.')).toBeVisible();
 const id=await page.evaluate(()=>localStorage.getItem('techspot.demo.session'));
 const response=await request.get(`/api/sessions/${id}`);
 expect((await response.json()).state.outcome).toBe('resolved');
});
