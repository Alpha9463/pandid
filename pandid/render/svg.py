"""SVG rendering backend."""

from typing import NamedTuple, TYPE_CHECKING
import html
import math
import re
from datetime import datetime

from pandid.render import furniture as F
from pandid.render.symbols import closed_marking, fail_marking
from pandid.streams import SIGNAL_KINDS as _SIGNAL_KINDS
from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

# A symbol's own lettering — the "M" in a motor operator, the "S" in a solenoid.
# Matched to be counter-transformed when the symbol is turned or flipped.
_SYMBOL_TEXT = re.compile(
    r'<text\b[^>]*?\bx="(-?[\d.]+)"[^>]*?\by="(-?[\d.]+)"[^>]*?>.*?</text>', re.S)
# Balloon variants whose symbol draws a location bar across the middle (see the
# instrument symbols in pandid.render.symbols): their tag text has to clear it.
_BARRED_BALLOONS = {"panel", "aux"}
# Variants drawn as a diamond (ISA-5.1-2009 Table 5.1.1 column B and Table 5.1.2
# items 3-5): they carry the interlock number alone, and it has to sit where the
# sloping sides leave room for it rather than in the middle of the box.
_DIAMOND_BALLOONS = {"sis", "logic", "interlock"}

# --- line weights ------------------------------------------------------------
# ISO 15519 draws a process diagram in two weights, and the ratio between them
# is what tells a reader the process from the instrumentation at a glance.
#
# ISO 15519-1 §6.2 Table 1 gives the process industry field symbols 0,1 M and
# connections 0,2 M, with 0,4 M available where §12.2 wants a significant
# connection emphasised, and M = 2,5 mm (§11.1.2). That is the 0,25 / 0,5 / 1,0
# ladder ISO 10628-1 §5.3.1 uses: one ladder, of which ISO 15519 spends two
# rungs by default and holds the third in reserve. §6.2 then makes the spacing
# a requirement rather than a habit: "If two or more widths of line are used,
# the ratio between any two widths shall be at least 2:1."
#
# ISO 15519-2 Annex A.1 spends that pair per line type: A.1.01 pipeline 0,50;
# A.1.02 instrument connection and control connection 0,25; A.1.03 pilot line
# and signal line 0,25.
#
# A drawing unit here is a CSS pixel, 25,4/96 mm, so 2 and 1 land on 0,53 mm and
# 0,26 mm, which is the standard's own pair at exactly the 2:1 it requires.
# They are relative weights within one drawing and still scale with the sheet;
# holding them at a physical width is ISO 15519-1 §11.1.3's separate problem.
_PROCESS_STROKE = 2
_SIGNAL_STROKE = 1

# --- stream-label placement -------------------------------------------------
# A stream label is written on an opaque halo, so it can only sit *on* the pipe
# where the run is long enough to leave pipe showing at each end: the 12px
# arrowhead a PFD draws, plus enough line either side that the run still reads
# as one line rather than two stubs. Anything shorter is written beside the pipe
# instead, which is what a sheet does with a line number a dozen characters long.
_LABEL_CLEAR = 20.0
# Gap from the pipe to the near edge of a label written beside it.
_LABEL_GAP = 4.0
# Search step along the run. Fine, because a label only has to clear whatever it
# landed on rather than jump a whole label width.
_LABEL_STEP = 6.0


