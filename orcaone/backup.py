"""Backups of a data directory as ZIP files (hard rule 4).

A backup holds the whole data directory except log/, cache/, web/, hms/, ota/, user/Temp/,
user/*/temp/ and user_backup-v*/ (scanner.in_backup), plus orcaone-backup.json with time, reason,
slicer, version, data directory and the file list. It lives in OrcaOne's folder data/ (settings.py)
as backups/<instance_id>/<YYYY-MM-DD_HHMMSS>_<reason>.zip, readable by the owner only: the .conf
holds credentials (FINDINGS 4.3).

A restore writes back the .conf and user/** only (hard rule 2); what it changes is planned and
written by orcaone/operations.py like any other change.
"""

import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import __version__, settings
from .model import SLICERS, Instance
from .scanner import in_backup

MANIFEST = "orcaone-backup.json"
# Backups made while the app was called Orfix (until 23.09.2026) carry this one.
OLD_MANIFEST = "orfix-backup.json"


def _manifest_name(zf: zipfile.ZipFile) -> str | None:
    names = set(zf.namelist())
    return next((m for m in (MANIFEST, OLD_MANIFEST) if m in names), None)
_NAME = re.compile(r"(?P<stamp>\d{4}-\d\d-\d\d_\d{6})(?:-(?P<seq>\d+))?_(?P<reason>[a-z_]+)")
_UTF8_FLAG = 0x800


class BackupError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _RawName(zipfile.ZipInfo):
    """An entry whose name goes into the ZIP as the raw bytes of the file name, without the UTF-8
    flag, the way Info-ZIP stores names on Linux. A name that is not valid UTF-8 (from a Latin-1
    ZIP, say) thus comes back unchanged. zipfile has no public way to do this; the name is kept
    as cp437 text, which maps every byte to one character and back."""

    def _encodeFilenameFlags(self):
        return self.filename.encode("cp437"), self.flag_bits & ~_UTF8_FLAG


def _entry_name(rel: str) -> tuple[type, str]:
    raw = os.fsencode(rel)
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return _RawName, raw.decode("cp437")
    return zipfile.ZipInfo, rel


def entry_path(info: zipfile.ZipInfo) -> str:
    """The relative path of an entry as the file system spells it (os.fsdecode)."""
    raw = info.filename.encode("utf-8") if info.flag_bits & _UTF8_FLAG else info.filename.encode("cp437")
    return os.fsdecode(raw).rstrip("/")


def _display(text: str) -> str:
    # For orcaone-backup.json and the API: a name that is not valid UTF-8 shows with "?".
    return os.fsencode(text).decode("utf-8", "replace")


def backup_dir(instance_id: str) -> Path:
    return settings.DATA_DIR / "backups" / instance_id


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        for folder in (path.parent, path):
            os.chmod(folder, 0o700)


def _raise(error: OSError):
    raise error


def walk(data_dir: Path, strict: bool = False):
    """(relative posix path, is_dir) of everything a backup holds, sorted. Symlinks are left out:
    they may point outside the data directory (orcaone/operations.py never writes through one).
    strict: a folder that cannot be listed raises OSError instead of being skipped quietly."""
    for root, dirs, names in os.walk(data_dir, onerror=_raise if strict else None):
        rel_root = PurePosixPath(Path(root).relative_to(data_dir).as_posix())
        dirs[:] = sorted(d for d in dirs if in_backup(rel_root / d) and not (Path(root) / d).is_symlink())
        for d in dirs:
            yield (rel_root / d).as_posix(), True
        for name in sorted(names):
            rel = rel_root / name
            if in_backup(rel) and not (Path(root) / name).is_symlink():
                yield rel.as_posix(), False


