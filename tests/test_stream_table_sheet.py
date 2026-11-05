"""Check stream-table sheets, their exports, and failed-render rollback."""

import importlib.util
import inspect
import pickle
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast

import pytest

from pandid import Flowsheet, Pin, units as U
from pandid.document import Revision, TitleBlock
from pandid.render import furniture as F
from pandid.render.drawio import DrawioRenderer
from pandid.render.svg import SvgRenderer, _page, table_sheet_plan

_HAS_PDF_EXTRA = all(
    importlib.util.find_spec(m) is not None for m in ("svglib", "reportlab", "pypdfium2", "PIL")
)


def _sheet(streams: int = 21, rows: int = 4) -> Flowsheet:
    """Create a flowsheet with tabulated feed-to-product streams."""
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
    """Extract stream-table block markup from an SVG export."""
    return re.findall(r'<g id="stream_table_\d+">.*?</g>', svg, re.S)


def _cells(block: str) -> list[tuple[float, float, float, float]]:
    """Extract ruled table-cell bounds from a table block."""
    return [
        (float(m[0]), float(m[1]), float(m[2]), float(m[3]))
        for m in re.findall(
            r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)"', block
        )
    ]


def _texts(block: str) -> list[str]:
    """Extract text values from a stream-table block."""
    return re.findall(r"<text[^>]*>([^<]*)</text>", block)


def _lettering(block: str) -> list[tuple[float, str, float, bool, str]]:
    """Extract table-cell text and its rendered style."""
    root = ET.fromstring(block)
    out: list[tuple[float, str, float, bool, str]] = []
    width: float | None = None
    for el in root:
        if el.tag == "rect":
            width = float(el.attrib["width"])
        elif el.tag == "text" and width is not None:
            out.append(
                (
                    width,
                    el.text or "",
                    float(el.attrib["font-size"]),
                    el.attrib.get("font-weight") == "bold",
                    el.attrib.get("text-anchor", "start"),
                )
            )
            width = None
    return out


def _zone_letters(svg: str) -> list[str]:
    """Extract row-zone letters from a table-sheet border."""
    return re.findall(r'<text[^>]*font-size="9.0"[^>]*>([A-Z])</text>', svg)[::2]


# --- the sheet is a drawing in its own right ---------------------------------


def test_the_table_sheet_carries_a_border_a_title_block_and_a_drawing_number():
    """Verify that a table sheet includes a border, title block, and drawing number."""
    svg = _sheet().to_svg(show_stream_table="sheet", page_size="A3")
    # Zone-border frame and letters.
    assert 'stroke-width="2"' in svg
    assert _zone_letters(svg)[:3] == ["A", "B", "C"]
    # Title-strip fields.
    assert "Aromatics Recovery A100" in svg  # the diagram's own title, kept
    assert "Stream Table" in svg  # what this sheet is
    assert "PFD-1001-ST" in svg  # a number of its own, derived
    assert "DRAWING No" in svg and "REV" in svg and "Issued for review" in svg


def test_no_diagram_is_drawn_on_it():
    """Verify that no diagram is drawn on it."""
    svg = _sheet(streams=3).to_svg(show_stream_table="sheet", page_size="A3")
    assert 'id="drawing"' not in svg and "<defs>" not in svg
    for tag in ("F0", "P0", "F1", "P1"):
        assert f">{tag}</text>" not in svg


def test_the_diagram_sheet_is_untouched_by_the_option():
    """Verify that the diagram sheet is untouched by the option."""
    fs = _sheet(streams=3)
    docked = fs.to_svg(show_stream_table=True, page_size="A3", border="zone")
    assert ">F0</text>" in docked  # the diagram is drawn
    assert len(_blocks(docked)) == 0 and '<g id="stream_table">' in docked


def test_a_table_sheet_rules_the_zone_border_without_being_asked():
    """Verify that a table sheet rules the zone border without being asked."""
    fs = _sheet(streams=3)
    assert _zone_letters(fs.to_svg(show_stream_table="sheet", page_size="A3"))
    plain = fs.to_svg(show_stream_table="sheet", page_size="A3", border="none")
    assert not _zone_letters(plain)
    assert "PFD-1001-ST" in plain  # the strip is drawn either way


def test_the_document_is_named_for_the_sheet_it_is():
    """Verify table-sheet document naming."""
    fs = _sheet(streams=3)
    assert "<title>Aromatics Recovery A100</title>" in fs.to_svg(page_size="A3")
    assert "<title>Aromatics Recovery A100 - Stream Table</title>" in fs.to_svg(
        show_stream_table="sheet", page_size="A3"
    )


# --- the sheet's own identity ------------------------------------------------


def test_the_drawing_number_is_derived_and_can_be_stated():
    """Verify that the drawing number is derived and can be stated."""
    fs = _sheet(streams=3)
    assert "PFD-1001-ST" in fs.to_svg(show_stream_table="sheet", page_size="A3")
    fs.stream_table.sheet_drawing_number = "PFD-1003"
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert "PFD-1003" in svg and "PFD-1001-ST" not in svg


