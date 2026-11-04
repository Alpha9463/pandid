"""Test the mxGraph stencil converter's directives and that both backends dash alike."""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET

import pytest

from pandid.render.symbols import default_registry
from test_symbol_invariants import _script

ROOT = pathlib.Path(__file__).resolve().parent.parent
STENCILS = ROOT / "scripts" / "vendor_data" / "drawio"


#: A stroked line, so every specimen below has some ink for the pen to land on.
GEOM = '<path><move x="0" y="0"/><line x="10" y="10"/></path>'


def _shape(body: str, name: str = "Specimen") -> ET.Element:
    """Build one <shape> whose <foreground> is *body*."""
    return ET.fromstring(
        f'<shape name="{name}" w="100" h="100"><foreground>{body}</foreground></shape>'
    )


def _drawn(body: str, stroke_width: float = 2.0) -> list[ET.Element]:
    """Return the elements *body* converts to, in document order."""
    inner, *_ = _script("mxgraph_to_svg").convert_shape(_shape(body), stroke_width=stroke_width)
    return list(ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{inner}</svg>'))


# --- unknown and declined directives ---


def test_a_directive_the_converter_does_not_know_stops_the_conversion():
    """Check that an unknown directive raises a ValueError naming it."""
    with pytest.raises(ValueError, match="glow"):
        _drawn(f'<glow radius="4"/>{GEOM}<stroke/>')


def test_the_shape_that_could_not_be_converted_is_named():
    """Check that a failed conversion names the shape."""
    with pytest.raises(ValueError, match="Liquid Filter"):
        _script("mxgraph_to_svg").convert_shape(
            _shape(f'<glow radius="4"/>{GEOM}', "Liquid Filter")
        )


@pytest.mark.parametrize("directive", sorted(_script("mxgraph_to_svg").DECLINED))
def test_a_declined_directive_is_written_down_and_changes_no_ink(directive):
    """Check that a declined directive has a stated reason and changes no ink."""
    assert _script("mxgraph_to_svg").DECLINED[directive].strip(), (
        f"<{directive}> is declined with no reason"
    )
    plain = _drawn(f"{GEOM}<stroke/>")
    with_it = _drawn(f"<{directive}/>{GEOM}<stroke/>")
    assert [el.attrib for el in with_it] == [el.attrib for el in plain]


@pytest.mark.parametrize("path", sorted(STENCILS.glob("*.xml")), ids=lambda p: p.name)
def test_every_vendored_stencil_converts_without_a_directive_falling_off_the_end(path):
    """Check that every shape in a vendored stencil file converts."""
    for _name, shape in _script("mxgraph_to_svg").shapes_in(path):
        _script("mxgraph_to_svg").convert_shape(shape)


# --- the pen ---


def test_a_dashed_line_comes_out_dashed():
    assert _drawn(f'<dashed dashed="1"/>{GEOM}<stroke/>')[0].get("stroke-dasharray")


def test_a_dash_pattern_is_measured_in_pen_widths():
    """Check that a dash pattern is multiplied by the stroke width."""
    body = f'<dashpattern pattern="2 3"/><dashed dashed="1"/>{GEOM}<stroke/>'
    assert _drawn(body, stroke_width=4.0)[0].get("stroke-dasharray") == "8 12"
    assert _drawn(body, stroke_width=1.0)[0].get("stroke-dasharray") == "2 3"


def test_dashes_turned_on_without_a_pattern_take_mxgraphs_own():
    body = f'<dashed dashed="1"/>{GEOM}<stroke/>'
    assert _drawn(body, stroke_width=2.0)[0].get("stroke-dasharray") == "6 6"


def test_dashed_zero_puts_the_pen_back_down():
    body = f'<dashed dashed="1"/>{GEOM}<stroke/><dashed dashed="0"/>{GEOM}<stroke/>'
    on, off = _drawn(body)
    assert on.get("stroke-dasharray")
    assert off.get("stroke-dasharray") is None


def test_a_zero_length_dash_keeps_the_round_cap_that_makes_it_a_dot():
    """Check that a dash-dot pattern keeps its zero-length dash and its round cap."""
    body = (
        f'<linecap cap="round"/><dashpattern pattern="6 3 0 3"/><dashed dashed="1"/>{GEOM}<stroke/>'
    )
    el = _drawn(body, stroke_width=1.0)[0]
    assert el.get("stroke-dasharray") == "6 3 0 3"
    assert el.get("stroke-linecap") == "round"


def test_a_stencil_may_draw_finer_than_the_sheet_weight_but_not_heavier():
    """Check that a stencil stroke width is clamped between half and one sheet weight."""
    assert _drawn(f'<strokewidth width="1.5"/>{GEOM}<stroke/>')[0].get("stroke-width") == "1.5"
    assert _drawn(f'<strokewidth width="0.5"/>{GEOM}<stroke/>')[0].get("stroke-width") == "1.0"
    assert _drawn(f'<strokewidth width="4"/>{GEOM}<stroke/>')[0].get("stroke-width") == "2.0"


def test_save_and_restore_bracket_the_pen_as_well_as_the_fill():
    """Check that restore puts back the dash and stroke width set after save."""
    body = (
        f'<save/><dashed dashed="1"/><strokewidth width="1.5"/><fillcolor color="none"/>'
        f"{GEOM}<stroke/><restore/>{GEOM}<stroke/>"
    )
    inside, outside = _drawn(body)
    assert inside.get("stroke-dasharray") and inside.get("stroke-width") == "1.5"
    assert outside.get("stroke-dasharray") is None
    assert outside.get("stroke-width") == "2.0"


# --- the fill and the shape ---

#: A square for the fill specimens to paint.
BOX = '<rect x="0" y="0" w="10" h="10"/>'


@pytest.mark.parametrize(
    ("body", "fills"),
    [
        (f"{BOX}<fillstroke/>", ["white"]),
        (f"{BOX}<stroke/>", ["none"]),
        (f"{BOX}<fill/>", ["white"]),
        (f'{BOX}<fillcolor color="#000000"/><fillstroke/>', ["#111"]),
        (f'{BOX}<fillcolor color="#000000"/><fill/>', ["#111"]),
        (f'{BOX}<fillcolor color="stroke"/><fillstroke/>', ["#111"]),
        (f'{BOX}<fillcolor color="none"/><fillstroke/>', ["none"]),
        (
            '<save/><rect x="0" y="0" w="4" h="4"/><fillcolor color="#000000"/><fillstroke/>'
            '<restore/><rect x="5" y="5" w="4" h="4"/><fillstroke/>',
            ["#111", "white"],
        ),
    ],
)
def test_a_fill_takes_the_paper_until_fillcolor_asks_for_ink(body, fills):
    """Check that a shape fills with paper until fillcolor sets ink, and restore puts it back."""
    assert [el.get("fill") for el in _drawn(body)] == fills


@pytest.mark.parametrize(
    "declared,aspect",
    [('aspect="fixed" ', "fixed"), ('aspect="variable" ', "variable"), ("", "variable")],
)
def test_the_converter_reports_a_stencil_shapes_aspect(declared, aspect):
    """Verify stencil conversion reports shape aspect behaviour."""
    shape = ET.fromstring(
        f'<shape {declared}w="100" h="50"><foreground>'
        f'<rect x="0" y="0" w="100" h="50"/><stroke/></foreground></shape>'
    )
    assert _script("mxgraph_to_svg").convert_shape(shape)[4] == aspect


# --- the two backends ---


def _dashed_stencil_keys() -> set[str]:
    """Return the draw.io shape keys whose stencil draws part of itself dashed."""
    keys = set()
    for path in sorted(STENCILS.glob("*.xml")):
        root = ET.parse(path).getroot()
        package = root.get("name")
        for shape in root.findall("shape"):
            drawn = []
            for section in ("background", "foreground"):
                sec = shape.find(section)
                if sec is not None:
                    drawn += [el for el in sec if el.tag == "dashed"]
            if drawn and drawn[-1].get("dashed", "1") == "1":
                keys.add(f"{package}.{shape.get('name')}".replace(" ", "_").lower())
    return keys


DASHED_STENCILS = _dashed_stencil_keys()

_DRAWINGS = [
    (key, sym)
    for key, sym in sorted(default_registry._symbols.items())
    + [
        ((kind, f"{variant} [closed]"), sym)
        for (kind, variant), sym in sorted(default_registry._closed.items())
    ]
    if sym.drawio_shape
]
_IDS = [f"{kind}/{variant}" for (kind, variant), _ in _DRAWINGS]


def test_the_stencil_set_draws_something_dashed():
    """Check that more than ten vendored stencils draw part of themselves dashed."""
    assert len(DASHED_STENCILS) > 10


@pytest.mark.parametrize("entry", _DRAWINGS, ids=_IDS)
def test_the_two_backends_draw_the_same_equipment(entry):
    """Check that a symbol's inlined SVG is dashed exactly when its draw.io stencil is."""
    (kind, variant), sym = entry
    upstream = sym.drawio_shape in DASHED_STENCILS
    inlined = "stroke-dasharray" in sym.svg
    assert inlined == upstream, (
        f"{kind}/{variant}: draw.io draws {sym.drawio_shape} "
        f"{'dashed' if upstream else 'solid'} and the inlined SVG draws it "
        f"{'dashed' if inlined else 'solid'}, so one flowsheet exports two "
        f"drawings that disagree about the equipment"
    )
