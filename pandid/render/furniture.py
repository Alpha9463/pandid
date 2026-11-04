"""Measure, place and draw sheet furniture as SVG.

Furniture is the title strip, titled boxes, tables, the stream table
and the zone border. :func:`dock` places it for both backends.
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

# Helvetica advance widths in thousandths of the type size, for ASCII
# 32..126 and Latin-1 160..255.
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

# Flat advance, in thousandths, of a narrow codepoint outside the table.
_ADV = 560
_ADV_BOLD = 620

#: Overflow callback ``(field, text, drawn, room, need)``: the field,
#: the requested and drawn text, the cell's room and the text's width.
#: ``field`` reads ``source -> cell`` when another field supplied the
#: value.
Reporter = Callable[[str, str, str, float, float], None]


def text_width(s, size: float, bold: bool = False) -> float:
    """Return the drawn width of ``s`` at ``size``.

    Parameters
    ----------
    s : object
        Text, converted with ``str``.
    size : float
        Type size in drawing units.
    bold : bool, default=False
        Measure bold advances.

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
    """Return the sum of ``values``, added left to right with ``+=``.

    Parameters
    ----------
    values : iterable of float
        Values to add.

    Returns
    -------
    float
        Their sum.
    """
    total = 0.0
    for v in values:
        total += v
    return total


def clip(s, room: float, size: float, bold: bool = False, *,
         field: str = "", report: "Reporter | None" = None) -> str:
    """Return ``s`` cut to ``room`` with an ellipsis, reporting it.

    Parameters
    ----------
    s : object
        Text, converted with ``str``.
    room : float
        Width available, in drawing units.
    size : float
        Type size in drawing units.
    bold : bool, default=False
        Measure bold advances.
    field : str, default=""
        Field name passed to ``report``.
    report : Reporter, optional
        Receives a finding when ``s`` is cut.

    Returns
    -------
    str
        ``s``, or its longest prefix that fits with an ellipsis.
    """
    s = str(s)
    need = text_width(s, size, bold)
    if need <= room:
        return s
    ellipsis = "…"
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
    """Return ``s`` unchanged, reporting it if it overruns ``room``.

    Parameters
    ----------
    s : object
        Text, converted with ``str``.
    room : float
        Width available, in drawing units.
    size : float
        Type size in drawing units.
    bold : bool, default=False
        Measure bold advances.
    field : str, default=""
        Field name passed to ``report``.
    report : Reporter, optional
        Receives a finding when ``s`` overruns.

    Returns
    -------
    str
        ``s`` as a string.
    """
    s = str(s)
    need = text_width(s, size, bold)
    if report is not None and need > room:
        report(field, s, s, room, need)
    return s


def _text(x, y, s, size, *, anchor="start", bold=False, fill="black"):
    """Return an SVG ``<text>`` element with escaped content.

    Parameters
    ----------
    x, y : float
        Anchor point.
    s : object
        Text.
    size : float
        Type size.
    anchor : str, default="start"
        SVG ``text-anchor``.
    bold : bool, default=False
        Set the text bold.
    fill : str, default="black"
        Text colour.

    Returns
    -------
    str
        SVG element.
    """
    wt = ' font-weight="bold"' if bold else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size:.1f}"'
            f' text-anchor="{anchor}"{wt} fill="{fill}">{escaped(s)}</text>')


# Generic titled box (Annotation): title bar over rows

# Rule weights of a titled box and the line under its title.
_BOX_RULE = 1.5
_BOX_UNDERLINE = 1.0
# Cell rule weight of a TableBox.
_CELL_RULE = 0.75

#: Rule weights of the sheet edge, the drawing frame and the zone ticks.
SHEET_RULE = 1.0
FRAME_RULE = 2.0
ZONE_TICK = 0.75

# Inset from a titled box's border to its text, and its column gap.
_ANN_PAD, _ANN_GAP = 9.0, 12.0
# Inset of a left- or right-aligned TableBox cell's text.
_TABLE_PAD = 5.0
# Depth a TableBox title adds beyond its type size.
_TABLE_TITLE = 10
# Rise of a box title's baseline above the rule under it.
_TITLE_RISE = 6


def _ann_layout(ann):
    """Return ``(size, row_h, title_h, col_w)`` for an Annotation.

    Parameters
    ----------
    ann : Annotation
        Titled box.

    Returns
    -------
    tuple
        Type size, row depth, title depth and column widths.
    """
    size = ann.font_size
    row_h = size + 7
    title_h = size + 12 if ann.title else 0
    ncol = max((len(r) for r in ann.rows if isinstance(r, (tuple, list))), default=1)
    col_w = [0.0] * ncol
    for r in ann.rows:
        if isinstance(r, (tuple, list)):
            for i, c in enumerate(r):
                # A row's first cell is bold.
                col_w[i] = max(col_w[i], text_width(c, size, bold=(i == 0 and len(r) > 1)))
        else:
            col_w[0] = max(col_w[0], text_width(r, size))
    return size, row_h, title_h, col_w


