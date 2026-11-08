"""Test symbol composition from ISO 10628-2 group 26-29 parts and the registry's ISO rows."""

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace

import pytest

from pandid import Flowsheet, units
from pandid.render.iso_parts import SUPPORTS
from pandid.render.svg import SvgRenderer
from pandid.render.symbols import (
    COMPOSED_APPARATUS,
    PART_GROUPS,
    IsoPart,
    Overlay,
    OverlayPart,
    Symbol,
    SymbolRegistry,
    compose,
    default_registry,
)

# Four genuine group 26-29 rows, since :class:`IsoPart` refuses an invented number.
TRAY = IsoPart(27, "27.1", "C2044", "Tray (general)")
PACKING = IsoPart(27, "27.8", "X8141", "Packing")
TURBINE = IsoPart(28, "28.10", "C2027", "Agitator, turbine type")
SETTLING = IsoPart(29, "29.1", "C2028", "Gravity type, settling type")

#: pandid's name for each part.
NAMES = {TRAY: "tray", PACKING: "packing", TURBINE: "turbine", SETTLING: "gravity"}


def part(iso, **kwargs):
    """Return a part with placeholder artwork: a horizontal rule in a 40 x 10 box."""
    kwargs.setdefault("name", NAMES[iso])
    kwargs.setdefault(
        "svg",
        '<g id="part"><line x1="0" y1="5" x2="40" y2="5" stroke="black" stroke-width="1.5"/></g>',
    )
    kwargs.setdefault("width", 40.0)
    kwargs.setdefault("height", 10.0)
    return OverlayPart(iso=iso, **kwargs)


def body(**kwargs):
    """A plain 100 x 200 body with one nozzle per face."""
    kwargs.setdefault(
        "svg",
        '<g id="sym_test_body"><rect x="0" y="0" width="100" height="200" '
        'fill="none" stroke="black" stroke-width="2"/></g>',
    )
    kwargs.setdefault("width", 100.0)
    kwargs.setdefault("height", 200.0)
    kwargs.setdefault(
        "ports", {"feed": (0.0, 40.0), "bottoms": (50.0, 200.0), "vapour": (50.0, 0.0)}
    )
    return Symbol(**kwargs)


def transforms(svg):
    """Every ``transform`` in a composed drawing, outermost first."""
    return re.findall(r'transform="([^"]+)"', svg)


# ---------------------------------------------------------------- the rule


def test_the_part_groups_are_the_four_iso_names_them():
    assert sorted(PART_GROUPS) == [26, 27, 28, 29]


def test_the_one_apparatus_iso_composes_itself_is_admitted_by_item():
    """Check that item 20.6 is the one apparatus admitted as a part, and its neighbours are not."""
    assert IsoPart(20, "20.6", "C0082", "Electric motor (general)").group == 20
    assert set(COMPOSED_APPARATUS) == {"20.6"}
    for group, item, reg, name in (
        (20, "20.1", "C0080", "Turbine (general)"),
        (20, "20.7", "C0083", "Generator (general)"),
        (8, "8.10", "X2618", "Separator, cyclone type"),
    ):
        with pytest.raises(ValueError, match="not one of the part groups"):
            IsoPart(group, item, reg, name)


@pytest.mark.parametrize("reg", ["2062", "301", "C2044", "X2618", "X8141"])
def test_every_namespace_clause_5_declares_is_accepted(reg):
    """``nnn``, ``nnnn``, ``Cnnnn``, ``X2nnn`` and ``X8nnn``."""
    assert IsoPart(27, "27.1", reg, "a part").reg == reg


@pytest.mark.parametrize("reg", ["", "vortex", "27.1", "X1234", "CC2044", "X20000"])
def test_a_mark_with_no_registration_number_cannot_become_a_part(reg):
    """Check that a part without a registration number is refused."""
    with pytest.raises(ValueError, match="not a registration number"):
        IsoPart(29, "29.1", reg, "a mark")


def test_an_item_number_has_to_be_in_the_group_it_claims():
    with pytest.raises(ValueError, match="not in group 27"):
        IsoPart(27, "29.1", "C2028", "Gravity type, settling type")


def test_a_part_has_to_say_what_the_standard_calls_it():
    with pytest.raises(ValueError, match="the standard's own descriptor"):
        IsoPart(27, "27.1", "C2044", "   ")


# ---------------------------------------------------------------- placement


def test_the_placement_is_proportional_so_a_stretched_body_carries_its_parts():
    """Check that a part placed by fractions moves with the body's height."""
    tall = compose(
        body(height=400.0, ports={"feed": (0.0, 80.0)}),
        [(Overlay(27, "tray", 0.15, 0.30, 0.70, 0.05), part(TRAY))],
    )
    short = compose(body(), [(Overlay(27, "tray", 0.15, 0.30, 0.70, 0.05), part(TRAY))])
    assert re.search(r"translate\(15,(\d+)\)", tall.svg).group(1) == "120"
    assert re.search(r"translate\(15,(\d+)\)", short.svg).group(1) == "60"


def test_a_scaled_part_keeps_the_line_weight_its_author_drew_it_at():
    """Check that a scaled part keeps the line weight it was drawn at."""
    sym = compose(body(), [(Overlay(27, "tray", 0.1, 0.5, 0.1, 0.0125), part(TRAY))])
    placed = sym.svg[sym.svg.index('<g transform="translate(10,100)') :]
    scale = re.search(r"scale\(([\d.]+),([\d.]+)\)", placed)
    factor = (float(scale.group(1)) * float(scale.group(2))) ** 0.5
    drawn = float(re.search(r'stroke-width="([\d.]+)"', placed).group(1))
    assert drawn * factor == pytest.approx(1.5, rel=1e-4)


def test_a_part_whose_shape_carries_meaning_is_not_distorted():
    """Check that a non-stretchable part is scaled evenly and centred."""
    sym = compose(
        body(),
        [(Overlay(28, "turbine", 0.0, 0.0, 1.0, 0.1), part(TURBINE, stretchable=False))],
    )
    # 100 x 20 offered to a 40 x 10 part: an even scale of 2, centred in the 100.
    assert transforms(sym.svg) == ["translate(10,0) scale(2,2)"]

    tighter = compose(
        body(),
        [(Overlay(28, "turbine", 0.0, 0.0, 1.0, 0.05), part(TURBINE, stretchable=False))],
    )
    # 100 x 10: an even scale of 1, the 40-wide part centred in the 100.
    assert transforms(tighter.svg) == ["translate(30,0) scale(1,1)"]


def test_a_part_that_may_not_be_reshaped_holds_the_whole_symbol_to_its_aspect():
    """Check that one non-stretchable part makes the whole composition non-stretchable."""
    assert body().stretchable
    loose = compose(body(), [(Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05), part(TRAY))])
    assert loose.stretchable
    fixed = compose(
        body(),
        [(Overlay(28, "turbine", 0.1, 0.5, 0.8, 0.2), part(TURBINE, stretchable=False))],
    )
    assert not fixed.stretchable


def test_a_part_can_make_the_body_gravity_fixed_and_directional():
    """Check that a gravity-fixed, directional part makes the composition so."""
    plain = body()
    assert not plain.gravity_fixed and not plain.directional
    sym = compose(
        plain,
        [
            (
                Overlay(29, "gravity", 0.3, 0.3, 0.4, 0.3),
                part(SETTLING, gravity_fixed=True, directional=True),
            )
        ],
    )
    assert sym.gravity_fixed and sym.directional


