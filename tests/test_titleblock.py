"""P&ID title block + revision history rendering."""

import re

import pytest

from pandid import Flowsheet, units as U
from pandid.document import TitleBlock, Revision


def _sheet(name="Demo", span=0.0):
    fs = Flowsheet(name)
    a = fs.add(U.Feed("F")).pin(x=60, y=105)
    b = fs.add(U.Product("P")).pin(x=260 + span, y=105)
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
    fs.connect(col.distillate, prod.inlet)
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


# --- a column has to have something in it -------------------------------------
#
# ISO 10628-1:2014 4.3.3 a) lists the flows *between the process steps* among
# the things a process flow diagram "can also contain", so an internal column
# with nothing in it is a heading over a rule of dashes and is dropped. 4.3.2 d)
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
    incoming one. Only the first segment's *values* are tabulated, which is
    why every shipped example writes a run's properties on each of its
    segments."""
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
    fs = _sheet()
    fs.title_block = TitleBlock(drawing_number="PFD-1", title="Ethanol Purification A300")
    svg = fs.to_svg(page_size="A3", border="zone")
    assert "Ethanol Purification A3…" in svg  # the strip cannot grow: it abbreviates
    cut = [w for w in fs.warnings if w.code == "text-truncated"]
    assert cut, "an abbreviated title must not be silent"
    assert len(cut) == 1 and "title" in cut[0].message
    assert "Ethanol Purification A300" in cut[0].message


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
    fs.title_block = TitleBlock(title="Ethanol Purification A300")
    fs.to_svg(border="zone")
    assert [w for w in fs.warnings if w.code == "text-truncated"]
    fs.title_block.title = "Ethanol A300"
    fs.to_svg(border="zone")
    assert not [w for w in fs.warnings if w.code == "text-truncated"]
