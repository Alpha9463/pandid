"""Test coordinate-overlay rendering and placement invariants."""

import re
import xml.etree.ElementTree as ET

import pytest

from _render_cases import copy_settled_case
from pandid import Flowsheet, units as U
from pandid.render import debug as D
from pandid.render.export import flatten

from test_halo_invariants import _halos, _overlaps
from test_label_invariants import CORPUS, _RENDER_OPTS

SVG = "{http://www.w3.org/2000/svg}"

_FIT = re.compile(
    r'<g id="drawing" transform="translate\(([-\d.]+), ([-\d.]+)\) scale\(([\d.e+-]+)\)"'
)


def _sheet() -> Flowsheet:
    """Build a small flowsheet with corner and port pins.

    Returns
    -------
    Flowsheet
        Flowsheet used for coordinate-overlay checks.
    """
    fs = Flowsheet("overlay")
    feed = fs.add(U.Feed("F-1")).pin(x=60, y=105)
    hx = fs.add(U.HeatExchanger("E-1")).pin(x=210).pin(port="tube_in", y=330)
    prod = fs.add(U.Product("P-1")).pin(x=430, y=105)
    fs.connect(feed.outlet, hx.tube_in)
    fs.connect(hx.tube_out, prod.inlet)
    return fs


def _group(svg: str) -> ET.Element:
    """Return the coordinate-overlay SVG group.

    Parameters
    ----------
    svg : str
        Rendered SVG document.

    Returns
    -------
    ET.Element
        Coordinate-overlay group.

    Raises
    ------
    AssertionError
        If the SVG does not contain the coordinate overlay.
    """
    root = ET.fromstring(svg)
    for g in root.iter(f"{SVG}g"):
        if g.get("id") == "debug":
            return g
    raise AssertionError('the render carries no <g id="debug">')


def _texts(g: ET.Element) -> list[str]:
    """Return text written in the coordinate overlay.

    Parameters
    ----------
    g : ET.Element
        Coordinate-overlay group.

    Returns
    -------
    list[str]
        Text content in drawing order.
    """
    return [(t.text or "") for t in g.iter(f"{SVG}text")]


def _rules(g: ET.Element) -> list[ET.Element]:
    """Return dashed grid rules from a coordinate overlay.

    Parameters
    ----------
    g : ET.Element
        Coordinate-overlay group.

    Returns
    -------
    list[ET.Element]
        Dashed grid-rule elements.
    """
    return [ln for ln in g.iter(f"{SVG}line") if ln.get("stroke-dasharray")]


def _wide() -> Flowsheet:
    """Build a flowsheet that requires fixed-page scaling.

    Returns
    -------
    Flowsheet
        Flowsheet used for fixed-page overlay checks.
    """
    fs = Flowsheet("wide")
    feed = fs.add(U.Feed("F-1")).pin(x=60, y=105)
    hx = fs.add(U.HeatExchanger("E-1")).pin(x=1200).pin(port="tube_in", y=330)
    prod = fs.add(U.Product("P-1")).pin(x=2400, y=105)
    fs.connect(feed.outlet, hx.tube_in)
    fs.connect(hx.tube_out, prod.inlet)
    return fs


# ---------------------------------------------------------------------------
# Default behavior
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("off", [False, None])
def test_a_sheet_drawn_without_it_is_the_sheet_that_was_drawn_before_it_existed(off):
    """Test that disabled overlays leave SVG output unchanged.

    Parameters
    ----------
    off : bool | None
        Debug option that disables the overlay.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    assert _sheet().to_svg(debug=off) == _sheet().to_svg()
    assert "debug" not in _sheet().to_svg()


def test_it_is_off_by_default_everywhere_a_sheet_can_be_asked_for():
    """Test that SVG render entry points omit the overlay by default.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    for svg in (_sheet().to_svg(), _sheet()._repr_svg_()):
        assert 'id="debug"' not in svg


# ---------------------------------------------------------------------------
# Coordinate mapping
# ---------------------------------------------------------------------------


