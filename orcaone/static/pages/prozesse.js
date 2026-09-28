// Page "Prozesse": the print settings (process profiles) the slicer offers per printer and
// nozzle, and what they set. Full editing opens the shared local profile workspace.
// The printer comes from the top bar (app.js), as on the page
// "Filamente", and the nozzle chosen counts for both pages. A process belongs to the printer
// profile of one nozzle; which filament goes with it is a separate choice in the slicer.
// Data: GET /api/data (processes, models[].printers[].processes and .process, the last choice);
// the values of one process on demand from GET /api/instances/{id}/profile.
import {
  INSTANCES, ui, go, hashOf, nozzleLabel, printerShortName, modelShown, chosenNozzle, nozzleKey, DECIMAL, LOCALE, printerModels,
} from "../common.js";
import { T, plainName } from "../texts.js";
import { api } from "../api.js";
import { problemText } from "../plan.js";
import { openProfiles } from "./profile-session.js";

const { ref, computed, nextTick, onMounted, onUnmounted } = Vue;
const P = T.processes;
const F = T.filaments;

// Own first, like on the page "Filamente".
const KIND_ORDER = ["user", "bundle", "vendor"];
const KIND_ICON = { user: "user", bundle: "package", vendor: "factory" };
// The values the side panel shows first; texts.js names the groups and keys. Everything else is
// under "Alle Werte".
const GROUPS = [
  { id: "quality", keys: ["layer_height", "initial_layer_print_height", "seam_position", "ironing_type"] },
  { id: "strength", keys: ["wall_loops", "top_shell_layers", "bottom_shell_layers", "sparse_infill_density", "sparse_infill_pattern"] },
  { id: "speed", keys: ["outer_wall_speed", "inner_wall_speed", "sparse_infill_speed", "top_surface_speed", "initial_layer_speed", "travel_speed", "default_acceleration"] },
  { id: "support", keys: ["enable_support", "support_type", "support_threshold_angle", "support_on_build_plate_only"] },
  { id: "adhesion", keys: ["brim_type", "brim_width", "skirt_loops", "raft_layers"] },
];

// "10000" -> "10.000", "0.25" -> "0,25" in German; anything else as it is.
const fmt = (v) => v !== "" && !isNaN(Number(v)) ? Number(v).toLocaleString(LOCALE, { maximumFractionDigits: 3 }) : String(v);
const asList = (v) => Array.isArray(v) ? v : [v];
// "0.2" -> "0,20": two decimals, as the process names write layer heights.
const layerText = (v) => isNaN(Number(v)) ? fmt(v) : Number(v).toFixed(2).replace(".", DECIMAL);
// "0.20mm Standard" -> "Standard": without its layer height the name says what kind it is.
const kindOf = (alias) => alias.replace(/^\s*\d+(?:[.,]\d+)?\s*(?:mm)?\s*/i, "").trim() || alias;
// A shown value in words: switches and choices from texts.js, numbers with their unit. Snapmaker
// Orca keeps a second value for the high-flow hotend (FINDINGS 4.4): "200 / 500 mm/s".
function valueText(key, raw) {
  const words = P.enums[key];
  const parts = asList(raw).filter((x) => x !== "" && x !== null && x !== undefined)
    .map((x) => words ? words[x] ?? x : fmt(x));
  if (!parts.length) return "–";
  const unit = P.units[key];
  return parts.join(" / ") + (!unit ? "" : unit === "°" ? unit : " " + unit);
}
// "Alle Werte" shows the values as the files hold them.
const rawText = (raw) => asList(raw).join(", ") || "–";

