import json
import os
import urllib.parse

import pytest

from conftest import call, copy_fixture
from orcaone import logs

# As Snapmaker Orca and OrcaSlicer write it (docs/STAND.md, "Logs"): OrcaSlicer's system
# information runs over several lines.
LOG = """[info]\t2026-09-23 08:55:19.192448[Thread 0x00007c698042e7c0]:gui mode, Current OrcaSlicer Version 2.5.0-dev
[info]\t2026-09-23 08:55:19.289261[Thread 0x00007c698042e7c0]:Operating System:    Unix
System Architecture: 64 bit
Total RAM size [MB]: 16,805MB
[error]\t2026-09-23 08:55:19.387426[Thread 0x00007c698042e7c0]:get_version_from_json: parse OrcaFilamentLibrary.json got a parse_error
[warning]\t2026-09-23 08:55:20.850237[Thread 0x00007c698042e7c0]:get_version, get_version not supported
[fatal]\t2026-09-23 08:56:01.000001[Thread 0x00007c698042e7c0]:Unhandled exception
"""


def write_log(data_dir, name, text, mtime):
    folder = data_dir / "log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(text.encode("utf-8"))
    os.utime(folder / name, (mtime, mtime))


def test_files_newest_first_with_their_start(tmp_path):
    write_log(tmp_path, "2026-09-22-13-04-19.log.0", LOG.replace("2026-09-23", "2026-09-22"), 1_000)
    write_log(tmp_path, "debug_Wed_Sep_23_08_55_19_55230.log.0", LOG, 2_000)
    write_log(tmp_path, "empty.log.0", "", 500)
    found = logs.files(tmp_path)
    assert [(f["name"], f["started"]) for f in found] == [
        ("debug_Wed_Sep_23_08_55_19_55230.log.0", "2026-09-23 08:55:19"),
        ("2026-09-22-13-04-19.log.0", "2026-09-22 08:55:19"),
        ("empty.log.0", None)]
    assert found[0]["size"] == len(LOG.encode()) and found[0]["modified"] == 2_000
    assert logs.files(tmp_path / "missing") == []


def test_entries_levels_and_following_lines(tmp_path):
    write_log(tmp_path, "a.log.0", LOG, 1_000)
    read = logs.read(tmp_path, "a.log.0")
    assert read["counts"] == {"info": 2, "error": 1, "warning": 1, "fatal": 1}
    assert (read["total"], read["matched"], read["cut"]) == (5, 5, False)
    assert not any("more" in e for e in read["entries"])
    second = read["entries"][1]
    assert (second["level"], second["time"]) == ("info", "2026-09-23 08:55:19")
    assert second["text"] == "Operating System:    Unix\nSystem Architecture: 64 bit\nTotal RAM size [MB]: 16,805MB"
    assert [e["level"] for e in logs.read(tmp_path, "a.log.0", "problems")["entries"]] == ["error", "warning", "fatal"]
    assert [e["level"] for e in logs.read(tmp_path, "a.log.0", "errors")["entries"]] == ["error", "fatal"]


def test_search_and_the_last_entries(tmp_path):
    write_log(tmp_path, "a.log.0", LOG, 1_000)
    # Words in any order, any case; following lines count.
    found = logs.read(tmp_path, "a.log.0", query="ram SYSTEM")
    assert [e["n"] for e in found["entries"]] == [2] and found["matched"] == 1
    assert logs.read(tmp_path, "a.log.0", "errors", "version")["matched"] == 1
    # As a regular expression (the user's wish of 26.09.2026), case never matters; a broken one says so.
    assert [e["n"] for e in logs.read(tmp_path, "a.log.0", query=r"get_version\b.*NOT", regex=True)["entries"]] == [6]
    assert logs.read(tmp_path, "a.log.0", query="ram [MB]")["matched"] == 1          # plain: the brackets as they are
    for wrong in ("(", "x" * 201):
        with pytest.raises(logs.LogError, match="log_query_invalid"):
            logs.read(tmp_path, "a.log.0", query=wrong, regex=True)
    last = logs.read(tmp_path, "a.log.0", limit=2)
    assert [e["level"] for e in last["entries"]] == ["warning", "fatal"] and last["matched"] == 5


