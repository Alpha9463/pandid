"""Check the steam trap, ISO 10628-2 Table 2 item 24.15 (2181), in both backends."""

import math
import re
import xml.etree.ElementTree as ET

import pytest
from test_symbol_invariants import _script

from pandid import Feed, Fitting, Flowsheet, Product, SteamTrap
from pandid.render.drawio import _APPROXIMATIONS
from pandid.render.symbols import default_registry

#: The drawing, resolved once.
TRAP = default_registry.get("fitting", "steam_trap")

#: Table 2's grid module, in drawing units.
M = 10.0


def _elements() -> "list[ET.Element]":
    """The drawing's painted elements, in the order they are painted."""
    return list(ET.fromstring(TRAP.svg))


def test_the_registry_draws_a_steam_trap():
    """Check that ``fitting/steam_trap`` is a registered variant."""
    assert ("fitting", "steam_trap") in default_registry._symbols
    assert "steam_trap" in default_registry.variants("fitting")


def test_the_body_is_a_circle_four_modules_across_on_the_run():
    """Check that the body is a 4 M circle on the run with 1 M of lead each side."""
    circles = [el for el in _elements() if el.tag == "circle"]
    assert len(circles) == 1, "the body is one circle"
    body = circles[0]
    radius = float(body.get("r", "0"))
    cx, cy = float(body.get("cx", "0")), float(body.get("cy", "0"))

    assert radius * 2 == pytest.approx(4 * M)
    assert cy == pytest.approx(TRAP.height / 2)
    assert TRAP.ports["inlet"][1] == pytest.approx(cy)
    assert TRAP.ports["outlet"][1] == pytest.approx(cy)
    # One module of lead each side, so the box holds the body and both.
    assert cx - radius == pytest.approx(M)
    assert TRAP.width - (cx + radius) == pytest.approx(M)


def _filled_region():
    """Return the filled mark's chord ends and the midpoints of its two arcs."""
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
    """Check that the mark is a 45 degree diameter with the half below it filled."""
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

    # Every arc midpoint is on the body and on the painted side of the diameter.
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

    # Below right of the diameter is ink and above left is white, at half the radius.
    assert inside((cx + radius / 2, cy + radius / 2)), (
        "the half below the diameter is not the half that is filled"
    )
    assert not inside((cx - radius / 2, cy - radius / 2)), (
        "the half above the diameter is filled, which is the other drawing"
    )
    assert inside((cx, cy + radius / 2))
    assert not inside((cx, cy - radius / 2))


def test_the_two_nozzles_sit_on_the_run_at_the_ends_of_the_box():
    """Check that the inlet and outlet sit on the run at the ends of the box."""
    assert set(TRAP.ports) == {"inlet", "outlet"}
    assert TRAP.ports["inlet"] == (0.0, TRAP.height / 2)
    assert TRAP.ports["outlet"] == (TRAP.width, TRAP.height / 2)


def test_the_drawing_is_the_row_rather_than_the_placeholder_stencil():
    """Check that the trap is drawn from the row, not a stencil or the empty fallback."""
    assert TRAP.drawio_shape == "", "a hand-drawn symbol names no stencil"
    assert TRAP.drawio_body_shape == "", "not a composition"
    assert TRAP.svg != default_registry._generic_symbol().svg
    # A body, a mark and the run, with ink in the body.
    assert len(_elements()) == 3
    assert 'fill="#111"' in TRAP.svg


def test_the_drawing_is_ruled_as_a_piping_accessory_and_keeps_its_shape():
    """Check that the trap is trimmed, not stretchable, not gravity-fixed and numbered 2181."""
    assert TRAP.trim is True
    assert TRAP.stretchable is False
    assert TRAP.iso_reg == "2181"
    # Not gravity-fixed: the mark depicts no liquid surface.
    assert TRAP.gravity_fixed is False


def test_the_class_and_the_variant_reach_the_one_drawing():
    """Check that ``SteamTrap`` and ``Fitting(variant="steam_trap")`` draw the same symbol."""
    assert SteamTrap("T-1").variant == "steam_trap"
    assert default_registry.for_unit(SteamTrap("T-1")) is TRAP
    assert default_registry.for_unit(Fitting("T-2", variant="steam_trap")) is TRAP


def test_the_svg_backend_draws_it_on_a_sheet(tmp_path):
    """Check that a rendered sheet uses the trap's definition."""
    fs, _steam, _trap, _drain = _trap_sheet()
    path = tmp_path / "trap.svg"
    fs.render(str(path))

    sheet = path.read_text(encoding="utf-8")
    assert "sym_fitting_steam_trap" in sheet
    assert "T-701" in sheet


