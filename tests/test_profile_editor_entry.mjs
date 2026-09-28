import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const sandbox = { console, URLSearchParams };
vm.createContext(sandbox);
vm.runInContext(readFileSync(new URL('../orcaone/static/vendor/vue.global.prod.js', import.meta.url), 'utf8'), sandbox);
const Vue = sandbox.Vue;
const source = readFileSync(new URL('../orcaone/static/pages/profile-editor.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?$/gm, '').replace('export default', 'return');
const profiles = [{ kind: 'process', name: 'Quality' }, { kind: 'process', name: 'Other' }];
const plain = value => JSON.parse(JSON.stringify(value));
const flush = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };

function fixture(fail = false, initialProfiles = profiles.slice(0, 1), storage = new Map()) {
  const session = Vue.ref(null), calls = [];
  let chosen = initialProfiles;
  const api = { profileEditor: async (id, path, body) => {
    calls.push({ id, path, body: body && plain(body) });
    if (path === '/catalog') return { catalog: { complete: true, options: {} } };
    if (path.startsWith('/history')) return { branches: [], states: [], observations: [] };
    if (path === '/branches') {
      if (fail) throw { code: 'profile_missing' };
      chosen = body.profiles;
      return { id: 'workspace' };
    }
    if (path === '/branches/workspace') return {
      branch: { id: 'workspace', name: 'Quality', selected: chosen.map((_, i) => String(i)) },
      documents: Object.fromEntries(chosen.map((p, i) => [String(i), { ...p, id: String(i), effective: {}, complete: true }])),
      draft_generation: 0,
    };
    throw Error(path);
  } };
  const scope = Vue.effectScope();
  const component = new Function('Vue', 'api', 'INSTANCES', 'T', 'profileSession', 'ProfileField', 'ProfileTransfer',
    'PlanView', 'DoneView', 'problemText', 'document', 'window', source)(
    { ...Vue, onUnmounted() {} }, api, [{ id: 'slicer', processes: profiles }],
    { profileEditor: { copySuffix: ' copy', compositionReady: 'Composition saved locally', errors: { profile_missing: 'missing' } } }, session,
    {}, {}, {}, {}, () => 'error', { activeElement: null }, { confirm: () => true,
      localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) } });
  assert.ok(component.setup.length > 1, 'Vue must provide setupContext for emit');
  const state = scope.run(() => component.setup({}, { emit() {} }));
  return { session, calls, state, component, stop: () => scope.stop() };
}

test('process entry opens only its profile in an automatically named workspace', async () => {
  const f = fixture();
  f.session.value = { instanceId: 'slicer', profiles: [profiles[0]] };
  await flush();
  const creates = f.calls.filter(c => c.path === '/branches');
  assert.equal(creates.length, 1);
  assert.deepEqual(creates[0].body.profiles, [profiles[0]]);
  assert.equal(creates[0].body.name, 'Quality');
  assert.equal(f.state.tab.value, 'editor');
  assert.deepEqual(plain(f.state.tabs.value), ['editor', 'timeline']);
  assert.deepEqual(plain(f.state.scoped.value), ['0']);
  f.stop();
});

test('global entry waits for selection but needs no manual workspace name', async () => {
  const f = fixture();
  f.session.value = { instanceId: 'slicer', profiles: [] };
  await flush();
  assert.equal(f.calls.filter(c => c.path === '/branches').length, 0);
  assert.ok(f.state.tabs.value.includes('selection'));
  f.state.selected.value = ['process:Quality', 'process:Other'];
  await f.state.start();
  const create = f.calls.find(c => c.path === '/branches');
  assert.deepEqual(create.body.profiles, profiles);
  assert.equal(create.body.name, 'Quality, Other');
  assert.doesNotMatch(f.component.template, /v-model="branchName"/);
  f.stop();
});

test('opening an existing workspace does not create a second one', async () => {
  const f = fixture();
  f.session.value = { instanceId: 'slicer', profiles: [], branchId: 'workspace' };
  await flush();
  assert.equal(f.calls.filter(c => c.path === '/branches').length, 0);
  assert.equal(f.state.current.value.id, 'workspace');
  f.stop();
});

