"""The stream table drawn as a sheet of its own (#481).

``show_stream_table="sheet"`` renders a full drawing whose body is the
stream table: a zone border, a title strip with a drawing number of its
own, and the table wrapped into stacked blocks when the streams do not
fit across the page. What is checked here is the drawing -- which blocks
carry which streams, that each is headed, and that everything lands
inside the frame -- rather than the strings the renderer happens to
emit.
"""

import importlib.util
import re
import xml.etree.ElementTree as ET
from typing import Any, cast

import pytest

from pandid import Flowsheet, units as U
from pandid.document import Revision, TitleBlock
from pandid.render import furniture as F
from pandid.render.svg import _page, table_sheet_plan

_HAS_PDF_EXTRA = all(
    importlib.util.find_spec(m) is not None for m in ("svglib", "reportlab", "pypdfium2", "PIL")
)


def _sheet(streams: int = 21, rows: int = 4) -> Flowsheet:
    """A flowsheet with *streams* tabulated runs, each carrying *rows*
    properties, drawn as a feed into a product apiece.

    Straight lines and no equipment: this file is about the table sheet,
    which draws no diagram at all, so what the diagram would have looked
    like is nobody's business here.
    """
    fs = Flowsheet("Aromatics Recovery A100")
    fs.title_block = TitleBlock(
        title="Aromatics Recovery A100",
        subtitle="Process Flow Diagram 1",
        drawing_number="PFD-1001",
        company="Pandid",
        revisions=[Revision("A", "2026-01-01", "Issued for review", "AA")],
    )
    fs.stream_table_sections = [("Benzene", "Mass Fraction")]
    for i in range(streams):
        feed = fs.add(U.Feed(f"F{i}")).pin(x=100, y=100 + 80 * i)
        product = fs.add(U.Product(f"P{i}")).pin(x=320, y=100 + 80 * i)
        stream = fs.connect(feed.outlet, product.inlet)
        values = {
            "Temperature (C)": f"{25 + i} C",
            "Pressure (bar)": f"{1 + i / 10:.1f} bar",
            "Total Flow (kg/h)": f"{1000 - 10 * i}",
            "Benzene": f"{0.9 - i / 100:.2f}",
        }
        stream.properties = dict(list(values.items())[:rows])
    return fs


def _blocks(svg: str) -> list[str]:
    """Each stream-table block of a rendered sheet, as its own markup."""
    return re.findall(r'<g id="stream_table_\d+">.*?</g>', svg, re.S)


def _cells(block: str) -> list[tuple[float, float, float, float]]:
    """Every ruled cell of a block, as ``(x, y, w, h)``."""
    return [
        (float(m[0]), float(m[1]), float(m[2]), float(m[3]))
        for m in re.findall(
            r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)"', block
        )
    ]


def _texts(block: str) -> list[str]:
    return re.findall(r"<text[^>]*>([^<]*)</text>", block)


def _zone_letters(svg: str) -> list[str]:
    """The row letters ruled in the border band, which is the one thing on a
    table sheet lettered at the zone size. Every row is lettered twice, on the
    left band and the right, so every second one is the row list."""
    return re.findall(r'<text[^>]*font-size="9.0"[^>]*>([A-Z])</text>', svg)[::2]


# --- the sheet is a drawing in its own right ---------------------------------


def test_the_table_sheet_carries_a_border_a_title_block_and_a_drawing_number():
    svg = _sheet().to_svg(show_stream_table="sheet", page_size="A3")
    # The zone border: the frame, and the letters ruled in the band.
    assert 'stroke-width="2"' in svg
    assert _zone_letters(svg)[:3] == ["A", "B", "C"]
    # The strip, saying which drawing this is and which sheet of it.
    assert "Aromatics Recovery A100" in svg  # the diagram's own title, kept
    assert "Stream Table" in svg  # what this sheet is
    assert "PFD-1001-ST" in svg  # a number of its own, derived
    assert "DRAWING No" in svg and "REV" in svg and "Issued for review" in svg