def test_what_the_sheet_is_called_can_be_stated():
    """Verify that what the sheet is called can be stated."""
    fs = _sheet(streams=3)
    fs.stream_table.sheet_subtitle = "Stream Summary"
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert "Stream Summary" in svg and ">Stream Table</text>" not in svg


def test_the_rest_of_the_title_block_is_the_diagram_s():
    """Verify that a table sheet preserves the diagram title-block fields."""
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


def test_a_table_sheet_states_no_scale():
    """Verify that a table sheet states no scale."""
    fs = _sheet(streams=3)
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert ">SCALE</text>" in svg  # the box is ruled...
    # The SCALE cell has no value.
    after = svg.split(">SCALE</text>", 1)[1].lstrip()
    assert after.startswith("<line"), after[:120]


# --- wrapping ----------------------------------------------------------------


def test_more_streams_than_fit_wrap_into_stacked_blocks():
    """Verify that streams wrap into stacked, headed blocks holding each stream once, in order."""
    fs = _sheet(streams=21)
    names = [run[0].name for run in fs._named_runs().values()]
    blocks = _blocks(fs.to_svg(show_stream_table="sheet", page_size="A4"))
    assert len(blocks) > 1, "21 streams do not fit across an A4 sheet"
    # Blocks share an x origin and stack vertically.
    tops = []
    drawn: list[str] = []
    for i, block in enumerate(blocks):
        cells = _cells(block)
        tops.append(min(y for _x, y, _w, _h in cells))
        assert min(x for x, _y, _w, _h in cells) == min(x for x, _y, _w, _h in _cells(blocks[0]))
        texts = _texts(block)
        assert texts[0] == "Stream Number", f"block {i} is not headed"
        # Each block retains the section heading.
        assert "Mass Fraction" in texts, f"block {i} lost its section heading"
        drawn.extend(t for t in texts if t in names)
    assert tops == sorted(tops) and len(set(tops)) == len(tops)
    assert drawn == names


def test_how_many_streams_a_block_holds_comes_from_the_page():
    """Verify that page size determines stream-table block capacity."""

    def blocks(page: str) -> int:
        """Count stream-table blocks on a page size."""
        return len(_blocks(_sheet(streams=21).to_svg(show_stream_table="sheet", page_size=page)))

    assert blocks("A4") > blocks("A3") >= blocks("A2") == 1


def test_the_blocks_are_evened_out_rather_than_filled_and_left_a_stub():
    """Verify that the blocks are evened out rather than filled and left a stub."""
    table = F.stream_table_sheet(_sheet(streams=21), 900.0)
    assert table is not None
    counts = [len(block.rows[0]) - 1 for block in table.blocks]
    assert len(counts) > 1 and max(counts) - min(counts) <= 1


def test_one_ruling_answers_for_every_block():
    """Verify that one ruling answers for every block."""
    table = F.stream_table_sheet(_sheet(streams=21), 900.0)
    assert table is not None
    for block in table.blocks:
        assert block.size == table.blocks[0].size
        assert block.row_h == table.blocks[0].row_h
        assert [c.w for c in block.rows[0]] == [c.w for c in table.blocks[0].rows[0]][
            : len(block.rows[0])
        ]


def test_a_block_is_not_shrunk_to_fit_when_it_can_wrap_instead():
    """Verify that a block is not shrunk to fit when it can wrap instead."""
    fs = _sheet(streams=21)
    docked = F.stream_table_layout(fs)
    wrapped = F.stream_table_sheet(fs, 900.0)
    assert docked is not None and wrapped is not None
    assert docked.size < F._BASE_SIZE  # 21 columns: shrunk
    assert wrapped.blocks[0].size == F._BASE_SIZE


def test_a_stated_font_size_still_rules_the_table_sheet():
    """Verify that a stated font size still rules the table sheet."""
    fs = _sheet(streams=21)
    ruled = F.stream_table_sheet(fs, 500.0)
    fs.stream_table.font_size = 7.0
    smaller = F.stream_table_sheet(fs, 500.0)
    assert ruled is not None and smaller is not None
    assert smaller.blocks[0].size == 7.0
    assert len(smaller.blocks) < len(ruled.blocks)
    assert smaller.h < ruled.h


def test_a_sheet_with_no_page_takes_the_table_in_one_block():
    """Verify that a sheet with no page takes the table in one block."""
    svg = _sheet(streams=21).to_svg(show_stream_table="sheet")
    assert len(_blocks(svg)) == 1


# --- everything lands on the paper -------------------------------------------


def _viewbox(svg: str) -> tuple[float, float, float, float]:
    """Extract the SVG view box."""
    m = re.search(r'viewBox="([-\d. ]+)"', svg)
    assert m
    x, y, w, h = (float(v) for v in m.group(1).split())
    return x, y, w, h


@pytest.mark.parametrize("page", ["A4", "A3", "A2", "A1", None])
@pytest.mark.parametrize("streams", [1, 8, 21])
def test_every_cell_is_drawn_inside_the_sheet(page, streams):
    """Verify that every cell is drawn inside the sheet."""
    fs = _sheet(streams=streams)
    svg = fs.to_svg(show_stream_table="sheet", page_size=page)
    vx, vy, vw, vh = _viewbox(svg)
    for block in _blocks(svg):
        for x, y, w, h in _cells(block):
            assert vx <= x and x + w <= vx + vw, f"a cell runs off the side of an {page} sheet"
            assert vy <= y and y + h <= vy + vh, f"a cell runs off the end of an {page} sheet"


