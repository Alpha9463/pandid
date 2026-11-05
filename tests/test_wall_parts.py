"""Test manholes and sockets placed on a vessel's walls (ISO 10628-2 26.5, 26.6)."""

import math
import re

import pytest

from pandid import Evaporator, Feed, Flowsheet, Product, Vessel
from pandid.portgeom import outward_dir, port_point, resolve_size
from pandid.render.iso_parts import MANHOLE_DEPTH, MANHOLE_SPAN, SOCKET_DEPTH, SOCKET_SPAN
from pandid.render.symbols import PortSeries, default_registry, overlay_boxes
from pandid.spec import SpecError, from_dict, to_dict
from pandid.units import _drawn_parts
from test_symbol_invariants import GEOM_TOL, _collect_segments, _nearest_distance


def _parts(unit):
    """Return each overlay on a unit's drawing with its box and the drawing."""
    sym = unit.symbol()
    body = _drawn_parts(unit, unit.__dict__.get("overlays", ()))[0]
    return list(zip(sym.overlays, overlay_boxes(body, sym.overlays))), sym, body


def _drawn_size(unit, box):
    """Return a part box's width and height as drawn in the unit's box."""
    sym = unit.symbol()
    across = (unit.width or sym.width) / sym.width
    down = (unit.height or sym.height) / sym.height
    return (box[2] - box[0]) * across, (box[3] - box[1]) * down


def test_a_manhole_stands_on_the_stated_wall_at_the_stated_fraction():
    """Check that ('E', 0.3) puts the manhole against the east wall, 0.3 of the way down."""
    vessel = Vessel("D-101", manholes=[("E", 0.3)])
    [(overlay, box)], sym, body = _parts(vessel)
    assert overlay.name == "manhole" and overlay.mirror
    # The body sits at the composed box's left edge; the manhole grows it east.
    assert box[0] == pytest.approx(body.width)
    assert (box[1] + box[3]) / 2 == pytest.approx(0.3 * body.height)
    assert sym.width == pytest.approx(body.width + MANHOLE_DEPTH)


def test_a_fraction_is_measured_as_a_column_feed_stage_is():
    """Check that a wall part and a pinned port series put one fraction at one point."""
    body = default_registry.get("vessel", "default")
    for face, fraction in (("W", 0.25), ("E", 0.6)):
        vessel = Vessel("D-1", sockets=[(face, fraction)])
        series = PortSeries("x_", face).placement(
            0, 1, body.width, body.height, pin=fraction, band=body.bands[face]
        )
        assert vessel.symbol().ports["socket_1"][1] == pytest.approx(series[1])


@pytest.mark.parametrize("height", [None, 300.0, 60.0])
@pytest.mark.parametrize("width", [None, 140.0])
def test_a_wall_part_is_drawn_at_its_own_size_whatever_the_box(width, height):
    """Check that a manhole and a socket keep their size on a stretched or squashed vessel."""
    vessel = Vessel(
        "T-101", width=width, height=height, manholes=[("E", 0.3)], sockets=[("W", 0.6)]
    )
    sizes = [_drawn_size(vessel, box) for _, box in _parts(vessel)[0]]
    assert sizes[0] == pytest.approx((MANHOLE_DEPTH, MANHOLE_SPAN))
    assert sizes[1] == pytest.approx((SOCKET_DEPTH, SOCKET_SPAN))


def test_a_tall_column_carries_several_manholes_in_the_order_given():
    """Check that each of several manholes is drawn where its fraction says."""
    tower = Vessel("T-101", height=300, manholes=[("E", 0.25), ("E", 0.5), ("W", 0.75)])
    placed, _, body = _parts(tower)
    assert [(o.name, o.mirror) for o, _ in placed] == [
        ("manhole", True),
        ("manhole", True),
        ("manhole", False),
    ]
    centres = [(box[1] + box[3]) / 2 / body.height for _, box in placed]
    assert centres == pytest.approx([0.25, 0.5, 0.75])
    assert "manhole_1" not in tower.ports


