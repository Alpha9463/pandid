"""The placement fit: its arithmetic, its boundary conditions, its determinism.

``pandid.layout.place`` states where every process unit goes by fitting
every claim the equipment makes at once, in the least-squares sense, and
then making the answer legal. Three things have to hold whatever a sheet
looks like, and they are what is tested here:

- **a pin is a boundary condition**, honoured exactly at every density
  of pinning from none to all-but-one;
- **the fit is exact**, not approached -- the residual of the system it
  claims to solve is zero, and a hand-solvable case comes out at the
  hand-solved answer;
- **the same model draws the same sheet**, across processes with
  different string-hash seeds and across a ``to_dict``/``from_dict``
  round trip.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import warnings
from pathlib import Path

from pandid import Flowsheet, devices as D, units as U
from pandid.geometry import Pin
from pandid.layout import claims as claims_mod
from pandid.layout import solver
from pandid.portgeom import drawn_direction, port_faces
from pandid.render.symbols import default_registry

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# The mock flowsheets the pin sweep runs over
# ---------------------------------------------------------------------------


def _train(name: str, length: int) -> Flowsheet:
    """A straight run: feed, a line of pumps and drums, product."""
    fs = Flowsheet(name)
    port = fs.add(U.Feed("F")).outlet
    for i in range(length):
        unit = fs.add(U.Pump(f"P-{i}") if i % 2 else U.Vessel(f"V-{i}"))
        fs.connect(port, unit.ports["suction" if i % 2 else "in_1"])
        port = unit.ports["discharge" if i % 2 else "out_1"]
    fs.connect(port, fs.add(U.Product("OUT")).inlet)
    return fs


def _tower() -> Flowsheet:
    """A column with an overhead system and a reboiler loop."""
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
    """A loop: mixer, reactor, separator, and the gas back round."""
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
    """Two trains that share no run at all, on one sheet.

    The disconnected case: each piece is anchored on its own, so this is
    where an unanchored component or two components fitted on top of
    each other would show up.
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
    return [_train("short train", 3), _train("long train", 9), _tower(), _recycle(), _two_trains()]


# ---------------------------------------------------------------------------
# Pins are boundary conditions
# ---------------------------------------------------------------------------


def _place(units: list[U.Unit], seed: int) -> dict[U.Unit, tuple[int, int]]:
    """A distinct ``(col, row)`` per unit, from a fixed generator."""
    rng = random.Random(seed)
    cells = sorted({(rng.randrange(-2, 12), rng.randrange(-2, 8)) for _ in range(len(units) * 6)})
    rng.shuffle(cells)
    return dict(zip(units, cells))


def _held(fs: Flowsheet, share: float, seed: int) -> dict[U.Unit, tuple[int, int]]:
    """Pin about ``share`` of the sheet's units, and say where."""
    units = [u for u in fs.units if u.kind != "instrument"]
    count = len(units) - 1 if share > 0.99 else round(len(units) * share)
    rng = random.Random(seed)
    chosen = sorted(rng.sample(range(len(units)), count))
    wanted = _place([units[i] for i in chosen], seed)
    for unit, (col, row) in wanted.items():
        unit.pin(col=col, row=row)
    return wanted


def test_a_pin_lands_where_it_was_put_at_every_density() -> None:
    """0, a quarter, a half, three quarters, and all but one.

    The last is the sharpest: the single free unit is placed entirely by
    the boundary conditions around it, which is the case an engine that
    treated pins as a preference to be reconciled would get wrong.
    """
    for share in (0.0, 0.25, 0.5, 0.75, 1.0):
        for seed, fs in enumerate(_mocks()):
            wanted = _held(fs, share, seed * 17 + int(share * 100))
            fs.layout()
            for unit, (col, row) in wanted.items():
                assert unit.frame is not None
                assert (unit.frame.col, unit.frame.row) == (col, row), (
                    f"{fs.name} at {share:.0%} pinned: {unit.name} was pinned to "
                    f"({col}, {row}) and drew at "
                    f"({unit.frame.col}, {unit.frame.row})"
                )


