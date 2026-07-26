"""P&ID title block + revision history rendering."""

import re

import pytest

from pfd import Flowsheet, units as U
from pfd.document import TitleBlock, Revision


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
    from pfd.document import equipment_list, notes

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
    assert build().to_svg(styling="pid") == zoned  # the older spelling
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
        {"styling": "isometric"},
        {"border": "ruled"},
        {"styling": "pid", "border": "none"},
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
    from pfd.render.furniture import measure_title_strip

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
    svg = fs.to_svg(styling="pid")
    for token in ("PFD-9", "2 of 4", "AA", "BB", "CC", "REV", "DESCRIPTION", "Issued"):
        assert token in svg, token


def test_no_title_block_still_renders_pid():
    fs = Flowsheet("Bare")
    fs.add(U.Feed("F"))
    fs.add(U.Product("P"))
    fs.connect(fs.units[0].outlet, fs.units[1].inlet)
    svg = fs.to_svg(styling="pid")  # falls back to defaults, must not raise
    assert "Bare" in svg


def test_title_block_fits_narrow_sheet():
    import re
    from pfd.render.furniture import measure_title_strip

    fs = Flowsheet("Tiny")
    a = fs.add(U.Feed("F"))
    b = fs.add(U.Product("P"))
    fs.connect(a.outlet, b.inlet)
    fs.title_block = TitleBlock(drawing_number="PFD-1")
    svg = fs.to_svg(styling="pid")
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
    from pfd.document import equipment_list, notes, legend

    fs = Flowsheet("Furnished")
    feed = fs.add(U.Feed("Crude", reference="PFD-000"))
    col = fs.add(U.Column("T-101", description="Main Column"))
    prod = fs.add(U.Product("Top", reference="PFD-002"))
    fs.connect(feed.outlet, col.feed)
    fs.connect(col.distillate, prod.inlet)
    fs.add_annotation(equipment_list(fs))
    fs.add_annotation(notes(["First note", "Second note"]))
    fs.add_annotation(legend({"SS": "Stainless Steel"}))
    svg = fs.to_svg(styling="pid")
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


def test_align_nine_point_and_anchor_alias():
    import pytest
    from pfd.document import Annotation

    assert Annotation(align="top").align == "top"
    assert Annotation(align="center").align == "center"
    # `anchor=` is the deprecated alias for `align=`
    assert Annotation(anchor="bottom-left").align == "bottom-left"
    with pytest.raises(ValueError):
        Annotation(align="middle-ish")


def test_annotation_docks_flush_to_frame():
    import re
    from pfd.document import Annotation

    fs = Flowsheet("Flush")
    a = fs.add(U.Feed("F"))
    b = fs.add(U.Product("P"))
    fs.connect(a.outlet, b.inlet)
    fs.add_annotation(Annotation(title="BOX", rows=["row"], align="top-right"))
    svg = fs.to_svg(styling="pid")
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
    from pfd.document import Annotation

    fs = Flowsheet("Placed")
    a = fs.add(U.Feed("F"))
    b = fs.add(U.Product("P"))
    fs.connect(a.outlet, b.inlet)
    fs.add_annotation(Annotation(title="HOLD", rows=["x"], position=(500, 120)))
    svg = fs.to_svg(styling="pid")
    # top-left corner drawn exactly at the requested absolute coordinates
    assert re.search(r'<rect x="500.0" y="120.0" [^>]*stroke-width="1.5"/>', svg)


def test_stream_table_section_header():
    fs = Flowsheet("Tabled")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet)
    s.properties = {"Temperature": "25 C", "Ethanol": "0.9"}
    fs.stream_table_sections = [("Ethanol", "Mass Fraction")]
    svg = fs.to_svg(styling="pid", show_stream_table=True)
    assert "Mass Fraction" in svg
    assert "Stream Number" in svg