def test_the_table_does_not_run_into_the_title_strip():
    """Verify that the table does not run into the title strip."""
    fs = _sheet(streams=21, rows=4)
    plan = table_sheet_plan(fs, _page("A4"))
    strip_top = plan.strip[1]
    assert plan.top + plan.table.h <= strip_top


def test_the_stack_is_centred_across_the_page_and_flush_with_its_top():
    """Verify that the stack is centred across the page and flush with its top."""
    plan = table_sheet_plan(_sheet(streams=21), _page("A3"))
    page = _page("A3")
    assert page is not None
    left_gap = plan.left
    right_gap = page.width - (plan.left + plan.table.w)
    assert abs(left_gap - right_gap) < 1.0
    # Blocks share the same left edge.
    lefts = [x for _i, _b, x, _y in plan.table.at(plan.left, plan.top)]
    assert len(set(lefts)) == 1


# --- what it refuses ---------------------------------------------------------


def test_a_page_too_small_for_the_table_says_which_furniture_will_not_fit():
    """Verify that an undersized page identifies the stream table."""
    fs = _sheet(streams=6)
    for run in fs._named_runs().values():
        run[0].properties = {f"Component {n}": f"{n / 100:.2f}" for n in range(40)}
    with pytest.raises(ValueError, match="stream table"):
        fs.to_svg(show_stream_table="sheet", page_size="A4")
    # A larger page renders the same table.
    assert _blocks(fs.to_svg(show_stream_table="sheet", page_size="A2"))


def test_a_flowsheet_with_nothing_to_tabulate_is_refused():
    """Verify that a flowsheet with nothing to tabulate is refused."""
    fs = Flowsheet("bare")
    pump = fs.add(U.Pump("P-101")).pin(x=100, y=100)
    tank = fs.add(U.Tank("T-101")).pin(x=300, y=100)
    fs.connect(pump.discharge, tank.inlet)
    with pytest.raises(ValueError, match="nothing to tabulate"):
        fs.to_svg(show_stream_table="sheet", page_size="A3")


def test_a_line_across_the_edge_with_nothing_stated_is_refused_for_the_property():
    """Check that the refusal blames the missing property, not a missing boundary line."""
    fs = Flowsheet("flagged")
    feed = fs.add(U.Feed("F")).pin(x=100, y=100)
    product = fs.add(U.Product("P")).pin(x=300, y=100)
    fs.connect(feed.outlet, product.inlet)
    with pytest.raises(ValueError, match="nothing to tabulate") as refused:
        fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert "no stream states a property." in str(refused.value)


def test_a_spelling_neither_backend_knows_is_refused():
    """Verify that a spelling neither backend knows is refused."""
    fs = _sheet(streams=3)
    for value in ("own sheet", "Sheet", "table"):
        with pytest.raises(ValueError, match="show_stream_table"):
            fs.to_svg(show_stream_table=cast(Any, value), page_size="A3")


def test_the_coordinate_overlay_is_refused_rather_than_drawn_over_nothing():
    """Verify that the coordinate overlay is refused rather than drawn over nothing."""
    fs = _sheet(streams=3)
    with pytest.raises(ValueError, match="debug"):
        fs.to_svg(show_stream_table="sheet", page_size="A3", debug=True)


# --- the other output paths --------------------------------------------------


def test_the_drawio_export_draws_the_same_sheet():
    """Verify that Draw.io exports the table-sheet structure."""
    fs = _sheet(streams=21)
    xml = fs.to_drawio(show_stream_table="sheet", page_size="A4")
    root = ET.fromstring(xml)
    cells = list(root.iter("mxCell"))
    tables = [c for c in cells if "shape=table;" in (c.get("style") or "")]
    # One table per block and one revision grid.
    blocks = len(_blocks(fs.to_svg(show_stream_table="sheet", page_size="A4")))
    assert len(tables) == blocks + 1
    text = "".join(c.get("value") or "" for c in cells)
    assert text.count("Stream Number") == blocks
    assert "PFD-1001-ST" in text
    # Equipment is absent from the table-sheet export.
    assert "F0" not in text and "P0" not in text


def test_the_drawio_export_opens_on_the_same_paper():
    """Verify that Draw.io uses the requested table-sheet page size."""
    fs = _sheet(streams=21)
    model = ET.fromstring(fs.to_drawio(show_stream_table="sheet", page_size="A4")).find(
        "diagram/mxGraphModel"
    )
    page = _page("A4")
    assert model is not None and page is not None
    assert model.get("page") == "1"
    assert float(model.get("pageWidth") or 0) == pytest.approx(page.width, abs=0.01)


def test_render_writes_the_table_sheet_to_whatever_the_extension_asks_for(tmp_path):
    """Verify that render writes the requested table-sheet format."""
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
    """Verify that raster exports include the table sheet."""
    out = tmp_path / f"stream_table{ext}"
    _sheet(streams=21).render(out, show_stream_table="sheet", page_size="A4")
    assert out.stat().st_size > 1000


