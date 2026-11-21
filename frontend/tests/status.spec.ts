import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

async function healthyApi(page: Page) {
  await page.route('**/health', route => route.fulfill({
    json: { status: 'ok' }, headers: { 'access-control-allow-origin': '*' },
  }));
}

async function healthyDatabase(page: Page) {
  await page.route('**/ready', route => route.fulfill({
    json: { status: 'ok', database: 'ok' }, headers: { 'access-control-allow-origin': '*' },
  }));
}

test('shows both successful checks', async ({ page }) => {
  await healthyApi(page);
  await healthyDatabase(page);
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Your setup is ready.' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'API server' })).toContainText('Running');
  await expect(page.getByRole('region', { name: 'PostgreSQL database' })).toContainText('Connected');
  await expect(page.getByText('2 of 2 services ready')).toBeVisible();
});

test('keeps the API healthy when the database is unavailable and can retry', async ({ page }) => {
  await healthyApi(page);
  let available = false;
  await page.route('**/ready', route => route.fulfill({
    status: available ? 200 : 503,
    json: available ? { status: 'ok', database: 'ok' } : { status: 'not_ready', database: 'unavailable' },
    headers: { 'access-control-allow-origin': '*' },
  }));
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'One service needs attention.' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'API server' })).toContainText('Running');
  await expect(page.getByRole('region', { name: 'PostgreSQL database' })).toContainText('Unavailable');

  available = true;
  await page.getByRole('button', { name: 'Check again' }).click();
  await expect(page.getByRole('heading', { name: 'Your setup is ready.' })).toBeVisible();
});

test('shows a useful message when the API cannot be reached', async ({ page }) => {
  await page.route('**/health', route => route.abort('connectionrefused'));
  await page.route('**/ready', route => route.abort('connectionrefused'));
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Your services need attention.' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'API server' })).toContainText('Make sure FastAPI is running');
  await expect(page.getByText('0 of 2 services ready')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Check again' })).toBeEnabled();
});

test('rejects a success status with an invalid response body', async ({ page }) => {
  await healthyApi(page);
  await page.route('**/ready', route => route.fulfill({
    json: { status: 'ok' }, headers: { 'access-control-allow-origin': '*' },
  }));
  await page.goto('/');

  await expect(page.getByRole('region', { name: 'PostgreSQL database' })).toContainText('unexpected response');
  await expect(page.getByText('1 of 2 services ready')).toBeVisible();
});

test('replaces a cached healthy result when a later check fails', async ({ page }) => {
  await healthyApi(page);
  let available = true;
  await page.route('**/ready', route => route.fulfill({
    status: available ? 200 : 503,
    json: available ? { status: 'ok', database: 'ok' } : { status: 'not_ready', database: 'unavailable' },
    headers: { 'access-control-allow-origin': '*' },
  }));
  await page.goto('/');
  await expect(page.getByText('2 of 2 services ready')).toBeVisible();

  available = false;
  await page.getByRole('button', { name: 'Check again' }).click();

  await expect(page.getByRole('region', { name: 'PostgreSQL database' })).toContainText('Unavailable');
  await expect(page.getByText('1 of 2 services ready')).toBeVisible();
});

test('rejects malformed JSON without displaying raw response text', async ({ page }) => {
  await healthyApi(page);
  await page.route('**/ready', route => route.fulfill({
    body: 'private backend error text',
    contentType: 'application/json',
    headers: { 'access-control-allow-origin': '*' },
  }));
  await page.goto('/');

  await expect(page.getByRole('region', { name: 'PostgreSQL database' })).toContainText('unexpected response');
  await expect(page.getByText('private backend error text')).toHaveCount(0);
});

test('reports a failed check while the browser is offline instead of pausing forever', async ({ page, context }) => {
  let available = true;
  for (const endpoint of ['/health', '/ready']) {
    await page.route(`**${endpoint}`, route => available
      ? route.fulfill({
        json: { status: 'ok', database: 'ok' },
        headers: { 'access-control-allow-origin': '*' },
      })
      : route.abort('internetdisconnected'));
  }
  await page.goto('/');
  await expect(page.getByText('2 of 2 services ready')).toBeVisible();

  available = false;
  await context.setOffline(true);
  await page.getByRole('button', { name: 'Check again' }).click();

  await expect(page.getByText('0 of 2 services ready')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Check again' })).toBeEnabled();
});

test('finishes a slow check with a timeout instead of hanging', async ({ page }) => {
  await healthyApi(page);
  await page.route('**/ready', async route => {
    await new Promise(resolve => setTimeout(resolve, 10_000));
    await route.fulfill({ json: { status: 'ok', database: 'ok' } }).catch(() => {});
  });
  await page.goto('/');

  await expect(page.getByRole('region', { name: 'PostgreSQL database' })).toContainText('timed out', { timeout: 12_000 });
  await expect(page.getByRole('button', { name: 'Check again' })).toBeEnabled();
});

test('fits a mobile viewport and supports keyboard refresh', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await healthyApi(page);
  await healthyDatabase(page);
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Your setup is ready.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Check again' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Your setup is ready.' })).toBeVisible();
});

test('connects to the running FastAPI backend', async ({ page }) => {
  test.skip(process.env.RUN_LIVE_STATUS_CHECKS !== '1', 'Enable explicitly with a running FastAPI and PostgreSQL.');
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Your setup is ready.' })).toBeVisible();
  await expect(page.getByText('2 of 2 services ready')).toBeVisible();
});
