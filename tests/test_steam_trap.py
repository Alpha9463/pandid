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

import importlib.util
import math
import pathlib
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from pandid import Feed, Fitting, Flowsheet, Product, SteamTrap
from pandid.render.drawio import _APPROXIMATIONS
from pandid.render.symbols import default_registry

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _script(name: str) -> Any:
    """One of the dev-only generator scripts, imported by path.

    ``scripts/`` is not a package, and importing from it by putting the
    directory on ``sys.path`` at run time leaves a name no type checker
    can resolve. Same approach as ``tests/test_symbol_invariants``.
    """
    spec = importlib.util.spec_from_file_location(
        f"_pandid_script_{name}", ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _filled_region():
    """The painted half, as ``(centre, radius, chord ends, arc midpoints)``.

    The path is parsed rather than assumed: the endpoints say where the
    diameter is, and the arcs say **which side of it** is painted. Both
    have to be read, because a chord is the same chord whichever half it
    bounds -- flip the two sweep flags and every endpoint in the ``d``
    stays exactly where it was while the ink moves to the other half.

    The endpoint-to-centre conversion is the one already in this
    repository (``scripts/mxgraph_to_svg``, SVG 1.1 Appendix F.6.5),
    rather than a second copy written for a test.
    """
    _endpoint_to_center = _script("mxgraph_to_svg")._endpoint_to_center

    filled = [
        el
        for el in _elements()
        if el.tag == "path" and (el.get("fill") or "none") not in ("none", "white")
    ]
    assert len(filled) == 1, "one filled region: the discharge half"
    tokens = (filled[0].get("d") or "").replace(",", " ").split()
    assert tokens[0] == "M" and tokens[-1] == "Z"

    here = (float(tokens[1]), float(tokens[2]))
    start = here
    midpoints = []
    i = 3
    while i < len(tokens) and tokens[i] == "A":
        rx, ry, rot = (float(v) for v in tokens[i + 1 : i + 4])
        large, sweep = (int(float(v)) for v in tokens[i + 4 : i + 6])
        end_pt = (float(tokens[i + 6]), float(tokens[i + 7]))
        cx, cy, arx, _ary, theta1, dtheta = _endpoint_to_center(
            here[0], here[1], rx, ry, math.radians(rot), large, sweep, end_pt[0], end_pt[1]
        )
        half = theta1 + dtheta / 2
        midpoints.append((cx + arx * math.cos(half), cy + arx * math.sin(half)))
        here = end_pt
        i += 8
    assert i == len(tokens) - 1, "the mark is two arcs closed by the diameter"
    return start, here, midpoints


def test_the_mark_is_a_diameter_at_45_degrees_with_the_half_below_it_filled():
    """**Measured off the row:** a full diameter across the body at 45
    degrees, from its lower left to its upper right, with the half below
    that line filled solid. That contrast is the whole of what tells this
    row from a plain circle.

    Both halves of the claim are asserted, and the second one is the one
    that is easy to leave untested: the diameter is checked from the two
    endpoints, and **which side is painted** is checked by sampling a
    point that has to be in the ink and one that has to be in the white.
    Membership is decided from the arcs the path actually draws, so a mark
    whose arcs bulge the wrong way fails here rather than passing on
    endpoints that never moved.
    """
    body = next(el for el in _elements() if el.tag == "circle")
    cx, cy = float(body.get("cx", "0")), float(body.get("cy", "0"))
    radius = float(body.get("r", "0"))
    start, end, midpoints = _filled_region()

    for point in (start, end):
        assert math.dist(point, (cx, cy)) == pytest.approx(radius), "an end off the body"
    assert (start[0] + end[0]) / 2 == pytest.approx(cx), "not a diameter"
    assert (start[1] + end[1]) / 2 == pytest.approx(cy), "not a diameter"
    run, rise = end[0] - start[0], end[1] - start[1]
    assert abs(rise) == pytest.approx(abs(run)), "the diameter is not at 45 degrees"
    assert run > 0 and rise < 0, "the diameter runs the other way"

    # Every arc midpoint is on the body, and on the painted side of the
    # diameter -- which is what the sweep flags decide and nothing else in
    # the path records.
    assert len(midpoints) == 2
    for point in midpoints:
        assert math.dist(point, (cx, cy)) == pytest.approx(radius, abs=1e-6)

    def side(point):
        return math.copysign(
            1.0,
            run * (point[1] - start[1]) - rise * (point[0] - start[0]),
        )

    painted = side(midpoints[0])
    assert side(midpoints[1]) == painted, "the two arcs bound different halves"

    def inside(point):
        return math.dist(point, (cx, cy)) < radius and side(point) == painted

    # Down and to the right of the diameter is ink; up and to the left is
    # white. Sampled at half the radius, so neither point is near an edge.
    assert inside((cx + radius / 2, cy + radius / 2)), (
        "the half below the diameter is not the half that is filled"
    )
    assert not inside((cx - radius / 2, cy - radius / 2)), (
        "the half above the diameter is filled, which is the other drawing"
    )
    # And the foot of the body is ink while its crown is not, which is the
    # same statement taken on the axis the reader actually looks at.
    assert inside((cx, cy + radius / 2))
    assert not inside((cx, cy - radius / 2))


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


def _trap_sheet(**kwargs):
    """A trap in a run, as a rendered draw.io document and its warnings."""
    fs = Flowsheet("Trap")
    steam = fs.add(Feed("Steam"))
    trap = fs.add(SteamTrap("T-701", **kwargs))
    drain = fs.add(Product("Condensate"))
    fs.connect(steam.outlet, trap.inlet)
    fs.connect(trap.outlet, drain.inlet)
    return fs.to_drawio(), fs


def _cells(document):
    """Every ``<mxCell>`` in *document*, as ``{id: (style, geometry)}``."""
    out = {}
    for cell in ET.fromstring(document).iter("mxCell"):
        geometry = cell.find("mxGeometry")
        if geometry is None:
            continue
        style = dict(
            part.split("=", 1) for part in (cell.get("style") or "").split(";") if "=" in part
        )
        out[cell.get("id")] = (
            style,
            {k: float(geometry.get(k, 0)) for k in ("x", "y", "width", "height")},
        )
    return out


def test_the_drawio_backend_draws_the_body_and_both_leads():
    """The other half of "both backends", and the part an ``ellipse`` over
    the whole cell got wrong.

    draw.io has no stencil for this drawing -- the one it has draws
    nothing -- so the export is a stand-in. But a stand-in is still held
    to drawing what it *can*: the body is 4 M of a 6 M box, so one ellipse
    filling the cell would be an oval half again too wide and would
    swallow both leads, and a reader would take the body outline on trust
    because the warning talks about the mark.

    So the cell carries three pieces, and they are measured here against
    the **SVG** symbol rather than against numbers written twice: the body
    ellipse has to cover exactly the circle's span, and each lead exactly
    the run drawn beside it.
    """
    document, _fs = _trap_sheet()
    cells = _cells(document)
    parent = next(cid for cid, (style, _g) in cells.items() if style.get("strokeColor") == "none")
    pieces = [cells[cid] for cid in sorted(cells) if cid.startswith(f"{parent}-s")]
    assert len(pieces) == 3, "the run, the body and the run"

    _style, box = cells[parent]
    assert (box["width"], box["height"]) == (TRAP.width, TRAP.height)

    circle = next(el for el in _elements() if el.tag == "circle")
    cx, radius = float(circle.get("cx", "0")), float(circle.get("r", "0"))

    (west_style, west), (body_style, body), (east_style, east) = pieces
    assert body_style.get("shape") == "ellipse"
    assert west_style.get("shape") == "line" and east_style.get("shape") == "line"
    # The body covers the circle and nothing else.
    assert body["x"] == pytest.approx(cx - radius)
    assert body["width"] == pytest.approx(2 * radius)
    assert body["height"] == pytest.approx(TRAP.height)
    # A lead each side of it, meeting the box edges the nozzles are on.
    assert west["x"] == pytest.approx(0.0)
    assert west["width"] == pytest.approx(cx - radius)
    assert east["x"] + east["width"] == pytest.approx(TRAP.width)
    assert east["width"] == pytest.approx(TRAP.width - (cx + radius))
    # No stencil is named anywhere: the one draw.io has draws nothing.
    assert "steam_trap" not in document


def test_the_drawio_backend_reports_the_mark_it_cannot_draw():
    """What is left after the body and the leads is the mark, and no
    built-in draws a chord across an ellipse or fills one side of it.

    Reporting is the requirement: a stand-in nobody wrote down is
    indistinguishable from a mistake, and an export that quietly drew a
    plain circle for a steam trap would be #367 again in a different file.
    """
    approximation = _APPROXIMATIONS[("fitting", "steam_trap")]
    assert approximation.lost, "a stand-in has to say what it loses"
    _document, fs = _trap_sheet()
    reports = [
        issue
        for issue in fs.warnings
        if issue.code == "drawio-approximated" and "T-701" in issue.message
    ]
    assert len(reports) == 1, "exactly one report, naming the unit"
    assert approximation.lost in reports[0].message


def test_the_drawio_backend_reports_a_body_it_will_reproportion():
    """The trap keeps its shape and draw.io cannot be told to.

    ``stretchable=False`` is honoured on the sheet --
    :func:`~pandid.portgeom.ink_box` centres the drawing and leaves the
    letterbox blank -- and there is no way to ask a built-in ``ellipse``
    to stay a circle, so an author who sizes a trap to a box of another
    shape gets a drawing the two backends disagree about.

    That divergence is real and it must not be silent, which is the whole
    of this backend's promise. It is reported, and it is reported *only*
    when it happens: a trap at its own proportions says nothing.
    """

    def reshape_reports(fs):
        return [
            issue
            for issue in fs.warnings
            if issue.code == "drawio-approximated" and "reproportioned" in issue.message
        ]

    _plain, plain = _trap_sheet()
    assert reshape_reports(plain) == [], "a trap at its own shape has nothing to report"

    _wide, wide = _trap_sheet(width=TRAP.width * 2, height=TRAP.height)
    reports = reshape_reports(wide)
    assert len(reports) == 1, "a reshaped trap is reported once"
    assert "T-701" in reports[0].message
