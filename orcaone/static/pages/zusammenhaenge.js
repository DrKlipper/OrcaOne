// Page "Zusammenhänge" (the user's wish of 25.09.2026: the dependencies "als Tree", foldable, with
// links to the pages, "schön und übersichtlich"): what hangs on what in the slicer. A printer model
// has one printer profile per nozzle; the processes and filaments that fit a profile hang at it
// (compatible_printers, FINDINGS 4.6), a filament of a vendor only while it is switched on
// ("filaments" in the .conf); the slicer's filament list takes one of them per head (orca_presets,
// FINDINGS 4.3). As the slicer has it (GET /api/data), the printers as the change list leaves them.
// Only to look at: every node leads to the page that shows or changes it. The names below a nozzle
// come only while it is open, filaments grouped by where they come from; a big group starts closed
// (the user's colleague: 30 printers, 300 own filaments).
import {
  INSTANCES, live, ui, go, hashOf, nozzleLabel, chosenNozzle, nozzleKey, printerModels, printerShortName, printerText, originGroup, whenText,
} from "../common.js";
import { T, plainName } from "../texts.js";

const { reactive, computed, watch } = Vue;
const Z = T.relations;
const O = T.home;
const NO_COLOUR = "#D9D9D9";  // a spool without a colour
const BIG = 12;               // a group of filaments with more names starts closed
const short = (name) => plainName(name || "").replace(/ @.*$/, "");

