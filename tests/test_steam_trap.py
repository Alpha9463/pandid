"""The steam trap: ISO 10628-2 Table 2 item 24.15, registered 2181 (#367).

Every steam system has one at each low point and each drip leg, and until
this landed the library had no way to draw one. The gap was not silent --
``fitting/steam_trap`` was refused by ``SymbolRegistry.get`` rather than
answered with something else -- but it was worked round in a shipped
example, which drew its trap as a ``Product`` boundary flag: a sheet edge
standing in for a device in the run.

The measurements below are the row's, read off the standard's own modular
grid. They are asserted from the drawing rather than from the constants
that produced it wherever the two can differ, since a test that recomputes
the artwork from the same numbers the artwork was built from proves only
that Python arithmetic is deterministic.
"""

import math
import xml.etree.ElementTree as ET

import pytest

from pandid import Feed, Fitting, Flowsheet, Product, SteamTrap
from pandid.render.drawio import _APPROXIMATIONS
from pandid.render.symbols import default_registry

#: The drawing, resolved once. ``get`` raises for an unregistered variant,
#: so on a checkout without this change every test in the file errors here
#: rather than failing an assertion -- which is the honest report: there is
#: no drawing to measure.
TRAP = default_registry.get("fitting", "steam_trap")

#: What the row is drawn on. Table 2's grid module is 10 drawing units in
#: this library, the scale ``_MIXER_W`` and ``_SCREEN_W`` are stated at.
M = 10.0


def _elements() -> "list[ET.Element]":
    """The drawing's painted elements, in the order they are painted."""
    return list(ET.fromstring(TRAP.svg))


def test_the_registry_draws_a_steam_trap():
    """The variant exists at all, which is the whole of #367.

    Before this change ``Fitting("T-1", variant="steam_trap")`` constructed
    and then refused to render: the class does not name its variants, so
    the registry is where the name is answered.
    """
    assert ("fitting", "steam_trap") in default_registry._symbols
    assert "steam_trap" in default_registry.variants("fitting")


def test_the_body_is_a_circle_four_modules_across_on_the_run():
    """**Measured off the row:** the body is a circle 4 M across, centred on
    a grid node, with the run on its own horizontal diameter.

    Asserted on the drawn ``<circle>`` rather than on the constants, so a
    later edit that moved the body without moving the ports is caught.
    """
    circles = [el for el in _elements() if el.tag == "circle"]
    assert len(circles) == 1, "the body is one circle"
    body = circles[0]
    radius = float(body.get("r", "0"))
    cx, cy = float(body.get("cx", "0")), float(body.get("cy", "0"))

    assert radius * 2 == pytest.approx(4 * M)
    # Centred across the box's height, and the run is on that centreline.
    assert cy == pytest.approx(TRAP.height / 2)
    assert TRAP.ports["inlet"][1] == pytest.approx(cy)
    assert TRAP.ports["outlet"][1] == pytest.approx(cy)
    # One module of lead each side, so the box holds the body and both.
    assert cx - radius == pytest.approx(M)
    assert TRAP.width - (cx + radius) == pytest.approx(M)


def test_the_mark_is_a_diameter_at_45_degrees_with_the_half_below_it_filled():
    """**Measured off the row:** a full diameter across the body at 45
    degrees, from its lower left to its upper right, with the half below
    that line filled solid. That contrast is the whole of what tells this
    row from a plain circle, so it is asserted as geometry and not as a
    substring.

    The filled path is closed back along the diameter itself, so the two
    ends of the ``Z`` are the two ends of the diameter: both on the circle,
    the midpoint on its centre, and the line at 45 degrees. Checking all
    three is what distinguishes a diameter from a chord that merely looks
    like one.
    """
    filled = [
        el
        for el in _elements()
        if el.tag == "path" and (el.get("fill") or "none") not in ("none", "white")
    ]
    assert len(filled) == 1, "one filled region: the discharge half"
    body = next(el for el in _elements() if el.tag == "circle")
    cx, cy = float(body.get("cx", "0")), float(body.get("cy", "0"))
    radius = float(body.get("r", "0"))

    tokens = (filled[0].get("d") or "").replace(",", " ").split()
    assert tokens[0] == "M" and tokens[-1] == "Z"
    start = (float(tokens[1]), float(tokens[2]))
    # The last coordinate pair written before the close is the other end.
    end = (float(tokens[-3]), float(tokens[-2]))

    for point in (start, end):
        assert math.dist(point, (cx, cy)) == pytest.approx(radius), "an end off the body"
    assert (start[0] + end[0]) / 2 == pytest.approx(cx), "not a diameter"
    assert (start[1] + end[1]) / 2 == pytest.approx(cy), "not a diameter"
    # 45 degrees, and running from the body's lower left to its upper right.
    run, rise = end[0] - start[0], end[1] - start[1]
    assert abs(rise) == pytest.approx(abs(run)), "the diameter is not at 45 degrees"
    assert run > 0 and rise < 0, "the diameter runs the other way"
    # The filled half is the one below the diameter: the point a quarter turn
    # clockwise from its lower-left end is inside the path's own extent.
    assert start[0] < cx and start[1] > cy, "the fill starts at the wrong end"