def test_no_two_units_share_a_cell_when_nothing_is_pinned() -> None:
    """What the separation pass is for, over the same mock sheets."""
    for fs in _mocks():
        fs.layout()
        cells = [
            (u.frame.col, u.frame.row)
            for u in fs.units
            if u.frame is not None and u.kind != "instrument"
        ]
        assert len(cells) == len(set(cells)), f"{fs.name} drew two units in one cell"


def test_a_disconnected_piece_gets_a_band_of_its_own() -> None:
    """Two trains and an orphan, none of them joined, none overlapping."""
    fs = _two_trains()
    fs.layout()
    bands: dict[str, set[int]] = {}
    for u in fs.units:
        assert u.frame is not None and u.frame.row is not None
        piece = "orphan" if u.name == "ORPHAN" else u.name.rpartition("-")[2][0]
        bands.setdefault(piece, set()).add(u.frame.row)
    assert bands["A"].isdisjoint(bands["B"]), "the two trains share a band"
    assert bands["orphan"].isdisjoint(bands["A"] | bands["B"])


# ---------------------------------------------------------------------------
# The fit is exact
# ---------------------------------------------------------------------------


def test_the_solver_returns_the_hand_solved_answer() -> None:
    """Three nodes, one anchored, weights chosen so the answer is exact.

    Claims: 0 says 1 is one step on at weight 3; 2 says 1 is one step
    back at weight 1. With 0 anchored at zero and 2 free, stationarity
    gives ``p1 = 1`` and ``p2 = 2`` exactly -- both claims satisfied,
    since there is an arrangement that satisfies both.
    """
    pulls: list[solver.Pull] = [(0, 1, 3.0, 1.0), (2, 1, 1.0, -1.0)]
    answer = solver.relax(3, pulls, {0: 0.0})
    assert answer == [0.0, 1.0, 2.0]


def test_a_disagreement_settles_where_the_weights_put_it() -> None:
    """Two claims about one pair, pulling opposite ways.

    ``0`` insists ``1`` is a step east at weight 3; ``1`` insists ``0``
    is a step east of *it* at weight 1. The compromise is
    ``(3 * 1 + 1 * -1) / 4`` -- and it is a compromise, not one of the
    two claims winning and the other being dropped.
    """
    pulls: list[solver.Pull] = [(0, 1, 3.0, 1.0), (1, 0, 1.0, 1.0)]
    answer = solver.relax(2, pulls, {0: 0.0})
    assert answer == [0.0, 0.5]


def test_every_component_needs_an_anchor() -> None:
    """An unanchored component is a singular matrix, and says so."""
    pulls: list[solver.Pull] = [(0, 1, 1.0, 1.0), (2, 3, 1.0, 1.0)]
    assert [sorted(g) for g in solver.components(4, pulls)] == [[0, 1], [2, 3]]
    try:
        solver.relax(4, pulls, {0: 0.0})
    except AssertionError:
        return
    raise AssertionError("an unanchored component was solved anyway")


def test_a_half_step_rounds_away_from_zero_on_both_sides() -> None:
    """The mirror of a sheet is the same sheet, so 0.5 and -0.5 cannot
    round the same way. Python's own ``round`` sends both to zero."""
    assert solver.discretise(0.5) == 1
    assert solver.discretise(-0.5) == -1
    assert solver.discretise(1.5) == 2
    assert solver.discretise(-1.5) == -2
    # And a half that arrives a hair short of one is still a half.
    assert solver.discretise(0.5 - 1e-12) == 1


# ---------------------------------------------------------------------------
# Claims are what the equipment says
# ---------------------------------------------------------------------------


