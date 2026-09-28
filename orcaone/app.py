"""FastAPI app: JSON API under /api, the static UI under /."""

import asyncio
import ipaddress
import json
import math
import mimetypes
import re
import socket
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import anyio
from fastapi import Body, FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from . import (__version__, backup, calibration, camera, console, control, covers, guard, history, importer, instances, live, logs,
               monitor, errors, network, operations, overview, printer_files, printer_logs, scanner, settings, snapshot, ssh)
from .resolver import Resolver

STATIC_DIR = Path(__file__).parent / "static"
# The names this computer goes by in the LAN besides its addresses; not getfqdn(), whose reverse
# lookup can block the start.
_OWN_NAMES = {name.lower() for name in ("localhost", socket.gethostname(), socket.gethostname() + ".local")}
# An installation's id (instances.instance_id), part of a path to its backups.
_INSTANCE_ID = re.compile(r"[0-9a-f]{12}")

# On Windows the registry can map .js to text/plain, and browsers then refuse to
# run ES modules.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


class Utf8Response(JSONResponse):
    """JSONResponse that does not fail on odd file names: on Linux a name that is not valid UTF-8
    (from a Latin-1 ZIP, say) reaches Python with surrogate escapes, which strict UTF-8 refuses.
    Those characters become "?"."""

    def render(self, content) -> bytes:
        text = json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        return text.encode("utf-8", "replace")


@asynccontextmanager
async def _running(_app):
    # The recording of every printer with an address for the page "Diagramme" (live.recording), as long
    # as the server runs.
    task = asyncio.create_task(live.recording()) if live.RECORD else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="OrcaOne", version=__version__, docs_url=None, redoc_url=None, openapi_url=None,
              default_response_class=Utf8Response, lifespan=_running)


def _hostname(value: str) -> str | None:
    try:
        return urlparse(f"//{value}").hostname
    except ValueError:
        return None   # "[" without "]" and the like


def _host_ok(value: str) -> bool:
    """A Host header a page of OrcaOne sends: an IP address, localhost or this computer's name.
    Any other name may be DNS rebinding (a page whose name its owner lets resolve to this
    computer), an address cannot: only this computer serves a page at its address."""
    name = _hostname(value)
    if not name:
        return False
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return name.rstrip(".") in _OWN_NAMES
    return not (ip.is_unspecified or ip.is_multicast)


def _own_page(websocket: WebSocket) -> bool:
    """For WebSockets, which the HTTP guard below does not see and which browsers let any page
    open: Host as there, and Origin exactly OrcaOne's own. Closing before accepting refuses them."""
    host = websocket.headers.get("host", "")
    return _host_ok(host) and websocket.headers.get("origin") == f"http://{host}"


def is_remote(client) -> bool:
    """A client on another device (Starlette's request.client or websocket.client): the address of
    the connection, as uvicorn runs without proxy headers (__main__.py). What lends out this
    computer's identity or reaches its folders stays with the computer itself."""
    try:
        ip = ipaddress.ip_address(client.host)
    except (AttributeError, ValueError):
        return True
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_loopback


