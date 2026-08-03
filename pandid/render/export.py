"""PDF and PNG export.

``.svg`` is the native output and needs nothing. ``.pdf`` and ``.png``
go through svglib (SVG -> ReportLab drawing) and ReportLab (drawing ->
PDF), with pypdfium2 rasterising that PDF for ``.png``. All three are
pure Python or ship ``py3-none-<platform>`` wheels. cairosvg does not:
it reaches libcairo through cairocffi, which ``dlopen``s the shared
library at import time, so ``pip install 'pandid[pdf]'`` succeeds and
then

    OSError: no library called "cairo-2" was found

comes out of the *import* on a machine that has GTK nowhere.

svglib does not implement all of SVG, and what it does not implement it
*skips silently*. Measured against a cairosvg reference over the gallery
sheets, four gaps change the meaning of the drawing:

- ``<use>`` of a ``<symbol>`` ignores the width/height on the reference
  and the viewBox on the definition, so equipment is drawn at its
  intrinsic size instead of the size the layout gave it.
- ``marker-end`` is ignored outright, so on a PFD every flow arrow
  disappears.
- ``dominant-baseline`` is ignored, so a string centred on a point is
  drawn with its *baseline* there and rides about a quarter of its type
  size high. The opaque halo is struck round the same point and does not
  move, so the two come apart: 2.7 px of a 13 px halo.
- ``font-size`` is converted px to pt *and* the drawing the string sits
  in is scaled px to pt, so lettering comes out at three quarters of the
  size the file asked for while geometry beside it comes out right.

:func:`flatten` resolves the first three into plain geometry and plain
coordinates before svglib sees any of it, and
:func:`_reject_unsupported` then refuses to export at all if the
renderer has grown some *other* construct this file does not know about,
so the next gap is a loud failure rather than a quietly wrong drawing.

The fourth is applied twice rather than skipped, so no rewriting of the
SVG can state it away. :func:`_type_scale` measures the ratio and
:func:`to_pdf` corrects it on the drawing, after svglib has built it and
before ReportLab draws it.

The ``.svg`` output itself is untouched: both happen on the way to the
PDF and nowhere else.
"""

from __future__ import annotations

import copy
import functools
import io
import math
import re
import xml.etree.ElementTree as ET

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"

# A CSS px is 1/96 inch and a PDF point is 1/72, so a PDF page carrying
# an SVG at its stated physical size rasterises back to the SVG's own
# pixel count at exactly this scale.
_PX_PER_PT = 96 / 72

# Constructs that reach the page in a browser and do not reach it in
# svglib. Some are what flatten() removes and must therefore be gone by
# the time the check runs; the rest are ones pandid does not emit today,
# listed so that the day it starts emitting one the export stops instead
# of dropping it. Only things svglib is *known* to ignore belong here: a
# false alarm would refuse a drawing that would have exported perfectly
# well.
_UNSUPPORTED_TAGS = {
    "use": "a <use> reference",
    "symbol": "a <symbol> definition",
    "marker": "a <marker> definition",
    "clipPath": "a clipping path",
    "mask": "a mask",
    "filter": "a filter",
    "pattern": "a pattern fill",
    "textPath": "text on a path",
    "switch": "a <switch>",
    "foreignObject": "a foreign object",
}
_UNSUPPORTED_ATTRS = {
    "marker-start": "a start marker",
    "marker-mid": "a mid marker",
    "marker-end": "an end marker",
    "clip-path": "a clip-path reference",
    "mask": "a mask reference",
    "filter": "a filter reference",
    # _resolve_baselines() takes this off every <text> it can place, so
    # what is left is one on an ancestor, inherited by whatever text is
    # below it: a shift this file has not applied and svglib will not
    # either.
    "dominant-baseline": "a dominant-baseline away from the <text> it sets",
    "alignment-baseline": "an alignment-baseline",
}

# Absolute path commands and how many numbers each takes. pandid emits
# only these: a route is moves and lines, with an elliptical arc where
# one line hops over another. A relative or curve command would mean the
# renderer changed.
_PATH_ARITY = {"M": 2, "L": 2, "A": 7}
_PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _tag(name: str) -> str:
    return f"{{{_SVG_NS}}}{name}"


def _local(tag: object) -> str:
    """The element name without its namespace."""
    return str(tag).rsplit("}", 1)[-1]


