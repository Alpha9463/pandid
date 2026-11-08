"""Check the tumbling mills."""

import pytest
from marks import assert_inked, drawio_ink, off_ink, svg_ink

from pandid import Flowsheet, Mill
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
        ValueError, match="ML-101: a box 50 x 40 is too small to draw a .ball. mill"
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
    }
