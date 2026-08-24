"""The declarative spec format: round-tripping, feature coverage, and the
quality of the errors a hand-written file gets back.

The error tests assert on the *message*, not just the type. Whoever writes one
of these files is a process engineer with a typo, not a programmer with a
traceback, so "unknown key 'varient'" that goes on to name the real key is the
feature. A bare ValueError is a bug report waiting to happen.
"""

import json
import sys
import warnings

import pytest

# The round-trip corpus is the golden scenarios: the same seven flowsheets the
# examples draw, already built here once. Re-typing them would only let the two
# copies drift.
from test_golden import SCENARIOS

from pandid import Flowsheet, units
from pandid.document import Annotation, TableBox
from pandid.spec import SpecError

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
    fs.add(units.Pump("P-1")).pin(x=60, y=105)
    assert fs.to_dict()["units"][0]["pin"] == {"x": 60, "y": 105}


def test_a_flag_comes_back_where_it_was_pinned():
    """A written pin is a corner, including a flag's, so reading it back must not
    take it for the nozzle ``pin(x=...)`` places there and shift it again."""
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
    # An off-page reference belongs to the sheet boundary, and a valve is not
    # one: honouring the key on equipment would draw nothing.
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            _spec(units=[{"kind": "Valve", "name": "FV-1", "reference": "PFD-100"}])
        )
    assert "Feed or Product" in str(excinfo.value)


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


def test_exchanger_side_nozzles_round_trip():
    """An exchanger's nozzles are named for its sides, and the sides depend on
    the variant, so the reader has to build the right four before it can resolve
    a connection to them, and the writer has to name them back."""
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
    """The nozzles a filter has depend on its variant, exactly as an
    exchanger's do -- and per-variant ports are a different axis from the
    composition keywords the spec learned in 0.1.3.

    Nothing writes a port list: what carries these four across is ``variant``,
    which is written because it is not ``default``, and the constructor laying
    the table down again on the way back. The trip is made from a built sheet
    rather than from a hand-written spec so the *writer* is under test too; a
    dropped variant would read back as a two-nozzle bag filter and take the wash
    and the cake with it.
    """
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
    # Both new ones came back carrying a stream, not merely existing.
    assert back.port("wash_in").stream is not None
    assert back.port("cake").stream is not None
    assert rebuilt.to_dict() == spec
    assert rebuilt.to_svg() == fs.to_svg()


def test_an_ion_exchangers_regenerant_round_trips():
    """The variant that is its own case has to survive the trip under its own
    two names. Reading it back as a filter press would offer ``wash_in`` and
    silently lose the line.
    """
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


def test_a_column_or_reactor_feed_count_round_trips():
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {"kind": "Column", "name": "T-302", "n_feeds": 2},
                {"kind": "Reactor", "name": "R-1"},
            ],
        }
    )
    assert {"feed_1", "feed_2"} <= set(fs.units[0].ports)
    assert "feed_1" in fs.units[1].ports
    assert fs.units[1].feed is fs.units[1].feed_1
    written = {u["name"]: u for u in fs.to_dict()["units"]}
    assert written["T-302"]["n_feeds"] == 2
    # One feed is the class's own shape, so the count is not written down.
    assert "n_feeds" not in written["R-1"]


