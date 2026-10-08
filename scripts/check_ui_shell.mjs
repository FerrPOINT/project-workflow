import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../.smoke/package.json', import.meta.url));
const { chromium } = require('playwright');
const baseUrl = process.env.SMOKE_BASE_URL;
assert.ok(baseUrl, 'SMOKE_BASE_URL must identify the isolated project UI test runtime');
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(baseUrl).hostname), 'UI shell tests are local-only');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${baseUrl}/namespaces`);
  const cards = page.locator('#namespaceNav [data-namespace-id]');
  assert.ok(await cards.count() >= 2, 'Two neutral namespaces are required');
  const ids = await cards.evaluateAll(nodes => nodes.slice(0, 2).map(node => node.dataset.namespaceId));
  const selectedIds = () => page.locator('[data-namespace-selector]').evaluateAll(nodes => nodes.map(node => node.value));
  for (const id of ids) {
    await page.locator(`#namespaceNav [data-namespace-id="${id}"]`).click();
    assert.deepEqual(await selectedIds(), [id, id]);
  }
  await page.goBack();
  assert.deepEqual(await selectedIds(), [ids[0], ids[0]], 'Both selectors restore browser history');
  await page.goForward();
  assert.deepEqual(await selectedIds(), [ids[1], ids[1]]);
  await page.reload();
  assert.deepEqual(await selectedIds(), [ids[1], ids[1]], 'Both selectors restore after reload');
  for (const width of [320, 375, 767, 768, 1920, 2560]) {
    await page.setViewportSize({ width, height: 812 });
    await page.locator('#serviceMenu summary').click();
    const box = await page.locator('.service-menu-popover').boundingBox();
    assert.ok(box && box.x >= 0 && box.x + box.width <= width, `Service menu escapes viewport ${width}`);
    await page.locator('#serviceMenu summary').press('Escape');
    if (width < 768) {
      await page.locator('#burgerBtn').click();
      assert.equal(await page.locator('#mobileNamespaceSelector').inputValue(), ids[1]);
      await page.locator('.sidebar-close').press('Escape');
      assert.equal(await page.locator('#burgerBtn').getAttribute('aria-expanded'), 'false');
    }
  }
  if (process.argv.includes('--owned-fixture')) {
    const initial = await (await page.request.get(`${baseUrl}/api/namespaces`)).json();
    assert.deepEqual(initial.namespaces.map(item => item.cli_command).sort(), ['workflow-dev', 'workflow-qa'], 'Mutation tests require the neutral smoke database');
    const response = await page.request.post(`${baseUrl}/api/namespaces`, { data: {
      name: 'UI shell owned fixture', cli_command: `workflow-shell-${Date.now()}`, workflow_id: initial.namespaces[0].workflow_id,
    } });
    const created = await response.json();
    assert.ok(response.ok() && created.ok);
    const id = String(created.namespace_id);
    await page.goto(`${baseUrl}/namespaces?namespace_id=${id}`);
    assert.deepEqual(await selectedIds(), [id, id]);
    await page.locator('#deleteNamespaceButton').click();
    await page.locator('#confirmDialogAccept').click();
    await page.waitForFunction(deleted => {
      const selectors = [...document.querySelectorAll('[data-namespace-selector]')];
      return selectors.length === 2 && selectors.every(node => node.value !== deleted && ![...node.options].some(option => option.value === deleted));
    }, id);
    const remaining = await (await page.request.get(`${baseUrl}/api/namespaces`)).json();
    assert.deepEqual(remaining.namespaces.map(item => item.id).sort(), initial.namespaces.map(item => item.id).sort());
    console.log('PASS: owned empty-namespace deletion removes both selector options and preserves neighboring fixtures');
  }
  console.log('PASS: namespace selection/history/reload and service menu 320/375/767/768/1920/2560');
} finally {
  await browser.close();
}