def _trap_sheet(**kwargs):
    """A steam feed, a trap and a condensate product in one run."""
    fs = Flowsheet("Trap")
    steam = fs.add(Feed("Steam"))
    trap = fs.add(SteamTrap("T-701", **kwargs))
    drain = fs.add(Product("Condensate"))
    fs.connect(steam.outlet, trap.inlet)
    fs.connect(trap.outlet, drain.inlet)
    return fs, steam, trap, drain


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
    """Check that the draw.io cell has a body ellipse and two leads matching the SVG symbol."""
    document = _trap_sheet()[0].to_drawio()
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
    assert body["x"] == pytest.approx(cx - radius)
    assert body["width"] == pytest.approx(2 * radius)
    assert body["height"] == pytest.approx(TRAP.height)
    assert west["x"] == pytest.approx(0.0)
    assert west["width"] == pytest.approx(cx - radius)
    assert east["x"] + east["width"] == pytest.approx(TRAP.width)
    assert east["width"] == pytest.approx(TRAP.width - (cx + radius))
    assert "steam_trap" not in document


def test_the_drawio_backend_reports_the_mark_it_cannot_draw():
    """Check that the draw.io export reports once the mark it cannot draw."""
    approximation = _APPROXIMATIONS[("fitting", "steam_trap")]
    assert approximation.lost, "a stand-in has to say what it loses"
    fs = _trap_sheet()[0]
    fs.to_drawio()
    reports = [
        issue
        for issue in fs.warnings
        if issue.code == "drawio-approximated" and "T-701" in issue.message
    ]
    assert len(reports) == 1, "exactly one report, naming the unit"
    assert approximation.lost in reports[0].message


def test_the_drawio_backend_reports_a_body_it_will_reproportion():
    """Check that the draw.io export reports a reshaped trap, and only then."""

    def reshape_reports(fs):
        return [
            issue
            for issue in fs.warnings
            if issue.code == "drawio-approximated" and "reproportioned" in issue.message
        ]

    plain = _trap_sheet()[0]
    plain.to_drawio()
    assert reshape_reports(plain) == [], "a trap at its own shape has nothing to report"

    wide = _trap_sheet(width=TRAP.width * 2, height=TRAP.height)[0]
    wide.to_drawio()
    reports = reshape_reports(wide)
    assert len(reports) == 1, "a reshaped trap is reported once"
    assert "T-701" in reports[0].message


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_every_nozzle_lands_on_drawn_ink_however_the_trap_is_turned(rot):
    """Check that each exported nozzle lands on a lead at every orientation."""
    fs, steam, trap, drain = _trap_sheet()
    # Pinned well apart, since the trap is turned by hand.
    steam.pin(x=100.0, y=300.0)
    trap.pin(x=500.0, y=300.0, orientation=rot)
    drain.pin(x=1000.0, y=300.0)
    document = fs.to_drawio()
    root = ET.fromstring(document)

    cells = _cells(document)
    cid = next(
        cell.get("id", "")
        for cell in root.iter("mxCell")
        if cell.get("value") == "T-701" and cell.get("vertex") == "1"
    )
    _parent_style, box = cells[cid]
    pieces = [cells[key][1] for key in sorted(cells) if key.startswith(cid + "-s")]
    assert len(pieces) == 3
    leads = [pieces[0], pieces[2]]

    fractions = []
    for edge in root.iter("mxCell"):
        if not edge.get("edge"):
            continue
        style = edge.get("style") or ""
        for prefix, end in (("entry", "target"), ("exit", "source")):
            if edge.get(end) != cid:
                continue
            found = re.search(prefix + r"X=([-\d.]+);" + prefix + r"Y=([-\d.]+)", style)
            if found:
                fractions.append((float(found.group(1)), float(found.group(2))))
    assert len(fractions) == 2, "the trap has two nozzles and both are piped"

    for fx, fy in fractions:
        px, py = fx * box["width"], fy * box["height"]
        assert any(
            lead["x"] - 0.02 <= px <= lead["x"] + lead["width"] + 0.02
            and lead["y"] - 0.02 <= py <= lead["y"] + lead["height"] + 0.02
            for lead in leads
        ), (
            f"at orientation {rot} the nozzle at ({px:g}, {py:g}) is on no lead: "
            f"the export drew its ink somewhere the stream does not arrive"
        )
