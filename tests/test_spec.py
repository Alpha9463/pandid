"""Test the declarative spec format: round-tripping, feature coverage and error messages."""

import json
import sys
import warnings
from typing import Any

import pytest

from pandid import Flowsheet, units
from pandid.document import Annotation, TableBox, legend
from pandid.spec import SpecError

try:
    import yaml  # noqa: F401

    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False


def _spec(**overrides):
    """Return a minimal valid spec with the given sections swapped in."""
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


def test_round_trip_keeps_whole_number_coordinates_whole():
    """Check that a whole-number pin is written back as an int, not a float."""
    fs = Flowsheet("T")
    fs.add(units.Pump("P-1")).pin(x=60, y=105)
    assert fs.to_dict()["units"][0]["pin"] == {"x": 60, "y": 105}


def test_a_flag_comes_back_where_it_was_pinned():
    """Check that a pinned feed flag reads back at the same pin."""
    fs = Flowsheet("T")
    fs.add(units.Feed("F")).pin(x=60, y=105)
    assert Flowsheet.from_dict(fs.to_dict()).units[0].pin_ == fs.units[0].pin_


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
                    "width": 60,
                    "height": 32,
                    "label_pos": "bottom",
                    "new_line_number": True,
                },
                {"kind": "Feed", "name": "Raw Feed", "reference": "PFD-100"},
            ],
        }
    )
    valve, feed = fs.units
    assert (valve.variant, valve.width, valve.height) == ("control", 60, 32)
    assert valve.description == "Feed Control Valve"
    assert feed.reference == "PFD-100"
    assert valve.label_pos == "bottom"
    assert valve.new_line_number is True


def test_reference_on_equipment_is_refused():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            _spec(units=[{"kind": "Valve", "name": "FV-1", "reference": "PFD-100"}])
        )
    assert "Feed or Product" in str(excinfo.value)


@pytest.mark.parametrize(
    "entry",
    [
        {"kind": "Mixer", "name": "M-1", "n_inlets": 4},
        {"kind": "Splitter", "name": "SP-1", "n_outlets": 3},
        {"kind": "Column", "name": "T-302", "n_feeds": 2},
        {"kind": "Reactor", "name": "R-1"},
        {"kind": "Separator", "name": "V-1", "n_feeds": 2},
        {"kind": "Absorber", "name": "V-501"},
        {"kind": "Stripper", "name": "T-601"},
        {"kind": "Column", "name": "T-101"},
        {"kind": "DistillationColumn", "name": "T-101", "internals": "valve_tray", "trays": 20},
        {"kind": "Absorber", "name": "V-501", "n_feeds": 2, "feed_stages": [1, 8]},
        {"kind": "Column", "name": "T-301", "n_draws": 2},
        {
            "kind": "Column",
            "name": "T-301",
            "internals": "valve_tray",
            "trays": 30,
            "n_feeds": 2,
            "feed_stages": [10, None],
            "n_draws": 2,
            "draw_stages": [None, 22],
        },
    ],
)
def test_a_one_unit_entry_is_written_back_as_it_was_read(entry):
    """Check that a one-unit spec entry is written back unchanged, twice over."""
    written = Flowsheet.from_dict({"name": "T", "units": [entry]}).to_dict()
    assert written["units"] == [entry]
    assert Flowsheet.from_dict(written).to_dict() == written


def test_exchanger_side_nozzles_round_trip():
    """Check that each exchanger variant gets its side nozzles and they round-trip."""
    spec = {
        "name": "T",
        "units": [
            {"kind": "HeatExchanger", "name": "E-1"},
            {"kind": "HeatExchanger", "name": "E-2", "variant": "air_cooled"},
            {"kind": "HeatExchanger", "name": "E-3", "variant": "plate"},
            {"kind": "HeatExchanger", "name": "E-4", "variant": "thin_film"},
            {"kind": "HeatExchanger", "name": "E-5", "variant": "kettle"},
            {"kind": "Heater", "name": "H-1"},
            {"kind": "Cooler", "name": "C-1"},
        ],
        "streams": [
            {"from": ["E-1", "tube_out"], "to": ["E-2", "tube_in"]},
            {"from": ["E-2", "tube_out"], "to": ["E-3", "side_a_in"]},
            {"from": ["E-3", "side_a_out"], "to": ["E-4", "product_in"]},
            {"from": ["E-4", "product_out"], "to": ["E-5", "shell_in"]},
            {"from": ["E-5", "bottoms"], "to": ["H-1", "inlet"]},
            {"from": ["C-1", "utility_out"], "to": ["H-1", "utility_in"]},
        ],
    }
    fs = Flowsheet.from_dict(spec)
    by_name = {u.name: u for u in fs.units}
    assert sorted(by_name["E-1"].ports) == ["shell_in", "shell_out", "tube_in", "tube_out"]
    assert sorted(by_name["E-2"].ports) == ["air_in", "air_out", "tube_in", "tube_out"]
    assert sorted(by_name["E-3"].ports) == [
        "side_a_in",
        "side_a_out",
        "side_b_in",
        "side_b_out",
    ]
    assert sorted(by_name["E-4"].ports) == [
        "jacket_in",
        "jacket_out",
        "product_in",
        "product_out",
    ]
    assert "bottoms" in by_name["E-5"].ports
    written = fs.to_dict()
    assert [(s["from"], s["to"]) for s in written["streams"]] == [
        (s["from"], s["to"]) for s in spec["streams"]
    ]
    assert Flowsheet.from_dict(written).to_dict() == written