def test_the_option_reaches_the_drafting_call(caught):
    """Verify that table-sheet options reach the drafting call."""
    fs = _sheet(streams=21)
    fs.show(show_stream_table="sheet", page_size="A4")
    assert caught["svg"] == _sheet(streams=21).to_svg(show_stream_table="sheet", page_size="A4")


# --- one number apiece -------------------------------------------------------


def _unnumbered(fs: Flowsheet) -> list:
    """Find missing-number warnings on a table sheet."""
    return [w for w in fs.warnings if w.code == "table-sheet-unnumbered"]


def test_a_table_sheet_with_no_number_to_derive_says_so():
    """Verify that a sheet with no title block is drawn and filed, and warns until numbered."""
    fs = _sheet(streams=3)
    fs.title_block = None
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert _blocks(svg), "the sheet is still drawn"
    assert "Stream Table" in svg and "DRAWING No" in svg
    assert "Aromatics Recovery A100" in svg  # the flowsheet's name, as the strip falls back to
    found = _unnumbered(fs)
    assert len(found) == 1
    assert "drawing number" in found[0].message
    assert found[0].severity == "warning"
    # A valid number removes the previous warning.
    fs.stream_table.sheet_drawing_number = "PFD-1003"
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert not _unnumbered(fs)


def test_a_title_block_carrying_no_number_says_so_too():
    """Verify that a title block carrying no number says so too."""
    fs = _sheet(streams=3)
    fs.title_block = TitleBlock(title="Aromatics Recovery A100", company="Pandid")
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert _unnumbered(fs)


def test_the_diagram_sheet_is_never_unnumbered_by_this():
    """Verify that the diagram sheet is never unnumbered by this."""
    fs = _sheet(streams=3)
    fs.title_block = None
    fs.to_svg(page_size="A3", border="zone")
    assert not _unnumbered(fs)


def test_the_drawio_export_reports_it_in_the_same_words():
    """Verify that Draw.io reports missing numbering consistently."""
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
    """Report whether a flowsheet has unresolved geometry."""
    return all(u.frame is None for u in fs.units) and all(s.route is None for s in fs.streams)


def test_the_table_sheet_s_own_refusals_come_before_the_geometry():
    """Verify that table-sheet validation runs before geometry creation."""
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
    """Verify that a duplicate number is refused before the geometry."""
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
    """Verify that unknown table-sheet options are always rejected."""
    fs = _sheet(streams=3)
    for render in (fs.to_svg, fs.to_drawio):
        with pytest.raises(ValueError, match=match):
            render(show_stream_table=cast(Any, table), page_size="A3", **cast(Any, kwargs))


def test_a_valid_option_this_sheet_cannot_show_is_still_accepted():
    """Verify that valid inapplicable options remain accepted."""
    fs = _sheet(streams=3)
    assert fs.to_svg(show_stream_table="sheet", page_size="A3", connections="flanged")
    assert fs.to_svg(show_stream_table="sheet", page_size="A3", jump_direction="horizontal")


# --- one ruling, page or no page ---------------------------------------------


def test_the_ruling_does_not_depend_on_whether_a_page_was_named():
    """Verify that the ruling does not depend on whether a page was named."""
    fs = _sheet(streams=21)
    unpaged = F.stream_table_sheet(fs, None)
    paged = F.stream_table_sheet(fs, 4000.0)
    wrapped = F.stream_table_sheet(fs, 900.0)
    assert unpaged is not None and paged is not None and wrapped is not None
    assert len(unpaged.blocks) == len(paged.blocks) == 1
    assert unpaged.blocks[0].size == paged.blocks[0].size == F._BASE_SIZE
    assert unpaged.blocks[0].row_h == paged.blocks[0].row_h
    assert unpaged.w == paged.w and unpaged.h == paged.h
    # A page that cuts the table into blocks rules them as the unpaged sheet does.
    assert len(wrapped.blocks) > 1
    assert wrapped.blocks[0].size == unpaged.blocks[0].size
    assert wrapped.blocks[0].row_h == unpaged.blocks[0].row_h
    # Paged and unpaged sheets use the same column widths.
    assert wrapped.blocks[0].rows[0][0].w == unpaged.blocks[0].rows[0][0].w
    assert wrapped.blocks[0].rows[0][1].w == unpaged.blocks[0].rows[0][1].w


# --- a backend cannot swallow an argument it does not know -------------------


def test_an_entry_point_refuses_a_keyword_it_does_not_take(tmp_path: Path) -> None:
    """Verify that every entry point refuses a keyword it does not take."""
    fs = _sheet(streams=3)
    for call, args in (
        (fs.to_svg, ()),
        (fs.to_drawio, ()),
        (fs.render, (tmp_path / "sheet.svg",)),
        (fs.show, ()),
    ):
        with pytest.raises(TypeError, match="nonsense"):
            cast(Any, call)(*args, nonsense=True)
    with pytest.raises(TypeError, match="debug"):
        cast(Any, fs.to_drawio)(debug=True)


