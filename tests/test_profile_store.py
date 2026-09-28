import json
import subprocess
import sys

import pytest

from orcaone import settings
from orcaone.profile_store import HistoryError, get_object, put_object, replace_ref


INSTANCE = "a" * 12
REF = "b" * 32


def test_stale_generation_preserves_first_writer(data_dir):
    first = replace_ref(INSTANCE, REF, 0, {"state": "first"})
    assert first == {"state": "first", "generation": 1}
    with pytest.raises(HistoryError, match="draft_conflict"):
        replace_ref(INSTANCE, REF, 0, {"state": "second"})
    path = settings.DATA_DIR / "snapshots" / "profiles" / INSTANCE / "refs" / f"{REF}.json"
    assert json.loads(path.read_text(encoding="utf-8")) == first


def test_content_addressed_objects_remain_immutable(data_dir):
    old = put_object(INSTANCE, {"value": "old"})
    assert put_object(INSTANCE, {"value": "old"}) == old
    put_object(INSTANCE, {"value": "new"})
    assert get_object(INSTANCE, old) == {"value": "old"}


def test_missing_corrupt_and_invalid_ids(data_dir):
    with pytest.raises(HistoryError, match="invalid_id"):
        put_object("../escape", {})
    with pytest.raises(HistoryError, match="invalid_id"):
        replace_ref(INSTANCE, "../escape", 0, {})
    with pytest.raises(HistoryError, match="object_missing"):
        get_object(INSTANCE, "0" * 64)
    object_id = put_object(INSTANCE, {"value": 1})
    path = settings.DATA_DIR / "snapshots" / "profiles" / INSTANCE / "objects" / f"{object_id}.json"
    path.write_text('{"value":2}', encoding="utf-8")
    with pytest.raises(HistoryError, match="object_corrupt"):
        get_object(INSTANCE, object_id)


def test_known_secrets_are_absent_from_object_bytes(data_dir):
    object_id = put_object(INSTANCE, {"own": {"printhost_password": "hidden-value", "layer_height": "0.2"},
                                      "unknown": {"access_code": "secret-code"}})
    path = settings.DATA_DIR / "snapshots" / "profiles" / INSTANCE / "objects" / f"{object_id}.json"
    assert "hidden-value" not in path.read_text(encoding="utf-8")
    assert "secret-code" not in path.read_text(encoding="utf-8")
    assert get_object(INSTANCE, object_id)["own"] == {"layer_height": "0.2"}


def test_secret_role_and_raw_conf_are_not_archived(data_dir):
    object_id = put_object(INSTANCE, {"metadata": {"role": "secret", "value": "private-value"},
                                      "raw_conf": "raw-conf-value", "complete": False})
    path = settings.DATA_DIR / "snapshots" / "profiles" / INSTANCE / "objects" / f"{object_id}.json"
    raw = path.read_text(encoding="utf-8")
    assert "private-value" not in raw
    assert "raw-conf-value" not in raw
    assert get_object(INSTANCE, object_id)["complete"] is False


def test_failed_replace_keeps_existing_ref(data_dir, monkeypatch):
    replace_ref(INSTANCE, REF, 0, {"state": "first"})
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(settings, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        replace_ref(INSTANCE, REF, 1, {"state": "second"})
    path = settings.DATA_DIR / "snapshots" / "profiles" / INSTANCE / "refs" / f"{REF}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "first"


def test_second_writer_does_not_steal_live_process_lock(data_dir):
    from orcaone.profile_store import _writer
    with _writer(INSTANCE):
        with pytest.raises(HistoryError, match="writer_conflict"):
            replace_ref(INSTANCE, REF, 0, {"state": "second"})


def test_second_process_cannot_write_while_instance_is_locked(data_dir):
    from orcaone.profile_store import _writer
    code = ("from pathlib import Path\n"
            "from orcaone import settings\n"
            "from orcaone.profile_store import put_object, HistoryError\n"
            "import sys\n"
            "settings.DATA_DIR = Path(sys.argv[1])\n"
            "try:\n"
            "    put_object('aaaaaaaaaaaa', {'value': 'other'})\n"
            "except HistoryError as exc:\n"
            "    print(exc.code)\n")
    with _writer(INSTANCE):
        result = subprocess.run([sys.executable, "-c", code, str(settings.DATA_DIR)],
                                capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "writer_conflict"


def test_symlink_cannot_redirect_store(data_dir, tmp_path):
    root = settings.DATA_DIR / "snapshots" / "profiles"
    root.mkdir(parents=True)
    try:
        (root / INSTANCE).symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(HistoryError, match="unsafe_path"):
        put_object(INSTANCE, {"value": 1})


def test_failed_object_replace_leaves_no_published_object(data_dir, monkeypatch):
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(settings, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        put_object(INSTANCE, {"value": 1})
    folder = settings.DATA_DIR / "snapshots" / "profiles" / INSTANCE / "objects"
    assert list(folder.iterdir()) == []


def test_branch_draft_aggregate_failure_is_atomic(data_dir, monkeypatch):
    from orcaone.profile_store import get_ref, get_draft_ref, replace_branch_draft
    branch = replace_ref(INSTANCE, REF, 0, {"type": "branch", "state": "old"})
    first = replace_branch_draft(INSTANCE, REF, 1, 0, None, {"documents": {"old": True}})
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(settings, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        replace_branch_draft(INSTANCE, REF, 1, 1,
                             {"type": "branch", "state": "new"}, {"documents": {}})
    assert get_ref(INSTANCE, REF) == branch
    assert get_draft_ref(INSTANCE, REF) == first["draft"]


def test_branch_draft_cas_checks_both_generations_and_hides_internal_payload(data_dir):
    from orcaone.profile_store import get_ref, get_draft_ref, replace_branch_draft, list_refs
    replace_ref(INSTANCE, REF, 0, {"type": "branch", "state": "old"})
    first = replace_branch_draft(INSTANCE, REF, 1, 0, None, {"documents": {}})
    for branch_generation, draft_generation, code in [(0, 1, "branch_conflict"), (1, 0, "draft_conflict")]:
        with pytest.raises(HistoryError, match=code):
            replace_branch_draft(INSTANCE, REF, branch_generation, draft_generation,
                                 {"type": "branch", "state": "bad"}, {"documents": {"bad": True}})
    assert get_ref(INSTANCE, REF) == first["branch"]
    assert get_draft_ref(INSTANCE, REF) == first["draft"]
    assert "_draft" not in list_refs(INSTANCE)[0]


def test_legacy_draft_migrates_and_stale_file_cannot_resurrect(data_dir):
    from orcaone.profile_store import get_draft_ref, replace_branch_draft, replace_draft_ref
    replace_draft_ref(INSTANCE, REF, 0, {"documents": {"legacy": True}})
    replace_ref(INSTANCE, REF, 0, {"type": "branch", "state": "old"})
    assert get_draft_ref(INSTANCE, REF)["documents"] == {"legacy": True}
    replace_branch_draft(INSTANCE, REF, 1, 1, None, {"documents": {}})
    assert get_draft_ref(INSTANCE, REF)["documents"] == {}
