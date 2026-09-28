# Native printer models: research and implementation constraints

Status: implemented with isolated backend and restore tests, 2026-09-28. Native GUI acceptance in OrcaSlicer remains pending; Snapmaker native package publishing is not enabled.

## Verified behavior

OrcaSlicer tag `v2.4.2` resolves to `8500fcdccaa10b5099ac20d252af3a7c560046f1` (`git ls-remote`). Its [printer dropdown](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/slic3r/GUI/PresetComboBoxes.cpp#L1238) groups only default/system presets by `printer_model`. User presets remain separate entries. Giving user presets the same model or alias cannot create one native printer entry.

The existing local Snapmaker source has the same condition in `slicer-src/snorca-v2.4.0/src/slic3r/GUI/PresetComboBoxes.cpp:1359`: system/default printer presets are grouped by model; other presets enter `nonsys_presets` individually at line 1392. [Snapmaker source](https://github.com/Snapmaker/OrcaSlicer/blob/v2.4.0/src/slic3r/GUI/PresetComboBoxes.cpp#L1359). This verifies the grouping condition only. Orca's package loading, variant suffixes and activation details below require separate Snapmaker verification before claiming support.

## OrcaSlicer package structure

The [system loader](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/libslic3r/PresetBundle.cpp#L2183) discovers vendor manifests in the Slicer data directory's `system/` folder. An isolated managed package would contain:

```text
system/OrcaOne_<stable-id>.json
system/OrcaOne_<stable-id>/machine/model.json
system/OrcaOne_<stable-id>/machine/nozzle_04.json
system/OrcaOne_<stable-id>/machine/nozzle_06.json
```

Illustrative vendor manifest:

```json
{
  "name": "OrcaOne",
  "version": "02.04.02.00",
  "machine_model_list": [
    {"name": "Workshop Voron", "sub_path": "machine/model.json"}
  ],
  "machine_list": [
    {"name": "Workshop Voron 0.4 nozzle", "sub_path": "machine/nozzle_04.json"},
    {"name": "Workshop Voron 0.6 nozzle", "sub_path": "machine/nozzle_06.json"}
  ],
  "process_list": [],
  "filament_list": []
}
```

Illustrative model:

```json
{
  "type": "machine_model",
  "name": "Workshop Voron",
  "model_id": "OrcaOne_<stable-id>",
  "nozzle_diameter": "0.4;0.6",
  "machine_tech": "FFF",
  "family": "OrcaOne",
  "bed_model": "",
  "bed_texture": "",
  "hotend_model": "",
  "default_materials": ""
}
```

Each machine JSON contains its validated effective printer configuration plus `type: machine`, a unique `name`, `instantiation: "true"`, `printer_model: "Workshop Voron"`, `printer_variant: "0.4"` and `nozzle_diameter: ["0.4"]` (respectively `0.6`). This field list is not a complete usable printer configuration.

- Omit `inherits` completely for materialized machines. Even an empty inherited name triggers parent lookup in the [loader](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/libslic3r/PresetBundle.cpp#L4884).
- Other vendors load independently in this version. A managed vendor cannot assume that a Voron or user parent is available; only the Orca filament library is provided as the external base bundle.
- Model and variant must match the vendor model declaration exactly. Names must not collide with already loaded presets.
- Vendor version must parse as Semver. `02.04.02.00` is an illustrative initial version, not evidence of a requirement to match the application version.
- Processes and filaments may remain user presets, with compatibility references to the new system machine names.

## Activation and same-diameter variants

Add an entry to the existing `models` array of `OrcaSlicer.conf`, preserving other entries:

```json
{
  "vendor": "OrcaOne_<stable-id>",
  "model": "Workshop Voron",
  "nozzle_diameter": "0.4;0.6"
}
```

`vendor` is the manifest filename stem, not its display name. `model` is the model-list name. [AppConfig loading](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/libslic3r/AppConfig.cpp#L734) and [preset visibility](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/libslic3r/Preset.cpp#L855) establish this requirement. Selecting the new printer immediately is optional and separate from making it available.

The [nozzle dropdown](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/libslic3r/Preset.cpp#L3320) contains unique `printer_variant` strings. Two different configurations both called `0.5` collapse into one option. [Preset selection](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/libslic3r/PresetBundle.cpp#L3750) chooses a preferred name or the first matching variant, so distinct configurations are not reliably individually selectable.

Orca [accepts a numeric diameter prefix with a suffix](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.2/src/libslic3r/PresetBundle.cpp#L5007), such as `0.5A` and `0.5B`. The user must deliberately choose distinguishable variants or resolve conflicting settings. Never silently discard a variant or infer equality from diameter alone. Multi-nozzle syntax uses `+`; it is not equivalent to several interchangeable single-nozzle profiles.

## Required write and restore boundary

`CLAUDE.md` now permits a narrow exception for marked OrcaOne-owned model packages in addition to `user/**` and the application conf. Arbitrary `system/` writes remain prohibited:

- Verify ownership and exact manifest/subfile allowlists; reject foreign packages, collisions, traversal and links escaping the managed paths.
- Include managed package files and conf changes in preview, stale-state checks, backup, atomic publication, failure rollback and restore.
- Extend scanning and subsequent editing to recognize managed profiles without treating other vendor presets as editable.
- Preserve live credentials through the existing protected writing path; never expose them in preview, history or a distributable package.
- Preserve original user profiles unless the user explicitly chooses migration/removal. Publishing a new model alone does not remove old dropdown entries.
- Native edits to system presets can create user copies, which again appear individually. Explain this limitation rather than promising user-profile grouping.

Native GUI acceptance, clean startup, nozzle switching and restore remain required before claiming either OrcaSlicer or Snapmaker support.
