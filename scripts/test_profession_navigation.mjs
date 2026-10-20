import assert from 'node:assert/strict';
import { closeSync, fstatSync, openSync, readFileSync, readSync, realpathSync } from 'node:fs';
import { createHash } from 'node:crypto';
import vm from 'node:vm';

// This inventory drives both actual reads and Base's receipt inputs.
const inputs = {
  descriptor: '.quality-gate.json',
  executor: 'scripts/test_profession_navigation.mjs',
  navigation: 'project_workflow/interfaces/ui/templates/profession-navigation.js',
  namespaces: 'project_workflow/interfaces/ui/templates/namespaces.html',
};
const readInput = key => readFileSync(new URL('../' + inputs[key], import.meta.url), 'utf8');
const descriptor = JSON.parse(readInput('descriptor'));
const gate = descriptor.gates.find(value => value.id === 'frontend:navigation');
assert.deepEqual(gate?.inputs, Object.values(inputs));
assert.deepEqual(gate.argv, ['node', inputs.executor]);
assert.equal(gate.cwd, '.');
assert.deepEqual(gate.exclude_inputs ?? [], []);

if (process.env.NODE_OPTIONS || process.env.NODE_PATH || process.execArgv.length) {
  throw new Error('Navigation executor requires Node builtins without injected modules or flags');
}
const mode = process.argv.slice(2);
if (mode.length) {
  assert.deepEqual(mode, ['--context']);
  const executable = realpathSync(process.execPath);
  const fd = openSync(executable, 'r');
  const hash = createHash('sha256');
  try {
    const before = fstatSync(fd, { bigint: true });
    const buffer = Buffer.alloc(64 * 1024);
    let size;
    while ((size = readSync(fd, buffer, 0, buffer.length, null))) hash.update(buffer.subarray(0, size));
    const after = fstatSync(fd, { bigint: true });
    for (const field of ['dev', 'ino', 'mode', 'size', 'mtimeNs', 'ctimeNs']) {
      assert.equal(after[field], before[field], 'Node changed during observation: ' + field);
    }
  } finally {
    closeSync(fd);
  }
  console.log(JSON.stringify({
    schema: 'workflow-navigation-context/v1', version: process.version,
    platform: process.platform, architecture: process.arch,
    executable, sha256: hash.digest('hex'),
  }));
  process.exit(0);
}

const { default: test } = await import('node:test');
const source = readInput('navigation');
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

test('loading stored profession fields resets the leave guard after the form is populated', () => {
  const template = readInput('namespaces');
  const fill = template.match(/function fillNamespaceForm\(namespace\)\{([\s\S]*?)\n\}/)[1];
  const fields = new Map(['namespaceIconSelect', 'namespaceName', 'namespaceCliCommand', 'namespaceDescription', 'namespaceLaunchProfile', 'namespaceThemeColor', 'namespaceForm'].map(id => [id, {}]));
  const saved = [];
  const context = { document: { getElementById: id => fields.get(id), querySelectorAll: () => [] }, window: { SdlcPlatformNavigation: { saved: form => saved.push({ form, name: fields.get('namespaceName').value, color: fields.get('namespaceThemeColor').value }) } }, updateNamespaceThemePreview() {}, defaultNamespaceThemeIcon: 'folder', defaultNamespaceThemeColor: '#000' };
  vm.runInNewContext('function fillNamespaceForm(namespace){' + fill + '} fillNamespaceForm({name:"Analyst",theme_color:"#123456"});', context);
  assert.equal(saved.length, 1);
  assert.equal(saved[0].form, fields.get('namespaceForm'));
  assert.equal(saved[0].name, 'Analyst');
  assert.equal(saved[0].color, '#123456');
  fields.get('namespaceName').value = 'Unsaved edit';
  assert.equal(saved[0].name, 'Analyst');
});
