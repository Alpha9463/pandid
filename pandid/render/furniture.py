"""Sheet furniture: the engineering title strip, generic titled boxes,
generic tables, the stream property table, and the zone-ruled drawing
border.

Every routine here is a pure function returning a list of SVG-fragment
strings (or a ``(width, height)`` measurement). The renderer in
:mod:`pandid.render.svg` measures each piece, places it at a sheet
corner, unions the result to size the canvas, then draws it; none of the
geometry logic lives in the giant render method.

:func:`dock` is the placement itself, and it is *not* SVG: it takes
measured boxes and answers the rectangle the sheet gives each one. It
lives here rather than inside the renderer because two backends now ask
the question. See its docstring.

Coordinates are absolute SVG user units. Boxes are drawn from a top-left
origin; the title strip is drawn from a bottom-right corner (its natural
anchor).
"""

from __future__ import annotations

import string
from typing import Callable, NamedTuple

from pandid.render.escape import escaped

# Rough advance width of the sans-serif the renderer uses, as a fraction
# of the font size. Slightly generous so auto-sized boxes never clip
# their text.
_ADV = 0.56
_ADV_BOLD = 0.62

FONT = "sans-serif"

# How a cell says it could not hold what it was given: the field it
# draws, the text it was asked for, and the text it actually drew (the
# same string when nothing was trimmed). An ellipsis tells whoever reads
# the sheet that a value was abbreviated and tells the program that
# supplied it nothing at all, and that program is the one that can
# shorten the field or ask for a bigger sheet. Every fixed-width cell
# here measures first and reports through one of these.
Reporter = Callable[[str, str, str], None]


def text_width(s, size: float, bold: bool = False) -> float:
    return len(str(s)) * size * (_ADV_BOLD if bold else _ADV)


def clip(s, room: float, size: float, bold: bool = False, *,
         field: str = "", report: "Reporter | None" = None) -> str:
    """Trim a value to the room its cell has, and report what was cut.

    A title-block cell is ruled and the strip is fixed geometry, so a
    value longer than its cell would run across the rule and into the
    value beside it and no amount of growing can help. A draftsman
    abbreviates.
    """
    s = str(s)
    if text_width(s, size, bold) <= room:
        return s
    per = size * (_ADV_BOLD if bold else _ADV)
    drawn = s[: max(0, int(room / per) - 1)].rstrip() + "…"
    if report is not None:
        report(field, s, drawn)
    return drawn


def check_fit(s, room: float, size: float, bold: bool = False, *,
              field: str = "", report: "Reporter | None" = None) -> str:
    """Measure a value that is drawn whole whatever it measures, and
    report an overrun.

    Some cells have nothing worth trimming. Half a sheet count reads as
    a different sheet count, and a company name broken mid-word reads as
    a different company, so those are drawn in full and the overrun is
    reported instead of hidden.
    """
    s = str(s)
    if report is not None and text_width(s, size, bold) > room:
        report(field, s, s)
    return s


def _text(x, y, s, size, *, anchor="start", bold=False, fill="black", baseline=None):
    wt = ' font-weight="bold"' if bold else ""
    bl = f' dominant-baseline="{baseline}"' if baseline else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size:.1f}"'
            f' text-anchor="{anchor}"{wt}{bl} fill="{fill}">{escaped(s)}</text>')


# ----------------------------------------------------------------
# Generic titled box (Annotation): title bar over rows
# ----------------------------------------------------------------

#: The weight a titled box's own rectangle is ruled at, and the rule
#: under its title. Named because :mod:`pandid.render.drawio` writes the
#: box out as a draw.io table and has to state the weight on the
#: container: draw.io draws a table's border and internal rules from the
#: container's own style.
_BOX_RULE = 1.5
_BOX_UNDERLINE = 1.0
#: The weight a :class:`~pandid.document.TableBox` rules every one of
#: its cells at -- lighter than the box above, because a table really is
#: ruled across and down and a grid at 1,5 would compete with the
#: drawing beside it.
_CELL_RULE = 0.75


def _ann_layout(ann):
    """Compute the column widths and row metrics for an Annotation."""
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
    size, row_h, title_h, col_w = _ann_layout(ann)
    pad, gap = 9.0, 12.0
    body_w = sum(col_w) + gap * (len(col_w) - 1)
    inner = max(body_w, text_width(ann.title, size + 1, bold=True))
    w = ann.width if ann.width is not None else inner + 2 * pad
    h = title_h + len(ann.rows) * row_h + 8
    return w, h


def _overflowing_text(ann, size: float, body_w: float) -> str:
    """The one string a too-narrow box is best described by: its title
    where that is what overruns, otherwise the row that does.
    """
    if text_width(ann.title, size + 1, bold=True) > body_w:
        return ann.title

    def flat(r):
        return "   ".join(str(c) for c in r) if isinstance(r, (tuple, list)) else str(r)
    return max((flat(r) for r in ann.rows), key=lambda s: text_width(s, size),
               default=ann.title)