@app.middleware("http")
async def check_request(request: Request, call_next):
    # OrcaOne listens on every interface and needs no login (the user's wish of 25.09.2026: any
    # device in the LAN, "Ist nix wichtiges dran"). Against other web pages in the user's
    # browser: checking Host blocks DNS rebinding, checking Origin blocks other pages (even other
    # local ports) from sending changes, and refusing frames blocks clickjacking.
    host = request.headers.get("host", "")
    if not _host_ok(host):
        return Utf8Response({"error": "forbidden"}, status_code=403)
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origin and origin != f"http://{host}":
        return Utf8Response({"error": "forbidden"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    # An answer of the API never runs as a page: a printer's file opened in a tab (an HTML or SVG
    # file of a printer, or of a host posing as one) would otherwise run script as OrcaOne.
    response.headers["Content-Security-Policy"] = ("sandbox; frame-ancestors 'none'" if request.url.path.startswith("/api/")
                                                   else "frame-ancestors 'none'")
    # Revalidate every file: browsers otherwise keep old ES modules after an
    # update of OrcaOne and mix them with new ones. An answer may say otherwise (printer pictures).
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


def _error(code: str, status: int = 400, **params) -> JSONResponse:
    return Utf8Response({"error": code, **params}, status_code=status)


@app.exception_handler(operations.OperationError)
def _operation_error(request: Request, exc: operations.OperationError):
    return _error(exc.code, exc.status, **exc.params)


@app.exception_handler(operations.InvalidChange)
def _invalid_change(request: Request, exc: operations.InvalidChange):
    return _error("invalid_change", index=exc.index, field=exc.field)


@app.exception_handler(backup.BackupError)
def _backup_error(request: Request, exc: backup.BackupError):
    return _error(exc.code, 404 if exc.code == "backup_not_found" else 500)


@app.websocket("/api/ssh")
async def ssh_terminal(websocket: WebSocket, model: str = ""):
    # The page "SSH" (orcaone/ssh.py). This computer's SSH keys and agent only for a page on this
    # computer: from the LAN anyone could name a "printer" at any host and log in there with them.
    if not _own_page(websocket):
        await websocket.close(code=1008)
        return
    await ssh.session(websocket, model, keys=not is_remote(websocket.client))


@app.websocket("/api/network")
async def network_page(websocket: WebSocket, model: str = ""):
    # The page "Netzwerk" (orcaone/network.py): SSH to the printer as for "SSH", so the same rules.
    if not _own_page(websocket):
        await websocket.close(code=1008)
        return
    await network.session(websocket, model, keys=not is_remote(websocket.client))


@app.websocket("/api/live")
async def live_values(websocket: WebSocket):
    # Live values of the printers a page watches (orcaone/live.py).
    if not _own_page(websocket):
        await websocket.close(code=1008)
        return
    await live.serve(websocket)


@app.exception_handler(camera.CameraError)
def _camera_error(request: Request, exc: camera.CameraError):
    status = {"camera_not_found": 404, "printer_not_found": 404, "camera_host_invalid": 400, "printer_invalid": 400, "printer_name_taken": 400, "search_failed": 500,
              "camera_every_invalid": 400, "object_invalid": 400, "pause_invalid": 400, "folder_unknown": 404, "folder_missing": 404, "file_not_found": 404, "file_invalid": 400,
              "folder_read_only": 400, "print_invalid": 400, "print_refused": 409, "gcode_invalid": 400,
              "name_invalid": 400, "name_taken": 409, "file_refused": 409, "upload_failed": 400,
              "wifi_printing": 409, "wifi_printing_unknown": 409, "ssh_login": 403, "ssh_user_invalid": 400, "ssh_key_invalid": 400, "ssh_login_invalid": 400, "log_query_invalid": 400, "range_unsatisfiable": 416, "ssh_key_missing": 400, "ssh_key_no_public": 400}.get(exc.code, 502)
    return _error(exc.code, status, **({"detail": exc.detail} if exc.detail else {}))


@app.exception_handler(calibration.CalibrationError)
def _calibration_error(request: Request, exc: calibration.CalibrationError):
    return _error(str(exc))


@app.exception_handler(logs.LogError)
def _log_error(request: Request, exc: logs.LogError):
    return _error(str(exc), 404 if str(exc) == "log_not_found" else 400)


@app.exception_handler(snapshot.SnapshotError)
def _snapshot_error(request: Request, exc: snapshot.SnapshotError):
    return _error(exc.code, 409)


@app.exception_handler(importer.ImportFailed)
def _import_error(request: Request, exc: importer.ImportFailed):
    status = {"file_too_big": 413, "unknown_profile": 404, "folder_unknown": 404, "profile_invalid": 409}.get(exc.code, 400)
    return _error(exc.code, status, **exc.params)


@app.get("/api/instances")
def list_instances():
    processes = guard.find_processes()
    process_dirs = [p.data_dir for p in processes if p.data_dir]
    found = instances.discover(process_dirs)
    manual = set(instances.manual_paths())
    return {
        "version": __version__,
        "instances": [
            {
                **asdict(instance),
                "manual": str(instance.data_dir) in manual,
                "run_state": asdict(guard.run_state(instance, processes)),
            }
            for instance in found
        ],
    }


# ---------------------------------------------------------------- OrcaOne's own settings (orcaone/settings.py)

LANGUAGES = ("de", "en")
THEMES = ("light", "dark")
# The two parts of OrcaOne (the user's wish of 25.09.2026): the slicers' profiles and the printers.
AREAS = ("slicer", "printer")
# What the page "Dateien" sorts by: name, size, date, print time.
FILE_SORT_KEYS = ("name", "size", "modified", "time")


def _chosen(value) -> dict:
    """The printer chosen last per part, {"slicer": model, "printer": name}: names only."""
    return ({a: v for a, v in value.items() if a in AREAS and isinstance(v, str) and 0 < len(v) <= 200}
            if isinstance(value, dict) else {})


def _chosen_instance(value) -> str | None:
    """The installation chosen last (its id, instances.instance_id), None if it is none."""
    return value if isinstance(value, str) and 0 < len(value) <= 64 else None


def _print_files(value) -> dict:
    """The print file chosen last per printer of the printer part, {"<printer>": "<path on it>"}."""
    return ({k: v for k, v in value.items() if isinstance(k, str) and 0 < len(k) <= 200 and isinstance(v, str) and 0 < len(v) <= 1000}
            if isinstance(value, dict) else {})


def _charts(value) -> dict:
    """The curves shown per printer on "Diagramme" (the user's wish of 27.09.2026), {"<printer>": [series]}."""
    if not isinstance(value, dict):
        return {}
    return {k: [n for n in v if isinstance(n, str) and 0 < len(n) <= 120][:60] for k, v in value.items()
            if isinstance(k, str) and 0 < len(k) <= 200 and isinstance(v, list)}


def _view3d(value) -> dict | None:
    """The camera of "3D Ansicht" as the user left it, in mm: {"position": [x, y, z], "target": [x, y, z]}."""
    point = lambda v: (isinstance(v, list) and len(v) == 3
                       and all(isinstance(n, (int, float)) and not isinstance(n, bool) and abs(n) < 1e6 and math.isfinite(n) for n in v))
    return ({"position": value["position"], "target": value["target"]}
            if isinstance(value, dict) and point(value.get("position")) and point(value.get("target")) else None)


def _files_sort(value) -> dict | None:
    """How the page "Dateien" sorts: {"key": "name", "size", "modified" or "time", "desc": bool}."""
    if isinstance(value, dict) and value.get("key") in FILE_SORT_KEYS and isinstance(value.get("desc"), bool) and len(value) == 2:
        return {"key": value["key"], "desc": value["desc"]}
    return None


def _risk(value):
    """The confirmation "use at your own risk" (the user's wish of 26.09.2026): when, and with which
    version of OrcaOne; None while there is none."""
    if isinstance(value, dict) and all(isinstance(value.get(k), str) and 0 < len(value[k]) <= 40 for k in ("at", "version")):
        return {"at": value["at"], "version": value["version"]}
    return None


@app.get("/api/settings")
def get_settings():
    stored = settings.load()
    language, theme, area = stored.get("language"), stored.get("theme"), stored.get("area")
    return {"language": language if language in LANGUAGES else None, "menu_collapsed": stored.get("menu_collapsed") is True,
            "theme": theme if theme in THEMES else None, "area": area if area in AREAS else None,
            "chosen_printer": _chosen(stored.get("chosen_printer")), "view3d": _view3d(stored.get("view3d")),
            "chosen_instance": _chosen_instance(stored.get("chosen_instance")), "print_file": _print_files(stored.get("print_file")),
            "files_sort": _files_sort(stored.get("files_sort")), "files_info": stored.get("files_info") is not False,
            "charts": _charts(stored.get("charts")), "record_idle": stored.get("record_idle") is True,
            "version": __version__, "risk_accepted": _risk(stored.get("risk_accepted"))}


@app.get("/api/progress")
def scan_progress():
    """What the running GET /api/data does, for the boot screen (overview.progress)."""
    return overview.progress()


@app.post("/api/settings")
def set_settings(payload: dict = Body(...)):
    """Any of: "language" ("de", "en"), "menu_collapsed" (the menu folded away), "theme" ("light", "dark"),
    "area" ("slicer", "printer": the part of OrcaOne used last, where the next start begins),
    "chosen_printer" ({"slicer": model} or {"printer": name}: the printer chosen last in that part, which
    the next start takes again; the user's wish of 25.09.2026), "view3d" (the camera of "3D Ansicht",
    which it takes again instead of the standard view; the user's wish of 25.09.2026), "accept_risk"
    (true: the user confirmed "use at your own risk", kept with the time and the version),
    "chosen_instance" (the installation chosen last) and "print_file" ({"<printer>": "<path>"}: the
    print file chosen last for a printer); the next start takes them again (the user's wish of 26.09.2026);
    "charts" ({"<printer>": [series]}: the curves shown on "Diagramme"); "record_idle" (true: the printers'
    values are kept at rest too, not only while printing or heating; history.py); "files_sort"
    ({"key", "desc"}): how the page "Dateien" sorts, and "files_info" (false: its info pane hidden),
    both kept for the next visit."""
    changed = {key: payload[key] for key in ("language", "menu_collapsed", "theme", "area", "record_idle", "files_info") if key in payload}
    chosen, view, accept = payload.get("chosen_printer"), payload.get("view3d"), payload.get("accept_risk")
    instance, files, charts = payload.get("chosen_instance"), payload.get("print_file"), payload.get("charts")
    sort = payload.get("files_sort")
    if ((not changed and chosen is None and view is None and accept is None and instance is None and files is None and charts is None and sort is None)
            or (charts is not None and (not isinstance(charts, dict) or not charts or _charts(charts) != charts))
            or (sort is not None and _files_sort(sort) != sort)
            or ("language" in changed and changed["language"] not in LANGUAGES)
            or ("chosen_instance" in payload and _chosen_instance(instance) is None)
            or (files is not None and (not isinstance(files, dict) or not files or _print_files(files) != files))
            or ("accept_risk" in payload and accept is not True)
            or not isinstance(changed.get("menu_collapsed", False), bool)
            or not isinstance(changed.get("record_idle", False), bool)
            or not isinstance(changed.get("files_info", False), bool)
            or ("theme" in changed and changed["theme"] not in THEMES)
            or ("area" in changed and changed["area"] not in AREAS)
            or (chosen is not None and (not isinstance(chosen, dict) or not chosen or _chosen(chosen) != chosen))
            or (view is not None and _view3d(view) != view)):
        return _error("setting_invalid")

    def edit(data):
        data.update(changed)
        if chosen:
            data["chosen_printer"] = {**_chosen(data.get("chosen_printer")), **chosen}
        if view is not None:
            data["view3d"] = view
        if instance is not None:
            data["chosen_instance"] = instance
        if files:
            data["print_file"] = {**_print_files(data.get("print_file")), **files}
        if charts:
            data["charts"] = {**_charts(data.get("charts")), **charts}
        if sort is not None:
            data["files_sort"] = sort
        if accept:
            data["risk_accepted"] = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "version": __version__}
    try:
        settings.change(edit)
    except OSError:
        return _error("save_failed", 500)
    return get_settings()


@app.get("/api/data")
def data():
    # Read fresh on every call: the slicer may have changed its files or started meanwhile.
    # A response directly: FastAPI's jsonable_encoder is slow for a megabyte of nested dicts.
    return Utf8Response(overview.build_all())


@app.post("/api/instances/manual")
def add_manual(request: Request, payload: dict = Body(...)):
    # Only at the computer itself: a folder of another device (\\host\share) would make Windows
    # send it the user's NTLM hash, and the answer would tell which paths exist.
    if is_remote(request.client):
        return _error("local_only", 403)
    path = payload.get("path")
    if not isinstance(path, str):
        return _error("path_not_found")
    try:
        instance = instances.add_manual_path(path)
    except ValueError as exc:
        return _error(str(exc))
    except OSError:
        return _error("save_failed", 500)
    return {"instance": asdict(instance)}


@app.delete("/api/instances/manual")
def remove_manual(request: Request, path: str):
    if is_remote(request.client):
        return _error("local_only", 403)
    try:
        instances.remove_manual_path(path)
    except ValueError as exc:
        return _error(str(exc), 404)
    except OSError:
        return _error("save_failed", 500)
    return {"removed": path}


@app.get("/api/instances/{instance_id}/profile")
def profile(instance_id: str, kind: str, name: str):
    # Read on demand: every value of every profile would make GET /api/data megabytes larger.
    details = overview.profile_details(operations.find_instance(instance_id)[0], kind, name) \
        if kind in ("filament", "process", "machine") else None
    if details is None:
        return _error("unknown_profile", 404, name=name)
    return details


# ---------------------------------------------------------------- changes (hard rule 5)

@app.post("/api/instances/{instance_id}/plan")
def make_plan(instance_id: str, payload: dict = Body(...)):
    changes = payload.get("changes")
    if not isinstance(changes, list):
        raise operations.InvalidChange(None, "changes")
    return {"plan": operations.make_plan(*operations.find_instance(instance_id), changes)}


@app.post("/api/instances/{instance_id}/apply")
def apply_plan(instance_id: str, payload: dict = Body(...)):
    return operations.apply(instance_id, payload.get("plan_id"))


# ---------------------------------------------------------------- backups (hard rule 4)

@app.get("/api/instances/{instance_id}/backups")
def list_backups(instance_id: str):
    operations.find_instance(instance_id)
    made = backup.list_backups(instance_id)
    return {"backups": made, "total_size": sum(b["size"] for b in made),
            "location": overview.home_path(backup.backup_dir(instance_id))}


@app.post("/api/instances/{instance_id}/backups")
def backup_now(instance_id: str):
    # Reads the data directory only, so every installation may have one.
    instance, _ = operations.find_instance(instance_id)
    return {"backup": backup.create(instance, "manual")}


@app.delete("/api/instances/{instance_id}/backups/{name}")
def delete_backup(request: Request, instance_id: str, name: str):
    # Works without the installation, too: its folder may be gone, its backups not. Only at the
    # computer itself: a backup is the way back after every change (hard rule 4).
    if is_remote(request.client):
        return _error("local_only", 403)
    if not _INSTANCE_ID.fullmatch(instance_id):
        return _error("backup_not_found", 404)
    backup.delete(instance_id, name)
    return {"deleted": name}


@app.post("/api/instances/{instance_id}/backups/{name}/restore-plan")
def restore_plan(instance_id: str, name: str):
    return {"plan": operations.restore_plan(*operations.find_instance(instance_id), name)}


# ---------------------------------------------------------------- the slicers' logs (orcaone/logs.py)

@app.get("/api/instances/{instance_id}/logs")
def list_logs(instance_id: str):
    instance, _ = operations.find_instance(instance_id)
    return {"files": logs.files(instance.data_dir), "location": overview.home_path(instance.data_dir / "log")}


@app.get("/api/instances/{instance_id}/logs/{name}")
def read_log(instance_id: str, name: str, show: str = "all", q: str = "", regex: bool = False):
    instance, _ = operations.find_instance(instance_id)
    return logs.read(instance.data_dir, name, show, q, regex=regex)


# ---------------------------------------------------------------- page "Änderungen" (orcaone/snapshot.py)

@app.get("/api/instances/{instance_id}/news")
def news(instance_id: str):
    return snapshot.news(operations.find_instance(instance_id)[0])


@app.post("/api/instances/{instance_id}/news/seen")
def news_seen(instance_id: str):
    # Writes only into OrcaOne's own folder data/, no plan needed (PLAN 1.5).
    return snapshot.seen(operations.find_instance(instance_id)[0])


# ---------------------------------------------------------------- page "Import/Export" (orcaone/importer.py)

def _answer(instance, source: dict, name: str) -> dict:
    """What a file or folder holds (importer.read, read_backup) and what an import would do here."""
    res = Resolver(scanner.scan(instance.data_dir, instance.slicer))
    project = {**source["project"], "uses": importer.uses(source, res)} if source.get("project") else None
    return {"file": name, "format": source["format"], "skipped": source["skipped"], "project": project,
            "profiles": importer.analyse(source, res, instance.slicer)}


def _read_file(instance_id: str, raw: bytes, name: str) -> dict:
    return _answer(operations.find_instance(instance_id)[0], importer.read(raw, name), name)


@app.post("/api/instances/{instance_id}/import")
async def import_read(instance_id: str, request: Request, name: str = ""):
    """What a file holds and what an import would do; writes nothing. The file is the body itself,
    no multipart and so no further package (docs/IMPORT-QUELLEN.md)."""
    if int(request.headers.get("content-length") or 0) > importer.MAX_FILE:
        raise importer.ImportFailed("file_too_big")
    raw = await request.body()
    # A 3MF of many megabytes takes a moment: not on the server's event loop.
    return await run_in_threadpool(_read_file, instance_id, raw, name or "import")


@app.get("/api/instances/{instance_id}/import/slicer-backups")
def import_slicer_backups(instance_id: str):
    """The slicer's own copies of user/ (user_backup-v…) in the data directory, to import from."""
    return {"backups": importer.slicer_backups(operations.find_instance(instance_id)[0].data_dir)}


@app.get("/api/instances/{instance_id}/import/slicer-backup")
def import_slicer_backup(instance_id: str, name: str = ""):
    """What one of those copies holds and what an import would do; writes nothing."""
    instance = operations.find_instance(instance_id)[0]
    return _answer(instance, importer.read_backup(instance.data_dir, name), name)


@app.post("/api/instances/{instance_id}/import/attach")
def import_attach(instance_id: str, payload: dict = Body(...)):
    """What a filament of the file would become, hung onto a printer here (importer.attach);
    writes nothing."""
    profile, parents, printer = payload.get("profile"), payload.get("parents") or [], payload.get("printer")
    if not isinstance(profile, dict) or not isinstance(parents, list) or not all(isinstance(p, dict) for p in parents) \
            or not isinstance(printer, str) or not printer:
        return _error("attach_invalid")
    instance = operations.find_instance(instance_id)[0]
    res = Resolver(scanner.scan(instance.data_dir, instance.slicer))
    return importer.analyse_attach(res, instance.slicer, profile, parents, printer)


@app.post("/api/clean-3mf")
async def clean_3mf(request: Request):
    """Page "3MF bereinigen": the 3MF back without the printer, process and filaments of its project,
    so the slicer does not set them up when opening it. Writes nothing; the page saves the answer."""
    if int(request.headers.get("content-length") or 0) > importer.MAX_FILE:
        raise importer.ImportFailed("file_too_big")
    raw = await request.body()
    return Response(content=await run_in_threadpool(importer.clean_3mf, raw), media_type="model/3mf")


@app.post("/api/instances/{instance_id}/export")
def export(instance_id: str, payload: dict = Body(...)):
    wanted = payload.get("profiles")
    if not isinstance(wanted, list) or not wanted or not all(
            isinstance(p, dict) and p.get("kind") in importer.KINDS and isinstance(p.get("name"), str) for p in wanted):
        return _error("export_invalid")
    instance = operations.find_instance(instance_id)[0]
    res = Resolver(scanner.scan(instance.data_dir, instance.slicer))
    data = importer.export(res, [(p["kind"], p["name"]) for p in wanted], payload.get("flat") is True)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="OrcaOne-Export.zip"'})


# ---------------------------------------------------------------- page "Kalibrieren" (orcaone/calibration.py)

@app.get("/api/instances/{instance_id}/calibration")
def get_calibration(instance_id: str):
    return calibration.state(instance_id)


@app.post("/api/instances/{instance_id}/calibration")
def mark_calibration(instance_id: str, payload: dict = Body(...)):
    operations.find_instance(instance_id)
    try:
        return calibration.mark(instance_id, payload.get("filament"), payload.get("step"), payload.get("done"), payload.get("temp"))
    except OSError:
        return _error("save_failed", 500)


# ---------------------------------------------------------------- camera of the U1 (orcaone/camera.py)

@app.get("/api/cameras")
def list_cameras():
    return {"cameras": camera.cameras()}


@app.get("/api/printers")
def list_printers():
    return {"printers": camera.printers()}


@app.get("/api/printers/ssh-state")
def printer_ssh_state(model: str = ""):
    # Whether the printer lets SSH in, a short look at port 22 without a login (ssh.probe); only a
    # printer OrcaOne knows, so from the LAN too.
    return {"state": ssh.probe(camera.host_of(model))}


@app.get("/api/printers/info")
def printer_info(model: str = ""):
    # Read only, any printer with Klipper and Moonraker: what its card on the page "Drucker" shows.
    return camera.info(camera.host_of(model))


@app.get("/api/printers/status")
def printer_status(model: str = ""):
    # Read only: state, progress and heads for the card, as "Kamera" reads them (camera.status).
    return camera.status(camera.host_of(model))


@app.get("/api/printers/monitor")
def printer_monitor(model: str = ""):
    # The page "Status" (orcaone/monitor.py): what the printer is doing now, read only.
    return monitor.read(camera.host_of(model))


@app.get("/api/printers/gcode")
def gcode_history(model: str = "", since: float = 0):
    # The page "Konsole" (orcaone/console.py): what Klipper said since then.
    return console.history(camera.host_of(model), since)


@app.post("/api/printers/gcode")
def gcode_send(payload: dict = Body(...)):
    # G-code the user typed or chose, for any printer with Klipper and an address.
    return console.send(camera.host_of(payload.get("model")), payload.get("script"))


# ---------------------------------------------------------------- SSH key per printer (orcaone/ssh.py)
# The keys of this computer: only for a page on it (is_remote), as the logins with them.
@app.get("/api/ssh/keys")
def ssh_keys(request: Request):
    if is_remote(request.client):
        return _error("local_only", 403)
    return {"keys": ssh.list_keys()}


@app.post("/api/printers/ssh")
def printer_ssh(request: Request, payload: dict = Body(...)):
    # The user and how a printer's SSH logs in: a key (a file name in ~/.ssh), login "auto" or the password.
    if is_remote(request.client):
        return _error("local_only", 403)
    return {"printers": ssh.save_setting(payload.get("model"), payload.get("user"), payload.get("key"), payload.get("login"))}


@app.post("/api/printers/ssh-key")
def printer_ssh_key(request: Request, payload: dict = Body(...)):
    # On the user's click: the chosen key onto the printer; a typed password only passes through.
    if is_remote(request.client):
        return _error("local_only", 403)
    password = payload.get("password")
    return ssh.install_key(payload.get("model"), password if isinstance(password, str) and password else None)


@app.post("/api/printers/search")
def search_printers():
    # About 6 s: Snapmaker printers that answer in the LAN (mDNS, orcaone/camera.py search).
    return {"found": camera.search()}


@app.post("/api/printers")
def set_printer(request: Request, payload: dict = Body(...)):
    # The address of a printer by its name, from its card on the page "Drucker"; empty takes it away.
    # With "name": another printer of the model "model" (camera.add_printer). Only at the computer
    # itself: the pages there log in at this address with its SSH keys, a device in the LAN would
    # choose the host they go to.
    if is_remote(request.client):
        return _error("local_only", 403)
    try:
        if "name" in payload:
            return {"printers": camera.add_printer(payload.get("model"), payload.get("name"), payload.get("host"))}
        return {"printers": camera.set_host(payload.get("model"), payload.get("host"))}
    except OSError:
        return _error("save_failed", 500)


@app.post("/api/cameras/{camera_id}")
def update_camera(camera_id: str, payload: dict = Body(...)):
    try:
        return {"camera": camera.set_every(camera_id, payload.get("every"))}
    except OSError:
        return _error("save_failed", 500)


@app.post("/api/cameras/{camera_id}/wake")
def wake_camera(camera_id: str):
    return {"result": camera.wake(camera.find(camera_id)["host"])}


@app.post("/api/cameras/{camera_id}/light")
def camera_light(camera_id: str, payload: dict = Body(...)):
    # On the user's wish (24.09.2026): the light in the U1 on or off.
    on = payload.get("on")
    if not isinstance(on, bool):
        return _error("light_invalid")
    return {"light": camera.set_light(camera.find(camera_id)["host"], on)}


@app.get("/api/cameras/{camera_id}/status")
def camera_status(camera_id: str):
    # Read only: spools, pressure advance and print state for the page "Kalibrieren".
    return camera.status(camera.find(camera_id)["host"])


@app.get("/api/history")
def printer_history(printer: str = "", seconds: float = 900, points: int = history.POINTS_MAX, until: float | None = None):
    # What OrcaOne recorded of a printer (history.py): the `seconds` up to now or up to `until` (a window
    # of the past on "Diagramme"), thinned to `points` time steps.
    if not printer or len(printer) > 200:
        return _error("printer_invalid")
    if not math.isfinite(seconds) or seconds <= 0 or (until is not None and not math.isfinite(until)):
        return _error("history_invalid")
    now = time.time()
    start = (now if until is None else until) - min(seconds, history.SECONDS_MAX)
    return history.read(printer, start, now if until is None else min(until, now), points=points)


@app.get("/api/covers/{key}")
def printer_cover(key: str):
    # A printer's picture, only one a scan named (covers.py): from the slicer's program folder or
    # data/covers/, else fetched from GitHub now. Kept an hour: the U1's is 350 KB, and the page
    # shows it on every page of the printer part. Without one OrcaOne's own drawing.
    path = covers.file_of(key)
    if path is not None:
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=3600"})
    fallback = covers.fallback_of(key)
    return RedirectResponse("/" + fallback, status_code=302) if fallback else _error("cover_unknown", 404)


@app.get("/api/cameras/{camera_id}/image")
def camera_image(camera_id: str):
    data, age = camera.image(camera.find(camera_id)["host"])
    return Response(content=data, media_type="image/jpeg", headers={} if age is None else {"X-Image-Age": f"{age:.0f}"})


# ---------------------------------------------------------------- the page "Dateien" (orcaone/printer_files.py)
# By model, for every Klipper printer with an address; the videos only on the U1. Text files open as
# text in the browser.
_TEXT_FILES = (".gcode", ".log", ".cfg", ".conf", ".json", ".txt", ".bkp")
# Types a printer's file keeps: pictures and videos the pages show.
_SHOWN_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "video/mp4", "text/plain"}


