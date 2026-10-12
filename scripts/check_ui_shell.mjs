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
  const logoBefore = await page.locator('.brand-mark').evaluate(node => ({ markup: node.innerHTML, color: getComputedStyle(node).color }));
  for (const id of ids) {
    await page.locator(`#namespaceNav [data-namespace-id="${id}"]`).click();
    assert.deepEqual(await selectedIds(), [id, id]);
    const identity = await page.locator('.namespace-trigger').evaluateAll(nodes => nodes.map(node => ({ name: node.querySelector('.namespace-selector-name').textContent, color: node.style.getPropertyValue('--namespace-color'), icon: node.querySelector('path').getAttribute('d') })));
    assert.deepEqual(identity[0], identity[1], 'Desktop and mobile profession identity must agree');
    assert.deepEqual(await page.locator('.brand-mark').evaluate(node => ({ markup: node.innerHTML, color: getComputedStyle(node).color })), logoBefore, 'Profession selection must preserve the Base application logo');
  }
  await page.goBack();
  assert.deepEqual(await selectedIds(), [ids[0], ids[0]], 'Both selectors restore browser history');
  await page.goForward();
  assert.deepEqual(await selectedIds(), [ids[1], ids[1]]);
  await page.reload();
  assert.deepEqual(await selectedIds(), [ids[1], ids[1]], 'Both selectors restore after reload');
  const trigger = page.locator('.platform-header .namespace-trigger');
  await trigger.click();
  assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
  const options = page.locator('#namespaceSelectorOptions [role="option"]');
  assert.equal(await options.count(), await cards.count());
  assert.equal(await page.locator('#namespaceSelectorOptions .namespace-selector-mark svg').count(), await cards.count());
  await trigger.press('ArrowDown');
  await page.locator('#namespaceSelectorOptions [aria-selected="true"]').press('Home');
  assert.equal(await options.first().evaluate(node => node === document.activeElement), true);
  await options.first().press('Escape');
  await page.waitForFunction(() => document.querySelector('.platform-header .namespace-trigger').getAttribute('aria-expanded') === 'false');
  assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
  await trigger.click();
  await page.locator(`#namespaceSelectorOptions [data-value="${ids[0]}"]`).click();
  await page.waitForURL(`**/namespaces?namespace_id=${ids[0]}`);
  assert.deepEqual(await selectedIds(), [ids[0], ids[0]], 'Dropdown selection changes profession');
  await page.locator(`#namespaceNav [data-namespace-id="${ids[1]}"]`).click();
  for (const width of [320, 375, 767, 768, 1000, 1279, 1280, 1920, 2560]) {
    await page.setViewportSize({ width, height: 812 });
    const shell = await page.evaluate(() => {
      const sidebar = document.querySelector('#sidebar').getBoundingClientRect();
      const main = document.querySelector('.main').getBoundingClientRect();
      const label = document.querySelector('.sidebar-label').getBoundingClientRect();
      const context = document.querySelector('.platform-header .namespace-trigger').getBoundingClientRect();
      const account = document.querySelector('.base-ssr-account').getBoundingClientRect();
      return { sidebarWidth: sidebar.width, mainLeft: main.left, labelWidth: label.width, contextRight: context.right, accountLeft: account.left };
    });
    if (width >= 768) {
      const expectedWidth = width < 1280 ? 72 : 264;
      assert.equal(shell.sidebarWidth, expectedWidth, `Sidebar width at ${width}`);
      assert.equal(shell.mainLeft, expectedWidth, `Content offset at ${width}`);
      assert.equal(shell.labelWidth > 1, width >= 1280, `Sidebar labels at ${width}`);
      assert.ok(shell.contextRight <= shell.accountLeft && shell.accountLeft - shell.contextRight < 24, `Namespace context must sit beside account at ${width}`);
    }
    await page.locator('#serviceMenu summary').click();
    const box = await page.locator('.service-menu-popover').boundingBox();
    assert.ok(box && box.x >= 0 && box.x + box.width <= width, `Service menu escapes viewport ${width}`);
    await page.locator('#serviceMenu summary').press('Escape');
    if (width < 768) {
      await page.locator('#burgerBtn').click();
      assert.equal(await page.locator('#mobileNamespaceSelector').inputValue(), ids[1]);
      const mobileTrigger = page.locator('.sidebar-utilities .namespace-trigger');
      await mobileTrigger.click();
      const professionList = await page.locator('#mobileNamespaceSelectorOptions').boundingBox();
      assert.ok(professionList && professionList.x >= 0 && professionList.x + professionList.width <= width, `Profession list escapes viewport ${width}`);
      await mobileTrigger.press('Escape');
      assert.equal(await page.locator('#sidebar').getAttribute('aria-hidden'), 'false', 'First Escape closes the selector and keeps navigation open');
      const targets = await page.locator('#sidebar .sidebar-link').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().height));
      assert.ok(targets.every(height => height >= 44), `Mobile navigation targets at ${width}`);
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
  console.log('PASS: namespace context beside account; sidebar72/264 with matching labels/content offset; menu320/375/767/768/1000/1279/1280/1920/2560');
} finally {
  await browser.close();
}
