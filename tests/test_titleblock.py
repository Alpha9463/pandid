"""P&ID title block + revision history rendering."""

import re

import pytest

from pandid import Flowsheet, units as U
from pandid.document import TitleBlock, Revision


def _sheet(name="Demo", span=0.0):
    fs = Flowsheet(name)
    a = fs.add(U.Feed("F")).pin(x=110, y=130)
    b = fs.add(U.Product("P")).pin(x=260 + span, y=130)
    fs.connect(a.outlet, b.inlet)
    return fs


def test_title_block_draws_without_a_border():
    # Both reference PFDs carry a title strip, so a strip is not a P&ID's to
    # own: supplying one is the whole of the request to draw it.
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
    from pandid.document import equipment_list, notes

    fs = _sheet()
    fs.add(U.Pump("P-101", description="Transfer Pump"))
    fs.add_annotation(equipment_list(fs))
    fs.add_annotation(notes(["Sampling point on every product line."]))
    svg = fs.to_svg()
    for token in ("EQUIPMENT LIST", "P-101", "Transfer Pump", "NOTES", "Sampling point"):
        assert token in svg, token


def test_border_and_furniture_are_independent():
    # The border is ink around the sheet; it decides nothing about what the
    # sheet carries. Toggling it must not move a single piece of furniture.
    def build():
        fs = _sheet()
        fs.title_block = TitleBlock(title="Demo Sheet", drawing_number="PFD-9")
        return fs

    zoned = build().to_svg(border="zone")
    plain = build().to_svg(border="none")
    # The frame and the drawing are asked for separately, and a P&ID ruled with
    # the frame is the same furniture as a PFD ruled with it.
    both = build().to_svg(border="zone", diagram="p&id")
    assert '<text x="6' in both
    assert '<text x="6' in zoned  # zone letters are ruled only when asked for
    strip = r'<rect x="[-\d.]+" y="[-\d.]+" width="652.0" height="80.0" fill="white"'
    assert re.search(strip, zoned).group(0) == re.search(strip, plain).group(0)


def test_a_border_nobody_asked_for_is_not_drawn():
    svg = _sheet().to_svg()
    assert "S1" in svg  # the sheet still renders
    assert 'fill="none" stroke="black" stroke-width="2"/>' not in svg  # no frame


@pytest.mark.parametrize(
    "kwargs",
    [
        {"border": "isometric"},
        {"border": "ruled"},
        # The drawing's name is not one of the frame's: border= rules the sheet
        # and diagram= says which drawing is on it.
        {"border": "p&id"},
    ],
)
def test_a_frame_the_renderer_cannot_draw_raises(kwargs):
    with pytest.raises(ValueError):
        _sheet().to_svg(**kwargs)


def test_client_and_project_are_drawn():
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Demo Sheet", client="Northwind Chemicals", project="Ethanol Purification A300"
    )
    svg = fs.to_svg()
    for token in ("CLIENT", "Northwind Chemicals", "PROJECT", "Ethanol Purification A300"):
        assert token in svg, token


def test_the_strip_grows_a_row_for_each_of_them():
    from pandid.render.furniture import measure_title_strip

    bare = measure_title_strip(TitleBlock())
    one = measure_title_strip(TitleBlock(project="Ethanol A300"))
    two = measure_title_strip(TitleBlock(project="Ethanol A300", client="Northwind"))
    assert bare[0] == one[0] == two[0]  # the strip keeps its width
    assert one[1] - bare[1] == two[1] - one[1] > 0


def test_scale_is_drawn():
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo Sheet", scale="1:100")
    svg = fs.to_svg()
    assert "SCALE" in svg and "1:100" in svg


def test_a_sheet_with_no_scale_to_state_rules_no_scale_cell():
    # A drawing on a sheet sized to fit it is at no scale at all, and an empty
    # cell headed SCALE says less than no cell.
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo Sheet")
    assert "SCALE" not in fs.to_svg()


def test_scale_reports_the_ratio_the_drawing_was_fitted_at():
    fs = _sheet(span=4000.0)
    fs.title_block = TitleBlock(title="Demo Sheet")
    svg = fs.to_svg(page_size="A4", border="zone")
    fitted = float(re.search(r'<g id="drawing" transform="[^"]*scale\(([\d.]+)\)', svg).group(1))
    assert fitted < 1
    reported = re.search(r">1:([\d.]+)</text>", svg)
    assert reported, "no scale drawn"
    assert 1 / float(reported.group(1)) == pytest.approx(fitted, rel=0.01)


def test_a_stated_scale_beats_the_computed_one():
    fs = _sheet(span=4000.0)
    fs.title_block = TitleBlock(title="Demo Sheet", scale="NTS")
    svg = fs.to_svg(page_size="A4", border="zone")
    assert ">NTS</text>" in svg
    assert not re.search(r">1:[\d.]+</text>", svg)


def test_title_block_fields_rendered():
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
    fs = Flowsheet("Bare")
    fs.add(U.Feed("F"))
    fs.add(U.Product("P"))
    fs.connect(fs.units[0].outlet, fs.units[1].inlet)
    svg = fs.to_svg(border="zone", diagram="p&id")  # falls back to defaults, must not raise
    assert "Bare" in svg


def test_title_block_fits_narrow_sheet():
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
    import pytest
    from pandid.document import Annotation

    assert Annotation(align="top").align == "top"
    assert Annotation(align="center").align == "center"
    assert Annotation(align="bottom-left").align == "bottom-left"
    with pytest.raises(ValueError):
        Annotation(align="middle-ish")


def test_annotation_docks_flush_to_frame():
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


def _schedule(fs, **kwargs):
    from pandid.document import equipment_list

    return equipment_list(fs, **kwargs).rows


