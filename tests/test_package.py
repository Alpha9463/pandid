"""Check package units: fs.package(), the boundary frame and its layout."""

import re
from collections.abc import Callable

import pytest

from pandid import (
    Column,
    ControlValve,
    Feed,
    Filter,
    Flowsheet,
    Mixer,
    Package,
    Product,
    Pump,
    ShellAndTubeExchanger,
    SpecError,
    Splitter,
    Tank,
    Valve,
    Vessel,
)
from pandid.document import equipment_table
from pandid.layout.conflicts import boxes_overlap
from pandid.package import DEPTH, MARGIN, boundary, frame
from pandid.portgeom import unit_box
from pandid.render.svg import PACKAGE_DASH
from pandid.render.weights import LineWeight
from pandid.routing import astar


def _one(packaged: bool = True) -> Flowsheet:
    """Build a dosing skid between a tank and a reactor, with a side feed."""
    fs = Flowsheet("One package")
    feed = fs.add(Feed("Feed"))
    tank = fs.add(Tank("T-300"))
    split = fs.add(Splitter("SP-1"))
    pump_a = fs.add(Pump("P-301A"))
    pump_b = fs.add(Pump("P-301B"))
    mix = fs.add(Mixer("MX-1"))
    filt = fs.add(Filter("F-301"))
    reactor = fs.add(Vessel("R-302", inputs=2))
    product = fs.add(Product("Product"))
    water = fs.add(Feed("Water"))
    pump_w = fs.add(Pump("P-305"))
    heater = fs.add(ShellAndTubeExchanger("E-306"))
    fs.connect(feed.outlet, tank.in_1)
    fs.connect(tank.outlet, split.inlet)
    fs.connect(split.out_1, pump_a.suction)
    fs.connect(split.out_2, pump_b.suction)
    fs.connect(pump_a.discharge, mix.in_1)
    fs.connect(pump_b.discharge, mix.in_2)
    fs.connect(mix.outlet, filt.inlet)
    fs.connect(filt.outlet, reactor.in_1)
    fs.connect(water.outlet, pump_w.suction)
    fs.connect(pump_w.discharge, heater.tube_in)
    fs.connect(heater.tube_out, reactor.in_2)
    fs.connect(reactor.outlet, product.inlet)
    if packaged:
        fs.package(
            "PK-301",
            [split, pump_a, pump_b, mix, filt],
            description="Dosing Package",
            reference="VENDOR DWG 4711",
        )
    return fs


def _two(packaged: bool = True) -> Flowsheet:
    """Build two skids in series, a valve in the second, and a make-up pump."""
    fs = Flowsheet("Two packages")
    feed = fs.add(Feed("Feed"))
    pump_1 = fs.add(Pump("P-101"))
    cooler = fs.add(ShellAndTubeExchanger("E-101"))
    drum = fs.add(Vessel("V-102"))
    pump_2 = fs.add(Pump("P-102"))
    filt = fs.add(Filter("F-201"))
    tank = fs.add(Tank("T-202", inputs=2))
    product = fs.add(Product("Product"))
    cws = fs.add(Feed("CWS"))
    cwr = fs.add(Product("CWR"))
    makeup = fs.add(Feed("Make-up"))
    pump_m = fs.add(Pump("P-900"))
    fs.connect(feed.outlet, pump_1.suction)
    fs.connect(pump_1.discharge, cooler.tube_in)
    fs.connect(cooler.tube_out, drum.in_1)
    fs.connect(cws.outlet, cooler.shell_in)
    fs.connect(cooler.shell_out, cwr.inlet)
    fs.connect(drum.outlet, pump_2.suction)
    valve = fs.add(Valve("HV-201"), on=fs.connect(pump_2.discharge, filt.inlet))
    fs.connect(filt.outlet, tank.in_1)
    fs.connect(makeup.outlet, pump_m.suction)
    fs.connect(pump_m.discharge, tank.in_2)
    fs.connect(tank.outlet, product.inlet)
    if packaged:
        fs.package("PK-100", [pump_1, cooler, drum], description="Cooling Package")
        fs.package(
            "PK-200", [pump_2, valve, filt], description="Filter Package", reference="VENDOR DWG 88"
        )
    return fs


