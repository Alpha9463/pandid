"""Drawing documentation: the title block and sheet furniture.

Attach a :class:`TitleBlock` to a flowsheet
(``fs.title_block = TitleBlock(...)``) and the sheet is drawn with a
full-width engineering title strip (revision history + company/logo cell
+ client / project / status / drawing-number / title / date / scale /
rev cells), the data fields ISO 7200 specifies for a title block and ISO
10628-1 §5.1.2 requires on a process diagram. Seven of the eight ISO
7200 mandatory fields have a cell; the eighth, document type, does not.
A PFD carries a title strip as readily as a P&ID does, so the strip
follows the block, not the border: ``border="zone"`` adds the zone-ruled
drawing frame around it.

Around the drawing you can place *generic titled boxes*:
:class:`Annotation` (a title over free-form, optionally columnar, text)
and :class:`TableBox` (a title over a bordered header+rows grid).
Equipment lists, notes, and legends are all just :class:`Annotation`
boxes; :func:`equipment_list`, :func:`notes` and :func:`legend` are thin
constructors for the common cases.

Add them with ``fs.annotations.append(...)`` (or
``fs.add_annotation(...)``); a box on the flowsheet is a box on the
sheet, whichever border is drawn.
"""

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------
# Location references (ISO 15519-1:2010 Clause 9)
# --------------------------------------------------------------

#: How a zone may be spelled, from ISO 15519-1 §5.1.2: *"The grid
#: reference system consists of columns and rows. A zone is the
#: cross-section of a column and a row. Columns are designated with
#: numbers. Rows are designated with letters."* So a zone is its row
#: letter followed by its column number (Table 2's ``B3``), and a row or
#: a column on its own is the letter or the number alone. ``3B`` is
#: neither, and is the mistake this rejects.
_ZONE = re.compile(r"\A(?:[A-Za-z]+[0-9]+|[A-Za-z]+|[0-9]+)\Z")

# The two signs Clause 9 reserves. A field containing one would be read
# as a separator by whoever reads the finished string, so they are
# refused in the parts rather than escaped.
_SEPARATORS = "/."


def _clean(value, field_name: str) -> str:
    text = str(value or "").strip()
    bad = sorted({c for c in text if c in _SEPARATORS or c.isspace()})
    if bad:
        raise ValueError(
            f"{field_name}={text!r} contains {', '.join(repr(c) for c in bad)}; "
            f"ISO 15519-1 Clause 9 reserves '/' for the sheet and '.' for the "
            f"zone, so a reference part cannot carry one. Pass the parts "
            f"separately."
        )
    return text


def location_reference(document="", sheet="", zone="") -> str:
    """Compose an ISO 15519-1 Clause 9 location reference.

    Clause 9, *Location references*, in full:

        For reference to a document, to a sheet of a document, or to
        a column, a row or a zone on a sheet, the grid reference
        system described in 5.1.2 shall be used.

        The following signs shall be used for creating location
        references:

        * solidus (/) for identification of a sheet;

        * full stop (.) for identification of a column, a row or a
          zone in a sheet.

        The location reference shall be presented in following sequence:
        document — sheet — column, row or zone.

    So the three parts always appear in that order, each introduced by
    its own sign, and a part left out narrows the *scope* of the
    reference rather than changing its shape. That is what Table 2
    tabulates, and this function reproduces all seven of its rows:

    ================================  ==================================
    ``location_reference(...)``       result (Table 2)
    ================================  ==================================
    ``("4334", zone="B3")``           ``4334/.B3``  zone B3 on
                                      single-sheet diagram No. 4334
    ``("7569", "12", "B3")``          ``7569/12.B3``  ...on sheet 12
                                      of multi-sheet diagram No. 7569
    ``(sheet="2")``                   ``/2``  another sheet, same doc
    ``(sheet="12", zone="B3")``       ``/12.B3``  zone B3 on sheet 12
    ``(zone="B")``                    ``/.B``  row B on this sheet
    ``(zone="3")``                    ``/.3``  column 3 on this sheet
    ``(zone="B3")``                   ``/.B3``  zone B3 on this sheet
    ================================  ==================================

    A document with nothing after it is the document itself,
    ``PFD-302``, which is what a real sheet's off-page connector
    carries, and what :attr:`pandid.units.Feed.reference` has always
    been given. The helper is therefore a way to *spell* a reference
    that names a sheet or a zone as well, not a new kind of value: it
    returns a plain string and ``reference=`` still takes one.

    ``zone`` is validated against §5.1.2 (rows are letters, columns are
    numbers, and a zone is the row's letter then the column's number),
    so ``"3B"`` raises rather than reaching a drawing back to front. The
    sheet reference is only checked for the two reserved signs, since
    sheet numbering is the drawing office's (ISO 15519-1 §5.2.3 requires
    only that the sheets of a set relate to one another).

    Raises :class:`ValueError` if every part is empty: a reference to
    nothing is not a scope, it is a blank.
    """
    document = _clean(document, "document")
    sheet = _clean(sheet, "sheet")
    zone = _clean(zone, "zone")
    if zone and not _ZONE.match(zone):
        raise ValueError(
            f"zone={zone!r} is not a zone, a row or a column. ISO 15519-1 5.1.2 "
            f"designates columns with numbers and rows with letters, so a zone "
            f"is its row's letter then its column's number ('B3'), a row is the "
            f"letter alone ('B') and a column the number alone ('3')."
        )
    if not (document or sheet or zone):
        raise ValueError(
            "a location reference names a document, a sheet or a zone, and this "
            "one names none of the three. ISO 15519-1 Clause 9 scopes a "
            "reference by what it leaves out, so there is nothing an empty one "
            "could mean."
        )
    # The solidus marks the sheet field whether or not that field has a
    # number in it: Table 2 writes zone B3 of single-sheet diagram 4334
    # as "4334/.B3", keeping the sign and dropping only the sheet.
    out = document
    if sheet or zone:
        out += "/" + sheet
    if zone:
        out += "." + zone
    return out