def test_the_marker_sits_on_the_point_pin_set():
    """Test that a marker reports a unit corner pin.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    g = _group(_sheet().to_svg(debug=True))
    assert "F-1 60,105" in _texts(g)
    assert "P-1 430,105" in _texts(g)
    # The exchanger is pinned by its inlet nozzle.
    assert "E-1 210,300" in _texts(g)
    lines = [
        ln
        for ln in g.iter(f"{SVG}line")
        if float(ln.get("x1")) < 60 < float(ln.get("x2"))
        and float(ln.get("y1")) == float(ln.get("y2")) == 105
    ]
    assert lines, "no crosshair through (60, 105)"


def test_a_port_marker_sits_on_the_nozzle_and_not_on_the_corner():
    """Test that a port marker reports its nozzle pin.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    g = _group(_sheet().to_svg(debug=True))
    assert "tube_in 210,330" in _texts(g)
    dots = [(float(c.get("cx")), float(c.get("cy"))) for c in g.iter(f"{SVG}circle")]
    assert (210.0, 330.0) in dots
    assert (210.0, 300.0) not in dots


def test_the_grid_is_ruled_on_round_multiples_of_the_spacing():
    """Test that grid rules use round spacing multiples.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    g = _group(_sheet().to_svg(debug=True))
    verticals = {float(ln.get("x1")) for ln in _rules(g) if ln.get("x1") == ln.get("x2")}
    assert {100.0, 200.0, 300.0, 400.0} <= verticals
    assert all(x % 50 == 0 for x in verticals)
    assert {"100", "200", "300", "400"} <= set(_texts(g))


def test_the_spacing_is_the_one_that_was_asked_for():
    """Test that the overlay honors an explicit grid spacing.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    g = _group(_sheet().to_svg(debug=25))
    verticals = {float(ln.get("x1")) for ln in _rules(g) if ln.get("x1") == ln.get("x2")}
    assert 225.0 in verticals and 250.0 in verticals


def test_the_written_coordinates_stay_a_hundred_apart_at_any_spacing():
    """Test that coordinate labels retain a readable interval.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    for spacing in (10, 25, 50, 100):
        g = _group(_sheet().to_svg(debug=spacing))
        assert {"100", "200", "300"} <= set(_texts(g))
        assert "150" not in _texts(g)
    # Coarser grids label their own grid lines.
    assert "500" in _texts(_group(_sheet().to_svg(debug=500)))


def test_the_overlay_is_drawn_before_the_diagram():
    """Test that the overlay is placed beneath diagram content.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    svg = _sheet().to_svg(debug=True)
    assert svg.index('<g id="debug">') < svg.index('<g id="units">')


def test_the_overlay_stays_inside_the_drawing_it_annotates():
    """Test that an overlay preserves the drawing view box.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    plain, marked = _sheet().to_svg(), _sheet().to_svg(debug=True)
    box = re.search(r'viewBox="([^"]+)"', plain).group(1)
    assert f'viewBox="{box}"' in marked


# ---------------------------------------------------------------------------
# Fixed-page rendering
# ---------------------------------------------------------------------------


def test_a_fixed_page_does_not_move_the_numbers():
    """Test that fixed-page scaling preserves drawing coordinates.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
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
    """Test that fixed-page overlays preserve readable text size.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    fitted_svg = _wide().to_svg(page_size="A3", border="zone", debug=True)
    s = float(_FIT.search(fitted_svg).group(3))
    assert s < 1.0
    plain = {
        float(t.get("font-size")) for t in _group(_wide().to_svg(debug=True)).iter(f"{SVG}text")
    }
    fitted = {float(t.get("font-size")) for t in _group(fitted_svg).iter(f"{SVG}text")}
    # SVG font sizes are rounded to two decimal places.
    assert len(fitted) == len(plain)
    for got, want in zip(sorted(fitted), sorted(plain)):
        assert got * s == pytest.approx(want, abs=0.01)


# ---------------------------------------------------------------------------
# Export compatibility
# ---------------------------------------------------------------------------


def test_the_overlay_survives_the_route_to_pdf_and_png():
    """Test that export flattening preserves the coordinate overlay.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    flat = flatten(_wide().to_svg(page_size="A3", border="zone", debug=True))
    assert 'id="debug"' in flat


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_true_is_the_default_spacing_and_false_is_nothing():
    """Test the boolean debug options.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    assert D.resolve_spacing(True) == D.DEFAULT_SPACING
    assert D.resolve_spacing(False) is None
    assert D.resolve_spacing(None) is None


def test_a_spacing_of_nought_is_a_mistake_and_not_an_off_switch():
    """Test that zero is rejected as a grid spacing.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    with pytest.raises(ValueError, match="debug=0"):
        _sheet().to_svg(debug=0)


