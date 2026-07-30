"""PDF and PNG export.

``.svg`` is the native output and needs nothing. ``.pdf`` and ``.png`` need a
renderer, and the renderer has to arrive as a *wheel*: an engineer who types
``pip install 'pandid[pdf]'`` on Windows has no compiler, no package manager and
no reason to install one.

That requirement is what this module exists for. The obvious backend, cairosvg,
does not meet it: cairosvg reaches libcairo through cairocffi, which ``dlopen``s
the shared library at import time and finds it only if the machine already has
GTK or something else that ships it. Nothing in any wheel provides it, so
``pip install 'pandid[pdf]'`` succeeded and then

    OSError: no library called "cairo-2" was found

came out of the *import*, on a machine that had done exactly what it was told.

The replacement is svglib (SVG -> ReportLab drawing) and ReportLab (drawing ->
PDF), both pure Python, with pypdfium2 rasterising that PDF for ``.png``.
pypdfium2 ships ``py3-none-<platform>`` wheels, so it carries PDFium with it and
does not care which interpreter it lands on.

The catch, and the reason for the first half of this file: svglib does not
implement all of SVG, and what it does not implement it *skips silently*.
Rendering the gallery sheets through it against a cairosvg reference, three gaps
change the meaning of the drawing:

- ``<use>`` of a ``<symbol>`` ignores the width/height on the reference and the
  viewBox on the definition, so every piece of equipment is drawn at its
  intrinsic size instead of the size the layout gave it. On 11_ethanol_pid the
  beer-column condenser came out about four fifths of its box and its process
  lines stopped in mid-air, several units short of their nozzles.
- ``marker-end`` is ignored outright, so on a PFD every flow arrow disappears.
  On a process flow diagram the arrowhead *is* the flow direction.
- ``dominant-baseline`` is ignored too, so a string the renderer centred on a
  point is drawn with its *baseline* there and rides about a quarter of its own
  type size high of where it belongs. Stream numbers, balloon tags and most
  equipment labels are centred that way onto a white halo struck round the same
  point, so the halo and the lettering inside it came apart: 2.7 px of a 13 px
  halo, on the two sheet elements a reader reads first. The comparison that
  found the other two did not find this one, having stripped ``<text>`` before
  comparing.

All three are mechanical to resolve, and pandid wrote the SVG so it knows
exactly what shapes they take. :func:`flatten` resolves them into plain geometry
and plain coordinates before svglib sees any of it, and
:func:`_reject_unsupported` then refuses to export at all if the renderer has
grown some *other* construct this file does not know about, so the next gap is a
loud failure rather than a quietly wrong drawing.

The ``.svg`` output itself is untouched: flattening happens on the way to the
PDF and nowhere else.
"""

from __future__ import annotations

import copy
import io
import math
import re
import xml.etree.ElementTree as ET

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"

# A CSS px is 1/96 inch and a PDF point is 1/72, so a PDF page carrying an SVG
# at its stated physical size rasterises back to the SVG's own pixel count at
# exactly this scale. cairosvg's default PNG was that pixel count; this keeps it.
_PX_PER_PT = 96 / 72

# Constructs that reach the page in a browser and do not reach it in svglib.
# Some are what flatten() removes and must therefore be gone by the time the
# check runs; the rest are ones pandid does not emit today, listed so that the
# day it starts emitting one the export stops instead of dropping it. Only
# things svglib is *known* to ignore belong here: a false alarm would refuse a
# drawing that would have exported perfectly well.
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
    # _resolve_baselines() takes this off every <text> it can place, so what is
    # left is one on an ancestor, inherited by whatever text is below it: a
    # shift this file has not applied and svglib will not either.
    "dominant-baseline": "a dominant-baseline away from the <text> it sets",
    "alignment-baseline": "an alignment-baseline",
}

# Absolute path commands and how many numbers each takes. pandid emits only
# these: a route is moves and lines, with an elliptical arc where one line hops
# over another. A relative or curve command would mean the renderer changed.
_PATH_ARITY = {"M": 2, "L": 2, "A": 7}
_PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _tag(name: str) -> str:
    return f"{{{_SVG_NS}}}{name}"


def _local(tag: object) -> str:
    """The element name without its namespace."""
    return str(tag).rsplit("}", 1)[-1]


def _num(value: float) -> str:
    # Six decimals is well below a rasteriser's ability to tell two positions
    # apart at any plate size, and keeps the intermediate SVG readable when a
    # failure has to be looked at by hand.
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


# --------------------------------------------------------------------- flatten


def _viewbox(el: ET.Element) -> tuple[float, float, float, float]:
    parts = [float(v) for v in (el.get("viewBox") or "").replace(",", " ").split()]
    if len(parts) != 4:
        raise RuntimeError(f"{_local(el.tag)} {el.get('id')!r} has no usable viewBox")
    return parts[0], parts[1], parts[2], parts[3]