def test_a_stream_is_claimed_by_each_end_that_speaks() -> None:
    """Two ends with something to say are two claims, disagreeing freely."""
    fs = Flowsheet("both ends")
    col = fs.add(U.DistillationColumn("T-1"))
    cond = fs.add(D.Condenser("E-1"))
    fs.connect(col.overhead, cond.shell_in)
    fs.layout()

    from pandid.layout.stages import process_streams

    claims = claims_mod.read(process_streams(fs))
    assert len(claims) == 2
    by_author = {c.author: c for c in claims}
    assert by_author[col] == claims_mod.Claim(col, cond, 1, -1, 8.0), (
        "the column places its overhead peer north east of it, at a column's weight"
    )
    assert by_author[cond].confidence == 2.0, "the exchanger answers at its own weight"
    # They disagree, which is the point: the condenser reads its own
    # inlet face, which is fixed north, and so says the column is above
    # *it*. Nothing here reconciles them; the fit does.
    assert (by_author[cond].eastward, by_author[cond].southward) == (0, -1)


def test_a_silent_end_is_not_dropped_because_the_other_spoke() -> None:
    """One stated end and one silent one is one claim: the stated one.

    The half of the two-claim contract that survives its amendment (see
    :mod:`pandid.layout.claims`). What the old engine did here was rank
    the two ends and keep the winner; what is wrong with that is not the
    count but that ranking throws away a statement. There is nothing to
    throw away when the other end is a block valve.
    """
    fs = Flowsheet("one end")
    col = fs.add(U.DistillationColumn("T-1"))
    valve = fs.add(D.ControlValve("FV-1"))
    fs.connect(col.overhead, valve.inlet)
    fs.layout()

    from pandid.layout.stages import process_streams

    claims = claims_mod.read(process_streams(fs))
    assert claims == [claims_mod.Claim(col, valve, 1, -1, 8.0)]


def _classes_that_state_a_direction() -> list[type]:
    """Every ``pandid.units`` class whose ``PLACES`` names a compass point.

    Walked off ``Unit.__subclasses__`` and filtered to the module, exactly as
    ``tests/test_variants._unit_classes`` does and for the same reason: this
    file and two others subclass ``Unit`` for fixtures, and pytest has already
    imported them by the time a sweep runs.
    """
    found: dict[type, None] = {}
    pending = [U.Unit]
    while pending:
        cls = pending.pop()
        if cls in found:
            continue
        pending.extend(cls.__subclasses__())
        if cls.__module__ == U.__name__ and any(entry is not None for entry in cls.PLACES.values()):
            found[cls] = None
    return list(found)


#: Every placement transform a unit can be drawn under.
_TRANSFORMS = [
    Pin(orientation=turn, mirrored=mirror_x, mirror_y=mirror_y)
    for turn in (0, 90, 180, 270)
    for mirror_x in (False, True)
    for mirror_y in (False, True)
]


