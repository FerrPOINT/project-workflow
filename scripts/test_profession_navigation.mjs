import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../project_workflow/interfaces/ui/templates/profession-navigation.js', import.meta.url), 'utf8');
const registry = '11111111-1111-4111-8111-111111111111';
const namespace = '22222222-2222-4222-8222-222222222222';
function page(search) {
  const window = { location: new URL('http://workflow.test/namespaces' + search) };
  window.SdlcPlatformNavigation = { syncRoute: url => { window.location = new URL(url); } };
  const links = [
    { href: 'http://workflow.test/workflows?profession_id=7#details', service: false },
    { href: 'http://wiki.test/?namespace_id=stale', service: true },
    { href: 'http://other.test/?namespace_id=external', service: false },
  ].map(link => ({ ...link, hasAttribute: () => false, classList: { contains: () => link.service } }));
  vm.runInNewContext(source, { window, document: { querySelectorAll: () => links }, URL, URLSearchParams });
  window.WorkflowNavigation.preserveProjectContext();
  return { url: window.location, targets: links.map(link => new URL(link.href)) };
}

for (const id of ['1', '37']) test(`legacy profession ${id} is local and cannot poison service navigation`, () => {
  const p = page(`?namespace_id=${id}&project_scope=all#section`);
  assert.equal(p.url.searchParams.get('profession_id'), id);
  assert.equal(p.url.searchParams.has('namespace_id'), false);
  assert.equal(p.url.hash, '#section');
  assert.equal(p.targets[0].searchParams.get('profession_id'), '7');
  assert.equal(p.targets[1].search, '?project_scope=all');
  assert.equal(p.targets[2].search, '?namespace_id=external');
});

test('project UUID identity survives local profession selection and internal navigation', () => {
  const p = page(`?registry_instance_id=${registry}&namespace_id=${namespace}&profession_id=37&project_scope=all`);
  assert.equal(p.url.searchParams.get('profession_id'), '37');
  for (const target of p.targets.slice(0, 2)) {
    assert.equal(target.searchParams.get('registry_instance_id'), registry);
    assert.equal(target.searchParams.get('namespace_id'), namespace);
    assert.equal(target.searchParams.get('project_scope'), 'all');
  }
  assert.equal(p.targets[0].hash, '#details');
  assert.equal(p.targets[1].searchParams.has('profession_id'), false);
});

test('malformed and duplicate explicit project identity remain visible to destination validation', () => {
  const p = page('?registry_instance_id=invalid&namespace_id=1&namespace_id=2&project_scope=all&project_scope=bad');
  assert.equal(p.url.searchParams.has('profession_id'), false);
  assert.deepEqual(p.targets[1].searchParams.getAll('namespace_id'), ['1', '2']);
  assert.deepEqual(p.targets[1].searchParams.getAll('project_scope'), ['all', 'bad']);
});

test('invalid legacy profession is not silently converted into all projects', () => {
  const p = page('?namespace_id=invalid');
  assert.equal(p.targets[1].searchParams.get('namespace_id'), 'invalid');
  assert.equal(p.url.searchParams.has('profession_id'), false);
});
