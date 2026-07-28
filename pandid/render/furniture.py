"""Sheet furniture: the engineering title strip, generic titled boxes, generic
tables, and the zone-ruled drawing border.

Every routine here is a pure function returning a list of SVG-fragment strings
(or a ``(width, height)`` measurement). The renderer in :mod:`pandid.render.svg`
measures each piece, places it at a sheet corner, unions the result to size the
canvas, then draws it — none of the geometry logic lives in the giant render
method.

Coordinates are absolute SVG user units. Boxes are drawn from a top-left origin;
the title strip is drawn from a bottom-right corner (its natural anchor).
"""

from __future__ import annotations

import html
import string
from typing import Callable

# Rough advance width of the sans-serif the renderer uses, as a fraction of the
# font size. Slightly generous so auto-sized boxes never clip their text.
_ADV = 0.56
_ADV_BOLD = 0.62

FONT = "sans-serif"

# How a cell says it could not hold what it was given: the field it draws, the
# text it was asked for, and the text it actually drew (the same string when
# nothing was trimmed). An ellipsis tells whoever reads the sheet that a value
# was abbreviated; it tells the program that supplied the value nothing at all,
# and that program is the one that can shorten the field or ask for a bigger
# sheet. Every fixed-width cell in this module therefore measures first and
# reports through one of these.
Reporter = Callable[[str, str, str], None]


def text_width(s, size: float, bold: bool = False) -> float:
    return len(str(s)) * size * (_ADV_BOLD if bold else _ADV)


def clip(s, room: float, size: float, bold: bool = False, *,
         field: str = "", report: "Reporter | None" = None) -> str:
    """Trim a value to the room its cell has, and report what was cut.

    A title-block cell is ruled and the strip is fixed geometry, so a value
    longer than its cell would run across the rule and into the value beside it
    and no amount of growing can help. A draftsman abbreviates.
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
    """Measure a value that is drawn whole whatever it measures, and report an
    overrun.

    Some cells have nothing worth trimming. Half a sheet count reads as a
    different sheet count, and a company name broken mid-word reads as a
    different company, so those are drawn in full and the overrun is reported
    instead of hidden.
    """
    s = str(s)
    if report is not None and text_width(s, size, bold) > room:
        report(field, s, s)
    return s


def _esc(s) -> str:
    return html.escape(str(s))


def _text(x, y, s, size, *, anchor="start", bold=False, fill="black", baseline=None):
    wt = ' font-weight="bold"' if bold else ""
    bl = f' dominant-baseline="{baseline}"' if baseline else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size:.1f}"'
            f' text-anchor="{anchor}"{wt}{bl} fill="{fill}">{_esc(s)}</text>')


# ---------------------------------------------------------------------------
# Generic titled box (Annotation): title bar over free-form / columnar rows
# ---------------------------------------------------------------------------

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
    """The one string a too-narrow box is best described by: its title where
    that is what overruns, otherwise the row that does."""
    if text_width(ann.title, size + 1, bold=True) > body_w:
        return ann.title

    def flat(r):
        return "   ".join(str(c) for c in r) if isinstance(r, (tuple, list)) else str(r)
    return max((flat(r) for r in ann.rows), key=lambda s: text_width(s, size),
               default=ann.title)


def draw_annotation(ann, x: float, y: float, *,
                    report: "Reporter | None" = None) -> list[str]:
    """Draw an Annotation with its top-left corner at (x, y).

    A box left to size itself is sized from its own rows, so it always fits.
    One given an explicit ``width`` is a fixed cell like any other: the rows are
    still drawn at the column stops their content asks for, so a width smaller
    than that content runs the text out through the side of the box.
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
         f'fill="white" stroke="black" stroke-width="1.5"/>']
    if ann.title:
        L.append(_text(x + w / 2, y + title_h - 6, ann.title, size + 1,
                       anchor="middle", bold=True))
        L.append(f'<line x1="{x:.1f}" y1="{y + title_h:.1f}" x2="{x + w:.1f}" '
                 f'y2="{y + title_h:.1f}" stroke="black" stroke-width="1"/>')
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


# ---------------------------------------------------------------------------
# Generic bordered table (TableBox)
# ---------------------------------------------------------------------------

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
                     f'height="{row_h:.1f}" fill="{fill}" stroke="black" stroke-width="0.75"/>')
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


# ---------------------------------------------------------------------------
# Engineering title strip (revision table | company | client/project, title,
# status, drawing number / scale / date / rev)
# ---------------------------------------------------------------------------

