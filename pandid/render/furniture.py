"""Draw sheet furniture: title strip, titled boxes, tables, stream table, border.

Each routine is a pure function returning SVG fragment strings or a
``(width, height)`` measurement. :mod:`pandid.render.svg` measures each
piece, places it, sizes the canvas and draws it.

:func:`dock` does the placement and is not SVG: it maps measured boxes to
sheet rectangles, and both the SVG and draw.io backends use it.

Coordinates are absolute SVG user units. Boxes are drawn from a top-left
origin; the title strip from its bottom-right corner.
"""

from __future__ import annotations

import dataclasses
import math
import string
import unicodedata
from typing import Any, Callable, NamedTuple

from pandid.document import _drawn_text
from pandid.render.escape import escaped

FONT = "sans-serif"

# Advance widths of FONT in thousandths of the type size, for ASCII
# 32..126 and Latin-1 160..255. These are the Adobe Core-14 Helvetica AFM
# advances: svglib maps ``sans-serif`` to Helvetica for PDF and PNG
# (:mod:`pandid.render.export`), and Arial and Liberation Sans share
# Helvetica's advances. DejaVu Sans is wider, which errs towards spare room.
# ``tests/test_text_width.py`` checks them against ReportLab.
_ADVANCE = (
    (  # Helvetica, 32..126
        278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
        556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
        1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
        667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
        333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
        556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
    ),
    (  # Helvetica, 160..255
        278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333,
        400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611,
        667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
        722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
        556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278,
        556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500, 556, 500,
    ),
)
_ADVANCE_BOLD = (
    (  # Helvetica-Bold, 32..126
        278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
        556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
        975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
        667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
        333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
        611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
    ),
    (  # Helvetica-Bold, 160..255
        278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333,
        400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611,
        722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
        722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
        556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278,
        611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556,
    ),
)

# Flat advance, in thousandths, for a narrow codepoint outside the table
# (Greek, Cyrillic and other non-Latin-1 text), slightly above Helvetica's
# ASCII mean so it errs towards spare room. Wide codepoints are charged a
# full em and combining marks nothing (:func:`script_counts`).
_ADV = 560
_ADV_BOLD = 620

#: Callback a fixed-width cell reports an overflow through:
#: ``(field, text, drawn, room, need)``, giving the field, the requested
#: text, the text drawn (the same if untrimmed), and the cell's room and
#: the text's width in drawing units. ``field`` is the field the author
#: edits, written ``source -> cell`` where another field supplied the value
#: (a blank ``title`` draws the flowsheet name, a blank ``date`` today's).
Reporter = Callable[[str, str, str, float, float], None]


def script_counts(s: str) -> "tuple[int, int, int]":
    """Return how many codepoints of ``s`` are narrow, wide or zero-width.

    Wide and fullwidth codepoints (``unicodedata.east_asian_width`` W or F)
    draw about a full em. Ambiguous ones are counted narrow, the UAX #11
    default without context. Combining marks (categories Mn and Me) advance
    nothing. Used by the tag halo
    (:func:`pandid.render.svg._unit_label_box`) and block labels
    (:func:`pandid.render.symbols.label_span`).

    Parameters
    ----------
    s : str
        Text.

    Returns
    -------
    tuple[int, int, int]
        ``(narrow, wide, zero)`` counts.
    """
    narrow = wide = zero = 0
    for ch in s:
        if unicodedata.category(ch) in ("Mn", "Me"):
            zero += 1
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            wide += 1
        else:
            narrow += 1
    return narrow, wide, zero


def text_width(s, size: float, bold: bool = False) -> float:
    """Return the drawn width of ``s`` at ``size``, without padding.

    Measured glyph by glyph from the face's advances (:data:`_ADVANCE`),
    because the result decides whether a table sheet fits its page
    (:func:`_partition`). Outside the table, a narrow codepoint is charged
    the flat rate, a wide one a full em and a combining mark nothing. The
    sum is in integer thousandths, scaled once, so it does not depend on
    character order.

    Parameters
    ----------
    s : object
        Text; converted with ``str``.
    size : float
        Font size in drawing units.
    bold : bool, default=False
        Use the bold advances.

    Returns
    -------
    float
        Width in drawing units.
    """
    s = str(s)
    table = _ADVANCE_BOLD if bold else _ADVANCE
    flat = _ADV_BOLD if bold else _ADV
    thousandths = 0
    for ch in s:
        c = ord(ch)
        if 0x20 <= c <= 0x7E:
            thousandths += table[0][c - 0x20]
        elif 0xA0 <= c <= 0xFF:
            thousandths += table[1][c - 0xA0]
        elif unicodedata.category(ch) in ("Mn", "Me"):
            continue
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            thousandths += 1000
        else:
            thousandths += flat
    return thousandths * size / 1000


def _total(values) -> float:
    """Return the sum of ``values``, added left to right.

    Avoids ``sum()``, whose compensated algorithm (CPython 3.12+) can
    differ in the last bit from the running ``+=`` used to position each
    piece, which would make one-decimal centring differ between Python
    versions.

    Parameters
    ----------
    values : iterable of float
        Values to add.

    Returns
    -------
    float
        Running total.
    """
    total = 0.0
    for v in values:
        total += v
    return total


def clip(s, room: float, size: float, bold: bool = False, *,
         field: str = "", report: "Reporter | None" = None) -> str:
    """Trim a value to its cell's room with an ellipsis, and report the cut.

    Title-block cells are fixed, so an overlong value is abbreviated. The
    longest prefix whose text plus ellipsis :func:`text_width` says fits is
    kept, measured whole so no float rounding drops a character that fits.

    Parameters
    ----------
    s : object
        Value; converted with ``str``.
    room : float
        Cell width.
    size : float
        Font size.
    bold : bool, default=False
        Measure in bold.
    field : str, default=""
        Field name for the report.
    report : Reporter, optional
        Receives a finding when the value is trimmed.

    Returns
    -------
    str
        The value, or a trimmed prefix ending in an ellipsis.
    """
    s = str(s)
    need = text_width(s, size, bold)
    if need <= room:
        return s
    ellipsis = "…"
    # Measure each candidate with its ellipsis against the room itself,
    # rather than subtracting the ellipsis width, which rounds.
    kept = 0
    while (kept < len(s)
           and text_width(s[:kept + 1] + ellipsis, size, bold) <= room):
        kept += 1
    drawn = s[:kept].rstrip() + ellipsis
    if report is not None:
        report(field, s, drawn, room, need)
    return drawn


def check_fit(s, room: float, size: float, bold: bool = False, *,
              field: str = "", report: "Reporter | None" = None) -> str:
    """Return a value unchanged, reporting it if it overruns its cell.

    For values that must not be trimmed, such as a sheet count or a company
    name.

    Parameters
    ----------
    s : object
        Value; converted with ``str``.
    room : float
        Cell width.
    size : float
        Font size.
    bold : bool, default=False
        Measure in bold.
    field : str, default=""
        Field name for the report.
    report : Reporter, optional
        Receives a finding when the value overruns.

    Returns
    -------
    str
        The value as a string.
    """
    s = str(s)
    need = text_width(s, size, bold)
    if report is not None and need > room:
        report(field, s, s, room, need)
    return s


def report_once(report: "Reporter") -> "Reporter":
    """Wrap a reporter so each distinct finding is passed on once.

    A repeated value, such as a word repeated across wrapped company-name
    lines, would otherwise report once per line. The key is the whole
    finding, so different fields stay separate.

    Parameters
    ----------
    report : Reporter
        Reporter to wrap.

    Returns
    -------
    Reporter
        De-duplicating reporter.
    """
    seen: set[tuple[str, str, str, float, float]] = set()

    def once(field: str, text: str, drawn: str,
             room: float, need: float) -> None:
        """Pass on a finding not seen before."""
        key = (field, text, drawn, room, need)
        if key not in seen:
            seen.add(key)
            report(field, text, drawn, room, need)

    return once


def fit_size(s, room: float, size: float, floor: float,
             bold: bool = False) -> float:
    """Return the largest size, at most ``size`` and at least ``floor``, that fits.

    For display text such as the drawing title; values matched against other
    documents (drawing number, date) are trimmed or reported instead.
    :func:`text_width` is linear in size, so the result is
    ``size * room / need`` rounded down to the tenth :func:`_text` writes.

    Parameters
    ----------
    s : object
        Text.
    room : float
        Cell width.
    size : float
        Preferred font size.
    floor : float
        Smallest allowed size.
    bold : bool, default=False
        Measure in bold.

    Returns
    -------
    float
        Font size.
    """
    need = text_width(s, size, bold)
    if need <= room or need <= 0 or room <= 0:
        return size
    return max(floor, math.floor(size * room / need * 10) / 10)


