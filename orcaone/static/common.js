// Shared data, state, icons and small components for all pages.
// The data comes live from GET /api/data (orcaone/overview.py): load() fetches it at the start
// and again for "Neu einlesen". Pages are plain component objects; app.js picks one by the hash
// route and mounts it fresh for every route and every load.
import { T, plainName, SETTINGS } from "./texts.js";
import { api } from "./api.js";

const { reactive, ref, shallowReactive, computed } = Vue;

export const LOCALE = T.locale;
// The decimal sign of the chosen language, for values as the profiles write them: "0.4" -> "0,4".
export const DECIMAL = (1.5).toLocaleString(LOCALE).charAt(1);

// ------------------------------------------------------------ data
// shallowReactive: a load replaces the list, the megabyte of nested data inside stays plain.
export const INSTANCES = shallowReactive([]);
// Installations OrcaOne found but could not read (failed[] of GET /api/data); the others still show.
export const FAILED = shallowReactive([]);
// editable_fields with label and unit from texts.js, for the filament form.
export const FIELDS = shallowReactive([]);
// status: "loading" until the first answer, then "ready" or "error". version counts the loads,
// it is part of the page key in app.js.
export const loadState = reactive({ status: "loading", error: null, busy: false, generated: null, version: 0 });

// ------------------------------------------------------------ routing
// #/<page>/<installation>, for one printer #/filamente/<installation>/<model index> (the same
// for "prozesse"). The installation is part of the address, so a reload stays with it.
export const PAGE_IDS = ["uebersicht", "zusammenhaenge", "profile-editor", "profile-workbench", "filamente", "kalibrieren", "transfer", "vergleichen", "import", "prozesse", "drucker", "status", "diagramme", "fehler", "steuern", "hoehenkarte", "druck3d", "druck2d", "dateien", "kamera", "konsole", "druckerlogs", "ssh", "netzwerk", "aenderungen", "bereinigen", "sicherungen", "slicer", "details", "logs", "lizenz"];
// Pages that show one printer at a time: the menu keeps the printer when switching between them.
export const PRINTER_PAGES = ["filamente", "prozesse"];
// The printer models OrcaOne knows as a Snapmaker U1: camera, live values, calibration and the
// search in the LAN are for them only (orcaone/camera.py, U1_MODELS).
export const U1_MODELS = ["Snapmaker U1"];

// The two parts of OrcaOne (the user's wish of 25.09.2026, the mix of both was confusing): "Slicer"
// with the slicers' profiles and "Drucker" with the printers themselves, each with its own menu, top bar and first page.
// A start without a page begins in the part used last (SETTINGS.area, app.js keeps it up to date).
export const AREA_START = { slicer: "uebersicht", printer: "drucker" };