def test_no_diagram_is_drawn_on_it():
    """The point of the sheet: the flowsheet's equipment is *not* on it."""
    svg = _sheet(streams=3).to_svg(show_stream_table="sheet", page_size="A3")
    assert 'id="drawing"' not in svg and "<defs>" not in svg
    for tag in ("F0", "P0", "F1", "P1"):
        assert f">{tag}</text>" not in svg


def test_the_diagram_sheet_is_untouched_by_the_option():
    """``True`` still means the table under the drawing, and the sheet that
    comes out of it is the sheet that always did."""
    fs = _sheet(streams=3)
    docked = fs.to_svg(show_stream_table=True, page_size="A3", border="zone")
    assert ">F0</text>" in docked  # the diagram is drawn
    assert len(_blocks(docked)) == 0 and '<g id="stream_table">' in docked


def test_a_table_sheet_rules_the_zone_border_without_being_asked():
    """It is a formal drawing rather than a table on paper. Stated
    ``border`` still decides."""
    fs = _sheet(streams=3)
    assert _zone_letters(fs.to_svg(show_stream_table="sheet", page_size="A3"))
    plain = fs.to_svg(show_stream_table="sheet", page_size="A3", border="none")
    assert not _zone_letters(plain)
    assert "PFD-1001-ST" in plain  # the strip is drawn either way


def test_the_document_is_named_for_the_sheet_it_is():
    """Two sheets of one drawing set are two documents. Left at the drawing's
    title alone, the table sheet answered to the diagram's accessible name."""
    fs = _sheet(streams=3)
    assert "<title>Aromatics Recovery A100</title>" in fs.to_svg(page_size="A3")
    assert "<title>Aromatics Recovery A100 - Stream Table</title>" in fs.to_svg(
        show_stream_table="sheet", page_size="A3"
    )


# --- the sheet's own identity ------------------------------------------------


def test_the_drawing_number_is_derived_and_can_be_stated():
    fs = _sheet(streams=3)
    assert "PFD-1001-ST" in fs.to_svg(show_stream_table="sheet", page_size="A3")
    fs.stream_table.sheet_drawing_number = "PFD-1003"
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert "PFD-1003" in svg and "PFD-1001-ST" not in svg


def test_what_the_sheet_is_called_can_be_stated():
    fs = _sheet(streams=3)
    fs.stream_table.sheet_subtitle = "Stream Summary"
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert "Stream Summary" in svg and ">Stream Table</text>" not in svg


def test_the_rest_of_the_title_block_is_the_diagram_s():
    """Same issue, same office, same day: only the two cells that say which
    drawing this is are re-written."""
    fs = _sheet(streams=3)
    fs.title_block = TitleBlock(
        title="Aromatics Recovery A100",
        subtitle="Process Flow Diagram 1",
        drawing_number="PFD-1001",
        client="Aromatics Australia Pty Ltd",
        status="ISSUED FOR REVIEW",
        date="2026-02-03",
    )
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    for token in ("Aromatics Australia Pty Ltd", "ISSUED FOR REVIEW", "2026-02-03"):
        assert token in svg, token
    assert "Process Flow Diagram 1" not in svg  # the diagram's subtitle is not this sheet's


def test_a_flowsheet_with_no_title_block_still_gets_a_sheet_that_can_be_filed():
    fs = _sheet(streams=3)
    fs.title_block = None
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert "Stream Table" in svg and "DRAWING No" in svg
    assert "Aromatics Recovery A100" in svg  # the flowsheet's name, as the strip falls back to


def test_a_table_sheet_states_no_scale():
    """A table is not drawn to scale, so the cell is not ruled at all -- unlike
    a fitted diagram, which reports the ratio it was placed at."""
    fs = _sheet(streams=3)
    assert "SCALE" in fs.to_svg(page_size="A3", border="zone")
    assert "SCALE" not in fs.to_svg(show_stream_table="sheet", page_size="A3")


# --- wrapping ----------------------------------------------------------------