def _text(x, y, s, size, *, anchor="start", bold=False, fill="black", baseline=None):
    """Return an SVG ``<text>`` element with escaped content.

    Parameters
    ----------
    x, y : float
        Anchor point.
    s : str
        Text.
    size : float
        Font size.
    anchor : str, default="start"
        ``text-anchor``.
    bold : bool, default=False
        Set bold.
    fill : str, default="black"
        Text colour.
    baseline : str, optional
        ``dominant-baseline``.

    Returns
    -------
    str
        SVG element.
    """
    wt = ' font-weight="bold"' if bold else ""
    bl = f' dominant-baseline="{baseline}"' if baseline else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size:.1f}"'
            f' text-anchor="{anchor}"{wt}{bl} fill="{fill}">{escaped(s)}</text>')


# ----------------------------------------------------------------
# Generic titled box (Annotation): title bar over rows
# ----------------------------------------------------------------

# Rule weights of a titled box and the line under its title; drawio states
# them on the exported table container.
_BOX_RULE = 1.5
_BOX_UNDERLINE = 1.0
# Cell rule weight of a TableBox, lighter so the grid does not compete with
# the drawing.
_CELL_RULE = 0.75

#: Rule weights of the sheet border: the sheet edge, the drawing frame and
#: the zone ticks. Not on :class:`~pandid.render.weights.LineWeight`, since
#: ISO 10628-1 5.3.1 governs the diagram, not the sheet. Shared by both
#: backends.
SHEET_RULE = 1.0
FRAME_RULE = 2.0
ZONE_TICK = 0.75


def _ann_layout(ann):
    """Return an Annotation's font size, row height, title height and column widths.

    Parameters
    ----------
    ann : Annotation
        Box to measure.

    Returns
    -------
    tuple[float, float, float, list[float]]
        ``(size, row_h, title_h, col_w)``.
    """
    size = ann.font_size
    row_h = size + 7
    title_h = size + 12 if ann.title else 0
    ncol = max((len(r) for r in ann.rows if isinstance(r, (tuple, list))), default=1)
    col_w = [0.0] * ncol
    for r in ann.rows:
        if isinstance(r, (tuple, list)):
            for i, c in enumerate(r):
                col_w[i] = max(col_w[i], text_width(c, size))
        else:
            col_w[0] = max(col_w[0], text_width(r, size))
    return size, row_h, title_h, col_w


def measure_annotation(ann) -> tuple[float, float]:
    """Return an Annotation's drawn size.

    Parameters
    ----------
    ann : Annotation
        Box to measure.

    Returns
    -------
    tuple[float, float]
        ``(width, height)``; ``ann.width`` wins where set.
    """
    size, row_h, title_h, col_w = _ann_layout(ann)
    pad, gap = 9.0, 12.0
    body_w = _total(col_w) + gap * (len(col_w) - 1)
    inner = max(body_w, text_width(ann.title, size + 1, bold=True))
    w = ann.width if ann.width is not None else inner + 2 * pad
    h = title_h + len(ann.rows) * row_h + 8
    return w, h


def _overflowing_text(ann, size: float, body_w: float) -> str:
    """Return the string to report for a box too narrow for its content.

    Parameters
    ----------
    ann : Annotation
        Box.
    size : float
        Body font size.
    body_w : float
        Width the rows need.

    Returns
    -------
    str
        The title if it overruns, otherwise the widest row.
    """
    if text_width(ann.title, size + 1, bold=True) > body_w:
        return ann.title

    def flat(r):
        """Return a row as one string."""
        return "   ".join(str(c) for c in r) if isinstance(r, (tuple, list)) else str(r)
    return max((flat(r) for r in ann.rows), key=lambda s: text_width(s, size),
               default=ann.title)


def draw_annotation(ann, x: float, y: float, *,
                    report: "Reporter | None" = None) -> list[str]:
    """Return an Annotation drawn with its top-left corner at ``(x, y)``.

    A self-sized box always fits. With an explicit ``width``, rows keep
    their measured column stops, so a too-small width overruns the box
    and is reported.

    Parameters
    ----------
    ann : Annotation
        Box to draw.
    x, y : float
        Top-left corner.
    report : Reporter, optional
        Receives a finding when an explicit width is too small.

    Returns
    -------
    list[str]
        SVG elements.
    """
    size, row_h, title_h, col_w = _ann_layout(ann)
    pad, gap = 9.0, 12.0
    w, h = measure_annotation(ann)
    if report is not None and ann.width is not None:
        body_w = _total(col_w) + gap * (len(col_w) - 1)
        inner = max(body_w, text_width(ann.title, size + 1, bold=True))
        if ann.width < inner + 2 * pad:
            over = _overflowing_text(ann, size, body_w)
            # Report the stated width against the measured one.
            report(f"annotation {ann.title!r} (width={ann.width:g})", over, over,
                   ann.width, inner + 2 * pad)
    L = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
         f'fill="white" stroke="black" stroke-width="{_BOX_RULE:g}"/>']
    if ann.title:
        L.append(_text(x + w / 2, y + title_h - 6, ann.title, size + 1,
                       anchor="middle", bold=True))
        L.append(f'<line x1="{x:.1f}" y1="{y + title_h:.1f}" x2="{x + w:.1f}" '
                 f'y2="{y + title_h:.1f}" stroke="black" '
                 f'stroke-width="{_BOX_UNDERLINE:g}"/>')
    ry = y + title_h + row_h - 4
    for r in ann.rows:
        if isinstance(r, (tuple, list)):
            cx = x + pad
            for i, c in enumerate(r):
                L.append(_text(cx, ry, c, size, bold=(i == 0 and len(r) > 1)))
                cx += col_w[i] + gap
        else:
            L.append(_text(x + pad, ry, r, size))
        ry += row_h
    return L


# ----------------------------------------------------------------
# Generic bordered table (TableBox)
# ----------------------------------------------------------------

def _table_layout(tb):
    """Return a TableBox's font size, column count, column widths and row height.

    Parameters
    ----------
    tb : TableBox
        Table to measure.

    Returns
    -------
    tuple[float, int, list[float], float]
        ``(size, ncol, col_w, row_h)``.
    """
    size = tb.font_size
    ncol = max(len(tb.headers), max((len(r) for r in tb.rows), default=0))
    col_w = [0.0] * ncol
    for ci in range(ncol):
        cells = [tb.headers[ci]] if ci < len(tb.headers) else []
        cells += [r[ci] for r in tb.rows if ci < len(r)]
        col_w[ci] = max((text_width(c, size, bold=True) for c in cells), default=20.0) + 14
    row_h = size + 12
    return size, ncol, col_w, row_h


def measure_table(tb) -> tuple[float, float]:
    """Return a TableBox's drawn size.

    Parameters
    ----------
    tb : TableBox
        Table to measure.

    Returns
    -------
    tuple[float, float]
        ``(width, height)``.
    """
    size, ncol, col_w, row_h = _table_layout(tb)
    title_h = size + 10 if tb.title else 0
    nrows = len(tb.rows) + (1 if tb.headers else 0)
    return _total(col_w), title_h + nrows * row_h


def draw_table(tb, x: float, y: float) -> list[str]:
    """Return a TableBox drawn with its top-left corner at ``(x, y)``.

    Parameters
    ----------
    tb : TableBox
        Table to draw.
    x, y : float
        Top-left corner.

    Returns
    -------
    list[str]
        SVG elements.
    """
    size, ncol, col_w, row_h = _table_layout(tb)
    title_h = size + 10 if tb.title else 0
    w = _total(col_w)
    align = tb.col_align or ["c"] * ncol
    L = []
    if tb.title:
        L.append(_text(x + w / 2, y + title_h - 6, tb.title, size,
                       anchor="middle", bold=True))
    top = y + title_h

    def _row(ry, cells, *, header):
        """Append one ruled row at ``ry``."""
        cx = x
        for ci in range(ncol):
            val = cells[ci] if ci < len(cells) else ""
            fill = "#eee" if header else "white"
            L.append(f'<rect x="{cx:.1f}" y="{ry:.1f}" width="{col_w[ci]:.1f}" '
                     f'height="{row_h:.1f}" fill="{fill}" stroke="black" '
                     f'stroke-width="{_CELL_RULE:g}"/>')
            a = align[ci] if ci < len(align) else "c"
            if a == "l":
                tx, anc = cx + 5, "start"
            elif a == "r":
                tx, anc = cx + col_w[ci] - 5, "end"
            else:
                tx, anc = cx + col_w[ci] / 2, "middle"
            L.append(_text(tx, ry + row_h / 2 + size / 3, val, size,
                           anchor=anc, bold=header))
            cx += col_w[ci]

    ry = top
    if tb.headers:
        _row(ry, tb.headers, header=True)
        ry += row_h
    for r in tb.rows:
        _row(ry, list(r), header=False)
        ry += row_h
    return L


# ----------------------------------------------------------------
# Stream property table (a heading row of line numbers, a row per
# property, section headings where the flowsheet asks for them)
# ----------------------------------------------------------------
#
# stream_table_layout gives each cell's position and text; draw_stream_table
# strokes it, and pandid.render.drawio builds table cells from the same
# layout.

# Clearance added to the widest heading or value in a stream-table column.
_STREAM_GUTTER = 14.0

# Gutter before left-aligned text; drawio applies it less its own inset.
_STREAM_PAD = 5.0