def test_a_filters_wash_and_cake_round_trip():
    """Check that a filter press's wash and cake nozzles round-trip with their streams."""
    fs = Flowsheet("dewatering")
    slurry = fs.add(units.Feed("Slurry"))
    wash = fs.add(units.Feed("Wash Water"))
    press = fs.add(units.Filter("F-301", variant="press"))
    filtrate = fs.add(units.Product("Filtrate"))
    solids = fs.add(units.Product("Cake"))
    fs.connect(slurry.outlet, press.port("inlet"))
    fs.connect(wash.outlet, press.port("wash_in"))
    fs.connect(press.port("outlet"), filtrate.inlet)
    fs.connect(press.port("cake"), solids.inlet)

    spec = fs.to_dict()
    assert json.loads(json.dumps(spec)) == spec, "spec must be JSON-safe"
    assert [(s["from"], s["to"]) for s in spec["streams"]] == [
        (["Slurry", "outlet"], ["F-301", "inlet"]),
        (["Wash Water", "outlet"], ["F-301", "wash_in"]),
        (["F-301", "outlet"], ["Filtrate", "inlet"]),
        (["F-301", "cake"], ["Cake", "inlet"]),
    ]

    rebuilt = Flowsheet.from_dict(spec)
    back = next(u for u in rebuilt.units if u.name == "F-301")
    assert sorted(back.ports) == ["cake", "inlet", "outlet", "wash_in"]
    assert back.port("wash_in").stream is not None
    assert back.port("cake").stream is not None
    assert rebuilt.to_dict() == spec
    assert rebuilt.to_svg() == fs.to_svg()


def test_an_absorbers_packing_default_round_trips_silently():
    """Check that an Absorber's packing default is not written and a null one stays null."""
    fs = Flowsheet.from_dict({"name": "T", "units": [{"kind": "Absorber", "name": "V-501"}]})
    assert fs.units[0].internals == "packing"
    written = fs.to_dict()["units"][0]
    assert "internals" not in written
    bare = Flowsheet.from_dict(
        {"name": "T", "units": [{"kind": "Absorber", "name": "V-502", "internals": None}]}
    )
    assert bare.units[0].internals is None
    assert Flowsheet.from_dict(bare.to_dict()).units[0].internals is None


_STAGED_FAMILIES = [("n_feeds", "feed_stages"), ("n_draws", "draw_stages")]


@pytest.mark.parametrize(
    ("count", "stages", "where"),
    [("n_feeds", "feed_stages", [12, 22]), ("n_draws", "draw_stages", [8, 20])],
)
def test_a_columns_stages_round_trip(count, stages, where):
    """Check that a column's feed and draw stages are written and read back."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "Column",
                    "name": "T-101",
                    "internals": "valve_tray",
                    "trays": 30,
                    count: 2,
                    stages: where,
                },
            ],
        }
    )
    assert getattr(fs.units[0], stages) == where
    assert fs.to_dict()["units"][0][stages] == where
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()
    assert Flowsheet.from_dict(fs.to_dict()).to_svg() == fs.to_svg()


@pytest.mark.parametrize(("count", "stages"), _STAGED_FAMILIES)
def test_a_null_stage_round_trips_as_null_not_as_absent(count, stages):
    """Check that a null stage is written as null and read back as null."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "Column",
                    "name": "T-101",
                    "internals": "tray",
                    "trays": 8,
                    count: 2,
                    stages: [3, None],
                },
            ],
        }
    )
    assert fs.to_dict()["units"][0][stages] == [3, None]
    assert getattr(Flowsheet.from_dict(fs.to_dict()).units[0], stages) == [3, None]


@pytest.mark.parametrize(("count", "stages"), _STAGED_FAMILIES)
def test_an_unstated_stage_list_is_not_written_down(count, stages):
    """Check that a family with no stages written writes none."""
    family: dict[str, Any] = {count: 2}
    fs = Flowsheet("T")
    fs.add(units.Column("T-101", **family))
    assert stages not in fs.to_dict()["units"][0]


@pytest.mark.parametrize(("count", "stages"), _STAGED_FAMILIES)
def test_a_stage_list_of_the_wrong_length_is_refused_from_a_spec(count, stages):
    """Check that a stage list longer or shorter than its family is refused."""
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {"name": "T", "units": [{"kind": "Column", "name": "T-1", count: 2, stages: [5]}]}
        )
    assert f"{stages} names 1" in str(excinfo.value)


@pytest.mark.parametrize(
    ("key", "value", "owners"),
    [
        ("feed_stages", [1], "a Column"),
        ("draw_stages", [1], "a Column"),
        ("n_draws", 2, "a Column"),
        ("n_feeds", 2, "a Column or a Reactor or a Separator"),
        ("n_inlets", 3, "a Mixer"),
        ("supports", "skirt", "a Evaporator or a Vessel"),
        ("diameter", 40, "a Conveyor"),
        ("length", 200, "a Conveyor"),
        ("large_end", "outlet", "a Reducer"),
        ("normal_position", "closed", "a Valve or a Fitting"),
        ("header", True, "a Feed or a Product"),
        ("fail", "closed", "a Valve"),
        ("branch", "inlet", "a Tee"),
    ],
)
def test_a_family_key_on_a_kind_with_no_such_family_is_rejected(key, value, owners):
    """Check that a family key on a pump is refused, naming the kinds that take it."""
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict({"name": "T", "units": [{"kind": "Pump", "name": "P-1", key: value}]})
    assert f"only {owners} takes {key!r}, not a Pump" in str(excinfo.value)