def test_more_streams_than_fit_wrap_into_stacked_blocks():
    svg = _sheet(streams=21).to_svg(show_stream_table="sheet", page_size="A4")
    blocks = _blocks(svg)
    assert len(blocks) > 1, "21 streams do not fit across an A4 sheet"
    # Stacked, not laid side by side: every block starts at the same x and
    # each begins below the one before it.
    tops = []
    for block in blocks:
        cells = _cells(block)
        tops.append(min(y for _x, y, _w, _h in cells))
        assert min(x for x, _y, _w, _h in cells) == min(x for x, _y, _w, _h in _cells(blocks[0]))
    assert tops == sorted(tops) and len(set(tops)) == len(tops)


def test_every_block_repeats_the_heading_row():
    svg = _sheet(streams=21).to_svg(show_stream_table="sheet", page_size="A4")
    blocks = _blocks(svg)
    assert len(blocks) > 1
    for i, block in enumerate(blocks):
        texts = _texts(block)
        assert texts[0] == "Stream Number", f"block {i} is not headed"
        # And the section heading, which heads a group of rows in each block
        # for the same reason.
        assert "Mass Fraction" in texts, f"block {i} lost its section heading"


def test_every_stream_appears_once_and_in_order():
    fs = _sheet(streams=21)
    names = [run[0].name for run in fs._named_runs().values()]
    svg = fs.to_svg(show_stream_table="sheet", page_size="A4")
    drawn: list[str] = []
    for block in _blocks(svg):
        drawn.extend(t for t in _texts(block) if t in names)
    assert drawn == names


def test_how_many_streams_a_block_holds_comes_from_the_page():
    """Not from a constant: the same table wraps into more blocks on smaller
    paper and into one on paper wide enough for it."""

    def blocks(page: str) -> int:
        return len(_blocks(_sheet(streams=21).to_svg(show_stream_table="sheet", page_size=page)))

    assert blocks("A4") > blocks("A3") >= blocks("A2") == 1


def test_the_blocks_are_evened_out_rather_than_filled_and_left_a_stub():
    """Twenty-one streams that fit twelve across come out eleven and ten. A
    block of nine beside a block of twelve reads as an afterthought."""
    table = F.stream_table_sheet(_sheet(streams=21), 900.0)
    assert table is not None
    counts = [len(block.rows[0]) - 1 for block in table.blocks]
    assert len(counts) > 1 and max(counts) - min(counts) <= 1


def test_one_ruling_answers_for_every_block():
    """A stream table is read down for one stream and across for one property.
    Blocks ruled to different widths would not line up under one another."""
    table = F.stream_table_sheet(_sheet(streams=21), 900.0)
    assert table is not None
    for block in table.blocks:
        assert block.size == table.blocks[0].size
        assert block.row_h == table.blocks[0].row_h
        assert [c.w for c in block.rows[0]] == [c.w for c in table.blocks[0].rows[0]][
            : len(block.rows[0])
        ]


def test_a_block_is_not_shrunk_to_fit_when_it_can_wrap_instead():
    """The docked table trades type size for width above eighteen columns,
    because it has one row of columns and no other way to make room. A table
    sheet makes room by wrapping, so it stays at the reading size."""
    fs = _sheet(streams=21)
    docked = F.stream_table_layout(fs)
    wrapped = F.stream_table_sheet(fs, 900.0)
    assert docked is not None and wrapped is not None
    assert docked.size < F._BASE_SIZE  # 21 columns: shrunk
    assert wrapped.blocks[0].size == F._BASE_SIZE


def test_a_stated_font_size_still_rules_the_table_sheet():
    """The author overruling the reading size, which is how a table too deep
    for its page is brought back onto it: smaller type buys columns per block,
    and columns per block cost blocks."""
    fs = _sheet(streams=21)
    ruled = F.stream_table_sheet(fs, 700.0)
    fs.stream_table.font_size = 7.0
    smaller = F.stream_table_sheet(fs, 700.0)
    assert ruled is not None and smaller is not None
    assert smaller.blocks[0].size == 7.0
    assert len(smaller.blocks) < len(ruled.blocks)
    assert smaller.h < ruled.h