def test_absorber_and_stripper_kind_round_trips():
    """``kind: Absorber``/``Stripper`` is a fact about which nozzles the
    drawing has, and it is the class name -- not ``Column`` plus a variant
    -- that carries it, so it has to survive the trip unchanged."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {"kind": "Absorber", "name": "V-501"},
                {"kind": "Stripper", "name": "T-601"},
            ],
        }
    )
    assert set(fs.units[0].ports) == {"feed_1", "overhead", "bottoms"}
    assert type(fs.units[0]).__name__ == "Absorber"
    assert type(fs.units[1]).__name__ == "Stripper"
    written = {u["name"]: u for u in fs.to_dict()["units"]}
    assert written["V-501"]["kind"] == "Absorber"
    assert written["T-601"]["kind"] == "Stripper"
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_a_bare_column_kind_still_loads_as_the_general_tower():
    """#400: four classes now share ``kind == "column"`` and a bare
    ``kind: column`` still has to mean the one that draws every variant
    of it -- the general tower, not whichever of the four happened to
    iterate last building ``_ALIASES``."""
    fs = Flowsheet.from_dict({"name": "T", "units": [{"kind": "column", "name": "T-101"}]})
    assert type(fs.units[0]).__name__ == "Column"
    assert set(fs.units[0].ports) == {"feed_1", "overhead", "bottoms"}


def test_a_distillation_column_kind_round_trips():
    """``kind: distillation_column`` is the fourth spelling the same
    collision resolves, and it has to survive the trip unchanged, exactly
    as ``Absorber``/``Stripper`` do above."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "distillation_column",
                    "name": "T-101",
                    "internals": "valve_tray",
                    "trays": 20,
                },
            ],
        }
    )
    assert type(fs.units[0]).__name__ == "DistillationColumn"
    assert set(fs.units[0].ports) == {
        "feed_1",
        "overhead",
        "bottoms",
        "reflux_in",
        "boilup_in",
        "reboiler_duty",
        "condenser_duty",
    }
    written = fs.to_dict()["units"][0]
    assert written["kind"] == "DistillationColumn"
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_a_plain_columns_retired_nozzle_round_trips():
    """A plain ``Column`` still answers ``reflux_in``/``condenser_duty`` for
    one release (#400), minted lazily through ``getattr`` rather than
    declared in ``unit.ports`` -- so a stream connected to one of them is
    real, and ``to_dict()`` writes it out under that name. ``from_dict()``
    used to look the name up in ``unit.ports`` directly, never asking
    ``getattr`` for it, so the very sheet the grace period was for could not
    be read back: the deprecation broke its own round trip.
    """
    fs = Flowsheet("legacy")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        col = fs.add(units.Column("T-901"))
        drum = fs.add(units.Vessel("D-101"))
        prod = fs.add(units.Product("PR-1"))
        fs.connect(drum.outlet, getattr(col, "reflux_in"), draw_as_recycle=True)
        fs.connect(getattr(col, "condenser_duty"), prod.inlet)

    written = fs.to_dict()
    with pytest.warns(DeprecationWarning, match="DistillationColumn"):
        back = Flowsheet.from_dict(written)
    reread = back.units[0]
    assert type(reread).__name__ == "Column"
    assert reread.port("reflux_in").stream is not None
    assert back.to_dict() == written


def test_an_absorbers_packing_default_round_trips_silently():
    """``internals="packing"`` is :class:`~pandid.units.Absorber`'s own
    default, not :class:`~pandid.units.Column`'s, so a bare
    ``{kind: Absorber}`` has to read back packed rather than bare -- the
    silent-failure shape this project has already been bitten by three
    times: a default that depends on the *class* the spec names has to be
    asked of that class, not of its base's.
    """
    fs = Flowsheet.from_dict({"name": "T", "units": [{"kind": "Absorber", "name": "V-501"}]})
    assert fs.units[0].internals == "packing"
    written = fs.to_dict()["units"][0]
    # Nothing is written: packing is what an unstated Absorber already means.
    assert "internals" not in written
    # A bare absorber -- one that really carries no internal -- still says so.
    bare = Flowsheet.from_dict(
        {"name": "T", "units": [{"kind": "Absorber", "name": "V-502", "internals": None}]}
    )
    assert bare.units[0].internals is None
    assert Flowsheet.from_dict(bare.to_dict()).units[0].internals is None


def test_absorber_and_stripper_still_take_n_feeds_and_feed_stages():
    """The reduced port set is only the four return nozzles; the feed
    family Column already has is untouched, and a spec has to be able to
    say where an absorber's two counter-current feeds land exactly as it
    would on a plain Column."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "Absorber",
                    "name": "V-501",
                    "internals": "packing",
                    "trays": 8,
                    "n_feeds": 2,
                    "feed_stages": [1, 8],
                },
            ],
        }
    )
    absorber = fs.units[0]
    assert {"feed_1", "feed_2"} <= set(absorber.ports)
    assert absorber.feed_stages == [1, 8]
    written = fs.to_dict()["units"][0]
    assert written["n_feeds"] == 2
    assert written["feed_stages"] == [1, 8]
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_a_columns_feed_stages_round_trip():
    """The keyword the writer must not drop: unlike ``n_feeds``, nothing else
    on the entry says where a feed landed, so a dropped ``feed_stages`` reads
    back as the even spread and both sides of a dict comparison would agree
    on a drawing that had moved."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "Column",
                    "name": "T-101",
                    "internals": "valve_tray",
                    "trays": 30,
                    "n_feeds": 2,
                    "feed_stages": [12, 22],
                },
            ],
        }
    )
    col = fs.units[0]
    assert col.feed_stages == [12, 22]
    written = fs.to_dict()["units"][0]
    assert written["feed_stages"] == [12, 22]
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()
    assert Flowsheet.from_dict(fs.to_dict()).to_svg() == fs.to_svg()