export default {
  name: "ProzessePage",
  props: {
    instId: { type: String, required: true },
    modelIdx: { type: Number, default: null },  // null only for an installation without a printer
  },

  setup(props) {
    const inst = computed(() => INSTANCES.find((i) => i.id === props.instId));
    const model = computed(() => props.modelIdx === null ? null : inst.value.models[props.modelIdx]);
    const gone = computed(() => !!model.value && !modelShown(inst.value, model.value));
    const byName = computed(() => new Map(inst.value.processes.map((r) => [r.name, r])));
    const printerTitle = computed(() => model.value && (model.value.display_name || printerShortName(model.value.printers[0]?.name || model.value.model)));

    const noPrinter = computed(() => !printerModels(inst.value).length);

    // ------------------------------------------------------------ nozzle and tiles
    // The nozzle chosen here or on the page "Filamente"; for "all" there, the printer the slicer
    // starts with, else the first.
    const nozzle = computed(() => {
      const m = model.value;
      if (!m) return null;
      const chosen = chosenNozzle[nozzleKey(inst.value, m)];
      return m.printers.find((p) => p.name === chosen) || m.printers.find((p) => p.selected) || m.printers[0];
    });
    function pickNozzle(p) {
      chosenNozzle[nozzleKey(inst.value, model.value)] = p.name;
      panel.value = null;
    }
    const kindTitle = (kind) => kind === "vendor" && model.value.origin && model.value.origin !== "Custom"
      ? F.kinds.vendorFrom(model.value.origin) : F.kinds[kind];
    const groups = computed(() => {
      const p = nozzle.value;
      if (!p) return [];
      const tiles = p.processes.map((n) => byName.value.get(n)).filter(Boolean).map((r) => ({
        r, layer: layerText(r.layer_height), kind: kindOf(plainName(r.alias)), last: r.name === p.process,
      })).sort((a, b) => Number(a.r.layer_height) - Number(b.r.layer_height) || a.kind.localeCompare(b.kind, "de"));
      return KIND_ORDER.map((kind) => ({ kind, title: kindTitle(kind), icon: KIND_ICON[kind], tiles: tiles.filter((t) => t.r.origin_kind === kind) }))
        .filter((g) => g.tiles.length || g.kind === "user");
    });
    const lastTile = computed(() => groups.value.flatMap((g) => g.tiles).find((t) => t.last) || null);

    // ------------------------------------------------------------ side panel
    // { t: the tile, data: GET /profile, error }; the values come on demand.
    const panel = ref(null);
    let seq = 0, lastFocus = null;
    async function openTile(t) {
      if (!panel.value) lastFocus = document.activeElement;
      const mine = ++seq;
      panel.value = { t, data: null, error: "" };
      nextTick(() => document.getElementById("panel-title")?.focus());
      try {
        const data = await api.profile(inst.value.id, "process", t.r.name);
        if (mine === seq && panel.value) panel.value = { ...panel.value, data };
      } catch (err) {
        if (mine === seq && panel.value) panel.value = { ...panel.value, error: problemText(err.code, inst.value, err.data) };
      }
    }
    function closePanel() {
      panel.value = null;
      if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
      lastFocus = null;
    }
    const originText = (t) => t.r.origin_kind === "user" ? P.ownProcess
      : t.r.origin_kind === "bundle" ? F.bundlePrinter(t.r.bundle) : kindTitle("vendor");
    const shownGroups = computed(() => {
      const d = panel.value && panel.value.data;
      if (!d) return [];
      const ownDots = d.origin_kind === "user";
      return GROUPS.map((g) => ({
        id: g.id, title: P.groups[g.id],
        rows: g.keys.map((key) => {
          const v = d.values[key];
          return { key, label: P.keys[key], text: v ? valueText(key, v.value) : "–", own: ownDots && !!v && v.own, fallback: !!v && !!v.default };
        }),
      }));
    });
    const twoValues = computed(() => shownGroups.value.some((g) => g.rows.some((r) => r.text.includes(" / "))));
    const allValues = computed(() => {
      const d = panel.value && panel.value.data;
      return d ? Object.entries(d.values).filter(([, v]) => !v.default).map(([key, v]) => ({ key, text: rawText(v.value), source: v.source, own: v.own })) : [];
    });
    const onKey = (ev) => { if (ev.key === "Escape" && panel.value) closePanel(); };
    onMounted(() => window.addEventListener("keydown", onKey));
    // Opened from "Übersicht" for one process: its tile with the side panel.
    if (ui.processFocus) {
      const name = ui.processFocus;
      ui.processFocus = null;
      onMounted(() => {
        const t = groups.value.flatMap((g) => g.tiles).find((x) => x.r.name === name);
        if (t) openTile(t);
      });
    }
    onUnmounted(() => window.removeEventListener("keydown", onKey));

    return {
      T, P, F, inst, model, gone, printerTitle, noPrinter, nozzle, pickNozzle, groups, lastTile, panel, openProfiles,
      openTile, closePanel, originText, shownGroups, twoValues, allValues, nozzleLabel, hashOf, go, plainName,
    };
  },

  template: `
    <div :class="['page-host', { 'with-panel': panel }]">
      <!-- No printer in this installation; else app.js puts the one of the top bar into the address -->
      <div v-if="!model" class="page">
        <h1 id="page-title" tabindex="-1">{{ T.nav.pages.prozesse }}</h1>
        <p v-if="noPrinter" class="empty">{{ F.noPrinter }}</p>
      </div>

      <!-- Screen 2 without a printer: removed on the page "Drucker" -->
      <div v-else-if="gone" class="page">
        <div class="printer-bar">
          <div class="bar-title">
            <h1 id="page-title" tabindex="-1">{{ printerTitle }}</h1>
            <span>{{ inst.slicer }} {{ inst.version }}</span>
          </div>
        </div>
        <p class="empty">{{ F.printerGone }}</p>
      </div>

      <!-- Screen 2: one printer -->
      <div v-else class="page">
        <div class="printer-bar">
          <img class="bar-img" :src="model.cover" alt="" width="48" height="48">
          <div class="bar-title">
            <h1 id="page-title" tabindex="-1">{{ printerTitle }}</h1>
            <span>{{ model.own ? F.ownPrinter + ' · ' : '' }}{{ inst.slicer }} {{ inst.version }}</span>
          </div>
          <run-status :inst="inst"/>
        </div>

        <section class="box nozzles" aria-labelledby="nozzle-h">
          <h2 id="nozzle-h">{{ F.nozzle }}</h2>
          <div class="nozzle-row">
            <button v-for="p in model.printers" :key="p.name" type="button" class="nozzle-tile"
                    :aria-pressed="nozzle && nozzle.name === p.name" @click="pickNozzle(p)">
              <nozzle-icon :sizes="p.variant.split('+').map(Number)"/>{{ nozzleLabel(p.variant) }} mm
              <small v-if="model.group_id">{{ p.label || p.name }}</small>
            </button>
          </div>
        </section>

        <p class="quiet-note"><ui-icon name="info"/>{{ P.lead }}</p>
        <p v-if="lastTile" class="proc-last-line"><ui-icon name="star"/>{{ P.lastLine(lastTile.layer, lastTile.kind) }}</p>

        <section v-for="g in groups" :key="g.kind" class="box proc-group" :aria-label="g.title">
          <div class="box-head">
            <span class="kind-icon"><ui-icon :name="g.icon"/></span>
            <h2>{{ g.title }}</h2>
            <span class="sub">{{ P.count(g.tiles.length) }}</span>
          </div>
          <ul v-if="g.tiles.length" class="proc-grid">
            <li v-for="t in g.tiles" :key="t.r.name">
              <button type="button" class="proc-tile" :aria-current="panel && panel.t.r.name === t.r.name ? 'true' : null"
                      :title="plainName(t.r.name)" @click="openTile(t)">
                <span class="proc-layer">{{ t.layer }}<small>mm</small></span>
                <span class="proc-kind">{{ t.kind }}</span>
                <span v-if="t.last" class="tag tag-default proc-last"><ui-icon name="star" :size="14"/>{{ P.last }}</span>
              </button>
            </li>
          </ul>
          <p v-else class="no-hits">{{ g.kind === 'user' ? P.noOwn : P.none }}</p>
        </section>
      </div>

      <aside v-if="panel" class="panel" aria-labelledby="panel-title">
        <div class="panel-head">
          <h2 id="panel-title" tabindex="-1">{{ P.panelTitle }}</h2>
          <button class="icon-btn" type="button" :aria-label="T.close" @click="closePanel"><ui-icon name="close"/></button>
        </div>
        <div class="panel-body">
          <div class="hero">
            <span class="proc-hero"><span class="proc-layer">{{ panel.t.layer }}<small>mm</small></span></span>
            <div class="hero-text">
              <p class="hero-name">{{ panel.t.kind }}</p>
              <p class="hero-sub">{{ originText(panel.t) }}</p>
              <p v-if="panel.t.last" class="tags hero-tags"><span class="tag tag-default"><ui-icon name="star" :size="14"/>{{ P.last }}</span></p>
            </div>
          </div>
          <p class="note mono">{{ plainName(panel.t.r.name) }}</p>
          <p v-if="panel.t.r.template" class="from">{{ F.templateLabel }} {{ plainName(panel.t.r.template) }}</p>

          <p v-if="panel.error" class="alert" role="alert">{{ panel.error }}</p>
          <p v-else-if="!panel.data" class="note">{{ P.loading }}</p>
          <template v-else>
            <template v-for="g in shownGroups" :key="g.id">
              <h3>{{ g.title }}</h3>
              <dl class="proc-values">
                <div v-for="r in g.rows" :key="r.key" class="proc-value">
                  <dt>{{ r.label }}</dt>
                  <dd :title="r.fallback ? P.defaultValue : null">{{ r.text }}<span v-if="r.own" class="own-dot" :title="F.ownValue"></span></dd>
                </div>
              </dl>
            </template>
            <p v-if="twoValues" class="legend">{{ P.highFlow }}</p>
            <p v-if="shownGroups.some((g) => g.rows.some((r) => r.own))" class="legend"><span class="own-dot"></span> {{ F.ownLegend }}</p>

            <details class="more all-values">
              <summary>{{ P.allValues(allValues.length) }}</summary>
              <p class="note">{{ P.allValuesNote }}</p>
              <dl class="kv">
                <template v-for="v in allValues" :key="v.key">
                  <dt>{{ v.key }}</dt>
                  <dd>{{ v.text }}<small>{{ v.own ? P.setHere : plainName(v.source) }}</small></dd>
                </template>
              </dl>
            </details>
          </template>
          <button class="btn" type="button" @click="openProfiles(inst.id, [{kind: 'process', name: panel.t.r.name}])">{{ T.profileEditor.title }}</button>
        </div>
      </aside>
    </div>
  `,
};
