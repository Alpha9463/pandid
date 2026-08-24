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
from dataclasses import dataclass, field, replace
from typing import Literal

# --------------------------------------------------------------
# Location references (ISO 15519-1:2010 Clause 9)
# --------------------------------------------------------------

#: How a zone may be spelled. ISO 15519-1 §5.1.2 builds the grid from
#: columns designated with numbers and rows designated with letters, and
#: calls the cross-section of one column and one row a zone. So a zone is
#: its row letter followed by its column number (Table 2's ``B3``), and a
#: row or a column on its own is the letter or the number alone. ``3B``
#: is neither, and is the mistake this rejects.
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

    Clause 9, *Location references*, covers a reference to a document, to
    a sheet of a document, and to a column, a row or a zone on a sheet,
    each of them spelled against the §5.1.2 grid. It reserves the solidus
    for the sheet and the full stop for the column, row or zone, and
    fixes the order they are presented in: document, then sheet, then
    column, row or zone.

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

    ``sheet`` and ``of_sheets`` are the two halves of the ``SHEET n of
    m`` count in the title band, and they are the only two fields that
    default to something other than blank: a drawing with no set behind
    it is sheet 1 of 1. **A blank half draws that default**, on both
    backends and however the block is edited, because half a count reads
    as a different sheet -- ``SHEET  of 1`` names no sheet at all, and
    is short enough that no width check would ever have spoken up about
    it.

    ``scale`` is the scale cell. Left blank, the sheet reports the ratio
    the renderer actually placed the drawing at, which is a real number
    once ``page_size`` fixes the page and nothing at all on a sheet
    sized to fit its drawing, which is at no scale to state. Give the
    field a value (``"NTS"``, ``"1:100"``) to state one regardless.

    The cell is **ruled either way**. A title block is a form and its
    boxes belong to the form, so an unstated scale leaves an empty box
    rather than removing one -- and the three cells beside it keep their
    widths, which is what stops ``drawing_number`` being budgeted one
    width by ``to_svg()`` and a narrower one by
    ``to_svg(page_size=...)``.
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


#: A :class:`TableBox` column's alignment: left, centre or right, spelled
#: short. The spelled-out word is the obvious guess, and both renderers
#: used to answer it by silently centring rather than raising.
_COL_ALIGN = {"l", "c", "r"}