def _three(packaged: bool = True) -> Flowsheet:
    """Build three skids feeding one header through control valves."""
    fs = Flowsheet("Three packages")
    mix = fs.add(Mixer("MX-1", n_inlets=3))
    fs.connect(mix.outlet, fs.add(Product("Product")).inlet)
    for k in range(1, 4):
        tank = fs.add(Tank(f"T-{k}01"))
        pump = fs.add(Pump(f"P-{k}01"))
        filt = fs.add(Filter(f"F-{k}01"))
        valve = fs.add(ControlValve(f"FV-{k}01"))
        fs.connect(fs.add(Feed(f"Feed {k}")).outlet, tank.in_1)
        fs.connect(tank.outlet, pump.suction)
        fs.connect(pump.discharge, filt.inlet)
        fs.connect(filt.outlet, valve.inlet)
        fs.connect(valve.outlet, mix.inlets[k - 1])
        if packaged:
            fs.package(f"PK-{k}00", [pump, filt], description=f"Package {k}")
    return fs


def _across(packaged: bool = True) -> Flowsheet:
    """Build the three trains with one package taking the first and last pumps."""
    fs = _three(packaged=False)
    if packaged:
        units = {u.name: u for u in fs.units}
        fs.package("PK-X", [units["P-101"], units["P-301"]])
    return fs


def _column(packaged: bool = True) -> Flowsheet:
    """Build a packaged column whose bottoms valve sits outside the package."""
    fs = Flowsheet("Column")
    column = fs.add(Column("C-1"))
    pump = fs.add(Pump("P-1"))
    fs.connect(fs.add(Feed("Feed")).outlet, column.feed_1)
    fs.connect(column.overhead, fs.add(Product("Overhead")).inlet)
    fs.add(Valve("HV-1"), on=fs.connect(column.bottoms, pump.suction))
    fs.connect(pump.discharge, fs.add(Product("Out")).inlet)
    if packaged:
        fs.package("PK-1", [column])
    return fs


def _pinned(build: Callable[[bool], Flowsheet]) -> Callable[[bool], Flowsheet]:
    """Return a build that pins every unit where automatic layout drew it."""

    def pinned(packaged: bool = True) -> Flowsheet:
        fs = build(packaged)
        fs.route()
        for u in fs.units:
            f = u.frame
            assert f is not None
            u.pin(port=None, x=f.x, y=f.y) if u.kind in ("feed", "product") else u.pin(x=f.x, y=f.y)
        return fs

    return pinned


SHEETS = {"one": _one, "two": _two, "three": _three, "across": _across, "column": _column}


def _inside(fs: Flowsheet) -> list[tuple[str, str]]:
    """Return each package and unit not in it drawn inside its frame."""
    out = []
    for pkg in fs.packages:
        box = frame(pkg)
        assert box is not None
        for u in fs.units:
            assert u.frame is not None
            if u not in pkg.units and boxes_overlap(unit_box(u, u.frame), box, -1.0):
                out.append((pkg.name, u.name))
    return out


def _sheet_with_a_skid() -> tuple[Flowsheet, Pump, Filter, Tank]:
    """Build a pump and filter after a tank."""
    fs = Flowsheet("Skid")
    tank = fs.add(Tank("T-1"))
    pump = fs.add(Pump("P-1"))
    filt = fs.add(Filter("F-1"))
    fs.connect(fs.add(Feed("Feed")).outlet, tank.in_1)
    fs.connect(tank.outlet, pump.suction)
    fs.connect(pump.discharge, filt.inlet)
    fs.connect(filt.outlet, fs.add(Product("Out")).inlet)
    return fs, pump, filt, tank


def test_package_returns_its_handle_and_lists_it_on_the_sheet():
    """Check that fs.package() returns a Package holding what was typed."""
    fs, pump, filt, _ = _sheet_with_a_skid()
    skid = fs.package(
        "PK-1", [pump, filt], description="Dosing Package", reference="VENDOR DWG 4711"
    )
    assert isinstance(skid, Package)
    assert (skid.name, skid.units) == ("PK-1", (pump, filt))
    assert (skid.description, skid.reference) == ("Dosing Package", "VENDOR DWG 4711")
    assert fs.packages == [skid]


