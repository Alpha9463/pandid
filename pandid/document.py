"""Define the title block, the sheet furniture and the drawing set.

Sheet furniture is titled boxes of text (:class:`Annotation`) or of a
bordered grid (:class:`TableBox`). A :class:`Document` checks a set of
sheets against each other.
"""

from contextlib import ExitStack
from dataclasses import dataclass, field, fields, replace
from typing import TYPE_CHECKING, Any, Literal

from pandid._checks import check_real, suggest
from pandid.deprecation import Deprecation

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit
    from pandid.validate import Issue


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


# TableBox column alignments: left, centre, right.
_COL_ALIGN = {"l", "c", "r"}


class _Box:
    """Field checks shared by the annotation and table boxes."""

    def __setattr__(self, name: str, value: Any) -> None:
        """Set a field, storing text as drawn and checking numbers and alignments.

        A ``None`` alignment takes the class default.

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
            If a numeric field or ``position`` entry is not finite, or
            ``align`` or a ``col_align`` entry is not one of its choices.
        """
        where = f"{type(self).__name__}.{name}"
        if name == "rows":
            # shortcut: rows.append skips this, convert at draw time if needed.
            value = [tuple(map(_drawn_text, r)) if isinstance(r, tuple)
                     else list(map(_drawn_text, r)) if isinstance(r, list)
                     else _drawn_text(r) for r in value]
        elif name == "headers":
            value = [_drawn_text(c) for c in value]
        elif name in ("margin", "width", "font_size") and value is not None:
            check_real(value, where)
        elif name == "position" and value is not None:
            for i, coordinate in enumerate(value):
                check_real(coordinate, f"{where}[{i}]")
        elif name == "align":
            value = getattr(type(self), "align") if value is None else value
            if value not in _ALIGN:
                raise ValueError(f"align must be one of {sorted(_ALIGN)}, got {value!r}")
        elif name == "col_align" and value is not None:
            for i, a in enumerate(value):
                if a not in _COL_ALIGN:
                    raise ValueError(
                        f"col_align[{i}] must be one of {sorted(_COL_ALIGN)} ('l'/'c'/'r' "
                        f"for left/centre/right), got {a!r}"
                    )
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
    if stated and stated.strip().casefold() == number.strip().casefold():
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

# Kinds an equipment table schedules by default.
_MAJOR_EQUIPMENT = frozenset({
    "blower", "boiler", "centrifuge", "column", "compressor", "conveyor",
    "cooler", "cooling_tower", "crusher", "crushing_machine", "crystallizer",
    "dryer", "ejector", "elevator", "evaporator", "feeder", "filter", "flare",
    "furnace", "heater", "hex", "kiln", "kneader", "mill", "pump", "reactor",
    "screening_device", "separator", "stack", "tank", "thickener", "turbine",
    "vessel",
})

# Equipment-table description of a kind whose name is not its title.
_KIND_LABELS = {
    "block": "Process Block",
    "crushing_machine": "Crushing/Grinding Machine",
    "elevator": "Bucket Elevator",
    "fitting": "In-Line Fitting",
    "funnel": "Charging Funnel",
    "furnace": "Fired Heater",
    "hex": "Heat Exchanger",
    "screening_device": "Screen",
    "tee": "Pipe Tee",
}


#: Deprecation of the drawn box's old name.
_EQUIPMENT_LIST = Deprecation(
    what="pandid.document.equipment_list(fs)",
    instead="pandid.document.equipment_table(fs)",
    removed_in="0.4.0",
)


def _scheduled_units(fs):
    """Return the units an equipment table lists by default.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to schedule.

    Returns
    -------
    list[Unit]
        Units of a major equipment kind, in sheet order.
    """
    return [u for u in fs.units if u.kind in _MAJOR_EQUIPMENT]


def _described(unit):
    """Return a unit's equipment-table description.

    Parameters
    ----------
    unit : Unit
        Unit to describe.

    Returns
    -------
    str
        The stated description, else the kind's name.
    """
    return (getattr(unit, "description", "")
            or _KIND_LABELS.get(unit.kind, unit.kind.replace("_", " ").title()))