def _num(value: float) -> str:
    # Six decimals is below what a rasteriser can resolve at any plate
    # size, and keeps the intermediate SVG legible by hand.
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


# -------------------------------------------------------- flatten


def _viewbox(el: ET.Element) -> tuple[float, float, float, float]:
    parts = [float(v) for v in (el.get("viewBox") or "").replace(",", " ").split()]
    if len(parts) != 4:
        raise RuntimeError(f"{_local(el.tag)} {el.get('id')!r} has no usable viewBox")
    return parts[0], parts[1], parts[2], parts[3]


def _placement(use: ET.Element, symbol: ET.Element) -> str:
    """The transform that puts *symbol* into the box *use* asks for.

    The ``<symbol>`` viewport rule written out: scale the viewBox to the
    reference's width and height, and, unless the definition gave up its
    aspect ratio, keep the scale uniform and centre what is left over.
    ``pandid.portgeom.ink_box`` resolves ports against that same centred
    rectangle, so the two agree by construction.
    """
    vx, vy, vw, vh = _viewbox(symbol)
    x, y = float(use.get("x", 0)), float(use.get("y", 0))
    w, h = float(use.get("width", vw)), float(use.get("height", vh))
    if symbol.get("preserveAspectRatio") == "none":
        sx, sy = w / vw, h / vh
        tx, ty = x, y
    else:  # the xMidYMid meet default
        sx = sy = min(w / vw, h / vh)
        tx, ty = x + (w - vw * sx) / 2, y + (h - vh * sy) / 2
    ops = f"translate({_num(tx)}, {_num(ty)}) scale({_num(sx)}, {_num(sy)})"
    if vx or vy:
        ops += f" translate({_num(-vx)}, {_num(-vy)})"
    return ops


def _expand_use(use: ET.Element, symbols: dict[str, ET.Element]) -> ET.Element:
    """One ``<use>`` as a ``<g>`` holding a copy of what it named."""
    href = use.get("href") or use.get(f"{{{_XLINK_NS}}}href") or ""
    symbol = symbols.get(href.lstrip("#"))
    if symbol is None:
        raise RuntimeError(f"<use> references {href!r}, which is not a <symbol> in <defs>")
    # Composed right to left, so the reference's own transform applies
    # to the placed box rather than inside it -- which is what the
    # renderer meant by putting rotate() and the mirror on the <use>.
    own = use.get("transform")
    transform = f"{own} {_placement(use, symbol)}" if own else _placement(use, symbol)
    group = ET.Element(_tag("g"), {"transform": transform})
    group.extend(copy.deepcopy(child) for child in symbol)
    return group


def _path_tail(d: str) -> tuple[tuple[float, float], tuple[float, float]]:
    """The last point on a path and the one before, for its angle."""
    tokens = _PATH_TOKEN.findall(d)
    points: list[tuple[float, float]] = []
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        arity = _PATH_ARITY.get(cmd)
        if arity is None:
            raise RuntimeError(f"path command {cmd!r} is not one this module can measure")
        nums = [float(v) for v in tokens[i + 1 : i + 1 + arity]]
        points.append((nums[-2], nums[-1]))
        i += 1 + arity
    if len(points) < 2:
        raise RuntimeError("a path wearing a marker has fewer than two points")
    return points[-2], points[-1]


def _arrowhead(el: ET.Element, markers: dict[str, ET.Element]) -> ET.Element | None:
    """The ``marker-end`` of *el* drawn where the marker would have
    gone.

    Returns ``None`` if *el* wears no end marker. The attribute is
    removed either way, since it has been honoured here and nothing
    downstream reads it.
    """
    ref = el.attrib.pop("marker-end", None)
    if not ref:
        return None
    marker = markers.get(ref.removeprefix("url(#").removesuffix(")"))
    if marker is None:
        raise RuntimeError(f"marker-end={ref!r} names no <marker> in <defs>")
    if marker.get("markerUnits", "strokeWidth") != "userSpaceOnUse":
        # strokeWidth units scale the head by the line it ends, which is
        # a second rule to reproduce and one pandid has never asked for.
        raise RuntimeError("only markerUnits='userSpaceOnUse' can be flattened")

    _, _, vw, vh = _viewbox(marker)
    sx = float(marker.get("markerWidth", vw)) / vw
    sy = float(marker.get("markerHeight", vh)) / vh
    rx, ry = float(marker.get("refX", 0)), float(marker.get("refY", 0))
    (px, py), (ex, ey) = _path_tail(el.get("d") or "")
    # orient="auto" turns the head to the direction the line arrives
    # from; "auto-start-reverse" differs from it only for marker-start.
    angle = math.degrees(math.atan2(ey - py, ex - px))
    group = ET.Element(
        _tag("g"),
        {
            "transform": (
                f"translate({_num(ex)}, {_num(ey)}) rotate({_num(angle)}) "
                f"scale({_num(sx)}, {_num(sy)}) translate({_num(-rx)}, {_num(-ry)})"
            )
        },
    )
    group.extend(copy.deepcopy(child) for child in marker)
    return group


