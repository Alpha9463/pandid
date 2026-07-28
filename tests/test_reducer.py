"""The fitting that changes a line's size, and which way its cone points.

The reference is the issued sheet the package reproduces
(``professional_examples/P&ID_301.pdf``, gitignored). Measured off its vector
geometry, it carries **eight** size-change fittings and every one of them is
half of a pair on one centreline: a reduction into a control valve and an
expansion back out of it. The CV-306 station's pair is

* the reduction, ``(510.51, 628.70) (519.01, 630.83) (519.01, 635.08)
  (510.51, 637.20)`` -- a west face 8.50 pt tall, an east face 4.25 pt tall,
  8.50 pt long;
* the expansion, the same trapezoid the other way round: ``(553.55, 630.83)``
  to ``(553.55, 635.08)`` on the west at 4.25 pt, and ``(562.05, 628.70)`` to
  ``(562.05, 637.20)`` on the east at 8.50 pt;
* both centred on the run at y = 632.95, with the control valve between them
  drawn to the same 8.50 pt height, and a drain tee outside each of them.

There is no second fitting on that sheet: a reduction and an expansion are one
casting piped round the other way, which is what ``large_end`` says and why it
is not a variant. The tests below hold the drawn consequence of that -- the cone
points downstream on one and upstream on the other, the box and the two faces
are unchanged, and the run crosses both without a break.
"""

from __future__ import annotations

import pytest

from pandid import Flowsheet, spec, units
from pandid.portgeom import port_point, resolve_size
from pandid.render.symbols import default_registry as registry
from pandid.render.symbols import expander

#: Every body a reducer is drawn with.
VARIANTS = ("default", "concentric", "eccentric")

RUN_Y = 300.0


def _station(variant="concentric"):
    """Feed -> reduction -> control valve -> expansion -> product, in one run."""
    fs = Flowsheet("valve station")
    feed = fs.add(units.Feed("FROM T-301"))
    rd = fs.add(units.Reducer("RD-306A", variant=variant))
    cv = fs.add(units.Valve("CV-306", variant="control"))
    ex = fs.add(units.Reducer("RD-306B", variant=variant, large_end="outlet"))
    prod = fs.add(units.Product("TO F-301"))
    x = 160.0
    for unit in (rd, cv, ex):
        w, h = resolve_size(unit)
        unit.pin(x=x, y=RUN_Y - h / 2)
        x += w + 14.0
    feed.pin(x=40.0, y=RUN_Y - 25.0)
    prod.pin(x=x + 40.0, y=RUN_Y - 25.0)
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
    """The argument names a port rather than describing the flow, so the two
    have to stay the same words: a value nothing is called would be a setting
    with no nozzle behind it."""
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
def test_the_two_drawings_are_two_definitions(variant):
    """A ``<use>`` points at a ``<defs>`` entry keyed by the artwork, so a
    station carrying both has to define both -- one id drawn twice would draw
    the reduction where the expansion goes."""
    fs, _, _, _ = _station(variant)
    svg = fs.to_svg()
    assert svg.count('<symbol id="sym_reducer') == 2


@pytest.mark.parametrize("variant", VARIANTS)
def test_the_run_crosses_both_fittings_without_a_break(variant):
    """Every stream ends exactly on the nozzle it is drawn to.

    The reference draws its station as one unbroken stroke through every device
    on it; a nozzle that had moved with the mirrored artwork would leave the
    line hanging off the far side of the fitting.
    """
    fs, rd, cv, ex = _station(variant)
    for stream in fs.streams:
        start, end = stream.route.waypoints[0], stream.route.waypoints[-1]
        assert start == pytest.approx(
            port_point(stream.source.owner, stream.source.owner.frame, stream.source.name)
        )
        assert end == pytest.approx(
            port_point(stream.dest.owner, stream.dest.owner.frame, stream.dest.name)
        )
    # ...and the flow crosses each fitting west to east, as it is drawn.
    for fitting in (rd, ex):
        west = port_point(fitting, fitting.frame, "inlet")
        east = port_point(fitting, fitting.frame, "outlet")
        assert west[0] < east[0]


def test_the_reference_stations_proportions():
    """The drawn pair, against P&ID-301's own.

    The reference's trapezoid is 8.50 pt long between an 8.50 pt face and a
    4.25 pt one -- square, with the small face exactly half the large -- and its
    control valve is drawn 17.0 pt long by 8.50 pt tall. The package draws the
    concentric body 12.5 x 12.5 beside a 24.5 x 15.0 valve, so the fitting is
    half the valve's length on both sheets.
    """
    reducer = registry.get("reducer", "concentric")
    valve = registry.get("valve", "control")
    assert reducer.width == reducer.height
    assert reducer.width == pytest.approx(valve.width / 2, rel=0.05)


