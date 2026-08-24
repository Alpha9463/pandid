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

import dataclasses
import math
import string
import unicodedata
from typing import Any, Callable, NamedTuple

from pandid.render.escape import escaped

# Rough advance width of the sans-serif the renderer uses, as a fraction
# of the font size. Slightly generous so auto-sized boxes never clip
# their text.
_ADV = 0.56
_ADV_BOLD = 0.62

FONT = "sans-serif"

# How a cell says it could not hold what it was given: the field it
# draws, the text it was asked for, the text it actually drew (the same
# string when nothing was trimmed), the room the cell has and the width
# the text needed, the last two in drawing units. An ellipsis tells
# whoever reads the sheet that a value was abbreviated and tells the
# program that supplied it nothing at all, and that program is the one
# that can shorten the field or ask for a bigger sheet. Every
# fixed-width cell here measures first and reports through one of these.
#
# The two widths are carried because a finding without them is not
# actionable: "the title was truncated" leaves an author guessing how
# much has to come out, and "needs 194 of the 187 units its cell has"
# says it. ``route-detour`` states its two lengths and their ratio for
# the same reason.
#
# **The field is the one the author edits, not the cell that drew it**,
# and where the two differ it is spelled ``source -> cell``. Half the
# strip's cells draw a value some *other* field supplied: a blank
# ``title`` draws the flowsheet's name, a blank ``scale`` draws the
# ratio the sheet was fitted at, a blank ``date`` draws today's, the REV
# cell draws the newest revision's ``rev``, and the newest revision's
# blank signatory cells draw the block's ``drawn_by``/``checked_by``/
# ``approved_by``. Naming the cell in those cases sends the author to a
# field they never set -- the mistake ``of_sheets`` reported as ``sheet``
# was, one function away.
Reporter = Callable[[str, str, str, float, float], None]