def _rewrite(parent: ET.Element, symbols: dict, markers: dict) -> None:
    """Replace every ``<use>`` below *parent*; draw every end marker."""
    rewritten: list[ET.Element] = []
    for child in list(parent):
        if _local(child.tag) == "use":
            child = _expand_use(child, symbols)
        else:
            _rewrite(child, symbols, markers)
        rewritten.append(child)
        # A marker paints after the element wearing it and before the
        # next sibling, so the head goes here and not at the end of the
        # parent: the halo that knocks a line out from under a label is
        # painted by z-order too.
        head = _arrowhead(child, markers)
        if head is not None:
            rewritten.append(head)
    parent[:] = rewritten


# ------------------------------------------------------ baselines
#
# svglib maps ``text-anchor`` and nothing else about how a string sets:
# search it for ``dominant-baseline`` and there is no match, so every
# ``<text>`` is drawn with its alphabetic baseline on the ``y`` it was
# given. The geometry the attribute stands for is a fixed fraction of
# the font size, so honouring it here is arithmetic on ``y``. Written in
# the same user units the font size is in, that shift rides through
# whatever transform is above it, as it does in a browser.

# Where each value puts the alphabetic baseline relative to the anchored
# point, in ascent and descent: ``shift = wa * ascent + wd * descent``,
# descent being negative. Anything not here is refused rather than
# guessed at: ``hanging`` is a baseline a browser reads out of the font
# and ReportLab's base-14 metrics do not carry.
_BASELINES = {
    # The value names the baseline svglib already draws on, so there is
    # nothing to do but take the attribute off. "baseline" is not an SVG
    # 1.1 keyword and a browser falls back to "auto" for it, which is
    # this; pandid emits it above a unit, where the y it computed is a
    # baseline.
    "auto": (0.0, 0.0),
    "alphabetic": (0.0, 0.0),
    "baseline": (0.0, 0.0),
    # ``middle`` is half the *x-height* above the alphabetic baseline
    # and ``central`` the middle of the ascent/descent box, and only the
    # second can be answered from what ReportLab holds for a base-14
    # face: there is no x-height in it. For Helvetica the substitution
    # is 0.2555 em against a true 0.2615 em, which is 0.07 px on a
    # sheet's 12 px lettering.
    "middle": (0.5, 0.5),
    "central": (0.5, 0.5),
}

# The face the backend will draw with. pandid writes
# font-family="sans-serif" on every string, and svglib resolves that
# generic family onto ReportLab's base 14 -- the ``/BaseFont
# /Helvetica`` an exported PDF carries.
_FACES = {False: "Helvetica", True: "Helvetica-Bold"}
# ...and that face's ascent and descent in ems, for a machine without
# the optional extra: flatten() is checked against every golden sheet
# whether or not the backend is installed to draw one, and must not
# answer differently for its absence. A test holds these to what
# pdfmetrics says where both are present.
_HELVETICA_EM = (0.718, -0.207)


def _ascent_descent(bold: bool) -> tuple[float, float]:
    """The drawing face's ascent and descent, as fractions of its em."""
    try:
        from reportlab.pdfbase import pdfmetrics
    except ImportError:
        return _HELVETICA_EM
    ascent, descent = pdfmetrics.getAscentDescent(_FACES[bold], 1.0)
    return float(ascent), float(descent)


