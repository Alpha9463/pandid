"""The declarative spec format: round-tripping, feature coverage, and the
quality of the errors a hand-written file gets back.

The error tests assert on the *message*, not just the type. Whoever writes one
of these files is a process engineer with a typo, not a programmer with a
traceback, so "unknown key 'varient'" that goes on to name the real key is the
feature — a bare ValueError is a bug report waiting to happen.
"""

import json
import sys

import pytest

# The round-trip corpus is the golden scenarios: the same seven flowsheets the
# examples draw, already built here once. Re-typing them would only let the two
# copies drift.
from test_golden import SCENARIOS

from pfd import Flowsheet, units
from pfd.document import Annotation, TableBox
from pfd.spec import SpecError

try:  # PyYAML is an optional extra, so the YAML tests skip without it
    import yaml  # noqa: F401

    _HAS_YAML = True
except ImportError:  # pragma: no cover - exercised only on a bare install
    _HAS_YAML = False


def _spec(**overrides):
    """A minimal valid spec, with one section swapped in per test."""
    spec = {
        "name": "T",
        "units": [
            {"kind": "Feed", "name": "F"},
            {"kind": "Pump", "name": "P-101"},
            {"kind": "Product", "name": "P"},
        ],
        "streams": [
            {"from": ["F", "outlet"], "to": ["P-101", "suction"]},
            {"from": ["P-101", "discharge"], "to": ["P", "inlet"]},
        ],
    }
    spec.update(overrides)
    return spec


# --- round-tripping -----------------------------------------------------------


@pytest.mark.parametrize("name", list(SCENARIOS), ids=list(SCENARIOS))
def test_every_example_round_trips(name):
    """to_dict() -> from_dict() -> the same spec, and the same drawing.

    Comparing the rendered SVG is what makes this a real round trip: a spec that
    merely re-imports without raising could still have dropped a pin, a mirror
    or a port face, and only the geometry would show it.
    """
    build, render_kwargs = SCENARIOS[name]
    original = build()
    spec = original.to_dict()

    assert json.loads(json.dumps(spec)) == spec, "spec must be JSON-safe"

    rebuilt = Flowsheet.from_dict(spec)
    assert rebuilt.to_dict() == spec
    assert rebuilt.to_svg(**render_kwargs) == original.to_svg(**render_kwargs)


def test_round_trip_keeps_whole_number_coordinates_whole():
    """pin(x=60) must not come back as 60.0 -- it changes every path string."""
    fs = Flowsheet("T")
    fs.add(units.Feed("F")).pin(x=60, y=105)
    assert fs.to_dict()["units"][0]["pin"] == {"x": 60, "y": 105}


# --- equipment ----------------------------------------------------------------


@pytest.mark.parametrize("kind", ["HeatExchanger", "heatexchanger", "heat_exchanger", "hex"])
def test_kind_accepts_the_names_a_reader_would_use(kind):
    fs = Flowsheet.from_dict({"name": "T", "units": [{"kind": kind, "name": "E-1"}]})
    assert isinstance(fs.units[0], units.HeatExchanger)


def test_unit_fields():
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "Valve",
                    "name": "FV-1",
                    "variant": "control",
                    "description": "Feed Control Valve",
                    "reference": "PFD-100",
                    "width": 60,
                    "height": 32,
                    "label_pos": "bottom",
                    "significant": True,
                }
            ],
        }
    )
    valve = fs.units[0]
    assert (valve.variant, valve.width, valve.height) == ("control", 60, 32)
    assert valve.description == "Feed Control Valve"
    assert valve.reference == "PFD-100"
    assert valve.label_pos == "bottom"
    assert valve.significant is True


def test_variable_port_units():
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {"kind": "Mixer", "name": "M-1", "n_inlets": 4},
                {"kind": "Splitter", "name": "SP-1", "n_outlets": 3},
            ],
        }
    )
    assert sorted(fs.units[0].ports) == ["in_1", "in_2", "in_3", "in_4", "outlet"]
    assert sorted(fs.units[1].ports) == ["inlet", "out_1", "out_2", "out_3"]


def test_pin_absolute_and_grid():
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {"kind": "Pump", "name": "P-1", "pin": {"x": 200, "y": 100, "orientation": 90}},
                {"kind": "Pump", "name": "P-2", "pin": {"col": 2, "row": 1, "mirrored": "y"}},
            ],
        }
    )
    assert (fs.units[0].pin_.x, fs.units[0].pin_.y) == (200, 100)
    assert fs.units[0].pin_.orientation == 90
    assert (fs.units[1].pin_.col, fs.units[1].pin_.row) == (2, 1)
    assert (fs.units[1].pin_.mirrored, fs.units[1].pin_.mirror_y) == (False, True)


