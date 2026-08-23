"""Control loops: identity, tagging, and the two rules a declared loop enforces."""

import pytest

from pandid import Flowsheet, units as U
from pandid.document import equipment_list
from pandid.validate import validate


def _sheet():
    """A metering line with a control valve on it, ready for a flow loop."""
    fs = Flowsheet("loops")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    fv = fs.add(U.Valve("CV-300", variant="control")).pin(x=300, y=180)
    prod = fs.add(U.Product("Product")).pin(x=520, y=170)
    line = fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    return fs, line


# --- identity -----------------------------------------------------------------


def test_a_loop_is_its_variable_and_its_number_together():
    """Two loops may share a number; the pair is what tells them apart.

    This is the shape of ``examples/04``, which runs FE/FT/FIC-101 alongside
    LIC/LAH/LAL-101, so anything recovering loops from the number alone would
    call those one loop.
    """
    fs = Flowsheet("two loops on one number")
    flow = fs.add_loop("F", 101)
    level = fs.add_loop("L", 101)

    assert (flow.variable, flow.number) == ("F", "101")
    assert flow.name == "F-101" and level.name == "L-101"
    assert flow.tag("FT") == "FT-101"
    assert level.tag("LT") == "LT-101"


def test_fs_loops_enumerates_them_in_declaration_order():
    fs = Flowsheet("many")
    declared = [fs.add_loop("F", 303), fs.add_loop("L", 304), fs.add_loop("T", 307)]
    assert fs.loops == declared
    assert [loop.name for loop in fs.loops] == ["F-303", "L-304", "T-307"]


def test_one_loop_cannot_be_declared_twice():
    fs = Flowsheet("dupe")
    fs.add_loop("F", 303)
    with pytest.raises(ValueError, match=r"loop F-303 is already declared"):
        fs.add_loop("F", 303)


def test_a_loop_takes_a_single_letter_and_a_number():
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="single ISA letter"):
        fs.add_loop("FIC", 303)
    with pytest.raises(ValueError, match="needs a number"):
        fs.add_loop("F", "")


# --- automatic numbering ------------------------------------------------------


def test_an_omitted_number_takes_the_sheets_next_one():
    fs = Flowsheet("draft", loop_number_start=301)
    assert [fs.add_loop(v).name for v in ("P", "T", "F")] == ["P-301", "T-302", "F-303"]


def test_the_counter_is_one_series_across_measured_variables():
    """P&ID_301 runs P-301, T-302, F-303, L-304, F-305, L-306, T-307, F-308.

    One series climbing through whichever variable came next, not a counter per
    variable -- which would have put F-301, T-301 and L-301 on one sheet.
    """
    fs = Flowsheet("A300", loop_number_start=301)
    names = [fs.add_loop(v).name for v in ("P", "T", "F", "L", "F", "L", "T", "F")]
    assert names == ["P-301", "T-302", "F-303", "L-304", "F-305", "L-306", "T-307", "F-308"]


def test_the_series_starts_at_a_unit_100_number_by_default():
    """101, not 1, for the reason ``line_number_start`` is 1001: ``FIC-1`` is
    not a tag anyone writes on a P&ID, and the sheet has to be showable before
    the author has said which plant area it is.
    """
    fs = Flowsheet("plain")
    assert [fs.add_loop("F").name for _ in range(3)] == ["F-101", "F-102", "F-103"]


def test_allocation_order_is_declaration_order():
    """Eagerly, at the ``add_loop`` line, not at render or on first use.

    A loop that is declared and then never tagged still spends its number, which
    is what makes the file readable: the numbers run down the page in the order
    the page declares them.
    """
    fs, line = _sheet()
    first = fs.add_loop("F")
    unused = fs.add_loop("L")  # declared, never tagged, still spends 102
    third = fs.add_loop("T")
    fs.add_instrument("TT", third, sensing=line, at=0.5, offset=60)
    fs.to_svg()
    assert [loop.number for loop in (first, unused, third)] == ["101", "102", "103"]


def test_allocated_and_typed_numbers_mix_on_one_sheet():
    """The typed ones do not move the counter and the counter does not skip them."""
    fs = Flowsheet("mixed", loop_number_start=301)
    assert fs.add_loop("P").name == "P-301"
    assert fs.add_loop("F", 316).name == "F-316"  # typed: reserves nothing
    assert fs.add_loop("T").name == "T-302"  # the series carries straight on
    assert fs.add_loop("L").name == "L-303"


def test_a_one_member_loop_is_a_legitimate_use():
    """CHEE4001 p.13 numbers "each group of components", and a group of one is a
    group: the tail of P&ID_301 (FE-313, PI-316, TI-319, LI-322) is loops of one.
    """
    fs, line = _sheet()
    lone = fs.add_loop("P")
    pi = fs.add_instrument("PI", lone, sensing=line, at=0.3, offset=50)
    assert (lone.name, pi.name) == ("P-101", "PI-101")


def test_an_allocated_number_that_lands_on_a_typed_one_raises_at_that_line():
    """No reservation list, so the counter can walk onto a number typed by hand.

    It is not resolved silently in either direction: stepping over the typed
    number would put a hole in the series nothing asked for, and taking it would
    mint a second F-102.
    """
    fs = Flowsheet("collision")
    fs.add_loop("F", 102)
    fs.add_loop("F")  # F-101
    with pytest.raises(ValueError) as excinfo:
        fs.add_loop("F")  # would be F-102
    message = str(excinfo.value)
    assert "loop F-102 took 102, the next number in this sheet's series" in message
    assert "loop_number_start" in message  # names the way out
    # and nothing was declared, so the sheet still holds two loops
    assert [loop.name for loop in fs.loops] == ["F-102", "F-101"]


