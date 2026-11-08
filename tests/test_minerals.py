"""Check the tumbling mills and the open stockpile of ISO 10628-2 item 1.29."""

import math

import pytest
from marks import assert_inked, drawio_ink, off_ink, svg_ink

from pandid import Conveyor, Feed, Flowsheet, Mill, Product, Stockpile
from pandid.devices import AGMill, BallMill, RodMill, SAGMill
from pandid.portgeom import port_faces

#: Grid module, in drawing units.
M = 10.0


def _bare(unit, points) -> None:
    """Check that no point lies on the unit's ink in either export."""
    for export, ink in (("SVG", svg_ink(unit)), ("draw.io", drawio_ink(unit))):
        assert off_ink(points, ink) == points, f"{unit.name}: the {export} drawing inks them"


def _ball(cx: float, cy: float) -> list:
    """Return four points on a grinding ball's rim, 0.5 M round its centre."""
    return [(cx + 5, cy), (cx - 5, cy), (cx, cy + 5), (cx, cy - 5)]


def _drum(w: float, h: float) -> list:
    """Return points on a tumbling mill's trunnions, heads and shell for a box."""
    c = h / 2
    return [
        # Each trunnion, 1 M long and 2 M across, open to its line at the end.
        (0, c - 5),
        (0, c + 5),
        (5, c - M),
        (5, c + M),
        (M, c),
        (w, c - 5),
        (w, c + 5),
        (w - 5, c - M),
        (w - 5, c + M),
        (w - M, c),
        # Each conical head, 1 M long, from the trunnion to the shell.
        (1.5 * M, (c - M) / 2),
        (w - 1.5 * M, (c - M) / 2),
        (1.5 * M, h - (c - M) / 2),
        (w - 1.5 * M, h - (c - M) / 2),
        # The shell, and the lines where it meets the heads.
        (w / 2, 0),
        (w / 2, h),
        (2 * M, h / 4),
        (w - 2 * M, h / 4),
    ]


@pytest.mark.parametrize(
    ("cls", "variant", "box"),
    [
        (BallMill, "ball", (120, 40)),
        (RodMill, "rod", (140, 40)),
        (SAGMill, "sag", (80, 60)),
        (AGMill, "ag", (80, 60)),
    ],
)
def test_each_tumbling_mill_is_a_drum_on_two_trunnions(cls, variant, box):
    """Check the drum and trunnions, fed through the west one and discharged through the east."""
    mill = cls("ML-101")
    assert (mill.kind, mill.variant) == ("mill", variant)
    assert_inked(mill, _drum(*box))
    assert {name: port_faces(mill, name) for name in mill.ports} == {
        "feed": ["W"],
        "discharge": ["E"],
        "drive": ["N"],
    }


def test_a_ball_mill_carries_two_staggered_rows_of_balls():
    """Check the ball charge: two rows of 0.5 M balls 1.5 M apart along the bottom."""
    bottom = [p for x in (30, 45, 60, 75, 90) for p in _ball(x, 35)]
    above = [p for x in (37.5, 52.5, 67.5, 82.5) for p in _ball(x, 25)]
    assert_inked(BallMill("ML-101"), bottom + above)


def test_a_rod_mill_carries_three_rods_along_its_shell():
    """Check the rod charge: three rods 0.75 M apart, a module in from each end of the shell."""
    mill = RodMill("ML-101")
    assert_inked(mill, [(x, y) for y in (35, 27.5, 20) for x in (31, 70, 109)])


def test_a_sag_mill_carries_one_row_of_balls_and_an_ag_mill_none():
    """Check that a SAG mill carries one row of balls and an AG mill an empty drum."""
    assert_inked(SAGMill("ML-101"), [p for x in (30, 45) for p in _ball(x, 55)])
    inside = [(x, y) for x in (25, 30, 40, 50, 55) for y in (10, 25, 35, 45, 55)]
    _bare(AGMill("ML-102"), inside)


def test_a_longer_mill_keeps_its_trunnions_and_balls_and_gets_more_of_them():
    """Check that a mill drawn to a box keeps every feature's size and lengthens its shell."""
    balls = [p for x in range(30, 191, 15) for p in _ball(x, 45)]
    assert_inked(BallMill("ML-101", width=220, height=50), _drum(220, 50) + balls)


def test_a_mill_box_too_small_for_its_drum_is_refused():
    """Check that a box with no room for the trunnions, heads and charge is refused."""
    with pytest.raises(
        ValueError,
        match="ML-101: a box 50 x 40 is too small to draw a .ball. mill.*at least 70 wide",
    ):
        fs = Flowsheet("Small")
        fs.add(BallMill("ML-101", width=50))
        fs.to_svg()