test('merge handoff retains the complete explicitly selected group', async () => {
  const f = fixture(false, profiles);
  f.session.value = { instanceId: 'slicer', profiles: [], branchId: 'workspace', selectAll: true };
  await flush();
  assert.deepEqual(plain(f.state.scoped.value), ['0', '1']);
  assert.equal(f.calls.filter(c => c.path === '/branches').length, 0);
  f.stop();
});

test('composition separates profile kinds and confirms local success', async () => {
  const f = fixture(false, [
    { kind: 'filament', name: 'PLA', workbench: {} },
    { kind: 'machine', name: 'Printer', workbench: {} },
    { kind: 'process', name: 'Fine', workbench: {} },
  ]);
  f.session.value = { instanceId: 'slicer', profiles: [], branchId: 'workspace', selectAll: true };
  await flush();
  assert.deepEqual(plain(f.state.scopeGroups.value).map(g => [g.kind, g.rows.map(r => r.name)]),
    [['machine', ['Printer']], ['process', ['Fine']], ['filament', ['PLA']]]);
  assert.equal(f.state.notice.value, 'Composition saved locally');
  assert.deepEqual(plain(f.state.scoped.value), ['0', '1', '2']);
  f.stop();
});

test('editor restores local input and selection after reopening', async () => {
  const storage = new Map();
  const first = fixture(false, profiles, storage);
  first.session.value = { instanceId: 'slicer', profiles: [], branchId: 'workspace', selectAll: true };
  await flush();
  first.state.setField('layer_height', '0.15');
  first.state.scopeIds.value = ['0'];
  await flush(); first.stop();
  const second = fixture(false, profiles, storage);
  second.session.value = { instanceId: 'slicer', profiles: [], branchId: 'workspace', selectAll: true };
  await flush();
  assert.equal(second.state.fieldValue('layer_height'), '0.15');
  assert.deepEqual(plain(second.state.scopeIds.value), ['0']);
  second.stop();
});

test('failed contextual entry shows the error without expanding profile selection', async () => {
  const f = fixture(true);
  f.session.value = { instanceId: 'slicer', profiles: [profiles[0]] };
  await flush();
  assert.equal(f.state.error.value, 'missing');
  assert.equal(f.state.busy.value, false);
  assert.equal(f.state.current.value, null);
  assert.ok(!f.state.tabs.value.includes('selection'));
  f.stop();
});

test('entry template compiles with the bundled Vue version', () => {
  const f = fixture();
  const errors = [];
  Vue.compile(f.component.template, { decodeEntities: value => value, onError: error => errors.push(error) });
  assert.deepEqual(errors, []);
  f.stop();
});

test('publish blocker explains the missing reference with its exact name and parameter', () => {
  const planSource = readFileSync(new URL('../orcaone/static/plan.js', import.meta.url), 'utf8');
  const problemSource = planSource.slice(planSource.indexOf('export function problemText'), planSource.indexOf('// Names as'))
    .replace('export function', 'function');
  for (const lang of ['de', 'en']) {
    const textSource = readFileSync(new URL(`../orcaone/static/texts/${lang}.js`, import.meta.url), 'utf8')
      .replace(/^import .*;\r?$/gm, '').replace('export default T;', 'return T;');
    const texts = new Function('plainName', 'profileEditor', 'profileTransfer', 'printerMerge', textSource)(name => name, {}, {}, {});
    const problemText = new Function('T', problemSource + '\nreturn problemText;')(texts);
    const message = problemText('reference_missing', { slicer: 'Orca' }, { key: 'default_filament_profile', name: 'Snapmaker PLA' });
    assert.notEqual(message, texts.errors.unknown);
    assert.ok(message.includes('default_filament_profile'));
    assert.ok(message.includes('Snapmaker PLA'));
    assert.match(message, lang === 'de' ? /Zuordnung.*Vorschau/ : /reference.*preview/);
  }
});