def test_a_null_feed_stage_round_trips_as_null_not_as_absent():
    """``feed_stages: [12, null]`` and no ``feed_stages`` at all are two
    different requests -- one feed pinned and the other free, against
    neither feed pinned -- and the writer has to be able to tell them apart
    on the way back out."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "Column",
                    "name": "T-101",
                    "internals": "tray",
                    "trays": 8,
                    "n_feeds": 2,
                    "feed_stages": [3, None],
                },
            ],
        }
    )
    written = fs.to_dict()["units"][0]
    assert written["feed_stages"] == [3, None]
    assert Flowsheet.from_dict(fs.to_dict()).units[0].feed_stages == [3, None]


def test_an_unstated_feed_stages_is_not_written_down():
    col = units.Column("T-101", n_feeds=2)
    fs = Flowsheet("T")
    fs.add(col)
    entry = fs.to_dict()["units"][0]
    assert "feed_stages" not in entry


def test_a_feed_stages_length_mismatch_is_refused_from_a_spec():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {
                "name": "T",
                "units": [
                    {"kind": "Column", "name": "T-1", "n_feeds": 2, "feed_stages": [5]},
                ],
            }
        )
    assert "feed_stages names 1" in str(excinfo.value)


def test_feed_stages_on_a_kind_with_no_feed_family_is_rejected():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {"name": "T", "units": [{"kind": "Pump", "name": "P-1", "feed_stages": [1]}]}
        )
    assert "only a Column takes 'feed_stages', not a Pump" in str(excinfo.value)


def test_a_columns_draw_count_round_trips():
    """``n_draws`` the other way round: unlike ``n_feeds``, zero -- not one
    -- is the shape that writes nothing down, since most columns have no
    side draw at all."""
    fs = Flowsheet.from_dict(
        {"name": "T", "units": [{"kind": "Column", "name": "T-301", "n_draws": 2}]}
    )
    assert {"draw_1", "draw_2"} <= set(fs.units[0].ports)
    written = fs.to_dict()["units"][0]
    assert written["n_draws"] == 2
    bare = Flowsheet.from_dict({"name": "T", "units": [{"kind": "Column", "name": "T-101"}]})
    assert "n_draws" not in bare.to_dict()["units"][0]


def test_a_columns_draw_stages_round_trip():
    """The keyword the writer must not drop, for the reason
    ``test_a_columns_feed_stages_round_trip`` gives ``feed_stages``: nothing
    else on the entry says where a draw landed."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "Column",
                    "name": "T-301",
                    "internals": "valve_tray",
                    "trays": 30,
                    "n_draws": 2,
                    "draw_stages": [8, 20],
                },
            ],
        }
    )
    col = fs.units[0]
    assert col.draw_stages == [8, 20]
    written = fs.to_dict()["units"][0]
    assert written["draw_stages"] == [8, 20]
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()
    assert Flowsheet.from_dict(fs.to_dict()).to_svg() == fs.to_svg()


def test_a_null_draw_stage_round_trips_as_null_not_as_absent():
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {
                    "kind": "Column",
                    "name": "T-101",
                    "internals": "tray",
                    "trays": 8,
                    "n_draws": 2,
                    "draw_stages": [3, None],
                },
            ],
        }
    )
    written = fs.to_dict()["units"][0]
    assert written["draw_stages"] == [3, None]
    assert Flowsheet.from_dict(fs.to_dict()).units[0].draw_stages == [3, None]


def test_an_unstated_draw_stages_is_not_written_down():
    col = units.Column("T-101", n_draws=2)
    fs = Flowsheet("T")
    fs.add(col)
    entry = fs.to_dict()["units"][0]
    assert "draw_stages" not in entry


