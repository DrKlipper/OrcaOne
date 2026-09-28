import json

import pytest

from orcaone import backup, operations
from orcaone.profile_native_paths import managed_path, owned_files, validate_existing
from test_operations import isolated, snorca

VENDOR = 'OrcaOne_' + 'a' * 32
MANIFEST = f'system/{VENDOR}.json'
MODEL = f'system/{VENDOR}/machine/model.json'
MACHINE = f'system/{VENDOR}/machine/' + 'b' * 32 + '.json'


def package(root):
    data = {'orcaone': {'kind': 'native_model', 'format': 1, 'group_id': 'a' * 32},
            'machine_model_list': [{'name': 'Model', 'sub_path': 'machine/model.json'}],
            'machine_list': [{'name': 'Printer', 'sub_path': 'machine/' + 'b' * 32 + '.json'}],
            'process_list': [], 'filament_list': []}
    for rel, raw in ((MANIFEST, json.dumps(data).encode()), (MODEL, b'{}'), (MACHINE, b'{}')):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def test_namespace_and_foreign_collisions(tmp_path):
    assert managed_path(MANIFEST) and managed_path(MODEL) and managed_path(MACHINE)
    for path in ('system/Voron.json', f'system/{VENDOR}/machine/../../other.json', f'system/{VENDOR}/secret.json'):
        assert not managed_path(path)
    validate_existing(tmp_path, VENDOR)
    (tmp_path / 'system').mkdir()
    (tmp_path / MANIFEST).write_text('{}')
    with pytest.raises(ValueError):
        validate_existing(tmp_path, VENDOR)
    assert operations.outside_backup(tmp_path, MANIFEST, 'OrcaSlicer.conf')


def test_owned_files_and_symlink_rejection(tmp_path):
    package(tmp_path)
    assert owned_files(tmp_path) == {MANIFEST, MODEL, MACHINE}
    assert not operations.outside_backup(tmp_path, MACHINE, 'OrcaSlicer.conf')
    path = tmp_path / MACHINE
    path.unlink()
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip('symlink privilege unavailable')
    with pytest.raises(ValueError):
        validate_existing(tmp_path, VENDOR)
    assert operations.outside_backup(tmp_path, MACHINE, 'OrcaSlicer.conf')


def test_restore_removes_new_owned_package_but_preserves_foreign_vendor(snorca):
    made = backup.create(snorca, 'manual')
    package(snorca.data_dir)
    foreign = snorca.data_dir / 'system/Foreign.json'
    foreign.write_bytes(b'foreign')
    plan = operations.restore_plan(snorca, [], made['name'])
    assert not plan['blocked'], plan
    operations.apply(snorca.id, plan['id'])
    assert not (snorca.data_dir / MANIFEST).exists()
    assert not (snorca.data_dir / MACHINE).exists()
    assert foreign.read_bytes() == b'foreign'


def test_restore_old_owned_package_and_rollback_new_files(snorca):
    package(snorca.data_dir)
    made = backup.create(snorca, 'manual')
    files, _ = backup.restorable(snorca, made['name'])
    assert {MANIFEST, MODEL, MACHINE}.issubset(files)
    (snorca.data_dir / MACHINE).write_bytes(b'changed')
    plan = operations.restore_plan(snorca, [], made['name'])
    assert not plan['blocked'], plan
    operations.apply(snorca.id, plan['id'])
    assert (snorca.data_dir / MACHINE).read_bytes() == b'{}'


def test_rollback_removes_new_managed_files_and_empty_package(snorca):
    made = backup.create(snorca, 'manual')
    package(snorca.data_dir)
    steps = [operations.Step('write', rel, (snorca.data_dir / rel).read_bytes()) for rel in (MANIFEST, MODEL, MACHINE)]
    assert operations._roll_back(snorca, steps, made['name'])
    assert not (snorca.data_dir / MANIFEST).exists()
    assert not (snorca.data_dir / 'system' / VENDOR).exists()


def test_invalid_archive_ownership_is_never_restored(snorca):
    package(snorca.data_dir)
    (snorca.data_dir / MANIFEST).write_text('{}')
    made = backup.create(snorca, 'manual')
    files, _ = backup.restorable(snorca, made['name'])
    assert not {MANIFEST, MODEL, MACHINE}.intersection(files)
