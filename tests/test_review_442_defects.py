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


def _grid(fs: Flowsheet) -> tuple[dict[int, float], dict[int, float]]:
    """The columns and rows stage 1 drew, as `control._grid` reads them."""
    cols: dict[int, float] = {}
    rows: dict[int, float] = {}
    for u in fs.units:
        frame = u.frame
        # Stage 1's units, which is what `control._grid` reads: a balloon
        # is placed in stage 2 and consumes the grid, and its frame now
        # records the rank it was stood in so `pin-not-honored` can tell
        # a grid pin that was honoured from one nothing read. Letting one
        # back in here would have `pin(col=7)` answer as though the sheet
        # had a column 7 -- which is the very thing this test denies.
        if frame is None or isinstance(u, U.Instrument):
            continue
        if frame.col is not None:
            held = cols.get(frame.col)
            cols[frame.col] = frame.x if held is None else min(held, frame.x)
        if frame.row is not None:
            held = rows.get(frame.row)
            rows[frame.row] = frame.y if held is None else min(held, frame.y)
    return cols, rows


def test_a_pinned_column_on_a_free_standing_balloon_is_honoured() -> None:
    fs, fic = _panel()
    fic.pin(col=0)
    fs.layout()

    cols, _ = _grid(fs)
    assert fic.frame is not None
    assert fic.frame.x == cols[0], (
        f"pin(col=0) put FIC-101 at x={fic.frame.x}, but column 0 is at x={cols[0]}"
    )


def test_a_pinned_row_on_a_free_standing_balloon_is_honoured() -> None:
    fs, fic = _panel()
    fic.pin(row=0)
    fs.layout()

    _, rows = _grid(fs)
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

    cols, _ = _grid(fs)
    assert fic.frame is not None
    assert max(cols) < 7, "this sheet is supposed to be narrower than the pin"
    pitch = (cols[max(cols)] - cols[min(cols)]) / (max(cols) - min(cols))
    assert fic.frame.x == cols[max(cols)] + (7 - max(cols)) * pitch


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