def test_two_parts_land_on_one_body_in_the_order_they_are_given():
    """Check that two parts are placed and listed in the order given."""
    sym = compose(
        body(),
        [
            (Overlay(27, "tray", 0.1, 0.2, 0.8, 0.05), part(TRAY)),
            (Overlay(27, "packing", 0.1, 0.6, 0.8, 0.05), part(PACKING)),
        ],
    )
    assert [t.split(")")[0] for t in transforms(sym.svg)] == [
        "translate(10,40",
        "translate(10,120",
    ]
    assert [o.name for o in sym.overlays] == ["tray", "packing"]


# ---------------------------------------------------------------- the box


def test_a_part_inside_the_body_leaves_the_box_exactly_as_it_was():
    """The common case, and it costs nothing: no wrapper, no shift."""
    sym = compose(body(), [(Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05), part(TRAY))])
    assert (sym.width, sym.height) == (100.0, 200.0)
    assert sym.ports["feed"] == (0.0, 40.0)
    assert transforms(sym.svg) == ["translate(10,100) scale(2,1)"]


def test_a_part_drawn_outside_the_body_grows_the_box_and_moves_the_body_into_it():
    """Check that a part above the body grows the box and moves the body and its nozzles down."""
    sym = compose(
        body(ports={"bottoms": (50.0, 200.0)}),
        [(Overlay(28, "turbine", 0.3, -0.1, 0.4, 0.1), part(TURBINE))],
    )
    assert (sym.width, sym.height) == (100.0, 220.0)
    assert sym.ports["bottoms"] == (50.0, 220.0)
    # The body wrapped in the shift, then the part at the top of the new box.
    assert transforms(sym.svg) == ["translate(0,20)", "translate(30,0) scale(1,2)"]


def test_growing_the_box_may_not_move_a_nozzle_onto_another_face():
    """Check that growing the box is refused when it moves a nozzle onto another face."""
    with pytest.raises(ValueError, match="grows the box"):
        compose(
            body(ports={"relief": (10.0, 0.0), "bottoms": (50.0, 200.0)}),
            [(Overlay(28, "turbine", 0.3, -0.5, 0.4, 0.5), part(TURBINE))],
        )


# ---------------------------------------------------------------- ports


def test_an_internal_and_a_characteristic_bring_no_connection():
    """Nothing is ever routed to a tray or to a settling arrow."""
    sym = compose(
        body(),
        [
            (Overlay(27, "tray", 0.1, 0.2, 0.8, 0.05), part(TRAY)),
            (Overlay(29, "gravity", 0.3, 0.5, 0.4, 0.2), part(SETTLING)),
        ],
    )
    assert sorted(sym.ports) == ["bottoms", "feed", "vapour"]


def test_an_agitator_brings_its_drive_connection():
    """Check that a part's own nozzle is added to the composition at its placed point."""
    sym = compose(
        body(),
        [
            (
                Overlay(28, "turbine", 0.3, 0.1, 0.4, 0.1),
                part(TURBINE, ports={"drive": (20.0, 0.0)}),
            )
        ],
    )
    assert sorted(sym.ports) == ["bottoms", "drive", "feed", "vapour"]
    # 0.3 x 100 across plus 20 of the part's own scaled by 40 over 40.
    assert sym.ports["drive"] == (50.0, 20.0)


def test_a_part_may_not_take_over_a_nozzle_the_body_already_has():
    """Two nozzles under one name is a stream drawn to whichever survived."""
    with pytest.raises(ValueError, match="the body already has one"):
        compose(
            body(),
            [
                (
                    Overlay(28, "turbine", 0.3, 0.1, 0.4, 0.1),
                    part(TURBINE, ports={"feed": (20.0, 0.0)}),
                )
            ],
        )


def test_a_parts_nozzle_has_to_be_on_the_part():
    with pytest.raises(ValueError, match="outside the"):
        part(TURBINE, ports={"drive": (200.0, 0.0)})


def test_the_body_keeps_its_faceless_and_series_declarations():
    """A part adds artwork and connections; it does not restate the body."""
    from pandid.render.symbols import PortSeries

    plain = body(
        ports={"bottoms": (50.0, 200.0)},
        port_series=(PortSeries("feed_", "W", singular="feed"),),
        label_pos="center",
    )
    sym = compose(plain, [(Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05), part(TRAY))])
    assert sym.port_series == plain.port_series
    assert sym.label_pos == "center"


# ---------------------------------------------------------------- registry


@pytest.fixture
def registry():
    """Return a registry holding the test body and the four parts above, and no shipped parts."""
    reg = SymbolRegistry()
    reg._parts.clear()
    reg.register("composition_test", body())
    for iso in (TRAY, PACKING, TURBINE, SETTLING):
        reg.register_part(part(iso))
    return reg


def test_a_part_is_keyed_by_its_iso_group_and_its_name(registry):
    """A name is only unique inside its group."""
    assert registry.part(27, "tray").iso is TRAY
    assert registry.part_names(27) == ["packing", "tray"]
    assert registry.part_names(28) == ["turbine"]
    # Sorted by key: group, then name.
    assert [p.iso.reg for p in registry.parts()] == ["X8141", "C2044", "C2027", "C2028"]


def test_a_part_nobody_registered_is_refused_with_the_ones_that_are(registry):
    with pytest.raises(ValueError, match="did you mean 'tray'"):
        registry.part(27, "trey")
    with pytest.raises(ValueError, match=r"group 26 parts: \(none\)"):
        registry.part(26, "skirt")


def test_no_overlays_gives_the_body_back_unchanged(registry):
    """The zero case, and the one every shipped symbol is in."""
    assert registry.composed("composition_test") is registry.get("composition_test")