export function parseHash(hash) {
  const [page, instId, idx] = hash.replace(/^#\/?/, "").split("/");
  if (!PAGE_IDS.includes(page)) return { page: AREA_START[SETTINGS.area] || AREA_START.slicer, instId: null, modelIdx: null };
  const inst = INSTANCES.find((i) => i.id === instId) || null;
  const ok = PRINTER_PAGES.includes(page) && !!inst && /^\d+$/.test(idx || "") && !!inst.models[+idx];
  return { page, instId: inst ? inst.id : null, modelIdx: ok ? +idx : null };
}
export const hashOf = (page, instId, modelIdx = null) =>
  "#/" + page + (instId ? "/" + instId : "") + (modelIdx === null ? "" : "/" + modelIdx);

export const route = ref(parseHash(location.hash));

export function syncRoute(hash = location.hash) {
  const next = parseHash(hash), cur = route.value;
  if (next.page !== cur.page || next.instId !== cur.instId || next.modelIdx !== cur.modelIdx) route.value = next;
}

// A page with input that is not saved yet (the filament form) sets a guard. The guard gets the
// step that leaves the page and runs it, after asking if needed. Back and forward in the
// browser do not pass here.
let leaveGuard = null;
export const setLeaveGuard = (fn) => { leaveGuard = fn; };
export const clearLeaveGuard = (fn) => { if (leaveGuard === fn) leaveGuard = null; };
export const leave = (step) => (leaveGuard ? leaveGuard(step) : step());

// Internal links set the route right away, so the view never depends on the "hashchange"
// event alone. Back, forward and typed URLs still arrive through the listener in app.js.
export function go(ev, hash) {
  if (ev && (ev.button > 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey)) return;  // new tab or window
  if (ev) ev.preventDefault();
  leave(() => {
    if (location.hash !== hash) location.hash = hash;
    syncRoute(hash);
  });
}

// ------------------------------------------------------------ shared state
// The chosen installation follows the address (app.js).
// detailsFor: a filament the page "Details" opens with (from the page "Filamente"), and
// filamentFocus the other way round: the page "Filamente" shows that filament's row and panel
// (also from "Übersicht"). processFocus: the process the page "Prozesse" opens with (from "Übersicht").
// calibrateFor: the own filament the page "Kalibrieren" opens with.
// printer: the model OrcaOne works with, chosen in the top bar for every page (app.js).
// printFile: the print file "3D Ansicht" and "2D Ansicht" show, one for both (the user's wish of
// 24.09.2026): chosen in the top bar or on "Dateien", set by itself when the printer starts a print
// (app.js). { model, path } of a file on the printer, or { local, size, stamp } of one from this
// computer, which localPrintFile() holds.
// addressFor: the printer the page "Drucker" opens the address form for ("Mit dem Drucker
// verbinden" on "Übersicht"); the printer part itself chooses only printers with an address.
// viewLayer: the layer both stand at, one slider for both (the user: "out of sync" through the menu);
// null for a new file, then both start at the top, as the slicer's preview does.
export const ui = reactive({ instId: null, printer: null, toast: "", detailsFor: null, filamentFocus: null, processFocus: null, calibrateFor: null,
                             printFile: null, viewLayer: null, addressFor: null,
                             // While the printer of the printer part prints: its file stays the print file (app.js).
                             fileLocked: false,
                             // Per printer the folder "Dateien" showed last, while OrcaOne is open: { folder, path }.
                             filesAt: {} });
let localFile = null;
export function setLocalPrintFile(file) {
  if (ui.fileLocked) return flash(T.fileMenu.locked);
  localFile = file;
  ui.printFile = { local: file.name, size: file.size, stamp: file.lastModified };
}
export const localPrintFile = () => localFile;

// The design in use: the one chosen at the bottom of the menu (data-theme on <html>, app.js), else
// the system's. style.css picks its colours the same way (color-scheme, light-dark()).
export const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
export const isDark = () => (document.documentElement.dataset.theme || (darkQuery.matches ? "dark" : "light")) === "dark";

// One word per state on every page.
export function statusText(inst, short = false) {
  if (!inst.running) return T.status.closed;
  const maybe = inst.running_reason?.code === "process_unmapped";
  // Short in the top bar (the user: "view only" there was too much text); the tooltip says it all.
  if (short) return maybe ? T.status.maybeRunningShort : T.status.runningShort;
  return maybe ? T.status.maybeRunning : T.status.running;
}

// Why OrcaOne may not write to this installation now: a code of T.blocked, or null. The backend
// checks the same, in the same order, when it plans and applies (environment_block in
// orcaone/operations.py); checked here as well, so "Übernehmen" is off right away. Not with a
// .conf OrcaOne cannot read, and never while the slicer runs (hard rule 3). A restore writes the
// whole .conf back, so a broken one does not stop it: it is the way to repair it.
export function writeBlock(inst, restore = false) {
  if (inst.problems.includes("conf_unreadable") && !restore) return "conf_unreadable";
  if (inst.running) return inst.running_reason?.code === "process_unmapped" ? "slicer_maybe_running" : "slicer_running";
  return null;
}

// Entries of the "filaments" list that fit no printer set up (the 8 × @J1, @Dual … the wizard
// took along, FINDINGS 4.6), also those without a profile of that name: the backend removes a
// listed name either way. The page "Slicer" offers to hide them.
export const unusedListNames = (inst) => inst.without_printer.map((w) => w.name);

// What the pages "Drucker" and "Slicer" change, per installation: own profiles (files in
// user/), the printer models switched on and the vendor packages in system/, the default
// printer, the stale "orca_presets" entries and the unused "filaments" entries (in the .conf).
// Memory only: the change list collects it, ops.js turns it into the ops of POST /plan.
function initialLive(inst) {
  const pp = inst.printers_page;
  const own = new Set(inst.filaments.filter((f) => f.origin_kind === "user").map((f) => f.name));
  for (const p of pp.own) own.add(p.name);
  for (const x of [...pp.system, ...pp.own].flatMap((c) => c.only_here)) own.add(x.name);
  return {
    own,
    models: new Set(pp.system.map((m) => m.model)),
    packages: new Set(pp.system.map((m) => m.origin)),
    defaultPrinter: pp.default_printer.name,
    dead: pp.dead_entries.map((d) => d.machine),
    hideUnused: false,
  };
}
const copyLive = (s) => ({
  own: new Set(s.own), models: new Set(s.models), packages: new Set(s.packages),
  defaultPrinter: s.defaultPrinter, dead: [...s.dead], hideUnused: s.hideUnused,
});
export const live = reactive({});

// A printer card shows while the slicer shows the printer: a model switched on in "models", an
// own printer while its file and its vendor package are there. "Entfernen" on the page
// "Drucker" takes it away before it is written.
export function modelShown(inst, m) {
  const s = live[inst.id];
  if (m.group_id) return m.printers.some(p => s.own.has(p.name));
  return m.own ? s.own.has(m.model) && (!m.origin || s.packages.has(m.origin)) : s.models.has(m.model);
}
// The printers of an installation for the choice in the top bar, and the one the slicer starts
// with; its name as on the cards: "MyKlipper" rather than "Generic Klipper Printer".
export const printerModels = (inst) => (inst ? inst.models.filter((m) => modelShown(inst, m)) : []);
export function slicerModel(inst) {
  const models = printerModels(inst), start = live[inst.id]?.defaultPrinter;
  return models.find((m) => m.printers.some((p) => p.name === start)) || models[0] || null;
}
export const modelName = (m) => (m ? m.display_name || printerShortName(m.printers[0]?.name || m.model) : "");
// A printer model of the chosen installation, else of any: the printer part does not depend on
// one installation, but names and pictures come from there.
export function anyModel(model) {
  for (const i of [INSTANCES.find((x) => x.id === ui.instId), ...INSTANCES]) {
    const m = i?.models.find((x) => x.model === model);
    if (m) return m;
  }
  return null;
}
// Stand-in logo of a slicer from its capital letters: "Snapmaker Orca" -> "SO", "OrcaSlicer" -> "OS".
export const slicerLogo = (name) => (name.match(/[A-Z]/g) || [name[0] || "?"]).slice(0, 2).join("");
// The model a printer's network address goes by (camera.printers()): an own printer shares the one
// of the model it is built on, as the slicers keep print_host (overview.py).
export const addressKey = (m) => (m.own ? m.based_on || m.model : m.model);
// The installations that have a printer model set up (the user: the printer part must still show
// which printer is in which slicer), with its nozzles there and whether the slicer starts with it.
export function slicersOf(model) {
  return INSTANCES.flatMap((i) => {
    const m = printerModels(i).find((x) => addressKey(x) === model);
    if (!m) return [];
    const start = live[i.id]?.defaultPrinter;
    return [{ id: i.id, slicer: i.slicer, nozzles: m.printers.map((p) => p.variant && nozzleLabel(p.variant)).filter(Boolean).join(" · "),
              isDefault: m.printers.some((p) => p.name === start) }];
  });
}
// The printer of the top bar by that name, for the pages that talk to it.
export function activeName() {
  const machine = machines.value.find((x) => x.key === ui.printer);
  if (machine) return machine.name;
  const m = anyModel(ui.printer);
  return m ? modelName(m) : ui.printer || "";
}

// The printers with a network address, by name (camera.printers()): the printers of the printer
// part. The first of a model goes by the model, a second of the same model by a name of its own
// (the user's wish of 25.09.2026). null until read; the page "Drucker" sets it anew when one changes.
export const hosts = ref(null);
// Whether a printer lets SSH in (ssh.probe, no login; the user's wish of 26.09.2026: what needs SSH
// should say so): "on", "off" (on the U1 Root Access is off) or "unknown"; by printer name, looked
// at once a minute at most, or at once when asked to.
export const sshState = reactive({});
const sshLooked = {};
export async function checkSsh(printer, now = false) {
  if (!printer || (!now && Date.now() - (sshLooked[printer] || 0) < 60000)) return;
  sshLooked[printer] = Date.now();
  try {
    sshState[printer] = (await api.sshState(printer)).state;
  } catch {
    sshState[printer] = "unknown";
  }
}
export async function loadHosts() {
  try {
    hosts.value = (await api.printers()).printers;
  } catch {
    if (!hosts.value) hosts.value = {};
  }
  return hosts.value;
}
// The model of a printer of the printer part, for its picture and what OrcaOne knows of it: a U1
// has a camera, files, its light. In the slicer part ui.printer is a model already.
export const modelOf = (key) => hosts.value?.[key]?.model || key;
export const isU1Printer = (key) => U1_MODELS.includes(modelOf(key));
// Klipper's names as a person says them (pages "Status" and "Diagramme"); on the U1 its heads and their
// fans by number (printer.cfg: [fan] and e1_fan … e3_fan cool the part, e0_nozzle_fan … the hotends).
export function partLabel(name, u1) {
  const S = T.monitor, U1 = T.u1;
  const rest = name.includes(" ") ? name.slice(name.indexOf(" ") + 1) : "";
  let m;
  if (name === "heater_bed") return S.names.bed;
  if ((m = /^tmc\w+ stepper_(\w+)$/.exec(name))) return S.names.driver(m[1].toUpperCase());
  if ((m = /^extruder(\d*)$/.exec(name))) return u1 ? U1.head(+(m[1] || 0) + 1) : S.names.extruder(m[1]);
  if (name === "fan") return u1 ? `${U1.head(1)} · ${S.names.partFan}` : S.names.partFan;
  if (u1 && (m = /^e(\d+)_fan$/.exec(rest))) return `${U1.head(+m[1] + 1)} · ${S.names.partFan}`;
  if (u1 && (m = /^e(\d+)_nozzle_fan$/.exec(rest))) return `${U1.head(+m[1] + 1)} · ${S.names.hotendFan}`;
  return S.names[rest] || (rest || name).replace(/_/g, " ");
}
// A microcontroller as a person says it: the main board, on the U1 "mcu eN" the board of head N+1.
export function mcuLabel(name, u1) {
  if (name === "mcu") return T.monitor.mainBoard;
  const m = /^mcu e(\d+)$/.exec(name);
  return m && u1 ? T.u1.head(+m[1] + 1) : name.slice(4);
}
// Those printers for the top bar and the page "Drucker": { key, model, host, name, cover }; key is
// the name ui.printer and the API go by.
export const machines = computed(() => Object.entries(hosts.value || {}).map(([key, h]) => {
  const model = h.model || key, m = anyModel(model);
  return { key, model, host: h.host, name: key !== model ? plainName(key) : m ? modelName(m) : model, cover: m?.cover || "assets/printer-placeholder.svg" };
}));

// Heading of a profile in the lists of the pages "Details" and "Übertragen", as in the tree on
// "Filamente": own ones, bundles, then per maker and, for filaments, brand. key sorts the headings.
export function originGroup(f) {
  const F = T.filaments;
  if (f.origin_kind === "user") return { key: "0", label: F.kinds.user };
  if (f.origin_kind === "bundle") return { key: "1" + f.bundle, label: F.bundlePrinter(f.bundle) };
  const kind = f.origin_kind === "vendor" ? F.kinds.vendorFrom(f.package) : F.kinds.library;
  const prefix = (f.origin_kind === "vendor" ? "2" + f.package : "3") + "|";
  if (f.material === undefined) return { key: prefix, label: kind };  // a process: no brand
  const brand = f.vendor || F.noBrand;
  return { key: prefix + brand.toLowerCase(), label: `${kind} · ${brand}` };
}

// The nozzle chosen per printer model, the same on the pages "Filamente" and "Prozesse": a
// printer name, or "all" (only the page "Filamente" offers that).
export const chosenNozzle = reactive({});
export const nozzleKey = (inst, model) => inst.id + "|" + model.model;

// Pages with state of their own (the filament switches) rebuild it here after every load and
// after "Verwerfen".
const resetHooks = [];
export const onReset = (fn) => resetHooks.push(fn);
export function resetChanges() {
  for (const id of Object.keys(live)) delete live[id];
  for (const i of INSTANCES) live[i.id] = copyLive(i.initial);
  for (const fn of resetHooks) fn();
}

// Own profiles by name, for the change list, "Mitlöschen" and the printer cards.
const orphaned = (x) => x.status === "orphaned" || x.status === "ignored";
function profileMap(inst) {
  const pp = inst.printers_page, map = new Map();
  for (const f of inst.filaments) {
    if (f.origin_kind === "user") map.set(f.name, { name: f.name, kind: "filament", helper: !!f.helper, orphaned: orphaned(f) });
  }
  for (const x of [...pp.system, ...pp.own].flatMap((c) => c.only_here)) {
    if (!map.has(x.name)) map.set(x.name, { name: x.name, kind: x.kind, helper: !!x.helper, orphaned: !!x.orphaned });
  }
  for (const p of pp.own) map.set(p.name, { name: p.name, kind: "machine", helper: false, orphaned: orphaned(p) });
  return map;
}
export const profileInfo = (inst, name) => inst.profiles.get(name) || { name, kind: "filament", helper: false, orphaned: false };
export const KIND_ICON = { machine: "printer", filament: "spool", process: "layers" };
// One short line under a profile name, in the words of the page "Filamente".
export function profileSub(p) {
  if (p.orphaned) return T.profileSub.orphaned;
  if (p.helper) return T.profileSub.helper;
  return T.kindText[p.kind];
}

// "Snapmaker U1 · 0,4 mm" for a printer of a manufacturer, the plain name for an own one.
export function printerText(inst, name) {
  for (const m of inst.printers_page.system) {
    const p = m.printers.find((x) => x.name === name);
    if (p) return T.printerWithNozzle(printerShortName(p.name), nozzleLabel(p.variant));
  }
  return plainName(name);
}

// Pending changes of the pages "Drucker" and "Slicer": where `live` differs from the data.
// The page "Filamente" adds its own (pages/filamente.js); app.js shows both in one list.
// Backups are no pending change: the page "Sicherungen" makes, restores and deletes them directly.
export const liveChanges = computed(() => {
  const out = [];
  for (const i of INSTANCES) {
    const now = live[i.id], was = i.initial;
    if (!now) continue;
    const add = (page, type, name, where = "") => out.push({ inst: i, page, type, name, where });
    for (const m of i.printers_page.system) {
      if (!was.models.has(m.model) || now.models.has(m.model)) continue;
      const dropped = was.packages.has(m.origin) && !now.packages.has(m.origin);
      add("uebersicht", "remove", printerShortName(m.printers[0]?.name || m.model), dropped ? T.changes.packageGoes(m.origin) : "");
    }
    for (const n of was.own) {
      if (!now.own.has(n)) add("uebersicht", "delete", n, T.kindText[profileInfo(i, n).kind]);
    }
    if (now.defaultPrinter !== was.defaultPrinter) add("uebersicht", "default", printerText(i, now.defaultPrinter));
    const cleaned = was.dead.filter((d) => !now.dead.includes(d));
    if (cleaned.length) add("uebersicht", "clean", plural(cleaned.length, ...T.words.staleEntry), cleaned.join(", "));
    if (now.hideUnused) add("slicer", "hide", plural(unusedListNames(i).length, ...T.words.filament), T.changes.withoutPrinter);
  }
  return out;
});

// ------------------------------------------------------------ backups
// Backups per installation from GET /api/instances/{id}/backups: the page "Sicherungen" and the
// main menu show them. Read after every load and after every backup action. `error` holds the
// code when the list could not be read; the last list read stays then.
export const BACKUPS = reactive({});
export async function refreshBackups(instId) {
  try {
    const data = await api.backups(instId);
    BACKUPS[instId] = {
      backups: data.backups || [], total_size: data.total_size || 0, location: data.location || "", error: null,
    };
  } catch (err) {
    BACKUPS[instId] = { backups: [], total_size: 0, location: "", ...BACKUPS[instId], error: err.code || "unknown" };
  }
}

// Changes per installation since it was last marked seen (page "Änderungen"), for the menu:
// from GET /api/data, the page updates it.
export const NEWS = reactive({});

let toastTimer = 0;
export function flash(text) {
  ui.toast = text;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { ui.toast = ""; }, 2800);
}