def equipment_table(fs, *, title="EQUIPMENT LIST", align="top-right",
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
        Equipment table.

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
        chosen = _scheduled_units(fs)
    else:
        by_name = {u.name: u for u in fs.units}
        missing = [tag for tag in include if tag not in by_name]
        if missing:
            hints = [f"{tag!r}{suggest(tag, by_name)}" for tag in missing]
            raise ValueError(
                f"equipment_table(include=...) names {', '.join(hints)}, which "
                f"{'is' if len(missing) == 1 else 'are'} not on this flowsheet. "
                f"A named row is one the schedule asserts exists; add the unit, or "
                f"drop the tag from include=."
            )
        chosen = [by_name[tag] for tag in include]
    rows = [(u.name, _described(u)) for u in chosen]
    return Annotation(title=title, rows=rows, align=align,
                      position=position, margin=margin, width=width)


def equipment_list(fs, **options):
    """Build the box :func:`equipment_table` builds; deprecated.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to schedule.
    **options
        Keyword arguments of :func:`equipment_table`.

    Returns
    -------
    Annotation
        Equipment table.

    Raises
    ------
    ValueError
        As for :func:`equipment_table`.
    TypeError
        As for :func:`equipment_table`.

    Warns
    -----
    DeprecationWarning
        Always.
    """
    box = equipment_table(fs, **options)
    _EQUIPMENT_LIST.warn(fs)
    return box


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


# Line fields compared across a connector pair, with the keyword to set.
_LINE_FIELDS = (("line number", "name= or sequence="), ("service", "service="),
                ("size", "size="))

# Line number, service and size at a connector, each None if unstated.
_Line = tuple[str | None, str | None, str | None]


def _key(number: str) -> str:
    """Return a drawing number in the form two numbers compare in.

    Parameters
    ----------
    number : str
        Drawing number or reference.

    Returns
    -------
    str
        ``number`` stripped and casefolded.
    """
    return number.strip().casefold()


def _number(fs: "Flowsheet") -> str:
    """Return a sheet's drawing number, blank if it has none.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    str
        ``fs.title_block.drawing_number`` stripped, or ``""``.
    """
    block = fs.title_block
    return "" if block is None else _drawn_text(block.drawing_number).strip()


def _label(fs: "Flowsheet") -> str:
    """Return how a finding names a sheet.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    str
        The drawing number, or ``sheet 'name'`` without one.
    """
    return _number(fs) or f"sheet {fs.name!r}"


def _number_call(fs: "Flowsheet") -> str:
    """Return the call that sets a sheet's drawing number.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    str
        An assignment that keeps the sheet's other title-block fields.
    """
    if fs.title_block is None:
        return 'fs.title_block = TitleBlock(drawing_number="<number>")'
    return 'fs.title_block.drawing_number = "<number>"'


def _line(fs: "Flowsheet", flags: "list[Unit]") -> _Line:
    """Return the stated fields of the one line at a connector's flags.

    Parameters
    ----------
    fs : Flowsheet
        Sheet the flags are on.
    flags : list[Unit]
        Flags drawn for one connector.

    Returns
    -------
    tuple
        Line number, service and size, each ``None`` when unstated,
        and all ``None`` unless exactly one stream ends at the flags. A
        stream number the sheet assigned is not a line number.
    """
    runs = [s for s in fs.streams if s.source.owner in flags or s.dest.owner in flags]
    if len(runs) != 1:
        return (None, None, None)
    (s,) = runs
    return (s.name if s.has_line_number or not s.auto_named else None,
            _drawn_text(s.service) or None, _drawn_text(s.size) or None)


def _connectors(fs: "Flowsheet") -> "dict[tuple[str, str, str], tuple[list[Unit], _Line]]":
    """Return a sheet's off-page connectors and the line at each.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    dict
        ``(kind, tag, reference)`` to the flags drawn for that
        connector and their line, the reference as :func:`_key` gives.
    """
    from pandid.units import _Boundary

    groups: dict[tuple[str, str, str], list[Unit]] = {}
    for u in fs.units:
        reference = _drawn_text(u.reference)
        if isinstance(u, _Boundary) and reference.strip():
            groups.setdefault((u.kind, u.tag, _key(reference)), []).append(u)
    return {k: (flags, _line(fs, flags)) for k, flags in groups.items()}


@dataclass
class Document:
    """A set of drawing sheets, checked against each other.

    A sheet's drawing number is its ``title_block.drawing_number``. A
    Feed or Product with ``reference=`` is an off-page connector to the
    sheet of that number. Its partner is the flag of the other
    direction on that sheet whose ``reference=`` names this sheet and
    that has the same tag, or else the same stated line number.
    Drawing numbers compare without case or surrounding spaces.

    Attributes
    ----------
    sheets : list[Flowsheet]
        Sheets in the set.

    Raises
    ------
    TypeError
        If a sheet is not a :class:`~pandid.flowsheet.Flowsheet`.
    """

    sheets: "list[Flowsheet]"

    def __post_init__(self) -> None:
        """Check that every sheet is a Flowsheet.

        Raises
        ------
        TypeError
            If a sheet is not a Flowsheet.
        """
        from pandid.flowsheet import Flowsheet

        self.sheets = list(self.sheets)
        for i, fs in enumerate(self.sheets):
            if not isinstance(fs, Flowsheet):
                raise TypeError(
                    f"Document(sheets) takes Flowsheets; sheets[{i}] is {fs!r}"
                )

    def validate(self) -> "list[Issue]":
        """Return the findings across sheets, errors first, then warnings.

        Number each sheet's streams first, as a render does, and keep
        those numbers; a call that raises leaves every sheet unchanged.
        A sheet's own findings come from its ``validate()``.

        Returns
        -------
        list[Issue]
            Findings, each naming the sheets it involves.

        Raises
        ------
        ValueError
            If a sheet's naming scheme cannot name a stream.
        """
        with ExitStack() as unchanged:
            for fs in self.sheets:
                unchanged.enter_context(fs._unchanged_if_it_raises())
            return self._findings()

    def _findings(self) -> "list[Issue]":
        """Number each sheet's streams and return the findings across sheets.

        Returns
        -------
        list[Issue]
            Findings, errors first, then warnings.

        Raises
        ------
        ValueError
            If a sheet's naming scheme cannot name a stream.
        """
        from pandid.units import _Boundary
        from pandid.validate import Issue

        found: list[Issue] = []
        by_number: dict[str, list[Flowsheet]] = {}
        for fs in self.sheets:
            fs.renumber_streams()
            if _number(fs):
                by_number.setdefault(_key(_number(fs)), []).append(fs)
        for same in by_number.values():
            if len(same) > 1:
                names = ", ".join(repr(fs.name) for fs in same)
                found.append(Issue("error", "drawing-number-duplicate", (
                    f"Sheets {names} share drawing number {_number(same[0])!r}, so "
                    f"a reference to it cannot say which. Give each sheet its "
                    f"own number: {_number_call(same[-1])} on {same[-1].name!r}."
                )))

        connectors = {id(fs): _connectors(fs) for fs in self.sheets}
        for fs in self.sheets:
            here, cut_off = _number(fs), []
            for (kind, tag, reference), (flags, line) in connectors[id(fs)].items():
                where = f"{type(flags[0]).__name__}({tag!r}) on {_label(fs)}"
                far = by_number.get(reference)
                if far is None:
                    found.append(Issue("warning", "reference-not-in-set", (
                        f"{where} names drawing {_drawn_text(flags[0].reference)!r}, "
                        f"which is not in this Document. Add that sheet to "
                        f"Document([...]), or correct the flag's reference=."
                    )))
                    continue
                there = _number(far[0])
                if not here:
                    cut_off.append(there)
                    continue
                partner_kind = "feed" if kind == "product" else "product"
                candidates = {k: v for k, v in connectors[id(far[0])].items()
                              if k[0] == partner_kind and k[2] == _key(here)}
                partner = next((k for k in candidates if k[1] == tag), None)
                if partner is None and line[0] is not None:
                    partner = next((k for k, (_, far_line) in candidates.items()
                                    if far_line[0] == line[0]), None)
                if partner is None:
                    partner_cls = partner_kind.title()
                    found.append(Issue("error", "connector-unmatched", (
                        f"{where} continues onto {there}, which has no "
                        f"{partner_cls} pointing back at {here} with the same tag "
                        f"or line number. Add {partner_cls}({tag!r}, "
                        f"reference={here!r}) to {there}, or correct reference= on "
                        f"{where}."
                    )))
                    continue
                far_flags, far_line = candidates[partner]
                differ = [(field, keyword, mine, theirs)
                          for (field, keyword), mine, theirs in zip(_LINE_FIELDS, line, far_line)
                          if mine is not None and theirs is not None and mine != theirs]
                # Report a pair once, from the sheet the line leaves.
                if kind == "product" and differ:
                    disagree = "; ".join(f"{field} {mine!r} on {here} and {theirs!r} on {there}"
                                         for field, _, mine, theirs in differ)
                    fields = " and ".join(f"{field} ({keyword})"
                                          for field, keyword, _, _ in differ)
                    found.append(Issue("error", "connector-line-mismatch", (
                        f"{where} and {type(far_flags[0]).__name__}({partner[1]!r}) "
                        f"on {there} are one line but disagree on {disagree}. Give "
                        f"connect() the same {fields} on both sheets."
                    )))
            if cut_off:
                found.append(Issue("error", "drawing-number-missing", (
                    f"Sheet {fs.name!r} has no drawing number, so "
                    f"{', '.join(dict.fromkeys(cut_off))} cannot point its connectors "
                    f"back at it. Number it: {_number_call(fs)}."
                )))

        tagged: dict[str, dict[str, list[tuple[str, str]]]] = {}
        for fs in self.sheets:
            for u in fs.units:
                if not isinstance(u, _Boundary):
                    tagged.setdefault(u.name, {}).setdefault(u.kind, []).append(
                        (type(u).__name__, _label(fs)))
        for tag, kinds in tagged.items():
            if len(kinds) > 1:
                shown = " and ".join(f"{cls}({tag!r}) on {sheet}"
                                     for drawn in kinds.values() for cls, sheet in drawn)
                last = next(reversed(kinds.values()))[0][0]
                found.append(Issue("error", "tag-reused", (
                    f"{shown} share one tag but are different kinds of equipment. "
                    f"A tag names one piece of equipment: build one of them under "
                    f'another tag, such as {last}("<new tag>").'
                )))
        return sorted(found, key=lambda issue: issue.severity != "error")
