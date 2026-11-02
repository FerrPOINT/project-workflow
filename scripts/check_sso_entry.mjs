import assert from 'node:assert/strict';
import vm from 'node:vm';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const { html, expected } = JSON.parse(input);
const events = new Map();
const posted = [];
const parent = { postMessage: (message, origin) => posted.push({ message, origin }) };
// Execute the real presentation bootstrap too: a public reader outage must not
// prevent the callback from reporting its authentication result to the host.
const styles = new Map();
const element = () => ({ dataset: {}, querySelectorAll: () => [],
  setAttribute() {}, removeAttribute() {}, remove() {},
  style: { getPropertyValue: (name) => styles.get(name) ?? '', getPropertyPriority: () => '',
    setProperty: (name, value) => styles.set(name, value), removeProperty: (name) => styles.delete(name) } });
const document = { documentElement: element(), cookie: '', baseURI: 'http://workflow.test/sso/callback',
  querySelectorAll: () => [], createElement: element, head: { appendChild() {} },
  addEventListener() {}, removeEventListener() {} };
const window = { parent, document, location: new URL(document.baseURI), localStorage: { getItem: () => null },
  addEventListener: (name, callback) => events.set(name, callback), removeEventListener: () => {},
  dispatchEvent: (event) => events.get(event.type)?.(event),
  MutationObserver: class { observe() {} disconnect() {} }, setInterval: () => 1, clearInterval() {} };
document.documentElement.ownerDocument = document;
document.defaultView = window;
const requests = [];
const context = vm.createContext({ window, document, URL, URLSearchParams, queueMicrotask, AbortController, Event, TextEncoder,
  fetch: async (url, options) => { requests.push({ url, options }); return { status: 503, ok: false }; } });
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
assert.equal(requests.length, 1);
assert.equal(new URL(requests[0].url, document.baseURI).pathname, '/api/platform/branding');
assert.equal(requests[0].options.headers.Authorization, undefined);
console.log(`SSO entry reports ${expected} without treating the callback as a product route`);