def test_port_faces():
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "Vessel",
                    "name": "V-1",
                    "variant": "horizontal",
                    "port_faces": {"inlet": "N"},
                }
            ],
        }
    )
    assert fs.units[0]._port_faces == {"inlet": "N"}


def test_components_accept_a_bare_name_or_a_formula():
    fs = Flowsheet.from_dict(
        {"name": "T", "components": ["Nitrogen", {"name": "Water", "formula": "H2O"}]}
    )
    assert [(c.name, c.formula) for c in fs.components] == [("Nitrogen", None), ("Water", "H2O")]


def test_flowsheet_level_options():
    fs = Flowsheet.from_dict({"name": "T", "direction": "RL", "stream_naming_scheme": "L-{n}"})
    assert fs.direction == "RL"
    assert fs.stream_naming_scheme == "L-{n}"


# --- connections --------------------------------------------------------------


def test_stream_fields():
    fs = Flowsheet.from_dict(
        _spec(
            streams=[
                {
                    "from": ["F", "outlet"],
                    "to": ["P-101", "suction"],
                    "name": "100-BFW-01",
                    "tear_hint": True,
                    "color": "#0a7",
                    "dasharray": "6,3",
                    "via": [[130, 65], [130, 110]],
                    "properties": {"Temperature": "25 C", "Flow": 1200},
                }
            ]
        )
    )
    stream = fs.streams[0]
    assert stream.name == "100-BFW-01"
    assert stream.auto_named is False
    assert stream.tear_hint is True
    assert (stream.color, stream.dasharray) == ("#0a7", "6,3")
    assert stream.route.manual is True
    assert stream.route.waypoints == [(130, 65), (130, 110)]
    assert stream.properties == {"Temperature": "25 C", "Flow": 1200}


def test_signal_lines_take_a_kind():
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [{"kind": "Valve", "name": "FV-1"}],
            "instruments": [{"type": "FIC", "number": 101}],
            "streams": [
                {"from": ["FIC-101", "sig_out"], "to": ["FV-1", "actuator"], "kind": "pneumatic"}
            ],
        }
    )
    assert fs.streams[0].kind == "pneumatic"


def test_endpoints_may_be_spelled_out():
    fs = Flowsheet.from_dict(
        _spec(
            streams=[
                {
                    "from": {"unit": "F", "port": "outlet"},
                    "to": {"unit": "P-101", "port": "suction"},
                }
            ]
        )
    )
    assert fs.streams[0].dest.name == "suction"


# --- instruments --------------------------------------------------------------


def test_instrument_attached_to_a_unit():
    fs = Flowsheet.from_dict(
        _spec(
            instruments=[
                {
                    "type": "LIC",
                    "number": 101,
                    "variant": "panel",
                    "on": "P-101",
                    "at": "S",
                    "offset": 90,
                    "angle": 35,
                    "port_faces": {"sig_out": "W"},
                }
            ]
        )
    )
    inst = fs.units[-1]
    assert inst.name == "LIC-101"
    assert (inst.type, inst.number, inst.variant) == ("LIC", "101", "panel")
    assert inst.host.name == "P-101"
    assert (inst.at, inst.offset, inst.angle) == ("S", 90.0, 35.0)
    assert inst._port_faces == {"sig_out": "W"}


def test_instrument_tapping_a_line_by_the_port_it_leaves():
    fs = Flowsheet.from_dict(
        _spec(
            instruments=[
                {"type": "FE", "number": 101, "on": ["F", "outlet"], "at": 0.4, "offset": 0}
            ]
        )
    )
    inst = fs.units[-1]
    assert inst.host is fs.streams[0]
    assert (inst.at, inst.offset) == (0.4, 0.0)


def test_instrument_tapping_a_named_line():
    fs = Flowsheet.from_dict(
        _spec(
            streams=[{"from": ["F", "outlet"], "to": ["P-101", "suction"], "name": "100-P-01"}],
            instruments=[{"type": "FT", "number": 101, "on": "100-P-01"}],
        )
    )
    assert fs.units[-1].host is fs.streams[0]


