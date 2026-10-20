import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

assert.ok(!process.env.NODE_OPTIONS && !process.env.NODE_PATH && !process.execArgv.length,
  'Navigation executor requires Node builtins without injected modules or flags');
const root = new URL('../../', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('.quality-gate.json', root)));
const gate = manifest.gates.find(value => value.id === 'frontend:navigation');

function fixture(t) {
  const directory = mkdtempSync(path.join(tmpdir(), 'workflow-navigation-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  for (const input of gate.inputs) {
    const target = path.join(directory, input);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, readFileSync(new URL(input, root)));
  }
  return directory;
}

function run(directory, args = [], env = {}) {
  const environment = { ...process.env, NODE_OPTIONS: '', NODE_PATH: '', ...env };
  delete environment.NODE_TEST_CONTEXT;
  return spawnSync(process.execPath, ['scripts/test_profession_navigation.mjs', ...args], {
    cwd: directory, encoding: 'utf8', timeout: 10000,
    env: environment,
  });
}

test('closed input executor retains all nine PDLC3 navigation cases', t => {
  const result = run(fixture(t));
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.match(result.stdout, /\bpass 9\b/);
});

test('input guard rejects missing, extra and excluded dependencies', t => {
  const directory = fixture(t);
  for (const mutate of [
    value => value.inputs.pop(),
    value => value.inputs.push('project_workflow/backend.py'),
    value => { value.exclude_inputs = ['**']; },
    value => { value.argv = ['node', 'unreviewed.mjs']; },
  ]) {
    const changed = structuredClone(manifest);
    mutate(changed.gates.find(value => value.id === gate.id));
    writeFileSync(path.join(directory, '.quality-gate.json'), JSON.stringify(changed));
    assert.notEqual(run(directory).status, 0);
  }
});

test('changed navigation bytes with old timestamp fail the real assertion', t => {
  const directory = fixture(t);
  const filename = path.join(directory, 'project_workflow/interfaces/ui/templates/profession-navigation.js');
  writeFileSync(filename, 'window.WorkflowNavigation = { preserveProjectContext() {} };');
  utimesSync(filename, new Date(0), new Date(0));
  const result = run(directory);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /\bfail 5\b/);
});

test('context observes the executable without registering tests', t => {
  const result = run(fixture(t), ['--context']);
  assert.equal(result.status, 0, result.stderr);
  const context = JSON.parse(result.stdout);
  assert.equal(context.schema, 'workflow-navigation-context/v1');
  assert.equal(context.version, process.version);
  assert.equal(context.platform, process.platform);
  assert.match(context.sha256, /^[0-9a-f]{64}$/);
  assert.doesNotMatch(result.stdout, /TAP version/);
});

test('changed bootstrap with old timestamp fails its real compatibility assertions', t => {
  const directory = fixture(t);
  const filename = path.join(directory, 'project_workflow/interfaces/ui/templates/base/platform-navigation.js');
  writeFileSync(filename, '/* missing namespace controller */');
  utimesSync(filename, new Date(0), new Date(0));
  const result = run(directory);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /\bfail 9\b/);
});

test('unreviewed arguments and injected modules fail closed', t => {
  const directory = fixture(t);
  assert.notEqual(run(directory, ['--unknown']).status, 0);
  // Node reads NODE_PATH itself; a nonempty path must still be rejected.
  assert.notEqual(run(directory, ['--context'], { NODE_PATH: directory }).status, 0);
});