def test_a_refused_declaration_burns_no_number():
    fs = Flowsheet("refused", loop_number_start=301)
    assert fs.add_loop("P").name == "P-301"
    with pytest.raises(ValueError, match="single ISA letter"):
        fs.add_loop("FIC")
    assert fs.add_loop("T").name == "T-302"  # the bad letter cost nothing


def test_a_number_that_is_already_free_of_the_series_never_collides():
    """The reason the naive counter is safe: nothing outside ``fs.loops`` spends
    a loop number. A final control element takes its loop's -- CHEE4001 p.11
    numbers a flow loop's element, transmitter, controller and valve all 504 --
    so tagging one consumes nothing the counter could later hand out.
    """
    fs = Flowsheet("elements", loop_number_start=504)
    flow = fs.add_loop("F")
    cv = fs.add(U.Valve(flow.tag("CV"), variant="control"))
    fe = fs.add(U.Fitting(flow.tag("FE"), variant="venturi"))
    assert (cv.name, fe.name) == ("CV-504", "FE-504")
    assert fs.add_loop("T").name == "T-505"  # the valve reserved nothing


def test_an_allocated_number_is_never_rewritten_afterwards():
    """Allocation is where "allocate once" happens, not an exception to it."""
    fs, line = _sheet()
    loop = fs.add_loop("F", None)
    ft = fs.add_instrument("FT", loop, sensing=line, at=0.5, offset=60)
    cv = fs.add(U.Valve(loop.tag("CV"), variant="control")).pin(x=300, y=300)
    vent = fs.add(U.Product("Vent")).pin(x=520, y=300)
    fs.connect(cv.outlet, vent.inlet)
    fs.add_loop("L")  # a later declaration does not renumber an earlier one
    fs.to_svg()
    assert (loop.number, ft.name, cv.name) == ("101", "FT-101", "CV-101")


def test_moving_the_start_moves_the_numbers_still_to_come():
    """The start stays the authoritative setting after construction too.

    The counter is the start plus what has been handed out, so moving the start
    moves everything still to come and un-spends nothing: the ``F-101`` below is
    already on the sheet and no longer the start's business.
    """
    fs = Flowsheet("moved")
    assert fs.add_loop("F").name == "F-101"
    fs.loop_number_start = 301
    assert fs.add_loop("T").name == "T-302"
    assert fs.add_loop("L").name == "L-303"


def test_the_number_is_allocated_once_and_never_renumbered():
    """A loop number leaves the drawing for the DCS, unlike a stream number.

    ``renumber_streams()`` re-runs on every ``connect()`` and again before every
    render, because a stream number is engine output. Nothing re-runs on a loop,
    so the tag a sheet minted before it was finished is the tag it renders with.
    """
    fs, line = _sheet()
    loop = fs.add_loop("F", 303)
    ft = fs.add_instrument("FT", loop, sensing=line, at=0.5, offset=60)
    cv = fs.add(U.Valve(loop.tag("CV"), variant="control")).pin(x=300, y=300)
    vent = fs.add(U.Product("Vent")).pin(x=520, y=300)
    fs.connect(cv.outlet, vent.inlet)  # more topology, and so more renumbering

    fs.to_svg()  # routes, renumbers the streams, validates
    assert (loop.number, ft.name, cv.name) == ("303", "FT-303", "CV-303")


# --- tagging things that are not balloons -------------------------------------


def test_loop_tag_hands_a_tag_to_any_unit_class():
    """Loop 303's primary element is a venturi and its final element a valve.

    Neither is minted by ``add_instrument``, so ``loop.tag`` is the one route
    into a loop that every unit class shares.
    """
    fs = Flowsheet("mixed members")
    loop = fs.add_loop("F", 303)
    fe = fs.add(U.Fitting(loop.tag("FE"), variant="venturi"))
    cv = fs.add(U.Valve(loop.tag("CV"), variant="control"))
    assert (fe.name, cv.name) == ("FE-303", "CV-303")


def test_loop_tag_does_not_hold_a_final_element_to_the_measured_variable():
    """The reference sheet spells every control valve ``CV-``, whatever it
    strokes, so a final element's letters do not track the loop it closes and
    there is nothing for a first-letter rule to hold true. Its number does
    track -- ``LIC-306`` there strokes ``CV-306`` -- which is why ``tag()``
    supplies the number and judges nothing else.
    """
    fs = Flowsheet("final elements")
    assert fs.add_loop("F", 303).tag("CV") == "CV-303"
    assert fs.add_loop("T", 307).tag("XV") == "XV-307"


def test_loop_tag_still_refuses_an_empty_tag():
    fs = Flowsheet("empty")
    with pytest.raises(ValueError, match="was given an empty tag"):
        fs.add_loop("F", 303).tag("  ")


# --- a primary element, which is lettered from the measured variable (#203) ----


def test_loop_element_composes_a_primary_elements_tag():
    fs = Flowsheet("elements")
    assert fs.add_loop("F", 303).element("FE") == "FE-303"
    assert fs.add_loop("L", 304).element("LE") == "LE-304"


def test_loop_element_holds_a_primary_element_to_the_measured_variable():
    """The whole of issue #203. ``add_instrument("TT", flow_loop)`` had raised
    at the line that wrote it since the loop existed, and ``tag("TE")`` on the
    same loop quietly composed a temperature element on a flow loop -- the same
    mistake caught on one route in and not the other. A primary element is
    lettered from the measured variable exactly as a balloon is."""
    fs = Flowsheet("wrong variable")
    loop = fs.add_loop("F", 303)
    assert loop.tag("TE") == "TE-303", "tag() still composes anything: that is its job"
    with pytest.raises(ValueError) as excinfo:
        loop.element("TE")
    message = str(excinfo.value)
    assert "loop F-303 measures 'F'" in message, "names the loop's variable"
    assert "'TE' opens with 'T'" in message, "and what was passed"
    assert "FE" in message, "and the tag this loop's element would carry"