def _font_size(el: ET.Element, inherited: float | None) -> float | None:
    """The size *el* is set in, in user units, or the one inherited."""
    raw = (el.get("font-size") or "").strip().removesuffix("px")
    if not raw:
        return inherited
    try:
        return float(raw)
    except ValueError:  # an em, a percentage, a keyword: not resolvable here
        raise RuntimeError(f"font-size={el.get('font-size')!r} is not a user-unit length") from None


def _set_baseline(text: ET.Element, size: float | None) -> None:
    """One ``<text>``'s ``dominant-baseline`` folded into its ``y``."""
    value = (text.attrib.pop("dominant-baseline", None) or "").strip()
    if not value:
        return
    if value not in _BASELINES:
        raise RuntimeError(
            f"the PDF/PNG backend cannot draw dominant-baseline={value!r}, and would have "
            f"placed the text by its baseline instead. pandid.render.export needs to learn it."
        )
    if size is None:
        raise RuntimeError(
            f"dominant-baseline={value!r} moves the text by a fraction of its font size, "
            f"and this <text> sets none and inherits none"
        )
    wa, wd = _BASELINES[value]
    ascent, descent = _ascent_descent((text.get("font-weight") or "").strip() == "bold")
    shift = (wa * ascent + wd * descent) * size
    if shift:
        text.set("y", _num(float(text.get("y") or 0) + shift))


def _resolve_baselines(el: ET.Element, size: float | None = None) -> None:
    """Fold every ``dominant-baseline`` below *el* into its ``y``."""
    size = _font_size(el, size)
    if _local(el.tag) == "text":
        # And no further down: pandid writes no ``<tspan>``, and one
        # wearing a baseline of its own would need a ``y`` of its own to
        # move. Left for _reject_unsupported, which refuses the
        # attribute wherever it is still set by the time it looks.
        _set_baseline(el, size)
        return
    for child in el:
        _resolve_baselines(child, size)


def _reject_unsupported(root: ET.Element) -> None:
    for el in root.iter():
        name = _local(el.tag)
        if name in _UNSUPPORTED_TAGS:
            raise RuntimeError(
                f"the PDF/PNG backend cannot draw {_UNSUPPORTED_TAGS[name]}, and would "
                f"have dropped it silently. pandid.render.export needs to learn it."
            )
        for attr, described in _UNSUPPORTED_ATTRS.items():
            if attr in el.attrib:
                raise RuntimeError(
                    f"the PDF/PNG backend cannot draw {described} (on <{name}>), and "
                    f"would have dropped it silently. pandid.render.export needs to "
                    f"learn it."
                )


def flatten(svg: str) -> str:
    """*svg* with ``<use>``, ``marker-end`` and ``dominant-baseline``
    resolved.

    The drawing is unchanged; only the way it is written down is.
    Anything the PDF backend would have dropped without saying so raises
    instead.
    """
    ET.register_namespace("", _SVG_NS)
    ET.register_namespace("xlink", _XLINK_NS)
    root = ET.fromstring(svg)
    symbols = {el.get("id", ""): el for el in root.iter(_tag("symbol"))}
    markers = {el.get("id", ""): el for el in root.iter(_tag("marker"))}
    _rewrite(root, symbols, markers)
    # After the expansion, so a symbol's own lettering -- the "M" on a
    # motor operator -- is placed in the units the symbol is drawn in
    # and then scaled by whatever placed it, rather than in the sheet's.
    _resolve_baselines(root)
    # <defs> now holds only definitions that have been copied to where
    # they were used. Dropping it is what makes the check below mean
    # something.
    for defs in root.findall(_tag("defs")):
        root.remove(defs)
    _reject_unsupported(root)
    return ET.tostring(root, encoding="unicode")


# --------------------------------------------------------- export


def _require(module: str, package: str, ext: str):
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as e:
        raise ImportError(
            f"Exporting {ext} requires the optional {package} backend. "
            f"Install it with: pip install 'pandid[pdf]'"
        ) from e


