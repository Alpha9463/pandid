"""Check face selection for block, tank and vessel connection families."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pandid import Flowsheet, units
from pandid.layout import layered
from _quality import measure_final
from pandid.portgeom import port_anchor, resolve_port
from pandid.render.symbols import BLOCK_PITCH
from pandid.spec import from_dict, to_dict
from pandid.units import Unit


def _face(unit: Unit, port: str) -> str:
    """Return the face a placed unit's port is drawn on."""
    assert unit.frame is not None
    return port_anchor(unit, unit.frame, port)[2]


def _flag(fs: Flowsheet, unit: Unit, port: str, x: float, y: float, mirrored: bool) -> None:
    """Connect a unit's port to a boundary flag whose tip is at ``(x, y)``."""
    if unit.port(port).direction == "inlet":
        feed = fs.add(units.Feed(f"F-{port}")).pin(x=x, y=y, mirrored=mirrored)
        fs.connect(feed.outlet, unit.port(port))
    else:
        product = fs.add(units.Product(f"P-{port}")).pin(x=x, y=y, mirrored=mirrored)
        fs.connect(unit.port(port), product.inlet)


def _block(
    port: str, x: float, y: float, mirrored: bool = False, sheet: Flowsheet | None = None, **block
) -> tuple[Flowsheet, units.Block]:
    """Build a block at (300, 300) with one connection to a flag."""
    fs = sheet if sheet is not None else Flowsheet("bfd")
    b = fs.add(units.Block("Reaction", **block)).pin(x=300, y=300)
    _flag(fs, b, port, x, y, mirrored)
    return fs, b


# A 120 x 80 block at (300, 300): W (300, 340), E (420, 340), N (360, 300),
# S (360, 380); in_1 and out_1 on one side face sit at 325 and 355.
@pytest.mark.parametrize(
    ("port", "x", "y", "mirrored", "face"),
    [
        ("in_1", 340, 150, False, "N"),
        ("in_1", 340, 520, False, "S"),
        ("in_1", 100, 340, False, "W"),
        ("in_1", 650, 325, True, "E"),
        ("out_1", 650, 120, False, "N"),
        ("out_1", 650, 560, False, "S"),
        ("out_1", 80, 355, True, "W"),
        ("out_1", 650, 340, False, "E"),
    ],
    ids=[
        "in-above",
        "in-below",
        "in-left",
        "in-right",
        "out-above",
        "out-below",
        "out-left",
        "out-right",
    ],
)
def test_a_counted_block_connection_takes_the_face_toward_its_peer(port, x, y, mirrored, face):
    """Draw an unstated block connection on the face toward its peer."""
    fs, b = _block(port, x, y, mirrored)
    fs.route()
    assert _face(b, port) == face


def test_two_inlets_on_the_west_split_when_one_comes_from_above():
    """Move the inlet fed from above and leave its sibling on the west."""
    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Reaction", inputs=2)).pin(x=300, y=300)
    _flag(fs, b, "in_1", 100, 340, False)
    _flag(fs, b, "in_2", 340, 150, False)
    fs.route()
    assert (_face(b, "in_1"), _face(b, "in_2")) == ("W", "N")


@pytest.mark.parametrize(
    ("x", "y", "mirrored", "face"),
    [(340, 150, False, "N"), (100, 385, False, "W"), (650, 385, True, "E")],
    ids=["above", "left", "right"],
)
def test_a_second_tank_inlet_takes_the_face_toward_its_peer(x, y, mirrored, face):
    """Choose among the faces a tank's artwork offers an inlet."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=2)).pin(x=300, y=300)
    # in_1 sits at y = 385 alone on the west face and at 365 beside in_2.
    _flag(fs, tank, "in_1", 100, 300 if face == "W" else 385, False)
    _flag(fs, tank, "in_2", x, y, mirrored)
    fs.route()
    assert _face(tank, "in_2") == face


def test_a_tank_inlet_family_never_takes_a_face_its_artwork_lacks():
    """Keep a tank inlet off the floor, which offers it no nozzle."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=2)).pin(x=300, y=300)
    _flag(fs, tank, "in_1", 100, 365, False)
    _flag(fs, tank, "in_2", 340, 560, False)
    fs.layout()
    assert _face(tank, "in_2") in ("W", "E", "N")


# --- The author's face wins ---------------------------------------------------


def test_a_listed_face_is_kept():
    """Keep a face named in ``inputs=[...]``."""
    fs, b = _block("in_1", 340, 150, inputs=["W"])
    fs.layout()
    assert _face(b, "in_1") == "W"


