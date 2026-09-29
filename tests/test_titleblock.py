"""Test title-block, revision-history, annotation, and stream-table rendering."""

import dataclasses
import html
import re
from typing import Any

import pytest

from pandid import Flowsheet, units as U
from pandid.document import TitleBlock, Revision


def _sheet(name: str = "Demo", span: float = 0.0) -> Flowsheet:
    """Create a pinned feed-to-product flowsheet.

    Parameters
    ----------
    name : str, default="Demo"
        Flowsheet name.
    span : float, default=0.0
        Extra horizontal distance between the terminal units.

    Returns
    -------
    Flowsheet
        Flowsheet with one material stream.
    """
    fs = Flowsheet(name)
    a = fs.add(U.Feed("F")).pin(x=110, y=130)
    b = fs.add(U.Product("P")).pin(x=260 + span, y=130)
    fs.connect(a.outlet, b.inlet)
    return fs


def test_title_block_draws_without_a_border():
    # A title block may render without a P&ID border.
    """Verify title block draws without a border."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo Sheet",
        drawing_number="PFD-9",
        revisions=[Revision("0", "2026-01-01", "Issued", "AA")],
    )
    svg = fs.to_svg()
    for token in ("PFD-9", "Demo Sheet", "REV", "DESCRIPTION", "Issued"):
        assert token in svg, token


def test_annotations_draw_without_a_border():
    """Verify annotations draw without a border."""
    from pandid.document import equipment_list, notes

    fs = _sheet()
    fs.add(U.Pump("P-101", description="Transfer Pump"))
    fs.add_annotation(equipment_list(fs))
    fs.add_annotation(notes(["Sampling point on every product line."]))
    svg = fs.to_svg()
    for token in ("EQUIPMENT LIST", "P-101", "Transfer Pump", "NOTES", "Sampling point"):
        assert token in svg, token


def test_border_and_furniture_are_independent():
    # Border choice does not change furniture placement.
    """Verify border and furniture are independent."""

    def build():
        """Create a sheet with title-block furniture."""
        fs = _sheet()
        fs.title_block = TitleBlock(title="Demo Sheet", drawing_number="PFD-9")
        return fs

    zoned = build().to_svg(border="zone")
    plain = build().to_svg(border="none")
    # Diagram type does not change title-strip geometry.
    both = build().to_svg(border="zone", diagram="p&id")
    assert '<text x="6' in both
    assert '<text x="6' in zoned  # zone letters are ruled only when asked for
    strip = r'<rect x="[-\d.]+" y="[-\d.]+" width="652.0" height="80.0" fill="white"'
    assert re.search(strip, zoned).group(0) == re.search(strip, plain).group(0)


def test_a_border_nobody_asked_for_is_not_drawn():
    """Verify a border nobody asked for is not drawn."""
    svg = _sheet().to_svg()
    assert "S1" in svg  # the sheet still renders
    assert 'fill="none" stroke="black" stroke-width="2"/>' not in svg  # no frame


@pytest.mark.parametrize(
    "kwargs",
    [
        {"border": "isometric"},
        {"border": "ruled"},
        # ``border`` accepts frame names only.
        {"border": "p&id"},
    ],
)
def test_a_frame_the_renderer_cannot_draw_raises(kwargs):
    """Verify a frame the renderer cannot draw raises."""
    with pytest.raises(ValueError):
        _sheet().to_svg(**kwargs)


def test_client_and_project_are_drawn():
    """Verify client and project are drawn."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo Sheet", client="Northwind Chemicals", project="Ethanol Purification A300"
    )
    svg = fs.to_svg()
    for token in ("CLIENT", "Northwind Chemicals", "PROJECT", "Ethanol Purification A300"):
        assert token in svg, token


def test_the_strip_grows_a_row_for_each_of_them():
    """Verify the strip grows a row for each of them."""
    from pandid.render.furniture import measure_title_strip

    bare = measure_title_strip(TitleBlock())
    one = measure_title_strip(TitleBlock(project="Ethanol A300"))
    two = measure_title_strip(TitleBlock(project="Ethanol A300", client="Northwind"))
    assert bare[0] == one[0] == two[0]  # the strip keeps its width
    assert one[1] - bare[1] == two[1] - one[1] > 0


def test_scale_is_drawn():
    """Verify scale is drawn."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo Sheet", scale="1:100")
    svg = fs.to_svg()
    assert "SCALE" in svg and "1:100" in svg


def test_a_sheet_with_no_scale_to_state_still_rules_the_scale_cell():
    """Verify a sheet with no scale to state still rules the scale cell."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo Sheet")
    svg = fs.to_svg()
    assert ">SCALE</text>" in svg
    # Ruled and empty, not filled with something invented.
    assert ">NTS</text>" not in svg and ">1:1</text>" not in svg


def test_the_drawing_number_has_one_budget_however_the_sheet_is_asked_for():
    """Verify the drawing number has one budget however the sheet is asked for."""
    number = "PFD-A100-0001-REV"

    def drawn(**kw):
        """Render the drawing-number cell and collect truncation findings."""
        fs = _sheet()
        fs.title_block = TitleBlock(title="Demo", drawing_number=number)
        svg = fs.to_svg(border="zone", **kw)
        cell = re.search(r">DRAWING No</text>\s*<text[^>]*>([^<]*)</text>", svg)
        assert cell is not None, "the sheet ruled no DRAWING No cell"
        return (
            cell.group(1),
            [w.message for w in fs.warnings if w.code == "text-truncated"],
        )

    loose, loose_found = drawn()
    paged, paged_found = drawn(page_size="A3")
    assert loose == paged
    assert loose_found == paged_found
    # And it is reported, not merely consistent.
    assert len(paged_found) == 1
    assert paged_found[0].startswith("drawing_number was truncated")

    # ...and validate() says the same thing, with nothing rendered.
    ahead = _sheet()
    ahead.title_block = TitleBlock(title="Demo", drawing_number=number)
    assert [i.message for i in ahead.validate() if i.code == "text-truncated"] == paged_found


def test_scale_reports_the_ratio_the_drawing_was_fitted_at():
    """Verify scale reports the ratio the drawing was fitted at."""
    fs = _sheet(span=4000.0)
    fs.title_block = TitleBlock(title="Demo Sheet")
    svg = fs.to_svg(page_size="A4", border="zone")
    fitted = float(re.search(r'<g id="drawing" transform="[^"]*scale\(([\d.]+)\)', svg).group(1))
    assert fitted < 1
    reported = re.search(r">1:([\d.]+)</text>", svg)
    assert reported, "no scale drawn"
    assert 1 / float(reported.group(1)) == pytest.approx(fitted, rel=0.01)


def test_a_stated_scale_beats_the_computed_one():
    """Verify a stated scale beats the computed one."""
    fs = _sheet(span=4000.0)
    fs.title_block = TitleBlock(title="Demo Sheet", scale="NTS")
    svg = fs.to_svg(page_size="A4", border="zone")
    assert ">NTS</text>" in svg
    assert not re.search(r">1:[\d.]+</text>", svg)


def test_title_block_fields_rendered():
    """Verify title block fields rendered."""
    fs = Flowsheet("Demo Unit")
    fs.add(U.Feed("F"))
    fs.add(U.Product("P"))
    fs.connect(fs.units[0].outlet, fs.units[1].inlet)
    fs.title_block = TitleBlock(
        title="Demo Sheet",
        drawing_number="PFD-9",
        sheet="2",
        of_sheets="4",
        drawn_by="AA",
        checked_by="BB",
        approved_by="CC",
        revisions=[Revision("0", "2026-01-01", "Issued", "AA")],
    )
    svg = fs.to_svg(border="zone", diagram="p&id")
    for token in ("PFD-9", "2 of 4", "AA", "BB", "CC", "REV", "DESCRIPTION", "Issued"):
        assert token in svg, token


def test_no_title_block_still_renders_pid():
    """Verify no title block still renders pid."""
    fs = Flowsheet("Bare")
    fs.add(U.Feed("F"))
    fs.add(U.Product("P"))
    fs.connect(fs.units[0].outlet, fs.units[1].inlet)
    svg = fs.to_svg(border="zone", diagram="p&id")  # falls back to defaults, must not raise
    assert "Bare" in svg


def test_title_block_fits_narrow_sheet():
    """Verify title block fits narrow sheet."""
    import re
    from pandid.render.furniture import measure_title_strip

    fs = Flowsheet("Tiny")
    a = fs.add(U.Feed("F"))
    b = fs.add(U.Product("P"))
    fs.connect(a.outlet, b.inlet)
    fs.title_block = TitleBlock(drawing_number="PFD-1")
    svg = fs.to_svg(border="zone", diagram="p&id")
    vb = re.search(r'viewBox="([-\d.]+) [-\d.]+ ([\d.]+)', svg)
    minx, width = float(vb.group(1)), float(vb.group(2))
    strip_w, _ = measure_title_strip(fs.title_block)
    # locate the engineering title strip (its rect is the strip width, stroke 2)
    m = re.search(
        rf'<rect x="([-\d.]+)" y="[-\d.]+" width="{strip_w:.1f}" '
        r'height="[-\d.]+" fill="white" stroke="black" stroke-width="2"/>',
        svg,
    )
    assert m, "title strip rect not found"
    tbx = float(m.group(1))
    assert tbx >= minx - 0.5  # not clipped on the left
    assert tbx + strip_w <= minx + width + 0.5  # nor the right


def test_furniture_boxes_rendered():
    """Verify furniture boxes rendered."""
    from pandid.document import equipment_list, notes, legend

    fs = Flowsheet("Furnished")
    feed = fs.add(U.Feed("Crude", reference="PFD-000"))
    col = fs.add(U.Column("T-101", description="Main Column"))
    prod = fs.add(U.Product("Top", reference="PFD-002"))
    fs.connect(feed.outlet, col.feed)
    fs.connect(col.overhead, prod.inlet)
    fs.add_annotation(equipment_list(fs))
    fs.add_annotation(notes(["First note", "Second note"]))
    fs.add_annotation(legend({"SS": "Stainless Steel"}))
    svg = fs.to_svg(border="zone", diagram="p&id")
    for token in (
        "EQUIPMENT LIST",
        "T-101",
        "Main Column",
        "NOTES",
        "First note",
        "LEGEND",
        "Stainless Steel",
        "PFD-000",
        "PFD-002",
    ):
        assert token in svg, token