# ------------------------------------------------------ type size
#
# svglib turns a length into points twice on the way to a glyph and once
# on the way to a line. ``convertLengthToPt`` multiplies ``font-size``
# by its px-to-pt 0.75 to set the ReportLab ``String``'s ``fontSize``,
# and the group holding the whole drawing is then scaled by that same
# 0.75 to take user units to points -- so every string is drawn inside a
# transform that has already made the conversion its own size carries.
# Geometry takes the factor once and lands right; lettering lands at
# three quarters. Measured against a rule of the same declared length in
# the same document, a 100-unit capital drew a cap height 0.752 of the
# 0.718 em Helvetica declares while the rule drew 1.000 of its length.
#
# One multiplier on every ``String`` puts it back, and it is measured
# rather than written down. _TYPE_PROBE declares a square and a capital
# at one size, so whatever svg2rlg makes of it states what a glyph is
# drawn at against what a line of the same length is, and the ratio
# between them is the whole correction. On an svglib that has stopped
# converting twice it reads 1.0 and nothing is applied, which is the
# difference between this ageing into a no-op and it ageing into
# lettering four thirds too big with nothing to say so.
_TYPE_PROBE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
    'viewBox="0 0 100 100">'
    '<rect x="0" y="0" width="100" height="100" />'
    '<text x="0" y="100" font-family="sans-serif" font-size="100">H</text>'
    "</svg>"
)


def _leaves(node, scale: float = 1.0):
    """Every drawn shape below *node*, with the scale it will be drawn
    at.

    A group's transform applies to its children rather than to itself,
    and both of the things weighed against each other here are heights,
    so the y term of that transform is all either needs from it.
    """
    contents = getattr(node, "contents", None)
    if contents is None:
        yield node, scale
        return
    for child in contents:
        yield from _leaves(child, scale * abs(node.transform[3]))


@functools.cache
def _type_scale() -> float:
    """What svglib's idea of a string's size is out by, as a factor.

    One on a backend that sizes type the way it sizes everything else,
    and four thirds on one that has taken the px-to-pt conversion twice.
    """
    svglib = _require("svglib.svglib", "svglib", ".pdf")
    drawing = svglib.svg2rlg(io.BytesIO(_TYPE_PROBE.encode("utf-8")))
    # svg2rlg returns None rather than raising on a parse it cannot make
    # sense of, which the count below reports as the nothing it is.
    leaves = list(_leaves(drawing)) if drawing is not None else []
    rule = [scale * shape.height for shape, scale in leaves if hasattr(shape, "height")]
    letter = [scale * shape.fontSize for shape, scale in leaves if hasattr(shape, "fontSize")]
    if len(rule) != 1 or len(letter) != 1:
        raise RuntimeError(
            f"the PDF backend drew the type probe as {len(rule)} rules and {len(letter)} "
            f"strings rather than one of each, so the size it sets type at cannot be "
            f"measured against the size it draws a line at. pandid.render.export needs "
            f"to learn what it does now."
        )
    return rule[0] / letter[0]


def _rescale_type(drawing, factor: float) -> None:
    """Draw every string in *drawing* at *factor* times the size svglib
    set it.

    Nothing but ``fontSize`` moves, so no geometry can follow it. What a
    ``text-anchor`` of ``middle`` or ``end`` shifts a string by is
    worked out from that same ``fontSize`` when ReportLab draws it, so a
    centred label is re-centred on the new size rather than left on the
    old one.
    """
    for shape, _ in _leaves(drawing):
        if hasattr(shape, "fontSize"):
            shape.fontSize *= factor


def to_pdf(svg: str) -> bytes:
    """*svg* as a one-page PDF, drawn as vectors at its own size."""
    svglib = _require("svglib.svglib", "svglib", ".pdf")
    renderPDF = _require("reportlab.graphics.renderPDF", "reportlab", ".pdf")
    drawing = svglib.svg2rlg(io.BytesIO(flatten(svg).encode("utf-8")))
    if drawing is None:  # svglib returns None rather than raising on a bad parse
        raise RuntimeError("the PDF backend could not read the rendered SVG")
    _rescale_type(drawing, _type_scale())
    return renderPDF.drawToString(drawing)


def to_png(svg: str, scale: float = _PX_PER_PT) -> bytes:
    """*svg* rasterised by way of that PDF, so the two agree."""
    pdfium = _require("pypdfium2", "pypdfium2", ".png")
    _require("PIL.Image", "pillow", ".png")
    page = pdfium.PdfDocument(to_pdf(svg))[0]
    buffer = io.BytesIO()
    page.render(scale=scale).to_pil().save(buffer, format="PNG")
    return buffer.getvalue()