@pytest.mark.parametrize(
    ("call", "error", "words"),
    [
        (lambda fs, u: fs.package(301, [u["P-1"]]), TypeError, "text"),
        (lambda fs, u: fs.package(" ", [u["P-1"]]), ValueError, "needs a tag"),
        (lambda fs, u: fs.package("T-1", [u["P-1"]]), ValueError, "already tags"),
        (lambda fs, u: fs.package("PK-1", [u["P-1"]]), ValueError, "already tags"),
        (lambda fs, u: fs.package("PK-2", []), ValueError, "holds no units"),
        (lambda fs, u: fs.package("PK-2", ["P-1"]), TypeError, "not a unit"),
        (lambda fs, u: fs.package("PK-2", [Pump("P-9")]), ValueError, "fs.add(P-9)"),
        (lambda fs, u: fs.package("PK-2", [u["P-1"], u["P-1"]]), ValueError, "twice"),
        (lambda fs, u: fs.package("PK-2", [u["F-1"]]), ValueError, "already in package PK-1"),
    ],
)
def test_a_refused_package_leaves_the_sheet_unchanged(call, error, words):
    """Check that each refusal names its cause and adds no package."""
    fs, pump, filt, tank = _sheet_with_a_skid()
    first = fs.package("PK-1", [filt])
    units = {u.name: u for u in fs.units}
    with pytest.raises(error, match=re.escape(words)):
        call(fs, units)
    assert fs.packages == [first]
    assert first.units == (filt,)
    assert [u.name for u in fs.units] == list(units)
    del pump, tank


def test_a_unit_may_not_take_a_package_tag():
    """Check that fs.add() refuses a unit tagged like a package."""
    fs, pump, _, _ = _sheet_with_a_skid()
    fs.package("PK-1", [pump])
    before = list(fs.units)
    with pytest.raises(ValueError, match="already tags package PK-1"):
        fs.add(Pump("PK-1"))
    assert fs.units == before


def test_the_frame_is_a_dash_dot_rectangle_at_the_detail_weight():
    """Check the frame's line type (ISO 15519-1 6.1) and weight (Table 1)."""
    fs = _one()
    svg = fs.to_svg()
    box = frame(fs.packages[0])
    assert box is not None
    group = re.search(r'<g id="packages">(.*?)</g>', svg, re.S)
    assert group is not None
    rect = re.search(
        r'<rect x="([\d.-]+)" y="([\d.-]+)" width="([\d.]+)" '
        r'height="([\d.]+)" fill="none" stroke="black" '
        r'stroke-width="([\d.]+)" stroke-dasharray="([\d.,]+)" />',
        group.group(1),
    )
    assert rect is not None
    x, y, w, h, width, dash = rect.groups()
    assert (float(x), float(y), float(x) + float(w), float(y) + float(h)) == pytest.approx(box)
    assert float(width) == LineWeight.DETAIL.width == 0.1 * 10
    # ISO 128-20 line type 10: a 12d dash, 3d gap, a dot and 3d gap.
    assert dash == PACKAGE_DASH == "12,3,0.5,3"
    # The frame is drawn behind the units.
    assert svg.index('<g id="packages">') < svg.index('<g id="units">')


def test_the_tag_is_outside_the_upper_left_corner_and_the_reference_inside_the_lower_left():
    """Check where the package tag (7.3.3) and the reference (7.3.2) go."""
    fs = _one()
    svg = fs.to_svg()
    x0, y0, x1, y1 = frame(fs.packages[0]) or (0, 0, 0, 0)

    def spot(text: str) -> tuple[float, float]:
        found = re.search(rf'<text x="([\d.-]+)" y="([\d.-]+)"[^>]*>{text}</text>', svg)
        assert found is not None, text
        return float(found.group(1)), float(found.group(2))

    tag_x, tag_y = spot("PK-301")
    assert tag_x == pytest.approx(x0) and y0 - 15 < tag_y < y0
    ref_x, ref_y = spot("VENDOR DWG 4711")
    assert x0 < ref_x < x0 + 10 and y1 - 10 < ref_y < y1
    # The members keep their own tags.
    for name in ("P-301A", "P-301B", "F-301"):
        spot(name)


@pytest.mark.parametrize("name", list(SHEETS))
def test_the_frame_holds_each_unit_with_its_margin(name):
    """Check that the frame clears every member box by the margin."""
    fs = SHEETS[name]()
    fs.route()
    for pkg in fs.packages:
        x0, y0, x1, y1 = frame(pkg) or (0, 0, 0, 0)
        for u in pkg.units:
            assert u.frame is not None
            bx0, by0, bx1, by1 = unit_box(u, u.frame)
            assert x0 + MARGIN <= bx0 + 1e-6 and bx1 <= x1 - MARGIN + 1e-6, u.name
            assert y0 + DEPTH <= by0 + 1e-6 and by1 <= y1 - DEPTH + 1e-6, u.name


