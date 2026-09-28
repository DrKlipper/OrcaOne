// Run with node tests/test_printer_merge_ui.cjs; no browser or dependencies needed.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const decode = value => value.replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&amp;/g, '&').replace(/&quot;/g, '"');
const context = { console, URLSearchParams, crypto: { getRandomValues: array => array.fill(7) },
  document: { activeElement: null, createElement() { return { set innerHTML(value) {
    this.textContent = decode(value); this.children = [{ getAttribute: () => decode(value.match(/foo="([\s\S]*)"/)[1]) }];
  } }; } }, window: { confirm: () => true } };
vm.createContext(context);
vm.runInContext(fs.readFileSync('orcaone/static/vendor/vue.global.prod.js', 'utf8'), context);
const readText = lang => vm.runInNewContext(fs.readFileSync(`orcaone/static/texts/printer-merge-${lang}.js`, 'utf8').replace('export default', 'result ='));
const de = readText('de'), en = readText('en');
assert.deepEqual(Object.keys(de).sort(), Object.keys(en).sort());
assert.deepEqual(Object.keys(de.actions).sort(), Object.keys(en.actions).sort());
assert.deepEqual(Object.keys(de.errors).sort(), Object.keys(en.errors).sort());
const V = context.Vue;
const calls = [];
let activeDocuments = 0, maxConcurrentDocuments = 0;
Object.assign(context, { T: { printerMerge: en, profileEditor: { errors: {} } },
  INSTANCES: [{ id: 'fixture', models: [{ own: true, printers: ['A', 'B', 'C', 'D'].map(name => ({ name })) }] }],
  printerMergeSession: V.ref(null), profileSession: V.ref(null), api: { async profileEditor(id, path, body) {
    calls.push({ id, path, body });
    if (path.startsWith('/document')) {
      activeDocuments++;
      maxConcurrentDocuments = Math.max(maxConcurrentDocuments, activeDocuments);
      await new Promise(resolve => setImmediate(resolve));
      activeDocuments--;
      return { name: new URLSearchParams(path.split('?')[1]).get('name'), effective: { nozzle_diameter: ['0.6'], printer_model: 'actual-model' } };
    }
    if (path === '/printer-merge-preview') return { preview_id: 'review', issues: [], process_candidates: [{ name: 'Quality', compatible_printers: ['A'], origin_kind: 'user' }] };
    if (path === '/catalog') return { catalog: { complete: true, options: { machine: {} } } };
    if (path === '/branches/branch') return { branch: { id: 'branch', selected: ['A', 'C', 'D'] }, draft_generation: 0,
      documents: Object.fromEntries(['A', 'C', 'D'].map(id => [id, { id, name: id, kind: 'machine', complete: true, effective: {}, origins: {} }])) };
    if (path.startsWith('/history')) return { branches: [], states: [], observations: [] };
    return { created: true, branch: { id: 'branch' } };
  } } });
let source = fs.readFileSync('orcaone/static/pages/printer-merge.js', 'utf8').replace(/^import .*;\r?\n/gm, '')
  .replace('export function mergeToken', 'function mergeToken').replace('export const MERGE_MIME', 'const MERGE_MIME').replace('export function readMergeDrop', 'function readMergeDrop').replace('export default', 'globalThis.component =');
vm.runInContext(source + '\nglobalThis.readDrop = readMergeDrop; globalThis.mime = MERGE_MIME;', context);
V.compile(context.component.template, { onError(error) { throw error; } });
for (const file of ['orcaone/static/pages/uebersicht.js', 'orcaone/static/pages/zusammenhaenge.js', 'orcaone/static/app.js']) {
  const code = fs.readFileSync(file, 'utf8');
  const start = code.lastIndexOf('template: `') + 'template: `'.length;
  V.compile(code.slice(start, code.lastIndexOf('`')), { onError(error) { throw error; } });
}
const event = (value, types = [context.mime]) => ({ dataTransfer: { types, getData: () => typeof value === 'string' ? value : JSON.stringify(value) }, preventDefault() {}, stopPropagation() {} });
assert.equal(context.readDrop(event({ token: 'bad', kind: 'machine', name: 'A' }), 'session-token', ['A'], []), null);
assert.equal(context.readDrop(event('not JSON'), 'session-token', ['A'], []), null);
assert.equal(context.readDrop(event({ token: 'session-token', kind: 'machine', name: 'other' }), 'session-token', ['A'], []), null);
assert.equal(context.readDrop(event({}, ['text/plain']), 'session-token', ['A'], []), null);
(async () => {
  const ui = context.component.setup();
  context.printerMergeSession.value = { instanceId: 'fixture', names: ['A', 'B', 'C', 'D'] };
  await V.nextTick();
  await ui.loadSources();
  assert.equal(maxConcurrentDocuments, 1, 'identity-creating document reads must be sequential');
  assert.equal(ui.sources.value.length, 4, 'no three-profile limit');
  assert.equal(ui.members.value.length, 0, 'membership is explicit');
  assert.equal(ui.sources.value[0].nozzles[0], '0.6', 'actual document diameter');
  assert.equal(ui.processes.value[0].action, 'leave', 'no automatic process sharing');
  for (const name of ['A', 'B', 'C', 'D']) ui.include(name);
  ui.drop(event({ token: '07'.repeat(16), kind: 'process', name: 'Quality' }), 'B');
  assert.equal(ui.processes.value[0].action, 'share');
  assert.deepEqual(Array.from(ui.processes.value[0].targets), ['B']);
  await ui.preview(); assert.equal(ui.review.value.preview_id, 'review');
  ui.sources.value[0].nozzles[0] = '0.8';
  assert.equal(ui.review.value, null, 'changing proposed values invalidates preview');
  assert.equal(ui.sources.value[0].originalNozzles[0], '0.6', 'source evidence remains unchanged');
  assert.equal(ui.step.value, 2);
  ui.remove('B'); assert.equal(ui.processes.value[0].targets.length, 0);
  ui.processes.value[0].action = 'copy'; ui.processes.value[0].targets = ['C']; ui.processes.value[0].copyName = 'Quality copy';
  await ui.preview();
  assert.equal(calls.at(-1).body.profiles.length, 3);
  assert.equal(calls.at(-1).body.process_choices[0].copy_name, 'Quality copy');
  Object.assign(context, { ProfileField: {}, ProfileTransfer: {}, PlanView: {}, DoneView: {}, problemText: code => code });
  context.T.profileEditor = vm.runInNewContext(fs.readFileSync('orcaone/static/texts/profile-en.js', 'utf8').replace('export default', 'result ='));
  const editorSource = fs.readFileSync('orcaone/static/pages/profile-editor.js', 'utf8').replace(/^import .*;\r?\n/gm, '').replace('export default', 'globalThis.editorComponent =');
  vm.runInContext('(function() {' + editorSource + '})()', context);
  const setup = context.editorComponent.setup;
  const editor = setup({}, setup.length > 1 ? { emit() {} } : null);
  await ui.create();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(editor.current.value.id, 'branch', 'actual editor watcher loads the created branch');
  assert.equal(editor.tab.value, 'editor');
  assert.equal(editor.scoped.value.length, 3, 'actual editor selects all group members');
  assert.equal(context.profileSession.value.branchId, 'branch');
  assert.equal(context.profileSession.value.selectAll, true);
  assert.equal(context.printerMergeSession.value, null);
  console.log('PASS: Vue template, language parity, MIME/session/name guards, 4-profile selection, explicit membership, actual nozzle values, process targets, stale preview, copy payload, editor handoff');
})().catch(error => { console.error(error); process.exitCode = 1; });
