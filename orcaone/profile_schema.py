"""Version-pinned profile catalogs and structural value validation."""

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path


SCHEMA_DIR = Path(__file__).with_name("profile_schemas")

_SCALAR_TYPES = {
    "coBool", "coInt", "coFloat", "coPercent", "coFloatOrPercent",
    "coString", "coEnum", "coPoint",
}
_VECTOR_TYPES = {
    "coBools": "coBool", "coInts": "coInt", "coFloats": "coFloat",
    "coPercents": "coPercent", "coFloatsOrPercents": "coFloatOrPercent",
    "coStrings": "coString", "coEnums": "coEnum", "coPoints": "coPoint",
    "coPointsGroups": "coPointsGroup",
}
_INTEGER = re.compile(r"[+-]?[0-9]+", re.ASCII)
_FLOAT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)


def load_catalog(slicer: str, version: str) -> dict | None:
    """Load only a catalog explicitly pinned by the manifest."""
    if not isinstance(slicer, str) or not isinstance(version, str):
        return None
    try:
        manifest = json.loads((SCHEMA_DIR / "manifest.json").read_text(encoding="utf-8"))
        entries = manifest["catalogs"]
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("slicer") != slicer or entry.get("version") != version:
                continue
            name = entry.get("file")
            if not isinstance(name, str) or not name.endswith(".json") or Path(name).name != name:
                return None
            base = SCHEMA_DIR.resolve()
            path = (base / name).resolve()
            if path.parent != base:
                return None
            catalog = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(catalog, dict)
                    or catalog.get("slicer") != slicer
                    or catalog.get("version") != version
                    or catalog.get("id") != f"{slicer}@{version}"
                    or not isinstance(catalog.get("options"), dict)):
                return None
            return catalog
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return None


def _number(text: str, *, percent: bool = False, integer: bool = False) -> Decimal | None:
    if percent:
        if not text.endswith("%"):
            return None
        text = text[:-1]
    elif "%" in text:
        return None
    pattern = _INTEGER if integer else _FLOAT
    if not pattern.fullmatch(text):
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite() or (integer and number != number.to_integral_value()):
        return None
    return number


def _point(value: str, *, scalar: bool = False) -> bool:
    separator = "," if scalar and "," in value else "x"
    parts = value.split(separator)
    return len(parts) == 2 and all(_number(part) is not None for part in parts)


def _one(option: dict, type_: str, value: str, *, scalar_point: bool = False) -> str | None:
    if value == "nil":
        return None if option.get("nullable") else "nil_not_allowed"
    if type_ == "coBool":
        return None if value in ("0", "1") else "invalid_bool"
    if type_ == "coString":
        return None
    if type_ == "coEnum":
        return None if value in option.get("enums", []) else "invalid_enum"
    if type_ == "coPoint":
        return None if _point(value, scalar=scalar_point) else "invalid_point"
    if type_ == "coPointsGroup":
        return None if value and all(_point(point) for point in value.split(",")) else "invalid_point"
    percent = type_ == "coPercent" or (type_ == "coFloatOrPercent" and value.endswith("%"))
    number = _number(value, percent=percent, integer=type_ == "coInt")
    if number is None:
        return "invalid_number"
    try:
        lower = option.get("min")
        upper = option.get("max")
        if (lower is not None and number < Decimal(str(lower))) or (upper is not None and number > Decimal(str(upper))):
            return "out_of_range"
    except InvalidOperation:
        return "invalid_number"
    return None


def validate_value(option: dict, value: str | list[str] | list[list[str]]) -> list[dict]:
    """Return structural issues for the exact Slicer JSON value representation."""
    type_ = option.get("type") if isinstance(option, dict) else None
    if type_ not in _SCALAR_TYPES and type_ not in _VECTOR_TYPES:
        return [{"code": "unsupported_type"}]
    if type_ == "coPointsGroups" and isinstance(value, list) and any(isinstance(item, list) for item in value):
        # Config.cpp parse_str_arr requires homogeneous sibling types. Preserve
        # both accepted JSON depths; '#' separates groups at either depth.
        if any(not isinstance(group, list) or any(not isinstance(item, str) for item in group) for group in value):
            return [{"code": "invalid_type"}]
        issues = []
        for group_index, group in enumerate(value):
            for item_index, item in enumerate(group):
                error = _one(option, "coPointsGroup", item)
                if error:
                    issues.append({"code": error, "indices": [group_index, item_index]})
        return issues
    vector = type_ in _VECTOR_TYPES
    if vector:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return [{"code": "invalid_type"}]
        element_type = _VECTOR_TYPES[type_]
        values = value
    else:
        if not isinstance(value, str):
            return [{"code": "invalid_type"}]
        element_type = type_
        values = [value]
    issues = []
    for index, item in enumerate(values):
        error = _one(option, element_type, item, scalar_point=type_ == "coPoint")
        if error:
            issue = {"code": error}
            if vector:
                issue["indices"] = [index]
            issues.append(issue)
    return issues
