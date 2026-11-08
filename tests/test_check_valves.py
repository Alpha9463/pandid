"""Check the check valve forms: ISO 10628-2 items 22.2 to 22.4 and the forms practice draws."""

import base64
import re
import urllib.parse
import zlib

import pytest

from pandid import Flowsheet, devices, spec, units as U
from pandid.render.drawio import DrawioRenderer
from pandid.render.symbols import default_registry

# Every form sits on a 24.5 x 15 body whose top-left corner is at (3.75, 3.75),
# under the check dot centred on that corner; the seat is at (16, 11.25).
_CORNER_DOT = '<circle cx="3.75" cy="3.75" r="3.75" fill="#111"'
_SEAT_DOT = '<circle cx="16" cy="11.25" r="3.75" fill="#111"'
_CONES = '<path d="M 3.75 18.75 L 3.75 3.75 L 28.25 18.75 L 28.25 3.75 Z" fill="white"'
_BOX = '<rect x="3.75" y="3.75" width="24.5" height="15" fill="white"'

#: Each form's registry variant, and the marks that tell it from its neighbours.
_MARKS = {
    "lift": ("lift_check", [_CONES, _CORNER_DOT, _SEAT_DOT]),
    "swing": ("swing_check", [_CONES, _CORNER_DOT, _SEAT_DOT, '<path d="M 16 3.75 L 16 18.75"']),
    "swing_form_2": (
        "swing_check_form_2",
        [_BOX, _CORNER_DOT, '<path d="M 3.75 3.75 L 28.25 18.75"'],
    ),
    "ball": ("ball_check", [_CONES, _CORNER_DOT, '<circle cx="16" cy="11.25" r="5" fill="white"']),
    "dual_plate": (
        "dual_plate_check",
        [_BOX, _CORNER_DOT, '<path d="M 28.25 3.75 L 16 11.25 L 28.25 18.75"'],
    ),
    "stop": (
        "stop_check",
        [_CONES, _CORNER_DOT, _SEAT_DOT, '<path d="M 16 11.25 L 16 2.5 L 23.5 2.5"'],
    ),
    "foot": (
        "foot",
        [
            '<path d="M 18.75 24.5 L 3.75 24.5 L 18.75 0 L 3.75 0 Z" fill="white"',
            '<path d="M 11.25 24.5 L 11.25 29.5"',
            '<rect x="6.25" y="29.5" width="10" height="20" fill="white"',
            '<path d="M 6.25 29.5 L 16.25 49.5" fill="none" stroke="#111" stroke-width="2" '
            'stroke-dasharray="4 4"',
            '<circle cx="3.75" cy="24.5" r="3.75" fill="#111"',
        ],
    ),
}

#: The same marks in each form's draw.io outline.
_DRAWIO_CORNER = '<save/><fillcolor color="#111"/><ellipse x="0" y="0" w="7.5" h="7.5"/>'
_DRAWIO_SEAT = '<save/><fillcolor color="#111"/><ellipse x="12.25" y="7.5" w="7.5" h="7.5"/>'
_DRAWIO_MARKS = {
    "lift": [_DRAWIO_CORNER, _DRAWIO_SEAT],
    "swing": [_DRAWIO_CORNER, _DRAWIO_SEAT, '<move x="16" y="3.75"/><line x="16" y="18.75"/>'],
    "swing_form_2": [
        _DRAWIO_CORNER,
        '<rect x="3.75" y="3.75" w="24.5" h="15"/>',
        '<move x="3.75" y="3.75"/><line x="28.25" y="18.75"/>',
    ],
    "ball": [_DRAWIO_CORNER, '<ellipse x="11" y="6.25" w="10" h="10"/>'],
    "dual_plate": [
        _DRAWIO_CORNER,
        '<rect x="3.75" y="3.75" w="24.5" h="15"/>',
        '<move x="28.25" y="3.75"/><line x="16" y="11.25"/><line x="28.25" y="18.75"/>',
    ],
    "stop": [
        _DRAWIO_CORNER,
        _DRAWIO_SEAT,
        '<move x="16" y="11.25"/><line x="16" y="2.5"/><line x="23.5" y="2.5"/>',
    ],
    "foot": [
        '<save/><fillcolor color="#111"/><ellipse x="0" y="20.75" w="7.5" h="7.5"/>',
        '<rect x="6.25" y="29.5" w="10" h="20"/>',
        '<save/><dashed dashed="1"/><path><move x="6.25" y="29.5"/><line x="16.25" y="49.5"/>',
    ],
}