def test_a_spacing_fine_enough_to_be_a_typo_is_refused_by_name():
    """Test that impractically fine grid spacing is rejected.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    with pytest.raises(ValueError, match="debug=True"):
        _sheet().to_svg(debug=1)


def test_something_that_is_not_a_spacing_at_all():
    """Test that nonnumeric debug options are rejected.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    with pytest.raises(ValueError, match="must be True, False"):
        _sheet().to_svg(debug="fine")


def test_the_refusal_comes_before_a_sheet_is_built():
    """Test that invalid options leave the flowsheet render unchanged.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    fs = _sheet()
    with pytest.raises(ValueError):
        fs.to_svg(debug=-5)
    assert "debug" not in fs.to_svg()


# ---------------------------------------------------------------------------
# Pin placement
# ---------------------------------------------------------------------------


def test_a_turned_or_mirrored_unit_still_marks_the_point_pin_set():
    """Test that transformed units retain their marker coordinates.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    fs = Flowsheet("turned")
    pump = fs.add(U.Pump("P-1")).pin(x=300, y=200, orientation=90, mirrored=True)
    prod = fs.add(U.Product("P-2")).pin(x=600, y=200)
    fs.connect(pump.discharge, prod.inlet)
    assert "P-1 300,200" in _texts(_group(fs.to_svg(debug=True)))


def test_a_feed_flag_is_drawn_left_of_the_point_that_pins_it():
    """Test that a feed symbol ends at its pin coordinate.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    fs = Flowsheet("feed")
    feed = fs.add(U.Feed("F-1")).pin(x=60, y=105)
    prod = fs.add(U.Product("P-1")).pin(x=430, y=105)
    fs.connect(feed.outlet, prod.inlet)
    g = _group(fs.to_svg(debug=True))
    boxes = [(float(r.get("x")), float(r.get("width"))) for r in g.iter(f"{SVG}rect")]
    assert any(x < 60 and x + w == pytest.approx(60) for x, w in boxes), (
        "the feed's outline should end at the point that pinned it"
    )


# ---------------------------------------------------------------------------
# Label placement
# ---------------------------------------------------------------------------


def _placed(svg: str) -> "list[tuple[tuple[float, float, float, float], str]]":
    """Return non-axis overlay-label boxes and text.

    Parameters
    ----------
    svg : str
        Rendered SVG document.

    Returns
    -------
    list[tuple[tuple[float, float, float, float], str]]
        Bounding boxes and text for placed overlay labels.
    """
    out = []
    for t in _group(svg).iter(f"{SVG}text"):
        if t.get("fill") == D._NUMBER:
            continue
        lead = 1.0 if t.get("text-anchor") == "start" else -1.0
        out.append(
            (
                D._box(
                    float(t.get("x")),
                    float(t.get("y")),
                    t.text or "",
                    float(t.get("font-size")),
                    lead,
                ),
                t.text or "",
            )
        )
    return out


def test_a_port_label_is_not_written_under_the_unit_tags_halo():
    """Test that a port label avoids a unit-tag halo.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    svg = _sheet().to_svg(debug=True)
    halos = _halos(svg)
    shell_in = [b for b, text in _placed(svg) if text.startswith("shell_in")]
    assert shell_in, "the exchanger's shell_in port is not labelled at all"
    for box in shell_in:
        assert not [h for h in halos if _overlaps(box, h)], (
            "shell_in is written under an opaque halo and loses characters to it"
        )


# Maximum tolerated overlay-label collisions for intentionally dense sheets.
_CROWDED = {
    "04_control_loop": 3,
    "11_ethanol_pid": 50,
    "14_tank_farm": 14,
    "17_stirred_reactor_train": 6,
    "18_fixed_bed_recycle": 7,
    "19_absorber_stripper": 4,
    "20_molecular_sieve_dryer": 5,
}