def script_counts(s: str) -> "tuple[int, int, int]":
    """How many of *s*'s codepoints draw narrow, draw a full em wide, or
    draw nothing of their own -- the one classification every width
    estimate in the renderer measures a string by, so a CJK tag and a
    combining mark are never charged the Latin rate that only ``_ADV``
    was ever measured against.

    :func:`unicodedata.east_asian_width` sorts a codepoint into five
    classes. *W*ide and *F*ullwidth -- CJK ideographs, fullwidth forms --
    draw close to a full em, same as the font's own point size. *H*alfwidth
    and *Na*rrow -- Latin letters, digits, halfwidth kana -- draw at the
    fraction ``_ADV``/``_ADV_BOLD`` was measured against a real PDF at
    (see :func:`text_width`). *A*mbiguous -- Greek, Cyrillic, most
    symbols, a character that is narrow set among Latin and wide set
    among CJK -- has no surrounding text here to decide it by, so it
    takes the standard's own default for that case (UAX #11, East Asian
    Width, section "Recommendations"): "In the absence of context,
    Ambiguous characters should be treated as Narrow." This renderer
    never knows whether a string sits in a CJK line or a Latin one, so
    the no-context default is the only defensible reading, and it is
    also the one that leaves every shipped, Latin-tagged sheet exactly
    where it was.

    A combining mark -- general category ``Mn`` (nonspacing) or ``Me``
    (enclosing) -- draws on top of the glyph before it rather than
    beside it, so it advances nothing of its own. Charged a full
    narrow glyph, it is the same bug this function exists to fix, just
    pointed at an accent instead of an ideograph: a string reading
    shorter than what it measures.
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
    """Estimated drawn width of *s* set at *size*, without padding.

    ``_ADV``/``_ADV_BOLD`` are measured against a real PDF rendering of
    this renderer's Latin lettering (see the module's callers) and are
    accurate to within a few percent -- good enough that a
    codepoint-only count (``len(s) * size * _ADV``) is exactly what a
    Latin, digit or punctuation string still gets, unchanged, below.
    A wide (CJK/fullwidth) codepoint is charged a full em instead, and
    a combining mark nothing at all; see :func:`script_counts`.
    """
    s = str(s)
    adv = _ADV_BOLD if bold else _ADV
    narrow, wide, zero = script_counts(s)
    if not wide and not zero:
        return len(s) * size * adv
    return _width(narrow, wide, size, adv)


def _width(narrow: int, wide: int, size: float, adv: float) -> float:
    """What *narrow* narrow and *wide* wide codepoints measure, set at
    *size* with advance fraction *adv*.

    One expression with two callers: :func:`text_width`, which measures
    a whole string, and :func:`clip`, which walks the counts forward to
    find where to cut one. Written down once because the two have to
    agree *bit for bit* -- a cut computed by summing per-character
    widths lands a rounding away from the same string measured whole,
    which is :func:`_total`'s complaint about ``sum()`` pointed at a
    different pair of numbers. Given the same counts this returns the
    same float, so the prefix ``clip`` keeps is a prefix ``text_width``
    agrees fits.
    """
    return narrow * size * adv + wide * size


def _total(values) -> float:
    """The sum of *values*, added left to right by hand rather than
    through the builtin ``sum()``.

    A box measured this way (its total width or height) is later
    subtracted from a frame edge to place the box, and each of its own
    pieces -- a column centred at half its width, an entry stacked at
    half a run's height -- is positioned by walking the same values
    forward with plain ``+=``. ``sum()``'s float algorithm changed in
    CPython 3.12 (Neumaier-compensated, gh-100425): more accurate, and
    a different last bit from a plain running total on the same
    values. The measurement and the walk have to agree on that bit or
    a centring formatted to one decimal place lands on a rounding tie
    that falls one way on 3.11 and the other on 3.12+ -- the same
    values, drawn 0,1 unit apart depending only on which Python drew
    them. Adding by hand, the one way every version of Python always
    has, is what keeps a box's measured extent and its own drawing
    from ever disagreeing about it.
    """
    total = 0.0
    for v in values:
        total += v
    return total


def clip(s, room: float, size: float, bold: bool = False, *,
         field: str = "", report: "Reporter | None" = None) -> str:
    """Trim a value to the room its cell has, and report what was cut.

    A title-block cell is ruled and the strip is fixed geometry, so a
    value longer than its cell would run across the rule and into the
    value beside it and no amount of growing can help. A draftsman
    abbreviates.

    **How many characters survive is decided the way the width is
    measured** -- and :func:`text_width` measures two ways, so this cuts
    two ways, on the same test.

    A string of narrow codepoints alone measures ``len(s) * size * adv``,
    a closed form, and the cut is that form inverted: the count of
    characters the room holds, less one for the ellipsis. Every sheet
    this package has drawn was cut by that arithmetic, and it is exact
    -- one division, no accumulated error -- so a value that fills its
    cell to the last unit keeps the last character that fits.

    Anything with a CJK or fullwidth codepoint in it (a full em) or a
    combining mark (nothing at all) has no such closed form, and there
    the counts are walked forward through :func:`_width` -- the same
    expression, given the same counts, so the prefix kept is a prefix
    ``text_width`` agrees fits.

    **Both ends used to be the Latin one.** The cut counted characters
    at the Latin advance while the decision to cut at all was
    ``text_width``'s, so the two disagreed by the ratio between the two
    rates: a fullwidth title kept 28 characters measuring 290 units for
    a 187-unit cell and was drawn straight through the sheet count
    beside it, on every page size. Making *both* ends walk was the
    obvious repair and the wrong one -- summing per-character widths
    lands a rounding away from the same characters measured whole, so
    seventy Latin room/size pairs in a sweep of the strip's own type
    sizes cut a character earlier or later than they always had. That is
    :func:`_total`'s complaint, and the answer here is the same one:
    measure and use the identical arithmetic.
    """
    s = str(s)
    need = text_width(s, size, bold)
    if need <= room:
        return s
    adv = _ADV_BOLD if bold else _ADV
    _narrow, wide, zero = script_counts(s)
    if not wide and not zero:
        keep = max(0, int(room / (size * adv)) - 1)
    else:
        budget, keep, n, w = room - text_width("…", size, bold), 0, 0, 0
        for ch in s:
            dn, dw, _dz = script_counts(ch)
            n, w = n + dn, w + dw
            if _width(n, w, size, adv) > budget:
                break
            keep += 1
    drawn = s[:keep].rstrip() + "…"
    if report is not None:
        report(field, s, drawn, room, need)
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
    need = text_width(s, size, bold)
    if report is not None and need > room:
        report(field, s, s, room, need)
    return s


def report_once(report: "Reporter") -> "Reporter":
    """*report*, with each distinct finding passed on only once.

    One strip can put one value in more than one place. The company cell
    stacks its name over several lines, so a name repeating a word too
    wide to break -- a group of companies, a joint venture -- reported
    that word once per line, and the author read two findings about one
    thing they can do once.

    Wrapped around the whole layout rather than at each of the three
    places findings are collected (the two backends and
    :func:`title_strip_fit`), because three de-duplications are three
    chances to disagree about what counts as the same finding. The key
    is the whole tuple, so two revisions that abbreviate the same
    initials are still two findings: their fields differ, and they are
    two rows the author edits separately.
    """
    seen: set[tuple[str, str, str, float, float]] = set()

    def once(field: str, text: str, drawn: str,
             room: float, need: float) -> None:
        key = (field, text, drawn, room, need)
        if key not in seen:
            seen.add(key)
            report(field, text, drawn, room, need)

    return once


def fit_size(s, room: float, size: float, floor: float,
             bold: bool = False) -> float:
    """The largest type size at or under *size* that draws *s* inside
    *room*, and never under *floor*.

    The third answer to a value too long for its cell, and the only one
    that keeps all of it and stays inside the rule. Lettering a long
    value smaller is what a draughtsman does to a value that is *read*
    -- the drawing title, set in display type well above everything else
    on the strip. It is not what they do to a drawing number or a date,
    which are matched character by character against another document
    and are set at the strip's own reading size already, with nothing to
    give back. So this is offered rather than applied: the caller says
    which cell has size to spare and what its floor is, and the cells
    that have none never ask.

    :func:`text_width` is linear in the size, so the size that exactly
    fills the cell is ``size * room / need``. That is rounded *down* to
    the tenth :func:`_text` writes into the file, so the size measured
    here is the size the consumer sets and the fit is not a rounding
    away from a clipped glyph.
    """
    need = text_width(s, size, bold)
    if need <= room or need <= 0 or room <= 0:
        return size
    return max(floor, math.floor(size * room / need * 10) / 10)


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

#: The three weights the **sheet's own border** is ruled at: the outer sheet
#: rectangle, the drawing frame inside it, and the ticks that divide the band
#: between the two into zones.
#:
#: Sheet furniture, and so *not* on :class:`~pandid.render.weights.LineWeight`:
#: ISO 10628-1 5.3.1 rules the flow diagram, and a border and its zone grid are
#: the drawing sheet rather than anything drawn on it. Named here all the same,
#: because both backends rule them and each used to write its own literal --
#: this module for the sheet and ``pandid.render.drawio`` for the export -- so
#: the border was three numbers stated twice with nothing holding the pairs
#: together.
SHEET_RULE = 1.0
FRAME_RULE = 2.0
ZONE_TICK = 0.75


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
    body_w = _total(col_w) + gap * (len(col_w) - 1)
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
        body_w = _total(col_w) + gap * (len(col_w) - 1)
        inner = max(body_w, text_width(ann.title, size + 1, bold=True))
        if ann.width < inner + 2 * pad:
            over = _overflowing_text(ann, size, body_w)
            # The box's own ``width`` is the room and the width it would
            # have measured to is the need, so the two numbers in the
            # finding are the two numbers the author edits between.
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
    return _total(col_w), title_h + nrows * row_h


def draw_table(tb, x: float, y: float) -> list[str]:
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

#: The type size a table of up to 18 columns is set at, and the size the
#: row depth below and both column-width floors
#: (:class:`~pandid.document.StreamTableOptions`) were chosen against. An
#: author who states a size states it as a multiple of this one, which is
#: what makes the three follow it; see :func:`stream_table_layout`.
_BASE_SIZE = 10.5

#: Depth of every row at :data:`_BASE_SIZE`.
_ROW_H = 20.0


def _width_floor(stated: float | str, name: str, ruled: float) -> float:
    """Narrowest one of the table's two kinds of column is ruled, in
    drawing units, from what the sheet asked for.

    The floors used to be constants here, 122.0 and 52.0 at
    :data:`_BASE_SIZE`. They are
    :class:`~pandid.document.StreamTableOptions` fields now and those
    two numbers are their defaults, which is where a default has to live
    once a value can be stated: a floor that scaled with ``font_size``
    only while it held its own default would be a field an author cannot
    reason about.

    So a number is scaled by ``ruled`` for the reason :data:`_ROW_H` is,
    stated or not. ``"auto"`` is no floor at all, which is a floor of
    zero: every column is measured from its contents anyway (see
    :func:`stream_table_layout`) and a floor only ever holds one *up*,
    so dropping it needs no second path through the measuring and cannot
    rule a column narrower than what goes in it.
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
    """This sheet's :class:`~pandid.document.StreamTableOptions`.

    Through ``getattr``, as :attr:`stream_table_sections` is read: every
    :class:`~pandid.flowsheet.Flowsheet` has one, and this module is
    handed whatever the renderer was handed.
    """
    from pandid.document import StreamTableOptions
    options = getattr(fs, "stream_table", None)
    return StreamTableOptions() if options is None else options