@pytest.mark.parametrize("kind", ["Vessel", "Tank"])
def test_a_vessels_relief_and_drain_need_no_key_of_their_own(kind):
    """Check that a vessel's relief and drain round-trip with no key of their own."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {"kind": kind, "name": "V-1", "variant": "sphere" if kind == "Tank" else "dished"},
                {"kind": "Product", "name": "Flare"},
                {"kind": "Product", "name": "Sump"},
            ],
            "streams": [
                {"from": ["V-1", "relief"], "to": ["Flare", "inlet"]},
                {"from": ["V-1", "drain"], "to": ["Sump", "inlet"]},
            ],
        }
    )
    written = {u["name"]: u for u in fs.to_dict()["units"]}["V-1"]
    assert set(written) == {"kind", "name", "variant"}
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


# --- composition: what a body carries -----------------------------------------


def _drawn(unit):
    """Return the overlays drawn on a unit as (group, name, mirror), in order."""
    from pandid.render.symbols import default_registry

    return [(o.group, o.name, o.mirror) for o in default_registry.for_unit(unit).overlays]


def _artwork(unit):
    """Return the composed SVG of a unit's symbol."""
    from pandid.render.symbols import default_registry

    return default_registry.for_unit(unit).svg


def _round_trip(unit):
    """Write one unit through ``to_dict``, read it back, and return its entry and the unit."""
    fs = Flowsheet("T")
    fs.add(unit)
    spec = fs.to_dict()
    assert json.loads(json.dumps(spec)) == spec, "spec must be JSON-safe"
    return spec["units"][0], Flowsheet.from_dict(spec).units[0]


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda: units.Vessel("D-301", supports="skirt"), {"supports": "skirt"}),
        (lambda: units.Vessel("D-302", supports="bracket"), {"supports": "bracket"}),
        (lambda: units.Reactor("R-101", agitator="anchor"), {"agitator": "anchor"}),
        (
            lambda: units.Reactor("R-201", internals="packing"),
            {"internals": "packing"},
        ),
        (
            lambda: units.Column("T-101", internals="valve_tray", trays=30),
            {"internals": "valve_tray", "trays": 30},
        ),
        (
            lambda: units.Separator("V-201", characteristic="gravity"),
            {"characteristic": "gravity"},
        ),
    ],
)
def test_every_composition_keyword_round_trips(make, expected):
    """Check that each composition keyword is written under its own name and read back."""
    unit = make()
    entry, rebuilt = _round_trip(unit)
    assert {key: value for key, value in entry.items() if key not in ("kind", "name")} == expected
    assert _drawn(rebuilt) == _drawn(unit)
    assert _artwork(rebuilt) == _artwork(unit)


def test_a_body_carrying_two_parts_keeps_both_and_their_order():
    """Check that a reactor's bed and stirrer round-trip in drawing order."""
    unit = units.Reactor("R-301", internals="fluidised_bed", agitator="turbine")
    entry, rebuilt = _round_trip(unit)
    assert (entry["internals"], entry["agitator"]) == ("fluidised_bed", "turbine")
    assert _drawn(unit) == [
        (27, "fluidised_bed", False),
        (28, "turbine", False),
        (20, "motor", False),
    ]
    assert _drawn(rebuilt) == _drawn(unit)
    assert _artwork(rebuilt) == _artwork(unit)


@pytest.mark.parametrize(
    "make",
    [
        lambda: units.Pump("P-101"),  # a kind that cannot compose at all
        lambda: units.Vessel("D-101"),  # one that can, and was not asked to
        lambda: units.Separator("V-101"),
        lambda: units.Tank("TK-101"),
        # ISO item 2.1 X8100: the general column carries no internal.
        lambda: units.Column("T-101"),
    ],
)
def test_a_unit_that_composes_nothing_gains_nothing(make):
    """Check that a unit with no composed part writes and draws none after a round trip."""
    unit = make()
    entry, rebuilt = _round_trip(unit)
    assert set(entry) == {"kind", "name"}
    assert _drawn(unit) == []
    assert _drawn(rebuilt) == []


@pytest.mark.parametrize(
    ("make", "drawn"),
    [
        (lambda: units.Reactor("R-101"), {(28, "agitator"), (20, "motor")}),
    ],
)
def test_the_part_a_class_draws_by_itself_is_not_written_down(make, drawn):
    """Check that a reactor's default agitator and motor are drawn but not written."""
    unit = make()
    entry, rebuilt = _round_trip(unit)
    assert set(entry) == {"kind", "name"}
    assert {(group, name) for group, name, _ in _drawn(unit)} == drawn
    assert _drawn(rebuilt) == _drawn(unit)


@pytest.mark.parametrize(
    ("make", "key"),
    [
        (lambda: units.Reactor("R-105", agitator=None), "agitator"),
    ],
)
def test_a_body_asked_for_bare_comes_back_bare(make, key):
    """Check that a part set to None is written as null and draws nothing after a round trip."""
    unit = make()
    entry, rebuilt = _round_trip(unit)
    assert entry[key] is None
    assert _drawn(unit) == []
    assert _drawn(rebuilt) == []


def test_composition_keywords_read_from_a_hand_written_spec():
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {"kind": "Column", "name": "T-101", "internals": "bubble_cap_tray", "trays": 12},
                {"kind": "Vessel", "name": "D-301", "supports": "leg"},
                {"kind": "Reactor", "name": "R-201", "internals": "packing", "agitator": None},
            ],
        }
    )
    column, vessel, reactor = fs.units
    assert (column.internals, column.trays) == ("bubble_cap_tray", 12)
    assert vessel.supports == "leg"
    assert (reactor.internals, reactor.agitator) == ("packing", None)
    assert _drawn(column) == [(27, "bubble_cap_tray", False)] * 12
    assert _drawn(vessel) == [(26, "leg", False), (26, "leg", False)]


def test_a_part_no_such_group_has_names_the_ones_it_does():
    """Check that a misspelt agitator is refused on read, naming the part meant."""
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {"name": "T", "units": [{"kind": "Reactor", "name": "R-1", "agitator": "turbin"}]}
        )
    assert "turbine" in str(excinfo.value)


def test_a_part_that_is_not_a_name_is_told_how_to_ask_for_none():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {"name": "T", "units": [{"kind": "Vessel", "name": "V-1", "supports": 3}]}
        )
    assert "must be the name of a part, or null for none at all" in str(excinfo.value)