# Fills for the heading row, section headings, row labels and values,
# lightening from heading to value.
_STREAM_HEAD_FILL = "#eee"
_STREAM_SECTION_FILL = "#f4f4f4"
_STREAM_KEY_FILL = "#f9f9f9"
_STREAM_VALUE_FILL = "white"

# Type size for up to 18 columns; the row depth and column-width floors
# (:class:`~pandid.document.StreamTableOptions`) scale with a stated size
# relative to this one.
_BASE_SIZE = 10.5

# Row depth at _BASE_SIZE.
_ROW_H = 20.0


def _width_floor(stated: float | str, name: str, ruled: float) -> float:
    """Return a column-width floor in drawing units.

    A number is scaled by ``ruled``, like :data:`_ROW_H`; ``"auto"`` means
    no floor, since columns are measured from their content anyway.

    Parameters
    ----------
    stated : float or str
        Floor from :class:`~pandid.document.StreamTableOptions`, or
        ``"auto"``.
    name : str
        Option name, for error messages.
    ruled : float
        Scale relative to :data:`_BASE_SIZE`.

    Returns
    -------
    float
        Floor width.

    Raises
    ------
    ValueError
        If ``stated`` is not a number or ``"auto"``, or is negative.
    """
    if stated == "auto":
        return 0.0
    if isinstance(stated, bool) or not isinstance(stated, (int, float)):
        raise ValueError(
            f"fs.stream_table.{name}={stated!r}: a column width is a number "
            f"of drawing units (the floor the column is held up to), or "
            f'"auto" to rule the column to its content'
        )
    if stated < 0:
        raise ValueError(
            f"fs.stream_table.{name}={stated!r}: a column width floor is not "
            f'a negative number; use 0 or "auto" for no floor'
        )
    return stated * ruled


def _options(fs):
    """Return the sheet's :class:`~pandid.document.StreamTableOptions`.

    Parameters
    ----------
    fs : Flowsheet
        Sheet; defaults apply when it has no options.

    Returns
    -------
    StreamTableOptions
        Options.
    """
    from pandid.document import StreamTableOptions
    options = getattr(fs, "stream_table", None)
    return StreamTableOptions() if options is None else options


# Warning code for a stream_table_sections key that matched no property.
# Checked at render time, since the streams may not exist when it is set.
_UNUSED_SECTION_CODE = "stream-table-section-unused"


def _report_unused_sections(fs, sec_before: dict[str, str], seen: set) -> None:
    """Replace warnings for sections whose property no stream sets.

    Earlier warnings of this code are dropped, so a fixed section stops
    warning.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose warnings are updated.
    sec_before : dict[str, str]
        Property key to section label.
    seen : set
        Property keys some stream sets.
    """
    from pandid.validate import Issue

    unused = [Issue(
        "warning", _UNUSED_SECTION_CODE,
        f"stream_table_sections names {key!r}, which no stream in the table "
        f"sets, so its heading {label!r} never appears"
    ) for key, label in sec_before.items() if key not in seen]
    fs.warnings = [w for w in fs.warnings
                   if getattr(w, "code", "") != _UNUSED_SECTION_CODE] + unused


class StreamCell(NamedTuple):
    """One ruled cell of the stream table.

    Attributes
    ----------
    text : str
        Cell text.
    w : float
        Cell width; a section heading is one cell spanning the table.
    fill : str
        Fill colour.
    bold : bool
        Set bold.
    anchor : str
        SVG ``text-anchor``: ``"start"`` for labels, ``"middle"`` for
        values.
    """
    text: str
    w: float
    fill: str
    bold: bool
    anchor: str


class StreamTable(NamedTuple):
    """Stream property table geometry, shared by both backends.

    Attributes
    ----------
    rows : list[list[StreamCell]]
        Rows top to bottom, cells left to right.
    size : float
        Font size.
    row_h : float
        Depth of every row.
    w, h : float
        Table size, as passed to :func:`dock`.
    """
    rows: list
    size: float
    row_h: float
    w: float
    h: float


def _stream_cell_text(values, key) -> str:
    """Return a column's text for one property row, ``"-"`` if missing.

    Parameters
    ----------
    values : dict
        The column's property values.
    key : str
        Property.

    Returns
    -------
    str
        Cell text.
    """
    val = values.get(key, "-")
    return "-" if val in (None, "") else str(val)


def _run_values(run) -> dict:
    """Return one column's property values, gathered over the whole run.

    A run drawn through inline devices is several streams in one column.
    Segments are read in drawing order, the first value of a key winning,
    except that a segment marked :attr:`~pandid.streams.Stream.tabulate`
    is read first; segments may legitimately differ, such as pressure
    either side of a control valve.

    Parameters
    ----------
    run : list[Stream]
        Segments of one named run.

    Returns
    -------
    dict
        Property key to value.

    Raises
    ------
    ValueError
        If more than one segment is marked ``tabulate``.
    """
    marked = [s for s in run if s.tabulate]
    if len(marked) > 1:
        raise ValueError(
            f"{run[0].name} is drawn in {len(run)} segments and {len(marked)} of them "
            f"are marked tabulate=True. The run is one column in the stream table, so "
            f"the mark says which segment's properties that column reports and only one "
            f"segment can be the answer. Clear the mark on all but the point you mean, "
            f"or break the run into two lines at the device between them with "
            f"unit.new_line_number = True, which gives each its own number and its own "
            f"column"
        )
    values: dict = {}
    for s in marked + [s for s in run if not s.tabulate]:
        for key, value in s.properties.items():
            values.setdefault(key, value)
    return values


def _table_runs(fs) -> list:
    """Return the runs that get a column, in sheet order.

    One column per name, never for signals. A run with no property is
    dropped (ISO 10628-1:2014 4.3.3 a) makes internal flows optional),
    unless it crosses the sheet edge
    (:attr:`pandid.streams.Stream.at_boundary`): 4.3.2 d) requires every
    ingoing and outgoing material, so its empty column shows the omission.
    A property present but blank keeps a column. Both tests cover the whole
    run.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    list[list[Stream]]
        Each run's segments.
    """
    return [run for run in fs._named_runs().values()
            if any(s.properties for s in run) or any(s.at_boundary for s in run)]


def _table_streams(fs) -> list:
    """Return the stream each column is headed from, in sheet order.

    The first segment of each run in :func:`_table_runs`; the values are
    gathered over the run (:func:`_run_values`).

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    list[Stream]
        Heading streams.
    """
    return [run[0] for run in _table_runs(fs)]


class _Measured(NamedTuple):
    """Stream table measurements shared by the docked and sheet layouts.

    Settled over the whole table, so blocks of a table sheet share one
    ruling.

    Attributes
    ----------
    streams : list[Stream]
        Heading stream per column.
    cells : list[dict]
        Values per column.
    disp : list[tuple[str, str]]
        Rows as ``("section", label)`` or ``("prop", key)``.
    heading : str
        Text of the top-left heading cell.
    size : float
        Font size.
    row_h : float
        Row depth.
    label_w : float
        Label column width before section headings.
    name_w : float
        Width of every stream column.
    span : float
        Total width a section heading needs; resolved per layout by
        :func:`_section_span`.
    """
    streams: list
    cells: list
    disp: list
    heading: str
    size: float
    row_h: float
    label_w: float
    name_w: float
    span: float


def _section_span(m: "_Measured", columns: int) -> float:
    """Return the label column width needed to fit section headings.

    Section headings span the table, so the label column takes up any
    shortfall.

    Parameters
    ----------
    m : _Measured
        Measurements.
    columns : int
        Stream columns beside the label column.

    Returns
    -------
    float
        Label column width.
    """
    return max(m.label_w, m.span - m.name_w * columns)


def _stream_rows(m: "_Measured", streams: list, cells: list,
                 label_w: float) -> list[list[StreamCell]]:
    """Return the table's cells row by row for the given columns.

    A table sheet block passes its own slice, so each block gets its own
    heading row.

    Parameters
    ----------
    m : _Measured
        Measurements.
    streams : list[Stream]
        Heading streams for these columns.
    cells : list[dict]
        Values for these columns.
    label_w : float
        Label column width.

    Returns
    -------
    list[list[StreamCell]]
        Rows.
    """
    rows: list[list[StreamCell]] = [
        [StreamCell(m.heading, label_w, _STREAM_HEAD_FILL, True, "start")]
        + [StreamCell(s.name, m.name_w, _STREAM_HEAD_FILL, True, "middle")
           for s in streams]]
    for kind, key in m.disp:
        if kind == "section":
            rows.append([StreamCell(key, label_w + m.name_w * len(streams),
                                    _STREAM_SECTION_FILL, True, "start")])
            continue
        rows.append(
            [StreamCell(key, label_w, _STREAM_KEY_FILL, True, "start")]
            + [StreamCell(_stream_cell_text(c, key), m.name_w,
                          _STREAM_VALUE_FILL, False, "middle")
               for c in cells])
    return rows