def test_unattached_instrument_is_laid_out_like_any_unit():
    fs = Flowsheet.from_dict(_spec(instruments=[{"type": "PI", "number": 7}]))
    assert fs.units[-1].host is None


# --- sheet furniture ----------------------------------------------------------


def test_title_block_and_revisions():
    fs = Flowsheet.from_dict(
        _spec(
            title_block={
                "title": "Utilities U200",
                "subtitle": "Sheet 1",
                "drawing_number": "PFD-2001",
                "status": "ISSUED FOR REVIEW",
                "sheet": "1",
                "of_sheets": "2",
                "revisions": [
                    {"rev": "A", "date": "2026-05-18", "description": "Issued", "by": "AA"},
                    {
                        "rev": "B",
                        "date": "2026-07-02",
                        "description": "Spillback",
                        "by": "AA",
                        "checked": "JS",
                        "approved": "RL",
                    },
                ],
            }
        )
    )
    block = fs.title_block
    assert (block.title, block.drawing_number, block.of_sheets) == (
        "Utilities U200",
        "PFD-2001",
        "2",
    )
    assert [r.rev for r in block.revisions] == ["A", "B"]
    assert block.revisions[1].approved == "RL"


def test_annotation_boxes():
    fs = Flowsheet.from_dict(
        _spec(
            units=[{"kind": "Pump", "name": "P-101", "description": "Feed Pump"}],
            streams=[],
            annotations=[
                {"type": "equipment_list", "align": "top-right", "margin": 6},
                {"type": "notes", "items": ["Sample every product line."], "align": "top"},
                {"type": "legend", "entries": {"SS": "316L"}, "align": "top-left"},
                {
                    "type": "annotation",
                    "title": "HOLD",
                    "rows": ["Awaiting vendor data"],
                    "position": [1200, 90],
                },
                {
                    "type": "table",
                    "title": "TIE-INS",
                    "headers": ["Tag", "Line"],
                    "rows": [["TI-1", "6-P-101"]],
                    "col_align": ["l", "c"],
                },
            ],
        )
    )
    schedule, note_box, legend_box, hold, table = fs.annotations
    assert schedule.rows == [("P-101", "Feed Pump")]
    assert (schedule.align, schedule.margin) == ("top-right", 6)
    assert note_box.rows == [("1.", "Sample every product line.")]
    assert legend_box.rows == [("SS", "316L")]
    assert hold.position == (1200, 90)
    assert isinstance(hold, Annotation) and isinstance(table, TableBox)
    assert table.headers == ["Tag", "Line"] and table.col_align == ["l", "c"]


def test_stream_table_sections():
    fs = Flowsheet.from_dict(_spec(stream_table_sections=[["Benzene", "Mass Fraction"]]))
    assert fs.stream_table_sections == [("Benzene", "Mass Fraction")]


# --- file loaders -------------------------------------------------------------


def test_from_json(tmp_path):
    path = tmp_path / "fs.json"
    path.write_text(json.dumps(_spec()), encoding="utf-8")
    assert len(Flowsheet.from_json(path).streams) == 2


@pytest.mark.skipif(not _HAS_YAML, reason="PyYAML is an optional extra")
def test_from_yaml(tmp_path):
    path = tmp_path / "fs.yaml"
    path.write_text(
        "name: Skid\n"
        "units:\n"
        "  - {kind: Feed, name: Raw Feed, pin: {x: 60, y: 275}}\n"
        "  - {kind: Fitting, name: ST-101, variant: strainer}\n"
        "streams:\n"
        "  - from: [Raw Feed, outlet]\n"
        "    to: [ST-101, inlet]\n",
        encoding="utf-8",
    )
    fs = Flowsheet.from_yaml(path)
    assert fs.name == "Skid"
    assert fs.units[0].pin_.x == 60
    assert fs.units[1].variant == "strainer"


@pytest.mark.skipif(not _HAS_YAML, reason="PyYAML is an optional extra")
def test_yaml_reads_the_keys_that_were_written(tmp_path):
    """YAML 1.1 makes ``on:`` the boolean True and a bare date a date object.

    Both traps are sprung by writing the format exactly as documented, so the
    loader follows the YAML 1.2 core schema instead.
    """
    path = tmp_path / "fs.yaml"
    path.write_text(
        "name: T\n"
        "units: [{kind: Vessel, name: V-1}]\n"
        "instruments:\n"
        "  - type: LIC\n"
        "    number: 101\n"
        "    on: V-1\n"
        "    at: S\n"
        "title_block: {revisions: [{rev: A, date: 2026-05-18}]}\n",
        encoding="utf-8",
    )
    fs = Flowsheet.from_yaml(path)
    assert fs.units[-1].host is fs.units[0]
    assert fs.title_block.revisions[0].date == "2026-05-18"


