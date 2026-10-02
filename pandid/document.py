"""Drawing documentation: the title block and sheet furniture.

Set ``fs.title_block = TitleBlock(...)`` to draw a full-width title strip:
revision history, company cell, and client, project, status, drawing
number, title, date, scale and revision cells. These are the ISO 7200
title-block fields that ISO 10628-1 5.1.2 requires on a process diagram;
seven of the eight mandatory ISO 7200 fields have a cell, and document
type does not. The strip follows the title block, not the border, so a
PFD carries one too; ``border="zone"`` adds the zone-ruled frame.

Sheet furniture is generic titled boxes: :class:`Annotation` (a title
over free or columnar text) and :class:`TableBox` (a title over a
bordered grid). :func:`equipment_list`, :func:`notes` and :func:`legend`
build the common annotations. Add a box with ``fs.annotations.append(...)``
or ``fs.add_annotation(...)``; it is drawn whichever border is used.
"""

import re
from dataclasses import dataclass, field, fields, replace
from typing import Any, Literal

from pandid._checks import check_real

# --------------------------------------------------------------
# Location references (ISO 15519-1:2010 Clause 9)
# --------------------------------------------------------------

# A zone, row or column (ISO 15519-1 5.1.2): rows are letters and columns
# numbers, so a zone is row then column ("B3"); "3B" is refused.
_ZONE = re.compile(r"\A(?:[A-Za-z]+[0-9]+|[A-Za-z]+|[0-9]+)\Z")

# Signs Clause 9 reserves as separators; refused inside a part.
_SEPARATORS = "/."


def _clean(value, field_name: str) -> str:
    """Return one location-reference part as stripped text.

    Parameters
    ----------
    value : object
        Part value; ``None`` or empty gives ``""``.
    field_name : str
        Part name, for error messages.

    Returns
    -------
    str
        Stripped text.

    Raises
    ------
    ValueError
        If the part contains whitespace, ``/`` or ``.``.
    """
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

    The parts appear in the order document, sheet, then column, row or
    zone; the solidus introduces the sheet and the full stop the zone. A
    part left out narrows the reference's scope without changing its
    shape. This reproduces all seven rows of Clause 9 Table 2:

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

    A document alone (``PFD-302``) is what an off-page connector usually
    carries. The result is a plain string for ``reference=``.

    Parameters
    ----------
    document : str, default=""
        Document number.
    sheet : str, default=""
        Sheet number; only checked for the reserved signs, since sheet
        numbering is the drawing office's (ISO 15519-1 5.2.3).
    zone : str, default=""
        Zone (``"B3"``), row (``"B"``) or column (``"3"``), checked against
        ISO 15519-1 5.1.2.

    Returns
    -------
    str
        Location reference.

    Raises
    ------
    ValueError
        If every part is empty, a part contains whitespace or a reserved
        sign, or ``zone`` is not a zone, row or column.
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
    # Keep the solidus when only the zone is given ("4334/.B3", Table 2).
    out = document
    if sheet or zone:
        out += "/" + sheet
    if zone:
        out += "." + zone
    return out