def test_the_wrong_method_names_the_right_one():
    """A control valve reaching for ``element()`` is the mistake this method
    invites, and the message has to send it back to ``tag()`` rather than
    leaving an author to conclude the valve is on the wrong loop."""
    fs = Flowsheet("a valve down the wrong route")
    with pytest.raises(ValueError) as excinfo:
        fs.add_loop("F", 303).element("CV")
    message = str(excinfo.value)
    assert "loop.tag('CV')" in message, "names the call that composes a final element"
    assert "final control element" in message, "and what one is"


def test_loop_element_checks_only_the_measured_variable():
    """A restriction orifice and a sight glass are lettered from the measured
    variable too, so the rule is the *first* letter and not a second one that
    has to be ``E``."""
    loop = Flowsheet("function letters").add_loop("F", 303)
    assert [loop.element(t) for t in ("FE", "FO", "FG")] == ["FE-303", "FO-303", "FG-303"]


def test_loop_element_matches_the_letter_case_insensitively():
    loop = Flowsheet("case").add_loop("f", 303)
    assert loop.element("fe") == "fe-303", "the tag is the author's, the check is the loop's"


def test_loop_element_refuses_an_empty_tag():
    fs = Flowsheet("empty element")
    with pytest.raises(ValueError, match="was given an empty tag"):
        fs.add_loop("F", 303).element("  ")


# --- the first-letter check ---------------------------------------------------


def test_a_foreign_first_letter_raises_at_the_call_site():
    fs, line = _sheet()
    loop = fs.add_loop("F", 303)
    with pytest.raises(ValueError) as excinfo:
        fs.add_instrument("TT", loop, sensing=line, at=0.5, offset=60)
    message = str(excinfo.value)
    assert "loop F-303 measures 'F'" in message  # names the loop's variable
    assert "'TT' opens with 'T'" in message  # names what was passed
    # and nothing was added, so the sheet is not left holding a wrong tag
    assert [u.name for u in fs.units if isinstance(u, U.Instrument)] == []


def test_the_check_is_only_on_the_first_letter():
    """The function letters are the member's own business; the loop owns one."""
    fs = Flowsheet("functions")
    loop = fs.add_loop("L", 101)
    assert [loop.tag(t) for t in ("LT", "LIC", "LAH", "LAL", "LY")] == [
        "LT-101",
        "LIC-101",
        "LAH-101",
        "LAL-101",
        "LY-101",
    ]


def test_a_loop_letter_is_matched_case_insensitively():
    fs = Flowsheet("case")
    loop = fs.add_loop("f", 303)
    assert loop.variable == "F"
    assert loop.tag("FT") == "FT-303"


# --- the loop-less form survives ----------------------------------------------


def test_a_literal_number_still_works():
    """Nine of the 25 balloons on ``examples/11`` are in no multi-member loop.

    An indicator standing alone and an interlock square with no measured
    variable at all are correct as they are, so the literal-number form is not
    legacy and takes no deprecation.
    """
    fs, line = _sheet()
    ti = fs.add_instrument("TI", 325, sensing=line, at=0.3, offset=50)
    square = fs.add_instrument("I", 1, sensing=ti, at="S", offset=44, variant="logic")
    assert (ti.name, square.name) == ("TI-325", "I-1")
    assert fs.loops == []
    fs.to_svg()  # renders, and validation raises nothing


def test_declared_and_undeclared_instruments_mix_on_one_sheet():
    fs, line = _sheet()
    loop = fs.add_loop("F", 303)
    ft = fs.add_instrument("FT", loop, sensing=line, at=0.5, offset=60)
    pi = fs.add_instrument("PI", 315, sensing=line, at=0.2, offset=50)
    assert (ft.name, pi.name) == ("FT-303", "PI-315")


# --- a loop is not a unit -----------------------------------------------------


def test_a_loop_never_reaches_the_units_list_or_an_equipment_list():
    """A loop is a namespace: no frame, no ports, nothing drawn.

    Everything downstream (layout, routing, the renderer, the equipment list)
    iterates ``fs.units`` unconditionally, so the loop has to stay out of it.
    """
    fs, line = _sheet()
    loop = fs.add_loop("F", 303)
    fs.add(U.Vessel("V-101", description="Surge Drum")).pin(x=300, y=320)
    fs.add_instrument("FT", loop, sensing=line, at=0.5, offset=60)

    assert loop not in fs.units
    rows = equipment_list(fs).rows
    assert "303" not in repr(rows) and "F-303" not in repr(rows)
    assert [tag for tag, _ in rows] == ["V-101"]

    svg = fs.to_svg()
    assert ">F-303<" not in svg


# --- ISO 15519-2 5.2.4, the control-function letter sequence -------------------


def _letter_warnings(fs):
    fs.to_svg()
    return [w for w in fs.warnings if w.code == "letter-sequence"]


def test_out_of_sequence_control_functions_warn():
    """ISO 15519-2:2015 5.2.4 orders control functions I, R, C, S, M, Z, A."""
    fs, line = _sheet()
    fs.add_instrument("FCI", 303, sensing=line, at=0.5, offset=60)
    (warning,) = _letter_warnings(fs)
    assert warning.severity == "warning"
    assert "FCI-303 spells its control functions 'FCI'" in warning.message
    assert "ISO 15519-2:2015 5.2.4" in warning.message
    assert "this tag reads 'FIC'" in warning.message


def test_the_sequence_is_a_warning_and_never_stops_the_drawing():
    fs, line = _sheet()
    fs.add_instrument("FCI", 303, sensing=line, at=0.5, offset=60)
    assert fs.to_svg()  # no raise: the letters still read
    assert [i.severity for i in fs.validate() if i.code == "letter-sequence"] == ["warning"]