def draw_annotation(ann, x: float, y: float, *,
                    report: "Reporter | None" = None) -> list[str]:
    """Draw an Annotation with its top-left corner at (x, y).

    A box left to size itself is sized from its own rows, so it always
    fits. One given an explicit ``width`` is a fixed cell like any
    other: the rows are still drawn at the column stops their content
    asks for, so a width smaller than that content runs the text out
    through the side of the box.
    """
    size, row_h, title_h, col_w = _ann_layout(ann)
    pad, gap = 9.0, 12.0
    w, h = measure_annotation(ann)
    if report is not None and ann.width is not None:
        body_w = sum(col_w) + gap * (len(col_w) - 1)
        inner = max(body_w, text_width(ann.title, size + 1, bold=True))
        if ann.width < inner + 2 * pad:
            over = _overflowing_text(ann, size, body_w)
            report(f"annotation {ann.title!r} (width={ann.width:g})", over, over)
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
    size, ncol, col_w, row_h = _table_layout(tb)
    title_h = size + 10 if tb.title else 0
    nrows = len(tb.rows) + (1 if tb.headers else 0)
    return sum(col_w), title_h + nrows * row_h


def draw_table(tb, x: float, y: float) -> list[str]:
    size, ncol, col_w, row_h = _table_layout(tb)
    title_h = size + 10 if tb.title else 0
    w = sum(col_w)
    align = tb.col_align or ["c"] * ncol
    L = []
    if tb.title:
        L.append(_text(x + w / 2, y + title_h - 6, tb.title, size,
                       anchor="middle", bold=True))
    top = y + title_h

    def _row(ry, cells, *, header):
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
# Split the way the title strip is split: a layout function
# (:func:`stream_table_layout`) that answers where every cell goes and
# what is in it, and a stroker (:func:`draw_stream_table`) that turns
# that into SVG. The sheet strokes the layout;
# :mod:`pandid.render.drawio` builds table cells from the same one.
# Neither backend measures a column.

#: Clearance a stream-table column is ruled with over the widest thing
#: in it. Applied once per column, to whichever of the heading and the
#: values is wider.
_STREAM_GUTTER = 14.0

#: Gutter between a cell's rule and text set against its left edge. The
#: draw.io exporter states this too -- less what a draw.io cell insets
#: on its own account -- so a row label starts the same distance in
#: whichever backend drew it.
_STREAM_PAD = 5.0

#: What the table fills its four kinds of cell with. The heading row is
#: the grey the sheet fills every heading row with; a section heading is
#: a shade lighter, being a heading *inside* the table rather than over
#: it; a row label is lighter still, since it is read as a label rather
#: than as a heading; a value is the paper.
_STREAM_HEAD_FILL = "#eee"
_STREAM_SECTION_FILL = "#f4f4f4"
_STREAM_KEY_FILL = "#f9f9f9"
_STREAM_VALUE_FILL = "white"


class StreamCell(NamedTuple):
    """One ruled cell of the stream table.

    ``w`` is the cell's own width rather than its column's: a section
    heading spans the whole table and is **one** cell, which is what the
    sheet strokes and what a merged cell is in a draw.io table.
    ``anchor`` is the SVG ``text-anchor``, and the table sets a cell one
    of two ways -- ``start`` for a label, ``middle`` for a value -- so
    those are the two it takes.
    """
    text: str
    w: float
    fill: str
    bold: bool
    anchor: str


class StreamTable(NamedTuple):
    """The stream property table, as geometry rather than as ink.

    ``rows`` is the table row by row, top to bottom, each row its cells
    left to right -- which is both the order the sheet strokes them in
    and the structure a draw.io table is built from (a container of rows
    of cells).

    ``w``/``h`` is what the table measures, which is what :func:`dock`
    is given to place it by; ``row_h`` is the depth of every row and
    ``size`` the type it is all set in. A row is uniform depth here,
    unlike a revision grid: every row holds one line of text.
    """
    rows: list
    size: float
    row_h: float
    w: float
    h: float


def _stream_cell_text(values, key) -> str:
    """What one column's cell draws for one property row.

    The single place the placeholder for a missing value is decided, so
    the column that is *measured* is the column that is drawn.
    """
    val = values.get(key, "-")
    return "-" if val in (None, "") else str(val)