def test_every_keyword_the_entry_points_pass_is_one_its_backend_names():
    """Verify that entry-point keywords match backend parameters."""
    for entry, backend in (
        (Flowsheet.to_svg, SvgRenderer.render),
        (Flowsheet.to_drawio, DrawioRenderer.render),
    ):
        passed = set(inspect.signature(entry).parameters) - {"self", "check"}
        named = set(inspect.signature(backend).parameters) - {"self", "fs"}
        assert passed <= named, f"{backend.__qualname__} would swallow {passed - named}"


# --- an unsupported extension is a fact about the path ----------------------


def test_the_supported_extensions_still_write(tmp_path):
    """Verify that the supported extensions still write."""
    fs = _sheet(streams=3)
    for name in ("sheet.svg", "sheet", "sheet.drawio"):
        out = tmp_path / name
        fs.render(out)
        assert out.stat().st_size > 0


# --- a refused render leaves fs.warnings exactly as it found them ------------


def _with_an_unused_section(streams: int = 3) -> Flowsheet:
    """Create a flowsheet that reports an unused table section."""
    fs = _sheet(streams=streams)
    fs.stream_table_sections = [("Nothing Sets This", "Mass Fraction")]
    return fs


def test_a_refused_render_adds_no_finding_of_its_own():
    """Verify that a refused render adds no finding of its own."""
    fs = _with_an_unused_section()
    fs.stream_table.sheet_drawing_number = "PFD-1001"  # refused: the diagram's
    with pytest.raises(ValueError, match="drawing number"):
        fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert fs.warnings == []


def test_a_refused_render_erases_no_finding_from_the_last_one():
    """Verify that a refused render erases no finding from the last one."""
    fs = _with_an_unused_section()
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    kept = [w.code for w in fs.warnings]
    assert "stream-table-section-unused" in kept, "the fixture must warn about something"
    with pytest.raises(ValueError):
        fs.to_svg(show_stream_table="sheet", page_size="A9")
    assert [w.code for w in fs.warnings] == kept


def test_a_successful_render_still_replaces_the_last_one_s_findings():
    """Verify that a successful render still replaces the last one's findings."""
    fs = _with_an_unused_section()
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert any(w.code == "stream-table-section-unused" for w in fs.warnings)
    fs.stream_table_sections = []
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert not any(w.code == "stream-table-section-unused" for w in fs.warnings)


# --- what "the same number" means --------------------------------------------


@pytest.mark.parametrize(
    "stated,collides",
    [
        ("PFD-1001", True),  # itself
        ("pfd-1001", True),  # letter case
        ("  PFD-1001\t", True),  # surrounding space, of any kind
        (" PFD-1001 ", True),  # ...including NBSP and em space
        ("PFD 1001", False),  # an interior space is a different number
        ("PFD-1001.", False),  # so is a trailing stop
        ("PFD-1001​", False),  # so is a zero-width character
        ("PFD-1002", False),
    ],
)
def test_which_numbers_count_as_the_diagram_s_own(stated, collides):
    """Verify drawing-number collisions after canonicalisation."""
    fs = _sheet(streams=3)
    fs.stream_table.sheet_drawing_number = stated
    if collides:
        with pytest.raises(ValueError, match="the diagram's own drawing number"):
            fs.to_svg(show_stream_table="sheet", page_size="A3")
    else:
        assert fs.to_svg(show_stream_table="sheet", page_size="A3")


def test_a_ligature_is_the_same_number_as_the_letters_it_stands_for():
    """Verify that a ligature is the same number as the letters it stands for."""
    fs = _sheet(streams=3)
    fs.title_block = TitleBlock(title="Ligatures", drawing_number="PFD-FFI")
    fs.stream_table.sheet_drawing_number = "PFD-ﬃ"
    with pytest.raises(ValueError, match="the diagram's own drawing number"):
        fs.to_svg(show_stream_table="sheet", page_size="A3")


# --- a valid option this sheet cannot show changes nothing about it ----------


@pytest.fixture(scope="module")
def table_sheet_noop_baselines() -> dict[str, str]:
    """Render plain table-sheet baselines for both backends."""
    options = {"show_stream_table": "sheet", "page_size": "A4", "diagram": "p&id"}
    return {
        "to_svg": _sheet(streams=21).to_svg(**options),
        "to_drawio": _sheet(streams=21).to_drawio(**options),
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"connections": "flanged"},
        {"connections": "flanged-at-nozzles"},
        {"connections": "none"},
        {"jump_direction": "horizontal"},
    ],
)
def test_an_option_a_table_sheet_cannot_show_leaves_the_drawing_identical(
    kwargs: dict[str, str], table_sheet_noop_baselines: dict[str, str]
) -> None:
    """Verify that table-sheet no-op options preserve both backend exports."""
    for render in ("to_svg", "to_drawio"):
        plain = table_sheet_noop_baselines[render]
        stated = getattr(_sheet(streams=21), render)(
            show_stream_table="sheet", page_size="A4", diagram="p&id", **cast(Any, kwargs)
        )
        assert stated == plain, f"{kwargs} moved ink on a {render} table sheet"


