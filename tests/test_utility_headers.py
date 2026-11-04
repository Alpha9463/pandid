"""Check that a utility header is one service, tapped wherever the sheet needs it."""

import pytest

from pandid import units as U
from pandid.document import equipment_list
from pandid.flowsheet import Flowsheet


def _two_taps(**flag):
    """Return a sheet with one cooling-water header tapped at two exchangers, and the taps."""
    fs = Flowsheet("cooling water")
    e1 = fs.add(U.HeatExchanger("E-301", description="Condenser"))
    e2 = fs.add(U.HeatExchanger("E-302", description="Product Cooler"))
    taps = []
    for hx, size in ((e1, '6"'), (e2, '4"')):
        supply = fs.add(U.Feed("CWSH", header=True, **flag))
        ret = fs.add(U.Product("CWRH", header=True, **flag))
        fs.connect(supply.outlet, hx.tube_in, size=size, service="CWS", spec="A1A")
        fs.connect(hx.tube_out, ret.inlet, size=size, service="CWR", spec="A1A")
        taps.append((supply, ret))
    return fs, taps


# --- the header repeats -------------------------------------------------------


def test_one_header_can_be_tapped_more_than_once():
    """Check that a header tapped twice keeps its tag and gets distinct names."""
    fs, taps = _two_taps()
    assert [f.tag for pair in taps for f in pair] == ["CWSH", "CWRH", "CWSH", "CWRH"]
    assert [f.name for pair in taps for f in pair] == [
        "CWSH",
        "CWRH",
        "CWSH (2)",
        "CWRH (2)",
    ]


def test_every_tap_draws_the_service_it_taps():
    """Check that every tap draws the header's tag and not its name."""
    fs, _ = _two_taps()
    svg = fs.to_svg()
    assert svg.count(">CWSH</text>") == 2
    assert svg.count(">CWRH</text>") == 2
    assert "(2)" not in svg


def test_both_taps_of_a_header_are_drawn_the_same_size():
    """Check that every tap of a header is drawn the same width."""
    fs, taps = _two_taps()
    fs.layout()
    widths = {f.frame.w for pair in taps for f in pair}
    assert len(widths) == 1


def test_each_tap_is_still_one_unit_to_look_up():
    """Check that each tap is one unit with its own stream."""
    fs, taps = _two_taps()
    for supply, ret in taps:
        assert [u for u in fs.units if u.name == supply.name] == [supply]
        assert [u for u in fs.units if u.name == ret.name] == [ret]
        assert supply.outlet.stream is not ret.inlet.stream


def test_a_header_flag_carries_its_off_page_reference_to_every_tap():
    """Check that every tap draws the header's off-page reference."""
    fs, taps = _two_taps(reference="U-1201")
    svg = fs.to_svg()
    assert svg.count(">U-1201</text>") == 4


# --- and a genuine duplicate still does not ----------------------------------


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (lambda: U.Product("Reactor Effluent"), lambda: U.Product("Reactor Effluent")),
        (lambda: U.Feed("CWSH", header=True), lambda: U.Feed("CWSH")),
        (lambda: U.Feed("CWSH"), lambda: U.Feed("CWSH", header=True)),
        (lambda: U.Feed("CWSH", header=True), lambda: U.Product("CWSH", header=True)),
        (
            lambda: U.Feed("CWSH", header=True, reference="U-1201"),
            lambda: U.Feed("CWSH", header=True, reference="U-1300"),
        ),
        (lambda: U.Pump("P-101"), lambda: U.Pump("P-101")),
    ],
    ids=[
        "two flags",
        "second not a header",
        "first not a header",
        "supply and return",
        "two references",
        "equipment",
    ],
)
def test_a_repeated_name_is_refused_unless_both_are_taps_of_one_header(first, second):
    """Check that a second unit under a taken name is refused unless it repeats a header."""
    fs = Flowsheet("duplicate")
    fs.add(first())
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(second())


def test_header_is_refused_on_equipment():
    """Check that ``header=`` is refused on equipment."""
    with pytest.raises(TypeError):
        U.Pump("P-101", header=True)


# --- what the rest of the sheet makes of it -----------------------------------


def test_a_tapped_header_is_scheduled_nowhere():
    """Check that a tapped header is left off the equipment list."""
    fs, _ = _two_taps()
    rows = equipment_list(fs).rows
    assert rows == [("E-301", "Condenser"), ("E-302", "Product Cooler")]


def test_each_tap_gets_its_own_stream_and_line_number():
    """Check that each tap's line gets its own line number."""
    fs, _ = _two_taps()
    numbers = [s.name for s in fs.streams]
    assert numbers == [
        '6"-CWS-1001-A1A',
        '6"-CWR-1002-A1A',
        '4"-CWS-1003-A1A',
        '4"-CWR-1004-A1A',
    ]
    assert len(set(numbers)) == len(numbers)


def test_a_repeated_header_passes_validation():
    """Check that a repeated header raises no overlap or coincident-port finding."""
    fs, _ = _two_taps()
    fs.route()
    assert [i for i in fs.validate() if i.code in ("unit-overlap", "coincident-ports")] == []


