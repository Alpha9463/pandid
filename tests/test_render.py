from pfd import Flowsheet, units as U


def test_render_svg_with_manual_placements(tmp_path):
    fs = Flowsheet("Render Test")
    feed = fs.add(U.Feed("F")).pin(x=10, y=10)
    hx = fs.add(U.HeatExchanger("E-1")).pin(x=100, y=10)
    prod = fs.add(U.Product("P")).pin(x=200, y=10)

    fs.connect(feed.outlet, hx.cold_in)
    fs.connect(hx.cold_out, prod.inlet).via([(150, 20), (150, 150)])

    out_path = tmp_path / "test.svg"
    fs.render(str(out_path))

    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")

    # Check root and defs
    assert "<svg" in content
    assert "<defs>" in content
    assert 'id="sym_hex"' in content

    # Check <use> tags for manually pinned coordinates
    assert "<polygon" in content
    assert 'fill="transparent"' in content
    # Pinned position is honored; dimensions come from the symbol (don't hard-code).
    assert '<use href="#sym_hex" x="100" y="10"' in content

    # Check stream paths (waypoints should be present in string)
    assert "150.0,20.0" in content
    assert "150.0,150.0" in content
    assert '<path d="' in content


def test_render_svg_escapes_xml(tmp_path):
    fs = Flowsheet("Render Test")
    fs.add(U.Feed("<Malicious>&")).pin(x=10, y=10)

    out_path = tmp_path / "test_escape.svg"
    fs.render(str(out_path))

    content = out_path.read_text(encoding="utf-8")
    assert "&lt;Malicious&gt;&amp;" in content
    assert "<Malicious>" not in content


def test_render_svg_generic_symbol_duplicate_ids(tmp_path):
    fs = Flowsheet("Render Test Generic")

    class UnknownUnit1(U.Unit):
        kind = "unknown1"

    class UnknownUnit2(U.Unit):
        kind = "unknown2"

    fs.add(UnknownUnit1("U1")).pin(x=10, y=10)
    fs.add(UnknownUnit2("U2")).pin(x=200, y=20)

    out_path = tmp_path / "test_generic.svg"
    fs.render(str(out_path))

    content = out_path.read_text(encoding="utf-8")
    assert 'id="sym_unknown1"' in content
    assert 'id="sym_unknown2"' in content
    assert 'id="sym_generic"' not in content
