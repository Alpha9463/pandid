from pfd import Flowsheet, units as U
from pfd.layout import _seed_slots
from pfd.layout.cycles import break_cycles
from pfd.layout.layering import assign_layers
from pfd.layout.ordering import order_within_layers
from pfd.layout.coordinates import assign_coordinates


def test_cycle_breaking():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u2 = fs.add(U.Separator("S1"))

    s1 = fs.connect(u1.outlet, u2.feed)
    s2 = fs.connect(u2.liquid, u1.feed)  # backward

    break_cycles(fs)

    # One of them should be marked as recycle. Because u1 is first,
    # and has out-degree 1, DFS from u1 goes to u2, then u2 goes to u1.
    # The edge from u2 to u1 is the back-edge.
    assert s1.is_recycle is False
    assert s2.is_recycle is True


def test_layering():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u2 = fs.add(U.Separator("S1"))
    u3 = fs.add(U.Mixer("M1"))

    fs.connect(u1.outlet, u2.feed)
    fs.connect(u2.vapor, u3.in_1)

    break_cycles(fs)
    _seed_slots(fs)
    assign_layers(fs)

    assert u1._slot.col == 0
    assert u2._slot.col == 1
    assert u3._slot.col == 2


def test_pinned_layering():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u2 = fs.add(U.Separator("S1"))

    fs.connect(u1.outlet, u2.feed)

    u1.pin(col=2, row=0)  # u1 is forced to col 2

    break_cycles(fs)
    _seed_slots(fs)
    assign_layers(fs)

    assert u1._slot.col == 2
    # u2 must be at least u1.col + 1
    assert u2._slot.col == 3


def test_ordering():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Separator("S1"))
    u2 = fs.add(U.Reactor("R1"))
    u3 = fs.add(U.Mixer("M1"))

    fs.connect(u1.vapor, u2.feed)
    fs.connect(u1.liquid, u3.in_1)

    break_cycles(fs)
    _seed_slots(fs)
    assign_layers(fs)
    order_within_layers(fs)

    # u2 and u3 are both in col 1, they must have different rows (0 and 1)
    assert u1._slot.row == 0
    assert {u2._slot.row, u3._slot.row} == {0, 1}


def test_coordinates():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u1.pin(col=1, row=2)

    _seed_slots(fs)
    assign_coordinates(fs)

    # Only one column (col 1) exists, so it starts at MARGIN_X
    assert u1.frame.x == 50
    assert u1.frame.y == 50 + 2 * 120


def test_full_layout_via_render(tmp_path):
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u2 = fs.add(U.Separator("S1"))
    fs.connect(u1.outlet, u2.feed)

    # rendering should implicitly trigger layout because frames are None
    svg_path = tmp_path / "test.svg"
    fs.render(str(svg_path))

    assert u1.frame.x is not None
    assert u2.frame.col == 1

    content = svg_path.read_text()
    assert "<use" in content
