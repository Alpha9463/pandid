"""Define the title block and the sheet furniture.

Sheet furniture is titled boxes of text (:class:`Annotation`) or of a
bordered grid (:class:`TableBox`).
"""

from dataclasses import dataclass, field, fields, replace
from typing import Any, Literal

from pandid._checks import check_real, suggest


@dataclass
class Revision:
    """One row of the revision history.

    Attributes
    ----------
    rev, date, description : str
        Revision mark, date and description.
    by, checked, approved : str
        Initials; blank ones on the newest row take the block's.
    """
    rev: str = ""
    date: str = ""
    description: str = ""
    by: str = ""
    checked: str = ""
    approved: str = ""


@dataclass
class TitleBlock:
    """Hold the title-block fields for a drawing sheet.

    Attributes
    ----------
    title, subtitle : str
        Title lines; an empty title draws the flowsheet name.
    drawing_number : str
        Drawing number; a blank one draws a dash.
    project, client : str
        Information rows; a blank one draws no row.
    company : str
        Organisation issuing the drawing.
    status : str
        Issue status, such as ``"ISSUED"``; a blank one draws a dash.
    sheet, of_sheets : str
        The ``SHEET n of m`` count; a blank one draws ``"1"``.
    scale : str
        Scale, such as ``"1:100"``. A blank one on a diagram shows the
        placed scale when ``page_size`` fixes the page.
    drawn_by, checked_by, approved_by : str
        Initials for the newest revision row's blank cells.
    date : str
        Issue date; an empty one draws today's.
    revisions : list[Revision]
        Revision history.
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


def _drawn_text(value: Any) -> str:
    """Return a field value as drawn text; ``None`` is blank.

    Parameters
    ----------
    value : Any
        Field value.

    Returns
    -------
    str
        ``""`` for ``None``, else ``str(value)``.
    """
    return "" if value is None else str(value)


def _drawn_rows(rows: Any) -> list:
    """Return box rows with every line and cell as drawn text.

    Parameters
    ----------
    rows : Iterable
        Lines, or tuples or lists of cells.

    Returns
    -------
    list
        Rows of the same shapes, as text.
    """
    # shortcut: rows.append skips this, convert at draw time if needed.
    return [tuple(map(_drawn_text, r)) if isinstance(r, tuple)
            else list(map(_drawn_text, r)) if isinstance(r, list)
            else _drawn_text(r) for r in rows]


def _drawn_text_fields(cls: type) -> frozenset[str]:
    """Return the names of a dataclass's string-default fields.

    Parameters
    ----------
    cls : type
        Dataclass.

    Returns
    -------
    frozenset[str]
        Field names.
    """
    return frozenset(f.name for f in fields(cls) if isinstance(f.default, str))


# Docking positions of a box on the sheet frame.
_ALIGN = {
    "top-left", "top", "top-right",
    "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
}


def _resolve_align(align, default):
    """Return the alignment, checked against the docking positions.

    Parameters
    ----------
    align : str or None
        Stated alignment, or ``None`` for the default.
    default : str
        Alignment used when ``align`` is ``None``.

    Returns
    -------
    str
        Docking position.

    Raises
    ------
    ValueError
        If the alignment is not a docking position.
    """
    value = default if align is None else align
    if value not in _ALIGN:
        raise ValueError(f"align must be one of {sorted(_ALIGN)}, got {value!r}")
    return value


# TableBox column alignments: left, centre, right.
_COL_ALIGN = {"l", "c", "r"}


def _resolve_col_align(col_align):
    """Return ``col_align`` after checking each entry.

    Parameters
    ----------
    col_align : list[str] or None
        Column alignments.

    Returns
    -------
    list[str] or None
        The same alignments.

    Raises
    ------
    ValueError
        If an entry is not ``"l"``, ``"c"`` or ``"r"``.
    """
    if col_align is None:
        return None
    for i, a in enumerate(col_align):
        if a not in _COL_ALIGN:
            raise ValueError(
                f"col_align[{i}] must be one of {sorted(_COL_ALIGN)} ('l'/'c'/'r' for "
                f"left/centre/right), got {a!r}"
            )
    return col_align


class _Box:
    """Field checks shared by the annotation and table boxes."""

    def __setattr__(self, name: str, value: Any) -> None:
        """Set a field, storing text as drawn and checking numbers.

        Parameters
        ----------
        name : str
            Field name.
        value : Any
            New value.

        Raises
        ------
        TypeError
            If a numeric field or ``position`` entry is a bool or not
            a real number, or a given ``position`` is not iterable.
        ValueError
            If a numeric field or ``position`` entry is not finite.
        """
        where = f"{type(self).__name__}.{name}"
        if name == "rows":
            value = _drawn_rows(value)
        elif name == "headers":
            value = [_drawn_text(c) for c in value]
        elif name in ("margin", "width", "font_size") and value is not None:
            check_real(value, where)
        elif name == "position" and value is not None:
            for i, coordinate in enumerate(value):
                check_real(coordinate, f"{where}[{i}]")
        super().__setattr__(name, value)


@dataclass
class Annotation(_Box):
    """Titled text box placed on the sheet.

    A row is a string (one line) or a tuple or list of cells aligned
    into columns.

    Attributes
    ----------
    title : str
        Box title.
    rows : list
        Lines or cell sequences.
    align : str
        Docking position: a corner, an edge centre or ``"center"``.
    position : tuple[float, float] or None
        Top-left corner in sheet coordinates; overrides ``align``.
    margin : float
        Inset of a docked box from the frame.
    width : float or None
        Box width; ``None`` sizes it to the content.
    font_size : float
        Type size.

    Raises
    ------
    TypeError
        If a numeric field or ``position`` coordinate is a bool or
        not a real number, or a given ``position`` is not iterable.
    ValueError
        If ``align`` is invalid or a number is not finite.
    """
    title: str = ""
    rows: list = field(default_factory=list)
    align: str = "top-right"
    position: tuple[float, float] | None = None
    margin: float = 0.0
    width: float | None = None
    font_size: float = 11.0

    def __post_init__(self):
        """Check the alignment.

        Raises
        ------
        ValueError
            If ``align`` is not a docking position.
        """
        self.align = _resolve_align(self.align, "top-right")


@dataclass
class TableBox(_Box):
    """Bordered table with a title, header row and body rows.

    Attributes
    ----------
    title : str
        Table title.
    headers : list[str]
        Header cells.
    rows : list[list]
        Body rows.
    align : str
        Docking position, as for :class:`Annotation`.
    position : tuple[float, float] or None
        Top-left corner; overrides ``align``.
    margin : float
        Inset of a docked box from the frame.
    font_size : float
        Type size.
    col_align : list[str] or None
        ``"l"``, ``"c"`` or ``"r"`` per column; ``None`` centres them.

    Raises
    ------
    TypeError
        If a numeric field or ``position`` coordinate is a bool or
        not a real number, or a given ``position`` is not iterable.
    ValueError
        If ``align`` or ``col_align`` is bad or a number is not finite.
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
        """Check the alignment and column alignments.

        Raises
        ------
        ValueError
            If ``align`` or a ``col_align`` entry is invalid.
        """
        self.align = _resolve_align(self.align, "bottom-right")
        self.col_align = _resolve_col_align(self.col_align)