def test_a_draw_stages_length_mismatch_is_refused_from_a_spec():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {
                "name": "T",
                "units": [
                    {"kind": "Column", "name": "T-1", "n_draws": 2, "draw_stages": [5]},
                ],
            }
        )
    assert "draw_stages names 1" in str(excinfo.value)


def test_draw_stages_on_a_kind_with_no_draw_family_is_rejected():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(
            {"name": "T", "units": [{"kind": "Pump", "name": "P-1", "draw_stages": [1]}]}
        )
    assert "only a Column takes 'draw_stages', not a Pump" in str(excinfo.value)


def test_a_draw_count_on_a_kind_with_no_draw_family_is_rejected():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict({"name": "T", "units": [{"kind": "Pump", "name": "P-1", "n_draws": 2}]})
    assert "only a Column takes 'n_draws', not a Pump" in str(excinfo.value)


def test_a_column_with_both_feed_and_draw_families_round_trips():
    """The intersection ``Column.__new__``'s comment names: both counts
    above one, resolving to the untyped base class at the type level but
    drawing and round-tripping exactly like any other column."""
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
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
        }
    )
    col = fs.units[0]
    assert {"feed_1", "feed_2", "draw_1", "draw_2"} <= set(col.ports)
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()
    assert Flowsheet.from_dict(fs.to_dict()).to_svg() == fs.to_svg()


