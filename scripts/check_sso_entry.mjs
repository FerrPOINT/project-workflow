import assert from 'node:assert/strict';
import vm from 'node:vm';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const { html, expected } = JSON.parse(input);
const events = new Map();
const posted = [];
const parent = { postMessage: (message, origin) => posted.push({ message, origin }) };
const document = { documentElement: { dataset: {} } };
const window = { parent, document, location: new URL('http://workflow.test/sso/callback'), localStorage: { getItem: () => null }, addEventListener: (name, callback) => events.set(name, callback), removeEventListener: () => {} };
const context = vm.createContext({ window, document, URL, URLSearchParams, queueMicrotask });
for (const [, attributes, source] of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) {
  vm.runInContext(attributes.includes('module') ? source.replace(/\bexport (const|function)/g, '$1') : source, context);
}
await events.get('message')({ origin: 'http://portal.test', source: parent, data: {
  protocol: 'sdlc.platform.v1', serviceKey: 'project-workflow', type: 'initialize',
  attemptId: 'attempt-1', publicPath: '/workflow/', services: [],
} });
const result = posted.find(item => item.message.type === expected);
assert.ok(result, `Missing ${expected} instead of waiting for a timeout`);
assert.equal(result.origin, 'http://portal.test');
assert.equal(posted.some(item => item.message.type === 'route' || item.message.type === 'ready'), false);
if (expected === 'error') assert.ok(result.message.message);
else assert.equal(result.message.route, '/');
console.log(`SSO entry reports ${expected} without treating the callback as a product route`);
