"""``debug=``: the coordinate overlay, and the two things that make it safe.

The overlay exists so an author can read a placement off the sheet and type it
back into ``pin()``. Two properties decide whether it does that or actively
misleads, and both are checked here rather than left to the golden sheet:

**The numbers are drawing coordinates.** A sheet with a fixed ``page_size``
puts the whole drawing under a uniform fit scale, and an overlay drawn outside
that group -- or drawn in page units inside it -- would write numbers that are
not the ones ``pin()`` takes. Getting this wrong makes the feature worse than
absent: it would teach the wrong coordinate system and be believed.

**Off leaves no trace.** ``tests/test_golden.py`` compares the corpus byte for
byte, and every scenario but ``02`` draws with the overlay off; that is the real
guard. What is here is the same claim made directly, so a failure says which
property broke rather than pointing at a 70 KB diff.
"""

import re
import xml.etree.ElementTree as ET

import pytest

from pandid import Flowsheet, units as U
from pandid.render import debug as D
from pandid.render.export import flatten

SVG = "{http://www.w3.org/2000/svg}"

_FIT = re.compile(
    r'<g id="drawing" transform="translate\(([-\d.]+), ([-\d.]+)\) scale\(([\d.e+-]+)\)"'
)


def _sheet() -> Flowsheet:
    """A feed, an exchanger and a product: one corner pin and one nozzle pin.

    Small on purpose. Every assertion below names a coordinate that is written
    in this function, so a reader can check the test against the sheet the same
    way an author checks a drawing against their source.
    """
    fs = Flowsheet("overlay")
    feed = fs.add(U.Feed("F-1")).pin(x=60, y=105)
    hx = fs.add(U.HeatExchanger("E-1")).pin(x=210).pin(port="tube_in", y=330)
    prod = fs.add(U.Product("P-1")).pin(x=430, y=105)
    fs.connect(feed.outlet, hx.tube_in)
    fs.connect(hx.tube_out, prod.inlet)
    return fs


def _group(svg: str) -> ET.Element:
    """The ``<g id="debug">`` element, or fail saying it is not there."""
    root = ET.fromstring(svg)
    for g in root.iter(f"{SVG}g"):
        if g.get("id") == "debug":
            return g
    raise AssertionError('the render carries no <g id="debug">')


def _texts(g: ET.Element) -> list[str]:
    return [(t.text or "") for t in g.iter(f"{SVG}text")]


def _rules(g: ET.Element) -> list[ET.Element]:
    """The grid rules alone. A crosshair arm is a ``<line>`` too, and a vertical
    one is indistinguishable from a grid line by its coordinates; the dash is
    what the grid is drawn with and the markers are not."""
    return [ln for ln in g.iter(f"{SVG}line") if ln.get("stroke-dasharray")]


def _wide() -> Flowsheet:
    """The same drawing, stretched past what an A3 sheet holds, so a fixed page
    has to scale it down. A drawing smaller than the paper is drawn at 1:1 (see
    ``svg._fit_scale``), and at 1:1 every fitted-sheet claim below is vacuous."""
    fs = Flowsheet("wide")
    feed = fs.add(U.Feed("F-1")).pin(x=60, y=105)
    hx = fs.add(U.HeatExchanger("E-1")).pin(x=1200).pin(port="tube_in", y=330)
    prod = fs.add(U.Product("P-1")).pin(x=2400, y=105)
    fs.connect(feed.outlet, hx.tube_in)
    fs.connect(hx.tube_out, prod.inlet)
    return fs


# ---------------------------------------------------------------------------
# off is off
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("off", [False, None])
def test_a_sheet_drawn_without_it_is_the_sheet_that_was_drawn_before_it_existed(off):
    """Byte for byte, not merely "no grid visible"."""
    assert _sheet().to_svg(debug=off) == _sheet().to_svg()
    assert "debug" not in _sheet().to_svg()


def test_it_is_off_by_default_everywhere_a_sheet_can_be_asked_for():
    for svg in (_sheet().to_svg(), _sheet()._repr_svg_()):
        assert 'id="debug"' not in svg


# ---------------------------------------------------------------------------
# the numbers are the ones pin() takes
# ---------------------------------------------------------------------------


