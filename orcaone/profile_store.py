"""Content-addressed profile history objects and generation-checked references."""

import hashlib
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import psutil

from . import settings


_INSTANCE = re.compile(r"[0-9a-f]{12}\Z")
_UUID = re.compile(r"[0-9a-f]{32}\Z")
_OBJECT = re.compile(r"[0-9a-f]{64}\Z")
_SECRET = re.compile(r"apikey|password|token|secret|access_code", re.IGNORECASE)
_locks_guard = threading.Lock()
_locks = {}
_active = set()


class HistoryError(Exception):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


def validate_id(value: str, kind: str) -> str:
    pattern = {"instance": _INSTANCE, "profile": _UUID, "ref": _UUID,
               "branch": _UUID, "object": _OBJECT}[kind]
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise HistoryError("invalid_id", kind=kind)
    return value


def _safe(path: Path) -> Path:
    """Reject symlinks in our own storage path, including an existing leaf."""
    anchor = settings.DATA_DIR
    if anchor.is_symlink():
        raise HistoryError("unsafe_path")
    relative = path.relative_to(anchor)
    part = anchor
    for name in relative.parts:
        part = part / name
        if part.is_symlink():
            raise HistoryError("unsafe_path")
    return path


def _root(instance_id: str) -> Path:
    return _safe(settings.DATA_DIR / "snapshots" / "profiles" / validate_id(instance_id, "instance"))


def _canonical(value: dict) -> bytes:
    try:
        if not isinstance(value, dict):
            raise TypeError("expected object")
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                           allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise HistoryError("invalid_object") from exc