@dataclass
class StreamTableOptions:
    """Stream property table options for one sheet: ``fs.stream_table``.

    Attributes
    ----------
    font_size : float or None
        Positive type size or ``None`` to choose; scales the floors.
    label_width : float or "auto"
        Row-label column floor, 0 or more, or ``"auto"`` for none.
    column_width : float or "auto"
        Stream column floor, 0 or more, or ``"auto"`` for none.
    sheet_subtitle : str
        Subtitle of the table's own sheet.
    sheet_drawing_number : str
        Table sheet's number; the diagram's own raises ValueError on
        a table-sheet render. Empty uses the diagram's number plus
        :data:`TABLE_SHEET_SUFFIX`, or stays empty if that is empty.
    """

    font_size: float | None = None
    label_width: float | Literal["auto"] = 122.0
    column_width: float | Literal["auto"] = 52.0
    sheet_subtitle: str = "Stream Table"
    sheet_drawing_number: str = ""


#: Suffix added to the diagram's number for the table sheet.
TABLE_SHEET_SUFFIX = "-ST"


def table_sheet_block(block: "TitleBlock | None",
                      options: StreamTableOptions) -> TitleBlock:
    """Return the title block for the stream table's own sheet.

    Parameters
    ----------
    block : TitleBlock or None
        Diagram's title block, or ``None`` for a blank one.
    options : StreamTableOptions
        Table options giving the subtitle and number.

    Returns
    -------
    TitleBlock
        Shallow copy of ``block`` with the table's subtitle and number.

    Raises
    ------
    ValueError
        If ``options.sheet_drawing_number`` is the diagram's own number.
    """
    diagram = TitleBlock() if block is None else block
    number = diagram.drawing_number
    stated = _drawn_text(options.sheet_drawing_number)
    if stated and _same_number(stated, number):
        raise ValueError(
            f"fs.stream_table.sheet_drawing_number={stated!r} is the diagram's "
            f"own drawing number. The table sheet is a second document and "
            f"cannot be filed under the first one's number: give it a number of "
            f"its own, or leave the field blank to derive "
            f"{number}{TABLE_SHEET_SUFFIX}"
        )
    return replace(
        diagram,
        subtitle=options.sheet_subtitle,
        drawing_number=(stated
                        or (f"{number}{TABLE_SHEET_SUFFIX}" if number else "")),
    )