_REV_W = 300.0
_COMPANY_W = 100.0
_INFO_W = 252.0
_REV_ROW = 14.0
# (heading, width, the Revision field the column draws). The widths sum to
# _REV_W. DATE holds a full ISO 8601 date at 7.5 with a gutter either side,
# which is what fixes it at 50: at the 42 it was, the date every one of these
# sheets is stamped with ran over its own rule.
_REV_COLS = (("REV", 22, "rev"), ("DATE", 50, "date"),
             ("DESCRIPTION", 132, "description"), ("BY", 32, "by"),
             ("CHK'D", 32, "checked"), ("APP'D", 32, "approved"))
# Gutter between a revision cell's rule and its text, left and right.
_REV_PAD = 3.0
# The title / status / drawing-number bands, which every sheet carries.
_BODY_H = 80.0
# The sheet count is drawn top-right of the title band, on the same line as the
# title. Reserving it a fixed slot is what keeps the title's own budget a
# constant: how much of a drawing's title survives must not depend on how many
# sheets the set happens to have, which is not a fact about the title. Sized for
# "SHEET 1 of 12" at 7.5; a longer count is drawn whole and reported, since half
# a sheet count reads as a different sheet.
_SHEET_W = 55.0
_TITLE_W = _INFO_W - 10 - _SHEET_W
# One client or project line above them. Neither is an ISO 7200 field. Its
# mandatory "legal owner" is the issuing organisation, which is the company
# cell. An issued sheet names both anyway, so the pair heads the information
# block; a block that names neither is ruled no row for them.
_HDR_ROW = 13.0
_HDR_VALUE_X = 40.0


def _header_lines(tb) -> list[tuple[str, str]]:
    return [(label, value) for label, value
            in (("CLIENT", tb.client), ("PROJECT", tb.project)) if value]


def measure_title_strip(tb) -> tuple[float, float]:
    n = len(tb.revisions)
    h = max((n + 1) * _REV_ROW, _BODY_H) + _HDR_ROW * len(_header_lines(tb))
    return _REV_W + _COMPANY_W + _INFO_W, h


