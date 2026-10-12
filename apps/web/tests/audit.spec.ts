import {test, expect} from '@playwright/test';

const clear = 'My demo-campus Wi-Fi stopped working on macOS and reports a demo credential error.';
async function send(page: import('@playwright/test').Page, text: string) {
 await page.getByLabel('Your message').fill(text);
 await page.getByRole('button', {name: 'Send'}).click();
}

test('new conversation wins over an in-flight restore', async ({page, request}) => {
 const created = await request.post('/api/sessions', {data: {mode: 'policy'}});
 const {id} = await created.json();
 await request.post(`/api/sessions/${id}/messages`, {data: {text: clear}});
 await page.addInitScript(id => localStorage.setItem('techspot.demo.session', id), id);
 let release!: () => void;
 let started!: () => void;
 const held = new Promise<void>(resolve => { release = resolve; });
 const seen = new Promise<void>(resolve => { started = resolve; });
 await page.route(`**/api/sessions/${id}`, async route => {
  const response = await route.fetch(); started(); await held; await route.fulfill({response});
 });
 await page.goto('/'); await seen;
 await expect(page.getByText('Restoring your conversation…')).toBeVisible();
 await page.getByRole('button', {name: 'New conversation'}).click();
 const finished = page.waitForResponse(`**/api/sessions/${id}`);
 release(); await finished;
 await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
 await expect(page.locator('.message')).toHaveCount(0);
 await expect(page.getByRole('heading', {name: 'What’s getting in your way?'})).toBeVisible();
 expect(await page.evaluate(() => localStorage.getItem('techspot.demo.session'))).toBeNull();
});

test('successful send renders without a follow-up history read', async ({page, request}) => {
 await page.goto('/');
 let historyReads = 0;
 await page.route(/\/api\/sessions\/[^/]+$/, route => {
  historyReads++; return route.fulfill({status: 503, body: '{}'});
 });
 await send(page, "Wi-Fi isn't working.");
 await expect(page.getByText('Which operating system are you using?')).toBeVisible();
 await expect(page.getByLabel('Your message')).toHaveValue('');
 expect(historyReads).toBe(0);
 const id = await page.evaluate(() => localStorage.getItem('techspot.demo.session'));
 const history = await (await request.get(`/api/sessions/${id}`)).json();
 expect(history.messages).toHaveLength(2);
 expect(history.state.questions).toHaveLength(1);
});

test('lost POST response retries once without another question or snapshot', async ({page, request}) => {
 await page.goto('/');
 let loseResponse = true;
 await page.route('**/api/sessions/*/messages', async route => {
  const response = await route.fetch();
  if (loseResponse) { loseResponse = false; await route.fulfill({status: 503, body: '{}'}); }
  else await route.fulfill({response});
 });
 await send(page, "Wi-Fi isn't working.");
 await expect(page.locator('.error[role="alert"]')).toContainText('unavailable');
 await page.getByRole('button', {name: 'Send'}).click();
 await expect(page.getByText('Which operating system are you using?')).toBeVisible();
 const id = await page.evaluate(() => localStorage.getItem('techspot.demo.session'));
 const history = await (await request.get(`/api/sessions/${id}`)).json();
 expect(history.messages).toHaveLength(2);
 expect(history.state.questions).toHaveLength(1);
 expect(await (await request.get(`/api/sessions/${id}/snapshots`)).json()).toHaveLength(1);
});

test('saved vote stays selected and cannot silently change after refresh', async ({page}) => {
 await page.goto('/'); await send(page, clear);
 await page.getByRole('button', {name: 'Thumbs up'}).click();
 await expect(page.getByText('Feedback saved. Thank you.')).toBeVisible();
 await page.reload();
 await expect(page.getByRole('button', {name: 'Thumbs up'})).toHaveAttribute('aria-pressed', 'true');
 await expect(page.getByRole('button', {name: 'Thumbs down'})).toBeDisabled();
});

test('failed fix follow-up survives refresh and has a safe retry', async ({page, request}) => {
 await page.goto('/'); await send(page, clear);
 await expect(page.getByText('Guide-backed steps')).toBeVisible();
 await page.route('**/api/sessions/*/messages', route => route.fulfill({status: 503, body: '{}'}));
 await page.locator('.message.assistant').last().getByRole('button', {name: 'No', exact: true}).click();
 await expect(page.getByRole('button', {name: 'Retry next step'})).toBeEnabled();
 await page.unroute('**/api/sessions/*/messages');
 await page.reload();
 await page.getByRole('button', {name: 'Retry next step'}).click();
 await expect(page.getByText('Guide-backed steps')).toHaveCount(2);
 const id = await page.evaluate(() => localStorage.getItem('techspot.demo.session'));
 const history = await (await request.get(`/api/sessions/${id}`)).json();
 expect(history.messages).toHaveLength(4);
 expect(history.state.failures).toBe(1);
 await expect(page.getByRole('button', {name: 'Retry next step'})).toHaveCount(0);
});

test('changing error descriptions still reaches two-failure handoff', async ({page}) => {
 await page.goto('/'); await send(page, clear);
 await expect(page.getByText('Guide-backed steps')).toHaveCount(1);
 await send(page, 'No, that did not fix it. Error: authentication rejected.');
 await expect(page.getByText('Guide-backed steps')).toHaveCount(2);
 await send(page, 'No, that did not fix it. Error: authentication timed out.');
 await expect(page.getByLabel('Ticket draft')).toContainText('Unsuccessful solutions: 2');
 await expect(page.getByLabel('Ticket draft')).toContainText('authentication timed out');
 await page.screenshot({path: '../../docs/mvp/results/cleaned-ticket.png', fullPage: true});
});

test('mobile starts with composer visible and usable feedback targets', async ({page}) => {
 await page.setViewportSize({width: 390, height: 844}); await page.goto('/');
 await expect(page.getByRole('button', {name: "Wi-Fi isn't working."})).toBeEnabled();
 const composer = await page.getByLabel('Your message').boundingBox();
 expect(composer!.y + composer!.height).toBeLessThanOrEqual(844);
 expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 await page.screenshot({path: '../../docs/mvp/results/cleaned-mobile-home.png', fullPage: true});
 await send(page, clear);
 await expect(page.getByText('Guide-backed steps')).toBeVisible();
 for (const button of await page.locator('.feedback button').all()) {
  const bounds = await button.boundingBox();
  expect(bounds!.width).toBeGreaterThanOrEqual(44);
  expect(bounds!.height).toBeGreaterThanOrEqual(44);
 }
 await page.screenshot({path: '../../docs/mvp/results/cleaned-mobile-answer.png', fullPage: true});
});