def test_bulk_items_and_junctions_are_not_scheduled():
    """An equipment list is major plant. A valve, a strainer, a reducer, a vent
    and a funnel are bought by the line and covered by the piping class; a mixer
    or splitter is a branch in that line drawn as a triangle. Scheduling them
    puts items on the sheet that no one buys, builds or maintains."""
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
    """``kind`` is a dict key. A schedule reading ('E-101', 'Hex') quotes the
    source code at the reader instead of naming the exchanger."""
    fs = Flowsheet("Named")
    fs.add(U.HeatExchanger("E-101"))
    fs.add(U.HeatExchanger("E-102", description="Feed/Effluent Exchanger"))
    assert _schedule(fs) == [
        ("E-101", "Heat Exchanger"),
        ("E-102", "Feed/Effluent Exchanger"),
    ]


def test_every_registered_kind_names_itself():
    """A kind with no label falls back to its own key, so the map has to cover
    the library rather than the kinds that happened to need it first."""
    from pandid.document import _KIND_LABELS

    kinds = {getattr(U, name).kind for name in U.__all__ if name != "Unit"}
    assert kinds <= set(_KIND_LABELS)
    assert not [label for label in _KIND_LABELS.values() if not label[:1].isupper()]


def test_include_builds_a_schedule_of_its_own():
    """A valve schedule is a real drawing, so naming the rows takes whatever is
    named, in that order, bulk item or not."""
    fs = Flowsheet("Valves")
    fs.add(U.Pump("P-101", description="Feed Pump"))
    fs.add(U.Valve("FV-100", description="Feed Control Valve"))
    fs.add(U.Valve("FV-200"))
    assert _schedule(fs, title="VALVE SCHEDULE", include=["FV-200", "FV-100"]) == [
        ("FV-200", "Valve"),
        ("FV-100", "Feed Control Valve"),
    ]


def test_include_refuses_a_tag_the_flowsheet_does_not_have():
    """Naming a row asserts it exists, so a typo is a mistake and not a filter.

    ``include=["P-101", "P-1O2"]`` -- letter O for zero -- used to draw a
    schedule one line short of what it was asked for and say nothing about it,
    on a sheet whose whole purpose is to list the equipment.
    """
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
    """A section heading keyed to a property no stream sets never appears --
    the same silence :func:`test_include_refuses_a_tag_the_flowsheet_does_not_have`
    above refuses outright. This one cannot raise at assignment (the streams
    may not exist yet when ``stream_table_sections`` is set), so it warns at
    render time instead, naming the key and the heading that never showed."""
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


# --- a column has to have something in it -------------------------------------
#
# ISO 10628-1:2014 4.3.3 a) puts the flows *between the process steps* among
# the things a process flow diagram may carry rather than must, so an internal
# column with nothing in it is a heading over a rule of dashes and is dropped.
# 4.3.2 d)
# makes the ingoing and outgoing ones something the diagram **shall** contain,
# so a boundary column is kept however empty it is -- dropping it would hide the
# omission instead of showing it -- and pandid.validate reports it in words; see
# ``boundary-flow-missing`` in tests/test_validate.py.
#
# A value present and blank is not nothing: it is the author reporting that
# there is nothing to report, and it keeps the column.


def _columns(fs) -> list:
    """The stream numbers the table heads its columns with, in order."""
    from pandid.render.furniture import stream_table_layout

    table = stream_table_layout(fs)
    return [] if table is None else [c.text for c in table.rows[0][1:]]


def _table(fs, **kwargs) -> str:
    """The drawn table alone, since a stream number is also drawn on its line."""
    svg = fs.to_svg(show_stream_table=True, **kwargs)
    body = re.search(r'<g id="stream_table">(.*?)</g>', svg, re.S)
    return body.group(1) if body else ""