def _same_number(a: str, b: str) -> bool:
    """Compare two drawing numbers, stripped and case-folded.

    Parameters
    ----------
    a, b : str
        Drawing numbers.

    Returns
    -------
    bool
        Whether they name the same drawing.
    """
    return a.strip().casefold() == b.strip().casefold()


# Stream label enclosures; "none" is the bare number on its halo.
_ENCLOSURES = ("none", "diamond", "circle", "box")


# Synonyms of each enclosure, named in the error message.
_ENCLOSURE_MEANT = {
    "rhombus": "diamond", "rhomb": "diamond", "lozenge": "diamond",
    "ellipse": "circle", "oval": "circle", "round": "circle",
    "balloon": "circle", "bubble": "circle",
    "rect": "box", "rectangle": "box", "square": "box", "frame": "box",
    "border": "box",
    "off": "none", "plain": "none", "bare": "none", "nothing": "none",
}


def _resolve_enclosure(shape):
    """Return an enclosure name after checking it.

    Parameters
    ----------
    shape : str
        Stated enclosure.

    Returns
    -------
    str
        The same enclosure.

    Raises
    ------
    ValueError
        If ``shape`` is not an enclosure.
    """
    if shape not in _ENCLOSURES:
        meant = (_ENCLOSURE_MEANT.get(shape.strip().lower())
                 if isinstance(shape, str) else None)
        raise ValueError(
            f"fs.stream_labels.enclosure must be one of {list(_ENCLOSURES)}, "
            f"got {shape!r}"
            + (f"; this package spells that one {meant!r}" if meant else "")
        )
    return shape


@dataclass
class StreamLabelOptions:
    """Stream label options for one sheet: ``fs.stream_labels``.

    Attributes
    ----------
    enclosure : {"none", "diamond", "circle", "box"}
        Shape around each stream label, or ``"none"`` for a bare one.

    Raises
    ------
    ValueError
        If ``enclosure`` is not one of the four shapes.
    """

    enclosure: Literal["none", "diamond", "circle", "box"] = "none"

    def __post_init__(self):
        """Check the enclosure.

        Raises
        ------
        ValueError
            If ``enclosure`` is not one of the four shapes.
        """
        self.enclosure = _resolve_enclosure(self.enclosure)


# Convenience constructors for the common boxes

# Kinds an equipment list schedules by default.
_MAJOR_EQUIPMENT = frozenset({
    "blower", "boiler", "column", "compressor", "conveyor", "cooler",
    "cooling_tower", "crusher", "dryer", "ejector", "elevator", "evaporator",
    "feeder", "filter", "flare", "furnace", "heater", "hex", "kiln", "kneader",
    "mill", "pump", "reactor", "screening_device", "separator", "stack", "tank",
    "thickener", "turbine", "vessel",
})

# Equipment-list description of each kind.
_KIND_LABELS = {
    "block": "Process Block",
    "blower": "Blower",
    "boiler": "Boiler",
    "centrifuge": "Centrifuge",
    "column": "Column",
    "compressor": "Compressor",
    "conveyor": "Conveyor",
    "cooler": "Cooler",
    "cooling_tower": "Cooling Tower",
    "crusher": "Crusher",
    "crushing_machine": "Crushing/Grinding Machine",
    "dryer": "Dryer",
    "ejector": "Ejector",
    "evaporator": "Evaporator",
    "elevator": "Bucket Elevator",
    "feed": "Feed",
    "feeder": "Feeder",
    "filter": "Filter",
    "fitting": "In-Line Fitting",
    "flare": "Flare",
    "funnel": "Charging Funnel",
    "furnace": "Fired Heater",
    "heater": "Heater",
    "hex": "Heat Exchanger",
    "instrument": "Instrument",
    "kiln": "Kiln",
    "kneader": "Kneader",
    "mill": "Mill",
    "mixer": "Mixer",
    "product": "Product",
    "pump": "Pump",
    "reactor": "Reactor",
    "reducer": "Reducer",
    "screening_device": "Screen",
    "thickener": "Thickener",
    "separator": "Separator",
    "splitter": "Splitter",
    "spray_nozzle": "Spray Nozzle",
    "stack": "Stack",
    "tank": "Tank",
    "tee": "Pipe Tee",
    "turbine": "Turbine",
    "valve": "Valve",
    "vent": "Vent",
    "vessel": "Vessel",
}


