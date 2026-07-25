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


def test_unit_labels_drawn_over_streams_with_a_halo():
    # Equipment tags are emitted after the stream group and backed by a white
    # halo, so a passing line can never strike through the text.
    fs = Flowsheet("Labels")
    feed = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-601"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, hx.cold_in)
    fs.connect(hx.cold_out, prod.inlet)
    svg = fs.to_svg()

    assert svg.index('id="unit_labels"') > svg.index('id="streams"')
    labels = svg[svg.index('id="unit_labels"') :]
    assert 'fill="white"' in labels  # halo behind the tag
    assert ">E-601<" in labels


def test_stream_number_labels_do_not_overprint():
    # Streams sharing a corridor sit a few px apart; their numbers must be slid
    # along the line rather than stacked on the same point.
    import re

    fs = Flowsheet("Crossing")
    f1, f2 = fs.add(U.Feed("Feed A")), fs.add(U.Feed("Feed B"))
    s1 = fs.add(U.Splitter("SP-501", n_outlets=2))
    s2 = fs.add(U.Splitter("SP-502", n_outlets=2))
    m1 = fs.add(U.Mixer("M-501", n_inlets=2))
    m2 = fs.add(U.Mixer("M-502", n_inlets=2))
    p1, p2 = fs.add(U.Product("Product A")), fs.add(U.Product("Product B"))
    fs.connect(f1.outlet, s1.inlet)
    fs.connect(f2.outlet, s2.inlet)
    fs.connect(s1.out_1, m1.in_1)
    fs.connect(s1.out_2, m2.in_1)
    fs.connect(s2.out_1, m1.in_2)
    fs.connect(s2.out_2, m2.in_2)
    fs.connect(m1.outlet, p1.inlet)
    fs.connect(m2.outlet, p2.inlet)
    svg = fs.to_svg()

    pts = [
        (float(x), float(y))
        for x, y in re.findall(r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*font-size="10"', svg)
    ]
    assert len(pts) >= 2
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dx = abs(pts[i][0] - pts[j][0])
            dy = abs(pts[i][1] - pts[j][1])
            assert dx >= 12 or dy >= 12, f"labels overprint at {pts[i]} / {pts[j]}"


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