def measure_annotation(ann) -> tuple[float, float]:
    """Return an Annotation's ``(width, height)``.

    Parameters
    ----------
    ann : Annotation
        Titled box.

    Returns
    -------
    tuple[float, float]
        Width and height in drawing units.
    """
    size, row_h, title_h, col_w = _ann_layout(ann)
    pad, gap = _ANN_PAD, _ANN_GAP
    body_w = _total(col_w) + gap * (len(col_w) - 1)
    inner = max(body_w, text_width(ann.title, size + 1, bold=True))
    w = ann.width if ann.width is not None else inner + 2 * pad
    h = title_h + len(ann.rows) * row_h + 8
    return w, h


def draw_annotation(ann, x: float, y: float, *,
                    report: "Reporter | None" = None) -> list[str]:
    """Return an Annotation drawn with its top-left at ``(x, y)``.

    Parameters
    ----------
    ann : Annotation
        Titled box.
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
    pad, gap = _ANN_PAD, _ANN_GAP
    w, h = measure_annotation(ann)
    if report is not None and ann.width is not None:
        body_w = _total(col_w) + gap * (len(col_w) - 1)
        inner = max(body_w, text_width(ann.title, size + 1, bold=True))
        if ann.width < inner + 2 * pad:
            # Name the title if it overruns, else the widest row, its
            # cells spaced apart.
            rows = ("   ".join(str(c) for c in r) if isinstance(r, (tuple, list))
                    else str(r) for r in ann.rows)
            over = (ann.title if text_width(ann.title, size + 1, bold=True) > body_w
                    else max(rows, key=lambda s: text_width(s, size), default=ann.title))
            report(f"annotation {ann.title!r} (width={ann.width:g})", over, over,
                   ann.width, inner + 2 * pad)
    L = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
         f'fill="white" stroke="black" stroke-width="{_BOX_RULE:g}"/>']
    if ann.title:
        L.append(_text(x + w / 2, y + title_h - _TITLE_RISE, ann.title, size + 1,
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


# Generic bordered table (TableBox)

def _table_layout(tb):
    """Return ``(size, ncol, col_w, row_h)`` for a TableBox.

    Parameters
    ----------
    tb : TableBox
        Table.

    Returns
    -------
    tuple
        Type size, column count, column widths and row depth.
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
    """Return a TableBox's ``(width, height)``.

    Parameters
    ----------
    tb : TableBox
        Table.

    Returns
    -------
    tuple[float, float]
        Width and height in drawing units.
    """
    size, ncol, col_w, row_h = _table_layout(tb)
    title_h = size + _TABLE_TITLE if tb.title else 0
    nrows = len(tb.rows) + (1 if tb.headers else 0)
    return _total(col_w), title_h + nrows * row_h


def draw_table(tb, x: float, y: float) -> list[str]:
    """Return a TableBox drawn with its top-left at ``(x, y)``.

    Parameters
    ----------
    tb : TableBox
        Table.
    x, y : float
        Top-left corner.

    Returns
    -------
    list[str]
        SVG elements.
    """
    size, ncol, col_w, row_h = _table_layout(tb)
    title_h = size + _TABLE_TITLE if tb.title else 0
    w = _total(col_w)
    align = tb.col_align or ["c"] * ncol
    L = []
    if tb.title:
        L.append(_text(x + w / 2, y + title_h - _TITLE_RISE, tb.title, size,
                       anchor="middle", bold=True))
    top = y + title_h

    def _row(ry, cells, *, header):
        """Append one ruled row at ``ry``.

        Parameters
        ----------
        ry : float
            Top of the row.
        cells : list
            Cell values.
        header : bool
            Draw a heading row.
        """
        cx = x
        for ci in range(ncol):
            val = cells[ci] if ci < len(cells) else ""
            fill = "#eee" if header else "white"
            L.append(f'<rect x="{cx:.1f}" y="{ry:.1f}" width="{col_w[ci]:.1f}" '
                     f'height="{row_h:.1f}" fill="{fill}" stroke="black" '
                     f'stroke-width="{_CELL_RULE:g}"/>')
            a = align[ci] if ci < len(align) else "c"
            if a == "l":
                tx, anc = cx + _TABLE_PAD, "start"
            elif a == "r":
                tx, anc = cx + col_w[ci] - _TABLE_PAD, "end"
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


# Stream property table (a heading row of line numbers, a row per
# property, section headings where the flowsheet asks for them)

# Clearance added to the widest text in a stream-table column.
_STREAM_GUTTER = 14.0

# Gutter before left-aligned text.
_STREAM_PAD = 5.0

# Fills for the heading row, section headings, row labels and values.
_STREAM_HEAD_FILL = "#eee"
_STREAM_SECTION_FILL = "#f4f4f4"
_STREAM_KEY_FILL = "#f9f9f9"
_STREAM_VALUE_FILL = "white"

# Default type size; a stated size scales row depth and column floors
# by its ratio to this.
_BASE_SIZE = 10.5

# Row depth at _BASE_SIZE.
_ROW_H = 20.0


