"""Version-aware preview of a detached profile copy; no Slicer or history writes."""

from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from .profile_schema import load_catalog, validate_value
from .scanner import META_KEYS


_VECTORS = {"coBools", "coInts", "coFloats", "coPercents", "coFloatsOrPercents",
            "coStrings", "coEnums", "coPoints", "coPointsGroups"}
_SECRETS = {"api_key", "user", "password", "ca", "cert", "key", "clientId", "access_code",
            "token", "print_host", "printhost_apikey", "printhost_password", "printhost_user"}


def conversion_report(source: dict, target_catalog: dict) -> dict:
    """Propose a new root profile, retaining all target-representable effective values.

    Losses are pending per-field decisions. A report never authorizes publication;
    confirmation only makes this local copy eligible for normal editor validation.
    """
    kind = source.get("kind")
    options = target_catalog.get("options", {}).get(kind, {})
    issues, losses, values = [], [], {}
    source_options = {}
    source_catalog = None
    source_schema_id = source.get("schema_id")
    if isinstance(source_schema_id, str) and "@" in source_schema_id:
        slicer, version = source_schema_id.split("@", 1)
        source_catalog = load_catalog(slicer, version)
        source_options = (source_catalog or {}).get("options", {}).get(kind, {})

    def issue(code, key=None, indices=None):
        issues.append({"severity": "error", "code": code, "profile_id": source.get("id"),
                       "key": key, "indices": indices, "params": {}})

    def loss(code, key, before, after, *, redacted=False):
        item = {"code": code, "key": key, "before": deepcopy(before), "after": deepcopy(after)}
        if redacted:
            item["redacted"] = True
        payload = json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        item["id"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
        losses.append(item)

    if not target_catalog.get("complete") or not target_catalog.get("id"):
        issue("catalog_incomplete")
    if source.get("complete") is False or not source.get("context", {}).get("chain_complete", True):
        issue("document_incomplete")
    if not source_catalog or not source_catalog.get("complete"):
        issue("source_catalog_unavailable")
    if kind not in {"process", "filament", "machine"}:
        issue("invalid_kind")
    effective = source.get("effective", {})
    unknown = source.get("unknown", {})
    if not isinstance(effective, dict) or not isinstance(unknown, dict):
        issue("invalid_document")
        effective, unknown = {}, {}
    for key, original in sorted((unknown | effective).items()):
        option = options.get(key)
        source_option = source_options.get(key, {})
        if key in _SECRETS or (option or {}).get("role") == "secret" or source_option.get("role") == "secret":
            loss("secret_omitted", key, None, None, redacted=True)
            continue
        if key == "inherits":
            continue
        if key in META_KEYS or (option or {}).get("role") == "metadata":
            loss("metadata_omitted", key, None, None, redacted=True)
            continue
        if option is None:
            loss("unknown_field", key, original, None)
            continue
        if not option.get("complete"):
            issue("option_incomplete", key)
            continue
        point_groups = (option.get("type") == "coPointsGroups" and isinstance(original, list)
                        and all(isinstance(group, list) and all(isinstance(point, str) for point in group)
                                for group in original))
        if not isinstance(original, str) and not point_groups and not (isinstance(original, list) and all(isinstance(x, str) for x in original)):
            issue("invalid_type", key)
            continue
        vector = option.get("type") in _VECTORS
        value = deepcopy(original)
        if vector and isinstance(value, str):
            value = [value]
        elif not vector and isinstance(value, list):
            if not value:
                value = deepcopy(option.get("default"))
                loss("empty_vector_replaced", key, original, value)
            else:
                value = value[0]
                if len(original) > 1:
                    loss("vector_truncated", key, original, value)
        if (isinstance(value, list) and isinstance(original, list) and source_option
                and (source_option.get("dimension"), source_option.get("dimension_context"))
                != (option.get("dimension"), option.get("dimension_context"))):
            loss("dimension_changed", key, original, value)
        validation = validate_value(option, value)
        replaceable = {"invalid_enum", "nil_not_allowed"}
        if source_option and not validate_value(source_option, original):
            replaceable.add("out_of_range")
        if validation and all(x["code"] in replaceable for x in validation):
            default = deepcopy(option.get("default"))
            if default is not None and not validate_value(option, default):
                replacement = deepcopy(value)
                if isinstance(replacement, list) and isinstance(default, list) and default:
                    for problem in validation:
                        index = problem.get("indices", [None])[0]
                        if index is not None:
                            replacement[index] = default[index] if index < len(default) else default[0]
                else:
                    replacement = default
                codes = {problem["code"] for problem in validation}
                code = "enum_changed" if "invalid_enum" in codes else "range_replaced" if "out_of_range" in codes else "nil_replaced"
                loss(code, key, value, replacement)
                value = replacement
                validation = validate_value(option, value)
        for problem in validation:
            issue(problem["code"], key, problem.get("indices"))
        values[key] = value
    document = {"id": uuid4().hex, "kind": kind, "name": source.get("name", ""),
                "schema_id": target_catalog.get("id"), "inherits": "", "package": "", "origin_kind": "own",
                "own": deepcopy(values), "effective": deepcopy(values), "inherited": {}, "origins": {},
                "context": {"chain_complete": True}, "references": [], "unknown": {}, "complete": False,
                "issues": deepcopy(issues), "provenance": {"operation": "cross_slicer_copy",
                    "source_profile_id": source.get("id"), "source_schema_id": source_schema_id}}
    document["references"] = [{"key": key, "value": deepcopy(value)} for key, value in values.items()
                              if options.get(key, {}).get("role") == "reference"]
    report = {"document": document, "losses": losses, "issues": issues, "confirmed_loss_ids": [], "ready": False}
    return confirm_conversion(report, [])


def confirm_conversion(report: dict, confirmed_loss_ids: list[str]) -> dict:
    """Confirm server-retained report loss IDs; this performs no publication."""
    result = deepcopy(report)
    required = {loss["id"] for loss in result["losses"]}
    confirmed = set(confirmed_loss_ids) & required
    result["confirmed_loss_ids"] = sorted(confirmed)
    result["ready"] = not result["issues"] and confirmed == required
    result["document"]["complete"] = result["ready"]
    return result
