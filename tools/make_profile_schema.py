"""Build release-bound technical profile catalogs without executing upstream C++."""

from __future__ import annotations

import argparse
from bisect import bisect_right
import copy
import hashlib
import json
import re
from pathlib import Path

if __package__:
    from tools.make_options import LISTS
else:
    from make_options import LISTS

ROOT = Path(__file__).resolve().parents[1]
RELEASES = {
    ("OrcaSlicer", "2.4.2"): ("8500fcdccaa10b5099ac20d252af3a7c560046f1", "orcaslicer-v2.4.2", "orca-2.4.2.json"),
    ("Snapmaker_Orca", "2.4.0"): ("b1831e5dcb464172de33783142425aafda834fbc", "snorca-v2.4.0", "snorca-2.4.0.json"),
}
TOKEN = re.compile(r'''(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|(?P<string>(?:u8)?"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|(?P<name>[A-Za-z_]\w*)|(?P<punct>->|::|[^\s])''')
VECTOR_TYPES = {"coFloats", "coInts", "coBools", "coStrings", "coPercents", "coFloatsOrPercents", "coEnums", "coPoints", "coPointsGroups"}


class SchemaBuildError(ValueError):
    def __init__(self, code, key="", expression="", source_line=None):
        self.code, self.key, self.expression, self.source_line = code, key, expression, source_line
        super().__init__(f"{code}: {key}: {expression} (line {source_line})")


def tokens(text):
    lines = [m.start() for m in re.finditer("\n", text)]
    return [(m.group(), bisect_right(lines, m.start()) + 1) for m in TOKEN.finditer(text) if m.lastgroup != "comment"]


def balanced(values, start):
    pairs = {"(": ")", "{": "}", "[": "]"}
    stack = [pairs[values[start]]]
    for i in range(start + 1, len(values)):
        if values[i] in pairs:
            stack.append(pairs[values[i]])
        elif values[i] in pairs.values():
            if values[i] != stack.pop():
                raise SchemaBuildError("unbalanced_source", expression=values[i])
            if not stack:
                return i
    raise SchemaBuildError("unbalanced_source")


def split_args(values):
    result, start, i = [], 0, 0
    while i < len(values):
        if values[i] in ("(", "{", "["):
            i = balanced(values, i)
        elif values[i] == ",":
            result.append(values[start:i])
            start = i + 1
        i += 1
    if values[start:]:
        result.append(values[start:])
    return result


def expression(values):
    return " ".join(values)


def literal(values, symbols):
    if values and values[0] == "(" and balanced(values, 0) == len(values) - 1:
        return literal(values[1:-1], symbols)
    if "".join(values) in symbols:
        return symbols["".join(values)]
    if values[:2] == ["L", "("] and balanced(values, 1) == len(values) - 1:
        return literal(values[2:-1], symbols)
    if len(values) == 2 and values[0] in ("-", "+") and values[1] in symbols and isinstance(symbols[values[1]], (int, float)):
        return symbols[values[1]] * (-1 if values[0] == "-" else 1)
    if len(values) == 1 and values[0] in symbols:
        return symbols[values[0]]
    if len(values) == 1 and values[0] in ("true", "false"):
        return values[0] == "true"
    if values and all(v.startswith(('"', 'u8"')) for v in values):
        return "".join(json.loads(v.removeprefix("u8")) for v in values)
    number = "".join(values)
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[fF]", number):
        number = number[:-1]
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", number):
        return float(number) if any(c in number for c in ".eE") else int(number)
    if values and values[0] == "{" and balanced(values, 0) == len(values) - 1:
        return [literal(x, symbols) for x in split_args(values[1:-1])]
    if len(values) > 2 and values[0] in ("Vec2d", "Vec3d", "FloatOrPercent") and values[1] in ("(", "{") and balanced(values, 1) == len(values) - 1:
        return {"constructor": values[0], "values": [literal(x, symbols) for x in split_args(values[2:-1])]}
    raise ValueError(expression(values))


