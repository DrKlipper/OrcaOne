// Page "Logs" (under "Technik"): what the chosen installation's slicer wrote at each start, from
// <data dir>/log/. Pick a start, show everything or only warnings and errors, search. OrcaOne
// filters on the server (orcaone/logs.py): OrcaSlicer's files reach 10 MB, the page gets the last
// entries only. Only to look at.
import { INSTANCES, fmtSize, whenText } from "../common.js";
import { T } from "../texts.js";
import { api } from "../api.js";
import { RegexHelp } from "./regex-help.js";

const { ref, computed, watch, nextTick, onMounted } = Vue;
const L = T.logs;
const SHOWS = ["all", "problems", "errors"];

export default {
  name: "LogsPage",
  components: { RegexHelp },
  props: { instId: { type: String, required: true } },

  setup(props) {
    const inst = computed(() => INSTANCES.find((i) => i.id === props.instId));
    const files = ref(null);   // null while loading
    const location = ref("");
    const name = ref("");
    const show = ref("all");
    const query = ref("");
    const regex = ref(false);   // the search as a regular expression (the user's wish of 26.09.2026)
    const log = ref(null);
    const error = ref("");
    const listEl = ref(null);
    let seq = 0;
    let typing = null;

    const errorText = (code) => L.errors[code] || T.errors[code] || T.errors.unknown;
    // "2026-09-23 09:24:21" is the local time of the slicer's computer, which is this one.
    const startOf = (f) => f.started ? new Date(f.started.replace(" ", "T")) : new Date(f.modified * 1000);
    const fileLabel = (f, i) => L.fileOption(whenText(startOf(f)), fmtSize(f.size), i === 0)
      + (f.readable ? "" : ` · ${L.unreadable} (${f.name})`);

    async function loadFiles() {
      try {
        const data = await api.logs(props.instId);
        files.value = data.files;
        location.value = data.location;
        if (!data.files.some((f) => f.name === name.value && f.readable)) {
          ++seq;
          log.value = null;
          name.value = data.files.find((f) => f.readable)?.name || "";
        }
        error.value = "";
      } catch (err) {
        error.value = errorText(err.code);
      }
    }
    async function loadLog() {
      const mine = ++seq;
      log.value = null;
      if (!files.value?.some((f) => f.name === name.value && f.readable)) return;
      try {
        const data = await api.log(props.instId, name.value, show.value, query.value.trim(), regex.value);
        if (mine !== seq) return;
        log.value = data;
        error.value = "";
        // The newest entries are at the end.
        await nextTick();
        if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight;
      } catch (err) {
        if (mine === seq) error.value = errorText(err.code);
      }
    }
    // A new name loads through the watch below, the same name has to be asked again.
    async function refresh() {
      const before = name.value;
      await loadFiles();
      if (name.value === before) await loadLog();
    }

    watch([name, show, regex], loadLog);
    // An example of the cheat sheet: as a regular expression; the watches load it.
    function useExample(pattern) {
      query.value = pattern;
      regex.value = true;
    }
    watch(query, () => {
      clearTimeout(typing);
      typing = setTimeout(loadLog, 250);
    });
    onMounted(refresh);

    // How many entries each choice shows, from the counts over the whole file.
    const countOf = (s) => {
      const c = log.value?.counts || {};
      const sum = (levels) => levels.reduce((total, l) => total + (c[l] || 0), 0);
      return s === "errors" ? sum(["fatal", "error"]) : s === "problems" ? sum(["fatal", "error", "warning"]) : log.value?.total || 0;
    };
    const shownText = computed(() => log.value ? L.shown(log.value.entries.length, log.value.matched) : "");

    return { T, L, SHOWS, inst, files, location, name, show, query, regex, useExample, log, error, listEl, fileLabel, countOf, shownText, refresh };
  },

  template: `
    <div class="page logs-page">
      <h1 id="page-title" tabindex="-1">{{ L.title }}</h1>
      <p class="note">{{ L.lead(inst.slicer) }}</p>

      <p v-if="files === null && !error" class="note">{{ L.loading }}</p>
      <p v-else-if="files && !files.length" class="empty">{{ L.none }}</p>
      <section v-else-if="files" class="box">
        <div class="log-bar">
          <label class="log-file">
            <span>{{ L.file }}</span>
            <select v-model="name" class="input">
              <option v-for="(f, i) in files" :key="f.name" :value="f.name" :disabled="!f.readable">{{ fileLabel(f, i) }}</option>
            </select>
          </label>
          <button class="btn" type="button" :title="L.refreshTitle" @click="refresh"><ui-icon name="refresh"/>{{ L.refresh }}</button>
        </div>
        <p v-if="!name" class="empty">{{ L.noneReadable }}</p>
        <div v-else class="log-bar">
          <div class="chips" role="group" :aria-label="L.showLabel">
            <button v-for="s in SHOWS" :key="s" class="chip" type="button" :aria-pressed="show === s ? 'true' : 'false'" @click="show = s">
              {{ L.show[s] }}<span class="log-count">{{ countOf(s) }}</span>
            </button>
          </div>
          <span class="search">
            <ui-icon name="search"/>
            <input v-model="query" class="input" type="search" :placeholder="L.search" :aria-label="L.search">
          </span>
          <button class="chip" type="button" :aria-pressed="regex ? 'true' : 'false'" :title="L.regexHint" @click="regex = !regex">{{ L.regex }}</button>
          <regex-help examples="slicer" @use="useExample"/>
        </div>

        <p v-if="error" class="alert" role="alert">{{ error }}</p>
        <template v-else-if="log">
          <p class="note">{{ shownText }}<template v-if="log.cut"> · {{ L.cut }}</template></p>
          <div v-if="log.entries.length" ref="listEl" class="log-list" tabindex="0" :aria-label="L.entries">
            <div v-for="e in log.entries" :key="e.n" :class="['log-row', 'lv-' + (e.level || 'none')]">
              <span class="log-time" :title="e.time">{{ e.time.slice(11) }}</span>
              <span class="log-level">{{ L.levels[e.level] }}</span>
              <span class="log-text">{{ e.text }}<em v-if="e.more" class="log-more">{{ L.more(e.more) }}</em></span>
            </div>
          </div>
          <p v-else class="empty">{{ L.noMatch }}</p>
        </template>
        <p class="note">{{ L.where }} <code>{{ location }}</code></p>
      </section>
      <p v-else-if="error" class="alert" role="alert">{{ error }}</p>
    </div>
  `,
};
