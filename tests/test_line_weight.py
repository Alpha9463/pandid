"""Line weight, as it lands on the page rather than as it is written down.

A sheet is drawn in two weights and the ratio between them is what tells a
reader the process from the instrumentation (ISO 15519-1 §6.2; see
``pandid.render.svg._PROCESS_STROKE``). Every check here is therefore about the
*drawn* weight: what a stroke measures after every viewport and transform
between it and the drawing has been applied, which is not what its
``stroke-width`` attribute says. The one transform left out is the fit a fixed
``page_size`` puts the whole drawing under, since it moves every pen together
and so says nothing about any of them; ``_walk`` is where that is done.

The difference is where #153 lived. A symbol's weights are compensated once, at
generation time, for the scale its artwork is drawn at; a ``<use>`` then scales
the ``<symbol>``'s viewport, ink and all, and nothing scaled it back, so any
unit given a ``width``/``height`` of its own quietly left the weight every other
line on the sheet is drawn at. A 90 x 140 surge vessel drew at 2.9 against its
neighbours' 2.0, and the 40 x 68 relief valve of #152 drew at 5.8 and filled in.

So the invariant is stated as *the box a unit is given does not change the pen*,
and it is checked against what the symbol library declares rather than against a
constant: a symbol's own fine detail (a column's trays, an agitator, the
location bar across a panel balloon) is deliberately finer than its outline, and
a signal line is deliberately half a process line's weight. "2.0 everywhere" is
not the invariant. "The weight it should be" is.

And it is one weight, not a range. #235 is the half of #153 that was left: a box
of another *shape* scales the two axes differently, and this file used to price
that as an ellipse bounded by the aspect change the placement asked for -- which
let V-604's shell walls draw 1,53 heavier than its heads inside one outline, and
let the four vendored families whose own wrapper group is uneven draw an ellipse
at their natural size with no placement involved at all. ISO 15519-1:2010
§11.1.3 is a *shall* -- "When the size of a symbol is changed, the line width
shall be unchanged" -- and §6.2's "the ratio between any two widths shall be at
least 2:1" leaves nothing between 1:1 and 2:1 to call it instead. The renderer
now redraws the artwork at the placed size rather than stretching its viewport
(``pandid.render.svg._baked``), so every stroke below is checked for being
*round*, at the weight its definition declares, with no bound and no exception.
"""

import math
import re
import xml.etree.ElementTree as ET

import pytest

from pandid import Flowsheet, units
from pandid.render.svg import (
    _PROCESS_STROKE,
    _SIGNAL_STROKE,
    SvgRenderer,
    _placement_scale,
)
from pandid.render.symbols import default_registry
from test_golden import SCENARIOS

_NS = "{http://www.w3.org/2000/svg}"
_XFORM = re.compile(r"(translate|scale|rotate|matrix)\(([^)]*)\)")
_IDENTITY = (1.0, 0.0, 0.0, 1.0)


# --- what a stroke actually measures ------------------------------------------


def _mul(p, q):
    """Two 2x2 row-major matrices, composed the way SVG nests them."""
    return (
        p[0] * q[0] + p[1] * q[2],
        p[0] * q[1] + p[1] * q[3],
        p[2] * q[0] + p[3] * q[2],
        p[2] * q[1] + p[3] * q[3],
    )


def _linear(transform):
    """The 2x2 linear part of an SVG transform list.

    Translation is dropped: it moves a stroke without touching its weight, and
    weight is the whole of what this file measures.
    """
    m = _IDENTITY
    for op, args in _XFORM.findall(transform or ""):
        v = [float(t) for t in re.split(r"[,\s]+", args.strip()) if t]
        if op == "translate":
            continue
        if op == "scale":
            n = (v[0], 0.0, 0.0, v[1] if len(v) > 1 else v[0])
        elif op == "rotate":
            r = math.radians(v[0])
            n = (math.cos(r), -math.sin(r), math.sin(r), math.cos(r))
        else:  # matrix(a b c d e f), column-major as SVG writes it
            n = (v[0], v[2], v[1], v[3])
        m = _mul(m, n)
    return m


def _pen_axes(m):
    """The two weights a unit-wide pen comes out at under *m*, smaller first.

    SVG strokes a path by sweeping a circular pen along it, so a transform that
    scales the axes differently sweeps an elliptical one and the weight depends
    on which way the line runs: these are that ellipse's axes, which a vertical
    and a horizontal line respectively land on. Taken as singular values rather
    than off the diagonal, so a quarter turn or a mirror -- which turn the pen
    without deforming it -- does not read as a change of weight.
    """
    a, b, c, d = m
    q = math.hypot((a + d) / 2, (c - b) / 2)
    r = math.hypot((a - d) / 2, (c + b) / 2)
    return abs(q - r), q + r