def _stream_table(m: "_Measured", streams: list, cells: list,
                  label_w: float) -> StreamTable:
    """Return a table over the given columns: whole, or one sheet block.

    Parameters
    ----------
    m : _Measured
        Measurements.
    streams : list[Stream]
        Heading streams.
    cells : list[dict]
        Values.
    label_w : float
        Label column width.

    Returns
    -------
    StreamTable
        Table geometry.
    """
    rows = _stream_rows(m, streams, cells, label_w)
    return StreamTable(rows, m.size, m.row_h,
                       label_w + m.name_w * len(streams),
                       m.row_h * len(rows))


def stream_table_layout(fs) -> "StreamTable | None":
    """Return the stream table docked on a diagram, as one block.

    Measured from its contents, never abbreviated; the sheet grows to fit
    or a too-small page is refused. :func:`stream_table_sheet` lays the same
    table out on a sheet of its own.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    StreamTable or None
        Table geometry, or ``None`` with nothing to tabulate.

    Raises
    ------
    ValueError
        If the stream-table options are invalid.
    """
    m = _measure(fs)
    if m is None:
        return None
    return _stream_table(m, m.streams, m.cells,
                         _section_span(m, len(m.streams)))


def _measure(fs, *, own_sheet: bool = False) -> "_Measured | None":
    """Return the table's measurements, or ``None`` with nothing to tabulate.

    Nothing to tabulate means no run gets a column, or no run states a
    property.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    own_sheet : bool, default=False
        The table is a sheet of its own, which changes only the default
        type size.

    Returns
    -------
    _Measured or None
        Measurements.

    Raises
    ------
    ValueError
        If the stream-table options are invalid.
    """
    runs = _table_runs(fs)
    if not runs:
        return None
    streams = [run[0] for run in runs]  # what each column is headed from
    cells = [_run_values(run) for run in runs]  # and what goes down it

    # Property rows in first-seen order over every segment of every run.
    order, seen = [], set()
    for run in runs:
        for s in run:
            for k in s.properties:
                if k not in seen:
                    seen.add(k)
                    order.append(k)
    sec_before: dict[str, str] = {}
    for key, label in (getattr(fs, "stream_table_sections", []) or []):
        sec_before.setdefault(key, label)
    _report_unused_sections(fs, sec_before, seen)
    if not order:
        return None

    n = len(streams)
    options = _options(fs)
    asked = options.font_size
    if asked is not None and asked <= 0:
        raise ValueError(
            f"fs.stream_table.font_size={asked!r}: a type size is a positive "
            f"number of drawing units, or None to let the table pick one from "
            f"how many columns it has"
        )
    if asked is None and own_sheet:
        # A table sheet wraps columns rather than shrinking type, paged or
        # not, so one table is lettered the same on any sheet.
        size, row_h, ruled = _BASE_SIZE, _ROW_H, 1.0
    elif asked is None:
        # 10.5 up to 18 columns, then smaller. The column floors do not
        # shrink, so a wide table stays readable across.
        size = _BASE_SIZE if n <= 18 else max(8.0, 190.0 / n)
        row_h = _ROW_H if n <= 18 else max(15.0, size + 5)
        ruled = 1.0
    else:
        # A stated size scales the row height and column floors too, so the
        # table's footprint shrinks with it. The gutter and pad do not
        # scale: they are clearances, not type.
        size = asked
        ruled = size / _BASE_SIZE
        row_h = _ROW_H * ruled
    disp = []  # ('section', label) | ('data', key)
    for k in order:
        if k in sec_before:
            disp.append(("section", sec_before[k]))
        disp.append(("data", k))
    # "Line Number" only when every column has a line number.
    heading = ("Line Number" if all(s.has_line_number for s in streams)
               else "Stream Number")

    # Size columns to their content, held up to a floor the sheet may lower
    # or drop (label_width, column_width).
    labels = [heading] + [key for kind, key in disp if kind == "data"]
    label_w = max(_width_floor(options.label_width, "label_width", ruled),
                  max(text_width(t, size, bold=True)
                      for t in labels) + _STREAM_GUTTER)
    values = [_stream_cell_text(c, key) for kind, key in disp if kind == "data"
              for c in cells]
    # One width for every stream column, over all headings and values, so
    # columns line up when read across.
    name_w = max(_width_floor(options.column_width, "column_width", ruled),
                 max((text_width(s.name, size, bold=True) for s in streams),
                     default=0.0) + _STREAM_GUTTER,
                 max((text_width(v, size) for v in values), default=0.0)
                 + _STREAM_GUTTER)
    # Width a section heading needs; resolved per layout by _section_span.
    sections = [label for kind, label in disp if kind == "section"]
    span = max((text_width(t, size, bold=True) for t in sections),
               default=0.0) + _STREAM_GUTTER
    return _Measured(streams, cells, disp, heading, size, row_h,
                     label_w, name_w, span)


# Gap between table-sheet blocks, in rows, so it follows the type size.
_BLOCK_ROWS = 1.0


class TableSheet(NamedTuple):
    """Stream table on a sheet of its own, cut into stacked blocks.

    Blocks are flush left, so property rows can be followed down the
    label column (:meth:`at`).

    Attributes
    ----------
    blocks : list[StreamTable]
        Blocks, top to bottom.
    gap : float
        Space between blocks.
    w : float
        Widest block.
    h : float
        Whole stack, gaps included.
    """
    blocks: list
    gap: float
    w: float
    h: float

    def at(self, left: float, top: float):
        """Yield each block with the corner it is drawn from.

        Both backends place blocks through this.

        Parameters
        ----------
        left, top : float
            Corner of the stack.

        Yields
        ------
        tuple[int, StreamTable, float, float]
            ``(index, block, x, y)``.
        """
        y = top
        for i, block in enumerate(self.blocks):
            yield i, block, left, y
            y += block.h + self.gap


def _blocks_of(n: int, count: int) -> list:
    """Return ``n`` column indices shared evenly over ``count`` blocks.

    Each block gets ``n // count``, with the remainder one apiece to the
    first blocks, so blocks differ by at most one column (ten over four is
    3/3/2/2). :func:`_partition` measures these exact shapes.

    Parameters
    ----------
    n : int
        Number of columns.
    count : int
        Number of blocks; capped at ``n``.

    Returns
    -------
    list[list[int]]
        Column indices per block.
    """
    count = min(count, n)  # an empty block is not a block
    per, extra = divmod(n, count)
    blocks, start = [], 0
    for i in range(count):
        stop = start + per + (1 if i < extra else 0)
        blocks.append(list(range(start, stop)))
        start = stop
    return blocks


def _partition(m: "_Measured", n: int, room: "float | None") -> list:
    """Return the fewest blocks whose ruled width fits ``room``.

    The width depends on the partition, because the label column widens to
    carry a section heading over the narrowest block
    (:func:`_section_span`), so each block count is measured as drawn
    rather than computed from a capacity. If no count fits, one column per
    block is returned and the sheet reports the page as too small.

    Parameters
    ----------
    m : _Measured
        Measurements.
    n : int
        Number of stream columns.
    room : float or None
        Page width for the table, or ``None`` for one block.

    Returns
    -------
    list[list[int]]
        Column indices per block.
    """
    if room is None:
        return [list(range(n))]
    for count in range(1, n + 1):
        chunks = _blocks_of(n, count)
        width = (_section_span(m, min(len(c) for c in chunks))
                 + m.name_w * max(len(c) for c in chunks))
        if width <= room:
            return chunks
    return _blocks_of(n, n)


def stream_table_sheet(fs, room: "float | None") -> "TableSheet | None":
    """Return the stream table laid out as a sheet of its own.

    The block count comes from the page width (:func:`_partition`), and
    columns are shared evenly (:func:`_blocks_of`). Type size, row depth
    and column widths are the same with or without a page
    (:func:`_measure`). Every block repeats the heading row and shares one
    ruling.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    room : float or None
        Page width for the table, or ``None`` for one block.

    Returns
    -------
    TableSheet or None
        Stacked blocks, or ``None`` with nothing to tabulate.

    Raises
    ------
    ValueError
        If the stream-table options are invalid.
    """
    m = _measure(fs, own_sheet=True)
    if m is None:
        return None
    n = len(m.streams)
    chunks = _partition(m, n, room)
    # Widen the label column against the smallest block so one ruling
    # fits every block.
    label_w = _section_span(m, min(len(c) for c in chunks))
    blocks = [_stream_table(m, [m.streams[i] for i in c],
                            [m.cells[i] for i in c], label_w)
              for c in chunks]
    gap = m.row_h * _BLOCK_ROWS
    return TableSheet(blocks, gap, max(b.w for b in blocks),
                      _total(b.h for b in blocks) + gap * (len(blocks) - 1))


def table_sheet_origin(table: TableSheet, free) -> "tuple[float, float]":
    """Return the corner the block stack is drawn from.

    Centred across the page and against its top.

    Parameters
    ----------
    table : TableSheet
        Stacked blocks.
    free : tuple[float, float, float, float] or None
        Region a fixed page leaves, or ``None`` for a grown sheet.

    Returns
    -------
    tuple[float, float]
        Top-left of the stack; the origin for a grown sheet.
    """
    if free is None:
        return (0.0, 0.0)
    fx, fy, fw, _fh = free
    return (fx + (fw - table.w) / 2, fy)


