"""Export the rendered SVG to PDF and PNG.

The PDF is drawn with svglib and ReportLab; the PNG is that PDF
rasterised with pypdfium2.
"""

from __future__ import annotations

import copy
import functools
import io
import math
import re
import xml.etree.ElementTree as ET

from pandid.render.escape import fmt

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"

# CSS pixels per PDF point.
_PX_PER_PT = 96 / 72

# Elements and attributes svglib drops, with how an error names them.
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
    # Left only on an ancestor after _resolve_baselines().
    "dominant-baseline": "a dominant-baseline away from the <text> it sets",
    "alignment-baseline": "an alignment-baseline",
}

# Absolute path commands pandid emits, with their argument counts.
_PATH_ARITY = {"M": 2, "L": 2, "A": 7}
_PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _tag(name: str) -> str:
    """Return an SVG-namespaced element tag.

    Parameters
    ----------
    name : str
        Element name.

    Returns
    -------
    str
        Tag in ``{namespace}name`` form.
    """
    return f"{{{_SVG_NS}}}{name}"


def _local(tag: object) -> str:
    """Return an element tag without its namespace.

    Parameters
    ----------
    tag : object
        Element tag.

    Returns
    -------
    str
        Element name.
    """
    return str(tag).rsplit("}", 1)[-1]


# -------------------------------------------------------- flatten


def _viewbox(el: ET.Element) -> tuple[float, float, float, float]:
    """Return an element's viewBox.

    Parameters
    ----------
    el : Element
        Element with a ``viewBox`` attribute.

    Returns
    -------
    tuple[float, float, float, float]
        Minimum x, minimum y, width and height.

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
    """Return the transform placing a symbol in a ``<use>``'s box.

    The viewBox is scaled to the box, uniformly and centred unless
    ``preserveAspectRatio="none"``.

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
    ops = f"translate({fmt(tx, 6)}, {fmt(ty, 6)}) scale({fmt(sx, 6)}, {fmt(sy, 6)})"
    if vx or vy:
        ops += f" translate({fmt(-vx, 6)}, {fmt(-vy, 6)})"
    return ops


def _expand_use(use: ET.Element, symbols: dict[str, ET.Element]) -> ET.Element:
    """Return a ``<use>`` as a ``<g>`` holding a copy of its symbol.

    Parameters
    ----------
    use : Element
        ``<use>`` element.
    symbols : dict[str, Element]
        Symbols by id.

    Returns
    -------
    Element
        Group drawing the symbol.

    Raises
    ------
    RuntimeError
        If the reference names no ``<symbol>``.
    """
    href = use.get("href") or use.get(f"{{{_XLINK_NS}}}href") or ""
    symbol = symbols.get(href.lstrip("#"))
    if symbol is None:
        raise RuntimeError(f"<use> references {href!r}, which is not a <symbol> in <defs>")
    # The use's own transform applies to the placed box.
    own = use.get("transform")
    transform = f"{own} {_placement(use, symbol)}" if own else _placement(use, symbol)
    group = ET.Element(_tag("g"), {"transform": transform})
    group.extend(copy.deepcopy(child) for child in symbol)
    return group


def _path_tail(d: str) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return a path's last two points.

    Parameters
    ----------
    d : str
        Path data of absolute ``M``, ``L`` and ``A`` commands.

    Returns
    -------
    tuple[tuple[float, float], tuple[float, float]]
        Second-last and last points.

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
    """Remove an element's ``marker-end`` and return it as geometry.

    Parameters
    ----------
    el : Element
        Element that may carry ``marker-end``.
    markers : dict[str, Element]
        Markers by id.

    Returns
    -------
    Element or None
        Group drawing the head, or ``None`` without an end marker.

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
        raise RuntimeError("only markerUnits='userSpaceOnUse' can be flattened")

    _, _, vw, vh = _viewbox(marker)
    sx = float(marker.get("markerWidth", vw)) / vw
    sy = float(marker.get("markerHeight", vh)) / vh
    rx, ry = float(marker.get("refX", 0)), float(marker.get("refY", 0))
    (px, py), (ex, ey) = _path_tail(el.get("d") or "")
    # Turn the head to the direction the line arrives from.
    angle = math.degrees(math.atan2(ey - py, ex - px))
    group = ET.Element(
        _tag("g"),
        {
            "transform": (
                f"translate({fmt(ex, 6)}, {fmt(ey, 6)}) rotate({fmt(angle, 6)}) "
                f"scale({fmt(sx, 6)}, {fmt(sy, 6)}) translate({fmt(-rx, 6)}, {fmt(-ry, 6)})"
            )
        },
    )
    group.extend(copy.deepcopy(child) for child in marker)
    return group


def _rewrite(parent: ET.Element, symbols: dict, markers: dict) -> None:
    """Expand each ``<use>`` and end marker below an element.

    Parameters
    ----------
    parent : Element
        Element whose descendants are rewritten in place.
    symbols : dict
        Symbols by id.
    markers : dict
        Markers by id.
    """
    rewritten: list[ET.Element] = []
    for child in list(parent):
        if _local(child.tag) == "use":
            child = _expand_use(child, symbols)
        else:
            _rewrite(child, symbols, markers)
        rewritten.append(child)
        # Insert the head right after its element.
        head = _arrowhead(child, markers)
        if head is not None:
            rewritten.append(head)
    parent[:] = rewritten


# ------------------------------------------------------ baselines

# Baseline shift in ems as ``wa * ascent + wd * descent``, with descent
# negative, per supported ``dominant-baseline`` value.
_BASELINES = {
    "auto": (0.0, 0.0),
    "alphabetic": (0.0, 0.0),
    "baseline": (0.0, 0.0),
    # "middle" is drawn as "central".
    "middle": (0.5, 0.5),
    "central": (0.5, 0.5),
}

# Ascent and descent in ems of Helvetica and Helvetica-Bold, as
# ReportLab computes them.
_HELVETICA_EM = (718 * 0.001, -207 * 0.001)


def _set_baseline(text: ET.Element, size: float | None) -> None:
    """Fold one ``<text>``'s ``dominant-baseline`` into its ``y``.

    Parameters
    ----------
    text : Element
        ``<text>`` element, changed in place.
    size : float or None
        Font size that applies to it.

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
    ascent, descent = _HELVETICA_EM
    shift = (wa * ascent + wd * descent) * size
    if shift:
        text.set("y", fmt(float(text.get("y") or 0) + shift, 6))