def test_align_nine_point():
    """Verify align nine point."""
    import pytest
    from pandid.document import Annotation

    assert Annotation(align="top").align == "top"
    assert Annotation(align="center").align == "center"
    assert Annotation(align="bottom-left").align == "bottom-left"
    with pytest.raises(ValueError):
        Annotation(align="middle-ish")


def test_annotation_docks_flush_to_frame():
    """Verify annotation docks flush to frame."""
    import re
    from pandid.document import Annotation

    fs = Flowsheet("Flush")
    a = fs.add(U.Feed("F"))
    b = fs.add(U.Product("P"))
    fs.connect(a.outlet, b.inlet)
    fs.add_annotation(Annotation(title="BOX", rows=["row"], align="top-right"))
    svg = fs.to_svg(border="zone", diagram="p&id")
    # the annotation box (stroke-width 1.5, white fill) ...
    box = re.search(
        r'<rect x="([-\d.]+)" y="[-\d.]+" width="([\d.]+)" '
        r'height="[-\d.]+" fill="white" stroke="black" stroke-width="1.5"/>',
        svg,
    )
    # ... and the inner drawing frame (stroke-width 2, no fill)
    frame = re.search(
        r'<rect x="([-\d.]+)" y="[-\d.]+" width="([\d.]+)" '
        r'height="[-\d.]+" fill="none" stroke="black" stroke-width="2"/>',
        svg,
    )
    assert box and frame, "box and frame rects must both render"
    box_right = float(box.group(1)) + float(box.group(2))
    frame_right = float(frame.group(1)) + float(frame.group(2))
    assert abs(box_right - frame_right) < 0.6  # right edges coincide (flush)


def test_annotation_absolute_position():
    """Verify annotation absolute position."""
    import re
    from pandid.document import Annotation

    fs = Flowsheet("Placed")
    a = fs.add(U.Feed("F"))
    b = fs.add(U.Product("P"))
    fs.connect(a.outlet, b.inlet)
    fs.add_annotation(Annotation(title="HOLD", rows=["x"], position=(500, 120)))
    svg = fs.to_svg(border="zone", diagram="p&id")
    # top-left corner drawn exactly at the requested absolute coordinates
    assert re.search(r'<rect x="500.0" y="120.0" [^>]*stroke-width="1.5"/>', svg)


# --- what the equipment list schedules, and what it calls it ------------------


def _schedule(fs: Flowsheet, **kwargs: object) -> list[tuple[str, str]]:
    """Return equipment-schedule rows for a flowsheet.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to schedule.
    **kwargs : object
        Options forwarded to ``equipment_list``.

    Returns
    -------
    list[tuple[str, str]]
        ``(tag, description)`` rows.
    """
    from pandid.document import equipment_list

    return equipment_list(fs, **kwargs).rows


def test_bulk_items_and_junctions_are_not_scheduled():
    """Verify bulk items and junctions are not scheduled."""
    fs = Flowsheet("Bulk")
    fs.add(U.Pump("P-101", description="Feed Pump"))
    fs.add(U.Valve("FV-100"))
    fs.add(U.Fitting("ST-101", variant="strainer"))
    fs.add(U.Reducer("RD-101"))
    fs.add(U.Vent("VT-101"))
    fs.add(U.Funnel("FN-101"))
    fs.add(U.Mixer("M-100", n_inlets=2))
    fs.add(U.Splitter("SP-100", n_outlets=2))
    fs.add(U.Feed("Raw Feed"))
    fs.add(U.Product("To Unit 200"))
    fs.add_instrument("FT", 101)
    assert [tag for tag, _ in _schedule(fs)] == ["P-101"]


def test_major_equipment_is_scheduled_whatever_it_is():
    """Verify major equipment is scheduled whatever it is."""
    fs = Flowsheet("Plant")
    for unit in (
        U.Vessel("V-101"),
        U.Column("T-101"),
        U.HeatExchanger("E-101"),
        U.Heater("H-101"),
        U.Cooler("C-101"),
        U.Pump("P-101"),
        U.Compressor("K-101"),
        U.Blower("B-101"),
        U.Tank("TK-101"),
        U.Reactor("R-101"),
        U.Separator("S-101"),
        U.Filter("F-101"),
        U.Dryer("D-101"),
        U.Furnace("FH-101"),
        U.Turbine("TU-101"),
        U.Ejector("EJ-101"),
    ):
        fs.add(unit)
    assert [tag for tag, _ in _schedule(fs)] == [u.name for u in fs.units]


def test_the_description_is_words_not_the_kind_key():
    """Verify the description is words not the kind key."""
    fs = Flowsheet("Named")
    fs.add(U.HeatExchanger("E-101"))
    fs.add(U.HeatExchanger("E-102", description="Feed/Effluent Exchanger"))
    assert _schedule(fs) == [
        ("E-101", "Heat Exchanger"),
        ("E-102", "Feed/Effluent Exchanger"),
    ]


def test_every_registered_kind_names_itself():
    """Verify every registered kind names itself."""
    from pandid.document import _KIND_LABELS

    kinds = {getattr(U, name).kind for name in U.__all__ if name != "Unit"}
    assert kinds <= set(_KIND_LABELS)
    assert not [label for label in _KIND_LABELS.values() if not label[:1].isupper()]


def test_include_builds_a_schedule_of_its_own():
    """Verify include builds a schedule of its own."""
    fs = Flowsheet("Valves")
    fs.add(U.Pump("P-101", description="Feed Pump"))
    fs.add(U.Valve("FV-100", description="Feed Control Valve"))
    fs.add(U.Valve("FV-200"))
    assert _schedule(fs, title="VALVE SCHEDULE", include=["FV-200", "FV-100"]) == [
        ("FV-200", "Valve"),
        ("FV-100", "Feed Control Valve"),
    ]


def test_include_refuses_a_tag_the_flowsheet_does_not_have():
    """Verify include refuses a tag the flowsheet does not have."""
    fs = Flowsheet("Valves")
    fs.add(U.Pump("P-101", description="Feed Pump"))
    with pytest.raises(ValueError) as excinfo:
        _schedule(fs, include=["P-101", "P-1O2"])
    message = str(excinfo.value)
    assert "P-1O2" in message
    assert "did you mean 'P-101'?" in message
    # ...and the rows that do exist are still taken, in the order named.
    assert _schedule(fs, include=["P-101"]) == [("P-101", "Feed Pump")]


def test_stream_table_section_header():
    """Verify stream table section header."""
    fs = Flowsheet("Tabled")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet)
    s.properties = {"Temperature": "25 C", "Ethanol": "0.9"}
    fs.stream_table_sections = [("Ethanol", "Mass Fraction")]
    svg = fs.to_svg(border="zone", diagram="p&id", show_stream_table=True)
    assert "Mass Fraction" in svg
    assert "Stream Number" in svg


def test_a_stream_table_section_keyed_to_nothing_warns_instead_of_vanishing():
    """Verify a stream table section keyed to nothing warns instead of vanishing."""
    fs = Flowsheet("Tabled")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet)
    s.properties = {"Ethanol": "0.9"}
    fs.stream_table_sections = [("Bogus", "Mass Fraction"), ("Ethanol", "Real Section")]
    svg = fs.to_svg(border="zone", diagram="p&id", show_stream_table=True)
    assert "Mass Fraction" not in svg
    assert "Real Section" in svg
    codes = [w.code for w in fs.warnings]
    assert "stream-table-section-unused" in codes
    message = next(str(w) for w in fs.warnings if w.code == "stream-table-section-unused")
    assert "'Bogus'" in message and "'Mass Fraction'" in message


# --- stream-table column inclusion --------------------------------------------


def _columns(fs: Flowsheet) -> list[str]:
    """Return stream-table column labels.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet containing the stream table.

    Returns
    -------
    list[str]
        Labels of emitted stream columns.
    """
    from pandid.render.furniture import stream_table_layout

    table = stream_table_layout(fs)
    return [] if table is None else [c.text for c in table.rows[0][1:]]


def _table(fs: Flowsheet, **kwargs: object) -> str:
    """Render a flowsheet's stream table as SVG.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet containing the table.
    **kwargs : object
        Options forwarded to ``Flowsheet.to_svg``.

    Returns
    -------
    str
        SVG stream-table group.
    """
    svg = fs.to_svg(show_stream_table=True, **kwargs)
    body = re.search(r'<g id="stream_table">(.*?)</g>', svg, re.S)
    return body.group(1) if body else ""


def _two_and_two() -> Flowsheet:
    """Create a flowsheet with tabulated and boundary-only streams.

    Returns
    -------
    Flowsheet
        Sheet with two feeds and two products.
    """
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("Raw Feed"))
    pump = fs.add(U.Pump("P-101"))
    e1 = fs.add(U.HeatExchanger("E-101"))
    e2 = fs.add(U.HeatExchanger("E-102"))
    prod = fs.add(U.Product("To Storage"))
    s1 = fs.connect(feed.outlet, pump.suction)
    s2 = fs.connect(pump.discharge, e1.tube_in)
    fs.connect(e1.tube_out, e2.tube_in)
    fs.connect(e2.tube_out, prod.inlet)
    s1.properties = {"Temperature": "25 C"}
    s2.properties = {"Temperature": "80 C"}
    return fs


def test_an_internal_column_with_nothing_in_it_is_dropped():
    """Verify an internal column with nothing in it is dropped."""
    fs = _two_and_two()
    assert _columns(fs) == ["S1", "S2", "S4"]
    assert ">S3<" not in _table(fs)


def test_a_boundary_column_with_nothing_in_it_is_kept():
    """Verify a boundary column with nothing in it is kept."""
    fs = _two_and_two()
    assert "S4" in _columns(fs)
    assert ">S4<" in _table(fs)


def test_a_value_present_and_blank_keeps_the_column():
    """Verify a value present and blank keeps the column."""
    fs = _two_and_two()
    internal = fs.streams[2]
    internal.properties = {"Temperature": ""}
    assert _columns(fs) == ["S1", "S2", "S3", "S4"]
    table = _table(fs)
    assert ">S3<" in table
    assert table.count(">-<") == 2  # the blank one and the boundary one