def _width_floor(stated: float | str, name: str, ruled: float) -> float:
    """Return a column-width floor, scaled by ``ruled``.

    Parameters
    ----------
    stated : float or str
        Stated floor, or ``"auto"`` for none.
    name : str
        Option name, for error messages.
    ruled : float
        Scale relative to :data:`_BASE_SIZE`.

    Returns
    -------
    float
        Floor in drawing units; 0 for ``"auto"``.

    Raises
    ------
    ValueError
        If ``stated`` is not ``"auto"`` or a non-negative number.
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
    """Return the sheet's stream-table options, or the defaults.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet.

    Returns
    -------
    StreamTableOptions
        Stated or default options.
    """
    from pandid.document import StreamTableOptions
    options = getattr(fs, "stream_table", None)
    return StreamTableOptions() if options is None else options


# Warning code for a stream_table_sections key that matches no property.
_UNUSED_SECTION_CODE = "stream-table-section-unused"


def _report_unused_sections(fs, sec_before: dict[str, str], seen: set) -> None:
    """Replace the unused-section warnings on ``fs``.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet whose warnings are updated.
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
        Cell width.
    fill : str
        Cell fill.
    bold : bool
        Whether the text is bold.
    anchor : str
        SVG ``text-anchor``.
    """
    text: str
    w: float
    fill: str
    bold: bool
    anchor: str


class StreamTable(NamedTuple):
    """Stream table geometry, shared by both backends.

    Attributes
    ----------
    rows : list[list[StreamCell]]
        Cells, row by row, top to bottom.
    size : float
        Type size.
    row_h : float
        Row depth.
    w, h : float
        Table width and height.
    """
    rows: list
    size: float
    row_h: float
    w: float
    h: float


def _stream_cell_text(values, key) -> str:
    """Return the cell text for ``key``, ``"-"`` if missing.

    Parameters
    ----------
    values : dict
        A column's property values.
    key : str
        Property name.

    Returns
    -------
    str
        Cell text.
    """
    val = values.get(key, "-")
    return "-" if val in (None, "") else str(val)


def _run_values(run) -> dict:
    """Return one column's property values, merged over its run.

    Parameters
    ----------
    run : list[Stream]
        Segments of one named run, in drawing order.

    Returns
    -------
    dict
        First value of each key, the tabulated segment read first.

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
    """Return the named runs that get a column, in sheet order.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet.

    Returns
    -------
    list[list[Stream]]
        Runs with a property or crossing the edge (ISO 10628-1 4.3.2 d).
    """
    return [run for run in fs._named_runs().values()
            if any(s.properties for s in run) or any(s.at_boundary for s in run)]


class _Measured(NamedTuple):
    """Stream table measurements shared by the docked and sheet layouts.

    Attributes
    ----------
    streams : list[Stream]
        Each column's stream.
    cells : list[dict]
        Each column's property values.
    disp : list[tuple[str, str]]
        Rows as ``("section", label)`` or ``("data", key)``.
    heading : str
        Label of the heading row.
    size : float
        Type size.
    row_h : float
        Row depth.
    label_w : float
        Label column width.
    name_w : float
        Width of each stream column.
    span : float
        Width a section heading needs.
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
    """Return the label column width that fits section headings.

    Parameters
    ----------
    m : _Measured
        Table measurements.
    columns : int
        Stream columns beside the label column.

    Returns
    -------
    float
        Label column width.
    """
    return max(m.label_w, m.span - m.name_w * columns)


def _stream_table(m: "_Measured", streams: list, cells: list,
                  label_w: float) -> StreamTable:
    """Return a table over the given columns: whole, or one block.

    Parameters
    ----------
    m : _Measured
        Table measurements.
    streams : list[Stream]
        Each column's stream.
    cells : list[dict]
        Each column's property values.
    label_w : float
        Label column width.

    Returns
    -------
    StreamTable
        Table geometry.
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
    return StreamTable(rows, m.size, m.row_h,
                       label_w + m.name_w * len(streams),
                       m.row_h * len(rows))


def stream_table_layout(fs) -> "StreamTable | None":
    """Return the stream table docked on a diagram, or ``None``.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet.

    Returns
    -------
    StreamTable or None
        Table geometry, or ``None`` if it is empty.

    Raises
    ------
    ValueError
        If the stated font size is not positive.
    ValueError
        If a column width is not ``"auto"`` or a non-negative number.
    ValueError
        If more than one segment of a run is marked ``tabulate``.
    """
    m = _measure(fs)
    if m is None:
        return None
    return _stream_table(m, m.streams, m.cells,
                         _section_span(m, len(m.streams)))