def test_a_roof_and_a_floor_part_point_away_from_the_drum():
    """Check that a north part is drawn above a lying drum and a south one below."""
    drum = Vessel("D-102", variant="horizontal", manholes=[("N", 0.6)], sockets=[("S", 0.4)])
    placed, sym, body = _parts(drum)
    (manhole, up), (socket, down) = placed
    assert (manhole.name, socket.name) == ("manhole_up", "socket_down")
    assert up[3] == pytest.approx(MANHOLE_DEPTH)  # its foot on the roof, which moved down
    assert down[1] == pytest.approx(MANHOLE_DEPTH + body.height)
    assert sym.ports["socket_1"] == pytest.approx((0.4 * body.width, sym.height))


def test_a_socket_is_an_outlet_a_line_connects_to_where_it_is_drawn():
    """Check that socket_1 and socket_2 are numbered in order and take a line at the flange."""
    fs = Flowsheet("sockets")
    vessel = fs.add(Vessel("D-101", sockets=[("W", 0.7), ("E", 0.25)]))
    feed, sample, vent = fs.add(Feed("Feed")), fs.add(Product("Sample")), fs.add(Product("Vent"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.port("socket_1"), sample.inlet)
    fs.connect(vessel.port("socket_2"), vent.inlet)
    fs.to_svg(diagram="p&id")
    assert fs.validate() == []
    first, second = vessel.port("socket_1"), vessel.port("socket_2")
    assert (first.direction, second.direction) == ("outlet", "outlet")
    frame = vessel.frame
    assert frame is not None
    x, y = port_point(vessel, frame, "socket_1")
    assert x == pytest.approx(frame.x)  # the flange face is the box's west edge
    assert (y - frame.y) / frame.h == pytest.approx(0.7, abs=1e-6)
    x, _ = port_point(vessel, frame, "socket_2")
    assert x == pytest.approx(frame.x + frame.w)


def test_a_vessel_with_wall_parts_pins_by_a_nozzle():
    """Check that a vessel with a manhole lands its pinned nozzle on the pin."""
    fs = Flowsheet("pinned")
    vessel = fs.add(Vessel("D-101", manholes=[("E", 0.3)])).pin(x=200, y=100, port="inlet")
    fs.connect(fs.add(Feed("Feed")).outlet, vessel.inlet)
    fs.to_svg(diagram="p&id")
    frame = vessel.frame
    assert frame is not None
    assert port_point(vessel, frame, "inlet") == pytest.approx((200, 100))


def test_a_socket_takes_no_line_in():
    """Check that a socket refuses to be a line's destination."""
    fs = Flowsheet("sockets")
    vessel = fs.add(Vessel("D-101", sockets=[("W", 0.7)]))
    feed = fs.add(Feed("Feed"))
    with pytest.raises(ValueError, match="outlet"):
        fs.connect(feed.outlet, vessel.port("socket_1"))


def test_an_evaporator_carries_them_on_its_shell():
    """Check that an evaporator takes manholes and sockets on its W and E shell."""
    evaporator = Evaporator("E-101", manholes=[("E", 0.3)], sockets=[("W", 0.8)])
    placed, sym, body = _parts(evaporator)
    assert [o.name for o, _ in placed] == ["manhole", "socket"]
    assert sym.ports["socket_1"] == pytest.approx((0.0, 0.8 * body.height))
    with pytest.raises(ValueError, match="no clear straight wall; put it on 'W' or 'E'"):
        Evaporator("E-102", sockets=[("N", 0.5)])


@pytest.mark.parametrize("kind", ["vessel", "evaporator"])
def test_every_wall_a_part_stands_on_is_drawn_ink_at_the_box_edge(kind):
    """Check that each face a wall part may use is drawn wall along its whole band."""
    cls = {"vessel": Vessel, "evaporator": Evaporator}[kind]
    for variant in default_registry.variants(kind):
        body = default_registry.get(kind, variant)
        segments = _collect_segments(body.svg)
        for face, (lo, hi) in body.bands.items():
            along = body.height if face in ("W", "E") else body.width
            try:
                cls("X-1", variant=variant, sockets=[(face, (lo + hi) / 2 / along)])
            except ValueError:
                continue
            for t in (lo, (lo + hi) / 2, hi):
                point = {
                    "W": (0.0, t),
                    "E": (body.width, t),
                    "N": (t, 0.0),
                    "S": (t, body.height),
                }[face]
                distance = _nearest_distance(point, segments)
                assert distance <= GEOM_TOL, f"{kind}/{variant} {face} at {t} is off the wall"


@pytest.mark.parametrize(
    ("keyword", "given", "message"),
    [
        ("manholes", [("N", 0.5)], "on the N face, where a 'default' vessel has no clear"),
        ("sockets", [("E", 0.05)], r"off the E wall, which runs from 0\.18 to 0\.82"),
        ("manholes", [("E", 1.5)], "needs a fraction from 0 to 1"),
        ("manholes", [("E", -0.1)], "needs a fraction from 0 to 1"),
        ("sockets", [("E", math.nan)], "needs a fraction from 0 to 1"),
        ("sockets", [("E", math.inf)], "needs a fraction from 0 to 1"),
        ("sockets", [("E", "0.3")], "needs a fraction from 0 to 1"),
        ("sockets", [("E", True)], "needs a fraction from 0 to 1"),
        ("manholes", [("Q", 0.3)], "'Q' is not a face"),
        ("manholes", ("E", 0.3), r"takes a list of \(face, fraction\) pairs"),
        ("manholes", "E", r"takes a list of \(face, fraction\) pairs"),
        ("sockets", [("E",)], r"takes a list of \(face, fraction\) pairs"),
        ("sockets", [("E", 0.3, 1)], r"takes a list of \(face, fraction\) pairs"),
        ("sockets", None, r"takes a list of \(face, fraction\) pairs"),
    ],
)
def test_a_bad_placement_is_refused_naming_the_fix(keyword, given, message):
    """Check that each malformed or off-wall placement is refused with its cure."""
    with pytest.raises(ValueError, match=message):
        Vessel("D-101", **{keyword: given})


def test_a_variant_with_no_clear_wall_says_so():
    """Check that a body drawn with detail on its walls refuses them, naming another."""
    with pytest.raises(ValueError, match="draw it with variant='default'"):
        Vessel("D-101", variant="dished", manholes=[("W", 0.5)])
    with pytest.raises(ValueError, match="put it on 'W'"):
        Vessel("D-101", variant="electrical_heating", sockets=[("E", 0.5)])


@pytest.mark.parametrize("keyword", ["manholes", "sockets"])
def test_a_refused_change_leaves_the_vessel_as_it_was(keyword):
    """Check that a placement cannot be reassigned, and the refusal changes nothing."""
    vessel = Vessel("D-101", manholes=[("E", 0.3)], sockets=[("W", 0.6)])
    before = (vessel.manholes, vessel.sockets, list(vessel.ports), vessel.symbol())
    with pytest.raises(AttributeError, match="read-only"):
        setattr(vessel, keyword, [("Q", 9)])
    assert (vessel.manholes, vessel.sockets, list(vessel.ports), vessel.symbol()) == before


def test_the_placements_are_stored_as_given_and_cannot_be_edited_through_the_list():
    """Check that the vessel keeps its own copy of the placements."""
    given = [("E", 0.3)]
    vessel = Vessel("D-101", manholes=given)
    given.append(("W", 0.5))
    assert vessel.manholes == (("E", 0.3),)


def test_supports_refuses_a_wall_part_and_points_at_its_keyword():
    """Check that supports= takes only the four supports."""
    with pytest.raises(ValueError, match=r"manholes=\[\('E', 0\.3\)\]"):
        Vessel("D-101", supports="manhole")
    with pytest.raises(ValueError, match="did you mean 'leg'"):
        Vessel("D-101", supports="lgs")


def test_a_box_too_small_for_its_parts_is_refused():
    """Check that a stated size with no room left for the body is refused."""
    with pytest.raises(ValueError, match=r"give width=46 or more"):
        Vessel("D-101", width=20, manholes=[("E", 0.3)], sockets=[("W", 0.6)])


@pytest.mark.parametrize(
    ("build", "face", "names"),
    [
        (lambda: Vessel("D-101", width=50, inputs=4, manholes=[("W", 0.8)]), "W", "in_"),
        (lambda: Vessel("D-101", outputs=4, height=90, sockets=[("E", 0.6)]), "E", "out_"),
    ],
    ids=["narrow", "short"],
)
def test_a_stated_size_keeps_a_family_on_its_wall_beside_a_wall_part(build, face, names):
    """Check that a shell built to a stated size keeps every member nearest its face."""
    vessel = build()
    sym = vessel.symbol()
    w, h = resolve_size(vessel)
    assert (sym.width, sym.height) == (w, h), "the shell is built to the box, not scaled"
    for i in range(1, 5):
        x, y = sym.ports[f"{names}{i}"]
        assert outward_dir(x, y, w, h) == face, f"{names}{i}"


@pytest.mark.parametrize(
    ("build", "connect", "message"),
    [
        (
            lambda: Vessel("D-101", manholes=[("W", 0.5)]),
            "inlet",
            r"the line on in_1 meets it through the manhole at \('W', 0\.5\)",
        ),
        (
            lambda: Vessel("D-101", sockets=[("E", 0.5)]),
            "outlet",
            r"the line on out_1 meets it through the socket at \('E', 0\.5\)",
        ),
        (
            lambda: Vessel("D-101", supports="bracket", manholes=[("E", 0.7)]),
            "",
            r"the manhole at \('E', 0\.7\) is drawn over the bracket support",
        ),
        (
            lambda: Vessel("D-101", manholes=[("E", 0.3), ("E", 0.35)]),
            "",
            r"the manhole at \('E', 0\.35\) is drawn over the manhole at \('E', 0\.3\)",
        ),
    ],
    ids=["line-through-manhole", "line-through-socket", "over-a-bracket", "two-overlap"],
)
def test_a_wall_part_drawn_under_a_line_or_a_part_is_an_error(build, connect, message):
    """Check that validate() reports a clash a reader would misread."""
    fs = Flowsheet("clash")
    vessel = fs.add(build())
    if connect == "inlet":
        fs.connect(fs.add(Feed("Feed")).outlet, vessel.inlet)
    elif connect == "outlet":
        fs.connect(vessel.outlet, fs.add(Product("Product")).inlet)
    fs.layout()
    found = [issue for issue in fs.validate() if issue.code == "wall-part-clash"]
    assert len(found) == 1
    assert found[0].severity == "error"
    assert found[0].message.startswith("D-101: ")
    assert re.search(message, found[0].message)


def test_a_line_beside_a_wall_part_is_no_clash():
    """Check that a manhole clear of the inlet's line draws without a finding."""
    fs = Flowsheet("clear")
    vessel = fs.add(Vessel("D-101", manholes=[("W", 0.25)]))
    fs.connect(fs.add(Feed("Feed")).outlet, vessel.inlet)
    fs.to_svg(diagram="p&id")
    assert fs.validate() == []


def test_the_spec_round_trips_and_refuses_them_on_a_tank():
    """Check that manholes and sockets survive to_dict and from_dict."""
    spec = {
        "name": "walls",
        "units": [
            {"kind": "Vessel", "name": "D-101", "manholes": [["E", 0.3]], "sockets": [["W", 0.6]]},
            {"kind": "Evaporator", "name": "E-101", "sockets": [["E", 0.5]]},
            {"kind": "Product", "name": "Sample"},
        ],
        "streams": [{"from": ["D-101", "socket_1"], "to": ["Sample", "inlet"]}],
    }
    written = to_dict(from_dict(spec))
    assert written["units"][:2] == spec["units"][:2]
    assert to_dict(from_dict(written)) == written
    with pytest.raises(SpecError, match="only an Evaporator or a Vessel takes 'manholes'"):
        from_dict(
            {"name": "x", "units": [{"kind": "Tank", "name": "T-1", "manholes": [["E", 0.5]]}]}
        )
    with pytest.raises(SpecError, match="needs a fraction from 0 to 1"):
        from_dict(
            {"name": "x", "units": [{"kind": "Vessel", "name": "D-1", "sockets": [["E", 2]]}]}
        )


def test_the_drawio_export_flips_an_east_wall_part():
    """Check that draw.io draws an east manhole mirrored and a roof socket open below."""
    fs = Flowsheet("drawio")
    fs.add(Vessel("D-101", manholes=[("E", 0.3)]))
    fs.add(Vessel("D-102", variant="horizontal", sockets=[("N", 0.5)]))
    xml = fs.to_drawio()
    assert "shape=partialRectangle;right=0;flipH=1;" in xml
    assert "shape=partialRectangle;left=0;right=0;bottom=0;" in xml