def _describe(unit):
    """Return a unit's ``description``, else its kind's name.

    Parameters
    ----------
    unit : Unit
        Unit to describe.

    Returns
    -------
    Any
        Stated description as given, else the kind's name.
    """
    return (getattr(unit, "description", "")
            or _KIND_LABELS.get(unit.kind, unit.kind.replace("_", " ").title()))


def equipment_list(fs, *, title="EQUIPMENT LIST", align="top-right",
                   position=None, margin=0.0, include=None, width=None):
    """Build an :class:`Annotation` scheduling the major equipment.

    Each row is ``(name, description)``.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to schedule.
    title : str, default="EQUIPMENT LIST"
        Box title.
    align : str, default="top-right"
        Docking position.
    position : tuple[float, float], optional
        Top-left corner; overrides ``align``.
    margin : float, default=0.0
        Inset from the frame.
    include : Sequence[str], optional
        Unit names to list, in order, instead of the major equipment.
    width : float, optional
        Box width.

    Returns
    -------
    Annotation
        Equipment list.

    Raises
    ------
    ValueError
        If an ``include`` name is not on the sheet, ``align`` is
        invalid, or a number is not finite.
    TypeError
        If ``margin``, ``width`` or a ``position`` coordinate is a bool
        or not a real number, or a given ``position`` is not iterable.
    """
    if include is None:
        chosen = [u for u in fs.units if u.kind in _MAJOR_EQUIPMENT]
    else:
        by_name = {u.name: u for u in fs.units}
        missing = [tag for tag in include if tag not in by_name]
        if missing:
            hints = [f"{tag!r}{suggest(tag, by_name)}" for tag in missing]
            raise ValueError(
                f"equipment_list(include=...) names {', '.join(hints)}, which "
                f"{'is' if len(missing) == 1 else 'are'} not on this flowsheet. "
                f"A named row is one the schedule asserts exists; add the unit, or "
                f"drop the tag from include=."
            )
        chosen = [by_name[tag] for tag in include]
    rows = [(u.name, _describe(u)) for u in chosen]
    return Annotation(title=title, rows=rows, align=align,
                      position=position, margin=margin, width=width)


def notes(items, *, title="NOTES", align="top-right", position=None,
          margin=0.0, numbered=True, width=None):
    """Build a notes :class:`Annotation`.

    Parameters
    ----------
    items : Iterable[str]
        Note texts.
    title : str, default="NOTES"
        Box title.
    align : str, default="top-right"
        Docking position.
    position : tuple[float, float], optional
        Top-left corner; overrides ``align``.
    margin : float, default=0.0
        Inset from the frame.
    numbered : bool, default=True
        Number the notes ``1.``, ``2.``, ...
    width : float, optional
        Box width.

    Returns
    -------
    Annotation
        Notes box.

    Raises
    ------
    ValueError
        If ``align`` is invalid or a number is not finite.
    TypeError
        If ``margin``, ``width`` or a ``position`` coordinate is a bool
        or not a real number, or a given ``position`` is not iterable.
    """
    rows = []
    for i, text in enumerate(items, start=1):
        rows.append((f"{i}.", text) if numbered else text)
    return Annotation(title=title, rows=rows, align=align,
                      position=position, margin=margin, width=width)


def legend(entries, *, title="LEGEND", align="top-left",
           position=None, margin=0.0, width=None):
    """Build a legend :class:`Annotation` from abbreviation pairs.

    Parameters
    ----------
    entries : Iterable[tuple[str, str]] or dict[str, str]
        ``(abbreviation, meaning)`` pairs.
    title : str, default="LEGEND"
        Box title.
    align : str, default="top-left"
        Docking position.
    position : tuple[float, float], optional
        Top-left corner; overrides ``align``.
    margin : float, default=0.0
        Inset from the frame.
    width : float, optional
        Box width.

    Returns
    -------
    Annotation
        Legend box.

    Raises
    ------
    ValueError
        If ``align`` is invalid or a number is not finite.
    TypeError
        If ``margin``, ``width`` or a ``position`` coordinate is a bool
        or not a real number, or a given ``position`` is not iterable.
    """
    if isinstance(entries, dict):
        entries = list(entries.items())
    return Annotation(title=title, rows=[tuple(e) for e in entries],
                      align=align, position=position,
                      margin=margin, width=width)