#: A :attr:`~pandid.flowsheet.Flowsheet.stream_table_sections` key that
#: matched no property row. Unlike ``label_pos`` or ``col_align``, this
#: cannot be checked when the author sets it -- the streams it is
#: checked against may not exist yet -- so it is a render-time warning
#: rather than a constructor-time raise.
_UNUSED_SECTION_CODE = "stream-table-section-unused"


def _report_unused_sections(fs, sec_before: dict[str, str], seen: set) -> None:
    """Warn on ``fs.warnings`` for a section keyed to a property no
    stream in the table sets, so it silently never heads anything.

    Filtered and replaced rather than appended to, exactly as
    :data:`~pandid.render.svg._FIT_CODES` is: a section named on an
    earlier render that a later one has fixed must stop being warned
    about.
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


class _Measured(NamedTuple):
    """What the stream table measures to, before it is a grid of cells.

    The split exists because the table is now laid out two ways from one
    measurement: whole, docked at the foot of a diagram
    (:func:`stream_table_layout`), and cut into blocks on a sheet of its
    own (:func:`stream_table_sheet`). Every number here is settled over
    the *whole* table -- one type size, one row depth, one width for
    every stream column -- so a table read across two blocks is read
    across one ruling.

    ``span`` is what a section heading needs, which is a constraint on
    the total width rather than on any column, so it is carried
    unresolved: how much of it the label column has to take up depends
    on how many stream columns stand beside it, and that is the one
    thing the two layouts disagree about. See :func:`_section_span`.
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
    """The label column's width once a section heading has to fit over
    *columns* stream columns beside it.

    A section header spans the whole table, so it is the total width it
    constrains rather than any one column; the row label column is the
    only one free to take up the slack.
    """
    return max(m.label_w, m.span - m.name_w * columns)