def _two_and_two() -> Flowsheet:
    """Four streams, two of them at the sheet edge, two of them tabulated.

    The shape the drop rule is about: S1 comes in off a flag and carries
    data, S2 is internal and carries data, S3 is internal and carries
    none, S4 goes out to a flag and carries none.
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
    fs = _two_and_two()
    assert _columns(fs) == ["S1", "S2", "S4"]
    assert ">S3<" not in _table(fs)


def test_a_boundary_column_with_nothing_in_it_is_kept():
    """The 4.3.2 d) shall. The column is empty because the sheet does not
    say what leaves it, and that is the thing to show rather than hide."""
    fs = _two_and_two()
    assert "S4" in _columns(fs)
    assert ">S4<" in _table(fs)


def test_a_value_present_and_blank_keeps_the_column():
    """The escape hatch, and the reason an absent key and an empty string
    are two different statements: one is silence, the other is an author
    saying this line has none to report. Both draw a dash."""
    fs = _two_and_two()
    internal = fs.streams[2]
    internal.properties = {"Temperature": ""}
    assert _columns(fs) == ["S1", "S2", "S3", "S4"]
    table = _table(fs)
    assert ">S3<" in table
    assert table.count(">-<") == 2  # the blank one and the boundary one


# --- sizing the table ---------------------------------------------------------


def _layout(fs):
    from pandid.render.furniture import stream_table_layout

    table = stream_table_layout(fs)
    assert table is not None
    return table


def _wide(n: int) -> Flowsheet:
    """*n* tabulated streams, each its own feed-to-product line."""
    fs = Flowsheet("wide")
    for i in range(n):
        feed = fs.add(U.Feed(f"F{i}"))
        prod = fs.add(U.Product(f"P{i}"))
        fs.connect(feed.outlet, prod.inlet).properties = {"Temperature": f"{i} C"}
    return fs


def test_the_table_is_set_at_the_size_the_sheet_asks_for():
    fs = _two_and_two()
    fs.stream_table.font_size = 8.0
    assert _layout(fs).size == 8.0
    assert 'font-size="8.0"' in _table(fs)


def test_the_size_rules_the_table_and_not_only_its_lettering():
    """The whole of the feature. Every column of a table of short names and
    short values sits on its minimum width, so a size that reached the
    glyphs alone would leave the table its entire footprint and the author
    whose table overruns an A3 sheet exactly where they were."""
    fs, small = _two_and_two(), _two_and_two()
    small.stream_table.font_size = 7.0
    big, little = _layout(fs), _layout(small)
    assert little.w < big.w
    assert little.h < big.h
    assert little.row_h < big.row_h
    # Ruled in proportion: 7 of 10.5 is two thirds, and the height is rows
    # of one line each, so it lands on the ratio exactly.
    assert little.h / big.h == pytest.approx(7.0 / 10.5)
    assert little.w / big.w == pytest.approx(7.0 / 10.5)


def test_a_table_left_alone_is_drawn_exactly_as_it_always_was():
    """The automatic regime is untouched, at both ends of it: 10.5 while the
    columns fit and shrinking past 18 of them, with the minimum column width
    fixed there because the size is being shrunk to fit values *into* that
    minimum."""
    narrow, wide, widest = _layout(_two_and_two()), _layout(_wide(20)), _layout(_wide(40))
    assert (narrow.size, narrow.row_h) == (10.5, 20.0)
    assert (wide.size, wide.row_h) == (pytest.approx(190.0 / 20), 15.0)
    assert (widest.size, widest.row_h) == (8.0, 15.0)  # and no further
    assert wide.w == pytest.approx(122.0 + 20 * 52.0)


@pytest.mark.parametrize("size", [0, -1, -0.5])
def test_a_size_that_is_not_a_size_is_refused(size):
    fs = _two_and_two()
    fs.stream_table.font_size = size
    with pytest.raises(ValueError, match="font_size"):
        _layout(fs)


def test_an_option_set_after_a_render_reaches_the_next_one():
    """The table is measured at every render rather than cached with the
    frames, so this needs no ``_invalidate_layout()`` -- which is worth
    proving rather than assuming, since a sheet whose geometry is up to date
    skips the stages that would otherwise redo the measuring."""
    fs = _two_and_two()
    first = _table(fs)
    fs.stream_table.font_size = 8.0
    second = _table(fs)
    assert 'font-size="10.5"' in first and 'font-size="8.0"' in second


def test_the_stated_size_reaches_the_drawio_export_too():
    """Both backends measure the table with the same function, so the
    editable model is ruled at the size the sheet is."""
    fs = _two_and_two()
    fs.stream_table.font_size = 8.0
    assert "fontSize=8" in fs.to_drawio(show_stream_table=True)


# --- the two width floors -----------------------------------------------------


def _widths(fs) -> tuple[float, float]:
    """(row-label column, stream column) as the layout rules them."""
    table = _layout(fs)
    return table.rows[0][0].w, table.rows[0][1].w


def _with(fs: Flowsheet, **options: object) -> Flowsheet:
    """*fs* with these stream-table options set on it."""
    for key, value in options.items():
        setattr(fs.stream_table, key, value)
    return fs


def _fits(text: str, size: float = 10.5, bold: bool = False) -> float:
    """What a column holding exactly *text* is ruled at, gutter included."""
    from pandid.render.furniture import _STREAM_GUTTER, text_width

    return text_width(text, size, bold=bold) + _STREAM_GUTTER


def _one_long_value() -> Flowsheet:
    """Three short-named streams, one of which reports a value far wider
    than anything else in the table.

    The awkward case the uniform rule is for: fitting each column to its
    own contents would rule S2 wide and S1 and S3 narrow.
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
    fs = _two_and_two()
    assert (fs.stream_table.label_width, fs.stream_table.column_width) == (122.0, 52.0)
    assert _widths(fs) == (122.0, 52.0)


def test_auto_drops_the_floor_and_rules_the_column_to_its_content():
    fs = _two_and_two()
    fs.stream_table.label_width = "auto"
    fs.stream_table.column_width = "auto"
    label, name = _widths(fs)
    # The row-label column holds "Stream Number", which is wider than the
    # one property name; a stream column holds "S1" and "25 C".
    assert label == pytest.approx(_fits("Stream Number", bold=True))
    assert name == pytest.approx(_fits("25 C"))
    assert label < 122.0 and name < 52.0


def test_each_floor_is_dropped_on_its_own():
    """Two fields and not one switch: a sheet with long row labels and
    two-character stream names wants the second dropped and the first left
    exactly where it is."""
    label_only, name_only = _two_and_two(), _two_and_two()
    label_only.stream_table.label_width = "auto"
    name_only.stream_table.column_width = "auto"
    assert _widths(label_only) == (pytest.approx(_fits("Stream Number", bold=True)), 52.0)
    assert _widths(name_only) == (122.0, pytest.approx(_fits("25 C")))


def test_a_number_is_a_floor_and_not_a_width():
    """Which is the whole of what these two fields are. A number below what
    the column holds changes nothing -- the column is measured either way --
    and a number above it is the way to buy a wide one."""
    fs = _two_and_two()
    fs.stream_table.label_width = 10.0
    fs.stream_table.column_width = 10.0
    assert _widths(fs) == _widths(_with(_two_and_two(), label_width="auto", column_width="auto"))
    wide = _with(_two_and_two(), label_width=300.0, column_width=90.0)
    assert _widths(wide) == (300.0, 90.0)


def test_auto_rules_every_stream_column_at_the_widest_cell_in_the_table():
    """Uniform and not fitted. A stream table is read down for one stream
    and across for one property, so columns that did not line up would be a
    worse drawing than wide ones -- and ``"auto"`` is therefore not a
    promise of a narrow table, only of one with no slack in it."""
    fs = _with(_one_long_value(), column_width="auto")
    table = _layout(fs)
    widths = {c.w for row in table.rows for c in row[1:]}
    assert len(widths) == 1
    assert widths.pop() == pytest.approx(_fits("1013.25 mbara"))


def test_a_column_is_never_ruled_narrower_than_its_own_heading():
    """The headings are measured with the values rather than beside them,
    so the one long name rules the columns exactly as the one long value
    does. A column too narrow for the stream number over it would be a
    defect however much slack it saved."""
    fs = _one_long_value()
    for stream, name in zip(fs.streams, ("HPS-308-100-80-CS", "S2", "S3")):
        stream.name = name
    fs.stream_table.column_width = "auto"
    table = _layout(fs)
    assert table.rows[0][1].w == pytest.approx(_fits("HPS-308-100-80-CS", bold=True))


