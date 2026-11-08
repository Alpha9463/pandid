"""Check the reducer and which way its cone points."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from pandid import Flowsheet, spec, units
from pandid.portgeom import port_point, resolve_size
from pandid.render.symbols import Overlay, Symbol, expander
from pandid.render.symbols import default_registry as registry

#: Every body a reducer is drawn with.
VARIANTS = ("default", "concentric", "eccentric")

RUN_Y = 300.0


def _station(variant="concentric"):
    """Feed -> reduction -> control valve -> expansion -> product, in one run."""
    fs = Flowsheet("valve station")
    feed = fs.add(units.Feed("FROM T-301"))
    rd = fs.add(units.Reducer("RD-306A", variant=variant))
    cv = fs.add(units.Valve("CV-306", actuator="diaphragm"))
    ex = fs.add(units.Reducer("RD-306B", variant=variant, large_end="outlet"))
    prod = fs.add(units.Product("TO F-301"))
    x = 160.0
    for unit in (rd, cv, ex):
        w, h = resolve_size(unit)
        unit.pin(x=x, y=RUN_Y - h / 2)
        x += w + 14.0
    feed.pin(x=90.0, y=RUN_Y)
    prod.pin(x=x + 40.0, y=RUN_Y)
    fs.connect(feed.outlet, rd.inlet)
    fs.connect(rd.outlet, cv.inlet)
    fs.connect(cv.outlet, ex.inlet)
    fs.connect(ex.outlet, prod.inlet)
    fs.layout()
    fs.route()
    return fs, rd, cv, ex


# --- what the argument means --------------------------------------------------


def test_a_reducer_puts_its_large_end_on_the_inlet_by_default():
    assert units.Reducer("RD-1").large_end == "inlet"


def test_the_large_end_may_be_named_at_construction_or_after():
    rd = units.Reducer("RD-1", large_end="outlet")
    assert rd.large_end == "outlet"
    rd.large_end = "inlet"
    assert rd.large_end == "inlet"


def test_an_end_that_is_not_a_nozzle_is_refused():
    with pytest.raises(ValueError, match="large_end names the nozzle on the wide face"):
        units.Reducer("RD-1", large_end="big")


def test_the_ends_are_the_units_own_port_names():
    """Check that every ``large_end`` value is one of the reducer's ports."""
    assert set(units.Reducer.LARGE_ENDS) <= set(units.Reducer("RD-1").ports)


# --- what it draws ------------------------------------------------------------


@pytest.mark.parametrize("variant", VARIANTS)
def test_an_expansion_is_the_reduction_turned_end_for_end(variant):
    """One casting, two installations: same box, same faces, mirrored ink."""
    reduction = registry.for_unit(units.Reducer("RD-A", variant=variant))
    expansion = registry.for_unit(units.Reducer("RD-B", variant=variant, large_end="outlet"))
    assert (expansion.width, expansion.height) == (reduction.width, reduction.height)
    assert list(expansion.port_faces["inlet"]) == ["W"]
    assert list(expansion.port_faces["outlet"]) == ["E"]
    assert expansion.svg != reduction.svg
    assert "scale(-1,1)" in expansion.svg


@pytest.mark.parametrize("variant", VARIANTS)
def test_the_run_crosses_both_fittings_without_a_break(variant):
    """Check that every stream ends on its nozzles and both fittings are drawn."""
    fs, rd, cv, ex = _station(variant)
    for stream in fs.streams:
        start, end = stream.route.waypoints[0], stream.route.waypoints[-1]
        assert start == pytest.approx(
            port_point(stream.source.owner, stream.source.owner.frame, stream.source.name)
        )
        assert end == pytest.approx(
            port_point(stream.dest.owner, stream.dest.owner.frame, stream.dest.name)
        )
    for fitting in (rd, ex):
        west = port_point(fitting, fitting.frame, "inlet")
        east = port_point(fitting, fitting.frame, "outlet")
        assert west[0] < east[0]
    assert fs.to_svg().count('<symbol id="sym_reducer') == 2


def test_the_reference_stations_proportions():
    """Check that a concentric reducer is square and half the control valve's width."""
    reducer = registry.get("reducer", "concentric")
    valve = registry.actuated("default", "diaphragm")
    assert reducer.width == reducer.height
    assert reducer.width == pytest.approx(valve.width / 2, rel=0.05)


# --- the eccentric body's two orientations ------------------------------------


def test_an_eccentric_reducer_is_drawn_flat_on_top():
    """Check that an eccentric reducer is flat on top."""
    sym = registry.get("reducer", "eccentric")
    assert sym.ports["outlet"][1] < sym.ports["inlet"][1]
    # The flat side is the artwork's top edge, at y = 0.
    assert '"M 0.0 0.0 L 20.0 0.0' in sym.svg