def test_the_marker_sits_on_the_point_pin_set():
    """The crosshair is drawn at the corner, and says so in words beside it."""
    g = _group(_sheet().to_svg(debug=True))
    assert "F-1 60,105" in _texts(g)
    assert "P-1 430,105" in _texts(g)
    # The exchanger was pinned by its nozzle, so its corner is a number nobody
    # wrote down. The marker is what tells the author what it came out as.
    assert "E-1 210,300" in _texts(g)
    lines = [
        ln
        for ln in g.iter(f"{SVG}line")
        if float(ln.get("x1")) < 60 < float(ln.get("x2"))
        and float(ln.get("y1")) == float(ln.get("y2")) == 105
    ]
    assert lines, "no crosshair through (60, 105)"


def test_a_port_marker_sits_on_the_nozzle_and_not_on_the_corner():
    """The distinction the overlay exists for: E-1's corner is at y=300 and the
    nozzle that was pinned is at y=330."""
    g = _group(_sheet().to_svg(debug=True))
    assert "tube_in 210,330" in _texts(g)
    dots = [(float(c.get("cx")), float(c.get("cy"))) for c in g.iter(f"{SVG}circle")]
    assert (210.0, 330.0) in dots
    assert (210.0, 300.0) not in dots


def test_the_grid_is_ruled_on_round_multiples_of_the_spacing():
    """Lines at 100, 200, 300 -- not at the drawing's own left edge plus 100.

    A number nobody would type is a number nobody can use.
    """
    g = _group(_sheet().to_svg(debug=True))
    verticals = {float(ln.get("x1")) for ln in _rules(g) if ln.get("x1") == ln.get("x2")}
    assert {100.0, 200.0, 300.0, 400.0} <= verticals
    assert all(x % 50 == 0 for x in verticals)
    assert {"100", "200", "300", "400"} <= set(_texts(g))


def test_the_spacing_is_the_one_that_was_asked_for():
    g = _group(_sheet().to_svg(debug=25))
    verticals = {float(ln.get("x1")) for ln in _rules(g) if ln.get("x1") == ln.get("x2")}
    assert 225.0 in verticals and 250.0 in verticals


def test_the_written_coordinates_stay_a_hundred_apart_at_any_spacing():
    """Otherwise a fine grid is a wall of numbers and a coarse one is unlabelled."""
    for spacing in (10, 25, 50, 100):
        g = _group(_sheet().to_svg(debug=spacing))
        assert {"100", "200", "300"} <= set(_texts(g))
        assert "150" not in _texts(g)
    # ...and a pitch coarser than that is still numbered, on its own lines.
    assert "500" in _texts(_group(_sheet().to_svg(debug=500)))


def test_the_overlay_is_drawn_before_the_diagram():
    """Under the sheet's ink, so nothing it draws can obscure the drawing."""
    svg = _sheet().to_svg(debug=True)
    assert svg.index('<g id="debug">') < svg.index('<g id="units">')


def test_the_overlay_stays_inside_the_drawing_it_annotates():
    """It adds nothing to the extent of the drawing, which is what lets a fixed
    page fit the sheet exactly as it would have without it."""
    plain, marked = _sheet().to_svg(), _sheet().to_svg(debug=True)
    box = re.search(r'viewBox="([^"]+)"', plain).group(1)
    assert f'viewBox="{box}"' in marked


# ---------------------------------------------------------------------------
# ...on a fixed page too, which is where it would silently go wrong
# ---------------------------------------------------------------------------


def test_a_fixed_page_does_not_move_the_numbers():
    """The whole drawing is scaled and centred on an A3 sheet. The overlay is
    inside that group, so it is scaled with it and keeps writing the drawing's
    own coordinates -- which are the ones ``pin()`` takes."""
    svg = _wide().to_svg(page_size="A3", border="zone", debug=True)
    fit = _FIT.search(svg)
    assert fit and float(fit.group(3)) < 1.0, "this sheet is meant to be fitted"

    g = _group(svg)
    assert "F-1 60,105" in _texts(g)
    assert "tube_in 1200,330" in _texts(g)
    dots = [(float(c.get("cx")), float(c.get("cy"))) for c in g.iter(f"{SVG}circle")]
    assert (1200.0, 330.0) in dots
    verticals = {float(ln.get("x1")) for ln in _rules(g) if ln.get("x1") == ln.get("x2")}
    assert {1000.0, 1500.0, 2000.0} <= verticals


