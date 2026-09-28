import { INSTANCES } from '../common.js';
import { api } from '../api.js';
import { T } from '../texts.js';
import { openProfileBranch } from './profile-session.js';
import DE from '../texts/workbench-de.js';
import EN from '../texts/workbench-en.js';

const { ref, reactive, computed, watch, nextTick } = Vue;
const W = T.locale.startsWith('en') ? EN : DE;
const drafts = reactive(new Map());
const MIME = 'application/x-orcaone-workbench';
const storageKey = id => 'orcaone.workbench.v1.' + id;
function readDraft(id) {
 try {
  const raw = window.localStorage?.getItem(storageKey(id));
  if (!raw || raw.length > 1000000) return null;
  const draft = JSON.parse(raw);
  return Array.isArray(draft.variants) && Array.isArray(draft.assignments) && typeof draft.group_name === 'string' ? draft : null;
 } catch { return null; }
}
watch(drafts, () => {
 for (const [id, draft] of drafts) {
  try { window.localStorage?.setItem(storageKey(id), JSON.stringify(draft)); } catch { /* In-memory draft remains available. */ }
 }
}, { deep: true, flush: 'sync' });
let unloadGuardInstalled = false;
function installUnloadGuard() {
 if (unloadGuardInstalled || typeof window === 'undefined') return;
 window.addEventListener('beforeunload', event => {
  if ([...drafts.values()].some(draft => draft.variants.length)) { event.preventDefault(); event.returnValue = ''; }
 });
 unloadGuardInstalled = true;
}
const token = () => Array.from(crypto.getRandomValues(new Uint32Array(4)), n => n.toString(16)).join('-');
export function workbenchDirty(id) { return !!drafts.get(id)?.variants.length; }
export function clearWorkbenchDraft(id) {
 drafts.delete(id);
 try { window.localStorage?.removeItem(storageKey(id)); } catch { /* Storage may be unavailable. */ }
}
const flatten = nodes => nodes.flatMap(n => [n, ...flatten(n.children || [])]);

const WorkbenchTree = {
 name: 'WorkbenchTree',
 props: ['nodes', 'selected', 'opened', 'side', 'editing', 'renameText'],
 emits: ['select', 'label-click', 'toggle', 'drag', 'drop-node', 'rename', 'context', 'rename-input', 'commit', 'cancel'],
 setup() { return { W }; },
 template: `<ul class="rel-tree wb-tree" :role="side === 'root' ? 'tree' : 'group'">
  <li v-for="node in nodes" :key="node.id">
   <div class="rel-row wb-row" :class="{'is-selected': selected.includes(node.id)}" role="treeitem" tabindex="0"
    :aria-selected="selected.includes(node.id)" :aria-expanded="node.children ? opened.includes(node.id) : undefined"
    :draggable="!node.category && !editing" @click="$emit('select', node, $event)" @keydown.space.prevent="$emit('select', node, $event)"
    @keydown.enter.prevent="$emit('select', node, $event)" @keydown.f2.prevent="$emit('rename', node)"
    @keydown.right.prevent="node.children && !opened.includes(node.id) && $emit('toggle', node.id)"
    @keydown.left.prevent="node.children && opened.includes(node.id) && $emit('toggle', node.id)"
    @contextmenu.prevent="$emit('context', node, $event)" @dragstart.stop="$emit('drag', node, $event)"
    @dragover.prevent.stop @drop.prevent.stop="$emit('drop-node', node, $event)">
    <button v-if="node.children" type="button" class="rel-toggle wb-expander" :aria-label="node.label" :aria-expanded="opened.includes(node.id)" @click.stop="$emit('toggle', node.id)"><ui-icon :name="opened.includes(node.id) ? 'chevronDown' : 'chevron'" :size="16"/></button>
    <nozzle-icon v-if="node.kind === 'machine'" :sizes="node.sizes || []" :height="22"/>
    <ui-icon v-else :name="node.kind === 'process' ? 'layers' : node.kind === 'filament' ? 'spool' : 'printer'" :size="18"/>
    <span v-if="node.kind === 'machine'" class="wb-nozzle-label">{{ W.nozzle + (node.sizes?.length ? ' ' + node.sizes.join(' / ') + ' mm' : '') }}</span>
    <input v-if="editing === node.id" class="wb-rename" :value="renameText" :aria-label="node.label" @input="$emit('rename-input', $event.target.value)" @click.stop @keydown.stop @keydown.enter.prevent="$emit('commit')" @keydown.esc.prevent="$emit('cancel')" @blur="$emit('commit')">
    <span v-else class="rel-name" @click.stop="$emit('label-click', node, $event)">{{ node.label }}{{ node.category ? ' (' + node.children.length + ')' : '' }}</span><small v-if="node.meta" class="rel-meta">{{ node.meta }}</small>
   </div>
   <workbench-tree v-if="node.children && opened.includes(node.id)" :nodes="node.children" :selected="selected" :opened="opened" side="group" :editing="editing" :rename-text="renameText"
    @select="(n,e) => $emit('select',n,e)" @label-click="(n,e) => $emit('label-click',n,e)" @toggle="id => $emit('toggle',id)" @drag="(n,e) => $emit('drag',n,e)" @drop-node="(n,e) => $emit('drop-node',n,e)"
    @rename="n => $emit('rename',n)" @context="(n,e) => $emit('context',n,e)" @rename-input="v => $emit('rename-input',v)" @commit="$emit('commit')" @cancel="$emit('cancel')"/>
  </li></ul>`,
};