def _slide(x: float, y: float, room: float, vertical: bool):
    """Anchor positions along a run: centred first, then out either way."""
    yield x, y
    for k in range(1, int(room // _LABEL_STEP) + 1):
        d = k * _LABEL_STEP
        yield (x, y - d) if vertical else (x - d, y)
        yield (x, y + d) if vertical else (x + d, y)


def _label_anchors(cx: float, cy: float, span: float, hw: float, hh: float, vertical: bool):
    """Where a label of ``hw`` x ``hh`` may go on a run of ``span``, best first.

    On the pipe only while the run can still show clear line at each end; then
    beside it (above a horizontal run, left of a vertical one), then the far
    side, then further out. Each of those is slid along the run in turn, so the
    label leaves the pipe before it leaves the neighbourhood of its own line.

    Above and left is the side ISO 15519-1 §7.2.5 asks for. On the pipe comes
    first anyway, since a dozen-character line number costs the sheet more room
    beside the run than on it, and §7.2.5 words its preference as a ``should``.

    On the pipe the label has to stay within the run, clearance and all. Beside
    it, it erases nothing, so it may slide until its near edge reaches the run's
    end: far enough to get out from under a symbol the run butts into, and no
    further, since past that it stops reading as this line's number.
    """
    if span >= hw + 2 * _LABEL_CLEAR:
        yield from _slide(cx, cy, (span - hw) / 2 - _LABEL_CLEAR, vertical)
    for out in range(3):
        off = hh / 2 + _LABEL_GAP + out * hh
        for side in (-1.0, 1.0):
            ax = cx + side * off if vertical else cx
            ay = cy if vertical else cy + side * off
            yield from _slide(ax, ay, (span + hw) / 2, vertical)


def _unit_label_box(item) -> "tuple[float, float, float, float] | None":
    """Halo rect of an equipment tag. ``None`` for a ``center`` tag, which sits
    inside its own symbol and so is drawn without one."""
    lx, ly, anchor, baseline, lpos, text = item
    if lpos == "center":
        return None
    hw, hh = len(text) * 6.6 + 8, 15.0
    rx = lx - hw / 2 if anchor == "middle" else (lx - hw if anchor == "end" else lx)
    ry = ly - hh / 2 if baseline == "middle" else ly - hh + 3
    return (rx, ry, rx + hw, ry + hh)


def _num(v: float) -> str:
    """Format a coordinate without trailing zeros (100.0 -> '100')."""
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def _xform_tag(rot: int, mirror_x: bool, mirror_y: bool) -> str:
    """Short id suffix naming a placement transform ('' for the identity)."""
    if not (rot or mirror_x or mirror_y):
        return ""
    return "_t" + (f"r{rot}" if rot else "") + ("x" if mirror_x else "") + ("y" if mirror_y else "")


def _reshapes(sym, u) -> bool:
    """True when a unit's box is a different shape from its symbol's own.

    Which is the whole of what a placement can ask of the artwork beyond a plain
    resize: an explicit ``width``/``height`` is taken as the final box, so a unit
    left to size itself lands on the symbol's proportions exactly and one given
    both may land on any others. A quarter turn swaps the box, and swaps the
    symbol with it, so it never reshapes anything by itself.
    """
    f = getattr(u, "frame", None)
    if f is None:
        return False
    rot = int(getattr(f, "orientation", 0) or 0)
    bw, bh = (f.h, f.w) if rot in (90, 270) else (f.w, f.h)
    # Cross-multiplied, so a zero dimension cannot divide. A box that matches is
    # copied from the symbol's own size and matches to the bit; the tolerance is
    # only there so arithmetic on a size the author computed cannot claim a
    # reshaping that is not one.
    return not math.isclose(sym.width * bh, sym.height * bw, rel_tol=1e-9)


def _upright_text(svg: str, rot: int, mirror_x: bool, mirror_y: bool) -> str:
    """Keep a symbol's own lettering readable under a placement transform.

    Flipping a motor-operated valve to put its operator below the line is a
    statement about the *equipment*, not about the letter stamped on it: the
    box moves, the "M" inside it does not turn upside down. The transform on
    the ``<use>`` reaches the glyphs as readily as the strokes, so each text is
    wrapped in the inverse of that transform taken about its own anchor. The
    anchor still lands where the flip puts it — only the orientation is undone.
    """
    if not (rot or mirror_x or mirror_y):
        return svg

    def wrap(match: "re.Match[str]") -> str:
        tx, ty = float(match.group(1)), float(match.group(2))
        # Pivot on the glyph's visual centre, not on its anchor: `y` is a
        # *baseline*, and reflecting a baseline leaves the letter hanging off
        # the top of the box it is stamped in, since the glyph body sits above
        # the line rather than astride it. Cap height is ~0.7em, so the middle
        # of a capital is ~0.35em above the baseline. `x` needs no such
        # correction — these are all text-anchor="middle".
        size = re.search(r'font-size="(-?[\d.]+)"', match.group(0))
        cy = ty - 0.35 * float(size.group(1) if size else 12.0)
        # Undone in the reverse of the order the <use> applies them.
        ops = []
        if mirror_x:
            ops.append(f"translate({_num(2 * tx)}, 0) scale(-1, 1)")
        if mirror_y:
            ops.append(f"translate(0, {_num(2 * cy)}) scale(1, -1)")
        if rot:
            ops.append(f"rotate({-rot}, {_num(tx)}, {_num(cy)})")
        return f'<g transform="{" ".join(ops)}">{match.group(0)}</g>'

    return _SYMBOL_TEXT.sub(wrap, svg)

# Standard page sizes in millimetres, landscape, straight from ISO 216. Held in
# millimetres because that is what the sizes are defined in: deriving each one
# from the last by doubling accumulates ISO's per-size rounding, which is how A1
# and A0 previously came out a millimetre short.
_PAGE_SIZES = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}

# The user unit the drawing is laid out in is the CSS pixel, 1/96 inch.
_PX_PER_MM = 96.0 / 25.4


class _Sheet(NamedTuple):
    """A fixed sheet the drawing is placed on, rather than sized to.

    ``width``/``height`` are the layout units the diagram is placed in;
    ``width_mm``/``height_mm`` are the physical size the SVG declares, so the
    sheet prints and converts to PDF at exactly its ISO size rather than at
    whatever the consumer assumes a pixel is worth.
    """
    name: str
    width_mm: float
    height_mm: float

    @property
    def width(self) -> float:
        return self.width_mm * _PX_PER_MM

    @property
    def height(self) -> float:
        return self.height_mm * _PX_PER_MM


def _page(page_size: "str | None") -> "_Sheet | None":
    """Resolve ``page_size``; ``None`` means fit the sheet to the drawing."""
    if page_size is None:
        return None
    dims = _PAGE_SIZES.get(page_size.upper())
    if dims is None:
        raise ValueError(
            f"Unknown page size {page_size!r}; use one of {', '.join(_PAGE_SIZES)}, "
            "or omit page_size to fit the sheet to the drawing."
        )
    return _Sheet(page_size.upper(), *dims)


# The frame the sheet is ruled with: sheet furniture, and a statement about the
# paper rather than about the diagram drawn on it. A PFD carries a zone frame as
# readily as a P&ID does.
_BORDERS = ("none", "zone")
# Which drawing this is, which is a statement about the conventions it is read
# by. It is what decides whether a process line carries an arrowhead.
_DIAGRAMS = ("pfd", "p&id")
# `styling` predates both and says the two together: a P&ID on an engineering
# frame. Kept as the one-word way to ask for that, and as the older spelling.
_STYLINGS = {"default": ("none", "pfd"), "p&id": ("zone", "p&id")}
# The drawing's name has one accepted spelling per value plus whatever the
# caller can reasonably be expected to type for it.
_ALIASES = {"pid": "p&id", "p&id": "p&id", "pfd": "pfd", "default": "default"}


def _canon(value: str) -> str:
    """Fold a styling or diagram name to the one spelling the tables key on.

    Case is folded and the ampersand-less ``"pid"`` is read as ``"p&id"``. This
    package spells the drawing's name with the ampersand everywhere else, down
    to the distribution, so an engineer who types ``"P&ID"`` is typing the real
    name and must not be told it is unknown; ``"pid"`` is the spelling already
    published and stays working. Nothing else is guessed at.
    """
    return _ALIASES.get(value.strip().lower(), value)


def _resolve_sheet(styling: str, border: "str | None",
                   diagram: "str | None") -> "tuple[str, str]":
    """The frame to rule and the drawing to rule it around, from whichever
    spelling of the request the caller used.

    A name none of the three knows is a sheet the renderer cannot draw, so it
    raises rather than quietly handing back a plain PFD.
    """
    style = _canon(styling)
    if style not in _STYLINGS:
        raise ValueError(
            f"Unknown styling {styling!r}; use styling='p&id' (also spelled 'pid') "
            f"for a P&ID on the zone-ruled engineering frame, or 'default' for a "
            f"plain PFD sheet. border= and diagram= ask for the two halves of that "
            f"one at a time."
        )
    styled_border, styled_diagram = _STYLINGS[style]

    if border is None:
        border = styled_border
    elif border not in _BORDERS:
        raise ValueError(
            f"Unknown border {border!r}; use one of {', '.join(_BORDERS)}."
        )
    elif style != "default" and border != styled_border:
        raise ValueError(
            f"border={border!r} and styling={styling!r} ask for different frames; "
            f"pass border= alone."
        )

    if diagram is None:
        return border, styled_diagram
    kind = _canon(diagram)
    if kind not in _DIAGRAMS:
        raise ValueError(
            f"Unknown diagram {diagram!r}; use 'p&id' (also spelled 'pid') or 'pfd'."
        )
    if style != "default" and kind != styled_diagram:
        raise ValueError(
            f"diagram={diagram!r} and styling={styling!r} ask for different drawings; "
            f"pass diagram= alone."
        )
    return border, kind


def _fit_scale(dw: float, dh: float, free) -> float:
    """The uniform scale that puts a ``dw`` x ``dh`` drawing inside *free*.

    Never enlarges: sheet furniture is drawn at a fixed size, so blowing a small
    drawing up to fill the page would swell its line weights and lettering out
    of proportion to the border and title strip around it. A draftsman picks a
    scale that fits and leaves the rest of the sheet white.
    """
    _, _, fw, fh = free
    return min(1.0, fw / dw if dw > 0 else 1.0, fh / dh if dh > 0 else 1.0)


def _scale_text(s: float) -> str:
    """A fit scale as a title-block ratio."""
    return "1:1" if s >= 1.0 else f"1:{1 / s:.3g}"


# Findings this renderer raises about text that did not fit the cell drawn for
# it, as opposed to the validator's findings about the diagram.
_FIT_CODES = ("text-truncated", "text-overruns-cell")


def _too_small(sheet: _Sheet, need_w: float, need_h: float,
               cause: str = "") -> ValueError:
    """Furniture is drawn at a fixed size, so a sheet too small to hold it is an
    error no scale of the drawing can resolve.

    ``cause`` names the widest piece, which is the one worth shortening: a
    stream table sized to its own contents is usually what pushed a sheet over,
    and "the furniture does not fit" does not say which furniture.
    """
    blame = f" The widest piece is {cause}." if cause else ""
    return ValueError(
        f"The sheet furniture does not fit page size {sheet.name}: the border, title strip "
        f"and docked boxes need at least {need_w:.0f}x{need_h:.0f}px of the "
        f"{sheet.width:.0f}x{sheet.height:.0f}px sheet.{blame} Use a larger page_size, or omit "
        "page_size to fit the sheet to the drawing."
    )


# The title strip and stream table are placed by the same band arithmetic as the
# boxes the caller docked, but neither is an object of the caller's, so each
# stands in the columns as a sentinel. Naming them is what an error that has to
# say *which* piece of furniture will not fit needs.
TITLE, STREAM = "\x00title", "\x00stream"
_FURNITURE_NAMES = {TITLE: "the title strip", STREAM: "the stream table"}


def _furniture_name(obj) -> str:
    if isinstance(obj, str):
        return _FURNITURE_NAMES.get(obj, obj)
    title = getattr(obj, "title", "")
    return f"the {title!r} box" if title else "an untitled annotation box"


class SvgRenderer:
    """Renders a Flowsheet to an SVG file using manual geometry."""

    def __init__(self, registry=None):
        from pandid.render.symbols import default_registry
        self.registry = registry or default_registry

    def render(self, fs: "Flowsheet", *, jump_direction: str = "vertical",
               show_stream_table: bool = False, styling: str = "default",
               border: "str | None" = None, diagram: "str | None" = None,
               page_size: "str | None" = None, **opts) -> str:
        """Render the flowsheet to SVG.

        Parameters
        ----------
        fs : Flowsheet
            The flowsheet to render.
        jump_direction : str
            Which crossing lines get a semicircle bump: ``"vertical"`` or ``"horizontal"``.
        show_stream_table : bool
            Whether to render a stream property table on the sheet.
        border : str | None
            ``"none"`` for a plain sheet edge, ``"zone"`` for the zone-ruled
            ASME-style drawing frame. The flowsheet's title block and annotation
            boxes are drawn whichever is chosen.
        diagram : str | None
            Which drawing this is: ``"pfd"`` (the default) or ``"p&id"``, also
            spelled ``"pid"``. A P&ID draws its process lines without arrowheads.
        styling : str
            The one-word way to ask for both, and the older spelling:
            ``"p&id"`` means ``border="zone"`` with ``diagram="p&id"``.
        page_size : str | None
            Standard paper size — ``"A4"``, ``"A3"``, ``"A2"``, ``"A1"``, ``"A0"`` —
            drawn at exactly that size, with the furniture docked to the sheet edges
            and the drawing fitted into what they leave. ``None`` (the default) sizes
            the sheet to the drawing instead.
        """
        from pandid.portgeom import unit_box
        border, diagram = _resolve_sheet(styling, border, diagram)
        # ANSI/ISA-5.1 draws process piping on a P&ID as plain line. Flow
        # direction is read off the equipment and off the line list, so an
        # arrowhead at the end of every run is a PFD convention, where showing
        # where the material goes is the whole job of the line.
        arrows = diagram != "p&id"
        sheet = _page(page_size)

        # 1. Diagram bounding box — union of every unit's drawn box and every
        #    route waypoint. Furniture is placed *around* this fixed region.
        dx0 = dy0 = float("inf")
        dx1 = dy1 = float("-inf")
        for u in fs.units:
            if u.frame is None:
                raise ValueError(f"Unit '{u.name}' lacks a frame even after layout was run.")
            bx0, by0, bx1, by1 = unit_box(u, u.frame)
            dx0, dy0 = min(dx0, bx0), min(dy0, by0)
            dx1, dy1 = max(dx1, bx1), max(dy1, by1)
        for s in fs.streams:
            if s.route and s.route.waypoints:
                for px, py in s.route.waypoints:
                    dx0, dy0 = min(dx0, px), min(dy0, py)
                    dx1, dy1 = max(dx1, px), max(dy1, py)
        if not fs.units:  # empty flowsheet: fall back to the nominal page size
            nominal = sheet or _page("A3")
            assert nominal is not None
            dx0 = dy0 = 0.0
            dx1, dy1 = nominal.width, nominal.height

        # 2. Which streams get a table column (unique material streams only).
        table_streams = self._table_streams(fs) if show_stream_table else []
        st_layout = self._stream_table_layout(fs, table_streams) if table_streams else None

        # 3. Place furniture around the diagram and size the sheet.
        margin = 55.0
        furniture: list[str] = []
        # union of everything drawn (diagram + furniture), grown as boxes land
        U = [dx0, dy0, dx1, dy1]

        def grow(x0, y0, x1, y1):
            U[0], U[1] = min(U[0], x0), min(U[1], y0)
            U[2], U[3] = max(U[2], x1), max(U[3], y1)

        free = None  # region a fixed sheet leaves for the drawing
        fit_issues: list[Issue] = []

        def report(field: str, text: str, drawn: str) -> None:
            fit_issues.append(
                Issue("warning", "text-truncated",
                      f"{field} was truncated to fit its cell: "
                      f"{text!r} drawn as {drawn!r}")
                if drawn != text else
                Issue("warning", "text-overruns-cell",
                      f"{field} is wider than the cell it is drawn in: {text!r}"))

        # Furniture belongs to the sheet, not to the border: a title block or a
        # docked box is drawn because it was supplied. A zone border implies a
        # formal sheet, which carries a title strip whether one was filled in or
        # not.
        furnished = (border == "zone" or fs.title_block is not None
                     or bool(getattr(fs, "annotations", None)))
        if furnished:
            (frame_x, frame_y, canvas_width, canvas_height), free = self._place_furniture(
                fs, st_layout, dx0, dy0, dx1, dy1, furniture, sheet, border, report)
        elif sheet is not None:
            free = self._place_plain(st_layout, sheet, margin, furniture)
            frame_x, frame_y = 0.0, 0.0
            canvas_width, canvas_height = sheet.width, sheet.height
        else:
            # Plain sheet: optional stream table docked below the diagram, left.
            if st_layout:
                top = dy1 + 24
                furniture.extend(self._draw_stream_table(st_layout, dx0, top))
                grow(dx0, top, dx0 + st_layout["w"], top + st_layout["h"])
            frame_x, frame_y = U[0] - margin, U[1] - margin
            canvas_width = (U[2] - U[0]) + 2 * margin
            canvas_height = (U[3] - U[1]) + 2 * margin

        # A cell that could not hold its text is a finding about this render, so
        # it joins the validator's on ``fs.warnings``. Findings from an earlier
        # render are dropped rather than added to: a title shortened and
        # re-rendered must stop warning about the old one.
        fs.warnings = [w for w in fs.warnings
                       if getattr(w, "code", "") not in _FIT_CODES] + fit_issues

        # 4. SVG document.
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        # A named page size declares its physical size, so the sheet prints and
        # converts to PDF at exactly that ISO size instead of at whatever the
        # consumer takes a user unit to be worth. A sheet fitted to the drawing
        # has no physical size to declare and stays in user units.
        if sheet is not None:
            decl_w, decl_h = f"{sheet.width_mm:g}mm", f"{sheet.height_mm:g}mm"
        else:
            decl_w, decl_h = f"{canvas_width:.0f}", f"{canvas_height:.0f}"
        lines.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{decl_w}" height="{decl_h}" '
            f'viewBox="{frame_x:.1f} {frame_y:.1f} {canvas_width:.1f} {canvas_height:.1f}">'
        )
        lines.append('  <!-- Background -->')
        lines.append(f'  <rect x="{frame_x:.1f}" y="{frame_y:.1f}" width="{canvas_width:.1f}" height="{canvas_height:.1f}" fill="white" />')

        # Furniture (border + title strip + boxes) sits behind the diagram.
        for item in furniture:
            lines.append("    " + item)

        lines.extend(self._defs(fs, arrows))
        unit_labels: list = []
        balloons: list = []
        drawing = self._draw_units(fs, unit_labels, balloons)
        drawing.extend(self._draw_streams(fs, jump_direction, unit_labels, arrows))
        # Instrumentation goes on over the lines: an impulse line runs from the
        # tap to the balloon, and the balloon's opaque body then knocks out both
        # it and any process line an in-line element straddles.
        drawing.extend(self._draw_taps(fs))
        if balloons:
            drawing.append('  <g id="instruments">')
            drawing.extend(balloons)
            drawing.append('  </g>')
        # Equipment tags go on last, haloed, so no stream line strikes through them.
        drawing.extend(self._draw_unit_labels(unit_labels))

        if free is None:
            lines.extend(drawing)
        else:  # a fixed sheet: the drawing is fitted into what the furniture leaves
            lines.append(f'  <g id="drawing" transform="{self._fit(dx0, dy0, dx1, dy1, free)}">')
            lines.extend(drawing)
            lines.append('  </g>')
        lines.append('</svg>')
        return "\n".join(lines)

    def _fit(self, dx0, dy0, dx1, dy1, free) -> str:
        """Transform centring the drawing in *free* at a uniform scale."""
        fx, fy, fw, fh = free
        dw, dh = dx1 - dx0, dy1 - dy0
        s = _fit_scale(dw, dh, free)
        return (f"translate({_num(fx + (fw - s * dw) / 2 - s * dx0)}, "
                f"{_num(fy + (fh - s * dh) / 2 - s * dy0)}) scale({s:.6g})")

    # ------------------------------------------------------------------ furniture

    def _place_furniture(self, fs, st_layout, dx0, dy0, dx1, dy1, furniture, sheet,
                         border, report=None):
        """Dock furniture flush to the sheet *frame* (not the drawing), and rule
        that frame into zones when the sheet asked for a border.

        Boxes are grouped into edge *bands* by ``align``; the frame grows
        outward from the diagram bounds just enough to hold them, and each box
        is placed flush against the frame edge its ``align`` names (inset by its
        ``margin``). A box with an explicit ``position`` is hand-placed instead.
        Given a *sheet*, the frame is instead the fixed page inset by the border,
        and the drawing is fitted into the region the bands leave.

        Returns the outer canvas rect ``(x, y, w, h)`` and that free region
        ``(x, y, w, h)`` — ``None`` when the frame was grown to the drawing.
        """
        from pandid.document import TitleBlock, TableBox, _ALIGN

        INNER, GAP, SEP, OUT = 26.0, 14.0, 18.0, 8.0

        def measure(a):
            return F.measure_table(a) if isinstance(a, TableBox) else F.measure_annotation(a)

        def draw_box(a, x, y):
            furniture.extend(F.draw_table(a, x, y) if isinstance(a, TableBox)
                             else F.draw_annotation(a, x, y, report=report))

        # Title strip + stream table are bottom furniture. Represent them as
        # sentinel "boxes" (see TITLE / STREAM) at the foot of the bottom-right
        # / bottom-left columns so the band maths sizes the frame around them
        # too.
        strip = fs.title_block is not None or border == "zone"
        tb = fs.title_block or TitleBlock()
        ts_w, ts_h = F.measure_title_strip(tb)
        date = tb.date or datetime.now().strftime("%Y-%m-%d")
        name = tb.title or fs.name

        cols: dict[str, list] = {k: [] for k in _ALIGN}
        positioned: list = []
        for a in getattr(fs, "annotations", []) or []:
            w, h = measure(a)
            if a.position is not None:
                positioned.append((a, a.position[0], a.position[1], w, h))
            else:
                cols[a.align].append((a, w, h))
        if strip:
            cols["bottom-right"].append((TITLE, ts_w, ts_h))
        if st_layout:
            cols["bottom-left"].append((STREAM, st_layout["w"], st_layout["h"]))

        def stack_h(items):
            return sum(h for _, _, h in items) + GAP * max(0, len(items) - 1)

        def stack_w(items):
            return max((w for _, w, _ in items), default=0.0)

        def biggest(dim: int) -> str:
            """Name the largest piece of furniture on the sheet along ``dim``
            (1 = width, 2 = height), for an error that has to say which piece
            will not fit rather than that something will not."""
            items = [it for col in cols.values() for it in col]
            if not items:
                return ""
            return _furniture_name(max(items, key=lambda it: it[dim])[0])

        # --- band thicknesses -------------------------------------------------
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

        # --- frame rectangle --------------------------------------------------
        if sheet is not None:
            # A named page fixes the frame: the sheet inset by the zone band and
            # the margin outside it, so the border rules to the sheet edges and
            # the zone count does not drift with the drawing.
            edge = OUT + F.ZONE_BAND
            need_w = max(band_w, left_w + right_w + 2 * INNER)
            need_h = max(top_h + bottom_h + 2 * INNER,
                         stack_h(cols["left"]), stack_h(cols["right"]))
            too_wide = need_w >= sheet.width - 2 * edge
            if too_wide or need_h >= sheet.height - 2 * edge:
                raise _too_small(sheet, need_w + 2 * edge, need_h + 2 * edge,
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

        # The bands are measured, so the region left for the drawing is settled
        # and so is the ratio it will be placed at: the number the title strip's
        # scale cell reports. A frame grown to the drawing has no fixed page and
        # so no scale to state.
        free = None if sheet is None else (
            ix + left_w + INNER, iy + top_h + INNER,
            iw - left_w - right_w - 2 * INNER, ih - top_h - bottom_h - 2 * INNER)
        fit = "" if free is None else _scale_text(
            _fit_scale(dx1 - dx0, dy1 - dy0, free))

        # --- place each column flush to the frame -----------------------------
        def x_for(mode, w, m):
            if mode == "l":
                return ix + m
            if mode == "r":
                return ixr - m - w
            return ix + (iw - w) / 2  # centred on the frame

        def place(obj, x, y, w, h):
            if obj is TITLE:
                furniture.extend(
                    F.draw_title_strip(tb, name, date, x + w, y + h, fit_scale=fit,
                                       report=report))
            elif obj is STREAM:
                furniture.extend(self._draw_stream_table(st_layout, x, y))
            else:
                draw_box(obj, x, y)

        def draw_top(items, mode):     # flush to the top edge, grow downward
            y = iy
            for obj, w, h in items:
                m = getattr(obj, "margin", 0.0)
                place(obj, x_for(mode, w, m), y + m, w, h)
                y += m + h + GAP

        def draw_bottom(items, mode):  # flush to the bottom edge, grow upward
            y = iyb
            for obj, w, h in reversed(items):
                m = getattr(obj, "margin", 0.0)
                top = y - m - h
                place(obj, x_for(mode, w, m), top, w, h)
                y = top - GAP

        def draw_side(items, mode):    # flush to a side edge, vertically centred
            y = (iy + iyb) / 2 - stack_h(items) / 2
            for obj, w, h in items:
                m = getattr(obj, "margin", 0.0)
                place(obj, x_for(mode, w, m), y, w, h)
                y += h + GAP

        draw_top(cols["top-left"], "l")
        draw_top(cols["top"], "c")
        draw_top(cols["top-right"], "r")
        draw_bottom(cols["bottom-left"], "l")
        draw_bottom(cols["bottom"], "c")
        draw_bottom(cols["bottom-right"], "r")
        draw_side(cols["left"], "l")
        draw_side(cols["right"], "r")
        cy = (iy + iyb) / 2 - stack_h(cols["center"]) / 2  # dead-centre overlay
        for obj, w, h in cols["center"]:
            place(obj, ix + (iw - w) / 2, cy, w, h)
            cy += h + GAP

        # --- hand-placed boxes; expand the frame to keep them inside ----------
        for a, px, py, w, h in positioned:
            draw_box(a, px, py)
            if sheet is not None:  # the page is fixed; absolute means absolute
                continue
            ix, iy = min(ix, px - INNER), min(iy, py - INNER)
            ixr, iyb = max(ixr, px + w + INNER), max(iyb, py + h + INNER)
        iw, ih = ixr - ix, iyb - iy

        # --- border around the frame, then the sheet edge ---------------------
        if border == "zone":
            frame_lines, outer = F.zone_frame(ix, iy, iw, ih)
            furniture[:0] = frame_lines  # border sits behind the boxes
        else:
            outer = F.sheet_rect(ix, iy, iw, ih)
        ox, oy, ow, oh = outer
        return (ox - OUT, oy - OUT, ow + 2 * OUT, oh + 2 * OUT), free

    def _place_plain(self, st_layout, sheet, margin, furniture):
        """Fixed page carrying no furniture of its own: the stream table docks to
        the foot of the sheet and the drawing takes the region above it. Returns
        that region."""
        free_w = sheet.width - 2 * margin
        free_h = sheet.height - 2 * margin
        table_h = (st_layout["h"] + 24) if st_layout else 0.0
        if free_w <= 0 or free_h - table_h <= 0 or (st_layout and st_layout["w"] > free_w):
            raise _too_small(sheet,
                             2 * margin + (st_layout["w"] if st_layout else 0.0),
                             2 * margin + table_h,
                             "the stream table" if st_layout else "")
        if st_layout:
            furniture.extend(self._draw_stream_table(
                st_layout, margin, sheet.height - margin - st_layout["h"]))
        return (margin, margin, free_w, free_h - table_h)

    @staticmethod
    def _cell_text(s, key) -> str:
        """What one stream's cell draws for one property row.

        The single place the placeholder for a missing value is decided, so the
        column that is *measured* is the column that is drawn.
        """
        val = s.properties.get(key, "-")
        return "-" if val in (None, "") else str(val)

    def _table_streams(self, fs):
        streams, seen = [], set()
        for s in fs.streams:
            if s.kind in _SIGNAL_KINDS or s.name in seen:
                continue
            seen.add(s.name)
            streams.append(s)
        return streams

    def _stream_table_layout(self, fs, streams):
        # property rows in first-seen order (dict preserves insertion order)
        order, seen = [], set()
        for s in streams:
            for k in s.properties:
                if k not in seen:
                    seen.add(k)
                    order.append(k)
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
        # The corner cell has to be true of every column under it, so the table
        # only calls itself a line-number table when every line drawn in it is
        # identified that way.
        heading = ("Line Number" if all(s.has_line_number for s in streams)
                   else "Stream Number")

        # Every column is sized to what goes in it. The table's width is a
        # layout *output* — it is placed at whatever it measures, and the sheet
        # is grown or the page is refused around it — so there is no fixed cell
        # here to abbreviate into: a stream table that cannot show
        # "0.0441 kg/kg total" is not a stream table. A minimum keeps a table of
        # short values from ruling columns too narrow to read as columns.
        GUTTER = 14.0                     # the same either side of any cell
        labels = [heading] + [key for kind, key in disp if kind == "data"]
        label_w = max(122.0, max(F.text_width(t, size, bold=True)
                                 for t in labels) + GUTTER)
        values = [self._cell_text(s, key) for kind, key in disp if kind == "data"
                  for s in streams]
        name_w = max(52.0,
                     max((F.text_width(s.name, size, bold=True) for s in streams),
                         default=0.0) + GUTTER,
                     max((F.text_width(v, size) for v in values), default=0.0) + GUTTER)
        # A section header spans the whole table, so it is the total width it
        # constrains rather than any one column; the row label column is the
        # only one free to take up the slack.
        sections = [label for kind, label in disp if kind == "section"]
        span = max((F.text_width(t, size, bold=True) for t in sections),
                   default=0.0) + GUTTER
        label_w = max(label_w, span - name_w * n)
        return dict(streams=streams, disp=disp, size=size, row_h=row_h,
                    label_w=label_w, name_w=name_w, heading=heading,
                    w=label_w + name_w * n, h=row_h * (1 + len(disp)))

    def _draw_stream_table(self, L, left, top):
        streams = L["streams"]
        size, row_h, label_w, name_w = L["size"], L["row_h"], L["label_w"], L["name_w"]
        out = ['<g id="stream_table">']

        def cell(x, y, w, text, *, fill, bold=False, anchor="middle"):
            out.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{row_h:.1f}" '
                       f'fill="{fill}" stroke="black" stroke-width="0.75"/>')
            if anchor == "start":
                tx = x + 5
            elif anchor == "end":
                tx = x + w - 5
            else:
                tx = x + w / 2
            wt = ' font-weight="bold"' if bold else ''
            out.append(f'  <text x="{tx:.1f}" y="{y + row_h / 2 + size / 3:.1f}" '
                       f'font-family="{F.FONT}" font-size="{size:.1f}"{wt} '
                       f'text-anchor="{anchor}">{html.escape(str(text))}</text>')

        # header row: the corner heading + each stream's number or line number
        y = top
        cell(left, y, label_w, L["heading"], fill="#eee", bold=True, anchor="start")
        cx = left + label_w
        for s in streams:
            cell(cx, y, name_w, s.name, fill="#eee", bold=True)
            cx += name_w
        y += row_h
        for kind, key in L["disp"]:
            if kind == "section":
                cell(left, y, label_w + name_w * len(streams), key,
                     fill="#f4f4f4", bold=True, anchor="start")
                y += row_h
                continue
            cell(left, y, label_w, key, fill="#f9f9f9", bold=True, anchor="start")
            cx = left + label_w
            for s in streams:
                cell(cx, y, name_w, self._cell_text(s, key), fill="white")
                cx += name_w
            y += row_h
        out.append('</g>')
        return out

    # ------------------------------------------------------------------ defs

    def _text_xform(self, u) -> tuple[int, bool, bool]:
        """The placement transform a unit's symbol definition must bake in.

        The identity for every symbol without lettering of its own, so those
        keep sharing one definition and one id no matter how they are placed.
        """
        sym = self.registry.for_unit(u)
        f = getattr(u, "frame", None)
        if f is None or "<text" not in sym.svg:
            return (0, False, False)
        return (int(getattr(f, "orientation", 0) or 0),
                bool(f.mirrored), bool(getattr(f, "mirror_y", False)))

    def _sym_id(self, u) -> str:
        """The ``<defs>`` id a unit's ``<use>`` points at.

        One definition per ``(kind, variant)``, plus a suffix for whatever else
        is baked into the definition rather than applied by the ``<use>``: the
        size a built-to-measure symbol was drawn at, and the counter-rotation
        that keeps a symbol's own lettering readable.
        """
        variant = getattr(u, 'variant', 'default')
        sym_id = f"sym_{u.kind}" if variant == "default" else f"sym_{u.kind}_{variant}"
        sym_id += self.registry.for_unit(u).id_suffix
        return sym_id + _xform_tag(*self._text_xform(u))

    def _defs(self, fs, arrows=True):
        lines = []
        # Sorted, not raw set order: set iteration depends on the process hash
        # seed, so an identical flowsheet would otherwise emit byte-different
        # SVG from run to run — breaking diffs, caching and golden tests.
        used_colors = sorted({s.color or "black" for s in fs.streams})
        lines.append('  <defs>')
        # A sheet that draws no arrowhead defines none: the only lines that ever
        # wore one are the process lines, so on a P&ID the whole set is dead.
        for c in used_colors if arrows else ():
            marker_id = f'arrow_{c.replace("#", "").replace(" ", "_")}'
            lines.append(
                f'    <marker id="{marker_id}" viewBox="0 0 10 10" refX="10" refY="5" '
                f'markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
            )
            lines.append(f'      <path d="M 0 0 L 10 5 L 0 10 z" fill="{c}" />')
            lines.append('    </marker>')

        # A symbol carrying its own lettering needs one definition per placement
        # transform in use, since the counter-transform that keeps the letters
        # readable is baked into the definition; a symbol built to measure needs
        # one per size, so the box it is placed in is the box it was drawn in and
        # the scale factor stays exactly 1. Everything else — the great majority
        # — still shares a single definition however it is placed.
        used: dict[tuple, tuple] = {}
        # Definitions some placement asks to fill a box of another shape. A
        # <symbol> scales its viewBox to fit and centres what is left over, so a
        # unit given a width and height of its own is drawn smaller than the box
        # with whitespace down one pair of sides -- and portgeom, which maps its
        # ports linearly onto the box, then puts them out in that whitespace.
        # The two are made to agree by stretching the artwork instead, wherever
        # the symbol says it may be (see Symbol.stretchable); where it may not,
        # portgeom follows the letterbox and the ports land on the drawing.
        stretched: set[tuple] = set()
        for u in fs.units:
            if u.kind in ("feed", "product"):
                continue
            sym = self.registry.for_unit(u)
            xform = self._text_xform(u)
            key = (u.kind, getattr(u, 'variant', 'default'), sym.id_suffix) + xform
            used[key] = (self._sym_id(u), sym, *xform)
            if sym.stretchable and _reshapes(sym, u):
                stretched.add(key)
        for key in sorted(used):
            sym_id, sym, rot, mirror_x, mirror_y = used[key]
            svg_str = _upright_text(sym.svg, rot, mirror_x, mirror_y)
            if svg_str.startswith('<g'):
                inner = svg_str[svg_str.find('>') + 1:svg_str.rfind('</g>')]
                # preserveAspectRatio: stated only where a placement reshapes the
                # artwork, since "none" and the "xMidYMid meet" default are the
                # same drawing whenever the scale is uniform -- and a definition
                # nothing reshapes has nothing to say about being reshaped.
                fill = ' preserveAspectRatio="none"' if key in stretched else ''
                # overflow="visible": a <symbol> viewport defaults to overflow:hidden,
                # which clips the outer half of any stroke whose geometry sits on the
                # viewBox edge (e.g. an ellipse with rx == w/2). That makes a circle
                # render thin at its four cardinal points while the diagonals stay full
                # weight. Letting the symbol overflow keeps every stroke at uniform width.
                svg_str = (f'<symbol id="{sym_id}" viewBox="0 0 {sym.width} {sym.height}"'
                           f'{fill} overflow="visible">{inner}</symbol>')
            else:
                svg_str = re.sub(r'id="[^"]+"', f'id="{sym_id}"', svg_str, count=1)
            lines.append(f'    {svg_str}')
        lines.append('  </defs>')
        return lines

    # ------------------------------------------------------------------ units

    def _draw_units(self, fs, label_items, balloons):
        lines = ['  <g id="units">']
        for u in fs.units:
            f = u.frame
            out = balloons if u.kind == "instrument" else lines
            x, y = f.x, f.y
            # The tag, not the name: a symbol that repeats — a trip square, a
            # utility header flag — is drawn with the tag it shares and named
            # apart only so the flowsheet can address each drawing of it.
            safe_name = html.escape(u.tag)

            if u.kind in ("feed", "product"):
                lines.extend(self._draw_boundary(u, f, x, y, safe_name))
                continue

            sym_id = self._sym_id(u)
            u_width, u_height = f.w, f.h
            rot = int(getattr(f, "orientation", 0) or 0)
            mirror_x, mirror_y = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
            cx, cy = x + u_width / 2, y + u_height / 2

            # A quarter turn swaps the box the artwork is drawn into; place that
            # box centred on the frame so rotating it about the centre lands it
            # back on the frame exactly.
            if rot in (90, 270):
                bw, bh = u_height, u_width
            else:
                bw, bh = u_width, u_height
            ux, uy = cx - bw / 2, cy - bh / 2

            # Composed right-to-left by SVG, so this reads "mirror, then rotate"
            # — the same order portgeom.symbol_to_box uses for the ports.
            ops = []
            if rot:
                ops.append(f"rotate({rot}, {_num(cx)}, {_num(cy)})")
            if mirror_x:
                ops.append(f"translate({_num(2 * cx)}, 0) scale(-1, 1)")
            if mirror_y:
                ops.append(f"translate(0, {_num(2 * cy)}) scale(1, -1)")
            transform = f' transform="{" ".join(ops)}"' if ops else ""
            out.append(f'    <use href="#{sym_id}" x="{_num(ux)}" y="{_num(uy)}" '
                       f'width="{bw}" height="{bh}"{transform} />')

            if u.kind == "instrument":
                out.extend(self._draw_instrument_tag(u, x, y, u_width, u_height))
            else:
                # A symbol that carries no tag is labelled nowhere. Only the
                # pipe tee is such a symbol today: it is bare pipe, and an
                # issued sheet writes nothing against a junction.
                if u.tag:
                    label_items.append(
                        self._unit_label_item(u, f, x, y, u_width, u_height, safe_name))
                # A body that cannot carry the darkening says so in letters
                # instead; see ISO 15519-1 §11.4.5 and _nc_label_item.
                if closed_marking(u, self.registry) == "NC":
                    label_items.append(
                        self._nc_label_item(u, f, x, y, u_width, u_height))
                # Where an actuated valve goes when its air or power is lost.
                # A separate question from the one above, in a separate corner;
                # see ISA-5.1 Table 5.4.4 and _fail_label_item.
                letters = fail_marking(u)
                if letters:
                    label_items.append(
                        self._fail_label_item(u, f, x, y, u_width, u_height, letters))
        lines.append('  </g>')
        return lines

    def _draw_taps(self, fs):
        """Impulse lines: the fine line from a tap point to the balloon reading it.

        A process tap is a solid fine line; a balloon hung off another balloon
        (an interlock under its controller) is an internal loop connection and
        is drawn dashed. Nothing is drawn where a stream already joins the two,
        or where the element sits directly on the line (``offset=0``).

        Fine is the same fine as a signal stream: ISO 15519-2 Annex A.1.02 puts
        an instrument connection on the 0,25 rung, alongside the signal line and
        half the pipeline it taps. See :data:`_SIGNAL_STROKE`.
        """
        from pandid.layout.attach import is_attached

        wired = {(id(s.source.owner), id(s.dest.owner)) for s in fs.streams}
        out = []
        for u in fs.units:
            tap = getattr(u, "tap", None)
            if not is_attached(u) or tap is None or u.frame is None:
                continue
            host = u.host
            if (id(u), id(host)) in wired or (id(host), id(u)) in wired:
                continue
            tx, ty = tap
            cx, cy = u.frame.cx, u.frame.cy
            if abs(cx - tx) < 0.5 and abs(cy - ty) < 0.5:
                continue
            dash = ' stroke-dasharray="5,4"' if getattr(host, "kind", "") == "instrument" else ""
            out.append(f'    <line x1="{_num(tx)}" y1="{_num(ty)}" x2="{_num(cx)}" '
                       f'y2="{_num(cy)}" stroke="black" stroke-width="{_SIGNAL_STROKE}"{dash} />')
        return ['  <g id="instrument_taps">'] + out + ['  </g>'] if out else []

    def _draw_boundary(self, u, f, x, y, safe_name):
        """Feed / Product off-page connector flag, with an optional second line
        referencing the drawing the stream comes from / goes to."""
        label_w = f.w
        ref = getattr(u, "reference", "") or ""
        if u.kind == "feed":
            if f.mirrored:
                px0, px1, px2 = x + label_w, x + 15, x
                tx = x + 15 + (label_w - 15) / 2
            else:
                px0, px1, px2 = x + 50 - label_w, x + 50 - 15, x + 50
                tx = px0 + (label_w - 15) / 2
        else:  # product
            if f.mirrored:
                px0, px1, px2 = x + label_w, x + 15, x
                tx = x + 15 + (label_w - 15) / 2
            else:
                px0, px1, px2 = x, x + label_w - 15, x + label_w
                tx = px0 + (label_w - 15) / 2
        # slightly taller flag so two lines of text fit, centered on the port (y+25)
        top, bot = (y + 12, y + 38) if ref else (y + 15, y + 35)
        points = f"{px0},{top} {px1},{top} {px2},{y + 25} {px1},{bot} {px0},{bot}"
        out = [f'    <polygon points="{points}" fill="transparent" stroke="black" stroke-width="2" />']
        if ref:
            out.append(f'    <text x="{tx}" y="{y + 21}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
            out.append(f'    <text x="{tx}" y="{y + 33}" font-family="sans-serif" font-size="10.5" text-anchor="middle" dominant-baseline="middle" fill="#333">{html.escape(ref)}</text>')
        else:
            out.append(f'    <text x="{tx}" y="{y + 25}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
        return out

    def _draw_instrument_tag(self, u, x, y, u_width, u_height):
        """Functional letters over the bare loop number, as ISA-5.1 draws them.

        An interlock square carries the number alone — its letters are only the
        tag prefix, and a real sheet leaves the square holding one figure.
        """
        from pandid.units import split_tag

        variant = getattr(u, "variant", "default")
        # The tag, not the name: a repeated square is drawn with the tag it
        # shares and named apart only so the flowsheet can address it.
        tag = getattr(u, "tag", "") or u.name
        top, bot = split_tag(getattr(u, "type", "") or tag, getattr(u, "number", "") or "")
        cx, cy = x + u_width / 2, y + u_height / 2
        if variant in _DIAMOND_BALLOONS:
            # A diamond is widest on its horizontal diagonal and narrows to
            # nothing at the bottom vertex, so the number cannot simply be
            # centred in the box the way the old bare square's was: it goes in
            # the lower half, where ISA-5.1 draws it under the interlock
            # designator, but only as far down as the sloping sides still leave
            # it room. Seven units below the middle of a 40 box is where a
            # two-figure number's bottom corners clear the edges; it is set at
            # the balloons' own number size, being the same loop number they
            # carry.
            return [f'    <text x="{cx}" y="{cy + 7}" font-family="sans-serif" '
                    f'font-size="11" text-anchor="middle" '
                    f'dominant-baseline="middle">{html.escape(bot or top)}</text>']
        if not top:
            return [f'    <text x="{cx}" y="{cy}" font-family="sans-serif" '
                    f'font-size="12" text-anchor="middle" '
                    f'dominant-baseline="middle">{html.escape(bot or top)}</text>']
        # The location bar is what the balloon says about *where* the instrument
        # lives, and it is drawn across the middle — exactly where the letters
        # would otherwise sit. ISA-5.1 puts the letters wholly above the bar and
        # the number wholly below, so a barred variant needs the pair pushed
        # apart to leave the band clear.
        letters_dy, number_dy = (-10, 11) if variant in _BARRED_BALLOONS else (-4, 10)
        out = [f'    <text x="{cx}" y="{cy + letters_dy}" font-family="sans-serif" '
               f'font-size="12" font-weight="bold" text-anchor="middle" '
               f'dominant-baseline="middle">{html.escape(top.upper())}</text>']
        if bot:
            out.append(f'    <text x="{cx}" y="{cy + number_dy}" font-family="sans-serif" '
                       f'font-size="11" text-anchor="middle" '
                       f'dominant-baseline="middle">{html.escape(bot)}</text>')
        return out

    def _label_place(self, lpos, x, y, u_width, u_height):
        """Where a label on side ``lpos`` of a unit's box goes, and how it sets."""
        if lpos == "bottom":
            return x + u_width / 2, y + u_height + 15, "middle", "middle"
        if lpos == "left":
            return x - 10, y + u_height / 2, "end", "middle"
        if lpos == "right":
            return x + u_width + 10, y + u_height / 2, "start", "middle"
        if lpos == "center":
            return x + u_width / 2, y + u_height / 2, "middle", "middle"
        if lpos == "top_right":
            # Above the symbol *and to the right*: the text starts at the box's
            # right edge on the same baseline a top label sets on. Only the NC
            # marking is placed here; see :meth:`_nc_label_item`.
            return x + u_width, y - 10, "start", "baseline"
        return x + u_width / 2, y - 10, "middle", "baseline"  # top

    def _unit_label_item(self, u, f, x, y, u_width, u_height, safe_name):
        """Resolve a unit label's placement. Drawn in a final pass (see
        :meth:`_draw_unit_labels`) so stream lines never strike through it."""
        lpos = f.label_pos or "top"
        return (*self._label_place(lpos, x, y, u_width, u_height), lpos, safe_name)

    def _nc_label_item(self, u, f, x, y, u_width, u_height):
        """The ``NC`` abbreviation, for a valve whose body cannot be darkened.

        **ISO 15519-1 §11.4.5** governs the letters: the state "may be indicated
        by adding the letter symbol NC *Normal closed* or NO *Normal open*
        **above the symbol and to the right**, as indicated in Figure 28". The
        figure draws it on an unfilled bowtie with the letters starting at about
        the valve's right-hand edge, clear above the run.

        The corner is fixed, not chosen from the valve's quarter turn. Reading
        the marking always in the same place is what lets someone scan a sheet
        for closed valves, and the upper right is the corner an equipment tag is
        least likely to be in already: the default tag sits centred *above*.

        This departs from PIP PIC001 4.2.2.8, which puts the letters below a
        horizontal valve and to the right of a vertical one, and which is where
        the darkened body of 4.2.2.7 still comes from. The two conventions are
        answering different questions and are taken from different sources on
        purpose: PIP is the only standard that fills a valve body, and ISO
        15519-1 is the only one that letters it. See
        :func:`pandid.render.symbols.closed_marking`.

        Where the equipment tag already reaches into that corner, the
        abbreviation steps past it rather than over it. Both are drawn on opaque
        halos in the same final pass, so the second one down would otherwise
        erase the first.
        """
        item = (*self._label_place("top_right", x, y, u_width, u_height), "top_right", "NC")
        tag = _unit_label_box(self._unit_label_item(
            u, f, x, y, u_width, u_height, html.escape(u.tag)))
        nc = _unit_label_box(item)
        if tag is not None and nc is not None and (
                tag[0] < nc[2] and tag[2] > nc[0] and tag[1] < nc[3] and tag[3] > nc[1]):
            lx, ly, anchor, baseline, lpos, text = item
            item = (lx + tag[2] - nc[0] + 6, ly, anchor, baseline, lpos, text)
        return item

    def _fail_label_item(self, u, f, x, y, u_width, u_height, letters):
        """The fail position, in letters, beside the valve body.

        The letters are **ANSI/ISA-5.1-2009 Table 5.4.4** Method B, which **PIP
        PIC001 clause 4.5.3.2** requires over the standard's own Method A stem
        arrows. See :func:`pandid.render.symbols.fail_marking`.

        **PIP PIC001 clause 4.2.4.6(1)** places them, and is followed exactly:
        *"Control valve failure action abbreviation shall be shown at 0.06 inch
        directly below the control valve in horizontal lines and 0.06 inch to
        the right of the control valve in vertical lines."*

        The quarter turn therefore moves these letters, where it does not move
        the ``NC`` abbreviation (:meth:`_nc_label_item`), and the two are not
        inconsistent: they are the same principle applied to marks that live in
        different places. ``NC`` sits in a *corner*, and a corner is free
        whichever way a valve is laid, so fixing it lets a reader scan for one
        thing in one place. These letters sit against a *face*, and which face
        is free is exactly what the quarter turn changes: the face below a valve
        on a horizontal run is clear, and the face below the same valve on a
        riser is its outlet nozzle with the line running out of it. PIP's rule
        is the geometry, not a style, which is why it is taken whole.

        The remaining sides are spoken for either way. Every valve symbol here
        draws its actuator on **top** and the controller output or interlock
        lands there, so the space above the body belongs to the signal line and
        to the default equipment tag; the upper right corner is the ``NC``
        abbreviation's, fixed there by ISO 15519-1 §11.4.5. A valve stating both
        of the two things it can state about its position states them in two
        places that cannot collide.

        Where the equipment tag is already on the side the letters want -- which
        the engine chooses freely, and does choose the right-hand side for a
        valve on a riser -- the letters step past it along that same side rather
        than over it. Both are drawn on opaque halos in the same final pass, so
        the second one down would otherwise erase the first.

        Nothing steps past a *neighbouring* unit, which is the one case to place
        around by hand. ``pin(mirrored="y")`` turns a valve's artwork over and
        puts its actuator underneath, so its signal lead then arrives through
        the space PIP reserves for these letters; a balloon hung directly below
        such a valve is in the same space. Neither is a placement the standard
        contemplates, since it words the rule for an actuator drawn on top. Put
        the balloon on another side, or leave the valve the way up its symbol is
        drawn.
        """
        # 90 and 270 both stand the run on end; 0 and 180 both leave it flat.
        upright = int(getattr(f, "orientation", 0) or 0) in (90, 270)
        lpos = "right" if upright else "bottom"
        item = (*self._label_place(lpos, x, y, u_width, u_height), lpos, letters)
        tag = _unit_label_box(self._unit_label_item(
            u, f, x, y, u_width, u_height, html.escape(u.tag)))
        fail = _unit_label_box(item)
        if tag is not None and fail is not None and (
                tag[0] < fail[2] and tag[2] > fail[0] and tag[1] < fail[3] and tag[3] > fail[1]):
            lx, ly, anchor, baseline, lpos, text = item
            # Step along the axis the side runs off, by the overlap plus a gap.
            # Sideways is the six _nc_label_item steps by, being the same move;
            # downwards is tighter, because a halo is 15 tall against 12 of text
            # and so already carries a margin the horizontal one does not.
            if upright:
                item = (lx + tag[2] - fail[0] + 6, ly, anchor, baseline, lpos, text)
            else:
                item = (lx, ly + tag[3] - fail[1] + 4, anchor, baseline, lpos, text)
        return item

    def _draw_unit_labels(self, items):
        """Final pass: equipment tags on white halos, over every stream line.

        Labels are placed on a free face where one exists, but a passing stream
        (or a unit whose every face carries a nozzle) can still run behind the
        text — the halo keeps the tag legible either way. A ``center`` label
        sits inside its symbol, so it gets no halo that would erase detail.
        """
        out = ['  <g id="unit_labels">']
        for item in items:
            lx, ly, anchor, baseline, _, text = item
            box = _unit_label_box(item)
            if box is not None:
                rx, ry, rx1, ry1 = box
                out.append(f'    <rect x="{rx:.1f}" y="{ry:.1f}" width="{rx1 - rx:.1f}" '
                           f'height="{ry1 - ry:.1f}" fill="white" />')
            out.append(f'    <text x="{lx}" y="{ly}" font-family="sans-serif" '
                       f'font-size="12" text-anchor="{anchor}" '
                       f'dominant-baseline="{baseline}">{text}</text>')
        out.append('  </g>')
        return out

    # ------------------------------------------------------------------ streams

    def _tipped(self, s, arrows: bool) -> bool:
        """Does this stream wear an arrowhead at its far end?

        Three things say no. A P&ID draws none at all (``arrows``). A signal
        line never carried one on either drawing. And a stream that ends at a
        symbol drawn as bare pipe has not arrived anywhere: a tee is a point on
        a line where the line divides, and the run carries straight on past it,
        so a head there reads as flow stopping in the middle of an unbroken
        run. The question is about the artwork rather than about the class, so
        it is the symbol that answers it (see ``Symbol.bare_run``): every
        in-line device that draws a body, a valve or a reducer or a fitting,
        gives the head something to land against and keeps it.

        A stream *leaving* a junction is untouched. It gets its head at its own
        destination, which is wherever the branch or the run actually ends.
        """
        if not arrows or s.kind in _SIGNAL_KINDS:
            return False
        dest = s.dest.owner
        return not self.registry.for_unit(dest).bare_run

    def _draw_streams(self, fs, jump_direction, unit_labels, arrows=True):
        from pandid.portgeom import port_point, unit_box

        stream_geoms, horizontals, verticals = [], [], []
        for s in fs.streams:
            src_u, dst_u = s.source.owner, s.dest.owner
            sx, sy = port_point(src_u, src_u.frame, s.source.name)
            dx, dy = port_point(dst_u, dst_u.frame, s.dest.name)
            points = [(sx, sy)] + (s.route.waypoints if s.route and s.route.waypoints else []) + [(dx, dy)]

            simplified = [points[0]]
            for i in range(1, len(points) - 1):
                p_prev, p_curr, p_next = simplified[-1], points[i], points[i + 1]
                if (p_prev[0] == p_curr[0] == p_next[0]) or (p_prev[1] == p_curr[1] == p_next[1]):
                    continue
                simplified.append(p_curr)
            simplified.append(points[-1])
            points = simplified
            stream_geoms.append((s, points))
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                if y1 == y2:
                    horizontals.append((min(x1, x2), max(x1, x2), y1))
                elif x1 == x2:
                    verticals.append((x1, min(y1, y2), max(y1, y2)))

        lines = ['  <g id="streams">']
        labeled_names: set = set()
        label_items: list = []   # (tx, ty, name, color) — drawn last, over every line
        _SIGNAL_DASH = {"electric": "7,4", "data": "9,3,2,3", "software": "9,3,2,3",
                        "capillary": "3,3"}
        for s, points in stream_geoms:
            color = s.color or "black"
            marker_id = f'arrow_{color.replace("#", "").replace(" ", "_")}'
            is_signal = s.kind in _SIGNAL_KINDS
            dash = ""
            if s.dasharray:
                dash = f' stroke-dasharray="{s.dasharray}"'
            elif s.kind in _SIGNAL_DASH:
                dash = f' stroke-dasharray="{_SIGNAL_DASH[s.kind]}"'

            longest_seg, max_len = None, -1
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                seg = abs(x2 - x1) + abs(y2 - y1)
                if seg > max_len:
                    max_len, longest_seg = seg, ((x1, y1), (x2, y2))

            d_parts = [f"M {points[0][0]},{points[0][1]}"]
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                if jump_direction == "vertical" and x1 == x2:
                    crossings = [hy for mnx, mxx, hy in horizontals if mnx < x1 < mxx and min(y1, y2) < hy < max(y1, y2)]
                    crossings.sort(reverse=(y1 > y2))
                    for hy in crossings:
                        if y1 < y2:
                            d_parts.extend([f"L {x1},{hy - 5}", f"A 5 5 0 0 1 {x1},{hy + 5}"])
                        else:
                            d_parts.extend([f"L {x1},{hy + 5}", f"A 5 5 0 0 1 {x1},{hy - 5}"])
                    d_parts.append(f"L {x2},{y2}")
                elif jump_direction == "horizontal" and y1 == y2:
                    crossings = [vx for vx, my, My in verticals if my < y1 < My and min(x1, x2) < vx < max(x1, x2)]
                    crossings.sort(reverse=(x1 > x2))
                    for vx in crossings:
                        if x1 < x2:
                            d_parts.extend([f"L {vx - 5},{y1}", f"A 5 5 0 0 1 {vx + 5},{y1}"])
                        else:
                            d_parts.extend([f"L {vx + 5},{y1}", f"A 5 5 0 0 1 {vx - 5},{y1}"])
                    d_parts.append(f"L {x2},{y2}")
                else:
                    d_parts.append(f"L {x2},{y2}")
            d_str = " ".join(d_parts)

            # A stream number is labelled once (on its longest segment); a
            # white halo drawn in a final pass knocks the line out beneath it.
            if bool(longest_seg) and not is_signal and s.name not in labeled_names:
                labeled_names.add(s.name)
                label_items.append((longest_seg, s.name, color))

            marker = f' marker-end="url(#{marker_id})"' if self._tipped(s, arrows) else ""
            # A signal is drawn at half the weight of the pipe it reads, per
            # ISO 15519-2 Annex A.1.02/A.1.03 against A.1.01. See _SIGNAL_STROKE.
            width = _SIGNAL_STROKE if is_signal else _PROCESS_STROKE
            lines.append(
                f'    <path d="{d_str}" fill="none" '
                f'stroke="{color}" stroke-width="{width}"{dash}{marker} />'
            )

            if s.kind == "pneumatic":
                for i in range(len(points) - 1):
                    (px1, py1), (px2, py2) = points[i], points[i + 1]
                    seglen = abs(px2 - px1) + abs(py2 - py1)
                    # ISA-5.1 draws a pneumatic signal as a *solid* line marked
                    # with double cross-hatches, so the hatch is the only thing
                    # telling it apart from process piping. One mark per 45px
                    # alone leaves a short run — a transducer to the actuator
                    # right beneath it — with none at all, reading as plain pipe.
                    # Any segment with room for a mark gets at least one; longer
                    # segments keep the 45px spacing.
                    #
                    # The mark is drawn at the weight of the line it marks. A
                    # supplementary symbol on a connection is a graphical symbol
                    # (ISO 15519-2 Annex A.1.09, pneumatic type 433A), and
                    # ISO 15519-1 §11.1.3 puts a graphical symbol at 0,1 M, the
                    # same rung the signal line itself sits on. A hatch heavier
                    # than its own line would read as the weightier of the two.
                    n = int(seglen // 45) or (1 if seglen >= 16 else 0)
                    horiz = abs(py1 - py2) < 0.1
                    for k in range(1, n + 1):
                        t = k / (n + 1)
                        mx, my = px1 + (px2 - px1) * t, py1 + (py2 - py1) * t
                        for off in (-2.5, 1.5):
                            if horiz:
                                lines.append(f'    <line x1="{mx+off-3:.1f}" y1="{my+5:.1f}" '
                                             f'x2="{mx+off+3:.1f}" y2="{my-5:.1f}" stroke="{color}" stroke-width="{_SIGNAL_STROKE}" />')
                            else:
                                lines.append(f'    <line x1="{mx-5:.1f}" y1="{my+off-3:.1f}" '
                                             f'x2="{mx+5:.1f}" y2="{my+off+3:.1f}" stroke="{color}" stroke-width="{_SIGNAL_STROKE}" />')

        # Final pass: stream-number labels, each on a white halo so it reads
        # cleanly over any line that crosses beneath it.
        #
        # A label runs parallel to the pipe it names, turned on a vertical run so
        # it reads bottom to top and never upside down. ISO 15519-1 §5.1.5 allows
        # text read "from the bottom edge or ... from the right-hand edge of the
        # document", and this is the second of those. Its next sentence, that
        # reference designations stay horizontal "independent of symbol
        # orientation", is a rule about a symbol's own designation and does not
        # reach a connection: §7.2.5 is the clause for those, and it asks for
        # orientation *along* the connecting line. ISO 15519-1's own Figure 40
        # turns the annotation on every vertical connecting line to read bottom
        # to top, left of the line, while boxing symbol designations flat.
        #
        # Everything already on the sheet is seeded as occupied so a label slides
        # clear of it: balloons and equipment tags are drawn over the lines, so a
        # number parked under one would simply vanish, and a number over a symbol
        # would take a bite out of it with its own halo. Two streams sharing a
        # corridor sit only a few px apart, so their labels are held apart the
        # same way, which is what a draftsman does.
        placed: list[tuple[float, float, float, float]] = [
            unit_box(u, u.frame) for u in fs.units if u.frame is not None
        ]
        placed += [b for b in map(_unit_label_box, unit_labels) if b is not None]

        def _clear(box):
            return all(box[2] <= p[0] or box[0] >= p[2] or box[3] <= p[1] or box[1] >= p[3]
                       for p in placed)

        for seg, name, color in label_items:
            (sx1, sy1), (sx2, sy2) = seg
            hw, hh = len(name) * 6.2 + 6, 13.0
            cx, cy = (sx1 + sx2) / 2, (sy1 + sy2) / 2
            vertical = abs(sx2 - sx1) < abs(sy2 - sy1)
            span = abs(sy2 - sy1) if vertical else abs(sx2 - sx1)
            # Turned to follow the run, the halo measures hw along it, hh across.
            bw, bh = (hh, hw) if vertical else (hw, hh)

            spot = None
            for ux, uy in _label_anchors(cx, cy, span, hw, hh, vertical):
                box = (ux - bw / 2, uy - bh / 2, ux + bw / 2, uy + bh / 2)
                if spot is None:
                    spot = (ux, uy)  # first choice, kept if nothing is ever clear
                if _clear(box):
                    spot = (ux, uy)
                    break
            tx, ty = spot
            placed.append((tx - bw / 2, ty - bh / 2, tx + bw / 2, ty + bh / 2))
            lines.append(f'    <rect x="{tx - bw / 2:.1f}" y="{ty - bh / 2:.1f}" '
                         f'width="{bw:.1f}" height="{bh:.1f}" fill="white" />')
            turn = f' transform="rotate(-90, {tx:.1f}, {ty:.1f})"' if vertical else ""
            lines.append(
                f'    <text x="{tx:.1f}" y="{ty:.1f}" font-family="sans-serif" font-size="10" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'fill="{color}"{turn}>{html.escape(name)}</text>'
            )
        lines.append('  </g>')
        return lines
