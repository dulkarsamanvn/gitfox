import { expect, test } from '@playwright/test';
import type { Page, Route } from '@playwright/test';
import { previewFixture } from './fixtures/preview';

const endpoint = '**/api/v1/pull-requests/preview';
const prUrl = 'https://github.com/example/project/pull/42';
const cors = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'POST, OPTIONS',
  'access-control-allow-headers': 'Content-Type',
};

async function respond(route: Route, json: unknown = previewFixture(), status = 200) {
  if (route.request().method() === 'OPTIONS') {
    await route.fulfill({ status: 204, headers: cors });
    return;
  }
  await route.fulfill({ status, json, headers: cors });
}

async function submit(page: Page, url = prUrl) {
  await page.getByLabel('GitHub pull request URL', { exact: true }).fill(url);
  await page.getByRole('button', { name: 'Preview PR', exact: true }).click();
}

test.beforeEach(async ({ page }) => {
  for (const path of ['/health', '/ready']) {
    await page.route(`**${path}`, route => route.fulfill({
      json: { status: 'ok', database: 'ok' }, headers: cors,
    }));
  }
});

test('submits only on request and displays metadata, patches, renames, and skip reasons', async ({ page }) => {
  let posts = 0;
  await page.route(endpoint, async route => {
    if (route.request().method() === 'POST') {
      posts++;
      expect(route.request().postDataJSON()).toEqual({ pr_url: prUrl });
    }
    await respond(route);
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'See what changed.' })).toBeVisible();
  expect(posts).toBe(0);
  await submit(page, '  HTTPS://GITHUB.COM/example/project/pull/42/  ');

  const result = page.getByRole('region', { name: 'Guard empty user lists' });
  await expect(result).toBeVisible();
  await expect(result).toContainText('Opened by contributor');
  await expect(result.getByRole('link', { name: 'View on GitHub' })).toHaveAttribute('href', prUrl);
  await expect(result.getByRole('heading', { name: 'Selected files (2)' })).toBeVisible();
  await expect(result.getByRole('heading', { name: 'Skipped files (1)' })).toBeVisible();
  await expect(result).toContainText('Binary file type');
  await result.locator('summary').filter({ hasText: 'src/users.py' }).click();
  await expect(result.getByLabel('Patch for src/users.py')).toContainText('+return users[0] if users else None');
  await result.locator('summary').filter({ hasText: 'frontend/profile.tsx' }).click();
  await expect(result).toContainText('Previous path: frontend/user.tsx');
  await result.locator('summary').filter({ hasText: 'Commit details' }).click();
  await expect(result).toContainText('b'.repeat(40));
  expect(posts).toBe(1);
});

for (const url of ['https://example.com/repo/pull/1', 'http://127.0.0.1/private', 'https://github.com/a/b/pull/01', 'https://github.com/a/b/pull/1?token=fake-secret']) {
  test(`rejects invalid URL without fetching: ${url.split('?')[0]}`, async ({ page }) => {
    let posts = 0;
    await page.route(endpoint, route => { posts++; return respond(route); });
    await page.goto('/');
    await submit(page, url);
    await expect(page.getByRole('alert')).toContainText('Enter an HTTPS GitHub PR URL');
    await expect(page.getByLabel('GitHub pull request URL', { exact: true })).toHaveAttribute('aria-invalid', 'true');
    await expect(page.getByRole('alert')).not.toContainText('fake-secret');
    expect(posts).toBe(0);
  });
}

test('shows an input error for an empty submission', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Preview PR', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Enter an HTTPS GitHub PR URL');
});

test('does not require a ready database for preview', async ({ page }) => {
  await page.route('**/ready', route => route.fulfill({ status: 503, json: { status: 'not_ready', database: 'unavailable' }, headers: cors }));
  await page.route(endpoint, route => respond(route));
  await page.goto('/');
  await submit(page);
  await expect(page.getByRole('heading', { name: 'Guard empty user lists' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'PostgreSQL database' })).toContainText('Unavailable');
});