export default {
 name: 'ProfileWorkbench', components: { WorkbenchTree }, props: { instId: { type: String, required: true } },
 setup(props, { emit }) {
  const inst = computed(() => INSTANCES.find(i => i.id === props.instId));
  const draft = computed(() => {
   if (!drafts.has(props.instId)) drafts.set(props.instId, readDraft(props.instId) || { group_name: W.target, target_model: W.target, variants: [], assignments: [] });
   return drafts.get(props.instId);
  });
  const sourceSelected = ref([]), targetSelected = ref([]), opened = ref(['target']), mode = ref('copy'), query = ref('');
  const editing = ref(''), renameText = ref(''), menu = ref(null), error = ref(''), busy = ref(false), review = ref(null), repairable = ref(false);
  const transferTarget = ref('');
  const dragToken = token();
  let anchor = '', editingNode = null, revision = 0, lastLabelClick = null;
  installUnloadGuard();
  const translateError = code => { if (code === 'slicer_running') return W.slicerRunning; const text = W.errors[code] || T.profileEditor?.errors?.[code] || T.printerMerge?.errors?.[code]; return typeof text === 'string' ? text : code; };
  const errorText = e => [translateError(e.code || e.message),
   e.data?.name, ...(e.data?.names || []), e.data?.schema_id, e.data?.key, ...(e.data?.issues || []).map(i => [i.key, i.message || translateError(i.code),
    i.expected ? W.expected + ': ' + i.expected : '', i.value !== undefined ? JSON.stringify(i.value) : '', i.origin].filter(Boolean).join(' · '))].filter(Boolean).join(' · ');
  const sources = computed(() => (inst.value?.models || []).map(m => ({
   id: 'model:' + m.model, kind: 'model', label: m.display_name || m.model,
   children: (m.printers || []).map(p => ({ id: 'machine:' + p.name, kind: 'machine', name: p.name, label: p.name,
    model: m.model, nozzle: p.nozzle || p.nozzle_diameter, sizes: (p.nozzle || p.nozzle_diameter || []).map(Number),
    children: ['process', 'filament'].map(kind => ({ id: p.name + ':' + kind, category: true, kind, label: kind === 'process' ? W.processes : W.filaments,
     children: (kind === 'process' ? (p.processes || []).map(name => (inst.value.processes || []).find(f => f.name === name) || { name }) : (inst.value.filaments || []).filter(f => f.printers?.[p.name]?.status === 'visible'))
      .map(f => ({ id: JSON.stringify([kind, p.name, f.name]), kind, name: f.name, label: f.name, from: p.name, vendor: f.origin_kind === 'vendor' || f.origin_kind === 'system' })),
    })),
   })),
  })));
  const filteredSources = computed(() => {
   const q = query.value.trim().toLowerCase();
   const filter = nodes => nodes.flatMap(n => {
    if (!q || n.label.toLowerCase().includes(q)) return [n];
    const children = filter(n.children || []); return children.length ? [{ ...n, children }] : [];
   }); return filter(sources.value);
  });
  function targetChildren(v, kind) {
   const assignments = draft.value.assignments.filter(a => a.kind === kind && a.targets.includes(v.key));
   const explicit = assignments.map(a => ({ id: v.key + ':' + a.localKey, kind, label: a.name || a.source_name,
    assignment: a.localKey, variant: v.key, meta: W[a.action] || W.rename }));
   if (v.mode !== 'move') return explicit;
   const source = flatten(sources.value).find(n => n.kind === 'machine' && n.name === v.source_name);
   const retained = (source?.children.find(n => n.kind === kind)?.children || []).flatMap(n => {
    const changed = draft.value.assignments.find(a => a.kind === kind && a.source_name === n.name && a.action !== 'copy');
    if (assignments.some(a => a.source_name === n.name && a.action !== 'copy')) return [];
    if (changed?.action === 'move' && changed.from.includes(v.source_name)) return [];
    return [{ ...n, id: v.key + ':baseline:' + n.id, variant: v.key, baseline: true,
     label: changed?.name || n.name, meta: W.unchanged }];
   });
   return [...retained, ...explicit];
  }
  const targets = computed(() => [{ id: 'target', kind: 'model', label: draft.value.group_name,
   children: draft.value.variants.map(v => ({ id: v.key, kind: 'machine', label: v.name, variant: v.key,
    sizes: v.nozzle_diameter.map(Number), meta: W[v.mode],
    children: ['process', 'filament'].map(kind => ({ id: v.key + ':' + kind, kind, category: true, variant: v.key, label: kind === 'process' ? W.processes : W.filaments,
     children: targetChildren(v, kind),
    })),
   })),
  }]);
  const selectedVariant = computed(() => {
   const node = flatten(targets.value).find(n => targetSelected.value.includes(n.id));
   return draft.value.variants.find(v => v.key === node?.variant);
  });
  const selectedTarget = computed(() => flatten(targets.value).find(n => targetSelected.value.includes(n.id)));
  const transferTargets = computed(() => draft.value.variants.filter(v => v.key !== selectedVariant.value?.key));
  watch(() => selectedVariant.value?.key, () => { transferTarget.value = ''; });
  const canNewNozzle = computed(() => sourceSelected.value.length === 1 && flatten(sources.value).find(n => n.id === sourceSelected.value[0])?.kind === 'machine');
  const blocked = computed(() => (review.value?.issues || []).some(i => i.severity !== 'warning'));
  watch(() => JSON.stringify(draft.value), () => { review.value = null; revision++; });
  watch(() => props.instId, () => { sourceSelected.value = []; targetSelected.value = []; menu.value = null; review.value = null;
   opened.value = ['target', ...(sources.value[0] ? [sources.value[0].id] : [])];
  }, { immediate: true });
  watch(query, () => { if (query.value) opened.value = [...new Set([...opened.value, ...flatten(filteredSources.value).filter(n => n.children).map(n => n.id)])]; });
  function toggle(id) { lastLabelClick = null; opened.value = opened.value.includes(id) ? opened.value.filter(x => x !== id) : [...opened.value, id]; }
  function select(node, event, side) {
   lastLabelClick = null;
   menu.value = null; const selection = side === 'source' ? sourceSelected : targetSelected;
   const rows = flatten(side === 'source' ? filteredSources.value : targets.value).filter(n => !n.category);
   if (node.category) { toggle(node.id); return; }
   if (event.shiftKey && side === 'source' && anchor) {
    const a = rows.findIndex(n => n.id === anchor), b = rows.findIndex(n => n.id === node.id);
    selection.value = rows.slice(Math.min(a, b), Math.max(a, b) + 1).map(n => n.id);
   } else if ((event.ctrlKey || event.metaKey) && side === 'source') selection.value = selection.value.includes(node.id) ? selection.value.filter(x => x !== node.id) : [...selection.value, node.id];
   else selection.value = [node.id];
   anchor = node.id;
  }
  const selectSource = (n, e) => select(n, e, 'source');
  const selectTarget = (n, e) => select(n, e, 'target');
  function labelClick(node, event, side) {
   const previous = lastLabelClick, selected = targetSelected.value.includes(node.id);
   select(node, event, side);
   if (side !== 'target' || node.category || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
   const elapsed = event.timeStamp - (previous?.time || 0);
   if (selected && previous?.id === node.id && elapsed >= 300 && elapsed <= 1500 && event.detail !== 2) {
    beginRename(node); return;
   }
   lastLabelClick = { id: node.id, time: event.timeStamp };
  }
  function uniqueName(name) {
   const used = new Set([...flatten(sources.value).map(n => n.name), ...draft.value.variants.map(v => v.name), ...draft.value.assignments.map(a => a.name)]);
   let result = name + ' ' + W.copySuffix, suffix = 2;
   while (used.has(result)) result = name + ' ' + W.copySuffix + ' ' + suffix++;
   return result;
  }
  async function addNodes(nodes, target, newNozzle = false, selectionMode = mode.value) {
   error.value = ''; if (busy.value) return;
   const expanded = nodes.flatMap(n => n.kind === 'model' ? n.children : [n]).filter(n => !n.category);
   for (const n of [...new Map(expanded.map(n => [n.id, n])).values()]) {
    if (n.kind === 'machine') {
     if (selectionMode === 'share' && !newNozzle) { error.value = W.shareMachine; continue; }
     let nozzle = n.nozzle;
     if (!Array.isArray(nozzle) || !nozzle.length) {
      // Identity creation on the server must stay sequential.
      busy.value = true;
      try { const d = await api.profileEditor(props.instId, '/document?kind=machine&name=' + encodeURIComponent(n.name)); nozzle = d.effective?.nozzle_diameter || d.document?.effective?.nozzle_diameter; }
      catch (e) { error.value = errorText(e); } finally { busy.value = false; }
     }
     if (!Array.isArray(nozzle) || !nozzle.length) { error.value = W.missingNozzle; continue; }
     const action = newNozzle ? 'copy' : selectionMode;
     if (action === 'move' && draft.value.variants.some(v => v.source_name === n.name && v.mode === 'move')) continue;
     const key = 'variant-' + token();
     draft.value.variants.push({ key, source_name: n.name, name: action === 'copy' ? uniqueName(n.name) : n.name, mode: action, nozzle_diameter: nozzle.map(String) });
     if (action === 'copy') {
      const source = flatten(sources.value).find(source => source.kind === 'machine' && source.name === n.name);
      await addNodes((source?.children || []).flatMap(category => category.children || []), { variant: key }, false, 'copy');
     }
     opened.value.push(key); targetSelected.value = [key];
    } else {
     if (n.vendor && selectionMode !== 'copy') { error.value = W.vendorCopy; continue; }
     const key = target?.variant || selectedVariant.value?.key;
     if (!key) { error.value = W.chooseTarget; continue; }
     const existing = draft.value.assignments.find(a => a.source_name === n.name && a.kind === n.kind && (selectionMode === 'copy' ? a.action === 'copy' : a.action !== 'copy'));
     if (existing) {
      if (selectionMode === 'move') { existing.action = 'move'; existing.targets = existing.targets.filter(k => !draft.value.variants.some(v => v.key === k && v.mode === 'move' && v.source_name === n.from)); }
      if (!existing.targets.includes(key)) existing.targets.push(key); if (!existing.from.includes(n.from)) existing.from.push(n.from);
     }
     else draft.value.assignments.push({ localKey: 'item-' + token(), kind: n.kind, source_name: n.name, name: selectionMode === 'copy' ? uniqueName(n.name) : n.name, action: selectionMode, targets: [key], from: [n.from] });
    }
   }
  }
  const addSelected = () => addNodes(flatten(sources.value).filter(n => sourceSelected.value.includes(n.id)));
  const newNozzle = () => canNewNozzle.value && addNodes(flatten(sources.value).filter(n => sourceSelected.value.includes(n.id)), null, true);
  function drag(node, event, side) {
   lastLabelClick = null;
   if (busy.value || node.category || (side === 'target' && !node.assignment && !node.baseline)) { event.preventDefault(); return; }
   if (side === 'target') {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData(MIME, JSON.stringify({ token: dragToken, instance: props.instId, side, id: node.id })); return;
   }
   if (!sourceSelected.value.includes(node.id)) selectSource(node, {});
   event.dataTransfer.effectAllowed = 'copyMove';
   event.dataTransfer.setData(MIME, JSON.stringify({ token: dragToken, instance: props.instId, ids: sourceSelected.value }));
  }
  async function drop(node, event) {
   try {
    if (!Array.from(event.dataTransfer.types).includes(MIME)) return;
    const data = JSON.parse(event.dataTransfer.getData(MIME));
    if (busy.value || data.token !== dragToken || data.instance !== props.instId) return;
    if (data.side === 'target') {
     const origin = flatten(targets.value).find(n => n.id === data.id);
     if ((!origin?.assignment && !origin?.baseline) || !node?.variant || origin.variant === node.variant) return;
     if (origin.baseline) { await addNodes([origin], node); opened.value.push(node.variant); return; }
     const a = draft.value.assignments.find(a => a.localKey === origin.assignment);
     if (mode.value === 'copy') draft.value.assignments.push({ ...a, localKey: 'item-' + token(), action: 'copy', name: uniqueName(a.name), from: [...a.from], targets: [node.variant] });
     else a.targets = [...new Set((mode.value === 'move' ? a.targets.filter(k => k !== origin.variant) : a.targets).concat(node.variant))];
     opened.value.push(node.variant); return;
    }
    if (!Array.isArray(data.ids)) return;
    const all = flatten(sources.value), nodes = data.ids.map(id => all.find(n => n.id === id));
    if (nodes.some(n => !n || n.category)) return;
    await addNodes(nodes, node);
   } catch { /* Ignore foreign or malformed drag payloads. */ }
  }
  function beginRename(node) {
   menu.value = null; if (busy.value || !node || node.category || !flatten(targets.value).some(n => n.id === node.id)) return;
   editingNode = node; editing.value = node.id; renameText.value = node.label;
   if (node.baseline && node.vendor) { renameText.value = uniqueName(node.name); error.value = W.vendorCopy; }
   nextTick(() => { const input = document.querySelector('.wb-rename'); input?.focus(); input?.select(); });
  }
  function commitRename() {
   if (!editingNode) return;
   const name = renameText.value.trim(); if (!name) { error.value = W.invalidName; return; }
   if (editingNode.id === 'target') { draft.value.group_name = name; draft.value.target_model = name; }
   else if (editingNode.baseline) {
    if (name !== editingNode.label) {
     const existing = draft.value.assignments.find(a => a.kind === editingNode.kind && a.source_name === editingNode.name && a.action !== 'copy');
     if (existing && !editingNode.vendor) { existing.name = name; if (!existing.targets.includes(editingNode.variant)) existing.targets.push(editingNode.variant); }
     else draft.value.assignments.push({ localKey: 'item-' + token(), kind: editingNode.kind, source_name: editingNode.name,
      name, action: editingNode.vendor ? 'copy' : 'share', targets: [editingNode.variant], from: [editingNode.from] });
    }
   } else if (editingNode.assignment) {
    const a = draft.value.assignments.find(a => a.localKey === editingNode.assignment); a.name = name;
   } else draft.value.variants.find(v => v.key === editingNode.variant).name = name;
   cancelRename();
  }
  function cancelRename() { editing.value = ''; editingNode = null; }
  function context(node, event, side) { select(node, {}, side); menu.value = { node, side }; }
  function deleteSelection(event) {
   if (event.target.closest('input, textarea, select, [contenteditable]') || editing.value || busy.value || !targetSelected.value.length) return;
   event.preventDefault(); event.stopPropagation(); removeSelected();
  }
  function removeVariantKeepProfiles() {
   if (busy.value) return;
   const source = selectedVariant.value;
   const destination = draft.value.variants.find(v => v.key === transferTarget.value);
   if (!source || selectedTarget.value?.kind !== 'machine' || !destination || source.key === destination.key) { error.value = W.chooseTransferTarget; return; }
   const retained = ['process', 'filament'].flatMap(kind => targetChildren(source, kind).filter(n => n.baseline));
   for (const assignment of draft.value.assignments) {
    if (assignment.targets.includes(source.key)) assignment.targets = [...new Set(assignment.targets.map(key => key === source.key ? destination.key : key))];
   }
   for (const node of retained) {
    const existing = draft.value.assignments.find(a => a.kind === node.kind && a.source_name === node.name && a.action === 'copy');
    if (existing) {
     if (!existing.targets.includes(destination.key)) existing.targets.push(destination.key);
     if (!existing.from.includes(source.source_name)) existing.from.push(source.source_name);
    } else draft.value.assignments.push({ localKey: 'item-' + token(), kind: node.kind, source_name: node.name,
     name: uniqueName(node.label || node.name), action: 'copy', targets: [destination.key], from: [source.source_name] });
   }
   draft.value.variants = draft.value.variants.filter(v => v.key !== source.key);
   opened.value = opened.value.filter(id => id !== source.key && !id.startsWith(source.key + ':') && ![destination.key + ':process', destination.key + ':filament'].includes(id));
   targetSelected.value = [destination.key]; transferTarget.value = ''; menu.value = null; error.value = '';
  }
  function removeSelected() {
   if (busy.value) return;
   for (const node of flatten(targets.value).filter(n => targetSelected.value.includes(n.id))) {
    if (node.baseline) continue;
    if (node.assignment) { const a = draft.value.assignments.find(a => a.localKey === node.assignment); a.targets = a.targets.filter(k => k !== node.variant); }
    else if (node.variant && !node.category) { draft.value.variants = draft.value.variants.filter(v => v.key !== node.variant); for (const a of draft.value.assignments) a.targets = a.targets.filter(k => k !== node.variant); }
   }
   draft.value.assignments = draft.value.assignments.filter(a => a.targets.length); targetSelected.value = []; menu.value = null;
  }
  function setDiameter(event) {
   const values = event.target.value.split(',').map(v => v.trim());
   if (values.some(v => !/^(?:\d+\.?\d*|\.\d+)$/.test(v) || Number(v) <= 0)) { error.value = W.invalidDiameter; return; }
   selectedVariant.value.nozzle_diameter = values; error.value = '';
  }
  async function preview(repair = false) {
   if (busy.value || !draft.value.variants.length) return;
   await nextTick(); const currentRevision = revision; busy.value = true; error.value = '';
   const body = JSON.parse(JSON.stringify(draft.value)); body.assignments.forEach(a => delete a.localKey);
   body.repair_compatibility = repair === true || draft.value.repair_compatibility === true; repairable.value = false;
   try { const result = await api.profileEditor(props.instId, '/composer-preview', body); if (revision === currentRevision) review.value = result; }
   catch (e) { error.value = errorText(e); repairable.value = e.data?.repairable === true; }
   finally { busy.value = false; }
  }
  async function createBranch() {
   if (!review.value || busy.value || blocked.value) return; busy.value = true; error.value = '';
   try { const result = await api.profileEditor(props.instId, '/composer-branch', { preview_id: review.value.preview_id });
    if (result.created && result.branch?.id) { clearWorkbenchDraft(props.instId); openProfileBranch(props.instId, result.branch.id); }
    else error.value = (result.issues || []).map(i => i.message || i.code).join(' · ');
   } catch (e) { error.value = errorText(e); } finally { busy.value = false; }
  }
  async function applyRepair() {
   if (!review.value?.repairs?.length || busy.value || blocked.value) return;
   const checked = review.value;
   draft.value.repair_compatibility = true;
   await nextTick();
   review.value = checked; error.value = '';
  }
  function reset() { if (busy.value) return; clearWorkbenchDraft(props.instId); review.value = null; targetSelected.value = []; }
  const valueText = value => Array.isArray(value) ? value.join(', ') : value == null ? '—' : String(value);
  const describe = item => typeof item === 'string' ? item : [item.name,
   item.code ? (item.message || translateError(item.code)) : null,
   item.key ? (T.profileEditor?.fields?.[item.key] || item.key) : null,
   'before' in item || 'after' in item ? valueText(item.before) + ' → ' + valueText(item.after) : null].filter(Boolean).join(' · ');
  return { W, draft, sources, filteredSources, targets, sourceSelected, targetSelected, selectedVariant, selectedTarget, transferTarget, transferTargets, opened, mode, query, labelClick,
   editing, renameText, menu, error, busy, review, repairable, blocked, canNewNozzle, toggle, selectSource, selectTarget, addSelected, newNozzle,
   drag, drop, beginRename, commitRename, cancelRename, context, removeSelected, removeVariantKeepProfiles, deleteSelection, setDiameter, preview, createBranch, applyRepair, reset, describe };
 },
 template: `<div class="page wb-page" @keydown.esc="menu = null">
  <div class="page-head"><h1 id="page-title" tabindex="-1">{{ W.title }}</h1><span v-if="draft.variants.length" class="tag">{{ W.dirty }}</span></div>
  <p class="quiet-note">{{ W.lead }}</p>
  <div class="wb-toolbar"><label>{{ W.mode }} <select v-model="mode" :disabled="busy"><option value="copy">{{ W.copy }}</option><option value="move">{{ W.move }}</option><option value="share">{{ W.share }}</option></select></label>
   <button class="btn" :disabled="busy || !sourceSelected.length" @click="addSelected">{{ W.add }}</button>
   <button class="btn" :disabled="busy || !canNewNozzle" :title="W.newNozzleHint" @click="newNozzle">{{ W.newNozzle }}</button>
  </div><p class="wb-hint">{{ W.modeHint }}</p>
  <div class="wb-columns" :aria-busy="busy">
   <section class="wb-pane" :aria-label="W.sources"><div class="wb-pane-head"><h2>{{ W.sources }}</h2><input v-model="query" type="search" :placeholder="W.search" :aria-label="W.search"></div>
    <workbench-tree :nodes="filteredSources" :selected="sourceSelected" :opened="opened" side="root" @select="selectSource" @label-click="(n,e) => labelClick(n,e,'source')" @toggle="toggle" @drag="(n,e) => drag(n,e,'source')" @context="(n,e) => context(n,e,'source')"/>
    <p v-if="!filteredSources.length" class="empty">{{ W.noResults }}</p>
   </section>
   <section class="wb-pane wb-target" :aria-label="W.target" @keydown.delete="deleteSelection" @dragover.prevent @drop.prevent="drop(null,$event)"><div class="wb-pane-head"><h2>{{ W.target }}</h2>
    <button class="link" :disabled="busy || !targetSelected.length" @click="beginRename(selectedTarget)">{{ W.rename }}</button></div>
    <workbench-tree :nodes="targets" :selected="targetSelected" :opened="opened" side="root" :editing="editing" :rename-text="renameText" @select="selectTarget" @label-click="(n,e) => labelClick(n,e,'target')" @toggle="toggle" @drag="(n,e) => drag(n,e,'target')" @drop-node="drop" @rename="beginRename" @context="(n,e) => context(n,e,'target')" @rename-input="v => renameText = v" @commit="commitRename" @cancel="cancelRename"/>
    <p v-if="!draft.variants.length" class="empty wb-empty">{{ W.empty }}</p>
    <div v-if="selectedVariant" class="wb-nozzle"><label>{{ W.diameter }}<input :key="selectedVariant.key" :value="selectedVariant.nozzle_diameter.join(', ')" :disabled="busy" @change="setDiameter"></label><button class="link" :disabled="busy || selectedTarget?.baseline" @click="removeSelected">{{ W.remove }}</button></div>
    <div v-if="selectedVariant && selectedTarget?.kind === 'machine' && transferTargets.length" class="wb-nozzle"><label>{{ W.transferProfilesTo }}<select v-model="transferTarget" :disabled="busy"><option value="">{{ W.chooseTransferTarget }}</option><option v-for="variant in transferTargets" :key="variant.key" :value="variant.key">{{ variant.name }}</option></select></label><button class="btn" :disabled="busy || !transferTarget" @click="removeVariantKeepProfiles">{{ W.removeKeepProfiles }}</button></div>
   </section>
  </div>
  <div v-if="menu" class="wb-context" role="toolbar"><strong>{{ menu.node.label }}</strong><template v-if="menu.side === 'target'"><button class="btn" @click="beginRename(menu.node)">{{ W.rename }}</button><button class="btn" :disabled="menu.node.baseline" @click="removeSelected">{{ W.remove }}</button></template><button v-else class="btn" @click="addSelected(); menu = null">{{ W.add }}</button><button class="link" @click="menu = null">{{ W.cancel }}</button></div>
  <div class="wb-footer"><span class="wb-hint">{{ W.saved }}</span><button class="link" :disabled="busy || !draft.variants.length" @click="reset">{{ W.reset }}</button><button class="btn primary" :disabled="busy || !draft.variants.length" @click="preview">{{ busy ? W.busy : W.preview }}</button></div>
  <p v-if="error && !review" role="alert" class="wb-error">{{ error }}</p>
  <div v-if="repairable"><p class="wb-hint">{{ W.repairHelp }}</p><button class="btn" :disabled="busy" @click="preview(true)">{{ W.repair }}</button></div>
  <section v-if="review" class="wb-review" aria-live="polite"><h2>{{ W.review }}</h2><p>{{ W.renamed }}</p>
   <ul v-if="review.issues?.length"><li v-for="(issue,i) in review.issues" :key="i">{{ describe(issue) }}</li></ul><p v-if="blocked" role="alert">{{ W.blocked }}</p>
   <h3>{{ W.affected }}</h3><ul><li v-for="(doc,i) in review.documents" :key="i">{{ doc.name || doc.id }} <small>{{ doc.kind }}</small></li></ul>
   <ul v-if="review.impacts?.length"><li v-for="(impact,i) in review.impacts" :key="i">{{ describe(impact) }}</li></ul><p v-else>{{ W.nothing }}</p>
   <p v-if="draft.repair_compatibility" role="status">{{ W.repairSaved }}</p>
   <p v-if="error" role="alert" class="wb-error">{{ error }}</p>
   <template v-if="review.repairs?.length && !draft.repair_compatibility"><p>{{ W.repairOnly }}</p><ul><li v-for="item in review.repairs" :key="item.kind + item.name">{{ item.name }}</li></ul><button class="btn primary" :disabled="busy || blocked" @click="applyRepair">{{ W.applyRepair }}</button></template>
   <button v-else class="btn primary" :disabled="busy || blocked" @click="createBranch">{{ W.merge }}</button>
  </section>
 </div>`,
};