def _u1(model: str) -> bool:
    return (camera.printers().get(model) or {}).get("model") in camera.U1_MODELS


@app.get("/api/printers/folder")
def printer_folder(model: str = "", folder: str = "gcodes", path: str = ""):
    host, u1 = camera.host_of(model), _u1(model)
    return {"folders": printer_files.folders(host, u1), "folder": folder, "path": path, **printer_files.listing(host, folder, path, u1)}


@app.get("/api/printers/folder/file")
def printer_file(request: Request, model: str = "", folder: str = "", path: str = "", download: bool = False):
    # Pictures, videos and files pass through OrcaOne: the browser never talks to the printer itself.
    return _passed_on(printer_files.open_file(camera.host_of(model), folder, path, _range(request)), path, download)


def _range(request: Request) -> str | None:
    """The piece the browser asks for, if it is one plain range ("bytes=100-199", "bytes=100-"). A
    video player needs it: the U1's time-lapses keep their index at the end (moov after mdat, checked
    27.09.2026), without ranges the browser would first load the whole video."""
    wanted = request.headers.get("range", "")
    return wanted if re.fullmatch(r"bytes=\d+-\d*", wanted) else None


@app.post("/api/printers/folder/delete")
def delete_printer_files(payload: dict = Body(...)):
    # Print files, folders in "gcodes" and the U1's videos, on the user's click after a question.
    model = str(payload.get("model", ""))
    host, folder = camera.host_of(model), payload.get("folder")
    if folder == "camera" and not _u1(model):
        return _error("folder_read_only")
    return printer_files.delete(host, folder, payload.get("names"), payload.get("dirs"), _u1(model))