def _viewport(use, symbol):
    """The scale a ``<use>`` box applies to a ``<symbol>``'s contents.

    The viewport rule, and the same one ``pandid.render.export._placement``
    resolves for the PDF backend: fill the box where the definition gave up its
    aspect ratio, and otherwise keep the scale uniform and centre what is left.
    """
    _, _, vw, vh = (float(t) for t in symbol.get("viewBox").split())
    w = float(use.get("width", vw))
    h = float(use.get("height", vh))
    if symbol.get("preserveAspectRatio") == "none":
        return (w / vw, 0.0, 0.0, h / vh)
    s = min(w / vw, h / vh)
    return (s, 0.0, 0.0, s)


def _walk(el, m, symbols, out, where):
    for child in el:
        tag = child.tag.replace(_NS, "")
        if tag in ("defs", "symbol", "marker"):
            continue  # a definition is ink only where a <use> puts it
        cm = _mul(m, _linear(child.get("transform", "")))
        if tag == "g" and child.get("id") == "drawing":
            # A sheet given a fixed ``page_size`` fits its whole drawing into
            # what the furniture leaves, under one uniform scale
            # (``SvgRenderer._fit``). That moves every pen on the drawing
            # together, so it changes what a stroke measures against the page
            # and nothing about what the weights say to each other -- which is
            # the whole of what a line weight is. It is left out here, so the
            # weights below are the ones the drawing is drawn in and the
            # invariant reads the same on the A3 sheets as on the rest.
            lo, hi = _pen_axes(_linear(child.get("transform", "")))
            assert math.isclose(lo, hi, rel_tol=1e-9), (
                f"the page fit is not a uniform scale: {lo:.4g} by {hi:.4g}"
            )
            cm = m
        if tag == "use":
            ref = (child.get("href") or child.get(f"{_NS}href", ""))[1:]
            sym = symbols[ref]
            _walk(sym, _mul(cm, _viewport(child, sym)), symbols, out, ref)
            continue
        width = child.get("stroke-width")
        if width is not None and child.get("stroke", "none") != "none":
            lo, hi = _pen_axes(cm)
            out.append((where, float(width) * lo, float(width) * hi))
        _walk(child, cm, symbols, out, where if tag != "g" else child.get("id", where))


def drawn_pens(svg):
    """Every stroke the sheet draws, as ``(group or symbol id, thin, thick)``.

    ``thin``/``thick`` are the weights the stroke lands on for the two extreme
    directions, and are equal for everything drawn under a uniform scale.
    """
    root = ET.fromstring(svg)
    symbols = {el.get("id", ""): el for el in root.iter(f"{_NS}symbol")}
    out = []
    _walk(root, _IDENTITY, symbols, out, "")
    return out


def authored_pens(sym):
    """The weight a symbol's own definition declares, in document order.

    Read through the artwork's internal scale group, so this is the weight the
    symbol draws at in the box it was drawn for: 2.0 for an outline, and
    whatever finer weight the author chose for a detail line.

    One number per stroke, taken as the geometric mean of the two axes, because
    four of the vendored families are drawn under an *uneven* scale group and so
    declare an ellipse rather than a pen -- a plain vessel under
    ``scale(0.62, 0.5)`` declares 2.23 by 1.80. That is a fact about how the
    stencil was reproportioned and not a weight anybody chose; the mean is the
    weight it was centred on, it is what ``scripts/vendor_symbols.py`` divided
    by to bake it in, and it is exact for the other 138 families, whose two axes
    agree. The renderer flattens that group into the coordinates and strokes at
    this number (``pandid.render.svg._baked``), which is why the drawn pens
    checked against it below are round even for those four.
    """
    root = ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{sym.svg}</svg>')
    out = []
    _walk(root, _IDENTITY, {}, out, "")
    return [math.sqrt(lo * hi) for _, lo, hi in out]


# --- the invariant ------------------------------------------------------------