# --- sizing the table ---------------------------------------------------------


def _layout(fs: Flowsheet):
    """Return the calculated stream-table layout.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet containing a stream table.

    Returns
    -------
    object
        Non-empty stream-table layout.
    """
    from pandid.render.furniture import stream_table_layout

    table = stream_table_layout(fs)
    assert table is not None
    return table


def _wide(n: int) -> Flowsheet:
    """Create a sheet with a requested number of tabulated streams.

    Parameters
    ----------
    n : int
        Number of feed-to-product lines.

    Returns
    -------
    Flowsheet
        Flowsheet containing ``n`` tabulated streams.
    """
    fs = Flowsheet("wide")
    for i in range(n):
        feed = fs.add(U.Feed(f"F{i}"))
        prod = fs.add(U.Product(f"P{i}"))
        fs.connect(feed.outlet, prod.inlet).properties = {"Temperature": f"{i} C"}
    return fs


def test_the_table_is_set_at_the_size_the_sheet_asks_for():
    """Verify the table is set at the size the sheet asks for."""
    fs = _two_and_two()
    fs.stream_table.font_size = 8.0
    assert _layout(fs).size == 8.0
    assert 'font-size="8.0"' in _table(fs)


def test_the_size_rules_the_table_and_not_only_its_lettering():
    """Verify the size rules the table and not only its lettering."""
    fs, small = _two_and_two(), _two_and_two()
    small.stream_table.font_size = 7.0
    big, little = _layout(fs), _layout(small)
    assert little.w < big.w
    assert little.h < big.h
    assert little.row_h < big.row_h
    # Table dimensions scale with font size.
    assert little.h / big.h == pytest.approx(7.0 / 10.5)
    assert little.w / big.w == pytest.approx(7.0 / 10.5)


def test_a_table_left_alone_is_drawn_exactly_as_it_always_was():
    """Verify a table left alone is drawn exactly as it always was."""
    narrow, wide, widest = _layout(_two_and_two()), _layout(_wide(20)), _layout(_wide(40))
    assert (narrow.size, narrow.row_h) == (10.5, 20.0)
    assert (wide.size, wide.row_h) == (pytest.approx(190.0 / 20), 15.0)
    assert (widest.size, widest.row_h) == (8.0, 15.0)  # and no further
    assert wide.w == pytest.approx(122.0 + 20 * 52.0)


@pytest.mark.parametrize("size", [0, -1, -0.5])
def test_a_size_that_is_not_a_size_is_refused(size):
    """Verify a size that is not a size is refused."""
    fs = _two_and_two()
    fs.stream_table.font_size = size
    with pytest.raises(ValueError, match="font_size"):
        _layout(fs)


def test_an_option_set_after_a_render_reaches_the_next_one():
    """Verify an option set after a render reaches the next one."""
    fs = _two_and_two()
    first = _table(fs)
    fs.stream_table.font_size = 8.0
    second = _table(fs)
    assert 'font-size="10.5"' in first and 'font-size="8.0"' in second


def test_the_stated_size_reaches_the_drawio_export_too():
    """Verify the stated size reaches the drawio export too."""
    fs = _two_and_two()
    fs.stream_table.font_size = 8.0
    assert "fontSize=8" in fs.to_drawio(show_stream_table=True)


# --- stream-table column widths ------------------------------------------------


def _widths(fs) -> tuple[float, float]:
    """Return calculated label and stream-column widths.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet containing a stream table.

    Returns
    -------
    tuple[float, float]
        Label-column width followed by stream-column width.
    """
    table = _layout(fs)
    return table.rows[0][0].w, table.rows[0][1].w


def _with(fs: Flowsheet, **options: object) -> Flowsheet:
    """Set stream-table options on a flowsheet.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to update.
    **options : object
        Attributes to set on ``fs.stream_table``.

    Returns
    -------
    Flowsheet
        Updated flowsheet.
    """
    for key, value in options.items():
        setattr(fs.stream_table, key, value)
    return fs


def _fits(text: str, size: float = 10.5, bold: bool = False) -> float:
    """Measure a stream-table cell including its gutter.

    Parameters
    ----------
    text : str
        Cell text.
    size : float, default=10.5
        Font size.
    bold : bool, default=False
        Whether the text is bold.

    Returns
    -------
    float
        Required cell width.
    """
    from pandid.render.furniture import _STREAM_GUTTER, text_width

    return text_width(text, size, bold=bold) + _STREAM_GUTTER


def _one_long_value() -> Flowsheet:
    """Create a table with one value wider than the remaining values.

    Returns
    -------
    Flowsheet
        Flowsheet with three tabulated streams.
    """
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-101"))
    hex_ = fs.add(U.HeatExchanger("E-101"))
    prod = fs.add(U.Product("P"))
    s1 = fs.connect(feed.outlet, pump.suction)
    s2 = fs.connect(pump.discharge, hex_.tube_in)
    s3 = fs.connect(hex_.tube_out, prod.inlet)
    s1.properties = {"P": "1 bar"}
    s2.properties = {"P": "1013.25 mbara"}
    s3.properties = {"P": "2 bar"}
    return fs


def test_the_floors_are_where_they_always_were():
    """Verify the floors are where they always were."""
    fs = _two_and_two()
    assert (fs.stream_table.label_width, fs.stream_table.column_width) == (122.0, 52.0)
    assert _widths(fs) == (122.0, 52.0)


def test_auto_drops_the_floor_and_rules_the_column_to_its_content():
    """Verify auto drops the floor and rules the column to its content."""
    fs = _two_and_two()
    fs.stream_table.label_width = "auto"
    fs.stream_table.column_width = "auto"
    label, name = _widths(fs)
    # Headings and values set automatic widths.
    assert label == pytest.approx(_fits("Stream Number", bold=True))
    assert name == pytest.approx(_fits("25 C"))
    assert label < 122.0 and name < 52.0


def test_each_floor_is_dropped_on_its_own():
    """Verify each floor is dropped on its own."""
    label_only, name_only = _two_and_two(), _two_and_two()
    label_only.stream_table.label_width = "auto"
    name_only.stream_table.column_width = "auto"
    assert _widths(label_only) == (pytest.approx(_fits("Stream Number", bold=True)), 52.0)
    assert _widths(name_only) == (122.0, pytest.approx(_fits("25 C")))


def test_a_number_is_a_floor_and_not_a_width():
    """Verify a number is a floor and not a width."""
    fs = _two_and_two()
    fs.stream_table.label_width = 10.0
    fs.stream_table.column_width = 10.0
    assert _widths(fs) == _widths(_with(_two_and_two(), label_width="auto", column_width="auto"))
    wide = _with(_two_and_two(), label_width=300.0, column_width=90.0)
    assert _widths(wide) == (300.0, 90.0)


def test_auto_rules_every_stream_column_at_the_widest_cell_in_the_table():
    """Verify auto rules every stream column at the widest cell in the table."""
    fs = _with(_one_long_value(), column_width="auto")
    table = _layout(fs)
    widths = {c.w for row in table.rows for c in row[1:]}
    assert len(widths) == 1
    assert widths.pop() == pytest.approx(_fits("1013.25 mbara"))


def test_a_column_is_never_ruled_narrower_than_its_own_heading():
    """Verify a column is never ruled narrower than its own heading."""
    fs = _one_long_value()
    for stream, name in zip(fs.streams, ("HPS-308-100-80-CS", "S2", "S3")):
        stream.name = name
    fs.stream_table.column_width = "auto"
    table = _layout(fs)
    assert table.rows[0][1].w == pytest.approx(_fits("HPS-308-100-80-CS", bold=True))


def test_a_section_heading_still_widens_the_row_label_column_under_auto():
    """Verify a section heading still widens the row label column under auto."""
    fs = _with(_two_and_two(), label_width="auto", column_width="auto")
    plain = _layout(fs).w
    fs.stream_table_sections = [
        ("Temperature", "Conditions at the Battery Limit, as Tendered and Guaranteed")
    ]
    label, name = _widths(fs)
    assert label > plain - name * 3  # the label column took up the slack
    assert label + name * 3 == pytest.approx(
        _fits("Conditions at the Battery Limit, as Tendered and Guaranteed", bold=True)
    )


def test_a_stated_floor_follows_the_stated_type_size():
    """Verify a stated floor follows the stated type size."""
    by_hand = _with(_two_and_two(), label_width=122.0, column_width=52.0, font_size=7.0)
    left_alone = _with(_two_and_two(), font_size=7.0)
    assert _widths(by_hand) == _widths(left_alone)
    assert _widths(by_hand) == (pytest.approx(122.0 * 7.0 / 10.5), pytest.approx(52.0 * 7.0 / 10.5))


def test_auto_composes_with_the_stated_type_size():
    """Verify auto composes with the stated type size."""
    big = _with(_two_and_two(), column_width="auto")
    small = _with(_two_and_two(), column_width="auto", font_size=7.0)
    assert _widths(small)[1] == pytest.approx(_fits("25 C", 7.0))
    assert _layout(small).w < _layout(big).w


@pytest.mark.parametrize("field", ["label_width", "column_width"])
@pytest.mark.parametrize("value", ["fit", "", -1, None, True])
def test_a_width_that_is_not_one_is_refused(field, value):
    """Verify a width that is not one is refused."""
    fs = _with(_two_and_two(), **{field: value})
    with pytest.raises(ValueError, match=field):
        _layout(fs)


def test_the_widths_reach_the_drawio_export_too():
    """Verify the widths reach the drawio export too."""
    from pandid.render.drawio import _num

    fs = _with(_two_and_two(), label_width="auto", column_width="auto")
    label, name = _widths(fs)
    xml = fs.to_drawio(show_stream_table=True)
    assert f'width="{_num(label)}"' in xml
    assert f'width="{_num(name)}"' in xml
    assert f'width="{_num(label + name * 3)}"' in xml  # three tabulated columns


def test_a_content_ruled_cell_still_clears_the_drawio_text_inset():
    """Verify a content ruled cell still clears the drawio text inset."""
    from pandid.render.drawio import _TEXT_INSET
    from pandid.render.furniture import _STREAM_PAD, _STREAM_GUTTER

    assert _STREAM_GUTTER >= _STREAM_PAD + _TEXT_INSET