@app.post("/api/printers/folder/move")
def move_printer_files(payload: dict = Body(...)):
    # On the user's drag and drop: files and folders into another folder in "gcodes".
    model = str(payload.get("model", ""))
    return printer_files.move(camera.host_of(model), payload.get("paths"), payload.get("target"), _u1(model))


@app.post("/api/printers/folder/make")
def make_printer_folder(payload: dict = Body(...)):
    model = str(payload.get("model", ""))
    return printer_files.make_dir(camera.host_of(model), payload.get("parent"), payload.get("name"), _u1(model))


# Uploads run in threads of their own, two at a time: a browser gone quiet mid-upload (a phone leaving the
# WLAN) must not hold the threads every other endpoint shares, the emergency stop among them (review
# 27.09.2026); and each block has to come within UPLOAD_WAIT seconds.
_UPLOADS = anyio.CapacityLimiter(2)
UPLOAD_WAIT = 60


@app.post("/api/printers/folder/upload")
async def upload_printer_file(request: Request, model: str = "", folder: str = "", name: str = "", replace: bool = False):
    # A print file dropped on the page, the file itself as the body, passed on to Moonraker block by
    # block while it arrives (printer_files.upload); the blocking request runs in a thread.
    size = request.headers.get("content-length", "")
    if not size.isdigit():
        return _error("upload_failed", 411)
    host = camera.host_of(model)
    blocks = request.stream().__aiter__()

    async def next_block() -> bytes:
        try:
            with anyio.fail_after(UPLOAD_WAIT):
                return await blocks.__anext__()
        except StopAsyncIteration:
            return b""
        except ClientDisconnect:
            raise ValueError("the browser went away") from None
        except TimeoutError:
            raise ValueError("the browser went quiet") from None

    def chunks():
        while block := anyio.from_thread.run(next_block):
            yield block
    u1 = _u1(model)
    return await anyio.to_thread.run_sync(lambda: printer_files.upload(host, folder, name, int(size), chunks(), replace, u1),
                                          limiter=_UPLOADS)