@dataclass
class Revision:
    """One row of the revision history.

    ``checked``/``approved`` are optional per-row initials; when omitted
    the strip leaves those cells blank (typical for early, un-checked
    revisions).
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

    ``title`` and ``subtitle`` are the two title lines (e.g. an area
    name over the drawing type, ``"Ethanol Purification A300"`` /
    ``"Process Flow Diagram 1"``). ``company`` fills the logo/company
    cell, ``status`` the issue-status cell (e.g.
    ``"ISSUED FOR REVIEW"``).

    ``client`` and ``project`` head the information block, above the
    title. Neither is an ISO 7200 field: ISO 5457 specifies no
    title-block data fields at all and defers them to ISO 7200, whose
    mandatory "legal owner" is the organisation issuing the drawing,
    which is ``company`` here. An issued sheet names its client anyway,
    so the pair is drawn. Either may be left blank and the line for it
    is not ruled.

    ``scale`` is the scale cell. Left blank, the sheet reports the ratio
    the renderer actually placed the drawing at, which is a real number
    once ``page_size`` fixes the page; a drawing on a sheet sized to fit
    it has no scale to state, so the cell is not ruled. Give the field a
    value (``"NTS"``, ``"1:100"``) to state one regardless.
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


# The nine positions a box can dock to on the sheet *frame* (not the
# drawing), as a 3x3 grid: the box goes flush against the frame edges
# its ``align`` names, so ``"top-right"`` puts its top-right corner in
# the frame's and ``"top"`` centres it on the top edge.
_ALIGN = {
    "top-left", "top", "top-right",
    "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
}


def _resolve_align(align, default):
    """The effective alignment, checked against the dock's nine."""
    value = default if align is None else align
    if value not in _ALIGN:
        raise ValueError(f"align must be one of {sorted(_ALIGN)}, got {value!r}")
    return value


@dataclass
class Annotation:
    """A generic titled box placed on the sheet.

    Placement (see :data:`_ALIGN`):

    * ``align`` docks the box flush to the sheet frame at one of nine
      positions (corners, edge-centres, or dead centre). This is the
      usual way.
    * ``position=(x, y)`` instead pins the box's **top-left corner** at
      absolute sheet coordinates, ignoring ``align``: the escape hatch
      for hand-placed furniture.
    * ``margin`` insets a docked box from the frame edge (default ``0``
      = flush).

    ``rows`` entries are either a plain ``str`` (one left-aligned line)
    or a tuple/list of cell strings that align into columns (first
    column left, the rest following at shared column stops), enough to
    lay out an equipment schedule (``("T-301", "Beer Column")``) or a
    legend (``("SS", "316L")``) without a full table.
    """
    title: str = ""
    rows: list = field(default_factory=list)
    align: str = "top-right"
    position: tuple[float, float] | None = None
    margin: float = 0.0
    width: float | None = None
    font_size: float = 11.0

    def __post_init__(self):
        self.align = _resolve_align(self.align, "top-right")


@dataclass
class TableBox:
    """A bordered table (title, header row, body rows) placed on the
    sheet. Cells are stringified as-is; ``col_align`` is per-column
    ``"l"``/``"c"``/``"r"`` (defaults to centered).

    Placement (``align`` / ``position`` / ``margin``) works exactly as
    for :class:`Annotation`.
    """
    title: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    align: str = "bottom-right"
    position: tuple[float, float] | None = None
    margin: float = 0.0
    font_size: float = 11.0
    col_align: list[str] | None = None

    def __post_init__(self):
        self.align = _resolve_align(self.align, "bottom-right")