def test_a_section_heading_still_widens_the_row_label_column_under_auto():
    """A section heading spans the whole table, so it is content the table
    has to hold and not slack ``"auto"`` may take out. The row-label column
    is the only one free to take it up, exactly as at the default."""
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
    """Both floors are stated at 10.5, which is what lets them scale with
    ``font_size``. A field that scaled only while it held its own default
    would be a field an author cannot reason about, so 122.0 set by hand is
    the 122.0 that was there."""
    by_hand = _with(_two_and_two(), label_width=122.0, column_width=52.0, font_size=7.0)
    left_alone = _with(_two_and_two(), font_size=7.0)
    assert _widths(by_hand) == _widths(left_alone)
    assert _widths(by_hand) == (pytest.approx(122.0 * 7.0 / 10.5), pytest.approx(52.0 * 7.0 / 10.5))


def test_auto_composes_with_the_stated_type_size():
    """Nothing left to scale, and the content measured at the size it is
    drawn at: the table shrinks on both counts."""
    big = _with(_two_and_two(), column_width="auto")
    small = _with(_two_and_two(), column_width="auto", font_size=7.0)
    assert _widths(small)[1] == pytest.approx(_fits("25 C", 7.0))
    assert _layout(small).w < _layout(big).w


@pytest.mark.parametrize("field", ["label_width", "column_width"])
@pytest.mark.parametrize("value", ["fit", "", -1, None, True])
def test_a_width_that_is_not_one_is_refused(field, value):
    fs = _with(_two_and_two(), **{field: value})
    with pytest.raises(ValueError, match=field):
        _layout(fs)


def test_the_widths_reach_the_drawio_export_too():
    """The exporter states its own cell inset, so a table ruled to its
    content has to come out of it the width the sheet ruled it -- not merely
    a table that looked right in SVG. Both backends take the columns from
    the one layout, so the .drawio carries the measured widths themselves."""
    from pandid.render.drawio import _num

    fs = _with(_two_and_two(), label_width="auto", column_width="auto")
    label, name = _widths(fs)
    xml = fs.to_drawio(show_stream_table=True)
    assert f'width="{_num(label)}"' in xml
    assert f'width="{_num(name)}"' in xml
    assert f'width="{_num(label + name * 3)}"' in xml  # three tabulated columns


def test_a_content_ruled_cell_still_clears_the_drawio_text_inset():
    """The gutter is the clearance between a rule and a glyph and does not
    scale, so it is what makes an ``"auto"`` table safe in the editable
    model: draw.io insets a cell's own label before the sheet's pad is added,
    and the gutter has to cover both sides of that."""
    from pandid.render.drawio import _TEXT_INSET
    from pandid.render.furniture import _STREAM_PAD, _STREAM_GUTTER

    assert _STREAM_GUTTER >= _STREAM_PAD + _TEXT_INSET


def test_a_sheet_that_states_no_property_draws_no_table():
    """Every column empty is the same finding writ large: a grid of
    headings over nothing is not a stream table."""
    fs = _sheet()
    assert _columns(fs) == []
    assert _table(fs) == ""


def test_a_run_is_judged_over_every_segment_it_is_drawn_in():
    """A line through an inline valve is several streams under one name and
    one column, so what earns the column can sit on a segment other than
    the one the column is headed from: here the product flag is on the far
    segment of the outgoing run, and the property on the far segment of the
    incoming one. The value on that far segment reaches the column too --
    it earned the column, so drawing a dash in it would be the table
    contradicting itself."""
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


# --- which segment of a run the column reports --------------------------------
#
# A run drawn through a valve is one column over several streams, and their
# properties can genuinely differ: a control valve is there to drop the
# pressure. One column cannot show both, and no rule can pick -- which point
# it reports is a decision about the drawing. `tabulate=True` is where the
# author makes it; unmarked, the run reads in the order it is drawn.


def _row(fs, key) -> list:
    """The values the table draws down one property row, in column order."""
    from pandid.render.furniture import stream_table_layout

    table = stream_table_layout(fs)
    for row in [] if table is None else table.rows:
        if len(row) > 1 and row[0].text == key:
            return [c.text for c in row[1:]]
    return []


