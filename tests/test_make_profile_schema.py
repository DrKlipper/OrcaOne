import json
import subprocess
import sys

import pytest

from tools.make_profile_schema import ROOT, RELEASES, build_catalog, extract_catalog, SchemaBuildError


def source(key="speed"):
    return f'static std::vector<std::string> s_Preset_print_options {{"{key}"}};'


def test_unknown_default_expression_blocks_build():
    config = 'def = this->add("speed", coFloat); def->set_default_value(new ConfigOptionFloat(compute_unknown()));'
    with pytest.raises(SchemaBuildError) as exc:
        extract_catalog(config, source(), {})
    assert exc.value.code == "unresolved_default"
    assert exc.value.key == "speed"


def test_literal_default_limits_and_comments():
    config = '''// def = this->add("wrong", coFloat);
    def = this->add("speed", coFloat);
    def->min = 0; def->max = 100;
    def->set_default_value(new ConfigOptionFloat(12.5));'''
    entry = extract_catalog(config, source(), {})["options"]["process"]["speed"]
    assert entry["default"] == "12.5"
    assert (entry["min"], entry["max"]) == (0, 100)


def test_missing_definition_blocks_build():
    with pytest.raises(SchemaBuildError) as exc:
        extract_catalog("", source(), {})
    assert exc.value.code == "missing_definition"


def test_string_escapes_and_inline_enum():
    config = r'''def = this->add("speed", coString);
    def->enum_values = {"a//b", "c\"d"};
    def->set_default_value(new ConfigOptionString("a//b"));'''
    entry = extract_catalog(config, source(), {})["options"]["process"]["speed"]
    assert entry["enums"] == ["a//b", 'c"d']
    assert entry["default"] == "a//b"


def test_macro_and_enum_default_are_resolved_from_source():
    config = '''#define SPEED 12.5
    static t_config_enum_values s_keys_map_Mode {{"fast", Mode::Fast}, {"slow", Mode::Slow}};
    def = this->add("speed", coEnum);
    def->enum_keys_map = &ConfigOptionEnum<Mode>::get_enum_values();
    def->set_default_value(new ConfigOptionEnum<Mode>(Mode::Fast));'''
    entry = extract_catalog(config, source(), {})["options"]["process"]["speed"]
    assert entry["default"] == "fast"
    assert entry["enums"] == ["fast", "slow"]
    config = '#define SPEED 12.5\ndef = this->add("speed", coFloat); def->set_default_value(new ConfigOptionFloat(SPEED));'
    assert extract_catalog(config, source(), {})["options"]["process"]["speed"]["default"] == "12.5"


def test_vector_dimensions_are_not_inferred_from_length():
    config = 'def = this->add("speed", coFloats); def->set_default_value(new ConfigOptionFloats{1, 2});'
    with pytest.raises(SchemaBuildError, match="unclassified_dimension"):
        extract_catalog(config, source(), {})


def test_points_and_float_or_percent_vectors():
    config = 'def = this->add("speed", coPoints); def->set_default_value(new ConfigOptionPoints{Vec2d(0, 1), Vec2d(2, 3)});'
    rules = {"dimensions": {"speed": "points"}}
    assert extract_catalog(config, source(), rules)["options"]["process"]["speed"]["default"] == ["0x1", "2x3"]
    config = 'def = this->add("speed", coFloatsOrPercents); def->set_default_value(new ConfigOptionFloatsOrPercents{{25, true}, {3, false}});'
    rules = {"dimensions": {"speed": "flow"}}
    assert extract_catalog(config, source(), rules)["options"]["process"]["speed"]["default"] == ["25%", "3"]


def test_repeated_add_retains_prior_limits():
    config = 'def = this->add("speed", coFloat); def->min = 0; def->set_default_value(new ConfigOptionFloat(1)); def = this->add("speed", coFloat); def->set_default_value(new ConfigOptionFloat(2));'
    entry = extract_catalog(config, source(), {})["options"]["process"]["speed"]
    assert entry["default"] == "2"
    assert entry["min"] == 0


