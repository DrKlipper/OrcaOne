// Page "Übersicht", the first page of the slicer part (the user's wishes of 24.09.2026: what OrcaOne
// works with at a glance, as pictures rather than lists; of 25.09.2026: see at once which slicer is
// chosen and all printers in it, one page instead of "Übersicht" and "Druckerprofile", and "auf den
// ersten Blick sehen, was bei dem Drucker gerade los ist in Orca", nothing overloaded, more only on
// demand). On top the installations as cards, the chosen one marked, each with whether it runs; a
// click chooses another. Below one full-width card per printer model of a manufacturer and per own
// printer: its name, the ways on (filaments, processes, the printer part) and one line with what is
// set in the slicer (presets and orca_presets of the .conf, overview.py): every nozzle with the one
// the slicer starts with marked, the process and the filament per head. A click on a nozzle chooses
// it in the slicer (the user: changing it must not be hidden), a click on the process or a filament
// opens it on its page. "Alle Düsen …" shows every nozzle with its last process and the processes
// and filaments there, open at the printer the slicer has chosen. Behind "⋯": remove a printer
// together with the own filaments and processes that belong to it only, with the plan in the side
// panel first (hard rule 5). Every change goes into the change list (app.js), which writes it with
// "Übernehmen"; ops.js turns the `live` state into printer_model_off, printer_delete, filament_delete,
// default_printer and cleanup_presets. Removing the last model of a vendor can make the slicer delete
// its package at its next start (FINDINGS 4.2); the plan says so. Tiles for own filaments, backups
// and what changed since last time.
import {
  INSTANCES, BACKUPS, NEWS, U1_MODELS, live, ui, go, hashOf, flash, printerModels, nozzleLabel, chosenNozzle, nozzleKey, whenText,
  printerShortName, printerText, profileSub, KIND_ICON, hosts, loadHosts, slicerLogo, originGroup,
} from "../common.js";
import { T, plainName } from "../texts.js";

const { ref, reactive, computed, watch, nextTick, onMounted, onUnmounted } = Vue;
const O = T.home;
const P = T.printers;
const SPOOLS = 10;         // own filaments shown as spools, the rest as a number
const NO_COLOUR = "#D9D9D9";  // a spool without a colour
// Filament slots shown at first, as many as the U1 has heads; the slicers allow up to 64
// (MAXIMUM_EXTRUDER_NUMBER, "Add one filament"), the rest behind "N weitere".
const HEADS = 4;