def test_the_two_nozzles_sit_on_the_run_at_the_ends_of_the_box():
    """A fitting is a pair of faces on a line, and the leads are what the
    stream actually meets. Table 2 stops its connecting line 1 M short of
    the body; a port off ink draws a stream stopping short of its device,
    so the same module is drawn as real line here.
    """
    assert set(TRAP.ports) == {"inlet", "outlet"}
    assert TRAP.ports["inlet"] == (0.0, TRAP.height / 2)
    assert TRAP.ports["outlet"] == (TRAP.width, TRAP.height / 2)


def test_the_drawing_is_the_row_rather_than_the_placeholder_stencil():
    """The point of the change. draw.io's own "Steam Trap" is an empty
    rectangle byte-identical to its "Desuper Heater", so the drawing had to
    be made rather than vendored -- and this asserts the result is neither
    that stencil nor the empty fallback it converts to.
    """
    assert TRAP.drawio_shape == "", "a hand-drawn symbol names no stencil"
    assert TRAP.drawio_body_shape == "", "not a composition"
    assert TRAP.svg != default_registry._generic_symbol().svg
    # An empty box has one element and no fill; this has a body, a mark and
    # the run, and paints ink into the body.
    assert len(_elements()) == 3
    assert 'fill="#111"' in TRAP.svg


def test_the_drawing_is_ruled_as_a_piping_accessory_and_keeps_its_shape():
    """ISO 10628-1 clause 5.3.1 c) rules a piping accessory at half the
    equipment weight, which every other ``Fitting`` variant is drawn at.

    And the roundness carries meaning: the mark is a diameter at 45
    degrees, so a body stretched to a box of another proportion is an
    ellipse whose mark is at some other angle, with the halves no longer
    halves.
    """
    assert TRAP.trim is True
    assert TRAP.stretchable is False
    assert TRAP.iso_reg == "2181"
    # Not gravity-fixed: the mark is a marking, not a drawn liquid surface,
    # and nothing in the body depicts holdup. See Symbol.gravity_fixed.
    assert TRAP.gravity_fixed is False


def test_the_class_and_the_variant_reach_the_one_drawing():
    """``SteamTrap("T-1")`` is what an engineer types; the variant spelling
    stays reachable because that is how the other 132 classless drawings
    are asked for.
    """
    assert SteamTrap("T-1").variant == "steam_trap"
    assert default_registry.for_unit(SteamTrap("T-1")) is TRAP
    assert default_registry.for_unit(Fitting("T-2", variant="steam_trap")) is TRAP


def test_the_svg_backend_draws_it_on_a_sheet(tmp_path):
    """End to end: a trap in a run reaches the sheet as its own definition,
    with the run drawn to both of its faces.
    """
    fs = Flowsheet("Trap")
    steam = fs.add(Feed("Steam"))
    trap = fs.add(SteamTrap("T-701"))
    drain = fs.add(Product("Condensate"))
    fs.connect(steam.outlet, trap.inlet)
    fs.connect(trap.outlet, drain.inlet)
    path = tmp_path / "trap.svg"
    fs.render(str(path))

    sheet = path.read_text(encoding="utf-8")
    assert "sym_fitting_steam_trap" in sheet
    assert "T-701" in sheet


def test_the_drawio_backend_says_what_its_stand_in_loses():
    """The other half of "both backends". draw.io has no stencil for this
    drawing -- the one it has draws nothing -- so the export stands the
    body in with a built-in ellipse and **reports** what that costs.

    Reporting is the requirement, not the ellipse: a stand-in nobody wrote
    down is indistinguishable from a mistake, and an export that quietly
    drew a plain circle for a steam trap would be #367 again in a different
    file.
    """
    approximation = _APPROXIMATIONS[("fitting", "steam_trap")]
    assert approximation.shape == "ellipse"
    assert approximation.lost, "a stand-in has to say what it loses"

    fs = Flowsheet("Trap")
    steam = fs.add(Feed("Steam"))
    trap = fs.add(SteamTrap("T-701"))
    drain = fs.add(Product("Condensate"))
    fs.connect(steam.outlet, trap.inlet)
    fs.connect(trap.outlet, drain.inlet)
    document = fs.to_drawio()

    assert "shape=ellipse" in document
    warnings = [
        issue
        for issue in fs.warnings
        if issue.code == "drawio-approximated" and "T-701" in issue.message
    ]
    assert len(warnings) == 1, "exactly one report, naming the unit"
    assert approximation.lost in warnings[0].message