def test_nullable_loop_copies_default_and_limits():
    config = '''def = this->add("speed", coFloats); def->min = 0;
    def->set_default_value(new ConfigOptionFloats{12.5});
    for (const char *opt_key : {"speed"}) {
        auto it_opt = options.find(opt_key);
        def = this->add_nullable(std::string("filament_") + opt_key, it_opt->second.type);
        def->min = it_opt->second.min;
        def->set_default_value(new ConfigOptionFloatsNullable(static_cast<const ConfigOptionFloats*>(it_opt->second.default_value.get())->values));
    }'''
    entry = extract_catalog(config, source("filament_speed"), {"dimensions": {"filament_speed": "filament"}})["options"]["process"]["filament_speed"]
    assert entry["default"] == ["12.5"]
    assert entry["nullable"] is True
    assert entry["min"] == 0


def test_axis_loop_reads_each_source_value():
    config = '''std::vector<AxisDefault> axes {
        {"x", {500., 200.}, {1000., 900.}, {10., 9.}},
        {"z", {12., 11.}, {500., 200.}, {0.2, 0.4}}
    };
    for (const AxisDefault &axis : axes) {
        def = this->add("machine_max_speed_" + axis.name, coFloats);
        def->min = 0;
        def->set_default_value(new ConfigOptionFloats(axis.max_feedrate));
    }'''
    key = "machine_max_speed_z"
    entry = extract_catalog(config, source(key), {"dimensions": {key: "list"}})["options"]["process"][key]
    assert entry["default"] == ["12", "11"]


def test_nullable_assignment_and_nil_are_preserved():
    config = 'def = this->add("speed", coPercents); def->nullable = true; def->set_default_value(new ConfigOptionPercentsNullable{ConfigOptionPercentsNullable::nil_value()});'
    entry = extract_catalog(config, source(), {"dimensions": {"speed": "flow"}})["options"]["process"]["speed"]
    assert entry["nullable"] is True
    assert entry["default"] == ["nil"]


def test_copied_enum_values_and_casted_default():
    config = '''static t_config_enum_values s_keys_map_Mode = {{"fast", int(Mode::Fast)}, {"slow", int(Mode::Slow)}};
    auto original = def = this->add("base", coEnum);
    def->enum_values = {"fast", "slow"};
    def->enum_keys_map = &ConfigOptionEnum<Mode>::get_enum_values();
    def->set_default_value(new ConfigOptionEnum<Mode>(Mode::Slow));
    def = this->add("speed", coEnums);
    def->enum_values = original->enum_values;
    def->enum_keys_map = original->enum_keys_map;
    def->set_default_value(new ConfigOptionEnumsGeneric{(int) Mode::Fast});'''
    entry = extract_catalog(config, source(), {"dimensions": {"speed": "flow"}})["options"]["process"]["speed"]
    assert entry["default"] == ["fast"]
    assert entry["enums"] == ["fast", "slow"]


@pytest.mark.parametrize("filename,counts", [
    ("orca-2.4.2.json", {"process": 355, "filament": 126, "machine": 160}),
    ("snorca-2.4.0.json", {"process": 319, "filament": 106, "machine": 134}),
])
def test_bundled_catalog_is_complete_and_defaults_validate_offline(filename, counts):
    from orcaone.profile_schema import validate_value

    catalog = json.loads((ROOT / "orcaone/profile_schemas" / filename).read_text(encoding="utf-8"))
    assert catalog["complete"] is True
    assert catalog["coverage"]["expected"] == counts
    assert catalog["coverage"]["read"] == counts
    assert catalog["coverage"]["unclassified"] == []
    assert catalog["coverage"]["missing_defaults"] == []
    assert catalog["coverage"]["rule_count"] == catalog["coverage"]["rules_verified"]
    for kind, fields in catalog["options"].items():
        assert len(fields) == counts[kind]
        for key, option in fields.items():
            assert option["default"] is not None, (kind, key)
            assert option["complete"] is True, (kind, key)
            assert validate_value(option, option["default"]) == [], (kind, key)
            assert "tooltip" not in option and "label" not in option
    machine = catalog["options"]["machine"]
    assert machine["machine_max_speed_z"]["default"] == ["12", "12"]
    assert machine["printhost_apikey"]["role"] == "secret"
    assert catalog["options"]["process"]["inherits"]["role"] == "reference"