def test_a_face_set_with_nozzle_is_kept():
    """Keep a face set with ``nozzle()`` on a counted connection."""
    fs, b = _block("in_1", 340, 150)
    b.nozzle("in_1", "W")
    fs.layout()
    assert _face(b, "in_1") == "W"


def test_a_connection_pinned_by_its_port_is_kept():
    """Keep the face of the connection a pin measures to."""
    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Reaction")).pin(port="in_1", x=300, y=340)
    _flag(fs, b, "in_1", 340, 150, False)
    fs.layout()
    assert _face(b, "in_1") == "W"


def test_a_listed_face_on_a_lone_tank_inlet_is_kept():
    """Keep ``Tank(inputs=["N"])`` on the roof with its peer to the west."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=["N"])).pin(x=300, y=300)
    _flag(fs, tank, "in_1", 50, 385, False)
    fs.layout()
    assert _face(tank, "in_1") == "N"


def test_listed_tank_inlets_are_kept():
    """Keep each face of ``Tank(inputs=["W", "W"])``."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=["W", "W"])).pin(x=300, y=300)
    _flag(fs, tank, "in_1", 100, 365, False)
    _flag(fs, tank, "in_2", 340, 150, False)
    fs.layout()
    assert _face(tank, "in_2") == "W"


def test_without_automatic_faces_every_connection_keeps_its_default():
    """Draw the default faces when ``auto_faces=False``."""
    fs, b = _block("in_1", 340, 150, sheet=Flowsheet("bfd", auto_faces=False))
    fs.layout()
    assert _face(b, "in_1") == "W"
    assert b.frame is not None and b.frame.port_faces == {}


# --- What stops a move --------------------------------------------------------


def test_a_full_face_takes_no_more_connections():
    """Leave a connection off a face its box has no room on."""
    fs, b = _block("in_1", 340, 150, outputs=["N", "N", "N", "N"])
    fs.layout()
    assert _face(b, "in_1") != "N"
    assert b.frame is not None
    xs = sorted(resolve_port(b, b.frame, p).point[0] for p in ("out_1", "out_2", "out_3", "out_4"))
    assert min(b - a for a, b in zip(xs, xs[1:])) >= BLOCK_PITCH - 1e-6


def test_a_face_whose_line_would_turn_before_it_clears_the_box_is_not_taken():
    """Keep an outlet off the top when its line would run along the roof."""
    # The peer is 5 above the roof, so the top's line would turn at once.
    fs, b = _block("out_1", 600, 295)
    fs.layout()
    assert _face(b, "out_1") == "E"


def test_two_inlets_never_share_a_face_in_the_order_that_crosses_them():
    """Leave an inlet off a face where it would cross its sibling's line."""
    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Reaction", inputs=2)).pin(x=300, y=300)
    # Both peers are above; in_2's is west of in_1's, so on one face in_2,
    # drawn east of in_1, would cross it.
    _flag(fs, b, "in_1", 350, 150, False)
    _flag(fs, b, "in_2", 320, 100, False)
    fs.layout()
    assert _face(b, "in_1") == "N"
    assert _face(b, "in_2") != "N"


def test_an_inlet_never_lands_beside_a_nozzle_on_its_new_face():
    """Leave an inlet off the roof where it would crowd the vent's line."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=2)).pin(x=300, y=300)
    _flag(fs, tank, "in_1", 100, 365, False)
    # The roof inlet sits 15 from the vent, closer than two arrowheads need.
    _flag(fs, tank, "in_2", 340, 150, False)
    vent = fs.add(units.Product("Vent")).pin(x=600, y=100)
    fs.connect(tank.vent, vent.inlet)
    fs.layout()
    assert _face(tank, "in_2") != "N"


def test_a_move_that_costs_its_sibling_more_bends_than_it_saves_is_not_made():
    """Keep an inlet home when its sibling's straight run would bend."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=2)).pin(x=300, y=300)
    # in_1 runs straight only while in_2 shares the west face; the roof
    # would save in_2 one bend and cost in_1 two.
    _flag(fs, tank, "in_1", 100, 365, False)
    _flag(fs, tank, "in_2", 200, 150, False)
    fs.layout()
    assert (_face(tank, "in_1"), _face(tank, "in_2")) == ("W", "W")


def test_a_move_that_shifts_a_line_it_cannot_count_is_not_made():
    """Keep an inlet home when its sibling's peer has a choice of faces."""
    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Reaction", inputs=2)).pin(x=300, y=300)
    # A reactor outlet may take three faces, so in_1's bends are unknown.
    reactor = fs.add(units.Reactor("R-1")).pin(x=50, y=250)
    fs.connect(reactor.outlet, b.in_1)
    _flag(fs, b, "in_2", 340, 150, False)
    fs.layout()
    assert _face(b, "in_2") == "W"