def _across_a_valve():
    """One run in two segments with the drop across the valve written on it.

    The shape of ``examples/08``'s S6: 11.6 barg above the spillback valve and
    3.4 barg below it, both under one stream number.
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
    fs, _up, _down = _across_a_valve()
    assert _row(fs, "Pressure") == ["11.6 barg"]


def test_the_marked_segment_is_the_one_the_column_reports():
    fs, _up, down = _across_a_valve()
    down.tabulate = True
    assert _row(fs, "Pressure") == ["3.4 barg"]


def test_the_mark_moves_the_values_and_not_the_heading():
    """The number and the line-number components belong to the run rather
    than to any one segment, so the column is headed from the first segment
    whichever one it reports."""
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
    """It says which segment to read *first*, not which to read only. A key
    the marked segment is silent on still comes off the run, so nominating
    the downstream point does not blank out the analysis written upstream.
    """
    fs, up, down = _across_a_valve()
    up.properties["Benzene"] = "0.90"
    down.tabulate = True
    assert _row(fs, "Pressure") == ["3.4 barg"]
    assert _row(fs, "Benzene") == ["0.90"]


def test_two_marks_on_one_run_name_the_run_and_the_way_out():
    """The mark exists to settle which point the column reports, so two of
    them on one column is the question asked again rather than answered."""
    fs, up, down = _across_a_valve()
    up.tabulate = down.tabulate = True
    with pytest.raises(ValueError) as excinfo:
        _row(fs, "Pressure")
    message = str(excinfo.value)
    assert "S1 is drawn in 2 segments and 2 of them are marked" in message
    assert "new_line_number" in message  # names the other way out


def test_a_mark_on_a_run_of_one_segment_changes_nothing():
    fs = Flowsheet("one")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    only = fs.connect(feed.outlet, prod.inlet)
    only.properties = {"Pressure": "4.0 barg"}
    only.tabulate = True
    assert _row(fs, "Pressure") == ["4.0 barg"]


def test_the_mark_survives_the_spec_round_trip():
    """Asserted on the rebuilt sheet's table, not on the two dicts: a flag
    dropped on the way out is dropped from both sides of a dict comparison
    and the column quietly goes back to reporting the upstream point."""
    fs, _up, down = _across_a_valve()
    down.tabulate = True
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert [s.tabulate for s in rebuilt.streams] == [False, True]
    assert _row(rebuilt, "Pressure") == ["3.4 barg"]


# --- text that does not fit the cell drawn for it -----------------------------
#
# Two shapes of answer, and the sheet is entitled to exactly one of them. The
# stream table is sized by the renderer, so it grows to its contents. The title
# strip is fixed geometry -- an ISO 7200 block is a known rectangle in a known
# corner -- so it abbreviates, and says on fs.warnings which field it cut.

_CELL = re.compile(
    r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="[\d.]+" '
    r'fill="[^"]+" stroke="black" stroke-width="0\.75"/>\s*'
    r'<text x="([-\d.]+)" y="[-\d.]+" font-family="[^"]+" font-size="([\d.]+)"'
    r'( font-weight="bold")? text-anchor="(\w+)">([^<]*)</text>'
)


def _table_cells(svg):
    """Every drawn stream-table cell as (rect, text, ink extent).

    Read straight back out of the SVG: the box the renderer ruled, the string it
    wrote in it, and where that string's ink actually starts and ends, measured
    with the same advance width the renderer sizes boxes by.
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


def _wide_table_sheet():
    """A sheet whose row label and values are both wider than the hard-coded
    122 x 52 the table used to rule, taken from the case in issue #68."""
    fs = _sheet()
    fs.streams[0].properties = {
        "Vapour Fraction (mass)": "0.0441 kg/kg total",
        "Temperature": "35 C",
    }
    return fs


def test_stream_table_columns_are_ruled_wide_enough_for_their_values():
    svg = _wide_table_sheet().to_svg(show_stream_table=True)
    assert "Vapour Fraction (mass)" in svg and "0.0441 kg/kg total" in svg
    for x0, x1, ink0, ink1, text in _table_cells(svg):
        assert x0 <= ink0 and ink1 <= x1, (
            f"{text!r} is drawn from {ink0:.1f} to {ink1:.1f}, outside its cell {x0:.1f}..{x1:.1f}"
        )


def test_a_page_too_small_for_the_stream_table_says_so():
    """The table is sized to its contents, so on a fixed page it can be the
    thing that does not fit. That is an error, and the error names it."""
    fs = _sheet()
    fs.streams[0].properties = {
        "Vapour Fraction (mass)": "0.0441 kg/kg total " * 12,
    }
    with pytest.raises(ValueError, match="stream table"):
        fs.to_svg(show_stream_table=True, page_size="A4", border="zone")


def test_an_abbreviated_title_names_the_field_and_the_text_it_cut():
    """Past the size the title is allowed down to, the cell abbreviates -- and
    says which field, what it was given, and by how much it missed."""
    long_title = "Ethanol Purification and Dehydration Area A300"
    fs = _sheet()
    fs.title_block = TitleBlock(drawing_number="PFD-1", title=long_title)
    svg = fs.to_svg(page_size="A3", border="zone")
    assert "Ethanol Purification and De…" in svg  # the strip cannot grow
    cut = [w for w in fs.warnings if w.code == "text-truncated"]
    assert cut, "an abbreviated title must not be silent"
    assert len(cut) == 1 and "title" in cut[0].message
    assert long_title in cut[0].message
    # The two widths and the ratio: what the author edits between. The need is
    # measured at the smallest size the title is allowed down to, since that is
    # the width the text still has to come out of.
    assert "needs 299 of the 187 units its cell has (1.6x)" in cut[0].message


def test_a_title_that_fits_says_nothing():
    fs = _sheet()
    fs.title_block = TitleBlock(drawing_number="PFD-1", title="Ethanol A300")
    svg = fs.to_svg(page_size="A3", border="zone")
    assert "…" not in svg
    assert not [w for w in fs.warnings if w.code.startswith("text-")]