@pytest.mark.parametrize("form", sorted(_MARKS))
def test_each_form_draws_the_marks_that_tell_it_apart(form):
    """Draw each form's body, its check dot and its own mark where they are stated."""
    variant, marks = _MARKS[form]
    valve = devices.CheckValve("NRV-1", variant=form)
    assert valve.variant == variant
    svg = default_registry.for_unit(valve).svg
    for mark in marks:
        assert mark in svg, mark


@pytest.mark.parametrize("form", sorted(_MARKS))
def test_no_form_draws_a_neighbour_s_mark(form):
    """Keep the hinge, the ball, the plates and the handwheel each on its own form."""
    svg = default_registry.get("valve", _MARKS[form][0]).svg
    own = set(_MARKS[form][1])
    for other, (_, marks) in _MARKS.items():
        for mark in set(marks) - own:
            if mark not in (_CONES, _BOX, _CORNER_DOT, _SEAT_DOT):
                assert mark not in svg, (form, other, mark)


@pytest.mark.parametrize("form", sorted(_DRAWIO_MARKS))
def test_draw_io_draws_each_form_s_marks(form):
    """Export each form's dots filled, its strainer screen dashed and its marks in place."""
    fs = Flowsheet("checks")
    fs.add(devices.CheckValve("NRV-1", variant=form)).pin(x=100, y=100)
    fs.layout()
    cell = next(
        line for line in DrawioRenderer().render(fs).splitlines() if 'value="NRV-1"' in line
    )
    packed = re.search(r"shape=stencil\(([^)]*)\)", cell)
    assert packed is not None
    outline = urllib.parse.unquote(
        zlib.decompressobj(-15).decompress(base64.b64decode(packed.group(1))).decode("ascii")
    )
    for mark in _DRAWIO_MARKS[form]:
        assert mark in outline, mark


def test_a_straight_check_runs_through_its_body_under_the_dot():
    """Pipe a straight form through the middle of its body, the dot overhanging its corner."""
    sym = default_registry.get("valve", "swing_check")
    assert (sym.width, sym.height) == (28.25, 18.75)
    assert sym.ports == {"inlet": (3.75, 11.25), "outlet": (28.25, 11.25), "actuator": (16, 0)}


def test_the_foot_valve_stands_over_its_strainer():
    """Rise from the strainer's foot to the body's top, and refuse to be turned."""
    sym = default_registry.get("valve", "foot")
    assert (sym.width, sym.height) == (18.75, 49.5)
    assert (sym.ports["inlet"], sym.ports["outlet"]) == ((11.25, 49.5), (11.25, 0))
    assert sym.gravity_fixed


def test_the_iso_forms_carry_their_registration_numbers():
    numbers = {
        form: default_registry.get("valve", variant).iso_reg
        for form, (variant, _) in _MARKS.items()
    }
    assert numbers == {
        "lift": "X2113",
        "swing": "X8078",
        "swing_form_2": "X8165",
        "ball": "",
        "dual_plate": "",
        "stop": "",
        "foot": "",
    }


@pytest.mark.parametrize("form", sorted(_MARKS))
def test_a_check_form_has_no_fail_position(form):
    with pytest.raises(ValueError, match="no actuator"):
        U.Valve("NRV-1", variant=_MARKS[form][0], fail="closed")


@pytest.mark.parametrize("form", sorted(_MARKS))
def test_a_normally_closed_check_form_says_so_in_letters(form):
    """Letter a closed check form NC rather than darken it (ISO 15519-1 11.4.5)."""
    fs = Flowsheet("nc")
    fs.add(devices.CheckValve("NRV-1", variant=form, normal_position="closed")).pin(x=100, y=100)
    assert ">NC</text>" in fs.to_svg()


@pytest.mark.parametrize("form", sorted(_MARKS))
def test_a_check_form_round_trips_through_a_spec(form):
    fs = Flowsheet("round trip")
    fs.add(devices.CheckValve("NRV-1", variant=form))
    written = spec.to_dict(fs)
    rebuilt = Flowsheet.from_dict(written).units[0]
    assert (type(rebuilt), rebuilt.variant) == (devices.CheckValve, _MARKS[form][0])
    assert spec.to_dict(Flowsheet.from_dict(written)) == written
