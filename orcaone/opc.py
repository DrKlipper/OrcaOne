"""Read an OrcaSlicer vendor preset cache (system/<Vendor>.opc, OrcaSlicer 2.5).

The layout follows src/libslic3r/PresetCacheFormat.{hpp,cpp}, Config.hpp and Preset.hpp of
OrcaSlicer main, written by cereal's BinaryOutputArchive (little endian, sizes are uint64).
CACHE_VERSION 1 and 2 are parsed (2 of 24.09.2026 inserts a preset's "includes" after
"inherits"); magic, size and CRC are checked first. Anything else raises OpcError with an
error code instead of guessing. Details: docs/FINDINGS.md, "Das .opc-Format".
"""

import math
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

CACHE_MAGIC = 0x4F52435A  # "ORCZ", stored little endian -> bytes "ZCRO"
# CACHE_VERSION in PresetCacheFormat.cpp: 1 was the 2.5.0-dev of September 2026, 2 came with
# CachedPreset.includes on 24.09.2026 (commit 2b602943a5, "Load profile includes").
SUPPORTED_CACHE_VERSIONS = {1, 2}
HEADER = struct.Struct("<IIQI")  # magic, version, data_size, crc32 (#pragma pack(1), 20 bytes)

INT_MAX = 2**31 - 1   # nil of ConfigOptionIntsNullable / EnumsGenericNullable
BOOL_NIL = 255        # nil of ConfigOptionBoolsNullable (unsigned char max)
ENUM_UNNAMED = 0      # CacheDictionary::ENUM_UNNAMED

# ConfigOptionType (Config.hpp). Vector types are scalar + 0x4000.
VEC = 0x4000
CO_FLOAT, CO_INT, CO_STRING, CO_PERCENT, CO_FLOAT_OR_PERCENT = 1, 2, 3, 4, 5
CO_POINT, CO_POINT3, CO_BOOL, CO_ENUM = 6, 7, 8, 9
CO_FLOATS, CO_INTS, CO_STRINGS, CO_PERCENTS = VEC + 1, VEC + 2, VEC + 3, VEC + 4
CO_FLOATS_OR_PERCENTS, CO_POINTS, CO_BOOLS, CO_ENUMS = VEC + 5, VEC + 6, VEC + 8, VEC + 9
CO_POINTS_GROUPS, CO_INTS_GROUPS = VEC + 10, VEC + 11


class OpcError(Exception):
    """code: opc_unreadable, opc_unsupported_version or opc_corrupt."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class Reader:
    """Sequential reader for cereal's BinaryInputArchive encoding."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        end = self.pos + n
        if n < 0 or end > len(self.data):
            raise OpcError("opc_corrupt", f"truncated at offset {self.pos}")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def unpack(self, fmt: str):
        s = struct.Struct("<" + fmt)
        return s.unpack(self.take(s.size))

    def u8(self): return self.unpack("B")[0]
    def u16(self): return self.unpack("H")[0]
    def u32(self): return self.unpack("I")[0]
    def i32(self): return self.unpack("i")[0]
    def u64(self): return self.unpack("Q")[0]
    def f64(self): return self.unpack("d")[0]
    def boolean(self): return self.u8() != 0  # cereal writes bool as one byte

    def size(self) -> int:
        # cereal::size_type (uint64). The bound only guards against garbage.
        n = self.u64()
        if n > len(self.data) - self.pos:
            raise OpcError("opc_corrupt", f"implausible size at offset {self.pos - 8}")
        return n

    def string(self) -> str:
        # Profiles are UTF-8; keep stray bytes instead of failing.
        return self.take(self.size()).decode("utf-8", errors="surrogateescape")

    def strings(self) -> list[str]:
        return [self.string() for _ in range(self.size())]

    def array(self, fmt: str, count: int) -> list:
        # std::vector of an arithmetic type: one binary block.
        if count == 0:
            return []
        return list(struct.unpack(f"<{count}{fmt}", self.take(count * struct.calcsize(fmt))))


@dataclass
class Dictionary:
    keys: list
    types: list
    enum_values: list  # [0] is always ""


@dataclass
class PrinterModel:
    id: str
    name: str
    model_id: str
    technology: int  # PrinterTechnology: 0 FFF, 1 SLA, 2 Unknown, 3 Any
    family: str
    variants: list
    default_materials: list
    not_support_bed_types: list
    bed_model: str
    bed_texture: str
    image_bed_type: str
    bottom_texture_end_name: str
    use_double_extruder_default_texture: str
    bottom_texture_rect: str
    bottom_texture_rect_longer: str
    middle_texture_rect: str
    hotend_model: str


@dataclass
class VendorProfile:
    name: str
    id: str
    config_version: str
    config_update_url: str
    changelog_url: str
    models: list
    default_filaments: list
    default_sla_materials: list


@dataclass
class Option:
    type: int      # ConfigOptionType as written by the writer
    value: object  # python value, see read_option()


