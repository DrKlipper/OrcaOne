"""Explicit printer variants and evidence-based nozzle suggestions, without writes."""

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from .profile_schema import validate_value


def group_profiles(documents: list[dict]) -> list[dict]:
    groups = {}
    for document in documents:
        if document.get("kind") != "machine":
            continue
        model = document.get("effective", {}).get("printer_model", "")
        explicit = document.get("model_group")
        package = document.get("package")
        # A generic name is not proof that two profiles describe one printer.
        key = ("explicit", explicit) if explicit else (("vendor", package, model)
               if package and model and model != "Custom" else ("profile", document["id"]))
        group = groups.setdefault(key, {"key": list(key), "model": model, "profiles": []})
        group["profiles"].append(deepcopy(document))
    return list(groups.values())


def variant_changes(source: dict, target_model: str, configuration: dict, choices: dict) -> dict:
    issues = []
    if source.get("kind") != "machine" or not source.get("complete"):
        issues.append({"severity": "error", "code": "profile_incomplete"})
    if not isinstance(target_model, str) or not target_model.strip():
        issues.append({"severity": "error", "code": "invalid_model"})
    diameters = configuration.get("nozzle_diameter", source.get("effective", {}).get("nozzle_diameter"))
    valid = isinstance(diameters, list) and bool(diameters) and all(isinstance(x, str) for x in diameters)
    if valid:
        option = {"type": "coFloat", "complete": True, "role": "parameter"}
        valid = all(not validate_value(option, x) and Decimal(x) > 0 for x in diameters)
    if not valid:
        issues.append({"severity": "error", "code": "invalid_nozzle", "key": "nozzle_diameter"})
    if not isinstance(choices, dict) or any(value not in ("share", "copy", "leave") for value in choices.values()):
        issues.append({"severity": "error", "code": "invalid_choices"})
    if issues:
        return {"document": None, "choices": {}, "issues": issues}
    document = deepcopy(source)
    if configuration.get("copy"):
        document["id"] = uuid4().hex
        document["copied_from"] = source["id"]
    if "name" in configuration:
        if not isinstance(configuration["name"], str) or not configuration["name"].strip():
            return {"document": None, "choices": {}, "issues": [{"severity": "error", "code": "invalid_name"}]}
        document["name"] = configuration["name"]
    # Materialize effective values for the user's independent merged variant.
    document["own"] = deepcopy(source["effective"])
    document["own"].update(printer_model=target_model, nozzle_diameter=deepcopy(diameters))
    if "printer_variant" in configuration:
        if not isinstance(configuration["printer_variant"], str):
            return {"document": None, "choices": {}, "issues": [{"severity": "error", "code": "invalid_variant"}]}
        document["own"]["printer_variant"] = configuration["printer_variant"]
    document["effective"] = deepcopy(document["own"])
    document["inherits"] = ""
    document["inherited"] = {}
    document["model_group"] = configuration.get("model_group") or target_model
    document["context"] = {**document.get("context", {}), "extruder_count": len(diameters)}
    return {"document": document, "choices": deepcopy(choices), "issues": []}


def suggest_nozzle_changes(document: dict, target: dict, catalog: dict) -> list[dict]:
    """Only propose known target process values, never invent a diameter ratio."""
    if document.get("kind") != "process" or target.get("kind") != "process":
        return []
    suggestions = []
    before, after = document.get("effective", {}), target.get("effective", {})
    for key, option in catalog.get("options", {}).get("process", {}).items():
        if key not in ("layer_height", "initial_layer_print_height") and not key.endswith("line_width"):
            continue
        if key not in after or before.get(key) == after[key] or not option.get("complete"):
            continue
        if validate_value(option, after[key]):
            continue
        suggestions.append({"key": key, "before": deepcopy(before.get(key)), "after": deepcopy(after[key]),
                            "reason": "target_profile_value", "source": target.get("name", "")})
    return suggestions
