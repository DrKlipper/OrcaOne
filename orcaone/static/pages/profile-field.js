import { T } from "../texts.js";

export default {
  props: { fieldKey: String, option: Object, value: [String, Array], origin: Object, profileId: String, editable: Boolean, batchCount: Number, mixed: Boolean },
  emits: ["change", "reset", "batch"],
  setup(props, { emit }) {
    const P = T.profileEditor;
    const selectedIndices = Vue.ref([]);
    const vector = Vue.computed(() => Array.isArray(props.value));
    const values = Vue.computed(() => vector.value ? props.value : [props.value ?? ""]);
    const boolean = Vue.computed(() => ["coBool", "coBools"].includes(props.option.type));
    const enumeration = Vue.computed(() => ["coEnum", "coEnums"].includes(props.option.type));
    const grouped = Vue.computed(() => props.option.type === "coPointsGroups");
    const points = Vue.computed(() => grouped.value || ["coPoint", "coPoints", "coPoint3"].includes(props.option.type));
    const coordinates = Vue.computed(() => props.option.type === "coPoint3" ? ["X", "Y", "Z"] : ["X", "Y"]);
    const multiline = Vue.computed(() => props.fieldKey.includes("gcode") || values.value.some(v => typeof v === "string" && v.includes("\n")));
    const originName = Vue.computed(() => props.origin?.kind === "default" ? P.default :
      props.origin?.profile_id === props.profileId ? P.own : props.origin?.kind === "profile" ? P.inherited : P.own);
    const axisName = Vue.computed(() => ({ extruder: P.extruder, filament: P.filament, flow: P.flowVariant, points: P.point })[props.option.dimension] || P.head);
    const resizable = Vue.computed(() => grouped.value || ["list", "points"].includes(props.option.dimension));
    function change(index, value) {
      const next = [...values.value];
      next[index] = value;
      emit("change", vector.value ? next : value);
    }
    function groupPoints(item) {
      if (!grouped.value) return [String(item ?? "")];
      return item ? String(item).split(",") : [];
    }
    function pointParts(point) {
      return String(point ?? "").split(props.option.type === "coPoint" || props.option.type === "coPoint3" ? /[,x]/ : "x");
    }
    function leaf(index, inner) { return inner < 0 ? values.value[index] : values.value[index][inner]; }
    function setGroup(index, inner, next) {
      if (inner < 0) change(index, next.join(","));
      else { const nextGroup = [...values.value[index]]; nextGroup[inner] = next.join(","); change(index, nextGroup); }
    }
    function coordinate(index, inner, pointIndex, axis, value) {
      const group = [...groupPoints(leaf(index, inner))], parts = pointParts(group[pointIndex]);
      parts[axis] = value;
      group[pointIndex] = coordinates.value.map((_, i) => parts[i] ?? "").join(!grouped.value && !vector.value ? "," : "x");
      if (grouped.value) setGroup(index, inner, group); else change(index, group[pointIndex]);
    }
    function addPoint(index, inner) { setGroup(index, inner, [...groupPoints(leaf(index, inner)), "0x0"]); }
    function removePoint(index, inner, pointIndex) { setGroup(index, inner, groupPoints(leaf(index, inner)).filter((_, i) => i !== pointIndex)); }
    function addGroup(index) { change(index, [...values.value[index], "0x0"]); }
    function removeGroup(index, inner) { change(index, values.value[index].filter((_, i) => i !== inner)); }
    function addValue() { emit("change", [...values.value, grouped.value ? values.value.some(Array.isArray) ? ["0x0"] : "0x0" : points.value ? "0x0" : ""]); }
    function batch() {
      const indices = vector.value ? [...selectedIndices.value].sort((a, b) => a - b) : null;
      emit('batch', { indices, value: indices ? indices.map(index => Array.isArray(values.value[index]) ? [...values.value[index]] : values.value[index]) : props.value });
    }
    Vue.watch(() => values.value.length, length => { selectedIndices.value = selectedIndices.value.filter(index => index < length); });
    return { P, vector, values, boolean, enumeration, multiline, change, grouped, points, coordinates,
      originName, axisName, resizable, groupPoints, pointParts, coordinate, addPoint, removePoint, addGroup, removeGroup, addValue, selectedIndices, batch };
  },
  template: `
    <div class="profile-field">
      <div class="profile-field-title"><strong>{{ option.label || fieldKey.replaceAll('_', ' ') }}</strong>
        <code>{{ fieldKey }}</code>
        <small>{{ originName }}<span v-if="option.unit"> · {{ option.unit }}</span></small>
        <small v-if="mixed" class="profile-mixed">{{ P.mixedValues }}</small>
      </div>
      <div class="profile-field-values">
        <div v-for="(item, index) in values" :key="index" class="profile-value">
          <span v-if="vector" class="profile-axis">{{ grouped ? Array.isArray(item) ? P.collection : P.group : axisName }} {{ index + 1 }}</span>
          <label v-if="vector && editable && batchCount" class="profile-index-choice"><input type="checkbox" v-model="selectedIndices" :value="index">{{ P.batchIndex }} {{ index + 1 }}</label>
          <template v-if="points">
            <div v-for="(leaf, inner) in grouped && Array.isArray(item) ? item : [item]" :key="inner" class="profile-point-group">
            <span v-if="Array.isArray(item)" class="profile-axis">{{ P.group }} {{ inner + 1 }}</span>
            <div v-for="(point, pointIndex) in groupPoints(leaf)" :key="pointIndex" class="profile-point">
              <label v-for="(axis, axisIndex) in coordinates" :key="axis">{{ axis }}
                <input inputmode="decimal" :aria-label="fieldKey + ' ' + (index + 1) + ' ' + (inner + 1) + ' ' + (pointIndex + 1) + ' ' + axis" :value="pointParts(point)[axisIndex] ?? ''" :disabled="!editable" @input="coordinate(index, Array.isArray(item) ? inner : -1, pointIndex, axisIndex, $event.target.value)">
              </label>
              <button v-if="grouped && editable" class="btn" type="button" :disabled="groupPoints(leaf).length < 2" :aria-label="P.removePoint + ' ' + (pointIndex + 1)" @click="removePoint(index, Array.isArray(item) ? inner : -1, pointIndex)">{{ P.removePoint }}</button>
            </div>
            <div v-if="grouped && editable" class="profile-inline-actions"><button class="btn" type="button" @click="addPoint(index, Array.isArray(item) ? inner : -1)">{{ P.addPoint }}</button><button v-if="Array.isArray(item)" class="btn" type="button" @click="removeGroup(index, inner)">{{ P.removeGroup }}</button></div>
            </div>
            <button v-if="grouped && Array.isArray(item) && editable" class="btn" type="button" @click="addGroup(index)">{{ P.addGroup }}</button>
          </template>
          <select v-else-if="boolean" :aria-label="fieldKey + ' ' + (index + 1)" :value="item" :disabled="!editable" @change="change(index, $event.target.value)">
            <option value="0">{{ P.off }}</option><option value="1">{{ P.on }}</option><option v-if="option.nullable" value="nil">{{ P.nil }}</option>
          </select>
          <select v-else-if="enumeration" :aria-label="fieldKey + ' ' + (index + 1)" :value="item" :disabled="!editable" @change="change(index, $event.target.value)">
            <option v-if="!option.enums.includes(item) && item !== 'nil'" :value="item">{{ item }}</option>
            <option v-for="entry in option.enums" :key="entry" :value="entry">{{ entry }}</option><option v-if="option.nullable" value="nil">{{ P.nil }}</option>
          </select>
          <textarea v-else-if="multiline" :aria-label="fieldKey + ' ' + (index + 1)" :value="item" :disabled="!editable" rows="5" spellcheck="false" @input="change(index, $event.target.value)"></textarea>
          <input v-else :aria-label="fieldKey + ' ' + (index + 1)" :value="item" :disabled="!editable" spellcheck="false" @input="change(index, $event.target.value)">
        </div>
        <p v-if="vector && !values.length" class="profile-muted">{{ P.emptyValues }}</p>
        <div v-if="vector && resizable && editable" class="profile-inline-actions"><button type="button" class="btn" @click="addValue">{{ grouped ? P.addGroup : P.add }}</button>
          <button v-if="values.length" type="button" class="btn" @click="$emit('change', values.slice(0, -1))">{{ grouped ? P.removeGroup : P.remove }}</button></div>
      </div>
      <div class="profile-field-actions" v-if="editable">
        <button type="button" class="btn" @click="$emit('reset')">{{ P.reset }}</button>
        <button type="button" class="btn" :disabled="!batchCount || vector && !selectedIndices.length" @click="batch">{{ vector ? P.batchSelectedIndices : P.batch }} ({{ batchCount || 0 }})</button>
      </div>
    </div>`,
};