// A Blob from the server as a download under name: an export, a cleaned 3MF.
export function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ------------------------------------------------------------ loading
function enrich(raw) {
  const inst = { ...raw, snorca: raw.kind === "snorca", byName: new Map(raw.filaments.map((f) => [f.name, f])) };
  inst.profiles = profileMap(inst);
  inst.initial = initialLive(inst);
  return inst;
}

// The installation in the address, else the one chosen so far, else the first. An address
// without an installation gets it added, so a reload stays with it.
function pickInstance() {
  const wanted = parseHash(location.hash);
  const kept = INSTANCES.some((i) => i.id === ui.instId) ? ui.instId : null;
  // At the start the one chosen last (app.js keeps it, the user's wish of 26.09.2026), if it is still there.
  const last = INSTANCES.some((i) => i.id === SETTINGS.chosen_instance) ? SETTINGS.chosen_instance : null;
  ui.instId = wanted.instId || kept || last || INSTANCES[0]?.id || null;
  if (!wanted.instId && ui.instId) history.replaceState(null, "", hashOf(wanted.page, ui.instId));
  syncRoute();
}

function setData(data) {
  FIELDS.splice(0, FIELDS.length, ...data.editable_fields.map((f) => ({ ...f, ...(T.fields[f.key] || { label: f.key, unit: "" }) })));
  INSTANCES.splice(0, INSTANCES.length, ...data.instances.map(enrich));
  for (const id of Object.keys(NEWS)) delete NEWS[id];
  for (const i of data.instances) NEWS[i.id] = i.news || 0;
  FAILED.splice(0, FAILED.length, ...(data.failed || []));
  loadState.generated = data.generated;
  resetChanges();
  pickInstance();
  loadState.version++;
}