def test_a_sheet_with_no_page_takes_the_table_in_one_block():
    """There is no width to wrap against, so the frame grows to the table --
    which is what a sheet sized to its contents does everywhere else."""
    svg = _sheet(streams=21).to_svg(show_stream_table="sheet")
    assert len(_blocks(svg)) == 1


# --- everything lands on the paper -------------------------------------------


def _viewbox(svg: str) -> tuple[float, float, float, float]:
    m = re.search(r'viewBox="([-\d. ]+)"', svg)
    assert m
    x, y, w, h = (float(v) for v in m.group(1).split())
    return x, y, w, h


@pytest.mark.parametrize("page", ["A4", "A3", "A2", "A1", None])
@pytest.mark.parametrize("streams", [1, 8, 21])
def test_every_cell_is_drawn_inside_the_sheet(page, streams):
    fs = _sheet(streams=streams)
    svg = fs.to_svg(show_stream_table="sheet", page_size=page)
    vx, vy, vw, vh = _viewbox(svg)
    for block in _blocks(svg):
        for x, y, w, h in _cells(block):
            assert vx <= x and x + w <= vx + vw, f"a cell runs off the side of an {page} sheet"
            assert vy <= y and y + h <= vy + vh, f"a cell runs off the end of an {page} sheet"


def test_the_table_does_not_run_into_the_title_strip():
    fs = _sheet(streams=21, rows=4)
    plan = table_sheet_plan(fs, _page("A4"))
    strip_top = plan.strip[1]
    assert plan.top + plan.table.h <= strip_top


def test_the_stack_is_centred_across_the_page_and_flush_with_its_top():
    plan = table_sheet_plan(_sheet(streams=21), _page("A3"))
    page = _page("A3")
    assert page is not None
    left_gap = plan.left
    right_gap = page.width - (plan.left + plan.table.w)
    assert abs(left_gap - right_gap) < 1.0
    # Blocks are flush left with one another, whatever their own widths.
    lefts = [x for _i, _b, x, _y in plan.table.at(plan.left, plan.top)]
    assert len(set(lefts)) == 1


# --- what it refuses ---------------------------------------------------------


def test_a_page_too_small_for_the_table_says_which_furniture_will_not_fit():
    """Wrapping answers width. Depth is what a page can still run out of, and
    the error names the piece rather than saying the furniture does not fit."""
    fs = _sheet(streams=6)
    for run in fs._named_runs().values():
        run[0].properties = {f"Component {n}": f"{n / 100:.2f}" for n in range(40)}
    with pytest.raises(ValueError, match="stream table"):
        fs.to_svg(show_stream_table="sheet", page_size="A4")
    # The same table on the next size up comes out, so what was reported was
    # the page rather than the table.
    assert _blocks(fs.to_svg(show_stream_table="sheet", page_size="A2"))


def test_a_flowsheet_with_nothing_to_tabulate_is_refused():
    """The file asked for is a sheet whose whole body is the table."""
    fs = Flowsheet("bare")
    pump = fs.add(U.Pump("P-101")).pin(x=100, y=100)
    tank = fs.add(U.Tank("T-101")).pin(x=300, y=100)
    fs.connect(pump.discharge, tank.inlet)
    with pytest.raises(ValueError, match="nothing to tabulate"):
        fs.to_svg(show_stream_table="sheet", page_size="A3")


def test_a_spelling_neither_backend_knows_is_refused():
    """Read as truthy, ``show_stream_table="own sheet"`` drew the whole table
    onto the diagram. The annotation refuses it at the desk -- which is what
    the cast here is stepping around -- and the renderer refuses it at run
    time, for the author who typed it into a config file instead."""
    fs = _sheet(streams=3)
    for value in ("own sheet", "Sheet", "table"):
        with pytest.raises(ValueError, match="show_stream_table"):
            fs.to_svg(show_stream_table=cast(Any, value), page_size="A3")


def test_the_coordinate_overlay_is_refused_rather_than_drawn_over_nothing():
    fs = _sheet(streams=3)
    with pytest.raises(ValueError, match="debug"):
        fs.to_svg(show_stream_table="sheet", page_size="A3", debug=True)


# --- the other output paths --------------------------------------------------


