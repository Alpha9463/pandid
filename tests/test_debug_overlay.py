"""``debug=``: the coordinate overlay, and the three things that make it safe.

The overlay exists so an author can read a placement off the sheet and type it
back into ``pin()``. Three properties decide whether it does that or actively
misleads, and all three are checked here rather than left to the golden sheet:

**The numbers are drawing coordinates.** A sheet with a fixed ``page_size``
puts the whole drawing under a uniform fit scale, and an overlay drawn outside
that group -- or drawn in page units inside it -- would write numbers that are
not the ones ``pin()`` takes. Getting this wrong makes the feature worse than
absent: it would teach the wrong coordinate system and be believed.

**The numbers can be read, and belong to something.** The overlay is drawn
under the sheet, so a label written where a halo lands is a label that is not
there. One written clear of every halo but two nozzles away from its own is
worse still. See the last two sections.

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

from test_halo_invariants import _halos, _overlaps
from test_label_invariants import CORPUS, _RENDER_OPTS

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
    """The one unit whose ink does not start at its own pin: it *ends* there,
    the pennant growing back from the tip by however long the label is. The box
    outline is what says so on the sheet, and it is why it is drawn at all."""
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
# ...and the words can be read once they are there
# ---------------------------------------------------------------------------
#
# The overlay is drawn *under* the sheet, so every opaque white halo the
# renderer lays down paints over it, and #200 placed the port labels without
# ever asking where those halos were. On this module's own sheet the E-1 tag's
# halo took the leading "s" off "shell_in 240,100"; over the corpus it took a
# bite out of 174 of the 830 labels the overlay writes, and 313 of them were
# written on top of one another. Both are one defect -- placement that has not
# been told what is already on the paper -- and the fix is one placement pass,
# run against the finished sheet. See :mod:`pandid.render.debug`.


def _placed(svg: str) -> "list[tuple[tuple[float, float, float, float], str]]":
    """Every overlay label on a rendered sheet, as the paper it covers.

    The axis coordinates are left out: they are not placed, they name a grid
    line and go where it is, so they are an obstacle to the rest rather than one
    of them.
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
    """The defect, named: ``shell_in`` against ``E-1``'s opaque tag plate.

    Both want the paper just above the exchanger's top-left corner, the tag is
    drawn last and on white, and the overlay is drawn first -- so the tag won and
    the port label lost its first character to it.
    """
    svg = _sheet().to_svg(debug=True)
    halos = _halos(svg)
    shell_in = [b for b, text in _placed(svg) if text.startswith("shell_in")]
    assert shell_in, "the exchanger's shell_in port is not labelled at all"
    for box in shell_in:
        assert not [h for h in halos if _overlaps(box, h)], (
            "shell_in is written under an opaque halo and loses characters to it"
        )