@pytest.mark.parametrize(
    "letters", ["FIC", "FT", "FE", "LAH", "LAL", "PAH", "TIC", "FY", "PI", "I", "LT", "PDI", "FICA"]
)
def test_correctly_ordered_tags_do_not_warn(letters):
    """The shipped examples spell every one of these; none may start warning."""
    fs, line = _sheet()
    fs.add_instrument(letters, 303, sensing=line, at=0.5, offset=60)
    assert _letter_warnings(fs) == []


def test_a_modifier_keeps_the_place_the_author_gave_it():
    """``H`` in ``LAH`` says which limit alarmed, so it is not resequenced."""
    from pandid.validate import _in_sequence

    assert _in_sequence("LAH") == "LAH"
    assert _in_sequence("LAHH") == "LAHH"
    assert _in_sequence("PDIC") == "PDIC"
    assert _in_sequence("FCI") == "FIC"
    assert _in_sequence("FAIC") == "FICA"


@pytest.mark.parametrize("letters", ["ZSC", "ZSO", "ZSH", "ZSL"])
def test_a_position_switch_is_qualified_open_or_closed_not_controlled(letters):
    """ANSI/ISA-5.1-2009 Table 5.2.1 reads ``Z`` as *Position, dimension* and
    ``S`` as *Switch*, and a position switch is qualified by the position it
    switches at: ``O`` open, ``C`` closed, doing for a valve what the ``H`` and
    ``L`` of ``LAH`` do for a measurement.

    Reading that ``C`` as *Control (closed loop)* made ``ZSC`` -- a standard ISA
    valve-position switch -- a tag the library warned against, offering ``ZCS``
    as the cure. Its three siblings escaped only because their qualifier is not
    one of the seven ordered letters."""
    fs, line = _sheet()
    fs.add_instrument(letters, 303, sensing=line, at=0.5, offset=60)
    assert _letter_warnings(fs) == []


def test_only_a_position_switch_takes_that_reading():
    """The narrowness is the whole of the exception: a ``C`` that closes no
    position switch is still a control function out of place."""
    from pandid.validate import _in_sequence

    assert _in_sequence("ZSCA") == "ZSCA"  # the alarm on one still sorts
    assert _in_sequence("ZAC") == "ZCA"  # no switch for the C to close
    assert _in_sequence("FSC") == "FCS"  # flow, switching and control
    assert _in_sequence("ZC") == "ZC"  # position control: one letter, in order


def test_one_warning_per_tag_however_often_the_square_is_drawn():
    fs, line = _sheet()
    first = fs.add_instrument("ZAC", 1, sensing=line, at=0.5, offset=60, variant="logic")
    host = first
    for _ in range(3):
        host = fs.add_instrument("ZAC", 1, sensing=host, at="N", offset=50, variant="logic")
    assert len({u.tag for u in fs.units if isinstance(u, U.Instrument)}) == 1
    assert len(_letter_warnings(fs)) == 1


# --- serialization ------------------------------------------------------------


def test_loops_round_trip_through_a_spec():
    fs, line = _sheet()
    loop = fs.add_loop("F", 303)
    fs.add_instrument("FT", loop, sensing=line, at=0.5, offset=60)

    spec = fs.to_dict()
    assert spec["loops"] == [{"variable": "F", "number": "303"}]

    rebuilt = Flowsheet.from_dict(spec)
    assert [(loop.variable, loop.number) for loop in rebuilt.loops] == [("F", "303")]
    assert rebuilt.to_dict() == spec


def test_a_sheet_with_no_loops_writes_no_loops_section():
    """An unconverted sheet serializes exactly as it did before loops existed."""
    fs, line = _sheet()
    fs.add_instrument("FT", 101, sensing=line, at=0.5, offset=60)
    assert "loops" not in fs.to_dict()


def test_a_loop_entry_needs_the_variable_it_measures():
    """The number may be left out; the variable may not.

    Nothing else in the file records what a loop measures -- its members carry
    their own letters and are checked *against* it -- so an entry with only a
    number declares nothing.
    """
    from pandid import SpecError

    with pytest.raises(SpecError, match=r"loops\[0\] needs a 'variable'"):
        Flowsheet.from_dict({"name": "T", "loops": [{"number": 303}]})


def test_a_spec_loop_with_no_number_takes_the_sheets_next_one():
    fs = Flowsheet.from_dict(
        {
            "name": "A300",
            "loop_number_start": 301,
            "loops": [{"variable": "P"}, {"variable": "T"}, {"variable": "F", "number": 316}],
        }
    )
    assert [loop.name for loop in fs.loops] == ["P-301", "T-302", "F-316"]


def test_an_auto_numbered_sheet_freezes_when_it_is_written_out():
    """``to_dict()`` is the issue: every loop's number goes out as a literal,
    allocated or typed, so reading the spec back gives the sheet nailed down.
    """
    fs = Flowsheet("draft", loop_number_start=301)
    fs.add_loop("P")
    fs.add_loop("T")
    fs.add_loop("F", 316)

    spec = fs.to_dict()
    assert spec["loops"] == [
        {"variable": "P", "number": "301"},
        {"variable": "T", "number": "302"},
        {"variable": "F", "number": "316"},
    ]
    assert spec["loop_number_start"] == 301  # kept, for the loop added by hand tomorrow

    rebuilt = Flowsheet.from_dict(spec)
    assert [loop.name for loop in rebuilt.loops] == ["P-301", "T-302", "F-316"]
    assert rebuilt.to_dict() == spec  # and again, unmoved


def test_a_default_loop_number_start_writes_no_key():
    fs = Flowsheet("plain")
    fs.add_loop("F", 101)
    assert "loop_number_start" not in fs.to_dict()