def test_the_drawio_export_draws_the_same_sheet():
    fs = _sheet(streams=21)
    xml = fs.to_drawio(show_stream_table="sheet", page_size="A4")
    root = ET.fromstring(xml)
    cells = list(root.iter("mxCell"))
    tables = [c for c in cells if "shape=table;" in (c.get("style") or "")]
    # One editable table per block, plus the strip's revision grid.
    blocks = len(_blocks(fs.to_svg(show_stream_table="sheet", page_size="A4")))
    assert len(tables) == blocks + 1
    text = "".join(c.get("value") or "" for c in cells)
    assert text.count("Stream Number") == blocks
    assert "PFD-1001-ST" in text
    # And no diagram: the equipment is not exported either.
    assert "F0" not in text and "P0" not in text


def test_the_drawio_export_opens_on_the_same_paper():
    fs = _sheet(streams=21)
    model = ET.fromstring(fs.to_drawio(show_stream_table="sheet", page_size="A4")).find(
        "diagram/mxGraphModel"
    )
    page = _page("A4")
    assert model is not None and page is not None
    assert model.get("page") == "1"
    assert float(model.get("pageWidth") or 0) == pytest.approx(page.width, abs=0.01)


def test_render_writes_the_table_sheet_to_whatever_the_extension_asks_for(tmp_path):
    fs = _sheet(streams=21)
    out = tmp_path / "stream_table.svg"
    fs.render(out, show_stream_table="sheet", page_size="A4")
    assert out.read_text(encoding="utf-8") == fs.to_svg(show_stream_table="sheet", page_size="A4")
    model = tmp_path / "stream_table.drawio"
    fs.render(model, show_stream_table="sheet", page_size="A4")
    assert model.read_text(encoding="utf-8") == fs.to_drawio(
        show_stream_table="sheet", page_size="A4"
    )


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
@pytest.mark.parametrize("ext", [".pdf", ".png"])
def test_the_raster_paths_produce_the_table_sheet_too(tmp_path, ext):
    out = tmp_path / f"stream_table{ext}"
    _sheet(streams=21).render(out, show_stream_table="sheet", page_size="A4")
    assert out.stat().st_size > 1000


def test_the_option_reaches_the_drafting_call(monkeypatch):
    """``show()`` is ``render()`` without the path, and a table sheet is a
    sheet an author previews like any other."""
    from pandid.render import preview as P

    seen: dict = {}

    def fake(svg: str, *, title: str = "") -> str:
        seen["svg"] = svg
        return "window"

    monkeypatch.setattr(P, "preview", fake)
    fs = _sheet(streams=21)
    fs.show(show_stream_table="sheet", page_size="A4")
    assert seen["svg"] == _sheet(streams=21).to_svg(show_stream_table="sheet", page_size="A4")


# --- one number apiece -------------------------------------------------------


def test_a_table_sheet_numbered_as_its_diagram_is_refused():
    """The suffix guarantees two numbers only while nobody overrules it. Stated
    outright, the collision the derivation exists to prevent is typed in by
    hand, and there is no reading of it that produces a filable set."""
    fs = _sheet(streams=3)
    fs.stream_table.sheet_drawing_number = "PFD-1001"
    with pytest.raises(ValueError, match="the diagram's own drawing number"):
        fs.to_svg(show_stream_table="sheet", page_size="A3")


@pytest.mark.parametrize("stated", ["pfd-1001", "  PFD-1001 "])
def test_one_number_said_a_different_way_is_still_the_same_number(stated):
    """A drawing register does not file 'PFD-301' and 'pfd-301 ' as two
    drawings, and neither does the person looking for one."""
    fs = _sheet(streams=3)
    fs.stream_table.sheet_drawing_number = stated
    with pytest.raises(ValueError, match="the diagram's own drawing number"):
        fs.to_svg(show_stream_table="sheet", page_size="A3")


def test_a_number_of_its_own_is_accepted():
    fs = _sheet(streams=3)
    fs.stream_table.sheet_drawing_number = "PFD-1003"
    assert "PFD-1003" in fs.to_svg(show_stream_table="sheet", page_size="A3")