def test_the_same_option_does_change_a_diagram_that_can_show_it():
    """Verify that the same option changes a normal diagram export."""

    def build() -> Flowsheet:
        """Create a diagram that can show flanged connections."""
        fs = Flowsheet("joints")
        feed = fs.add(U.Feed("F")).pin(x=100, y=100)
        pump = fs.add(U.Pump("P-101")).pin(x=280, y=100)
        out = fs.add(U.Product("P")).pin(x=460, y=100)
        fs.connect(feed.outlet, pump.suction)
        fs.connect(pump.discharge, out.inlet)
        return fs

    plain = build().to_svg(page_size="A3", diagram="p&id")
    marked = build().to_svg(page_size="A3", diagram="p&id", connections="flanged")
    assert marked != plain


# --- a refused render changes nothing at all ---------------------------------
#
# Failed renders restore all mutable flowsheet state.


def test_the_state_check_can_see_a_change_the_old_one_could_not():
    """Verify that the state check can see a change the old one could not."""
    fs = _sheet(streams=3)
    before = pickle.dumps(fs)
    fs.stream_number_start = 90
    fs.renumber_streams()
    assert pickle.dumps(fs) != before


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
        {"page_size": "A9"},
    ],
)
@pytest.mark.parametrize("numbering", [False, True])
def test_a_refused_render_leaves_the_whole_flowsheet_alone(kwargs, numbering):
    """Verify that a refused render leaves the whole flowsheet alone."""
    fs = _sheet(streams=3)
    if numbering:
        fs.stream_number_start = 90
        fs.line_number_start = 700
    before = pickle.dumps(fs)
    with pytest.raises(ValueError):
        fs.to_svg(**cast(Any, kwargs))
    assert pickle.dumps(fs) == before, "a refused render changed the flowsheet"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"show_stream_table": "sheet", "page_size": "A3"},
        {"jump_direction": "sideways"},
    ],
)
def test_a_refused_drawio_export_leaves_the_whole_flowsheet_alone(kwargs):
    """Verify that a refused draw.io export leaves the whole flowsheet alone."""
    bare = Flowsheet("bare")
    pump = bare.add(U.Pump("P-101")).pin(x=100, y=100)
    tank = bare.add(U.Tank("T-101")).pin(x=300, y=100)
    bare.connect(pump.discharge, tank.inlet)
    before = pickle.dumps(bare)
    with pytest.raises(ValueError):
        bare.to_drawio(**cast(Any, kwargs))
    assert pickle.dumps(bare) == before


def test_a_refused_render_leaves_the_flowsheet_alone_after_a_successful_one():
    """Verify that a refused render leaves the flowsheet alone after a successful one."""
    fs = _sheet(streams=3)
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    before = pickle.dumps(fs)
    with pytest.raises(ValueError):
        fs.to_svg(show_stream_table="sheet", page_size="A9")
    assert pickle.dumps(fs) == before


def test_an_unsupported_extension_leaves_the_whole_flowsheet_alone(tmp_path):
    """Verify that an unsupported extension leaves the whole flowsheet alone."""
    fs = _sheet(streams=3)
    before = pickle.dumps(fs)
    with pytest.raises(ValueError, match="Unsupported output format"):
        fs.render(tmp_path / "sheet.unsupported", check=False)
    assert pickle.dumps(fs) == before


def test_a_model_error_leaves_the_whole_flowsheet_alone():
    """Verify that a model error leaves the whole flowsheet alone."""
    fs = _sheet(streams=3)
    fs.units[0].pin_ = Pin(x=float("nan"), y=10.0)  # pin() refuses a NaN
    before = pickle.dumps(fs)
    with pytest.raises(ValueError, match="Flowsheet validation failed"):
        fs.to_svg(page_size="A3")
    assert pickle.dumps(fs) == before


# --- ...including the findings it was reading --------------------------------


def test_a_model_error_erases_no_finding_from_the_last_render():
    """Verify that a model error erases no finding from the last render."""
    fs = _with_an_unused_section()
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    kept = [w.code for w in fs.warnings]
    assert "stream-table-section-unused" in kept
    fs.units[0].pin_ = Pin(x=float("nan"), y=10.0)  # pin() refuses a NaN
    with pytest.raises(ValueError, match="Flowsheet validation failed"):
        fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert [w.code for w in fs.warnings] == kept


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page_size": "A9"},
        {"show_stream_table": "sheet", "page_size": "A4", "debug": True},
        {"show_stream_table": "sheet", "page_size": "A3"},  # the duplicate number
    ],
)
def test_a_refused_render_keeps_the_very_list_object_fs_warnings_had(kwargs):
    """Verify that a rejected render preserves warning-list identity."""
    fs = _with_an_unused_section()
    fs.stream_table.sheet_drawing_number = "PFD-1001"  # refused: the diagram's
    fs.stream_table_sections = []
    fs.to_svg(page_size="A3")
    held = fs.warnings
    with pytest.raises(ValueError):
        fs.to_svg(**cast(Any, kwargs))
    assert fs.warnings is held