def test_a_tray_count_that_is_not_a_number_is_refused():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {"name": "T", "units": [{"kind": "Column", "name": "T-1", "trays": "twelve"}]}
        )
    assert "must be a whole number" in str(excinfo.value)


def test_no_constructor_argument_is_unreachable_from_a_spec():
    """Check that every non-Instrument constructor argument but ``actuator`` is a spec key."""
    import inspect

    from pandid import spec as spec_module

    known = set(spec_module._UNIT_KEYS) | set(spec_module._KIND_KEYS) | {"actuator"}
    for name, cls in spec_module._CLASSES.items():
        if name == "Instrument":
            continue
        for argument in inspect.signature(cls.__init__).parameters:
            if argument == "self":
                continue
            assert argument in known, f"{name}({argument}=...) can be neither written nor read"


def test_no_class_leaves_a_variant_dependent_default_unresolved():
    """Check that no class's ``composition_defaults`` holds the ``_UNSTATED`` sentinel."""
    from pandid import spec as spec_module
    from pandid.render.symbols import default_registry
    from pandid.units import _UNSTATED

    for cls in spec_module._CLASSES.values():
        for variant in default_registry.variants(cls.kind) or ["default"]:
            assert _UNSTATED not in cls.composition_defaults(variant).values()


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
    # ``inlet`` is stored under its canonical name ``in_1``.
    assert fs.units[0]._port_faces == {"in_1": "N"}


def test_a_tanks_face_list_round_trips_through_a_spec():
    """Check that a tank's input face list round-trips and its default outlet is not written."""
    from pandid.spec import from_dict, to_dict

    fs = Flowsheet("tanks")
    tk = fs.add(units.Tank("TK-1", inputs=["W", "W", "N"]))
    feed = fs.add(units.Feed("F"))
    prod = fs.add(units.Product("P"))
    fs.connect(feed.outlet, tk.port("in_2"))
    fs.connect(tk.outlet, prod.inlet)

    spec = to_dict(fs)
    (entry,) = [u for u in spec["units"] if u["kind"] == "Tank"]
    assert entry["inputs"] == ["W", "W", "N"]
    assert "outputs" not in entry

    read = from_dict(spec)
    (got,) = [u for u in read.units if isinstance(u, units.Tank)]
    assert got.input_faces == tk.input_faces == ("W", "W", "N")
    assert got.output_faces == tk.output_faces
    assert list(got.ports) == list(tk.ports)
    assert to_dict(read) == spec


def test_a_vessels_moved_nozzle_and_reordered_face_round_trip():
    """Check that a vessel's ``nozzle()`` moves and ``order_on()`` order round-trip."""
    from pandid.spec import from_dict, to_dict

    fs = Flowsheet("vessels")
    v = fs.add(units.Vessel("V-1", variant="horizontal", inputs=("W", "E"), width=130, height=42))
    v.nozzle("in_1", "N")
    v.nozzle("in_2", "N")
    v.order_on("N", [v.in_2, v.in_1])

    spec = to_dict(fs)
    (entry,) = [u for u in spec["units"] if u["kind"] == "Vessel"]
    assert entry["inputs"] == ["N", "N"]
    assert entry["port_order"] == {"N": ["in_2", "in_1"]}

    read = from_dict(spec)
    (got,) = [u for u in read.units if isinstance(u, units.Vessel)]
    assert got.input_faces == v.input_faces == ("N", "N")
    assert (
        [p.name for p in got.ports_on("N")]
        == [p.name for p in v.ports_on("N")]
        == [
            "in_2",
            "in_1",
        ]
    )
    assert to_dict(read) == spec


def test_components_accept_a_bare_name_or_a_formula():
    fs = Flowsheet.from_dict(
        {"name": "T", "components": ["Nitrogen", {"name": "Water", "formula": "H2O"}]}
    )
    assert [(c.name, c.formula) for c in fs.components] == [("Nitrogen", None), ("Water", "H2O")]


def test_flowsheet_level_options():
    fs = Flowsheet.from_dict({"name": "T", "stream_naming_scheme": "L-{n}"})
    assert fs.stream_naming_scheme == "L-{n}"
    assert fs.auto_faces is True


def test_a_valve_station_tag_scheme_survives_a_round_trip():
    """Check that ``valve_station_tag_scheme`` is read, written, and left out when unset."""
    fs = Flowsheet("T", valve_station_tag_scheme="{letters}{number}{suffix}")
    spec = fs.to_dict()
    assert spec["valve_station_tag_scheme"] == "{letters}{number}{suffix}"
    back = Flowsheet.from_dict(spec)
    assert back.valve_station_tag_scheme == "{letters}{number}{suffix}"
    bypass = back.add_valve_station("CV-303").bypass
    assert bypass is not None and bypass.name == "HV303C"
    assert "valve_station_tag_scheme" not in Flowsheet("T").to_dict()


def test_a_callable_valve_station_tag_scheme_cannot_be_written_out():
    fs = Flowsheet("T", valve_station_tag_scheme=lambda role, control: f"{control}/{role}")
    with pytest.raises(SpecError, match="callable valve_station_tag_scheme"):
        fs.to_dict()


def test_auto_faces_off_survives_a_round_trip():
    """Check that ``auto_faces: false`` round-trips and the default writes nothing."""
    fs = Flowsheet.from_dict({"name": "T", "auto_faces": False})
    assert fs.auto_faces is False
    assert fs.to_dict()["auto_faces"] is False
    assert "auto_faces" not in Flowsheet("T").to_dict()


def test_retired_direction_key_is_refused():
    """Check that the retired ``direction`` key is refused with a message saying so."""
    with pytest.raises(SpecError) as e:
        Flowsheet.from_dict(_spec(direction="TB"))
    assert "'direction' is no longer part of the spec" in str(e.value)
    assert "left to right" in str(e.value)


# --- connections --------------------------------------------------------------