def serial(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return format(value, ".6g")
    return str(value)


def default_value(values, option_type, symbols, enum_map):
    if not values or values[0] != "new":
        raise ValueError(expression(values))
    start = next((i for i, v in enumerate(values) if v in ("(", "{")), None)
    if start is None or balanced(values, start) != len(values) - 1:
        raise ValueError(expression(values))
    args = split_args(values[start + 1:-1])
    if option_type in VECTOR_TYPES and len(args) == 1 and args[0] and args[0][0] == "{" and option_type != "coFloatsOrPercents":
        args = split_args(args[0][1:-1])
    parsed = []
    for arg in args:
        if arg[:3] == ["(", "int", ")"]:
            arg = arg[3:]
        joined = "".join(arg)
        if re.fullmatch(r"ConfigOption\w+Nullable::nil_value\(\)", joined):
            parsed.append("nil")
        else:
            parsed.append(enum_map[joined] if joined in enum_map else literal(arg, symbols))
    vector = option_type in VECTOR_TYPES
    if option_type in ("coEnum", "coEnums"):
        if any(not isinstance(v, str) or (v != "nil" and v not in enum_map.values()) for v in parsed):
            raise ValueError(expression(values))
    if option_type == "coFloatOrPercent":
        if len(parsed) != 2 or not isinstance(parsed[1], bool):
            raise ValueError(expression(values))
        return serial(parsed[0]) + ("%" if parsed[1] else "")
    if option_type in ("coPoint", "coPoint3", "coPoints"):
        expected = "Vec3d" if option_type == "coPoint3" else "Vec2d"
        if any(not isinstance(v, dict) or v["constructor"] != expected for v in parsed):
            raise ValueError(expression(values))
        encoded = [("x" if vector else ",").join(serial(c) for c in v["values"]) for v in parsed]
        return encoded if vector else encoded[0]
    if option_type == "coFloatsOrPercents":
        pairs = [v["values"] if isinstance(v, dict) else v for v in parsed]
        return [serial(v[0]) + ("%" if v[1] else "") for v in pairs]
    if vector:
        if len(parsed) == 1 and isinstance(parsed[0], list):
            parsed = parsed[0]
        return [serial(v) + ("%" if option_type == "coPercents" and v != "nil" else "") for v in parsed]
    if not parsed and option_type == "coString":
        return ""
    if len(parsed) != 1:
        raise ValueError(expression(values))
    return serial(parsed[0]) + ("%" if option_type == "coPercent" else "")


def named_lists(text):
    vals = [v for v, _ in tokens(text)]
    out = {}
    for i, value in enumerate(vals[:-1]):
        if not re.fullmatch(r"[A-Za-z_]\w*", value):
            continue
        j = i + 2 if vals[i + 1] == "=" else i + 1
        if j < len(vals) and vals[j] == "{":
            end = balanced(vals, j)
            members = split_args(vals[j + 1:end])
            if all(len(x) == 1 and x[0].startswith('"') for x in members):
                out[value] = [json.loads(x[0]) for x in members]
    return out


def enum_maps(text, symbols):
    vals = [v for v, _ in tokens(text)]
    maps = {}
    for i, value in enumerate(vals):
        start = i + 2 if i + 1 < len(vals) and vals[i + 1] == "=" else i + 1
        if value.startswith("s_keys_map_") and start < len(vals) and vals[start] == "{":
            end = balanced(vals, start)
            mapping = {}
            for pair in split_args(vals[start + 1:end]):
                items = split_args(pair[1:-1])
                if len(items) == 2:
                    if items[1][:2] == ["int", "("] and items[1][-1] == ")":
                        items[1] = items[1][2:-1]
                    mapping["".join(items[1])] = literal(items[0], symbols)
            name = value.removeprefix("s_keys_map_")
            mapping.update({f"{name}::{key}": val for key, val in list(mapping.items()) if "::" not in key})
            mapping.update({key.removeprefix(name + "::"): val for key, val in list(mapping.items()) if key.startswith(name + "::")})
            maps[name] = mapping
    return maps


def definitions(text):
    ts = tokens(text)
    vals = [v for v, _ in ts]
    out, current, depth, owner_depth, i = {}, None, 0, 0, 0
    aliases = {}
    while i < len(vals):
        if vals[i:i + 5] == ["def", "=", "this", "->", "add"] or vals[i:i + 5] == ["def", "=", "this", "->", "add_nullable"]:
            end = balanced(vals, i + 5)
            args = split_args(vals[i + 6:end])
            current = None
            if len(args) == 2 and len(args[0]) == 1 and args[0][0].startswith('"') and len(args[1]) == 1:
                current = json.loads(args[0][0])
                entry = {"type": args[1][0], "nullable": vals[i + 4] == "add_nullable", "line": ts[i][1], "fields": {}, "enums": []}
                if current in out:
                    # ConfigDef::add returns the existing map entry, retaining fields.
                    entry["fields"] = out[current]["fields"]
                    entry["enums"] = out[current]["enums"]
                    entry["nullable"] |= out[current]["nullable"]
                out[current] = entry
                owner_depth = depth
                if i >= 2 and vals[i - 1] == "=":
                    aliases[vals[i - 2]] = current
            i = end + 1
            continue
        if current and vals[i:i + 2] == ["def", "->"] and i + 3 < len(vals):
            member = vals[i + 2]
            if member == "set_default_value" and vals[i + 3] == "(":
                end = balanced(vals, i + 3)
                out[current]["fields"]["default"] = vals[i + 4:end]
                i = end + 1
                continue
            if member in ("min", "max", "sidetext", "enum_keys_map", "enum_values", "gui_type", "nullable") and vals[i + 3] == "=":
                end = i + 4
                while end < len(vals) and vals[end] != ";":
                    if vals[end] in ("(", "{", "["):
                        end = balanced(vals, end)
                    end += 1
                assigned = vals[i + 4:end]
                if len(assigned) == 3 and assigned[1] == "->" and assigned[0] in aliases:
                    original = out[aliases[assigned[0]]]
                    if member == "enum_values":
                        out[current]["enums"] = copy.deepcopy(original["enums"])
                        assigned = original["fields"].get(member, ["{", "}"])
                    else:
                        assigned = original["fields"].get(assigned[2], assigned)
                out[current]["fields"][member] = assigned
                if member == "nullable":
                    out[current]["nullable"] = literal(assigned, {})
                i = end + 1
                continue
            if member == "enum_values" and vals[i + 3:i + 5] in ([".", "push_back"], [".", "emplace_back"]):
                end = balanced(vals, i + 5)
                out[current]["enums"].append(vals[i + 6:end])
                i = end + 1
                continue
        if current and vals[i + 1:i + 4] == ["=", "def", ";"]:
            aliases[vals[i]] = current
        if vals[i] == "{":
            depth += 1
        elif vals[i] == "}":
            depth -= 1
            if depth < owner_depth:
                current = None
        i += 1
    return out


def source_symbols(text):
    symbols = {}
    for match in re.finditer(r"^\s*#define\s+(\w+)\s+([^\n]+)", text, re.M):
        try:
            symbols[match[1]] = literal([v for v, _ in tokens(match[2])], symbols)
        except ValueError:
            pass
    for match in re.finditer(r"constexpr\s+const\s+char\s*\*\s*(\w+)\s*=\s*([^;]+);", text):
        symbols[match[1]] = literal([v for v, _ in tokens(match[2])], symbols)
    for match in re.finditer(r"(?:const|constexpr)\s+(?:int|double|float)\s+(\w+)\s*=\s*([^;]+);", text):
        try:
            value = literal([v for v, _ in tokens(match[2])], symbols)
            if match[1] in symbols and symbols[match[1]] != value:
                raise SchemaBuildError("ambiguous_symbol", expression=match[1])
            symbols[match[1]] = value
        except ValueError:
            pass
    return symbols


def loop_definitions(text, defs):
    """Interpret the two source-level declaration loops, never default values by name."""
    ts = tokens(text)
    vals = [v for v, _ in ts]
    lists = named_lists(text)
    axes = None
    for i, value in enumerate(vals[:-1]):
        if value == "axes" and vals[i + 1] == "{":
            end = balanced(vals, i + 1)
            axes = literal(vals[i + 1:end + 1], {})
        if value != "for" or vals[i + 1] != "(":
            continue
        end = balanced(vals, i + 1)
        if end + 1 >= len(vals) or vals[end + 1] != "{":
            continue
        body_end = balanced(vals, end + 1)
        header, body = vals[i + 2:end], vals[end + 2:body_end]
        if "add_nullable" in body and "opt_key" in header and "it_opt" in body:
            range_values = header[header.index(":") + 1:]
            keys = lists.get(range_values[0]) if len(range_values) == 1 else literal(range_values, {})
            if keys is None or "values" not in body or "default_value" not in body:
                raise SchemaBuildError("unresolved_nullable_loop", expression=expression(header), source_line=ts[i][1])
            supported_copies = set()
            for j in range(len(body) - 3):
                if body[j:j + 4] != ["def", "->", "set_default_value", "("]:
                    continue
                call_end = balanced(body, j + 3)
                copied = "".join(body[j + 4:call_end])
                match = re.fullmatch(r"newConfigOption(Floats|Percents|Bools|EnumsGeneric)Nullable\(static_cast<constConfigOption\1\*>\(it_opt->second.default_value.get\(\)\)->values\)", copied)
                if match is None:
                    raise SchemaBuildError("unresolved_nullable_loop", expression=copied, source_line=ts[i][1])
                supported_copies.add("coEnums" if match[1] == "EnumsGeneric" else "co" + match[1])
            for key in keys:
                base = key.removeprefix("filament_")
                target = "filament_" + base
                if base not in defs:
                    raise SchemaBuildError("missing_definition", base)
                if defs[base]["type"] not in supported_copies:
                    raise SchemaBuildError("unresolved_nullable_loop", base, defs[base]["type"], ts[i][1])
                entry = copy.deepcopy(defs[base])
                entry.update(nullable=True, line=ts[i][1], copied_from=base)
                defs[target] = entry
        if "AxisDefault" in header and "axes" in header and "add" in body:
            if axes is None:
                raise SchemaBuildError("unresolved_axis_loop", source_line=ts[i][1])
            for axis in axes:
                if len(axis) != 4:
                    raise SchemaBuildError("unresolved_axis_loop", expression=str(axis))
                replacements = dict(zip(("name", "max_feedrate", "max_acceleration", "max_jerk"), axis))
                expanded, j = [], 0
                while j < len(body):
                    if body[j:j + 2] == ["axis", "."] and j + 2 < len(body) and body[j + 2] in replacements:
                        replaced = replacements[body[j + 2]]
                        if isinstance(replaced, str):
                            if expanded and expanded[-1] == "+" and len(expanded) > 1 and expanded[-2].startswith('"'):
                                expanded[-2:] = [json.dumps(json.loads(expanded[-2]) + replaced)]
                            else:
                                expanded.append(json.dumps(replaced))
                        else:
                            expanded.extend(["{", *[v for v, _ in tokens(",".join(serial(x) for x in replaced))], "}"])
                        j += 3
                    else:
                        expanded.append(body[j])
                        j += 1
                for key, entry in definitions(expression(expanded)).items():
                    entry["line"] = ts[i][1]
                    entry["loop"] = "axes"
                    defs[key] = entry
    return defs


def extract_catalog(config_text: str, preset_text: str, rules: dict) -> dict:
    symbols = source_symbols(config_text) | rules.get("symbols", {})
    defs = loop_definitions(config_text, definitions(config_text))
    maps = enum_maps(config_text, symbols)
    lists = named_lists(preset_text)
    config_lists = named_lists(config_text)
    expected = {kind: sorted(set(k for name in names for k in lists.get(name, []))) for kind, names in LISTS.items()}
    expected["machine"] = sorted(set(expected["machine"] + config_lists.get("m_extruder_option_keys", [])))
    kinds, all_keys = {}, set()
    for kind, keys in expected.items():
        kinds[kind] = {}
        for key in keys:
            all_keys.add(key)
            if key not in defs:
                raise SchemaBuildError("missing_definition", key)
            raw = defs[key]
            fields = raw["fields"]
            mapping = {}
            map_expression = expression(fields.get("enum_keys_map", []))
            for name, values in maps.items():
                if name in map_expression.split() or f"< {name} >" in map_expression:
                    mapping = values
            try:
                enums = [literal(x, symbols) for x in raw["enums"]]
                enums = [item for value in enums for item in (value if isinstance(value, list) else [value])]
                if "enum_values" in fields:
                    enums += literal(fields["enum_values"], symbols)
                if raw["type"] in ("coEnum", "coEnums"):
                    enums = sorted(set(enums) | set(mapping.values()))
                default = default_value(fields.get("default", []), raw["type"], symbols, mapping)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                raise SchemaBuildError("unresolved_default", key, expression(fields.get("default", [])), raw["line"]) from exc
            limits = {}
            for limit in ("min", "max"):
                try:
                    limits[limit] = literal(fields[limit], symbols) if limit in fields else None
                except ValueError as exc:
                    raise SchemaBuildError("unresolved_limit", key, expression(fields[limit]), raw["line"]) from exc
            dimension = "scalar" if raw["type"] not in VECTOR_TYPES else rules.get("dimensions", {}).get(key)
            if dimension is None:
                raise SchemaBuildError("unclassified_dimension", key, raw["type"], raw["line"])
            unit_values = fields.get("sidetext", [])
            if unit_values[:2] == ["L", "("]:
                unit_values = unit_values[2:-1]
            try:
                unit = literal(unit_values, symbols) if unit_values else None
            except ValueError as exc:
                raise SchemaBuildError("unresolved_unit", key, expression(unit_values), raw["line"]) from exc
            kinds[kind][key] = {"type": raw["type"], "default": default, "nullable": raw["nullable"], **limits, "enums": sorted(set(enums)), "unit": unit,
                                "enum_open": "f_enum_open" in fields.get("gui_type", []),
                                "dimension": dimension, "role": rules.get("roles", {}).get(key, "parameter"), "complete": True,
                                "source": {"file": "src/libslic3r/PrintConfig.cpp", "line": raw["line"], "expression": expression(fields.get("default", []))}}
            if key in rules.get("dimension_context", {}):
                kinds[kind][key]["dimension_context"] = rules["dimension_context"][key]
            if "copied_from" in raw:
                kinds[kind][key]["source"]["copied_from"] = raw["copied_from"]
            if "loop" in raw:
                kinds[kind][key]["source"]["loop"] = raw["loop"]
    return {"options": kinds, "complete": True, "coverage": {"expected": {kind: len(keys) for kind, keys in expected.items()}, "read": {kind: len(keys) for kind, keys in kinds.items()}, "unique_fields": len(all_keys), "unclassified": [], "missing_defaults": []}}


def build_catalog(slicer: str, version: str, source_dir: Path) -> dict:
    commit, _, _ = RELEASES[(slicer, version)]
    rules = json.loads((ROOT / "tools/profile_schema_rules.json").read_text(encoding="utf-8"))[slicer]
    if rules["commit"] != commit:
        raise SchemaBuildError("source_commit_mismatch", expression=rules["commit"])
    sources = {}
    for filename, expected_hash in rules["source_sha256"].items():
        path = source_dir / filename
        if not path.is_file():
            raise SchemaBuildError("missing_source", expression=filename)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise SchemaBuildError("source_hash_mismatch", expression=filename)
        sources[filename] = data.decode("utf-8")
    rules = copy.deepcopy(rules)
    rules["symbols"] = {}
    for text in sources.values():
        rules["symbols"].update(source_symbols(text))
    if "src/libslic3r/MaterialType.cpp" in sources:
        vals = [v for v, _ in tokens(sources["src/libslic3r/MaterialType.cpp"])]
        start = vals.index("material_types") + 2
        rules["symbols"]["filament.name"] = [row[0] for row in literal(vals[start:balanced(vals, start) + 1], {})]
    config = (source_dir / "src/libslic3r/PrintConfig.cpp").read_text(encoding="utf-8")
    preset = (source_dir / "src/libslic3r/Preset.cpp").read_text(encoding="utf-8")
    catalog = extract_catalog(config, preset, rules)
    for rule in rules["field_rules"]:
        entries = [fields[rule["field"]] for fields in catalog["options"].values() if rule["field"] in fields]
        if not entries or any(entry["source"]["expression"] != rule["expected_expression"] for entry in entries):
            raise SchemaBuildError("rule_expression_mismatch", rule["field"], rule["expected_expression"], rule["line"])
    catalog["normalization_rules"] = rules["normalization_rules"]
    catalog["protected_fields"] = rules["protected_fields"]
    catalog["coverage"].update(rule_count=len(rules["field_rules"]), rules_verified=len(rules["field_rules"]),
                               source_files_verified=len(sources), normalization_source_verified=True)
    catalog.update(id=f"{slicer}@{version}", slicer=slicer, version=version, source_commit=commit, catalog_version=1)
    catalog["source_sha256"] = rules["source_sha256"]
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for (slicer, version), (_, source, filename) in RELEASES.items():
        catalog = build_catalog(slicer, version, ROOT / "slicer-src" / source)
        (args.output_dir / filename).write_text(json.dumps(catalog, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        print(slicer, json.dumps(catalog["coverage"], sort_keys=True))


if __name__ == "__main__":
    main()