def test_a_fixed_page_holds_the_lettering_to_a_constant_size_on_paper():
    """The geometry is in drawing units and rides the fit; the type is not, or a
    sheet fitted to a third of its size would carry lettering nobody can read."""
    fitted_svg = _wide().to_svg(page_size="A3", border="zone", debug=True)
    s = float(_FIT.search(fitted_svg).group(3))
    assert s < 1.0
    plain = {
        float(t.get("font-size")) for t in _group(_wide().to_svg(debug=True)).iter(f"{SVG}text")
    }
    fitted = {float(t.get("font-size")) for t in _group(fitted_svg).iter(f"{SVG}text")}
    # Sizes are written to two decimals, so scaling one back lands near its
    # unfitted twin rather than exactly on it.
    assert len(fitted) == len(plain)
    for got, want in zip(sorted(fitted), sorted(plain)):
        assert got * s == pytest.approx(want, abs=0.01)


# ---------------------------------------------------------------------------
# every output format
# ---------------------------------------------------------------------------


def test_the_overlay_survives_the_route_to_pdf_and_png():
    """``flatten`` refuses anything the export backend would drop silently, so
    running it is the check that the overlay uses no construct the .pdf and .png
    cannot carry. It needs no optional package to say so."""
    flat = flatten(_wide().to_svg(page_size="A3", border="zone", debug=True))
    assert 'id="debug"' in flat


# ---------------------------------------------------------------------------
# what it refuses
# ---------------------------------------------------------------------------


def test_true_is_the_default_spacing_and_false_is_nothing():
    assert D.resolve_spacing(True) == D.DEFAULT_SPACING
    assert D.resolve_spacing(False) is None
    assert D.resolve_spacing(None) is None


def test_a_spacing_of_nought_is_a_mistake_and_not_an_off_switch():
    """``0 == False`` in Python. It is not ``False`` here."""
    with pytest.raises(ValueError, match="debug=0"):
        _sheet().to_svg(debug=0)


def test_a_spacing_fine_enough_to_be_a_typo_is_refused_by_name():
    """``debug=1`` meant as "on" would rule a line every drawing unit. The
    message names the spelling that was meant."""
    with pytest.raises(ValueError, match="debug=True"):
        _sheet().to_svg(debug=1)


def test_something_that_is_not_a_spacing_at_all():
    with pytest.raises(ValueError, match="must be True, False"):
        _sheet().to_svg(debug="fine")


def test_the_refusal_comes_before_a_sheet_is_built():
    """A bad spacing is the caller's mistake, so it is reported rather than
    half a drawing."""
    fs = _sheet()
    with pytest.raises(ValueError):
        fs.to_svg(debug=-5)
    assert "debug" not in fs.to_svg()


# ---------------------------------------------------------------------------
# placements the marker could get wrong
# ---------------------------------------------------------------------------


def test_a_turned_or_mirrored_unit_still_marks_the_point_pin_set():
    """A quarter turn and a mirror are applied about the box's centre, so the
    corner does not move. If that ever stops being true the marker would point
    at a number ``pin()`` does not take, which is the failure worth catching."""
    fs = Flowsheet("turned")
    pump = fs.add(U.Pump("P-1")).pin(x=300, y=200, orientation=90, mirrored=True)
    prod = fs.add(U.Product("P-2")).pin(x=600, y=200)
    fs.connect(pump.discharge, prod.inlet)
    assert "P-1 300,200" in _texts(_group(fs.to_svg(debug=True)))


def test_a_feed_flag_is_drawn_left_of_the_point_that_pins_it():
    """The one unit whose ink does not start at its own pin. The box outline is
    what says so on the sheet, and it is why the outline is drawn at all."""
    fs = Flowsheet("feed")
    feed = fs.add(U.Feed("F-1")).pin(x=60, y=105)
    prod = fs.add(U.Product("P-1")).pin(x=430, y=105)
    fs.connect(feed.outlet, prod.inlet)
    g = _group(fs.to_svg(debug=True))
    boxes = [(float(r.get("x")), float(r.get("width"))) for r in g.iter(f"{SVG}rect")]
    assert any(x < 60 and x + w > 60 for x, w in boxes), (
        "the feed's outline should straddle the point that pinned it"
    )
