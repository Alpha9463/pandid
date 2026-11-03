"""Equipment placement, read off the drawn sheet.

``Flowsheet.layout()`` places equipment and boundary flags as a layered
graph (:mod:`pandid.layout.layered`). What is held here is what an author
can see on the sheet:

- **a pin lands where it was put**, at every density of pinning from none
  to all but one;
- **nozzle faces and flow set the direction**: flow runs east, a return
  line runs west, a peer sits on the side its nozzle is drawn on under a
  mirror or a turn, and a top-to-bottom pipe stacks its two units;
- **the same model draws the same sheet**, across processes with
  different string-hash seeds and across a ``to_dict``/``from_dict``
  round trip;
- **the retired placement hints are reported**: a class that still sets
  ``PLACES`` or ``LAYOUT_CONFIDENCE`` is told so.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from pandid import Flowsheet, devices as D, units as U
from pandid.geometry import Frame
from pandid.portgeom import port_faces

from _layout_cases import frame_of, nozzle_of

ROOT = Path(__file__).resolve().parent.parent

#: Shares of a sheet's units pinned by the pin sweeps.
SHARES = (0.0, 0.25, 0.5, 0.75, 1.0)


# ---------------------------------------------------------------------------
# Reading the drawing
# ---------------------------------------------------------------------------


def _frames(fs: Flowsheet) -> dict[str, Frame]:
    """Return every unit's frame by tag.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.

    Returns
    -------
    dict[str, Frame]
        Frame of each unit, keyed by its name.
    """
    return {unit.name: frame_of(unit) for unit in fs.units}


# ---------------------------------------------------------------------------
# The mock flowsheets the sweeps run over
# ---------------------------------------------------------------------------


def _train(name: str, length: int) -> Flowsheet:
    """Build a straight run: feed, a line of pumps and drums, product.

    Parameters
    ----------
    name : str
        Sheet name.
    length : int
        Number of units between the flags.

    Returns
    -------
    Flowsheet
        Unpinned flowsheet.
    """
    fs = Flowsheet(name)
    port = fs.add(U.Feed("F")).outlet
    for i in range(length):
        unit = fs.add(U.Pump(f"P-{i}") if i % 2 else U.Vessel(f"V-{i}"))
        fs.connect(port, unit.ports["suction" if i % 2 else "in_1"])
        port = unit.ports["discharge" if i % 2 else "out_1"]
    fs.connect(port, fs.add(U.Product("OUT")).inlet)
    return fs


def _tower() -> Flowsheet:
    """Build a column with an overhead system and a reboiler loop.

    Returns
    -------
    Flowsheet
        Unpinned flowsheet.
    """
    fs = Flowsheet("tower")
    feed = fs.add(U.Feed("F"))
    col = fs.add(U.DistillationColumn("T-1"))
    cond = fs.add(D.Condenser("E-1"))
    drum = fs.add(U.Vessel("V-1", variant="horizontal"))
    pump = fs.add(U.Pump("P-1"))
    top = fs.add(U.Product("Distillate"))
    reb = fs.add(D.KettleReboiler("E-2"))
    bottom = fs.add(U.Product("Bottoms"))
    fs.connect(feed.outlet, col.feed)
    fs.connect(col.overhead, cond.shell_in)
    fs.connect(cond.shell_out, drum.inlet)
    fs.connect(drum.outlet, pump.suction)
    fs.connect(pump.discharge, top.inlet)
    fs.connect(col.bottoms, reb.shell_in)
    fs.connect(reb.shell_out, col.boilup_in)
    fs.connect(reb.bottoms, bottom.inlet)
    return fs


def _recycle() -> Flowsheet:
    """Build a loop: mixer, reactor, separator, and the gas back round.

    Returns
    -------
    Flowsheet
        Unpinned flowsheet with one return line, compressor to mixer.
    """
    fs = Flowsheet("recycle")
    feed = fs.add(U.Feed("F"))
    mix = fs.add(U.Mixer("M-1", n_inlets=2))
    react = fs.add(U.Reactor("R-1"))
    sep = fs.add(U.Separator("V-1"))
    comp = fs.add(U.Compressor("K-1"))
    out = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, mix.in_1)
    fs.connect(mix.outlet, react.feed)
    fs.connect(react.outlet, sep.feed)
    fs.connect(sep.liquid, out.inlet)
    fs.connect(sep.vapor, comp.suction)
    fs.connect(comp.discharge, mix.in_2, draw_as_recycle=True)
    return fs


def _two_trains() -> Flowsheet:
    """Build two trains that share no run at all, and an orphan, on one sheet.

    Returns
    -------
    Flowsheet
        Unpinned flowsheet of three disconnected pieces.
    """
    fs = Flowsheet("two trains")
    for tag in ("A", "B"):
        port = fs.add(U.Feed(f"F-{tag}")).outlet
        for i in range(3):
            block = fs.add(U.Block(f"{tag}-{i}", inputs=["W"], outputs=["E"]))
            fs.connect(port, block.in_1)
            port = block.out_1
        fs.connect(port, fs.add(U.Product(f"OUT-{tag}")).inlet)
    fs.add(U.Vessel("ORPHAN"))  # joined to nothing at all
    return fs


def _mocks() -> list[Flowsheet]:
    """Build every mock sheet afresh.

    Returns
    -------
    list[Flowsheet]
        Unpinned flowsheets.
    """
    return [_train("short train", 3), _train("long train", 9), _tower(), _recycle(), _two_trains()]


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------


def _held(fs: Flowsheet, share: float, seed: int) -> dict[U.Unit, tuple[int, int]]:
    """Pin about ``share`` of a sheet's units to distinct grid cells.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to pin.
    share : float
        Fraction of its units to pin; above 0.99 pins all but one.
    seed : int
        Seed for the choice of units and cells.

    Returns
    -------
    dict[Unit, tuple[int, int]]
        The ``(col, row)`` each pinned unit was given.
    """
    units = [u for u in fs.units if u.kind != "instrument"]
    count = len(units) - 1 if share > 0.99 else round(len(units) * share)
    rng = random.Random(seed)
    chosen = [units[i] for i in sorted(rng.sample(range(len(units)), count))]
    cells = sorted({(rng.randrange(-2, 12), rng.randrange(-2, 8)) for _ in range(len(units) * 6)})
    rng.shuffle(cells)
    wanted = dict(zip(chosen, cells))
    for unit, (col, row) in wanted.items():
        unit.pin(col=col, row=row)
    return wanted


def test_a_col_pin_sets_the_layer_at_every_density() -> None:
    """None, a quarter, a half, three quarters, and all but one pinned.

    The frame reports the column the unit was pinned to, and the drawing
    agrees: a unit pinned to a lower column is drawn west of one pinned to
    a higher column.
    """
    for share in SHARES:
        for seed, fs in enumerate(_mocks()):
            wanted = _held(fs, share, seed * 17 + int(share * 100))
            fs.layout()
            for unit, (col, _) in wanted.items():
                assert frame_of(unit).col == col, (
                    f"{fs.name} at {share:.0%} pinned: {unit.name} was pinned to "
                    f"col {col} and drew in col {frame_of(unit).col}"
                )
            for west, (west_col, _) in wanted.items():
                for east, (east_col, _) in wanted.items():
                    assert west_col >= east_col or frame_of(west).x < frame_of(east).x, (
                        f"{fs.name} at {share:.0%} pinned: {west.name} (col {west_col}) "
                        f"is drawn east of {east.name} (col {east_col})"
                    )


def test_a_row_pin_orders_its_column_at_every_density() -> None:
    """Within one pinned column, a unit pinned to a lower row is drawn higher.

    The frame reports the row the unit was pinned to, so the drawing has to
    agree with it: frames that say one order over ink that shows another
    have not honoured the pin.
    """
    for share in SHARES:
        for seed, fs in enumerate(_mocks()):
            wanted = _held(fs, share, seed * 17 + int(share * 100))
            fs.layout()
            for unit, (_, row) in wanted.items():
                assert frame_of(unit).row == row
            for upper, (col, upper_row) in wanted.items():
                for lower, (lower_col, lower_row) in wanted.items():
                    if col != lower_col or upper_row >= lower_row:
                        continue
                    assert frame_of(upper).y < frame_of(lower).y, (
                        f"{fs.name} at {share:.0%} pinned: {upper.name} (row {upper_row}) "
                        f"is drawn below {lower.name} (row {lower_row}) in col {col}"
                    )


# ---------------------------------------------------------------------------
# Separation
# ---------------------------------------------------------------------------


def test_no_two_units_overlap_when_nothing_is_pinned() -> None:
    """Every mock sheet draws each unit clear of every other."""
    for fs in _mocks():
        fs.layout()
        found = [issue.message for issue in fs.validate() if issue.code == "unit-overlap"]
        assert not found, f"{fs.name}: {found}"


def test_a_disconnected_piece_gets_a_band_of_its_own() -> None:
    """Two trains and an orphan, none of them joined, none sharing a height."""
    fs = _two_trains()
    fs.layout()
    spans: dict[str, tuple[float, float]] = {}
    for unit in fs.units:
        frame = frame_of(unit)
        tags = unit.name.split("-")
        piece = "A" if "A" in tags else "B" if "B" in tags else "orphan"
        top, bottom = spans.get(piece, (frame.y, frame.y_max))
        spans[piece] = (min(top, frame.y), max(bottom, frame.y_max))
    pieces = sorted(spans.values())
    for (_, bottom), (top, _) in zip(pieces, pieces[1:]):
        assert bottom <= top, f"two pieces share a band: {spans}"


# ---------------------------------------------------------------------------
# Direction: nozzle faces and flow
# ---------------------------------------------------------------------------


def test_flow_runs_east_and_a_return_line_runs_west() -> None:
    """The loop is read in flow order and the gas comes back west to the mixer."""
    fs = _recycle()
    fs.layout()
    at = _frames(fs)
    train = ["F", "M-1", "R-1", "V-1", "K-1"]
    assert sorted(train, key=lambda name: at[name].x) == train, {n: at[n].x for n in train}
    assert at["V-1"].x < at["Product"].x
    assert at["M-1"].x < at["K-1"].x, "the return line runs west, compressor to mixer"


def _pump_line(*, mirrored: bool) -> dict[str, Frame]:
    """Lay out feed, pump and product with nothing placed but the pump's mirror.

    Parameters
    ----------
    mirrored : bool
        Whether the pump is drawn mirrored.

    Returns
    -------
    dict[str, Frame]
        Frames of ``F``, ``P-1`` and ``Pr``.
    """
    fs = Flowsheet("mirrored pump" if mirrored else "plain pump")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-1")).pin(mirrored=mirrored)
    prod = fs.add(U.Product("Pr"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, prod.inlet)
    fs.layout()
    return _frames(fs)


def test_a_mirrored_pump_draws_its_peers_on_the_mirrored_side() -> None:
    """A mirror swaps the sides a pump's peers sit on, because it swaps its nozzles.

    Drawn ``mirrored=True`` the pump's suction is on its east face, so its
    supply is drawn east of it and the train reads right to left, which is
    the whole of what mirroring a pump asks for (#471).
    """
    at = _pump_line(mirrored=False)
    assert at["F"].x < at["P-1"].x < at["Pr"].x

    at = _pump_line(mirrored=True)
    assert at["Pr"].x < at["P-1"].x < at["F"].x, (
        "a mirrored pump draws its supply on the side its suction is drawn on: "
        f"F at {at['F'].x}, P-1 at {at['P-1'].x}, Pr at {at['Pr'].x}"
    )


def test_a_condenser_sits_beside_the_column_top() -> None:
    """The overhead condenser is drawn east of the tower, level with its top nozzle.

    Both nozzles are on top faces, so neither says which side the condenser
    goes: flow order puts it east, and its inlet is drawn no lower than the
    overhead nozzle that feeds it.
    """
    fs = Flowsheet("overhead")
    col = fs.add(U.DistillationColumn("T-1"))
    cond = fs.add(D.Condenser("E-1"))
    fs.connect(col.overhead, cond.shell_in)
    fs.layout()
    assert frame_of(col).x_max < frame_of(cond).x
    assert nozzle_of(cond, "shell_in")[1] <= nozzle_of(col, "overhead")[1] + 0.5, (
        f"the condenser inlet at {nozzle_of(cond, 'shell_in')} is below the overhead "
        f"nozzle at {nozzle_of(col, 'overhead')}"
    )


def test_a_turned_unit_places_its_peers_on_its_turned_faces() -> None:
    """A quarter turn moves the overhead nozzle to a side, and the condenser with it.

    Turned 90 degrees clockwise the overhead leaves the east face and the
    condenser is drawn east; turned 270 it leaves the west face and the
    condenser is drawn west, against flow order.
    """
    for turn, face in ((90, "E"), (270, "W")):
        fs = Flowsheet(f"column turned {turn}")
        col = fs.add(U.DistillationColumn("T-1")).pin(orientation=turn)
        cond = fs.add(D.Condenser("E-1"))
        fs.connect(col.overhead, cond.shell_in)
        fs.layout()
        assert port_faces(col, "overhead") == [face]
        tower, peer = frame_of(col), frame_of(cond)
        if face == "E":
            assert tower.x_max < peer.x, f"turned {turn}: the condenser is not east"
        else:
            assert peer.x_max < tower.x, f"turned {turn}: the condenser is not west"


def test_a_top_to_bottom_pipe_stacks_its_units_with_nozzles_lined_up() -> None:
    """A pipe from a bottom nozzle to a top nozzle puts one unit over the other.

    Both are drawn in one layer, the upper one wholly above, and the two
    nozzles share an x so the pipe drops straight.
    """
    fs = Flowsheet("stack")
    upper = fs.add(U.Block("A", inputs=["W"], outputs=["S"]))
    lower = fs.add(U.Block("B", inputs=["N"], outputs=["E"]))
    fs.connect(upper.out_1, lower.in_1)
    fs.layout()
    assert frame_of(upper).col == frame_of(lower).col
    assert frame_of(upper).y_max < frame_of(lower).y
    drop, landing = nozzle_of(upper, "out_1"), nozzle_of(lower, "in_1")
    assert abs(drop[0] - landing[0]) <= 0.5, f"the stack's nozzles {drop} and {landing}"


def test_a_header_stays_between_the_column_and_the_bank_it_feeds() -> None:
    """A free header sits between its pinned supply and its pinned bank at every size.

    Between a column pinned to column 0 and one to eight pumps pinned to
    column 4, the header is drawn east of the column, west of the bank, and
    level with the bank rather than off either end of it.
    """
    for pumps in range(1, 9):
        fs = Flowsheet("manifold")
        col = fs.add(U.Column("T-1")).pin(col=0, row=0)
        header = fs.add(U.Splitter("H-1", n_outlets=pumps))
        fs.connect(col.bottoms, header.inlet)
        bank = []
        for i in range(pumps):
            pump = fs.add(U.Pump(f"P-{i + 1}")).pin(col=4, row=i)
            fs.connect(header.outlets[i], pump.suction)
            bank.append(pump)
        fs.layout()
        at = frame_of(header)
        frames = [frame_of(pump) for pump in bank]
        assert frame_of(col).x_max < at.x and at.x_max < min(f.x for f in frames), (
            f"{pumps} pumps: the header left the run between the column and the bank"
        )
        assert min(f.y for f in frames) <= at.y and at.y_max <= max(f.y_max for f in frames), (
            f"{pumps} pumps: the header is not level with the bank it feeds"
        )


def test_a_header_is_not_sunk_by_the_bank_it_supplies() -> None:
    """#459: five heaters do not drag their steam header below them.

    Each heater takes its steam on a bottom nozzle. What is asserted is the
    shape and not a crossing count: the header lands level with the bank it
    feeds, never under all of it.
    """
    fs = Flowsheet("LP steam users")
    steam = fs.add(U.Feed("LP Steam"))
    condensate = fs.add(U.Product("Condensate"))
    heaters = [fs.add(U.Heater(f"E-10{i}")) for i in range(1, 6)]
    for heater in heaters:
        fs.connect(steam.outlet, heater.utility_in)
        fs.connect(heater.outlet, condensate.inlet)
    fs.layout()
    top = min(frame_of(h).y for h in heaters)
    bottom = max(frame_of(h).y_max for h in heaters)
    header = frame_of(steam)
    assert top <= header.y and header.y_max <= bottom, (
        f"the header spans {header.y:.0f}..{header.y_max:.0f}, outside the bank's "
        f"{top:.0f}..{bottom:.0f}"
    )


# ---------------------------------------------------------------------------
# The same model draws the same sheet
# ---------------------------------------------------------------------------


def _geometry(fs: Flowsheet) -> list[tuple[str, float, float, int | None, int | None]]:
    """Return each unit's tag, corner and grid cell.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.

    Returns
    -------
    list[tuple[str, float, float, int or None, int or None]]
        ``(name, x, y, col, row)`` per framed unit, in sheet order.
    """
    return [
        (u.name, u.frame.x, u.frame.y, u.frame.col, u.frame.row)
        for u in fs.units
        if u.frame is not None
    ]


def test_a_round_trip_through_a_dict_draws_the_same_sheet() -> None:
    """A sheet rebuilt from ``to_dict`` lays out exactly as the original."""
    for fs in _mocks():
        fs.layout()
        before = _geometry(fs)
        again = Flowsheet.from_dict(fs.to_dict())
        again.layout()
        assert _geometry(again) == before, f"{fs.name} moved across a round trip"


_UNDER_A_SEED = """
import json, sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[1] + "/tests")
from test_placement import _mocks, _geometry
out = []
for fs in _mocks():
    fs.layout()
    out.append(_geometry(fs))
