import { api } from "../api.js";
import { INSTANCES } from "../common.js";
import { T } from "../texts.js";
import { profileSession } from "./profile-session.js";
import ProfileField from "./profile-field.js";
import ProfileTransfer from "./profile-transfer.js";
import PlanView, { DoneView, problemText } from "../plan.js";

const { ref, computed, watch, nextTick, onUnmounted } = Vue;

export default {
  components: { ProfileField, ProfileTransfer, PlanView, DoneView },
  props: { embedded: { type: Boolean, default: false } },
  emits: ['applied', 'pending', 'running'],
  setup(_props, { emit }) {
    const P = T.profileEditor;
    const session = profileSession;
    const mountedInstanceId = session.value?.instanceId;
    const dialog = ref(null), tab = ref("selection"), busy = ref(false), error = ref(""), notice = ref("");
    const progress = ref(null);
    const progressLabel = computed(() => progress.value?.connection_lost ? P.progressConnectionLost :
      progress.value?.state === 'failed' ? P.progressFailed : P.progressPhases?.[progress.value?.phase] || P.loading);
    const updateProgress = value => { progress.value = value; };
    const catalog = ref(null), branches = ref([]), selected = ref([]);
    const current = ref(null), documents = ref({}), generation = ref(0), active = ref(""), patches = ref({});
    const query = ref(""), changedOnly = ref(false), note = ref(""), stateList = ref([]), sourceState = ref(""), observations = ref([]);
    const comparison = ref(null), mergeChoices = ref({}), plan = ref(null), done = ref(null);
    const scopeIds = ref([]), stale = ref(false), page = ref(1), pageSize = 40, forkName = ref("");
    const copyName = ref(""), copyBranchName = ref("");
    const variantForm = ref(null), variantReview = ref(null), variantRequest = ref(null);
    const suggestionTarget = ref(''), suggestions = ref([]), suggestionKeys = ref([]);
    const historyCursor = ref(null), bindingNames = ref({});
    const stateRestore = ref(null), restoreRequest = ref(null);
    const profileNames = ref({});
    let variantBaseline = '';
    let previousFocus = null;
    const inst = computed(() => INSTANCES.find(i => i.id === session.value?.instanceId));
    const contextual = computed(() => !!session.value?.profiles?.length);
    const tabs = computed(() => contextual.value ? ['editor', 'timeline'] : ['selection', 'editor', 'timeline']);
    const available = computed(() => {
      const value = inst.value;
      if (!value) return [];
      const rows = [];
      for (const model of value.models || []) for (const printer of model.printers || []) rows.push({ kind: "machine", name: printer.name });
      for (const kind of ["process", "filament"]) for (const profile of value[kind === "process" ? "processes" : "filaments"] || []) rows.push({ kind, name: profile.name });
      return [...new Map(rows.map(row => [row.kind + ':' + row.name, row])).values()];
    });
    const doc = computed(() => documents.value[active.value]);
    const options = computed(() => catalog.value?.options?.[doc.value?.kind] || {});
    const fields = computed(() => Object.entries(options.value).filter(([key, option]) =>
      option.role === "parameter" && (key + ' ' + (option.label || '')).toLowerCase().includes(query.value.toLowerCase()) &&
      (!changedOnly.value || patches.value[active.value + ':' + key])).sort(([a], [b]) => a.localeCompare(b)));
    const dirty = computed(() => Object.keys(patches.value).length > 0);
    const scopeRows = computed(() => (current.value?.selected || Object.keys(documents.value)).map(id => documents.value[id] ||
      { id, name: profileNames.value[id]?.name || profileNames.value[id] || id, kind: profileNames.value[id]?.kind, removed: true }));
    const scopeGroups = computed(() => ['machine', 'process', 'filament', 'removed'].map(kind => ({
      kind, rows: scopeRows.value.filter(row => kind === 'removed' ? !['machine', 'process', 'filament'].includes(row.kind) : row.kind === kind),
    })).filter(group => group.rows.length));
    const scoped = computed(() => scopeIds.value.filter(id => scopeRows.value.some(row => row.id === id)));
    const editableScope = computed(() => scoped.value.filter(id => documents.value[id]));
    const scopedDirty = computed(() => Object.values(patches.value).flat().some(p => scoped.value.includes(p.profile_id)));
    const batchCount = computed(() => editableScope.value.filter(id => documents.value[id].kind === doc.value?.kind).length);
    const pageCount = computed(() => Math.max(1, Math.ceil(fields.value.length / pageSize)));
    const pageFields = computed(() => fields.value.slice((page.value - 1) * pageSize, page.value * pageSize));
    const related = computed(() => editableScope.value.map(id => documents.value[id]).filter(d => d.kind !== 'machine'));
    const suggestionTargets = computed(() => Object.values(documents.value).filter(d => d.kind === 'process' && d.id !== active.value));
    const referenceFields = computed(() => Object.entries(options.value).filter(([key, option]) => option.role === 'reference' &&
      option.type === 'coStrings' && ['compatible_printers', 'compatible_prints', 'default_filament_profile', 'upward_compatible_machine'].includes(key)));
    const chosenMergeCount = computed(() => Object.values(mergeChoices.value).filter(v => v === 'source').length);
    const issueText = issue => `${issue.key ? issue.key + ': ' : ''}${P.errors?.[issue.code] || issue.code}`;
    const variantDirty = () => variantForm.value && JSON.stringify(variantForm.value) !== variantBaseline;
    const request = (path, body, method) => api.profileEditor(session.value.instanceId, path, body, method);
    async function run(action) {
      if (busy.value) return;
      busy.value = true; error.value = ""; notice.value = ""; progress.value = null;
      try { return await action(); }
      catch (e) {
        if (progress.value) progress.value = { ...progress.value, state: 'failed' };
        if (['draft_conflict', 'branch_conflict', 'stale_generation'].includes(e.code)) stale.value = true;
        if (e.code === 'plan_outdated') plan.value = null;
        error.value = (e.code === 'composer_modified' ? P.retainedConflict : P.errors?.[e.code]) || problemText(e.code, inst.value, e.data) || P.error;
      }
      finally { busy.value = false; }
    }
    async function refreshHistory(branchId = current.value?.id, more = false) {
      const params = new URLSearchParams();
      if (branchId) params.set('branch_id', branchId);
      if (more && historyCursor.value) params.set('cursor', historyCursor.value);
      const result = await request('/history' + (params.size ? '?' + params : ''));
      const append = (old, next) => more ? [...new Map([...old, ...next].map(item => [item.id, item])).values()] : next;
      branches.value = append(branches.value, result.branches || []);
      observations.value = append(observations.value, result.observations || []);
      stateList.value = append(stateList.value, result.states || []);
      historyCursor.value = result.cursor || null;
    }
    const editorStorageKey = id => 'orcaone.editor.draft.' + session.value?.instanceId + '.' + id;
    async function openBranch(id, preserve = false) {
      if (!preserve && (dirty.value || variantDirty()) && !window.confirm(P.discard)) return;
      let remembered;
      try { remembered = JSON.parse(window.localStorage?.getItem(editorStorageKey(id)) || 'null'); } catch { /* No usable stored draft. */ }
      const same = current.value?.id === id;
      const result = await request('/branches/' + id);
      done.value = null; plan.value = null;
      current.value = result.branch; documents.value = result.documents;
      try { window.localStorage?.setItem('orcaone.editor.branch.' + session.value.instanceId, id); } catch { /* Server branch remains saved. */ }
      profileNames.value = { ...profileNames.value, ...result.profile_names, ...Object.fromEntries(Object.values(result.documents).map(d => [d.id, { name: d.name, kind: d.kind }])) };
      generation.value = result.draft_generation;
      active.value = same && result.documents[active.value] ? active.value : Object.keys(result.documents)[0] || "";
      scopeIds.value = same ? scopeIds.value.filter(id => (result.branch.selected || Object.keys(result.documents)).includes(id)) :
        session.value?.selectAll ? [...(result.branch.selected || Object.keys(result.documents))] :
        active.value ? [active.value] : (result.branch.selected || []).slice(0, 1);
      if (!preserve) patches.value = {};
      stale.value = false; comparison.value = null; variantForm.value = null; variantReview.value = null; tab.value = "editor";
      if (!same && remembered) {
        scopeIds.value = (remembered.scope || []).filter(id => scopeRows.value.some(row => row.id === id));
        if (documents.value[remembered.active]) active.value = remembered.active;
        patches.value = remembered.patches || {};
        if (Object.keys(patches.value).length && (remembered.state !== current.value.state || remembered.generation !== generation.value)) {
          stale.value = true; error.value = P.retainedConflict;
        }
      }
      await refreshHistory(id);
    }
    async function startSelected() {
      const profiles = contextual.value ? session.value.profiles :
        selected.value.map(key => available.value.find(p => p.kind + ':' + p.name === key)).filter(Boolean);
      if (!profiles.length) return;
      const branch = await request('/branches', { name: profiles.map(p => p.name).join(', ').slice(0, 120), profiles });
      patches.value = {};
      await openBranch(branch.id);
    }
    async function start() {
      if (dirty.value && !window.confirm(P.discard)) return;
      await run(startSelected);
    }
    function setField(key, value, op = "set", all = false, indices = null) {
      plan.value = null; done.value = null;
      const ids = all ? editableScope.value.filter(id => documents.value[id].kind === doc.value.kind) : [active.value];
      for (const id of ids) {
        const storageKey = id + ':' + key;
        const patch = { profile_id: id, key, op, value, indices };
        patches.value[storageKey] = indices !== null || op.startsWith('bind_') ? [...(patches.value[storageKey] || []), patch] : [patch];
      }
    }
    function switchProfile(event) {
      if (variantDirty() && !window.confirm(P.discard)) { event.target.value = active.value; return; }
      active.value = event.target.value;
    }
    function changePage(delta) {
      page.value = Math.min(pageCount.value, Math.max(1, page.value + delta));
      nextTick(() => dialog.value?.querySelector('.profile-pagination')?.scrollIntoView({ block: 'start' }));
    }
    function valueFor(id, key) {
      let value = documents.value[id].effective[key];
      for (const patch of patches.value[id + ':' + key] || []) {
        if (patch.op === 'bind_add') value = [...(value || []), ...patch.value.filter(member => !(value || []).includes(member))];
        else if (patch.op === 'bind_remove') value = (value || []).filter(member => !patch.value.includes(member));
        else if (patch.indices !== null && Array.isArray(value)) {
          const next = [...value];
          patch.indices.forEach((index, offset) => { next[index] = patch.op === 'reset' ? documents.value[id].inherited[key]?.[index] : patch.value[offset]; });
          value = next;
        } else value = patch.op === 'reset' ? documents.value[id].inherited[key] : patch.value;
      }
      return value;
    }
    function fieldValue(key) { return valueFor(active.value, key); }
    function mixedField(key) {
      return new Set(editableScope.value.filter(id => documents.value[id].kind === doc.value.kind).map(id => JSON.stringify(valueFor(id, key)))).size > 1;
    }
    function bindingOptions(key) {
      const kind = key === 'compatible_prints' ? 'process' : key === 'default_filament_profile' ? 'filament' : 'machine';
      const names = [...available.value, ...Object.values(documents.value)].filter(row => row.kind === kind).map(row => row.name);
      return [...new Set(names)].filter(name => !(fieldValue(key) || []).includes(name)).sort((a, b) => a.localeCompare(b));
    }
    function bindField(key, member, add) {
      if (!member) return;
      setField(key, [member], add ? 'bind_add' : 'bind_remove'); bindingNames.value[key] = '';
    }
    function fieldOrigin(key) {
      const patch = patches.value[active.value + ':' + key]?.at(-1);
      return patch ? patch.op === 'reset' ? doc.value.inherited_origins?.[key] : { kind: 'profile', profile_id: active.value } : doc.value.origins[key];
    }
    async function save() {
      if (!editableScope.value.length || stale.value) return false;
      const selectedPatches = Object.values(patches.value).flat().filter(p => scoped.value.includes(p.profile_id));
      const result = await request('/drafts/' + current.value.id, { selected: editableScope.value, expected_generation: generation.value, patches: selectedPatches }, "PUT");
      if (!result.saved) {
        error.value = result.issues.map(issueText).join('\n'); return false;
      }
      generation.value = result.generation; documents.value = { ...documents.value, ...result.documents };
      for (const patch of selectedPatches) delete patches.value[patch.profile_id + ':' + patch.key];
      notice.value = P.saved; return true;
    }
    async function checkpoint() {
      await run(async () => {
        if (!await save()) return;
        await request('/states', { branch_id: current.value.id, selected: editableScope.value,
          expected_generation: generation.value, expected_branch_generation: current.value.generation, note: note.value });
        await openBranch(current.value.id, true); await refreshHistory(); notice.value = P.checkpointSaved;
      });
    }
    async function previewPublish() {
      await run(async () => {
        if (scopedDirty.value) { error.value = P.saveBeforePublish; return; }
        done.value = null;
        const makePreview = () => {
          updateProgress({ state: 'queued', phase: 'check', completed: 0, total: null });
          return api.profilePublishProgress(inst.value.id, { branch_id: current.value.id, state_id: current.value.state, selected: scoped.value }, updateProgress);
        };
        try { plan.value = await makePreview(); if (['plan_outdated', 'native_preview_required'].includes(plan.value.blocked)) throw { code: plan.value.blocked }; }
        catch (e) {
          if (!['plan_outdated', 'native_preview_required'].includes(e.code) || dirty.value || !Object.values(documents.value).every(d => d.workbench)) throw e;
          const selectedNames = scoped.value.map(id => documents.value[id]).map(d => d.kind + ':' + d.name);
          const refreshed = await request('/composer-refresh', { branch_id: current.value.id });
          await openBranch(refreshed.branch.id, true);
          scopeIds.value = Object.values(documents.value).filter(d => selectedNames.includes(d.kind + ':' + d.name)).map(d => d.id);
          await nextTick();
          plan.value = await makePreview();
        }
        progress.value = null;
        nextTick(() => dialog.value?.querySelector('.profile-publish-review')?.scrollIntoView({ block: 'start' }));
      });
    }
    async function applyPlan() {
      await run(async () => {
        if (!plan.value || plan.value.blocked) return;
        updateProgress({ state: 'queued', phase: 'check', completed: 0, total: null });
        const result = await api.applyProgress(inst.value.id, plan.value.id, updateProgress);
        if (result.blocked) throw { code: result.blocked, data: result };
        done.value = result; progress.value = null; plan.value = null; emit('applied');
      });
    }
    async function compare(mode) {
      await run(async () => {
        const result = await request('/' + mode + '-preview', { branch_id: current.value.id, source_state: sourceState.value,
          selected: scoped.value });
        if (result.issues?.some(i => i.severity === 'error')) { error.value = result.issues.map(issueText).join('\n'); return; }
        comparison.value = { mode, ...result }; mergeChoices.value = {};
      });
    }
    async function previewStateRestore() {
      await run(async () => {
        const payload = { branch_id: current.value.id, source_state: sourceState.value, selected: [...scoped.value] };
        stateRestore.value = await request('/restore-state-preview', payload);
        restoreRequest.value = payload;
      });
    }
    async function applyStateRestore() {
      await run(async () => {
        const result = await request('/restore-state', { ...restoreRequest.value, expected_branch_generation: stateRestore.value.branch_generation });
        stateRestore.value = null; await openBranch(result.branch.id, true); notice.value = P.wholeRestoreSaved;
      });
    }
    function restoreDetails(change) {
      const before = change.before?.effective || {}, after = change.after?.effective || {};
      return [...new Set([...Object.keys(before), ...Object.keys(after)])].sort().filter(key => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
        .map(key => ({ key, before: before[key], after: after[key] }));
    }
    function openTransferred(result) {
      if ((dirty.value || variantDirty()) && !window.confirm(P.discard)) return;
      session.value = { instanceId: result.instanceId, profiles: [], branchId: result.branchId };
    }
    async function adopt() {
      await run(async () => {
        const fields = {};
        for (const [id, rows] of Object.entries(comparison.value.profiles || {})) {
          const keys = rows.filter(row => mergeChoices.value[id + ':' + row.key] === 'source').map(row => row.key);
          if (keys.length) fields[id] = keys;
        }
        const result = await request('/history-draft', { branch_id: current.value.id, source_state: sourceState.value,
          mode: comparison.value.mode, fields, expected_generation: generation.value });
        if (result.issues?.length) { error.value = result.issues.map(issueText).join('\n'); return; }
        await openBranch(current.value.id, true); comparison.value = null;
      });
    }
    async function fork() {
      if (dirty.value && !window.confirm(P.discard)) return;
      await run(async () => {
        const branch = await request('/branches', { name: forkName.value, state_id: sourceState.value, selected: scoped.value });
        patches.value = {}; await refreshHistory(); await openBranch(branch.id);
      });
    }
    async function copyProfile() {
      if (dirty.value) { error.value = P.saveBeforeVariant; return; }
      await run(async () => {
        const result = await request('/copy-branch', { branch_id: current.value.id, profile_id: active.value, name: copyName.value, branch_name: copyBranchName.value });
        if (result.issues?.length) { error.value = result.issues.map(issueText).join('\n'); return; }
        await refreshHistory(); await openBranch(result.branch.id);
      });
    }
    function openVariant() {
      variantForm.value = { target_model: doc.value.effective.printer_model || '', name: doc.value.name + P.copySuffix,
        branch_name: doc.value.name + P.copySuffix, copy: true, nozzle_diameter: [...(doc.value.effective.nozzle_diameter || [])],
        printer_variant: doc.value.effective.printer_variant || '', choices: {}, copy_names: {} };
      for (const relatedDoc of related.value) {
        variantForm.value.choices[relatedDoc.id] = 'leave';
        variantForm.value.copy_names[relatedDoc.id] = relatedDoc.name + P.copySuffix;
      }
      variantBaseline = JSON.stringify(variantForm.value);
      variantReview.value = null;
    }
    async function previewVariant() {
      await run(async () => {
        const form = variantForm.value;
        const body = { branch_id: current.value.id, profile_id: active.value, target_model: form.target_model,
          configuration: { copy: form.copy, name: form.name, nozzle_diameter: form.nozzle_diameter, printer_variant: form.printer_variant },
          choices: Object.fromEntries(related.value.map(d => [d.id, form.choices[d.id] || 'leave'])), copy_names: form.copy_names, name: form.branch_name };
        variantRequest.value = JSON.parse(JSON.stringify(body)); variantReview.value = await request('/variant-preview', body);
      });
    }
    async function createVariant() {
      if (!variantReview.value || variantReview.value.issues?.length) return;
      await run(async () => {
        const result = await request('/variant-branch', { ...variantRequest.value, basis: variantReview.value.basis });
        if (!result.created) { error.value = result.issues.map(issueText).join('\n'); return; }
        variantForm.value = null; await refreshHistory(); await openBranch(result.branch.id);
      });
    }
    async function loadSuggestions() {
      await run(async () => {
        const result = await request('/suggestions', { branch_id: current.value.id, profile_id: active.value, target_profile_id: suggestionTarget.value });
        suggestions.value = result.suggestions || []; suggestionKeys.value = [];
        if (!suggestions.value.length) notice.value = P.noSuggestions;
      });
    }
    function acceptSuggestions() {
      for (const suggestion of suggestions.value) if (suggestionKeys.value.includes(suggestion.key)) setField(suggestion.key, suggestion.after);
      notice.value = P.suggestionsApplied; suggestions.value = []; suggestionKeys.value = [];
    }
    function close() {
      if (busy.value) return;
      if ((dirty.value || variantDirty()) && !window.confirm(P.discard)) return;
      session.value = null; previousFocus?.focus();
    }
    function keydown(event) {
      if (_props.embedded) return;
      if (event.key === 'Escape') { event.preventDefault(); close(); }
      if (event.key !== 'Tab') return;
      const items = [...dialog.value.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')].filter(e => e.getClientRects().length);
      if (!items.length) return;
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1).focus(); }
      else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); }
    }
    watch(session, value => {
      if (!value) return;
      previousFocus = document.activeElement; tab.value = value.profiles.length ? 'editor' : 'selection'; current.value = null; documents.value = {};
      patches.value = {}; plan.value = null; done.value = null; comparison.value = null; stateRestore.value = null;
      stale.value = false; scopeIds.value = []; profileNames.value = {}; variantForm.value = null; variantReview.value = null; error.value = ''; notice.value = '';
      selected.value = value.profiles.map(p => p.kind + ':' + p.name);
      run(async () => {
        catalog.value = (await request('/catalog')).catalog;
        if (value.branchId) {
          await openBranch(value.branchId);
          if (Object.values(documents.value).some(document => document.workbench)) notice.value = P.compositionReady;
        }
        else if (value.profiles.length) await startSelected();
        else await refreshHistory();
      });
      nextTick(() => dialog.value?.focus());
    }, { immediate: true });
    watch([active, query, changedOnly], () => { page.value = 1; });
    watch(active, () => {
      variantForm.value = null; variantReview.value = null;
      suggestionTarget.value = ''; suggestions.value = []; suggestionKeys.value = [];
      copyName.value = (doc.value?.name || '') + P.copySuffix;
      copyBranchName.value = copyName.value;
      bindingNames.value = {};
    });
    watch([patches, scopeIds, active, busy], () => {
      if (!current.value || busy.value) return;
      try { window.localStorage?.setItem(editorStorageKey(current.value.id), JSON.stringify({
        state: current.value.state, generation: generation.value, patches: patches.value, scope: scopeIds.value, active: active.value,
      })); } catch { /* Keep unsaved edits in memory if browser storage is unavailable. */ }
    }, { deep: true, flush: 'sync' });
    watch([scopeIds, sourceState], () => { comparison.value = null; variantReview.value = null; stateRestore.value = null; plan.value = null; }, { deep: true });
    watch(variantForm, () => { variantReview.value = null; }, { deep: true });
    watch([dirty, variantForm, busy], () => {
      emit('running', busy.value);
      emit('pending', !!(busy.value || dirty.value || variantDirty()));
    }, { deep: true, immediate: true, flush: 'sync' });
    watch(suggestionTarget, () => { suggestions.value = []; suggestionKeys.value = []; });
    watch(pageCount, count => { page.value = Math.min(page.value, count); });
    onUnmounted(() => {
      if (session.value?.instanceId === mountedInstanceId) session.value = null;
    });
    return { P, session, inst, dialog, tab, tabs, contextual, busy, error, notice, progress, progressLabel, catalog, branches, selected, available,
      current, documents, active, doc, fields, dirty, query, changedOnly, note, stateList, sourceState, comparison,
      mergeChoices, plan, done, run, openBranch, start, setField, fieldValue, save, checkpoint, previewPublish,
      applyPlan, compare, adopt, close, keydown, json: value => JSON.stringify(value), scopeIds, scoped, scopedDirty, stale,
      page, pageSize, pageCount, pageFields, batchCount, fieldOrigin, forkName, fork, copyName, copyBranchName, copyProfile,
      variantForm, variantReview, related, openVariant, previewVariant, createVariant, issueText, chosenMergeCount, observations,
      suggestionTarget, suggestions, suggestionKeys, suggestionTargets, loadSuggestions, acceptSuggestions,
      historyCursor, refreshHistory, referenceFields, bindingNames, bindingOptions, bindField, mixedField, switchProfile, changePage,
      stateRestore, previewStateRestore, applyStateRestore, restoreDetails, openTransferred, scopeRows, scopeGroups, editableScope };
  },
  template: `
  <div v-if="session" :class="embedded ? 'profile-inline' : 'profile-backdrop'">
    <section ref="dialog" class="profile-editor" :role="embedded ? 'region' : 'dialog'" :aria-modal="embedded ? null : 'true'" :aria-labelledby="embedded ? 'page-title' : 'profile-editor-title'" tabindex="-1" @keydown="keydown">
      <header class="profile-editor-head"><div><component :is="embedded ? 'h1' : 'h2'" :id="embedded ? 'page-title' : 'profile-editor-title'">{{ P.title }}</component><p>{{ inst?.slicer }} · {{ current?.name || session.profiles[0]?.name || P.select }}</p></div>
        <button v-if="!embedded" class="btn" type="button" :disabled="busy" @click="close">{{ P.close }}</button></header>
      <p class="profile-local-note">{{ P.local }}</p>
      <nav class="profile-tabs" :aria-label="P.title"><button v-for="name in tabs" :key="name" class="btn" :aria-pressed="tab === name" :disabled="name === 'editor' && !current" @click="tab = name">{{ P[name] }}</button></nav>
      <p v-if="busy" role="status">{{ P.loading }}</p><p v-if="error" class="profile-error" role="alert">{{ error }}</p><p v-if="notice" class="profile-success" role="status">{{ notice }}</p>
      <div v-if="stale && current" class="profile-stale"><p>{{ P.staleHelp }}</p><button class="btn" :disabled="busy" @click="run(() => openBranch(current.id))">{{ P.reload }}</button></div>
      <div class="profile-editor-body" :aria-busy="busy">
        <details v-if="current && scopeRows.length > 1 && tab !== 'selection'" class="profile-scope" open>
          <summary>{{ P.actionScope }} · {{ scoped.length }} / {{ scopeRows.length }}</summary>
          <p class="profile-muted">{{ P.scopeHelp }}</p>
          <div class="profile-scope-actions"><button class="btn" :disabled="busy" @click="scopeIds = scopeRows.map(d => d.id)">{{ P.selectAll }}</button><button class="btn" :disabled="busy" @click="scopeIds = []">{{ P.selectNone }}</button></div>
          <section v-for="group in scopeGroups" :key="group.kind" class="profile-scope-group"><h3>{{ P.scopeGroups[group.kind] }} ({{ group.rows.length }})</h3><div class="profile-scope-list"><label v-for="d in group.rows" :key="d.id"><input type="checkbox" v-model="scopeIds" :value="d.id" :disabled="busy"><span><small v-if="d.removed">{{ P.removedProfile }}</small>{{ d.name }}</span></label></div></section>
          <p v-if="!scoped.length" class="profile-warning">{{ P.scopeRequired }}</p>
        </details>
        <template v-if="tab === 'selection' && !contextual">
          <p v-if="!catalog?.complete" class="profile-warning">{{ P.unsupported }}</p>
          <p>{{ P.empty }}</p><div class="profile-selection"><label v-for="p in available" :key="p.kind + ':' + p.name"><input type="checkbox" v-model="selected" :value="p.kind + ':' + p.name"> <span><small>{{ P[p.kind] }}</small>{{ p.name }}</span></label></div>
          <div class="profile-toolbar"><button class="btn btn-primary" :disabled="busy || !selected.length" @click="start">{{ P.start }}</button></div>
        </template>
        <template v-if="tab === 'editor' && doc">
          <div class="profile-toolbar"><label v-if="scopeRows.length > 1">{{ P.activeProfile }}<select :value="active" :disabled="busy" @change="switchProfile"><option v-for="d in documents" :key="d.id" :value="d.id">{{ P[d.kind] }} · {{ d.name }}</option></select></label>
            <label>{{ P.search }}<input type="search" v-model="query"></label><label><input type="checkbox" v-model="changedOnly"> {{ P.changed }}</label></div>
          <p v-if="!doc.complete" class="profile-warning">{{ P.incomplete }}</p>
          <p v-if="!scoped.includes(active)" class="profile-muted">{{ P.activeNotSelected }}</p>
          <details v-if="referenceFields.length" class="profile-copy"><summary>{{ P.referenceTitle }}</summary><p>{{ P.referenceHelp }}</p>
            <div v-for="[key, option] in referenceFields" :key="key" class="profile-reference"><h4>{{ P.referenceLabels[key] || key }}</h4>
              <p v-if="!(fieldValue(key) || []).length" class="profile-muted">{{ key.startsWith('compatible_') ? P.unrestricted : P.emptyBindings }}</p>
              <ul><li v-for="member in fieldValue(key) || []" :key="member"><span>{{ member }}</span><button class="btn" :disabled="busy || stale || !doc.complete" @click="bindField(key, member, false)">{{ P.unbind }}</button></li></ul>
              <div class="profile-toolbar"><label>{{ P.bindTarget }}<select v-model="bindingNames[key]" :disabled="busy || stale || !doc.complete"><option value="">{{ P.choose }}</option><option v-for="name in bindingOptions(key)" :key="name" :value="name">{{ name }}</option></select></label><button class="btn" :disabled="busy || stale || !doc.complete || !bindingNames[key]" @click="bindField(key, bindingNames[key], true)">{{ P.bind }}</button></div>
            </div>
          </details>
          <details class="profile-copy"><summary>{{ P.copyProfile }}</summary><p>{{ P.copyHelp }}</p><div class="profile-toolbar"><label>{{ P.name }}<input v-model="copyName" maxlength="120"></label><label>{{ P.branchName }}<input v-model="copyBranchName" maxlength="120"></label><button class="btn" :disabled="busy || stale || dirty || !copyName.trim() || !copyBranchName.trim()" @click="copyProfile">{{ P.createCopy }}</button></div></details>
          <details v-if="doc.kind === 'process'" class="profile-copy"><summary>{{ P.suggestionsTitle }}</summary><p>{{ P.suggestionsHelp }}</p>
            <p v-if="!suggestionTargets.length" class="profile-muted">{{ P.suggestionsNoTarget }}</p>
            <div v-else class="profile-toolbar"><label>{{ P.suggestionsTarget }}<select v-model="suggestionTarget" :disabled="busy"><option value="">{{ P.choose }}</option><option v-for="target in suggestionTargets" :key="target.id" :value="target.id">{{ target.name }}</option></select></label><button class="btn" :disabled="busy || stale || dirty || !suggestionTarget" @click="loadSuggestions">{{ P.loadSuggestions }}</button></div>
            <div v-for="suggestion in suggestions" :key="suggestion.key" class="profile-diff-row"><label><input type="checkbox" v-model="suggestionKeys" :value="suggestion.key" :disabled="busy">{{ suggestion.key.replaceAll('_', ' ') }}</label><div><small>{{ P.before }}</small><pre>{{ json(suggestion.before) }}</pre></div><div><small>{{ P.after }} · {{ suggestion.source }}</small><pre>{{ json(suggestion.after) }}</pre></div></div>
            <button v-if="suggestions.length" class="btn" :disabled="busy || stale || !suggestionKeys.length || !scoped.includes(active)" @click="acceptSuggestions">{{ P.acceptSuggestions }} ({{ suggestionKeys.length }})</button>
          </details>
          <div v-if="doc.kind === 'machine'" class="profile-variant">
            <button class="btn" :disabled="busy || stale || dirty || !doc.complete || !scoped.includes(active)" @click="openVariant">{{ P.variant }}</button>
            <template v-if="variantForm"><h3>{{ P.variant }}</h3><p>{{ P.variantHelp }}</p>
              <div class="profile-toolbar"><label>{{ P.model }}<input v-model="variantForm.target_model"></label><label>{{ P.name }}<input v-model="variantForm.name" maxlength="120" :disabled="!variantForm.copy"></label><label>{{ P.branchName }}<input v-model="variantForm.branch_name" maxlength="120"></label></div>
              <label class="profile-check"><input type="checkbox" v-model="variantForm.copy" @change="variantForm.name = variantForm.copy ? doc.name + P.copySuffix : doc.name">{{ P.newVariant }}</label>
              <div class="profile-toolbar"><label v-for="(diameter, index) in variantForm.nozzle_diameter" :key="index">{{ P.extruder }} {{ index + 1 }} · {{ P.diameterShort }}<input inputmode="decimal" v-model="variantForm.nozzle_diameter[index]"></label><label>{{ P.variantLabel }}<input v-model="variantForm.printer_variant"></label></div>
              <p>{{ P.shared }}</p><div v-for="d in related" :key="d.id" class="profile-related"><label>{{ d.name }}<select v-model="variantForm.choices[d.id]"><option value="leave">{{ P.leaveRelated }}</option><option value="share">{{ P.shareRelated }}</option><option value="copy">{{ P.copyRelated }}</option></select></label><label v-if="variantForm.choices[d.id] === 'copy'">{{ P.name }}<input v-model="variantForm.copy_names[d.id]" maxlength="120"></label></div>
              <p v-if="!related.length" class="profile-muted">{{ P.noRelatedSelected }}</p>
              <button class="btn" :disabled="busy || stale" @click="previewVariant">{{ P.variantPreview }}</button>
              <div v-if="variantReview" class="profile-variant-review"><h4>{{ P.preview }}</h4><p v-for="(issue, index) in variantReview.issues" :key="index" class="profile-warning">{{ issueText(issue) }}</p><template v-if="variantReview.document"><p><strong>{{ variantReview.document.name }}</strong> · {{ variantReview.document.effective.printer_model }}</p><p>{{ P.diameter }}: {{ variantReview.document.effective.nozzle_diameter.join(' / ') }}</p><ul><li v-for="d in variantReview.documents" :key="d.id">{{ P[d.kind] }} · {{ d.name }}</li></ul><p>{{ P.variantLocal }}</p></template><button class="btn btn-primary" :disabled="busy || stale || !variantReview.document || variantReview.issues?.length" @click="createVariant">{{ P.createVariant }}</button></div>
            </template>
          </div>
          <details class="profile-parameters" :open="changedOnly || !!query"><summary>{{ P.allParameters }} ({{ fields.length }})</summary>
          <div class="profile-pagination" v-if="fields.length"><p>{{ P.parameterCount }}: {{ fields.length }} · {{ P.page }} {{ page }} / {{ pageCount }}</p><div><button class="btn" :disabled="page <= 1" @click="changePage(-1)">{{ P.previous }}</button><button class="btn" :disabled="page >= pageCount" @click="changePage(1)">{{ P.next }}</button></div></div>
          <p v-else class="profile-muted">{{ P.noParameters }}</p>
          <ProfileField v-for="[key, option] in pageFields" :key="active + ':' + key" :field-key="key" :profile-id="doc.id" :option="option" :value="fieldValue(key)" :origin="fieldOrigin(key)" :batch-count="batchCount" :mixed="mixedField(key)" :editable="doc.complete && option.complete && !busy && !stale"
            @change="setField(key, $event)" @reset="setField(key, undefined, 'reset')" @batch="setField(key, $event.value, 'set', true, $event.indices)"/>
          <div v-if="pageCount > 1" class="profile-pagination"><p>{{ P.page }} {{ page }} / {{ pageCount }}</p><div><button class="btn" :disabled="page <= 1" @click="changePage(-1)">{{ P.previous }}</button><button class="btn" :disabled="page >= pageCount" @click="changePage(1)">{{ P.next }}</button></div></div>
          <details v-if="Object.keys(doc.unknown || {}).length"><summary>{{ P.unknown }}</summary><pre>{{ json(doc.unknown) }}</pre></details>
          </details>
          <ProfileTransfer :instance-id="session.instanceId" :branch-id="current.id" :selected="scoped" :documents="documents" :disabled="busy || stale || scopedDirty || !scoped.length || editableScope.length !== scoped.length" @created="openTransferred"/>
        </template>
        <template v-if="tab === 'timeline'">
          <p v-if="!branches.length">{{ P.emptyHistory }}</p>
          <ul class="profile-timeline"><li v-for="b in branches" :key="b.id"><div><strong>{{ b.name }}</strong><small>{{ b.created }}</small></div><button class="btn" :disabled="busy" @click="run(() => openBranch(b.id))">{{ P.open }}</button></li></ul>
          <button v-if="historyCursor" class="btn" :disabled="busy" @click="run(() => refreshHistory(current?.id, true))">{{ P.loadMoreHistory }}</button>
          <template v-if="current"><label>{{ P.source }}<select v-model="sourceState" :disabled="busy"><option value="">{{ P.choose }}</option><optgroup v-for="b in branches" :key="b.id" :label="b.name"><option :value="b.state">{{ b.name }} · {{ P.state }}</option></optgroup><optgroup :label="P.savedStates"><option v-for="s in stateList" :key="s.id" :value="s.id">{{ s.note || s.created }}</option></optgroup><optgroup v-if="observations.length" :label="P.observedStates"><option v-for="s in observations" :key="s.id" :value="s.id">{{ s.note || s.created }}</option></optgroup></select></label>
          <div class="profile-toolbar"><button class="btn" :disabled="busy || stale || !sourceState || scopedDirty || !scoped.length" @click="compare('merge')">{{ P.mergePreview }}</button><button class="btn" :disabled="busy || stale || !sourceState || scopedDirty || !scoped.length" @click="compare('restore')">{{ P.restorePreview }}</button></div>
          <div class="profile-toolbar"><button class="btn" :disabled="busy || stale || !sourceState || scopedDirty || !scoped.length" @click="previewStateRestore">{{ P.wholeRestorePreview }}</button></div>
          <div class="profile-toolbar"><label>{{ P.branchName }}<input v-model="forkName" maxlength="120"></label><button class="btn" :disabled="busy || stale || !sourceState || !forkName.trim() || !scoped.length" @click="fork">{{ P.fork }}</button></div></template>
          <section v-if="stateRestore" class="profile-restore-review"><h3>{{ P.wholeRestorePreview }}</h3><p>{{ P.wholeRestoreHelp }}</p><div v-for="change in stateRestore.changes" :key="change.profile_id"><h4>{{ change.name }} · {{ change.action === 'remove' ? P.restoreRemoved : P.restorePresent }}</h4><details><summary>{{ P.diff }} ({{ restoreDetails(change).length }})</summary><div class="profile-restore-values"><div v-for="row in restoreDetails(change)" :key="row.key" class="profile-diff-row"><strong>{{ row.key }}</strong><span></span><pre>{{ row.before === undefined ? P.absent : json(row.before) }}</pre><pre>{{ row.after === undefined ? P.absent : json(row.after) }}</pre></div></div></details></div><p v-if="!stateRestore.changes?.length">{{ P.noChanges }}</p><button class="btn btn-primary" :disabled="busy || stale || !stateRestore.changes?.length" @click="applyStateRestore">{{ P.wholeRestoreConfirm }}</button></section>
          <div v-if="comparison"><p>{{ P.fields }}</p><template v-for="(rows, id) in comparison.profiles" :key="id"><h3>{{ documents[id]?.name }}</h3><div v-for="row in rows" :key="row.key" class="profile-diff-row"><label><input type="checkbox" :checked="mergeChoices[id + ':' + row.key] === 'source'" @change="mergeChoices[id + ':' + row.key] = $event.target.checked ? 'source' : 'target'"> {{ row.key }}</label><div><small>{{ P.before }}</small><pre>{{ row.before.present ? json(row.before.value) : P.absent }}</pre></div><div><small>{{ P.after }}</small><pre>{{ row.after.present ? json(row.after.value) : P.absent }}</pre></div><p v-if="row.conflict">{{ P.conflict }}</p></div></template><p v-if="!Object.values(comparison.profiles || {}).some(rows => rows.length)">{{ P.noChanges }}</p><button class="btn btn-primary" :disabled="busy || stale || !chosenMergeCount" @click="adopt">{{ P.applySelection }} ({{ chosenMergeCount }})</button></div>
        </template>
        <section v-if="plan" class="profile-publish-review"><details v-if="plan.profile_diffs?.length" open><summary>{{ P.publishChanges }}</summary><p>{{ P.publishChangesHelp }}</p><details v-for="profile in plan.profile_diffs" :key="profile.profile_id"><summary>{{ profile.name }} · {{ profile.fields.length }} {{ P.changedValues }}</summary><div v-if="profile.rename?.before !== profile.rename?.after" class="profile-diff-row"><strong>{{ P.name }}</strong><span></span><pre>{{ profile.rename.before }}</pre><pre>{{ profile.rename.after }}</pre></div><div v-if="profile.inherits?.before !== profile.inherits?.after" class="profile-diff-row"><strong>{{ P.parentProfile }}</strong><span></span><pre>{{ profile.inherits?.before || P.absent }}</pre><pre>{{ profile.inherits?.after || P.absent }}</pre></div><div class="profile-restore-values"><div v-for="field in profile.fields" :key="field.key" class="profile-diff-row"><strong>{{ field.key }}</strong><span></span><div><small>{{ P.before }}</small><pre>{{ field.before.present ? json(field.before.value) : P.absent }}</pre></div><div><small>{{ P.after }}</small><pre>{{ field.after.present ? json(field.after.value) : P.absent }}</pre></div></div></div></details></details><PlanView :plan="plan" :inst="inst" :busy="busy" @apply="applyPlan" @back="plan = null"/></section>
        <DoneView v-if="done?.warnings?.length" :warnings="done.warnings" :text="P.published" :inst="inst" @close="done = null"/>
        <p v-else-if="done" class="state-note" role="status"><span class="ch-on"><ui-icon name="check"/></span><strong>{{ P.published }}</strong></p>
      </div>
      <footer v-if="current" class="profile-editor-foot"><div v-if="progress" class="profile-progress" role="status" aria-live="polite"><span>{{ progressLabel }}<template v-if="progress.total != null && !progress.connection_lost"> · {{ progress.completed }} / {{ progress.total }}</template></span><progress v-if="busy" :aria-label="progressLabel" :max="progress.total > 0 ? progress.total : 1" :value="!progress.connection_lost && progress.total > 0 ? progress.completed : undefined"></progress></div><p v-if="error" class="profile-error profile-foot-error" role="alert">{{ error }}</p><p class="profile-foot-scope">{{ P.actionScope }}: {{ scoped.length }}<span v-if="dirty"> · {{ P.unsaved }}</span></p><button class="btn" :disabled="busy || stale || !scopedDirty || !editableScope.length" @click="run(save)">{{ P.save }}</button><label>{{ P.note }}<input v-model="note" maxlength="500"></label><button class="btn" :disabled="busy || stale || !editableScope.length" @click="checkpoint">{{ P.checkpoint }}</button><button class="btn btn-primary" :disabled="busy || stale || scopedDirty || !scoped.length || !catalog?.complete" @click="previewPublish">{{ plan ? P.refreshPreview : P.publish }}</button><button v-if="plan && !plan.blocked" class="btn btn-primary" :disabled="busy || stale || scopedDirty" @click="applyPlan">{{ P.confirmApply }}</button></footer>
    </section>
  </div>`,
};