def _resolve_col_align(col_align):
    """``col_align``, checked entry by entry against the three spellings
    the renderers key off. ``None`` passes through unchanged; a table
    with no ``col_align`` is centred by default and that is not this
    function's business to say.
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
        self.col_align = _resolve_col_align(self.col_align)


@dataclass
class StreamTableOptions:
    """How the stream property table is drawn, on the sheet that draws
    it: ``fs.stream_table``.

    Every flowsheet has one, so nothing is imported and nothing is
    constructed to use it::

        fs.stream_table.font_size = 8.0
        fs.stream_table.column_width = "auto"

    **An object rather than an attribute apiece, on purpose.**
    ``render()`` already carries nine keywords and three of the four
    output calls restate every one of them, so a table option spelled
    there costs four signatures; and a table option means nothing to
    ``to_drawio()`` differently from ``to_svg()``, because it describes
    the sheet rather than the file. Settling it on the flowsheet says it
    once for every way the sheet comes out. A bare
    ``fs.stream_table_font_size`` would have done as much for the first
    option and nothing for the two that followed it a release later:
    each such attribute adds a prefix-string to ``Flowsheet``'s
    namespace, a line to its ``__init__``, a key to the spec's top level
    and a paragraph to the docs, and nothing groups them. One object
    costs none of that, an option is a field rather than a fifth
    signature change, and validation of the group has somewhere to live.

    The three sizing fields compose. :attr:`font_size` scales both width
    floors, since both are stated at the type size they were chosen
    against; so a table sized down keeps its proportions, and a table
    sized down *and* ``"auto"``-ruled has no floor left to scale.

    The last two say who the table's own sheet is, and are read only by
    a render that asks for one (``show_stream_table="sheet"``). They are
    here rather than on :class:`TitleBlock` because a flowsheet has one
    title block and that one is the *diagram's*: the table sheet's is
    derived from it (:func:`table_sheet_block`), and what a derivation
    needs is the two fields it cannot work out for itself.

    :attr:`~pandid.flowsheet.Flowsheet.stream_table_sections` is *not*
    here, deliberately. It is content and not a setting -- the heading
    text drawn in the table, authored per sheet exactly as
    ``title_block`` and ``annotations`` are -- and it is a flowsheet
    attribute for the reason those two are.
    """

    #: Type size for the whole table, in drawing units, or ``None`` to
    #: let the table pick one from how many columns it has (10.5 up to
    #: 18 columns, shrinking from there). What is set here **rules the
    #: table and not only its lettering**: the row height and the
    #: minimum column widths follow it in proportion, so a table that
    #: overruns its page has a remedy short of a bigger page.
    #:
    #: The two regimes part company only above 18 columns, where the
    #: automatic size is chosen to keep long values inside a column
    #: already at its minimum width and so leaves that minimum alone. A
    #: size stated here is the author overruling that judgement for a
    #: sheet that has to fit a given page, and it would do nothing at
    #: all if it did not reach the ruling as well as the glyphs.
    font_size: float | None = None

    #: Narrowest the row-label column -- the leftmost one, carrying the
    #: corner heading and every property name -- is ruled: a number of
    #: drawing units, or ``"auto"`` to rule it at its own content.
    #:
    #: A number is a **floor and not a width.** The column is measured
    #: from what goes in it and only held *up* to this, so a long
    #: property name widens it past whatever is stated here rather than
    #: running into the cell beside it. Stating a bigger number is
    #: therefore the way to buy a wide label column; stating a smaller
    #: one, or ``"auto"``, is the way to stop paying for one.
    #:
    #: The default keeps a table of short property names from being
    #: ruled too narrow to read across. It is worth nothing on a sheet
    #: whose row labels are ``Total Flow (kg/h)`` and everything on a
    #: sheet whose rows are ``pH`` -- which is why it is a default and
    #: not a rule.
    label_width: float | Literal["auto"] = 122.0

    #: Narrowest **every** stream column is ruled: a number of drawing
    #: units, or ``"auto"`` to rule them at their content.
    #:
    #: The stream columns are one width, always. A stream table is read
    #: down for one stream and across for one property, and columns that
    #: did not line up would be a worse drawing than a wide one; so the
    #: width is measured once, over every stream name *and* every value
    #: in the table, and every column is ruled at it.
    #:
    #: That is what makes ``"auto"`` **content-ruled rather than
    #: fitted**, and the difference matters: one ``1013.25 mbara`` among
    #: three-figure values rules all fifty-five columns at it. ``"auto"``
    #: never comes out wider than the floor it drops -- it is the same
    #: measurement without the clamp -- but it is not always narrow, and
    #: a table that gains nothing from it is a table whose widest cell
    #: was already doing the ruling.
    column_width: float | Literal["auto"] = 52.0

    #: What the table's own sheet is called, drawn in the strip's
    #: **subtitle** cell. The title cell above it keeps the diagram's
    #: title, which is what tells a reader the two sheets are one
    #: drawing set: ``Ethanol Purification A300`` over ``Stream Table``,
    #: where the diagram reads ``Ethanol Purification A300`` over
    #: ``Process Flow Diagram 1``.
    #:
    #: Read only by a render that puts the table on its own sheet
    #: (``show_stream_table="sheet"``); a table docked at the foot of a
    #: diagram has no title block of its own.
    sheet_subtitle: str = "Stream Table"

    #: The drawing number the table's own sheet carries. Blank derives
    #: one: the diagram's number with :data:`TABLE_SHEET_SUFFIX` after
    #: it, so ``PFD-301`` numbers its table sheet ``PFD-301-ST``.
    #:
    #: **Derived, because two drawings cannot share one number**, and
    #: stated here when the drawing office's own numbering says
    #: otherwise -- a set that files the table as the next sheet in the
    #: series types ``fs.stream_table.sheet_drawing_number = "PFD-303"``.
    #: A suffix can be derived from what the flowsheet already carries
    #: and the next free number in a series cannot: nothing here knows
    #: what else that series has issued.
    #:
    #: Stating the **diagram's own** number here raises: that is the
    #: collision the derivation exists to prevent, and a derivation
    #: guarantees uniqueness only while nobody overrules it. Leaving
    #: both this and the diagram's number blank draws the table sheet
    #: unnumbered and reports it
    #: (:data:`~pandid.render.svg.TABLE_SHEET_UNNUMBERED`); a number
    #: invented from the flowsheet's name would be worse than the blank,
    #: because it would look issued.
    sheet_drawing_number: str = ""


#: What a derived table-sheet drawing number puts after the diagram's.
TABLE_SHEET_SUFFIX = "-ST"


def table_sheet_block(block: "TitleBlock | None",
                      options: StreamTableOptions) -> TitleBlock:
    """The title block the stream table's own sheet carries.

    The diagram's, with two cells changed. Everything else is copied
    across unread -- company, client, project, status, revisions, the
    date, the initials -- because the table sheet is a sheet of the same
    issue by the same office on the same day, and a table sheet that
    named a different client would be a different document.

    The two that change are the two that say *which drawing this is*:
    the subtitle, which is what the sheet is called
    (:attr:`~StreamTableOptions.sheet_subtitle`), and the drawing
    number, which cannot be the diagram's
    (:attr:`~StreamTableOptions.sheet_drawing_number`).

    A flowsheet with no title block at all still gets one here: a table
    sheet is a drawing in its own right and a drawing without a title
    block is a table on blank paper. It comes out carrying the subtitle
    and nothing else, which is what there is to say.

    The revision *list* is the diagram's own object rather than a copy
    of it. Both sheets are issued at the same revision, and this block
    is derived afresh on every render, so a copy would be a second list
    to keep in step for no gain.

    Raises :class:`ValueError` if the number stated for the table sheet
    is the diagram's own. **A derivation cannot promise uniqueness on
    its own**: the suffix guarantees it only while nobody overrules the
    suffix, and ``sheet_drawing_number = "PFD-301"`` on a ``PFD-301``
    diagram is two documents filed under one number -- the failure the
    derivation exists to prevent, typed in by hand. It is refused rather
    than warned about because the author stated it outright and there is
    no reading of it that produces a filable set.
    """
    diagram = TitleBlock() if block is None else block
    number = diagram.drawing_number
    stated = options.sheet_drawing_number
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
    """Are these one drawing number said twice?

    Surrounding space is stripped and the rest is **case-folded**,
    because a drawing register does not file ``PFD-301`` and
    ``pfd-301 `` as two drawings and neither does the person looking for
    one. Two numbers that differ only that way are the collision this is
    looking for, not an escape from it.

    ``str.casefold`` is aggressive by design and does more than lower the
    case: it also folds the compatibility forms, so the ``ﬃ`` ligature
    equals ``ffi`` and ``ß`` equals ``ss``. That is stated because it is
    more than "case", and it is *kept* because it is the same judgement
    one step further -- two numbers a reader could not tell apart are
    one number, and nobody files a drawing under a ligature to
    distinguish it from the same letters typed out.

    What is deliberately **not** folded is anything that changes what a
    reader sees: interior spaces (``PFD 301`` is not ``PFD301``), a
    trailing full stop, or a zero-width character, all of which stay
    distinct. Only the outer whitespace and the letter case come out.
    """
    return a.strip().casefold() == b.strip().casefold()


#: The shapes a stream label may be enclosed in, and ``"none"`` for the
#: bare number on its halo. The three are what drawing offices actually
#: rule around a stream number; there is no fourth in common use, and
#: the set is closed rather than open for the reason
#: :func:`_resolve_col_align` closes its own: a name outside it used to
#: be a shape silently not drawn.
_ENCLOSURES = ("none", "diamond", "circle", "box")


#: What an author reaches for instead, and what this package spells it.
#:
#: Named in the refusal and **not accepted**: the set stays closed, so
#: one sheet cannot spell in ``rhombus`` what the next spells in
#: ``diamond`` and no reader has to know both. But ``rhombus`` is the
#: word the geometry texts use and ``oval`` the word a drawing office
#: uses, so an author typing one of them has not made a typing mistake
#: -- they have used the other name for the thing they want, and being
#: handed the list without being told which of it they meant leaves
#: them to guess. Lower-cased and stripped before the lookup, since a
#: field taken off a form arrives that way.
_ENCLOSURE_MEANT = {
    "rhombus": "diamond", "rhomb": "diamond", "lozenge": "diamond",
    "ellipse": "circle", "oval": "circle", "round": "circle",
    "balloon": "circle", "bubble": "circle",
    "rect": "box", "rectangle": "box", "square": "box", "frame": "box",
    "border": "box",
    "off": "none", "plain": "none", "bare": "none", "nothing": "none",
}


def _resolve_enclosure(shape):
    """*shape*, checked against :data:`_ENCLOSURES`.

    Called from every door into the field, because a plain attribute of
    a closed set has more than one: :meth:`StreamLabelOptions.__post_init__`
    for the constructor, :meth:`~pandid.flowsheet.Flowsheet._prepare_to_draw`
    for the author who assigns to it afterwards (``fs.stream_labels.enclosure
    = "rhombus"``), :func:`~pandid.spec.to_dict` on the way out to a file
    and :func:`~pandid.spec._read_stream_labels` on the way back in. One
    sentence at all four, so the Python API and the file API cannot
    disagree about what a name means.
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
    """How the stream labels -- the numbers written on the lines -- are
    drawn, on the sheet that draws them: ``fs.stream_labels``.

    Every flowsheet has one, so nothing is imported and nothing is
    constructed to use it::

        fs.stream_labels.enclosure = "diamond"

    A sibling of :class:`StreamTableOptions` and for its reasons: a
    label option describes the *sheet*, so it means the same thing to
    ``to_drawio()`` as to ``to_svg()`` and would otherwise be a tenth
    keyword on ``render()`` restated across four output signatures.
    The two objects are kept apart because they are two drawings -- the
    table is the block of properties docked to the sheet, these are the
    marks on the pipes -- and merging them would put ``enclosure``
    beside ``column_width`` where neither can affect the other.
    """

    #: The shape ruled around every stream label: ``"none"`` (the
    #: default, the bare number on its opaque halo), ``"diamond"``,
    #: ``"circle"`` or ``"box"``.
    #:
    #: **A drafting convention, not a standard.** A stream number in a
    #: diamond is widespread in North American practice and in the
    #: chemical-engineering textbooks, and courses and company drawing
    #: standards ask for it; no clause of ISO 10628 or ISO 15519
    #: prescribes a shape around a stream number, which is why this is
    #: an option the author selects and why the default leaves the sheet
    #: as it was.
    #:
    #: **One size for the whole sheet.** The enclosure is measured once,
    #: over the longest label on it, and every enclosure is ruled at
    #: that size -- so ``1`` and ``1000`` get the same diamond. Sizing
    #: each to its own text is the alternative, and it draws a row of
    #: visibly different diamonds down one sheet, which reads as a
    #: mistake rather than as information. Same answer, and the same
    #: argument, as the stream table's columns.
    #:
    #: **An enclosed label never leaves its run.** A bare number that
    #: cannot fit on its line is written beside it, or out on a leader;
    #: a shape is not, because the run passing through it *is* the
    #: convention and one drawn off the line has no reading at all.
    #: A shape too big for the paper beside its run is drawn there
    #: anyway, crossing whatever is under it -- so **spacing the sheet
    #: is the author's lever**, and every crossing is named on
    #: ``fs.warnings`` after a render (``enclosure-over-unit``,
    #: ``enclosure-over-line``, ``enclosure-over-label``) rather than
    #: left to be found by eye.
    #:
    #: **Nothing is hidden by any of it.** The shape is ruled as an
    #: outline, and the plate under the words is laid down only where
    #: it covers the run being labelled and nothing else; where the run
    #: is too short to hold it clear anywhere along it, no plate is laid
    #: and the number is written straight onto the sheet with the
    #: crossing run drawn through it. Nine of the 286 labels on the
    #: shipped corpus are drawn that way. A number read across a run is
    #: harder to read; a run with a piece taken out of it is not there,
    #: and ``validate()`` cannot see it because the topology is
    #: untouched.
    #:
    #: A sheet lettered with full line numbers pays for the longest of
    #: them at every label -- ``AE-304-150-80-SS`` rules a diamond over
    #: 200 units wide -- which is the case the convention fits worst.
    #: ``"circle"`` is much the tightest of the three on a long label,
    #: at the cost of reading like an instrument balloon on a sheet
    #: that carries instruments.
    enclosure: Literal["none", "diamond", "circle", "box"] = "none"

    def __post_init__(self):
        self.enclosure = _resolve_enclosure(self.enclosure)


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
    "blower", "boiler", "column", "compressor", "conveyor", "cooler",
    "cooling_tower", "crusher", "dryer", "ejector", "elevator", "evaporator",
    "feeder", "filter", "flare", "furnace", "heater", "hex", "kiln", "kneader",
    "mill", "pump", "reactor", "screening_device", "separator", "stack", "tank",
    "thickener", "turbine", "vessel",
})
# ``boiler``, ``stack`` and ``flare`` are here and ``vent``/``funnel`` are
# not, for the reason ``Stack``'s own docstring gives: those two are
# bulk piping, bought by the line, and these three are ISO 10628-2's
# own group-4 equipment -- a stack or a flare stack has a foundation and
# a datasheet the way a furnace does, not a piping-class entry the way a
# vent cap does.
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
    flowsheet.

    ``align`` / ``position`` / ``margin`` place the box (see
    :class:`Annotation`).

    Raises :class:`ValueError` if ``include`` names a tag the flowsheet
    does not have. Naming a row is an assertion that it exists, and a
    schedule silently one line short is a schedule an author reads as
    complete -- ``include=["P-101", "P-1O2"]``, letter O for zero, drew
    one row and said nothing. It is refused rather than warned about
    because the check is exact and immediate: this function has the
    flowsheet in hand, and ``fs.warnings`` describes a *render*, which
    has not happened yet and will clear the list when it does.
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