def _stream_rows(m: "_Measured", streams: list, cells: list,
                 label_w: float) -> list[list[StreamCell]]:
    """The table's cells, row by row, for the *streams* given.

    The whole table passes all of them and a block of a table sheet
    passes its own slice, which is what makes each block carry the
    heading row again: the row is built here, from whatever columns this
    block has, rather than being copied off a table that was built once.
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
    """One ruled table over the columns given: the whole thing, or one
    block of a table sheet."""
    rows = _stream_rows(m, streams, cells, label_w)
    return StreamTable(rows, m.size, m.row_h,
                       label_w + m.name_w * len(streams),
                       m.row_h * len(rows))


def stream_table_layout(fs) -> "StreamTable | None":
    """Where every cell of the stream table goes and what is in it, or
    ``None`` for a flowsheet with nothing to tabulate.

    The table is measured from its own contents and placed at whatever
    it comes to -- the sheet is grown around it, or a page too small for
    it is refused -- so unlike a title-block cell there is no fixed room
    here to abbreviate into. A stream table that cannot show ``0.0441
    kg/kg total`` is not a stream table.

    This is the table drawn **on** a diagram, in one block, however wide
    that comes to. :func:`stream_table_sheet` is the same table given a
    sheet of its own, where the page it has to fit is known and the
    columns are cut into blocks against it.
    """
    m = _measure(fs)
    if m is None:
        return None
    return _stream_table(m, m.streams, m.cells,
                         _section_span(m, len(m.streams)))


def _measure(fs, *, own_sheet: bool = False) -> "_Measured | None":
    """Measure the table, or ``None`` for a flowsheet with nothing to
    tabulate.

    Nothing to tabulate is answered twice, and the second is the one
    that matters: no stream gets a column (:func:`_table_streams`), or
    no stream states a property, which leaves the columns that did get
    one with no row to fill. Both are a grid of headings over nothing,
    and a heading is not a stream table either.

    ``own_sheet`` says the table is the body of a sheet of its own
    rather than a block docked at the foot of a diagram, which changes
    one thing and only one: the type size nobody stated. See below.
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
        # A table on its own sheet has nothing to shrink *for*. The rule
        # below trades type size for width because a table drawn beside
        # a diagram has one row of columns and no way to make more room;
        # a table sheet makes room by wrapping, so shrinking as well
        # would letter a twenty-column sheet at 8 units to fit a page it
        # already fits. The author's own `font_size` still rules, and is
        # how a table too *deep* for its page is brought back onto it.
        #
        # **Whether or not a page was named**, which is why this reads
        # `own_sheet` and not "did it wrap". A sheet grown to its
        # contents does not wrap -- there is no width to wrap against --
        # but sizing it off the column count instead would letter the
        # same twenty-one streams at 9.05 unpaged and 10.5 on A2: two
        # different drawings of one table, differing for a reason
        # nothing on either sheet shows. One rule for the sheet, and the
        # page decides how it is cut up rather than how it is lettered.
        size, row_h, ruled = _BASE_SIZE, _ROW_H, 1.0
    elif asked is None:
        # As it always was: 10.5 while the columns fit, then shrunk so
        # that a long value still sits inside a column already at its
        # minimum width. That last clause is why the minimums do not
        # shrink with it -- shrinking them would rule a 55-column table
        # too narrow to track a row across, which is the failure they
        # were put there to prevent.
        size = _BASE_SIZE if n <= 18 else max(8.0, 190.0 / n)
        row_h = _ROW_H if n <= 18 else max(15.0, size + 5)
        ruled = 1.0
    else:
        # A size the author stated is the author overruling that
        # judgement, for a sheet that has to fit a given page. So it
        # rules the table and not only its lettering: the row height and
        # both minimum widths are taken as multiples of _BASE_SIZE and
        # follow it down. Setting only the glyphs would leave the table
        # its whole footprint and the feature would do nothing at all
        # for the sheet that needed it -- every column of a table of
        # short names and short values is at its floor.
        #
        # Everything else already followed: each column is measured from
        # `text_width(..., size)` and only *held up* by a floor.
        # _STREAM_GUTTER and _STREAM_PAD do not scale and are not meant
        # to. They are the clearance between a rule and a glyph, which
        # is about the eye and the printer rather than about the type,
        # and the draw.io exporter states the pad as a cell inset of its
        # own.
        size = asked
        ruled = size / _BASE_SIZE
        row_h = _ROW_H * ruled
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

    # Every column is sized to what goes in it, and held up to a floor
    # the sheet may lower or drop (`fs.stream_table.label_width` /
    # `.column_width`). The floor's default keeps a table of
    # two-character names and three-figure values from being ruled too
    # narrow to read across; dropping it is the author saying this table
    # is not that one.
    labels = [heading] + [key for kind, key in disp if kind == "data"]
    label_w = max(_width_floor(options.label_width, "label_width", ruled),
                  max(text_width(t, size, bold=True)
                      for t in labels) + _STREAM_GUTTER)
    values = [_stream_cell_text(c, key) for kind, key in disp if kind == "data"
              for c in cells]
    # One width for every stream column, measured over every heading and
    # every value in the table. That is not a shortcut and it does not
    # relax when the floor is dropped: a stream table is read down for
    # one stream and across for one property, so columns that did not
    # line up would be a worse drawing than wide ones. It also settles
    # the only way a column could be ruled narrower than its own
    # heading -- the headings are in the same measurement as the values.
    name_w = max(_width_floor(options.column_width, "column_width", ruled),
                 max((text_width(s.name, size, bold=True) for s in streams),
                     default=0.0) + _STREAM_GUTTER,
                 max((text_width(v, size) for v in values), default=0.0)
                 + _STREAM_GUTTER)
    # What a section header needs, left unresolved: it spans the whole
    # table, so it is the total width it constrains rather than any one
    # column, and how much of that the label column has to take up
    # depends on how many stream columns stand beside it. See
    # :func:`_section_span`.
    sections = [label for kind, label in disp if kind == "section"]
    span = max((text_width(t, size, bold=True) for t in sections),
               default=0.0) + _STREAM_GUTTER
    return _Measured(streams, cells, disp, heading, size, row_h,
                     label_w, name_w, span)


#: How many rows deep the white space between two blocks of a table
#: sheet is. One row rather than a fixed number of units, so the gap
#: follows the type: a table sized down to fit its page does not keep a
#: gap ruled for lettering half again as big.
_BLOCK_ROWS = 1.0


class TableSheet(NamedTuple):
    """The stream table as the body of a sheet of its own: the same
    table, cut into blocks stacked one above the other.

    ``w`` is the widest block and ``h`` the whole stack, gaps included,
    which is what the sheet is sized against. The blocks are drawn
    flush left with one another rather than each centred on its own
    width: a reader tracks a property row from one block to the next
    down the left-hand column, and a ragged left edge is what stops
    them. See :meth:`at`.
    """
    blocks: list
    gap: float
    w: float
    h: float

    def at(self, left: float, top: float):
        """Each block with the corner it is drawn from, given the corner
        the stack is drawn from. Both backends place blocks through
        this, so neither owns the stacking."""
        y = top
        for i, block in enumerate(self.blocks):
            yield i, block, left, y
            y += block.h + self.gap