def _unnumbered(fs) -> list:
    return [w for w in fs.warnings if w.code == "table-sheet-unnumbered"]


def test_a_table_sheet_with_no_number_to_derive_says_so():
    """Drawn, not refused: a flowsheet is not obliged to carry a title block
    anywhere else in this library. But an unnumbered sheet is the sheet's own
    identity missing, so it is a finding rather than a silence."""
    fs = _sheet(streams=3)
    fs.title_block = None
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert _blocks(svg), "the sheet is still drawn"
    found = _unnumbered(fs)
    assert len(found) == 1
    assert "drawing number" in found[0].message
    assert found[0].severity == "warning"


def test_a_title_block_carrying_no_number_says_so_too():
    """The finding is about the number, not about the block: a title block with
    every other cell filled in still leaves the sheet unfiled."""
    fs = _sheet(streams=3)
    fs.title_block = TitleBlock(title="Aromatics Recovery A100", company="Pandid")
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert _unnumbered(fs)


def test_numbering_it_either_way_silences_the_finding():
    fs = _sheet(streams=3)
    fs.title_block = None
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert _unnumbered(fs)
    # The same render again, with the table sheet numbered on its own: the
    # stale finding goes with it rather than accumulating.
    fs.stream_table.sheet_drawing_number = "PFD-1003"
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert not _unnumbered(fs)


def test_the_diagram_sheet_is_never_unnumbered_by_this():
    """The finding belongs to the table sheet. A diagram with no title block is
    a drawing this library has always been happy to make."""
    fs = _sheet(streams=3)
    fs.title_block = None
    fs.to_svg(page_size="A3", border="zone")
    assert not _unnumbered(fs)


def test_the_drawio_export_reports_it_in_the_same_words():
    fs = _sheet(streams=3)
    fs.title_block = None
    fs.to_drawio(show_stream_table="sheet", page_size="A3")
    exported = _unnumbered(fs)
    other = _sheet(streams=3)
    other.title_block = None
    other.to_svg(show_stream_table="sheet", page_size="A3")
    assert exported, "the export has to find it too, not merely agree about nothing"
    assert [w.message for w in exported] == [w.message for w in _unnumbered(other)]


# --- a refused render has not drawn half a sheet -----------------------------


def _unresolved(fs) -> bool:
    """Nothing has been laid out or routed on this flowsheet."""
    return all(u.frame is None for u in fs.units) and all(s.route is None for s in fs.streams)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"show_stream_table": "own sheet"},
        {"show_stream_table": "sheet", "page_size": "A9"},
        {"show_stream_table": "sheet", "page_size": "A4", "debug": True},
        {"show_stream_table": "sheet", "page_size": "A3", "jump_direction": "sideways"},
        {"show_stream_table": "sheet", "page_size": "A3", "connections": "welded"},
        {"show_stream_table": "sheet", "page_size": "A3", "border": "hatched"},
        {"jump_direction": "sideways"},
        {"connections": "welded"},
    ],
)
def test_a_render_that_cannot_happen_has_not_happened_halfway(kwargs):
    """Laying a sheet out and routing it writes a Frame onto every unit and a
    Route onto every stream. A render that raises after that has changed the
    flowsheet on its way to failing, and the geometry the author's *next*
    render reuses was resolved for the call that did not produce a file."""
    fs = _sheet(streams=3)
    assert _unresolved(fs), "the fixture must not lay itself out"
    with pytest.raises(ValueError):
        fs.to_svg(**cast(Any, kwargs))
    assert _unresolved(fs), "a refused render left the flowsheet laid out"


