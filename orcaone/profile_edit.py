"""Editable profile documents and atomic, explicitly scoped patches."""

from copy import deepcopy

from .profile_normalize import resolve_values, _normalize
from .profile_schema import validate_value
from .scanner import META_KEYS
from .snapshot import SECRET


_SECRETS = {"api_key", "user", "password", "ca", "cert", "key", "clientId", "access_code", "print_host", "printhost_apikey", "printhost_password", "printhost_user"}
_REFERENCES = {"compatible_printers", "compatible_prints", "default_print_profile", "default_filament_profile", "inherits"}


def _safe(values, options):
    return {key: deepcopy(value) for key, value in values.items()
            if key not in _SECRETS and not SECRET.search(key) and options.get(key, {}).get("role") != "secret"}


def make_document(profile_id, profile, resolver, catalog):
    """Snapshot resolved inheritance; secret values never enter the API document."""
    chain, complete = resolver.chain(profile)
    catalog = catalog or {}
    options = catalog.get("options", {}).get(profile.kind, {})
    layers = [{"id": f"{p.package}:{p.kind}:{p.name}", "values": _safe(p.values, options)} for p in reversed(chain)]
    context = {"chain_complete": complete}
    inherited = resolve_values(catalog, profile.kind, layers, context)
    own = _safe(profile.values, options)
    result = resolve_values(catalog, profile.kind, layers + [{"id": profile_id, "values": own}], context)
    references = [{"key": key, "value": deepcopy(value)} for key, value in result["values"].items()
                  if key in _REFERENCES or options.get(key, {}).get("role") == "reference"]
    if profile.inherits:
        references.append({"key": "inherits", "value": profile.inherits})
    return {"id": profile_id, "kind": profile.kind, "name": profile.name, "schema_id": catalog.get("id"),
            "package": profile.package, "origin_kind": profile.origin_kind, "inherits": profile.inherits,
            "own": {k: v for k, v in own.items() if k in options}, "inherited": inherited["values"],
            "inherited_origins": inherited["origins"], "effective": result["values"], "origins": result["origins"],
            "context": result["context"], "references": references, "unknown": result["unknown"],
            "own_unknown": {k: v for k, v in own.items() if k not in options},
            "inherited_unknown": inherited["unknown"],
            "complete": result["complete"], "issues": result["issues"]}


