"""The mxGraph stencil converter, and the loss it used to make in silence.

``scripts/mxgraph_to_svg.py`` walks a stencil's drawing directives with an
if/elif chain. Until #291 that chain had no ``else``, so seven directives fell
off the end without a word -- ``<dashed>`` among them, which is the only thing
on a filter or a strainer that says the thing in the line is a screen rather
than a plate. Twelve shipped symbols came out solid.

Nothing noticed, and the reason it could not is what these tests are mostly
about: the SVG backend inlines the *converted* artwork while the draw.io
backend writes a reference to the *original* stencil, which draw.io then draws
dashed. One flowsheet, two drawings, disagreeing about the equipment, and
``fs.warnings`` empty on both.

So there are two kinds of test here. The narrow ones pin each directive's
conversion. :func:`test_the_two_backends_draw_the_same_equipment` is the one a
user would actually have felt, and it is stated over the whole registry rather
than over the twelve, because the next stencil set vendored will have its own
twelve.
"""

from __future__ import annotations

import functools
import importlib.util
import pathlib
import xml.etree.ElementTree as ET

import pytest

from pandid.render.symbols import default_registry

ROOT = pathlib.Path(__file__).resolve().parent.parent
STENCILS = ROOT / "scripts" / "vendor_data" / "drawio"