def test_how_much_of_a_title_survives_does_not_depend_on_the_sheet_count():
    """The sheet count shares the title band, and used to be measured out of the
    title's own budget: a set of 100 sheets abbreviated the title of sheet 1."""

    def drawn_title(of_sheets):
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
    """The status cell was drawn with no measurement at all, so a long issue
    status ran straight out through the side of the strip."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", status="ISSUED FOR CONSTRUCTION, REVIEW AND APPROVAL")
    fs.to_svg(border="zone")
    assert [w for w in fs.warnings if w.code == "text-truncated" and "status" in w.message]


def test_a_revision_description_too_long_for_its_column_is_reported():
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
    """Every sheet in the corpus stamps an ISO 8601 date, and the column it goes
    in was 3px narrower than one measures."""
    fs = _sheet()
    # Tabulated, so stream-table-missing does not join the assertion below
    # -- this test is about the revision date column and nothing else.
    fs.streams[0].properties = {"Flow (kg/h)": "4200"}
    fs.title_block = TitleBlock(
        title="Demo", revisions=[Revision("A", "2026-01-01", "Issued", "AA")]
    )
    svg = fs.to_svg(border="zone")
    assert ">2026-01-01</text>" in svg
    assert not fs.warnings


def test_a_box_narrower_than_its_own_rows_is_reported():
    """An Annotation sizes itself to its rows unless it is given a width, and a
    width smaller than the rows need runs the text out through the side."""
    from pandid.document import Annotation

    fs = _sheet()
    fs.add_annotation(
        Annotation(title="NOTES", width=60, rows=["Sampling point on every product line."])
    )
    fs.to_svg(border="zone")
    assert [w for w in fs.warnings if w.code == "text-overruns-cell" and "NOTES" in w.message]


def test_a_finding_from_an_earlier_render_does_not_survive_the_fix():
    fs = _sheet()
    fs.title_block = TitleBlock(title="Ethanol Purification and Dehydration Area A300")
    fs.to_svg(border="zone")
    assert [w for w in fs.warnings if w.code == "text-truncated"]
    fs.title_block.title = "Ethanol A300"
    fs.to_svg(border="zone")
    assert not [w for w in fs.warnings if w.code == "text-truncated"]


# --- what each field does with a value too long for its cell ------------------
#
# The sweep behind #370. Fifteen fields, three answers, and the answer has to be
# a property of the field rather than of which cell somebody looked at last.


def test_a_long_title_is_lettered_smaller_rather_than_abbreviated():
    """The title is the one value on the strip set above the strip's reading
    size, so it has size to give back before it has meaning to give up. Two of
    these three were abbreviated before #370, one of them the title of the
    library's own shipped example."""
    for title, drawn_at in (
        ("Propylene Glycol Reaction", "12.0"),
        ("Ethanol Purification A300", "12.0"),
        ("Transfer and Relief U100", "12.5"),
    ):
        fs = _sheet()
        fs.title_block = TitleBlock(title=title)
        svg = fs.to_svg(border="zone")
        assert f'font-size="{drawn_at}"' in svg, title
        assert f">{title}</text>" in svg, title
        assert not [w for w in fs.warnings if w.code.startswith("text-")], title


def test_the_title_is_never_lettered_under_its_subtitle():
    """Below the subtitle's size the band would say the wrong thing about the
    drawing -- the subordinate line would read as the title -- so the shrinking
    stops there and the cell abbreviates instead."""
    fs = _sheet()
    fs.title_block = TitleBlock(
        title="Ethanol Purification and Dehydration Area A300",
        subtitle="Piping and Instrumentation Diagram",
    )
    svg = fs.to_svg(border="zone")
    assert "Ethanol Purification and De…" in svg
    title_sizes = re.findall(r'font-size="([\d.]+)" text-anchor="start" font-weight="bold"', svg)
    assert "10.5" in title_sizes  # the subtitle's size, and no smaller


def test_validate_reports_an_over_long_field_with_nothing_rendered():
    """The finding's point is to reach the author before the sheet is issued,
    and every width the strip rules is a constant -- so it needs no render."""
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
    """model_issues measures the strip and so does the render; the render's is
    the one that describes the sheet that came out, and it replaces rather than
    joins the other."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", status="ISSUED FOR CONSTRUCTION, REVIEW AND APPROVAL")
    fs.to_svg(border="zone", page_size="A3")
    assert len([w for w in fs.warnings if "status" in w.message]) == 1


def test_the_sheet_count_names_both_the_fields_that_fill_it():
    """One cell, two fields. Named only 'sheet', it sent an author who had set
    of_sheets to look at the wrong one."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", sheet="1", of_sheets="1 of the 128 issued")
    fs.to_svg(border="zone")
    over = [w for w in fs.warnings if w.code == "text-overruns-cell"]
    assert len(over) == 1
    assert over[0].message.startswith("sheet/of_sheets is wider than")


def test_a_signatory_with_no_revision_row_to_sign_is_reported():
    """drawn_by/checked_by/approved_by fill the newest revision row's BY /
    CHK'D / APP'D cells, and a block with no revisions has no such row -- so all
    three were accepted and drawn nowhere at all."""
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


#: Every field of the block that draws a cell of its own, the value that
#: overruns it, the answer the cell gives, and the name the finding has to use.
#: The three signatories are absent because they draw no cell of their own --
#: they backfill a revision row, which is the test two above this one.
#:
#: ``company`` takes an unbreakable value rather than a long one: its cell wraps
#: between words, so a long *name* is stacked rather than lost and only a single
#: over-wide word has nowhere to go. That is the sweep's point -- the answer is a
#: property of the field, and the probe has to be too.
_LONG = "Wollongong " * 12
_FIELD_ANSWERS = [
    ("title", _LONG, "text-truncated", "title"),
    ("subtitle", _LONG, "text-truncated", "subtitle"),
    ("drawing_number", _LONG, "text-truncated", "drawing_number"),
    ("project", _LONG, "text-truncated", "project"),
    ("client", _LONG, "text-truncated", "client"),
    ("company", "Wollongong-Warrawong-Woonona", "text-overruns-cell", "company"),
    ("status", _LONG, "text-truncated", "status"),
    ("sheet", _LONG, "text-overruns-cell", "sheet/of_sheets"),
    ("of_sheets", _LONG, "text-overruns-cell", "sheet/of_sheets"),
    ("scale", _LONG, "text-truncated", "scale"),
    ("date", _LONG, "text-truncated", "date"),
]


#: Every field of the block, for the sweeps that vary the *value* rather
#: than the answer. Taken off _FIELD_ANSWERS so the two cannot drift.
_FIELD_NAMES = [f for f, _v, _c, _n in _FIELD_ANSWERS] + ["drawn_by", "checked_by", "approved_by"]


@pytest.mark.parametrize("field,value,code,named", _FIELD_ANSWERS)
def test_every_title_block_field_reports_a_value_it_cannot_hold(field, value, code, named):
    """The sweep, kept: no field of the block takes an over-long value and says
    nothing about it, and each is named by the name it was set by."""
    fs = _sheet()
    fs.title_block = TitleBlock(**{field: value})
    found = [w for w in fs.validate() if w.code.startswith("text-")]
    assert [w.code for w in found] == [code]
    assert found[0].message.startswith(f"{named} ")