@pytest.fixture(scope="module")
def corpus_drawings(settled_gallery):
    """Render each debug-overlay corpus sheet in both modes.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[Flowsheet, dict]]
        Shared routed gallery flowsheets and render options.

    Returns
    -------
    dict[str, tuple[Flowsheet, str, str]]
        Flowsheets with debug and plain SVGs by corpus name.
    """
    drawings = {}
    for name, build in CORPUS.items():
        if name in settled_gallery:
            fs, kwargs = copy_settled_case(settled_gallery, name)
        else:
            fs, kwargs = build()
        options = {key: value for key, value in kwargs.items() if key in _RENDER_OPTS}
        drawings[name] = (fs, fs.to_svg(**options, debug=True), fs.to_svg(**options))
    return drawings


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_the_overlay_writes_where_the_sheet_left_it_room(corpus_drawings, name):
    """Test that corpus overlay labels remain visible and distinct.

    Parameters
    ----------
    corpus_drawings : dict[str, tuple[Flowsheet, str, str]]
        Cached flowsheets with debug and plain SVGs.
    name : str
        Corpus sheet name.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    fs, svg, _plain = corpus_drawings[name]
    halos, labels = _halos(svg), _placed(svg)
    expected = sum(1 + len(u.ports) for u in fs.units if u.frame is not None)
    assert len(labels) == expected, (
        f"{name}: the overlay wrote {len(labels)} labels where the sheet has "
        f"{expected} to write -- one per placed unit and one per nozzle"
    )
    buried = [
        text
        for i, (box, text) in enumerate(labels)
        if any(_overlaps(box, h) for h in halos)
        or any(_overlaps(box, other) for j, (other, _) in enumerate(labels) if j != i)
    ]
    assert len(buried) <= _CROWDED.get(name, 0), (
        f"{name}: {len(buried)} of {len(labels)} overlay labels are written under a "
        f"halo or over another label, e.g. {buried[:5]}"
    )


def test_a_label_that_had_to_move_is_joined_to_the_marker_it_names():
    """Test that displaced labels include a marker tether.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    svg = _sheet().to_svg(debug=True)
    g = _group(svg)
    (shell_in,) = [b for b, text in _placed(svg) if text.startswith("shell_in")]
    dots = {(float(c.get("cx")), float(c.get("cy"))) for c in g.iter(f"{SVG}circle")}
    assert (240.0, 300.0) in dots
    # The top-edge nozzle requires a displaced label.
    assert shell_in[0] > 240.0 + 2 * D._MARK_SIZE
    assert [
        ln
        for ln in g.iter(f"{SVG}line")
        if ln.get("stroke") == D._PORT
        and (float(ln.get("x1")), float(ln.get("y1"))) == (240.0, 300.0)
    ], "a port label written clear of its own dot is not joined back to it"


def test_a_label_still_against_its_own_marker_is_left_alone():
    """Test that adjacent labels do not include a tether.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    fs = Flowsheet("plain")
    feed = fs.add(U.Feed("F-1")).pin(x=60, y=105)
    prod = fs.add(U.Product("P-1")).pin(x=430, y=105)
    fs.connect(feed.outlet, prod.inlet)
    g = _group(fs.to_svg(debug=True))
    assert [b for b, text in _placed(fs.to_svg(debug=True)) if text.startswith("outlet")]
    assert not [ln for ln in g.iter(f"{SVG}line") if ln.get("stroke") == D._PORT], (
        "a label sitting against its own dot was given a tether anyway"
    )


# ---------------------------------------------------------------------------
# Diagram invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_the_drawing_is_the_same_drawing_with_the_overlay_lifted_off(corpus_drawings, name):
    """Test that removing the overlay restores the plain SVG.

    Parameters
    ----------
    corpus_drawings : dict[str, tuple[Flowsheet, str, str]]
        Cached flowsheets with debug and plain SVGs.
    name : str
        Corpus sheet name.

    Returns
    -------
    None
        Assertion result for the stated behavior.
    """
    _fs, marked, plain = corpus_drawings[name]
    head, rest = marked.split('  <g id="debug">', 1)
    assert head + rest.split("  </g>\n", 1)[1] == plain
