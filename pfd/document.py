"""Drawing documentation — the engineering title block and sheet furniture.

Attach a :class:`TitleBlock` to a flowsheet (``fs.title_block = TitleBlock(...)``)
and the sheet is drawn with a full-width engineering title strip (revision
history + company/logo cell + client / project / status / drawing-number / title
/ date / scale / rev cells), the metadata that ISO 10628 / ASME Y14 sheets
require. A PFD carries a title strip as readily as a P&ID does, so the strip
follows the block, not the border: ``border="zone"`` adds the zone-ruled drawing
frame around it.

Around the drawing you can place *generic titled boxes* — :class:`Annotation`
(a title over free-form, optionally columnar, text) and :class:`TableBox`
(a title over a bordered header+rows grid). Equipment lists, notes, and legends
are all just :class:`Annotation` boxes; :func:`equipment_list`, :func:`notes`
and :func:`legend` are thin constructors for the common cases.

Add them with ``fs.annotations.append(...)`` (or ``fs.add_annotation(...)``);
a box on the flowsheet is a box on the sheet, whichever border is drawn.
"""

from dataclasses import dataclass, field


@dataclass
class Revision:
    """One row of the revision history.

    ``checked``/``approved`` are optional per-row initials; when omitted the
    strip leaves those cells blank (typical for early, un-checked revisions).
    """
    rev: str = ""
    date: str = ""
    description: str = ""
    by: str = ""
    checked: str = ""
    approved: str = ""


@dataclass
class TitleBlock:
    """Title-block metadata for a drawing sheet.

    ``title`` and ``subtitle`` are the two title lines (e.g. an area name over
    the drawing type — ``"Ethanol Purification A300"`` / ``"Process Flow
    Diagram 1"``). ``company`` fills the logo/company cell, ``status`` the
    issue-status cell (e.g. ``"ISSUED FOR REVIEW"``).

    ``client`` and ``project`` head the information block, above the title,
    where ISO 5457 puts the owner of the drawing. Either may be left blank and
    the line for it is not ruled.

    ``scale`` is the scale cell. Left blank, the sheet reports the ratio the
    renderer actually placed the drawing at, which is a real number once
    ``page_size`` fixes the page; a drawing on a sheet sized to fit it has no
    scale to state, so the cell is not ruled. Give the field a value
    (``"NTS"``, ``"1:100"``) to state one regardless.
    """
    title: str = ""
    subtitle: str = ""
    drawing_number: str = ""
    project: str = ""
    client: str = ""
    company: str = ""
    status: str = ""
    sheet: str = "1"
    of_sheets: str = "1"
    scale: str = ""
    drawn_by: str = ""
    checked_by: str = ""
    approved_by: str = ""
    date: str = ""
    revisions: list[Revision] = field(default_factory=list)


# The nine positions a box can dock to on the sheet *frame* (not the drawing).
# Corners and edge-centres behave like a 3x3 grid: the box is placed flush
# against the frame edge(s) its ``align`` names — e.g. ``"top-right"`` puts the
# box's top-right corner in the frame's top-right corner, ``"top"`` centres it
# on the top edge. This mirrors how professional sheets pin their furniture.
_ALIGN = {
    "top-left", "top", "top-right",
    "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
}
_ANCHORS = _ALIGN  # alias for the deprecated ``anchor`` spelling


def _resolve_align(align, anchor, default):
    """Resolve the effective alignment, honouring the deprecated ``anchor=``."""
    value = anchor if anchor is not None else align
    if value is None:
        value = default
    if value not in _ALIGN:
        raise ValueError(f"align must be one of {sorted(_ALIGN)}, got {value!r}")
    return value