def test_bundled_release_specific_types_and_dimensions():
    orca = json.loads((ROOT / "orcaone/profile_schemas/orca-2.4.2.json").read_text(encoding="utf-8"))
    snorca = json.loads((ROOT / "orcaone/profile_schemas/snorca-2.4.0.json").read_text(encoding="utf-8"))
    assert orca["options"]["process"]["outer_wall_speed"]["type"] == "coFloat"
    assert snorca["options"]["process"]["outer_wall_speed"]["type"] == "coFloats"
    assert snorca["options"]["process"]["outer_wall_speed"]["dimension"] == "flow"
    assert orca["options"]["machine"]["nozzle_diameter"]["dimension"] == "extruder"
    assert orca["options"]["filament"]["filament_ironing_flow"]["default"] == ["nil"]
    assert orca["options"]["filament"]["filament_ironing_flow"]["nullable"] is True
    assert orca["options"]["filament"]["filament_type"]["enum_open"] is True


@pytest.mark.parametrize("release", list(RELEASES))
def test_pinned_source_reproduces_catalog_when_available(release):
    _, directory, filename = RELEASES[release]
    source_dir = ROOT / "slicer-src" / directory
    if not source_dir.is_dir():
        pytest.skip("Optional pinned upstream sources are not installed")
    built = build_catalog(*release, source_dir)
    bundled = json.loads((ROOT / "orcaone/profile_schemas" / filename).read_text(encoding="utf-8"))
    assert built == bundled
    assert build_catalog(*release, source_dir) == built


def test_changed_source_is_rejected_before_extraction(tmp_path):
    rules = json.loads((ROOT / "tools/profile_schema_rules.json").read_text(encoding="utf-8"))["OrcaSlicer"]
    first = next(iter(rules["source_sha256"]))
    path = tmp_path / first
    path.parent.mkdir(parents=True)
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(SchemaBuildError) as exc:
        build_catalog("OrcaSlicer", "2.4.2", tmp_path)
    assert exc.value.code == "source_hash_mismatch"


def test_nullable_loop_with_unknown_copy_expression_blocks():
    config = '''def = this->add("speed", coFloats);
    def->set_default_value(new ConfigOptionFloats{12.5});
    for (const char *opt_key : {"speed"}) {
        auto it_opt = options.find(opt_key);
        def = this->add_nullable(std::string("filament_") + opt_key, it_opt->second.type);
        def->set_default_value(new ConfigOptionFloatsNullable(compute_unknown(it_opt->second.default_value.get()->values)));
    }'''
    with pytest.raises(SchemaBuildError, match="unresolved_nullable_loop"):
        extract_catalog(config, source("filament_speed"), {"dimensions": {"filament_speed": "filament"}})


def test_unresolved_units_and_limits_block():
    for field, expected in (("min", "unresolved_limit"), ("sidetext", "unresolved_unit")):
        config = f'def = this->add("speed", coFloat); def->{field} = unknown(); def->set_default_value(new ConfigOptionFloat(12.5));'
        with pytest.raises(SchemaBuildError) as exc:
            extract_catalog(config, source(), {})
        assert exc.value.code == expected


def test_delimiters_inside_comments_and_strings_do_not_change_ownership():
    config = r'''void initialize() {
        def = this->add("speed", coString);
        def->set_default_value(new ConfigOptionString("quoted\"; } // text"));
        /* } def = this->add("bad", coFloat); */
    }
    void other() { def->set_default_value(new ConfigOptionString("wrong")); }'''
    assert extract_catalog(config, source(), {})["options"]["process"]["speed"]["default"] == 'quoted"; } // text'


def test_generator_cli_can_run_as_a_script():
    result = subprocess.run([sys.executable, str(ROOT / "tools/make_profile_schema.py"), "--help"],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert "--output-dir" in result.stdout
