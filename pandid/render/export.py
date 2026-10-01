"""Export the rendered SVG to PDF and PNG.

``.pdf`` goes through svglib (SVG to ReportLab drawing) and ReportLab;
``.png`` rasterises that PDF with pypdfium2. All ship pure-Python or
platform wheels. cairosvg is avoided because it loads libcairo at import
time and fails with ``OSError: no library called "cairo-2"`` where GTK is
absent.

svglib silently skips parts of SVG, four of which change a pandid drawing:

- ``<use>`` of a ``<symbol>`` ignores the reference's size and the
  viewBox, so equipment draws at its intrinsic size;
- ``marker-end`` is ignored, so PFD arrowheads disappear;
- ``dominant-baseline`` is ignored, so centred text sits about a quarter
  of its size high, off its halo;
- ``font-size`` is converted px to pt twice, so lettering is three
  quarters size while geometry is right.

:func:`flatten` rewrites the first three into plain geometry, and
:func:`_reject_unsupported` refuses any other construct svglib is known to
drop, so a new gap fails loudly. :func:`to_pdf` corrects the fourth on the
built drawing, using the ratio :func:`_type_scale` measures. The ``.svg``
output is unaffected.
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

# Constructs svglib is known to drop. flatten() removes some; the rest
# pandid does not emit yet, and are listed so export fails rather than
# silently dropping them.
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
    # Left only on an ancestor after _resolve_baselines(), so unapplied.
    "dominant-baseline": "a dominant-baseline away from the <text> it sets",
    "alignment-baseline": "an alignment-baseline",
}

# Absolute path commands pandid emits, with their argument counts: moves,
# lines and crossing arcs.
_PATH_ARITY = {"M": 2, "L": 2, "A": 7}
_PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _tag(name: str) -> str:
    """Return an SVG-namespaced element tag."""
    return f"{{{_SVG_NS}}}{name}"


def _local(tag: object) -> str:
    """Return the element name without its namespace."""
    return str(tag).rsplit("}", 1)[-1]


def _num(value: float) -> str:
    """Return a number with at most six decimals, trailing zeros removed."""
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


# -------------------------------------------------------- flatten


def _viewbox(el: ET.Element) -> tuple[float, float, float, float]:
    """Return an element's viewBox.

    Raises
    ------
    RuntimeError
        If it has no four-number viewBox.
    """
    parts = [float(v) for v in (el.get("viewBox") or "").replace(",", " ").split()]
    if len(parts) != 4:
        raise RuntimeError(f"{_local(el.tag)} {el.get('id')!r} has no usable viewBox")
    return parts[0], parts[1], parts[2], parts[3]


def _placement(use: ET.Element, symbol: ET.Element) -> str:
    """Return the transform placing ``symbol`` in the box ``use`` asks for.

    Applies the ``<symbol>`` viewport rule: scale the viewBox to the
    reference's size, uniformly and centred unless
    ``preserveAspectRatio="none"``. ``pandid.portgeom.ink_box`` uses the
    same rectangle for ports.

    Parameters
    ----------
    use : Element
        ``<use>`` element.
    symbol : Element
        ``<symbol>`` it references.

    Returns
    -------
    str
        SVG transform.
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
    """Return a ``<use>`` as a ``<g>`` holding a copy of its symbol.

    Raises
    ------
    RuntimeError
        If the reference names no ``<symbol>``.
    """
    href = use.get("href") or use.get(f"{{{_XLINK_NS}}}href") or ""
    symbol = symbols.get(href.lstrip("#"))
    if symbol is None:
        raise RuntimeError(f"<use> references {href!r}, which is not a <symbol> in <defs>")
    # The use's own rotate/mirror applies to the placed box.
    own = use.get("transform")
    transform = f"{own} {_placement(use, symbol)}" if own else _placement(use, symbol)
    group = ET.Element(_tag("g"), {"transform": transform})
    group.extend(copy.deepcopy(child) for child in symbol)
    return group


