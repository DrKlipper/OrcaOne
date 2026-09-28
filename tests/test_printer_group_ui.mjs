import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const source = readFileSync(new URL('../orcaone/static/common.js', import.meta.url), 'utf8');
const shown = source.match(/export function modelShown\(inst, m\) \{[\s\S]*?\n\}/)[0].replace('export ', '');
const named = source.match(/export const modelName = .*;/)[0].replace('export ', '');
const live = { slicer: { own: new Set(['first', 'second', 'third', 'fourth']), packages: new Set(), models: new Set() } };
const { modelShown, modelName } = new Function('live', 'printerShortName', `${shown}\n${named}\nreturn { modelShown, modelName };`)(live, value => value);

test('explicit group is visible by its members and uses its display name', () => {
  const group = { group_id: 'id', model: 'group:id', display_name: 'Voron', own: true,
    printers: ['first', 'second', 'third', 'fourth'].map(name => ({ name, variant: '0.5' })) };
  assert.equal(modelShown({ id: 'slicer' }, group), true);
  assert.equal(modelName(group), 'Voron');
  live.slicer.own.delete('first');
  assert.equal(modelShown({ id: 'slicer' }, group), true);
  live.slicer.own.clear();
  assert.equal(modelShown({ id: 'slicer' }, group), false);
});
