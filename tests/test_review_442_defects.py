"""Defects found reviewing #442 (`c45fcc0`). Every test here failed on it.

Each one states a promise the pull request made -- in its own body, in
issue #431's "what the new solver must not lose", or in the docstring of
the module under test -- and showed the engine breaking it.

They are kept as the acceptance for #447, which replaces that engine
with a weighted least-squares fit. Three are unchanged. The second is
rewritten: it was a unit test of the union-find pass and its rank floor,
and there is no union-find pass any more -- so it asks the *property*
the floor existed to protect, of the engine that replaced it.
"""

from collections.abc import Sequence

from pandid import Flowsheet, devices as D, units as U
from pandid.layout.control import COL_GAP, _grid as control_grid


# --- 1. a grid pin on a free-standing balloon is dropped ----------------------
#
# #431: "Pins are hard constraints." `pandid.layout.control._spot`:
# "A pinned column or row is read against the grid stage 1 laid out, so
# ``pin(col=3)`` on a controller means the same column it means on a
# pump." Stage 2 computed that column and then handed the answer to
# `_nearest_free`, which walked the balloon off it. The old engine
# ranked a free-standing balloon with the equipment and honoured the pin
# exactly; no shipped example pins an instrument, so the corpus does not
# notice.


def _panel() -> tuple[Flowsheet, U.Unit]:
    fs = Flowsheet("panel")
    feed = fs.add(U.Feed("Feed"))
    valve = fs.add(D.ControlValve("FV-101"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    fic = fs.add(U.Instrument("FIC-101"))
    fs.connect(fic.sig_out, valve.actuator, kind="pneumatic")
    return fs, fic


def _lanes(fs: Flowsheet) -> tuple[dict[int, float], dict[int, float]]:
    """Where each grid line the balloons are measured against starts.

    `control._grid` itself, not a copy of it. A test holding its own
    reimplementation of the code under test measures the copy: the copy
    grew the stage-1 filter alongside the real one and so agreed with it
    whether or not the real one had the filter at all, which hid the
    regression the filter exists to prevent. Asking the engine leaves
    nothing to agree with.

    Only the start of each line is wanted here; the depth `_lane` needs
    to continue a one-column grid is dropped.
    """
    cols, rows = control_grid(fs)
    return ({k: v[0] for k, v in cols.items()}, {k: v[0] for k, v in rows.items()})


def test_a_pinned_column_on_a_free_standing_balloon_is_honoured() -> None:
    fs, fic = _panel()
    fic.pin(col=0)
    fs.layout()

    cols, _ = _lanes(fs)
    assert fic.frame is not None
    assert fic.frame.x == cols[0], (
        f"pin(col=0) put FIC-101 at x={fic.frame.x}, but column 0 is at x={cols[0]}"
    )


def test_a_pinned_row_on_a_free_standing_balloon_is_honoured() -> None:
    fs, fic = _panel()
    fic.pin(row=0)
    fs.layout()

    _, rows = _lanes(fs)
    assert fic.frame is not None
    assert fic.frame.y == rows[0], (
        f"pin(row=0) put FIC-101 at y={fic.frame.y}, but row 0 is at y={rows[0]}"
    )


def test_a_column_past_the_last_one_the_sheet_used_is_still_honoured() -> None:
    """The other half of the same defect: a pin the grid has no line for.

    ``pin(col=7)`` on a three-column sheet was dropped outright and the
    balloon placed by its wiring instead, which is a sheet the author did
    not ask for and was told nothing about. The grid is continued at its
    own pitch instead.
    """
    fs, fic = _panel()
    fic.pin(col=7)
    fs.layout()

    cols, _ = _lanes(fs)
    assert fic.frame is not None
    # The grid a balloon is measured against is the one stage 1 drew, and
    # a balloon is stage 2's. Its own frame carries the rank it was stood
    # in, so a grid that read every frame would answer `pin(col=7)` with
    # the column this very balloon made -- which is not a line the sheet
    # used, and is the thing this test denies.
    assert 7 not in cols, (
        f"column 7 is the balloon's own rank, not a line stage 1 drew: {sorted(cols)}"
    )
    assert max(cols) < 7, "this sheet is supposed to be narrower than the pin"
    pitch = (cols[max(cols)] - cols[min(cols)]) / (max(cols) - min(cols))
    assert fic.frame.x == cols[max(cols)] + (7 - max(cols)) * pitch


def test_a_balloon_does_not_move_the_lane_the_next_balloon_is_measured_against() -> None:
    """The consequence of the same rule, in drawn pixels rather than in a dict.

    A one-column sheet has no pitch of its own, so `_lane` continues it by
    that column's own box and the gap after it -- which makes the *width*
    of column 0 the thing the second balloon's position is computed from.
    A balloon standing in column 0 is wider than the valve that drew it, so
    a grid that counted the balloon would widen the column and push the
    next balloon 19.5px east of the lane the process laid down.

    Two balloons, because one cannot show it: the first is placed before it
    has a frame to be counted from, so the sheet where a balloon pollutes
    the grid and the sheet where it does not are the same drawing until
    there is a second balloon to be measured against the first.

    The expected position is derived from the *valve's* frame and not from
    `_grid`, because a grid that has counted the balloon reports the
    widened column too and would agree with the sheet it produced.
    """
    fs = Flowsheet("one-column")
    valve = fs.add(D.ControlValve("FV-101"))
    first = fs.add(U.Instrument("FIC-101"))
    fs.connect(first.sig_out, valve.actuator, kind="pneumatic")
    second = fs.add(U.Instrument("XI-1"))
    fs.connect(second.sig_out, first.sig_in, kind="electric")
    first.pin(col=0)
    second.pin(col=1)
    fs.layout()

    assert valve.frame is not None and first.frame is not None
    assert second.frame is not None
    assert first.frame.w > valve.frame.w, (
        "this test needs a balloon wider than the column it stands in"
    )
    assert first.frame.x == valve.frame.x
    assert second.frame.x == valve.frame.x + valve.frame.w + COL_GAP, (
        f"XI-1 is at x={second.frame.x}; column 1 of a sheet whose only column "
        f"is the valve's is at x={valve.frame.x + valve.frame.w + COL_GAP}"
    )


# --- 2. one part of a sheet cannot pay for another ----------------------------
#
# As written against #442 this drove `solver._merge` directly: `floor`
# was `max(same.rank for same in sames)`, one number for the whole
# sheet, so a rank-1 union anywhere was served by whatever the strongest
# union anywhere else was willing to pay for -- and paid for it by
# demoting a *forward run* on an unrelated chain.
#
# The union-find pass, the ranks and the floor are all gone: nothing is
# demoted because nothing is dropped. What the floor was protecting
# survives as a property of the fit, and is what is asked here: a
# component of the sheet is solved on its own claims and an unrelated
# one cannot move it.


def _chain() -> tuple[Flowsheet, list[U.Block]]:
    fs = Flowsheet("chain")
    blocks = [fs.add(U.Block(name, inputs=["W"], outputs=["E"])) for name in "ABC"]
    fs.connect(blocks[0].out_1, blocks[1].in_1)
    fs.connect(blocks[1].out_1, blocks[2].in_1)
    return fs, blocks


def _arrangement(units: "Sequence[U.Unit]") -> list[tuple[int, int]]:
    """Where each unit sits relative to the first, in whole grid steps.

    Relative, because a second group on the sheet is entitled to a band
    of its own and the bands are numbered from the top of the *sheet*.
    What may not change is how these units sit against each other.
    """
    frames = [u.frame for u in units]
    assert all(f is not None and f.col is not None and f.row is not None for f in frames)
    origin = frames[0]
    assert origin is not None and origin.col is not None and origin.row is not None
    out: list[tuple[int, int]] = []
    for frame in frames:
        assert frame is not None and frame.col is not None and frame.row is not None
        out.append((frame.col - origin.col, frame.row - origin.row))
    return out


def test_an_unrelated_group_cannot_move_this_one() -> None:
    fs, (a, b, c) = _chain()
    fs.layout()
    alone = _arrangement([a, b, c])

    fs, (a, b, c) = _chain()
    x = fs.add(U.Vessel("X"))
    y = fs.add(U.Vessel("Y"))
    fs.connect(x.outlet, y.inlet)  # a stiffer pair, joined to nothing
    fs.layout()

    assert _arrangement([a, b, c]) == alone, (
        "adding a vessel pair with no connection to A, B or C rearranged them"
    )
    # And the newcomers are on the sheet rather than on top of it.
    assert x.frame is not None and y.frame is not None
    assert (x.frame.col, x.frame.row) != (y.frame.col, y.frame.row)
    assert {(u.frame.col, u.frame.row) for u in (a, b, c) if u.frame is not None}.isdisjoint(
        {(x.frame.col, x.frame.row), (y.frame.col, y.frame.row)}
    )


# --- 3. a column's overhead and its condenser state nothing about the row -----
#
# The pull request exists to stop "the disagreement between geometry and
# nozzle". A column overhead is fixed north and a condenser's shell inlet
# is fixed north, and `claims._agreed` read the pair as stating no order
# at all -- so the row solver had nothing to hold the condenser above the
# column, and `06_column_reflux` came out with the condenser under the
# tower and the reboiler over it.


def test_a_condenser_is_not_drawn_below_the_column_it_serves() -> None:
    """``examples/06_column_reflux.py``'s topology, with nothing pinned."""
    fs = Flowsheet("reflux")
    feed = fs.add(U.Feed("Feed"))
    tower = fs.add(U.DistillationColumn("T-701", internals="baffle_tray", trays=10))
    condenser = fs.add(D.ShellAndTubeExchanger("E-701", variant="straight_tubes"))
    drum = fs.add(U.Vessel("V-701", variant="horizontal"))
    vent = fs.add(U.Product("Vent Gas"))
    split = fs.add(U.Splitter("SP-701", n_outlets=2))
    dist = fs.add(U.Product("Distillate"))
    reboiler = fs.add(D.KettleReboiler("E-702"))
    bottoms = fs.add(U.Product("Bottoms"))

    fs.connect(feed.outlet, tower.feed_1)
    fs.connect(tower.overhead, condenser.shell_in)
    fs.connect(condenser.shell_out, drum.ports["in_1"])
    fs.connect(drum.vent, vent.inlet)
    fs.connect(drum.ports["out_1"], split.inlet)
    fs.connect(split.ports["out_1"], dist.inlet)
    fs.connect(split.ports["out_2"], tower.reflux_in)
    fs.connect(tower.bottoms, reboiler.shell_in)
    fs.connect(reboiler.shell_out, tower.boilup_in)
    fs.connect(reboiler.bottoms, bottoms.inlet)
    fs.layout()

    assert tower.frame is not None
    assert condenser.frame is not None
    assert reboiler.frame is not None
    # The old engine drew the reboiler at y=345 under a column at y=150,
    # and the condenser level with the column. This one has them the
    # other way up: condenser 465, column 270, reboiler 75.
    assert reboiler.frame.cy > tower.frame.cy, (
        f"the reboiler is drawn at y={reboiler.frame.cy}, above the column "
        f"it boils at y={tower.frame.cy}"
    )
    assert condenser.frame.cy < reboiler.frame.cy, (
        f"the overhead condenser (y={condenser.frame.cy}) is drawn below "
        f"the reboiler (y={reboiler.frame.cy}); the sheet is upside down"
    )
    # And to the east of it, which is the other half of #446: an
    # overhead system belongs top right and a reboiler bottom right, not
    # stacked over and under the tower in its own column.
    assert condenser.frame.cx > tower.frame.cx
    assert reboiler.frame.cx > tower.frame.cx
