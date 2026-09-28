// Thin wrapper around the JSON API. Errors are thrown as ApiError with the server's error code,
// which texts.js turns into a message; `data` keeps the rest of the answer ({"error": code, …}).

export class ApiError extends Error {
  constructor(code, data = {}) {
    super(code);
    this.code = code;
    this.data = data;
  }
}

async function request(method, url, body) {
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("network");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(data.error || "unknown", data);
  return data;
}

// A file as the body itself (page "Import/Export"), and a file back as a Blob.
async function upload(url, file) {
  let response;
  try {
    response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
  } catch {
    throw new ApiError("network");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(data.error || "unknown", data);
  return data;
}
async function download(url, body) {
  const raw = body instanceof Blob;
  let response;
  try {
    response = await fetch(url, { method: "POST", headers: { "Content-Type": raw ? "application/octet-stream" : "application/json" },
                                  body: raw ? body : JSON.stringify(body) });
  } catch {
    throw new ApiError("network");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(data.error || "unknown", data);
  }
  return response.blob();
}

const instUrl = (id) => `/api/instances/${encodeURIComponent(id)}`;
const backupUrl = (id, name) => `${instUrl(id)}/backups/${encodeURIComponent(name)}`;

async function profileJob(id, path, body, onProgress) {
  const payload = { ...body, request_id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` };
  let job;
  for (;;) {
    try {
      job = job
        ? await request("GET", `${instUrl(id)}/profile-editor/jobs/${encodeURIComponent(job.job_id)}`)
        : await request("POST", `${instUrl(id)}/profile-editor/${path}`, payload);
    } catch (error) {
      if (error.code !== "network") throw error;
      onProgress?.({ ...(job || { state: "queued", phase: "check", completed: 0, total: null }), connection_lost: true });
      await new Promise(resolve => setTimeout(resolve, 1500));
      continue;
    }
    onProgress?.({ ...job, connection_lost: false });
    if (job.state === "failed") throw new ApiError(job.error?.error || "operation_failed", job.error || {});
    if (job.state === "succeeded") return job.result;
    await new Promise(resolve => setTimeout(resolve, 400));
  }
}

export const api = {
  profilePublishProgress: (id, body, onProgress) => profileJob(id, "publish-preview-job", body, onProgress),
  applyProgress: (id, planId, onProgress) => profileJob(id, "apply-job", { plan_id: planId }, onProgress),
  profileEditor: (id, path, body, method) => request(method || (body ? "POST" : "GET"), `${instUrl(id)}/profile-editor${path}`, body),
  data: () => request("GET", "/api/data"),
  // What the scan of GET /api/data does right now, for the boot screen.
  progress: () => request("GET", "/api/progress"),
  // OrcaOne's own settings (data/settings.json): the language of the page, the folded menu, the design.
  settings: () => request("GET", "/api/settings"),
  setLanguage: (language) => request("POST", "/api/settings", { language }),
  setMenuCollapsed: (collapsed) => request("POST", "/api/settings", { menu_collapsed: collapsed }),
  setTheme: (theme) => request("POST", "/api/settings", { theme }),
  setArea: (area) => request("POST", "/api/settings", { area }),
  // The printer chosen last in a part ("slicer": a model, "printer": a printer's name): the next start takes it.
  setChosenPrinter: (area, name) => request("POST", "/api/settings", { chosen_printer: { [area]: name } }),
  // The installation, and a printer's print file, chosen last: the next start takes them (26.09.2026).
  setChosenInstance: (id) => request("POST", "/api/settings", { chosen_instance: id }),
  setPrintFile: (printer, path) => request("POST", "/api/settings", { print_file: { [printer]: path } }),
  // The curves shown on "Diagramme" for a printer (the user's wish of 27.09.2026).
  setCharts: (printer, names) => request("POST", "/api/settings", { charts: { [printer]: names } }),
  // Keep the printers' values at rest too, not only while printing or heating (orcaone/history.py).
  setRecordIdle: (on) => request("POST", "/api/settings", { record_idle: on }),
  // How "Dateien" sorts, and whether its info pane shows: the page opens so again.
  setFilesSort: (sort) => request("POST", "/api/settings", { files_sort: sort }),
  setFilesInfo: (on) => request("POST", "/api/settings", { files_info: on }),
  // Where the camera of "3D Ansicht" was left: the page opens with it again.
  setView3d: (view) => request("POST", "/api/settings", { view3d: view }),
  // "Use at your own risk" confirmed: the server keeps it with the time and the version
  acceptRisk: () => request("POST", "/api/settings", { accept_risk: true }),
  addManual: (path) => request("POST", "/api/instances/manual", { path }),
  removeManual: (path) => request("DELETE", `/api/instances/manual?path=${encodeURIComponent(path)}`),
  // Writing takes two steps (hard rule 5): the plan shows what would happen, only its id goes to
  // /apply. The backend refuses the apply if a file changed since the plan (plan_outdated).
  plan: (id, changes) => request("POST", `${instUrl(id)}/plan`, { changes }),
  apply: (id, planId) => request("POST", `${instUrl(id)}/apply`, { plan_id: planId }),
  // One profile with its chain, files and every value (pages "Prozesse" and "Details").
  profile: (id, kind, name) => request("GET", `${instUrl(id)}/profile?kind=${kind}&name=${encodeURIComponent(name)}`),
  // The slicer's own logs, filtered on the server (orcaone/logs.py).
  logs: (id) => request("GET", `${instUrl(id)}/logs`),
  log: (id, name, show, q, regex = false) =>
    request("GET", `${instUrl(id)}/logs/${encodeURIComponent(name)}?show=${show}&q=${encodeURIComponent(q)}&regex=${regex}`),
  backups: (id) => request("GET", `${instUrl(id)}/backups`),
  backupNow: (id) => request("POST", `${instUrl(id)}/backups`),
  // The address of a printer model (page "Drucker"); every U1 with one has a camera
  // (orcaone/camera.py). The picture itself comes as image/jpeg.
  printers: () => request("GET", "/api/printers"),
  // Read only, by model: what a printer with an address says of itself. What it is doing comes live
  // (live.js), no longer asked for here.
  printerInfo: (model) => request("GET", `/api/printers/info?model=${encodeURIComponent(model)}`),
  sshState: (model) => request("GET", `/api/printers/ssh-state?model=${encodeURIComponent(model)}`),
  // The logs of a printer (page "Logs" of the printer part): list, a view, the last start, a search.
  printerErrors: (model) => request("GET", `/api/printers/errors?model=${encodeURIComponent(model)}`),
  printerLogs: (model) => request("GET", `/api/printers/logs?model=${encodeURIComponent(model)}`),
  // Page "Diagramme": what OrcaOne recorded of a printer (orcaone/history.py), the `seconds` up to now or up to `until`.
  history: (printer, seconds, points, until = null) =>
    request("GET", `/api/history?${new URLSearchParams({ printer, seconds, points, ...(until ? { until } : {}) })}`),
  printerLog: (model, path, where = {}) => request("GET", `/api/printers/log?${new URLSearchParams({ model, path, ...where })}`),
  printerLogStart: (model, path) => request("GET", `/api/printers/log/start?${new URLSearchParams({ model, path })}`),
  printerLogSearch: (model, path, q, regex, context) =>
    request("GET", `/api/printers/log/search?${new URLSearchParams({ model, path, q, regex, context })}`),
  printerLogDownload: (model, path) => `/api/printers/log/download?${new URLSearchParams({ model, path })}`,
  // Page "3D Ansicht": the print files of a printer and the address of one (read in pages/gcode-worker.js).
  printFiles: (model, path = "") => request("GET", `/api/printers/files?${new URLSearchParams({ model, path })}`),
  printFileUrl: (model, path) => `/api/printers/file?model=${encodeURIComponent(model)}&path=${encodeURIComponent(path)}`,
  // Page "Höhenkarte" (orcaone/monitor.py, mesh), once; page "Steuerung": its two commands.
  printerMesh: (model) => request("GET", `/api/printers/mesh?model=${encodeURIComponent(model)}`),
  excludeObject: (model, name) => request("POST", "/api/printers/exclude", { model, name }),
  pauseAt: (model, what) => request("POST", "/api/printers/pause-at", { model, ...what }),
  // The G-code console on the page "Konsole" (orcaone/console.py).
  gcodeHistory: (model, since) => request("GET", `/api/printers/gcode?model=${encodeURIComponent(model)}&since=${since}`),
  gcodeSend: (model, script) => request("POST", "/api/printers/gcode", { model, script }),
  setPrinterHost: (model, host) => request("POST", "/api/printers", { model, host }),
  // SSH per printer (orcaone/ssh.py): the keys in ~/.ssh of the computer OrcaOne runs on, the one
  // chosen for a printer, and bringing it onto the printer (a typed password only passes through).
  sshKeys: () => request("GET", "/api/ssh/keys"),
  // login: "auto" for this computer's keys and agent; without key and login the password.
  setSsh: (model, user, key, login) => request("POST", "/api/printers/ssh", { model, user, key, login }),
  bringKey: (model, password) => request("POST", "/api/printers/ssh-key", { model, password }),
  addPrinter: (model, name, host) => request("POST", "/api/printers", { model, name, host }),
  // About 6 s: Snapmaker printers that answer in the LAN (mDNS, as Snapmaker Orca looks for them).
  searchPrinters: () => request("POST", "/api/printers/search"),
  cameras: () => request("GET", "/api/cameras"),
  cameraEvery: (id, every) => request("POST", `/api/cameras/${encodeURIComponent(id)}`, { every }),
  wakeCamera: (id) => request("POST", `/api/cameras/${encodeURIComponent(id)}/wake`),
  // The light in the U1 on or off.
  cameraLight: (id, on) => request("POST", `/api/cameras/${encodeURIComponent(id)}/light`, { on }),
  // Page "Dateien" (orcaone/printer_files.py): a folder of any Klipper printer, in "gcodes" also a
  // folder in it (path); deleting, moving, a new folder, an upload; on the U1 a print with the
  // options of the printer's display.
  printerFiles: (model, folder, path = "") =>
    request("GET", `/api/printers/folder?model=${encodeURIComponent(model)}&folder=${encodeURIComponent(folder)}&path=${encodeURIComponent(path)}`),
  printerFileUrl: (model, folder, path, download = false) =>
    `/api/printers/folder/file?model=${encodeURIComponent(model)}&folder=${encodeURIComponent(folder)}&path=${encodeURIComponent(path)}${download ? "&download=true" : ""}`,
  deletePrinterFiles: (model, folder, names, dirs = []) => request("POST", "/api/printers/folder/delete", { model, folder, names, dirs }),
  movePrinterFiles: (model, paths, target) => request("POST", "/api/printers/folder/move", { model, paths, target }),
  makePrinterFolder: (model, parent, name) => request("POST", "/api/printers/folder/make", { model, parent, name }),
  // The file as the body; onProgress(sent, total) while it goes, since fetch cannot say so. An
  // AbortSignal (signal) stops it.
  uploadPrinterFile: (model, folder, file, replace, onProgress, signal) => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/printers/folder/upload?model=${encodeURIComponent(model)}&folder=${encodeURIComponent(folder)}`
      + `&name=${encodeURIComponent(file.name)}${replace ? "&replace=true" : ""}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (ev) => onProgress?.(ev.loaded, ev.total);
    xhr.onload = () => {
      let data = {};
      try {
        data = JSON.parse(xhr.responseText);
      } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(data.error || "unknown", data));
    };
    xhr.onerror = xhr.ontimeout = () => reject(new ApiError("network"));
    xhr.onabort = () => reject(new ApiError("upload_failed"));
    if (signal?.aborted) return xhr.onabort();
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(file);
  }),
  printSetup: (id) => request("GET", `/api/cameras/${encodeURIComponent(id)}/print`),
  startPrint: (id, path, options, map) => request("POST", `/api/cameras/${encodeURIComponent(id)}/print`, { path, options, map }),
  // The buttons next to the print file in the top bar, each only on the user's click.
  printPlain: (model, path) => request("POST", "/api/printers/print", { model, path }),
  pausePrint: (model) => request("POST", "/api/printers/pause", { model }),
  resumePrint: (model) => request("POST", "/api/printers/resume", { model }),
  printCancel: (model) => request("POST", "/api/printers/cancel", { model }),
  emergencyStop: (model) => request("POST", "/api/printers/emergency-stop", { model }),
  // firmware: FIRMWARE_RESTART (out of a shutdown), else RESTART
  restartKlipper: (model, firmware) => request("POST", "/api/printers/restart", { model, firmware }),
  // The whole printer anew: the U1 over SSH, others through Moonraker
  rebootPrinter: (model) => request("POST", "/api/printers/reboot", { model }),
  // Page "Kalibrieren": the ticks; the printer itself comes live (live.js).
  calibration: (id) => request("GET", `${instUrl(id)}/calibration`),
  markCalibration: (id, filament, step, done, temp) => request("POST", `${instUrl(id)}/calibration`, { filament, step, done, temp }),
  deleteBackup: (id, name) => request("DELETE", backupUrl(id, name)),
  // Page "Import/Export" (orcaone/importer.py): what a file holds, and own profiles as a ZIP.
  importFile: (id, file, name) => upload(`${instUrl(id)}/import?name=${encodeURIComponent(name)}`, file),
  // The slicer's own copies of user/ (user_backup-v…), and what one of them holds.
  // A filament of the file hung onto a printer here: what it would become (importer.attach).
  importAttach: (id, body) => request("POST", `${instUrl(id)}/import/attach`, body),
  slicerBackups: (id) => request("GET", `${instUrl(id)}/import/slicer-backups`),
  importSlicerBackup: (id, name) => request("GET", `${instUrl(id)}/import/slicer-backup?name=${encodeURIComponent(name)}`),
  exportProfiles: (id, profiles, flat) => download(`${instUrl(id)}/export`, { profiles, flat }),
  clean3mf: (file) => download("/api/clean-3mf", file),
  // Page "Änderungen": what changed since the installation was last marked seen (orcaone/snapshot.py).
  news: (id) => request("GET", `${instUrl(id)}/news`),
  newsSeen: (id) => request("POST", `${instUrl(id)}/news/seen`),
  restorePlan: (id, name) => request("POST", `${backupUrl(id, name)}/restore-plan`),
};
