import {test, expect, Page} from '@playwright/test';

test.setTimeout(90000);
test.skip(process.env.CONVERSATION_E2E !== '1', 'Separate conversational-mode acceptance suite');
async function send(page: Page, text: string) {
 const response = page.waitForResponse(r => /\/api\/sessions\/[^/]+\/messages$/.test(r.url()) && r.request().method() === 'POST');
 await page.getByLabel('Your message', {exact:true}).fill(text);
 await page.getByRole('button', {name:'Send ↗'}).click();
 const result = await (await response).json();
 await expect(page.locator('.message.assistant').last()).toContainText(result.text);
 return result;
}
test.beforeEach(async ({page,request}) => {
 const health = await (await request.get('/api/health')).json();
 expect(health.dialogue_mode).toBe('conversational');
 expect(health.provider).toBe(process.env.LIVE_PROVIDER === '1' ? 'openrouter' : 'scripted');
 await page.goto('/');
});

test('freeform troubleshooting, explanations, source, resolution and refresh', async ({page}, testInfo) => {
 const trace = [];
 trace.push(await send(page, 'wifi'));
 expect(trace.at(-1).question_field).toBe('symptom');
 trace.push(await send(page, 'What do you mean by that?'));
 expect(trace.at(-1).response_kind).toBe('explanation');
 await expect(page.locator('.message.assistant').last()).not.toContainText('Did this fix it?');
 trace.push(await send(page, 'My home Wi-Fi disconnects every few minutes on my laptop'));
 expect(trace.at(-1).action).toBe('ANSWER');
 const source = page.locator('.message.assistant').last().getByRole('link');
 const href = await source.getAttribute('href');
 expect(href).toContain('/sources/general-wifi');
 const newPage = await page.context().newPage();
 await newPage.goto(href!);
 await expect(newPage.locator('main')).toContainText(/synthetic/i);
 await newPage.close();
 trace.push(await send(page, 'What does the first step mean?'));
 expect(trace.at(-1).response_kind).toBe('explanation');
 expect(trace.at(-1).state.last_answer_id).toBe(trace[2].id);
 trace.push(await send(page, 'Yes, it works now'));
 expect(trace.at(-1).state.outcome).toBe('resolved');
 expect(trace.at(-1).steps).toEqual([]);
 await page.reload();
 await expect(page.locator('.message.assistant').last()).toContainText('marked this issue resolved');
 await expect(page.locator('.message.assistant').last()).not.toContainText('Did this fix it?');
 await page.screenshot({path:`../../docs/conversational/results/${process.env.LIVE_PROVIDER==='1'?'live':'offline'}-conversation.png`,fullPage:true});
 await testInfo.attach('trajectory', {body:JSON.stringify(trace,null,2),contentType:'application/json'});
});

test('failed approaches lead to editable persisted ticket', async ({page},testInfo) => {
 test.skip(process.env.LIVE_PROVIDER === '1', 'Covered in the bounded live API suite');
 const trace = [];
 trace.push(await send(page,'My home Wi-Fi disconnects on my laptop'));
 await page.locator('.message.assistant').last().getByRole('group',{name:'Problem resolution'}).getByRole('button',{name:'No',exact:true}).click();
 await expect(page.locator('.message.assistant')).toHaveCount(2);
 await expect(page.getByLabel('Your message',{exact:true})).toBeEnabled();
 trace.push(await send(page,'It still disconnects after trying those checks'));
 expect(trace.at(-1).rule).toBe('repeated_failure');
 await page.getByLabel('Ticket draft',{exact:true}).fill('Synthetic home Wi-Fi issue, both checks failed. Please help.');
 await page.getByRole('button',{name:'Save draft',exact:true}).click();
 await expect(page.getByText('Draft saved with privacy filtering.')).toBeVisible();
 await page.reload();
 await expect(page.getByLabel('Ticket draft',{exact:true})).toHaveValue('Synthetic home Wi-Fi issue, both checks failed. Please help.');
 await page.screenshot({path:'../../docs/conversational/results/ticket.png',fullPage:true});
 await testInfo.attach('trajectory',{body:JSON.stringify(trace,null,2),contentType:'application/json'});
});