def test_a_table_sheet_reports_a_cell_that_cannot_hold_its_value():
    """Verify that a table sheet reports a cell that cannot hold its value."""
    fs = _sheet(streams=3)
    # The long table-sheet subtitle is truncated by the title strip.
    fs.stream_table.sheet_subtitle = (
        "Stream Table for the Aromatics Recovery Unit A100, Sheet 1 of 1"
    )
    svg = fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert svg.startswith("<?xml")
    cut = [w for w in fs.warnings if w.code == "text-truncated"]
    assert cut, "a value the strip had to abbreviate must not be silent"
    assert any("subtitle" in w.message for w in cut)
    assert any("units its cell has" in w.message for w in cut)


# --- a partition that fits is found ------------------------------------------


#: Width available to the table on an A4 sheet.
A4_ROOM = 1122.5196850393702 - 2 * (F.OUTER_MARGIN + F.ZONE_BAND) - 2 * F.INNER


def _long_section(streams: int = 21, width: int = 101) -> Flowsheet:
    """Create a flowsheet with a long stream-table section heading."""
    fs = _sheet(streams=streams, rows=1)
    fs.stream_table_sections = [("Temperature (C)", "W" * width)]
    return fs


def _ruled_width(m, chunks: list) -> float:
    """Calculate the table width required by a partition."""
    return F._section_span(m, min(len(c) for c in chunks)) + m.name_w * max(len(c) for c in chunks)