def draw_stream_table(table: StreamTable, left: float, top: float, *,
                      group: str = "stream_table") -> list[str]:
    """Return the stream table drawn with its top-left at ``(left, top)``.

    Every cell is ruled on all four sides at :data:`_CELL_RULE`.

    Parameters
    ----------
    table : StreamTable
        Layout from :func:`stream_table_layout`.
    left, top : float
        Top-left corner.
    group : str, default="stream_table"
        Group id; table-sheet blocks need distinct ids.

    Returns
    -------
    list[str]
        SVG elements.
    """
    out = [f'<g id="{group}">']
    y = top
    for row in table.rows:
        x = left
        for c in row:
            out.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{c.w:.1f}" '
                       f'height="{table.row_h:.1f}" '
                       f'fill="{c.fill}" stroke="black" '
                       f'stroke-width="{_CELL_RULE:g}"/>')
            tx = (x + _STREAM_PAD if c.anchor == "start" else x + c.w / 2)
            wt = ' font-weight="bold"' if c.bold else ''
            out.append(f'  <text x="{tx:.1f}" '
                       f'y="{y + table.row_h / 2 + table.size / 3:.1f}" '
                       f'font-family="{FONT}" font-size="{table.size:.1f}"{wt} '
                       f'text-anchor="{c.anchor}">{escaped(c.text)}</text>')
            x += c.w
        y += table.row_h
    out.append('</g>')
    return out


# ----------------------------------------------------------------
# Engineering title strip (revision table | company | client/project,
# title, status, drawing number / scale / date / rev)
# ----------------------------------------------------------------

# Strip rectangle weight, equal to the frame's, so the flush-docked rules
# coincide.
_STRIP_RULE = 2.0
# Hairline for revision columns and bottom-band cells.
_STRIP_HAIRLINE = 0.5

_REV_W = 300.0
_COMPANY_W = 100.0
_INFO_W = 252.0
_REV_ROW = 14.0
# (heading, width, Revision field). Widths sum to _REV_W; DATE fits a full
# ISO 8601 date at 7.5 with gutters.
_REV_COLS = (("REV", 22, "rev"), ("DATE", 50, "date"),
             ("DESCRIPTION", 132, "description"), ("BY", 32, "by"),
             ("CHK'D", 32, "checked"), ("APP'D", 32, "approved"))
# Gutter between a revision cell's rule and its text, left and right.
_REV_PAD = 3.0
# Block-level field that fills each signatory column the newest revision
# leaves blank; pandid.validate reads it to report undrawn signatories.
_BACKFILL = {"by": "drawn_by", "checked": "checked_by",
             "approved": "approved_by"}
# The title / status / drawing-number bands, which every sheet carries.
_BODY_H = 80.0
# Fixed slot for the sheet count at the top right of the title band, so
# the title's room does not depend on the count. Sized for "SHEET 1 of 12"
# at 7.5; a longer count is drawn whole and reported.
_SHEET_W = 55.0
_TITLE_W = _INFO_W - 10 - _SHEET_W
# Client and project rows above the bands, ruled only when set. Neither is
# an ISO 7200 field; its legal owner is the company cell.
_HDR_ROW = 13.0
_HDR_VALUE_X = 40.0
# Shares of the information block's depth for the title and status
# bands; the drawing-number band takes the rest.
_TITLE_BAND, _STATUS_BAND = 0.40, 0.28

# Type sizes per band, shared with draw.io.
_REV_TYPE = 7.5        # a revision cell, and the sheet count in the title band
_CAPTION = 6.5         # the small grey label sitting over a field's value
_COMPANY_TYPE = 8.0
_HDR_TYPE = 9.0        # a client or project value
_TITLE_TYPE = 12.5
_SUBTITLE_TYPE = 10.5
_VALUE_TYPE = 11.0     # a status, a drawing number, a scale, a date, a rev

#: Caption ink, lighter than the value it labels.
CAPTION_INK = "#666"


# Line spacing of the company cell's wrapped lines.
_COMPANY_LEAD = 12.0


def _field(obj, name: str) -> str:
    """Return a title-block field as the author stated it, stripped.

    Whitespace counts as blank, so fallbacks such as the flowsheet name
    still apply. Only ``None`` is unset, so ``sheet=0`` draws ``0``; the
    text conversion is :func:`pandid.document._drawn_text`, shared with
    the spec reader. Read here rather than normalised on the dataclass,
    because fields are edited after construction. :func:`_stated` adds
    the field's default.

    Parameters
    ----------
    obj : TitleBlock or Revision
        Object to read.
    name : str
        Field name.

    Returns
    -------
    str
        Stripped text, empty when unset.
    """
    return _drawn_text(getattr(obj, name, None)).strip()


# Cache for _class_defaults.
_DEFAULTS: "dict[type, dict[str, str]]" = {}


def _class_defaults(cls: "type[Any]") -> "dict[str, str]":
    """Return a dataclass's plain-string field defaults, cached per class.

    Factory fields such as ``revisions`` are omitted; a non-dataclass has
    none.

    Parameters
    ----------
    cls : type
        Class to read.

    Returns
    -------
    dict[str, str]
        Field name to default.
    """
    known = _DEFAULTS.get(cls)
    if known is None:
        known = _DEFAULTS[cls] = (
            {f.name: f.default for f in dataclasses.fields(cls)
             if isinstance(f.default, str)}
            if dataclasses.is_dataclass(cls) else {})
    return known


def _stated(obj, name: str) -> str:
    """Return the value a strip cell draws: the stated field, else its default.

    Defaults come from the dataclass, so a blank ``sheet`` or ``of_sheets``
    draws ``1`` as an unset one does, rather than ``SHEET  of 1``.

    Parameters
    ----------
    obj : TitleBlock or Revision
        Object to read.
    name : str
        Field name.

    Returns
    -------
    str
        Text to draw.
    """
    return _field(obj, name) or _class_defaults(type(obj)).get(name, "")


def company_lines(company: str) -> list[str]:
    """Return the company name wrapped into the lines its cell stacks.

    Breaks only between words; a word wider than the cell is kept whole
    and reported by :func:`check_fit`. Shared with
    :func:`pandid.validate.model_issues`, which checks the line count.

    Parameters
    ----------
    company : str
        Company name.

    Returns
    -------
    list[str]
        Lines.
    """
    line, lines = "", []
    for word in company.split():
        trial = (line + " " + word).strip()
        if text_width(trial, _COMPANY_TYPE, bold=True) > _COMPANY_W - 10 and line:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def company_overflow(tb) -> "tuple[int, float, float] | None":
    """Return how far the wrapped company name overruns the strip's depth.

    The cell is centred on the strip, so too many lines run out of the
    strip top and bottom, which no per-line width check sees. The room is
    the strip's full depth (:func:`measure_title_strip`).

    Parameters
    ----------
    tb : TitleBlock
        Title block.

    Returns
    -------
    tuple[int, float, float] or None
        ``(line count, room, need)``, or ``None`` if it fits.
    """
    lines = company_lines(_stated(tb, "company"))
    _, room = measure_title_strip(tb)
    need = len(lines) * _COMPANY_LEAD
    return (len(lines), room, need) if need > room else None


def undrawn_signatories(tb) -> "list[tuple[str, str, str]]":
    """Return the block-level signatories the strip does not draw.

    ``drawn_by``, ``checked_by`` and ``approved_by`` fill the newest
    revision row's BY, CHK'D and APP'D cells (:data:`_BACKFILL`). They go
    undrawn when there is no revision, or when the newest revision names a
    different signatory. Kept here so :func:`title_strip_layout` and
    :mod:`pandid.validate` read the fields the same way.

    Parameters
    ----------
    tb : TitleBlock
        Title block.

    Returns
    -------
    list[tuple[str, str, str]]
        ``(field, value, displaced_by)``; ``displaced_by`` is empty when
        there is no revision row.
    """
    out: list[tuple[str, str, str]] = []
    newest = tb.revisions[-1] if tb.revisions else None
    for column, block in _BACKFILL.items():
        value = _field(tb, block)
        if not value:
            continue
        if newest is None:
            out.append((block, value, ""))
            continue
        row = _field(newest, column)
        if row and row != value:
            out.append((block, value,
                        f"revisions[{len(tb.revisions) - 1}].{column}={row!r}"))
    return out


def _header_lines(tb) -> list[tuple[str, str]]:
    """Return the client and project rows that are set.

    Parameters
    ----------
    tb : TitleBlock
        Title block.

    Returns
    -------
    list[tuple[str, str]]
        ``(label, value)`` pairs.
    """
    return [(label, value) for label, value
            in (("CLIENT", _stated(tb, "client")),
                ("PROJECT", _stated(tb, "project"))) if value]


def measure_title_strip(tb) -> tuple[float, float]:
    """Return the title strip's size.

    The depth is the larger of the revision grid and the information
    bands, plus a row for each of client and project.

    Parameters
    ----------
    tb : TitleBlock
        Title block.

    Returns
    -------
    tuple[float, float]
        ``(width, height)``.
    """
    n = len(tb.revisions)
    h = max((n + 1) * _REV_ROW, _BODY_H) + _HDR_ROW * len(_header_lines(tb))
    return _REV_W + _COMPANY_W + _INFO_W, h