def _run_values(run) -> dict:
    """One column's values, gathered over the whole run.

    A run drawn through inline devices is several streams sharing one
    name and one column, and each of them can carry properties. Read in
    segment order, the first statement of a key winning, with any
    segment the author marked :attr:`~pandid.streams.Stream.tabulate`
    read before the rest.

    **Over the run**, because everything else about the column already
    is: whether it exists at all (:func:`_table_runs`) and which rows it
    fills (:func:`stream_table_layout`) are both asked of every segment,
    and only the values used to come off the first one. A property
    written on the far end of a line therefore kept the column, added
    its row and then drew a dash in it.

    **Marked**, because segments can disagree and no rule can settle it.
    A control valve is there to drop the pressure, so ``S6`` at 11.6
    barg above one and 3.4 barg below it is the author describing the
    line correctly; one column cannot show both, and which point it
    reports is a decision about the drawing rather than about the data.
    Unmarked, the run reads in the order it is drawn, which is what it
    always did.
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
    """The runs that get a column, each as its segments, in sheet order.

    One column per name -- a run drawn in two segments is one stream --
    and never a signal, which is not a stream of anything and has no
    properties to tabulate. What remains is the question this answers:
    **a column has to have something in it.**

    A stream that states no property at all is dropped. An empty column
    is a heading over a rule of dashes, and there is no clause behind
    it: ISO 10628-1:2014 4.3.3 a) puts the flows *between the process
    steps* among the things a PFD may carry rather than must.

    Unless it crosses the sheet edge. 4.3.2 d) makes the name of each
    ingoing and outgoing material, with its flow rate or quantity,
    something the diagram **shall** contain, so a feed or a product with
    nothing on it keeps its column -- dropping it would hide exactly
    what the standard asks the sheet to report, and hide it precisely
    because it is missing. The empty column is the sheet saying so, and
    :func:`pandid.validate.model_issues` says it in words as well.
    :attr:`pandid.streams.Stream.at_boundary` is where that line is
    drawn.

    A property *present and blank* is not nothing: ``{"H2S": ""}`` is
    the author saying this stream has none to report, and it keeps the
    column. Only an absent key is silence. The two draw the same dash
    (:func:`_stream_cell_text`) and are distinct in the model, which is
    what makes a blank the way to keep a column the drop rule would
    otherwise take.

    Both questions are asked of the **whole run** rather than of the
    segment the column is headed from, so nothing is dropped for being
    written down at the far end of a line: a run out to a product flag
    reaches it on its last segment, and a run's properties are written
    wherever the author wrote them.
    """
    return [run for run in fs._named_runs().values()
            if any(s.properties for s in run) or any(s.at_boundary for s in run)]


def _table_streams(fs) -> list:
    """The stream each column is headed from, in sheet order.

    The first segment of each run in :func:`_table_runs`. What the
    heading is made of belongs to the run rather than to any one segment
    -- the number is the same on all of them, and the line-number
    components are written where the run starts -- so the head is fixed
    and never moves with a ``tabulate`` mark. The column's *values* are
    a separate question and are gathered over the whole run; see
    :func:`_run_values`.
    """
    return [run[0] for run in _table_runs(fs)]


def stream_table_layout(fs) -> "StreamTable | None":
    """Where every cell of the stream table goes and what is in it, or
    ``None`` for a flowsheet with nothing to tabulate.

    The table is measured from its own contents and placed at whatever
    it comes to -- the sheet is grown around it, or a page too small for
    it is refused -- so unlike a title-block cell there is no fixed room
    here to abbreviate into. A stream table that cannot show ``0.0441
    kg/kg total`` is not a stream table.

    Nothing to tabulate is answered twice, and the second is the one
    that matters: no stream gets a column (:func:`_table_streams`), or
    no stream states a property, which leaves the columns that did get
    one with no row to fill. Both are a grid of headings over nothing,
    and a heading is not a stream table either.
    """
    runs = _table_runs(fs)
    if not runs:
        return None
    streams = [run[0] for run in runs]  # what each column is headed from
    cells = [_run_values(run) for run in runs]  # and what goes down it

    # property rows in first-seen order (dict preserves insertion order),
    # over every segment of a run for the reason its column was kept
    # over every segment: the row belongs to the sheet, and a run that
    # names a property anywhere has named it.
    order, seen = [], set()
    for run in runs:
        for s in run:
            for k in s.properties:
                if k not in seen:
                    seen.add(k)
                    order.append(k)
    if not order:
        return None
    sec_before: dict[str, str] = {}
    for key, label in (getattr(fs, "stream_table_sections", []) or []):
        sec_before.setdefault(key, label)

    n = len(streams)
    size = 10.5 if n <= 18 else max(8.0, 190.0 / n)
    row_h = 20.0 if n <= 18 else max(15.0, size + 5)
    disp = []  # ('section', label) | ('data', key)
    for k in order:
        if k in sec_before:
            disp.append(("section", sec_before[k]))
        disp.append(("data", k))
    # The corner cell has to be true of every column under it, so the
    # table only calls itself a line-number table when every line drawn
    # in it is identified that way.
    heading = ("Line Number" if all(s.has_line_number for s in streams)
               else "Stream Number")

    # Every column is sized to what goes in it. A minimum keeps a table
    # of short values from ruling columns too narrow to read as columns.
    labels = [heading] + [key for kind, key in disp if kind == "data"]
    label_w = max(122.0, max(text_width(t, size, bold=True)
                             for t in labels) + _STREAM_GUTTER)
    values = [_stream_cell_text(c, key) for kind, key in disp if kind == "data"
              for c in cells]
    name_w = max(52.0,
                 max((text_width(s.name, size, bold=True) for s in streams),
                     default=0.0) + _STREAM_GUTTER,
                 max((text_width(v, size) for v in values), default=0.0)
                 + _STREAM_GUTTER)
    # A section header spans the whole table, so it is the total width
    # it constrains rather than any one column; the row label column is
    # the only one free to take up the slack.
    sections = [label for kind, label in disp if kind == "section"]
    span = max((text_width(t, size, bold=True) for t in sections),
               default=0.0) + _STREAM_GUTTER
    label_w = max(label_w, span - name_w * n)

    rows: list[list[StreamCell]] = [
        [StreamCell(heading, label_w, _STREAM_HEAD_FILL, True, "start")]
        + [StreamCell(s.name, name_w, _STREAM_HEAD_FILL, True, "middle")
           for s in streams]]
    for kind, key in disp:
        if kind == "section":
            rows.append([StreamCell(key, label_w + name_w * n,
                                    _STREAM_SECTION_FILL, True, "start")])
            continue
        rows.append(
            [StreamCell(key, label_w, _STREAM_KEY_FILL, True, "start")]
            + [StreamCell(_stream_cell_text(c, key), name_w,
                          _STREAM_VALUE_FILL, False, "middle")
               for c in cells])
    return StreamTable(rows, size, row_h, label_w + name_w * n,
                       row_h * len(rows))


def draw_stream_table(table: StreamTable, left: float, top: float) -> list[str]:
    """Draw the table with its top-left corner at (``left``, ``top``).

    The geometry is :func:`stream_table_layout`'s; this strokes it,
    exactly as :func:`draw_title_strip` strokes
    :func:`title_strip_layout`. Every cell is ruled on all four sides --
    a stream table really is a grid, read across for one property and
    down for one stream -- at the weight a grid beside a drawing is
    ruled at rather than the weight a box around one is.
    """
    out = ['<g id="stream_table">']
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

#: The weight the strip's own rectangle is ruled at. It is the frame's
#: weight too, and it docks flush to the frame, so the two rules are
#: coincident and the corner of the sheet reads as one heavy line rather
#: than two.
_STRIP_RULE = 2.0
#: The hairline the strip rules a revision column and a bottom-band cell
#: with: light enough that the grid does not compete with the drawing
#: above it.
_STRIP_HAIRLINE = 0.5

_REV_W = 300.0
_COMPANY_W = 100.0
_INFO_W = 252.0
_REV_ROW = 14.0
# (heading, width, the Revision field the column draws). The widths sum
# to _REV_W. DATE is 50 because a full ISO 8601 date at 7.5 with a
# gutter either side comes to that, and at 42 it ran over its own rule.
_REV_COLS = (("REV", 22, "rev"), ("DATE", 50, "date"),
             ("DESCRIPTION", 132, "description"), ("BY", 32, "by"),
             ("CHK'D", 32, "checked"), ("APP'D", 32, "approved"))
# Gutter between a revision cell's rule and its text, left and right.
_REV_PAD = 3.0
# The title / status / drawing-number bands, which every sheet carries.
_BODY_H = 80.0
# The sheet count is drawn top-right of the title band, on the same line
# as the title. A fixed slot keeps the title's own budget constant: how
# much of a drawing's title survives must not depend on how many sheets
# the set happens to have. Sized for "SHEET 1 of 12" at 7.5; a longer
# count is drawn whole and reported, since half a sheet count reads as a
# different sheet.
_SHEET_W = 55.0
_TITLE_W = _INFO_W - 10 - _SHEET_W
# One client or project line above them. Neither is an ISO 7200 field:
# its mandatory "legal owner" is the issuing organisation, which is the
# company cell. An issued sheet names both anyway, so the pair heads the
# information block; a block that names neither is ruled no row for
# them.
_HDR_ROW = 13.0
_HDR_VALUE_X = 40.0
# How the information block's depth is shared between the title band,
# the status band and the drawing-number band that carries the rest.
_TITLE_BAND, _STATUS_BAND = 0.40, 0.28

# The type the strip is lettered in, band by band. Named because a
# second backend letters the same bands.
_REV_TYPE = 7.5        # a revision cell, and the sheet count in the title band
_CAPTION = 6.5         # the small grey label sitting over a field's value
_COMPANY_TYPE = 8.0
_HDR_TYPE = 9.0        # a client or project value
_TITLE_TYPE = 12.5
_SUBTITLE_TYPE = 10.5
_VALUE_TYPE = 11.0     # a status, a drawing number, a scale, a date, a rev

#: The ink a caption is set in, which is what holds it back from the
#: value under it: a caption names the field and the value is the
#: drawing's own information, so the two are not read at the same
#: weight.
CAPTION_INK = "#666"


def _header_lines(tb) -> list[tuple[str, str]]:
    return [(label, value) for label, value
            in (("CLIENT", tb.client), ("PROJECT", tb.project)) if value]


def measure_title_strip(tb) -> tuple[float, float]:
    n = len(tb.revisions)
    h = max((n + 1) * _REV_ROW, _BODY_H) + _HDR_ROW * len(_header_lines(tb))
    return _REV_W + _COMPANY_W + _INFO_W, h


class RevGrid(NamedTuple):
    """The revision history, as the grid it is rather than as ink.

    ``x``/``y``/``w``/``h`` is the whole left-hand column of the strip,
    which is the rectangle the vertical rules run the full depth of;
    ``cols`` is ``(heading, width)`` per column, ``row_h`` the depth of
    a row, ``header_y`` the line the heading row is ruled off at, and
    ``rows`` the revisions **oldest first** -- top to bottom on the
    sheet, since the heading sits at the foot and the newest revision
    immediately above it. Every value in ``rows`` and every heading has
    already been clipped to its own column, so a second backend cannot
    letter the grid at a size the widths were not measured at.

    The blank paper above the oldest revision is not a row and is not
    listed: it is the room the next revision will be written in, and the
    sheet rules nothing across it.
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
    """The title strip, as geometry rather than as ink.

    :func:`zone_layout`'s pattern one level up, so that the draw.io
    backend rules the *same* strip rather than a second opinion about
    one.

    ``box`` is the strip rectangle ``(x, y, w, h)``, ruled at 2.
    ``rules`` is the pair of full-depth column rules that divide it into
    revision grid, company cell and information block. ``rev`` is the
    grid. ``parts`` is everything else, **in drawing order**: ``("rule",
    x1, y1, x2, y2, weight)`` and ``("text", x, baseline, string, size,
    anchor, bold, fill)``, the text stated the way SVG states it -- at a
    baseline, with a ``text-anchor``. One list, because two would have
    to be re-interleaved to put the ink back where it was.
    """
    box: tuple
    rules: list
    rev: RevGrid
    parts: list