export default {
  name: "ZusammenhaengePage",
  props: { instId: { type: String, required: true } },

  setup(props) {
    const inst = computed(() => INSTANCES.find((i) => i.id === props.instId));
    const state = computed(() => live[props.instId]);

    // ------------------------------------------------------------ the tree
    // Printers and their nozzles with the numbers; the names come with the open nodes below. The
    // printer the slicer has chosen first, as on "Übersicht"; an own printer names its template
    // there too.
    const tree = computed(() => {
      const i = inst.value, start = state.value.defaultPrinter;
      const own = new Map(i.printers_page.own.map((p) => [p.name, p]));
      const templateOf = (m) => {
        const p = own.get(m.model);
        return p?.based_on ? (p.based_on_found ? printerText(i, p.based_on) : p.based_on) : "";
      };
      const first = (m) => (m.printers.some((p) => p.selected) ? 0 : 1);
      return printerModels(i).slice().sort((a, b) => first(a) - first(b)).map((m) => ({
        id: "m:" + m.model, m, idx: i.models.indexOf(m), cover: m.cover, own: !!m.own,
        label: m.display_name || (m.own ? plainName(m.model) : printerShortName(m.printers[0]?.name || m.model)),
        template: m.own ? templateOf(m) : "", start: m.printers.some((p) => p.name === start),
        nozzles: m.printers.map((p) => ({
          id: "p:" + p.name, p, text: [p.label || '', Array.isArray(p.nozzle_diameter) ? p.nozzle_diameter.join(' / ') : p.variant ? nozzleLabel(p.variant) : ''].filter(Boolean).join(' · '), sizes: Array.isArray(p.nozzle_diameter) ? p.nozzle_diameter.map(Number) : (p.variant || '').split('+').filter(Boolean).map(Number),
          start: p.name === start, procs: (p.processes || []).length, on: p.counts?.visible || 0, off: p.counts?.hidden || 0,
        })),
      }));
    });

    // Open nodes: "m:<model>", "p:<printer profile>" and below it ":procs" and ":fils".
    const open = reactive(new Set());
    const flipped = reactive(new Set());  // filament groups opened or closed against how they start
    const isOpen = (id) => open.has(id);
    const toggle = (id) => (open.has(id) ? open.delete(id) : open.add(id));
    const groupOpen = (g) => (g.items.length <= BIG) !== flipped.has(g.id);
    const toggleGroup = (g) => (flipped.has(g.id) ? flipped.delete(g.id) : flipped.add(g.id));
    // At first the printer the slicer has chosen, open down to its processes and filaments.
    function reset() {
      open.clear();
      flipped.clear();
      const start = state.value.defaultPrinter;
      const t = tree.value.find((x) => x.start) || tree.value[0];
      const z = t && (t.nozzles.find((x) => x.p.name === start) || t.nozzles[0]);
      if (t) open.add(t.id);
      if (z) [z.id, z.id + ":procs", z.id + ":fils"].forEach((id) => open.add(id));
    }
    watch(() => props.instId, reset, { immediate: true });
    // Every printer with its nozzles; the lists of names stay as they are (thousands otherwise).
    const openAll = () => tree.value.forEach((t) => [t.id, ...t.nozzles.map((z) => z.id)].forEach((id) => open.add(id)));
    const closeAll = () => open.clear();

    // The processes at a nozzle: own first, then by layer height, as on "Prozesse".
    const processes = computed(() => new Map(inst.value.processes.map((r) => [r.name, r])));
    function procsOf(z) {
      return (z.p.processes || []).map((name) => processes.value.get(name) || { name, alias: short(name), origin_kind: "vendor", layer_height: "" })
        .sort((a, b) => (a.origin_kind === "user" ? 0 : 1) - (b.origin_kind === "user" ? 0 : 1)
          || Number(a.layer_height) - Number(b.layer_height) || a.alias.localeCompare(b.alias))
        .map((r) => ({ name: r.name, label: plainName(r.alias || short(r.name)), own: r.origin_kind === "user", last: r.name === z.p.process }));
    }
    // The filaments the slicer shows at each open nozzle, by where they come from (as on "Filamente").
    const filaments = computed(() => {
      const out = {};
      for (const t of tree.value) {
        if (!open.has(t.id)) continue;
        for (const z of t.nozzles) {
          if (!open.has(z.id) || !open.has(z.id + ":fils")) continue;
          const groups = new Map();
          for (const f of inst.value.filaments) {
            if (f.printers?.[z.p.name]?.status !== "visible") continue;
            const g = originGroup(f);
            if (!groups.has(g.key)) groups.set(g.key, { id: z.id + ":" + g.key, label: g.label, items: [] });
            groups.get(g.key).items.push({
              name: f.name, label: plainName(f.alias || short(f.name)), colour: f.colour || NO_COLOUR,
              template: f.origin_kind === "user" && f.inherits ? short(f.inherits) : "",
            });
          }
          out[z.id] = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, g]) => g);
        }
      }
      return out;
    });

    // On to a page at this printer and nozzle; with a profile, that one opened there.
    function openPage(t, z, page, focus = null) {
      if (z) chosenNozzle[nozzleKey(inst.value, t.m)] = z.p.name;
      if (page === "filamente") ui.filamentFocus = focus;
      else ui.processFocus = focus;
      ui.printer = t.m.model;
      go(null, hashOf(page, inst.value.id, t.idx));
    }

    return {
      T, Z, O, NO_COLOUR, inst, tree, isOpen, toggle, groupOpen, toggleGroup, openAll, closeAll, procsOf, filaments, openPage,
      hashOf, plainName, short, whenText,
    };
  },

  template: `
    <div class="page">
      <div class="page-head">
        <h1 id="page-title" tabindex="-1">{{ T.nav.pages.zusammenhaenge }}</h1>
      </div>
      <p class="quiet-note"><ui-icon name="info"/><span>{{ Z.lead }}</span></p>
      <div class="rel-bar">
        <span v-if="inst.conf_saved" class="rel-saved" :title="O.savedWhy(inst.slicer)">{{ O.saved(whenText(new Date(inst.conf_saved))) }}</span>
        <span class="rel-bar-actions">
          <button class="link" type="button" @click="openAll">{{ Z.openAll }}</button>
          <button class="link" type="button" @click="closeAll">{{ Z.closeAll }}</button>
        </span>
      </div>

      <p v-if="!tree.length" class="empty">{{ O.noPrinter }}</p>
      <ul v-else class="rel-tree">
        <!-- The printer -->
        <li v-for="t in tree" :key="t.id" class="rel-root">
          <div class="rel-row">
            <button class="rel-toggle" type="button" :aria-expanded="isOpen(t.id) ? 'true' : 'false'" @click="toggle(t.id)">
              <ui-icon :name="isOpen(t.id) ? 'chevronDown' : 'chevron'" :size="16"/>
              <img class="rel-img" :src="t.cover" alt="" width="40" height="40">
              <span class="rel-name rel-printer">{{ t.label }}</span>
            </button>
            <span class="tag"><ui-icon :name="t.own ? 'user' : 'factory'" :size="14"/>{{ t.own ? T.printers.tags.own : T.printers.tags.vendor }}</span>
            <span v-if="t.start" class="tag tag-default" :title="O.startWhy(inst.slicer)"><ui-icon name="star" :size="14"/>{{ O.start }}</span>
            <span class="rel-meta">{{ Z.nozzles(t.nozzles.length) }}</span>
            <small v-if="t.template" class="rel-sub">{{ Z.template(t.template) }}</small>
          </div>
          <ul v-if="isOpen(t.id)">
            <!-- Each nozzle is a printer profile of its own -->
            <li v-for="z in t.nozzles" :key="z.id">
              <div class="rel-row">
                <button class="rel-toggle" type="button" :aria-expanded="isOpen(z.id) ? 'true' : 'false'" @click="toggle(z.id)">
                  <ui-icon :name="isOpen(z.id) ? 'chevronDown' : 'chevron'" :size="16"/>
                  <nozzle-icon :sizes="z.sizes" :height="22"/>
                  <span class="rel-name">{{ Z.nozzle(z.text) }}</span>
                </button>
                <span v-if="z.start" class="tag tag-default" :title="O.startWhy(inst.slicer)"><ui-icon name="star" :size="14"/>{{ O.start }}</span>
                <small class="rel-sub" :title="Z.profileWhy">{{ plainName(z.p.name) }}</small>
                <span class="rel-meta">{{ Z.counts(z.procs, z.on) }}</span>
              </div>
              <ul v-if="isOpen(z.id)">
                <!-- The processes that fit it -->
                <li>
                  <div class="rel-row">
                    <button class="rel-toggle" type="button" :aria-expanded="isOpen(z.id + ':procs') ? 'true' : 'false'" @click="toggle(z.id + ':procs')">
                      <ui-icon :name="isOpen(z.id + ':procs') ? 'chevronDown' : 'chevron'" :size="16"/>
                      <ui-icon name="layers"/><span class="rel-name">{{ Z.processes }}</span>
                    </button>
                    <span class="rel-meta">{{ z.procs }}</span>
                    <a class="rel-link" :href="hashOf('prozesse', inst.id, t.idx)" @click.prevent="openPage(t, z, 'prozesse')">{{ Z.open(T.nav.pages.prozesse) }}</a>
                  </div>
                  <template v-if="isOpen(z.id + ':procs')">
                    <p v-if="!z.procs" class="rel-none">{{ Z.noProcess }}</p>
                    <p v-else class="home-chips rel-leaves">
                      <button v-for="r in procsOf(z)" :key="r.name" type="button" :class="['home-chip', { 'is-last': r.last }]"
                              :title="O.openIn(plainName(r.name), T.nav.pages.prozesse) + (r.last ? ' · ' + Z.lastChosen : '')"
                              @click="openPage(t, z, 'prozesse', r.name)">
                        <ui-icon v-if="r.own" name="user" :size="12"/>{{ r.label }}<ui-icon v-if="r.last" name="star" :size="12"/></button>
                    </p>
                  </template>
                </li>
                <!-- The filaments that fit it and are switched on; the slicer's list takes one per head -->
                <li>
                  <div class="rel-row">
                    <button class="rel-toggle" type="button" :aria-expanded="isOpen(z.id + ':fils') ? 'true' : 'false'" @click="toggle(z.id + ':fils')">
                      <ui-icon :name="isOpen(z.id + ':fils') ? 'chevronDown' : 'chevron'" :size="16"/>
                      <ui-icon name="spool"/><span class="rel-name">{{ Z.filaments }}</span>
                    </button>
                    <span class="rel-meta" :title="z.off ? Z.offWhy : null">{{ Z.on(z.on) }}<template v-if="z.off"> · {{ Z.off(z.off) }}</template></span>
                    <a class="rel-link" :href="hashOf('filamente', inst.id, t.idx)" @click.prevent="openPage(t, z, 'filamente')">{{ Z.open(T.nav.pages.filamente) }}</a>
                  </div>
                  <ul v-if="isOpen(z.id + ':fils')">
                    <li v-if="z.p.heads?.length">
                      <div class="rel-row rel-slots">
                        <span class="rel-label"><ui-icon name="star" :size="14"/>{{ z.start ? Z.slotList : Z.slotListLast }}</span>
                        <button v-for="(h, k) in z.p.heads" :key="k" class="home-badge" type="button"
                                :title="O.openIn(O.slot(k + 1, plainName(h.name)), T.nav.pages.filamente)" @click="openPage(t, z, 'filamente', h.name)">
                          <small v-if="z.p.heads.length > 1" class="home-slot">{{ k + 1 }}</small><spool-icon :colour="h.colour || NO_COLOUR" :size="16"/>{{ h.material || short(h.name) }}</button>
                      </div>
                    </li>
                    <li v-for="g in filaments[z.id]" :key="g.id">
                      <div class="rel-row">
                        <button class="rel-toggle" type="button" :aria-expanded="groupOpen(g) ? 'true' : 'false'" @click="toggleGroup(g)">
                          <ui-icon :name="groupOpen(g) ? 'chevronDown' : 'chevron'" :size="16"/>
                          <span class="rel-name rel-group">{{ g.label }}</span>
                        </button>
                        <span class="rel-meta">{{ g.items.length }}</span>
                      </div>
                      <p v-if="groupOpen(g)" class="home-chips rel-leaves">
                        <button v-for="f in g.items" :key="f.name" type="button" class="home-chip"
                                :title="O.openIn(plainName(f.name), T.nav.pages.filamente)" @click="openPage(t, z, 'filamente', f.name)">
                          <spool-icon :colour="f.colour" :size="14"/>{{ f.label }}<small v-if="f.template" class="rel-tpl">{{ Z.template(f.template) }}</small></button>
                      </p>
                    </li>
                    <li v-if="!z.on"><p class="rel-none">{{ Z.noFilament }}</p></li>
                  </ul>
                </li>
              </ul>
            </li>
          </ul>
        </li>
      </ul>
    </div>
  `,
};