# --------------------------------------------------------------
# Convenience constructors for the common boxes
# --------------------------------------------------------------

# The kinds an equipment list schedules: major plant, the items that
# carry a tag on the sheet *and* a datasheet, a foundation and a
# purchase order behind it. Nothing else is scheduled:
#
# * bulk items (valves, fittings, reducers, tees, vents, funnels) are
#   bought by the line and specified by the piping class;
# * a mixer or splitter is a branch in the piping drawn as a triangle,
#   so scheduling one puts plant on the sheet that does not exist;
# * sheet boundaries and instruments are not equipment at all.
#
# A separate valve or instrument schedule is a real drawing, so
# ``include=`` names its rows explicitly and this rule stands aside.
_MAJOR_EQUIPMENT = frozenset({
    "blower", "column", "compressor", "conveyor", "cooler", "crusher", "dryer",
    "ejector", "elevator", "filter", "furnace", "heater", "hex", "mill",
    "pump", "reactor", "separator", "tank", "turbine", "vessel",
})
# ``block`` is absent: a block flow diagram's box stands for a whole
# section of plant, whose equipment list is a document of its own, so
# scheduling one would say that "Reaction" is a thing somebody
# purchases. ``include=`` still takes a block by name, for the author
# who wants a block *index* rather than an equipment list.

# What each kind is called in words. ``kind`` is a lookup key, so a
# schedule that falls back to it reads ``('E-101', 'Hex')``, the source
# code quoted at the reader in place of the equipment description an
# engineer would write.
_KIND_LABELS = {
    "block": "Process Block",
    "blower": "Blower",
    "column": "Column",
    "compressor": "Compressor",
    "conveyor": "Conveyor",
    "cooler": "Cooler",
    "crusher": "Crusher",
    "dryer": "Dryer",
    "ejector": "Ejector",
    "elevator": "Bucket Elevator",
    "feed": "Feed",
    "filter": "Filter",
    "fitting": "In-Line Fitting",
    "funnel": "Charging Funnel",
    "furnace": "Fired Heater",
    "heater": "Heater",
    "hex": "Heat Exchanger",
    "instrument": "Instrument",
    "mill": "Mill",
    "mixer": "Mixer",
    "product": "Product",
    "pump": "Pump",
    "reactor": "Reactor",
    "reducer": "Reducer",
    "separator": "Separator",
    "splitter": "Splitter",
    "tank": "Tank",
    "tee": "Pipe Tee",
    "turbine": "Turbine",
    "valve": "Valve",
    "vent": "Vent",
    "vessel": "Vessel",
}


def _describe(unit):
    """The words an equipment list puts against a tag.

    The unit's own ``description`` when it has one, otherwise what its
    kind is called (see :data:`_KIND_LABELS`).
    """
    return (getattr(unit, "description", "")
            or _KIND_LABELS.get(unit.kind, unit.kind.replace("_", " ").title()))


def equipment_list(fs, *, title="EQUIPMENT LIST", align="top-right",
                   position=None, margin=0.0, include=None, width=None):
    """Build an :class:`Annotation` scheduling the major equipment.

    Each row is ``(tag, description)``; the description is the unit's
    ``description``, or what its kind is called when it has none. Only
    major equipment is scheduled (see :data:`_MAJOR_EQUIPMENT`).

    ``include`` names the rows explicitly instead, in the order given,
    and takes whatever it names. That is how a valve or instrument
    schedule, a real drawing in its own right, gets built from the same
    flowsheet. A tag that is not on the flowsheet contributes no row.

    ``align`` / ``position`` / ``margin`` place the box (see
    :class:`Annotation`).
    """
    if include is None:
        chosen = [u for u in fs.units if u.kind in _MAJOR_EQUIPMENT]
    else:
        by_name = {u.name: u for u in fs.units}
        chosen = [by_name[tag] for tag in include if tag in by_name]
    rows = [(u.name, _describe(u)) for u in chosen]
    return Annotation(title=title, rows=rows, align=align,
                      position=position, margin=margin, width=width)


def notes(items, *, title="NOTES", align="top-right", position=None,
          margin=0.0, numbered=True, width=None):
    """Build a numbered (or bullet) notes :class:`Annotation`."""
    rows = []
    for i, text in enumerate(items, start=1):
        rows.append((f"{i}.", text) if numbered else text)
    return Annotation(title=title, rows=rows, align=align,
                      position=position, margin=margin, width=width)


def legend(entries, *, title="LEGEND", align="top-left",
           position=None, margin=0.0, width=None):
    """Build a legend :class:`Annotation` from ``(abbr, meaning)``
    pairs (a dict is accepted and keeps insertion order)."""
    if isinstance(entries, dict):
        entries = list(entries.items())
    return Annotation(title=title, rows=[tuple(e) for e in entries],
                      align=align, position=position,
                      margin=margin, width=width)