def draw_title_strip(tb, name: str, date: str, right: float, bottom: float,
                     fit_scale: str = "", *,
                     report: "Reporter | None" = None) -> list[str]:
    """Draw the strip so its bottom-right corner sits at (right, bottom).

    ``fit_scale`` is the ratio the renderer actually placed the drawing at, which
    is what the scale cell reports for a sheet that does not state a scale of
    its own.

    The strip is fixed geometry — an ISO 7200 block is a known rectangle in a
    known corner — so a value too long for its cell cannot be given more room
    and is abbreviated instead. ``report`` is how each such cell says which
    field it abbreviated and what it was given; see :data:`Reporter`.
    """
    w, h = measure_title_strip(tb)
    x, y = right - w, bottom - h
    L = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
         f'fill="white" stroke="black" stroke-width="2"/>']
    rx = x + _REV_W
    cx2 = rx + _COMPANY_W
    for vx in (rx, cx2):
        L.append(f'<line x1="{vx:.1f}" y1="{y:.1f}" x2="{vx:.1f}" y2="{bottom:.1f}" '
                 f'stroke="black" stroke-width="1.5"/>')

    # --- Revision table (left): header row at the bottom, revisions above it ---
    def rev_cells(ry, vals, bold=False, where=""):
        cx = x
        for (_, cw, attr), v in zip(_REV_COLS, vals):
            L.append(_text(cx + _REV_PAD, ry + _REV_ROW - 4,
                           clip(v, cw - 2 * _REV_PAD, 7.5, bold,
                                field=f"{where}.{attr}",
                                report=report if where else None),
                           7.5, bold=bold))
            cx += cw
    header_y = bottom - _REV_ROW
    L.append(f'<line x1="{x:.1f}" y1="{header_y:.1f}" x2="{rx:.1f}" y2="{header_y:.1f}" '
             f'stroke="black" stroke-width="1"/>')
    cx = x
    for _, cw, _attr in _REV_COLS[:-1]:
        cx += cw
        L.append(f'<line x1="{cx:.1f}" y1="{y:.1f}" x2="{cx:.1f}" y2="{bottom:.1f}" '
                 f'stroke="black" stroke-width="0.5"/>')
    rev_cells(header_y, [c[0] for c in _REV_COLS], bold=True)
    # newest revision nearest the header (bottom); oldest climbs the stack. The
    # block-level drawn/checked/approved fields backfill the newest row's
    # signatories when that revision leaves them blank.
    ry = header_y - _REV_ROW
    for idx, rv in enumerate(reversed(tb.revisions)):
        newest = idx == 0
        by = rv.by or (tb.drawn_by if newest else "")
        chk = rv.checked or (tb.checked_by if newest else "")
        app = rv.approved or (tb.approved_by if newest else "")
        rev_cells(ry, [rv.rev, rv.date, rv.description, by, chk, app],
                  where=f"revisions[{len(tb.revisions) - 1 - idx}]")
        ry -= _REV_ROW

    # --- Company / logo cell (middle) ---
    if tb.company:
        words, line, lines = tb.company.split(), "", []
        for wd in words:
            trial = (line + " " + wd).strip()
            if text_width(trial, 8, bold=True) > _COMPANY_W - 10 and line:
                lines.append(line)
                line = wd
            else:
                line = trial
        if line:
            lines.append(line)
        cy = y + h / 2 - (len(lines) - 1) * 6
        for ln in lines:
            # A word too long for the cell has no break point the wrapper may
            # use: hyphenating a company name invents one, so it is drawn whole
            # and said out loud instead.
            L.append(_text(rx + _COMPANY_W / 2, cy,
                           check_fit(ln, _COMPANY_W - 10, 8, True,
                                     field="company", report=report),
                           8, anchor="middle", bold=True))
            cy += 12

    # --- Info block (right): client/project header, title, status, dwg/date/rev ---
    ix = cx2
    header = _header_lines(tb)
    top = y + _HDR_ROW * len(header)     # top of the title band
    body = h - _HDR_ROW * len(header)
    title_h = body * 0.40
    status_h = body * 0.28
    band2 = top + title_h
    band3 = top + title_h + status_h
    hy = y
    for i, (label, value) in enumerate(header):
        if i:
            L.append(f'<line x1="{ix:.1f}" y1="{hy:.1f}" x2="{x + w:.1f}" '
                     f'y2="{hy:.1f}" stroke="black" stroke-width="0.5"/>')
        L.append(_text(ix + 6, hy + _HDR_ROW - 4, label, 6.5, fill="#666"))
        L.append(_text(ix + _HDR_VALUE_X, hy + _HDR_ROW - 4,
                       clip(value, _INFO_W - _HDR_VALUE_X - 5, 9,
                            field=label.lower(), report=report), 9))
        hy += _HDR_ROW
    for ly in ([top] if header else []) + [band2, band3]:
        L.append(f'<line x1="{ix:.1f}" y1="{ly:.1f}" x2="{x + w:.1f}" '
                 f'y2="{ly:.1f}" stroke="black" stroke-width="0.75"/>')
    # title + subtitle, with sheet count tucked top-right of the title band
    sheets = f"SHEET {tb.sheet} of {tb.of_sheets}"
    L.append(_text(ix + 6, top + 15,
                   clip(tb.title or name, _TITLE_W, 12.5, True,
                        field="title", report=report),
                   12.5, bold=True))
    if tb.subtitle:
        L.append(_text(ix + 6, band2 - 6,
                       clip(tb.subtitle, _INFO_W - 12, 10.5,
                            field="subtitle", report=report), 10.5))
    L.append(_text(x + w - 5, top + 11,
                   check_fit(sheets, _SHEET_W, 7.5, field="sheet", report=report),
                   7.5, anchor="end", fill="#666"))
    # status (tiny label at cell top, value below)
    L.append(_text(ix + 6, band2 + 8, "STATUS", 6.5, fill="#666"))
    L.append(_text(ix + 6, band3 - 5,
                   clip(tb.status or "—", _INFO_W - 12, 11, True,
                        field="status", report=report), 11, bold=True))
    # Bottom band: DRAWING No | SCALE | DATE | REV. Keeping the scale with the
    # number and the revision index is common drafting practice rather than a
    # standard: ISO 7200 §4 puts scale outside the title block, and ASME
    # title-block content is Y14.100's concern, not Y14.1's. A sheet with no
    # scale to state gives its room back to the three cells that identify the
    # drawing.
    rev = tb.revisions[-1].rev if tb.revisions else "0"
    scale = tb.scale or fit_scale
    cells: list[tuple[float, str, str, str]] = [
        (_INFO_W * 0.38, "DRAWING No", tb.drawing_number or "—", "drawing_number"),
        (_INFO_W * 0.21, "SCALE", scale, "scale"),
        (_INFO_W * 0.29, "DATE", date, "date"),
        (_INFO_W * 0.12, "REV", rev, "rev")] if scale else [
        (_INFO_W * 0.50, "DRAWING No", tb.drawing_number or "—", "drawing_number"),
        (_INFO_W * 0.30, "DATE", date, "date"),
        (_INFO_W * 0.20, "REV", rev, "rev")]
    cxr = ix
    for j, (seg_w, seg_label, seg_val, seg_field) in enumerate(cells):
        if j:
            L.append(f'<line x1="{cxr:.1f}" y1="{band3:.1f}" x2="{cxr:.1f}" '
                     f'y2="{bottom:.1f}" stroke="black" stroke-width="0.5"/>')
        bold = seg_label != "DATE"
        L.append(_text(cxr + 5, band3 + 8, seg_label, 6.5, fill="#666"))
        L.append(_text(cxr + 5, bottom - 5,
                       clip(seg_val, seg_w - 8, 11, bold,
                            field=seg_field, report=report), 11,
                       bold=bold))
        cxr += seg_w
    return L