def title_strip_layout(tb, name: str, date: str, right: float, bottom: float,
                       fit_scale: str = "", *,
                       report: "Reporter | None" = None) -> Strip:
    """Where every part of the title strip goes, its bottom-right corner
    at (``right``, ``bottom``).

    ``fit_scale`` is the ratio the renderer actually placed the drawing
    at, which is what the scale cell reports for a sheet that does not
    state a scale of its own.

    The strip is fixed geometry -- ISO 15519-1 §5.2.2 splits the title
    block in two and fixes both halves, where it sits to ISO 5457 and
    how big it is and what goes in it to ISO 7200 --
    so a value too long for its cell cannot be given more room and is
    abbreviated instead. ``report`` is how each such
    cell says which field it abbreviated and what it was given; see
    :data:`Reporter`. The clipping happens **here** and not in either
    stroker, so the two backends abbreviate the same field to the same
    string.
    """
    w, h = measure_title_strip(tb)
    x, y = right - w, bottom - h
    rx = x + _REV_W
    cx2 = rx + _COMPANY_W
    rules = [("rule", vx, y, vx, bottom, 1.5) for vx in (rx, cx2)]

    # --- Revision grid (left): heading at the foot, revisions above
    def rev_cells(vals, bold=False, where=""):
        return [clip(v, cw - 2 * _REV_PAD, _REV_TYPE, bold,
                     field=f"{where}.{attr}", report=report if where else None)
                for (_, cw, attr), v in zip(_REV_COLS, vals)]

    header_y = bottom - _REV_ROW
    headings = rev_cells([c[0] for c in _REV_COLS], bold=True)
    # Clipped newest first, which is the order the strip used to draw
    # them in and so the order a caller watching ``report`` already
    # sees; stored oldest first, which is the order they are read in.
    newest_first = []
    for idx, rv in enumerate(reversed(tb.revisions)):
        newest = idx == 0
        # The block-level drawn/checked/approved fields backfill the
        # newest row's signatories when that revision leaves them blank.
        by = rv.by or (tb.drawn_by if newest else "")
        chk = rv.checked or (tb.checked_by if newest else "")
        app = rv.approved or (tb.approved_by if newest else "")
        newest_first.append(rev_cells(
            [rv.rev, rv.date, rv.description, by, chk, app],
            where=f"revisions[{len(tb.revisions) - 1 - idx}]"))
    rev = RevGrid(x, y, _REV_W, h,
                  tuple((heading, cw) for heading, (_, cw, _a)
                        in zip(headings, _REV_COLS)),
                  _REV_ROW, header_y, list(reversed(newest_first)))

    parts: list[tuple] = []

    # Company / logo cell (middle) -------------------------------
    if tb.company:
        words, line, lines = tb.company.split(), "", []
        for wd in words:
            trial = (line + " " + wd).strip()
            if text_width(trial, _COMPANY_TYPE, bold=True) > _COMPANY_W - 10 and line:
                lines.append(line)
                line = wd
            else:
                line = trial
        if line:
            lines.append(line)
        cy = y + h / 2 - (len(lines) - 1) * 6
        for ln in lines:
            # A word too long for the cell has no break point the
            # wrapper may use: hyphenating a company name invents one,
            # so it is drawn whole and said out loud instead.
            parts.append(("text", rx + _COMPANY_W / 2, cy,
                          check_fit(ln, _COMPANY_W - 10, _COMPANY_TYPE, True,
                                    field="company", report=report),
                          _COMPANY_TYPE, "middle", True, "black"))
            cy += 12

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
    # title + subtitle, with sheet count tucked top-right of the title
    # band
    sheets = f"SHEET {tb.sheet} of {tb.of_sheets}"
    parts.append(("text", ix + 6, top + 15,
                  clip(tb.title or name, _TITLE_W, _TITLE_TYPE, True,
                       field="title", report=report),
                  _TITLE_TYPE, "start", True, "black"))
    if tb.subtitle:
        parts.append(("text", ix + 6, band2 - 6,
                      clip(tb.subtitle, _INFO_W - 12, _SUBTITLE_TYPE,
                           field="subtitle", report=report),
                      _SUBTITLE_TYPE, "start", False, "black"))
    parts.append(("text", x + w - 5, top + 11,
                  check_fit(sheets, _SHEET_W, _REV_TYPE, field="sheet",
                            report=report),
                  _REV_TYPE, "end", False, CAPTION_INK))
    # status (tiny label at cell top, value below)
    parts.append(("text", ix + 6, band2 + 8, "STATUS", _CAPTION,
                  "start", False, CAPTION_INK))
    parts.append(("text", ix + 6, band3 - 5,
                  clip(tb.status or "—", _INFO_W - 12, _VALUE_TYPE, True,
                       field="status", report=report),
                  _VALUE_TYPE, "start", True, "black"))
    # Bottom band: DRAWING No | SCALE | DATE | REV. Keeping the scale
    # with the number and the revision index is common drafting practice
    # rather than a standard: ISO 7200 §4 puts scale outside the title
    # block, and ASME title-block content is Y14.100's concern, not
    # Y14.1's. A sheet with no scale to state gives its room back to the
    # three cells that identify the drawing.
    rev_id = tb.revisions[-1].rev if tb.revisions else "0"
    scale = tb.scale or fit_scale
    cells: list[tuple[float, str, str, str]] = [
        (_INFO_W * 0.38, "DRAWING No", tb.drawing_number or "—", "drawing_number"),
        (_INFO_W * 0.21, "SCALE", scale, "scale"),
        (_INFO_W * 0.29, "DATE", date, "date"),
        (_INFO_W * 0.12, "REV", rev_id, "rev")] if scale else [
        (_INFO_W * 0.50, "DRAWING No", tb.drawing_number or "—", "drawing_number"),
        (_INFO_W * 0.30, "DATE", date, "date"),
        (_INFO_W * 0.20, "REV", rev_id, "rev")]
    cxr = ix
    for j, (seg_w, seg_label, seg_val, seg_field) in enumerate(cells):
        if j:
            parts.append(("rule", cxr, band3, cxr, bottom, _STRIP_HAIRLINE))
        bold = seg_label != "DATE"
        parts.append(("text", cxr + 5, band3 + 8, seg_label, _CAPTION,
                      "start", False, CAPTION_INK))
        parts.append(("text", cxr + 5, bottom - 5,
                      clip(seg_val, seg_w - 8, _VALUE_TYPE, bold,
                           field=seg_field, report=report),
                      _VALUE_TYPE, "start", bold, "black"))
        cxr += seg_w
    return Strip((x, y, w, h), rules, rev, parts)


