"""Drawing documentation — the engineering title block and sheet furniture.

Attach a :class:`TitleBlock` to a flowsheet (``fs.title_block = TitleBlock(...)``)
and render with ``styling="pid"`` to draw a full-width engineering title strip
(revision history + company/logo cell + status / drawing-number / title / date /
rev cells) inside a zone-ruled drawing border — the metadata that ISO 10628 /
ASME Y14 sheets require.

Around the drawing you can place *generic titled boxes* — :class:`Annotation`
(a title over free-form, optionally columnar, text) and :class:`TableBox`
(a title over a bordered header+rows grid). Equipment lists, notes, and legends
are all just :class:`Annotation` boxes; :func:`equipment_list`, :func:`notes`
and :func:`legend` are thin constructors for the common cases.

Add them with ``fs.annotations.append(...)`` (or ``fs.add_annotation(...)``).
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
    scale: str = "NTS"
    drawn_by: str = ""
    checked_by: str = ""
    approved_by: str = ""
    date: str = ""
    revisions: list[Revision] = field(default_factory=list)


# Corners a box can dock to. Top boxes grow the top band; bottom boxes grow the
# bottom band; the drawing body sits between them.
_ANCHORS = {"top-left", "top-right", "bottom-left", "bottom-right"}


@dataclass
class Annotation:
    """A generic titled box docked to a sheet corner.

    ``rows`` entries are either a plain ``str`` (one left-aligned line) or a
    tuple/list of cell strings that align into columns (first column left, the
    rest following at shared column stops) — enough to lay out an equipment
    schedule (``("T-301", "Beer Column")``) or a legend (``("SS", "316L")``)
    without a full table.
    """
    title: str = ""
    rows: list = field(default_factory=list)
    anchor: str = "top-right"
    width: float | None = None
    font_size: float = 11.0

    def __post_init__(self):
        if self.anchor not in _ANCHORS:
            raise ValueError(
                f"anchor must be one of {sorted(_ANCHORS)}, got {self.anchor!r}"
            )


@dataclass
class TableBox:
    """A generic bordered table (title + header row + body rows) docked to a
    corner. Cells are stringified as-is; ``col_align`` is per-column
    ``"l"``/``"c"``/``"r"`` (defaults to centered)."""
    title: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    anchor: str = "bottom-right"
    font_size: float = 11.0
    col_align: list[str] | None = None

    def __post_init__(self):
        if self.anchor not in _ANCHORS:
            raise ValueError(
                f"anchor must be one of {sorted(_ANCHORS)}, got {self.anchor!r}"
            )


# ---------------------------------------------------------------------------
# Convenience constructors for the common boxes
# ---------------------------------------------------------------------------

# Unit kinds that are drawing furniture / boundaries, not scheduled equipment.
_NON_EQUIPMENT = {"feed", "product", "instrument"}


def equipment_list(fs, *, title="EQUIPMENT LIST", anchor="top-right",
                   include=None, width=None):
    """Build an :class:`Annotation` scheduling every real equipment item.

    Each row is ``(tag, description)``; the description comes from the unit's
    ``description`` (falling back to a humanized kind). ``include`` optionally
    restricts to an explicit ordered list of tags.
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
    return Annotation(title=title, rows=rows, anchor=anchor, width=width)


def notes(items, *, title="NOTES", anchor="top-right", numbered=True, width=None):
    """Build a numbered (or bullet) notes :class:`Annotation`."""
    rows = []
    for i, text in enumerate(items, start=1):
        rows.append((f"{i}.", text) if numbered else text)
    return Annotation(title=title, rows=rows, anchor=anchor, width=width)


def legend(entries, *, title="LEGEND", anchor="top-left", width=None):
    """Build an abbreviations/legend :class:`Annotation` from ``(abbr, meaning)``
    pairs (a dict is accepted and keeps insertion order)."""
    if isinstance(entries, dict):
        entries = list(entries.items())
    return Annotation(title=title, rows=[tuple(e) for e in entries],
                      anchor=anchor, width=width)