def test_a_tapped_header_survives_a_round_trip_through_a_spec():
    """Check that a tapped header reads back as the same taps on the same streams."""
    fs, _ = _two_taps()
    spec = fs.to_dict()
    flags = [u for u in spec["units"] if u["kind"] in ("Feed", "Product")]
    assert [u["name"] for u in flags] == ["CWSH", "CWRH", "CWSH", "CWRH"]
    assert all(u["header"] is True for u in flags)

    rebuilt = Flowsheet.from_dict(spec)
    assert [u.name for u in rebuilt.units] == [u.name for u in fs.units]
    assert [u.tag for u in rebuilt.units] == [u.tag for u in fs.units]
    assert [(s.source.owner.name, s.dest.owner.name) for s in rebuilt.streams] == [
        (s.source.owner.name, s.dest.owner.name) for s in fs.streams
    ]
    assert rebuilt.to_dict() == spec


def test_a_flag_that_is_not_a_header_writes_no_word_about_it():
    """Check that a flag that is not a header writes no ``header`` key."""
    fs = Flowsheet("plain")
    fs.add(U.Feed("Raw Feed", reference="PFD-100"))
    assert "header" not in fs.to_dict()["units"][0]


# --- one flag, several lines --------------------------------------------------


def _one_tap():
    """Return a sheet with one supply and one return flag serving two exchangers."""
    fs = Flowsheet("cooling water")
    supply = fs.add(U.Feed("CWSH", header=True))
    ret = fs.add(U.Product("CWRH", header=True))
    for name, size in (("E-301", '6"'), ("E-302", '4"')):
        hx = fs.add(U.HeatExchanger(name))
        fs.connect(supply.outlet, hx.tube_in, size=size, service="CWS", spec="A1A")
        fs.connect(hx.tube_out, ret.inlet, size=size, service="CWR", spec="A1A")
    return fs, supply, ret


def test_one_flag_serves_as_many_users_as_the_sheet_has():
    """Check that one flag takes a line per user, each on a member of its connection."""
    fs, supply, ret = _one_tap()
    assert list(supply.ports) == ["outlet", "outlet_2"]
    assert list(ret.ports) == ["inlet", "inlet_2"]
    assert {p.direction for p in supply.ports.values()} == {"outlet"}
    assert {p.role for p in supply.ports.values()} == {"feed"}
    assert {p.role for p in ret.ports.values()} == {"product"}


def test_each_line_on_one_flag_stays_a_line_of_its_own():
    """Check that each line on one flag keeps its own number and stream-table row."""
    from pandid.render.furniture import _table_runs

    fs, supply, ret = _one_tap()
    assert [s.name for s in fs.streams] == [
        '6"-CWS-1001-A1A',
        '6"-CWR-1002-A1A',
        '4"-CWS-1003-A1A',
        '4"-CWR-1004-A1A',
    ]
    assert all(s.at_boundary for s in fs.streams)
    assert len(_table_runs(fs)) == 4


def test_every_line_on_a_flag_crosses_the_edge_at_the_flags_own_nozzle():
    """Check that every line on a flag leaves the flag's one point, the way it points."""
    from pandid.portgeom import resolve_port

    fs, supply, ret = _one_tap()
    fs.layout()
    for flag, face in ((supply, "E"), (ret, "W")):
        resolved = {resolve_port(flag, flag.frame, name) for name in flag.ports}
        assert len(resolved) == 1
        assert next(iter(resolved)).face == face


def test_the_coincidence_a_flag_draws_is_not_reported():
    """Check that the runs a flag draws on one point are not reported."""
    fs, supply, ret = _one_tap()
    fs.route()
    assert [i for i in fs.validate() if i.code in ("unit-overlap", "coincident-ports")] == []


def test_only_a_boundary_flag_draws_its_runs_on_one_point():
    """Check that only the boundary flags set ``ONE_NOZZLE_MANY_RUNS``."""
    from pandid import units

    def walk(cls):
        yield cls
        for sub in cls.__subclasses__():
            if sub.__module__.startswith("pandid."):
                yield from walk(sub)

    exempt = {c.__name__ for c in walk(units.Unit) if c.ONE_NOZZLE_MANY_RUNS}
    assert exempt == {"_Boundary", "Feed", "Product"}


def test_a_flag_carrying_two_lines_survives_a_round_trip_through_a_spec():
    """Check that a flag carrying two lines reads back as the same sheet."""
    fs, supply, ret = _one_tap()
    spec = fs.to_dict()
    assert [s["from"][1] for s in spec["streams"]] == [
        "outlet",
        "tube_out",
        "outlet_2",
        "tube_out",
    ]
    rebuilt = Flowsheet.from_dict(spec)
    assert list(rebuilt.units[0].ports) == ["outlet", "outlet_2"]
    assert rebuilt.to_dict() == spec
    assert rebuilt.to_svg() == fs.to_svg()


def test_two_taps_and_two_lines_on_one_tap_are_still_different_drawings():
    """Check that two taps are two units and two lines on one tap are one."""
    two, _ = _two_taps()
    one, supply, _ = _one_tap()
    taps = [u for u in two.units if isinstance(u, U.Feed)]
    assert [u.name for u in taps] == ["CWSH", "CWSH (2)"]
    assert [u.tag for u in taps] == ["CWSH", "CWSH"]
    assert [u.name for u in one.units if isinstance(u, U.Feed)] == ["CWSH"]
    assert taps[0].repeats(taps[1])
    assert not supply.repeats(U.Feed("CWSH"))  # header=False on the other side
