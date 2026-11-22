import { expect, test } from '@playwright/test';
import type { Route } from '@playwright/test';
import type { LlmConfiguration } from '../src/api/llm';

const base = '**/api/v1/llm/';
const key = 'fake-ui-provider-secret';
const cors = { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'Content-Type' };
function configuration(): LlmConfiguration {
  return { active_provider: 'openai', providers: [
    { id: 'openai', label: 'OpenAI', model: 'openai-test', key_configured: true },
    { id: 'anthropic', label: 'Anthropic Claude', model: '', key_configured: false },
    { id: 'gemini', label: 'Google Gemini', model: 'gemini-test', key_configured: false },
  ] };
}
async function respond(route: Route, data: unknown, status = 200) {
  if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
  return route.fulfill({ status, json: data, headers: cors });
}

test.beforeEach(async ({ page }) => {
  for (const path of ['/health', '/ready']) await page.route(`**${path}`, route => route.fulfill({ json: { status: 'ok', database: 'ok' }, headers: cors }));
});

test('loads only when opened and saves provider/model while clearing the entered key', async ({ page }) => {
  let state = configuration();
  let reads = 0;
  await page.route(base + 'configuration', async route => {
    if (route.request().method() === 'POST') {
      const draft = route.request().postDataJSON();
      expect(draft).toEqual({ provider: 'anthropic', model: 'claude-test', api_key: key });
      state = { ...state, active_provider: 'anthropic', providers: state.providers.map(profile => profile.id === 'anthropic' ? { ...profile, model: draft.model, key_configured: true } : profile) };
    } else if (route.request().method() === 'GET') reads++;
    await respond(route, state);
  });
  await page.goto('/');
  expect(reads).toBe(0);
  await page.getByText('LLM configuration', { exact: true }).click();
  await expect(page.getByLabel('LLM provider')).toHaveValue('openai');
  await expect(page.getByLabel('Model ID')).toHaveValue('openai-test');
  await page.getByLabel('LLM provider').selectOption('anthropic');
  await page.getByLabel('Model ID').fill('claude-test');
  await page.getByLabel('API key', { exact: true }).fill(key);
  await expect(page.getByLabel('API key', { exact: true })).toHaveAttribute('type', 'password');
  await page.getByRole('button', { name: 'Save configuration' }).click();
  await expect(page.getByText('Configuration saved. Your API key is hidden.')).toBeVisible();
  await expect(page.getByLabel('API key', { exact: true })).toHaveValue('');
  await expect(page.getByText('Active selection:')).toContainText('Anthropic Claude');
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain(key);
  await page.reload();
  await page.getByText('LLM configuration', { exact: true }).click();
  await expect(page.getByLabel('LLM provider')).toHaveValue('anthropic');
  await expect(page.getByLabel('Model ID')).toHaveValue('claude-test');
  await expect(page.getByLabel('API key', { exact: true })).toHaveValue('');
});

test('clears replacement keys even when the public configuration is unchanged', async ({ page }) => {
  const state = configuration();
  await page.route(base + 'configuration', route => respond(route, state));
  await page.goto('/');
  await page.getByText('LLM configuration', { exact: true }).click();
  await expect(page.getByLabel('Model ID')).toHaveValue('openai-test');
  await page.getByLabel('API key', { exact: true }).fill(key);
  await page.getByRole('button', { name: 'Save configuration' }).click();
  await expect(page.getByText('Configuration saved. Your API key is hidden.')).toBeVisible();
  await expect(page.getByLabel('API key', { exact: true })).toHaveValue('');
});