@dataclass
class Entry:
    name: str
    sub_path: str
    config: dict  # opt_key -> Option, the preset's own values, nothing inherited
    inherits: str
    description: str
    instantiation: str
    setting_id: str
    filament_id: str
    renamed_from: list
    includes: list = field(default_factory=list)  # CACHE_VERSION 2: layered under config, in this order


@dataclass
class VendorCache:
    cache_version: int
    vendor_name: str
    vendor_version: str  # Semver::to_string(), BBS 4-part form "2.4.0.15"
    vendors: dict
    process: list = field(default_factory=list)
    filament: list = field(default_factory=list)
    machine: list = field(default_factory=list)
    parse_errors: int = 0


def _printer_model(r: Reader) -> PrinterModel:
    # Field order = PrinterModel::serialize() in Preset.hpp.
    return PrinterModel(
        id=r.string(), name=r.string(), model_id=r.string(), technology=r.u8(),
        family=r.string(),
        variants=[r.string() for _ in range(r.size())],  # PrinterVariant = { name }
        default_materials=r.strings(), not_support_bed_types=r.strings(),
        bed_model=r.string(), bed_texture=r.string(), image_bed_type=r.string(),
        bottom_texture_end_name=r.string(), use_double_extruder_default_texture=r.string(),
        bottom_texture_rect=r.string(), bottom_texture_rect_longer=r.string(),
        middle_texture_rect=r.string(), hotend_model=r.string(),
    )


def _vendor_profile(r: Reader) -> VendorProfile:
    # Field order = VendorProfile::serialize(); std::set is size + elements.
    return VendorProfile(
        name=r.string(), id=r.string(), config_version=r.string(),
        config_update_url=r.string(), changelog_url=r.string(),
        models=[_printer_model(r) for _ in range(r.size())],
        default_filaments=r.strings(), default_sla_materials=r.strings(),
    )


def _enum(r: Reader, type_code: int, dic: Dictionary):
    # save_enum_option(): uint32 count, then per value a uint16 index into the enum names;
    # index 0 is followed by the raw int32.
    count = r.u32()
    if type_code == CO_ENUM and count != 1:
        raise OpcError("opc_corrupt", "scalar enum with more than one value")
    values = []
    for _ in range(count):
        idx = r.u16()
        if idx >= len(dic.enum_values):
            raise OpcError("opc_corrupt", "enum index past the dictionary")
        values.append(r.i32() if idx == ENUM_UNNAMED else dic.enum_values[idx])
    return values[0] if type_code == CO_ENUM else values


def read_option(r: Reader, t: int, dic: Dictionary):
    """Python value of one option: float/int/str/bool for scalars, FloatOrPercent as
    (value, is_percent), points as tuples, enums as name (or raw int), vectors as lists.
    Nil stays in its raw form: NaN, INT_MAX, 255."""
    if t in (CO_ENUM, CO_ENUMS):
        return _enum(r, t, dic)
    if t in (CO_FLOAT, CO_PERCENT):
        return r.f64()
    if t == CO_INT:
        return r.i32()
    if t == CO_STRING:
        return r.string()
    if t == CO_FLOAT_OR_PERCENT:
        return (r.f64(), r.boolean())
    if t == CO_POINT:
        return r.unpack("dd")
    if t == CO_POINT3:
        return r.unpack("ddd")
    if t == CO_BOOL:
        return r.boolean()
    if t in (CO_FLOATS, CO_PERCENTS):
        return r.array("d", r.size())
    if t == CO_INTS:
        return r.array("i", r.size())
    if t == CO_STRINGS:
        return r.strings()
    if t == CO_BOOLS:
        return r.array("B", r.size())  # vector<unsigned char>, 255 = nil
    if t == CO_FLOATS_OR_PERCENTS:
        return [(r.f64(), r.boolean()) for _ in range(r.size())]
    if t == CO_POINTS:
        flat = r.array("d", r.size() * 2)
        return list(zip(flat[0::2], flat[1::2]))
    if t == CO_POINTS_GROUPS:
        groups = []
        for _ in range(r.size()):
            flat = r.array("d", r.size() * 2)
            groups.append(list(zip(flat[0::2], flat[1::2])))
        return groups
    if t == CO_INTS_GROUPS:
        return [r.array("i", r.size()) for _ in range(r.size())]
    raise OpcError("opc_corrupt", f"unknown option type 0x{t:04x}")


def _config(r: Reader, dic: Dictionary) -> dict:
    config = {}
    for _ in range(r.u32()):
        idx = r.u16()
        if idx >= len(dic.keys):
            raise OpcError("opc_corrupt", "option index past the dictionary")
        t = dic.types[idx]
        config[dic.keys[idx]] = Option(t, read_option(r, t, dic))
    return config