def _scrub(value):
    if isinstance(value, dict):
        if value.get("role") == "secret":
            return {"role": "secret"}
        return {key: _scrub(item) for key, item in value.items()
                if isinstance(key, str) and not _SECRET.search(key)
                and key not in {"raw_conf", "conf_text", "source_conf", ".conf"}}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _write(path: Path, payload: bytes) -> None:
    _safe(path).parent.mkdir(parents=True, exist_ok=True)
    temp = _safe(path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp"))
    try:
        with temp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        settings.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _process_start(pid: int) -> float | None:
    try:
        return psutil.Process(pid).create_time()
    except psutil.NoSuchProcess:
        return None
    except (psutil.Error, OSError):
        raise HistoryError("writer_conflict")


def _os_lock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise HistoryError("writer_conflict") from exc


def _os_unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _writer(instance_id: str):
    root = _root(instance_id)
    with _locks_guard:
        lock = _locks.setdefault(instance_id, threading.RLock())
    with lock:
        if instance_id in _active:
            raise HistoryError("writer_conflict")
        _active.add(instance_id)
        try:
            root.mkdir(parents=True, exist_ok=True)
            path = _safe(root / ".writer.lock")
            owner = {"pid": os.getpid(), "start": _process_start(os.getpid()), "nonce": uuid.uuid4().hex}
            # Keep the file stable: unlinking a lock file allows two processes to lock
            # different inodes. The OS releases this lock when its owner exits.
            with path.open("a+b") as handle:
                _os_lock(handle)
                try:
                    handle.seek(0)
                    handle.truncate()
                    handle.write(json.dumps(owner).encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
                    yield
                finally:
                    _os_unlock(handle)
        finally:
            _active.remove(instance_id)


def put_object(instance_id: str, obj: dict) -> str:
    payload = _canonical(_scrub(obj))
    object_id = hashlib.sha256(payload).hexdigest()
    with _writer(instance_id):
        path = _safe(_root(instance_id) / "objects" / f"{object_id}.json")
        if path.exists():
            get_object(instance_id, object_id)
        else:
            _write(path, payload)
    return object_id


def get_object(instance_id: str, object_id: str) -> dict:
    path = _safe(_root(instance_id) / "objects" / f"{validate_id(object_id, 'object')}.json")
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise HistoryError("object_missing", object_id=object_id) from exc
    if hashlib.sha256(payload).hexdigest() != object_id:
        raise HistoryError("object_corrupt", object_id=object_id)
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise HistoryError("object_corrupt", object_id=object_id) from exc
    if not isinstance(value, dict):
        raise HistoryError("object_corrupt", object_id=object_id)
    return value


def _get_ref(instance_id: str, ref_id: str, folder: str) -> dict | None:
    path = _safe(_root(instance_id) / folder / f"{validate_id(ref_id, 'ref')}.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, UnicodeError) as exc:
        raise HistoryError("ref_corrupt") from exc
    if not isinstance(value, dict) or type(value.get("generation")) is not int or value["generation"] < 1:
        raise HistoryError("ref_corrupt")
    return value


def get_ref(instance_id: str, ref_id: str) -> dict | None:
    value = _get_ref(instance_id, ref_id, "refs")
    return {key: item for key, item in value.items() if key != "_draft"} if value else None


def get_draft_ref(instance_id: str, ref_id: str) -> dict | None:
    branch = _get_ref(instance_id, ref_id, "refs")
    if branch and "_draft" in branch:
        draft = branch["_draft"]
        if draft is not None and (not isinstance(draft, dict) or type(draft.get("generation")) is not int
                                  or draft["generation"] < 1):
            raise HistoryError("ref_corrupt")
        return draft
    return _get_ref(instance_id, ref_id, "drafts")


def _replace_ref(instance_id: str, ref_id: str, expected: int, value: dict, folder: str) -> dict:
    validate_id(ref_id, "ref")
    if (type(expected) is not int or expected < 0 or not isinstance(value, dict)
            or "generation" in value or "_draft" in value):
        raise HistoryError("invalid_ref")
    with _writer(instance_id):
        old = _get_ref(instance_id, ref_id, folder)
        current = old["generation"] if old else 0
        if current != expected:
            raise HistoryError("draft_conflict", expected=expected, actual=current)
        result = {**_scrub(value), "generation": current + 1}
        if folder == "refs" and old and "_draft" in old:
            result["_draft"] = old["_draft"]
        path = _safe(_root(instance_id) / folder / f"{ref_id}.json")
        _write(path, _canonical(result))
        return {key: item for key, item in result.items() if key != "_draft"}


def replace_ref(instance_id: str, ref_id: str, expected: int, value: dict) -> dict:
    return _replace_ref(instance_id, ref_id, expected, value, "refs")


def replace_draft_ref(instance_id: str, ref_id: str, expected: int, value: dict) -> dict:
    branch = get_ref(instance_id, ref_id)
    if branch and branch.get("type") == "branch":
        return replace_branch_draft(instance_id, ref_id, branch["generation"], expected,
                                    None, value)["draft"]
    return _replace_ref(instance_id, ref_id, expected, value, "drafts")


def replace_branch_draft(instance_id: str, ref_id: str, expected_branch: int,
                         expected_draft: int, branch: dict | None, draft: dict | None) -> dict:
    """Publish branch/draft together with one atomic replace and two CAS checks.

    Legacy standalone drafts are read until the first aggregate publication. Their
    old file remains harmless: the aggregate always takes precedence, even for None.
    A None branch leaves its generation unchanged; a None draft leaves it unchanged.
    """
    validate_id(ref_id, "ref")
    if any(type(value) is not int or value < 0 for value in (expected_branch, expected_draft)):
        raise HistoryError("invalid_ref")
    for value in (branch, draft):
        if value is not None and (not isinstance(value, dict) or "generation" in value or "_draft" in value):
            raise HistoryError("invalid_ref")
    with _writer(instance_id):
        old_branch = get_ref(instance_id, ref_id)
        old_draft = get_draft_ref(instance_id, ref_id)
        if not old_branch or old_branch.get("type") != "branch":
            raise HistoryError("branch_missing")
        actual_draft = old_draft["generation"] if old_draft else 0
        if actual_draft != expected_draft:
            raise HistoryError("draft_conflict", expected=expected_draft, actual=actual_draft)
        if old_branch["generation"] != expected_branch:
            raise HistoryError("branch_conflict", expected=expected_branch, actual=old_branch["generation"])
        next_branch = {**_scrub(branch), "generation": expected_branch + 1} if branch is not None else old_branch
        next_draft = {**_scrub(draft), "generation": expected_draft + 1} if draft is not None else old_draft
        payload = {**next_branch, "_draft": next_draft}
        _write(_safe(_root(instance_id) / "refs" / f"{ref_id}.json"), _canonical(payload))
        return {"branch": next_branch, "draft": next_draft}


def list_refs(instance_id: str) -> list[dict]:
    folder = _safe(_root(instance_id) / "refs")
    if not folder.exists():
        return []
    return [get_ref(instance_id, path.stem) for path in sorted(folder.glob("*.json"))]