def _measure(fs, *, own_sheet: bool = False) -> "_Measured | None":
    """Return the table's measurements, or ``None`` if it is empty.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet.
    own_sheet : bool, default=False
        Use the table-sheet default type size.

    Returns
    -------
    _Measured or None
        Measurements, or ``None`` if it is empty.

    Raises
    ------
    ValueError
        If the stated font size is not positive.
    ValueError
        If a column width is not ``"auto"`` or a non-negative number.
    ValueError
        If more than one segment of a run is marked ``tabulate``.
    """
    runs = _table_runs(fs)
    if not runs:
        return None
    streams = [run[0] for run in runs]
    cells = [_run_values(run) for run in runs]

    # Property rows, in first-seen order over every segment.
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
        # A table sheet keeps the base size and wraps columns instead.
        size, row_h, ruled = _BASE_SIZE, _ROW_H, 1.0
    elif asked is None:
        # The base size up to 18 columns, then smaller.
        size = _BASE_SIZE if n <= 18 else max(8.0, 190.0 / n)
        row_h = _ROW_H if n <= 18 else max(15.0, size + 5)
        ruled = 1.0
    else:
        # A stated size scales row depth and column floors.
        size = asked
        ruled = size / _BASE_SIZE
        row_h = _ROW_H * ruled
    disp = []  # ('section', label) | ('data', key)
    for k in order:
        if k in sec_before:
            disp.append(("section", sec_before[k]))
        disp.append(("data", k))
    heading = ("Line Number" if all(s.has_line_number for s in streams)
               else "Stream Number")

    # Size columns to their content, held up to the stated floors.
    labels = [heading] + [key for kind, key in disp if kind == "data"]
    label_w = max(_width_floor(options.label_width, "label_width", ruled),
                  max(text_width(t, size, bold=True)
                      for t in labels) + _STREAM_GUTTER)
    values = [_stream_cell_text(c, key) for kind, key in disp if kind == "data"
              for c in cells]
    # One width for every stream column, over all headings and values.
    name_w = max(_width_floor(options.column_width, "column_width", ruled),
                 max((text_width(s.name, size, bold=True) for s in streams),
                     default=0.0) + _STREAM_GUTTER,
                 max((text_width(v, size) for v in values), default=0.0)
                 + _STREAM_GUTTER)
    sections = [label for kind, label in disp if kind == "section"]
    span = max((text_width(t, size, bold=True) for t in sections),
               default=0.0) + _STREAM_GUTTER
    return _Measured(streams, cells, disp, heading, size, row_h,
                     label_w, name_w, span)


# Gap between table-sheet blocks, in rows.
_BLOCK_ROWS = 1.0


class TableSheet(NamedTuple):
    """Stream table on a sheet of its own, cut into stacked blocks.

    Attributes
    ----------
    blocks : list[StreamTable]
        Blocks, top to bottom.
    gap : float
        Gap between blocks.
    w, h : float
        Stack width and height.
    """
    blocks: list
    gap: float
    w: float
    h: float

    def at(self, left: float, top: float):
        """Yield ``(index, block, x, y)`` for each block, top down.

        Parameters
        ----------
        left : float
            Left edge of the stack.
        top : float
            Top of the stack.

        Yields
        ------
        tuple[int, StreamTable, float, float]
            Block index, block and its top-left corner.
        """
        y = top
        for i, block in enumerate(self.blocks):
            yield i, block, left, y
            y += block.h + self.gap


def _blocks_of(n: int, count: int) -> list:
    """Return ``range(n)`` split into ``count`` near-equal blocks.

    Parameters
    ----------
    n : int
        Number of columns.
    count : int
        Number of blocks, capped at ``n``.

    Returns
    -------
    list[list[int]]
        Column indices per block.
    """
    count = min(count, n)
    per, extra = divmod(n, count)
    blocks, start = [], 0
    for i in range(count):
        stop = start + per + (1 if i < extra else 0)
        blocks.append(list(range(start, stop)))
        start = stop
    return blocks


def _partition(m: "_Measured", n: int, room: "float | None") -> list:
    """Return the fewest column blocks whose ruled width fits ``room``.

    Parameters
    ----------
    m : _Measured
        Table measurements.
    n : int
        Number of columns.
    room : float or None
        Page width for the table, or ``None`` for one block.

    Returns
    -------
    list[list[int]]
        Column indices per block; one column each if none fits.
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
    """Return the stream table as stacked blocks, or ``None``.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet.
    room : float or None
        Page width for the table, or ``None`` for one block.

    Returns
    -------
    TableSheet or None
        Stacked blocks, or ``None`` if it is empty.

    Raises
    ------
    ValueError
        If the stated font size is not positive.
    ValueError
        If a column width is not ``"auto"`` or a non-negative number.
    ValueError
        If more than one segment of a run is marked ``tabulate``.
    """
    m = _measure(fs, own_sheet=True)
    if m is None:
        return None
    n = len(m.streams)
    chunks = _partition(m, n, room)
    # One label width for every block, fitted to the smallest.
    label_w = _section_span(m, min(len(c) for c in chunks))
    blocks = [_stream_table(m, [m.streams[i] for i in c],
                            [m.cells[i] for i in c], label_w)
              for c in chunks]
    gap = m.row_h * _BLOCK_ROWS
    return TableSheet(blocks, gap, max(b.w for b in blocks),
                      _total(b.h for b in blocks) + gap * (len(blocks) - 1))


def draw_stream_table(table: StreamTable, left: float, top: float, *,
                      group: str = "stream_table") -> list[str]:
    """Return ``table`` drawn with its top-left at ``(left, top)``.

    Parameters
    ----------
    table : StreamTable
        Table geometry.
    left, top : float
        Top-left corner.
    group : str, default="stream_table"
        SVG id of the enclosing group, unique per sheet.

    Returns
    -------
    list[str]
        SVG lines.
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


# Engineering title strip (revision table | company | client/project,
# title, status, drawing number / scale / date / rev)

# Strip rectangle weight, equal to the frame's.
_STRIP_RULE = 2.0
# Hairline for revision columns and bottom-band cells.
_STRIP_HAIRLINE = 0.5

_REV_W = 300.0
_COMPANY_W = 100.0
_INFO_W = 252.0
_REV_ROW = 14.0
# (heading, width, Revision field); widths sum to _REV_W.
_REV_COLS = (("REV", 22, "rev"), ("DATE", 50, "date"),
             ("DESCRIPTION", 132, "description"), ("BY", 32, "by"),
             ("CHK'D", 32, "checked"), ("APP'D", 32, "approved"))