def test_a_sheet_that_states_no_property_draws_no_table():
    """Verify a sheet that states no property draws no table."""
    fs = _sheet()
    assert _columns(fs) == []
    assert _table(fs) == ""


def test_a_run_is_judged_over_every_segment_it_is_drawn_in():
    """Verify a run is judged over every segment it is drawn in."""
    fs = Flowsheet("segments")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-1"))
    hv = fs.add(U.Valve("HV-1"))
    fv = fs.add(U.Valve("FV-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, hv.inlet)
    tail = fs.connect(hv.outlet, pump.suction)
    fs.connect(pump.discharge, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    tail.properties = {"Temperature": "25 C"}  # the far segment of the run in
    assert [s.name for s in fs.streams] == ["S1", "S1", "S2", "S2"]
    assert _columns(fs) == ["S1", "S2"]
    assert _row(fs, "Temperature") == ["25 C", "-"]


# --- stream-table segment selection -------------------------------------------


def _row(fs: Flowsheet, key: str) -> list[str]:
    """Return values from a stream-table property row.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet containing a stream table.
    key : str
        Property-row name.

    Returns
    -------
    list[str]
        Values in stream-column order.
    """
    from pandid.render.furniture import stream_table_layout

    table = stream_table_layout(fs)
    for row in [] if table is None else table.rows:
        if len(row) > 1 and row[0].text == key:
            return [c.text for c in row[1:]]
    return []


def _across_a_valve():
    """Create a two-segment pressure-drop run.

    Returns
    -------
    tuple
        Flowsheet, upstream stream, and downstream stream.
    """
    fs = Flowsheet("drop")
    feed = fs.add(U.Feed("F"))
    fv = fs.add(U.Valve("FV-1", variant="control"))
    prod = fs.add(U.Product("P"))
    up = fs.connect(feed.outlet, fv.inlet)
    down = fs.connect(fv.outlet, prod.inlet)
    up.properties = {"Pressure": "11.6 barg"}
    down.properties = {"Pressure": "3.4 barg"}
    assert [s.name for s in fs.streams] == ["S1", "S1"]
    return fs, up, down


def test_an_unmarked_run_reports_the_conditions_it_is_drawn_from():
    """Verify an unmarked run reports the conditions it is drawn from."""
    fs, _up, _down = _across_a_valve()
    assert _row(fs, "Pressure") == ["11.6 barg"]


def test_the_marked_segment_is_the_one_the_column_reports():
    """Verify the marked segment is the one the column reports."""
    fs, _up, down = _across_a_valve()
    down.tabulate = True
    assert _row(fs, "Pressure") == ["3.4 barg"]


def test_the_mark_moves_the_values_and_not_the_heading():
    """Verify the mark moves the values and not the heading."""
    fs = Flowsheet("heading")
    feed = fs.add(U.Feed("F"))
    fv = fs.add(U.Valve("FV-1", variant="control"))
    prod = fs.add(U.Product("P"))
    up = fs.connect(feed.outlet, fv.inlet, size='6"', service="P", spec="A1A")
    down = fs.connect(fv.outlet, prod.inlet)
    up.properties = {"Pressure": "11.6 barg"}
    down.properties = {"Pressure": "3.4 barg"}
    down.tabulate = True
    assert _columns(fs) == ['6"-P-1001-A1A']
    assert _row(fs, "Pressure") == ["3.4 barg"]


def test_the_mark_fills_only_the_rows_it_states():
    """Verify the mark fills only the rows it states."""
    fs, up, down = _across_a_valve()
    up.properties["Benzene"] = "0.90"
    down.tabulate = True
    assert _row(fs, "Pressure") == ["3.4 barg"]
    assert _row(fs, "Benzene") == ["0.90"]


def test_two_marks_on_one_run_name_the_run_and_the_way_out():
    """Verify two marks on one run name the run and the way out."""
    fs, up, down = _across_a_valve()
    up.tabulate = down.tabulate = True
    with pytest.raises(ValueError) as excinfo:
        _row(fs, "Pressure")
    message = str(excinfo.value)
    assert "S1 is drawn in 2 segments and 2 of them are marked" in message
    assert "new_line_number" in message  # names the other way out


def test_a_mark_on_a_run_of_one_segment_changes_nothing():
    """Verify a mark on a run of one segment changes nothing."""
    fs = Flowsheet("one")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    only = fs.connect(feed.outlet, prod.inlet)
    only.properties = {"Pressure": "4.0 barg"}
    only.tabulate = True
    assert _row(fs, "Pressure") == ["4.0 barg"]


def test_the_mark_survives_the_spec_round_trip():
    """Verify the mark survives the spec round trip."""
    fs, _up, down = _across_a_valve()
    down.tabulate = True
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert [s.tabulate for s in rebuilt.streams] == [False, True]
    assert _row(rebuilt, "Pressure") == ["3.4 barg"]


# --- title-strip fit reporting -------------------------------------------------

_CELL = re.compile(
    r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="[\d.]+" '
    r'fill="[^"]+" stroke="black" stroke-width="0\.75"/>\s*'
    r'<text x="([-\d.]+)" y="[-\d.]+" font-family="[^"]+" font-size="([\d.]+)"'
    r'( font-weight="bold")? text-anchor="(\w+)">([^<]*)</text>'
)


def _table_cells(svg: str) -> list[tuple[float, float, float, float, str]]:
    """Extract stream-table cell and text extents from SVG.

    Parameters
    ----------
    svg : str
        Rendered SVG document.

    Returns
    -------
    list[tuple[float, float, float, float, str]]
        Cell bounds, ink bounds, and text for each table cell.
    """
    from pandid.render.furniture import text_width

    body = re.search(r'<g id="stream_table">(.*?)</g>', svg, re.S)
    assert body, "no stream table drawn"
    out = []
    for m in _CELL.finditer(body.group(1)):
        x, w = float(m.group(1)), float(m.group(3))
        tx, size, bold, anchor, text = (
            float(m.group(4)),
            float(m.group(5)),
            bool(m.group(6)),
            m.group(7),
            m.group(8),
        )
        tw = text_width(text, size, bold)
        left = tx if anchor == "start" else (tx - tw if anchor == "end" else tx - tw / 2)
        out.append((x, x + w, left, left + tw, text))
    return out


def _wide_table_sheet() -> Flowsheet:
    """Create a sheet with wide stream-table text.

    Returns
    -------
    Flowsheet
        Flowsheet containing wide property labels and values.
    """
    fs = _sheet()
    fs.streams[0].properties = {
        "Vapour Fraction (mass)": "0.0441 kg/kg total",
        "Temperature": "35 C",
    }
    return fs


def test_stream_table_columns_are_ruled_wide_enough_for_their_values():
    """Verify stream table columns are ruled wide enough for their values."""
    svg = _wide_table_sheet().to_svg(show_stream_table=True)
    assert "Vapour Fraction (mass)" in svg and "0.0441 kg/kg total" in svg
    for x0, x1, ink0, ink1, text in _table_cells(svg):
        assert x0 <= ink0 and ink1 <= x1, (
            f"{text!r} is drawn from {ink0:.1f} to {ink1:.1f}, outside its cell {x0:.1f}..{x1:.1f}"
        )


def test_a_page_too_small_for_the_stream_table_says_so():
    """Verify a page too small for the stream table says so."""
    fs = _sheet()
    fs.streams[0].properties = {
        "Vapour Fraction (mass)": "0.0441 kg/kg total " * 12,
    }
    with pytest.raises(ValueError, match="stream table"):
        fs.to_svg(show_stream_table=True, page_size="A4", border="zone")


def test_an_abbreviated_title_names_the_field_and_the_text_it_cut():
    """Verify an abbreviated title names the field and the text it cut."""
    long_title = "Ethanol Purification and Dehydration Area A300"
    fs = _sheet()
    fs.title_block = TitleBlock(drawing_number="PFD-1", title=long_title)
    svg = fs.to_svg(page_size="A3", border="zone")
    assert "Ethanol Purification and Dehydratio…" in svg  # the strip cannot grow
    cut = [w for w in fs.warnings if w.code == "text-truncated"]
    assert cut, "an abbreviated title must not be silent"
    assert len(cut) == 1 and "title" in cut[0].message
    assert long_title in cut[0].message
    # The warning reports the measured text and cell widths.
    assert "needs 239 of the 187 units its cell has (1.3x)" in cut[0].message


def test_what_survives_an_abbreviation_fits_the_cell_it_was_cut_for():
    """Verify what survives an abbreviation fits the cell it was cut for."""
    from pandid.render.furniture import _TITLE_TYPE, _TITLE_W, clip, text_width

    titles = [
        "Ethanol Purification and Dehydration Area A300",
        "M" * 40,
        "i" * 40,
        "PROCESS FLOW DIAGRAM SHEET 1 OF 3",
    ]
    for title in titles:
        drawn = clip(title, _TITLE_W, _TITLE_TYPE, True)
        assert text_width(drawn, _TITLE_TYPE, True) <= _TITLE_W, drawn
        assert drawn.endswith("…") == (text_width(title, _TITLE_TYPE, True) > _TITLE_W)


def test_a_title_that_fits_says_nothing():
    """Verify a title that fits says nothing."""
    fs = _sheet()
    fs.title_block = TitleBlock(drawing_number="PFD-1", title="Ethanol A300")
    svg = fs.to_svg(page_size="A3", border="zone")
    assert "…" not in svg
    assert not [w for w in fs.warnings if w.code.startswith("text-")]


def test_how_much_of_a_title_survives_does_not_depend_on_the_sheet_count():
    """Verify how much of a title survives does not depend on the sheet count."""

    def drawn_title(of_sheets):
        """Return the rendered title for a sheet-count value."""
        fs = _sheet()
        fs.title_block = TitleBlock(title="Transfer and Relief U100", of_sheets=of_sheets)
        svg = fs.to_svg(border="zone")
        return re.search(
            r'font-size="12.5" text-anchor="start" '
            r'font-weight="bold" fill="black">([^<]*)</text>',
            svg,
        ).group(1)

    assert drawn_title("1") == "Transfer and Relief U100"
    assert drawn_title("100") == drawn_title("1")


def test_a_status_too_long_for_its_cell_is_reported():
    """Verify a status too long for its cell is reported."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", status="ISSUED FOR CONSTRUCTION, REVIEW AND APPROVAL")
    fs.to_svg(border="zone")
    assert [w for w in fs.warnings if w.code == "text-truncated" and "status" in w.message]


def test_a_revision_description_too_long_for_its_column_is_reported():
    """Verify a revision description too long for its column is reported."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo",
        revisions=[
            Revision(
                "A",
                "2026-01-01",
                "Issued for internal review by the process engineering group",
                "AA",
            )
        ],
    )
    fs.to_svg(border="zone")
    assert [
        w
        for w in fs.warnings
        if w.code == "text-truncated" and "revisions[0].description" in w.message
    ]


def test_the_revision_date_column_holds_a_full_date():
    """Verify the revision date column holds a full date."""
    fs = _sheet()
    # A stream property suppresses unrelated table warnings.
    fs.streams[0].properties = {"Flow (kg/h)": "4200"}
    fs.title_block = TitleBlock(
        title="Demo", revisions=[Revision("A", "2026-01-01", "Issued", "AA")]
    )
    svg = fs.to_svg(border="zone")
    assert ">2026-01-01</text>" in svg
    assert not fs.warnings


def test_a_box_narrower_than_its_own_rows_is_reported():
    """Verify a box narrower than its own rows is reported."""
    from pandid.document import Annotation

    fs = _sheet()
    fs.add_annotation(
        Annotation(title="NOTES", width=60, rows=["Sampling point on every product line."])
    )
    fs.to_svg(border="zone")
    assert [w for w in fs.warnings if w.code == "text-overruns-cell" and "NOTES" in w.message]


def test_a_finding_from_an_earlier_render_does_not_survive_the_fix():
    """Verify a finding from an earlier render does not survive the fix."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Ethanol Purification and Dehydration Area A300")
    fs.to_svg(border="zone")
    assert [w for w in fs.warnings if w.code == "text-truncated"]
    fs.title_block.title = "Ethanol A300"
    fs.to_svg(border="zone")
    assert not [w for w in fs.warnings if w.code == "text-truncated"]


# --- title-strip field outcomes -----------------------------------------------


def test_a_long_title_is_lettered_smaller_rather_than_abbreviated():
    """Verify a long title is lettered smaller rather than abbreviated."""
    for title, drawn_at in (
        ("Propylene Glycol Reaction U200", "12.1"),
        ("Transfer and Relief System U100", "12.0"),
        ("Aromatics Recovery A100 Sheet 1", "11.5"),
        # Titles that use the default title size.
        ("Propylene Glycol Reaction", "12.5"),
        ("Ethanol Purification A300", "12.5"),
        ("Transfer and Relief U100", "12.5"),
    ):
        fs = _sheet()
        fs.title_block = TitleBlock(title=title)
        svg = fs.to_svg(border="zone")
        assert f'font-size="{drawn_at}"' in svg, title
        assert f">{title}</text>" in svg, title
        assert not [w for w in fs.warnings if w.code.startswith("text-")], title


def test_the_title_is_never_lettered_under_its_subtitle():
    """Verify the title is never lettered under its subtitle."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Ethanol Purification and Dehydration Area A300",
        subtitle="Piping and Instrumentation Diagram",
    )
    svg = fs.to_svg(border="zone")
    assert "Ethanol Purification and Dehydratio…" in svg
    title_sizes = re.findall(r'font-size="([\d.]+)" text-anchor="start" font-weight="bold"', svg)
    assert "10.5" in title_sizes  # the subtitle's size, and no smaller


def test_validate_reports_an_over_long_field_with_nothing_rendered():
    """Verify validate reports an over long field with nothing rendered."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo", project="Dalby Bioethanol Expansion, Stage 2 Debottlenecking"
    )
    found = [i for i in fs.validate() if i.code == "text-truncated"]
    assert len(found) == 1
    assert "project" in found[0].message
    assert "units its cell has" in found[0].message
    assert fs.streams[0].route is None  # nothing was laid out to answer it


def test_a_render_reports_an_over_long_field_once():
    """Verify a render reports an over long field once."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", status="ISSUED FOR CONSTRUCTION, REVIEW AND APPROVAL")
    fs.to_svg(border="zone", page_size="A3")
    assert len([w for w in fs.warnings if "status" in w.message]) == 1