@functools.lru_cache(maxsize=None)
def _converter():
    """Import ``scripts/mxgraph_to_svg.py`` by path.

    A dev-only script rather than part of the package, exactly as
    ``scripts/vendor_symbols.py`` and ``scripts/gen_devices.py`` are, and this
    is the loader ``tests/test_devices.py`` uses for that one.
    """
    path = ROOT / "scripts" / "mxgraph_to_svg.py"
    module_spec = importlib.util.spec_from_file_location("_pandid_script_mxgraph", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


#: A stroked line, so every specimen below has some ink for the pen to land on.
GEOM = '<path><move x="0" y="0"/><line x="10" y="10"/></path>'


def _shape(body: str, name: str = "Specimen") -> ET.Element:
    """One <shape> whose <foreground> is *body*."""
    return ET.fromstring(
        f'<shape name="{name}" w="100" h="100"><foreground>{body}</foreground></shape>'
    )


def _drawn(body: str, stroke_width: float = 2.0) -> list[ET.Element]:
    """The elements *body* converts to, in document order."""
    inner, *_ = _converter().convert_shape(_shape(body), stroke_width=stroke_width)
    return list(ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{inner}</svg>'))


# ---------------------------------------------------------------------------
# The guard: nothing falls off the end
# ---------------------------------------------------------------------------


def test_a_directive_the_converter_does_not_know_stops_the_conversion():
    """The fix. The dashes below are the symptom; this is the class of bug.

    A converter that discards what it does not recognise loses something new
    every time a stencil set is re-vendored, and loses it into a file that
    still parses and still draws.
    """
    with pytest.raises(ValueError, match="glow"):
        _drawn(f'<glow radius="4"/>{GEOM}<stroke/>')


def test_the_shape_that_could_not_be_converted_is_named():
    """A stencil set is fourteen files and eight hundred shapes."""
    with pytest.raises(ValueError, match="Liquid Filter"):
        _converter().convert_shape(_shape(f'<glow radius="4"/>{GEOM}', "Liquid Filter"))


@pytest.mark.parametrize("directive", sorted(_converter().DECLINED))
def test_a_declined_directive_is_written_down_and_changes_no_ink(directive):
    """The other half of the guard: a decision, not a gap.

    A directive this converter does not act on is named in ``DECLINED`` with
    the reason it changes nothing, so the difference from what draw.io draws is
    a sentence somebody can read and argue with rather than an omission nobody
    can see.
    """
    assert _converter().DECLINED[directive].strip(), f"<{directive}> is declined with no reason"
    plain = _drawn(f"{GEOM}<stroke/>")
    with_it = _drawn(f"<{directive}/>{GEOM}<stroke/>")
    assert [el.attrib for el in with_it] == [el.attrib for el in plain]


@pytest.mark.parametrize("path", sorted(STENCILS.glob("*.xml")), ids=lambda p: p.name)
def test_every_vendored_stencil_converts_without_a_directive_falling_off_the_end(path):
    """Every shape in the vendored set, not only the ones ``KIND_MAP`` draws.

    An unmapped shape is one ``KIND_MAP`` addition away from being shipped, and
    the point of the guard is that the addition fails loudly rather than
    quietly drawing something else.
    """
    for _name, shape in _converter().shapes_in(path):
        _converter().convert_shape(shape)


# ---------------------------------------------------------------------------
# The pen
# ---------------------------------------------------------------------------


def test_a_dashed_line_comes_out_dashed():
    assert _drawn(f'<dashed dashed="1"/>{GEOM}<stroke/>')[0].get("stroke-dasharray")


def test_a_dash_pattern_is_measured_in_pen_widths():
    """mxGraph multiplies a pattern by the pen, and so does this.

    That is why one ``pattern="2 2"`` serves a stencil drawn on a 40-unit
    module and one drawn on a 200-unit module. It matters more here than it
    does upstream: pandid draws these symbols far smaller than draw.io does, so
    a dash measured in units would come out as a grey smear on a strainer ten
    units wide.
    """
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
    """The cone strainer asks for a dash-dot screen with ``"6 3 0 3"``.

    A zero-length dash draws nothing at all under a butt cap, so the cap is
    load-bearing here rather than a nicety -- which is why ``<linecap>`` is
    acted on where ``<linejoin>`` is declined.
    """
    body = (
        f'<linecap cap="round"/><dashpattern pattern="6 3 0 3"/><dashed dashed="1"/>{GEOM}<stroke/>'
    )
    el = _drawn(body, stroke_width=1.0)[0]
    assert el.get("stroke-dasharray") == "6 3 0 3"
    assert el.get("stroke-linecap") == "round"


def test_a_stencil_may_draw_finer_than_the_sheet_weight_but_not_heavier():
    """A P&ID is drawn at one line weight, and detail is finer than it.

    The library holds every symbol to exactly that: the heaviest pen in a
    drawing is the sheet's (``tests/test_line_weight.py``). draw.io's own base
    pen is 1px against pandid's 2, so a stencil written to stand out against
    the thinner one would come out heavier still against this one.
    """
    assert _drawn(f'<strokewidth width="0.5"/>{GEOM}<stroke/>')[0].get("stroke-width") == "0.5"
    assert _drawn(f'<strokewidth width="4"/>{GEOM}<stroke/>')[0].get("stroke-width") == "2.0"


def test_save_and_restore_bracket_the_pen_as_well_as_the_fill():
    """The pen is canvas state, exactly as the fill colour is.

    "Liquid Ring Compressor" turns this into a real drawing: it opens a
    ``<save/>``, draws its casing heavy, and ``<restore/>``s before the rest of
    the shape. A restore that put back only the fill would carry the casing's
    pen through everything after it.
    """
    body = (
        f'<save/><dashed dashed="1"/><strokewidth width="0.5"/><fillcolor color="none"/>'
        f"{GEOM}<stroke/><restore/>{GEOM}<stroke/>"
    )
    inside, outside = _drawn(body)
    assert inside.get("stroke-dasharray") and inside.get("stroke-width") == "0.5"
    assert outside.get("stroke-dasharray") is None
    assert outside.get("stroke-width") == "2.0"


# ---------------------------------------------------------------------------
# The divergence a user would have felt
# ---------------------------------------------------------------------------


def _dashed_stencil_keys() -> set[str]:
    """The draw.io shape keys whose stencil draws part of itself dashed.

    Built here from the XML, by draw.io's own filing rule, rather than imported
    from the generator -- the same independence ``tests/test_drawio.py`` keeps
    for the same reason: a key derived from the thing it is checking agrees
    with itself whatever the rule says.
    """
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

_DRAWINGS = sorted(default_registry._symbols.items()) + [
    ((kind, f"{variant} [closed]"), sym)
    for (kind, variant), sym in sorted(default_registry._closed.items())
]
_IDS = [f"{kind}/{variant}" for (kind, variant), _ in _DRAWINGS]


def test_the_stencil_set_draws_something_dashed():
    """Guards the check below against passing on an empty set.

    ``stroke-dasharray`` appeared zero times in the whole of
    ``_vendored_symbols.py`` when #291 was raised, and a comparison of two
    empty answers is exactly the shape of test that would have agreed with it.
    """
    assert len(DASHED_STENCILS) > 10


@pytest.mark.parametrize("entry", _DRAWINGS, ids=_IDS)
def test_the_two_backends_draw_the_same_equipment(entry):
    """The SVG a symbol inlines says what its draw.io stencil says.

    ``to_svg()`` inlines the converted artwork; ``to_drawio()`` writes
    ``shape=<key>`` and lets draw.io draw the original. So every difference
    between the two is a sheet that changes what it depicts depending on which
    file the reader was sent, with nothing on either one saying so.

    Dashes are the axis this checks because they are the axis that was lost,
    and on these shapes a dash is not decoration: a screen drawn solid is a
    plate, and a filter drawn solid is a drum.
    """
    (kind, variant), sym = entry
    if not sym.drawio_shape:
        pytest.skip("drawn by hand rather than vendored, so there is no stencil to differ from")
    upstream = sym.drawio_shape in DASHED_STENCILS
    inlined = "stroke-dasharray" in sym.svg
    assert inlined == upstream, (
        f"{kind}/{variant}: draw.io draws {sym.drawio_shape} "
        f"{'dashed' if upstream else 'solid'} and the inlined SVG draws it "
        f"{'dashed' if inlined else 'solid'}, so one flowsheet exports two "
        f"drawings that disagree about the equipment"
    )