def _entries(r: Reader, dic: Dictionary, version: int) -> list[Entry]:
    entries = []
    for _ in range(r.u32()):
        # visit_entry(): name, sub_path, config, then the remaining strings.
        name, sub_path = r.string(), r.string()
        config = _config(r, dic)
        entries.append(Entry(name, sub_path, config, inherits=r.string(),
                             includes=r.strings() if version >= 2 else [],
                             description=r.string(), instantiation=r.string(), setting_id=r.string(),
                             filament_id=r.string(), renamed_from=r.strings()))
    return entries


def parse_opc(blob: bytes) -> VendorCache:
    if len(blob) < HEADER.size:
        raise OpcError("opc_corrupt", "shorter than the header")
    magic, header_version, data_size, crc = HEADER.unpack_from(blob)
    if magic != CACHE_MAGIC:
        raise OpcError("opc_corrupt", f"bad magic 0x{magic:08x}")
    body = blob[HEADER.size:]
    if data_size == 0 or data_size != len(body):
        raise OpcError("opc_corrupt", "data size does not match")
    if zlib.crc32(body) != crc:  # boost::crc_32_type == zlib CRC-32
        raise OpcError("opc_corrupt", "CRC mismatch")
    if header_version not in SUPPORTED_CACHE_VERSIONS:
        raise OpcError("opc_unsupported_version", str(header_version))

    r = Reader(body)
    cache_version = r.u32()
    if cache_version not in SUPPORTED_CACHE_VERSIONS:
        raise OpcError("opc_unsupported_version", str(cache_version))
    vendor_name, vendor_version = r.string(), r.string()
    keys = r.strings()
    types = r.array("H", r.size())
    enum_values = r.strings()
    if len(keys) != len(types) or not enum_values or enum_values[0] != "":
        raise OpcError("opc_corrupt", "malformed dictionary")
    dic = Dictionary(keys, types, enum_values)
    vendors = {}
    for _ in range(r.size()):
        key = r.string()
        vendors[key] = _vendor_profile(r)
    cache = VendorCache(cache_version, vendor_name, vendor_version, vendors)
    cache.process = _entries(r, dic, cache_version)
    cache.filament = _entries(r, dic, cache_version)
    cache.machine = _entries(r, dic, cache_version)
    cache.parse_errors = r.u64()
    if r.pos != len(body):
        raise OpcError("opc_corrupt", "trailing bytes")
    return cache


def read_opc(path: Path) -> VendorCache:
    try:
        blob = Path(path).read_bytes()
    except OSError as exc:
        raise OpcError("opc_unreadable", str(exc)) from None
    return parse_opc(blob)


# ---------------------------------------------------------------- JSON string form

def _fmt_double(v: float) -> str:
    # std::ostream << double with default flags: precision 6, like printf("%g").
    return "%g" % v


def _scalar_json(t: int, v) -> str:
    if t in (CO_FLOAT, CO_FLOATS):
        return "nil" if math.isnan(v) else _fmt_double(v)
    if t in (CO_PERCENT, CO_PERCENTS):
        return "nil" if math.isnan(v) else _fmt_double(v) + "%"
    if t in (CO_FLOAT_OR_PERCENT, CO_FLOATS_OR_PERCENTS):
        val, pct = v
        return "nil" if math.isnan(val) else _fmt_double(val) + ("%" if pct else "")
    if t in (CO_INT, CO_INTS):
        # The cache does not say whether an option is nullable. INT_MAX is nil for every
        # nullable int option and no real setting uses it.
        return "nil" if (t == CO_INTS and v == INT_MAX) else str(v)
    if t in (CO_BOOL, CO_BOOLS):
        return "nil" if v == BOOL_NIL else ("1" if v else "0")
    if t in (CO_ENUM, CO_ENUMS):
        if isinstance(v, str):
            return v
        return "nil" if v == INT_MAX else str(v)  # unnamed raw int
    if t in (CO_STRING, CO_STRINGS):
        return v  # JSON keeps the raw string (save_to_json), not escape_string_cstyle
    raise OpcError("opc_corrupt", f"no scalar form for type 0x{t:04x}")


def to_json_value(opt: Option):
    """The value as ConfigBase::save_to_json writes it: serialize() for scalars (coString raw),
    vserialize() for vectors (a list of strings)."""
    t, v = opt.type, opt.value
    if t == CO_POINT:
        return f"{_fmt_double(v[0])},{_fmt_double(v[1])}"
    if t == CO_POINT3:
        return ",".join(_fmt_double(c) for c in v)
    if t == CO_POINTS:
        return [f"{_fmt_double(x)}x{_fmt_double(y)}" for x, y in v]
    if t == CO_POINTS_GROUPS:
        return [",".join(f"{_fmt_double(x)}x{_fmt_double(y)}" for x, y in g) for g in v]
    if t == CO_INTS_GROUPS:
        return [",".join(str(i) for i in g) for g in v]
    if t & VEC:
        return [_scalar_json(t, x) for x in v]
    return _scalar_json(t, v)
