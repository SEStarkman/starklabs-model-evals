import { expect, test } from '@playwright/test';

test('real local first-run flow persists comparison and rating history', async ({ page }) => {
  const browserErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });
  page.on('pageerror', (error) => browserErrors.push(error.message));

  await page.goto('/#token=browser-smoke');
  await expect(page).toHaveURL('http://127.0.0.1:5173/');

  await page.getByRole('button', { name: 'Models' }).click();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'Fake OK' })).toBeVisible();

  await page.getByRole('button', { name: 'Import pack' }).click();
  await expect(page.getByText('Starklabs public fixture')).toBeVisible();

  await page.getByRole('button', { name: 'Run', exact: true }).click();
  await page.getByRole('button', { name: 'Wait', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Test 1: strawberry r count' })).toBeVisible();
  await expect(page.getByText(/\[fake:fake-ok:/).first()).toBeVisible();

  await page.getByLabel('Blind review').check();
  await expect(page.getByRole('heading', { name: 'Model 1' }).first()).toBeVisible();
  await page.getByLabel('Notes').first().fill('Persisted browser rating');
  const ratingSaved = page.waitForResponse(
    (response) => response.url().includes('/rating') && response.status() === 201,
  );
  await page.getByRole('button', { name: 'Save', exact: true }).first().click();
  await ratingSaved;

  await page.reload();
  await expect(page.getByRole('heading', { name: 'Test 1: strawberry r count' })).toBeVisible();
  await expect(page.getByLabel('Notes').first()).toHaveValue('Persisted browser rating');
  await page.setViewportSize({ width: 900, height: 700 });
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();
  expect(browserErrors).toEqual([]);
});