class RevGrid(NamedTuple):
    """Revision history grid geometry, shared by both backends.

    Values and headings are already clipped to their columns. The blank
    space above the oldest revision is not a row.

    Attributes
    ----------
    x, y, w, h : float
        The strip's left-hand column.
    cols : tuple[tuple[str, float], ...]
        ``(heading, width)`` per column.
    row_h : float
        Row depth.
    header_y : float
        Where the heading row at the foot is ruled off.
    rows : list[list[str]]
        Revisions oldest first, top to bottom.
    """
    x: float
    y: float
    w: float
    h: float
    cols: tuple
    row_h: float
    header_y: float
    rows: list


class Strip(NamedTuple):
    """Title strip geometry, shared by both backends.

    Attributes
    ----------
    box : tuple[float, float, float, float]
        Strip rectangle ``(x, y, w, h)``, ruled at 2.
    rules : list[tuple]
        The two full-depth rules dividing revision grid, company cell and
        information block.
    rev : RevGrid
        Revision grid.
    parts : list[tuple]
        Everything else in drawing order: ``("rule", x1, y1, x2, y2,
        weight)`` and ``("text", x, baseline, string, size, anchor, bold,
        fill)``, with text placed at an SVG baseline.
    """
    box: tuple
    rules: list
    rev: RevGrid
    parts: list


def title_strip_layout(tb, name: str, date: str, right: float, bottom: float,
                       fit_scale: str = "", *,
                       report: "Reporter | None" = None) -> Strip:
    """Return the title strip layout with its bottom-right at ``(right, bottom)``.

    The strip is fixed geometry (ISO 15519-1 5.2.2, ISO 5457 position,
    ISO 7200 content), so an overlong value cannot get more room:

    * the drawing title is set smaller down to the subtitle size
      (:func:`fit_size`), then abbreviated;
    * the company name wraps between words, and it and the sheet count are
      drawn whole and reported (:func:`check_fit`);
    * everything else is abbreviated with an ellipsis (:func:`clip`).

    Measuring happens here, so both backends draw and report the same.

    Parameters
    ----------
    tb : TitleBlock
        Title block.
    name : str
        Title fallback, normally the flowsheet name.
    date : str
        Date fallback, normally today's date.
    right, bottom : float
        Bottom-right corner.
    fit_scale : str, default=""
        Scale the drawing was fitted at, for a block that states none.
    report : Reporter, optional
        Receives a finding per cell that cannot hold its value.

    Returns
    -------
    Strip
        Strip geometry.
    """
    # name and date are fallbacks, applied after whitespace reads as blank.
    name, date = str(name or "").strip(), str(date or "").strip()
    date = _stated(tb, "date") or date
    w, h = measure_title_strip(tb)
    x, y = right - w, bottom - h
    rx = x + _REV_W
    cx2 = rx + _COMPANY_W
    rules = [("rule", vx, y, vx, bottom, 1.5) for vx in (rx, cx2)]
    if report is not None:
        report = report_once(report)

    # --- Revision grid (left): heading at the foot, revisions above
    def rev_cells(cells, bold=False):
        """Return one grid row, each cell clipped to its column.

        ``cells`` is a ``(value, field)`` pair per column; an empty field
        is library lettering and is not reported.
        """
        return [clip(v, cw - 2 * _REV_PAD, _REV_TYPE, bold,
                     field=f, report=report if f else None)
                for (_, cw, _attr), (v, f) in zip(_REV_COLS, cells)]

    header_y = bottom - _REV_ROW
    headings = rev_cells([(c[0], "") for c in _REV_COLS], bold=True)
    # Clip newest first, so findings come in that order; store oldest first.
    newest_first = []
    for idx, rv in enumerate(reversed(tb.revisions)):
        newest = idx == 0
        i = len(tb.revisions) - 1 - idx
        row = []
        for _heading, _cw, attr in _REV_COLS:
            cell, value = f"revisions[{i}].{attr}", _stated(rv, attr)
            # Backfill the newest row's blank signatories from the block,
            # naming the block field in any finding.
            block = _BACKFILL.get(attr, "")
            if newest and not value and block and _field(tb, block):
                row.append((_stated(tb, block), f"{block} -> {cell}"))
            else:
                row.append((value, cell))
        newest_first.append(rev_cells(row))
    rev = RevGrid(x, y, _REV_W, h,
                  tuple((heading, cw) for heading, (_, cw, _a)
                        in zip(headings, _REV_COLS)),
                  _REV_ROW, header_y, list(reversed(newest_first)))

    parts: list[tuple] = []

    # Company / logo cell (middle) -------------------------------
    if _stated(tb, "company"):
        lines = company_lines(_stated(tb, "company"))
        cy = y + h / 2 - (len(lines) - 1) * _COMPANY_LEAD / 2
        for ln in lines:
            # A word wider than the cell is drawn whole and reported.
            parts.append(("text", rx + _COMPANY_W / 2, cy,
                          check_fit(ln, _COMPANY_W - 10, _COMPANY_TYPE, True,
                                    field="company", report=report),
                          _COMPANY_TYPE, "middle", True, "black"))
            cy += _COMPANY_LEAD

    # --- Info block (right): client/project, title, status, dwg/rev
    ix = cx2
    header = _header_lines(tb)
    top = y + _HDR_ROW * len(header)     # top of the title band
    body = h - _HDR_ROW * len(header)
    band2 = top + body * _TITLE_BAND
    band3 = band2 + body * _STATUS_BAND
    hy = y
    for i, (label, value) in enumerate(header):
        if i:
            parts.append(("rule", ix, hy, x + w, hy, _STRIP_HAIRLINE))
        parts.append(("text", ix + 6, hy + _HDR_ROW - 4, label, _CAPTION,
                      "start", False, CAPTION_INK))
        parts.append(("text", ix + _HDR_VALUE_X, hy + _HDR_ROW - 4,
                      clip(value, _INFO_W - _HDR_VALUE_X - 5, _HDR_TYPE,
                           field=label.lower(), report=report),
                      _HDR_TYPE, "start", False, "black"))
        hy += _HDR_ROW
    for ly in ([top] if header else []) + [band2, band3]:
        parts.append(("rule", ix, ly, x + w, ly, 0.75))
    # Title, subtitle, and the sheet count at the top right of the title
    # band. Blank sheet fields fall back to "1" (_stated), so the count is
    # never half drawn.
    sheets = f"SHEET {_stated(tb, 'sheet')} of {_stated(tb, 'of_sheets')}"
    # The title is set smaller to fit, down to the subtitle size, then
    # abbreviated; its baseline stays fixed across a set of sheets. A
    # fallback title is reported as the flowsheet name (see Reporter).
    title = _stated(tb, "title") or name
    title_type = fit_size(title, _TITLE_W, _TITLE_TYPE, _SUBTITLE_TYPE, True)
    parts.append(("text", ix + 6, top + 15,
                  clip(title, _TITLE_W, title_type, True,
                       field=("title" if _field(tb, "title")
                              else "Flowsheet name -> title"),
                       report=report),
                  title_type, "start", True, "black"))
    if _stated(tb, "subtitle"):
        parts.append(("text", ix + 6, band2 - 6,
                      clip(_stated(tb, "subtitle"), _INFO_W - 12, _SUBTITLE_TYPE,
                           field="subtitle", report=report),
                      _SUBTITLE_TYPE, "start", False, "black"))
    # One cell from two fields, so the finding names both.
    parts.append(("text", x + w - 5, top + 11,
                  check_fit(sheets, _SHEET_W, _REV_TYPE,
                            field="sheet/of_sheets", report=report),
                  _REV_TYPE, "end", False, CAPTION_INK))
    # status (tiny label at cell top, value below)
    parts.append(("text", ix + 6, band2 + 8, "STATUS", _CAPTION,
                  "start", False, CAPTION_INK))
    parts.append(("text", ix + 6, band3 - 5,
                  clip(_stated(tb, "status") or "—", _INFO_W - 12,
                       _VALUE_TYPE, True,
                       field="status", report=report),
                  _VALUE_TYPE, "start", True, "black"))
    # Bottom band: DRAWING No | SCALE | DATE | REV, four cells at fixed
    # shares whether or not there is a scale, so each value's room is the
    # same for every render and pandid.validate can measure it before
    # rendering. Scale here is drafting practice, not a standard (ISO 7200
    # 4 puts scale outside the title block). Fallback values name their
    # source field (see Reporter).
    rev_id = _stated(tb.revisions[-1], "rev") if tb.revisions else "0"
    rev_field = (f"revisions[{len(tb.revisions) - 1}].rev -> rev"
                 if tb.revisions else "rev")
    scale = _stated(tb, "scale") or fit_scale
    scale_field = ("scale" if _field(tb, "scale")
                   else "the fitted scale -> scale")
    date_field = ("date" if _field(tb, "date")
                  else "today's date -> date")
    cells: list[tuple[float, str, str, str]] = [
        (_INFO_W * 0.38, "DRAWING No",
         _stated(tb, "drawing_number") or "—", "drawing_number"),
        (_INFO_W * 0.21, "SCALE", scale, scale_field),
        (_INFO_W * 0.29, "DATE", date, date_field),
        (_INFO_W * 0.12, "REV", rev_id, rev_field)]
    cxr = ix
    for j, (seg_w, seg_label, seg_val, seg_field) in enumerate(cells):
        if j:
            parts.append(("rule", cxr, band3, cxr, bottom, _STRIP_HAIRLINE))
        bold = seg_label != "DATE"
        parts.append(("text", cxr + 5, band3 + 8, seg_label, _CAPTION,
                      "start", False, CAPTION_INK))
        # Measure always; skip an empty <text> in an unused scale cell.
        drawn = clip(seg_val, seg_w - 8, _VALUE_TYPE, bold,
                     field=seg_field, report=report)
        if drawn:
            parts.append(("text", cxr + 5, bottom - 5, drawn,
                          _VALUE_TYPE, "start", bold, "black"))
        cxr += seg_w
    return Strip((x, y, w, h), rules, rev, parts)