def test_long_entries_are_cut_after_the_search(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "TEXT_MAX", 10)
    write_log(tmp_path, "a.log.0", LOG, 1_000)
    read = logs.read(tmp_path, "a.log.0", query="unhandled exception")
    assert read["entries"][0]["text"] == "Unhandled " and read["entries"][0]["more"] == 9


def test_a_regex_looks_only_at_what_is_sent(tmp_path, monkeypatch):
    """Words go through the whole entry; a regular expression only through its first TEXT_MAX
    characters, as ".*x" on OrcaSlicer's profile list in one entry would take hours (review 26.09.2026)."""
    monkeypatch.setattr(logs, "TEXT_MAX", 10)
    write_log(tmp_path, "a.log.0", LOG, 1_000)
    assert logs.read(tmp_path, "a.log.0", query="exception")["matched"] == 1
    assert logs.read(tmp_path, "a.log.0", query="unhandled", regex=True)["matched"] == 1
    assert logs.read(tmp_path, "a.log.0", query="exception", regex=True)["matched"] == 0


def test_a_large_file_is_read_from_its_end(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "MAX_BYTES", 200)
    write_log(tmp_path, "a.log.0", LOG, 1_000)
    read = logs.read(tmp_path, "a.log.0")
    assert read["cut"] and read["entries"][-1]["text"] == "Unhandled exception"
    assert read["total"] < 5


def test_lines_before_the_first_entry_and_odd_bytes(tmp_path):
    folder = tmp_path / "log"
    folder.mkdir()
    (folder / "a.log.0").write_bytes(b"started without prefix\n[error]\t2026-09-23 08:55:19.1[Thread 0x1]:bad \xff byte\n")
    entries = logs.read(tmp_path, "a.log.0")["entries"]
    assert [(e["level"], e["text"]) for e in entries] == [("", "started without prefix"), ("error", "bad � byte")]


def test_only_files_in_log_can_be_read(tmp_path):
    write_log(tmp_path, "a.log.0", LOG, 1_000)
    (tmp_path / "Snapmaker_Orca.conf").write_text("{}")
    for name in ("../Snapmaker_Orca.conf", "missing.log", "", "."):
        with pytest.raises(logs.LogError, match="log_not_found"):
            logs.read(tmp_path, name)
    if os.name == "posix":
        (tmp_path / "log" / "link.log").symlink_to(tmp_path / "Snapmaker_Orca.conf")
        assert [f["name"] for f in logs.files(tmp_path)] == ["a.log.0"]
        with pytest.raises(logs.LogError, match="log_not_found"):
            logs.read(tmp_path, "link.log")
    with pytest.raises(logs.LogError, match="log_filter_invalid"):
        logs.read(tmp_path, "a.log.0", "everything")


def test_api(server, fake_home):
    data_dir = copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    write_log(data_dir, "2026-09-23-08-55-19.log.0", LOG, 2_000)
    inst = json.loads(call(f"{server}/api/data")[1])["instances"][0]
    base = f"{server}/api/instances/{inst['id']}/logs"

    status, body = call(base)
    listed = json.loads(body)
    assert status == 200 and [f["name"] for f in listed["files"]] == ["2026-09-23-08-55-19.log.0"]
    assert listed["location"] == "~/.config/Snapmaker_Orca/log"

    status, body = call(f"{base}/2026-09-23-08-55-19.log.0?show=problems&q=version")
    read = json.loads(body)
    assert status == 200 and [e["level"] for e in read["entries"]] == ["error", "warning"]

    quoted = urllib.parse.quote("../Snapmaker_Orca.conf", safe="")
    assert call(f"{base}/{quoted}")[0] == 404
    assert json.loads(call(f"{base}/missing.log")[1]) == {"error": "log_not_found"}
    assert call(f"{base}/2026-09-23-08-55-19.log.0?show=x")[0] == 400
    assert call(f"{server}/api/instances/nope/logs")[0] == 404