@pytest.mark.parametrize("pinned", [False, True], ids=["automatic", "pinned"])
@pytest.mark.parametrize("name", list(SHEETS))
def test_no_other_unit_is_drawn_inside_a_frame(name, pinned):
    """Check one, two and three packages, laid out or pinned, draw clean."""
    build = _pinned(SHEETS[name]) if pinned else SHEETS[name]
    fs = build(True)
    fs.to_svg(diagram="p&id")
    assert _inside(fs) == []
    assert [i.code for i in fs.validate(diagram="p&id") if i.severity == "error"] == []


@pytest.mark.parametrize(
    ("name", "intruder"), [("one", "E-306"), ("across", "P-201"), ("column", "HV-1")]
)
def test_layout_moves_out_a_unit_the_frame_would_take(name, intruder):
    """Check a unit drawn inside the frame on the plain sheet is moved out."""
    plain = SHEETS[name](False)
    plain.route()
    packaged = SHEETS[name](True)
    pkg = packaged.packages[0]
    units = {u.name: u for u in plain.units}
    boxes = []
    for member in pkg.units:
        f = units[member.name].frame
        assert f is not None
        boxes.append(unit_box(units[member.name], f))
    would = boundary(pkg, boxes)
    there = units[intruder].frame
    assert there is not None
    assert boxes_overlap(unit_box(units[intruder], there), would, -1.0)

    packaged.route()
    assert _inside(packaged) == []


def _bypass() -> Flowsheet:
    """Build a packaged pump and filter with a bypass round them."""
    fs = Flowsheet("Bypass")
    split = fs.add(Splitter("SP-1"))
    mix = fs.add(Mixer("MX-1"))
    pump = fs.add(Pump("P-1"))
    filt = fs.add(Filter("F-1"))
    fs.connect(fs.add(Feed("Feed")).outlet, split.inlet)
    fs.connect(split.out_1, pump.suction)
    fs.connect(pump.discharge, filt.inlet)
    fs.connect(filt.outlet, mix.in_1)
    fs.connect(split.out_2, mix.in_2, name="BYPASS")
    fs.connect(mix.outlet, fs.add(Product("Out")).inlet)
    fs.package("PK-1", [pump, filt])
    return fs


def test_a_line_keeps_out_of_a_package_it_does_not_serve(monkeypatch):
    """Check the bypass routes round the package, and through it uncharged."""

    def through() -> bool:
        fs = _bypass()
        fs.route()
        x0, y0, x1, y1 = frame(fs.packages[0]) or (0, 0, 0, 0)
        bypass = next(s for s in fs.streams if s.name == "BYPASS")
        assert bypass.route is not None
        points = bypass.route.waypoints
        return any(
            x0 < (ax + bx) / 2 < x1 and y0 < (ay + by) / 2 < y1
            for (ax, ay), (bx, by) in zip(points, points[1:])
        )

    assert not through()
    monkeypatch.setattr(astar, "FENCE_PENALTY", 0.0)
    assert through()


def test_a_unit_inside_a_frame_it_is_not_in_is_an_error():
    """Check that validate() names the intruder and the call that fixes it."""
    fs, pump, filt, tank = _sheet_with_a_skid()
    fs.package("PK-1", [pump, filt])
    fs.route()
    box = frame(fs.packages[0])
    assert box is not None and pump.frame is not None and filt.frame is not None
    pump.pin(x=pump.frame.x, y=pump.frame.y)
    filt.pin(x=filt.frame.x, y=filt.frame.y)
    tank.pin(x=(box[0] + box[2]) / 2, y=box[3] - DEPTH - 1)
    fs.route()
    found = [i for i in fs.validate() if i.code == "package-encloses"]
    assert [i.severity for i in found] == ["error"]
    assert "T-1 is drawn inside the frame of package PK-1" in found[0].message
    assert "fs.package('PK-1', [...])" in found[0].message
    assert ".pin(x=..., y=...) on T-1" in found[0].message
    with pytest.raises(ValueError, match="package-encloses"):
        fs.to_svg()


def test_an_unlisted_balloon_on_a_member_is_reported_with_its_attach_call():
    """Check that a balloon the frame takes in is named with attach()."""
    fs, pump, filt, _ = _sheet_with_a_skid()
    fs.add_instrument("PI", 1, sensing=pump, face="N")
    fs.package("PK-1", [pump, filt])
    fs.route()
    found = [i.message for i in fs.validate() if i.code == "package-encloses"]
    assert len(found) == 1 and found[0].startswith("PI-1 is drawn inside")
    assert ".attach(<the P-1 unit>, face=..., offset=...)" in found[0]