def _strip_part(part) -> str:
    """One laid-out strip part, as SVG."""
    if part[0] == "rule":
        _, x1, y1, x2, y2, weight = part
        return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="black" stroke-width="{weight:g}"/>')
    _, tx, ty, text, size, anchor, bold, fill = part
    return _text(tx, ty, text, size, anchor=anchor, bold=bold, fill=fill)


def draw_title_strip(tb, name: str, date: str, right: float, bottom: float,
                     fit_scale: str = "", *,
                     report: "Reporter | None" = None) -> list[str]:
    """Draw the strip so its bottom-right corner sits at (right,
    bottom).

    The geometry is :func:`title_strip_layout`'s; this strokes it,
    exactly as :func:`zone_frame` strokes :func:`zone_layout`.
    """
    strip = title_strip_layout(tb, name, date, right, bottom, fit_scale,
                               report=report)
    x, y, w, h = strip.box
    L = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
         f'fill="white" stroke="black" stroke-width="{_STRIP_RULE:g}"/>']
    L += [_strip_part(part) for part in strip.rules]

    # The revision grid: the heading's own rule, then the column rules
    # the full depth of the strip, then the cells. No rule *between*
    # revisions -- the rows are told apart by their lettering, and
    # ruling each one would put six more lines into the busiest corner
    # of the sheet.
    g = strip.rev
    L.append(_strip_part(("rule", g.x, g.header_y, g.x + g.w, g.header_y, 1)))
    cx = g.x
    for _heading, cw in g.cols[:-1]:
        cx += cw
        L.append(_strip_part(("rule", cx, g.y, cx, g.y + g.h, _STRIP_HAIRLINE)))

    def rev_row(ry, vals, bold=False):
        cx = g.x
        for (_heading, cw), value in zip(g.cols, vals):
            L.append(_text(cx + _REV_PAD, ry + g.row_h - 4, value,
                           _REV_TYPE, bold=bold))
            cx += cw
    rev_row(g.header_y, [heading for heading, _cw in g.cols], bold=True)
    # Newest revision nearest the heading (bottom); oldest climbs the
    # stack.
    for idx, values in enumerate(reversed(g.rows)):
        rev_row(g.header_y - (idx + 1) * g.row_h, values)

    L += [_strip_part(part) for part in strip.parts]
    return L