def test_a_loop_number_of_the_wrong_type_names_the_entry():
    from pandid import SpecError

    with pytest.raises(SpecError, match=r"loops\[0\]\.number must be a loop number or text"):
        Flowsheet.from_dict({"name": "T", "loops": [{"variable": "F", "number": True}]})


def test_a_duplicate_loop_in_a_spec_names_the_entry():
    from pandid import SpecError

    with pytest.raises(SpecError, match=r"loops\[1\]: loop F-303 is already declared"):
        Flowsheet.from_dict(
            {
                "name": "T",
                "loops": [{"variable": "F", "number": 303}, {"variable": "F", "number": "303"}],
            }
        )


# --- reading a frozen sheet back and carrying on ------------------------------


def test_a_sheet_read_back_carries_its_series_on():
    """The draft -> freeze -> continue path auto-numbering was built for.

    The numbers are literals in the file and nothing records how many the
    counter spent, so the counter is set past the highest number the file
    declares. Without it the rebuilt sheet starts at 301 again and mints a
    second series over the top of the first -- quietly, because ``F-301``
    beside ``P-301`` is two legal loops.
    """
    fs = Flowsheet("A300", loop_number_start=301)
    for variable in ("P", "T", "F", "L"):
        fs.add_loop(variable)

    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert [loop.name for loop in rebuilt.loops] == ["P-301", "T-302", "F-303", "L-304"]
    assert rebuilt.add_loop("F").name == "F-305" == fs.add_loop("F").name


def test_the_restored_counter_clears_a_typed_number_too():
    """It is the highest number declared, not a count of the loops.

    The counter it restores is therefore not always the one the sheet had:
    ``F-316`` typed by hand pushes the rebuilt series to 317 where the
    original would have gone on at 303. That is the cost of deriving the
    counter from the drawing rather than serialising it -- the series
    resumes past a gap instead of filling it, and never lands on a number
    the file already spells out.
    """
    fs = Flowsheet("mixed", loop_number_start=301)
    fs.add_loop("P")  # P-301
    fs.add_loop("T")  # T-302
    fs.add_loop("F", 316)  # typed, well clear of the series
    assert fs.add_loop("L").name == "L-303"

    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert rebuilt.add_loop("L").name == "L-317"


def test_the_restored_counter_only_ever_moves_forwards():
    """A loop numbered below the start does not un-spend anything.

    ``loop_number_start`` is where the series begins; a hand-written spec
    that also declares ``F-12`` has said nothing about where to resume.
    """
    rebuilt = Flowsheet.from_dict(
        {"name": "T", "loop_number_start": 301, "loops": [{"variable": "F", "number": 12}]}
    )
    assert rebuilt.add_loop("T").name == "T-301"


def test_a_loop_number_that_is_not_a_number_leaves_the_counter_alone():
    """``L-301A`` has no place in the series to be past, so it moves nothing
    and does not break the read.
    """
    rebuilt = Flowsheet.from_dict(
        {
            "name": "T",
            "loop_number_start": 301,
            "loops": [{"variable": "L", "number": "301A"}, {"variable": "P", "number": 303}],
        }
    )
    assert [loop.name for loop in rebuilt.loops] == ["L-301A", "P-303"]
    assert rebuilt.add_loop("T").name == "T-304"


def test_a_spec_loop_with_no_number_still_takes_the_sheets_next_one():
    """The counter is restored *after* the section, not before it.

    A hand-written spec is the same declaration as the same calls typed out,
    so ``{variable: T}`` following ``{variable: F, number: 316}`` takes 302
    here exactly as ``add_loop("T")`` would. What the restore fixes is the
    state the read leaves behind, not the read.
    """
    rebuilt = Flowsheet.from_dict(
        {
            "name": "A300",
            "loop_number_start": 301,
            "loops": [{"variable": "P"}, {"variable": "F", "number": 316}, {"variable": "T"}],
        }
    )
    assert [loop.name for loop in rebuilt.loops] == ["P-301", "F-316", "T-302"]
    assert rebuilt.add_loop("L").name == "L-317"


# --- a feedback loop in one statement (#439) ----------------------------------


def _feedback_sheet():
    """A drum on a line with a control valve after it.

    The shape a single-variable feedback loop closes on: something to measure,
    and a final element already standing in the run between two pieces of
    piping. Returns the sheet, the drum and the valve.
    """
    fs = Flowsheet("feedback")
    feed = fs.add(U.Feed("Feed")).pin(port="outlet", x=60, y=200)
    drum = fs.add(U.Vessel("V-101")).pin(x=220, port="inlet", y=200)
    lv = fs.add(U.Valve("LV-101", variant="control")).pin(x=470, port="inlet", y=200)
    prod = fs.add(U.Product("Product")).pin(port="inlet", x=640, y=200)
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    return fs, drum, lv


#: The two ways the same loop is placed: left to the defaults, and with the
#: standoffs an author states. Both are run through the equivalence test,
#: because "the helper adds no placement of its own" is only worth anything if
#: it holds when nothing is stated as well as when everything is.
_PLACEMENTS = [
    {},
    {"at": "S", "offset": 70, "controller_at": "S", "controller_offset": 95},
]