def check_symbol_weights(fs, svg):
    """Every symbol on *svg* is drawn with the pen its definition declares.

    Round, and at that weight exactly, whatever box the unit was given: a
    resize, a reshape, a quarter turn, a mirror or any of them together. Two
    assertions and no branch, which is the point of #235 -- the version of this
    function that shipped with #153 checked the *mean* of the two axes exactly
    and then allowed the axes themselves to spread as far apart as the box was
    out of the symbol's shape, so V-604's 2.48 by 1.61 passed. ISO 15519-1
    §11.1.3 does not allow a spread and §6.2 has no name for one under 2:1.

    ``authored_pens`` is a weight per stroke rather than a constant because a
    symbol's own fine detail is deliberately finer than its outline; the sheet
    weight itself is pinned separately, both under the definitions
    (:func:`test_every_symbol_declares_a_pen_centred_on_the_sheet_weight`) and
    on the lines a sheet draws directly
    (:func:`test_every_line_on_the_corpus_lands_on_one_of_the_two_sheet_weights`),
    so "the weight it should be" cannot be satisfied by moving the target.
    """
    renderer = SvgRenderer()
    by_id = {}
    for name, lo, hi in drawn_pens(svg):
        by_id.setdefault(name, []).append((lo, hi))

    checked = 0
    for u in fs.units:
        if u.kind in ("feed", "product"):
            continue  # a boundary flag is drawn inline, not placed from <defs>
        sym = default_registry.for_unit(u)
        sym_id = renderer._sym_id(u)
        assert sym_id in by_id, f"{u.name}: nothing on the sheet uses {sym_id!r}"
        expected = authored_pens(sym)
        drawn = by_id[sym_id][: len(expected)]
        assert len(drawn) == len(expected), (
            f"{u.name}: {sym_id} draws {len(drawn)} strokes, its definition "
            f"declares {len(expected)}"
        )
        kx, ky = _placement_scale(sym, u)
        for i, (want, (dlo, dhi)) in enumerate(zip(expected, drawn)):
            what = f"{u.name} ({sym_id}) stroke {i}"
            assert math.isclose(dlo, dhi, rel_tol=1e-5), (
                f"{what}: drawn {dhi:.4g} one way and {dlo:.4g} the other, in a box "
                f"{kx:.4g} by {ky:.4g} of the symbol's own -- one outline, two "
                f"widths, and ISO 15519-1 §6.2 has no weight between 1:1 and 2:1"
            )
            assert math.isclose(dlo, want, rel_tol=1e-5), (
                f"{what}: a {kx:.4g} by {ky:.4g} box moved the weight its "
                f"definition draws at, {want:.4g}, to {dlo:.4g}"
            )
        checked += 1
    assert checked, "no unit was checked"


# --- the pen a symbol declares ------------------------------------------------


def test_every_symbol_declares_a_pen_centred_on_the_sheet_weight():
    """The weight the *definitions* are drawn at, which nothing above can see.

    Every check above measures a placement against the definition it draws
    from, so a definition drawn at the wrong weight passes all of them: both
    sides of that comparison come from the same symbol. What the definitions
    are drawn at is settled a level further up, by
    ``scripts/vendor_symbols.py``, which bakes a compensated ``stroke-width``
    inside the scale group it wraps each stencil's artwork in.

    That compensation divided by ``sx`` alone until #158. Under a uniform
    factor there is nothing to choose and the outline landed exactly on the
    sheet weight; under the four uneven pairs ``SCALE`` reproportions it put
    the vertical strokes on that weight and left the horizontal ones at
    ``sy/sx`` of it -- the packed tower's bed grids at 0.93 against its own
    shell walls' 2.0, a pen a third short of the sheet's by area. It is the
    geometric mean now, so the sheet weight is the *middle* of every pen in the
    library rather than one edge of four of them.

    The middle is all a ``stroke-width`` inside an uneven scale group can be,
    and until #235 that was where it ended: those four families drew 2.23 by
    1.80 on the page, at their own natural size, and no care taken at the
    ``<use>`` could have helped. The renderer flattens the group into the
    coordinates now, so the mean this measures is the weight that reaches the
    page in both directions -- which is what
    :func:`test_every_symbol_on_the_corpus_is_drawn_at_its_declared_weight`
    checks and what makes this the right number to hold the library to.
    """
    checked = 0
    for (kind, variant), sym in sorted(default_registry._symbols.items()):
        pens = authored_pens(sym)
        assert pens, f"{kind}/{variant} declares no stroke at all"
        # The outline is the heaviest pen, and for the four uneven families that
        # is a mean rather than a width; see authored_pens.
        pen = max(pens)
        # The tolerance is the generator's own rounding: it emits the divided
        # weight to three decimals, and the packed tower's 0.662 is the
        # smallest number that lands on, so a part in a thousand there.
        assert math.isclose(pen, float(_PROCESS_STROKE), rel_tol=2e-3), (
            f"{kind}/{variant}: its outline is drawn at {pen:.4g} against the "
            f"sheet's {_PROCESS_STROKE}"
        )
        checked += 1
    assert checked > 100, f"only {checked} symbols were walked; the registry is bigger"


# --- the golden corpus --------------------------------------------------------


@pytest.mark.parametrize("name", list(SCENARIOS), ids=list(SCENARIOS))
def test_every_symbol_on_the_corpus_is_drawn_at_its_declared_weight(name):
    build, kwargs = SCENARIOS[name]
    fs = build()
    check_symbol_weights(fs, fs.to_svg(**kwargs))


