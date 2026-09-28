import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const sandbox = { console, URLSearchParams };
vm.createContext(sandbox);
vm.runInContext(readFileSync(new URL('../orcaone/static/vendor/vue.global.prod.js', import.meta.url), 'utf8'), sandbox);
const Vue = sandbox.Vue;
const source = file => readFileSync(new URL('../orcaone/static/pages/' + file, import.meta.url), 'utf8')
  .replace(/^import .*;\r?$/gm, '').replace('export default', 'return');
const flush = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };

function fixture() {
  const session = Vue.ref(null), instance = Vue.ref('first'), calls = [], lifecycle = [];
  const api = { profileEditor: async (id, path) => {
    calls.push({ id, path });
    if (path === '/catalog') return { catalog: { options: {} } };
    if (path.startsWith('/history')) return { branches: [], states: [], observations: [] };
    throw Error(path);
  } };
  const window = { location: { hash: '#/profile-editor/first' }, confirm: () => true,
    addEventListener() {}, removeEventListener() {} };
  const texts = { profileEditor: { copySuffix: ' copy', errors: {} } };
  const editor = new Function('Vue', 'api', 'INSTANCES', 'T', 'profileSession', 'ProfileField', 'ProfileTransfer',
    'PlanView', 'DoneView', 'problemText', 'document', 'window', source('profile-editor.js'))(
    Vue, api, [{ id: 'first' }, { id: 'second' }], texts, session,
    {}, {}, {}, {}, () => 'error', { activeElement: null }, window);
  const editorSetup = editor.setup;
  editor.setup = function (props, context) {
    const id = session.value?.instanceId;
    lifecycle.push('setup:' + id);
    const result = editorSetup(props, context);
    Vue.onUnmounted(() => lifecycle.push('unmounted:' + id));
    return result;
  };
  // Keep the production setup and lifecycle hooks; only replace DOM rendering.
  editor.render = function () { return Vue.h('div', this.session?.instanceId || 'empty'); };
  const page = new Function('Vue', 'ProfileEditor', 'profileSession', 'setLeaveGuard', 'clearLeaveGuard', 'T', 'window',
    source('profile-editor-page.js'))(Vue, editor, session, () => {}, () => {}, texts, window);
  page.render = function () { return Vue.h(editor, { embedded: true, onPending: value => { this.pending = value; } }); };
  const renderer = Vue.createRenderer({
    insert(child, parent, anchor = null) {
      parent.children ||= [];
      const index = anchor ? parent.children.indexOf(anchor) : -1;
      parent.children.splice(index < 0 ? parent.children.length : index, 0, child);
      child.parent = parent;
    },
    remove(child) {
      const siblings = child.parent?.children;
      if (siblings) siblings.splice(siblings.indexOf(child), 1);
    },
    createElement: tag => ({ tag }), createText: text => ({ text }), createComment: text => ({ text }),
    setText: (node, text) => { node.text = text; }, setElementText: (node, text) => { node.text = text; },
    parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
    patchProp() {},
  });
  const container = {};
  const app = renderer.createApp({ setup: () => () => Vue.h(page, { key: instance.value, instId: instance.value }) });
  app.mount(container);
  return { app, session, instance, calls, lifecycle, container };
}

test('instance remount preserves the new editor session after the old editor unmounts', async () => {
  const f = fixture();
  try {
    await flush();
    assert.equal(f.session.value.instanceId, 'first');
    f.instance.value = 'second';
    await flush();
    assert.deepEqual(f.lifecycle, ['setup:first', 'setup:second', 'unmounted:first']);
    assert.equal(f.session.value?.instanceId, 'second');
    assert.equal(f.container.children.at(-1).text, 'second');
    assert.ok(f.calls.some(call => call.id === 'second' && call.path.startsWith('/history')));
  } finally { f.app.unmount(); }
});

test('leaving the editor clears its own session', async () => {
  const f = fixture();
  await flush();
  f.app.unmount();
  assert.equal(f.session.value, null);
});