#: How many labels a sheet is allowed to leave sitting under something. Zero
#: everywhere the drawing has room, which is twelve of the nineteen sheets
#: swept; the eight below are where it genuinely runs out.
#:
#: ``11_ethanol_pid`` writes 364 labels on a forty-unit P&ID whose markers are
#: twenty units apart and whose labels are sixty units long, so some of them
#: have nowhere at all to go: 35 do not come out clear, against 313 before.
#: ``12_block_flow_diagram`` names its blocks in words rather than in tags, so
#: two of its labels are longer than the block they belong to.
#: ``14_tank_farm`` mounts two faceplates on the crown of the valve each one
#: strokes, which is what puts a controller's output on the actuator without a
#: line crossing the run; the balloon's marker and the valve's then sit a
#: nozzle's height apart and the two overlay labels meet.
#: ``04_control_loop`` stands its ``FE-101`` balloon 23 units off the
#: transmitter above it, which is what makes the primary element and its reading
#: read as one column, and leaves the two markers closer than a label is tall.
#:
#: ``17_stirred_reactor_train`` puts a tee, a static mixer and a second tee on
#: 70 units of charge line, which is closer than a port label is long.
#: ``18_fixed_bed_recycle`` is laid out by the engine, and the recycle machine
#: it places carries its tag over its own suction marker. It grew by one when
#: R-301 was given a box of the symbol's own shape: a wider converter moves
#: everything the engine ranks after it, and the separator's signal markers come
#: to rest a label's width apart.
#: ``19_absorber_stripper`` drains its overhead condenser into a reflux drum at
#: the same elevation, so the drain's marker and the drum's inlet share a row.
#: ``20_molecular_sieve_dryer`` hangs a sequence square off each of eight
#: switching valves; two of the sixteen markers that makes land under lettering.
#:
#: ``22_biodiesel_plant`` reads its reactor's own batch temperature from a
#: transmitter east of R-401 and a controller north of that, with the
#: discharge pump P-403 immediately south-east of the first and R-401's own
#: tag immediately north of the second -- both drawn above the symbol they
#: name, per ``label_pos``. Two markers land under a tag that is not theirs.
#:
#: 04 and 14 both grew when the letter codes ISO 15519-2 5.2.5 writes outside a
#: symbol arrived: a code is haloed lettering like any tag, so it is one more
#: thing an overlay marker can land under, and the sheets that letter the most
#: are the ones that moved. Every entry carries headroom, because the point of
#: the numbers is to catch a placement that has stopped working rather than to
#: pin the corpus to what it draws today.
_CROWDED = {
    "04_control_loop": 3,
    "11_ethanol_pid": 50,
    "12_block_flow_diagram": 4,
    "14_tank_farm": 14,
    "17_stirred_reactor_train": 6,
    "18_fixed_bed_recycle": 7,
    "19_absorber_stripper": 4,
    "20_molecular_sieve_dryer": 5,
    "22_biodiesel_plant": 3,
}


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_the_overlay_writes_where_the_sheet_left_it_room(name):
    """No overlay label under a halo, and no two of them on top of each other.

    One sweep for both, because they are one defect: a label that has not been
    told where the plates and the other labels are lands on whichever it meets
    first. The obstacles are read out of the drawn SVG rather than off the
    placement code, for the reason ``test_halo_invariants`` reads them there --
    what the invariant is about is what lands on the paper.
    """
    fs, kwargs = CORPUS[name]()
    svg = fs.to_svg(**{k: v for k, v in kwargs.items() if k in _RENDER_OPTS}, debug=True)
    halos, labels = _halos(svg), _placed(svg)
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
    """Letting the words walk is only safe because of this line.

    A coordinate that has stepped clear of a halo has also stepped away from its
    own dot, and on a crowded sheet the next dot along is nearer. A label read
    against the wrong nozzle is worse than one that cannot be read at all,
    because it is a number that gets typed into ``pin()``. So anything written
    more than a couple of lines from its marker carries a hairline back to it.
    """
    svg = _sheet().to_svg(debug=True)
    g = _group(svg)
    (shell_in,) = [b for b, text in _placed(svg) if text.startswith("shell_in")]
    dots = {(float(c.get("cx")), float(c.get("cy"))) for c in g.iter(f"{SVG}circle")}
    assert (240.0, 300.0) in dots
    # That nozzle is at the middle of the box's top edge, which is exactly where
    # the renderer centres the unit's own tag, so this is a label that has to
    # move -- and having moved, it has to say where it came from.
    assert shell_in[0] > 240.0 + 2 * D._MARK_SIZE
    assert [
        ln
        for ln in g.iter(f"{SVG}line")
        if ln.get("stroke") == D._PORT
        and (float(ln.get("x1")), float(ln.get("y1"))) == (240.0, 300.0)
    ], "a port label written clear of its own dot is not joined back to it"


def test_a_label_still_against_its_own_marker_is_left_alone():
    """The other half of that rule. A tether saying what the eye already had is
    clutter, so one is drawn only where the words have actually gone somewhere."""
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
# ...without the sheet underneath moving a hair
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_the_drawing_is_the_same_drawing_with_the_overlay_lifted_off(name):
    """Cut the ``<g id="debug">`` group out and what is left is the plain sheet.

    Stronger than "off is off", and it is exactly what the placement above put
    at risk. The labels are now worked out *after* the drawing exists, so the
    renderer builds the sheet and splices the overlay onto the head of the list
    afterwards; get that splice wrong and the overlay reorders the drawing
    itself. No golden would catch it, because every golden is drawn with the
    overlay off.
    """
    fs, kwargs = CORPUS[name]()
    opts = {k: v for k, v in kwargs.items() if k in _RENDER_OPTS}
    marked = fs.to_svg(**opts, debug=True)
    head, rest = marked.split('  <g id="debug">', 1)
    assert head + rest.split("  </g>\n", 1)[1] == fs.to_svg(**opts)