def _blocks_of(n: int, count: int) -> list:
    """*n* columns shared out over *count* blocks, as evenly as they go.

    The blocks come out one column apart at worst -- twenty-one over
    three is 7/7/7 and over two is 11/10 -- because two blocks of nearly
    a page each read as one table where a full block beside a stub of
    three reads as an afterthought.
    """
    per = (n + count - 1) // count
    return [list(range(i, min(i + per, n))) for i in range(0, n, per)]


def _partition(m: "_Measured", n: int, room: "float | None") -> list:
    """How the stream columns are cut into blocks for a page *room* units
    wide, or one block for a sheet with no page to fit.

    **Measured on the width the blocks are actually ruled at**, which is
    the whole of this function's reason for being separate. A block is
    as wide as its stream columns *plus the label column*, and the label
    column is widened to carry a section heading across the narrowest
    block (:func:`_section_span`) -- so the width cannot be known until
    the partition is chosen, and a capacity worked out before the
    widening is a capacity the finished table can exceed.

    That is not hypothetical: twenty-one streams under a long section
    heading were cut 11/10 from a capacity of eleven, then ruled 1023.0
    wide on the 1022.5 an A4 sheet has, and the page was reported too
    small for a table that fits it three blocks of seven at 971.0. The
    sheet was refused for not fitting when a partition that fits
    existed, which is the feature failing at its job rather than a
    bookkeeping slip.

    So the count is searched rather than divided out: the **fewest**
    blocks whose ruled width fits, fewest because fewer blocks are wider
    blocks and a shorter sheet, and every count is asked with the width
    it would really be drawn at. Where no section heading widens
    anything the answer is arithmetically identical to the division it
    replaces, so no sheet that fitted before moves.

    A table that fits at no count at all falls back to one column per
    block, the narrowest a table can be ruled: it is then a page too
    small however it is cut, which the sheet reports in those words
    rather than this function guessing at.
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
    """The stream table laid out for a sheet of its own, wrapped into as
    many blocks as *room* units of page width takes.

    ``room`` is the width the sheet has for the table, or ``None`` for a
    sheet with no fixed page, which has no width to wrap against and
    takes the table in one block. **The count comes from the page and
    never from a constant**: how many streams fit across is a fact about
    this table's columns on this paper, and a fixed "twelve per block"
    would wrap a sheet that did not need it and overrun one that did.

    The *ruling* does not depend on the page in the same way. Type size,
    row depth and column widths are the sheet's own whether or not one
    was named (:func:`_measure`), so an unpaged table sheet is the paged
    one with the cutting left out.

    The columns are then shared out **evenly** rather than filled to the
    brim and left with a remainder: twenty-one streams that fit twelve
    across come out as eleven and ten, not twelve and nine, because two
    blocks of nearly a page each read as one table and a stub of three
    columns reads as an afterthought.

    Every block carries the heading row again (:func:`_stream_rows`),
    and every block is ruled to one measurement -- one type size, one
    row depth, one stream-column width, one label column -- so the
    second block is read exactly as the first.

    Returns ``None`` for a flowsheet with nothing to tabulate, the same
    answer :func:`stream_table_layout` gives and for the same reasons.
    """
    m = _measure(fs, own_sheet=True)
    if m is None:
        return None
    n = len(m.streams)
    chunks = _partition(m, n, room)
    # The label column is widened for a section heading against the
    # *smallest* block, so the heading fits in every block and one
    # ruling still answers for all of them.
    label_w = _section_span(m, min(len(c) for c in chunks))
    blocks = [_stream_table(m, [m.streams[i] for i in c],
                            [m.cells[i] for i in c], label_w)
              for c in chunks]
    gap = m.row_h * _BLOCK_ROWS
    return TableSheet(blocks, gap, max(b.w for b in blocks),
                      _total(b.h for b in blocks) + gap * (len(blocks) - 1))


def table_sheet_origin(table: TableSheet, free) -> "tuple[float, float]":
    """The corner the block stack is drawn from, given the region a
    fixed page left for it (``None`` for a sheet grown to its contents,
    which starts the stack at the origin the frame was grown around).

    Centred across the page and hard against the top of it. Centred
    because a table is the whole body of this sheet and a body hugging
    one margin reads as a drawing that lost its left half; at the top
    because a table is read from its first row down, and floating the
    stack in the middle of the page puts a gap between the frame and
    the heading that a reader takes for a missing block.
    """
    if free is None:
        return (0.0, 0.0)
    fx, fy, fw, _fh = free
    return (fx + (fw - table.w) / 2, fy)


def draw_stream_table(table: StreamTable, left: float, top: float, *,
                      group: str = "stream_table") -> list[str]:
    """Draw the table with its top-left corner at (``left``, ``top``).

    The geometry is :func:`stream_table_layout`'s; this strokes it,
    exactly as :func:`draw_title_strip` strokes
    :func:`title_strip_layout`. Every cell is ruled on all four sides --
    a stream table really is a grid, read across for one property and
    down for one stream -- at the weight a grid beside a drawing is
    ruled at rather than the weight a box around one is.

    ``group`` names the group the cells go in. A sheet carrying blocks
    of one table has to number them: two elements under one id is not a
    document, and the id is how a reader of the file finds the table.
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
#: Which block-level field fills a revision column the newest row leaves
#: blank. Those three columns are the only place on the sheet the strip
#: letters a signatory, so a block-level name is drawn there or nowhere;
#: :func:`pandid.validate.model_issues` reads this table to say which of
#: the three the sheet is dropping and why.
_BACKFILL = {"by": "drawn_by", "checked": "checked_by",
             "approved": "approved_by"}
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


#: Baseline-to-baseline spacing of the company cell's wrapped lines.
_COMPANY_LEAD = 12.0