def _next_name(folder: Path, reason: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    # Numbered across all reasons of the same second, such as a change's backup and a manual one,
    # so the names keep the order; the folder lists them in any order (NTFS: alphabetically).
    seqs = [int(m["seq"] or 1) for p in folder.glob(f"{stamp}*.zip") if (m := _NAME.fullmatch(p.name[:-4]))]
    seq = max(seqs, default=0) + 1
    return f"{stamp}_{reason}" if seq == 1 else f"{stamp}-{seq}_{reason}"


def create(instance: Instance, reason: str, params: dict | None = None) -> dict:
    """Back up the data directory now. Raises BackupError("backup_failed") if a file cannot be
    read: without a complete backup OrcaOne writes nothing."""
    from .profile_jobs import report
    folder = backup_dir(instance.id)
    try:
        _private_dir(folder)
        name = _next_name(folder, reason)
    except OSError:
        raise BackupError("backup_failed") from None
    tmp = folder / f".{name}.zip.tmp"
    files = []
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as out, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
            entries = list(walk(instance.data_dir, strict=True))
            total_files = sum(not is_dir for _, is_dir in entries)
            report("backup", 0, total_files)
            for rel, is_dir in entries:
                path = instance.data_dir / rel
                cls, arcname = _entry_name(rel)
                info = cls.from_file(path, arcname, strict_timestamps=False)
                if is_dir:
                    # Folders go in as well, so a restore can remove the ones that came later.
                    info.CRC = info.compress_size = 0
                    zf.mkdir(info)
                    continue
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(path, "rb") as src, zf.open(info, "w") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                files.append(_display(rel))
                report("backup", len(files), total_files)
            manifest = {
                "orcaone": __version__,
                "created": datetime.now().astimezone().isoformat(timespec="seconds"),
                "reason": reason, "reason_params": params or {},
                "slicer": instance.slicer, "slicer_name": SLICERS[instance.slicer]["name"],
                "version": instance.version, "data_dir": _display(str(instance.data_dir)),
                "instance_id": instance.id, "files": files,
            }
            zf.writestr(MANIFEST, json.dumps(manifest, indent=4, ensure_ascii=False) + "\n")
        os.replace(tmp, folder / f"{name}.zip")
    except OSError:
        tmp.unlink(missing_ok=True)
        raise BackupError("backup_failed") from None
    return _entry(folder / f"{name}.zip")


def _entry(path: Path) -> dict:
    name = path.name[:-len(".zip")]
    entry = {"name": name, "created": None, "reason": None, "reason_params": {}, "size": 0, "files": 0}
    try:
        entry["size"] = path.stat().st_size
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read(_manifest_name(zf) or MANIFEST).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        entry["error"] = "backup_unreadable"
        return entry
    if isinstance(manifest, dict):
        entry.update(created=manifest.get("created"), reason=manifest.get("reason"),
                     reason_params=manifest.get("reason_params") or {},
                     files=len(manifest.get("files") or []))
    return entry


def _sort_key(entry: dict) -> tuple:
    match = _NAME.fullmatch(entry["name"])
    return (match["stamp"], int(match["seq"] or 1)) if match else ("", 0)


def list_backups(instance_id: str) -> list[dict]:
    """All backups of an installation, newest first."""
    folder = backup_dir(instance_id)
    try:
        paths = [p for p in folder.glob("*.zip") if p.is_file() and _NAME.fullmatch(p.name[:-4])]
    except OSError:
        return []
    return sorted((_entry(p) for p in paths), key=_sort_key, reverse=True)


def backup_path(instance_id: str, name: str) -> Path:
    """The ZIP of a backup name from the API. Raises BackupError("backup_not_found")."""
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise BackupError("backup_not_found")
    path = backup_dir(instance_id) / f"{name}.zip"
    if not path.is_file():
        raise BackupError("backup_not_found")
    return path


def delete(instance_id: str, name: str) -> None:
    path = backup_path(instance_id, name)
    try:
        path.unlink()
    except OSError:
        raise BackupError("delete_failed") from None


def restorable(instance: Instance, name: str) -> tuple[dict, set]:
    """What a restore writes back (hard rule 2): {relative path: bytes} of the .conf and the files
    in user/, and the folders in user/. Raises BackupError."""
    path = backup_path(instance.id, name)
    conf_name = f"{instance.slicer}.conf"
    files, dirs = {}, set()
    native_candidates = {}
    try:
        with zipfile.ZipFile(path) as zf:
            if _manifest_name(zf) is None:
                raise BackupError("backup_unreadable")
            for info in zf.infolist():
                rel = entry_path(info)
                parts = PurePosixPath(rel).parts
                # Only what OrcaOne itself put there: no absolute paths, no "..".
                if not parts or rel.startswith("/") or any(p in ("", ".", "..") for p in parts) or "\\" in rel:
                    continue
                if rel == conf_name and not info.is_dir():
                    files[rel] = zf.read(info)
                elif parts[0] == "user" and (len(parts) > 1 or info.is_dir()) and in_backup(PurePosixPath(rel)):
                    if info.is_dir():
                        dirs.add(rel)
                    else:
                        files[rel] = zf.read(info)
                elif parts[0] == "system" and not info.is_dir():
                    from .profile_native_paths import managed_path
                    if managed_path(rel):
                        native_candidates[rel] = zf.read(info)
            from .profile_native_paths import archive_owned_files
            for rel in archive_owned_files(native_candidates):
                files[rel] = native_candidates[rel]
                if rel.count("/") > 1:
                    dirs.update((str(PurePosixPath(rel).parent), str(PurePosixPath(rel).parent.parent)))
    except (OSError, zipfile.BadZipFile, ValueError):
        raise BackupError("backup_unreadable") from None
    return files, dirs
