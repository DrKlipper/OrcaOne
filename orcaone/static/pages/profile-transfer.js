import { api } from "../api.js";
import { INSTANCES } from "../common.js";
import { T } from "../texts.js";

export default {
  props: { instanceId: String, branchId: String, selected: Array, documents: Object, disabled: Boolean },
  emits: ["created"],
  setup(props, { emit }) {
    const P = T.profileTransfer;
    const target = Vue.ref(''), names = Vue.ref({}), note = Vue.ref(''), report = Vue.ref(null);
    const accepted = Vue.ref({}), busy = Vue.ref(false), error = Vue.ref(''), created = Vue.ref(null);
    const targets = Vue.computed(() => INSTANCES.filter(i => i.id !== props.instanceId));
    const ready = Vue.computed(() => report.value && Object.entries(report.value.profiles).every(([id, value]) =>
      !value.issues.length && value.losses.every(loss => accepted.value[id + ':' + loss.id])));
    Vue.watch(() => [target.value, props.branchId, props.selected, props.documents, names.value], () => {
      report.value = null; accepted.value = {}; created.value = null;
    }, { deep: true });
    async function preview() {
      busy.value = true; error.value = '';
      try {
        report.value = await api.profileEditor(target.value, '/conversion-preview', {
          source_instance_id: props.instanceId, source_branch_id: props.branchId,
          selected: props.selected, names: names.value });
        accepted.value = {};
      } catch (e) { error.value = P.failed + ': ' + e.code; }
      finally { busy.value = false; }
    }
    async function confirm() {
      busy.value = true; error.value = '';
      try {
        const confirmed = Object.fromEntries(Object.entries(report.value.profiles).map(([id, value]) =>
          [id, value.losses.filter(loss => accepted.value[id + ':' + loss.id]).map(loss => loss.id)]));
        created.value = (await api.profileEditor(target.value, '/conversion-branch', {
          preview_id: report.value.id, name: note.value, confirmed_losses: confirmed })).branch;
      } catch (e) { error.value = P.failed + ': ' + e.code; }
      finally { busy.value = false; }
    }
    return { P, target, targets, names, note, report, accepted, busy, error, created, ready, preview, confirm,
      json: value => JSON.stringify(value), open: () => emit('created', { instanceId: target.value, branchId: created.value.id }) };
  },
  template: `<details class="profile-transfer"><summary>{{ P.title }}</summary><p>{{ P.local }}</p>
    <p v-if="!targets.length">{{ P.none }}</p>
    <template v-else><label>{{ P.target }}<select v-model="target" :disabled="busy || disabled"><option value="">{{ P.choose }}</option><option v-for="i in targets" :key="i.id" :value="i.id">{{ i.slicer }} {{ i.version }}</option></select></label>
      <div class="profile-toolbar"><label v-for="id in selected" :key="id">{{ documents[id]?.name }} · {{ P.name }}<input v-model="names[id]" maxlength="120" :disabled="busy || disabled"></label></div>
      <button class="btn" :disabled="busy || disabled || !target || !selected.length || selected.some(id => !names[id]?.trim())" @click="preview">{{ P.preview }}</button>
      <p v-if="busy" role="status">{{ P.loading }}</p><p v-if="error" role="alert">{{ error }}</p>
      <template v-if="report"><h3>{{ P.losses }}</h3><section v-for="(value, id) in report.profiles" :key="id"><h4>{{ value.document.name }}</h4>
        <p v-if="value.issues.length">{{ P.issues }}: {{ value.issues.map(i => i.key + ': ' + i.code).join(', ') }}</p>
        <label v-for="loss in value.losses" :key="loss.id" class="profile-loss"><input type="checkbox" v-model="accepted[id + ':' + loss.id]" :disabled="busy || !!created"><span>{{ loss.key }} — {{ P.codes[loss.code] || loss.code }}<pre v-if="!loss.redacted">{{ json(loss.before) }} → {{ json(loss.after) }}</pre><small v-else>{{ P.redacted }}</small></span></label>
      </section><label>{{ P.note }}<input v-model="note" maxlength="120" :disabled="busy || !!created"></label>
      <button v-if="!created" class="btn" :disabled="busy || !ready || !note.trim()" @click="confirm">{{ P.confirm }}</button><button v-else class="btn" @click="open">{{ P.open }}</button></template>
    </template></details>`,
};