def test_the_sheet_count_names_both_the_fields_that_fill_it():
    """Verify the sheet count names both the fields that fill it."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", sheet="1", of_sheets="1 of the 128 issued")
    fs.to_svg(border="zone")
    over = [w for w in fs.warnings if w.code == "text-overruns-cell"]
    assert len(over) == 1
    assert over[0].message.startswith("sheet/of_sheets is wider than")


def test_a_signatory_with_no_revision_row_to_sign_is_reported():
    """Verify a signatory with no revision row to sign is reported."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", drawn_by="A. Anderson", approved_by="R. Lee")
    svg = fs.to_svg(border="zone")
    assert "A. Anderson" not in svg and "R. Lee" not in svg
    found = [w for w in fs.warnings if w.code == "title-block-signatory-undrawn"]
    assert len(found) == 1
    assert "drawn_by='A. Anderson'" in found[0].message
    assert "approved_by='R. Lee'" in found[0].message
    assert "checked_by" not in found[0].message  # unset, so nothing was lost


def test_a_signatory_with_a_revision_row_is_drawn_and_silent():
    """Verify a signatory with a revision row is drawn and silent."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo",
        drawn_by="AA",
        checked_by="JS",
        revisions=[Revision("0", "2026-01-01", "Issued")],
    )
    svg = fs.to_svg(border="zone")
    assert ">AA</text>" in svg and ">JS</text>" in svg
    assert not [w for w in fs.warnings if w.code == "title-block-signatory-undrawn"]


def _findings(fs: Flowsheet) -> list[tuple[str, str]]:
    """Return sorted title-strip validation findings.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to validate.

    Returns
    -------
    list[tuple[str, str]]
        Finding codes and messages.
    """
    return sorted(
        (i.code, i.message) for i in fs.validate() if i.code.startswith(("text-", "title-block"))
    )


def _rendered(fs: Flowsheet, how: str, **kw: object) -> list[tuple[str, str]]:
    """Render a flowsheet and return title-strip findings.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to render.
    how : str
        Name of the renderer method.
    **kw : object
        Renderer options.

    Returns
    -------
    list[tuple[str, str]]
        Finding codes and messages emitted by the render.
    """
    getattr(fs, how)(border="zone", **kw)
    return sorted(
        (w.code, w.message) for w in fs.warnings if w.code.startswith(("text-", "title-block"))
    )


def _block(name: str = "Ethanol A300", **kw: object) -> Flowsheet:
    """Create a sheet with a title block.

    Parameters
    ----------
    name : str, default="Ethanol A300"
        Flowsheet name.
    **kw : object
        ``TitleBlock`` constructor arguments.

    Returns
    -------
    Flowsheet
        Flowsheet containing the requested title block.
    """
    fs = _sheet(name=name)
    fs.title_block = TitleBlock(**kw)
    return fs


# --- title-block field coverage ------------------------------------------------


def _scalar_fields(cls: type[Any]) -> list[str]:
    """Return scalar dataclass fields.

    Parameters
    ----------
    cls : type[Any]
        Dataclass to inspect.

    Returns
    -------
    list[str]
        Fields that are not built by a default factory.
    """
    return [f.name for f in dataclasses.fields(cls) if f.default_factory is dataclasses.MISSING]


_BLOCK_FIELDS = _scalar_fields(TitleBlock)
_REV_FIELDS = _scalar_fields(Revision)


@dataclasses.dataclass(frozen=True)
class _Answer:
    """Expected validation and rendering outcome for one field.

    Parameters
    ----------
    overlong : str
        Value that exceeds the field's available space.
    code : str
        Expected validation code.
    named : str
        Expected source field in the validation message.
    fits : str
        Value that fits the field.
    ink : str, default=""
        Expected rendered value when it differs from ``fits``.
    cells : int, default=1
        Number of title-strip cells that render the value.
    signed : bool, default=False
        Whether the value requires a revision row.
    """

    overlong: str
    code: str
    named: str
    fits: str
    ink: str = ""
    cells: int = 1
    signed: bool = False

    @property
    def drawn(self) -> str:
        """Return the expected rendered value.

        Returns
        -------
        str
            Explicit ink value, or the fitting value.
        """
        return self.ink or self.fits


#: Long value used for truncation and overflow checks.
_LONG = "Wollongong " * 12

#: Revision values needed to render block-level signatories.
_SIGNED_ROW = ("0", "2026-01-01", "Issued")

_ANSWERS: dict[str, _Answer] = {
    "title": _Answer(_LONG, "text-truncated", "title", "Zed Title"),
    "subtitle": _Answer(_LONG, "text-truncated", "subtitle", "Zed Subtitle"),
    "drawing_number": _Answer(_LONG, "text-truncated", "drawing_number", "PFD-Zed-1"),
    "project": _Answer(_LONG, "text-truncated", "project", "Zed Project"),
    "client": _Answer(_LONG, "text-truncated", "client", "Zed Client"),
    "company": _Answer("Wollongong-Warrawong-Woonona", "text-overruns-cell", "company", "Zedco"),
    "status": _Answer(_LONG, "text-truncated", "status", "ZED STATUS"),
    # The count cell is supplied by both values.
    "sheet": _Answer(_LONG, "text-overruns-cell", "sheet/of_sheets", "7", "SHEET 7 of 1"),
    "of_sheets": _Answer(_LONG, "text-overruns-cell", "sheet/of_sheets", "9", "SHEET 1 of 9"),
    "scale": _Answer(_LONG, "text-truncated", "scale", "1:7"),
    "drawn_by": _Answer(_LONG, "text-truncated", "drawn_by -> revisions[0].by", "Zb", signed=True),
    "checked_by": _Answer(
        _LONG, "text-truncated", "checked_by -> revisions[0].checked", "Zc", signed=True
    ),
    "approved_by": _Answer(
        _LONG, "text-truncated", "approved_by -> revisions[0].approved", "Za", signed=True
    ),
    "date": _Answer(_LONG, "text-truncated", "date", "2026-07-02"),
}

#: Expected outcomes for revision-grid fields.
_REV_ANSWERS: dict[str, _Answer] = {
    # ``rev`` appears in the grid and the title-strip revision cell.
    "rev": _Answer(_LONG, "text-truncated", "revisions[0].rev", "Z1", cells=2),
    "date": _Answer(_LONG, "text-truncated", "revisions[0].date", "2026-07-02"),
    "description": _Answer(_LONG, "text-truncated", "revisions[0].description", "Zed issue"),
    "by": _Answer(_LONG, "text-truncated", "revisions[0].by", "Zb"),
    "checked": _Answer(_LONG, "text-truncated", "revisions[0].checked", "Zc"),
    "approved": _Answer(_LONG, "text-truncated", "revisions[0].approved", "Za"),
}

#: Fields covered by the title-block outcome matrices.
_SWEPT = [name for name in _BLOCK_FIELDS if name in _ANSWERS]
_UNANSWERED = [name for name in _BLOCK_FIELDS if name not in _ANSWERS]
_REV_SWEPT = [name for name in _REV_FIELDS if name in _REV_ANSWERS]
_REV_UNANSWERED = [name for name in _REV_FIELDS if name not in _REV_ANSWERS]


def test_the_sweep_answers_for_every_field_the_block_has():
    """Verify the sweep answers for every field the block has."""
    assert _UNANSWERED == [], "title-block fields with no answer in _ANSWERS"
    assert _REV_UNANSWERED == [], "revision fields with no answer in _REV_ANSWERS"
    assert sorted(_ANSWERS) == sorted(_BLOCK_FIELDS)
    assert sorted(_REV_ANSWERS) == sorted(_REV_FIELDS)


def _kw(field: str, value: "str | None") -> dict:
    """Create title-block keyword arguments for a field value.

    Parameters
    ----------
    field : str
        Title-block field to set.
    value : str or None
        Field value, or ``None`` to leave the field unset.

    Returns
    -------
    dict
        ``TitleBlock`` constructor arguments.
    """
    kw: dict = {} if field == "title" else {"title": "Demo"}
    if _ANSWERS[field].signed:
        kw["revisions"] = [Revision(*_SIGNED_ROW)]
    if value is not None:
        kw[field] = value
    return kw


@pytest.mark.parametrize("field", _SWEPT)
def test_every_title_block_field_reports_a_value_it_cannot_hold(field):
    """Verify every title block field reports a value it cannot hold."""
    answer = _ANSWERS[field]
    fs = _sheet()
    fs.title_block = TitleBlock(**_kw(field, answer.overlong))
    found = [w for w in fs.validate() if w.code.startswith("text-")]
    assert [w.code for w in found] == [answer.code]
    assert found[0].message.startswith(f"{answer.named} ")


# --- rendered title-block field coverage --------------------------------------

#: Patterns used to identify rendered title-strip cells.
_SVG_TEXT = re.compile(r'<text x="([^"]*)" y="([^"]*)"[^>]*>([^<]*)</text>')
_DRAWIO_VALUE = re.compile(r'<mxCell id="([^"]*)" value="([^"]*)"')


def _lettering(fs, how: str) -> "list[tuple[str, str]]":
    """Extract rendered title-strip cell values.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to render.
    how : str
        Name of the renderer method.

    Returns
    -------
    list[tuple[str, str]]
        Renderer cell identifiers and decoded values.
    """
    out = getattr(fs, how)(border="zone")
    if how == "to_svg":
        return [(x + "," + y, html.unescape(t)) for x, y, t in _SVG_TEXT.findall(out)]
    return [(cid, html.unescape(v)) for cid, v in _DRAWIO_VALUE.findall(out)]


def _cells_drawing(fs, how: str, ink: str) -> "list[str]":
    """Return cells that render a requested value.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to render.
    how : str
        Name of the renderer method.
    ink : str
        Rendered value to locate.

    Returns
    -------
    list[str]
        Matching cell identifiers.
    """
    return [cell for cell, text in _lettering(fs, how) if text == ink]


def _drawn_in(answer: _Answer, fs, how: str, what: str) -> None:
    """Assert that a rendered value occupies the expected cells.

    Parameters
    ----------
    answer : _Answer
        Expected field outcome.
    fs : Flowsheet
        Flowsheet to render.
    how : str
        Name of the renderer method.
    what : str
        Field name included in assertion output.
    """
    cells = _cells_drawing(fs, how, answer.drawn)
    assert len(cells) == answer.cells, (what, answer.drawn, cells)
    assert len(set(cells)) == answer.cells, (what, answer.drawn, cells)


@pytest.mark.parametrize("how", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("field", _SWEPT)
def test_every_title_block_field_a_cell_can_hold_is_drawn_and_silent(field, how):
    """Verify every title block field a cell can hold is drawn and silent."""
    answer = _ANSWERS[field]
    _drawn_in(answer, _block(**_kw(field, answer.fits)), how, field)
    assert _findings(_block(**_kw(field, answer.fits))) == []


@pytest.mark.parametrize("how", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("field", _REV_SWEPT)
def test_every_revision_field_a_cell_can_hold_is_drawn_and_silent(field, how):
    """Verify every revision field a cell can hold is drawn and silent."""
    answer = _REV_ANSWERS[field]
    kw = {"title": "Demo", "revisions": [Revision(**{field: answer.fits})]}
    _drawn_in(answer, _block(**kw), how, field)
    assert _findings(_block(**kw)) == []


# --- title-strip cell counts ---------------------------------------------------


def _text_findings(fs: Flowsheet) -> list:
    """Return text-related validation findings.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to validate.

    Returns
    -------
    list
        Validation findings with text-related codes.
    """
    return [i for i in fs.validate() if i.code.startswith("text-")]


@pytest.mark.parametrize("field", _SWEPT)
def test_a_block_field_is_drawn_in_as_many_cells_as_it_reports(field):
    """Verify a block field is drawn in as many cells as it reports."""
    assert len(_text_findings(_block(**_kw(field, _ANSWERS[field].overlong)))) == (
        _ANSWERS[field].cells
    )


@pytest.mark.parametrize("field", _REV_SWEPT)
def test_a_revision_field_is_drawn_in_as_many_cells_as_it_reports(field):
    """Verify a revision field is drawn in as many cells as it reports."""
    kw = {"title": "Demo", "revisions": [Revision(**{field: _REV_ANSWERS[field].overlong})]}
    assert len(_text_findings(_block(**kw))) == _REV_ANSWERS[field].cells


def test_a_company_name_that_wraps_past_the_strip_is_reported():
    """Verify a company name that wraps past the strip is reported."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", company="Wollongong " * 12)
    fs.to_svg(border="zone")
    found = [w for w in fs.warnings if w.code == "title-block-company-overflows"]
    assert len(found) == 1
    assert "wraps to 12 lines" in found[0].message
    assert "units the strip is deep" in found[0].message