def _passed_on(response, path: str, download: bool = False):
    """Moonraker's answer with a file, handed on to the browser block by block."""
    name = path.rsplit("/", 1)[-1]
    kind = (response.headers.get("Content-Type") or mimetypes.guess_type(name)[0] or "").split(";")[0].strip().lower()
    if not download and name.lower().endswith(_TEXT_FILES):
        kind = "text/plain; charset=utf-8"
    elif kind not in _SHOWN_TYPES:
        # What the printer names HTML, SVG or script comes as bytes, never as a page of OrcaOne.
        kind = "application/octet-stream"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"} if download else {}
    for name in ("Content-Length", "Content-Range", "Accept-Ranges"):
        if response.headers.get(name):
            headers[name] = response.headers[name]

    def chunks():
        try:
            while block := response.read(65536):
                yield block
        finally:
            response.close()
    return StreamingResponse(chunks(), status_code=response.status, media_type=kind, headers=headers)


# ---------------------------------------------------------------- print files of any Klipper printer
# By model, for the pages "3D Ansicht" and "2D Ansicht": the files in "gcodes" and one of them to
# read, whole or a piece of it (Range, for the G-code of one line).
@app.get("/api/printers/files")
def printer_print_files(model: str = "", path: str = ""):
    # The top bar reads a file chosen in a folder of "gcodes" in that folder (path, "" for the top).
    return printer_files.listing(camera.host_of(model), "gcodes", path, _u1(model))