def test_a_composition_is_built_once_and_shared(registry):
    """Port resolution asks for a unit's symbol on every call."""
    overlays = (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
    first = registry.composed("composition_test", "default", overlays)
    assert registry.composed("composition_test", "default", overlays) is first


def test_re_registering_a_body_or_a_part_drops_the_compositions_using_it(registry):
    overlays = (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
    first = registry.composed("composition_test", "default", overlays)
    registry.register_part(part(TRAY))
    assert registry.composed("composition_test", "default", overlays) is not first
    second = registry.composed("composition_test", "default", overlays)
    registry.register("composition_test", body())
    assert registry.composed("composition_test", "default", overlays) is not second


#: Attribute of the mark added to a re-registered drawing.
MARK = 'class="re-registered"'


def _marked(svg: str) -> str:
    """Return ``svg`` with a mark added inside its group."""
    return svg.removesuffix("</g>") + f'<path {MARK} d="M 0 0"/></g>'


def _drawn(unit: units.Unit) -> str:
    """Return ``unit`` drawn alone on a sheet."""
    fs = Flowsheet("redrawn")
    fs.add(unit)
    return fs.to_svg()


@pytest.mark.parametrize(("kind", "make"), [("tank", units.Tank), ("vessel", units.Vessel)])
def test_a_tank_or_vessel_is_drawn_with_the_body_registered_now(
    kind: str, make: Callable[[str], units.Unit]
) -> None:
    """Check that a tank or vessel is drawn with the body registered now."""
    shipped = default_registry.get(kind)
    assert MARK not in _drawn(make("X-1"))
    default_registry.register(kind, replace(shipped, svg=_marked(shipped.svg)))
    try:
        assert MARK in _drawn(make("X-1"))
    finally:
        default_registry.register(kind, shipped)
    assert MARK not in _drawn(make("X-1"))


def test_a_vessel_is_drawn_with_the_part_registered_now() -> None:
    """Check that a vessel is drawn with the part registered now."""
    shipped = default_registry.part(26, "leg")
    assert MARK not in _drawn(units.Vessel("V-1", supports="leg"))
    default_registry.register_part(replace(shipped, svg=_marked(shipped.svg)))
    try:
        assert MARK in _drawn(units.Vessel("V-1", supports="leg"))
    finally:
        default_registry.register_part(shipped)
    assert MARK not in _drawn(units.Vessel("V-1", supports="leg"))


def test_a_unit_that_names_no_parts_draws_what_it_always_drew(registry):
    """Check that a unit with no overlays is drawn with the bare body."""

    class Body(units.Unit):
        kind = "composition_test"

    assert registry.for_unit(Body("X-1")) is registry.get("composition_test")


def test_a_unit_that_names_parts_is_drawn_with_them(registry):
    class Body(units.Unit):
        kind = "composition_test"

    unit = Body("X-1")
    unit.overlays = (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
    assert registry.for_unit(unit).overlays == unit.overlays


# ---------------------------------------------------------------- identity


def test_a_composition_needs_a_definition_of_its_own(registry):
    """Check that each composition gets its own definition id."""
    bare = registry.get("composition_test")
    one = registry.composed(
        "composition_test", "default", (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
    )
    two = registry.composed(
        "composition_test", "default", (Overlay(27, "tray", 0.1, 0.6, 0.8, 0.05),)
    )
    assert one.id_suffix != bare.id_suffix
    assert one.id_suffix != two.id_suffix
    assert re.fullmatch(r"_c[0-9a-f]{8}", one.id_suffix)


def test_the_definition_id_does_not_depend_on_the_process_hash_seed():
    """Check that the definition id is the same under two ``PYTHONHASHSEED`` values."""
    script = (
        "from pandid.render.symbols import *\n"
        "p = OverlayPart(name='tray', iso=IsoPart(27, '27.1', 'C2044', 'Tray'),"
        ' svg=\'<g id="p"><line x1="0" y1="5" x2="40" y2="5"'
        ' stroke="black" stroke-width="1.5"/></g>\', width=40.0, height=10.0)\n'
        'b = Symbol(svg=\'<g id="b"><rect x="0" y="0" width="100"'
        ' height="200" fill="none" stroke="black" stroke-width="2"/></g>\','
        " width=100.0, height=200.0)\n"
        "print(compose(b, [(Overlay(27, 'tray', 0.1, 0.5, 0.8, 0.05), p)]).id_suffix)\n"
    )
    seen = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": ""},
        ).stdout.strip()
        for seed in ("0", "12345")
    }
    assert len(seen) == 1


def test_a_composition_is_not_the_symbol_it_was_composed_onto(registry):
    """Check that a composition claims no registration number unless one is stated."""
    overlays = (Overlay(29, "gravity", 0.3, 0.3, 0.4, 0.2),)
    assert registry.composed("composition_test", "default", overlays).iso_reg == ""
    stated = compose(
        body(iso_reg="301"),
        [(Overlay(29, "gravity", 0.3, 0.3, 0.4, 0.2), part(SETTLING))],
        iso_reg="X8125",
    )
    assert stated.iso_reg == "X8125"


# ---------------------------------------------------------------- backends


def test_a_composed_symbol_names_no_drawio_stencil():
    """Check that a composed symbol names no draw.io stencil."""
    stencilled = body(drawio_shape="mxgraph.pid.vessels.tower")
    sym = compose(stencilled, [(Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05), part(TRAY))])
    assert stencilled.drawio_shape
    assert sym.drawio_shape == ""
    assert sym.overlays  # ...and this is what the exporter draws instead


def test_a_composed_symbol_renders_through_the_svg_backend():
    """Check that a unit with a part renders through the SVG backend."""

    class Body(units.Unit):
        kind = "composition_test"
        PORTS = [("feed", "inlet", "feed"), ("bottoms", "outlet", "liquid")]

    default_registry.register(Body.kind, body())
    try:
        fs = Flowsheet("composition")
        unit = Body("X-1")
        unit.overlays = (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
        fs.add(unit)
        fs.layout()
        svg = SvgRenderer().render(fs)
        assert 'id="sym_composition_test_c' in svg
        # The part's own rule, drawn inside the body's definition.
        assert "<line" in svg
    finally:
        default_registry._symbols.pop((Body.kind, "default"), None)
        default_registry._composed.clear()


# ------------------------------------------------- what the registry composes


def test_the_registry_composes_exactly_the_rows_ISO_gives_a_number_to():
    """Check that the registry composes exactly the rows ISO numbers."""
    composed = {
        f"{kind}/{variant}": sym.iso_reg
        for (kind, variant), sym in default_registry._symbols.items()
        if sym.overlays
    }
    assert composed == {
        "separator/gravity": "X8031",
        "separator/electrostatic": "X8125",
        "separator/electromagnetic": "X8126",
        "crusher/hammer": "X8045",
        "crusher/impact": "X8046",
        "crusher/jaw": "X8047",
        "crusher/roller": "X8048",
        "crusher/cone": "X8049",
        "mill/hammer": "X8050",
        "mill/impact": "X8051",
        "mill/roller": "X8053",
        "mill/vibration": "X8054",
    }


def test_the_three_group_11_bodies_are_the_outline_table_2_draws():
    """Check the group 11 trapezoid and the mark that tells each of its three bodies apart."""
    trapezoid = "M 0 0 L 100 0 L 80 60 L 20 60 Z"
    general = default_registry.get("crushing_machine")
    crusher = default_registry.get("crusher")
    mill = default_registry.get("mill")
    for sym in (general, crusher, mill):
        assert (sym.width, sym.height) == (100.0, 60.0)
        assert trapezoid in sym.svg
        # Fed at the mouth, discharging at the throat, driven from the east.
        assert sym.ports == {"feed": (50.0, 0.0), "discharge": (50.0, 60.0), "drive": (90.0, 30.0)}
    assert general.iso_reg == "X8084"
    assert "M 20 0 L 20 60" not in general.svg
    assert "M 25 0 L 7.6923" not in general.svg
    assert "M 20 0 L 20 60 M 80 0 L 80 60" in crusher.svg
    assert "M 25 0 L 7.6923 23.0769 M 75 0 L 92.3077 23.0769" in mill.svg
    # The vibration mill is the mill body with X8054's drum on it.
    drum = default_registry.get("mill", "vibration")
    assert '<circle cx="50" cy="30" r="20"' in drum.svg


def test_the_group_9_bodies_are_the_outline_table_2_draws():
    """Check each group 9 centrifuge against its row, drawing for drawing."""
    ink = 'fill="none" stroke="#111" stroke-width="2"'
    square = '<path d="M 0 0 L 80 0 L 80 80 L 0 80 Z" fill="white" stroke="#111" stroke-width="2"/>'
    square_side = (
        '<path d="M 10 0 L 90 0 L 90 80 L 10 80 Z" fill="white" stroke="#111" stroke-width="2"/>'
    )
    top_ports = {"feed": (40.0, 0.0), "overflow": (80.0, 20.0), "underflow": (40.0, 90.0)}
    side_ports = {"feed": (0.0, 40.0), "overflow": (90.0, 20.0), "underflow": (80.0, 80.0)}

    # A perforated wall's dashes: 1 M ink, 1 M gap, 2 M ink, 1 M gap, 1 M ink.
    def dash_v(x: float, y0: float) -> str:
        return (
            f'<line x1="{x:g}" y1="{y0 + 10:g}" x2="{x:g}" y2="{y0 + 20:g}" {ink}/>'
            f'<line x1="{x:g}" y1="{y0 + 30:g}" x2="{x:g}" y2="{y0 + 50:g}" {ink}/>'
            f'<line x1="{x:g}" y1="{y0 + 60:g}" x2="{x:g}" y2="{y0 + 70:g}" {ink}/>'
        )

    def dash_h(y: float, x0: float) -> str:
        return (
            f'<line x1="{x0 + 10:g}" y1="{y:g}" x2="{x0 + 20:g}" y2="{y:g}" {ink}/>'
            f'<line x1="{x0 + 30:g}" y1="{y:g}" x2="{x0 + 50:g}" y2="{y:g}" {ink}/>'
            f'<line x1="{x0 + 60:g}" y1="{y:g}" x2="{x0 + 70:g}" y2="{y:g}" {ink}/>'
        )

    zigzag = f'<path d="M 30 40 L 40 20 L 60 60 L 70 40" {ink}/>'

    rows = {
        # item, reg, box, ports, inner
        "high_speed": (
            "9.1",
            "X2619",
            (80.0, 90.0),
            top_ports,
            square
            + f'<path d="M 10 70 L 30 20 M 50 20 L 70 70 L 10 70" {ink}/>'
            + f'<line x1="40" y1="70" x2="40" y2="90" {ink}/>',
        ),
        "perforated_shell": (
            "9.2",
            "X2614",
            (80.0, 90.0),
            top_ports,
            square
            + dash_v(10.0, 0.0)
            + dash_v(70.0, 0.0)
            + f'<line x1="10" y1="70" x2="70" y2="70" {ink}/>'
            + f'<line x1="40" y1="70" x2="40" y2="90" {ink}/>',
        ),
        "solid_shell": (
            "9.3",
            "X8035",
            (80.0, 90.0),
            top_ports,
            square
            + f'<path d="M 10 70 L 10 10 M 70 70 L 70 10 M 10 70 L 70 70" {ink}/>'
            + f'<line x1="40" y1="70" x2="40" y2="90" {ink}/>',
        ),
        "disc": (
            "9.4",
            "X8036",
            (80.0, 90.0),
            top_ports,
            square
            + f'<path d="M 10 24 L 40 10 L 70 24 M 10 44 L 40 30 L 70 44" {ink}/>'
            + f'<line x1="40" y1="10" x2="40" y2="90" {ink}/>',
        ),
        "screw_perforated": (
            "9.5",
            "X8037",
            (90.0, 80.0),
            side_ports,
            square_side
            + f'<line x1="20" y1="10" x2="20" y2="70" {ink}/>'
            + dash_h(10.0, 10.0)
            + dash_h(70.0, 10.0)
            + f'<line x1="0" y1="40" x2="80" y2="40" {ink}/>'
            + zigzag,
        ),
        "decanter": (
            "9.6",
            "X8082",
            (90.0, 80.0),
            side_ports,
            square_side
            + f'<path d="M 20 70 L 20 10 L 80 10 M 20 70 L 80 70" {ink}/>'
            + f'<line x1="0" y1="40" x2="80" y2="40" {ink}/>'
            + zigzag,
        ),
        "pusher": (
            "9.7",
            "X8038",
            (90.0, 80.0),
            side_ports,
            square_side
            + f'<line x1="20" y1="10" x2="20" y2="70" {ink}/>'
            + dash_h(10.0, 10.0)
            + dash_h(70.0, 10.0)
            + f'<line x1="0" y1="40" x2="30" y2="40" {ink}/>'
            + f'<line x1="30" y1="20" x2="30" y2="60" {ink}/>',
        ),
        "skimmer": (
            "9.8",
            "X8039",
            (90.0, 80.0),
            side_ports,
            square_side
            + f'<line x1="20" y1="10" x2="20" y2="70" {ink}/>'
            + dash_h(10.0, 10.0)
            + dash_h(70.0, 10.0)
            + f'<line x1="0" y1="40" x2="20" y2="40" {ink}/>'
            + f'<path d="M 70 20 L 50 20 L 50 10 L 60 20" {ink}/>',
        ),
    }
    assert len(rows) == 8
    for variant, (item, reg, (width, height), ports, inner) in rows.items():
        sym = default_registry.get("centrifuge", variant)
        assert sym.svg == f'<g id="sym_centrifuge_{variant}">{inner}</g>', (
            f"centrifuge/{variant} ({item} {reg}) does not draw the row as measured"
        )
        assert (sym.width, sym.height) == (width, height)
        assert sym.ports == ports
        assert sym.iso_reg == reg
        assert not sym.gravity_fixed

    # Bare ``Centrifuge(...)`` draws 9.6, the decanter, under a second key.
    assert default_registry.get("centrifuge") is default_registry.get("centrifuge", "decanter")


def test_group_4_matches_the_rows_it_claims():
    """Check the boiler, stack and flare against group 4's rows."""
    boiler = default_registry.get("boiler")
    assert (boiler.width, boiler.height) == (100.0, 125.0)
    assert "M 25 25 A 25 25 0 0 1 75 25" in boiler.svg
    assert "L 100 25 L 100 125 L 0 125 L 0 25 Z" in boiler.svg
    assert boiler.ports == {"feedwater": (0.0, 50.0), "steam": (50.0, 0.0)}
    assert boiler.iso_reg == "2532"

    stack = default_registry.get("stack")
    assert (stack.width, stack.height) == (60.0, 100.0)
    assert "M 20 0 L 40 0" in stack.svg
    assert "M 20 0 L 10 100" in stack.svg
    assert "M 40 0 L 50 100" in stack.svg
    assert "M 0 100 L 60 100" in stack.svg
    assert 'fill="none"' in stack.svg
    assert stack.ports == {"inlet": (12.0, 80.0)}
    assert stack.port_faces["inlet"] == {"W": (12.0, 80.0)}
    assert stack.iso_reg == "2041"

    flare = default_registry.get("flare")
    assert (flare.width, flare.height) == (60.0, 120.0)
    assert "M 30 40 A 25 25 0 0 1 30 0 A 25 25 0 0 1 30 40 Z" in flare.svg
    assert "M 20 40 L 40 40 M 20 40 L 20 120 M 40 40 L 40 120" in flare.svg
    assert "M 0 120 L 60 120" in flare.svg
    assert flare.ports == {"inlet": (20.0, 90.0)}
    assert flare.port_faces["inlet"] == {"W": (20.0, 90.0)}
    assert flare.iso_reg == "2591"


def test_the_furnace_and_combustion_chamber_match_their_group_4_rows():
    """Check items 4.3 and 4.5 against their rows, at ten units to the module."""
    furnace = default_registry.get("furnace", "general")
    assert (furnace.width, furnace.height) == (80.0, 80.0)
    assert "M 0 0 L 80 0 L 80 60 L 60 80 L 20 80 L 0 60 Z" in furnace.svg
    assert "M 15 0 L 15 55 L 25 65 L 55 65 L 65 55 L 65 0" in furnace.svg
    assert furnace.ports == {"inlet": (0.0, 40.0), "outlet": (80.0, 40.0), "fuel": (40.0, 80.0)}
    assert furnace.iso_reg == "2533"

    chamber = default_registry.get("furnace", "combustion_chamber")
    assert (chamber.width, chamber.height) == (100.0, 80.0)
    assert 'width="100" height="80"' in chamber.svg
    # The burner plate a module up, and the flame 6 M and 3 M across.
    assert "M 0 70 L 100 70 M 20 70 L 50 20 L 80 70 M 35 70 L 50 45 L 65 70" in chamber.svg
    # Row 4.5's three ticks: air from the west, hot gas up, fuel from below.
    assert chamber.ports == {"inlet": (0.0, 40.0), "outlet": (50.0, 0.0), "fuel": (50.0, 80.0)}
    assert chamber.iso_reg == "X8106"


@pytest.mark.parametrize(
    "variant, reg, needle",
    [
        ("general", "C0046", "M 0 120 L 0 20 L 10 0 L 70 0 L 80 20 L 80 120 Z"),
        ("shelf", "X8083", '<line x1="20" y1="30" x2="60" y2="30"'),
        (
            "turbo",
            "X8040",
            "M 20 30 L 60 30 M 20 50 L 60 50 M 0 40 L 30 40 M 50 40 L 80 40 M 40 50 L 40 0",
        ),
        ("belt", "X8043", '<circle cx="17.5" cy="40" r="7.5"'),
    ],
)
def test_group_10_marks_match_their_rows(variant, reg, needle):
    """Check each group 10 drier's outline, mark, number and nozzles."""
    sym = default_registry.get("dryer", variant)
    # Row 10.1: an 8 M x 12 M casing chamfered 1 M x 2 M at its top corners.
    assert (sym.width, sym.height) == (80.0, 120.0)
    assert "M 0 120 L 0 20 L 10 0 L 70 0 L 80 20 L 80 120 Z" in sym.svg
    assert needle in sym.svg
    assert sym.iso_reg == reg
    assert not sym.overlays
    assert sym.ports == {
        "feed": (0.0, 70.0),
        "product": (80.0, 70.0),
        "heating_in": (40.0, 120.0),
        "vent": (40.0, 0.0),
    }


@pytest.mark.parametrize(
    "variant, reg, has_dry, has_wet, has_fan",
    [
        ("general", "2521", False, False, None),
        ("dry_natural", "X8109", True, False, None),
        ("dry_forced", "X8110", True, False, 65.0),
        ("dry_induced", "X8111", True, False, 15.0),
        ("wet_natural", "X8112", False, True, None),
        ("wet_forced", "X8113", False, True, 65.0),
        ("wet_induced", "X8114", False, True, 15.0),
        ("wet_dry_natural", "X8115", True, True, None),
    ],
)
def test_group_5_fill_and_draught_marks_match_their_rows(variant, reg, has_dry, has_wet, has_fan):
    """Check each group 5 cooling tower's outline, fill and draught marks, number and nozzles."""
    sym = default_registry.get("cooling_tower", variant)
    # Row 5.1: a trapezoid 4 M to 8 M wide over 8 M, on a 2 M deep basin.
    assert (sym.width, sym.height) == (80.0, 100.0)
    assert "M 20 0 L 60 0 L 80 80 L 80 100 L 0 100 L 0 80 Z" in sym.svg
    assert sym.iso_reg == reg
    assert not sym.overlays
    assert sym.ports == {
        "air_out": (40.0, 0.0),
        "water_in": (0.0, 90.0),
        "air_in": (80.0, 90.0),
        "water_out": (40.0, 100.0),
        "makeup": (20.0, 100.0),
        "blowdown": (60.0, 100.0),
    }
    assert ('<line x1="0" y1="90" x2="80" y2="90"' in sym.svg) is has_dry
    assert ("M 10 40 L 40 40 M 30 50 L 40 40 L 50 50" in sym.svg) is has_wet
    if has_fan is None:
        assert '<circle cx="40" cy="65"' not in sym.svg
        assert '<circle cx="40" cy="15"' not in sym.svg
    else:
        assert f'<circle cx="40" cy="{has_fan:g}" r="10"' in sym.svg


def test_the_group_19_circle_carries_its_own_mark():
    """Check the two group 19 circles and the mark inside each."""
    general = default_registry.get("feeder", "general")
    assert general.svg == (
        '<g id="sym_feeder_general">'
        '<circle cx="20" cy="20" r="20" fill="white" stroke="#111" stroke-width="2"/>'
        '<path d="M 37.3 30 L 2.7 30 L 37.3 10 L 2.7 10" fill="none" stroke="#111" '
        'stroke-width="2"/></g>'
    )
    assert (general.width, general.height) == (40.0, 40.0)
    assert general.ports == {"feed": (20.0, 0.0), "discharge": (20.0, 40.0), "drive": (40.0, 20.0)}
    assert general.iso_reg == "C2056"
    assert general.gravity_fixed

    rotary_valve = default_registry.get("feeder", "rotary_valve")
    assert '<circle cx="20" cy="20" r="20" fill="white"' in rotary_valve.svg
    assert '<circle cx="20" cy="20" r="3" fill="none"' in rotary_valve.svg
    # Six spokes, hub to rim, the rim being the body's own wall (r 20).
    assert rotary_valve.svg.count("<line ") == 6
    assert 'x1="23" y1="20" x2="40" y2="20"' in rotary_valve.svg
    assert 'x1="17" y1="20" x2="0" y2="20"' in rotary_valve.svg
    assert (rotary_valve.width, rotary_valve.height) == (40.0, 40.0)
    assert rotary_valve.ports == general.ports
    assert rotary_valve.iso_reg == "X8067"
    assert rotary_valve.gravity_fixed


def test_group_19s_other_two_feeders_match_their_rows():
    """Check the rotary table and metering feeders against their rows."""
    table = default_registry.get("feeder", "rotary_table")
    assert table.svg == (
        '<g id="sym_feeder_rotary_table">'
        '<line x1="0" y1="0" x2="50" y2="0" fill="none" stroke="#111" stroke-width="2"/>'
        '<line x1="25" y1="0" x2="25" y2="60" fill="none" stroke="#111" stroke-width="2"/>'
        '<ellipse cx="25" cy="37.5" rx="25" ry="12.5" fill="none" stroke="#111" '
        'stroke-width="2"/>'
        '<line x1="50" y1="37.5" x2="50" y2="30.5" fill="none" stroke="#111" '
        'stroke-width="2"/>'
        '<polygon points="50,27.5 47.3,30.5 52.7,30.5" fill="#111" stroke="none"/></g>'
    )
    assert (table.width, table.height) == (50.0, 60.0)
    assert table.ports == {"feed": (25.0, 0.0), "discharge": (25.0, 60.0), "drive": (0.0, 37.5)}
    assert table.iso_reg == "C0074"
    assert table.gravity_fixed

    metering = default_registry.get("feeder", "metering")
    assert metering.svg == (
        '<g id="sym_feeder_metering">'
        '<line x1="0" y1="3" x2="148" y2="3" fill="none" stroke="#111" stroke-width="2"/>'
        '<path d="M 0 3 A 22 22 0 0 1 44 3" fill="none" stroke="#111" stroke-width="2"/>'
        '<path d="M 104 3 A 22 22 0 0 1 148 3" fill="none" stroke="#111" '
        'stroke-width="2"/>'
        '<path d="M 74 3 L 57 33 L 91 33 Z" fill="none" stroke="#111" '
        'stroke-width="2"/></g>'
    )
    assert (metering.width, metering.height) == (148.0, 33.0)
    # A third of a module below the top edge, so the ports resolve to the side walls.
    assert metering.ports == {"feed": (0.0, 3.0), "discharge": (148.0, 3.0), "drive": (74.0, 33.0)}
    assert metering.iso_reg == "C0035"
    assert metering.gravity_fixed


def test_the_spray_nozzle_ticks_both_sides_of_its_apex():
    """Check the spray nozzle's drawing and its one nozzle offered on both faces."""
    sym = default_registry.get("spray_nozzle")
    assert sym.svg == (
        '<g id="sym_spray_nozzle">'
        '<line x1="0" y1="0" x2="40" y2="0" fill="none" stroke="#111" '
        'stroke-width="2"/>'
        '<path d="M 20 0 L 0 20 M 20 0 L 20 20 M 20 0 L 40 20" fill="none" '
        'stroke="#111" stroke-width="2"/></g>'
    )
    assert (sym.width, sym.height) == (40.0, 20.0)
    # A tenth of a module below the header, so the port resolves to a wall, not a corner.
    assert sym.ports == {"inlet": (0.0, 1.0)}
    assert sym.port_faces["inlet"] == {"W": (0.0, 1.0), "E": (40.0, 1.0)}
    assert sym.iso_reg == "2037"
    assert not sym.gravity_fixed


def test_group_12s_in_line_mixers_are_one_element_repeated():
    """Check the two group 12 in-line mixers and the static mixer's number."""
    rotary = default_registry.get("fitting", "rotary_mixer")
    assert rotary.svg == (
        '<g id="sym_fitting_rotary_mixer">'
        '<path d="M 10 0 L 130 0 L 130 60 L 10 60 Z" fill="white" stroke="#111" '
        'stroke-width="2"/>'
        '<line x1="0" y1="30" x2="130" y2="30" fill="none" stroke="#111" '
        'stroke-width="2"/>'
        '<path d="M 20 5 L 20 25 M 20 5 L 60 55 M 60 35 L 60 55" fill="none" '
        'stroke="#111" stroke-width="2"/>'
        '<path d="M 70 5 L 70 25 M 70 5 L 110 55 M 110 35 L 110 55" fill="none" '
        'stroke="#111" stroke-width="2"/></g>'
    )
    assert (rotary.width, rotary.height) == (130.0, 60.0)
    # The flow axis is drawn one module clear of the west wall, inside the box.
    assert rotary.ports == {"inlet": (0.0, 30.0), "outlet": (130.0, 30.0)}
    assert rotary.iso_reg == "X2672"

    path = default_registry.get("fitting", "mixing_path")
    assert path.svg == (
        '<g id="sym_fitting_mixing_path">'
        '<path d="M 0 0 L 160 0 L 160 60 L 0 60 Z" fill="white" stroke="#111" '
        'stroke-width="2"/>'
        '<path d="M 10 5 L 10 25 M 10 5 L 50 55 M 50 35 L 50 55" fill="none" '
        'stroke="#111" stroke-width="2"/>'
        '<path d="M 60 5 L 60 25 M 60 5 L 100 55 M 100 35 L 100 55" fill="none" '
        'stroke="#111" stroke-width="2"/>'
        '<path d="M 110 5 L 110 25 M 110 5 L 150 55 M 150 35 L 150 55" fill="none" '
        'stroke="#111" stroke-width="2"/></g>'
    )
    assert (path.width, path.height) == (160.0, 60.0)
    assert path.ports == {"inlet": (0.0, 30.0), "outlet": (160.0, 30.0)}
    assert path.iso_reg == "X8184"

    # 12.2 is the vendored static mixer, numbered rather than redrawn.
    static = default_registry.get("fitting", "static_mixer")
    assert static.iso_reg == "X2673"
    assert static.drawio_shape == "mxgraph.pid.mixers.in-line_static_mixer"


def test_the_kneader_carries_its_own_row():
    """Check the kneader against its row."""
    sym = default_registry.get("kneader")
    assert sym.svg == (
        '<g id="sym_kneader">'
        '<path d="M 10 0 L 110 0 L 110 60 L 10 60 Z" fill="white" stroke="#111" '
        'stroke-width="2"/>'
        '<path d="M 0 30 L 20 30 L 40 20 L 70 40 L 100 30 L 110 30" fill="none" '
        'stroke="#111" stroke-width="2"/></g>'
    )
    assert (sym.width, sym.height) == (110.0, 60.0)
    assert sym.ports == {"inlet": (0.0, 30.0), "outlet": (110.0, 30.0)}
    assert sym.iso_reg == "X8134"
    assert sym.gravity_fixed


def test_the_group_7_outline_is_the_row_table_2_draws():
    """Check the general screening device against row 7.1."""
    general = default_registry.get("screening_device", "general")
    assert general.svg == (
        '<g id="sym_screen_general">'
        '<path d="M 0 0 L 60 0 L 60 60 L 30 90 L 0 60 Z" fill="white" stroke="#111" '
        'stroke-width="2"/>'
        '<line x1="0" y1="0" x2="60" y2="60" fill="none" stroke="#111" '
        'stroke-width="2" stroke-dasharray="20,10"/></g>'
    )
    assert (general.width, general.height) == (60.0, 90.0)
    assert general.ports == {
        "feed": (30.0, 0.0),
        "oversize": (60.0, 50.0),
        "undersize": (30.0, 90.0),
    }
    assert general.iso_reg == "X8123"
    assert general.gravity_fixed


@pytest.mark.parametrize(
    "variant, reg, needle",
    [
        ("coarse_rake", "X8026", 'x1="32.4853" y1="15.5147" x2="15.5147" y2="32.4853"'),
        ("fine_rake", "X8027", 'x1="25.9497" y1="16.0503" x2="16.0503" y2="25.9497"'),
        (
            "coarse_and_fine",
            "X8028",
            '<line x1="20" y1="0" x2="60" y2="40" fill="none" stroke="#111" '
            'stroke-width="2" stroke-dasharray="20,10"/>',
        ),
        ("vibrating", "X2605", 'polygon points="36.364,30.7071'),
        (
            "rotating_drum",
            "X8029",
            '<circle cx="30" cy="45" r="15" fill="none" stroke="#111" stroke-width="2" '
            'stroke-dasharray="20,10"/>',
        ),
    ],
)
def test_group_7_marks_match_their_rows(variant, reg, needle):
    """Check each group 7 screening device's outline, mark, number and nozzles."""
    sym = default_registry.get("screening_device", variant)
    assert '<path d="M 0 0 L 60 0 L 60 60 L 30 90 L 0 60 Z"' in sym.svg
    if variant != "rotating_drum":
        assert 'x1="0" y1="0" x2="60" y2="60"' in sym.svg
    assert needle in sym.svg
    assert sym.iso_reg == reg
    assert sym.ports == {"feed": (30.0, 0.0), "oversize": (60.0, 50.0), "undersize": (30.0, 90.0)}
    assert sym.gravity_fixed


def test_the_basket_reel_keeps_its_own_larger_outline():
    """Check the basket reel against row 7.7."""
    sym = default_registry.get("screening_device", "basket_reel")
    assert sym.svg == (
        '<g id="sym_screen_basket_reel">'
        '<path d="M 0 0 L 80 0 L 80 120 L 40 160 L 0 120 Z" fill="white" '
        'stroke="#111" stroke-width="2"/>'
        '<circle cx="40" cy="20" r="10" fill="none" stroke="#111" stroke-width="2"/>'
        '<circle cx="40" cy="100" r="10" fill="none" stroke="#111" stroke-width="2"/>'
        '<line x1="30" y1="30" x2="30" y2="90" fill="none" stroke="#111" '
        'stroke-width="2" stroke-dasharray="20,10"/>'
        '<line x1="50" y1="30" x2="50" y2="90" fill="none" stroke="#111" '
        'stroke-width="2" stroke-dasharray="20,10"/></g>'
    )
    assert (sym.width, sym.height) == (80.0, 160.0)
    assert sym.ports == {"feed": (0.0, 20.0), "oversize": (80.0, 20.0), "undersize": (40.0, 160.0)}
    assert sym.iso_reg == "X8030"
    assert sym.gravity_fixed


def test_separator_sifter_is_not_a_group_7_row():
    """Check that ``separator/sifter`` matches no group 7 row and claims no number."""
    sifter = default_registry.get("separator", "sifter")
    assert not sifter.iso_reg
    assert (sifter.width, sifter.height) == (80.0, 120.0)
    for variant in (
        "general",
        "coarse_rake",
        "fine_rake",
        "coarse_and_fine",
        "vibrating",
        "rotating_drum",
        "basket_reel",
    ):
        screen = default_registry.get("screening_device", variant)
        assert (screen.width, screen.height) != (sifter.width, sifter.height) or (
            screen.svg.split(">", 1)[1] != sifter.svg.split(">", 1)[1]
        )


def test_the_cyclone_is_not_composed():
    """Check that the cyclone and its four neighbours are whole drawings with a stencil."""
    for variant in ("cyclone", "sifter", "impact", "permanent_magnet", "scrubber"):
        sym = default_registry.get("separator", variant)
        assert not sym.overlays, f"separator/{variant} is composed"
        assert sym.drawio_shape, f"separator/{variant} lost its stencil"


def test_the_parts_that_ship_are_available_and_unused():
    """Check that shipped parts are registered apart from the symbols of the same name."""
    assert default_registry.parts()
    agitator = default_registry.part(28, "turbine")
    machine = default_registry.get("turbine")
    assert agitator.iso.reg == "C2027"
    assert agitator.svg != machine.svg and not machine.overlays


#: The whole drawings drawn from a Table 2 row, and so claiming its number.
_NUMBERED_WHOLE_DRAWINGS = {
    "crushing_machine/default": "X8084",
    "crusher/default": "X8085",
    "mill/default": "X8086",
    "conveyor/screw": "X8063",
    "elevator/default": "X8065",
    "elevator/z_form": "X8066",
    "centrifuge/high_speed": "X2619",
    "centrifuge/perforated_shell": "X2614",
    "centrifuge/solid_shell": "X8035",
    "centrifuge/disc": "X8036",
    "centrifuge/screw_perforated": "X8037",
    "centrifuge/decanter": "X8082",
    "centrifuge/default": "X8082",
    "centrifuge/pusher": "X8038",
    "centrifuge/skimmer": "X8039",
    # ISO 10628-2 group 4, STEAM GENERATORS, FURNACES, RECOOLING DEVICE.
    # Group 1, VESSELS AND TANKS.
    "silo/bunker": "2064",
    "silo/default": "X2062",
    "tank/flat_roof": "301",
    "tank/open_top": "2061",
    "stockpile/default": "2065",
    "boiler/default": "2532",
    "furnace/general": "2533",
    "furnace/combustion_chamber": "X8106",
    "stack/default": "2041",
    "flare/default": "2591",
    # Group 15, LIQUID PUMPS.
    "pump/progressive_cavity": "X8093",
    "pump/reciprocating": "X8094",
    "pump/diaphragm": "X8095",
    # Group 16, COMPRESSORS, VACUUM PUMPS.
    "compressor/screw": "X8161",
    # Group 17, BLOWERS, FANS.
    "blower/general": "X8164",
    # Group 10, DRIER.
    "dryer/general": "C0046",
    "dryer/shelf": "X8083",
    "dryer/turbo": "X8040",
    "dryer/belt": "X8043",
    # Group 5, COOLING TOWER.
    "cooling_tower/general": "2521",
    "cooling_tower/dry_natural": "X8109",
    "cooling_tower/dry_forced": "X8110",
    "cooling_tower/dry_induced": "X8111",
    "cooling_tower/wet_natural": "X8112",
    "cooling_tower/wet_forced": "X8113",
    "cooling_tower/wet_induced": "X8114",
    "cooling_tower/wet_dry_natural": "X8115",
    # Group 19, PROPORTIONERS, FEEDERS AND DISTRIBUTION FACILITIES.
    "feeder/general": "C2056",
    "feeder/rotary_valve": "X8067",
    "feeder/rotary_table": "C0074",
    "feeder/metering": "C0035",
    "spray_nozzle/default": "2037",
    # Group 12, MIXERS/KNEADERS; 12.2 is the vendored static mixer.
    "fitting/rotary_mixer": "X2672",
    "fitting/static_mixer": "X2673",
    "fitting/mixing_path": "X8184",
    "kneader/default": "X8134",
    # Group 24, item 24.15: the steam trap.
    "fitting/steam_trap": "2181",
    # Group 7, SCREENING DEVICES, SIEVES AND RAKES.
    "screening_device/general": "X8123",
    "screening_device/coarse_rake": "X8026",
    "screening_device/fine_rake": "X8027",
    "screening_device/coarse_and_fine": "X8028",
    "screening_device/vibrating": "X2605",
    "screening_device/rotating_drum": "X8029",
    "screening_device/basket_reel": "X8030",
    # Group 20, items 20.6 to 20.8: the electric motor.
    "motor/general": "C0082",
    "motor/ac": "X8157",
    "motor/dc": "X8158",
}


def test_a_registration_number_is_claimed_by_a_composition_or_by_a_measured_body():
    """Check that only a composition or a listed measured drawing claims a registration number."""
    numbered = {
        f"{kind}/{variant}": sym
        for (kind, variant), sym in default_registry._symbols.items()
        if sym.iso_reg
    }
    whole = {name: sym.iso_reg for name, sym in numbered.items() if not sym.overlays}
    assert whole == _NUMBERED_WHOLE_DRAWINGS, (
        "a whole drawing claimed a registration number without being drawn from "
        "the row; that is the backfill, and it wants its own change"
    )


def test_a_built_to_size_drawing_does_not_capture_its_kinds_other_variants():
    """Check that a built-to-size entry applies to its own variant only."""
    from pandid.render import symbols

    marker = body(width=7.0)
    symbols._BUILT_TO_SIZE[("composition_test", "sized")] = lambda unit: marker
    try:
        reg = SymbolRegistry()
        reg.register("composition_test", body())
        reg.register("composition_test", body(), "sized")

        class Body(units.Unit):
            kind = "composition_test"

        assert reg.for_unit(Body("X-1", variant="sized")) is marker
        assert reg.for_unit(Body("X-2")) is reg.get("composition_test")
    finally:
        del symbols._BUILT_TO_SIZE[("composition_test", "sized")]


def test_a_tubular_reactor_drops_the_vent_it_has_no_use_for():
    """Check that a tubular reactor has no vent."""
    assert [name for name, _, _ in units.Reactor._variant_ports("default")] == [
        "outlet",
        "vent",
        "duty",
    ]
    assert [name for name, _, _ in units.Reactor._variant_ports("tubular")] == [
        "outlet",
        "duty",
    ]
    assert "vent" not in units.Reactor("R-301", variant="tubular", agitator=None).ports


def test_only_the_agitator_brings_the_drive():
    """Check that a reactor has a drive exactly when it has an agitator."""
    assert "drive" in units.Reactor("R-101").ports
    assert "drive" in units.Reactor("R-102", agitator="turbine").ports
    assert "drive" not in units.Reactor("R-201", agitator=None).ports
    assert list(units.Reactor("R-101").ports) == ["outlet", "vent", "duty", "drive", "feed_1"]


def drawn(unit):
    """Return the ``(group, name)`` of each part on the unit's composed symbol."""
    return [(overlay.group, overlay.name) for overlay in default_registry.for_unit(unit).overlays]


@pytest.mark.parametrize(
    "internals", ["packing", "fluidised_bed", "sieve_tray", "tray", "filter_insert"]
)
@pytest.mark.parametrize("variant", ["default", "jacketed"])
def test_naming_internals_leaves_out_the_agitator_nobody_asked_for(variant, internals):
    """Check that naming internals leaves out the default agitator and its drive."""
    unit = units.Reactor("R-201", variant=variant, internals=internals)
    assert drawn(unit) == [(27, internals)]
    assert unit.agitator is None
    assert "drive" not in unit.ports


def test_an_agitator_the_author_named_survives_its_internals():
    """Check that an agitator the author named is drawn over the internals."""
    unit = units.Reactor("R-203", agitator="turbine", internals="packing")
    assert drawn(unit) == [(27, "packing"), (28, "turbine"), (20, "motor")]
    assert (unit.agitator, unit.internals) == ("turbine", "packing")
    assert "drive" in unit.ports


def test_the_reactor_forms_that_did_not_change():
    """Check the parts of a default, a bare and an anchor-stirred reactor."""
    # Nothing said: the default stirrer and its motor.
    assert drawn(units.Reactor("R-101")) == [(28, "agitator"), (20, "motor")]
    # Said empty: the bare shell.
    assert drawn(units.Reactor("R-102", agitator=None)) == []
    # Said: that stirrer and its motor.
    assert drawn(units.Reactor("R-103", agitator="anchor")) == [(28, "anchor"), (20, "motor")]


# Each composition keyword that names a part, and the ISO group it names one from.
_PART_KEYWORDS = {"supports": 26, "rake": 28, "agitator": 28, "internals": 27}
_COMPOSING = [
    (cls, keyword, variant)
    for cls in (
        units.Vessel,
        units.Evaporator,
        units.Thickener,
        units.Crystallizer,
        units.FlotationCell,
        units.MixerSettler,
        units.Column,
        units.Reactor,
        units.Tank,
    )
    for keyword in cls.COMPOSITION
    if keyword in _PART_KEYWORDS
    for variant in default_registry.variants(cls.kind)
]


@pytest.mark.parametrize(
    ("cls", "keyword", "variant"),
    _COMPOSING,
    ids=[f"{cls.__name__}-{keyword}-{variant}" for cls, keyword, variant in _COMPOSING],
)
def test_a_body_and_part_either_draw_or_are_refused_when_built(cls, keyword, variant):
    """Check that every body and part pairing either renders or is refused when built."""
    names = (
        SUPPORTS if keyword == "supports" else default_registry.part_names(_PART_KEYWORDS[keyword])
    )
    for part in [None, *names]:
        try:
            unit = cls("X-1", variant=variant, **{keyword: part})
        except ValueError as refused:
            assert f"variant {variant!r} cannot carry {keyword}={part!r}" in str(refused)
            continue
        fs = Flowsheet("composed")
        fs.add(unit)
        fs.to_svg()


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (
            lambda: units.Vessel("D-301", variant="horizontal", supports="ring"),
            "D-301: Vessel variant 'horizontal' cannot carry supports='ring'; "
            "variants that can: default, dished, dome, insulated, jacketed, swaged",
        ),
        (
            lambda: units.Reactor("R-301", variant="tubular", agitator="anchor"),
            "R-301: Reactor variant 'tubular' cannot carry agitator='anchor'; "
            "variants that can: default, jacketed",
        ),
        (
            lambda: units.Tank("TK-301", variant="floating_roof", agitator="turbine"),
            "TK-301: Tank variant 'floating_roof' cannot carry agitator='turbine'; "
            "variants that can: default, conical, conical_bottom, conical_ends, "
            "dished_roof_conical_bottom, flat_roof, open_top",
        ),
        (
            lambda: units.Vessel("D-303", variant="horizontal", agitator="anchor"),
            "D-303: Vessel variant 'horizontal' cannot carry agitator='anchor'; "
            "variants that can: default, dished, electrical_heating, insulated, jacketed",
        ),
    ],
    ids=[
        "ring-on-a-drum",
        "stirrer-in-a-tube",
        "stirrer-under-a-floating-roof",
        "stirrer-in-a-drum",
    ],
)
def test_a_part_the_body_cannot_carry_is_refused_by_name(build, message):
    """Check that a part the body cannot carry is refused, naming the bodies that can."""
    with pytest.raises(ValueError) as refused:
        build()
    assert str(refused.value) == message