def test_a_company_name_that_wraps_past_the_strip_is_reported():
    """The one cell that answers a long value by growing, and so the one that
    can lose it downwards: every wrapped line is inside its own cell and the
    stack of them runs out through the top and the bottom of the block."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", company="Wollongong " * 12)
    fs.to_svg(border="zone")
    found = [w for w in fs.warnings if w.code == "title-block-company-overflows"]
    assert len(found) == 1
    assert "wraps to 12 lines" in found[0].message
    assert "units the strip is deep" in found[0].message


def test_a_company_name_the_strip_is_deep_enough_for_is_silent():
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", company="PANDID Engineering Pty Ltd")
    fs.to_svg(border="zone")
    assert not [w for w in fs.warnings if w.code.startswith("title-block-")]


@pytest.mark.parametrize("field", ["rev", "date", "description", "by", "checked", "approved"])
def test_every_revision_field_reports_a_value_it_cannot_hold(field):
    """The revision grid is six narrow columns and every one of them abbreviates
    -- a revision row is a history, and a history reads as prose."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", revisions=[Revision(**{field: "Wollongong " * 12})])
    found = [w for w in fs.validate() if w.code == "text-truncated"]
    # The grid cell, named for the field the author set. `rev` is drawn twice --
    # the grid column and the bottom band's REV cell, at two different widths --
    # and the second names its source, so the two are told apart by name.
    assert sum(w.message.startswith(f"revisions[0].{field} was ") for w in found) == 1
    if field == "rev":
        assert sum(w.message.startswith("revisions[0].rev -> rev was ") for w in found) == 1


# --- the cut is measured, not counted ----------------------------------------


@pytest.mark.parametrize("page", ["A4", "A3", "A2", "A1", "A0"])
def test_a_fullwidth_title_is_cut_to_a_width_and_not_to_a_count(page):
    """`clip` used to choose how many characters survive at the *Latin*
    advance while `text_width` -- which decided there was anything to cut --
    charges a fullwidth codepoint a full em. A CJK title kept 28 characters
    measuring 290 units for a 187-unit cell and was drawn straight through the
    sheet count beside it, at every page size."""
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
    # _TITLE_W already holds back the slot the sheet count is drawn in, so
    # fitting it is what keeps the two clear of each other.
    assert text_width(drawn, size, True) <= _TITLE_W


def test_a_latin_title_is_cut_exactly_where_it_always_was():
    """The measured cut has to agree with the counted one on the corpus the
    counted one was right for, or every shipped sheet moves."""
    fs = _sheet()
    fs.title_block = TitleBlock(title="Ethanol Purification and Dehydration Area A300")
    svg = fs.to_svg(border="zone")
    assert "Ethanol Purification and De…" in svg


# --- one thing to fix is one finding ------------------------------------------


def test_a_word_the_company_cell_cannot_break_is_reported_once():
    """The cell stacks its name over several lines, so a group of companies
    repeating one unbreakable word reported it once per line -- two findings
    about one edit."""
    word = "Wollongong-Warrawong-Woonona"
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", company=f"{word} {word}")
    found = [w for w in fs.validate() if w.code == "text-overruns-cell"]
    assert len(found) == 1
    assert word in found[0].message


def test_two_revisions_abbreviating_the_same_initials_are_two_findings():
    """Deduplication is on the whole finding, not on the text: these are two
    rows, and the author edits them separately."""
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


# --- the finding names the field that supplied the value ----------------------


def test_a_blank_title_reports_the_flowsheet_name_that_filled_it():
    """A block that states no title draws the flowsheet's name. Reported as
    `title`, it sent the author to a field they never set."""
    fs = _sheet(name="A Flowsheet Name Far Too Long For The Title Cell To Hold")
    fs.title_block = TitleBlock()
    found = [i for i in fs.validate() if i.code == "text-truncated"]
    assert len(found) == 1
    assert found[0].message.startswith("Flowsheet name -> title was truncated")


def test_a_backfilled_signatory_reports_the_block_field_that_supplied_it():
    """The same wrong-source defect `of_sheets` had: the value comes from
    `drawn_by` and the cell is the revision row's."""
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
    """The row is the more specific claim and keeps the cell -- which leaves the
    block-level value on no sheet at all, and that was silent."""
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
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", drawn_by="AA", revisions=[revision])
    svg = fs.to_svg(border="zone")
    assert ">AA</text>" in svg
    assert not [w for w in fs.warnings if w.code == "title-block-signatory-undrawn"]


# --- the cut is the arithmetic the width was measured by ----------------------


@pytest.mark.parametrize("bold", [False, True])
@pytest.mark.parametrize("size", [6.5, 7.5, 8.0, 9.0, 10.5, 11.0, 12.5])
def test_a_narrow_script_is_cut_by_the_shipped_arithmetic(size, bold):
    """`text_width` measures an all-narrow string with a closed form, and the
    cut is that form inverted -- the arithmetic every sheet this package has
    drawn was cut by.

    Repairing the fullwidth defect by walking *both* ends was the obvious fix
    and the wrong one: summing per-character widths lands a rounding away from
    the same characters measured whole, and seventy room/size pairs over this
    sweep cut a character earlier or later than they always had. `room=126` at
    7.5 was one of them -- 30 characters fit it exactly, and the walk kept 29.
    """
    from pandid.render.furniture import _ADV, _ADV_BOLD, clip

    per = size * (_ADV_BOLD if bold else _ADV)
    room = 1.0
    while room <= 300.0:
        drawn = clip("W" * 400, room, size, bold)
        assert len(drawn) - 1 == max(0, int(room / per) - 1), (room, size, bold)
        room = round(room + 0.5, 3)


@pytest.mark.parametrize("bold", [False, True])
@pytest.mark.parametrize("size", [6.5, 7.5, 8.0, 9.0, 10.5, 11.0, 12.5])
def test_a_wide_script_is_never_cut_wider_than_its_cell(size, bold):
    """The other half of the same guarantee: what a fullwidth cell keeps is a
    prefix `text_width` agrees fits, at every width the strip rules."""
    from pandid.render.furniture import clip, text_width

    room = 1.0
    while room <= 300.0:
        drawn = clip("Ｗ" * 400, room, size, bold)
        if room > text_width("…", size, bold):
            assert text_width(drawn, size, bold) <= room, (room, size, bold)
        room = round(room + 0.5, 3)


