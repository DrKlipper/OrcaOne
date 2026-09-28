"""Pure profile comparisons; absent values are distinct from empty values."""

from copy import deepcopy


def _entry(values: dict, key: str) -> dict:
    return {"present": True, "value": deepcopy(values[key])} if key in values else {"present": False}


def diff_values(before: dict, after: dict) -> list[dict]:
    """Return stable field differences without coercing strings or vector dimensions."""
    return [{"key": key, "before": _entry(before, key), "after": _entry(after, key)}
            for key in sorted(before.keys() | after.keys())
            if _entry(before, key) != _entry(after, key)]


def merge_values(base: dict, target: dict, source: dict, selected_keys: list[str]) -> dict:
    """Propose a three-way merge of selected fields; conflicts retain the target."""
    values, conflicts = deepcopy(target), []
    for key in dict.fromkeys(selected_keys):
        b, t, s = (_entry(part, key) for part in (base, target, source))
        if t == s or s == b:
            chosen = t
        elif t == b:
            chosen = s
        else:
            conflicts.append({"key": key, "base": b, "target": t, "source": s})
            continue
        if chosen["present"]:
            values[key] = deepcopy(chosen["value"])
        else:
            values.pop(key, None)
    return {"values": values, "conflicts": conflicts}


def merge_parents(target_id: str, source_id: str, fully_integrated: bool) -> list[str]:
    """Partial adoption records provenance separately, never a false merge ancestor."""
    return list(dict.fromkeys([target_id, source_id] if fully_integrated else [target_id]))