@dataclass
class Revision:
    """One row of the revision history.

    Attributes
    ----------
    rev, date, description : str
        Revision mark, date and description.
    by, checked, approved : str
        Initials; ``checked`` and ``approved`` may be blank, which leaves
        their cells empty.
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

    ``client`` and ``project`` are not ISO 7200 fields (ISO 7200's legal
    owner is ``company``), but issued sheets name them; a blank one draws
    no line. A blank ``sheet`` or ``of_sheets`` draws its default of
    ``"1"``, since half a count names no sheet. The scale cell is always
    ruled, so the other cells keep their widths; left blank, it shows the
    ratio the drawing was placed at when ``page_size`` fixes the page.

    Attributes
    ----------
    title, subtitle : str
        Title lines, such as ``"Ethanol Purification A300"`` over
        ``"Process Flow Diagram 1"``.
    drawing_number, project, client : str
        Information cells.
    company : str
        Logo and company cell: the organisation issuing the drawing.
    status : str
        Issue status, such as ``"ISSUED FOR REVIEW"``.
    sheet, of_sheets : str
        The ``SHEET n of m`` count; both default to ``"1"``.
    scale : str
        Scale cell, such as ``"NTS"`` or ``"1:100"``; blank to report the
        placed scale, if any.
    drawn_by, checked_by, approved_by, date : str
        Initials and date.
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
    """Return the text a title-block field draws.

    Fields are annotated ``str`` but not enforced, so ``sheet=1`` works.
    The constructor and :meth:`~pandid.Flowsheet.from_dict` both use this,
    so a written spec reads back. ``None`` (YAML's empty value) is blank.
    Whitespace is kept; the drawn cell strips it.

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


def _drawn_text_fields(cls: type) -> frozenset[str]:
    """Return the dataclass fields that hold drawn text.

    A field with a string default holds text, so ``revisions`` and any
    later non-text field are left out. This is the test
    :func:`~pandid.render.furniture._class_defaults` uses, so the spec
    reader and the strip agree.

    Parameters
    ----------
    cls : type
        :class:`TitleBlock` or :class:`Revision`.

    Returns
    -------
    frozenset[str]
        Field names.
    """
    return frozenset(f.name for f in fields(cls) if isinstance(f.default, str))


# Nine docking positions on the sheet frame, not the drawing: "top-right"
# puts the box's corner in the frame's corner, "top" centres it on the
# top edge.
_ALIGN = {
    "top-left", "top", "top-right",
    "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
}


def _resolve_align(align, default):
    """Return the alignment, checked against the nine docking positions.

    Parameters
    ----------
    align : str or None
        Requested alignment; ``None`` for ``default``.
    default : str
        Box type's default.

    Returns
    -------
    str
        Alignment.

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
        ``"l"``, ``"c"`` or ``"r"`` per column; ``None`` centres every
        column.

    Returns
    -------
    list[str] or None
        ``col_align`` unchanged.

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


def _check_box_number(box: object, name: str, value: Any) -> None:
    """Refuse a non-number for an annotation or table box's layout field.

    Parameters
    ----------
    box : Annotation or TableBox
        Box being set.
    name : str
        Field name.
    value : Any
        New value.

    Raises
    ------
    TypeError
        If ``margin``, ``width`` or ``font_size`` is not a number, or a
        ``position`` coordinate is not one. ``None`` is allowed where the
        field takes it.
    """
    where = f"{type(box).__name__}.{name}"
    if name in ("margin", "width", "font_size") and value is not None:
        check_real(value, where)
    elif name == "position" and value is not None:
        for i, coordinate in enumerate(value):
            check_real(coordinate, f"{where}[{i}]")


@dataclass
class Annotation:
    """Titled text box placed on the sheet.

    A row is a string (one left-aligned line) or a sequence of cells that
    align into columns, enough for an equipment schedule
    (``("T-301", "Beer Column")``) or a legend (``("SS", "316L")``).

    Attributes
    ----------
    title : str
        Box title.
    rows : list
        Lines or cell sequences.
    align : str
        Docking position on the sheet frame, one of nine (corners, edge
        centres or ``"center"``); default ``"top-right"``.
    position : tuple[float, float] or None
        Top-left corner in sheet coordinates; overrides ``align``.
    margin : float
        Inset of a docked box from the frame; 0 is flush.
    width : float or None
        Box width; sized to content when ``None``.
    font_size : float
        Type size.

    Raises
    ------
    TypeError
        If ``margin``, ``width``, ``font_size`` or a ``position``
        coordinate is not a number, at construction or on assignment.
    ValueError
        If ``align`` is not a docking position.
    """
    title: str = ""
    rows: list = field(default_factory=list)
    align: str = "top-right"
    position: tuple[float, float] | None = None
    margin: float = 0.0
    width: float | None = None
    font_size: float = 11.0

    def __post_init__(self):
        """Check the alignment."""
        self.align = _resolve_align(self.align, "top-right")

    def __setattr__(self, name: str, value: Any) -> None:
        """Set a field, refusing a non-number for a layout field.

        Parameters
        ----------
        name : str
            Field name.
        value : Any
            New value.

        Raises
        ------
        TypeError
            If a layout field receives a non-number.
        """
        _check_box_number(self, name, value)
        super().__setattr__(name, value)


@dataclass
class TableBox:
    """Bordered table with a title, header row and body rows.

    Cells are drawn with ``str``. Placement works as for
    :class:`Annotation`.

    Attributes
    ----------
    title : str
        Table title.
    headers : list[str]
        Header cells.
    rows : list[list]
        Body rows.
    align : str
        Docking position; default ``"bottom-right"``.
    position : tuple[float, float] or None
        Top-left corner; overrides ``align``.
    margin : float
        Inset of a docked box from the frame.
    font_size : float
        Type size.
    col_align : list[str] or None
        ``"l"``, ``"c"`` or ``"r"`` per column; centred when ``None``.

    Raises
    ------
    TypeError
        If ``margin``, ``font_size`` or a ``position`` coordinate is not a
        number, at construction or on assignment.
    ValueError
        If ``align`` or a ``col_align`` entry is invalid.
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
        """Check the alignment and column alignments."""
        self.align = _resolve_align(self.align, "bottom-right")
        self.col_align = _resolve_col_align(self.col_align)

    def __setattr__(self, name: str, value: Any) -> None:
        """Set a field, refusing a non-number for a layout field.

        Parameters
        ----------
        name : str
            Field name.
        value : Any
            New value.

        Raises
        ------
        TypeError
            If a layout field receives a non-number.
        """
        _check_box_number(self, name, value)
        super().__setattr__(name, value)


@dataclass
class StreamTableOptions:
    """Stream property table options for one sheet: ``fs.stream_table``.

    Every flowsheet has one::

        fs.stream_table.font_size = 8.0
        fs.stream_table.column_width = "auto"

    The options describe the sheet, not the output file, so they live on
    the flowsheet rather than as keywords on every render call.
    :attr:`font_size` scales both width floors, so a smaller table keeps
    its proportions. The last two fields are read only by a render with
    ``show_stream_table="sheet"``, whose title block is derived by
    :func:`table_sheet_block`. Section headings are content, so they are
    :attr:`~pandid.flowsheet.Flowsheet.stream_table_sections`, not an
    option.

    Attributes
    ----------
    font_size : float or None
        Type size in drawing units, or ``None`` to choose from the column
        count (10.5 up to 18 columns, smaller beyond). Row height and
        minimum column widths scale with it, so a stated size also shrinks
        the ruling.
    label_width : float or "auto"
        Minimum width of the row-label column; ``"auto"`` rules it at its
        content. A long label still widens the column past this floor.
    column_width : float or "auto"
        Minimum width of every stream column. All stream columns share one
        width, measured over every name and value, so ``"auto"`` is
        content-ruled: one long value widens every column.
    sheet_subtitle : str
        Subtitle of the table's own sheet; the diagram's title stays above
        it.
    sheet_drawing_number : str
        Drawing number of the table's own sheet. Blank derives the
        diagram's number plus :data:`TABLE_SHEET_SUFFIX`; the diagram's own
        number is refused. With both blank, the table sheet is unnumbered
        and reported as :data:`~pandid.render.svg.TABLE_SHEET_UNNUMBERED`.
    """

    font_size: float | None = None
    label_width: float | Literal["auto"] = 122.0
    column_width: float | Literal["auto"] = 52.0
    sheet_subtitle: str = "Stream Table"
    sheet_drawing_number: str = ""


#: Suffix added to the diagram's number for a derived table-sheet number.
TABLE_SHEET_SUFFIX = "-ST"


def table_sheet_block(block: "TitleBlock | None",
                      options: StreamTableOptions) -> TitleBlock:
    """Return the title block for the stream table's own sheet.

    A copy of the diagram's block with the subtitle and drawing number
    changed; the table sheet belongs to the same issue. The revision list
    is shared, not copied. A flowsheet with no title block gets one
    carrying only the subtitle.

    Parameters
    ----------
    block : TitleBlock or None
        Diagram's title block.
    options : StreamTableOptions
        Table options giving the subtitle and number.

    Returns
    -------
    TitleBlock
        Table sheet's title block.

    Raises
    ------
    ValueError
        If ``options.sheet_drawing_number`` is the diagram's own number,
        which would file two documents under one number.
    """
    diagram = TitleBlock() if block is None else block
    number = diagram.drawing_number
    # Drawn text, so a number such as 100 is read as "100".
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
    """Return whether two drawing numbers are the same.

    Outer whitespace is stripped and case folded with ``str.casefold``,
    which also folds compatibility forms (``ß`` equals ``ss``). Interior
    spaces, punctuation and zero-width characters stay significant.

    Parameters
    ----------
    a, b : str
        Drawing numbers.

    Returns
    -------
    bool
        Whether a register would file them as one drawing.
    """
    return a.strip().casefold() == b.strip().casefold()


# Stream label enclosures; "none" is the bare number on its halo.
_ENCLOSURES = ("none", "diamond", "circle", "box")


# Other names for an enclosure, suggested in the error but not accepted,
# so every sheet spells each shape one way. Looked up stripped and
# lower-cased.
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

    Called by the constructor, by
    :meth:`~pandid.flowsheet.Flowsheet._prepare_to_draw` for later
    assignments, and by :func:`~pandid.spec.to_dict` and
    :func:`~pandid.spec._read_stream_labels`, so the Python and file APIs
    agree.

    Parameters
    ----------
    shape : str
        Enclosure name.

    Returns
    -------
    str
        ``shape`` unchanged.

    Raises
    ------
    ValueError
        If ``shape`` is not an enclosure; a known synonym is named in the
        message.
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

    Every flowsheet has one::

        fs.stream_labels.enclosure = "diamond"

    Kept apart from :class:`StreamTableOptions` because the labels and the
    table are separate drawings.

    Attributes
    ----------
    enclosure : {"none", "diamond", "circle", "box"}
        Shape ruled around every stream label; ``"none"`` draws the bare
        number on its halo.

    Notes
    -----
    An enclosed stream number is a drafting convention (common in North
    American practice and textbooks), not an ISO 10628 or ISO 15519 rule.
    Every enclosure is sized to the longest label on the sheet, so all
    match. An enclosed label stays on its run; if it does not fit, it is
    drawn anyway and reported on ``fs.warnings`` as
    ``enclosure-over-unit``, ``enclosure-over-line`` or
    ``enclosure-over-label``, so spacing the sheet is the remedy. The
    shape is an outline and its plate covers only the labelled run; where
    the run is too short, no plate is drawn and crossing lines show
    through the number. Long line numbers make large enclosures;
    ``"circle"`` is the tightest but resembles an instrument balloon.

    Raises
    ------
    ValueError
        If ``enclosure`` is not one of the four shapes.
    """

    enclosure: Literal["none", "diamond", "circle", "box"] = "none"

    def __post_init__(self):
        """Check the enclosure."""
        self.enclosure = _resolve_enclosure(self.enclosure)


# --------------------------------------------------------------
# Convenience constructors for the common boxes
# --------------------------------------------------------------

# Kinds an equipment list schedules by default: major plant with a tag,
# datasheet and purchase order. Excluded: bulk piping items (valves,
# fittings, reducers, tees, vents, funnels), mixers and splitters (piping
# branches), boundaries and instruments. ``include=`` overrides this for a
# valve or instrument schedule.
_MAJOR_EQUIPMENT = frozenset({
    "blower", "boiler", "column", "compressor", "conveyor", "cooler",
    "cooling_tower", "crusher", "dryer", "ejector", "elevator", "evaporator",
    "feeder", "filter", "flare", "furnace", "heater", "hex", "kiln", "kneader",
    "mill", "pump", "reactor", "screening_device", "separator", "stack", "tank",
    "thickener", "turbine", "vessel",
})
# Boilers, stacks and flares are ISO 10628-2 group-4 equipment with a
# foundation and datasheet, unlike a vent cap. A block is absent because
# it stands for a whole plant section; include= still accepts one.

# Kind -> description for an equipment list, so a row does not show the
# lookup key (``Hex``).
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
    """Return the equipment-list description for a unit.

    Parameters
    ----------
    unit : Unit
        Unit to describe.

    Returns
    -------
    str
        The unit's ``description``, else its kind's name.
    """
    return (getattr(unit, "description", "")
            or _KIND_LABELS.get(unit.kind, unit.kind.replace("_", " ").title()))


def equipment_list(fs, *, title="EQUIPMENT LIST", align="top-right",
                   position=None, margin=0.0, include=None, width=None):
    """Build an :class:`Annotation` scheduling the major equipment.

    Each row is ``(tag, description)``, using the unit's ``description``
    or its kind's name. By default only major equipment is listed
    (:data:`_MAJOR_EQUIPMENT`); ``include`` lists any named units instead,
    in the order given, for a valve or instrument schedule.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to schedule.
    title : str, default="EQUIPMENT LIST"
        Box title.
    align : str, default="top-right"
        Docking position; see :class:`Annotation`.
    position : tuple[float, float], optional
        Top-left corner; overrides ``align``.
    margin : float, default=0.0
        Inset from the frame.
    include : Sequence[str], optional
        Tags to list, in order.
    width : float, optional
        Box width.

    Returns
    -------
    Annotation
        Equipment list.

    Raises
    ------
    ValueError
        If ``include`` names a tag not on the flowsheet; the message
        suggests a close match. Raised rather than warned because a
        schedule one row short reads as complete.
    """
    if include is None:
        chosen = [u for u in fs.units if u.kind in _MAJOR_EQUIPMENT]
    else:
        by_name = {u.name: u for u in fs.units}
        missing = [tag for tag in include if tag not in by_name]
        if missing:
            from difflib import get_close_matches

            hints = []
            for tag in missing:
                close = get_close_matches(tag, list(by_name), n=1, cutoff=0.6)
                hints.append(f"{tag!r}" + (f" (did you mean {close[0]!r}?)" if close else ""))
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
        Docking position; see :class:`Annotation`.
    position : tuple[float, float], optional
        Top-left corner; overrides ``align``.
    margin : float, default=0.0
        Inset from the frame.
    numbered : bool, default=True
        Number the notes ``1.``, ``2.``, ...; otherwise one plain line
        each.
    width : float, optional
        Box width.

    Returns
    -------
    Annotation
        Notes box.
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
        ``(abbreviation, meaning)`` pairs; a dict keeps insertion order.
    title : str, default="LEGEND"
        Box title.
    align : str, default="top-left"
        Docking position; see :class:`Annotation`.
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
    """
    if isinstance(entries, dict):
        entries = list(entries.items())
    return Annotation(title=title, rows=[tuple(e) for e in entries],
                      align=align, position=position,
                      margin=margin, width=width)
