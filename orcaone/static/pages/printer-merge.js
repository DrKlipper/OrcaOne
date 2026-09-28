import { api } from '../api.js';
import { INSTANCES } from '../common.js';
import { T } from '../texts.js';
import { profileSession } from './profile-session.js';
import { printerMergeSession } from './printer-merge-session.js';

const { ref, computed, watch, nextTick } = Vue;
export const MERGE_MIME = 'application/x-orcaone-printer-merge';
export function mergeToken() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('');
}
export function readMergeDrop(event, token, machines, processes) {
  if (!Array.from(event.dataTransfer?.types || []).includes(MERGE_MIME)) return null;
  try {
    const value = JSON.parse(event.dataTransfer.getData(MERGE_MIME));
    const names = value.kind === 'machine' ? machines : value.kind === 'process' ? processes : [];
    return value.token === token && names.includes(value.name) ? value : null;
  } catch { return null; }
}

export default {
  name: 'PrinterMerge',
  setup() {
    const P = T.printerMerge, session = printerMergeSession, dialog = ref(null);
    const step = ref(1), selected = ref([]), sources = ref([]), members = ref([]), processes = ref([]);
    const groupName = ref(''), targetModel = ref(''), review = ref(null), busy = ref(false), error = ref('');
    const query = ref(''), processQuery = ref(''), processLimit = ref(30);
    let token = '', previousFocus = null;
    const inst = computed(() => INSTANCES.find(i => i.id === session.value?.instanceId));
    const available = computed(() => [...new Set((inst.value?.models || []).filter(m => m.own).flatMap(m => m.printers.map(p => p.name)))].sort());
    const visible = computed(() => available.value.filter(name => name.toLowerCase().includes(query.value.toLowerCase())));
    const targets = computed(() => sources.value.filter(s => members.value.includes(s.name)));
    const matchingProcesses = computed(() => processes.value.filter(p => p.name.toLowerCase().includes(processQuery.value.toLowerCase())));
    const visibleProcesses = computed(() => matchingProcesses.value.slice(0, processLimit.value));
    function sourceProcesses(source) {
      const names = (inst.value?.models || []).flatMap(m => m.printers).find(p => p.name === source.name)?.processes || [];
      return processes.value.filter(p => p.compatible_printers?.includes(source.name) || names.includes(p.name));
    }
    const canPreview = computed(() => targets.value.length >= 2 && groupName.value.trim() && targetModel.value.trim());
    const issues = computed(() => review.value?.issues || []);
    const blocked = computed(() => issues.value.some(i => i.severity === 'error'));
    const request = (path, body) => api.profileEditor(session.value.instanceId, path, body);
    const issueText = i => [i.key, T.profileEditor.errors?.[i.code] || P.errors?.[i.code] || i.code].filter(Boolean).join(': ');
    function invalidate() { review.value = null; if (step.value === 3) step.value = 2; }
    function payload(rows = targets.value, choices = true) {
      const names = rows.map(s => s.name);
      return { profiles: rows.map(s => ({ kind: 'machine', name: s.name })), group_name: groupName.value.trim(), target_model: targetModel.value.trim(),
        variants: rows.map(s => ({ name: s.name, label: s.label, nozzle_diameter: [...s.nozzles] })),
        process_choices: choices ? processes.value.map(p => ({ name: p.name, action: p.action, targets: p.targets.filter(n => names.includes(n)), ...(p.action === 'copy' ? { copy_name: p.copyName } : {}) })) : [] };
    }
    async function run(action) {
      if (busy.value) return;
      busy.value = true; error.value = '';
      try { await action(); } catch (e) { error.value = T.profileEditor.errors?.[e.code] || P.errors?.[e.code] || e.code || P.failed; }
      finally { busy.value = false; }
    }
    async function loadSources() {
      await run(async () => {
        const docs = [];
        // First reads can create identities in a shared index; serialize its updates.
        for (const name of selected.value) docs.push(await request('/document?kind=machine&name=' + encodeURIComponent(name)));
        sources.value = docs.map(d => ({ name: d.name, label: d.name, originalNozzles: [...(d.effective.nozzle_diameter || [])], nozzles: [...(d.effective.nozzle_diameter || [])], model: d.effective.printer_model || '' }));
        members.value = []; groupName.value = sources.value[0].name; targetModel.value = sources.value[0].model;
        processes.value = []; review.value = null; step.value = 2;
        if (targetModel.value) await discoverProcesses();
      });
    }
    async function discoverProcesses() {
      const result = await request('/printer-merge-preview', payload(sources.value, false));
      processes.value = (result.process_candidates || []).map(p => ({ ...p, action: 'leave', targets: [], copyName: p.name + P.copySuffix }));
    }
    function include(name) { if (busy.value || !sources.value.some(s => s.name === name)) return; if (!members.value.includes(name)) members.value.push(name); invalidate(); }
    function remove(name) {
      members.value = members.value.filter(n => n !== name);
      for (const p of processes.value) p.targets = p.targets.filter(n => n !== name);
      invalidate();
    }
    function drag(event, kind, name) {
      event.dataTransfer.setData(MERGE_MIME, JSON.stringify({ token, kind, name }));
      event.dataTransfer.effectAllowed = 'copy';
    }
    function allowDrop(event) { if (Array.from(event.dataTransfer?.types || []).includes(MERGE_MIME)) event.preventDefault(); }
    function drop(event, target = null) {
      if (busy.value) return;
      const value = readMergeDrop(event, token, sources.value.map(s => s.name), processes.value.map(p => p.name));
      if (!value) return;
      event.preventDefault(); event.stopPropagation();
      if (value.kind === 'machine') include(value.name);
      else if (target && members.value.includes(target)) {
        const p = processes.value.find(p => p.name === value.name);
        if (p.origin_kind !== 'user') { error.value = P.vendorCopy; return; }
        p.action = 'share'; if (!p.targets.includes(target)) p.targets.push(target); invalidate();
      }
    }
    async function preview() {
      await run(async () => { review.value = await request('/printer-merge-preview', payload()); step.value = 3; });
    }
    async function create() {
      if (!review.value || blocked.value) return;
      await run(async () => {
        const result = await request('/printer-merge-branch', { preview_id: review.value.preview_id, name: groupName.value });
        if (!result.created || !result.branch) { error.value = (result.issues || []).map(issueText).join('\n') || P.failed; return; }
        const instanceId = session.value.instanceId; session.value = null;
        profileSession.value = { instanceId, profiles: [], branchId: result.branch.id, selectAll: true };
      });
    }
    function close() {
      if (busy.value || (step.value > 1 && !window.confirm(P.discard))) return;
      session.value = null; previousFocus?.focus();
    }
    function keydown(event) {
      if (event.key === 'Escape') { event.stopPropagation(); close(); }
      if (event.key !== 'Tab') return;
      const els = [...dialog.value.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),[tabindex="0"]')].filter(el => el.getClientRects().length);
      const first = els[0], last = els.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    watch([groupName, targetModel, sources, processes], invalidate, { deep: true, flush: 'sync' });
    watch(session, async value => {
      if (!value) return;
      previousFocus = document.activeElement; token = mergeToken(); step.value = 1;
      selected.value = (value.names || []).filter(n => available.value.includes(n)); sources.value = []; members.value = []; processes.value = [];
      review.value = null; error.value = ''; query.value = ''; processQuery.value = ''; processLimit.value = 30;
      await nextTick(); dialog.value?.querySelector('button')?.focus();
    });
    return { P, session, dialog, step, selected, sources, members, processes, groupName, targetModel, review, busy, error, query, visible, targets,
      canPreview, blocked, issues, issueText, loadSources, discoverProcesses, include, remove, drag, allowDrop, drop, preview, create, close, keydown, invalidate, run, payload,
      sourceProcesses, processQuery, processLimit, matchingProcesses, visibleProcesses };
  },
  template: `
    <div v-if="session" class="profile-backdrop" @keydown="keydown">
      <section ref="dialog" class="profile-editor printer-merge" role="dialog" aria-modal="true" aria-labelledby="printer-merge-title">
        <header class="profile-editor-head"><h2 id="printer-merge-title">{{ P.title }}</h2><button class="btn" :disabled="busy" @click="close">{{ P.close }}</button></header>
        <p class="profile-local-note">{{ P.local }}</p>
        <ol class="merge-steps"><li v-for="(label,index) in P.steps" :key="label" :aria-current="step === index + 1 ? 'step' : null">{{ index + 1 }}. {{ label }}</li></ol>
        <div class="profile-editor-body" :aria-busy="busy">
          <p v-if="error" class="alert" role="alert">{{ error }}</p>
          <fieldset :disabled="busy" class="merge-fields">
            <template v-if="step === 1">
              <p>{{ P.selectHelp }}</p><label>{{ P.search }}<input v-model="query" type="search"></label>
              <div class="profile-selection"><label v-for="name in visible" :key="name"><input v-model="selected" type="checkbox" :value="name">{{ name }}</label></div>
              <p v-if="!visible.length" class="quiet-note">{{ P.empty }}</p><p role="status">{{ P.selected(selected.length) }}</p>
            </template>
            <template v-else-if="step === 2">
              <p>{{ P.assignHelp }}</p>
              <div class="merge-board">
                <section class="merge-sources"><h3>{{ P.sources }}</h3>
                  <article v-for="s in sources" :key="s.name" class="merge-source" draggable="true" @dragstart="drag($event,'machine',s.name)">
                    <h4>{{ s.name }}</h4><p>{{ P.nozzles }}: {{ s.originalNozzles.join(' / ') }} mm</p>
                    <button class="btn" :disabled="members.includes(s.name)" @click="include(s.name)">{{ members.includes(s.name) ? P.added : P.add }}</button>
                    <details v-if="sourceProcesses(s).length" open><summary>{{ P.existingProcesses }} ({{ sourceProcesses(s).length }})</summary>
                      <div class="merge-source-processes"><button v-for="p in sourceProcesses(s)" :key="p.name" type="button" class="merge-process-chip" draggable="true" @dragstart.stop="drag($event,'process',p.name)" @click="processQuery=p.name">{{ p.name }}</button></div>
                    </details>
                  </article>
                </section>
                <section class="merge-target" @dragover="allowDrop" @drop="drop($event)">
                  <h3>{{ P.target }}</h3><label>{{ P.groupName }}<input v-model="groupName" maxlength="160"></label><label>{{ P.targetModel }}<input v-model="targetModel"></label>
                  <p v-if="!targets.length" class="merge-drop-hint">{{ P.dropHint }}</p>
                  <article v-for="s in targets" :key="s.name" class="merge-variant" @dragover="allowDrop" @drop="drop($event,s.name)">
                    <strong>{{ s.name }}</strong><label>{{ P.label }}<input v-model="s.label"></label>
                    <div class="merge-nozzles"><label v-for="(_,index) in s.nozzles" :key="index">{{ P.nozzle(index + 1) }}<input v-model="s.nozzles[index]" inputmode="decimal"></label></div>
                    <p class="quiet-note">{{ P.labelHelp }}</p>
                    <ul v-if="processes.some(p => p.action !== 'leave' && p.targets.includes(s.name))"><li v-for="p in processes.filter(p => p.action !== 'leave' && p.targets.includes(s.name))" :key="p.name">{{ p.name }} · {{ P.actions[p.action] }}</li></ul>
                    <button class="link" @click="remove(s.name)">{{ P.remove }}</button>
                  </article>
                </section>
              </div>
              <section class="merge-processes"><h3>{{ P.processes }}</h3><p>{{ P.processHelp }}</p>
                <label v-if="processes.length">{{ P.searchProcesses }}<input v-model="processQuery" type="search" @input="processLimit=30"></label>
                <button v-if="!processes.length" class="btn" :disabled="!targetModel.trim()" @click="run(discoverProcesses)">{{ P.loadProcesses }}</button>
                <article v-for="p in visibleProcesses" :key="p.name" class="merge-process" draggable="true" @dragstart="drag($event,'process',p.name)">
                  <strong>{{ p.name }}</strong><small v-if="p.condition">{{ P.condition }}: {{ p.condition }}</small>
                  <small v-if="p.origin_kind !== 'user'">{{ P.vendorCopy }}</small>
                  <label>{{ P.action }}<select v-model="p.action"><option v-for="(label,key) in P.actions" :key="key" :value="key" :disabled="key === 'share' && p.origin_kind !== 'user'">{{ label }}</option></select></label>
                  <template v-if="p.action !== 'leave'"><label v-if="p.action === 'copy'">{{ P.copyName }}<input v-model="p.copyName"></label>
                    <div class="merge-process-targets"><label v-for="s in targets" :key="s.name"><input v-model="p.targets" type="checkbox" :value="s.name">{{ s.label }}</label></div>
                  </template>
                </article>
                <button v-if="matchingProcesses.length > processLimit" class="btn" @click="processLimit += 30">{{ P.more }}</button>
              </section>
            </template>
            <template v-else>
              <h3>{{ groupName }}</h3><p>{{ P.targetModel }}: {{ targetModel }}</p>
              <ul><li v-for="s in targets" :key="s.name">{{ s.label }} · {{ s.name }} · {{ s.nozzles.join(' / ') }} mm</li></ul>
              <h3>{{ P.processes }}</h3><ul><li v-for="p in processes" :key="p.name">{{ p.name }}: {{ P.actions[p.action] }}<template v-if="p.action !== 'leave'"> → {{ p.targets.join(', ') }}<template v-if="p.action === 'copy'"> · {{ p.copyName }}</template></template></li></ul>
              <p v-for="(issue,index) in issues" :key="index" :class="issue.severity === 'error' ? 'alert' : 'quiet-note'">{{ issueText(issue) }}</p>
              <p>{{ P.reviewHelp }}</p>
            </template>
          </fieldset>
        </div>
        <footer class="profile-editor-foot"><button v-if="step > 1" class="btn" :disabled="busy" @click="review=null; step--">{{ P.back }}</button>
          <button v-if="step === 1" class="btn btn-primary right" :disabled="busy || selected.length < 2" @click="loadSources">{{ P.assign }}</button>
          <button v-else-if="step === 2" class="btn btn-primary right" :disabled="busy || !canPreview" @click="preview">{{ P.preview }}</button>
          <button v-else class="btn btn-primary right" :disabled="busy || blocked || !review?.preview_id" @click="create">{{ P.create }}</button>
        </footer>
      </section>
    </div>
  `,
};