@pytest.mark.parametrize("held", ["pin", "via"])
def test_a_move_that_shifts_a_pinned_or_routed_nozzle_is_not_made(held):
    """Keep an inlet home when its sibling's nozzle is placed by the author."""
    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Reaction", inputs=2)).pin(x=300, y=300)
    # in_1 sits at y = 325 only while in_2 shares the west face.
    feed = fs.add(units.Feed("F-in_1")).pin(x=100, y=325)
    line = fs.connect(feed.outlet, b.in_1)
    if held == "pin":
        b.pin(port="in_1", x=300, y=325)
    else:
        line.via([(200, 325)])
    _flag(fs, b, "in_2", 340, 150, False)
    fs.layout()
    assert b.frame is not None
    assert resolve_port(b, b.frame, "in_1").anchor == (300, 325)
    assert _face(b, "in_2") == "W"


def test_route_keeps_the_default_face_where_the_move_draws_more_bends():
    """Undo a move whose routed line bends more than the default's."""
    fs, b = _block("in_1", 200, 150)
    # The vessel stands where the run down into the top would go.
    fs.add(units.Vessel("V-9", width=40, height=40, label_pos="center")).pin(x=340, y=170)
    fs.layout()
    assert _face(b, "in_1") == "N"
    fs.route()
    assert _face(b, "in_1") == "W"
    assert measure_final(fs).bends == 2


# --- A choice is derived geometry ---------------------------------------------


def test_the_choice_is_not_written_to_the_spec():
    """Write a counted family as a count after the engine moves it."""
    fs, b = _block("in_1", 340, 150)
    fs.layout()
    assert _face(b, "in_1") == "N"
    entry = next(u for u in to_dict(fs)["units"] if u["kind"] == "Block")
    assert entry["inputs"] == 1
    assert "port_faces" not in entry


def test_a_second_layout_draws_the_same_faces():
    """Choose the same faces on a second layout and route."""
    fs, b = _block("in_1", 340, 150)
    fs.route()
    assert b.frame is not None
    first = dict(b.frame.port_faces)
    fs.layout()
    fs.route()
    assert dict(b.frame.port_faces) == first == {"in_1": "N"}


def test_a_count_with_one_moved_connection_round_trips():
    """Keep a counted family counted, and its moved connection stated."""
    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Reaction", inputs=2)).pin(x=300, y=300)
    b.nozzle("in_2", "S")
    _flag(fs, b, "in_1", 340, 150, False)
    _flag(fs, b, "in_2", 340, 520, False)
    entry = next(u for u in to_dict(fs)["units"] if u["kind"] == "Block")
    assert entry["inputs"] == 2
    assert entry["port_faces"] == {"in_2": "S"}
    read = from_dict(to_dict(fs))
    read.layout()
    got = next(u for u in read.units if isinstance(u, units.Block))
    assert (_face(got, "in_1"), _face(got, "in_2")) == ("N", "S")


def test_a_listed_tank_inlet_round_trips_as_a_list():
    """Write a lone listed inlet on its default face as a list."""
    fs = Flowsheet("tank")
    fs.add(units.Tank("TK-1", inputs=["W"]))
    entry = next(u for u in to_dict(fs)["units"] if u["kind"] == "Tank")
    assert entry["inputs"] == ["W"]


def test_a_compact_block_with_moved_connections_round_trips():
    """Read back a block sized for the faces its connections were moved to."""
    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Reaction", inputs=4))
    for n in (2, 3, 4):
        b.nozzle(f"in_{n}", "N")
    b.height = 80
    got = next(u for u in from_dict(to_dict(fs)).units if isinstance(u, units.Block))
    assert got.height == 80
    assert got.input_faces == ("W", "N", "N", "N")


# --- A stated tank or vessel face is as drawn ---------------------------------