def _pump_line(*, mirrored: bool) -> tuple[Flowsheet, U.Unit, U.Unit, U.Unit]:
    """Feed -> pump -> product, with nothing placed but the pump's mirror."""
    fs = Flowsheet("mirrored pump" if mirrored else "plain pump")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-1")).pin(mirrored=mirrored)
    prod = fs.add(U.Product("Pr"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, prod.inlet)
    fs.layout()
    return fs, feed, pump, prod


def test_a_places_entry_is_read_as_the_unit_is_drawn() -> None:
    """A mirror swaps the sides a class states, because it swaps its nozzles.

    ``Pump.PLACES`` puts suction west and discharge east -- written in the
    symbol's own frame, beside the artwork it describes. Draw the pump
    ``mirrored=True`` and the artwork puts suction east, so a class still
    asserting its supply lies west asserts that the peer sits on the side the
    nozzle has just left, and the run has to cross the body to reach it. The
    author's mirror was honoured in the ink and discarded in the fit (#471):
    stated, accepted, and silently not done.
    """
    from pandid.layout.stages import process_streams

    fs, feed, pump, prod = _pump_line(mirrored=False)
    assert claims_mod.read(process_streams(fs)) == [
        claims_mod.Claim(pump, feed, -1, 0, 2.0),
        claims_mod.Claim(pump, prod, 1, 0, 2.0),
    ]
    assert feed.frame is not None and pump.frame is not None and prod.frame is not None
    assert feed.frame.x < pump.frame.x < prod.frame.x

    fs, feed, pump, prod = _pump_line(mirrored=True)
    assert claims_mod.read(process_streams(fs)) == [
        claims_mod.Claim(pump, feed, 1, 0, 2.0),
        claims_mod.Claim(pump, prod, -1, 0, 2.0),
    ], "a mirrored pump draws its supply on the side its suction is drawn on"
    # And the sheet follows the claim: the train reads right to left, which is
    # the whole of what mirroring a pump asks for.
    assert feed.frame is not None and pump.frame is not None and prod.frame is not None
    assert prod.frame.x < pump.frame.x < feed.frame.x


def test_a_diagonal_convention_turns_with_the_unit() -> None:
    """Not only the faces: the drafting convention itself is in the symbol's frame.

    A column's ``overhead -> "NE"`` is the condenser drawn top *right*, which
    reads that way because the sheet runs left to right past the tower. Mirror
    the tower and it does not: the overhead nozzle is still north and the
    column now reads right to left, so top left is where the same convention
    puts the condenser.
    """
    from pandid.layout.stages import process_streams

    fs = Flowsheet("mirrored column")
    col = fs.add(U.DistillationColumn("T-1")).pin(mirrored=True)
    cond = fs.add(D.Condenser("E-1"))
    fs.connect(col.overhead, cond.shell_in)
    fs.layout()

    stated = [c for c in claims_mod.read(process_streams(fs)) if c.author is col]
    assert stated == [claims_mod.Claim(col, cond, -1, -1, 8.0)]


def test_an_entry_that_restates_a_fixed_face_says_what_the_artwork_says() -> None:
    """A redundant entry is a no-op again -- under every transform, which is the point.

    An entry that merely restates the face the symbol already fixes was worse
    than no entry at all: a no-op on an unmirrored unit and silently wrong on a
    mirrored one, because the untransformed literal replaced a value that
    ``fixed_face`` would have flipped. Deleting them was the first fix proposed
    for #471 and it cannot be done: ``Vessel.PLACES["in"]`` restates the face on
    the vertical artwork and states a real convention on the horizontal one, so
    redundancy is a fact about a *variant* and the table is per class.

    Read as drawn, the two rungs of the ladder are the same statement again
    wherever they were ever the same statement. That is what this sweeps --
    every class in the library that states a direction, every variant of it
    registered, every quarter turn and mirror -- so nothing has to be deleted
    and the next contributor who adds one "for clarity" adds a no-op rather
    than a hazard.
    """
    restated: set[str] = set()
    for cls in _classes_that_state_a_direction():
        for variant in default_registry.variants(cls.kind) or ["default"]:
            # A few shipped variants are deprecated spellings. They are still
            # registered artwork and still have to answer this, and the notice
            # they raise is ``tests/test_variants``'s subject rather than
            # this one's.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                unit = cls("X-1", variant=variant)
            for key, entry in cls.PLACES.items():
                if entry is None:
                    continue
                stated = entry[0] if isinstance(entry, tuple) else entry
                for port in unit.ports:
                    if port != key and claims_mod.family(port) != key:
                        continue
                    if port_faces(unit, port) != [stated]:
                        continue  # a menu, or a face the entry does not restate
                    restated.add(f"{cls.__name__}.{port}")
                    for placed in _TRANSFORMS:
                        assert port_faces(unit, port, placed) == [
                            drawn_direction(stated, placed)
                        ], f"{cls.__name__}[{variant}].{port} under {placed}"
    # Not a sweep that swept nothing: these are the entries #471 names, and
    # every one of them is in fact restated artwork.
    assert {
        "Pump.suction",
        "Pump.discharge",
        "Compressor.suction",
        "Vessel.vent",
        "Tank.drain",
    } <= restated


def test_a_return_line_states_the_pipe_once() -> None:
    """A recycle is the pipe speaking, so it speaks once and at RETURN.

    Twice, once per end, is the same pull written down twice and was the
    2x stiffness asymmetry between forward and return plumbing. The
    weight it adds up to is kept and stated; what goes is the doubling
    happening where nobody could see it.
    """
    fs = Flowsheet("loop")
    col = fs.add(U.DistillationColumn("T-1"))
    drum = fs.add(U.Vessel("V-1", variant="horizontal"))
    fs.connect(col.overhead, drum.ports["in_1"])
    fs.connect(drum.ports["out_1"], col.reflux_in)
    fs.layout()

    from pandid.layout.stages import process_streams

    streams = process_streams(fs)
    returns = [s for s in streams if s.is_recycle]
    assert len(returns) == 1, "the loop is torn once"
    claims = claims_mod.read(streams)
    stated = [c for c in claims if c.confidence == claims_mod.RETURN]
    assert len(stated) == 1
    assert claims_mod.RETURN == 2 * claims_mod.LINE


def test_a_manifold_is_moved_by_the_bank_it_feeds() -> None:
    """Connection count outweighs declared confidence, on purpose.

    A header is a piece of piping and states nothing. Between a column
    that places its bottoms peer south east at confidence 8 and a bank
    of pumps each placing their suction peer west at 2, the pumps win as
    soon as there are five of them -- 10 against 8 -- and the header
    leaves the column's nozzle row for the middle of the bank.

    That is the approved design working, not failing: "a highly
    connected unit becomes stiff by connection count alone. Emergent,
    not declared" (#447). It is also the better drawing -- a header
    feeding five pumps belongs level with the middle of the five, not
    level with one end of the run into it.

    Normalising the weight by degree does not undo it and is not the
    remedy it looks like. Dividing every claim *about* the header by the
    header's own degree scales its whole barycentre, numerator and
    denominator alike, and moves it nowhere; dividing each unit's claims
    by its *own* degree leaves a pump at degree two however many pumps
    there are. Measured over the corpus the two cost 63 and 46 crossings
    respectively and this drift is unchanged by either.

    So the drift is pinned rather than fixed: what is guarded here is
    that it stays a drift **along the bank** and never a step to the
    wrong side of it -- the header stays between the column and the
    pumps at every size, which is the thing that would be a bug.
    """

    class Header(U.Splitter):
        LAYOUT_CONFIDENCE = 0
        PLACES: dict = {}

    seen = []
    for pumps in range(1, 9):
        fs = Flowsheet("manifold")
        col = fs.add(U.Column("T-1"))
        header = fs.add(Header("H-1", n_outlets=pumps))
        col.pin(col=0, row=0)
        fs.connect(col.bottoms, header.inlet)
        for i in range(pumps):
            pump = fs.add(U.Pump(f"P-{i + 1}"))
            pump.pin(col=4, row=i)
            fs.connect(header.outlets[i], pump.suction)
        fs.layout()
        assert header.frame is not None
        col_at, row_at = header.frame.col, header.frame.row
        assert col_at is not None and row_at is not None
        assert 0 < col_at < 4, (
            f"{pumps} pumps: the header left the paper between the column and "
            f"the bank for column {col_at}"
        )
        seen.append(row_at)

    assert seen == [1, 1, 1, 1, 2, 2, 2, 3], (
        "the header sits on the column's bottoms row until the bank musters "
        "more confidence than the column, and then follows the bank's middle"
    )


def test_a_valve_states_nothing_and_the_pipe_speaks_for_it() -> None:
    """Between two fittings there is no unit with an opinion at all."""
    fs = Flowsheet("in line")
    a = fs.add(D.ControlValve("FV-1"))
    b = fs.add(U.Reducer("RD-1"))
    fs.connect(a.outlet, b.inlet)
    fs.layout()

    from pandid.layout.stages import process_streams

    claims = claims_mod.read(process_streams(fs))
    assert claims == [claims_mod.Claim(a, b, 1, 0, claims_mod.LINE)]


def test_a_port_family_is_covered_by_one_entry() -> None:
    """``PLACES["feed"]`` answers for ``feed_1`` .. ``feed_n``."""
    assert claims_mod.family("feed_3") == "feed"
    assert claims_mod.family("draw_12") == "draw"
    assert claims_mod.family("shell_in") == "shell_in"
    assert claims_mod.family("in_1") == "in"


def test_a_nozzle_placed_nowhere_is_read_for_nothing() -> None:
    """``PLACES[port] = None`` stops the ladder: the face is not read.

    A heater's ``utility_in`` is fixed to the symbol's **south** face,
    and left to speak for itself it says "my steam supply is drawn below
    me" at the heater's own confidence of 2. It is not a statement about
    the sheet at all -- it is where the drawing puts the nozzle -- so the
    class declares the entry empty and what is left is the pipe: one
    claim, in flow order, at :data:`~pandid.layout.claims.LINE`.
    """
    fs = Flowsheet("steam user")
    steam = fs.add(U.Feed("LP Steam"))
    heater = fs.add(U.Heater("E-1"))
    fs.connect(steam.outlet, heater.utility_in)
    fs.layout()

    from pandid.layout.stages import process_streams

    claims = claims_mod.read(process_streams(fs))
    # The flag is confidence 0 and drops out, so the heater's is the one
    # claim there is: "the thing on my steam nozzle is a step west", not
    # "a step south", and weighed as the pipe rather than as the heater.
    assert claims == [claims_mod.Claim(heater, steam, -1, 0, claims_mod.LINE)]


def test_an_entry_of_none_is_not_the_same_as_no_entry() -> None:
    """A nozzle a class says nothing about still reads its own face.

    The two are one keystroke apart and mean opposite things, and
    ``dict.get`` cannot tell them apart -- it answers ``None`` to both.
    A cooler declares ``utility_out`` empty and says nothing at all
    about ``inlet``, whose west face therefore still speaks, at the
    cooler's own weight.
    """
    fs = Flowsheet("cooler")
    upstream = fs.add(U.Vessel("V-1"))
    cooler = fs.add(U.Cooler("E-1"))
    fs.connect(upstream.ports["out_1"], cooler.inlet)
    fs.layout()

    from pandid.layout.stages import process_streams

    assert "inlet" not in type(cooler).PLACES
    assert type(cooler).PLACES["utility_out"] is None
    claims = claims_mod.read(process_streams(fs))
    assert claims_mod.Claim(cooler, upstream, -1, 0, 2.0) in claims, (
        "the cooler's unmentioned inlet still reads its own west face, at 2"
    )


def test_a_header_is_not_sunk_by_the_bank_it_supplies() -> None:
    """#459: five heaters do not drag their steam header below them.

    The supply flag has no opinion of its own (a boundary is confidence
    0), so wherever the consumers put it is where it goes. Reading each
    heater's south-facing steam nozzle as a claim, five of them at 2
    mustered 10 saying "below me" and the header was drawn under the
    whole bank, with ten laterals running back up past every consumer.
    What is asserted here is the shape and not a crossing count: the
    header lands *level with* the bank it feeds, never under all of it.
    """
    fs = Flowsheet("LP steam users")
    steam = fs.add(U.Feed("LP Steam"))
    condensate = fs.add(U.Product("Condensate"))
    heaters = [fs.add(U.Heater(f"E-10{i}")) for i in range(1, 6)]
    for heater in heaters:
        fs.connect(steam.outlet, heater.utility_in)
        fs.connect(heater.outlet, condensate.inlet)
    fs.layout()

    rows = [h.frame.row for h in heaters if h.frame is not None and h.frame.row is not None]
    assert len(rows) == 5
    assert steam.frame is not None
    header_row = steam.frame.row
    assert header_row is not None
    assert min(rows) <= header_row <= max(rows), (
        f"the header is on row {header_row}, outside the bank's {rows}"
    )


# ---------------------------------------------------------------------------
# The same model draws the same sheet
# ---------------------------------------------------------------------------


def _geometry(fs: Flowsheet) -> list[tuple[str, float, float, int | None, int | None]]:
    return [
        (u.name, u.frame.x, u.frame.y, u.frame.col, u.frame.row)
        for u in fs.units
        if u.frame is not None
    ]


def test_a_round_trip_through_a_dict_draws_the_same_sheet() -> None:
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