def test_a_table_that_fits_in_more_blocks_is_drawn_rather_than_refused():
    """Verify that a wider partition permits a table-sheet render."""
    svg = _long_section().to_svg(show_stream_table="sheet", page_size="A4")
    blocks = _blocks(svg)
    assert len(blocks) == 3
    assert all(_texts(b) for b in blocks)  # every block drew something


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
def test_no_lettering_on_the_table_sheet_runs_outside_its_own_rule():
    """Verify that no lettering on the table sheet runs outside its own rule."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    svg = _long_section().to_svg(show_stream_table="sheet", page_size="A4")
    checked: list[str] = []
    for block in _blocks(svg):
        for width, body, size, bold, anchor in _lettering(block):
            drawn = stringWidth(body, "Helvetica-Bold" if bold else "Helvetica", size)
            room = width - (2 * F._STREAM_PAD if anchor == "start" else 0.0)
            assert drawn <= room, f"{body!r} draws {drawn:.1f} in {room:.1f} of cell"
            checked.append(body)
    # The long section heading appears in every block.
    assert checked.count("W" * 101) == 3
    assert len(checked) > 40


def test_the_widest_partition_that_fits_is_the_one_chosen():
    """Verify that the widest partition that fits is the one chosen."""
    fs = _long_section()
    table = F.stream_table_sheet(fs, A4_ROOM)
    assert table is not None
    assert len(table.blocks) == 3
    assert table.w <= A4_ROOM
    # Fewer blocks do not fit within the A4 width.
    m = F._measure(fs, own_sheet=True)
    assert m is not None
    assert _ruled_width(m, F._blocks_of(21, 2)) > A4_ROOM
    assert _ruled_width(m, F._blocks_of(21, 1)) > A4_ROOM


def test_a_table_no_partition_can_fit_is_still_refused():
    """Verify that an over-wide table has no valid partition."""
    with pytest.raises(ValueError, match="stream table"):
        _long_section(width=400).to_svg(show_stream_table="sheet", page_size="A4")


# --- the columns are shared out evenly, at every count ------------------------


def test_blocks_are_shared_out_within_one_column_at_every_count():
    """Verify that blocks are shared out within one column at every count."""
    for n in range(1, 26):
        for count in range(1, n + 1):
            blocks = F._blocks_of(n, count)
            sizes = [len(b) for b in blocks]
            assert len(blocks) == count, (n, sizes)
            assert max(sizes) - min(sizes) <= 1, (n, sizes)
            assert sum(sizes) == n
            # Every column occurs once in sheet order.
            assert [i for b in blocks for i in b] == list(range(n))


def test_a_stub_block_no_longer_widens_the_label_column_into_a_refusal():
    """Verify that a stub block no longer widens the label column into a refusal."""
    fs = _sheet(streams=10, rows=1)
    fs.stream_table_sections = [("Temperature (C)", "Trace Components and Contaminants (mg/kg)")]
    m = F._measure(fs, own_sheet=True)
    assert m is not None

    balanced = F._blocks_of(10, 4)
    assert [len(b) for b in balanced] == [3, 3, 2, 2]
    stub = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
    # A one-column stub widens the shared label column.
    assert _ruled_width(m, stub) == pytest.approx(_ruled_width(m, balanced) + m.name_w)

    # Four balanced blocks are the smallest partition that fits.
    room = _ruled_width(m, balanced)
    assert _ruled_width(m, stub) > room
    assert _ruled_width(m, F._blocks_of(10, 3)) > room
    assert [len(b) for b in F._partition(m, 10, room)] == [3, 3, 2, 2]
    # Five blocks fit but are not required.
    assert _ruled_width(m, F._blocks_of(10, 5)) < room


# --- what the search promises against the division it replaced ----------------


def _division_count(m, n: int, room: float) -> int:
    """Calculate the legacy stream-table partition count."""
    per = max(1, int((room - m.label_w) // m.name_w))
    return (n + per - 1) // per


def test_the_search_never_chooses_more_blocks_than_the_division_it_replaced():
    """Verify that partition search uses no more blocks than division."""
    for rows in (1, 4):
        for n in (5, 7, 10, 13, 21):
            fs = _sheet(streams=n, rows=rows)
            m = F._measure(fs, own_sheet=True)
            assert m is not None
            for step in range(140):
                room = 150.0 + step * 12.5
                divided = F._blocks_of(n, _division_count(m, n, room))
                if _ruled_width(m, divided) > room:
                    continue  # the division's own partition did not fit
                assert len(F._partition(m, n, room)) <= len(divided), (n, room)


def test_the_search_is_not_the_division_and_is_not_claimed_to_be():
    """Verify that partition search does not reproduce floating-point division."""
    fs = _sheet(streams=5, rows=1)
    fs.stream_table_sections = []
    for stream in fs.streams:
        # This value yields the floating-point boundary case.
        stream.properties = {"Total Flow (kg/h)": "0.0441 kg/kg total"}
    m = F._measure(fs, own_sheet=True)
    assert m is not None

    whole = [list(range(5))]
    room = _ruled_width(m, whole)  # exactly the room one block of five needs
    assert (room - m.label_w) // m.name_w == 4.0  # ...which the division reads as four
    assert _division_count(m, 5, room) == 2  # so it cuts the table in two
    assert [len(b) for b in F._partition(m, 5, room)] == [5]  # and this does not


# --- ...and the same guarantee through the write itself ----------------------
#
# Render-write failures also restore flowsheet state.


def _full_disk(*_args: object, **_kwargs: object) -> bytes:
    """Raise the output failure used by render rollback tests."""
    raise OSError(28, "No space left on device")


def _without_geometry(fs) -> tuple[set[str], set[str]]:
    """Capture units and streams without derived geometry."""
    return (
        {u.name for u in fs.units if u.frame is None},
        {s.name for s in fs.streams if s.route is None},
    )


def _damageable() -> Flowsheet:
    """Create a flowsheet with rendered and unresolved state."""
    fs = _with_an_unused_section()
    fs.to_svg(show_stream_table="sheet", page_size="A3")
    assert [w.code for w in fs.warnings] == ["stream-table-section-unused"]
    feed = fs.add(U.Feed("F9")).pin(x=100, y=340)
    product = fs.add(U.Product("P9")).pin(x=320, y=340)
    fs.connect(feed.outlet, product.inlet)
    fs.stream_number_start = 90
    return fs


def test_the_write_failure_checks_can_see_the_mutation_they_forbid(tmp_path):
    """Verify that rollback assertions detect a successful render mutation."""
    fs = _damageable()
    state, held, finding = pickle.dumps(fs), fs.warnings, fs.warnings[0]
    unbuilt, numbering = _without_geometry(fs), [s.name for s in fs.streams]
    fs.render(tmp_path / "sheet.svg", show_stream_table="sheet", page_size="A3")
    assert pickle.dumps(fs) != state
    assert fs.warnings is not held
    assert not any(w is finding for w in fs.warnings)
    assert _without_geometry(fs) != unbuilt
    assert [s.name for s in fs.streams] != numbering


_NEEDS_PDF = pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")


@pytest.mark.parametrize(
    "ext, injection",
    [
        (".svg", "write"),
        ("", "write"),  # no extension at all, which is drawn as SVG
        (".drawio", "write"),
        pytest.param(".pdf", "convert", marks=_NEEDS_PDF),
        pytest.param(".pdf", "write", marks=_NEEDS_PDF),
        pytest.param(".png", "convert", marks=_NEEDS_PDF),
        pytest.param(".png", "write", marks=_NEEDS_PDF),
    ],
)
def test_a_render_that_cannot_be_written_leaves_the_whole_flowsheet_alone(
    tmp_path, monkeypatch, ext, injection
):
    """Verify that write failures restore the complete flowsheet state."""
    fs = _damageable()
    state, held, finding = pickle.dumps(fs), fs.warnings, fs.warnings[0]
    unbuilt, numbering = _without_geometry(fs), [s.name for s in fs.streams]
    out = tmp_path / f"sheet{ext}"
    if injection == "write":
        monkeypatch.setattr(Path, "write_text", _full_disk)
        monkeypatch.setattr(Path, "write_bytes", _full_disk)
    else:
        monkeypatch.setattr(
            "pandid.render.export.to_pdf" if ext == ".pdf" else "pandid.render.export.to_png",
            _full_disk,
        )
    with pytest.raises(OSError):
        fs.render(out, show_stream_table="sheet", page_size="A3")
    assert not out.exists(), "the render produced no file"
    assert pickle.dumps(fs) == state, "a render that produced no file changed the flowsheet"
    assert fs.warnings is held, "fs.warnings was replaced with another list"
    assert any(w is finding for w in fs.warnings), "a finding was erased"
    assert _without_geometry(fs) == unbuilt, "geometry was left cached for the next render"
    assert [s.name for s in fs.streams] == numbering, "the streams were left renumbered"
