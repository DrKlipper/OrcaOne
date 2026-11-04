import struct
import zlib

import pytest

from conftest import FIXTURES
from orcaone import opc

SYSTEM = FIXTURES / "orca" / "system"


def patched(blob: bytes, header_version: int | None = None, cache_version: int | None = None) -> bytes:
    """The cache with another version in the header or the body, CRC recomputed."""
    magic, version, _, _ = opc.HEADER.unpack_from(blob)
    body = bytearray(blob[opc.HEADER.size:])
    if cache_version is not None:
        body[0:4] = struct.pack("<I", cache_version)
    return opc.HEADER.pack(magic, header_version or version, len(body), zlib.crc32(body)) + bytes(body)


def pack_str(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def pack_strs(items) -> bytes:
    return struct.pack("<Q", len(items)) + b"".join(pack_str(i) for i in items)


def build_cache_v2(vendor: str = "TestMaker", keys=None, process=(), filament=(), machine=()) -> bytes:
    """A vendor cache in CACHE_VERSION 2, all option values coString. Entries:
    (name, config {key: text}, inherits, includes, instantiation). For tests of OrcaSlicer 2.5.
    keys: the dictionary's option keys; default: every key any config uses."""
    if keys is None:
        keys = list(dict.fromkeys(k for entries in (process, filament, machine) for e in entries for k in e[1]))

    def entry(e) -> bytes:
        name, config, inherits, includes, instantiation = e
        out = pack_str(name) + pack_str("")                        # name, sub_path
        out += struct.pack("<I", len(config))                      # config
        for key, value in config.items():
            out += struct.pack("<H", keys.index(key)) + pack_str(value)
        return out + pack_str(inherits) + pack_strs(list(includes)) \
            + pack_str("") + pack_str(instantiation) + pack_str("") + pack_str("") + pack_strs([])

    types = struct.pack("<Q", len(keys)) + struct.pack(f"<{len(keys)}H", *([opc.CO_STRING] * len(keys)))
    vendor_profile = pack_str(vendor) + pack_str("") * 4 + struct.pack("<Q", 0) + pack_strs([]) + pack_strs([])
    body = struct.pack("<I", 2) + pack_str(vendor) + pack_str("1.0.0")  # cache_version and stamps
    body += pack_strs(list(keys)) + types + pack_strs([""])             # the dictionary
    body += struct.pack("<Q", 1) + pack_str(vendor) + vendor_profile    # the vendor map
    for entries in (process, filament, machine):
        body += struct.pack("<I", len(entries)) + b"".join(entry(e) for e in entries)
    body += struct.pack("<Q", 0)                                        # parse_errors
    return opc.HEADER.pack(opc.CACHE_MAGIC, 2, len(body), zlib.crc32(body)) + body


def test_reads_the_snapmaker_cache():
    cache = opc.read_opc(SYSTEM / "Snapmaker.opc")
    assert (cache.cache_version, cache.vendor_name, cache.vendor_version) == (1, "Snapmaker", "2.4.0.15")
    assert (len(cache.machine), len(cache.process), len(cache.filament), cache.parse_errors) == (101, 134, 327, 0)
    u1 = next(m for v in cache.vendors.values() for m in v.models if m.name == "Snapmaker U1")
    assert u1.variants == ["0.2", "0.4", "0.4+0.6", "0.6", "0.8"]


def test_values_come_out_as_in_a_profile_json():
    cache = opc.read_opc(SYSTEM / "Snapmaker.opc")
    printer = next(e for e in cache.machine if e.name == "Snapmaker U1 (0.4 nozzle)")
    values = {key: opc.to_json_value(option) for key, option in printer.config.items()}
    assert printer.inherits == "fdm_U1"
    assert values["printer_variant"] == "0.4"
    assert values["printable_height"] == "270.05"
    assert values["retraction_length"] == ["1.5", "1.5", "1.5", "1.5"]


def test_reads_library_metadata():
    cache = opc.read_opc(SYSTEM / "OrcaFilamentLibrary.opc")
    generic = next(e for e in cache.filament if e.name == "Generic PLA @System")
    assert (generic.inherits, generic.instantiation, generic.renamed_from) == ("fdm_filament_pla", "true", ["My Generic PLA"])


def test_reads_cache_version_2():
    """OrcaSlicer 2.5 (24.09.2026): CACHE_VERSION 2 inserts a preset's includes after inherits."""
    cache = opc.parse_opc(build_cache_v2(keys=["nozzle_temperature"], filament=[
        ("Basis", {"nozzle_temperature": "220"}, "", [], "false"),
        ("Mit Basis", {}, "", ["Basis"], "true")]))
    assert cache.cache_version == 2
    entries = {e.name: e for e in cache.filament}
    assert entries["Mit Basis"].includes == ["Basis"] and entries["Basis"].instantiation == "false"
    assert opc.to_json_value(entries["Basis"].config["nozzle_temperature"]) == "220"


@pytest.mark.parametrize("change", [{"header_version": 99}, {"cache_version": 99}])
def test_unknown_version_gives_a_code(tmp_path, change):
    path = tmp_path / "Snapmaker.opc"
    path.write_bytes(patched((SYSTEM / "Snapmaker.opc").read_bytes(), **change))
    with pytest.raises(opc.OpcError) as err:
        opc.read_opc(path)
    assert err.value.code == "opc_unsupported_version"


def test_damaged_files_give_a_code(tmp_path):
    blob = (SYSTEM / "Custom.opc").read_bytes()
    flipped = bytearray(blob)
    flipped[100] ^= 0xFF
    cases = {"crc.opc": bytes(flipped), "magic.opc": b"XXXX" + blob[4:], "short.opc": blob[:10],
             "cut.opc": blob[:-20]}
    for name, data in cases.items():
        (tmp_path / name).write_bytes(data)
        with pytest.raises(opc.OpcError) as err:
            opc.read_opc(tmp_path / name)
        assert err.value.code == "opc_corrupt", name
    with pytest.raises(opc.OpcError) as err:
        opc.read_opc(tmp_path / "missing.opc")
    assert err.value.code == "opc_unreadable"