def test_a_company_name_the_strip_is_deep_enough_for_is_silent():
    """Verify a company name the strip is deep enough for is silent."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", company="PANDID Engineering Pty Ltd")
    fs.to_svg(border="zone")
    assert not [w for w in fs.warnings if w.code.startswith("title-block-")]


@pytest.mark.parametrize("field", _REV_SWEPT)
def test_every_revision_field_reports_a_value_it_cannot_hold(field):
    """Verify every revision field reports a value it cannot hold."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo", revisions=[Revision(**{field: _REV_ANSWERS[field].overlong})]
    )
    found = [w for w in fs.validate() if w.code == "text-truncated"]
    # ``rev`` is drawn in both revision cells.
    assert sum(w.message.startswith(f"revisions[0].{field} was ") for w in found) == 1
    if field == "rev":
        assert sum(w.message.startswith("revisions[0].rev -> rev was ") for w in found) == 1


# --- width-based clipping ------------------------------------------------------


@pytest.mark.parametrize("page", ["A4", "A3", "A2", "A1", "A0"])
def test_a_fullwidth_title_is_cut_to_a_width_and_not_to_a_count(page):
    """Verify a fullwidth title is cut to a width and not to a count."""
    from pandid.render.furniture import _TITLE_W, text_width

    fs = _sheet()
    fs.title_block = TitleBlock(title="Ｗ" * 200, sheet="1", of_sheets="1")
    svg = fs.to_svg(border="zone", page_size=page)
    match = re.search(
        r'font-size="([\d.]+)" text-anchor="start" font-weight="bold" '
        r'fill="black">(Ｗ+…)</text>',
        svg,
    )
    assert match is not None
    size, drawn = float(match.group(1)), match.group(2)
    # The title width excludes the sheet-count cell.
    assert text_width(drawn, size, True) <= _TITLE_W


def test_a_latin_title_is_cut_where_the_face_says_and_not_where_a_mean_said():
    """Verify a latin title is cut where the face says and not where a mean said."""
    from pandid.render.furniture import _TITLE_W, _SUBTITLE_TYPE, text_width

    fs = _sheet()
    fs.title_block = TitleBlock(title="Ethanol Purification and Dehydration Area A300")
    svg = fs.to_svg(border="zone")
    assert "Ethanol Purification and Dehydratio…" in svg
    assert text_width("Ethanol Purification and Dehydratio…", _SUBTITLE_TYPE, True) <= _TITLE_W


# --- finding de-duplication ----------------------------------------------------


def test_a_word_the_company_cell_cannot_break_is_reported_once():
    """Verify a word the company cell cannot break is reported once."""
    word = "Wollongong-Warrawong-Woonona"
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", company=f"{word} {word}")
    found = [w for w in fs.validate() if w.code == "text-overruns-cell"]
    assert len(found) == 1
    assert word in found[0].message


def test_two_revisions_abbreviating_the_same_initials_are_two_findings():
    """Verify two revisions abbreviating the same initials are two findings."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo",
        revisions=[
            Revision("A", "2026-01-01", "Issued", "Wollongong " * 4),
            Revision("B", "2026-02-01", "Re-issued", "Wollongong " * 4),
        ],
    )
    found = [w for w in fs.validate() if w.code == "text-truncated" and ".by " in w.message]
    assert len(found) == 2


# --- finding source fields -----------------------------------------------------


def test_a_blank_title_reports_the_flowsheet_name_that_filled_it():
    """Verify a blank title reports the flowsheet name that filled it."""
    fs = _sheet(name="A Flowsheet Name Far Too Long For The Title Cell To Hold")
    fs.title_block = TitleBlock()
    found = [i for i in fs.validate() if i.code == "text-truncated"]
    assert len(found) == 1
    assert found[0].message.startswith("Flowsheet name -> title was truncated")


def test_a_backfilled_signatory_reports_the_block_field_that_supplied_it():
    """Verify a backfilled signatory reports the block field that supplied it."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo",
        drawn_by="A. Anderson",
        revisions=[Revision("0", "2026-01-01", "Issued")],
    )
    found = [i for i in fs.validate() if i.code == "text-truncated"]
    assert len(found) == 1
    assert found[0].message.startswith("drawn_by -> revisions[0].by was truncated")