@pytest.mark.parametrize("pin", [{"mirrored": True}, {"orientation": 90}])
def test_a_moved_tank_inlet_keeps_its_face_as_drawn_after_a_mirror_or_turn(pin):
    """Keep a ``nozzle()`` face as drawn when the tank is later mirrored or turned."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=2)).nozzle("in_2", "E")
    tank.pin(x=300, y=300, **pin)
    fs.layout()
    assert _face(tank, "in_2") == "E"


def test_layout_reads_a_stated_lone_inlet_on_its_stated_face():
    """Place peers against a listed or moved lone inlet's stated face."""
    listed = units.Tank("TK-1", inputs=["N"])
    moved = units.Tank("TK-2").nozzle("inlet", "E")
    fs = Flowsheet("tank")
    for tank in (listed, moved):
        fs.add(tank)
        feed = fs.add(units.Feed(f"F-{tank.name}"))
        fs.connect(feed.outlet, tank.inlet)
    fs.layout()
    assert (_face(listed, "in_1"), _face(moved, "in_1")) == ("N", "E")
    assert (layered._face(listed.inlet), layered._face(moved.inlet)) == ("N", "E")


@pytest.mark.parametrize(
    ("cls", "options", "moves"),
    [
        (units.Tank, {}, {"inlet": "E", "vent": "N"}),
        (units.Vessel, {"variant": "horizontal"}, {"inlet": "N", "relief": "N"}),
    ],
    ids=["tank", "lying-drum"],
)
def test_a_moved_inlet_and_a_moved_stencil_nozzle_both_round_trip(cls, options, moves):
    """Keep every face ``nozzle()`` moved when the sheet is written and read."""
    fs = Flowsheet("faces")
    unit = fs.add(cls("V-1", **options))
    for port, face in moves.items():
        unit.nozzle(port, face)
    got = from_dict(to_dict(fs)).units[0]
    assert isinstance(got, units.Tank | units.Vessel)
    assert got.face("in_1") == moves["inlet"]
    assert to_dict(from_dict(to_dict(fs))) == to_dict(fs)


def test_a_line_meeting_a_roof_nozzle_is_not_counted_through_its_tank():
    """Count no line through a unit where a line meets its own inset nozzle."""
    from pandid.layout.control import _flaws

    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=["N"])).pin(x=300, y=300)
    _flag(fs, tank, "in_1", 340, 150, False)
    fs.route()
    assert _flaws(fs)["line-through-unit"] == 0


def test_a_line_leaving_a_roof_nozzle_across_the_roof_is_counted_through_its_tank():
    """Count a line's end that runs inside its own unit off the nozzle's face."""
    from pandid.layout.control import _flaws

    fs = Flowsheet("roof")
    tank = fs.add(units.Tank("TK-1")).pin(x=300, y=300)
    product = fs.add(units.Product("P-1")).pin(x=600, y=307.9)
    # The vent's line runs east across the inside of the roof.
    fs.connect(tank.vent, product.inlet).via([(550, 307.9)])
    fs.route()
    assert _flaws(fs)["line-through-unit"] == 1


# --- Tank outlets and upright vessels -----------------------------------------


# A default tank at (300, 300) is 100 x 95.5: its walls take a fill and a draw
# 85 down. A default vessel there is 62 x 100: its walls take a nozzle 50 down
# and its top head one at (346.5, 301).
@pytest.mark.parametrize(
    ("x", "y", "mirrored", "face"),
    [(650, 385, False, "E"), (100, 385, True, "W"), (450, 600, False, "S")],
    ids=["right", "left", "below"],
)
def test_a_tank_outlet_takes_the_wall_toward_its_peer(x, y, mirrored, face):
    """Draw a tank's draw-off low on the wall toward its peer."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=0)).pin(x=300, y=300)
    _flag(fs, tank, "out_1", x, y, mirrored)
    fs.route()
    assert _face(tank, "out_1") == face


@pytest.mark.parametrize(
    ("port", "x", "y", "mirrored", "face"),
    [
        ("in_1", 336, 150, False, "N"),
        ("in_1", 650, 350, True, "E"),
        ("in_1", 100, 350, False, "W"),
        ("out_1", 100, 350, True, "W"),
        ("out_1", 650, 350, False, "E"),
    ],
    ids=["in-above", "in-right", "in-left", "out-left", "out-right"],
)
def test_an_upright_vessel_connection_takes_the_face_toward_its_peer(port, x, y, mirrored, face):
    """Choose among the walls and head an upright vessel offers."""
    fs = Flowsheet("vessel")
    inputs = 1 if port == "in_1" else 0
    vessel = fs.add(units.Vessel("V-1", inputs=inputs, outputs=1 - inputs)).pin(x=300, y=300)
    _flag(fs, vessel, port, x, y, mirrored)
    fs.route()
    assert _face(vessel, port) == face


def test_nozzle_moves_a_tank_outlet_onto_a_wall():
    """Take ``nozzle("outlet", "E")`` on a tank."""
    tank = units.Tank("TK-1").nozzle("outlet", "E")
    assert tank.face("out_1") == "E"


def test_an_inlet_and_an_outlet_on_one_wall_are_spread_inlet_above():
    """Spread a vessel's inlet and outlet apart on the wall they share."""
    fs = Flowsheet("vessel")
    vessel = fs.add(units.Vessel("V-1")).pin(x=300, y=300).nozzle("out_1", "W")
    fs.layout()
    assert vessel.frame is not None
    inlet = resolve_port(vessel, vessel.frame, "in_1")
    outlet = resolve_port(vessel, vessel.frame, "out_1")
    assert (inlet.face, outlet.face) == ("W", "W")
    assert outlet.point[1] - inlet.point[1] >= BLOCK_PITCH - 10