// Reads everything again. Pending changes are gone afterwards: they refer to the old state.
// Returns whether it worked; loadState.error holds the code otherwise.
export async function load() {
  loadState.busy = true;
  try {
    setData(await api.data());
    loadState.error = null;
    loadState.status = "ready";
    // Not awaited: the pages show while the lists come in.
    for (const i of INSTANCES) refreshBackups(i.id);
    return true;
  } catch (err) {
    if (!err.code) console.error(err);
    loadState.error = err.code || "unknown";
    if (loadState.status !== "ready") loadState.status = "error";
    return false;
  } finally {
    // The printers with an address only now: the slicers' addresses (print_host, the connected U1)
    // are known to the server after its scan (camera.remember_slicer_hosts). Asked earlier, after a
    // start of OrcaOne they were missing, and the top bar chose and kept another printer.
    await loadHosts();
    loadState.busy = false;
  }
}

// Data directories added by hand (orcaone/instances.py). Both read everything again and
// return an error code for T.errors, or null.
export async function addDataDir(path) {
  let result;
  try {
    result = await api.addManual(path);
  } catch (err) {
    return err.code || "unknown";
  }
  if (!(await load())) return loadState.error;
  go(null, hashOf(route.value.page, result.instance.id));
  return null;
}
export async function removeDataDir(inst) {
  let code = null;
  try {
    await api.removeManual(inst.data_dir);
  } catch (err) {
    code = err.code || "unknown";
  }
  // Also after "not_listed": the list on the page is out of date then.
  if (!(await load())) return loadState.error;
  return code;
}