@pytest.mark.parametrize("kind", ["Vessel", "Tank"])
def test_a_vessels_relief_and_drain_need_no_key_of_their_own(kind):
    """The spec carries #222's nozzles by carrying nothing.

    This is the round trip the design was partly chosen for. A counted family
    or a set of constructor flags would each have needed a new key here, a new
    entry in the ``_UNIT_KWARGS`` table that says which classes accept it, and
    a rule for when it is written out and when it is left off -- the three
    things ``n_feeds`` above costs. A port set that follows from the class
    follows from ``kind:``, which the spec already writes, so a sheet drawn
    against a relief connection round-trips with no format change at all.
    """
    fs = Flowsheet.from_dict(
        {
            "name": "T",
            "units": [
                {"kind": kind, "name": "V-1", "variant": "sphere" if kind == "Tank" else "legs"},
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


def test_a_feed_count_on_a_kind_with_no_feed_family_is_rejected():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict({"name": "T", "units": [{"kind": "Pump", "name": "P-1", "n_feeds": 2}]})
    assert "only a Column or a Reactor takes 'n_feeds', not a Pump" in str(excinfo.value)


# --- composition: what a body carries -----------------------------------------
#
# ``variant`` chooses the body and these keywords choose the ISO 10628-2 parts
# drawn in it. Every assertion below is on the **resolved symbol's overlays**,
# never on a count of them, because a count is what let the regression through:
# a reactor whose anchor stirrer had been swapped for the general one draws one
# overlay either way. Nor is a comparison of the two specs enough -- the
# keywords were dropped on the way *out*, so both directions agreed on a file
# that had already lost the drawing.


def _drawn(unit):
    """The parts really drawn on a unit: group, name and hand, in order."""
    from pandid.render.symbols import default_registry

    return [(o.group, o.name, o.mirror) for o in default_registry.for_unit(unit).overlays]


def _artwork(unit):
    """The composed drawing itself, which settles placement as well as parts."""
    from pandid.render.symbols import default_registry

    return default_registry.for_unit(unit).svg


def _round_trip(unit):
    """One unit out through ``to_dict`` and back: its entry, and the unit read."""
    fs = Flowsheet("T")
    fs.add(unit)
    spec = fs.to_dict()
    assert json.loads(json.dumps(spec)) == spec, "spec must be JSON-safe"
    return spec["units"][0], Flowsheet.from_dict(spec).units[0]


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda: units.Vessel("D-301", supports="skirt"), {"supports": "skirt"}),
        # Chiral, and drawn as a mirrored pair: a hand lost is a lug on one wall.
        (lambda: units.Vessel("D-302", supports="bracket"), {"supports": "bracket"}),
        (lambda: units.Reactor("R-101", agitator="anchor"), {"agitator": "anchor"}),
        # No ``agitator`` in the entry: a reactor with internals is not
        # stirred unless it says so, so the empty agitator *is* the
        # default here and writing it would be noise. The stated empty
        # that is not a default still gets its ``null`` -- see
        # ``test_a_body_asked_for_bare_comes_back_bare``.
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
    """Each keyword is written under its own name and read back as itself.

    The entry is compared whole, so a keyword that arrived as something else --
    a separator's characteristic folded back into ``variant`` -- fails here
    rather than in the drawing.
    """
    unit = make()
    entry, rebuilt = _round_trip(unit)
    assert {key: value for key, value in entry.items() if key not in ("kind", "name")} == expected
    assert _drawn(rebuilt) == _drawn(unit)
    assert _artwork(rebuilt) == _artwork(unit)


def test_a_columns_tray_count_survives_the_trip():
    """Eighteen sieve trays, and eighteen of them.

    The count and the part are two ways to lose the same tower: dropping
    ``internals`` draws generic decks and dropping ``trays`` draws the eight ISO
    item 2.6 X8011 does, so the tower came back as eight generic decks with
    neither direction of the spec able to see it.
    """
    unit = units.Column("T-102", internals="sieve_tray", trays=18)
    entry, rebuilt = _round_trip(unit)
    assert (entry["internals"], entry["trays"]) == ("sieve_tray", 18)
    assert _drawn(unit) == [(27, "sieve_tray", False)] * 18
    assert (rebuilt.internals, rebuilt.trays) == ("sieve_tray", 18)
    assert _drawn(rebuilt) == _drawn(unit)
    assert _artwork(rebuilt) == _artwork(unit)


def test_a_body_carrying_two_parts_keeps_both_and_their_order():
    """The bed first and the stirrer over it.

    Order is drawing order, so the shaft is drawn on top of whatever it turns in
    rather than under it; a round trip that kept both parts and swapped them
    would draw the reactor inside out.
    """
    unit = units.Reactor("R-301", internals="fluidised_bed", agitator="turbine")
    entry, rebuilt = _round_trip(unit)
    assert (entry["internals"], entry["agitator"]) == ("fluidised_bed", "turbine")
    # ...and the motor on the end of the stirrer's shaft, which comes with it:
    # ISO item 1.27 X8006 draws the two together and there is no keyword for
    # the second, so nothing about it is written down either.
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
        # ISO item 2.1 X8100: the general column carries no internal, so an
        # unfurnished tower is a body that composes nothing rather than one
        # whose default part goes unwritten.
        lambda: units.Column("T-101"),
    ],
)
def test_a_unit_that_composes_nothing_gains_nothing(make):
    """The other half of the round trip, and the one a golden would catch late.

    A writer that stated every keyword would put a part on a plain drum, and a
    reader that defaulted one would do the same on the way back.
    """
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
    """A reactor is a stirred tank without being told.

    Only what differs from a default is written, here as everywhere else in the
    format, so the entry for an ordinary reactor is the entry it always was.

    The reactor draws *two* parts and still writes nothing: the motor is item
    1.27 X8006's, it arrives with the stirrer, and a part no keyword asks for
    is a part no keyword records.
    """
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
    """Stated empty is not the same as not stated, and ``null`` is how it is said.

    Leave the keyword off and the class puts its own part back: an unstated
    agitator reads as the stirrer a reactor turns when nobody says otherwise.

    A reactor is the only class this still bites. A column's unfurnished
    default *is* bare -- ISO item 2.1 X8100 -- so for that one the two spellings
    genuinely mean the same thing and neither is written down.
    """
    unit = make()
    entry, rebuilt = _round_trip(unit)
    assert entry[key] is None
    assert _drawn(unit) == []
    assert _drawn(rebuilt) == []


def test_a_separators_characteristic_is_written_as_itself_not_as_the_variant():
    """The fold into ``variant`` is an implementation detail, and a time bomb.

    ``characteristic=`` sets ``variant=`` because the mark inside a separating
    vessel *is* which drawing it is. Writing the fold back out hands the reader
    a spelling deprecated with ``removed_in="0.2.0"``, so a sheet nobody had
    edited warns today and is refused then. ``_write_instrument`` drops a folded
    variant for the same reason.
    """
    entry, _ = _round_trip(units.Separator("V-201", characteristic="gravity"))
    assert entry == {"kind": "Separator", "name": "V-201", "characteristic": "gravity"}
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        rebuilt = Flowsheet.from_dict({"name": "T", "units": [entry]}).units[0]
    assert (rebuilt.characteristic, rebuilt.variant) == ("gravity", "gravity")


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


