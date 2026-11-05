"""Check face selection for block, tank and vessel connection families."""

from __future__ import annotations

import pytest

from pandid import Flowsheet, units
from pandid.layout.quality import measure_final
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
# S (360, 380).
@pytest.mark.parametrize(
    ("port", "x", "y", "mirrored", "face"),
    [
        ("in_1", 340, 150, False, "N"),
        ("in_1", 340, 520, False, "S"),
        ("in_1", 100, 340, False, "W"),
        ("in_1", 650, 340, True, "E"),
        ("out_1", 650, 120, False, "N"),
        ("out_1", 650, 560, False, "S"),
        ("out_1", 80, 340, True, "W"),
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
    fs.layout()
    assert _face(b, port) == face


def test_two_inlets_on_the_west_split_when_one_comes_from_above():
    """Move the inlet fed from above and leave its sibling on the west."""
    fs = Flowsheet("bfd")
    b = fs.add(units.Block("Reaction", inputs=2)).pin(x=300, y=300)
    _flag(fs, b, "in_1", 100, 340, False)
    _flag(fs, b, "in_2", 340, 150, False)
    fs.layout()
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
    _flag(fs, tank, "in_1", 100, 365, False)
    _flag(fs, tank, "in_2", x, y, mirrored)
    fs.layout()
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