def test_stream_fields():
    fs = Flowsheet.from_dict(
        _spec(
            streams=[
                {
                    "from": ["F", "outlet"],
                    "to": ["P-101", "suction"],
                    "name": "100-BFW-01",
                    "draw_as_recycle": True,
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
    assert stream.draw_as_recycle is True
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
                    "display": "central",
                    "sensing": "P-101",
                    "face": "S",
                    "offset": 90,
                    "angle": 35,
                    "port_faces": {"sig_out": "W"},
                }
            ]
        )
    )
    inst = fs.units[-1]
    assert inst.name == "LIC-101"
    assert (inst.type, inst.number) == ("LIC", "101")
    # The two axes the entry states, and the one variant they resolve to.
    assert (inst.symbol_type, inst.display, inst.variant) == ("default", "central", "panel")
    assert (inst.host.name, inst.relation) == ("P-101", "sensing")
    assert (inst.face, inst.offset, inst.angle) == ("S", 90.0, 35.0)
    assert inst._port_faces == {"sig_out": "W"}


#: The units of :func:`_spec`, and a tagged element to hang a balloon from.
_WITH_ELEMENT = [
    {"kind": "Feed", "name": "F"},
    {"kind": "Pump", "name": "P-101"},
    {"kind": "Product", "name": "P"},
    {"kind": "Fitting", "name": "FE-303", "variant": "venturi"},
]


def test_a_side_is_read_and_written_as_face_and_a_fraction_as_at():
    fs = Flowsheet.from_dict(
        _spec(
            instruments=[
                {"type": "LT", "number": 101, "sensing": "P-101", "face": "S"},
                {"type": "FT", "number": 101, "sensing": ["F", "outlet"], "at": 0.4},
            ]
        )
    )
    lt, ft = fs.units[-2:]
    assert (lt.at, lt.face, ft.at, ft.face) == (None, "S", 0.4, None)
    written = fs.to_dict()["instruments"]
    assert [sorted({"at", "face"} & set(entry)) for entry in written] == [["face"], ["at"]]
    assert (written[0]["face"], written[1]["at"]) == ("S", 0.4)
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_a_balloons_side_is_written_as_face():
    fs = Flowsheet("balloon")
    fe = fs.add(units.Fitting("FE-303", variant="venturi"))
    fs.add_balloon(fe, face="S")
    entry = fs.to_dict()["instruments"][0]
    assert (entry["face"], "at" in entry) == ("S", False)
    back = Flowsheet.from_dict(fs.to_dict()).units[-1]
    assert (back.at, back.face) == (None, "S")


@pytest.mark.parametrize(
    "entry",
    [
        {"type": "LT", "number": 101, "sensing": "P-101", "at": "S"},
        {"balloon_of": "FE-303", "at": "S"},
    ],
    ids=["instrument", "balloon"],
)
def test_a_side_given_as_at_still_loads_and_is_reported(entry):
    spec = _spec(units=_WITH_ELEMENT, instruments=[entry])
    with pytest.warns(DeprecationWarning, match="use face='S'"):
        fs = Flowsheet.from_dict(spec)
    inst = fs.units[-1]
    assert (inst.at, inst.face) == (None, "S")
    found = [i.message for i in fs.validate() if i.code == "deprecated"]
    assert len(found) == 1 and found[0].startswith(f"{inst.name}: ")
    assert fs.to_dict()["instruments"][0]["face"] == "S"


def test_a_balloon_entry_refused_after_its_old_face_warns_nothing():
    """Check that a balloon entry refused after its deprecated ``at`` side warns nothing."""
    entry = {"balloon_of": "FE-303", "at": "S", "port_faces": {"missing": "N"}}
    spec = _spec(units=_WITH_ELEMENT, instruments=[entry])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(SpecError, match="missing"):
            Flowsheet.from_dict(spec)
    assert caught == []


@pytest.mark.parametrize(
    "entry, match",
    [
        (
            {"type": "LT", "number": 101, "sensing": "P-101", "at": "S", "face": "S"},
            "give face= alone",
        ),
        (
            {"type": "FT", "number": 101, "sensing": ["F", "outlet"], "at": 0.4, "face": "S"},
            "give at= alone",
        ),
        ({"type": "FT", "number": 101, "sensing": ["F", "outlet"], "face": "S"}, "give at="),
        ({"balloon_of": "FE-303", "at": "S", "face": "S"}, "give face= alone"),
        ({"type": "LT", "number": 101, "face": "S"}, r"\['face'\] only mean something"),
    ],
    ids=["both on a unit", "both on a line", "face on a line", "both on a balloon", "no host"],
)
def test_a_side_the_spec_cannot_honour_is_refused(entry, match):
    spec = _spec(units=_WITH_ELEMENT, instruments=[entry])
    with pytest.raises(SpecError, match=match):
        Flowsheet.from_dict(spec)