def test_the_mill_kind_still_draws_its_iso_rows_unchanged():
    """Check that the general mill keeps its ISO 11.8 trapezoid and top-to-bottom ports."""
    mill = Mill("ML-101")
    assert {name: port_faces(mill, name) for name in mill.ports} == {
        "feed": ["N"],
        "discharge": ["S"],
        "drive": ["E"],
    }


#: Half the gap that breaks each slope, and the dots' offset, along it.
_GAP, _DOT = 7.5 / math.sqrt(2), 2.5 / math.sqrt(2)


def _slopes(w: float, h: float = 40.0) -> tuple:
    """Return points on a pile's solid slopes, its dots, and its gaps."""
    solid, dots, gaps = [], [], []
    for toe, way in ((M, 1), (w - M, -1)):
        mx, my = toe + way * h / 2, h / 2
        solid += [
            (toe + way * 5, h - 5),
            (mx - way * (_GAP + 2), my + _GAP + 2),
            (mx + way * (_GAP + 2), my - _GAP - 2),
            (toe + way * (h - 5), 5),
        ]
        dots += [(mx + way * d + 1, my - d) for d in (-_DOT, _DOT)]
        gaps += [(mx, my), (mx + way * (_DOT + 2.5), my - _DOT - 2.5)]
    return solid, dots, gaps


def test_the_stockpile_is_row_1_29():
    """Check item 1.29: a pile 4 M high on one-in-one slopes over a base line 10 M long."""
    solid, dots, gaps = _slopes(100)
    assert_inked(Stockpile("SP-101"), [(5, 40), (50, 40), (95, 40), (50, 0), *solid, *dots])
    _bare(Stockpile("SP-102"), gaps)
    pile = Stockpile("SP-103")
    assert port_faces(pile, "feed") == ["N"] and port_faces(pile, "reclaim") == ["S"]


def test_a_wider_stockpile_keeps_its_slopes_and_gains_a_flat_top():
    """Check that a pile built wider keeps its height and slopes, and runs flat along the top."""
    solid, dots, gaps = _slopes(200)
    ridge = [(5, 40), (195, 40), (60, 0), (100, 0), (140, 0)]
    assert_inked(Stockpile("SP-101", width=200), ridge + solid + dots)
    _bare(Stockpile("SP-102", width=200), gaps)


def test_a_stockpile_too_narrow_for_its_slopes_is_refused():
    """Check that a box narrower than the pile's slopes need is refused, naming the least."""
    with pytest.raises(
        ValueError,
        match="SP-101: a box 100 x 60 is too small to draw a stockpile.*width of at least 140",
    ):
        fs = Flowsheet("Narrow")
        fs.add(Stockpile("SP-101", width=100, height=60))
        fs.to_svg()


def test_a_stockpile_between_two_belts_feeds_a_ball_mill():
    """Check a stockpile stacked and reclaimed by belts, feeding a ball mill, draws clean."""
    fs = Flowsheet("Grinding")
    ore = fs.add(Feed("Ore"))
    stacker = fs.add(Conveyor("CV-101"))
    pile = fs.add(Stockpile("SP-101", description="Coarse Ore Stockpile"))
    reclaimer = fs.add(Conveyor("CV-102"))
    mill = fs.add(BallMill("ML-101"))
    out = fs.add(Product("Cyclone Feed"))
    fs.connect(ore.outlet, stacker.feed)
    fs.connect(stacker.discharge, pile.feed)
    fs.connect(pile.reclaim, reclaimer.feed)
    fs.connect(reclaimer.discharge, mill.feed)
    fs.connect(mill.discharge, out.inlet)
    fs.to_svg(diagram="p&id")
    assert [i for i in fs.validate() if i.severity == "error"] == []
    assert {"SP-101", "ML-101"} <= {row["tag"] for row in fs.equipment_list()}


@pytest.mark.parametrize("cls", [BallMill, RodMill, SAGMill, AGMill])
def test_a_mill_whose_shell_leaves_its_media_no_length_is_refused(cls):
    """Check that a shell no longer than the media's inset at each end is refused."""
    fs = Flowsheet("Short")
    fs.add(cls("ML-101", width=60))
    with pytest.raises(ValueError, match="ML-101: a box 60 x [0-9]+ is too small to draw"):
        fs.to_svg()


def test_the_shortest_rod_mill_draws_rods_with_length():
    """Check that the shortest rod mill drawn carries three rods a module long."""
    assert_inked(
        RodMill("ML-101", width=70), [(x, y) for y in (35, 27.5, 20) for x in (30, 35, 40)]
    )


@pytest.mark.parametrize("height", [5, 20])
def test_a_stockpile_too_low_for_its_break_is_refused(height):
    """Check that a pile too low for its slopes' dotted break is refused, naming the least."""
    fs = Flowsheet("Low")
    fs.add(Stockpile("SP-101", height=height))
    with pytest.raises(ValueError, match=f"SP-101: a box 100 x {height} is too small to draw"):
        fs.to_svg()
