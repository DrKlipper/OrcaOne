// Run with node --test tests/test_logs_ui.mjs. No browser or installed Vue needed.
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { test } from "node:test";

const source = readFileSync(process.env.LOGS_PAGE_SOURCE || new URL("../orcaone/static/pages/logs.js", import.meta.url), "utf8")
  .replace(/^import .*;\r?$/gm, "").replace("export default", "return");

test("select readable logs and discard a pending response after all become unreadable", async () => {
  const watchers = [];
  const Vue = {
    ref: (value) => {
      const item = { get value() { return value; }, set value(next) {
        if (next === value) return;
        value = next;
        for (const [refs, callback] of watchers) if (refs.includes(item)) queueMicrotask(callback);
      } };
      return item;
    },
    computed: (get) => ({ get value() { return get(); } }),
    watch: (refs, callback) => watchers.push([Array.isArray(refs) ? refs : [refs], callback]),
    nextTick: async () => {}, onMounted: () => {},
  };
  let files = [{ name: "network.log.enc", readable: false }, { name: "text.log.0", readable: true }];
  const pending = [];
  const calls = [];
  const api = {
    logs: async () => ({ files, location: "~/fixture/log" }),
    log: (id, name) => { calls.push(name); return new Promise((resolve) => pending.push(resolve)); },
  };
  const page = new Function("Vue", "INSTANCES", "T", "api", "RegexHelp", "whenText", "fmtSize", source)(
    Vue, [], { logs: { fileOption: () => "log", unreadable: "unreadable", errors: {} }, errors: {} }, api, {}, () => "", () => "");
  const state = page.setup({ instId: "fixture" });
  await state.refresh();
  await Promise.resolve();
  assert.equal(state.name.value, "text.log.0");
  assert.deepEqual(calls, ["text.log.0"]);
  assert.match(state.fileLabel(files[0], 0), /unreadable.*network.log.enc/);
  assert.match(page.template, /:disabled="!f.readable"/);

  state.log.value = { entries: [{ text: "previous" }] };
  files = [{ name: "network.log.enc", readable: false }];
  await state.refresh();
  await Promise.resolve();
  assert.equal(state.name.value, "");
  assert.equal(state.log.value, null);
  pending[0]({ entries: [{ text: "stale" }] });
  await Promise.resolve();
  assert.equal(state.log.value, null);
  assert.deepEqual(calls, ["text.log.0"]);
  assert.match(page.template, /L.noneReadable/);
});