def test_an_outlet_never_takes_the_wall_a_lone_inlet_was_moved_to():
    """Leave a lone inlet the wall it was moved to, and lay the sheet out."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1")).pin(x=300, y=300)
    _flag(fs, tank, "in_1", 650, 385, True)
    # The outlet's peer is above the floor to the east, so E would suit it too.
    _flag(fs, tank, "out_1", 650, 330, False)
    fs.route()
    assert _face(tank, "in_1") == "E"
    assert _face(tank, "out_1") != "E"


def test_a_rejected_wall_outlet_leaves_the_inlet_moves_main_draws():
    """Keep the inlet moves on the stencil's faces when the added faces lose."""
    fs = Flowsheet("tank")
    tank = fs.add(units.Tank("TK-1", inputs=2, outputs=2)).pin(x=400, y=400)
    _flag(fs, tank, "in_1", 100, 380, False)
    _flag(fs, tank, "in_2", 100, 180, False)
    _flag(fs, tank, "out_1", 780, 100, False)
    _flag(fs, tank, "out_2", 100, 780, True)
    fs.route()
    quality = measure_final(fs)
    assert _face(tank, "in_2") == "N"
    assert (quality.crossings, quality.bends) == (1, 7)


def _tank_to_mixer(case: str) -> Flowsheet:
    """Build a tank whose outlets reach a mixer by a pump and a vessel."""
    if case == "A":
        tk, v, p, m, n, out = (900, 100), (600, 550), (600, 100), (300, 300), 5, (900, 300)
    else:
        tk, v, p, m, n, out = (600, 100), (1100, 650), (600, 550), (900, 300), 3, (300, 650)
    fs = Flowsheet("tank to mixer")
    tank = fs.add(units.Tank("TK-1", inputs=2, outputs=2)).pin(x=tk[0], y=tk[1])
    vessel = fs.add(units.Vessel("V-1")).pin(x=v[0], y=v[1])
    pump = fs.add(units.Pump("P-1")).pin(x=p[0], y=p[1])
    mixer = fs.add(units.Mixer("M-1", n_inlets=n)).pin(x=m[0], y=m[1])
    product = fs.add(units.Product("Product")).pin(x=out[0], y=out[1])
    for k, y in enumerate((100, 340)):
        feed = fs.add(units.Feed(f"Feed-{k}")).pin(x=70, y=y)
        fs.connect(feed.outlet, tank.inlets[k])
    fs.connect(tank.outlets[0], pump.suction)
    fs.connect(pump.discharge, mixer.in_1)
    fs.connect(tank.outlets[1], vessel.inlet)
    fs.connect(vessel.outlet, mixer.in_2)
    last = fs.connect(mixer.outlet, product.inlet)
    for k in range(n - 2):
        additive = fs.add(units.Feed(f"Additive-{k}")).pin(x=70, y=700 + 150 * k)
        fs.connect(additive.outlet, mixer.inlets[k + 2])
    if case == "B":
        fs.add_instrument("FI", 101, sensing=last, at=0.5, offset=90)
    return fs


@pytest.mark.parametrize(
    ("case", "crossings", "bends"), [("A", 18, 28), ("B", 6, 22)], ids=["mixer-grown", "balloon"]
)
def test_the_family_face_trial_never_draws_worse_than_main(case, crossings, bends):
    """Judge the family faces from main's starting state, and keep the winner as scored."""
    from pandid.layout.control import _taps_off

    fs = _tank_to_mixer(case)
    fs.route()
    quality = measure_final(fs)
    assert quality.crossings <= crossings
    assert quality.bends <= bends
    assert fs.route_converged
    assert _taps_off(fs) == set()