def test_a_signatory_the_newest_revision_overrides_is_reported():
    """Verify a signatory the newest revision overrides is reported."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo",
        drawn_by="AA",
        checked_by="EE",
        revisions=[Revision("0", "2026-01-01", "Issued", "BB", "CC")],
    )
    svg = fs.to_svg(border="zone")
    assert ">AA</text>" not in svg and ">EE</text>" not in svg
    found = [w for w in fs.warnings if w.code == "title-block-signatory-undrawn"]
    assert len(found) == 1
    assert "drawn_by='AA' (revisions[0].by='BB' is drawn)" in found[0].message
    assert "checked_by='EE' (revisions[0].checked='CC' is drawn)" in found[0].message


@pytest.mark.parametrize(
    "revision",
    [
        Revision("0", "2026-01-01", "Issued", "AA"),  # the same name: drawn
        Revision("0", "2026-01-01", "Issued"),  # blank: the block fills it
    ],
)
def test_a_signatory_the_sheet_does_draw_is_silent(revision):
    """Verify a signatory the sheet does draw is silent."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", drawn_by="AA", revisions=[revision])
    svg = fs.to_svg(border="zone")
    assert ">AA</text>" in svg
    assert not [w for w in fs.warnings if w.code == "title-block-signatory-undrawn"]


# --- clipping boundaries -------------------------------------------------------


#: Glyphs with wide, narrow, and fullwidth metrics.
CUT_SCRIPTS = ["W", "i", "Ｗ"]


@pytest.mark.parametrize("glyph", CUT_SCRIPTS)
@pytest.mark.parametrize("bold", [False, True])
@pytest.mark.parametrize("size", [6.5, 7.5, 8.0, 9.0, 10.5, 11.0, 12.5])
def test_a_cut_string_fits_its_cell_and_one_more_character_would_not(size, bold, glyph):
    """Verify a cut string fits its cell and one more character would not."""
    from pandid.render.furniture import clip, text_width

    room = 1.0
    while room <= 300.0:
        drawn = clip(glyph * 400, room, size, bold)
        if room > text_width("…", size, bold):
            assert text_width(drawn, size, bold) <= room, (room, size, bold)
            # ...and maximal: one more of the same glyph would not have fitted.
            assert text_width(drawn[:-1] + glyph + "…", size, bold) > room, (room, size, bold)
        room = round(room + 0.5, 3)


# --- fitting-findings source fields --------------------------------------------


def _fit_messages(**kw: object) -> list[str]:
    """Return text-finding messages for a title block.

    Parameters
    ----------
    **kw : object
        ``TitleBlock`` constructor arguments.

    Returns
    -------
    list[str]
        Text-related validation messages.
    """
    fs = _sheet(name="A Flowsheet Name Far Too Long For The Title Cell To Hold")
    fs.title_block = TitleBlock(**kw)
    return [i.message for i in fs.validate() if i.code.startswith("text-")]


LONG = "Wollongong " * 12


@pytest.mark.parametrize(
    "kw,named",
    [
        # Blank fields use fallback source values.
        ({}, "Flowsheet name -> title"),
        ({"title": "Demo", "scale": LONG}, "scale"),
        ({"title": "Demo", "date": LONG}, "date"),
        (
            {
                "title": "Demo",
                "drawn_by": LONG,
                "revisions": [Revision("0", "2026-01-01", "Issued")],
            },
            "drawn_by -> revisions[0].by",
        ),
        (
            {"title": "Demo", "revisions": [Revision(LONG, "2026-01-01", "Issued")]},
            "revisions[0].rev -> rev",
        ),
    ],
)
def test_a_finding_names_the_field_that_supplied_the_value(kw, named):
    """Verify a finding names the field that supplied the value."""
    assert any(m.startswith(f"{named} ") for m in _fit_messages(**kw)), (named, _fit_messages(**kw))


def test_a_fitted_scale_is_not_reported_as_the_scale_field():
    """Verify a fitted scale is not reported as the scale field."""
    from pandid.render.furniture import title_strip_fit

    found = title_strip_fit(
        TitleBlock(title="Demo"), "Demo", "2026-01-01", fit_scale="1:" + "9" * 40
    )
    assert [f[0] for f in found] == ["the fitted scale -> scale"]


def test_a_stamped_date_is_not_reported_as_the_date_field():
    """Verify a stamped date is not reported as the date field."""
    from pandid.render.furniture import title_strip_fit

    found = title_strip_fit(TitleBlock(title="Demo"), "Demo", "2026-01-01" * 6)
    assert [f[0] for f in found] == ["today's date -> date"]


# --- whitespace normalization --------------------------------------------------


def _drawn_sheet(how: str, field: str, value: object | None, *, assigned: bool = False) -> str:
    """Render a sheet with one title-block field value.

    Parameters
    ----------
    how : str
        Name of the renderer method.
    field : str
        Title-block field to set.
    value : object or None
        Value to render, or ``None`` to leave the field unset.
    assigned : bool, default=False
        Whether to assign the value after construction.

    Returns
    -------
    str
        Rendered document.
    """
    fs = _sheet(name="Ethanol Purification A300")
    kw: dict = {} if field == "title" else {"title": "Demo"}
    if value is not None and not assigned:
        kw[field] = value
    fs.title_block = TitleBlock(**kw)
    if value is not None and assigned:
        setattr(fs.title_block, field, value)
    return getattr(fs, how)(border="zone", page_size="A3")


@pytest.mark.parametrize("assigned", [False, True], ids=["constructed", "assigned"])
@pytest.mark.parametrize("field", _BLOCK_FIELDS)
def test_a_whitespace_field_draws_exactly_what_an_unset_one_draws(field, assigned):
    """Verify a whitespace field draws exactly what an unset one draws."""
    unset = _drawn_sheet("to_svg", field, None)
    assert unset == _drawn_sheet("to_svg", field, "  \t ", assigned=assigned)


# --- non-string title-block values ---------------------------------------------


@pytest.mark.parametrize("how", ["to_svg", "to_drawio"])
@pytest.mark.parametrize(
    "stated", [0, 0.0, False, 7, 1], ids=["zero", "zero-float", "false", "seven", "one"]
)
def test_a_stated_title_block_value_is_drawn_as_stated_however_it_is_typed(stated, how):
    """Verify a stated title block value is drawn as stated however it is typed."""
    assert _drawn_sheet(how, "project", stated) == _drawn_sheet(how, "project", str(stated))


@pytest.mark.parametrize("how", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("half,ink", [("sheet", "SHEET 0 of 1"), ("of_sheets", "SHEET 1 of 0")])
def test_a_stated_sheet_number_is_never_replaced_by_the_default(half, ink, how):
    """Verify a stated sheet number is never replaced by the default."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", **{half: 0})
    assert [text for _cell, text in _lettering(fs, how) if text == ink]
    # An explicit zero differs from the default count.
    assert _drawn_sheet(how, half, 0) != _drawn_sheet(how, half, None)


# --- title-block document round trips ------------------------------------------


#: Non-string values accepted by the title-block document reader.
_TYPED = [0, 0.0, False, True, 1, 7, 7.5, None]
_TYPED_IDS = ["zero", "zero-float", "false", "true", "one", "seven", "float", "none"]


def _file(tb: TitleBlock, how: str) -> str:
    """Render a sheet containing a title block.

    Parameters
    ----------
    tb : TitleBlock
        Title block to render.
    how : str
        Name of the renderer method.

    Returns
    -------
    str
        Rendered document.
    """
    return getattr(_sheet_with(tb), how)(border="zone", page_size="A3")


def _through_a_spec(tb: TitleBlock) -> TitleBlock:
    """Round-trip a title block through a flowsheet specification.

    Parameters
    ----------
    tb : TitleBlock
        Title block to serialize and read.

    Returns
    -------
    TitleBlock
        Reconstructed title block.
    """
    read = Flowsheet.from_dict(_sheet_with(tb).to_dict()).title_block
    assert read is not None, "the document lost the block entirely"
    return read


def _stating(field: str, value: object | None) -> TitleBlock:
    """Create a title block with one explicitly stated value.

    Parameters
    ----------
    field : str
        Title-block field to set.
    value : object or None
        Value assigned to the field.

    Returns
    -------
    TitleBlock
        Title block with a non-empty title when required.
    """
    kw: dict = {} if field == "title" else {"title": "Demo"}
    kw[field] = value
    return TitleBlock(**kw)


def _revising(field: str, value: object | None) -> Revision:
    """Create a revision with one explicitly stated value.

    Parameters
    ----------
    field : str
        Revision field to set.
    value : object or None
        Value assigned to the field.

    Returns
    -------
    Revision
        Revision containing the requested value.
    """
    kw: dict = {field: value}
    return Revision(**kw)


@pytest.mark.parametrize("stated", _TYPED, ids=_TYPED_IDS)
@pytest.mark.parametrize("field", _BLOCK_FIELDS)
def test_a_typed_title_block_field_is_coerced_by_a_spec_round_trip(field, stated):
    """Verify a typed title block field is coerced by a spec round trip."""
    tb = _stating(field, stated)
    assert getattr(_through_a_spec(tb), field) == ("" if stated is None else str(stated))


@pytest.mark.parametrize("stated", _TYPED, ids=_TYPED_IDS)
@pytest.mark.parametrize("field", _REV_FIELDS)
def test_a_typed_revision_field_is_coerced_by_a_spec_round_trip(field, stated):
    """Verify a typed revision field is coerced by a spec round trip."""
    tb = TitleBlock(title="Demo", revisions=[_revising(field, stated)])
    assert getattr(_through_a_spec(tb).revisions[0], field) == (
        "" if stated is None else str(stated)
    )


@pytest.mark.parametrize("how", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("field", _BLOCK_FIELDS)
def test_a_falsey_title_block_field_draws_the_same_sheet_after_a_spec_round_trip(field, how):
    """Verify a falsey title block field draws the same sheet after a spec round trip."""
    tb = _stating(field, 0)
    assert _file(_through_a_spec(tb), how) == _file(tb, how)


@pytest.mark.parametrize("how", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("field", _REV_FIELDS)
def test_a_falsey_revision_field_draws_the_same_sheet_after_a_spec_round_trip(field, how):
    """Verify a falsey revision field draws the same sheet after a spec round trip."""
    tb = TitleBlock(title="Demo", revisions=[_revising(field, 0)])
    assert _file(_through_a_spec(tb), how) == _file(tb, how)


@pytest.mark.parametrize("how", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("half,ink", [("sheet", "SHEET 0 of 1"), ("of_sheets", "SHEET 1 of 0")])
def test_a_sheet_number_read_back_from_a_document_is_still_the_stated_one(half, ink, how):
    """Verify a sheet number read back from a document is still the stated one."""
    tb = _through_a_spec(_stating(half, 0))
    assert _cells_drawing(_sheet_with(tb), how, ink)


@pytest.mark.parametrize("field", _REV_FIELDS)
def test_a_revision_field_read_back_from_a_document_is_still_the_stated_one(field):
    """Verify a revision field read back from a document is still the stated one."""
    tb = _through_a_spec(TitleBlock(title="Demo", revisions=[_revising(field, 0)]))
    assert getattr(tb.revisions[0], field) == "0"


@pytest.mark.parametrize(
    "stated",
    ["Ethanol A300", "  spaced  ", "0", "", "  "],
    ids=["plain", "padded", "digit", "empty", "spaces"],
)
@pytest.mark.parametrize("field", _BLOCK_FIELDS)
def test_a_text_field_comes_back_out_of_a_document_exactly_as_it_went_in(field, stated):
    """Verify a text field comes back out of a document exactly as it went in."""
    tb = _stating(field, stated)
    assert getattr(_through_a_spec(tb), field) == stated
    fs = _sheet_with(tb)
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_the_reader_and_the_writer_cover_every_field_the_block_has():
    """Verify the reader and the writer cover every field the block has."""
    from pandid.document import _drawn_text_fields

    assert _drawn_text_fields(TitleBlock) == set(_BLOCK_FIELDS)
    assert _drawn_text_fields(Revision) == set(_REV_FIELDS)
    assert "revisions" not in _drawn_text_fields(TitleBlock)


def test_a_whitespace_revision_field_is_the_blank_it_means():
    """Verify a whitespace revision field is the blank it means."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo",
        drawn_by="AA",
        revisions=[Revision("0", "2026-01-01", "Issued", by="   ")],
    )
    svg = fs.to_svg(border="zone")
    # The block backfills, because a whitespace row value is not a value.
    assert ">AA</text>" in svg
    assert not [w for w in fs.warnings if w.code == "title-block-signatory-undrawn"]