def test_a_feedback_loop_is_one_statement():
    """The six statements of the long-hand, said once (#439)."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)

    assert loop.name == "L-101"
    assert loop.transmitter.name == "LT-101"
    assert loop.controller.name == "LIC-101"
    assert loop.final_element is lv
    assert (loop.measurement.source.owner, loop.measurement.dest.owner) == (
        loop.transmitter,
        loop.controller,
    )
    assert (loop.output.source.owner, loop.output.dest.owner) == (loop.controller, lv)
    assert (loop.measurement.kind, loop.output.kind) == ("electric", "pneumatic")
    # The transmitter reads the drum and the controller only stands on the
    # transmitter: one measurement is drawn, not two.
    assert (loop.transmitter.host, loop.transmitter.relation) == (drum, "sensing")
    assert (loop.controller.host, loop.controller.relation) == (loop.transmitter, "near")


@pytest.mark.parametrize("placement", _PLACEMENTS, ids=["defaults", "stated"])
def test_the_helper_draws_what_the_long_hand_draws(placement):
    """The whole of the claim: identical sheets, to the last character.

    Built twice on one process from two spellings and rendered, so this covers
    the tags, both balloon frames, both signal routes and every mark either
    spelling puts on the paper. ``examples/04_control_loop.py`` makes the same
    comparison against a committed golden; this one is the API's own, and the
    one that runs with no placement stated at all -- which is where a hidden
    default inside the helper would show up as a moved balloon.
    """
    long_hand, drum, lv = _feedback_sheet()
    loop = long_hand.add_loop("L", 101)
    lt = long_hand.add_instrument(
        "LT",
        loop,
        sensing=drum,
        **{k: v for k, v in placement.items() if not k.startswith("controller_")},
    )
    lic = long_hand.add_instrument(
        "LIC",
        loop,
        near=lt,
        variant="shared",
        **{
            k.removeprefix("controller_"): v
            for k, v in placement.items()
            if k.startswith("controller_")
        },
    )
    long_hand.connect(lt.sig_out, lic.sig_in, kind="electric")
    long_hand.connect(lic.sig_out, lv.actuator, kind="pneumatic")

    one_liner, drum, lv = _feedback_sheet()
    one_liner.add_control_loop("L", 101, measuring=drum, acting_on=lv, **placement)

    assert one_liner.to_svg() == long_hand.to_svg()


def test_the_balloons_it_places_land_clear_of_the_sheet():
    """What #439 was raised about: the probe guessed ``offset=40`` and
    ``offset=45`` and tripped ``unit-overlap``. Nothing is guessed here, and
    #428's standoff resolver is what keeps the pair apart.

    Both halves are asserted, and #448 is why: this used to forbid an overlap
    and nothing else, so it passed with ``add_control_loop`` stubbed to return
    ``None`` -- an empty sheet overlaps nothing. It also asked ``validate()``
    for a geometric finding on a sheet nothing had laid out, and that half is
    silent by design, so the finding it forbade could not have been made at
    all. Placed *and* clear is the claim, so the sheet is laid out and routed,
    and the frames are read off it before the findings are.
    """
    fs, drum, lv = _feedback_sheet()
    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)
    fs.layout()
    fs.route()  # what settles an attached balloon; see layout.attach

    findings = validate(fs)
    balloons = [loop.transmitter, loop.controller]
    # Placed: on the sheet, and each with a frame of a real size.
    assert [b.name for b in balloons] == ["LT-101", "LIC-101"]
    for balloon in balloons:
        assert balloon in fs.units
        assert balloon.frame is not None
        assert balloon.frame.w > 0 and balloon.frame.h > 0
    assert fs.unplaced_instruments == []
    # Clear: of each other, of the drum they read and of the valve they stroke.
    assert [f.code for f in findings if f.code == "unit-overlap"] == []
    assert [f.code for f in findings if f.code == "instrument-unplaced"] == []


def test_the_parts_stay_reachable_and_pinnable():
    """An author still has the four objects, and may still move them."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)
    loop.controller.annotate(high="LAH", low="LAL")
    loop.controller.pin(mirrored=True)
    # Re-anchored after the fact: the balloons this built are attached the way
    # any other balloon is, so the arrangement is not sealed by the call.
    loop.transmitter.attach(drum, at="E", offset=60)
    fs.layout()

    assert loop.controller.quadrants == {"c": ("LAH",), "d": ("LAL",)}
    assert loop.controller.frame is not None and loop.controller.frame.mirrored
    assert (loop.transmitter.at, loop.transmitter.offset) == ("E", 60)
    assert loop.transmitter.frame is not None


def test_it_takes_the_valve_rather_than_making_one():
    """A control valve is process equipment already standing between two pieces
    of piping, so nothing here invents one; ``acting_on`` has no default."""
    fs, drum, lv = _feedback_sheet()
    before = list(fs.units)

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)

    assert loop.final_element is lv
    assert [u for u in fs.units if u not in before] == [loop.transmitter, loop.controller]
    with pytest.raises(TypeError):
        fs.add_control_loop("F", 102, measuring=drum)  # type: ignore[call-arg]


def test_the_output_may_name_the_nozzle_it_lands_on():
    """The unit is the short spelling; the nozzle is there for equipment with
    more than one signal terminal, which is the case ``connect()`` refuses to
    guess between."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv.actuator)

    assert loop.final_element is lv
    assert loop.output.dest is lv.actuator


def test_the_letters_follow_from_the_measured_variable():
    """``"F"`` gives FT/FIC, ``"L"`` gives LT/LIC: the variable is typed once
    and ``Loop`` composes the rest."""
    fs, drum, lv = _feedback_sheet()
    fv = fs.add(U.Valve("FV-101", variant="control")).pin(x=340, port="inlet", y=340)
    run = drum.outlet.stream
    assert run is not None  # a level is read off the vessel, a flow off the line

    level = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)
    flow = fs.add_control_loop("F", 101, measuring=run, acting_on=fv)

    assert (level.transmitter.name, level.controller.name) == ("LT-101", "LIC-101")
    assert (flow.transmitter.name, flow.controller.name) == ("FT-101", "FIC-101")


def test_the_function_letters_are_the_authors_and_are_whole_codes():
    """A recording controller and an indicating transmitter are the same loop
    said in a different house style, spelled the way they are said."""
    fs, drum, lv = _feedback_sheet()
    run = drum.outlet.stream
    assert run is not None

    loop = fs.add_control_loop(
        "F",
        101,
        measuring=run,
        acting_on=lv,
        transmitter_letters="FIT",
        controller_letters="FRC",
    )

    assert (loop.transmitter.name, loop.controller.name) == ("FIT-101", "FRC-101")


def test_the_letters_are_the_whole_code_and_a_foreign_variable_is_refused():
    """#448: ``controller_letters="FIC"`` is what an engineer calls the
    instrument and so what they type. It used to be appended to the measured
    variable and draw ``FFIC-909`` with nothing raised. A whole code is checked
    against the loop, so the same string on the wrong loop now fails at the line
    that wrote it rather than reaching the paper."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 909, measuring=drum, acting_on=lv, controller_letters="LIC")
    assert loop.controller.name == "LIC-909"

    fs, drum, lv = _feedback_sheet()
    with pytest.raises(ValueError, match=r"loop L-101 measures 'L', but 'FIC'"):
        fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, controller_letters="FIC")