def _placed_eccentric(mirrored):
    """One eccentric reducer in a run, at the given flip, laid out."""
    fs = Flowsheet(f"eccentric, mirrored={mirrored!r}")
    feed = fs.add(units.Feed("IN")).pin(x=90, y=RUN_Y)
    rd = fs.add(units.Reducer("RD-1", variant="eccentric"))
    rd.pin(x=200, y=RUN_Y - resolve_size(rd)[1] / 2, mirrored=mirrored)
    prod = fs.add(units.Product("OUT")).pin(x=340, y=RUN_Y)
    fs.connect(feed.outlet, rd.inlet)
    fs.connect(rd.outlet, prod.inlet)
    fs.layout()
    return rd


def test_rolling_an_eccentric_reducer_over_puts_the_flat_side_underneath():
    """Check that a reducer mirrored top to bottom puts the flat side underneath."""
    flat_top = _placed_eccentric(False)
    flat_bottom = _placed_eccentric("y")
    assert flat_top.frame.h == flat_bottom.frame.h

    def offsets(unit):
        return {name: port_point(unit, unit.frame, name)[1] - unit.frame.y for name in unit.ports}

    up, down = offsets(flat_top), offsets(flat_bottom)
    # Rolled over, the small end is the lower one and every nozzle is mirrored in the box.
    assert up["outlet"] < up["inlet"]
    assert down["outlet"] > down["inlet"]
    for name in up:
        assert up[name] + down[name] == pytest.approx(flat_top.frame.h, abs=0.15)


def test_an_eccentric_expansion_keeps_the_flat_side_it_was_drawn_with():
    """Check that an eccentric expansion stays flat on top."""
    sym = registry.for_unit(units.Reducer("RD-B", variant="eccentric", large_end="outlet"))
    # The inlet is now the small end, and the flat top stays where it was.
    assert sym.ports["inlet"][1] < sym.ports["outlet"][1]


# --- the derivation itself ----------------------------------------------------


def test_only_a_two_ended_fitting_can_be_turned_end_for_end():
    """Check that ``expander`` refuses a symbol without exactly two ends."""
    with pytest.raises(ValueError, match="two ends to trade"):
        expander(registry.get("pump", "default"))
    with pytest.raises(ValueError, match="two ends to trade"):
        expander(registry.actuated("default", "diaphragm"))  # inlet, outlet and actuator


def test_the_turned_drawing_mirrors_its_bands_and_keeps_every_other_field() -> None:
    """Check that the turned drawing mirrors its bands and parts and keeps every other field."""
    banded = replace(
        registry.get("reducer", "default"),
        bands={"N": (2.5, 5.0), "W": (4.0, 8.0)},
        overlays=(Overlay(26, "bracket", 0.1, 0.2, 0.2, 0.1),),
    )
    turned = expander(banded)
    assert turned.bands == {"N": (7.5, 10.0), "E": (4.0, 8.0)}
    (part,) = turned.overlays
    assert (part.x, part.mirror) == (pytest.approx(0.7), True)
    mirrored = {"svg", "ports", "port_faces", "bands", "overlays", "id_suffix", "drawio_flip_h"}
    for f in fields(Symbol):
        if f.name not in mirrored:
            assert getattr(turned, f.name) == getattr(banded, f.name), f.name


def test_a_band_to_the_edge_of_an_uneven_width_still_fits_when_turned() -> None:
    """The mirrored band is measured from the same width, so it stays on the face."""
    sym = Symbol(
        svg='<g id="sym_odd"><path d="M 0 0 L 20 10"/></g>',
        width=20.00006,
        height=10.0,
        ports={"inlet": (0.0, 5.0), "outlet": (20.00006, 5.0)},
        bands={"N": (0.0, 10.0)},
    )
    assert expander(sym).bands == {"N": (pytest.approx(10.00006), 20.00006)}


def test_the_turned_drawing_is_built_once_and_shared():
    """Check that the turned drawing is built once and shared."""
    first = registry.for_unit(units.Reducer("RD-A", large_end="outlet"))
    second = registry.for_unit(units.Reducer("RD-B", large_end="outlet"))
    assert first is second


# --- round-tripping -----------------------------------------------------------


def test_an_expansion_survives_a_spec_round_trip():
    fs = Flowsheet("round trip")
    fs.add(units.Reducer("RD-306A", variant="concentric"))
    fs.add(units.Reducer("RD-306B", variant="concentric", large_end="outlet"))
    data = fs.to_dict()
    entries = {entry["name"]: entry for entry in data["units"]}
    assert "large_end" not in entries["RD-306A"]
    assert entries["RD-306B"]["large_end"] == "outlet"
    ends = {u.name: u.large_end for u in spec.from_dict(data).units}
    assert ends == {"RD-306A": "inlet", "RD-306B": "outlet"}