def test_a_second_route_draws_no_line_on_another():
    """Route a sheet twice without the trials' caches joining two lines."""
    from pandid.layout.control import _flaws

    fs = Flowsheet("tank to mixer")
    tank = fs.add(units.Tank("TK-1", inputs=2)).pin(x=900, y=600)
    vessel = fs.add(units.Vessel("V-1", variant="jacketed")).pin(x=900, y=100)
    pump = fs.add(units.Pump("P-1")).pin(x=900, y=350)
    mixer = fs.add(units.Mixer("M-1")).pin(x=1200, y=100)
    product = fs.add(units.Product("Product")).pin(x=300, y=100)
    feeds = [
        fs.add(units.Feed(name)).pin(x=70, y=y)
        for name, y in (("Feed-0", 100), ("Feed-1", 340), ("Vessel feed", 950))
    ]
    for a, b in [
        (feeds[0].outlet, tank.inlets[0]),
        (feeds[1].outlet, tank.inlets[1]),
        (tank.outlets[0], pump.suction),
        (pump.discharge, mixer.inlets[0]),
        (feeds[2].outlet, vessel.inlet),
        (vessel.outlet, mixer.inlets[1]),
        (mixer.outlet, product.inlet),
    ]:
        fs.connect(a, b)
    fs.layout()
    for _ in range(2):
        fs.route()
        assert _flaws(fs)["line-on-line"] == 0


def test_every_route_starts_main_from_mains_own_last_drawing():
    """Judge each route() against main's drawing of that call, not the last winner."""
    from pandid.routing.lanes import _score

    fs = Flowsheet("blending")
    tank = fs.add(units.Tank("TK-1")).pin(x=1200, y=850)
    vessel = fs.add(units.Vessel("V-1")).pin(x=1200, y=600)
    pump = fs.add(units.Pump("P-1")).pin(x=900, y=350)
    mixer = fs.add(units.Mixer("M-1")).pin(x=900, y=850)
    product = fs.add(units.Product("Product")).pin(x=600, y=350)
    feed = fs.add(units.Feed("Feed-0")).pin(x=70, y=100)
    vessel_feed = fs.add(units.Feed("Vessel feed")).pin(x=70, y=950)
    fs.connect(feed.outlet, tank.inlet)
    fs.connect(tank.outlet, pump.suction)
    fs.connect(pump.discharge, mixer.inlets[0])
    fs.connect(vessel_feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, mixer.inlets[1])
    line = fs.connect(mixer.outlet, product.inlet)
    fs.add_instrument("FI", 101, sensing=line, at=0.5, offset=60)
    fs.layout()
    crossings = []
    for _ in range(3):
        fs.route()
        crossings.append(_score(fs)[0]["crossings"])
    assert crossings == [8, 8, 8]


# --- Reactor, column and separator feeds and draws -----------------------------


# A default column at (300, 100) is 100 x 200: its feeds and draws sit 105
# down, at y = 205, and a feed and a draw on one wall at 187.5 and 222.5. A
# default separator at (300, 300) is 62 x 100: its feed
# sits at y = 350. A stirred reactor at (300, 300) takes a top-head feed at
# x = 310, clear of the drive.
@pytest.mark.parametrize(
    ("unit", "port", "x", "y", "mirrored", "face"),
    [
        ("column", "feed_1", 650, 187.5, True, "E"),
        ("column", "feed_1", 80, 205, False, "W"),
        ("column", "draw", 80, 222.5, True, "W"),
        ("column", "draw", 650, 205, False, "E"),
        ("separator", "feed_1", 650, 350, True, "E"),
        ("separator", "feed_1", 80, 350, False, "W"),
        ("reactor", "feed_1", 280, 150, False, "N"),
    ],
    ids=[
        "col-feed-right",
        "col-feed-left",
        "col-draw-left",
        "col-draw-right",
        "sep-feed-right",
        "sep-feed-left",
        "reactor-feed-above",
    ],
)
def test_a_series_member_takes_the_face_toward_its_peer(unit, port, x, y, mirrored, face):
    """Draw a feed or draw on the face its series offers toward its peer."""
    fs = Flowsheet("series")
    if unit == "column":
        body = fs.add(units.Column("T-1", n_draws=1)).pin(x=300, y=100)
    elif unit == "separator":
        body = fs.add(units.Separator("V-1")).pin(x=300, y=300)
    else:
        body = fs.add(units.Reactor("R-1")).pin(x=300, y=300)
    _flag(fs, body, port, x, y, mirrored)
    fs.route()
    assert _face(body, port) == face


