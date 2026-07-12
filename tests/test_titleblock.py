"""P&ID title block + revision history rendering."""
from pfd import Flowsheet, units as U
from pfd.document import TitleBlock, Revision


def test_title_block_fields_rendered():
    fs = Flowsheet("Demo Unit")
    fs.add(U.Feed("F")); fs.add(U.Product("P"))
    fs.connect(fs.units[0].outlet, fs.units[1].inlet)
    fs.title_block = TitleBlock(
        title="Demo Sheet", drawing_number="PFD-9", sheet="2", of_sheets="4",
        drawn_by="AA", checked_by="BB", approved_by="CC",
        revisions=[Revision("0", "2026-01-01", "Issued", "AA")],
    )
    svg = fs.to_svg(styling="pid")
    for token in ("PFD-9", "2 of 4", "AA", "BB", "CC", "REV", "DESCRIPTION", "Issued"):
        assert token in svg, token


def test_no_title_block_still_renders_pid():
    fs = Flowsheet("Bare")
    fs.add(U.Feed("F")); fs.add(U.Product("P"))
    fs.connect(fs.units[0].outlet, fs.units[1].inlet)
    svg = fs.to_svg(styling="pid")   # falls back to defaults, must not raise
    assert "Bare" in svg