test('shows loading, prevents duplicate submissions, and can cancel and resubmit', async ({ page }) => {
  let posts = 0;
  let release: (() => void) | undefined;
  await page.route(endpoint, async route => {
    if (route.request().method() === 'POST') {
      posts++;
      if (posts === 1) await new Promise<void>(resolve => { release = resolve; });
    }
    await respond(route).catch(() => {});
  });
  await page.goto('/');
  await submit(page);
  await expect(page.getByRole('button', { name: 'Fetching preview…' })).toBeDisabled();
  await expect(page.getByText('Fetching pull request details and changed files…')).toBeVisible();
  expect(posts).toBe(1);
  await page.getByRole('button', { name: 'Cancel preview' }).click();
  await expect(page.getByRole('button', { name: 'Preview PR', exact: true })).toBeEnabled();
  await expect(page.getByRole('alert')).toHaveCount(0);
  release?.();
  await page.getByRole('button', { name: 'Preview PR', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Guard empty user lists' })).toBeVisible();
  expect(posts).toBe(2);
});

for (const [code, status, message] of [
  ['github_not_found', 404, 'Pull request not found'],
  ['github_private_repository', 422, 'Private repositories are not supported'],
  ['github_rate_limited', 503, 'rate limit has been reached'],
  ['github_timeout', 504, 'GitHub took too long'],
] as const) {
  test(`shows a safe ${code} error and allows retry`, async ({ page }) => {
    let fail = true;
    await page.route(endpoint, route => fail
      ? respond(route, { detail: { code, message: 'fake-private-backend-secret' } }, status)
      : respond(route));
    await page.goto('/');
    await submit(page);
    await expect(page.getByRole('alert')).toContainText(message);
    await expect(page.getByText('fake-private-backend-secret')).toHaveCount(0);
    fail = false;
    await page.getByRole('button', { name: 'Preview PR', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Guard empty user lists' })).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
  });
}

test('handles network failures and unknown server errors without exposing bodies', async ({ page }) => {
  await page.route(endpoint, route => route.abort('connectionrefused'));
  await page.goto('/');
  await submit(page);
  await expect(page.getByRole('alert')).toContainText('Could not reach GitFox');
  await page.route(endpoint, route => respond(route, { detail: 'fake-private-backend-secret' }, 500));
  await page.getByRole('button', { name: 'Preview PR', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('HTTP 500');
  await expect(page.getByText('fake-private-backend-secret')).toHaveCount(0);
});

for (const kind of ['malformed', 'counts', 'wrong-pr', 'unsafe-url', 'duplicate'] as const) {
  test(`rejects an invalid ${kind} success response`, async ({ page }) => {
    await page.route(endpoint, route => {
      if (kind === 'malformed') return route.fulfill({ body: 'fake-private-backend-secret', contentType: 'application/json', headers: cors });
      const data = previewFixture();
      if (kind === 'counts') data.selection.files_seen = 100;
      if (kind === 'wrong-pr') data.metadata.pr_number = 99;
      if (kind === 'unsafe-url') data.metadata.pr_url = 'javascript:alert(1)';
      if (kind === 'duplicate') data.selection.selected[1].filename = data.selection.selected[0].filename;
      return respond(route, data);
    });
    await page.goto('/');
    await submit(page);
    await expect(page.getByRole('alert')).toContainText('unexpected preview');
    await expect(page.getByRole('heading', { name: 'Guard empty user lists' })).toHaveCount(0);
    await expect(page.getByText('fake-private-backend-secret')).toHaveCount(0);
  });
}

test('clears old results when the URL changes and when a later request fails', async ({ page }) => {
  let fail = false;
  await page.route(endpoint, route => fail
    ? respond(route, { detail: { code: 'github_not_found' } }, 404)
    : respond(route));
  await page.goto('/');
  await submit(page);
  await expect(page.getByRole('heading', { name: 'Guard empty user lists' })).toBeVisible();
  await page.getByLabel('GitHub pull request URL', { exact: true }).fill(prUrl.replace('/42', '/43'));
  await expect(page.getByRole('heading', { name: 'Guard empty user lists' })).toHaveCount(0);
  fail = true;
  await page.getByRole('button', { name: 'Preview PR', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Pull request not found');
  await expect(page.getByRole('heading', { name: 'Guard empty user lists' })).toHaveCount(0);
});

test('handles an all-skipped result and an empty PR', async ({ page }) => {
  const data = previewFixture();
  data.selection.selected = [];
  data.selection.skipped = data.selection.skipped.slice(0, 1);
  data.metadata.changed_files = data.selection.files_seen = data.selection.files_skipped = 1;
  data.selection.files_selected = data.selection.patch_chars = 0;
  await page.route(endpoint, route => respond(route, data));
  await page.goto('/');
  await submit(page);
  await expect(page.getByText('No patches were selected. Check the skipped-file reasons below.')).toBeVisible();
  data.selection.skipped = [];
  data.metadata.changed_files = data.selection.files_seen = data.selection.files_skipped = 0;
  await page.getByRole('button', { name: 'Preview PR', exact: true }).click();
  await expect(page.getByText('This pull request has no changed files.')).toBeVisible();
});

test('renders HTML-like repository text safely and counts Unicode characters correctly', async ({ page }) => {
  const data = previewFixture();
  data.metadata.title = '<img src=x onerror="window.previewInjected=true">';
  data.selection.selected[0].patch = '@@ -1 +1 @@\n-old\n+<script>window.previewInjected=true</script> 😀';
  data.selection.patch_chars = data.selection.selected.reduce((total, file) => total + Array.from(file.patch).length, 0);
  await page.route(endpoint, route => respond(route, data));
  await page.goto('/');
  await submit(page);
  await expect(page.getByRole('heading', { name: data.metadata.title })).toBeVisible();
  await page.locator('summary').filter({ hasText: 'src/users.py' }).click();
  await expect(page.getByLabel('Patch for src/users.py')).toContainText('<script>');
  expect(await page.evaluate(() => Object.hasOwn(window, 'previewInjected'))).toBe(false);
});

test('fits mobile, supports keyboard submission, and keeps long paths within the page', async ({ page }) => {
  const data = previewFixture();
  data.selection.selected[0].filename = `src/${'long'.repeat(35)}.py`;
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route(endpoint, route => respond(route, data));
  await page.goto('/');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('GitHub pull request URL', { exact: true })).toBeFocused();
  await page.keyboard.type(prUrl);
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Guard empty user lists' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/pr-preview-mobile.png', fullPage: true });
});

test('times out a long preview and lets the user try again', async ({ page }) => {
  let release: (() => void) | undefined;
  await page.route(endpoint, async route => {
    if (route.request().method() === 'POST') await new Promise<void>(resolve => { release = resolve; });
    await respond(route).catch(() => {});
  });
  await page.clock.install();
  await page.goto('/');
  await submit(page);
  await expect(page.getByRole('button', { name: 'Fetching preview…' })).toBeDisabled();
  await page.clock.fastForward(70_100);
  await expect(page.getByRole('alert')).toContainText('The preview timed out');
  await expect(page.getByRole('button', { name: 'Preview PR', exact: true })).toBeEnabled();
  release?.();
});

test('desktop preview is readable with expanded code', async ({ page }) => {
  await page.route(endpoint, route => respond(route));
  await page.goto('/');
  await submit(page);
  await page.locator('summary').filter({ hasText: 'src/users.py' }).click();
  await expect(page.getByLabel('Patch for src/users.py')).toBeVisible();
  await page.screenshot({ path: 'test-results/pr-preview-desktop.png', fullPage: true });
});
