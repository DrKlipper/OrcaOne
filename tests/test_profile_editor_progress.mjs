import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const sandbox = {}; vm.createContext(sandbox);
vm.runInContext(readFileSync('orcaone/static/vendor/vue.global.prod.js', 'utf8'), sandbox);
const source = readFileSync('orcaone/static/pages/profile-editor.js', 'utf8').replace(/^import .*;\r?$/gm, '').replace('export default', 'return');
function fixture(api, observePending = false) {
  const Vue = { ...sandbox.Vue, watch(sources, callback, options) { if (observePending && options?.flush === 'sync') return sandbox.Vue.watch(sources, callback, options); }, onUnmounted() {} };
  const emitted = [], events = [];
  const component = new Function('Vue', 'api', 'INSTANCES', 'T', 'profileSession', 'ProfileField', 'ProfileTransfer', 'PlanView', 'DoneView', 'problemText', source)(Vue, api, [{ id: 'test' }], { profileEditor: { loading: 'loading', progressPhases: { write: 'writing' }, progressConnectionLost: 'reconnecting', progressFailed: 'failed', errors: { denied: 'denied' } } }, Vue.ref({ instanceId: 'test', profiles: [] }), {}, {}, {}, {}, code => code);
  const editor = component.setup({ embedded: true }, { emit: (name, value) => { emitted.push(name); events.push([name, value]); } });
  editor.current.value = { id: 'branch', state: 'state', selected: ['a'] };
  editor.documents.value = { a: { id: 'a', kind: 'machine', name: 'A' } }; editor.scopeIds.value = ['a'];
  return { editor, emitted, component, events };
}
test('preview exposes real progress and suppresses duplicate requests', async () => {
  let callback, resolve, calls = 0;
  const { editor } = fixture({ profilePublishProgress: async (id, body, onProgress) => { calls++; callback = onProgress; assert.equal(id, 'test'); assert.deepEqual([...body.selected], ['a']); return new Promise(r => { resolve = r; }); } });
  const pending = editor.previewPublish();
  assert.equal(editor.progress.value.total, null);
  callback({ state: 'running', phase: 'check', completed: 2, total: 3 });
  assert.equal(editor.progress.value.completed, 2);
  await editor.previewPublish(); assert.equal(calls, 1);
  resolve({ id: 'plan' }); await pending;
  assert.equal(editor.plan.value.id, 'plan'); assert.equal(editor.progress.value, null);
});
test('apply keeps connection loss visible and confirms only returned result', async () => {
  let callback, resolve, calls = 0;
  const { editor, emitted } = fixture({ applyProgress: async (id, plan, onProgress) => { calls++; callback = onProgress; return new Promise(r => { resolve = r; }); } });
  editor.plan.value = { id: 'plan' }; const pending = editor.applyPlan();
  callback({ state: 'running', phase: 'write', completed: 1, total: 3, connection_lost: true });
  assert.equal(editor.progressLabel.value, 'reconnecting'); assert.equal(editor.done.value, null);
  await editor.applyPlan(); assert.equal(calls, 1);
  resolve({ verified: true }); await pending;
  assert.equal(editor.done.value.verified, true); assert.deepEqual(emitted, ['applied']);
});
test('blocked apply keeps preview and never emits applied', async () => {
  const { editor, emitted } = fixture({ applyProgress: async () => ({ blocked: 'denied' }) });
  editor.plan.value = { id: 'plan' }; await editor.applyPlan();
  assert.equal(editor.done.value, null); assert.equal(editor.error.value, 'denied');
  assert.equal(editor.plan.value.id, 'plan'); assert.equal(editor.progress.value.state, 'failed'); assert.deepEqual(emitted, []);
});
test('progress is accessible and remains inside sticky action footer', () => {
  const { component } = fixture({});
  const footer = component.template.slice(component.template.indexOf('<footer'));
  assert.match(footer, /role="status" aria-live="polite"/);
  assert.match(footer, /<progress v-if="busy"/);
  assert.match(footer, /progress.total > 0 \? progress.completed : undefined/);
});

test('preview and apply protect navigation while busy and release it after completion', async () => {
  let finish;
  const api = {
    profilePublishProgress: () => new Promise(resolve => { finish = resolve; }),
    applyProgress: () => new Promise(resolve => { finish = resolve; }),
  };
  const { editor, events } = fixture(api, true);
  const preview = editor.previewPublish();
  assert.deepEqual(events.slice(-2), [['running', true], ['pending', true]]);
  finish({ id: 'plan' }); await preview;
  assert.deepEqual(events.slice(-2), [['running', false], ['pending', false]]);
  const apply = editor.applyPlan();
  assert.deepEqual(events.slice(-2), [['running', true], ['pending', true]]);
  finish({ verified: true }); await apply;
  assert.deepEqual(events.slice(-2), [['running', false], ['pending', false]]);
});

test('native preview refresh preserves selected profile names and never applies', async () => {
  const calls = [], previews = [];
  const { editor, emitted } = fixture({
    profilePublishProgress: async (id, body) => {
      previews.push({ ...body, selected: [...body.selected] });
      if (previews.length === 1) throw { code: 'native_preview_required' };
      return { id: 'native-plan' };
    },
    profileEditor: async (id, path, body) => {
      calls.push({ path, body });
      if (path === '/composer-refresh') return { branch: { id: 'refreshed' } };
      if (path === '/branches/refreshed') return {
        branch: { id: 'refreshed', state: 'native-state', selected: ['new-a', 'new-b'] }, draft_generation: 2,
        documents: {
          'new-a': { id: 'new-a', kind: 'machine', name: 'A', workbench: {} },
          'new-b': { id: 'new-b', kind: 'filament', name: 'B', workbench: {} },
        },
      };
      if (path.startsWith('/history')) return { branches: [], states: [], observations: [] };
      throw Error(path);
    },
    applyProgress: async () => { throw Error('Refreshing must not apply'); },
  });
  editor.documents.value.a.workbench = {};
  editor.documents.value.b = { id: 'b', kind: 'filament', name: 'B', workbench: {} };
  editor.current.value.selected = ['a', 'b'];
  editor.scopeIds.value = ['b'];
  await editor.previewPublish();
  assert.equal(editor.error.value, '');
  assert.equal(calls[0].path, '/composer-refresh');
  assert.equal(calls[0].body.branch_id, 'branch');
  assert.deepEqual(previews, [
    { branch_id: 'branch', state_id: 'state', selected: ['b'] },
    { branch_id: 'refreshed', state_id: 'native-state', selected: ['new-b'] },
  ]);
  assert.deepEqual([...editor.scopeIds.value], ['new-b']);
  assert.equal(editor.plan.value.id, 'native-plan');
  assert.equal(editor.done.value, null);
  assert.ok(!emitted.includes('applied'));
});