print(json.dumps(out))
"""


def test_the_sheet_does_not_depend_on_the_string_hash_seed() -> None:
    """Run in fresh processes, so ``PYTHONHASHSEED`` really differs.

    A dict or a set iterated somewhere in placement would show up here
    and nowhere else: within one process every run agrees with itself.
    """
    answers = set()
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        done = subprocess.run(
            [sys.executable, "-c", _UNDER_A_SEED, str(ROOT)],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        answers.add(json.dumps(json.loads(done.stdout)))
    assert len(answers) == 1, "the sheet changed with PYTHONHASHSEED"


# ---------------------------------------------------------------------------
# The retired placement hints
# ---------------------------------------------------------------------------


def _shipped_unit_classes() -> list[type[U.Unit]]:
    """Return every ``Unit`` subclass pandid itself defines.

    Test fixtures elsewhere subclass ``Unit`` too, and pytest has imported
    them by the time this runs, so the walk keeps pandid's modules only.

    Returns
    -------
    list[type[Unit]]
        Shipped unit classes, ``Unit`` included.
    """
    found: dict[type[U.Unit], None] = {}
    pending: list[type[U.Unit]] = [U.Unit]
    while pending:
        cls = pending.pop()
        if cls in found:
            continue
        pending.extend(cls.__subclasses__())
        if cls.__module__.partition(".")[0] == "pandid":
            found[cls] = None
    return list(found)


def test_a_placement_hint_is_deprecated() -> None:
    """``PLACES`` or ``LAYOUT_CONFIDENCE`` on a subclass warns and is reported.

    Layout reads nozzle faces now, so a class that still states either is
    told so twice, by a ``DeprecationWarning`` and by a ``deprecated``
    finding carrying the same sentence. No class pandid ships states either.
    """

    class Placed(U.Pump):
        PLACES = {"suction": "W"}

    class Confident(U.Pump):
        LAYOUT_CONFIDENCE = 4

    for hinted in (Placed, Confident):
        fs = Flowsheet("hinted")
        with pytest.warns(DeprecationWarning, match="PLACES or LAYOUT_CONFIDENCE") as caught:
            fs.add(hinted("P-1"))
        found = [issue.message for issue in fs.validate() if issue.code == "deprecated"]
        assert found == [str(caught[0].message)], f"{hinted.__name__}: {found}"

    with warnings.catch_warnings(record=True) as heard:
        warnings.simplefilter("always")
        for cls in _shipped_unit_classes():
            cls("X-1")
    stated = [str(w.message) for w in heard if "PLACES or LAYOUT_CONFIDENCE" in str(w.message)]
    assert not stated, stated
