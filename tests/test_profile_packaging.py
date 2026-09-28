import json
from pathlib import Path
import shutil
import subprocess
import sys

from tools.build import data_files


ROOT = Path(__file__).resolve().parents[1]


def test_portable_asset_list_includes_catalogs_but_never_local_history():
    entries = data_files()
    assert (ROOT / "orcaone/profile_schemas", "orcaone/profile_schemas") in entries
    for source, _ in entries:
        assert "data" not in source.relative_to(ROOT).parts
        assert "slicer-src" not in source.relative_to(ROOT).parts
        assert "snapshots" not in source.relative_to(ROOT).parts


def test_staged_catalog_package_loads_offline_without_upstream_sources(tmp_path):
    for source, destination in data_files():
        if destination != "orcaone/profile_schemas":
            continue
        shutil.copytree(source, tmp_path / destination)
    package = tmp_path / "orcaone"
    shutil.copy2(ROOT / "orcaone/__init__.py", package)
    shutil.copy2(ROOT / "orcaone/profile_schema.py", package)
    script = '''import json, sys
sys.path.insert(0, sys.argv[1])
from orcaone.profile_schema import load_catalog
result = {}
for slicer, version in [("OrcaSlicer", "2.4.2"), ("Snapmaker_Orca", "2.4.0")]:
    catalog = load_catalog(slicer, version)
    assert catalog and catalog["complete"]
    result[catalog["id"]] = sum(len(x) for x in catalog["options"].values())
assert load_catalog("OrcaSlicer", "2.4.3") is None
print(json.dumps(result))
'''
    result = subprocess.run([sys.executable, "-I", "-c", script, str(tmp_path)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"OrcaSlicer@2.4.2": 641, "Snapmaker_Orca@2.4.0": 559}