def _path_tail(d: str) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return a path's last two points, for its end angle.

    Raises
    ------
    RuntimeError
        If the path uses another command or has fewer than two points.
    """
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
    """Return ``el``'s end marker drawn as geometry, removing the attribute.

    Parameters
    ----------
    el : Element
        Element that may carry ``marker-end``.
    markers : dict[str, Element]
        Markers by id.

    Returns
    -------
    Element or None
        Group drawing the head, or ``None`` without a marker.

    Raises
    ------
    RuntimeError
        If the marker is missing or not in ``userSpaceOnUse`` units.
    """
    ref = el.attrib.pop("marker-end", None)
    if not ref:
        return None
    marker = markers.get(ref.removeprefix("url(#").removesuffix(")"))
    if marker is None:
        raise RuntimeError(f"marker-end={ref!r} names no <marker> in <defs>")
    if marker.get("markerUnits", "strokeWidth") != "userSpaceOnUse":
        # pandid never uses strokeWidth-scaled markers.
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
    """Expand every ``<use>`` and draw every end marker below ``parent``."""
    rewritten: list[ET.Element] = []
    for child in list(parent):
        if _local(child.tag) == "use":
            child = _expand_use(child, symbols)
        else:
            _rewrite(child, symbols, markers)
        rewritten.append(child)
        # Insert the head right after its element, keeping paint order.
        head = _arrowhead(child, markers)
        if head is not None:
            rewritten.append(head)
    parent[:] = rewritten


# ------------------------------------------------------ baselines
#
# svglib ignores dominant-baseline and sets text on its alphabetic baseline.
# The shift is a fixed fraction of font size, applied to ``y``.

# Baseline shift as ``wa * ascent + wd * descent`` (descent negative).
# Unknown values such as "hanging" are refused.
_BASELINES = {
    # Already the alphabetic baseline; "baseline" falls back to "auto".
    "auto": (0.0, 0.0),
    "alphabetic": (0.0, 0.0),
    "baseline": (0.0, 0.0),
    # "middle" uses "central": base-14 metrics have no x-height, and for
    # Helvetica the error is 0.006 em.
    "middle": (0.5, 0.5),
    "central": (0.5, 0.5),
}

# svglib maps pandid's sans-serif to ReportLab's base-14 Helvetica.
_FACES = {False: "Helvetica", True: "Helvetica-Bold"}
# Helvetica ascent and descent in ems, used when ReportLab is absent so
# flatten() gives the same result; a test checks them against pdfmetrics.
_HELVETICA_EM = (0.718, -0.207)


def _ascent_descent(bold: bool) -> tuple[float, float]:
    """Return the drawing face's ascent and descent, in ems.

    Parameters
    ----------
    bold : bool
        Whether the face is bold.

    Returns
    -------
    tuple[float, float]
        Ascent and (negative) descent.
    """
    try:
        from reportlab.pdfbase import pdfmetrics
    except ImportError:
        return _HELVETICA_EM
    ascent, descent = pdfmetrics.getAscentDescent(_FACES[bold], 1.0)
    return float(ascent), float(descent)


def _font_size(el: ET.Element, inherited: float | None) -> float | None:
    """Return the font size ``el`` sets, or the inherited one.

    Raises
    ------
    RuntimeError
        If the size is not a user-unit length.
    """
    raw = (el.get("font-size") or "").strip().removesuffix("px")
    if not raw:
        return inherited
    try:
        return float(raw)
    except ValueError:  # an em, a percentage, a keyword: not resolvable here
        raise RuntimeError(f"font-size={el.get('font-size')!r} is not a user-unit length") from None


def _set_baseline(text: ET.Element, size: float | None) -> None:
    """Fold one ``<text>``'s ``dominant-baseline`` into its ``y``.

    Raises
    ------
    RuntimeError
        If the value is unsupported or no font size applies.
    """
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
    """Fold every ``dominant-baseline`` below ``el`` into its ``y``."""
    size = _font_size(el, size)
    if _local(el.tag) == "text":
        # pandid writes no <tspan>; any baseline left is refused later.
        _set_baseline(el, size)
        return
    for child in el:
        _resolve_baselines(child, size)


def _reject_unsupported(root: ET.Element) -> None:
    """Raise if ``root`` still uses a construct svglib would drop.

    Raises
    ------
    RuntimeError
        Naming the first unsupported element or attribute.
    """
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
    """Return ``svg`` rewritten without ``<use>``, markers or baselines.

    The drawing is unchanged. ``<defs>`` is removed once its contents have
    been copied into place.

    Parameters
    ----------
    svg : str
        Rendered SVG.

    Returns
    -------
    str
        Equivalent SVG svglib can draw.

    Raises
    ------
    RuntimeError
        If anything svglib would drop remains.
    """
    ET.register_namespace("", _SVG_NS)
    ET.register_namespace("xlink", _XLINK_NS)
    root = ET.fromstring(svg)
    symbols = {el.get("id", ""): el for el in root.iter(_tag("symbol"))}
    markers = {el.get("id", ""): el for el in root.iter(_tag("marker"))}
    _rewrite(root, symbols, markers)
    # After expansion, so symbol lettering shifts in the symbol's units.
    _resolve_baselines(root)
    # Drop the now-copied definitions so the check sees only drawn content.
    for defs in root.findall(_tag("defs")):
        root.remove(defs)
    _reject_unsupported(root)
    return ET.tostring(root, encoding="unicode")


# --------------------------------------------------------- export


def _require(module: str, package: str, ext: str):
    """Import an optional backend module.

    Raises
    ------
    ImportError
        Naming the ``pandid[pdf]`` extra to install.
    """
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as e:
        raise ImportError(
            f"Exporting {ext} requires the optional {package} backend. "
            f"Install it with: pip install 'pandid[pdf]'"
        ) from e


# ------------------------------------------------------ type size
#
# svglib converts font-size px to pt and then scales the whole drawing px
# to pt again, so text draws at 0.75 size while geometry is right.
# _TYPE_PROBE draws a 100-unit square and a 100-unit capital; the ratio of
# their drawn sizes is the correction, and it becomes 1.0 if svglib is
# fixed.
_TYPE_PROBE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
    'viewBox="0 0 100 100">'
    '<rect x="0" y="0" width="100" height="100" />'
    '<text x="0" y="100" font-family="sans-serif" font-size="100">H</text>'
    "</svg>"
)


def _leaves(node, scale: float = 1.0):
    """Yield every drawn shape below ``node`` with its vertical scale.

    Only heights are compared, so only the transforms' y scale is used.

    Parameters
    ----------
    node : reportlab Group or shape
        Drawing node.
    scale : float, default=1.0
        Scale inherited from ancestors.

    Yields
    ------
    tuple
        ``(shape, scale)``.
    """
    contents = getattr(node, "contents", None)
    if contents is None:
        yield node, scale
        return
    for child in contents:
        yield from _leaves(child, scale * abs(node.transform[3]))


@functools.cache
def _type_scale() -> float:
    """Return the factor svglib's text size is off by.

    1.0 if svglib sizes text like geometry; 4/3 if it converts twice.

    Returns
    -------
    float
        Correction factor.

    Raises
    ------
    RuntimeError
        If the probe does not produce one rule and one string.
    """
    svglib = _require("svglib.svglib", "svglib", ".pdf")
    drawing = svglib.svg2rlg(io.BytesIO(_TYPE_PROBE.encode("utf-8")))
    # svg2rlg returns None on a failed parse; the count check reports it.
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
    """Scale every string's ``fontSize`` in ``drawing`` by ``factor``.

    Only font sizes change; ReportLab recomputes anchored text positions
    from them.

    Parameters
    ----------
    drawing : reportlab Drawing
        Drawing from svglib.
    factor : float
        Correction factor.
    """
    for shape, _ in _leaves(drawing):
        if hasattr(shape, "fontSize"):
            shape.fontSize *= factor


def to_pdf(svg: str) -> bytes:
    """Return ``svg`` as a one-page vector PDF at its own size.

    Parameters
    ----------
    svg : str
        Rendered SVG.

    Returns
    -------
    bytes
        PDF document.

    Raises
    ------
    ImportError
        If svglib or ReportLab is not installed.
    RuntimeError
        If the SVG cannot be drawn faithfully.
    """
    svglib = _require("svglib.svglib", "svglib", ".pdf")
    renderPDF = _require("reportlab.graphics.renderPDF", "reportlab", ".pdf")
    drawing = svglib.svg2rlg(io.BytesIO(flatten(svg).encode("utf-8")))
    if drawing is None:  # svglib returns None rather than raising on a bad parse
        raise RuntimeError("the PDF backend could not read the rendered SVG")
    _rescale_type(drawing, _type_scale())
    return renderPDF.drawToString(drawing)


def to_png(svg: str, scale: float = _PX_PER_PT) -> bytes:
    """Return ``svg`` rasterised from its PDF, so PNG and PDF agree.

    Parameters
    ----------
    svg : str
        Rendered SVG.
    scale : float, default=_PX_PER_PT
        Pixels per PDF point; the default gives the SVG's own pixel size.

    Returns
    -------
    bytes
        PNG image.

    Raises
    ------
    ImportError
        If an optional backend is not installed.
    RuntimeError
        If the SVG cannot be drawn faithfully.
    """
    pdfium = _require("pypdfium2", "pypdfium2", ".png")
    _require("PIL.Image", "pillow", ".png")
    page = pdfium.PdfDocument(to_pdf(svg))[0]
    buffer = io.BytesIO()
    page.render(scale=scale).to_pil().save(buffer, format="PNG")
    return buffer.getvalue()