def test_a_bare_measured_variable_is_not_a_functional_code():
    """The old suffix spelling, typed at the new parameter: ``"IC"`` on an L
    loop opens with the wrong variable, and ``"L"`` alone leaves the balloon
    tagged ``L-101``, which no instrument carries. Both are refused by name."""
    fs, drum, lv = _feedback_sheet()

    with pytest.raises(ValueError, match=r"but 'IC' opens with 'I'"):
        fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, controller_letters="IC")

    fs, drum, lv = _feedback_sheet()
    with pytest.raises(ValueError, match=r"transmitter_letters='L' is the measured"):
        fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, transmitter_letters="L")


def test_empty_function_letters_are_refused():
    """An empty string is no tag at all, and the parameter it was given at is
    named so the author knows which of the two to correct."""
    fs, drum, lv = _feedback_sheet()

    with pytest.raises(ValueError, match="controller_letters"):
        fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, controller_letters="")


def test_a_declared_loop_is_taken_rather_than_declared_again():
    """The usual case, and why the letter is not the only spelling: the valve
    is tagged from the loop and goes in the run long before the balloons do."""
    fs, drum, lv = _feedback_sheet()
    declared = fs.add_loop("L", 101)
    assert lv.name == declared.tag("LV")  # the valve in the run was tagged from it

    loop = fs.add_control_loop(declared, measuring=drum, acting_on=lv)

    assert loop.loop is declared
    assert fs.loops == [declared]  # one entry, however the loop was reached
    assert loop.transmitter.name == "LT-101"


def test_a_declared_loop_may_not_also_be_given_a_number():
    fs, drum, lv = _feedback_sheet()
    declared = fs.add_loop("L", 101)

    with pytest.raises(ValueError, match=r"loop L-101 is already declared"):
        fs.add_control_loop(declared, 102, measuring=drum, acting_on=lv)


def test_it_declares_the_loop_when_given_a_letter():
    """Including taking the sheet's next number, exactly as ``add_loop`` does,
    for the sheet whose valve tag was typed literally."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", measuring=drum, acting_on=lv)

    assert loop.name == "L-101"
    assert [declared.name for declared in fs.loops] == ["L-101"]
    assert fs.add_loop("F").name == "F-102"


def test_the_handle_answers_for_the_loop_it_names():
    """``loop`` is what the author called it, so a second member joins from it
    without their having to know a ``ControlLoop`` is not a ``Loop``."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)
    alarm = fs.add_instrument("LAH", loop, near=loop.controller, at="E")

    assert (loop.variable, loop.number) == ("L", "101")
    assert loop.tag("XV") == "XV-101"
    assert loop.element("LG") == "LG-101"
    assert alarm.name == "LAH-101"
    with pytest.raises(ValueError, match="opens with 'T'"):
        fs.add_instrument("TT", loop)


def test_the_signal_kinds_are_the_authors():
    """Electric in and pneumatic out is the default because that is what most
    loops are; an electrically stroked valve says so."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop(
        "L", 101, measuring=drum, acting_on=lv, measurement_kind="data", output_kind="electric"
    )

    assert (loop.measurement.kind, loop.output.kind) == ("data", "electric")


def test_the_loop_it_builds_still_reaches_no_equipment_list():
    """A ControlLoop draws nothing of its own: the marks on the sheet are the
    two balloons and the valve, and the handle is not one of them."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)

    assert loop not in fs.units and loop.loop not in fs.units
    # The list in full, not "L-101 is absent from it": nothing on the sheet
    # could ever have been tagged with a loop's name, so forbidding that alone
    # is a check that cannot fail. What the list has to say is which of the
    # things this call *did* put on the sheet reach it -- the drum, and neither
    # balloon.
    assert [tag for tag, _ in equipment_list(fs).rows] == ["V-101"]
    assert loop.transmitter in fs.units and loop.controller in fs.units


# --- a rejected call changes nothing (#433) -----------------------------------


def _snapshot(fs: Flowsheet) -> dict[str, object]:
    """Everything a refused call must have left exactly as it found it.

    All five of the things ``add_control_loop`` writes to, because it writes to
    all five and the old failures were spread across them: the loops, the
    allocation counter behind an omitted number, the units, the streams, and
    which line each nozzle is on. Ports are read off the units by name rather
    than by identity, so a *minted* pool member -- a balloon left carrying a
    spare nozzle no line reaches -- shows up as a difference instead of hiding.

    Names and numbers rather than the objects: comparing the collections
    themselves would pass on a list whose members had been mutated in place.
    """
    return {
        "loops": [(loop.variable, loop.number) for loop in fs.loops],
        "allocated": fs._loops_allocated,
        "units": [unit.name for unit in fs.units],
        "streams": [
            (s.name, s.kind, s.source.owner.name, s.source.name, s.dest.owner.name, s.dest.name)
            for s in fs.streams
        ],
        "ports": {
            (unit.name, name): port.stream.name if port.stream is not None else None
            for unit in fs.units
            for name, port in unit.ports.items()
        },
    }