def apply_patches(documents: dict, patches: list[dict], catalogs: dict) -> dict:
    """Validate the entire batch on copies; any error returns the original state."""
    updated, issues = deepcopy(documents), []
    if not isinstance(patches, list):
        return {"documents": updated, "issues": [{"severity": "error", "code": "invalid_patch", "profile_id": None,
                                                   "key": None, "indices": None, "params": {}}]}
    for patch in patches:
        if (not isinstance(patch, dict) or not isinstance(patch.get("profile_id"), str)
                or not isinstance(patch.get("key"), str) or not isinstance(patch.get("op"), str)):
            issues.append({"severity": "error", "code": "invalid_patch", "profile_id": None, "key": None, "indices": None, "params": {}})
            continue
        profile_id, key = patch.get("profile_id"), patch.get("key")
        document = updated.get(profile_id)
        def reject(code, indices=None):
            issues.append({"severity": "error", "code": code, "profile_id": profile_id, "key": key, "indices": indices, "params": {}})
        if document is None:
            reject("profile_missing")
            continue
        catalog = catalogs.get(document.get("schema_id"))
        if (not catalog or not catalog.get("complete") or catalog.get("id") != document.get("schema_id")
                or not document.get("complete") or not document.get("context", {}).get("chain_complete", True)):
            reject("document_incomplete")
            continue
        option = catalog.get("options", {}).get(document["kind"], {}).get(key)
        if not option:
            reject("unknown_field")
            continue
        if not option.get("complete"):
            reject("option_incomplete")
            continue
        op, indices = patch.get("op"), patch.get("indices")
        role = option.get("role", "parameter")
        if key in META_KEYS or key in _SECRETS or role in {"metadata", "secret"} or (role == "reference" and op not in {"bind_add", "bind_remove"}):
            reject("protected_field")
            continue
        current = deepcopy(document.get("effective", {}).get(key))
        if indices is not None:
            if (not isinstance(indices, list) or not indices or any(type(i) is not int for i in indices)
                    or len(set(indices)) != len(indices) or not isinstance(current, list)
                    or option.get("dimension") == "scalar" or any(i < 0 or i >= len(current) for i in indices)):
                reject("invalid_indices", indices)
                continue
        if op == "set":
            value = deepcopy(patch.get("value"))
            if indices is not None:
                if not isinstance(value, list) or len(value) != len(indices):
                    reject("invalid_indices", indices)
                    continue
                for index, item in zip(indices, value):
                    current[index] = item
                value = current
        elif op == "reset":
            if key not in document.get("inherited", {}):
                reject("inherited_value_missing")
                continue
            value = deepcopy(document["inherited"][key])
            if indices is not None:
                if not isinstance(value, list) or any(i >= len(value) for i in indices):
                    reject("invalid_indices", indices)
                    continue
                for index in indices:
                    current[index] = value[index]
                value = current
        elif op in {"bind_add", "bind_remove"}:
            members = patch.get("value")
            if role != "reference" or indices is not None or not isinstance(current, list) or not isinstance(members, list) or any(not isinstance(x, str) for x in members):
                reject("invalid_binding")
                continue
            value = current + [x for x in members if x not in current] if op == "bind_add" else [x for x in current if x not in members]
        else:
            reject("invalid_operation")
            continue
        errors = validate_value(option, value)
        if errors:
            for error in errors:
                reject(error["code"], error.get("indices"))
            continue
        if op == "reset" and indices is None:
            document.setdefault("own", {}).pop(key, None)
            document.setdefault("origins", {})[key] = deepcopy(document.get("inherited_origins", {}).get(key, {"kind": "inherited", "schema_id": document["schema_id"]}))
        else:
            document.setdefault("own", {})[key] = value
            document.setdefault("origins", {})[key] = {"kind": "profile", "profile_id": profile_id, "schema_id": document["schema_id"]}
        document.setdefault("effective", {})[key] = deepcopy(value)
        if role == "reference":
            document["references"] = [r for r in document.get("references", []) if r.get("key") != key] + [{"key": key, "value": deepcopy(value)}]
    if not issues:
        for profile_id in {patch.get("profile_id") for patch in patches}:
            document = updated[profile_id]
            normalized = deepcopy(document["effective"])
            normalization_issues = []
            context = deepcopy(document.get("context", {}))
            _normalize(catalogs[document["schema_id"]], document["kind"], normalized, context, normalization_issues)
            for issue in normalization_issues:
                issues.append({**issue, "profile_id": profile_id})
            for key in normalized:
                if normalized[key] != document["effective"].get(key):
                    issues.append({"severity": "error", "code": "dimension_scope_expansion", "profile_id": profile_id,
                                   "key": key, "indices": None, "params": {}})
            document["context"] = context
    return {"documents": deepcopy(documents) if issues else updated, "issues": issues}


def reference_impacts(documents: dict, replacements: dict) -> list[dict]:
    """Report remaining references; never rewrite or add profiles to a selection."""
    impacts = []
    for profile_id, document in documents.items():
        fields = dict(document.get("effective", {}))
        fields.update({r["key"]: r.get("value") for r in document.get("references", [])})
        for key, value in fields.items():
            if key.endswith("_condition") and value:
                impacts.append({"profile_id": profile_id, "key": key, "code": "condition_unknown", "severity": "error", "params": {}})
            elif key in _REFERENCES:
                names = value if isinstance(value, list) else [value]
                for name in names:
                    if name in replacements:
                        impacts.append({"profile_id": profile_id, "key": key, "code": "reference_update_required", "severity": "error", "params": {"name": name, "replacement": replacements[name]}})
    return impacts