def _placement(use: ET.Element, symbol: ET.Element) -> str:
    """The transform that puts *symbol* into the box *use* asks for.

    This is the ``<symbol>`` viewport rule written out: scale the viewBox to the
    reference's width and height, and, unless the definition gave up its aspect
    ratio, keep the scale uniform and centre what is left over. ``pandid`` marks
    exactly the definitions some placement reshapes with
    ``preserveAspectRatio="none"``, and ``pandid.portgeom.ink_box`` resolves
    ports against the same centred rectangle, so the two agree by construction.
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
    """One ``<use>`` as a ``<g>`` holding a copy of what it referenced."""
    href = use.get("href") or use.get(f"{{{_XLINK_NS}}}href") or ""
    symbol = symbols.get(href.lstrip("#"))
    if symbol is None:
        raise RuntimeError(f"<use> references {href!r}, which is not a <symbol> in <defs>")
    # Composed right to left, so the reference's own transform is applied to the
    # placed box rather than inside it -- which is what the renderer meant by
    # putting rotate() and the mirror on the <use> and not on the <symbol>.
    own = use.get("transform")
    transform = f"{own} {_placement(use, symbol)}" if own else _placement(use, symbol)
    group = ET.Element(_tag("g"), {"transform": transform})
    group.extend(copy.deepcopy(child) for child in symbol)
    return group


def _path_tail(d: str) -> tuple[tuple[float, float], tuple[float, float]]:
    """The last point on a path and the one before it, for the arrival angle."""
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
    """The ``marker-end`` of *el* drawn where the marker would have gone.

    Returns ``None`` if *el* wears no end marker. The attribute is removed
    either way, since it has been honoured here and nothing downstream reads it.
    """
    ref = el.attrib.pop("marker-end", None)
    if not ref:
        return None
    marker = markers.get(ref.removeprefix("url(#").removesuffix(")"))
    if marker is None:
        raise RuntimeError(f"marker-end={ref!r} names no <marker> in <defs>")
    if marker.get("markerUnits", "strokeWidth") != "userSpaceOnUse":
        # strokeWidth units would scale the head by the line it ends, which is
        # a second rule to reproduce and one pandid has never asked for.
        raise RuntimeError("only markerUnits='userSpaceOnUse' can be flattened")

    _, _, vw, vh = _viewbox(marker)
    sx = float(marker.get("markerWidth", vw)) / vw
    sy = float(marker.get("markerHeight", vh)) / vh
    rx, ry = float(marker.get("refX", 0)), float(marker.get("refY", 0))
    (px, py), (ex, ey) = _path_tail(el.get("d") or "")
    # orient="auto" turns the head to the direction the line arrives from, and
    # "auto-start-reverse" differs from it only for marker-start.
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
    """Replace every ``<use>`` below *parent*, and draw every end marker."""
    rewritten: list[ET.Element] = []
    for child in list(parent):
        if _local(child.tag) == "use":
            child = _expand_use(child, symbols)
        else:
            _rewrite(child, symbols, markers)
        rewritten.append(child)
        # A marker paints after the element wearing it and before the next
        # sibling, so the head goes here rather than at the end of the parent:
        # the white halo that knocks a line out from under a label is painted
        # by z-order too, and moving anything past it would show through.
        head = _arrowhead(child, markers)
        if head is not None:
            rewritten.append(head)
    parent[:] = rewritten


# ------------------------------------------------------------------- baselines
#
# svglib maps ``text-anchor`` and nothing else about how a string sets: search it
# for ``dominant-baseline`` and there is no match, so every ``<text>`` is drawn
# with its alphabetic baseline on the ``y`` it was given, whatever the file asked
# for. The attribute is alignment rather than geometry, but the geometry it
# stands for is a fixed fraction of the font size, so honouring it here is
# arithmetic on ``y``: work out where the baseline has to go and hand the backend
# the plain one it does read. Written in the same user units the font size is in,
# that shift rides through whatever transform is above it -- a symbol placed at a
# third of its size shifts its lettering by a third as much, which is what the
# same file does in a browser.

# Where each value puts the alphabetic baseline relative to the anchored point,
# in ascent and descent: ``shift = wa * ascent + wd * descent``, descent being
# negative. Anything not here is refused rather than guessed at: ``hanging``, the
# one a renderer is next likeliest to reach for, is a baseline a browser reads
# out of the font and ReportLab's base-14 metrics do not carry, so placing it
# would be the quiet wrongness this module exists to prevent.
_BASELINES = {
    # The value names the baseline svglib already draws on, so there is nothing
    # to do but take the attribute off. "baseline" is not one of the SVG 1.1
    # keywords and a browser falls back to "auto" for it, which is this;
    # pandid emits it above a unit, where the y it computed is a baseline.
    "auto": (0.0, 0.0),
    "alphabetic": (0.0, 0.0),
    "baseline": (0.0, 0.0),
    # ``middle`` is half the *x-height* above the alphabetic baseline and
    # ``central`` the middle of the ascent/descent box, and only the second can
    # be answered from what ReportLab holds for a base-14 face: there is no
    # x-height in it. cairosvg, the backend this one replaced, made the same
    # substitution and said so in a comment of its own. For Helvetica it is
    # 0.2555 em against a true 0.2615 em: 0.006 em, which is 0.07 px on a
    # sheet's 12 px lettering and below what any plate size can resolve.
    "middle": (0.5, 0.5),
    "central": (0.5, 0.5),
}

# The face the backend will draw with. pandid writes font-family="sans-serif" on
# every string it draws, and svglib resolves that generic family onto ReportLab's
# base 14 -- the ``/BaseFont /Helvetica`` an exported PDF carries.
_FACES = {False: "Helvetica", True: "Helvetica-Bold"}
# ...and that face's ascent and descent in ems, for a machine without the
# optional extra: flatten() is checked against every golden sheet whether or not
# the backend is installed to draw one, and must not answer differently for its
# absence. A test holds these to what pdfmetrics says where both are present.
_HELVETICA_EM = (0.718, -0.207)


def _ascent_descent(bold: bool) -> tuple[float, float]:
    """The drawing face's ascent and descent, as fractions of its em."""
    try:
        from reportlab.pdfbase import pdfmetrics
    except ImportError:
        return _HELVETICA_EM
    # Asking pdfmetrics is asking the backend the same question it answers for
    # itself when it draws, rather than a constant that is right for one face.
    ascent, descent = pdfmetrics.getAscentDescent(_FACES[bold], 1.0)
    return float(ascent), float(descent)


