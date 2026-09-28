import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../orcaone/static/api.js', import.meta.url), 'utf8');
const { api } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('lost start/poll responses retry without repeating work or claiming completion', async () => {
  const originalFetch = globalThis.fetch;
  const originalTimeout = globalThis.setTimeout;
  const calls = [], progress = [];
  const responses = [null, { job_id: 'one', state: 'running', phase: 'write', completed: 1, total: 3 },
    null, { job_id: 'one', state: 'succeeded', phase: 'done', result: { ok: true } }];
  globalThis.setTimeout = fn => { queueMicrotask(fn); return 0; };
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options });
    const response = responses.shift();
    if (!response) throw new Error('network failure');
    return { ok: true, json: async () => response };
  };
  try {
    assert.deepEqual(await api.applyProgress('instance', 'plan', state => progress.push(state)), { ok: true });
    assert.equal(calls[0].body, calls[1].body);
    assert.equal(calls[2].method, 'GET');
    assert.equal(calls[3].method, 'GET');
    assert.equal(progress.filter(p => p.connection_lost).length, 2);
    assert.equal(progress.filter(p => p.state === 'succeeded').length, 1);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.setTimeout = originalTimeout;
  }
});

test('server failure retains rollback status', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ state: 'failed',
    error: { error: 'publish_failed', rolled_back: true } }) });
  try {
    await assert.rejects(api.applyProgress('instance', 'plan'), error =>
      error.code === 'publish_failed' && error.data.rolled_back === true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
