"""Check the membrane modules, the pig traps and the three-phase drums."""

import pytest
from marks import assert_inked, drawio_ink, off_ink, svg_ink

from pandid import Feed, Flowsheet, MembraneModule, PigTrap, Product, Separator
from pandid.devices import BootedDrum, PigLauncher, PigReceiver, ThreePhaseSeparator
from pandid.portgeom import port_faces


def _bare(unit, points) -> None:
    """Check that no point lies on the unit's ink in either export."""
    for export, ink in (("SVG", svg_ink(unit)), ("draw.io", drawio_ink(unit))):
        assert off_ink(points, ink) == points, f"{unit.name}: the {export} drawing inks them"


def _faces(unit) -> dict:
    """Return the face each of a unit's ports leaves by."""
    return {name: port_faces(unit, name)[0] for name in unit.ports}


# --- Membrane modules: a housing split by a dashed membrane, lettered ---------

#: The dashes' and gaps' middles along the membrane, a module under the top.
_DASHES = [(10.0 + 20 * k, 10.0) for k in range(6)]
_GAPS = [(20.0 + 20 * k, 10.0) for k in range(5)]

#: Points each grade's two letters pass through, 1 M by 1.5 M each, 0.5 M
#: apart, centred in the feed channel of a 120 x 40 module.
_LETTERS = {
    # R's upright, bowl top and leg; O's left, right, top and bottom.
    "ro": [
        (47.5, 25),
        (52.5, 17.5),
        (55, 28.75),
        (62.5, 25),
        (72.5, 25),
        (67.5, 17.5),
        (67.5, 32.5),
    ],
    # N's diagonal; F's top bar, upright and middle bar.
    "nf": [(52.5, 25), (47.5, 20), (57.5, 30), (67.5, 17.5), (62.5, 25), (66, 25)],
    # U's uprights and bottom; F as above.
    "uf": [(47.5, 20), (57.5, 20), (52.5, 32.5), (67.5, 17.5), (62.5, 25), (66, 25)],
    # M's uprights and its middle vertex; F as above.
    "mf": [(47.5, 25), (57.5, 25), (52.5, 25), (67.5, 17.5), (62.5, 25), (66, 25)],
}


@pytest.mark.parametrize("grade", sorted(_LETTERS))
def test_a_membrane_module_letters_its_grade_in_the_feed_channel(grade):
    """Check the housing, the dashed membrane, and the grade's letters."""
    housing = [(60, 0), (60, 40), (0, 20), (120, 20)]
    assert_inked(MembraneModule("M-101", variant=grade), housing + _DASHES + _LETTERS[grade])
    _bare(MembraneModule("M-102", variant=grade), _GAPS + [(52.5, 37), (67.5, 37)])


def test_the_plain_membrane_module_letters_nothing():
    """Check that the default module draws the housing and membrane and no letters."""
    assert_inked(MembraneModule("M-101"), _DASHES)
    _bare(MembraneModule("M-102"), [p for points in _LETTERS.values() for p in points])


def test_a_membrane_module_is_fed_west_and_drawn_off_east_and_up():
    """Check feed and concentrate in the feed channel, and permeate off the top."""
    module = MembraneModule("M-101", variant="ro")
    assert _faces(module) == {"feed": "W", "concentrate": "E", "permeate": "N"}


def test_a_longer_membrane_module_keeps_its_letters_and_dashes():
    """Check that a module built to a larger box keeps the size of its letters and dashes."""
    # O's rim round (107.5, 35), and dashes 1.5 M long every 2 M.
    o = [(102.5, 35), (112.5, 35), (107.5, 27.5), (107.5, 42.5)]
    assert_inked(MembraneModule("M-101", variant="ro", width=200, height=60), o + [(190, 10)])
    _bare(MembraneModule("M-102", variant="ro", width=200, height=60), [(180, 10)])


# --- Pig traps: a closure, a barrel, a reducer to the main nozzle -------------

#: A launcher's ink: the closure plate, the barrel, the reducer and the main.
_LAUNCHER = [
    (0, 20),
    (2.5, 0),
    (2.5, 40),
    (5, 2),
    (45, 5),
    (45, 35),
    (85, 20),
    (95, 10),
    (95, 30),
    (105, 20),
    (112.5, 15),
    (112.5, 25),
    (120, 20),
]


def test_a_pig_launcher_has_its_closure_west_and_its_main_east():
    """Check the launcher's closure, barrel, reducer and main nozzle, west to east."""
    assert_inked(PigLauncher("PL-101"), _LAUNCHER)
    # No closure at the main end.
    _bare(PigLauncher("PL-102"), [(117.5, 0), (117.5, 40)])
    launcher = PigLauncher("PL-103")
    assert _faces(launcher) == {
        "kicker": "N",
        "main": "E",
        "closure": "W",
        "vent": "N",
        "relief": "N",
        "drain": "S",
    }
    assert (launcher.ports["kicker"].direction, launcher.ports["main"].direction) == (
        "inlet",
        "outlet",
    )