def test_the_table_sheet_s_own_refusals_come_before_the_geometry():
    """Nothing to tabulate, and a page too small for the table: both are facts
    about the model and the paper, so neither needs a sheet laid out to find."""
    bare = Flowsheet("bare")
    pump = bare.add(U.Pump("P-101")).pin(x=100, y=100)
    tank = bare.add(U.Tank("T-101")).pin(x=300, y=100)
    bare.connect(pump.discharge, tank.inlet)
    with pytest.raises(ValueError, match="nothing to tabulate"):
        bare.to_svg(show_stream_table="sheet", page_size="A3")
    assert _unresolved(bare)

    deep = _sheet(streams=6)
    for run in deep._named_runs().values():
        run[0].properties = {f"Component {n}": f"{n / 100:.2f}" for n in range(40)}
    with pytest.raises(ValueError, match="stream table"):
        deep.to_svg(show_stream_table="sheet", page_size="A4")
    assert _unresolved(deep)


def test_a_duplicate_number_is_refused_before_the_geometry():
    fs = _sheet(streams=3)
    fs.stream_table.sheet_drawing_number = "PFD-1001"
    with pytest.raises(ValueError, match="drawing number"):
        fs.to_drawio(show_stream_table="sheet", page_size="A3")
    assert _unresolved(fs)


# --- an option that applies to nothing is still an option --------------------


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"jump_direction": "sideways"}, "jump_direction"),
        ({"connections": "welded"}, "connections"),
    ],
)
@pytest.mark.parametrize("table", [False, True, "sheet"])
def test_an_unknown_sheet_option_is_refused_whatever_the_sheet_holds(kwargs, match, table):
    """The hole this closes: ``jump_direction`` is read where the hops are
    *drawn*, as ``== "vertical"``, so a misspelling matched neither branch and
    the sheet came out with no hops and no complaint. A table sheet draws no
    process line at all, which made it the sheet where every such option was
    swallowed."""
    fs = _sheet(streams=3)
    for render in (fs.to_svg, fs.to_drawio):
        with pytest.raises(ValueError, match=match):
            render(show_stream_table=cast(Any, table), page_size="A3", **cast(Any, kwargs))


def test_a_valid_option_this_sheet_cannot_show_is_still_accepted():
    """The distinction being drawn: ``connections`` on a sheet with no joints to
    mark is a well-formed request this drawing has no answer to, and a PFD has
    always accepted it and marked nothing."""
    fs = _sheet(streams=3)
    assert fs.to_svg(show_stream_table="sheet", page_size="A3", connections="flanged")
    assert fs.to_svg(show_stream_table="sheet", page_size="A3", jump_direction="horizontal")


# --- one ruling, page or no page ---------------------------------------------


def test_the_ruling_does_not_depend_on_whether_a_page_was_named():
    """A sheet grown to its contents does not wrap -- there is no width to wrap
    against -- but it is lettered and ruled as the paged sheet is. Sized off the
    column count instead, the same twenty-one streams came out at 9.05 unpaged
    and 10.5 on A2: two drawings of one table, differing for a reason nothing on
    either sheet shows."""
    fs = _sheet(streams=21)
    unpaged = F.stream_table_sheet(fs, None)
    paged = F.stream_table_sheet(fs, 4000.0)
    assert unpaged is not None and paged is not None
    assert len(unpaged.blocks) == len(paged.blocks) == 1
    assert unpaged.blocks[0].size == paged.blocks[0].size == F._BASE_SIZE
    assert unpaged.blocks[0].row_h == paged.blocks[0].row_h
    assert unpaged.w == paged.w and unpaged.h == paged.h


def test_the_unpaged_sheet_is_the_paged_one_with_the_cutting_left_out():
    """Down to the drawn cells: one block of the wrapped sheet is ruled exactly
    as the unpaged sheet's single block is."""
    fs = _sheet(streams=21)
    unpaged = F.stream_table_sheet(fs, None)
    wrapped = F.stream_table_sheet(fs, 900.0)
    assert unpaged is not None and wrapped is not None
    assert len(wrapped.blocks) > 1
    assert wrapped.blocks[0].size == unpaged.blocks[0].size
    assert wrapped.blocks[0].row_h == unpaged.blocks[0].row_h
    # Same label column and same stream column, cut into fewer of them.
    assert wrapped.blocks[0].rows[0][0].w == unpaged.blocks[0].rows[0][0].w
    assert wrapped.blocks[0].rows[0][1].w == unpaged.blocks[0].rows[0][1].w