def title_strip_fit(tb, name: str, date: str, fit_scale: str = ""
                    ) -> "list[tuple[str, str, str, float, float]]":
    """Return every strip cell that cannot hold its value, without drawing.

    Runs :func:`title_strip_layout` with a collecting reporter, so the
    measurement is the renderers'. Every strip width is a constant, so
    :func:`pandid.validate.model_issues` can report before any render.
    ``name`` and ``date`` are passed unchosen, as the renderers pass them.
    Without ``fit_scale`` only the scale cell's own value goes unmeasured;
    the render reports that.

    Parameters
    ----------
    tb : TitleBlock
        Title block.
    name : str
        Title fallback.
    date : str
        Date fallback.
    fit_scale : str, default=""
        Fitted scale, if known.

    Returns
    -------
    list[tuple[str, str, str, float, float]]
        :data:`Reporter` arguments per finding.
    """
    found: list[tuple[str, str, str, float, float]] = []

    def collect(field: str, text: str, drawn: str,
                room: float, need: float) -> None:
        """Record a finding."""
        found.append((field, text, drawn, room, need))

    title_strip_layout(tb, name, date, 0.0, 0.0, fit_scale, report=collect)
    return found


def _strip_part(part) -> str:
    """Return one laid-out strip part as SVG.

    Parameters
    ----------
    part : tuple
        A ``"rule"`` or ``"text"`` part from :class:`Strip`.

    Returns
    -------
    str
        SVG element.
    """
    if part[0] == "rule":
        _, x1, y1, x2, y2, weight = part
        return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="black" stroke-width="{weight:g}"/>')
    _, tx, ty, text, size, anchor, bold, fill = part
    return _text(tx, ty, text, size, anchor=anchor, bold=bold, fill=fill)


def draw_title_strip(tb, name: str, date: str, right: float, bottom: float,
                     fit_scale: str = "", *,
                     report: "Reporter | None" = None) -> list[str]:
    """Return the title strip drawn with its bottom-right at ``(right, bottom)``.

    Strokes :func:`title_strip_layout`.

    Parameters
    ----------
    tb : TitleBlock
        Title block.
    name : str
        Title fallback.
    date : str
        Date fallback.
    right, bottom : float
        Bottom-right corner.
    fit_scale : str, default=""
        Fitted scale for a block that states none.
    report : Reporter, optional
        Receives a finding per cell that cannot hold its value.

    Returns
    -------
    list[str]
        SVG elements.
    """
    strip = title_strip_layout(tb, name, date, right, bottom, fit_scale,
                               report=report)
    x, y, w, h = strip.box
    L = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
         f'fill="white" stroke="black" stroke-width="{_STRIP_RULE:g}"/>']
    L += [_strip_part(part) for part in strip.rules]

    # Revision grid: the heading rule, full-depth column rules, then the
    # cells. No rules between revisions.
    g = strip.rev
    L.append(_strip_part(("rule", g.x, g.header_y, g.x + g.w, g.header_y,
                          _BOX_UNDERLINE)))
    cx = g.x
    for _heading, cw in g.cols[:-1]:
        cx += cw
        L.append(_strip_part(("rule", cx, g.y, cx, g.y + g.h, _STRIP_HAIRLINE)))

    def rev_row(ry, vals, bold=False):
        """Append one row of revision text at ``ry``."""
        cx = g.x
        for (_heading, cw), value in zip(g.cols, vals):
            L.append(_text(cx + _REV_PAD, ry + g.row_h - 4, value,
                           _REV_TYPE, bold=bold))
            cx += cw
    rev_row(g.header_y, [heading for heading, _cw in g.cols], bold=True)
    # Newest revision just above the heading; older ones above it.
    for idx, values in enumerate(reversed(g.rows)):
        rev_row(g.header_y - (idx + 1) * g.row_h, values)

    L += [_strip_part(part) for part in strip.parts]
    return L


# ----------------------------------------------------------------
# Zone-ruled drawing border (A.. top→down, 1.. left→right)
#
# Lettering follows ISO 5457 4.4: letters top down, numerals left to
# right, so ISO 15519-1 Clause 9 addresses
# (:func:`pandid.document.location_reference`) start at the top left. The
# 50 mm pitch, ISO 5457 field counts and centring marks are not used: the
# band is a constant and the field count suits the sheet; ISO 15519-1 5.1.2
# asks for centring marks only for microfilming.
# ----------------------------------------------------------------

#: Width of the lettered band between drawing frame and sheet border.
ZONE_BAND = 16.0


def sheet_rect(ix: float, iy: float, iw: float, ih: float, band: float = ZONE_BAND
               ) -> tuple[float, float, float, float]:
    """Return the sheet rectangle around a drawing frame.

    An unruled sheet keeps the band as margin, so the border can be turned
    on or off without moving furniture.

    Parameters
    ----------
    ix, iy, iw, ih : float
        Drawing frame.
    band : float, default=ZONE_BAND
        Band width.

    Returns
    -------
    tuple[float, float, float, float]
        Sheet rectangle ``(x, y, w, h)``.
    """
    return ix - band, iy - band, iw + 2 * band, ih + 2 * band


#: Zone letter size, and the drop from the band's middle to the baseline.
ZONE_TYPE, _ZONE_BASE = 9, 3


class Zoned(NamedTuple):
    """Zone-ruled border geometry, shared by both backends.

    Attributes
    ----------
    outer : tuple[float, float, float, float]
        Sheet border ``(x, y, w, h)``.
    inner : tuple[float, float, float, float]
        Drawing frame ``(x, y, w, h)``.
    parts : list[tuple]
        Band contents in drawing order: ``("rule", x1, y1, x2, y2)`` ticks
        and ``("label", x, y, text)`` letters centred on ``(x, y)``.
    """
    outer: tuple[float, float, float, float]
    inner: tuple[float, float, float, float]
    parts: list[tuple]


def zone_layout(ix: float, iy: float, iw: float, ih: float,
                band: float = ZONE_BAND) -> Zoned:
    """Return the zone-ruled border layout.

    Zones are about 165 units, with 4 to 12 columns and 3 to 8 rows,
    rather than ISO 5457's 50 mm pitch.

    Parameters
    ----------
    ix, iy, iw, ih : float
        Drawing frame.
    band : float, default=ZONE_BAND
        Band width.

    Returns
    -------
    Zoned
        Border geometry.
    """
    ox, oy, ow, oh = sheet_rect(ix, iy, iw, ih, band)
    cols = max(4, min(12, round(iw / 165)))
    rows = max(3, min(8, round(ih / 165)))
    parts: list[tuple] = []
    letters = string.ascii_uppercase
    # columns: numbers 1..cols left→right, on the top and bottom bands
    for c in range(cols):
        x0 = ix + iw * c / cols
        x1 = ix + iw * (c + 1) / cols
        num = str(c + 1)
        if c:
            parts.append(("rule", x0, oy, x0, iy))
            parts.append(("rule", x0, iy + ih, x0, oy + oh))
        parts.append(("label", (x0 + x1) / 2, oy + band / 2, num))
        parts.append(("label", (x0 + x1) / 2, oy + oh - band / 2, num))
    # rows: letters A.. top→down, on the left and right bands (y down).
    for r in range(rows):
        y0 = iy + ih * r / rows
        y1 = iy + ih * (r + 1) / rows
        letter = letters[r]
        if r:
            parts.append(("rule", ox, y0, ix, y0))
            parts.append(("rule", ix + iw, y0, ox + ow, y0))
        parts.append(("label", ox + band / 2, (y0 + y1) / 2, letter))
        parts.append(("label", ox + ow - band / 2, (y0 + y1) / 2, letter))
    return Zoned((ox, oy, ow, oh), (ix, iy, iw, ih), parts)