@pytest.mark.parametrize("stated", ["", "   ", "\t\n "])
def test_the_date_cell_is_never_blank_on_an_issued_sheet(stated):
    """Verify the date cell is never blank on an issued sheet."""
    import datetime

    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", date=stated)
    svg = fs.to_svg(border="zone", page_size="A3")
    cell = re.search(r'fill="#666">DATE</text>\s*<text[^>]*fill="black">([^<]*)</text>', svg)
    assert cell is not None, "the sheet ruled no DATE cell"
    assert cell.group(1) == datetime.datetime.now().strftime("%Y-%m-%d")


def test_a_whitespace_date_does_not_issue_a_visually_blank_cell():
    """Verify a whitespace date does not issue a visually blank cell."""
    import datetime

    fs = _sheet()
    tb = TitleBlock(date="   ", revisions=[Revision("A", "2026-07-02", "Issued", "AA")])
    fs.title_block = tb
    assert tb.date == "   "

    svg = fs.to_svg(border="zone")
    assert ">   </text>" not in svg
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    assert f">{today}</text>" in svg
    # ...and the export agrees, since both measure one strip.
    assert today in _sheet_with(tb).to_drawio(border="zone")


def _sheet_with(tb: TitleBlock) -> Flowsheet:
    """Attach a title block to a basic sheet.

    Parameters
    ----------
    tb : TitleBlock
        Title block to attach.

    Returns
    -------
    Flowsheet
        Sheet containing ``tb``.
    """
    fs = _sheet()
    fs.title_block = tb
    return fs


@pytest.mark.parametrize("half", ["sheet", "of_sheets"])
def test_a_blank_half_of_the_sheet_count_does_not_issue_half_a_count(half):
    """Verify a blank half of the sheet count does not issue half a count."""
    tb = TitleBlock(title="Demo", **{half: "   "})
    assert getattr(tb, half) == "   "

    svg = _sheet_with(tb).to_svg(border="zone")
    assert "SHEET  of " not in svg and " of </text>" not in svg
    assert ">SHEET 1 of 1</text>" in svg
    assert 'value="SHEET 1 of 1"' in _sheet_with(tb).to_drawio(border="zone")
    # A completed count emits no finding.
    assert _findings(_sheet_with(tb)) == []


def test_a_stated_date_still_wins_the_cell():
    """Verify a stated date still wins the cell."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", date="2026-01-02")
    svg = fs.to_svg(border="zone", page_size="A3")
    cell = re.search(r'fill="#666">DATE</text>\s*<text[^>]*fill="black">([^<]*)</text>', svg)
    assert cell is not None and cell.group(1) == "2026-01-02"


def test_a_whitespace_title_is_a_truncation_validate_reports():
    """Verify a whitespace title is a truncation validate reports."""
    long_name = "A Flowsheet Name Far Too Long For The Title Cell To Hold"
    fs = _sheet(name=long_name)
    fs.title_block = TitleBlock(title="   ")
    found = [i.message for i in fs.validate() if i.code == "text-truncated"]
    assert len(found) == 1
    assert found[0].startswith("Flowsheet name -> title was truncated")
    # And it is the finding the sheet itself makes, word for word.
    drawn = _sheet(name=long_name)
    drawn.title_block = TitleBlock(title="   ")
    drawn.to_svg(border="zone")
    assert [w.message for w in drawn.warnings if w.code == "text-truncated"] == found


#: The four states a field can be in. *unset* leaves the key off ``TitleBlock``
#: altogether; *blank* is whitespace, which is the blank it means; *fits* is a
#: value the cell holds; *overlong* is one it cannot. Only the last may speak,
#: and the third has to draw -- see ``_ANSWERS``.
_STATES = ("unset", "blank", "fits", "overlong")


def _state_value(answer: _Answer, state: str) -> "str | None":
    """Return the input value for a field state.

    Parameters
    ----------
    answer : _Answer
        Expected field outcome.
    state : str
        One of the configured field states.

    Returns
    -------
    str or None
        Value supplied to the title block.
    """
    return {"unset": None, "blank": "  \t ", "fits": answer.fits, "overlong": answer.overlong}[
        state
    ]


#: Expected validation outcomes for each title-block field state.
def _seam_cases():
    """Build title-block state and expected-finding cases.

    Returns
    -------
    list
        Case identifiers, title-block arguments, and expected findings.
    """
    cases = []
    for field in _SWEPT:
        answer = _ANSWERS[field]
        for state in _STATES:
            expect = [(answer.code, answer.named)] if state == "overlong" else []
            cases.append((f"{field}-{state}", _kw(field, _state_value(answer, state)), expect))
    # Revision fields use the same state matrix.
    for rf in _REV_SWEPT:
        answer = _REV_ANSWERS[rf]
        for state in _STATES:
            value = _state_value(answer, state)
            rkw = {} if value is None else {rf: value}
            expect = []
            if state == "overlong":
                # ``rev`` appears in two title-strip cells.
                if rf == "rev":
                    expect.append(("text-truncated", "revisions[0].rev -> rev"))
                expect.append((answer.code, answer.named))
            cases.append(
                (
                    f"revisions.{rf}-{state}",
                    {"title": "Demo", "revisions": [Revision(**rkw)]},
                    expect,
                )
            )
    # Block-level validation cases.
    cases += [
        (
            "signatory-no-row",
            {"title": "Demo", "drawn_by": "AA"},
            [("title-block-signatory-undrawn", "the title block sets")],
        ),
        (
            "signatory-overridden",
            {
                "title": "Demo",
                "drawn_by": "AA",
                "revisions": [Revision("0", "2026-01-01", "Issued", "BB")],
            },
            [("title-block-signatory-undrawn", "the title block sets")],
        ),
        (
            "company-overflows",
            {"title": "Demo", "company": "Wollongong " * 12},
            [("title-block-company-overflows", "company=")],
        ),
        (
            "all-quiet",
            {
                "title": "Demo",
                "drawing_number": "PFD-1",
                "company": "PANDID",
                "revisions": [Revision("0", "2026-01-01", "Issued", "AA")],
            },
            [],
        ),
    ]
    return cases


_SEAM = _seam_cases()


@pytest.mark.parametrize("case_id,kw,expected", _SEAM, ids=[c[0] for c in _SEAM])
def test_every_state_of_every_field_reports_what_it_should(case_id, kw, expected):
    """Verify every state of every field reports what it should."""
    got = _findings(_block(**kw))
    assert [c for c, _m in got] == [c for c, _n in expected], got
    for (_code, named), (_c, message) in zip(expected, got):
        assert message.startswith(named), (named, message)


@pytest.mark.parametrize("case_id,kw,expected", _SEAM, ids=[c[0] for c in _SEAM])
def test_validate_reports_exactly_what_both_backends_report(case_id, kw, expected):
    """Verify validate reports exactly what both backends report."""
    predicted = _findings(_block(**kw))
    assert predicted == _rendered(_block(**kw), "to_svg")
    assert predicted == _rendered(_block(**kw), "to_drawio")


def test_a_page_sized_drawio_title_block_reports_the_model_findings():
    """Verify a page sized drawio title block reports the model findings."""
    kw = _kw("drawing_number", _ANSWERS["drawing_number"].overlong)
    assert _findings(_block(**kw)) == _rendered(_block(**kw), "to_drawio", page_size="A3")