test('tests a draft with a new key, shows exactly what was verified, and clears stale success', async ({ page }) => {
  let saves = 0;
  await page.route(base + 'configuration', route => { if (route.request().method() === 'POST') saves++; return respond(route, configuration()); });
  await page.route(base + 'test-connection', async route => {
    if (route.request().method() === 'POST') expect(route.request().postDataJSON()).toEqual({ provider: 'gemini', model: 'gemini-test', api_key: key });
    await respond(route, { status: 'ok', provider: 'gemini', model: 'gemini-test', resolved_model: 'gemini-test', latency_ms: 125 });
  });
  await page.goto('/');
  await page.getByText('LLM configuration', { exact: true }).click();
  await page.getByLabel('LLM provider').selectOption('gemini');
  await page.getByLabel('API key', { exact: true }).fill(key);
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.getByText('Connection verified', { exact: true })).toBeVisible();
  await expect(page.getByText('Credentials accepted and model accessible. Text generation was not tested.')).toBeVisible();
  expect(saves).toBe(0);
  await page.getByLabel('Model ID').fill('another-model');
  await expect(page.getByText('Connection verified', { exact: true })).toHaveCount(0);
});

test('uses existing server credentials without sending a fake masked key', async ({ page }) => {
  await page.route(base + 'configuration', route => respond(route, configuration()));
  await page.route(base + 'test-connection', async route => {
    if (route.request().method() === 'POST') expect(route.request().postDataJSON()).toEqual({ provider: 'openai', model: 'openai-test' });
    await respond(route, { status: 'ok', provider: 'openai', model: 'openai-test', resolved_model: 'openai-test', latency_ms: 10 });
  });
  await page.goto('/');
  await page.getByText('LLM configuration', { exact: true }).click();
  await expect(page.getByLabel('Model ID')).toHaveValue('openai-test');
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.getByText('Connection verified', { exact: true })).toBeVisible();
});

test('validates missing model/key before testing and hides remote error messages', async ({ page }) => {
  let posts = 0;
  await page.route(base + 'configuration', route => respond(route, configuration()));
  await page.route(base + 'test-connection', route => { posts++; return respond(route, { detail: { code: 'llm_auth_failed', message: key } }, 401); });
  await page.goto('/');
  await page.getByText('LLM configuration', { exact: true }).click();
  await page.getByLabel('LLM provider').selectOption('anthropic');
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('Enter a model ID.');
  await page.getByLabel('Model ID').fill('claude-test');
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('Enter an API key for this provider.');
  expect(posts).toBe(0);
  await page.getByLabel('API key', { exact: true }).fill(key);
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('The provider rejected this API key');
  await expect(page.getByRole('alert')).not.toContainText(key);
});

test('rejects secret-bearing public configuration and can retry loading', async ({ page }) => {
  let bad = true;
  await page.route(base + 'configuration', route => respond(route, bad ? { ...configuration(), api_key: key } : configuration()));
  await page.goto('/');
  await page.getByText('LLM configuration', { exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('invalid LLM settings');
  await expect(page.getByRole('alert')).not.toContainText(key);
  bad = false;
  await page.getByRole('button', { name: 'Retry settings' }).click();
  await expect(page.getByLabel('Model ID')).toHaveValue('openai-test');
});

test('disables editing during a test and closes without showing a stale result', async ({ page }) => {
  let release: (() => void) | undefined;
  await page.route(base + 'configuration', route => respond(route, configuration()));
  await page.route(base + 'test-connection', async route => {
    await new Promise<void>(resolve => { release = resolve; });
    await respond(route, { status: 'ok', provider: 'openai', model: 'openai-test', resolved_model: 'openai-test', latency_ms: 10 }).catch(() => {});
  });
  await page.goto('/');
  await page.getByText('LLM configuration', { exact: true }).click();
  await expect(page.getByLabel('Model ID')).toHaveValue('openai-test');
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Testing connection…' })).toBeDisabled();
  await expect(page.getByLabel('LLM provider')).toBeDisabled();
  await page.getByText('LLM configuration', { exact: true }).click();
  release?.();
  await page.getByText('LLM configuration', { exact: true }).click();
  await expect(page.getByLabel('Model ID')).toHaveValue('openai-test');
  await expect(page.getByText('Connection verified', { exact: true })).toHaveCount(0);
});

test('provider settings fit on mobile with keyboard-accessible controls', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route(base + 'configuration', route => respond(route, configuration()));
  await page.goto('/');
  await page.locator('details.llm-settings > summary').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Model ID')).toHaveValue('openai-test');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/llm-settings-mobile.png', fullPage: true });
});
