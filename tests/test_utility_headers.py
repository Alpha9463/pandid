"""A utility header is one service, tapped wherever the sheet needs it.

P&ID_301 brings cooling water onto the sheet twice and sends it back twice, and
labels all four flags CWSH / CWRH, because there is one supply header and one
return header. Numbering them apart would put a service on the drawing that does
not exist on the plant.
"""

import pytest

from pandid import units as U
from pandid.document import equipment_list
from pandid.flowsheet import Flowsheet


def _two_taps(**flag):
    """One cooling water header feeding two exchangers, returning to one header.

    The shape of the utility connections on P&ID_301: four flags, two services.
    """
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
    """Two coolers on one cooling water system is two taps of one header, and a
    sheet that cannot draw the flag twice cannot show the second cooler getting
    any water."""
    fs, taps = _two_taps()
    assert [f.tag for pair in taps for f in pair] == ["CWSH", "CWRH", "CWSH", "CWRH"]
    assert [f.name for pair in taps for f in pair] == [
        "CWSH",
        "CWRH",
        "CWSH (2)",
        "CWRH (2)",
    ]


def test_every_tap_draws_the_service_it_taps():
    """The name that tells two taps apart is the flowsheet's bookkeeping. What
    is drawn is the header, at each place it is tapped."""
    fs, _ = _two_taps()
    svg = fs.to_svg()
    assert svg.count(">CWSH</text>") == 2
    assert svg.count(">CWRH</text>") == 2
    assert "(2)" not in svg


def test_both_taps_of_a_header_are_drawn_the_same_size():
    """A flag is sized to the text it carries. Sizing it to the name instead
    would draw the second tap of CWSH four characters wider than the first."""
    fs, taps = _two_taps()
    fs.layout()
    widths = {f.frame.w for pair in taps for f in pair}
    assert len(widths) == 1


def test_each_tap_is_still_one_unit_to_look_up():
    """The tag repeats; the name does not, so a stream endpoint means exactly
    one tap."""
    fs, taps = _two_taps()
    for supply, ret in taps:
        assert [u for u in fs.units if u.name == supply.name] == [supply]
        assert [u for u in fs.units if u.name == ret.name] == [ret]
        assert supply.outlet.stream is not ret.inlet.stream


def test_a_header_flag_carries_its_off_page_reference_to_every_tap():
    """The reference is the second line of the flag, so both taps draw it and
    both flags stay the same drawing of the same header."""
    fs, taps = _two_taps(reference="U-1201")
    svg = fs.to_svg()
    assert svg.count(">U-1201</text>") == 4


# --- and a genuine duplicate still does not ----------------------------------


def test_two_flags_of_one_name_are_refused_unless_they_are_a_header():
    """Two boundary flags called 'Reactor Effluent' are one line drawn as if it
    left the sheet twice. Nothing can tell that from a header except the author,
    which is what header= says."""
    fs = Flowsheet("duplicate")
    fs.add(U.Product("Reactor Effluent"))
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(U.Product("Reactor Effluent"))


@pytest.mark.parametrize("headers", [(True, False), (False, True)])
def test_both_flags_have_to_be_declared_a_header(headers):
    """Whichever way round: one of the two is a line leaving the sheet, and the
    author has said so."""
    first, second = headers
    fs = Flowsheet("half declared")
    fs.add(U.Feed("CWSH", header=first))
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(U.Feed("CWSH", header=second))


def test_a_supply_and_a_return_cannot_share_a_label():
    """Two flags pointing opposite ways under one label is two services the
    reader cannot tell apart."""
    fs = Flowsheet("supply and return")
    fs.add(U.Feed("CWSH", header=True))
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(U.Product("CWSH", header=True))


def test_two_taps_disagreeing_on_where_the_header_goes_are_refused():
    """One header continues onto one drawing. Two flags naming different ones
    are two headers, however they are labelled."""
    fs = Flowsheet("two references")
    fs.add(U.Feed("CWSH", header=True, reference="U-1201"))
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(U.Feed("CWSH", header=True, reference="U-1300"))


def test_equipment_still_refuses_a_repeated_tag():
    """header= is not a general escape from the rule: a pump is a piece of
    plant and there is one of it."""
    fs = Flowsheet("two pumps")
    fs.add(U.Pump("P-101"))
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(U.Pump("P-101"))


def test_header_is_refused_on_equipment():
    """Only a boundary flag stands for a service; a pump given the word would
    store a claim nothing acts on."""
    with pytest.raises(TypeError):
        U.Pump("P-101", header=True)


# --- what the rest of the sheet makes of it -----------------------------------


def test_a_tapped_header_is_scheduled_nowhere():
    """A flag is where the sheet ends, not a piece of plant, so no schedule has
    a row for it, and a header tapped twice cannot put two."""
    fs, _ = _two_taps()
    rows = equipment_list(fs).rows
    assert rows == [("E-301", "Condenser"), ("E-302", "Product Cooler")]


def test_each_tap_gets_its_own_stream_and_line_number():
    """Two taps of one header are two lines: same service, different sizes,
    different sequence numbers, and a line list with four entries."""
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
    """Nothing in validate() is keyed on a unit name, so a legitimate repeat
    raises no finding of its own."""
    fs, _ = _two_taps()
    fs.route()
    assert [i for i in fs.validate() if i.code in ("unit-overlap", "coincident-ports")] == []