# ----------------------------------------------------------------
# Zone-ruled drawing border (A.. top→down, 1.. left→right)
#
# The direction is ISO 5457 §4.4's: letters run top down and numerals
# left to right, so the grid's origin is the top-left corner. That is
# the whole of the reference's meaning -- ISO 15519-1 Clause 9 composes
# an address out of it (see :func:`pandid.document.location_reference`),
# and an address space that runs the other way names the wrong corner of
# the sheet.
#
# What is *not* ISO 5457 is the ruling. §4.4 fixes a 50 mm pitch and the
# field counts of its Table 2, and §4.3/§4.5 add centring and trimming
# marks. Neither is drawn here: the band is a constant in drawing units
# and the field count is chosen to suit the sheet. ISO 15519-1 §5.1.2,
# the clause that applies to a diagram, asks for the centring marks only
# on a document prepared for microfilming.
# ----------------------------------------------------------------

# Width of the lettered/numbered band between the drawing frame and the
# sheet border. A fixed-size sheet insets its frame by this to rule to
# the page edge.
ZONE_BAND = 16.0


def sheet_rect(ix: float, iy: float, iw: float, ih: float, band: float = ZONE_BAND
               ) -> tuple[float, float, float, float]:
    """The sheet rectangle around a drawing frame, ruled or not.

    An unruled sheet keeps the band as plain margin, so turning the
    border on and off leaves every piece of furniture exactly where it
    was.
    """
    return ix - band, iy - band, iw + 2 * band, ih + 2 * band