@dataclass
class Annotation:
    """A generic titled box placed on the sheet.

    Placement (see :data:`_ALIGN`):

    * ``align`` docks the box flush to the sheet frame at one of nine positions
      (corners, edge-centres, or dead centre). This is the usual way.
    * ``position=(x, y)`` instead pins the box's **top-left corner** at absolute
      sheet coordinates, ignoring ``align`` — the escape hatch for hand-placed
      furniture.
    * ``margin`` insets a docked box from the frame edge (default ``0`` = flush).

    ``rows`` entries are either a plain ``str`` (one left-aligned line) or a
    tuple/list of cell strings that align into columns (first column left, the
    rest following at shared column stops) — enough to lay out an equipment
    schedule (``("T-301", "Beer Column")``) or a legend (``("SS", "316L")``)
    without a full table.

    ``anchor`` is a deprecated alias for ``align``.
    """
    title: str = ""
    rows: list = field(default_factory=list)
    align: str = "top-right"
    position: tuple[float, float] | None = None
    margin: float = 0.0
    width: float | None = None
    font_size: float = 11.0
    anchor: str | None = None  # deprecated alias for ``align``

    def __post_init__(self):
        self.align = _resolve_align(self.align, self.anchor, "top-right")
        self.anchor = self.align


@dataclass
class TableBox:
    """A generic bordered table (title + header row + body rows) placed on the
    sheet. Cells are stringified as-is; ``col_align`` is per-column
    ``"l"``/``"c"``/``"r"`` (defaults to centered).

    Placement (``align`` / ``position`` / ``margin``) works exactly as for
    :class:`Annotation`; ``anchor`` is a deprecated alias for ``align``.
    """
    title: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    align: str = "bottom-right"
    position: tuple[float, float] | None = None
    margin: float = 0.0
    font_size: float = 11.0
    col_align: list[str] | None = None
    anchor: str | None = None  # deprecated alias for ``align``

    def __post_init__(self):
        self.align = _resolve_align(self.align, self.anchor, "bottom-right")
        self.anchor = self.align


# ---------------------------------------------------------------------------
# Convenience constructors for the common boxes
# ---------------------------------------------------------------------------

# Unit kinds that are drawing furniture / boundaries, not scheduled equipment.
_NON_EQUIPMENT = {"feed", "product", "instrument"}


def equipment_list(fs, *, title="EQUIPMENT LIST", align="top-right", anchor=None,
                   position=None, margin=0.0, include=None, width=None):
    """Build an :class:`Annotation` scheduling every real equipment item.

    Each row is ``(tag, description)``; the description comes from the unit's
    ``description`` (falling back to a humanized kind). ``include`` optionally
    restricts to an explicit ordered list of tags. ``align`` / ``position`` /
    ``margin`` place the box (see :class:`Annotation`); ``anchor`` is a
    deprecated alias for ``align``.
    """
    rows = []
    for u in fs.units:
        if u.kind in _NON_EQUIPMENT:
            continue
        if include is not None and u.name not in include:
            continue
        desc = getattr(u, "description", "") or u.kind.replace("_", " ").title()
        rows.append((u.name, desc))
    if include is not None:
        order = {t: i for i, t in enumerate(include)}
        rows.sort(key=lambda r: order.get(r[0], len(order)))
    return Annotation(title=title, rows=rows, align=align, anchor=anchor,
                      position=position, margin=margin, width=width)


def notes(items, *, title="NOTES", align="top-right", anchor=None, position=None,
          margin=0.0, numbered=True, width=None):
    """Build a numbered (or bullet) notes :class:`Annotation`."""
    rows = []
    for i, text in enumerate(items, start=1):
        rows.append((f"{i}.", text) if numbered else text)
    return Annotation(title=title, rows=rows, align=align, anchor=anchor,
                      position=position, margin=margin, width=width)


def legend(entries, *, title="LEGEND", align="top-left", anchor=None,
           position=None, margin=0.0, width=None):
    """Build an abbreviations/legend :class:`Annotation` from ``(abbr, meaning)``
    pairs (a dict is accepted and keeps insertion order)."""
    if isinstance(entries, dict):
        entries = list(entries.items())
    return Annotation(title=title, rows=[tuple(e) for e in entries],
                      align=align, anchor=anchor, position=position,
                      margin=margin, width=width)