def test_from_yaml_without_pyyaml_says_exactly_what_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)  # makes `import yaml` fail
    path = tmp_path / "fs.yaml"
    path.write_text("name: T\n", encoding="utf-8")
    with pytest.raises(ImportError) as excinfo:
        Flowsheet.from_yaml(path)
    message = str(excinfo.value)
    assert "PyYAML" in message
    assert "pip install 'chem-pfd[yaml]'" in message
    assert "from_json" in message  # and the way out that needs nothing


# --- errors: the spec is validated, never guessed ------------------------------


def test_unknown_kind_lists_the_valid_ones():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict({"name": "T", "units": [{"kind": "Pmup", "name": "P-1"}]})
    message = str(excinfo.value)
    assert "units[0]" in message  # which entry
    assert "'Pmup'" in message  # what you wrote
    assert "did you mean 'Pump'?" in message  # what you meant
    assert "'HeatExchanger'" in message and "'Column'" in message  # what exists


def test_unknown_port_lists_that_unit_s_ports():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(streams=[{"from": ["P-101", "dischrge"], "to": ["P", "inlet"]}]))
    message = str(excinfo.value)
    assert "streams[0].from" in message
    assert "Pump 'P-101' has no port 'dischrge'" in message
    assert "did you mean 'discharge'?" in message
    assert "available ports: ['discharge', 'suction']" in message


def test_unknown_port_face_lists_that_unit_s_ports():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {"name": "T", "units": [{"kind": "Pump", "name": "P-1", "port_faces": {"sution": "N"}}]}
        )
    message = str(excinfo.value)
    assert "port_faces" in message
    assert "has no port 'sution'" in message
    assert "did you mean 'suction'?" in message


def test_fixed_nozzle_cannot_be_moved():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {
                "name": "T",
                "units": [{"kind": "Column", "name": "T-1", "port_faces": {"bottoms": "N"}}],
            }
        )
    # A column's bottoms leaves the bottom because gravity put it there, so its
    # menu has one entry. The message names the drawn faces actually on offer.
    message = str(excinfo.value)
    assert "T-1.bottoms" in message
    assert "can be piped from S as drawn" in message
    assert "you asked for 'N'" in message


@pytest.mark.parametrize(
    "entry, expected",
    [
        ({"to": ["P", "inlet"]}, "'from' is missing"),
        ({"from": ["F", "outlet"]}, "'to' is missing"),
        ({"from": "F.outlet", "to": ["P", "inlet"]}, "an endpoint is [unit, port]"),
        ({"from": ["F", "outlet", "extra"], "to": ["P", "inlet"]}, "exactly two items"),
        ({"from": ["Fedd", "outlet"], "to": ["P", "inlet"]}, "no unit named 'Fedd'"),
    ],
)
def test_malformed_connection_names_the_offending_entry(entry, expected):
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(streams=[entry]))
    message = str(excinfo.value)
    assert "streams[0]" in message
    assert expected in message


def test_a_connection_that_is_not_a_mapping_at_all():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(streams=[["F", "P-101"]]))
    assert "streams[0] must be a mapping" in str(excinfo.value)
    assert "['F', 'P-101']" in str(excinfo.value)


@pytest.mark.parametrize(
    "spec, where, key, hint",
    [
        ({"name": "T", "unts": []}, "the flowsheet spec", "'unts'", "'units'"),
        (
            _spec(units=[{"kind": "Pump", "name": "P-1", "varient": "gear"}]),
            "units[0] 'P-1'",
            "'varient'",
            "'variant'",
        ),
        (
            _spec(streams=[{"from": ["F", "outlet"], "to": ["P-101", "suction"], "tear": True}]),
            "streams[0]",
            "'tear'",
            "'tear_hint'",
        ),
        (
            {"name": "T", "units": [{"kind": "Pump", "name": "P-1", "pin": {"xx": 1}}]},
            "units[0] 'P-1'.pin",
            "'xx'",
            "'x'",
        ),
    ],
)
def test_unknown_key_is_rejected_not_ignored(spec, where, key, hint):
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(spec)
    message = str(excinfo.value)
    assert f"{where}: unknown key {key}" in message
    assert f"did you mean {hint}?" in message
    assert "allowed keys:" in message