def test_secrets_never_leave(tmp_path):
    """Snapmaker Orca logs the MQTT login of the U1 at level info (MQTT.cpp); any device in the LAN
    may read the logs: from the name of a secret to the end of the line it is hidden, before any
    search, so a search cannot tell it either."""
    line = ("[info]\t2026-09-25 18:01:02.000001[Thread 0x1]:[MQTT_INFO] initializing MQTT SSL connection, server_address: "
            "10.30.40.174:8883, client_id: x, ca_content: A, cert_content: B, username: u1, password: Geh eim, 99\n"
            '[info]\t2026-09-25 18:01:03.000001[Thread 0x1]:{"access_code": "12345678", "token":"abc"}\n'
            "[info]\t2026-09-25 18:01:04.000001[Thread 0x1]:token refreshed\n")
    write_log(tmp_path, "s.log.0", line, 1_000)
    texts = [e["text"] for e in logs.read(tmp_path, "s.log.0")["entries"]]
    assert texts[0].endswith("username: u1, password: ***") and '"access_code": ***' in texts[1] and texts[2] == "token refreshed"
    assert logs.read(tmp_path, "s.log.0", query="Geh eim")["matched"] == 0


@pytest.mark.parametrize("name,raw", [
    ("network.log.enc", b"printable but encrypted"),
    ("network.LOG.ENC", b""),
    ("binary.log.0", bytes(range(256)) * 16),
    ("nul.log", b"header\x00payload"),
    ("invalid.log", b"\xff\xfe" * 200),
    ("controls.log", b"\x01\x02\x03" * 200),
], ids=["encrypted", "encrypted-uppercase", "binary", "nul", "invalid-utf8", "controls"])
def test_unreadable_files_are_listed_but_never_returned(tmp_path, name, raw):
    write_log(tmp_path, "text.log.0", LOG, 1000)
    path = tmp_path / "log" / name
    path.write_bytes(raw)
    os.utime(path, (2000, 2000))
    found = logs.files(tmp_path)
    assert [(f["name"], f["readable"]) for f in found] == [(name, False), ("text.log.0", True)]
    assert found[0]["started"] is None
    with pytest.raises(logs.LogError, match="^log_not_readable$"):
        logs.read(tmp_path, name)


def test_unicode_text_and_empty_files_are_readable(tmp_path):
    write_log(tmp_path, "unicode.log", "\tGrüße 世界 😀\r\n" * 3000, 1000)
    write_log(tmp_path, "empty.log", "", 500)
    assert all(f["readable"] for f in logs.files(tmp_path))
    assert "世界" in logs.read(tmp_path, "unicode.log")["entries"][0]["text"]
    assert logs.read(tmp_path, "empty.log")["entries"] == []


def test_read_checks_binary_after_text_header_and_listing(tmp_path, monkeypatch):
    write_log(tmp_path, "mixed.log", LOG * 100, 1000)
    listed = logs.files(tmp_path)
    with (tmp_path / "log" / "mixed.log").open("ab") as fh:
        fh.write(bytes(range(256)) * 40)
    monkeypatch.setattr(logs, "files", lambda _: listed)
    with pytest.raises(logs.LogError, match="^log_not_readable$"):
        logs.read(tmp_path, "mixed.log")


def test_api_rejects_binary_without_content(server, fake_home):
    data_dir = copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    write_log(data_dir, "network.log.enc", "synthetic encrypted payload", 2000)
    inst = json.loads(call(f"{server}/api/data")[1])["instances"][0]
    base = f"{server}/api/instances/{inst['id']}/logs"
    assert json.loads(call(base)[1])["files"][0]["readable"] is False
    status, body = call(f"{base}/network.log.enc")
    assert status == 400 and json.loads(body) == {"error": "log_not_readable"}


def test_listing_sample_boundary_does_not_reject_unicode(tmp_path):
    write_log(tmp_path, "boundary.log", "a" * 8190 + "😀", 1000)
    assert logs.files(tmp_path)[0]["readable"] is True
    assert logs.read(tmp_path, "boundary.log")["entries"]