def test_a_composition_keyword_on_a_kind_with_no_such_part_is_rejected():
    with pytest.raises(SpecError) as excinfo:
        Flowsheet.from_dict(_spec(units=[{"kind": "Pump", "name": "P-1", "supports": "skirt"}]))
    assert "only a Vessel takes 'supports', not a Pump" in str(excinfo.value)


def test_a_part_no_such_group_has_names_the_ones_it_does():
    """Resolved where the author typed it, not when the sheet is finally drawn."""
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
    """The guard the composition keywords went without.

    Five keywords landed on four equipment classes and none of this module's
    tables heard about them, so ``to_dict`` wrote a composed unit as
    ``{kind, name}`` and ``from_dict`` read the class's own part back in their
    place -- a different drawing, and one no comparison of the two specs could
    see. Derived from the constructors rather than listed, because a list
    restated is exactly what drifted: an argument added to a class tomorrow
    fails here on the day it lands.

    ``Instrument`` is excluded because it has a section of its own, a tag and an
    attachment instead of a kind, and ``_INSTRUMENT_KEYS`` to match.

    ``Valve(actuator=)`` is excluded because it is a **spelling of** ``variant``
    and nothing more: the constructor resolves the body and the operator to the
    one registered variant that draws both -- ``variant="gate",
    actuator="diaphragm"`` *is* ``variant="control"`` -- and leaves nothing
    behind under its own name, since ``valve.actuator`` is the signal
    connection. The spec already writes that variant, so the argument is
    reachable, just not by that word. Contrast ``Separator(characteristic=)``,
    which folds the same way but *is* kept on the unit and whose variant
    spelling is deprecated, so it has to be written as itself.
    """
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
    """``_UNSTATED`` is a sentinel, and the writer compares against it.

    A class that declares one and forgets the ``composition_defaults`` override
    would write the sentinel object itself into the file, which is neither
    JSON-safe nor anything the reader could take back.
    """
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
    # Stored under the canonical name: ``inlet`` is a live alias for
    # ``in_1`` and never a second key of its own -- see
    # ``Unit._canonical_port_name``.
    assert fs.units[0]._port_faces == {"in_1": "N"}


def test_a_tanks_face_list_round_trips_through_a_spec():
    """#342's own face list, over :class:`~pandid.units.Tank`'s mechanism
    rather than :class:`~pandid.units.Block`'s -- the shape
    ``test_block.py``'s own ``test_a_block_round_trips_through_a_spec``
    pins for the class this one is borrowed from. A face list dropped on
    write is the silent-failure class this project has been bitten by
    three times, so this is checked directly rather than assumed from
    the two classes sharing a mechanism.
    """
    from pandid.spec import from_dict, to_dict

    fs = Flowsheet("tanks")
    # A ``list``, not a ``tuple``: the spelling that keeps this on the
    # untyped ``Tank`` return (see ``units.Tank.__new__``'s overloads),
    # so ``.port("in_2")`` and not ``.in_2`` reaches the second inlet --
    # a checker cannot resolve the numbered attribute on this arm either.
    tk = fs.add(units.Tank("TK-1", inputs=["W", "W", "N"]))
    feed = fs.add(units.Feed("F"))
    prod = fs.add(units.Product("P"))
    fs.connect(feed.outlet, tk.port("in_2"))
    fs.connect(tk.outlet, prod.inlet)

    spec = to_dict(fs)
    (entry,) = [u for u in spec["units"] if u["kind"] == "Tank"]
    assert entry["inputs"] == ["W", "W", "N"]
    # A single outlet on its own default face is the shorthand every
    # ``Tank("TK-1")`` already means, so it is not written down at all --
    # unlike a Block, which has no connection-free shape to default to.
    assert "outputs" not in entry

    read = from_dict(spec)
    (got,) = [u for u in read.units if isinstance(u, units.Tank)]
    assert got.input_faces == tk.input_faces == ("W", "W", "N")
    assert got.output_faces == tk.output_faces
    assert list(got.ports) == list(tk.ports)
    assert to_dict(read) == spec