@pytest.mark.parametrize("name", list(SCENARIOS), ids=list(SCENARIOS))
def test_every_line_on_the_corpus_lands_on_one_of_the_two_sheet_weights(name):
    """Streams and impulse lines, against the pair ISO 15519-2 Annex A.1 spends.

    These are drawn straight onto the sheet rather than through a viewport, so
    they were never at risk from #153; they are the fixed point the symbols are
    measured against, and a check that says so is what stops a later fix to the
    symbols from being made by moving the target instead.
    """
    build, kwargs = SCENARIOS[name]
    fs = build()
    weights = {"streams": float(_PROCESS_STROKE), "instrument_taps": float(_SIGNAL_STROKE)}
    seen = 0
    for where, lo, hi in drawn_pens(fs.to_svg(**kwargs)):
        if where not in weights:
            continue
        # A signal stream is drawn on the fine rung inside the streams group, so
        # the weights are checked as a set rather than one per group.
        assert lo == hi, f"{where}: a sheet line came out {lo:.4g} by {hi:.4g}"
        assert lo in (float(_PROCESS_STROKE), float(_SIGNAL_STROKE)), (
            f"{where}: drawn at {lo:.4g}, which is neither sheet weight"
        )
        seen += 1
    assert seen, f"{name} drew no stream or impulse line"


# --- deliberately resized units -----------------------------------------------

# One specimen per way a placement can meet a symbol: a plain vendored drawing;
# one of the four families the generator reproportions unevenly, whose declared
# pen is already an ellipse before any placement touches it; a symbol drawn by
# hand rather than vendored; one carrying fine detail at a deliberate fraction
# of its outline weight; and a symbol that may not be stretched at all, which
# keeps its aspect and is centred, so its pen stays round however odd the box.
_SPECIMENS = {
    "valve": lambda **kw: units.Valve("FV-1", **kw),
    "vessel": lambda **kw: units.Vessel("V-1", **kw),
    "vessel/horizontal": lambda **kw: units.Vessel("V-2", variant="horizontal", **kw),
    "hex/kettle": lambda **kw: units.HeatExchanger("E-1", variant="kettle", **kw),
    "column/packed": lambda **kw: units.Column("T-1", variant="packed", **kw),
    "mixer": lambda **kw: units.Mixer("M-1", **kw),
    "instrument": lambda **kw: units.Instrument("PI-101", **kw),
}

# Factors on the symbol's own box. The uniform pair is the case that shipped
# wrong and the one the invariant pins exactly; the rest reshape as well, one of
# them past anything a drawing would ask for, since a bound is only worth having
# where it is under strain.
_BOXES = {
    "natural": (1.0, 1.0),
    "twice": (2.0, 2.0),
    "smaller": (0.6, 0.6),
    "wider": (2.0, 1.0),
    "taller": (1.0, 2.5),
    "flattened": (3.0, 0.5),
}


@pytest.mark.parametrize("box", list(_BOXES), ids=list(_BOXES))
@pytest.mark.parametrize("spec", list(_SPECIMENS), ids=list(_SPECIMENS))
def test_a_resized_unit_is_drawn_with_the_pen_its_symbol_declares(spec, box):
    fx, fy = _BOXES[box]
    sym = default_registry.get(*(spec.split("/") + ["default"])[:2])
    fs = Flowsheet("weights")
    fs.add(_SPECIMENS[spec](width=sym.width * fx, height=sym.height * fy))
    check_symbol_weights(fs, fs.to_svg())


def test_a_uniformly_resized_valve_draws_at_the_sheet_weight_exactly(request):
    """The bug of #152 and #153, written out in the numbers it went wrong in.

    A gate valve's artwork is drawn under ``scale(0.25)`` and carries an 8.0 so
    it lands on the sheet's 2.0. Placed in a box 2.878 times its own -- which is
    what ``examples/07`` asked of the relief valve -- it used to come out at 5.8
    and merge into a blob. It is one symbol and one number, and no bound or mean
    is involved: a uniform resize must move the weight not at all.
    """
    for factor in (1.0, 2.878, 0.5, 4.0):
        sym = default_registry.get("valve", "gate")
        fs = Flowsheet("weights")
        fs.add(
            units.Valve(
                "FV-1", variant="gate", width=sym.width * factor, height=sym.height * factor
            )
        )
        for where, lo, hi in drawn_pens(fs.to_svg()):
            if not where.startswith("sym_valve"):
                continue
            assert lo == pytest.approx(float(_PROCESS_STROKE), rel=1e-5)
            assert hi == pytest.approx(float(_PROCESS_STROKE), rel=1e-5)