@app.get("/api/printers/file")
def printer_print_file(request: Request, model: str = "", path: str = ""):
    return _passed_on(printer_files.open_file(camera.host_of(model), "gcodes", path, _range(request)), path)


# ---------------------------------------------------------------- errors of any Klipper printer (orcaone/errors.py)
@app.get("/api/printers/errors")
def printer_errors(model: str = ""):
    # Read only: now, before, and Snapmaker's words for the U1's codes (from Snapmaker Orca here).
    return errors.read(camera.host_of(model))


# ---------------------------------------------------------------- logs of any Klipper printer (orcaone/printer_logs.py)
# By model, for the page "Logs" of the printer part: read only, as written (the user's wish of 26.09.2026).
@app.get("/api/printers/logs")
def printer_logs_list(model: str = ""):
    return printer_logs.files(camera.host_of(model))


@app.get("/api/printers/log")
def printer_log(model: str = "", path: str = "", start: int | None = None, end: int | None = None):
    # Its end, or older than end, or from start (a jump, newer lines, following it).
    return printer_logs.read(camera.host_of(model), path, start, end)


@app.get("/api/printers/log/start")
def printer_log_start(model: str = "", path: str = ""):
    # Where Klipper or Moonraker last started in it, None without a start.
    return {"at": printer_logs.last_start(camera.host_of(model), path)}