def _field(obj, name: str) -> str:
    """A title-block field as the strip reads it: what the author
    stated, stripped, and blank only where they stated nothing.

    A field of nothing but spaces is *truthy*, so it defeated every
    fallback the block has. ``tb.title or name`` drew three spaces
    instead of the flowsheet's name; ``tb.status or "\u2014"`` and the
    drawing number's dash likewise; a whitespace ``client`` or
    ``project`` ruled an empty row and made the whole strip taller; a
    whitespace ``scale`` turned the four-cell bottom band on with
    nothing to put in it; and a whitespace ``company`` was accepted,
    wrapped to no lines and drawn nowhere. Six of the block's fields
    answered differently from the blank they mean, and none of them said
    so -- the same class of silent wrong answer as the rest of this
    strip, arrived at through truthiness rather than through width.

    Read *here* and not normalised on the dataclass because a block is
    edited after it is built -- ``fs.title_block.title = ...`` is the
    documented way to shorten a field and re-render -- and a
    ``__post_init__`` sees only what it was constructed with. Reading
    through one function also keeps :func:`measure_title_strip` and
    :func:`title_strip_layout` from disagreeing about whether a row
    exists, which is what would make the strip's own height wrong.

    This answers *what the author stated*, which is what decides which
    field a finding names and whether a signatory is the block's to
    backfill. What a cell **draws** is :func:`_stated`, one layer up:
    the same read, with the block's own default behind it.

    **Unset, not falsey.** The question this asks is whether the author
    put anything in the field, and truthiness only answers that for
    strings. Every field here is annotated ``str`` and nothing enforces
    it, so ``TitleBlock(sheet=1, of_sheets=3)`` is a perfectly ordinary
    thing to type and has always worked -- ``str(1)`` is ``"1"``. But
    ``sheet=0`` is falsey, so a truthy read discarded it as blank, and
    then :func:`_stated` filled the cell with the field's default: an
    author who stated sheet **0** was issued sheet **1**. That is this
    module's own subject committed by the code meant to fix it -- a
    stated value silently changed to a different stated value, which is
    worse than the blank it was guarding, because blank at least meant
    *unset*.

    So the test is ``is None`` and everything else is drawn as written.
    Refusing a non-string at the door was the other defensible answer
    and is not the one taken: it would break ``sheet=1``, which reads
    naturally, works today, and has nothing to do with the defect.

    :func:`pandid.document._clean` strips a location reference's parts
    for the reason this strips a drawing field: whitespace at the ends
    of either has nothing it could draw.
    """
    value = getattr(obj, name, None)
    return "" if value is None else str(value).strip()


#: :func:`_class_defaults` per class, since the answer is a property of
#: the class and the question is asked once per cell per render.
_DEFAULTS: "dict[type, dict[str, str]]" = {}


def _class_defaults(cls: "type[Any]") -> "dict[str, str]":
    """Every plain-string default the dataclass *cls* states, by field
    name. A field built by a factory (``revisions``) has no such default
    and is not listed, which is how the block's one list field leaves
    itself out without being named here.

    A class that is not a dataclass at all states nothing, for
    :func:`_field`'s reason: the strip reads whatever it is handed and
    draws a blank where there is nothing to draw, rather than raising
    over the shape of the object.
    """
    known = _DEFAULTS.get(cls)
    if known is None:
        known = _DEFAULTS[cls] = (
            {f.name: f.default for f in dataclasses.fields(cls)
             if isinstance(f.default, str)}
            if dataclasses.is_dataclass(cls) else {})
    return known


def _stated(obj, name: str) -> str:
    """The value a strip cell **draws** for a field: what the author
    wrote (:func:`_field`), and where that is blank, the default the
    field's own dataclass states for it.

    Every field of :class:`~pandid.document.TitleBlock` defaults to the
    empty string bar two. ``sheet`` and ``of_sheets`` default to
    ``"1"``, because a drawing with no set behind it is sheet 1 of 1 and
    the block says so in its own signature. Left blank they drew
    ``SHEET  of 1`` -- and a count with half of it missing is what the
    slot's own note calls *a different sheet*. Nothing reported it
    either: the string as a whole is well inside its 55 units, so no
    cell was over its room and there was nothing for :func:`check_fit`
    to say. Accepted, drawn meaningless, and issued.

    The fallback is **read off the dataclass** rather than written here
    so that the two cannot say different things. An author reads ``sheet:
    str = "1"`` on the block; that is what an unset field draws, and it
    is now what a blank one draws too. It also settles the next field
    somebody gives a default to on the day it is added rather than the
    day a cell is noticed drawing half of it.

    Read here and not in ``__post_init__`` for :func:`_field`'s reason:
    ``fs.title_block.sheet = "  "`` after the block is built has to
    answer the same way, and a dataclass hook sees only construction.
    """
    return _field(obj, name) or _class_defaults(type(obj)).get(name, "")