#: The size the zone letters and numerals are lettered at, and the drop
#: from the middle of the band to their baseline.
ZONE_TYPE, _ZONE_BASE = 9, 3


class Zoned(NamedTuple):
    """The zone-ruled border, as geometry rather than as ink.

    ``outer`` and ``inner`` are the sheet border and the drawing frame,
    each ``(x, y, w, h)``. ``parts`` is everything ruled in the band
    between them, in the order the sheet draws it: ``("rule", x1, y1,
    x2, y2)`` for a tick, and ``("label", x, y, text)`` for a letter or
    a numeral, stated at the point the glyph is *centred* on. The SVG
    sets a label ``text-anchor="middle"`` and drops the baseline by
    :data:`_ZONE_BASE`, which is that same point said the way SVG says
    it.

    One list rather than two, and in drawing order, since
    :func:`zone_frame` strokes it straight through.
    """
    outer: tuple[float, float, float, float]
    inner: tuple[float, float, float, float]
    parts: list[tuple]


def zone_layout(ix: float, iy: float, iw: float, ih: float,
                band: float = ZONE_BAND) -> Zoned:
    """Where every part of the zone-ruled border goes.

    The geometry of :func:`zone_frame`, with the drawing taken out of
    it, so the draw.io exporter rules the same border rather than a
    second opinion about one -- the same split :func:`dock` and
    :func:`~pandid.render.svg.stream_polyline` are already on the far
    side of.

    The field counts are the sheet's own and are chosen from its size (a
    zone about 165 units across, four to twelve columns and three to
    eight rows). They are *not* ISO 5457's fixed 50 mm pitch; see the
    note above :data:`ZONE_BAND`.
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
    # rows: letters A.. top→down, on the left and right bands. y grows
    # downwards here, so row 0 is the top band and takes the A.
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
    """Draw the drawing frame (inner rect) plus the sheet border (outer
    rect) with zone letters/numbers ruled in the band between them.

    (``ix``, ``iy``, ``iw``, ``ih``) is the inner drawing rectangle.
    Returns the SVG fragments and the outer sheet rectangle (x, y, w,
    h). The geometry is :func:`zone_layout`'s; this strokes it.
    """
    z = zone_layout(ix, iy, iw, ih, band)
    ox, oy, ow, oh = z.outer
    L = [f'<rect x="{ox:.1f}" y="{oy:.1f}" width="{ow:.1f}" height="{oh:.1f}" '
         f'fill="none" stroke="black" stroke-width="1"/>',
         f'<rect x="{ix:.1f}" y="{iy:.1f}" width="{iw:.1f}" height="{ih:.1f}" '
         f'fill="none" stroke="black" stroke-width="2"/>']
    for part in z.parts:
        if part[0] == "rule":
            _, x1, y1, x2, y2 = part
            L.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="black" stroke-width="0.75"/>')
        else:
            _, lx, ly, text = part
            L.append(_text(lx, ly + _ZONE_BASE, text, ZONE_TYPE,
                           anchor="middle", bold=True))
    return L, z.outer


# ----------------------------------------------------------------
# The sheet dock: which rectangle each piece of furniture is given
# ----------------------------------------------------------------

# Clearance between the drawing and the frame it is framed by; between
# two boxes stacked in one corner; and between a left-hand and a
# right-hand stack sharing a band. The last is what stops a wide
# equipment list and a wide legend being ruled as though they could be
# laid end to end.
INNER, GAP, SEP = 26.0, 14.0, 18.0

#: Margin outside the sheet border. A fixed page insets its frame by
#: this plus the zone band, so the border rules to the paper edge
#: whether or not the zones are lettered.
OUTER_MARGIN = 8.0


class Docked(NamedTuple):
    """One piece of furniture and the rectangle the sheet gives it."""
    obj: object
    x: float
    y: float
    w: float
    h: float


def dock(items, inner, *, sheet=None, too_small=None):
    """Where each piece of sheet furniture lands, and the frame it lands
    on.

    **This is the placement, and nothing here draws.** Both backends
    have the same boxes to place, so both ask this rather than deriving
    it twice.

    Nothing about the arithmetic is SVG's. A box is measured from its
    own text (:func:`measure_annotation`, :func:`measure_table`, and
    :func:`measure_title_strip`, all of which are already pure), grouped
    into an edge *band* by its ``align``, and placed flush against the
    frame edge that band names. The frame either grows out of the
    drawing far enough to hold the bands, or -- given a *sheet* -- is
    the fixed page inset by the border, with the drawing fitted into
    whatever the bands leave.

    ``items`` are ``(obj, align, w, h)``. ``obj`` is opaque: its
    ``margin`` and ``position`` are read off it where it has them, so a
    caller may pass a sentinel for a piece of furniture that is not one
    of the caller's objects (the title strip, the stream table) and have
    the band maths size the frame around it too. ``inner`` is the
    drawing's own bounding box ``(x0, y0, x1, y1)``.

    ``sheet`` is a fixed page, or None to grow the frame to the drawing.
    ``too_small`` is called with ``(need_w, need_h, culprit)`` when a
    fixed page cannot hold its own furniture and must return the
    exception to raise; the caller supplies it because naming
    ``culprit`` in words is the caller's vocabulary, not this module's.

    Returns ``(placed, frame, free)``: the list of :class:`Docked`
    rectangles in the order the sheet draws them, the frame rectangle
    ``(x, y, w, h)``, and the region a fixed page leaves for the drawing
    (None when the frame was grown to the drawing, which needs no
    fitting).
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
        return sum(h for _, _, h in entries) + GAP * max(0, len(entries) - 1)

    def stack_w(entries):
        return max((w for _, w, _ in entries), default=0.0)

    def biggest(dim: int):
        """The largest piece of furniture along ``dim`` (1 = width, 2 =
        height), for an error that has to say which piece will not fit
        rather than that something will not.
        """
        entries = [it for col in cols.values() for it in col]
        return max(entries, key=lambda it: it[dim])[0] if entries else None

    # band thicknesses -------------------------------------------
    top_h = max(stack_h(cols["top-left"]), stack_h(cols["top"]),
                stack_h(cols["top-right"]))
    bottom_h = max(stack_h(cols["bottom-left"]), stack_h(cols["bottom"]),
                   stack_h(cols["bottom-right"]))
    left_w, right_w = stack_w(cols["left"]), stack_w(cols["right"])

    def row_w(lk, ck, rk):
        lw, cw, rw = stack_w(cols[lk]), stack_w(cols[ck]), stack_w(cols[rk])
        side = (lw + SEP + rw) if (lw and rw) else max(lw, rw)
        return max(side, cw)

    band_w = max(row_w("top-left", "top", "top-right"),
                 row_w("bottom-left", "bottom", "bottom-right"))

    # frame rectangle --------------------------------------------
    if sheet is not None:
        # A named page fixes the frame: the sheet inset by the zone band
        # and the margin outside it, so the border rules to the sheet
        # edges and the zone count does not drift with the drawing.
        edge = OUTER_MARGIN + ZONE_BAND
        need_w = max(band_w, left_w + right_w + 2 * INNER)
        need_h = max(top_h + bottom_h + 2 * INNER,
                     stack_h(cols["left"]), stack_h(cols["right"]))
        too_wide = need_w >= sheet.width - 2 * edge
        if too_wide or need_h >= sheet.height - 2 * edge:
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

    # The bands are measured, so the region left for the drawing is
    # settled and so is the ratio it will be placed at. A frame grown to
    # the drawing has no fixed page and so nothing to fit into.
    free = None if sheet is None else (
        ix + left_w + INNER, iy + top_h + INNER,
        iw - left_w - right_w - 2 * INNER, ih - top_h - bottom_h - 2 * INNER)

    # place each column flush to the frame -----------------------
    placed: list[Docked] = []

    def x_for(mode, w, m):
        if mode == "l":
            return ix + m
        if mode == "r":
            return ixr - m - w
        return ix + (iw - w) / 2  # centred on the frame

    def put_top(entries, mode):     # flush to the top edge, grow downward
        y = iy
        for obj, w, h in entries:
            m = getattr(obj, "margin", 0.0)
            placed.append(Docked(obj, x_for(mode, w, m), y + m, w, h))
            y += m + h + GAP

    def put_bottom(entries, mode):  # flush to the bottom edge, grow upward
        y = iyb
        for obj, w, h in reversed(entries):
            m = getattr(obj, "margin", 0.0)
            top = y - m - h
            placed.append(Docked(obj, x_for(mode, w, m), top, w, h))
            y = top - GAP

    def put_side(entries, mode):    # flush to a side edge, vertically centred
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
