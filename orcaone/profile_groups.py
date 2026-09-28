"""Explicit machine cards kept locally in OrcaOne's existing settings file.

Publish calls save_group only after verification; previews use validate_group without writing.
Only display metadata belongs here, never profile documents or connection settings.
"""

import re
from collections import Counter

from . import settings


class ProfileGroupError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and not any(ord(c) < 32 for c in value)


def _group(group_id, names, display_name, labels=None, user_folder=None):
    if (not isinstance(group_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", group_id)
            or not isinstance(names, list) or len(names) < 1 or not all(_text(name) for name in names)
            or len(set(names)) != len(names) or not _text(display_name)):
        raise ProfileGroupError("invalid_group")
    if user_folder is not None and not _text(user_folder):
        raise ProfileGroupError("invalid_group")
    if labels is not None and (not isinstance(labels, dict)
                               or any(name not in names or not _text(label) for name, label in labels.items())):
        raise ProfileGroupError("invalid_group")
    return {"id": group_id, "names": list(names), "display_name": display_name,
            **({"labels": dict(labels)} if labels else {}),
            **({"user_folder": user_folder} if user_folder is not None else {})}


def _groups(data, instance_id, user_folder=None):
    section = data.get("machine_groups")
    stored = section.get(instance_id) if isinstance(section, dict) else None
    if not isinstance(stored, dict):
        return []
    groups = []
    for group_id, raw in sorted(stored.items()):
        if not isinstance(raw, dict) or raw.get("user_folder") != user_folder:
            continue
        try:
            groups.append(_group(group_id, raw.get("names"), raw.get("display_name"), raw.get("labels"), raw.get("user_folder")))
        except ProfileGroupError:
            continue
    return groups


def list_groups(instance_id, user_folder=None):
    """Read known metadata only; malformed records cannot break the live overview."""
    return _groups(settings.load(), instance_id, user_folder)


def _validate(data, instance_id, group):
    if not _text(instance_id):
        raise ProfileGroupError("invalid_group")
    section = data.get("machine_groups")
    stored = section.get(instance_id) if isinstance(section, dict) else None
    previous = stored.get(group["id"]) if isinstance(stored, dict) else None
    if isinstance(previous, dict) and previous.get("user_folder") != group.get("user_folder"):
        raise ProfileGroupError("group_member_conflict")
    names = set(group["names"])
    if any(names.intersection(other["names"]) for other in _groups(data, instance_id, group.get("user_folder")) if other["id"] != group["id"]):
        raise ProfileGroupError("group_member_conflict")
    return group


def _release_members(data, instance_id, user_folder, moved_names, target_id):
    if not isinstance(moved_names, list) or not all(_text(name) for name in moved_names):
        raise ProfileGroupError("invalid_group")
    groups = data.get("machine_groups", {}).get(instance_id, {})
    for group in list(_groups(data, instance_id, user_folder)):
        if group["id"] == target_id:
            continue
        remaining = [name for name in group["names"] if name not in moved_names]
        if remaining == group["names"]:
            continue
        if not remaining:
            groups.pop(group["id"], None)
        else:
            groups[group["id"]]["names"] = remaining
            if "labels" in groups[group["id"]]:
                groups[group["id"]]["labels"] = {name: label for name, label in group.get("labels", {}).items() if name in remaining}


def validate_group(instance_id, group_id, names, display_name, labels=None, user_folder=None, moved_names=None):
    """The publish preview's read-only metadata and existing-membership check."""
    data = settings.load()
    if moved_names is not None:
        _release_members(data, instance_id, user_folder, moved_names, group_id)
    return _validate(data, instance_id, _group(group_id, names, display_name, labels, user_folder))


def save_group(instance_id, group_id, names, display_name, labels=None, user_folder=None, moved_names=None):
    """Register a verified publication; replaying the same durable receipt is idempotent."""
    group = _group(group_id, names, display_name, labels, user_folder)

    def edit(data):
        if moved_names is not None:
            _release_members(data, instance_id, user_folder, moved_names, group_id)
        _validate(data, instance_id, group)
        if not isinstance(data.get("machine_groups"), dict):
            data["machine_groups"] = {}
        groups = data["machine_groups"]
        if not isinstance(groups.get(instance_id), dict):
            groups[instance_id] = {}
        groups[instance_id][group_id] = {key: value for key, value in group.items() if key != "id"}

    settings.change(edit)
    return group


def resolve_groups(instance_id, available_names, ambiguous_names=(), user_folder=None):
    """Keep only unique, available own members; ambiguous overlapping groups claim neither."""
    available = Counter(available_names)
    groups = list_groups(instance_id, user_folder)
    membership = Counter(name for group in groups for name in group["names"])
    ambiguous = set(ambiguous_names)
    result = []
    for group in groups:
        names = [name for name in group["names"]
                 if available[name] == 1 and membership[name] == 1 and name not in ambiguous]
        if names:
            result.append({**group, "names": names,
                           **({"labels": {name: label for name, label in group["labels"].items() if name in names}}
                              if "labels" in group else {})})
    return result


def rename_members(instance_id, renames, user_folder):
    """Replay-safe registry repair after verified physical profile renames."""
    def edit(data):
        for group in _groups(data, instance_id, user_folder):
            stored = data["machine_groups"][instance_id][group["id"]]
            stored["names"] = [renames.get(name, name) for name in group["names"]]
            if "labels" in stored:
                stored["labels"] = {renames.get(name, name): label for name, label in stored["labels"].items()}
    settings.change(edit)