def company_lines(company: str) -> list[str]:
    """The company name broken into the lines its cell stacks.

    The company cell is the one on the strip that *wraps*, because a
    company name is several words and the cell is a hundred units wide.
    It is also the one where breaking mid-word is not available: a
    hyphen the author did not write invents a name, so a single word
    wider than the cell is drawn whole and reported (:func:`check_fit`)
    rather than split.

    A function rather than four lines inside the layout because
    :func:`pandid.validate.model_issues` has to count the lines to know
    whether they still fit the strip's depth, and a second wrapper
    written to answer that would be a second opinion about where the
    breaks fall.
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
    """``(line count, room, need)`` when the company name wraps to more
    lines than the strip is deep, or ``None``.

    The cell is centred on the strip's depth, so a name that wraps to
    more lines than fit does not stop at the rule: it runs *out of the
    strip*, over the drawing above and off the sheet below, and the
    per-line width check above sees nothing wrong because every line is
    within its width. It is the one way this block loses a value in a
    direction the rest of the strip cannot.

    The depth is the strip's own, since the company cell is ruled the
    full height of it (:func:`measure_title_strip`), so a block with a
    revision history or a client line has more room than a bare one.
    """
    lines = company_lines(_stated(tb, "company"))
    _, room = measure_title_strip(tb)
    need = len(lines) * _COMPANY_LEAD
    return (len(lines), room, need) if need > room else None


def undrawn_signatories(tb) -> "list[tuple[str, str, str]]":
    """``(field, value, displaced_by)`` for every block-level signatory
    the strip does not letter anywhere.

    ``drawn_by``/``checked_by``/``approved_by`` fill the BY / CHK'D /
    APP'D cells of the *newest* revision row (:data:`_BACKFILL`), which
    is the only place on the sheet those three columns exist. So a
    block-level name is drawn in that row or it is drawn nowhere, and it
    goes undrawn two ways: there is no revision at all, and
    ``displaced_by`` is empty; or the newest revision states a signatory
    of its own, which is the more specific claim and keeps the cell.
    A row stating the *same* name displaces nothing -- the value is on
    the sheet, and which field put it there is nobody's problem.

    Here rather than in :mod:`pandid.validate` because it is the same
    question :func:`title_strip_layout` answers when it fills the row,
    asked of the same fields through the same :func:`_field`. Derived a
    second time in the validator, the two disagreed the moment one of
    them learned that a whitespace ``by`` is not a value: the strip
    backfilled the row and the validator reported an override that had
    not happened.
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
    return [(label, value) for label, value
            in (("CLIENT", _stated(tb, "client")),
                ("PROJECT", _stated(tb, "project"))) if value]


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
    how big it is and what goes in it to ISO 7200 -- so a value too long
    for its cell cannot be given more room. What each cell does about
    that is a property of the field it draws, and there are three
    answers:

    * the drawing **title** is lettered smaller until it fits
      (:func:`fit_size`), because it alone is set above the strip's
      reading size and is read straight through;
    * the **company** cell wraps between words, and the sheet count is
      drawn whole, because half of either reads as a different company
      or a different sheet (:func:`check_fit`);
    * everything else is abbreviated to an ellipsis (:func:`clip`),
      which is what a draughtsman does and what the cell beside it makes
      necessary.

    ``report`` is how each such cell says which field it could not hold,
    what it was given, what it drew and the two widths; see
    :data:`Reporter`. The measuring happens **here** and not in either
    stroker, so the two backends abbreviate the same field to the same
    string and report it in the same words.
    """
    # *name* and *date* are what the two cells fall back to, not what
    # they draw: the block's own values win, and the choice is made
    # here because it has to be made *after* whitespace is read as the
    # blank it means. A caller that chose first handed on a whitespace
    # title with the flowsheet name it should have fallen back to
    # already thrown away, and a whitespace date with today's.
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
        """One row of the grid, each cell clipped to its own column.

        *cells* is a ``(value, field)`` pair per column, the field
        naming what the author would edit; an empty field is the
        library's own lettering and is not reported on.
        """
        return [clip(v, cw - 2 * _REV_PAD, _REV_TYPE, bold,
                     field=f, report=report if f else None)
                for (_, cw, _attr), (v, f) in zip(_REV_COLS, cells)]

    header_y = bottom - _REV_ROW
    headings = rev_cells([(c[0], "") for c in _REV_COLS], bold=True)
    # Clipped newest first, which is the order the strip used to draw
    # them in and so the order a caller watching ``report`` already
    # sees; stored oldest first, which is the order they are read in.
    newest_first = []
    for idx, rv in enumerate(reversed(tb.revisions)):
        newest = idx == 0
        i = len(tb.revisions) - 1 - idx
        row = []
        for _heading, _cw, attr in _REV_COLS:
            cell, value = f"revisions[{i}].{attr}", _stated(rv, attr)
            # The block-level drawn/checked/approved fields backfill the
            # newest row's signatories when that revision leaves them
            # blank -- so the value in the cell is sometimes the block's
            # and the finding has to name whichever field supplied it.
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
            # A word too long for the cell has no break point the
            # wrapper may use: hyphenating a company name invents one,
            # so it is drawn whole and said out loud instead.
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
    # title + subtitle, with sheet count tucked top-right of the title
    # band. Both halves through :func:`_stated`, which is what keeps the
    # count whole: blank, each falls back to the ``"1"`` the block's own
    # signature states, so the cell reads SHEET 1 of 1 rather than
    # ``SHEET  of 1``. A half-count is the one thing this slot must not
    # draw -- see :data:`_SHEET_W` -- and it is not a width finding,
    # since the short string fits its room easily.
    sheets = f"SHEET {_stated(tb, 'sheet')} of {_stated(tb, 'of_sheets')}"
    # The drawing title is the one value on the strip lettered *above*
    # the strip's reading size, so it is the one with size to give back
    # before it has meaning to give up -- and it is read straight
    # through, where a drawing number or a date is matched character by
    # character against another document. A draughtsman letters a long
    # title smaller; nobody abbreviates it. So it is set down to fit,
    # and only abbreviated below the floor.
    #
    # The floor is the subtitle's size, because a title lettered under
    # it would read as the subordinate line of the two and the band
    # would say the wrong thing about the drawing. The baseline does not
    # move with the size: a set of sheets is scanned down the same line,
    # and it is the lettering that varies with the title's length, not
    # where the title sits.
    #
    # A block that states no title of its own draws the flowsheet's
    # name, so the finding names *that* -- an author told "title was
    # truncated" about a field they never set goes looking in the wrong
    # place. Same for the three cells below it; see :data:`Reporter`.
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
    # One cell drawn from two fields, so the finding names both: which
    # of the two is the long one is visible in the string it quotes, and
    # a cell that named only ``sheet`` sent an author who had set
    # ``of_sheets`` to look at the wrong field.
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
    # Bottom band: DRAWING No | SCALE | DATE | REV. Keeping the scale
    # with the number and the revision index is common drafting practice
    # rather than a standard: ISO 7200 §4 puts scale outside the title
    # block, and ASME title-block content is Y14.100's concern, not
    # Y14.1's.
    #
    # **Four cells, always, at fixed shares of the band.** A title block
    # is a form: its boxes are ruled by the form and filled in by the
    # drawing, and a real one carries a SCALE box whether or not there
    # is a scale to write in it. This band used to rule three when there
    # was none and hand the room back to the cells that identify the
    # drawing, which sounds like a kindness and is the defect. The scale
    # cell appears when the block states a scale *or* when a page size
    # lets the renderer state the ratio it fitted the drawing at -- so
    # ``drawing_number`` was budgeted 118 units under ``to_svg()`` and
    # 88 under ``to_svg(page_size="A3")``. The same ``PFD-111111111``
    # fits one call and is silently abbreviated by the other, and no
    # check that had not been told the page size could say which.
    #
    # A fixed slot is what :data:`_SHEET_W` already does for the title,
    # for the same reason and in nearly the same words: how much of a
    # drawing number survives must not depend on how the sheet happened
    # to be asked for. It is also what lets
    # :func:`pandid.validate.model_issues` measure this band at all --
    # every width here is a constant now, so the cell it measures is the
    # cell the renderer draws.
    #
    # Three of the four draw a value the block did not state, and each
    # names the field that did state it (see :data:`Reporter`).
    # Through :func:`_stated` like every other read: left raw, a
    # revision whose ``rev`` was whitespace put four invisible
    # characters in a 22-unit cell and had them reported as a
    # truncation.
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
        # Measured either way, drawn only when there is something to
        # draw: the scale box is ruled on a sheet with no scale to state
        # (see the note above) and an empty ``<text>`` under its caption
        # would be an element in every such file saying nothing.
        drawn = clip(seg_val, seg_w - 8, _VALUE_TYPE, bold,
                     field=seg_field, report=report)
        if drawn:
            parts.append(("text", cxr + 5, bottom - 5, drawn,
                          _VALUE_TYPE, "start", bold, "black"))
        cxr += seg_w
    return Strip((x, y, w, h), rules, rev, parts)


def title_strip_fit(tb, name: str, date: str, fit_scale: str = ""
                    ) -> "list[tuple[str, str, str, float, float]]":
    """Every cell of the strip that cannot hold what it was given, as
    :data:`Reporter` tuples, without drawing anything.

    ``name`` and ``date`` are what the title and date cells fall back to
    where the block states neither -- the flowsheet's name and today's
    date -- and are passed *unchosen*, exactly as the two renderers pass
    them, so that this and the sheet answer alike. Choosing first is
    what made a whitespace title a truncation the render reported and
    this did not.

    Whether a value fits is a fact about the *model*: every width the
    strip rules is a constant in this module, so the answer does not
    depend on the page size, on the drawing, or on anything layout or
    routing settles. That is what lets
    :func:`pandid.validate.model_issues` report an over-long title block
    on a sheet that has never been rendered -- the point of the finding
    being to reach the author *before* the sheet is issued, not to
    describe one that already was.

    It is the same measurement and not a second opinion about it: the
    layout is run with a collecting reporter and its ink thrown away,
    so a cell width can never be stated in two places and drift.

    ``fit_scale`` is the ratio the renderer settled on, which the scale
    cell reports for a block that states no scale of its own. A caller
    with no render behind it cannot know it and passes none, and that
    changes **nothing about any other cell**: the bottom band is ruled
    at four fixed shares whether or not there is a scale to write in the
    scale box, so the drawing number is budgeted the same 88 units under
    every call. It did not use to be -- the band gave the scale cell's
    room back to the three cells that identify the drawing, and
    ``drawing_number`` was measured against 118 units here and cut at 88
    by a render with a page size, which is exactly the silent
    abbreviation this module exists to report. The remedy was to stop
    the width moving, not to describe the two of them.

    The scale cell is the one cell whose *own* value this cannot
    measure, and it is the only one nobody typed: what goes in it is a
    ratio the dock settles from the page and the drawing, so it is the
    render's to report and the render does. Every value the **author**
    wrote is measured here, against the width it will be drawn in.
    """
    found: list[tuple[str, str, str, float, float]] = []

    def collect(field: str, text: str, drawn: str,
                room: float, need: float) -> None:
        found.append((field, text, drawn, room, need))

    title_strip_layout(tb, name, date, 0.0, 0.0, fit_scale, report=collect)
    return found


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
    L.append(_strip_part(("rule", g.x, g.header_y, g.x + g.w, g.header_y,
                          _BOX_UNDERLINE)))
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
    It is only reached from inside that same overflow, so a caller
    whose page cannot overflow -- an empty ``items``, say -- may still
    leave it ``None``.

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
        return _total(h for _, _, h in entries) + GAP * max(0, len(entries) - 1)

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
            # Only a fixed page can overflow, so this is the one place
            # a missing `too_small` would otherwise surface as a bare
            # "NoneType is not callable" -- naming the real invariant
            # here instead means whoever forgot it reads why, and only
            # a caller that actually overflows its page has to supply
            # it at all.
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