# Gutter between a revision cell's rule and its text, left and right.
_REV_PAD = 3.0
# Block field that fills each signatory column the newest revision
# leaves blank.
_BACKFILL = {"by": "drawn_by", "checked": "checked_by",
             "approved": "approved_by"}
# Depth of the title, status and drawing-number bands.
_BODY_H = 80.0
# Width of the sheet-count slot at the top right of the title band.
_SHEET_W = 55.0
_TITLE_W = _INFO_W - 10 - _SHEET_W
# Depth of the client and project rows, and the value indent.
_HDR_ROW = 13.0
_HDR_VALUE_X = 40.0
# Shares of the information block's depth for the title and status
# bands; the drawing-number band takes the rest.
_TITLE_BAND, _STATUS_BAND = 0.40, 0.28

# Type sizes per band.
_REV_TYPE = 7.5        # revision cells and the sheet count
_CAPTION = 6.5         # the grey label over a field's value
_COMPANY_TYPE = 8.0
_HDR_TYPE = 9.0        # client and project values
_TITLE_TYPE = 12.5
_SUBTITLE_TYPE = 10.5
_VALUE_TYPE = 11.0     # status, drawing number, scale, date and rev

#: Caption ink, lighter than the value it labels.
CAPTION_INK = "#666"


# Line spacing of the company cell's wrapped lines.
_COMPANY_LEAD = 12.0


def _field(obj, name: str) -> str:
    """Return a title-block field as text, stripped; empty if unset.

    Parameters
    ----------
    obj : object
        Title block or revision.
    name : str
        Field name.

    Returns
    -------
    str
        Field text.
    """
    return _drawn_text(getattr(obj, name, None)).strip()


# Cache for _class_defaults.
_DEFAULTS: "dict[type, dict[str, str]]" = {}


def _class_defaults(cls: "type[Any]") -> "dict[str, str]":
    """Return a dataclass's string field defaults, cached per class.

    Parameters
    ----------
    cls : type
        Dataclass, or any other class.

    Returns
    -------
    dict[str, str]
        Field name to default; empty for a non-dataclass.
    """
    known = _DEFAULTS.get(cls)
    if known is None:
        known = _DEFAULTS[cls] = (
            {f.name: f.default for f in dataclasses.fields(cls)
             if isinstance(f.default, str)}
            if dataclasses.is_dataclass(cls) else {})
    return known


def _stated(obj, name: str) -> str:
    """Return a field as drawn: the stated value, else its default.

    Parameters
    ----------
    obj : object
        Title block or revision.
    name : str
        Field name.

    Returns
    -------
    str
        Field text.
    """
    return _field(obj, name) or _class_defaults(type(obj)).get(name, "")


def company_lines(company: str) -> list[str]:
    """Return ``company`` wrapped between words for its cell.

    Parameters
    ----------
    company : str
        Company name.

    Returns
    -------
    list[str]
        Lines; a word wider than the cell stays whole on its own.
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
    """Return how far the wrapped company name overruns the strip.

    Parameters
    ----------
    tb : TitleBlock
        Title block.

    Returns
    -------
    tuple[int, float, float] or None
        ``(lines, room, need)``, or ``None`` if it fits.
    """
    lines = company_lines(_stated(tb, "company"))
    _, room = measure_title_strip(tb)
    need = len(lines) * _COMPANY_LEAD
    return (len(lines), room, need) if need > room else None


def undrawn_signatories(tb) -> "list[tuple[str, str, str]]":
    """Return the block signatories the strip does not draw.

    Parameters
    ----------
    tb : TitleBlock
        Title block.

    Returns
    -------
    list[tuple[str, str, str]]
        ``(field, value, displaced_by)``; ``displaced_by`` may be empty.
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
    """Return the set client and project rows as ``(label, value)``.

    Parameters
    ----------
    tb : TitleBlock
        Title block.

    Returns
    -------
    list[tuple[str, str]]
        Rows, client first.
    """
    return [(label, value) for label, value
            in (("CLIENT", _stated(tb, "client")),
                ("PROJECT", _stated(tb, "project"))) if value]


def measure_title_strip(tb) -> tuple[float, float]:
    """Return the title strip's ``(width, height)``.

    Parameters
    ----------
    tb : TitleBlock
        Title block.

    Returns
    -------
    tuple[float, float]
        Width and height in drawing units.
    """
    n = len(tb.revisions)
    h = max((n + 1) * _REV_ROW, _BODY_H) + _HDR_ROW * len(_header_lines(tb))
    return _REV_W + _COMPANY_W + _INFO_W, h


class RevGrid(NamedTuple):
    """Revision grid geometry, with text already clipped.

    Attributes
    ----------
    x, y : float
        Top-left corner.
    w, h : float
        Width and height.
    cols : tuple[tuple[str, float], ...]
        Heading and width of each column.
    row_h : float
        Row depth.
    header_y : float
        Top of the heading row, at the foot.
    rows : list[list[str]]
        Revision rows, oldest first.
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
        Strip ``(x, y, w, h)``.
    rules : list[tuple]
        The two full-depth dividers, as rule parts.
    rev : RevGrid
        Revision grid.
    parts : list[tuple]
        Rules and text in drawing order; see :func:`_strip_part`.
    """
    box: tuple
    rules: list
    rev: RevGrid
    parts: list