def test_instrument_tapping_a_line_by_the_port_it_leaves():
    fs = Flowsheet.from_dict(
        _spec(
            instruments=[
                {"type": "FE", "number": 101, "sensing": ["F", "outlet"], "at": 0.4, "offset": 0}
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
            instruments=[{"type": "FT", "number": 101, "sensing": "100-P-01"}],
        )
    )
    assert fs.units[-1].host is fs.streams[0]


def test_unattached_instrument_is_laid_out_like_any_unit():
    fs = Flowsheet.from_dict(_spec(instruments=[{"type": "PI", "number": 7}]))
    assert fs.units[-1].host is None


@pytest.mark.parametrize("relation", ["sensing", "acting_on", "near"])
def test_each_relation_is_read_back_and_written_out_again(relation):
    """Check that each anchor relation is read, written back, and round-trips."""
    entry = {"type": "I", "number": 1, "variant": "sis", relation: "P-101", "face": "S"}
    fs = Flowsheet.from_dict(_spec(instruments=[entry]))
    assert (fs.units[-1].host.name, fs.units[-1].relation) == ("P-101", relation)
    assert fs.to_dict()["instruments"][0][relation] == "P-101"
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_a_sheet_using_the_whole_instrument_vocabulary_round_trips():
    """Check that relations, display, quadrants and an element's balloon tag round-trip."""
    fs = Flowsheet("vocabulary")
    feed = fs.add(units.Feed("Feed")).pin(x=60, y=170)
    fe = fs.add(units.Fitting("FE-303", variant="venturi")).pin(x=300, port="inlet", y=195)
    prod = fs.add(units.Product("Product")).pin(x=620, y=170)
    fs.connect(feed.outlet, fe.inlet)
    fs.connect(fe.outlet, prod.inlet)
    balloon = fs.add_balloon(fe, face="N", offset=38)
    ft = fs.add_instrument("FT", 303, near=balloon, face="N", offset=23)
    fic = fs.add_instrument("FIC", 303, near=ft, face="E", offset=70, display="central")
    fic.annotate(high=("FAHH", "FSHH"), low="FAL", safety="SIL 2")

    spec = fs.to_dict()
    assert json.loads(json.dumps(spec)) == spec, "spec must be JSON-safe"
    rebuilt = Flowsheet.from_dict(spec)
    assert rebuilt.to_dict() == spec

    def by_name(sheet, name):
        return next(u for u in sheet.units if u.name == name)

    element = by_name(rebuilt, "FE-303")
    assert element.tag == "", "the tag moved to the balloon and stayed there"
    assert element.balloon is by_name(rebuilt, "FE-303 (2)")
    assert (element.balloon.tag, element.balloon.relation) == ("FE-303", "sensing")
    assert by_name(rebuilt, "FT-303").relation == "near"
    controller = by_name(rebuilt, "FIC-303")
    assert (controller.relation, controller.display, controller.variant) == (
        "near",
        "central",
        "panel",
    )
    assert controller.quadrants["a"] == ("SIL 2",)
    assert controller.quadrants["c"] == ("FAHH", "FSHH")
    assert controller.quadrants["d"] == ("FAL",)


def test_a_balloons_placement_reaches_the_file_and_comes_back():
    """Check that a balloon's pin and port faces are written and read back onto it."""
    fs = Flowsheet("placed")
    fe = fs.add(units.Fitting("FE-303", variant="venturi")).pin(x=300, y=195)
    balloon = fs.add_balloon(fe, face="S")
    balloon.pin(x=300, y=320)
    balloon.nozzle("pv", "N")

    entry = fs.to_dict()["instruments"][0]
    assert entry["pin"] == {"x": 300, "y": 320}, "the balloon's pin is not in the file"
    assert entry["port_faces"] == {"pv": "N"}

    rebuilt = Flowsheet.from_dict(fs.to_dict())
    back = next(u for u in rebuilt.units if u.name == balloon.name)
    assert back.pin_ == balloon.pin_, "the balloon came back somewhere else"
    assert back._port_faces == balloon._port_faces, "the impulse line comes off another face"


def test_a_balloon_carrying_every_field_it_takes_round_trips():
    """Check that every field ``add_balloon`` accepts survives a round trip."""
    fs = Flowsheet("vocabulary")
    fe = fs.add(units.Fitting("FE-303", variant="venturi")).pin(x=300, y=195)
    balloon = fs.add_balloon(
        fe,
        face="N",
        offset=38,
        angle=75,
        variant="shared",
        display="central",
        description="Venturi meter",
        width=44,
        height=44,
        label_pos="E",
    )
    balloon.annotate(safety="SIL 2", variable="pH", high="FAH", low="FAL")
    balloon.new_line_number = True
    balloon.pin(x=300, y=90)

    spec = fs.to_dict()
    rebuilt = Flowsheet.from_dict(spec)
    assert rebuilt.to_dict() == spec
    back = next(u for u in rebuilt.units if u.name == balloon.name)
    for field in (
        "description",
        "width",
        "height",
        "label_pos",
        "new_line_number",
        "symbol_type",
        "display",
        "at",
        "offset",
        "angle",
        "quadrants",
        "pin_",
        "relation",
        "tag",
    ):
        assert getattr(back, field) == getattr(balloon, field), f"{field} was lost"


def test_an_instruments_new_line_number_is_read_back():
    """Check that an instrument's ``new_line_number`` is read and round-trips."""
    fs = Flowsheet.from_dict(
        _spec(instruments=[{"type": "PI", "number": 7, "new_line_number": True}])
    )
    assert fs.units[-1].new_line_number is True
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_an_entry_naming_two_anchors_is_refused():
    """Check that an entry naming two anchors is refused, naming both keywords."""
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            _spec(instruments=[{"type": "FT", "number": 101, "sensing": "P-101", "near": "F"}])
        )
    message = str(excinfo.value)
    assert "named 2" in message
    assert "'sensing'" in message and "'near'" in message


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


def test_table_cells_and_legend_entries_read_as_the_text_drawn():
    """Check that null cells read as blank and numbers as their text in every box."""
    fs = Flowsheet.from_dict(
        _spec(
            annotations=[
                {"type": "table", "rows": [["TI-1", None, 101]]},
                {"type": "legend", "entries": {"SS": None, 1: 2.5}},
                {"type": "legend", "entries": [["SS", None], [3, 4]]},
                {"type": "annotation", "rows": [["TI-1", None, 101]]},
            ]
        )
    )
    table, by_mapping, by_list, note_box = fs.annotations
    assert table.rows == [["TI-1", "", "101"]]
    assert by_mapping.rows == [("SS", ""), ("1", "2.5")]
    assert by_list.rows == [("SS", ""), ("3", "4")]
    assert note_box.rows == [("TI-1", "", "101")]