@app.get("/api/printers/log/search")
def printer_log_search(model: str = "", path: str = "", q: str = "", regex: bool = False, context: int = 0):
    return printer_logs.search(camera.host_of(model), path, q, regex, context)


@app.get("/api/printers/log/download")
def printer_log_download(model: str = "", path: str = ""):
    # The file as it is, as a download, never as a page.
    return _passed_on(printer_files.open_file(camera.host_of(model), "logs", path), path, download=True)


@app.post("/api/printers/print")
def printer_print(payload: dict = Body(...)):
    # On the user's click in the top bar: a print file of any Klipper printer; the U1 starts through
    # /api/cameras/{id}/print with its display's options.
    return printer_files.start_plain(camera.host_of(str(payload.get("model", ""))), payload.get("path"))


@app.get("/api/printers/mesh")
def printer_mesh(model: str = ""):
    # The page "Höhenkarte": the bed mesh Klipper uses (orcaone/monitor.py), read only.
    return monitor.mesh(camera.host_of(model))


@app.get("/api/printers/control")
def printer_control(model: str = ""):
    # The page "Steuerung" (orcaone/control.py): the running print, its objects, a pause at a layer.
    return control.state(camera.host_of(model))


@app.post("/api/printers/exclude")
def printer_exclude(payload: dict = Body(...)):
    # On the user's click, after asking: one object of the running print left out.
    return control.exclude(camera.host_of(str(payload.get("model", ""))), payload.get("name"))