def _font_size(el: ET.Element, inherited: float | None) -> float | None:
    """The size *el* is set in, in user units, or the one it inherits."""
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
    """Fold every ``dominant-baseline`` below *el* into the ``y`` it stands for."""
    size = _font_size(el, size)
    if _local(el.tag) == "text":
        # And no further down: a ``<tspan>`` is not something pandid writes, and
        # one wearing a baseline of its own would need a ``y`` of its own to
        # move. Left for _reject_unsupported, which refuses the attribute
        # wherever it is still set by the time it looks.
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
    """*svg* with ``<use>``, ``marker-end`` and ``dominant-baseline`` resolved.

    The drawing is unchanged; only the way it is written down is. Anything the
    PDF backend would have dropped without saying so raises instead.
    """
    ET.register_namespace("", _SVG_NS)
    ET.register_namespace("xlink", _XLINK_NS)
    root = ET.fromstring(svg)
    symbols = {el.get("id", ""): el for el in root.iter(_tag("symbol"))}
    markers = {el.get("id", ""): el for el in root.iter(_tag("marker"))}
    _rewrite(root, symbols, markers)
    # After the expansion, so that a symbol's own lettering -- the "M" on a motor
    # operator -- is placed in the units the symbol is drawn in and then scaled
    # by whatever placed it, rather than in the sheet's.
    _resolve_baselines(root)
    # <defs> now holds only definitions that have been copied to where they were
    # used. Dropping it is what makes the check below meaningful.
    for defs in root.findall(_tag("defs")):
        root.remove(defs)
    _reject_unsupported(root)
    return ET.tostring(root, encoding="unicode")


# ---------------------------------------------------------------------- export


def _require(module: str, package: str, ext: str):
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as e:
        raise ImportError(
            f"Exporting {ext} requires the optional {package} backend. "
            f"Install it with: pip install 'pandid[pdf]'"
        ) from e


def to_pdf(svg: str) -> bytes:
    """*svg* as a one-page PDF, drawn as vectors at the sheet's physical size."""
    svglib = _require("svglib.svglib", "svglib", ".pdf")
    renderPDF = _require("reportlab.graphics.renderPDF", "reportlab", ".pdf")
    drawing = svglib.svg2rlg(io.BytesIO(flatten(svg).encode("utf-8")))
    if drawing is None:  # svglib returns None rather than raising on a bad parse
        raise RuntimeError("the PDF backend could not read the rendered SVG")
    return renderPDF.drawToString(drawing)


def to_png(svg: str, scale: float = _PX_PER_PT) -> bytes:
    """*svg* rasterised, by way of the same PDF, so the two agree by construction."""
    pdfium = _require("pypdfium2", "pypdfium2", ".png")
    _require("PIL.Image", "pillow", ".png")
    page = pdfium.PdfDocument(to_pdf(svg))[0]
    buffer = io.BytesIO()
    page.render(scale=scale).to_pil().save(buffer, format="PNG")
    return buffer.getvalue()