def test_a_null_cell_draws_blank_from_python_and_through_a_spec():
    """Check that a ``None`` cell draws blank from Python and through a spec."""
    fs = Flowsheet("T")
    fs.annotations += [TableBox(rows=[["Insulation", None]]), legend([("SS", None)])]
    svg = fs.to_svg()
    assert ">None<" not in svg
    assert 'value="None"' not in fs.to_drawio()
    assert Flowsheet.from_dict(fs.to_dict()).to_svg() == svg


@pytest.mark.parametrize("entry", [["SS"], ["SS", "316L", "extra"]])
def test_a_legend_entry_must_pair_an_abbreviation_with_its_meaning(entry):
    with pytest.raises(SpecError, match=r"annotations\[0\]\.entries\[0\].*two items"):
        Flowsheet.from_dict(_spec(annotations=[{"type": "legend", "entries": [entry]}]))


def test_stream_table_sections():
    fs = Flowsheet.from_dict(_spec(stream_table_sections=[["Benzene", "Mass Fraction"]]))
    assert fs.stream_table_sections == [("Benzene", "Mass Fraction")]


def test_stream_table_options_round_trip():
    fs = Flowsheet.from_dict(_spec(stream_table={"font_size": 8}))
    assert fs.stream_table.font_size == 8
    assert fs.to_dict()["stream_table"] == {"font_size": 8}


def test_a_table_left_alone_writes_no_section():
    """Check that a sheet with default table options writes no ``stream_table``."""
    assert "stream_table" not in Flowsheet.from_dict(_spec()).to_dict()


def test_a_stream_table_key_that_is_not_one_is_named():
    with pytest.raises(SpecError, match="font_sixe"):
        Flowsheet.from_dict(_spec(stream_table={"font_sixe": 8}))


def test_a_stream_table_value_of_the_wrong_kind_is_refused():
    with pytest.raises(SpecError, match="must be a number"):
        Flowsheet.from_dict(_spec(stream_table={"font_size": "8"}))


def test_the_column_widths_round_trip():
    table = {"label_width": 90, "column_width": "auto"}
    fs = Flowsheet.from_dict(_spec(stream_table=table))
    assert (fs.stream_table.label_width, fs.stream_table.column_width) == (90, "auto")
    assert fs.to_dict()["stream_table"] == table


@pytest.mark.parametrize("value", ["fit", None, True, [52]])
def test_a_column_width_that_is_neither_a_number_nor_auto_is_refused(value):
    """Check that a column width other than a number or ``"auto"``, null included, is refused."""
    with pytest.raises(SpecError, match='must be a number or "auto"'):
        Flowsheet.from_dict(_spec(stream_table={"column_width": value}))


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
    """Check that YAML reads ``N`` as text and a bare date as a string."""
    path = tmp_path / "fs.yaml"
    path.write_text(
        "name: T\n"
        "units: [{kind: Vessel, name: V-1}]\n"
        "instruments:\n"
        "  - type: LIC\n"
        "    number: 101\n"
        "    sensing: V-1\n"
        "    face: N\n"
        "title_block: {revisions: [{rev: A, date: 2026-05-18}]}\n",
        encoding="utf-8",
    )
    fs = Flowsheet.from_yaml(path)
    assert fs.units[-1].host is fs.units[0]
    assert fs.units[-1].face == "N"
    assert fs.title_block.revisions[0].date == "2026-05-18"


@pytest.mark.skipif(not _HAS_YAML, reason="PyYAML is an optional extra")
def test_yaml_reads_a_leading_zero_or_a_colon_as_written(tmp_path):
    """Check that YAML reads ``0101``, ``1:30`` and kin as text and decimals as numbers."""
    path = tmp_path / "fs.yaml"
    path.write_text(
        "name: T\n"
        "units:\n"
        "  - {kind: Vessel, name: V-1, pin: {x: 60.5, y: 1e3}}\n"
        "  - {kind: Vessel, name: V-2}\n"
        "instruments: [{type: FT, number: 0101, sensing: V-1}]\n"
        "streams:\n"
        "  - {from: [V-1, outlet], to: [V-2, inlet], sequence: 0010, size: 1:30,\n"
        "     spec: 1_000, service: 0x1F, schedule: 0o17}\n",
        encoding="utf-8",
    )
    fs = Flowsheet.from_yaml(path)
    assert fs.units[-1].name == "FT-0101"
    stream = fs.streams[0]
    assert (stream.sequence, stream.size) == ("0010", "1:30")
    assert (stream.spec, stream.service, stream.schedule) == ("1_000", "0x1F", "0o17")
    pin = fs.units[0].pin_
    assert pin is not None and (pin.x, pin.y) == (60.5, 1000.0)


def test_a_key_written_twice_in_json_is_refused(tmp_path):
    """Check that a key written twice in JSON is refused."""
    path = tmp_path / "fs.json"
    path.write_text(
        '{"name": "T", "units": [{"kind": "Pump", "name": "P-1", "name": "P-2"}]}',
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match="'name' is written twice"):
        Flowsheet.from_json(path)


@pytest.mark.skipif(not _HAS_YAML, reason="PyYAML is an optional extra")
def test_a_key_written_twice_in_yaml_is_refused(tmp_path):
    """Check that a key written twice in YAML is refused, merge sources included."""
    path = tmp_path / "fs.yaml"
    path.write_text(
        "name: T\nunits:\n  - kind: Pump\n    name: P-1\n    name: P-2\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match=r"'name' is written twice.*line 5"):
        Flowsheet.from_yaml(path)
    # Also in a mapping used only as a ``<<`` merge source.
    path.write_text(
        "name: T\nunits: [{<<: {kind: Pump, name: P-1, name: P-2}}]\n", encoding="utf-8"
    )
    with pytest.raises(SpecError, match="'name' is written twice"):
        Flowsheet.from_yaml(path)
    # A key a merge brings in may be overridden, even in a merge source.
    path.write_text(
        "name: T\nunits:\n  - &m {<<: {kind: Pump, name: X}, name: P-1}\n  - {<<: *m, name: P-2}\n",
        encoding="utf-8",
    )
    assert [u.name for u in Flowsheet.from_yaml(path).units] == ["P-1", "P-2"]


def test_from_yaml_without_pyyaml_says_exactly_what_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)  # makes `import yaml` fail
    path = tmp_path / "fs.yaml"
    path.write_text("name: T\n", encoding="utf-8")
    with pytest.raises(ImportError) as excinfo:
        Flowsheet.from_yaml(path)
    message = str(excinfo.value)
    assert "PyYAML" in message
    assert "pip install 'pandid[yaml]'" in message
    assert "from_json" in message


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