def test_a_tapped_header_survives_a_round_trip_through_a_spec():
    """Each tap is written out as its own entry carrying the header's label, and
    read back as the same tap wired to the same exchanger."""
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
    """One line leaving the sheet is what a flag already means, so writing the
    default down would put it in every spec ever serialized."""
    fs = Flowsheet("plain")
    fs.add(U.Feed("Raw Feed", reference="PFD-100"))
    assert "header" not in fs.to_dict()["units"][0]


def test_header_on_equipment_is_refused_by_the_spec():
    """The spec rejects a key the class cannot take rather than dropping it."""
    with pytest.raises(ValueError, match="header"):
        Flowsheet.from_dict(
            {
                "name": "spec",
                "units": [{"kind": "Pump", "name": "P-101", "header": True}],
            }
        )


# --- one flag, several lines (#454) -------------------------------------------
#
# The other way to draw the same plant. ``_two_taps`` above brings the header
# onto the sheet at two places and labels both; this brings it on once and runs
# two lines off it. Both are real drawings and the choice is the author's, which
# is why nothing here changes ``repeats()``: a tap is a flag, and two lines on
# one flag never reach that question.


def _one_tap():
    """One cooling water supply flag serving two exchangers, one return flag
    collecting from both."""
    fs = Flowsheet("cooling water")
    supply = fs.add(U.Feed("CWSH", header=True))
    ret = fs.add(U.Product("CWRH", header=True))
    for name, size in (("E-301", '6"'), ("E-302", '4"')):
        hx = fs.add(U.HeatExchanger(name))
        fs.connect(supply.outlet, hx.tube_in, size=size, service="CWS", spec="A1A")
        fs.connect(hx.tube_out, ret.inlet, size=size, service="CWR", spec="A1A")
    return fs, supply, ret


def test_one_flag_serves_as_many_users_as_the_sheet_has():
    """The whole of #454. A header entering a drawing once and serving two
    coolers is ordinary; forcing a second flag for the second cooler would say
    there are two supplies where the plant has one."""
    fs, supply, ret = _one_tap()
    assert list(supply.ports) == ["outlet", "outlet_2"]
    assert list(ret.ports) == ["inlet", "inlet_2"]
    # Every member is the connection it is a member of: same direction, same
    # role. A minted one that differed would be refused by ``connect()`` on the
    # second line and never on the first.
    assert {p.direction for p in supply.ports.values()} == {"outlet"}
    assert {p.role for p in supply.ports.values()} == {"feed"}
    assert {p.role for p in ret.ports.values()} == {"product"}


def test_each_line_on_one_flag_stays_a_line_of_its_own():
    """Only the flag is one thing. Every run keeps its own number, its own line
    number and its own row in the stream table -- a flag carrying two lines
    tabulates two, which is what ISO 10628-1 4.3.2 d) asks the sheet to report
    about each ingoing and outgoing material."""
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
    """A flag is a mark saying the material crosses here, not a body with
    nozzles on it, so there is one point and every run leaves it -- pointing the
    way the pennant points, which is what makes the second line's face the first
    line's and not the nearest box edge."""
    from pandid.portgeom import resolve_port

    fs, supply, ret = _one_tap()
    fs.layout()
    for flag, face in ((supply, "E"), (ret, "W")):
        resolved = {resolve_port(flag, flag.frame, name) for name in flag.ports}
        assert len(resolved) == 1
        assert next(iter(resolved)).face == face


def test_the_coincidence_a_flag_draws_is_not_reported():
    """Two live connections on one point is otherwise a hard finding, and it
    still is everywhere else: :func:`test_only_a_boundary_flag_draws_its_runs_on
    _one_point` below is the floor under this exemption."""
    fs, supply, ret = _one_tap()
    fs.route()
    assert [i for i in fs.validate() if i.code in ("unit-overlap", "coincident-ports")] == []


def test_only_a_boundary_flag_draws_its_runs_on_one_point():
    """The floor. ``ONE_NOZZLE_MANY_RUNS`` turns off a hard validation finding,
    so a class that set it would stop being checked for streams terminating on
    top of one another -- which is exactly what the finding exists to catch on
    equipment. A flag has no body and no second nozzle; anything else does."""
    from pandid import units

    def walk(cls):
        yield cls
        for sub in cls.__subclasses__():
            if sub.__module__.startswith("pandid."):
                yield from walk(sub)

    exempt = {c.__name__ for c in walk(units.Unit) if c.ONE_NOZZLE_MANY_RUNS}
    assert exempt == {"_Boundary", "Feed", "Product"}


def test_a_flag_carrying_two_lines_survives_a_round_trip_through_a_spec():
    """The members are minted by ``connect()`` rather than declared, so a spec
    names ones the rebuilt flag has not grown yet; asking the unit for the name
    is what makes ``from_dict(to_dict(fs))`` the sheet it just wrote."""
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
    """Nothing here collapses the two. ``repeats()`` compares *flags* -- is this
    one another drawing of that header -- and two lines on one flag never reach
    it, so an author still chooses between bringing the header on twice and
    running two lines off it once."""
    two, _ = _two_taps()
    one, supply, _ = _one_tap()
    # Two taps are two units, told apart by a name the flowsheet hands out and
    # drawn under one label; two lines on one tap are one unit.
    taps = [u for u in two.units if isinstance(u, U.Feed)]
    assert [u.name for u in taps] == ["CWSH", "CWSH (2)"]
    assert [u.tag for u in taps] == ["CWSH", "CWSH"]
    assert [u.name for u in one.units if isinstance(u, U.Feed)] == ["CWSH"]
    assert taps[0].repeats(taps[1])
    assert not supply.repeats(U.Feed("CWSH"))  # header=False on the other side
