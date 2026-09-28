"""Pure, catalog-bound effective values; never writes Slicer data."""

from copy import deepcopy
import re

from .profile_schema import validate_value


def _issue(code, key=None, **params):
    return {"severity": "error", "code": code, "key": key, "indices": None, "params": params}


def _resize(value, size, default):
    if len(value) >= size:
        return value[:size]
    seed = value[0] if value else (default[0] if isinstance(default, list) and default else None)
    if seed is None:
        raise ValueError("default_missing")
    return value + [seed] * (size - len(value))


def _normalize(catalog, kind, values, context, issues):
    options = catalog.get("options", {}).get(kind, {})
    snorca = catalog.get("slicer") == "Snapmaker_Orca"
    active_extruders = values.get("single_extruder_multi_material") == "0"
    count_key = "nozzle_diameter" if active_extruders else "filament_diameter"
    count = len(values[count_key]) if isinstance(values.get(count_key), list) else 1
    rules = catalog.get("normalization_rules", {})
    if not snorca and active_extruders and "nozzle_diameter" in values:
        if "extruder_variant_list" in options:
            variant_list = values.get("extruder_variant_list", ["Direct Drive Standard"])
            if isinstance(variant_list, list):
                try:
                    variant_list = _resize(variant_list, count, options["extruder_variant_list"].get("default"))
                    values["extruder_variant_list"] = variant_list
                    variant_ids, variant_names = [], []
                    for index, declaration_value in enumerate(variant_list):
                        parts = re.split(",+", declaration_value)
                        variant_names.extend(parts)
                        variant_ids.extend([str(index + 1)] * len(parts))
                    if "printer_extruder_variant" in options:
                        values["printer_extruder_variant"] = variant_names
                    if "printer_extruder_id" in options:
                        values["printer_extruder_id"] = variant_ids
                except ValueError as exc:
                    issues.append(_issue(str(exc), "extruder_variant_list"))
    declaration = ("filament_flow_support" if kind == "filament" else "process_flow_support")
    variants = values.get(declaration, context.get("flow_variants", []))
    flow_count = len(variants) if isinstance(variants, list) and variants else 1
    if kind == "filament" and count != 1:
        steps = values.get("filament_flow_step_size")
        flow_count = count
        if isinstance(steps, list) and len(steps) == count:
            try:
                flow_count = sum(max(1, int(step)) for step in steps)
            except (ValueError, TypeError):
                issues.append(_issue("invalid_dimension", "filament_flow_step_size"))
    context.update(extruder_count=len(values["nozzle_diameter"]) if isinstance(values.get("nozzle_diameter"), list) else context.get("extruder_count", 1),
                   filament_count=len(values["filament_diameter"]) if isinstance(values.get("filament_diameter"), list) else context.get("filament_count", 1),
                   flow_variants=deepcopy(variants))
    for key, option in options.items():
        value = values.get(key)
        if not isinstance(value, list) or key in {"compatible_printers", "compatible_prints", "default_filament_profile", "filament_flow_support", "process_flow_support"}:
            continue
        dimension = option.get("dimension")
        target = None
        grow_only = False
        extruder_keys = rules.get("extruder_option_keys")
        filament_keys = rules.get("filament_option_keys")
        is_extruder = key in extruder_keys if extruder_keys is not None else dimension == "extruder"
        is_filament = key in filament_keys if filament_keys is not None else dimension == "filament"
        if active_extruders and count_key in values and is_extruder:
            target = count
            if not snorca and dimension == "flow":
                domain = option.get("dimension_context", {}).get("kind", kind)
                variant_key = {"machine": "printer_extruder_variant", "process": "print_extruder_variant", "filament": "filament_extruder_variant"}.get(domain)
                declaration_values = values.get(variant_key, ["standard"])
                multiplier = option.get("dimension_context", {}).get("multiplier", 1)
                if isinstance(declaration_values, list) and multiplier in (1, 2):
                    target = len(declaration_values) * multiplier
                else:
                    target = None
                    issues.append(_issue("dimension_context_missing", key))
        elif not active_extruders and count_key in values and is_filament and not (snorca and (dimension == "flow" or key == "filament_flow_step_size")):
            target = count
        if target is not None and (not grow_only or len(value) < target):
            try:
                values[key] = _resize(value, target, option.get("default"))
            except ValueError as exc:
                issues.append(_issue(str(exc), key))
        # Preset::normalize performs a second pass after DynamicPrintConfig resizing.
        target = None
        if kind == "filament" and "filament_diameter" in values and key in rules.get("filament_options", options):
            if snorca:
                target = flow_count if dimension == "flow" else count
            elif dimension != "flow" and key not in rules.get("flow", {}).get("filament", []):
                target = count
        elif kind == "process" and snorca and dimension == "flow":
            target = flow_count
        if target is not None and (not snorca or len(values[key]) < target):
            try:
                values[key] = _resize(values[key], target, option.get("default"))
            except ValueError as exc:
                issues.append(_issue(str(exc), key))


def resolve_values(catalog: dict, kind: str, layers: list[dict], context: dict) -> dict:
    """Resolve root-to-child layers without mutating inputs or hiding unknown fields."""
    context = deepcopy(context)
    values, origins, unknown, issues = {}, {}, {}, []
    if not context.get("chain_complete", True):
        issues.append(_issue("parent_missing"))
    if not catalog or not catalog.get("complete") or kind not in catalog.get("options", {}):
        issues.append(_issue("schema_incomplete"))
    options = (catalog or {}).get("options", {}).get(kind, {})
    for key, option in options.items():
        if option.get("role") == "secret":
            continue
        if not option.get("complete", False):
            issues.append(_issue("option_incomplete", key))
        if option.get("default") is None:
            if option.get("role", "parameter") == "parameter":
                issues.append(_issue("default_missing", key))
            continue
        values[key] = deepcopy(option["default"])
        origins[key] = {"kind": "default", "schema_id": catalog.get("id")}
    seen = set()
    for layer in layers:
        identity = layer.get("id")
        if identity is not None and identity in seen:
            issues.append(_issue("inheritance_cycle"))
        seen.add(identity)
        for key, value in layer.get("values", {}).items():
            option = options.get(key)
            if option is None:
                unknown[key] = deepcopy(value)
            elif option.get("role") != "secret":
                values[key] = deepcopy(value)
                origins[key] = {"kind": "profile", "profile_id": identity, "schema_id": catalog.get("id")}
    for key, value in values.items():
        for issue in validate_value(options[key], value):
            issues.append({**_issue(issue["code"], key), **issue})
    if not any(i["code"] in {"invalid_type", "invalid_number"} for i in issues):
        _normalize(catalog or {}, kind, values, context, issues)
    return {"values": values, "origins": origins, "unknown": unknown, "context": context,
            "complete": not any(i["severity"] == "error" for i in issues), "issues": issues}
