import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const read = path => readFileSync(new URL('../orcaone/static/' + path, import.meta.url), 'utf8');

test('profile entries navigate to dedicated sidebar pages and retain their scope', () => {
  const destinations = [];
  const source = read('pages/profile-session.js').replace(/^import .*;\r?$/gm, '').replaceAll('export ', '');
  const entry = new Function('Vue', 'go', 'hashOf', source + '\nreturn {profileSession,openProfiles,openProfileBranch};')(
    { ref: value => ({ value }) }, (_event, url) => destinations.push(url), (page, id) => page + '/' + id);
  entry.openProfiles('instance', [{ kind: 'process', name: 'Quality' }]);
  assert.equal(destinations.at(-1), 'profile-editor/instance');
  assert.equal(entry.profileSession.value.profiles[0].name, 'Quality');
  entry.openProfileBranch('instance', 'branch');
  assert.equal(entry.profileSession.value.branchId, 'branch');
  assert.equal(entry.profileSession.value.selectAll, true);
  assert.equal(destinations.at(-1), 'profile-editor/instance');
});

test('sidebar registers both pages without overview or connections launch buttons', () => {
  for (const id of ['profile-editor', 'profile-workbench']) {
    assert.ok(read('app.js').includes('id: "' + id + '"'));
    assert.ok(read('common.js').includes('"' + id + '"'));
    for (const lang of ['de', 'en']) assert.ok(read('texts/' + lang + '.js').includes('"' + id + '":'));
  }
  assert.ok(!read('pages/uebersicht.js').includes('openPrinterMerge'));
  assert.ok(!read('pages/uebersicht.js').includes('openProfiles'));
  assert.ok(!read('pages/zusammenhaenge.js').includes('openPrinterMerge'));
  assert.ok(!read('app.js').includes('<ProfileEditor'));
  assert.ok(read('pages/profile-editor-page.js').includes(':embedded="true"'));
});
