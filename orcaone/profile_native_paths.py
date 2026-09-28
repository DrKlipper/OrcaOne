"""The only system paths OrcaOne owns: explicitly marked native model packages."""

import json
import re
from pathlib import PurePosixPath

_VENDOR = r'OrcaOne_[0-9a-f]{32}'
_PATH = re.compile(rf'system/({_VENDOR})(?:\.json|/machine/(?:model|[0-9a-f]{{32}})\.json)\Z')


def managed_path(rel):
    return isinstance(rel, str) and _PATH.fullmatch(rel) is not None


def vendor_of(rel):
    match = _PATH.fullmatch(rel) if isinstance(rel, str) else None
    return match[1] if match else None


def directory_vendor(rel):
    match = re.fullmatch(rf'system/({_VENDOR})(?:/machine)?', rel)
    return match[1] if match else None


def manifest_paths(vendor, raw):
    if not re.fullmatch(_VENDOR, vendor):
        raise ValueError('invalid native package')
    try:
        manifest = json.loads(raw)
        marker = manifest['orcaone']
        if marker != {'kind': 'native_model', 'group_id': vendor[8:], 'format': 1}:
            raise ValueError('foreign native package')
        models, machines = manifest['machine_model_list'], manifest['machine_list']
        if (not isinstance(models, list) or len(models) != 1 or not isinstance(machines, list)
                or not machines or manifest.get('process_list') != [] or manifest.get('filament_list') != []):
            raise ValueError('invalid native package lists')
        paths = {f'system/{vendor}.json'}
        for entry in [*models, *machines]:
            subpath = entry['sub_path']
            rel = f'system/{vendor}/{subpath}'
            if not isinstance(entry.get('name'), str) or not entry['name'] or not managed_path(rel) or rel in paths:
                raise ValueError('invalid native package entry')
            paths.add(rel)
        if models[0]['sub_path'] != 'machine/model.json' or any(e['sub_path'] == 'machine/model.json' for e in machines):
            raise ValueError('invalid native model')
        return paths
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid native package') from exc


def safe_path(root, rel):
    path = root
    for part in PurePosixPath(rel).parts:
        path = path / part
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            return False
    return (root / rel).resolve() == root.resolve().joinpath(*PurePosixPath(rel).parts)


def validate_existing(data_dir, vendor):
    if not re.fullmatch(_VENDOR, vendor) or not safe_path(data_dir, f'system/{vendor}.json') or not safe_path(data_dir, f'system/{vendor}'):
        raise ValueError('unsafe native package')
    manifest = data_dir / 'system' / f'{vendor}.json'
    folder = data_dir / 'system' / vendor
    if not manifest.exists():
        if folder.exists():
            raise ValueError('unowned native package folder')
        return
    try:
        paths = manifest_paths(vendor, manifest.read_bytes())
        if folder.exists() and not folder.is_dir():
            raise ValueError('invalid native package folder')
        for path in folder.rglob('*') if folder.exists() else []:
            rel = path.relative_to(data_dir).as_posix()
            if not safe_path(data_dir, rel) or (path.is_dir() and rel != f'system/{vendor}/machine') or (not path.is_dir() and rel not in paths):
                raise ValueError('unexpected native package file')
        if any(not safe_path(data_dir, rel) for rel in paths):
            raise ValueError('unsafe native package member')
    except OSError as exc:
        raise ValueError('unreadable native package') from exc


def owned_files(data_dir):
    result = set()
    for manifest in (data_dir / 'system').glob('OrcaOne_*.json'):
        if not managed_path(f'system/{manifest.name}'):
            continue
        try:
            validate_existing(data_dir, manifest.stem)
            result.update(rel for rel in manifest_paths(manifest.stem, manifest.read_bytes()) if (data_dir / rel).is_file())
        except (ValueError, OSError):
            continue
    return result


def archive_owned_files(files):
    result = set()
    for rel, raw in files.items():
        vendor = vendor_of(rel)
        if not vendor or rel != f'system/{vendor}.json':
            continue
        try:
            paths = manifest_paths(vendor, raw)
        except ValueError:
            continue
        if paths.issubset(files):
            result.update(paths)
    return result