# --- the eccentric body's two orientations ------------------------------------


def test_an_eccentric_reducer_is_drawn_flat_on_top():
    """Which is the pump-suction arrangement: a concentric body there leaves a
    pocket against the roof of the line for vapour to collect in and break the
    pump's suction.

    Read off the nozzles rather than the ink, because it is the nozzles that
    carry it onto the sheet. Flat on top means the small end's centreline is the
    higher of the two, so its ``outlet`` sits nearer the top of the box than the
    ``inlet`` does -- a smaller y, drawing coordinates running downward.
    """
    sym = registry.get("reducer", "eccentric")
    assert sym.ports["outlet"][1] < sym.ports["inlet"][1]
    # ...and the flat side is the artwork's own top edge, at y = 0 across.
    assert '"M 0.0 0.0 L 20.0 0.0' in sym.svg


def _placed_eccentric(mirrored):
    """One eccentric reducer in a run, at the given flip, laid out."""
    fs = Flowsheet(f"eccentric, mirrored={mirrored!r}")
    feed = fs.add(units.Feed("IN")).pin(x=40, y=RUN_Y - 25)
    rd = fs.add(units.Reducer("RD-1", variant="eccentric"))
    rd.pin(x=200, y=RUN_Y - resolve_size(rd)[1] / 2, mirrored=mirrored)
    prod = fs.add(units.Product("OUT")).pin(x=340, y=RUN_Y - 25)
    fs.connect(feed.outlet, rd.inlet)
    fs.connect(rd.outlet, prod.inlet)
    fs.layout()
    return rd


def test_rolling_an_eccentric_reducer_over_puts_the_flat_side_underneath():
    """Flat on the bottom is the same fitting turned over, for the line that has
    to drain rather than vent. It is a placement, not another symbol, and both
    nozzles stay on the faces the run enters and leaves by."""
    flat_top = _placed_eccentric(False)
    flat_bottom = _placed_eccentric("y")
    assert flat_top.frame.h == flat_bottom.frame.h

    def offsets(unit):
        return {name: port_point(unit, unit.frame, name)[1] - unit.frame.y for name in unit.ports}

    up, down = offsets(flat_top), offsets(flat_bottom)
    # Flat on top: the small end is the higher of the two. Rolled over, it is
    # the lower one, and every nozzle is its own reflection in the box.
    assert up["outlet"] < up["inlet"]
    assert down["outlet"] > down["inlet"]
    for name in up:
        assert up[name] + down[name] == pytest.approx(flat_top.frame.h, abs=0.15)


def test_an_eccentric_expansion_keeps_the_flat_side_it_was_drawn_with():
    """Turning a fitting end for end is a mirror across the *vertical*, so it
    cannot move the flat side: an eccentric expander out of a pump discharge is
    still flat on top unless the placement rolls it over."""
    sym = registry.for_unit(units.Reducer("RD-B", variant="eccentric", large_end="outlet"))
    # The large end is now the outlet, and it is the *inlet* whose centreline
    # has dropped -- the flat top is where it was.
    assert sym.ports["inlet"][1] < sym.ports["outlet"][1]


# --- the derivation itself ----------------------------------------------------


def test_only_a_two_ended_fitting_can_be_turned_end_for_end():
    """Every nozzle has to be accounted for: a symbol whose connections this
    cannot move would come back short of one, and a port the symbol does not
    anchor falls back to the middle of its own box."""
    with pytest.raises(ValueError, match="two ends to trade"):
        expander(registry.get("pump", "default"))
    with pytest.raises(ValueError, match="two ends to trade"):
        expander(registry.get("valve", "control"))  # inlet, outlet and actuator


def test_the_turned_drawing_is_built_once_and_shared():
    """Port resolution asks for a unit's symbol on every call, so a derivation
    rebuilt each time would redraw the artwork for every nozzle lookup."""
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
    # A reduction is what a reducer without the word already is, so only the
    # expansion is written down.
    assert "large_end" not in entries["RD-306A"]
    assert entries["RD-306B"]["large_end"] == "outlet"
    ends = {u.name: u.large_end for u in spec.from_dict(data).units}
    assert ends == {"RD-306A": "inlet", "RD-306B": "outlet"}


def test_only_a_reducer_takes_a_large_end():
    with pytest.raises(spec.SpecError, match="only a Reducer takes 'large_end'"):
        spec.from_dict(
            {
                "name": "wrong owner",
                "units": [{"kind": "Valve", "name": "HV-1", "large_end": "outlet"}],
            }
        )