def _take_the_controllers_tag(fs: Flowsheet, drum: U.Vessel, lv: U.Valve) -> None:
    fs.add_instrument("LIC", 101)


def _stroke_the_valve_already(fs: Flowsheet, drum: U.Vessel, lv: U.Valve) -> None:
    driver = fs.add_instrument("LY", 900, near=lv, at="N")
    fs.connect(driver.sig_out, lv.actuator, kind="pneumatic")


def _nothing(fs: Flowsheet, drum: U.Vessel, lv: U.Valve) -> None:
    pass


#: ``(prepare, the call that is refused, the corrected call, the message)``.
#: One entry per failure point the #433 review executed, plus the ones the
#: preflight added. Every one of them used to leave something behind.
_REJECTIONS = [
    pytest.param(
        _take_the_controllers_tag,
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv),
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, controller_letters="LRC"
        ),
        "already exists",
        id="the controller's tag is already on the sheet",
    ),
    pytest.param(
        _nothing,
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, controller_letters=""
        ),
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv),
        "controller_letters",
        id="empty function letters",
    ),
    pytest.param(
        _nothing,
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, controller_letters="FIC"
        ),
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv),
        "measures 'L'",
        id="a functional code from another variable",
    ),
    pytest.param(
        _nothing,
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, at="Q"),
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, at="N"),
        "at= on a unit host",
        id="the transmitter is placed nowhere",
    ),
    pytest.param(
        _nothing,
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, controller_at="Q"
        ),
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, controller_at="N"
        ),
        "at= on a unit host",
        id="the controller is placed nowhere",
    ),
    pytest.param(
        _nothing,
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, output_kind="nonsense"
        ),
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, output_kind="electric"
        ),
        "Stream kind must be one of",
        id="an output kind that is no kind",
    ),
    pytest.param(
        _nothing,
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, measurement_kind="material"
        ),
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv),
        "signal line",
        id="a measurement drawn as process piping",
    ),
    pytest.param(
        _stroke_the_valve_already,
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv),
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=fs.add(U.Valve("LV-102", variant="control"))
        ),
        "already connected",
        id="the final element is already stroked",
    ),
]


@pytest.mark.parametrize("prepare, refused, corrected, match", _REJECTIONS)
def test_a_refused_control_loop_leaves_the_sheet_as_it_found_it(prepare, refused, corrected, match):
    """#433: five mutations in sequence and no rollback, so a rejected call
    consumed a loop number and left half a control loop on the drawing.

    Every one of these used to leave something behind -- the loop, or the loop
    and the transmitter, or the loop, both balloons *and* the measurement line.
    The snapshot is the whole of the sheet's mutable state, and the retry is
    the half that says the wreckage is really gone: correcting the argument and
    calling again has to land the loop on the number it asked for the first
    time, not on the next one.
    """
    fs, drum, lv = _feedback_sheet()
    prepare(fs, drum, lv)
    before = _snapshot(fs)

    with pytest.raises(ValueError, match=match):
        refused(fs, drum, lv)

    assert _snapshot(fs) == before

    loop = corrected(fs, drum, lv)
    assert loop.name == "L-101"
    assert [declared.name for declared in fs.loops] == ["L-101"]


def test_a_refused_control_loop_burns_no_allocated_number():
    """The sharpest of them, because the damage outlives the error: the number
    is left to the sheet, the call is refused, and the retry used to come back
    L-102 -- a number nobody typed, arrived at silently, on a drawing whose
    loop numbers leave it for a DCS.
    """
    fs, drum, lv = _feedback_sheet()
    before = _snapshot(fs)

    with pytest.raises(ValueError, match="controller_letters"):
        fs.add_control_loop("L", measuring=drum, acting_on=lv, controller_letters="")

    assert _snapshot(fs) == before

    loop = fs.add_control_loop("L", measuring=drum, acting_on=lv)
    assert loop.name == "L-101"


def test_a_loop_declared_on_another_sheet_is_refused():
    """A loop is a namespace belonging to one sheet. Taken, ``fs.loops`` stays
    empty while two balloons are numbered from a loop the spec never writes."""
    fs, drum, lv = _feedback_sheet()
    elsewhere, _, _ = _feedback_sheet()
    theirs = elsewhere.add_loop("L", 101)
    before = _snapshot(fs)

    with pytest.raises(ValueError, match=r"was not declared on flowsheet 'feedback'"):
        fs.add_control_loop(theirs, measuring=drum, acting_on=lv)

    assert _snapshot(fs) == before
    assert fs.add_control_loop("L", 101, measuring=drum, acting_on=lv).name == "L-101"


@pytest.mark.parametrize("role", ["measuring", "acting_on"])
def test_a_member_from_another_sheet_is_refused(role):
    """The sheet it draws would not round-trip: ``to_dict()`` writes no entry
    for the other sheet's unit, so reading it back has nothing of that name for
    the balloon or the signal line to reach."""
    fs, drum, lv = _feedback_sheet()
    elsewhere, their_drum, their_valve = _feedback_sheet()
    ours: dict[str, U.Unit] = {"measuring": drum, "acting_on": lv}
    theirs = {"measuring": their_drum, "acting_on": their_valve}[role]
    before = _snapshot(fs)

    with pytest.raises(ValueError, match=rf"{role}=.*not on 'feedback'"):
        fs.add_control_loop("L", 101, **{**ours, role: theirs})

    assert _snapshot(fs) == before
    # And the sheet still round-trips, which is what the refusal protects.
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert [unit.name for unit in rebuilt.units] == [unit.name for unit in fs.units]