// ------------------------------------------------------------ formatting
export const nozzleLabel = (v) => v.split("+").map((d) => d.replace(".", DECIMAL)).join(" + ");
export const printerShortName = (name) => plainName(name).replace(/\s*\(?[\d.+]+ nozzle\)?$/, "");
export const plural = (n, one, many) => n.toLocaleString(LOCALE) + " " + (n === 1 ? one : many);

// Decimal units (kB, MB), as the file managers on Linux show them.
export function fmtSize(bytes) {
  if (bytes < 1000) return bytes + " B";
  const units = ["kB", "MB", "GB"];
  let v = bytes / 1000, u = 0;
  while (v >= 999.5 && u < units.length - 1) { v /= 1000; u++; }
  return v.toLocaleString(LOCALE, { maximumFractionDigits: v < 100 ? 1 : 0 }) + " " + units[u];
}

export const timeText = (d) => d.toLocaleString(LOCALE, {
  day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
});
export const clockText = (d) => d.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" });
export const generatedText = computed(() => loadState.generated ? timeText(new Date(loadState.generated)) : "");

// "Heute", "Gestern", else weekday and date.
export function dayLabel(d) {
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate());
  const diff = Math.round((day(new Date()) - day(d)) / 86400000);
  if (diff === 0) return T.today;
  if (diff === 1) return T.yesterday;
  return d.toLocaleDateString(LOCALE, { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
}
// "heute, 07:29 Uhr", "gestern, 16:40 Uhr", "Montag, 21.09.2026, 16:40 Uhr"; reads after "Stand von".
export function whenText(d) {
  const l = dayLabel(d);
  return T.when(l === T.today || l === T.yesterday ? l.toLowerCase() : l, clockText(d));
}

// ------------------------------------------------------------ icons
// 24x24, stroke = currentColor, so hover, the active menu entry and dark mode colour them.
export const ICONS = {
  back: '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
  fan: '<circle cx="12" cy="12" r="1.8"/><path d="M12 10.2c-1-3.1-.5-6.1 2-6.7 2.2-.5 3.3 2.2 1 4.3L13.4 10.1M13.6 12.8c3.2.6 5.5 2.6 4.9 4.9-.6 2.2-3.5 2.3-4.4-.6l-.6-2.8M10.5 12.9c-2.3 2.3-5.3 3.1-6.8 1.4-1.5-1.7 0-4.2 2.9-3.6l2.8.8"/>',
  cube: '<path d="m12 3.5 8 4.5v8L12 20.5 4 16V8z"/><path d="m4 8 8 4.5L20 8M12 12.5v8"/>',
  toolpath: '<rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><path d="M7.5 16.5v-9h3v9h3v-9h3v9"/>',
  pulse: '<path d="M3 12h4l2.5-6 5 12 2.5-6H21"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
  moon: '<path d="M19.5 14.6A7.8 7.8 0 0 1 9.4 4.5a7.8 7.8 0 1 0 10.1 10.1z"/>',
  home: '<path d="M4 11 12 4.5l8 6.5"/><path d="M6.5 9.5v10h11v-10"/><path d="M10 19.5v-5h4v5"/>',
  menu: '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
  tree: '<rect x="3.5" y="3.5" width="7" height="5" rx="1"/><rect x="13.5" y="9.5" width="7" height="5" rx="1"/><rect x="13.5" y="16" width="7" height="5" rx="1"/><path d="M7 8.5v10h6.5M7 12h6.5"/>',
  more: '<circle cx="5.5" cy="12" r=".9"/><circle cx="12" cy="12" r=".9"/><circle cx="18.5" cy="12" r=".9"/>',
  code: '<path d="M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5"/>',
  terminal: '<rect x="3.5" y="5" width="17" height="14" rx="1.5"/><path d="m7.5 10 2.5 2-2.5 2M12.5 14.5h4"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  pause: '<rect x="7" y="6" width="3.2" height="12" rx="1"/><rect x="13.8" y="6" width="3.2" height="12" rx="1"/>',
  mesh: '<path d="M3 8c3-2 6 2 9 0s6-2 9 0M3 13c3-2 6 2 9 0s6-2 9 0M3 18c3-2 6 2 9 0s6-2 9 0"/>',
  sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  resume: '<path d="M6.5 6v12"/><path d="M10.5 6v12l8.5-6z"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>',
  estop: '<path d="M8.6 3.5h6.8l5.1 5.1v6.8l-5.1 5.1H8.6l-5.1-5.1V8.6z"/><path d="M12 7.8v5.4M12 16.2v.2"/>',
  download: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19.5h14"/>',
  chevron: '<path d="m9.5 6 6 6-6 6"/>',
  chevronDown: '<path d="m6 9.5 6 6 6-6"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5.5M14 11v5.5"/>',
  lock: '<rect x="5.5" y="10.5" width="13" height="9.5" rx="1.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
  user: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6"/>',
  factory: '<path d="M3.5 20.5h17M5 20.5V12l4.5 3v-3l4.5 3v-3l4.5 3v5.5M15.5 12.5V4.5h3v8.2"/>',
  package: '<path d="m12 3.5 8 4v9l-8 4-8-4v-9z"/><path d="m4 7.5 8 4 8-4M12 11.5v9M8 5.5l8 4"/>',
  camera: '<path d="M4 8.5h3.2l1.6-2.5h6.4l1.6 2.5H20v10.5H4z"/><circle cx="12" cy="13.3" r="3.4"/>',
  network: '<path d="M4.5 9.8a10.8 10.8 0 0 1 15 0M7.3 12.9a6.6 6.6 0 0 1 9.4 0M10.1 16a2.6 2.6 0 0 1 3.8 0"/><circle cx="12" cy="18.7" r=".9"/>',
  // A network of cables (page "Netzwerk"), and the internet as a globe.
  lan: '<rect x="9" y="3.5" width="6" height="5" rx="1"/><rect x="3.5" y="15.5" width="6" height="5" rx="1"/><rect x="14.5" y="15.5" width="6" height="5" rx="1"/><path d="M12 8.5V12M6.5 15.5V12h11v3.5"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.3 2.3 3.5 5.2 3.5 8.5s-1.2 6.2-3.5 8.5c-2.3-2.3-3.5-5.2-3.5-8.5s1.2-6.2 3.5-8.5z"/>',
  window: '<rect x="3" y="4.5" width="18" height="15" rx="1.5"/><path d="M7 9.5V8h1.5M17 9.5V8h-1.5M7 14.5V16h1.5M17 14.5V16h-1.5"/>',
  fullscreen: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
  fit: '<path d="M4 8.5V4h4.5M15.5 4H20v4.5M20 15.5V20h-4.5M8.5 20H4v-4.5"/><circle cx="12" cy="12" r="3"/>',
  rotateLeft: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4h4"/>',
  rotateRight: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/>',
  shrink: '<path d="M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5"/>',
  calibrate: '<path d="M10 6.5h10M10 12h10M10 17.5h10"/><path d="m3.8 6.5 1.4 1.4 2.6-2.8M3.8 12l1.4 1.4 2.6-2.8M3.8 17.5l1.4 1.4 2.6-2.8"/>',
  diff: '<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4M9 11h4M11 9v4M9 16.5h4"/>',
  import: '<path d="M12 3.5v11M7.5 10 12 14.5 16.5 10"/><path d="M4.5 14.5v5h15v-5"/>',
  export: '<path d="M12 14.5v-11M7.5 8 12 3.5 16.5 8"/><path d="M4.5 14.5v5h15v-5"/>',
  transfer: '<path d="M4 8.5h14.5M15 5l3.5 3.5L15 12M20 15.5H5.5M9 12l-3.5 3.5L9 19"/>',
  compare: '<rect x="3.5" y="4.5" width="7" height="15" rx="1.5"/><rect x="13.5" y="4.5" width="7" height="15" rx="1.5"/><path d="M6 9h2M6 12.5h2M16 9h2M16 12.5h2"/>',
  arrowRight: '<path d="M4 12h15.5M13.5 6l6 6-6 6"/>',
  arrowLeft: '<path d="M20 12H4.5M10.5 6l-6 6 6 6"/>',
  bolt: '<path d="M13.5 3 5.5 13.5h6L10.5 21l8-10.5h-6z"/>',
  halfCircle: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor"/>',
  checkCircle: '<circle cx="12" cy="12" r="8.5"/><path d="m8.3 12.2 2.5 2.5 4.9-5.1"/>',
  books: '<rect x="3.5" y="4.5" width="4" height="15.5" rx="1"/><rect x="9" y="4.5" width="4" height="15.5" rx="1"/><path d="m14.7 6.2 3.8-1 3 14.4-3.8 1z"/>',
  temp: '<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 9v7"/>',
  bed: '<rect x="3" y="15" width="18" height="3.5" rx="1"/><path d="M8 12c1-1.2-.6-2.3.4-4M12 12c1-1.2-.6-2.3.4-4M16 12c1-1.2-.6-2.3.4-4"/>',
  box: '<rect x="5.5" y="5.5" width="13" height="13" rx="2.5"/>',
  price: '<path d="M3.5 12.5v-8h8l9 9-8 8z"/><circle cx="7.8" cy="8.8" r="1.3"/>',
  backup: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4h4"/><path d="M12 8.5V12l2.5 2"/>',
  grip: '<circle cx="9" cy="7" r=".8"/><circle cx="15" cy="7" r=".8"/><circle cx="9" cy="12" r=".8"/><circle cx="15" cy="12" r=".8"/><circle cx="9" cy="17" r=".8"/><circle cx="15" cy="17" r=".8"/>',
  spool: '<ellipse cx="16.5" cy="12" rx="3" ry="7.5"/><path d="M16.5 4.5H8c-1.9 0-3.5 3.4-3.5 7.5s1.6 7.5 3.5 7.5h8.5"/><ellipse cx="16.5" cy="12" rx="1" ry="2.5"/>',
  printer: '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M3.5 8h17M10 8v3.5h4V8M12 11.5V13M7 17h10"/>',
  folder: '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  folderPlus: '<path d="M11 19H5.5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V12"/><path d="M17.5 14.5v6M14.5 17.5h6"/>',
  folderMove: '<path d="M11 19H5.5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V12"/><path d="M14 17.5h6.5M17.5 14.5l3 3-3 3"/>',
  levelUp: '<path d="M9.5 13.5 5 9l4.5-4.5"/><path d="M5 9h8.5a5.5 5.5 0 0 1 5.5 5.5v4"/>',
  folderOpen: '<path d="M3.5 17V7a2 2 0 0 1 2-2h4l2 2.5h6a2 2 0 0 1 2 2v1"/><path d="M3.5 17l2.3-6a1.5 1.5 0 0 1 1.4-1h12.6a1 1 0 0 1 .9 1.4L18.4 17.8a1.8 1.8 0 0 1-1.7 1.2H5.2a1.7 1.7 0 0 1-1.7-2z"/>',
  file: '<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4"/>',
  log: '<rect x="5" y="3.5" width="14" height="17" rx="1.5"/><path d="M8.5 8h7M8.5 11.5h7M8.5 15h4.5"/>',
  // The switches of the page "Logs" (pages/druckerlogs.js): wrap lines, follow live, keep the end in view
  wrap: '<path d="M4 6.5h16M4 12h12.5a3.5 3.5 0 0 1 0 7H11.5"/><path d="m13.5 17-2 2 2 2"/><path d="M4 17.5h4"/>',
  live: '<circle cx="12" cy="12" r="1.8"/><path d="M8.6 8.6a4.8 4.8 0 0 0 0 6.8M15.4 8.6a4.8 4.8 0 0 1 0 6.8M5.8 5.8a8.8 8.8 0 0 0 0 12.4M18.2 5.8a8.8 8.8 0 0 1 0 12.4"/>',
  toEnd: '<path d="M12 4v11.5M7 10.5l5 5 5-5"/><path d="M5.5 19.5h13"/>',
  layers: '<path d="M12 4 3.5 8.5 12 13l8.5-4.5z"/><path d="m3.5 12.5 8.5 4.5 8.5-4.5"/><path d="m3.5 16.5 8.5 4.5 8.5-4.5"/>',
  pencil: '<path d="M4.5 19.5l1-4.5L15.5 5l3.5 3.5-10 10z"/><path d="m13 7.5 3.5 3.5"/>',
  undo: '<path d="M9 13.5 4.5 9 9 4.5"/><path d="M4.5 9H14a5.5 5.5 0 0 1 0 11h-3"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  key: '<circle cx="8" cy="15.5" r="4"/><path d="m11 12.5 8.5-8.5M16 7.5l2.5 2.5M13.5 10l2 2"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 3.5V6M12 18v2.5M3.5 12H6M18 12h2.5M6 6l1.8 1.8M16.2 16.2 18 18M6 18l1.8-1.8M16.2 7.8 18 6"/>',
  power: '<path d="M12 3.5v8"/><path d="M7 6.5a7.5 7.5 0 1 0 10 0"/>',
  chart: '<path d="M3.5 3.5v17h17"/><path d="m7 15 4-5 3.5 3L20 6.5"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 0 1-13 5.1"/><path d="M4.5 12a7.5 7.5 0 0 1 13-5.1"/><path d="M17.5 3.5v3.4h-3.4M6.5 20.5v-3.4h3.4"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.2"/>',
  panelRight: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M14.5 4.5v15"/>',
  warn: '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17.2v.2"/>',
  star: '<path d="m12 3.8 2.5 5.2 5.7.8-4.1 4 1 5.7L12 16.8l-5.1 2.7 1-5.7-4.1-4 5.7-.8z"/>',
  bulb: '<path d="M9.5 17.5h5M10.5 20.5h3"/><path d="M12 3.5a5.5 5.5 0 0 0-3.3 9.9c.5.4.8 1 .8 1.6v.5h5v-.5c0-.6.3-1.2.8-1.6A5.5 5.5 0 0 0 12 3.5z"/>',
  broom: '<path d="M14.5 3.5 11 11"/><path d="M7.5 11.5h7l2 9h-11z"/><path d="M9 16v4.5M12 16v4.5"/>',
};

// ------------------------------------------------------------ components
let spoolIds = 0;
export function registerCommon(app) {
  // A spool from the side, OrcaOne's own drawing (the user's choice of 27.09.2026; nothing from the
  // slicers' sources): the band takes the filament colour and looks round through a shade from light
  // above to dark below. Each spool its own gradient id: an id shared by all resolves to the first,
  // and that one may sit in a hidden part of the page. The flange's holes only where they show.
  app.component("spool-icon", {
    props: { colour: { type: String, default: "#009688" }, size: { type: Number, default: 24 } },
    setup() {
      return { shade: `spool-shade-${++spoolIds}` };
    },
    template: `
      <svg class="spool" viewBox="0 0 30 40" :width="Math.round(size * 0.75)" :height="size" fill="none" aria-hidden="true">
        <defs><linearGradient :id="shade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#fff" stop-opacity=".45"/><stop offset=".35" stop-color="#fff" stop-opacity="0"/>
          <stop offset=".7" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".28"/>
        </linearGradient></defs>
        <ellipse cx="22.5" cy="20" rx="4.6" ry="17.2" fill="#E6E6E6" stroke="#5C5C5C" stroke-width="1.6"/>
        <path d="M7.5 7H22.5A3.6 13 0 0 1 22.5 33H7.5Z" :fill="colour"/>
        <path d="M7.5 7H22.5A3.6 13 0 0 1 22.5 33H7.5Z" :fill="'url(#' + shade + ')'"/>
        <path d="M7.5 7H22.5A3.6 13 0 0 1 22.5 33H7.5" stroke="#5C5C5C" stroke-width="1.2"/>
        <ellipse cx="7.5" cy="20" rx="4.6" ry="17.2" fill="#F4F4F4" stroke="#5C5C5C" stroke-width="1.6"/>
        <template v-if="size >= 32"><ellipse cx="7.5" cy="11" rx="0.9" ry="2.6" fill="#D2D2D2"/><ellipse cx="7.5" cy="29" rx="0.9" ry="2.6" fill="#D2D2D2"/></template>
        <ellipse cx="7.5" cy="20" rx="1.7" ry="5" stroke="#5C5C5C" stroke-width="1.2"/>
        <ellipse cx="7.5" cy="20" rx="0.6" ry="2" fill="#5C5C5C"/>
      </svg>`,
  });

  // Hot end with the extruded line below; the line width grows with the nozzle diameter.
  app.component("nozzle-icon", {
    props: { sizes: { type: Array, required: true }, height: { type: Number, default: 34 } },
    methods: { w(d) { return Math.max(1.6, d * 10); } },
    template: `
      <svg class="nozzle" :viewBox="'0 0 ' + (sizes.length * 26 + 2) + ' 40'" :width="Math.round((sizes.length * 26 + 2) * height / 40)" :height="height" aria-hidden="true">
        <g v-for="(d, n) in sizes" :key="n" :transform="'translate(' + (n * 26) + ' 0)'">
          <rect x="4" y="2" width="20" height="12" rx="2" class="nz-body"/>
          <path :d="'M8 14h12l-' + (5.5 - w(d) / 2) + ' 9h-' + (w(d) + 1) + 'z'" class="nz-tip"/>
          <rect :x="14 - w(d) / 2" y="24" :width="w(d)" height="14" :rx="Math.min(2, w(d) / 2)" class="nz-flow"/>
        </g>
      </svg>`,
  });

  app.component("ui-icon", {
    props: { name: { type: String, required: true }, size: { type: Number, default: 18 } },
    computed: { paths() { return ICONS[this.name] || ""; } },
    template: `<svg class="icon" viewBox="0 0 24 24" :width="size" :height="size" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" v-html="paths"></svg>`,
  });

  // The heads of a printer as a picture (pages "Übersicht" and "Status"): spool, filament and head,
  // the nozzle orange while it is hot; in a print the working head sits lower, as if picked up (the
  // U1 changes heads). The bed below. p: camera.status. details: also nozzle, pressure advance,
  // tool changes and errors per head (monitor.py); sensors: the filament sensor of each head.
  app.component("printer-stage", {
    props: {
      p: { type: Object, required: true }, u1: { type: Boolean, default: false },
      details: { type: Boolean, default: false }, sensors: { type: Array, default: () => [] },
    },
    setup(props) {
      const M = T.monitor, NO_COLOUR = "#D9D9D9";
      const printing = computed(() => ["printing", "paused"].includes(props.p.state));
      const hot = (x) => (x?.target || 0) > 0 || (x?.temp || 0) >= 50;
      const deg = (v) => (v == null ? "–" : `${Math.round(v)} °C`);
      const num = (v, digits) => v.toLocaleString(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits });
      // A printer that knows its spools (the U1) colours the filament; other printers do not say.
      const colour = (h) => (props.u1 ? h.spool?.colour || NO_COLOUR : "var(--icon)");
      const material = (h) => (h.spool ? [h.spool.type, h.spool.subtype].filter(Boolean).join(" ") : T.printers.live.empty);
      const title = (h, i) => [T.u1.head(i + 1), h.spool ? [h.spool.vendor, material(h)].filter(Boolean).join(" ") : null,
        deg(h.temp) + (h.target ? ` → ${deg(h.target)}` : "")].filter(Boolean).join(" · ");
      return { T, M, NO_COLOUR, printing, hot, deg, num, colour, material, title, nozzleLabel };
    },
    template: `
      <div class="stage">
        <div class="stage-heads">
          <div v-for="(h, i) in p.heads" :key="h.extruder" :title="title(h, i)"
               :class="['stage-head', { 'is-active': printing && p.active === h.extruder, 'is-hot': hot(h), 'is-empty': u1 && !h.spool }]">
            <spool-icon v-if="u1" :colour="h.spool?.colour || NO_COLOUR" :size="40"/>
            <svg class="head-art" viewBox="0 0 64 92" width="64" height="92" aria-hidden="true">
              <rect class="head-filament" x="29" y="0" width="6" height="24" :style="{ fill: colour(h) }"/>
              <rect class="head-top" x="21" y="12" width="22" height="12" rx="3"/>
              <rect class="head-body" x="8" y="22" width="48" height="48" rx="12"/>
              <circle class="head-window" cx="32" cy="39" r="9" :style="{ fill: colour(h) }"/>
              <text class="head-num" x="32" y="62" text-anchor="middle">{{ i + 1 }}</text>
              <path class="head-block" d="M22 70h20l-3 9H25z"/>
              <path class="head-tip" d="M28.5 79h7L32 86z"/>
            </svg>
            <strong class="stage-temp">{{ deg(h.temp) }}</strong>
            <small class="stage-target">{{ h.target ? '→ ' + deg(h.target) : M.off }}</small>
            <small v-if="u1" class="stage-material">{{ material(h) }}</small>
            <template v-if="details">
              <small v-if="h.nozzle != null || h.pa != null" class="stage-detail">
                {{ [h.nozzle != null ? nozzleLabel(String(h.nozzle)) + ' mm' : '', h.pa != null ? 'PA ' + num(h.pa, 3) : ''].filter(Boolean).join(' · ') }}</small>
              <small v-if="h.changes != null" class="stage-detail" :title="M.retries(num(h.retries || 0, 0))">{{ M.changesN(num(h.changes, 0)) }}</small>
              <small v-if="h.errors" class="stage-detail is-bad">{{ M.errorsN(h.errors) }}</small>
              <small v-if="sensors[i]" :class="['stage-detail', sensors[i].detected ? 'st-on' : 'is-warn']">
                {{ sensors[i].enabled === false ? M.disabled : sensors[i].detected ? M.filamentIn : M.filamentOut }}</small>
            </template>
          </div>
        </div>
        <div :class="['stage-bed', { 'is-hot': hot(p.bed) }]"></div>
        <p class="stage-facts">
          <span :class="{ 'is-hot': hot(p.bed) }">{{ M.names.bed }} {{ deg(p.bed?.temp) }}<template v-if="p.bed?.target"> → {{ deg(p.bed.target) }}</template></span>
          <span v-if="p.cavity != null">{{ M.names.cavity }} {{ deg(p.cavity) }}</span>
          <span v-if="p.light != null"><ui-icon name="bulb" :size="14"/>{{ p.light ? M.lightOn : M.lightOff }}</span>
        </p>
      </div>`,
  });

  // State of an installation as text plus colour, the same words on every page.
  app.component("run-status", {
    props: { inst: { type: Object, required: true }, short: { type: Boolean, default: false } },
    computed: { text() { return statusText(this.inst, this.short); } },
    template: `<span :class="['status', { 'status--busy': inst.running }]">{{ text }}</span>`,
  });
}