def test_a_reactor_feed_on_the_top_head_keeps_clear_of_the_drive():
    """Draw a top-head feed beside the motor, its line clear of the drive."""
    from pandid.render.symbols import default_registry

    fs = Flowsheet("reactor")
    reactor = fs.add(units.Reactor("R-1").nozzle("feed", "N")).pin(x=300, y=300)
    fs.layout()
    assert reactor.frame is not None
    at = resolve_port(reactor, reactor.frame, "feed")
    assert at.face == "N"
    sym = default_registry.for_unit(reactor)
    motor = next(o for o in sym.overlays if o.name == "motor")
    drive = resolve_port(reactor, reactor.frame, "drive").point
    # Left of the motor, and below the box top on the head's ink.
    assert at.point[0] < reactor.frame.x + motor.x * reactor.frame.w
    assert at.point[0] < drive[0]
    assert at.point[1] > reactor.frame.y + 20


@pytest.mark.parametrize(
    ("build", "port", "face", "match"),
    [
        (lambda: units.Reactor("R-1"), "feed", "E", "can be piped from W or N"),
        (
            lambda: units.Reactor("R-1", n_feeds=2).nozzle("feed_1", "N"),
            "feed_2",
            "N",
            "takes one nozzle",
        ),
        (
            lambda: units.Column("T-1", internals="valve_tray", trays=30, feed_stages=[2]),
            "feed",
            "E",
            "outside the stretch of the E wall",
        ),
        (
            lambda: units.Separator("V-1", variant="horizontal"),
            "feed",
            "S",
            "can be piped from W, N or E",
        ),
    ],
    ids=["reactor-east-wall", "reactor-second-head-feed", "column-stage-off-stretch", "lying-drum"],
)
def test_nozzle_refuses_a_face_a_series_cannot_take(build, port, face, match):
    """Refuse a face a series member's body does not offer it."""
    unit = build()
    with pytest.raises(ValueError, match=match):
        unit.nozzle(port, face)


def test_nozzle_moves_a_series_member_and_the_spec_keeps_it():
    """Write a moved feed under ``port_faces`` and read it back there."""
    fs = Flowsheet("series")
    fs.add(units.Reactor("R-1").nozzle("feed", "N"))
    fs.add(units.Column("T-1", n_draws=1).nozzle("feed", "E").nozzle("draw", "W"))
    fs.add(units.Separator("V-1").nozzle("feed", "E"))
    entries = {u["name"]: u for u in to_dict(fs)["units"]}
    assert entries["R-1"]["port_faces"] == {"feed_1": "N"}
    assert entries["T-1"]["port_faces"] == {"feed_1": "E", "draw": "W"}
    read_back = from_dict(to_dict(fs))
    read = {u.name: u for u in read_back.units}
    read_back.layout()
    assert _face(read["R-1"], "feed") == "N"
    assert (_face(read["T-1"], "feed"), _face(read["T-1"], "draw")) == ("E", "W")
    assert _face(read["V-1"], "feed") == "E"


def test_a_feed_and_a_draw_on_one_column_wall_stay_apart():
    """Spread a moved feed and the draws on the wall they share."""
    fs = Flowsheet("column")
    column = fs.add(units.Column("T-1", n_draws=1).nozzle("feed", "E")).pin(x=300, y=100)
    fs.layout()
    assert column.frame is not None
    feed = resolve_port(column, column.frame, "feed")
    draw = resolve_port(column, column.frame, "draw")
    assert (feed.face, draw.face) == ("E", "E")
    assert abs(feed.point[1] - draw.point[1]) >= 16


# The face each of a symbol's own faces is drawn on under a placement.
_DRAWN = {
    "as drawn": {"N": "N", "E": "E", "S": "S", "W": "W"},
    "mirror x": {"N": "N", "E": "W", "S": "S", "W": "E"},
    "mirror y": {"N": "S", "E": "E", "S": "N", "W": "W"},
    "turn 90": {"N": "E", "E": "S", "S": "W", "W": "N"},
    "turn 180": {"N": "S", "E": "W", "S": "N", "W": "E"},
    "turn 270": {"N": "W", "E": "N", "S": "E", "W": "S"},
}
# Turn and mirror of each placement.
_PLACEMENTS: dict[str, tuple[int, bool | str]] = {
    "as drawn": (0, False),
    "mirror x": (0, True),
    "mirror y": (0, "y"),
    "turn 90": (90, False),
    "turn 180": (180, False),
    "turn 270": (270, False),
}