def test_the_equipment_list_puts_a_package_above_its_units():
    """Check the package row comes where its first unit would, then its units."""
    fs = _one()
    rows = fs.equipment_list()
    assert [r["tag"] for r in rows] == [
        "T-300",
        "PK-301",
        "P-301A",
        "P-301B",
        "F-301",
        "R-302",
        "P-305",
        "E-306",
    ]
    assert rows[1] == {
        "tag": "PK-301",
        "description": "Dosing Package",
        "class": "Package",
        "variant": None,
    }
    assert equipment_table(fs).rows[1] == ("PK-301", "Dosing Package")
    assert equipment_table(fs, include=["PK-301", "F-301"]).rows == [
        ("PK-301", "Dosing Package"),
        ("F-301", "Filter"),
    ]


def test_a_package_without_a_description_is_listed_as_a_package_unit():
    """Check the default equipment-list text of a package."""
    fs, pump, _, _ = _sheet_with_a_skid()
    fs.package("PK-1", [pump])
    assert [r["description"] for r in fs.equipment_list() if r["tag"] == "PK-1"] == ["Package Unit"]


def test_a_spec_round_trips_its_packages():
    """Check to_dict() writes the packages and from_dict() rebuilds them."""
    fs = _two()
    spec = fs.to_dict()
    assert spec["packages"] == [
        {"name": "PK-100", "units": ["P-101", "E-101", "V-102"], "description": "Cooling Package"},
        {
            "name": "PK-200",
            "units": ["P-102", "HV-201", "F-201"],
            "description": "Filter Package",
            "reference": "VENDOR DWG 88",
        },
    ]
    again = Flowsheet.from_dict(spec)
    assert [
        (p.name, [u.name for u in p.units], p.description, p.reference) for p in again.packages
    ] == [
        ("PK-100", ["P-101", "E-101", "V-102"], "Cooling Package", ""),
        ("PK-200", ["P-102", "HV-201", "F-201"], "Filter Package", "VENDOR DWG 88"),
    ]
    assert again.to_dict() == spec


@pytest.mark.parametrize(
    ("entry", "words"),
    [
        ({"name": "PK-1"}, "packages[0] needs 'units'"),
        ({"name": "PK-1", "units": ["P-9"]}, "no unit named 'P-9'"),
        ({"name": "PK-1", "units": ["P-1"], "colour": "red"}, "unknown key 'colour'"),
        ({"name": "P-1", "units": ["P-1"]}, "packages[0]: 'P-1' already tags"),
    ],
)
def test_a_bad_package_entry_names_itself(entry, words):
    """Check that the spec reader refuses a bad packages: entry."""
    spec = {"name": "Skid", "units": [{"kind": "Pump", "name": "P-1"}], "packages": [entry]}
    with pytest.raises(SpecError, match=re.escape(words)):
        Flowsheet.from_dict(spec)


def test_drawio_draws_the_frame_as_an_unfilled_dash_dot_cell_behind_the_units():
    """Check the draw.io frame cell, its tag label and its reference child."""
    fs = _one()
    xml = fs.to_drawio()
    cell = re.search(r'<mxCell id="pk0" value="PK-301" style="([^"]*)"', xml)
    assert cell is not None
    style = cell.group(1)
    for key in (
        "fillColor=none",
        "dashed=1",
        "dashPattern=12 3 0.5 3",
        "verticalLabelPosition=top",
        "align=left",
    ):
        assert key in style
    assert '<mxCell id="pk0-ref" value="VENDOR DWG 4711"' in xml
    assert 'parent="pk0"' in xml
    assert xml.index('id="pk0"') < xml.index('id="u0"')


def test_the_drawing_holds_the_package_tag():
    """Check the canvas reaches the tag above a frame at the top of the sheet."""
    fs, pump, filt, tank = _sheet_with_a_skid()
    fs.package("PK-1", [tank, pump, filt])
    svg = fs.to_svg()
    view = re.search(r'viewBox="([\d.-]+) ([\d.-]+)', svg)
    tag = re.search(r'<text x="[\d.-]+" y="([\d.-]+)"[^>]*>PK-1</text>', svg)
    assert view is not None and tag is not None
    assert float(view.group(2)) < float(tag.group(1)) - 12
