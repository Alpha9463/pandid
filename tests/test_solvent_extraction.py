"""Check the extraction column and the mixer-settler."""

import xml.etree.ElementTree as ET

import pytest

from test_drawio import _inline_stencil, _model, _style

from pandid import ExtractionColumn, Feed, Flowsheet, MixerSettler, Product
from pandid.portgeom import port_faces, port_point
from pandid.render import symbols
from pandid.render.symbols import default_registry, overlay_boxes


def test_an_extraction_column_feeds_each_phase_at_its_end():
    """Check that the heavy phase enters the top stage and the light phase the bottom one."""
    column = ExtractionColumn("C-301", trays=12)
    assert column.internals == "sieve_tray"
    assert column.feed_stages == [1, 12]
    fs = Flowsheet("Extraction")
    heavy, light = fs.add(Feed("Aqueous Feed")), fs.add(Feed("Solvent"))
    fs.add(column)
    extract, raffinate = fs.add(Product("Extract")), fs.add(Product("Raffinate"))
    fs.connect(heavy.outlet, column.feed_1)
    fs.connect(light.outlet, column.feed_2)
    fs.connect(column.overhead, extract.inlet)
    fs.connect(column.bottoms, raffinate.inlet)
    fs.layout()

    top = port_point(column, column.frame, "feed_1")[1]
    bottom = port_point(column, column.frame, "feed_2")[1]
    assert column.frame is not None
    third = column.frame.h / 3
    assert top < column.frame.y + third, "the heavy phase enters below the top third"
    assert bottom > column.frame.y + 2 * third, "the light phase enters above the bottom third"
    assert [i for i in fs.validate() if i.severity == "error"] == []


def test_an_extraction_column_states_its_stages_only_with_internals():
    """Check that a bare shell keeps the even spread and a stated stage list wins."""
    assert ExtractionColumn("C-302", internals=None).feed_stages is None
    assert ExtractionColumn("C-303", feed_stages=[2, 7]).feed_stages == [2, 7]
    assert ExtractionColumn("C-304", n_feeds=3).feed_stages is None


def test_each_mixer_settler_nozzle_leaves_by_its_own_face():
    """Check that both phases enter the mixer and leave the settler where they settle."""
    unit = MixerSettler("MS-101")
    faces = {name: port_faces(unit, name)[0] for name in unit.ports}
    assert faces == {"light_in": "W", "heavy_in": "W", "light_out": "E", "heavy_out": "S"}
    body = default_registry.get("mixer_settler")
    # The light phase over the weir, the heavy phase before it.
    assert body.ports["light_out"][1] > body.height - symbols._MS_WEIR_H
    assert symbols.MS_MIXER_W < body.ports["heavy_out"][0] < symbols._MS_WEIR_X


def test_the_agitator_stirs_the_mixer_only():
    """Check that the default turbine hangs inside the mixer, and ``agitator=`` is a choice."""
    body = default_registry.get("mixer_settler")
    parts = default_registry.for_unit(MixerSettler("MS-101")).overlays
    assert [(o.group, o.name) for o in parts] == [(28, "turbine")]
    ((left, top, right, bottom),) = overlay_boxes(body, parts)
    assert 0 < left < right < symbols.MS_MIXER_W
    assert top == 0.0 and bottom < body.height
    assert default_registry.for_unit(MixerSettler("MS-102", agitator=None)).overlays == ()
    with pytest.raises(ValueError, match="paddle wheel"):
        MixerSettler("MS-103", agitator="paddle wheel")


def test_two_stages_draw_counter_current_and_are_scheduled():
    """Check two mixer-settlers in counter-current render clean and are listed."""
    fs = Flowsheet("Solvent extraction")
    pls = fs.add(Feed("Pregnant Leach Solution"))
    organic = fs.add(Feed("Stripped Organic"))
    e1 = fs.add(MixerSettler("E-1"))
    e2 = fs.add(MixerSettler("E-2"))
    loaded = fs.add(Product("Loaded Organic"))
    raffinate = fs.add(Product("Raffinate"))
    fs.connect(pls.outlet, e1.heavy_in)
    fs.connect(e1.heavy_out, e2.heavy_in)
    fs.connect(e2.heavy_out, raffinate.inlet)
    fs.connect(organic.outlet, e2.light_in)
    fs.connect(e2.light_out, e1.light_in)
    fs.connect(e1.light_out, loaded.inlet)

    assert 'id="sym_mixer_settler_' in fs.to_svg()
    assert [i for i in fs.validate() if i.severity == "error"] == []
    assert [row["tag"] for row in fs.equipment_list()] == ["E-1", "E-2"]


def _steps(d: str) -> list:
    """Return a path's commands as ``(command, numbers)`` pairs."""
    out, tokens = [], d.replace(",", " ").split()
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        n = {"M": 2, "L": 2, "A": 7, "Z": 0}[cmd]
        out.append((cmd, [round(float(t), 4) for t in tokens[i + 1 : i + 1 + n]]))
        i += 1 + n
    return out


def _stencil_steps(path: ET.Element) -> list:
    """Return a stencil path's steps in the same form as :func:`_steps`."""
    names = {"move": "M", "line": "L", "arc": "A", "close": "Z"}
    keys = {
        "move": ("x", "y"),
        "line": ("x", "y"),
        "arc": ("rx", "ry", "x-axis-rotation", "large-arc-flag", "sweep-flag", "x", "y"),
        "close": (),
    }
    return [
        (names[step.tag], [round(float(step.get(k, "nan")), 4) for k in keys[step.tag]])
        for step in path
    ]


def test_draw_io_gets_the_outline_the_sheet_draws():
    """Check that the draw.io export traces the drawing's own paths and rectangles."""
    unit = MixerSettler("MS-1")
    fs = Flowsheet("Export")
    fs.add(unit)
    cell = next(c for c in _model(fs, check=False).iter("mxCell") if c.get("value") == unit.name)
    stencil = _inline_stencil(_style(cell).get("shape", ""))
    assert stencil is not None, f"{unit.name} exports as a box, not its outline"
    drawn = ET.fromstring(default_registry.get(unit.kind, unit.variant).svg)
    paths = [_steps(el.get("d", "")) for el in drawn.iter() if el.tag == "path"]
    rects = [
        tuple(float(el.get(k, "nan")) for k in ("x", "y", "width", "height"))
        for el in drawn.iter()
        if el.tag == "rect"
    ]
    assert [_stencil_steps(p) for p in stencil.iter("path")] == paths
    assert [
        tuple(float(r.get(k, "nan")) for k in ("x", "y", "w", "h")) for r in stencil.iter("rect")
    ] == rects
