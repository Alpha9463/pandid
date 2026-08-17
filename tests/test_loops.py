"""Control loops: identity, tagging, and the two rules a declared loop enforces."""

import pytest

from pandid import Flowsheet, units as U
from pandid.document import equipment_list


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
