import {test, expect, Page} from '@playwright/test';
import {mkdirSync, writeFileSync} from 'node:fs';

test.skip(process.env.FOLLOWUP_E2E !== '1', 'Offline follow-up usability audit');

async function send(page: Page, text: string) {
  const response = page.waitForResponse(r =>
    /\/api\/sessions\/[^/]+\/messages$/.test(r.url()) && r.request().method() === 'POST');
  await page.getByLabel('Your message', {exact: true}).fill(text);
  await page.getByRole('button', {name: 'Send', exact: true}).click();
  const result = await (await response).json();
  await expect(page.locator('.message.assistant').last()).toContainText(result.text);
  expect(result.response_kind).not.toBe('service_error');
  return result;
}

test.beforeEach(async ({page, request}) => {
  const health = await (await request.get('/api/health')).json();
  expect(health.provider).toBe('scripted');
  expect(health.corpus_version).toBe('synthetic-2026-10-v3');
  await page.goto('/');
});

test('short answers follow access and final resolution questions', async ({page}) => {
  const trace = [];
  trace.push(await send(page, 'I need to download AutoCAD on Windows for a student'));
  trace.push(await send(page, 'Yes'));
  expect(trace.at(-1).state.outcome).toBe('open');
  expect(trace.at(-1).progress.current).toBe(2);
  await expect(page.locator('.message.assistant').last()).toContainText('Download from');
  await page.reload();
  await expect(page.locator('.message.assistant').last()).toContainText('Download from');
  trace.push(await send(page, 'Download complete'));
  expect(trace.at(-1).progress.current).toBe(3);
  trace.push(await send(page, 'Yes'));
  expect(trace.at(-1).state.outcome).toBe('resolved');
  mkdirSync('../../docs/followup-audit/results', {recursive: true});
  writeFileSync('../../docs/followup-audit/results/short-answers.json', JSON.stringify(trace, null, 2));
});

test('negative access answer can recover after a corrected license route', async ({page}) => {
  const trace = [];
  trace.push(await send(page, 'I need to download AutoCAD on Windows for a student'));
  trace.push(await send(page, 'No'));
  expect(trace.at(-1).rule).toBe('step_blocked');
  expect(trace.at(-1).state.failures).toBe(0);
  await expect(page.getByLabel('Ticket draft', {exact: true})).toContainText('No');
  trace.push(await send(page, 'Actually, I already have access through an existing license'));
  expect(trace.at(-1).sources[0].id).toBe('autodesk-existing');
  expect(trace.at(-1).state.workflow_blocked).toBe(false);
  await page.reload();
  await expect(page.locator('.message.assistant').last()).toContainText(trace.at(-1).steps[0]);
  writeFileSync('../../docs/followup-audit/results/corrected-blocker.json', JSON.stringify(trace, null, 2));
});

test('switching from Wi-Fi to installation starts the appropriate task', async ({page}) => {
  const first = await send(page, 'My home Wi-Fi keeps disconnecting on my laptop');
  const next = await send(page, 'I need to download AutoCAD on Windows for a student');
  expect(next.state.category).toBe('software');
  expect(next.state.problem_id).not.toBe(first.state.problem_id);
  expect(next.state.details.network).toBeNull();
  expect(next.sources[0].id).toBe('autodesk-education');
  writeFileSync('../../docs/followup-audit/results/task-switch.json', JSON.stringify([first, next], null, 2));
});

test('yes to a product question does not invent a product or resolve the task', async ({page}) => {
  const first = await send(page, 'I need to download Autodesk');
  expect(first.question_field).toBe('system_or_app');
  const next = await send(page, 'Yes');
  expect(next.state.details.system_or_app).toBeNull();
  expect(next.state.outcome).toBe('open');
  expect(next.sources[0].id).toBe('autodesk-product');
  writeFileSync('../../docs/followup-audit/results/intake-ambiguity.json', JSON.stringify([first, next], null, 2));
});