def test_the_agitator_default_is_the_same_answer_wherever_it_is_asked_for():
    """Check that the constructor and ``composition_defaults`` give one agitator default."""
    for internals, expected in (("packing", None), (None, "agitator")):
        stated = {"agitator": units._UNSTATED, "internals": internals}
        assert units.Reactor.composition_defaults("default", stated)["agitator"] == expected
        assert units.Reactor("R-1", internals=internals).agitator == expected


def test_a_class_with_one_composition_keyword_has_nothing_to_suppress():
    """Check that only a reactor and a vessel compose two parts, and each draws what it names."""
    two_parts = {
        cls.__name__
        for cls in (units.Reactor, units.Column, units.Vessel, units.Separator)
        if len([key for key in cls.COMPOSITION if key != "trays"]) > 1
    }
    assert two_parts == {"Reactor", "Vessel"}
    stirred = units.Vessel("D-302", supports="skirt", agitator="anchor")
    assert drawn(stirred) == [(26, "skirt"), (28, "anchor"), (20, "motor")]
    assert drawn(units.Column("T-104", internals="packing", trays=2)) == [(27, "packing")] * 2
    assert drawn(units.Vessel("D-301", supports="skirt")) == [(26, "skirt")]
    assert drawn(units.Separator("V-201", characteristic="gravity")) == [(29, "gravity")]