export default {
  name: "UebersichtPage",
  props: { instId: { type: String, required: true } },

  setup(props) {
    const inst = computed(() => INSTANCES.find((i) => i.id === props.instId));
    const state = computed(() => live[props.instId]);
    const readOnly = computed(() => !!inst.value.running);
    const isU1 = computed(() => U1_MODELS.includes(ui.printer));
    const ownOf = (i) => i.filaments.filter((f) => f.origin_kind === "user");
    const own = computed(() => ownOf(inst.value));
    onMounted(() => { if (!hosts.value) loadHosts(); });

    // ------------------------------------------------------------ the installation
    // The one of the tab in short; choosing is the tabs' (the user's wish of 27.09.2026: the cards of all
    // installations here were the old choice).
    const logo = computed(() => slicerLogo(inst.value.slicer));
    const facts = computed(() => O.slicerFacts(inst.value.version, printerModels(inst.value).length, own.value.length));

    // ------------------------------------------------------------ the printers of this slicer
    const short = (name) => plainName(name || "").replace(/ @.*$/, "");
    // What is set in the slicer for a printer: the nozzle it starts with, else one it remembers a
    // choice for, with that process and the filament per head. null: never chosen there. The slicer
    // keeps no order of these choices (orca_presets), so "last" means the first one found.
    function nowOf(m, start) {
      const p = m.printers.find((x) => x.name === start) || m.printers.find((x) => x.process || x.heads?.length);
      if (!p) return null;
      return {
        preset: p.name, start: p.name === start, nozzle: variantText(p), process: p.process,
        heads: (p.heads || []).map((h) => ({ name: h.name, colour: h.colour || NO_COLOUR, label: h.material || short(h.name) })),
      };
    }
    const variantText = p => {
      const sizes = Array.isArray(p.nozzle_diameter) ? p.nozzle_diameter.join(' / ') : p.variant ? nozzleLabel(p.variant) : '';
      return p.label ? `${p.label} · ${sizes}` : sizes;
    };
    // One card per model of a manufacturer and per own printer, as the slicer shows them; with the
    // model's entry of GET /api/data for its nozzles, and its address by model as the printer part
    // keeps it (an own printer by the model it is built on).
    const cards = computed(() => {
      const i = inst.value, s = state.value, pp = i.printers_page;
      const mine = (list) => list.filter((x) => s.own.has(x.name));
      const out = [];
      for (const m of pp.system) {
        if (!s.models.has(m.model)) continue;
        const name = printerShortName(m.printers[0]?.name || m.model);
        out.push({
          id: "model:" + m.model, system: true, model: m.model, name, label: name, sub: name === m.model ? "" : m.model,
          cover: m.cover, printers: m.printers, tag: P.tags.vendor, tagIcon: "factory",
          visible: true, problem: null, package: m.origin, dropsPackage: m.drops_package,
          isDefault: m.printers.some((p) => p.name === s.defaultPrinter),
          // Own processes go only together with an own printer (printer_delete in ops.js), so a
          // model of a manufacturer offers the own filaments alone.
          onlyHere: mine(m.only_here).filter((x) => x.kind === "filament"), keepsOwn: m.own_printers.filter((n) => s.own.has(n)),
          entry: i.models.find((x) => !x.own && x.model === m.model),
        });
      }
      const emittedGroups = new Set();
      for (const p of pp.own) {
        if (!s.own.has(p.name)) continue;
        const group = i.models.find(m => m.group_id && m.printers.some(member => member.name === p.name));
        if (group) {
          if (emittedGroups.has(group.group_id)) continue;
          emittedGroups.add(group.group_id);
          const printers = group.printers.filter(member => s.own.has(member.name));
          const entry = printers.length === group.printers.length ? group : { ...group, printers };
          out.push({ id: 'group:' + group.group_id, group: true, system: false, model: group.model,
            name: group.display_name, label: group.display_name, sub: '', cover: group.cover || p.cover,
            printers, tag: P.tags.own, tagIcon: 'user', visible: true, problem: null,
            isDefault: printers.some(member => member.name === s.defaultPrinter), onlyHere: [], keepsOwn: [], entry,
          });
          continue;
        }
        const project = p.origin === "project", bundle = p.origin === "bundle";
        // Its template sits in a vendor package the slicer deletes at its next start.
        const packageGone = !!p.package && !s.packages.has(p.package);
        const visible = p.visible && !packageGone;
        const problem = T.profileProblems[p.problem];
        out.push({
          id: "own:" + p.name, system: false, model: p.model, name: p.name, label: plainName(p.name), bundle,
          sub: p.based_on ? T.filaments.template(p.based_on_found ? printerText(i, p.based_on) : p.based_on) : "",
          cover: p.cover, printers: visible ? [{ name: p.name, variant: p.variant }] : [],
          tag: bundle ? p.bundle : project ? T.printerOrigins.project : P.tags.own,
          tagIcon: bundle ? "package" : project ? "file" : "user",
          visible, package: p.package, unresolved: p.status === "unresolved",
          problem: packageGone ? P.packageGone(p.package) : problem ? problem(p) : null,
          isDefault: p.name === s.defaultPrinter, onlyHere: mine(p.only_here), keepsOwn: [],
          entry: visible ? i.models.find((x) => x.own && x.model === p.name) : null,
        });
      }
      // The printer the slicer has chosen on top, so it is found among many (the user's colleague:
      // 30 printers); by the file, so a card does not jump when another one is queued.
      const first = (c) => (c.entry?.printers.some((x) => x.selected) ? 0 : 1);
      return out.sort((a, b) => first(a) - first(b)).map((c) => {
        // The printer of the printer part: an own printer with an address of its own in the
        // slicer by its name (camera.remember_slicer_hosts), else the model's.
        const m = c.entry || null;
        const groupHosts = c.group ? [...new Set(m.printers.map(p => hosts.value?.[p.name]?.host).filter(Boolean))] : [];
        const groupHostKey = c.group && groupHosts.length === 1 && m.printers.every(p => hosts.value?.[p.name]?.host === groupHosts[0]) ? m.printers[0].name : null;
        const hostKey = c.group ? groupHostKey : hosts.value?.[c.name] ? c.name : c.model || c.name;
        return {
          ...c, idx: m ? i.models.findIndex(entry => entry.model === m.model) : -1, active: !!m && m.model === ui.printer, inSlicer: first(c) === 0,
          now: m ? nowOf(m, s.defaultPrinter) : null,
          // The one the slicer starts with marked; queued while it is not written yet.
          nozzles: m ? m.printers.filter((x) => x.variant || x.nozzle_diameter?.length).map((x) => ({
            name: x.name, text: variantText(x), start: x.name === s.defaultPrinter, queued: x.name === s.defaultPrinter && !x.selected,
          })) : [],
          hostKey, host: hosts.value?.[hostKey]?.host || "",
        };
      });
    });
    // The printer OrcaOne works with, chosen in the top bar (app.js): a click on a card chooses it.
    const choose = (c) => { if (c.entry) ui.printer = c.entry.model; };
    // A nozzle chooses that printer profile in the slicer, as its printer list does: into the change
    // list, written with "Übernehmen". "Filamente" and "Prozesse" follow it.
    function pickNozzle(c, z) {
      const s = state.value;
      if (readOnly.value) return;
      chosenNozzle[nozzleKey(inst.value, c.entry)] = z.name;
      choose(c);
      if (z.name === s.defaultPrinter) return;
      s.defaultPrinter = z.name;
      // Back to what the file says: nothing queued, so nothing to say.
      if (!c.entry.printers.some((x) => x.name === z.name && x.selected)) flash(P.queued.default(printerText(inst.value, z.name)));
    }
    // To the printer part with this printer; without an address its form opens there.
    function toMachine(c) {
      if (c.host) ui.printer = c.hostKey;
      else ui.addressFor = c.hostKey;
      go(null, hashOf("drucker", inst.value.id));
    }

    // ------------------------------------------------------------ details: every nozzle, on demand
    const allHeads = reactive({});  // card id -> every filament slot shown
    const open = reactive({});   // card id -> details shown; unset: open at the printer the slicer has chosen
    const shown = reactive({});  // card id -> { preset, kind: "procs" | "fils" }: the names shown below
    // Per card with details open: each nozzle with the process last chosen there, its processes and
    // the filaments the slicer shows there.
    const isOpen = (c) => open[c.id] ?? c.inSlicer;
    const details = computed(() => {
      const out = {}, start = state.value.defaultPrinter;
      for (const c of cards.value) {
        if (!isOpen(c) || !c.entry) continue;
        out[c.id] = c.entry.printers.filter((p) => p.variant || p.nozzle_diameter?.length).map((p) => ({
          name: p.name, text: variantText(p), start: p.name === start, last: p.process, procs: p.processes || [],
          fils: inst.value.filaments.filter((f) => f.printers?.[p.name]?.status === "visible"),
        }));
      }
      return out;
    });
    const toggleList = (c, z, kind) => {
      const cur = shown[c.id];
      shown[c.id] = cur && cur.preset === z.name && cur.kind === kind ? null : { preset: z.name, kind };
    };
    // The names shown per card: processes, or filaments by where they come from.
    const lists = computed(() => {
      const out = {};
      for (const [id, l] of Object.entries(shown)) {
        const z = l && details.value[id]?.find((x) => x.name === l.preset);
        if (!z) continue;
        const groups = new Map();
        if (l.kind === "fils") {
          for (const f of z.fils) {
            const g = originGroup(f);
            if (!groups.has(g.key)) groups.set(g.key, { label: g.label, items: [] });
            groups.get(g.key).items.push(f);
          }
        }
        out[id] = { kind: l.kind, z, groups: [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, g]) => g) };
      }
      return out;
    });
    // On to "Filamente" or "Prozesse" at that nozzle; with a profile, that one opened there.
    function openAt(c, preset, page, focus = null) {
      chosenNozzle[nozzleKey(inst.value, c.entry)] = preset;
      if (page === "filamente") ui.filamentFocus = focus;
      else ui.processFocus = focus;
      choose(c);
      go(null, to(page, c.idx));
    }
    // "⋯": remove, rarely needed.
    const menuFor = ref(null);  // card id
    const outside = (ev) => { if (menuFor.value && !(ev.target instanceof Element && ev.target.closest(".home-pcard-menu"))) menuFor.value = null; };
    onMounted(() => document.addEventListener("pointerdown", outside));
    onUnmounted(() => document.removeEventListener("pointerdown", outside));

    // Removing the last model of a vendor: SnOrca and Orca up to 2.4.2 delete its package at the
    // next start, own printers on top of it become invisible (FINDINGS 4.2).
    function dropsPackage(c) {
      if (!c.system || !c.dropsPackage) return false;
      const s = state.value;
      return !inst.value.printers_page.system.some((m) => m.model !== c.model && m.origin === c.package && s.models.has(m.model));
    }
    const lostOwn = (c) => dropsPackage(c) ? cards.value.filter((x) => !x.system && x.visible && x.package === c.package) : [];
    // What stays visible without c; at least one printer stays.
    const restOf = (c) => {
      const lost = new Set(lostOwn(c).map((x) => x.id));
      return cards.value.filter((x) => x.id !== c.id && x.visible && !lost.has(x.id));
    };
    const locked = (c) => c.visible && restOf(c).length < 1;
    const defaultCard = computed(() => cards.value.find((c) => c.isDefault) || null);
    const nozzleList = (c) => c.printers.filter((p) => p.variant).map((p) => nozzleLabel(p.variant)).join(" · ");
    // When the default printer goes, the slicer starts with another one; OrcaOne names it in the plan.
    function nextDefault(card) {
      const rest = restOf(card).filter((c) => c.printers.length);
      if (!rest.length) return null;
      const c = rest[0];
      return (c.printers.find((p) => p.variant === "0.4") || c.printers[0]).name;
    }

    // ------------------------------------------------------------ clean up
    // "orca_presets" keeps the last choice per printer and is never cleaned up (FINDINGS 4.3, 4.9).
    const dead = computed(() => inst.value.printers_page.dead_entries.filter((d) => state.value.dead.includes(d.machine)));
    function clean() {
      if (readOnly.value || !dead.value.length) return;
      state.value.dead = [];
      flash(P.queued.clean);
    }

    // ------------------------------------------------------------ panel
    const panel = ref(null);  // { type: "remove", id }
    const along = reactive(new Set());
    let lastFocus = null;
    const pcard = computed(() => panel.value && cards.value.find((c) => c.id === panel.value.id) || null);
    function openPanel(p) {
      if (!panel.value) lastFocus = document.activeElement;
      panel.value = p;
      nextTick(() => document.getElementById("panel-title")?.focus());
    }
    function closePanel() {
      panel.value = null;
      // The card may be gone after removing it; then the page title takes the focus.
      const target = lastFocus && document.contains(lastFocus) ? lastFocus : document.getElementById("page-title");
      target?.focus();
      lastFocus = null;
    }
    watch(() => props.instId, () => { panel.value = null; lastFocus = null; });
    // Own profiles that belong to this printer only are ticked, unless an own printer built on it
    // stays: it may still use them (FINDINGS 4.6, compatibility over the direct parent).
    function openRemove(c) {
      menuFor.value = null;
      if (readOnly.value || locked(c) || c.bundle) return;
      along.clear();
      if (!c.keepsOwn.length) c.onlyHere.forEach((x) => along.add(x.name));
      openPanel({ type: "remove", id: c.id });
    }
    const toggleAlong = (name) => along.has(name) ? along.delete(name) : along.add(name);
    const plan = computed(() => {
      const c = pcard.value;
      if (!c || !panel.value || panel.value.type !== "remove") return [];
      const out = [];
      const drops = dropsPackage(c);
      if (c.system) {
        // SnOrca switches all nozzles of a model back on at start, so only whole models go (FINDINGS 12).
        out.push({ icon: "minus", cls: "ch-off", name: c.name, verb: P.plan.switchedOff, sub: P.plan.allNozzles(nozzleList(c), drops) });
      } else {
        out.push({ icon: "trash", cls: "ch-delete", name: c.name, verb: P.plan.deleted, sub: P.plan.fileGoes });
      }
      if (drops) out.push({ icon: "factory", cls: "ch-delete", name: P.plan.packageName(c.package), verb: P.plan.packageDeleted, sub: P.plan.packageWhy });
      if (c.isDefault) {
        const next = nextDefault(c);
        if (next) out.push({ icon: "star", cls: "ch-on", name: printerText(inst.value, next), verb: P.plan.becomesDefault, sub: P.plan.startsWith });
      }
      if (drops) {
        for (const x of lostOwn(c)) out.push({ icon: "user", cls: "ch-delete", name: x.name, verb: P.plan.invisible, sub: P.plan.invisibleWhy });
      } else {
        // Own printers built on a model stay visible without it (Preset::set_visible_from_appconfig
        // leaves profiles without vendor alone). The ticked profiles below are part of the plan, too.
        for (const n of c.keepsOwn) out.push({ icon: "user", cls: "ch-on", name: n, verb: P.plan.stays, sub: P.plan.staysWhy });
      }
      return out;
    });
    function remove() {
      const c = pcard.value, s = state.value;
      if (!c || readOnly.value || locked(c)) return;
      const next = c.isDefault ? nextDefault(c) : null, drops = dropsPackage(c);
      if (c.system) s.models.delete(c.model);
      else s.own.delete(c.name);
      if (drops) s.packages.delete(c.package);
      for (const n of along) s.own.delete(n);
      if (next) s.defaultPrinter = next;
      const name = c.name, system = c.system;
      closePanel();
      flash(system ? P.queued.remove(name) : P.queued.delete(name));
    }
    const panelTitle = computed(() => (pcard.value && !pcard.value.system ? P.deleteTitle : P.removeTitle));
    const onKey = (ev) => {
      if (ev.key !== "Escape") return;
      if (menuFor.value) menuFor.value = null;
      else if (panel.value) closePanel();
    };
    onMounted(() => window.addEventListener("keydown", onKey));
    onUnmounted(() => window.removeEventListener("keydown", onKey));

    // ------------------------------------------------------------ the tiles
    const backups = computed(() => BACKUPS[inst.value.id]?.backups || []);
    const newestBackup = computed(() => backups.value.reduce((a, b) => (!a || b.created > a.created ? b : a), null));
    const news = computed(() => NEWS[inst.value.id] || 0);

    const to = (page, idx = null) => hashOf(page, inst.value.id, idx);
    return {
      T, O, P, KIND_ICON, INSTANCES, inst, state, readOnly, isU1, own, logo, facts, cards, choose, pickNozzle, toMachine, locked, defaultCard,
      open, isOpen, shown, details, lists, toggleList, openAt, menuFor, short, allHeads, HEADS,
      dead, clean, panel, along, pcard, plan, panelTitle, openRemove, toggleAlong, remove, closePanel,
      backups, newestBackup, news, SPOOLS, NO_COLOUR, to, go, hashOf, plainName, whenText, profileSub,
    };
  },

  template: `
    <div :class="['page-host', { 'with-panel': panel }]">
      <div class="page">
        <div class="page-head">
          <h1 id="page-title" tabindex="-1">{{ O.title }}</h1>
        </div>

        <!-- The installation of the tab above in short: what it holds, its data folder, whether it runs -->
        <section class="home-slicer" :aria-label="inst.slicer">
          <span :class="['slicer-logo', 'slicer-logo--' + inst.kind]" aria-hidden="true">{{ logo }}</span>
          <span class="home-slicer-text">
            <strong>{{ inst.slicer }}</strong>
            <small>{{ facts }}</small>
            <small class="mono home-slicer-path">{{ inst.path }}</small>
          </span>
          <run-status :inst="inst"/>
        </section>
        <p v-if="readOnly" class="banner">{{ T.busy(inst) }} {{ T.closeToChange }}</p>

        <!-- All printers of that slicer, with what they are in it -->
        <div class="section-head">
          <h2>{{ O.printersIn(inst.slicer) }}</h2>
          <span class="sub">{{ O.printerCount(cards.length) }}</span>
          <!-- How current the choices are (the user: "Ich drucke aktuell nur PLA", but the slicer here
               last saved the day before): the time of its .conf -->
          <span v-if="inst.conf_saved" class="sub" :title="O.savedWhy(inst.slicer)">{{ O.saved(whenText(new Date(inst.conf_saved))) }}</span>
        </div>
        <p v-if="state.defaultPrinter && !defaultCard" class="alert">{{ P.defaultGone }}</p>
        <div v-if="cards.length" class="home-printers">
          <article v-for="c in cards" :key="c.id" :class="['home-pcard', { 'is-active': c.active }]" :aria-label="c.label">
            <div class="home-pcard-top">
              <button class="home-pcard-img" type="button" :title="P.makeActive" :disabled="!c.entry" @click="choose(c)">
                <img :src="c.cover" alt="" width="56" height="56" :class="{ dim: !c.visible }"></button>
              <div class="home-pcard-title">
                <h3><button class="card-pick" type="button" :aria-pressed="c.active ? 'true' : 'false'" :title="P.makeActive"
                            :disabled="!c.entry" @click="choose(c)">{{ c.label }}</button>
                  <span v-if="c.isDefault" class="tag tag-default" :title="O.startWhy(inst.slicer)"><ui-icon name="star" :size="14"/>{{ O.start }}</span></h3>
                <p class="home-pcard-sub">{{ [c.tag, c.sub, c.host].filter(Boolean).join(" · ") }}</p>
              </div>
              <div class="home-pcard-links">
                <a v-if="c.idx >= 0" class="btn" :href="to('filamente', c.idx)" @click="go($event, to('filamente', c.idx))"><ui-icon name="spool"/>{{ T.nav.pages.filamente }}</a>
                <a v-if="c.idx >= 0" class="btn" :href="to('prozesse', c.idx)" @click="go($event, to('prozesse', c.idx))"><ui-icon name="layers"/>{{ T.nav.pages.prozesse }}</a>
                <a v-if="!c.group || c.host" class="btn" :href="to('drucker')" :title="c.host ? null : P.connectWhy" @click.prevent="toMachine(c)">
                  <ui-icon :name="c.host ? 'printer' : 'network'"/>{{ c.host ? O.toMachine : O.connect }}</a>
                <div v-if="!c.group" class="home-pcard-menu">
                  <button class="btn btn-icon" type="button" :aria-label="O.menu" :title="O.menu" aria-haspopup="menu"
                          :aria-expanded="menuFor === c.id ? 'true' : 'false'" @click="menuFor = menuFor === c.id ? null : c.id"><ui-icon name="more"/></button>
                  <div v-if="menuFor === c.id" class="inst-menu" role="menu">
                    <button class="inst-item" type="button" role="menuitem" :disabled="readOnly || locked(c) || c.bundle"
                            :title="c.bundle ? P.bundleLocked : locked(c) ? P.lastOne : null" @click="openRemove(c)">
                      <ui-icon :name="locked(c) || c.bundle ? 'lock' : 'trash'"/>{{ c.system ? P.remove : P.delete }}</button>
                  </div>
                </div>
              </div>
            </div>
            <!-- What is set in the slicer, at first glance: every nozzle, the chosen one marked, a click
                 chooses another there; the process and the filaments lead to their pages -->
            <div v-if="c.entry" class="home-now">
              <span v-if="c.nozzles.length" class="home-now-group" role="group" :aria-label="O.labels.nozzle">
                <small>{{ O.labels.nozzle }}</small>
                <span class="home-nozzles-pick">
                  <button v-for="z in c.nozzles" :key="z.name" type="button" :class="['home-nozzle', { 'is-start': z.start, 'is-queued': z.queued }]"
                          :aria-pressed="z.start ? 'true' : 'false'" :disabled="readOnly"
                          :title="z.queued ? O.nozzleQueued : z.start ? O.start : O.nozzlePick(inst.slicer)" @click="pickNozzle(c, z)">{{ z.text }}</button>
                </span>
                <small>mm</small>
              </span>
              <template v-if="c.now">
                <span v-if="!c.now.start" class="home-now-label">{{ O.lastAt(c.now.nozzle) }}</span>
                <span v-if="c.now.process" class="home-now-group"><small>{{ O.labels.process }}</small>
                  <button class="home-badge" type="button" :title="O.openIn(plainName(c.now.process), T.nav.pages.prozesse)"
                          @click="openAt(c, c.now.preset, 'prozesse', c.now.process)">{{ short(c.now.process) }}</button></span>
                <span v-if="c.now.heads.length" class="home-now-group"><small>{{ c.now.heads.length > 1 ? O.labels.filaments : O.labels.filament }}</small>
                  <button v-for="(h, k) in (allHeads[c.id] ? c.now.heads : c.now.heads.slice(0, HEADS))" :key="k" class="home-badge" type="button"
                          :title="O.openIn(O.slot(k + 1, plainName(h.name)), T.nav.pages.filamente)" @click="openAt(c, c.now.preset, 'filamente', h.name)">
                    <small v-if="c.now.heads.length > 1" class="home-slot">{{ k + 1 }}</small><spool-icon :colour="h.colour" :size="16"/>{{ h.label }}</button>
                  <button v-if="c.now.heads.length > HEADS" class="link home-more-heads" type="button" :aria-expanded="allHeads[c.id] ? 'true' : 'false'"
                          @click="allHeads[c.id] = !allHeads[c.id]">{{ allHeads[c.id] ? O.fewer : O.more(c.now.heads.length - HEADS) }}</button></span>
              </template>
              <span v-else class="home-now-label">{{ O.neverChosen }}</span>
            </div>
            <p v-if="!c.visible" class="card-problem" :title="c.problem"><ui-icon name="info" :size="16"/>{{ c.unresolved ? P.unresolved : P.notVisible }}</p>
            <!-- More on demand: every nozzle with its processes and filaments -->
            <template v-if="c.entry">
              <button class="link home-more" type="button" :aria-expanded="isOpen(c) ? 'true' : 'false'" @click="open[c.id] = !isOpen(c)">
                <ui-icon :name="isOpen(c) ? 'chevronDown' : 'chevron'" :size="14"/>{{ isOpen(c) ? O.detailsClose : O.details }}</button>
              <div v-if="details[c.id]" class="home-details">
                <div class="home-nozzles-scroll">
                  <table class="home-nozzles">
                    <thead><tr><th scope="col">{{ O.labels.nozzle }}</th>
                      <th v-for="z in details[c.id]" :key="z.name" scope="col" :class="{ 'is-start': z.start }" :title="z.start ? O.start : null">
                        {{ z.text }} mm<ui-icon v-if="z.start" name="star" :size="12"/></th></tr></thead>
                    <tbody>
                      <tr><th scope="row">{{ O.rows.last }}</th>
                        <td v-for="z in details[c.id]" :key="z.name" :class="{ 'is-start': z.start }">{{ short(z.last) || "–" }}</td></tr>
                      <tr v-for="kind in ['procs', 'fils']" :key="kind"><th scope="row">{{ O.rows[kind] }}</th>
                        <td v-for="z in details[c.id]" :key="z.name" :class="{ 'is-start': z.start }">
                          <button :class="['home-count', { 'is-open': shown[c.id]?.preset === z.name && shown[c.id]?.kind === kind }]" type="button"
                                  :aria-expanded="shown[c.id]?.preset === z.name && shown[c.id]?.kind === kind ? 'true' : 'false'"
                                  :disabled="!z[kind].length" @click="toggleList(c, z, kind)">{{ z[kind].length }}<ui-icon name="chevronDown" :size="12"/></button></td></tr>
                    </tbody>
                  </table>
                </div>
                <div v-if="lists[c.id]" class="home-list">
                  <template v-if="lists[c.id].kind === 'procs'">
                    <p class="home-list-title">{{ O.procsAt(lists[c.id].z.text) }}</p>
                    <p class="home-chips">
                      <button v-for="n in lists[c.id].z.procs" :key="n" type="button" :class="['home-chip', { 'is-last': n === lists[c.id].z.last }]"
                              :title="O.openIn(plainName(n), T.nav.pages.prozesse)" @click="openAt(c, lists[c.id].z.name, 'prozesse', n)">{{ short(n) }}</button>
                    </p>
                    <p><button class="link" type="button" @click="openAt(c, lists[c.id].z.name, 'prozesse')">{{ O.openPage(T.nav.pages.prozesse) }}</button></p>
                  </template>
                  <template v-else>
                    <p class="home-list-title">{{ O.filsAt(lists[c.id].z.text) }}</p>
                    <div v-for="g in lists[c.id].groups" :key="g.label" class="home-list-group">
                      <small>{{ g.label }}</small>
                      <p class="home-chips">
                        <button v-for="f in g.items" :key="f.name" type="button" class="home-chip" :title="O.openIn(plainName(f.name), T.nav.pages.filamente)"
                                @click="openAt(c, lists[c.id].z.name, 'filamente', f.name)"><spool-icon :colour="f.colour || NO_COLOUR" :size="14"/>{{ short(f.name) }}</button>
                      </p>
                    </div>
                    <p><button class="link" type="button" @click="openAt(c, lists[c.id].z.name, 'filamente')">{{ O.openPage(T.nav.pages.filamente) }}</button></p>
                  </template>
                </div>
              </div>
            </template>
          </article>
        </div>
        <p v-else class="empty">{{ O.noPrinter }}</p>

        <!-- What the slicer remembers of printers that are gone; only when there is something -->
        <section v-if="dead.length" class="box clean-box" aria-labelledby="clean-h">
          <div class="box-head"><h2 id="clean-h">{{ P.clean.title }}</h2></div>
          <p class="note">{{ P.clean.intro }}</p>
          <ul class="plain-list">
            <li v-for="d in dead" :key="d.machine">
              <span class="ch-off"><ui-icon name="printer"/></span>
              <span class="grow"><strong>{{ d.machine }}</strong><small>{{ T.deadEntries[d.reason] }}</small></span>
            </li>
          </ul>
          <div class="actions">
            <span class="safe-note inline"><ui-icon name="backup"/>{{ P.safe }}</span>
            <button class="btn btn-primary right" type="button" :disabled="readOnly" @click="clean"><ui-icon name="broom"/>{{ P.clean.button }}</button>
          </div>
        </section>

        <!-- Tiles: the whole tile leads to its page, the small links below it further on -->
        <div class="home-tiles">
          <section class="home-tile" aria-labelledby="tile-own">
            <h2 id="tile-own" class="home-tile-title"><a class="home-tile-link" :href="to('filamente')" @click="go($event, to('filamente'))"><ui-icon name="spool"/>{{ O.ownTitle }}</a></h2>
            <p class="home-tile-num">{{ own.length }}</p>
            <div class="home-tile-spools">
              <span v-for="f in own.slice(0, SPOOLS)" :key="f.name" :title="plainName(f.name)"><spool-icon :colour="f.colour || NO_COLOUR" :size="26"/></span>
              <small v-if="own.length > SPOOLS">{{ O.more(own.length - SPOOLS) }}</small>
            </div>
            <p class="home-tile-more">
              <a :href="to('import')" @click="go($event, to('import'))">{{ T.nav.pages.import }}</a>
              <a v-if="isU1" :href="to('kalibrieren')" @click="go($event, to('kalibrieren'))">{{ T.nav.pages.kalibrieren }}</a>
              <a v-if="INSTANCES.length > 1" :href="to('transfer')" @click="go($event, to('transfer'))">{{ T.nav.pages.transfer }}</a>
            </p>
          </section>
          <section class="home-tile" aria-labelledby="tile-backups">
            <h2 id="tile-backups" class="home-tile-title"><a class="home-tile-link" :href="to('sicherungen')" @click="go($event, to('sicherungen'))"><ui-icon name="backup"/>{{ T.nav.pages.sicherungen }}</a></h2>
            <p class="home-tile-num">{{ backups.length }}</p>
            <p class="home-tile-sub">{{ newestBackup ? O.lastBackup(whenText(new Date(newestBackup.created))) : O.noBackup }}</p>
          </section>
          <section :class="['home-tile', { 'is-news': news }]" aria-labelledby="tile-news">
            <h2 id="tile-news" class="home-tile-title"><a class="home-tile-link" :href="to('aenderungen')" @click="go($event, to('aenderungen'))"><ui-icon name="diff"/>{{ T.nav.pages.aenderungen }}</a></h2>
            <p class="home-tile-num">{{ news }}</p>
            <p class="home-tile-sub">{{ O.sinceLast }}</p>
          </section>
        </div>

      </div>
    </div>

    <aside v-if="panel" class="panel" aria-labelledby="panel-title">
      <div class="panel-head">
        <h2 id="panel-title" tabindex="-1">{{ panelTitle }}</h2>
        <button class="icon-btn" type="button" :aria-label="T.close" @click="closePanel"><ui-icon name="close"/></button>
      </div>
      <div class="panel-body">
        <p v-if="!pcard" class="note">{{ P.gone }}</p>
        <template v-else>
          <div class="hero">
            <img class="hero-img" :src="pcard.cover" alt="" width="96" height="96" :class="{ dim: !pcard.visible }">
            <div class="hero-text">
              <p class="hero-name">{{ pcard.label }}</p>
              <p v-if="pcard.sub" class="hero-sub">{{ pcard.sub }}</p>
              <p class="tags hero-tags">
                <span v-if="pcard.isDefault" class="tag tag-default"><ui-icon name="star" :size="14"/>{{ O.start }}</span>
                <span class="tag"><ui-icon :name="pcard.tagIcon" :size="14"/>{{ pcard.tag }}</span>
              </p>
            </div>
          </div>

          <template v-if="panel.type === 'remove'">
            <p v-if="pcard.problem" class="alert">{{ pcard.problem }}</p>
            <h3>{{ P.plan.title }}</h3>
            <ul class="plain-list">
              <li v-for="(it, n) in plan" :key="n">
                <span :class="it.cls"><ui-icon :name="it.icon"/></span>
                <span class="grow"><strong>{{ it.name }}</strong> {{ it.verb }}<small>{{ it.sub }}</small></span>
              </li>
            </ul>
            <template v-if="pcard.onlyHere.length">
              <h3>{{ P.along.title }}</h3>
              <p class="note">{{ P.along.intro }}</p>
              <ul class="plain-list">
                <li v-for="x in pcard.onlyHere" :key="x.name">
                  <label class="along">
                    <input type="checkbox" :checked="along.has(x.name)" @change="toggleAlong(x.name)">
                    <ui-icon :name="KIND_ICON[x.kind]"/>
                    <span class="grow"><strong>{{ x.name }}</strong><small>{{ profileSub(x) }}</small></span>
                  </label>
                </li>
              </ul>
              <p v-if="pcard.keepsOwn.length" class="note">{{ P.along.notTicked(pcard.keepsOwn) }}</p>
            </template>
            <p class="safe-note"><ui-icon name="backup"/><span>{{ P.safeRestore.before }}<a :href="hashOf('sicherungen', inst.id)" @click="go($event, hashOf('sicherungen', inst.id))">{{ T.nav.pages.sicherungen }}</a>{{ P.safeRestore.after }}</span></p>
            <div class="actions">
              <button class="btn" type="button" @click="closePanel">{{ T.cancel }}</button>
              <button class="btn btn-danger-solid right" type="button" :disabled="readOnly || locked(pcard)" @click="remove">
                <ui-icon name="trash"/>{{ pcard.system ? P.remove : P.delete }}
              </button>
            </div>
          </template>
        </template>
      </div>
    </aside>
  `,
};