def test_a_vessels_moved_nozzle_and_reordered_face_round_trip():
    """The other two connection-family calls, over :class:`Vessel`: an
    explicit :meth:`~pandid.units._MultiPortVessel.nozzle` move and an
    :meth:`~pandid.units._MultiPortVessel.order_on` reordering, each
    written back and read to the same declaration.

    ``horizontal`` because the default variant's inlet has no menu at
    all -- a single anchored face, so there is nowhere for ``nozzle()``
    to move two connections *to* and nothing for ``order_on()`` to
    reorder.
    """
    from pandid.spec import from_dict, to_dict

    fs = Flowsheet("vessels")
    v = fs.add(units.Vessel("V-1", variant="horizontal", inputs=2, width=130, height=42))
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
    # Objects of two different flowsheets, so it is the names that have
    # to agree, not the ``Port``s themselves.
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


def test_auto_faces_off_survives_a_round_trip():
    """A sheet whose faces were settled by hand has to come back settled by
    hand; silently re-enabling the selector would redraw it on reload."""
    fs = Flowsheet.from_dict({"name": "T", "auto_faces": False})
    assert fs.auto_faces is False
    assert fs.to_dict()["auto_faces"] is False
    assert "auto_faces" not in Flowsheet("T").to_dict()


def test_retired_direction_key_is_refused():
    """A file written against the old format is told what happened, not ignored."""
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
    assert (inst.type, inst.number) == ("LIC", "101")
    # The two axes the entry states, and the one variant they resolve to.
    assert (inst.symbol_type, inst.display, inst.variant) == ("default", "central", "panel")
    assert (inst.host.name, inst.relation) == ("P-101", "sensing")
    assert (inst.at, inst.offset, inst.angle) == ("S", 90.0, 35.0)
    assert inst._port_faces == {"sig_out": "W"}


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
    """Which keyword named the anchor is what decides what is drawn between the
    two, so it is part of the sheet and has to survive being written down."""
    entry = {"type": "I", "number": 1, "variant": "sis", relation: "P-101", "at": "S"}
    fs = Flowsheet.from_dict(_spec(instruments=[entry]))
    assert (fs.units[-1].host.name, fs.units[-1].relation) == ("P-101", relation)
    assert fs.to_dict()["instruments"][0][relation] == "P-101"
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_a_sheet_using_the_whole_instrument_vocabulary_round_trips():
    """Every part of a balloon that is a *decision* has to be in the file.

    The relation decides what is drawn between the balloon and its host, the
    display decides whether it carries a bar, the quadrants are lettering on the
    paper and a primary element's balloon is where its tag went. A sheet that
    lost any of them on the way through a spec would come back a different
    drawing under the same name.
    """
    fs = Flowsheet("vocabulary")
    feed = fs.add(units.Feed("Feed")).pin(x=60, y=170)
    fe = fs.add(units.Fitting("FE-303", variant="venturi")).pin(x=300, port="inlet", y=195)
    prod = fs.add(units.Product("Product")).pin(x=620, y=170)
    fs.connect(feed.outlet, fe.inlet)
    fs.connect(fe.outlet, prod.inlet)
    balloon = fs.add_balloon(fe, at="N", offset=38)
    ft = fs.add_instrument("FT", 303, near=balloon, at="N", offset=23)
    fic = fs.add_instrument("FIC", 303, near=ft, at="E", offset=70, display="central")
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
    """A pinned balloon is a balloon the author put somewhere on purpose.

    The assertions are on the rebuilt *object*, and deliberately not on the two
    dicts. The writer used to leave the balloon branch before it wrote the
    placement down, so the pin and the port faces reached neither the file nor
    the reader -- and a field that neither direction carries makes the sheet
    read back compare *equal* to the file it came from while the drawing has
    moved. Comparing specs is blind to exactly this, which is why it is not the
    test.
    """
    fs = Flowsheet("placed")
    fe = fs.add(units.Fitting("FE-303", variant="venturi")).pin(x=300, y=195)
    balloon = fs.add_balloon(fe, at="S")
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
    """Whatever ``add_balloon`` accepts has to survive being written down.

    Its keywords go straight into the balloon, so one reaches the spec with a
    description, a size, a label position, a display and lettering in its
    quadrants on it -- all written by the same code that writes them for any
    other unit. The reader's key list knew only about the placement, so a
    balloon given any of them was refused by its own writer's output.
    """
    fs = Flowsheet("vocabulary")
    fe = fs.add(units.Fitting("FE-303", variant="venturi")).pin(x=300, y=195)
    balloon = fs.add_balloon(
        fe,
        at="N",
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
    """The flag is written for an instrument exactly as it is for any other
    unit, so the reader has to accept the key its own writer emits."""
    fs = Flowsheet.from_dict(
        _spec(instruments=[{"type": "PI", "number": 7, "new_line_number": True}])
    )
    assert fs.units[-1].new_line_number is True
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_an_entry_naming_two_anchors_is_refused():
    """A balloon is placed against one thing. Two keywords are two placements,
    and the reader says which two rather than silently taking the first."""
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


def test_stream_table_sections():
    fs = Flowsheet.from_dict(_spec(stream_table_sections=[["Benzene", "Mass Fraction"]]))
    assert fs.stream_table_sections == [("Benzene", "Mass Fraction")]


def test_stream_table_options_round_trip():
    fs = Flowsheet.from_dict(_spec(stream_table={"font_size": 8}))
    assert fs.stream_table.font_size == 8
    assert fs.to_dict()["stream_table"] == {"font_size": 8}


def test_a_table_left_alone_writes_no_section():
    """So a spec written by a sheet that says nothing about its table is the
    same file it was before these options existed."""
    assert "stream_table" not in Flowsheet.from_dict(_spec()).to_dict()


def test_a_stream_table_key_that_is_not_one_is_named():
    with pytest.raises(SpecError, match="font_sixe"):
        Flowsheet.from_dict(_spec(stream_table={"font_sixe": 8}))


def test_a_stream_table_value_of_the_wrong_kind_is_refused():
    with pytest.raises(SpecError, match="must be a number"):
        Flowsheet.from_dict(_spec(stream_table={"font_size": "8"}))


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
    """YAML 1.1 makes ``N`` the boolean False and a bare date a date object.

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
        "    sensing: V-1\n"
        "    at: N\n"
        "title_block: {revisions: [{rev: A, date: 2026-05-18}]}\n",
        encoding="utf-8",
    )
    fs = Flowsheet.from_yaml(path)
    assert fs.units[-1].host is fs.units[0]
    assert fs.units[-1].at == "N"
    assert fs.title_block.revisions[0].date == "2026-05-18"


def test_from_yaml_without_pyyaml_says_exactly_what_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)  # makes `import yaml` fail
    path = tmp_path / "fs.yaml"
    path.write_text("name: T\n", encoding="utf-8")
    with pytest.raises(ImportError) as excinfo:
        Flowsheet.from_yaml(path)
    message = str(excinfo.value)
    assert "PyYAML" in message
    assert "pip install 'pandid[yaml]'" in message
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


@pytest.mark.parametrize("name", ["liquid", "vapour"])
def test_a_spec_file_naming_a_removed_port_is_refused(name):
    """``Separator(variant="cyclone")`` called its draws ``vapor`` and
    ``liquid`` up to 0.1.1 and ``overflow``/``underflow`` since; the old pair
    was read for 0.1.2 and is gone in 0.1.3. A file written then gets the
    message any other name off the unit gets, which names the nozzles it has.
    """
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
    """Named on a pump nozzle rather than on the feed flag it used to be named
    on: a flag's connection takes as many lines as the sheet gives it (#454),
    and a process nozzle still takes one."""
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
    """The spelled-out word is the obvious guess, and used to be taken as
    an unrecognised alignment and silently centred rather than refused."""
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
    """A joint stated on one line is the author overruling the sheet, so losing
    it on reload redraws that line as whatever the sheet says instead."""
    fs = Flowsheet.from_dict(_two_vessels(ends="flanged"))
    assert fs.streams[0].ends == "flanged"
    assert fs.to_dict()["streams"][0]["ends"] == "flanged"
    # ...and a line that says nothing writes nothing, so an unmarked sheet's
    # spec does not grow a key per stream.
    assert "ends" not in Flowsheet.from_dict(_two_vessels()).to_dict()["streams"][0]


def test_two_joints_stated_apart_survive_a_round_trip_in_order():
    fs = Flowsheet.from_dict(_two_vessels(ends=["flanged", "none"]))
    assert fs.streams[0].ends == ("flanged", "none")
    # Out as a list, which is what YAML and JSON both write a pair as.
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
