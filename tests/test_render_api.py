"""render() contract: to_svg() returns a string; render(path) writes the file
whose format is inferred from the extension and returns None (spec §9)."""

import pytest

from pfd import Flowsheet, units as U


def _fs():
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, prod.inlet)
    return fs


def test_to_svg_returns_a_string():
    svg = _fs().to_svg()
    assert isinstance(svg, str)
    assert "<svg" in svg


def test_render_svg_writes_file_and_returns_none(tmp_path):
    out = tmp_path / "d.svg"
    result = _fs().render(str(out))
    assert result is None
    assert out.exists()
    assert "<svg" in out.read_text(encoding="utf-8")


def test_render_pdf_without_cairosvg_raises_helpful_error(tmp_path):
    try:
        import cairosvg  # noqa: F401

        pytest.skip("cairosvg installed; the ImportError path isn't exercised")
    except ImportError:
        pass
    with pytest.raises(ImportError) as excinfo:
        _fs().render(str(tmp_path / "d.pdf"))
    msg = str(excinfo.value)
    assert "cairosvg" in msg and "pfd[pdf]" in msg


def test_render_unknown_extension_raises_valueerror(tmp_path):
    with pytest.raises(ValueError):
        _fs().render(str(tmp_path / "d.bmp"))


def test_canvas_fits_content_and_is_not_padded_to_page_size():
    # A two-box diagram must frame tightly, not float in a full A3 sheet
    # (1587x1122). Regression guard for the canvas-fit fix.
    import re

    svg = _fs().to_svg()
    m = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
    w, h = float(m.group(3)), float(m.group(4))
    assert w < 800 and h < 500
    # width/height in px must equal the viewBox (aspect-matched → no letterbox).
    dims = re.search(r'width="(\d+)" height="(\d+)" viewBox', svg)
    assert (float(dims.group(1)), float(dims.group(2))) == (round(w), round(h))