def title_strip_layout(tb, name: str, date: str, right: float, bottom: float,
                       fit_scale: str = "", *,
                       report: "Reporter | None" = None) -> Strip:
    """Return the title strip laid out from its bottom-right corner.

    An overlong title is set smaller, down to the subtitle size, then
    trimmed. The company name and sheet count are drawn whole; other
    values are trimmed with an ellipsis.

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
        Scale for a block that states none.
    report : Reporter, optional
        Receives a finding per cell that cannot hold its value.

    Returns
    -------
    Strip
        Strip geometry.
    """
    name, date = str(name or "").strip(), str(date or "").strip()
    date = _stated(tb, "date") or date
    w, h = measure_title_strip(tb)
    x, y = right - w, bottom - h
    rx = x + _REV_W
    cx2 = rx + _COMPANY_W
    rules = [("rule", vx, y, vx, bottom, 1.5) for vx in (rx, cx2)]

    # --- Revision grid (left): heading at the foot, revisions above
    def rev_cells(cells, bold=False):
        """Return one grid row, each cell clipped to its column.

        Parameters
        ----------
        cells : list[tuple[str, str]]
            ``(value, field)`` per column; blank fields go unreported.
        bold : bool, default=False
            Measure bold advances.

        Returns
        -------
        list[str]
            Clipped cell texts.
        """
        return [clip(v, cw - 2 * _REV_PAD, _REV_TYPE, bold,
                     field=f, report=report if f else None)
                for (_, cw, _attr), (v, f) in zip(_REV_COLS, cells)]

    header_y = bottom - _REV_ROW
    headings = rev_cells([(c[0], "") for c in _REV_COLS], bold=True)
    # Clip newest first; store oldest first.
    newest_first = []
    for idx, rv in enumerate(reversed(tb.revisions)):
        newest = idx == 0
        i = len(tb.revisions) - 1 - idx
        row = []
        for _heading, _cw, attr in _REV_COLS:
            cell, value = f"revisions[{i}].{attr}", _stated(rv, attr)
            # Fill the newest row's blank signatories from the block,
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
        for k, ln in enumerate(lines):
            # A word wider than the cell is drawn whole and reported once.
            parts.append(("text", rx + _COMPANY_W / 2, cy,
                          check_fit(ln, _COMPANY_W - 10, _COMPANY_TYPE, True,
                                    field="company",
                                    report=None if ln in lines[:k] else report),
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
    # band.
    sheets = f"SHEET {_stated(tb, 'sheet')} of {_stated(tb, 'of_sheets')}"
    title = _stated(tb, "title") or name
    need = text_width(title, _TITLE_TYPE, True)
    title_type = (_TITLE_TYPE if need <= _TITLE_W else max(
        _SUBTITLE_TYPE, math.floor(_TITLE_TYPE * _TITLE_W / need * 10) / 10))
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
    # One cell from two fields; the finding names both.
    parts.append(("text", x + w - 5, top + 11,
                  check_fit(sheets, _SHEET_W, _REV_TYPE,
                            field="sheet/of_sheets", report=report),
                  _REV_TYPE, "end", False, CAPTION_INK))
    # Status: caption at the cell top, value below.
    parts.append(("text", ix + 6, band2 + 8, "STATUS", _CAPTION,
                  "start", False, CAPTION_INK))
    parts.append(("text", ix + 6, band3 - 5,
                  clip(_stated(tb, "status") or "—", _INFO_W - 12,
                       _VALUE_TYPE, True,
                       field="status", report=report),
                  _VALUE_TYPE, "start", True, "black"))
    # Bottom band: DRAWING No | SCALE | DATE | REV at fixed shares.
    # Fallback values name their source field.
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
    """Return the strip's overflow findings without drawing.

    Parameters
    ----------
    tb : TitleBlock
        Title block.
    name : str
        Title fallback.
    date : str
        Date fallback.
    fit_scale : str, default=""
        Scale for a block that states none.

    Returns
    -------
    list[tuple[str, str, str, float, float]]
        Findings, each a tuple of :data:`Reporter` arguments.
    """
    found: list[tuple[str, str, str, float, float]] = []
    title_strip_layout(tb, name, date, 0.0, 0.0, fit_scale,
                       report=lambda *cell: found.append(cell))
    return found


def _strip_part(part) -> str:
    """Return one :class:`Strip` part as SVG.

    Parameters
    ----------
    part : tuple
        A ``"rule"`` or ``"text"`` part.

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
    """Return the title strip drawn from its bottom-right corner.

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
        Scale for a block that states none.
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

    # Revision grid: heading rule, full-depth column rules, then text.
    g = strip.rev
    L.append(_strip_part(("rule", g.x, g.header_y, g.x + g.w, g.header_y,
                          _BOX_UNDERLINE)))
    cx = g.x
    for _heading, cw in g.cols[:-1]:
        cx += cw
        L.append(_strip_part(("rule", cx, g.y, cx, g.y + g.h, _STRIP_HAIRLINE)))

    def rev_row(ry, vals, bold=False):
        """Append one row of revision text at ``ry``.

        Parameters
        ----------
        ry : float
            Top of the row.
        vals : list[str]
            Cell texts.
        bold : bool, default=False
            Set the text bold.
        """
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


# Zone-ruled drawing border: letters A.. top down, numerals 1.. left
# to right (ISO 5457 4.4).

#: Width of the lettered band between drawing frame and sheet border.
ZONE_BAND = 16.0


def sheet_rect(ix: float, iy: float, iw: float, ih: float
               ) -> tuple[float, float, float, float]:
    """Return the sheet rectangle a zone band's width around a frame.

    Parameters
    ----------
    ix, iy : float
        Frame top-left corner.
    iw, ih : float
        Frame width and height.

    Returns
    -------
    tuple[float, float, float, float]
        Sheet ``(x, y, w, h)``.
    """
    return ix - ZONE_BAND, iy - ZONE_BAND, iw + 2 * ZONE_BAND, ih + 2 * ZONE_BAND


#: Zone letter size, and its baseline drop from the band's middle.
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
        ``("rule", x1, y1, x2, y2)`` and ``("label", x, y, text)``.
    """
    outer: tuple[float, float, float, float]
    inner: tuple[float, float, float, float]
    parts: list[tuple]


def zone_layout(ix: float, iy: float, iw: float, ih: float) -> Zoned:
    """Return the zone-ruled border around a drawing frame.

    Parameters
    ----------
    ix, iy : float
        Frame top-left corner.
    iw, ih : float
        Frame width and height.

    Returns
    -------
    Zoned
        Border geometry.
    """
    ox, oy, ow, oh = sheet_rect(ix, iy, iw, ih)
    cols = max(4, min(12, round(iw / 165)))
    rows = max(3, min(8, round(ih / 165)))
    parts: list[tuple] = []
    letters = string.ascii_uppercase
    # Columns: numerals left to right, on the top and bottom bands.
    for c in range(cols):
        x0 = ix + iw * c / cols
        x1 = ix + iw * (c + 1) / cols
        num = str(c + 1)
        if c:
            parts.append(("rule", x0, oy, x0, iy))
            parts.append(("rule", x0, iy + ih, x0, oy + oh))
        parts.append(("label", (x0 + x1) / 2, oy + ZONE_BAND / 2, num))
        parts.append(("label", (x0 + x1) / 2, oy + oh - ZONE_BAND / 2, num))
    # Rows: letters top down, on the left and right bands.
    for r in range(rows):
        y0 = iy + ih * r / rows
        y1 = iy + ih * (r + 1) / rows
        letter = letters[r]
        if r:
            parts.append(("rule", ox, y0, ix, y0))
            parts.append(("rule", ix + iw, y0, ox + ow, y0))
        parts.append(("label", ox + ZONE_BAND / 2, (y0 + y1) / 2, letter))
        parts.append(("label", ox + ow - ZONE_BAND / 2, (y0 + y1) / 2, letter))
    return Zoned((ox, oy, ow, oh), (ix, iy, iw, ih), parts)


def zone_frame(ix: float, iy: float, iw: float, ih: float) -> list[str]:
    """Return the zone-ruled border drawn around a frame.

    Parameters
    ----------
    ix, iy : float
        Frame top-left corner.
    iw, ih : float
        Frame width and height.

    Returns
    -------
    list[str]
        SVG elements.
    """
    z = zone_layout(ix, iy, iw, ih)
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
    return L


# The sheet dock: which rectangle each piece of furniture is given

#: Clearances: drawing to frame, between boxes in one stack, and
#: between left and right stacks sharing a band.
INNER, GAP, SEP = 26.0, 14.0, 18.0

#: Margin outside the sheet border.
OUTER_MARGIN = 8.0


class Docked(NamedTuple):
    """One piece of furniture and the rectangle the sheet gives it.

    Attributes
    ----------
    obj : object
        The furniture.
    x, y : float
        Top-left corner.
    w, h : float
        Width and height.
    """
    obj: object
    x: float
    y: float
    w: float
    h: float


def dock(items, inner, *, sheet=None, too_small=None):
    """Return ``(placed, frame, free)`` for the sheet furniture.

    Each box stacks flush to the frame edge its ``align`` names, inset
    by its ``margin``; a box with a ``position`` goes there.

    Parameters
    ----------
    items : iterable of tuple
        ``(obj, align, w, h)``; ``obj`` may set margin and position.
    inner : tuple[float, float, float, float]
        Drawing bounds ``(x0, y0, x1, y1)``.
    sheet : _Sheet, optional
        Fixed page; without it the frame grows to fit.
    too_small : callable, optional
        Takes ``(need_w, need_h, culprit)``; returns the error to raise.

    Returns
    -------
    placed : list[Docked]
        Placed boxes.
    frame : tuple[float, float, float, float]
        Frame ``(x, y, w, h)``.
    free : tuple[float, float, float, float] or None
        Region left free on ``sheet``; ``None`` without ``sheet``.

    Raises
    ------
    TypeError
        If the furniture overflows ``sheet`` and ``too_small`` is None.
    Exception
        From ``too_small``, if the furniture overflows ``sheet``.
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
        """Return a stack's height, with gaps.

        Parameters
        ----------
        entries : list[tuple]
            ``(obj, w, h)`` boxes in one stack.

        Returns
        -------
        float
            Height including gaps.
        """
        return _total(h for _, _, h in entries) + GAP * max(0, len(entries) - 1)

    def stack_w(entries):
        """Return a stack's width.

        Parameters
        ----------
        entries : list[tuple]
            ``(obj, w, h)`` boxes in one stack.

        Returns
        -------
        float
            Width of its widest box.
        """
        return max((w for _, w, _ in entries), default=0.0)

    # band thicknesses -------------------------------------------
    top_h = max(stack_h(cols["top-left"]), stack_h(cols["top"]),
                stack_h(cols["top-right"]))
    bottom_h = max(stack_h(cols["bottom-left"]), stack_h(cols["bottom"]),
                   stack_h(cols["bottom-right"]))
    left_w, right_w = stack_w(cols["left"]), stack_w(cols["right"])

    def row_w(lk, ck, rk):
        """Return the width a band row needs.

        Parameters
        ----------
        lk, ck, rk : str
            Left, centre and right alignments of the row.

        Returns
        -------
        float
            Row width.
        """
        lw, cw, rw = stack_w(cols[lk]), stack_w(cols[ck]), stack_w(cols[rk])
        side = (lw + SEP + rw) if (lw and rw) else max(lw, rw)
        return max(side, cw)

    band_w = max(row_w("top-left", "top", "top-right"),
                 row_w("bottom-left", "bottom", "bottom-right"))

    # frame rectangle --------------------------------------------
    if sheet is not None:
        # A fixed page: the frame is the sheet inset by band and margin.
        edge = OUTER_MARGIN + ZONE_BAND
        need_w = max(band_w, left_w + right_w + 2 * INNER)
        need_h = max(top_h + bottom_h + 2 * INNER,
                     stack_h(cols["left"]), stack_h(cols["right"]))
        too_wide = need_w >= sheet.width - 2 * edge
        if too_wide or need_h >= sheet.height - 2 * edge:
            if too_small is None:
                raise TypeError("dock() needs a too_small callback when sheet is given")
            # Blame the widest piece, or the tallest.
            dim = 1 if too_wide else 2
            entries = [it for col in cols.values() for it in col]
            raise too_small(need_w + 2 * edge, need_h + 2 * edge,
                            max(entries, key=lambda it: it[dim])[0] if entries else None)
        ix, iy = edge, edge
        ixr, iyb = sheet.width - edge, sheet.height - edge
    else:
        ix = dx0 - INNER - left_w
        iy = dy0 - INNER - top_h
        ixr = dx1 + INNER + right_w
        iyb = dy1 + INNER + bottom_h
        extra = band_w - (ixr - ix)
        if extra > 0:
            ix -= extra / 2
            ixr += extra / 2
        extra = max(stack_h(cols["left"]), stack_h(cols["right"])) - (iyb - iy)
        if extra > 0:
            iy -= extra / 2
            iyb += extra / 2
    iw, ih = ixr - ix, iyb - iy

    free = None if sheet is None else (
        ix + left_w + INNER, iy + top_h + INNER,
        iw - left_w - right_w - 2 * INNER, ih - top_h - bottom_h - 2 * INNER)

    # place each column flush to the frame -----------------------
    placed: list[Docked] = []

    def x_for(mode, w, m):
        """Return a box's x for left, right or centred placement.

        Parameters
        ----------
        mode : str
            ``"l"``, ``"r"`` or ``"c"``.
        w : float
            Box width.
        m : float
            Box margin.

        Returns
        -------
        float
            Left edge of the box.
        """
        if mode == "l":
            return ix + m
        if mode == "r":
            return ixr - m - w
        return ix + (iw - w) / 2

    def put_top(entries, mode):
        """Place a stack against the top edge.

        Parameters
        ----------
        entries : list[tuple]
            ``(obj, w, h)`` boxes in one stack.
        mode : str
            ``"l"``, ``"r"`` or ``"c"``.
        """
        y = iy
        for obj, w, h in entries:
            m = getattr(obj, "margin", 0.0)
            placed.append(Docked(obj, x_for(mode, w, m), y + m, w, h))
            y += m + h + GAP

    def put_bottom(entries, mode):
        """Place a stack against the bottom edge.

        Parameters
        ----------
        entries : list[tuple]
            ``(obj, w, h)`` boxes in one stack.
        mode : str
            ``"l"``, ``"r"`` or ``"c"``.
        """
        y = iyb
        for obj, w, h in reversed(entries):
            m = getattr(obj, "margin", 0.0)
            top = y - m - h
            placed.append(Docked(obj, x_for(mode, w, m), top, w, h))
            y = top - GAP

    def put_side(entries, mode):
        """Place a stack against a side edge, centred vertically.

        Parameters
        ----------
        entries : list[tuple]
            ``(obj, w, h)`` boxes in one stack.
        mode : str
            ``"l"``, ``"r"`` or ``"c"``.
        """
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
    put_side(cols["center"], "c")

    # hand-placed boxes; expand the frame to keep them inside ----
    for obj, px, py, w, h in positioned:
        placed.append(Docked(obj, px, py, w, h))
        if sheet is not None:
            continue
        ix, iy = min(ix, px - INNER), min(iy, py - INNER)
        ixr, iyb = max(ixr, px + w + INNER), max(iyb, py + h + INNER)
    iw, ih = ixr - ix, iyb - iy

    return placed, (ix, iy, iw, ih), free