@pytest.mark.parametrize("placement", list(_DRAWN))
@pytest.mark.parametrize(
    ("build", "own"),
    [
        pytest.param(lambda: units.Column("T-1"), "W", id="column-feed-home"),
        pytest.param(lambda: units.Column("T-1"), "E", id="column-feed-across"),
        pytest.param(lambda: units.Reactor("R-1"), "W", id="reactor-feed-home"),
        pytest.param(lambda: units.Reactor("R-1"), "N", id="reactor-feed-head"),
        pytest.param(lambda: units.Separator("V-1"), "W", id="separator-feed-home"),
        pytest.param(lambda: units.Separator("V-1"), "E", id="separator-feed-across"),
    ],
)
def test_nozzle_puts_a_series_member_on_the_face_as_drawn(
    build: Callable[[], Unit], own: str, placement: str
):
    """Draw a feed on the face nozzle() names, under any turn or mirror."""
    _assert_drawn_on(build, "feed", _DRAWN[placement][own], placement)


def _assert_drawn_on(build: Callable[[], Unit], port_name: str, drawn: str, placement: str) -> None:
    """Assert a port nozzle() puts on a face is drawn there, also read back from a spec."""
    fs = Flowsheet("placed")
    turn, mirror = _PLACEMENTS[placement]
    unit = fs.add(build()).pin(x=300, y=100, orientation=turn, mirrored=mirror)
    unit.nozzle(port_name, drawn)
    read = from_dict(to_dict(fs))
    for sheet, placed in ((fs, unit), (read, read.units[0])):
        sheet.layout()
        assert placed.frame is not None
        port = resolve_port(placed, placed.frame, port_name)
        cx = placed.frame.x + placed.frame.w / 2
        cy = placed.frame.y + placed.frame.h / 2
        side = {
            "E": port.point[0] > cx,
            "W": port.point[0] < cx,
            "N": port.point[1] < cy,
            "S": port.point[1] > cy,
        }
        assert (port.face, side[drawn]) == (drawn, True)


def test_nozzle_on_a_mirrored_column_names_the_face_as_drawn():
    """Put a mirrored column's feed on the east wall nozzle() names."""
    fs = Flowsheet("column")
    column = fs.add(units.Column("T")).pin(x=300, y=100, mirrored=True).nozzle("feed", "E")
    fs.layout()
    assert column.frame is not None
    port = resolve_port(column, column.frame, "feed")
    assert (port.face, port.point) == ("E", (400.0, 205.0))


@pytest.mark.parametrize("placement", list(_DRAWN))
@pytest.mark.parametrize(
    ("build", "port_name", "own"),
    [
        pytest.param(lambda: units.Tank("TK-1"), "in_1", "W", id="tank-inlet-home"),
        pytest.param(lambda: units.Tank("TK-1"), "in_1", "E", id="tank-inlet-across"),
        pytest.param(lambda: units.Tank("TK-1"), "in_1", "N", id="tank-inlet-roof"),
        pytest.param(lambda: units.Tank("TK-1"), "out_1", "S", id="tank-outlet-home"),
        pytest.param(lambda: units.Tank("TK-1"), "out_1", "E", id="tank-outlet-wall"),
        pytest.param(lambda: units.Vessel("V-1"), "in_1", "W", id="vessel-inlet-home"),
        pytest.param(lambda: units.Vessel("V-1"), "in_1", "E", id="vessel-inlet-across"),
        pytest.param(lambda: units.Vessel("V-1"), "in_1", "N", id="vessel-inlet-head"),
        pytest.param(lambda: units.Vessel("V-1"), "out_1", "E", id="vessel-outlet-home"),
        pytest.param(lambda: units.Vessel("V-1"), "out_1", "W", id="vessel-outlet-across"),
    ],
)
def test_nozzle_puts_a_tank_or_vessel_nozzle_on_the_face_as_drawn(
    build: Callable[[], Unit], port_name: str, own: str, placement: str
):
    """Draw an inlet or outlet on the face nozzle() names, under any turn or mirror."""
    _assert_drawn_on(build, port_name, _DRAWN[placement][own], placement)


@pytest.mark.parametrize(
    ("build", "point"),
    [
        pytest.param(lambda: units.Tank("TK-1"), (400.0, 185.0), id="tank"),
        pytest.param(lambda: units.Vessel("V-1"), (362.0, 150.0), id="vessel"),
    ],
)
def test_nozzle_on_a_mirrored_tank_or_vessel_names_the_face_as_drawn(
    build: Callable[[], Unit], point: tuple[float, float]
):
    """Put a mirrored tank's or vessel's inlet on the east wall nozzle() names."""
    fs = Flowsheet("mirrored")
    unit = fs.add(build()).pin(x=300, y=100, mirrored=True).nozzle("in_1", "E")
    fs.layout()
    assert unit.frame is not None
    port = resolve_port(unit, unit.frame, "in_1")
    assert (port.face, port.point) == ("E", point)
