import json

from orcaone import backup, operations
from orcaone.profile_native_paths import owned_files
from test_operations import isolated, orca
from test_profile_native import native_orca, composition


def system_files(instance):
    return {p.relative_to(instance.data_dir).as_posix(): p.read_bytes()
            for p in (instance.data_dir / 'system').rglob('*') if p.is_file()}


def test_restore_before_native_publish_removes_whole_package(native_orca):
    baseline = system_files(native_orca)
    original_users = {p.relative_to(native_orca.data_dir).as_posix(): p.read_bytes()
                      for p in (native_orca.data_dir / 'user').rglob('*') if p.is_file()}
    plan, preview, _ = composition(native_orca, 'move')
    published = operations.apply(native_orca.id, plan['id'])
    assert published['receipt_state'] == 'verified'
    assert owned_files(native_orca.data_dir)
    restore = operations.restore_plan(native_orca, [], published['backup']['name'])
    assert restore['blocked'] is None
    assert operations.apply(native_orca.id, restore['id'])['ok']
    assert system_files(native_orca) == baseline
    vendor = 'OrcaOne_' + preview['group']['id']
    assert not (native_orca.data_dir / 'system' / vendor).exists()
    assert not owned_files(native_orca.data_dir)
    for rel, raw in original_users.items():
        assert (native_orca.data_dir / rel).read_bytes() == raw


def test_restore_native_package_exact_bytes_and_preserves_other_vendors(native_orca):
    plan, _, _ = composition(native_orca)
    operations.apply(native_orca.id, plan['id'])
    baseline = system_files(native_orca)
    made = backup.create(native_orca, 'manual')
    paths = owned_files(native_orca.data_dir)
    for rel in paths:
        path = native_orca.data_dir / rel
        values = json.loads(path.read_bytes())
        values['restoration_test'] = 'changed after backup'
        path.write_text(json.dumps(values), encoding='utf-8')
    restore = operations.restore_plan(native_orca, [], made['name'])
    assert restore['blocked'] is None
    assert operations.apply(native_orca.id, restore['id'])['ok']
    assert system_files(native_orca) == baseline
    assert owned_files(native_orca.data_dir) == paths