# --- the finding names the field that supplied the value, all five of them ----


def _fit_messages(**kw):
    fs = _sheet(name="A Flowsheet Name Far Too Long For The Title Cell To Hold")
    fs.title_block = TitleBlock(**kw)
    return [i.message for i in fs.validate() if i.code.startswith("text-")]


LONG = "Wollongong " * 12


@pytest.mark.parametrize(
    "kw,named",
    [
        # A blank field draws some other field's value, and the finding has to
        # name the field the author would edit rather than the cell.
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
    assert any(m.startswith(f"{named} ") for m in _fit_messages(**kw)), (named, _fit_messages(**kw))


def test_a_fitted_scale_is_not_reported_as_the_scale_field():
    """The scale cell draws the ratio the sheet was fitted at when the block
    states none, so a finding about it must not send the author to `scale`."""
    from pandid.render.furniture import title_strip_fit

    found = title_strip_fit(
        TitleBlock(title="Demo"), "Demo", "2026-01-01", fit_scale="1:" + "9" * 40
    )
    assert [f[0] for f in found] == ["the fitted scale -> scale"]


def test_a_stamped_date_is_not_reported_as_the_date_field():
    """And the date cell draws today's when the block states none."""
    from pandid.render.furniture import title_strip_fit

    found = title_strip_fit(TitleBlock(title="Demo"), "Demo", "2026-01-01" * 6)
    assert [f[0] for f in found] == ["today's date -> date"]


# --- a field of nothing but spaces is the blank it means -----------------------


@pytest.mark.parametrize(
    "field",
    ["title", "subtitle", "drawing_number", "project", "client", "company", "status", "scale"],
)
def test_a_whitespace_field_draws_what_an_unset_one_draws(field):
    """A field of only spaces is *truthy*, so it defeated every fallback the
    block has: the title lost the flowsheet's name, the status and the drawing
    number lost their dash, a whitespace client ruled an empty row and made the
    whole strip taller, and a whitespace scale turned the four-cell bottom band
    on with nothing to put in it."""

    def draw(**kw):
        fs = _sheet(name="Ethanol Purification A300")
        fs.title_block = TitleBlock(**kw)
        return fs.to_svg(border="zone", page_size="A3")

    base = {} if field == "title" else {"title": "Demo"}
    assert draw(**base) == draw(**{**base, field: "   "})


def test_a_whitespace_field_set_after_the_block_is_built_is_also_blank():
    """`fs.title_block.title = ...` is the documented way to shorten a field and
    re-render, so normalising on the dataclass would have missed it."""
    fs = _sheet(name="Ethanol Purification A300")
    fs.title_block = TitleBlock(title="Demo")
    fs.title_block.title = "  \t "
    svg = fs.to_svg(border="zone", page_size="A3")
    assert ">Ethanol Purification A300</text>" in svg


def test_a_whitespace_revision_field_is_the_blank_it_means():
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
    """A date of nothing but spaces is the blank it means -- and the blank it
    means is today's date, not an empty cell. The fallback used to be chosen by
    the renderer, on the raw value, so whitespace passed it and then normalised
    to nothing with the day it should have fallen back to already discarded."""
    import datetime

    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", date=stated)
    svg = fs.to_svg(border="zone", page_size="A3")
    cell = re.search(r'fill="#666">DATE</text>\s*<text[^>]*fill="black">([^<]*)</text>', svg)
    assert cell is not None, "the sheet ruled no DATE cell"
    assert cell.group(1) == datetime.datetime.now().strftime("%Y-%m-%d")


def test_a_stated_date_still_wins_the_cell():
    fs = _sheet()
    fs.title_block = TitleBlock(title="Demo", date="2026-01-02")
    svg = fs.to_svg(border="zone", page_size="A3")
    cell = re.search(r'fill="#666">DATE</text>\s*<text[^>]*fill="black">([^<]*)</text>', svg)
    assert cell is not None and cell.group(1) == "2026-01-02"


def test_a_whitespace_title_is_a_truncation_validate_reports():
    """The render draws the flowsheet's name in place of a title of spaces, and
    abbreviates it -- so validate() has to say so too. It did not: it chose the
    fallback itself, on the raw value, and a truthy `"   "` won."""
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


#: unset, whitespace, and stated-but-unfittable, over every field of the block.
_SEAM = [{f: v} for f in _FIELD_NAMES for v in ("   ", "\t \n ", _LONG)] + [
    {},
    {"title": "   ", "date": "  "},
    {"revisions": [Revision("   ", "   ", "   ", "   ")]},
    {"title": "   ", "drawn_by": _LONG, "revisions": [Revision("0", "2026-01-01", "Issued")]},
]


@pytest.mark.parametrize("kw", _SEAM, ids=lambda k: "+".join(k) or "unset")
@pytest.mark.parametrize(
    "name",
    ["Ethanol Purification A300", "A Flowsheet Name Far Too Long For The Title Cell To Hold"],
)
def test_validate_reports_exactly_what_the_sheet_reports(kw, name):
    """The guarantee the whole finding rests on: what `validate()` says before a
    render is what the sheet says after one. Both defects this test was written
    for were a fallback chosen by the caller rather than by the strip, so the
    two answered different questions about the same block."""
    ahead = _sheet(name=name)
    ahead.title_block = TitleBlock(**kw)
    predicted = sorted(
        i.message for i in ahead.validate() if i.code.startswith(("text-", "title-block"))
    )
    drawn = _sheet(name=name)
    drawn.title_block = TitleBlock(**kw)
    drawn.to_svg(border="zone")
    assert predicted == sorted(
        w.message for w in drawn.warnings if w.code.startswith(("text-", "title-block"))
    )