def zone_frame(ix: float, iy: float, iw: float, ih: float, band: float = ZONE_BAND
               ) -> tuple[list[str], tuple[float, float, float, float]]:
    """Return the drawing frame, sheet border and zone band, drawn.

    Strokes :func:`zone_layout`.

    Parameters
    ----------
    ix, iy, iw, ih : float
        Drawing frame.
    band : float, default=ZONE_BAND
        Band width.

    Returns
    -------
    tuple[list[str], tuple[float, float, float, float]]
        SVG elements and the sheet rectangle ``(x, y, w, h)``.
    """
    z = zone_layout(ix, iy, iw, ih, band)
    ox, oy, ow, oh = z.outer
    L = [f'<rect x="{ox:.1f}" y="{oy:.1f}" width="{ow:.1f}" height="{oh:.1f}" '
         f'fill="none" stroke="black" stroke-width="{SHEET_RULE:g}"/>',
         f'<rect x="{ix:.1f}" y="{iy:.1f}" width="{iw:.1f}" height="{ih:.1f}" '
         f'fill="none" stroke="black" stroke-width="{FRAME_RULE:g}"/>']
    for part in z.parts:
        if part[0] == "rule":
            _, x1, y1, x2, y2 = part
            L.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="black" stroke-width="{ZONE_TICK:g}"/>')
        else:
            _, lx, ly, text = part
            L.append(_text(lx, ly + _ZONE_BASE, text, ZONE_TYPE,
                           anchor="middle", bold=True))
    return L, z.outer


# ----------------------------------------------------------------
# The sheet dock: which rectangle each piece of furniture is given
# ----------------------------------------------------------------

#: Clearances: drawing to frame, between boxes stacked in one corner, and
#: between left and right stacks sharing a band.
INNER, GAP, SEP = 26.0, 14.0, 18.0

#: Margin outside the sheet border; a fixed page insets its frame by this
#: plus the zone band.
OUTER_MARGIN = 8.0


class Docked(NamedTuple):
    """One piece of furniture and the rectangle the sheet gives it.

    Attributes
    ----------
    obj : object
        The furniture, or a sentinel.
    x, y, w, h : float
        Placed rectangle.
    """
    obj: object
    x: float
    y: float
    w: float
    h: float


def dock(items, inner, *, sheet=None, too_small=None):
    """Return where each piece of furniture is placed and the frame.

    Draws nothing; both backends use it. Boxes are grouped into edge bands
    by ``align`` and placed flush to that frame edge, inset by their
    ``margin``; a box with ``position`` is placed by hand. Without a sheet
    the frame grows from the drawing to hold the bands; with one, the frame
    is the page inset by the border and the drawing fits what is left.

    Parameters
    ----------
    items : iterable of tuple
        ``(obj, align, w, h)``. ``margin`` and ``position`` are read from
        ``obj`` where present, so sentinels (title strip, stream table) are
        allowed.
    inner : tuple[float, float, float, float]
        Drawing bounds ``(x0, y0, x1, y1)``.
    sheet : _Sheet, optional
        Fixed page; ``None`` grows the frame to the drawing.
    too_small : callable, optional
        Called with ``(need_w, need_h, culprit)`` when a fixed page cannot
        hold its furniture; returns the exception to raise. Required only
        if that can happen.

    Returns
    -------
    tuple
        ``(placed, frame, free)``: :class:`Docked` rectangles in drawing
        order, the frame ``(x, y, w, h)``, and the region left for the
        drawing on a fixed page, or ``None``.

    Raises
    ------
    TypeError
        If a fixed page overflows and ``too_small`` is missing.
    """
    from pandid.document import _ALIGN

    dx0, dy0, dx1, dy1 = inner
    cols: dict[str, list] = {k: [] for k in _ALIGN}
    positioned: list = []
    for obj, align, w, h in items:
        position = getattr(obj, "position", None)
        if position is not None:
            positioned.append((obj, position[0], position[1], w, h))
        else:
            cols[align].append((obj, w, h))

    def stack_h(entries):
        """Return a stack's height, with gaps."""
        return _total(h for _, _, h in entries) + GAP * max(0, len(entries) - 1)

    def stack_w(entries):
        """Return a stack's width."""
        return max((w for _, w, _ in entries), default=0.0)

    def biggest(dim: int):
        """Return the largest piece along ``dim`` (1 width, 2 height), to name it."""
        entries = [it for col in cols.values() for it in col]
        return max(entries, key=lambda it: it[dim])[0] if entries else None

    # band thicknesses -------------------------------------------
    top_h = max(stack_h(cols["top-left"]), stack_h(cols["top"]),
                stack_h(cols["top-right"]))
    bottom_h = max(stack_h(cols["bottom-left"]), stack_h(cols["bottom"]),
                   stack_h(cols["bottom-right"]))
    left_w, right_w = stack_w(cols["left"]), stack_w(cols["right"])

    def row_w(lk, ck, rk):
        """Return the width a band row needs."""
        lw, cw, rw = stack_w(cols[lk]), stack_w(cols[ck]), stack_w(cols[rk])
        side = (lw + SEP + rw) if (lw and rw) else max(lw, rw)
        return max(side, cw)

    band_w = max(row_w("top-left", "top", "top-right"),
                 row_w("bottom-left", "bottom", "bottom-right"))

    # frame rectangle --------------------------------------------
    if sheet is not None:
        # A named page fixes the frame: the sheet inset by band and margin.
        edge = OUTER_MARGIN + ZONE_BAND
        need_w = max(band_w, left_w + right_w + 2 * INNER)
        need_h = max(top_h + bottom_h + 2 * INNER,
                     stack_h(cols["left"]), stack_h(cols["right"]))
        too_wide = need_w >= sheet.width - 2 * edge
        if too_wide or need_h >= sheet.height - 2 * edge:
            # Name the missing callback rather than fail on calling None.
            if too_small is None:
                raise TypeError("dock() needs a too_small callback when sheet is given")
            raise too_small(need_w + 2 * edge, need_h + 2 * edge,
                            biggest(1 if too_wide else 2))
        ix, iy = edge, edge
        ixr, iyb = sheet.width - edge, sheet.height - edge
    else:
        ix = dx0 - INNER - left_w
        iy = dy0 - INNER - top_h
        ixr = dx1 + INNER + right_w
        iyb = dy1 + INNER + bottom_h
        extra = band_w - (ixr - ix)
        if extra > 0:  # a wide band forces the frame wider than the drawing
            ix -= extra / 2      # widen symmetrically → drawing stays centred
            ixr += extra / 2
        extra = max(stack_h(cols["left"]), stack_h(cols["right"])) - (iyb - iy)
        if extra > 0:
            iy -= extra / 2
            iyb += extra / 2
    iw, ih = ixr - ix, iyb - iy

    # Region left for the drawing on a fixed page.
    free = None if sheet is None else (
        ix + left_w + INNER, iy + top_h + INNER,
        iw - left_w - right_w - 2 * INNER, ih - top_h - bottom_h - 2 * INNER)

    # place each column flush to the frame -----------------------
    placed: list[Docked] = []

    def x_for(mode, w, m):
        """Return a box's x for left, right or centred placement."""
        if mode == "l":
            return ix + m
        if mode == "r":
            return ixr - m - w
        return ix + (iw - w) / 2  # centred on the frame

    def put_top(entries, mode):     # flush to the top edge, grow downward
        """Place a stack against the top edge."""
        y = iy
        for obj, w, h in entries:
            m = getattr(obj, "margin", 0.0)
            placed.append(Docked(obj, x_for(mode, w, m), y + m, w, h))
            y += m + h + GAP

    def put_bottom(entries, mode):  # flush to the bottom edge, grow upward
        """Place a stack against the bottom edge."""
        y = iyb
        for obj, w, h in reversed(entries):
            m = getattr(obj, "margin", 0.0)
            top = y - m - h
            placed.append(Docked(obj, x_for(mode, w, m), top, w, h))
            y = top - GAP

    def put_side(entries, mode):    # flush to a side edge, vertically centred
        """Place a stack against a side edge, centred vertically."""
        y = (iy + iyb) / 2 - stack_h(entries) / 2
        for obj, w, h in entries:
            m = getattr(obj, "margin", 0.0)
            placed.append(Docked(obj, x_for(mode, w, m), y, w, h))
            y += h + GAP

    put_top(cols["top-left"], "l")
    put_top(cols["top"], "c")
    put_top(cols["top-right"], "r")
    put_bottom(cols["bottom-left"], "l")
    put_bottom(cols["bottom"], "c")
    put_bottom(cols["bottom-right"], "r")
    put_side(cols["left"], "l")
    put_side(cols["right"], "r")
    cy = (iy + iyb) / 2 - stack_h(cols["center"]) / 2  # dead-centre overlay
    for obj, w, h in cols["center"]:
        placed.append(Docked(obj, ix + (iw - w) / 2, cy, w, h))
        cy += h + GAP

    # hand-placed boxes; expand the frame to keep them inside ----
    for obj, px, py, w, h in positioned:
        placed.append(Docked(obj, px, py, w, h))
        if sheet is not None:  # the page is fixed; absolute means absolute
            continue
        ix, iy = min(ix, px - INNER), min(iy, py - INNER)
        ixr, iyb = max(ixr, px + w + INNER), max(iyb, py + h + INNER)
    iw, ih = ixr - ix, iyb - iy

    return placed, (ix, iy, iw, ih), free