# ---------------------------------------------------------------------------
# Zone-ruled drawing border (ASME-style: A.. bottom→top, 1.. right→left)
#
# This is a drawing-frame zone reference in the ASME idiom, not an ISO 5457
# grid. ISO 5457 §4.4 runs letters top down and numerals left to right at a
# fixed 50 mm pitch with the field counts of its Table 2, and §4.3/§4.5 add
# centring and trimming marks. None of that is drawn here: the band is a
# constant in drawing units and the field count is chosen to suit the sheet.
# ISO 15519-1 §5.1.2, the clause that applies to a diagram, asks for the
# centring marks only on a document prepared for microfilming.
# ---------------------------------------------------------------------------

# Width of the lettered/numbered band between the drawing frame and the sheet
# border. A fixed-size sheet insets its frame by this to rule to the page edge.
ZONE_BAND = 16.0


def sheet_rect(ix: float, iy: float, iw: float, ih: float, band: float = ZONE_BAND
               ) -> tuple[float, float, float, float]:
    """The sheet rectangle around a drawing frame, ruled or not.

    An unruled sheet keeps the band as plain margin, so turning the border on
    and off leaves every piece of furniture exactly where it was.
    """
    return ix - band, iy - band, iw + 2 * band, ih + 2 * band


def zone_frame(ix: float, iy: float, iw: float, ih: float, band: float = ZONE_BAND
               ) -> tuple[list[str], tuple[float, float, float, float]]:
    """Draw the drawing frame (inner rect) plus the sheet border (outer rect)
    with zone letters/numbers ruled in the band between them.

    (``ix``, ``iy``, ``iw``, ``ih``) is the inner drawing rectangle. Returns the
    SVG fragments and the outer sheet rectangle (x, y, w, h).
    """
    ox, oy, ow, oh = sheet_rect(ix, iy, iw, ih, band)
    cols = max(4, min(12, round(iw / 165)))
    rows = max(3, min(8, round(ih / 165)))
    L = [f'<rect x="{ox:.1f}" y="{oy:.1f}" width="{ow:.1f}" height="{oh:.1f}" '
         f'fill="none" stroke="black" stroke-width="1"/>',
         f'<rect x="{ix:.1f}" y="{iy:.1f}" width="{iw:.1f}" height="{ih:.1f}" '
         f'fill="none" stroke="black" stroke-width="2"/>']
    letters = string.ascii_uppercase
    # columns: numbers 1..cols, right→left, on the top and bottom bands
    for c in range(cols):
        x0 = ix + iw * c / cols
        x1 = ix + iw * (c + 1) / cols
        num = str(cols - c)
        if c:
            L.append(f'<line x1="{x0:.1f}" y1="{oy:.1f}" x2="{x0:.1f}" y2="{iy:.1f}" stroke="black" stroke-width="0.75"/>')
            L.append(f'<line x1="{x0:.1f}" y1="{iy + ih:.1f}" x2="{x0:.1f}" y2="{oy + oh:.1f}" stroke="black" stroke-width="0.75"/>')
        L.append(_text((x0 + x1) / 2, oy + band / 2 + 3, num, 9, anchor="middle", bold=True))
        L.append(_text((x0 + x1) / 2, oy + oh - band / 2 + 3, num, 9, anchor="middle", bold=True))
    # rows: letters A.. bottom→top, on the left and right bands
    for r in range(rows):
        y0 = iy + ih * r / rows
        y1 = iy + ih * (r + 1) / rows
        letter = letters[rows - 1 - r]
        if r:
            L.append(f'<line x1="{ox:.1f}" y1="{y0:.1f}" x2="{ix:.1f}" y2="{y0:.1f}" stroke="black" stroke-width="0.75"/>')
            L.append(f'<line x1="{ix + iw:.1f}" y1="{y0:.1f}" x2="{ox + ow:.1f}" y2="{y0:.1f}" stroke="black" stroke-width="0.75"/>')
        L.append(_text(ox + band / 2, (y0 + y1) / 2 + 3, letter, 9, anchor="middle", bold=True))
        L.append(_text(ox + ow - band / 2, (y0 + y1) / 2 + 3, letter, 9, anchor="middle", bold=True))
    return L, (ox, oy, ow, oh)