def _resolve_baselines(el: ET.Element, size: float | None = None) -> None:
    """Fold every ``dominant-baseline`` below an element into ``y``.

    Parameters
    ----------
    el : Element
        Element to walk, changed in place.
    size : float or None, default=None
        Font size inherited from its ancestors.

    Raises
    ------
    RuntimeError
        If a font size is invalid or a baseline unsupported.
    """
    raw = (el.get("font-size") or "").strip().removesuffix("px")
    if raw:
        try:
            size = float(raw)
        except ValueError:
            raise RuntimeError(
                f"font-size={el.get('font-size')!r} is not a user-unit length") from None
    if _local(el.tag) == "text":
        _set_baseline(el, size)
        return
    for child in el:
        _resolve_baselines(child, size)


def _reject_unsupported(root: ET.Element) -> None:
    """Raise if an SVG tree uses a construct svglib would drop.

    Parameters
    ----------
    root : Element
        SVG root.

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
    """Return SVG with ``<use>``, markers and baselines drawn out.

    Each ``<use>`` becomes a copy of its symbol, each end marker
    becomes geometry, each ``dominant-baseline`` is folded into
    ``y`` and ``<defs>`` is removed.

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
    _resolve_baselines(root)
    for defs in root.findall(_tag("defs")):
        root.remove(defs)
    _reject_unsupported(root)
    return ET.tostring(root, encoding="unicode")


# --------------------------------------------------------- export


def _require(module: str, package: str, ext: str):
    """Import an optional backend module.

    Parameters
    ----------
    module : str
        Module to import.
    package : str
        Package name shown in the error.
    ext : str
        Output extension shown in the error.

    Returns
    -------
    module
        The imported module.

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

# A 100-unit square and a 100-unit capital, drawn to measure the factor
# svglib's text size is off by.
_TYPE_PROBE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
    'viewBox="0 0 100 100">'
    '<rect x="0" y="0" width="100" height="100" />'
    '<text x="0" y="100" font-family="sans-serif" font-size="100">H</text>'
    "</svg>"
)


def _leaves(node, scale: float = 1.0):
    """Yield every drawn shape below a node with its vertical scale.

    Parameters
    ----------
    node : reportlab Group or shape
        Drawing node.
    scale : float, default=1.0
        Vertical scale inherited from its ancestors.

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

    Returns
    -------
    float
        Ratio of a drawn rule's height to a drawn letter's size.

    Raises
    ------
    RuntimeError
        If the probe does not draw one rule and one string.
    """
    svglib = _require("svglib.svglib", "svglib", ".pdf")
    drawing = svglib.svg2rlg(io.BytesIO(_TYPE_PROBE.encode("utf-8")))
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


def to_pdf(svg: str) -> bytes:
    """Return SVG as a one-page vector PDF at its own size.

    Text is scaled by :func:`_type_scale`.

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
    if drawing is None:
        raise RuntimeError("the PDF backend could not read the rendered SVG")
    factor = _type_scale()
    for shape, _ in _leaves(drawing):
        if hasattr(shape, "fontSize"):
            shape.fontSize *= factor
    return renderPDF.drawToString(drawing)


def to_png(svg: str, scale: float = _PX_PER_PT) -> bytes:
    """Return SVG as a PNG rasterised from its PDF.

    Parameters
    ----------
    svg : str
        Rendered SVG.
    scale : float, default=_PX_PER_PT
        Pixels per PDF point; the default gives the SVG's pixel size.

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