@app.post("/api/printers/pause-at")
def printer_pause_at(payload: dict = Body(...)):
    # On the user's click: a pause at a layer, or after the one printing now ("next").
    return control.pause_at(camera.host_of(str(payload.get("model", ""))), payload.get("layer"), payload.get("next"))


@app.post("/api/printers/pause")
def printer_pause(payload: dict = Body(...)):
    # On the user's click (the top bar, the page "Steuerung").
    return printer_files.pause(camera.host_of(str(payload.get("model", ""))))


@app.post("/api/printers/resume")
def printer_resume(payload: dict = Body(...)):
    return printer_files.resume(camera.host_of(str(payload.get("model", ""))))


@app.post("/api/printers/cancel")
def printer_cancel(payload: dict = Body(...)):
    # On the user's click, after asking (the top bar).
    return printer_files.cancel(camera.host_of(str(payload.get("model", ""))))


@app.post("/api/printers/emergency-stop")
def printer_emergency_stop(payload: dict = Body(...)):
    # On the user's second click (the top bar).
    return printer_files.emergency_stop(camera.host_of(str(payload.get("model", ""))))


@app.post("/api/printers/restart")
def printer_restart(payload: dict = Body(...)):
    # On the user's click: Klipper anew, with "firmware" also its boards (the way out of a shutdown).
    return printer_files.restart(camera.host_of(str(payload.get("model", ""))), payload.get("firmware") is True)


@app.post("/api/printers/reboot")
def printer_reboot(request: Request, payload: dict = Body(...)):
    # On the user's click, after a question: the whole printer anew; the U1 over SSH, with this
    # computer's keys only for a page on it (hard rule 8).
    return network.reboot(str(payload.get("model", "")), keys=not is_remote(request.client))



@app.get("/api/cameras/{camera_id}/print")
def print_setup(camera_id: str):
    return printer_files.print_setup(camera.find(camera_id)["host"])


@app.post("/api/cameras/{camera_id}/print")
def start_print(camera_id: str, payload: dict = Body(...)):
    # On the user's wish: a print with the options of the printer's display.
    return printer_files.start_print(camera.find(camera_id)["host"], payload.get("path"), payload.get("options"), payload.get("map"))


@app.get("/", include_in_schema=False)
def index():
    # The page in the design chosen in the menu, so it shows so from the first frame; without a
    # choice the system's (color-scheme in style.css).
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    theme = settings.load().get("theme")
    if theme in THEMES:
        html = html.replace("<html ", f'<html data-theme="{theme}" ', 1)
    return HTMLResponse(html)


from .profile_api import router as profile_router
from .profile_store import HistoryError


@app.exception_handler(HistoryError)
def _profile_history_error(request: Request, exc: HistoryError):
    status = (404 if exc.code.endswith("_missing") else
              400 if exc.code.startswith("invalid_") else 409)
    return _error(exc.code, status)


app.include_router(profile_router)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