def test_variable_port_count_belongs_to_its_own_kind():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {"name": "T", "units": [{"kind": "Pump", "name": "P-1", "n_inlets": 3}]}
        )
    assert "only a Mixer takes 'n_inlets', not a Pump" in str(excinfo.value)


def test_instruments_are_not_declared_as_units():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict({"name": "T", "units": [{"kind": "Instrument", "name": "FT-101"}]})
    message = str(excinfo.value)
    assert "instruments go in the top-level 'instruments:' section" in message
    assert "on/at/offset/angle" in message


def test_attachment_arguments_need_a_host():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(instruments=[{"type": "FT", "number": 101, "at": 0.5}]))
    assert "['at'] only mean something with 'on'" in str(excinfo.value)


def test_unknown_attachment_host():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(instruments=[{"type": "FT", "number": 101, "on": "P-1O1"}]))
    message = str(excinfo.value)
    assert "nothing named 'P-1O1' to attach to" in message
    assert "did you mean 'P-101'?" in message


def test_missing_required_fields():
    with pytest.raises(SpecError, match="needs a 'name'"):
        Flowsheet.from_dict({"units": []})
    with pytest.raises(SpecError, match=r"units\[0\] needs a 'kind'"):
        Flowsheet.from_dict({"name": "T", "units": [{"name": "P-1"}]})
    with pytest.raises(SpecError, match="a Pump needs a 'name'"):
        Flowsheet.from_dict({"name": "T", "units": [{"kind": "Pump"}]})
    with pytest.raises(SpecError, match=r"instruments\[0\] needs a 'type'"):
        Flowsheet.from_dict({"name": "T", "instruments": [{"number": 101}]})


def test_a_number_where_text_was_meant_says_to_quote_it():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict({"name": "T", "units": [{"kind": "Feed", "name": 101}]})
    assert "must be text, got 101 (quote it if it is a number)" in str(excinfo.value)


def test_library_errors_are_reported_against_the_entry_that_caused_them():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {
                "name": "T",
                "units": [{"kind": "Pump", "name": "P-1"}, {"kind": "Pump", "name": "P-1"}],
            }
        )
    message = str(excinfo.value)
    assert "units[1] 'P-1'" in message
    assert "already exists on this flowsheet" in message


def test_reusing_a_port_is_reported_against_the_second_connection():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            _spec(
                streams=[
                    {"from": ["F", "outlet"], "to": ["P-101", "suction"]},
                    {"from": ["F", "outlet"], "to": ["P", "inlet"]},
                ]
            )
        )
    message = str(excinfo.value)
    assert "streams[1]" in message
    assert "F.outlet is already connected" in message


def test_unknown_annotation_type():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(annotations=[{"type": "notess", "items": []}]))
    message = str(excinfo.value)
    assert "unknown box type 'notess'" in message
    assert "did you mean 'notes'?" in message


def test_bad_alignment_is_reported_with_the_valid_ones():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(annotations=[{"type": "notes", "items": [], "align": "up"}]))
    assert "align must be one of" in str(excinfo.value)


def test_invalid_json_points_at_the_line(tmp_path):
    path = tmp_path / "fs.json"
    path.write_text('{"name": "T",}', encoding="utf-8")
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_json(path)
    assert "not valid JSON" in str(excinfo.value)
    assert "line 1" in str(excinfo.value)


@pytest.mark.skipif(not _HAS_YAML, reason="PyYAML is an optional extra")
def test_empty_yaml_file(tmp_path):
    path = tmp_path / "fs.yaml"
    path.write_text("# nothing here yet\n", encoding="utf-8")
    with pytest.raises(SpecError, match="is empty"):
        Flowsheet.from_yaml(path)


def test_a_unit_class_the_reader_could_not_rebuild_is_refused():
    class Reboiler(units.HeatExchanger):
        pass

    fs = Flowsheet("T")
    fs.add(Reboiler("E-1"))
    with pytest.raises(SpecError, match="not one of the built-in equipment classes"):
        fs.to_dict()


def test_a_callable_naming_scheme_cannot_be_written_out():
    fs = Flowsheet("T", stream_naming_scheme=lambda n: f"S{n:03d}")
    with pytest.raises(SpecError, match="callable stream_naming_scheme"):
        fs.to_dict()