def test_a_pig_receiver_is_the_launcher_drawn_east_to_west():
    """Check the receiver's closure east and main west, and its flows the other way."""
    assert_inked(PigReceiver("PR-101"), [(120 - x, y) for x, y in _LAUNCHER])
    _bare(PigReceiver("PR-102"), [(2.5, 0), (2.5, 40)])
    receiver = PigReceiver("PR-103")
    assert (port_faces(receiver, "closure"), port_faces(receiver, "main")) == (["E"], ["W"])
    assert (receiver.ports["main"].direction, receiver.ports["kicker"].direction) == (
        "inlet",
        "outlet",
    )


def test_a_longer_pig_trap_keeps_its_closure_reducer_and_main():
    """Check that a trap built to a larger box lengthens its barrel only."""
    trap = PigTrap("PL-101", width=200, height=50)
    assert_inked(trap, [(2.5, 0), (5, 2), (165, 25), (175, 12.5), (192.5, 20), (200, 25)])


# --- Three-phase drums: a horizontal drum with a boot, or with a weir ---------

#: A 12 M by 3 M drum's ink: the top, the bottom, the tangent lines and the
#: west head's apex.
_DRUM = [(60, 0), (60, 30), (7.5, 15), (112.5, 15), (0, 15), (120, 15)]


def test_a_booted_drum_carries_its_water_boot_under_its_east_end():
    """Check the drum and the boot: 1.2 M across, its walls 1.2 M deep, 2 M from the east tangent."""
    assert_inked(BootedDrum("V-101"), _DRUM + [(86.5, 36), (98.5, 36), (92.5, 45)])
    drum = BootedDrum("V-102")
    assert _faces(drum) == {"feed_1": "W", "vapor": "N", "liquid": "S", "water": "S"}


def test_a_three_phase_separator_carries_its_weir_near_its_east_end():
    """Check the weir: 3 M in from the east tangent, 0.6 of the drum high, short of the top."""
    assert_inked(ThreePhaseSeparator("V-101"), _DRUM + [(82.5, 29), (82.5, 13)])
    _bare(ThreePhaseSeparator("V-102"), [(82.5, 8), (82.5, 3), (92.5, 36)])


def test_water_leaves_ahead_of_the_weir_and_liquid_beyond_it():
    """Check that the water draw is on the feed side of the weir and the liquid past it."""
    from pandid.render.symbols import default_registry

    sym = default_registry.get("separator", "three_phase")
    assert sym.ports["water"][0] < 82.5 < sym.ports["liquid"][0]
    assert _faces(ThreePhaseSeparator("V-101")) == {
        "feed_1": "W",
        "vapor": "N",
        "liquid": "S",
        "water": "S",
    }


def test_a_longer_drum_keeps_its_boot_and_weir():
    """Check that drums built to larger boxes keep the boot's and the weir's own size."""
    assert_inked(
        BootedDrum("V-101", width=200, height=60),
        [(166.5, 51), (178.5, 51), (172.5, 60), (100, 45)],
    )
    assert_inked(ThreePhaseSeparator("V-102", width=200, height=50), [(162.5, 49), (162.5, 21)])
    _bare(ThreePhaseSeparator("V-103", width=200, height=50), [(162.5, 15)])


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: MembraneModule("M-101", width=50), "M-101: a box 50 x 40 is too small to draw"),
        (lambda: PigLauncher("PL-101", width=80), "PL-101: a box 80 x 40 is too small to draw"),
        (
            lambda: ThreePhaseSeparator("V-101", height=15),
            "V-101: a box 120 x 15 is too small to draw",
        ),
    ],
    ids=["membrane", "pig-trap", "drum"],
)
def test_a_box_too_small_for_the_features_is_refused(build, match):
    """Check that a box with no room for the features is refused, naming the least box."""
    fs = Flowsheet("Small")
    fs.add(build())
    with pytest.raises(ValueError, match=match):
        fs.to_svg()


def test_a_drum_with_a_boot_or_a_weir_takes_one_feed():
    """Check that a booted drum or a three-phase separator refuses a feed family."""
    with pytest.raises(ValueError, match="is drawn with one feed nozzle"):
        Separator("V-101", variant="three_phase", n_feeds=2)


def test_a_pigged_line_into_a_three_phase_separator_and_a_membrane_draw_clean():
    """Check a sheet of a receiver, a three-phase separator and an RO module."""
    fs = Flowsheet("Well fluid")
    well = fs.add(Feed("Well Fluid"))
    receiver = fs.add(PigReceiver("PR-101"))
    separator = fs.add(ThreePhaseSeparator("V-101"))
    ro = fs.add(MembraneModule("RO-101", variant="ro"))
    gas, oil = fs.add(Product("Gas")), fs.add(Product("Oil"))
    permeate, brine = fs.add(Product("Permeate")), fs.add(Product("Brine"))
    fs.connect(well.outlet, receiver.main)
    fs.connect(receiver.kicker, separator.feed)
    fs.connect(separator.vapor, gas.inlet)
    fs.connect(separator.liquid, oil.inlet)
    fs.connect(separator.port("water"), ro.feed)
    fs.connect(ro.permeate, permeate.inlet)
    fs.connect(ro.concentrate, brine.inlet)
    fs.to_svg(diagram="p&id")
    assert [i for i in fs.validate() if i.severity == "error"] == []