@pytest.mark.parametrize("name", ["liquid", "vapour"])
def test_a_spec_file_naming_a_removed_port_is_refused(name):
    """Check that a removed cyclone port name is refused, listing the ports it has."""
    spec = {
        "name": "an 0.1.1 file",
        "units": [
            {"kind": "Separator", "name": "CY-401", "variant": "cyclone"},
            {"kind": "Product", "name": "Dust"},
        ],
        "streams": [{"from": ["CY-401", name], "to": ["Dust", "inlet"]}],
    }
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(spec)
    message = str(excinfo.value)
    assert f"has no port {name!r}" in message
    assert "available ports: ['feed_1', 'overflow', 'underflow']" in message


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
            _spec(streams=[{"from": ["F", "outlet"], "to": ["P-101", "suction"], "recycle": True}]),
            "streams[0]",
            "'recycle'",
            "'draw_as_recycle'",
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


def test_instruments_are_not_declared_as_units():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict({"name": "T", "units": [{"kind": "Instrument", "name": "FT-101"}]})
    message = str(excinfo.value)
    assert "instruments go in the top-level 'instruments:' section" in message
    assert "on/at/offset/angle" in message


def test_attachment_arguments_need_a_host():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(instruments=[{"type": "FT", "number": 101, "at": 0.5}]))
    assert (
        "['at'] only mean something with one of 'sensing', 'acting_on', 'near': "
        "the stream or unit the balloon is placed against"
    ) in str(excinfo.value)


def test_unknown_attachment_host():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(instruments=[{"type": "FT", "number": 101, "sensing": "P-1O1"}]))
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
    """Check that piping a pump nozzle twice is reported against the second stream."""
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            _spec(
                streams=[
                    {"from": ["F", "outlet"], "to": ["P-101", "suction"]},
                    {"from": ["F", "outlet"], "to": ["P-101", "suction"]},
                ]
            )
        )
    message = str(excinfo.value)
    assert "streams[1]" in message
    assert "P-101.suction is already connected" in message


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


def test_bad_col_align_is_reported_with_the_valid_ones():
    """Check that a spelled-out ``col_align`` word is refused in Python and in a spec."""
    with pytest.raises(ValueError, match=r"col_align\[0\] must be one of"):
        TableBox(headers=["A", "B"], rows=[["1", "2"]], col_align=["left", "r"])
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            _spec(
                annotations=[
                    {
                        "type": "table",
                        "headers": ["A"],
                        "rows": [["1"]],
                        "col_align": ["left"],
                    }
                ]
            )
        )
    assert "col_align[0] must be one of" in str(excinfo.value)


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


def _two_vessels(**stream):
    return {
        "name": "T",
        "units": [{"name": "V-1", "kind": "vessel"}, {"name": "V-2", "kind": "vessel"}],
        "streams": [{"from": ["V-1", "outlet"], "to": ["V-2", "inlet"], **stream}],
    }


def test_a_streams_joints_survive_a_round_trip():
    """Check that a stream's ``ends`` round-trips and an unset one writes nothing."""
    fs = Flowsheet.from_dict(_two_vessels(ends="flanged"))
    assert fs.streams[0].ends == "flanged"
    assert fs.to_dict()["streams"][0]["ends"] == "flanged"
    assert "ends" not in Flowsheet.from_dict(_two_vessels()).to_dict()["streams"][0]


def test_two_joints_stated_apart_survive_a_round_trip_in_order():
    fs = Flowsheet.from_dict(_two_vessels(ends=["flanged", "none"]))
    assert fs.streams[0].ends == ("flanged", "none")
    assert fs.to_dict()["streams"][0]["ends"] == ["flanged", "none"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("welded", "flanged"),  # a joint with no mark in this package
        (["flanged", "none", "flanged"], "two-item"),  # a stream has two ends
        (5, "two-item"),
    ],
)
def test_a_joint_the_package_cannot_draw_is_refused_with_the_ones_it_can(value, expected):
    with pytest.raises((SpecError, ValueError)) as e:
        Flowsheet.from_dict(_two_vessels(ends=value))
    assert expected in str(e.value)


def test_an_ion_exchangers_regenerant_round_trips():
    """Check that an ion exchanger's regenerant nozzles round-trip with their streams."""
    fs = Flowsheet("demin")
    regen = fs.add(units.Feed("Caustic"))
    ix = fs.add(units.Filter("F-802", variant="ion_exchange"))
    waste = fs.add(units.Product("To Neutralisation"))
    fs.connect(regen.outlet, ix.port("regenerant_in"))
    fs.connect(ix.port("spent_regenerant"), waste.inlet)

    spec = fs.to_dict()
    rebuilt = Flowsheet.from_dict(spec)
    back = next(u for u in rebuilt.units if u.name == "F-802")
    assert sorted(back.ports) == [
        "inlet",
        "outlet",
        "regenerant_in",
        "spent_regenerant",
    ]
    assert back.port("regenerant_in").stream is not None
    assert back.port("spent_regenerant").stream is not None
    assert rebuilt.to_dict() == spec
