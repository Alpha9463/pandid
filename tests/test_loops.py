"""Control loops: identity, tagging, and the two rules a declared loop enforces."""

import warnings

import pytest

from pandid import ControlValve, Flowsheet, Instrument, units as U
from pandid.document import equipment_list
from pandid.spec import from_dict, to_dict
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
    """Check that two loops may share a number and are told apart by their variable."""
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


def test_allocation_order_is_declaration_order():
    """Check that numbers are allocated in declaration order, tagged or not."""
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
    """Check that a loop with one member tags it."""
    fs, line = _sheet()
    lone = fs.add_loop("P")
    pi = fs.add_instrument("PI", lone, sensing=line, at=0.3, offset=50)
    assert (lone.name, pi.name) == ("P-101", "PI-101")


def test_an_allocated_number_that_lands_on_a_typed_one_raises_at_that_line():
    """Check that allocating a number already typed is refused and declares nothing."""
    fs = Flowsheet("collision")
    fs.add_loop("F", 102)
    fs.add_loop("F")  # F-101
    with pytest.raises(ValueError) as excinfo:
        fs.add_loop("F")  # would be F-102
    message = str(excinfo.value)
    assert "loop F-102 took 102, the next number in this sheet's series" in message
    assert "loop_number_start" in message  # names the way out
    assert [loop.name for loop in fs.loops] == ["F-102", "F-101"]


def test_a_refused_declaration_burns_no_number():
    fs = Flowsheet("refused", loop_number_start=301)
    assert fs.add_loop("P").name == "P-301"
    with pytest.raises(ValueError, match="single ISA letter"):
        fs.add_loop("FIC")
    assert fs.add_loop("T").name == "T-302"  # the bad letter cost nothing


def test_a_number_that_is_already_free_of_the_series_never_collides():
    """Check that tagging units from a loop spends no number."""
    fs = Flowsheet("elements", loop_number_start=504)
    flow = fs.add_loop("F")
    cv = fs.add(U.Valve(flow.tag("CV"), variant="control"))
    fe = fs.add(U.Fitting(flow.tag("FE"), variant="venturi"))
    assert (cv.name, fe.name) == ("CV-504", "FE-504")
    assert fs.add_loop("T").name == "T-505"  # the valve reserved nothing


@pytest.mark.parametrize(("number", "expected"), [(None, "101"), (303, "303")])
def test_the_number_is_allocated_once_and_never_renumbered(number: int | None, expected: str):
    """Check that a loop's number and tags survive later declarations and a render."""
    fs, line = _sheet()
    loop = fs.add_loop("F", number)
    ft = fs.add_instrument("FT", loop, sensing=line, at=0.5, offset=60)
    cv = fs.add(U.Valve(loop.tag("CV"), variant="control")).pin(x=300, y=300)
    vent = fs.add(U.Product("Vent")).pin(x=520, y=300)
    fs.connect(cv.outlet, vent.inlet)  # more topology, and so more renumbering
    fs.add_loop("L")  # a later declaration does not renumber an earlier one
    fs.to_svg()  # routes, renumbers the streams, validates
    assert (loop.number, ft.name, cv.name) == (expected, f"FT-{expected}", f"CV-{expected}")


def test_moving_the_start_moves_the_numbers_still_to_come():
    """Check that moving the start moves only the numbers still to come."""
    fs = Flowsheet("moved")
    assert fs.add_loop("F").name == "F-101"
    fs.loop_number_start = 301
    assert fs.add_loop("T").name == "T-302"
    assert fs.add_loop("L").name == "L-303"


# --- tagging things that are not balloons -------------------------------------


def test_loop_tag_does_not_hold_a_final_element_to_the_measured_variable():
    """Check that ``tag()`` composes a final element's tag whatever its letters."""
    fs = Flowsheet("final elements")
    assert fs.add_loop("F", 303).tag("CV") == "CV-303"
    assert fs.add_loop("T", 307).tag("XV") == "XV-307"


def test_loop_tag_still_refuses_an_empty_tag():
    fs = Flowsheet("empty")
    with pytest.raises(ValueError, match="was given an empty tag"):
        fs.add_loop("F", 303).tag("  ")


# --- a primary element, which is lettered from the measured variable -----------


def test_loop_element_composes_a_primary_elements_tag():
    fs = Flowsheet("elements")
    assert fs.add_loop("F", 303).element("FE") == "FE-303"
    assert fs.add_loop("L", 304).element("LE") == "LE-304"


def test_loop_element_holds_a_primary_element_to_the_measured_variable():
    """Check that ``element()`` refuses a primary element of another variable, naming both."""
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
    """Check that ``element()`` given a final element points to ``tag()``."""
    fs = Flowsheet("a valve down the wrong route")
    with pytest.raises(ValueError) as excinfo:
        fs.add_loop("F", 303).element("CV")
    message = str(excinfo.value)
    assert "loop.tag('CV')" in message, "names the call that composes a final element"
    assert "final control element" in message, "and what one is"


def test_loop_element_checks_only_the_measured_variable():
    """Check that ``element()`` checks only the first letter."""
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
    assert [u.name for u in fs.units if isinstance(u, U.Instrument)] == []


def test_a_loop_letter_is_matched_case_insensitively():
    fs = Flowsheet("case")
    loop = fs.add_loop("f", 303)
    assert loop.variable == "F"
    assert loop.tag("FT") == "FT-303"


# --- the loop-less form survives ----------------------------------------------


def test_a_literal_number_still_works():
    """Check that an instrument takes a literal number with no loop."""
    fs, line = _sheet()
    ti = fs.add_instrument("TI", 325, sensing=line, at=0.3, offset=50)
    square = fs.add_instrument("I", 1, sensing=ti, face="S", offset=44, variant="logic")
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
    """Check that a loop is not a unit, an equipment-list row or drawn text."""
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
    "letters",
    ["FIC", "FT", "FE", "LAH", "LAL", "PAH", "TIC", "FY", "PI", "I", "LT", "PDI", "FICA"]
    + ["ZSC", "ZSO", "ZSH", "ZSL"],  # a position switch is qualified open or closed
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


def test_only_a_position_switch_takes_that_reading():
    """Check that only a position switch reads ``C`` as closed."""
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
        host = fs.add_instrument("ZAC", 1, sensing=host, face="N", offset=50, variant="logic")
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
    """Check that a spec loop entry without a variable is refused."""
    from pandid import SpecError

    with pytest.raises(SpecError, match=r"loops\[0\] needs a 'variable'"):
        Flowsheet.from_dict({"name": "T", "loops": [{"number": 303}]})


def test_an_auto_numbered_sheet_freezes_when_it_is_written_out():
    """Check that every loop number is written out as a literal and reads back unchanged."""
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


def test_the_restored_counter_clears_a_typed_number_too():
    """Check that the restored counter resumes past the highest number declared."""
    fs = Flowsheet("mixed", loop_number_start=301)
    fs.add_loop("P")  # P-301
    fs.add_loop("T")  # T-302
    fs.add_loop("F", 316)  # typed, well clear of the series
    assert fs.add_loop("L").name == "L-303"

    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert rebuilt.add_loop("L").name == "L-317"


def test_the_restored_counter_only_ever_moves_forwards():
    """Check that a number below the start does not move the restored counter."""
    rebuilt = Flowsheet.from_dict(
        {"name": "T", "loop_number_start": 301, "loops": [{"variable": "F", "number": 12}]}
    )
    assert rebuilt.add_loop("T").name == "T-301"


def test_a_loop_number_that_is_not_a_number_leaves_the_counter_alone():
    """Check that a non-numeric loop number leaves the counter alone."""
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
    """Check that a spec loop with no number takes the next number, then the counter is restored."""
    rebuilt = Flowsheet.from_dict(
        {
            "name": "A300",
            "loop_number_start": 301,
            "loops": [{"variable": "P"}, {"variable": "F", "number": 316}, {"variable": "T"}],
        }
    )
    assert [loop.name for loop in rebuilt.loops] == ["P-301", "F-316", "T-302"]
    assert rebuilt.add_loop("L").name == "L-317"


# --- a feedback loop in one statement -----------------------------------------


def _feedback_sheet():
    """Return a sheet with a drum and a control valve in one run, with the drum and the valve."""
    fs = Flowsheet("feedback")
    feed = fs.add(U.Feed("Feed")).pin(port="outlet", x=60, y=200)
    drum = fs.add(U.Vessel("V-101")).pin(x=220, port="inlet", y=200)
    lv = fs.add(U.Valve("LV-101", variant="control")).pin(x=470, port="inlet", y=200)
    prod = fs.add(U.Product("Product")).pin(port="inlet", x=640, y=200)
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    return fs, drum, lv


#: The loop placed with the defaults and with every standoff stated.
_PLACEMENTS = [
    {},
    {"face": "S", "offset": 70, "controller_face": "S", "controller_offset": 95},
]


def test_a_feedback_loop_is_one_statement():
    """Check that ``add_control_loop`` declares the loop, both balloons and both signal lines."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)

    assert loop.loop.name == "L-101"
    assert loop.transmitter.name == "LT-101"
    assert loop.controller.name == "LIC-101"
    assert loop.final_element is lv
    assert (loop.measurement.source.owner, loop.measurement.dest.owner) == (
        loop.transmitter,
        loop.controller,
    )
    assert (loop.output.source.owner, loop.output.dest.owner) == (loop.controller, lv)
    assert (loop.measurement.kind, loop.output.kind) == ("electric", "pneumatic")
    # The transmitter reads the drum; the controller stands on the transmitter.
    assert (loop.transmitter.host, loop.transmitter.relation) == (drum, "sensing")
    assert (loop.controller.host, loop.controller.relation) == (loop.transmitter, "near")


@pytest.mark.parametrize("placement", _PLACEMENTS, ids=["defaults", "stated"])
def test_the_helper_draws_what_the_long_hand_draws(placement):
    """The helper and long-hand calls render identical tags, frames and routes."""
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


@pytest.mark.parametrize("by_unit", [False, True], ids=["ports", "units"])
def test_a_long_hand_loop_with_no_kind_draws_what_the_helper_draws(by_unit):
    """Check that signal lines connected with no kind take the helper's kinds."""
    long_hand, drum, lv = _feedback_sheet()
    loop = long_hand.add_loop("L", 101)
    lt = long_hand.add_instrument("LT", loop, sensing=drum)
    lic = long_hand.add_instrument("LIC", loop, near=lt, variant="shared")
    long_hand.connect(lt if by_unit else lt.sig_out, lic if by_unit else lic.sig_in)
    long_hand.connect(lic if by_unit else lic.sig_out, lv if by_unit else lv.actuator)

    one_liner, drum, lv = _feedback_sheet()
    one_liner.add_control_loop("L", 101, measuring=drum, acting_on=lv)

    assert [s.kind for s in long_hand.streams] == [s.kind for s in one_liner.streams]
    assert one_liner.to_svg() == long_hand.to_svg()


def test_the_balloons_it_places_land_clear_of_the_sheet():
    """Check that the loop's balloons are placed, sized and clear of each other and the sheet."""
    fs, drum, lv = _feedback_sheet()
    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)
    fs.layout()
    fs.route()  # what settles an attached balloon; see layout.attach

    findings = validate(fs)
    balloons = [loop.transmitter, loop.controller]
    assert [b.name for b in balloons] == ["LT-101", "LIC-101"]
    for balloon in balloons:
        assert balloon in fs.units
        assert balloon.frame is not None
        assert balloon.frame.w > 0 and balloon.frame.h > 0
    assert fs.unplaced_instruments == []
    assert [f.code for f in findings if f.code == "unit-overlap"] == []
    assert [f.code for f in findings if f.code == "instrument-unplaced"] == []


def _level_loop(**placement):
    """Return an unpinned drum and valve with a level loop on them, routed."""
    fs = Flowsheet("level")
    feed, drum = fs.add(U.Feed("Feed")), fs.add(U.Vessel("V-101"))
    lv, prod = fs.add(ControlValve("LV-101")), fs.add(U.Product("Product"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, **placement)
    fs.route()
    return fs, drum, loop


def test_the_default_transmitter_hangs_off_a_face_no_line_leaves():
    """Check that the default level loop hangs LT-101 off the drum's top, clear of its lines."""
    from pandid.portgeom import face_point

    fs, drum, loop = _level_loop()
    assert drum.frame is not None
    assert loop.transmitter.tap == face_point(drum, drum.frame, "N")[0]
    assert "route-along-unit" not in {f.code for f in validate(fs)}
    # A spec keeps the face unstated.
    back = from_dict(to_dict(fs))
    back.route()
    (lt,) = [u for u in back.units if isinstance(u, Instrument) and u.name == "LT-101"]
    assert lt.tap == loop.transmitter.tap
    # A stated face is kept, though a line leaves it.
    _, drum, loop = _level_loop(face="E")
    assert drum.frame is not None
    assert loop.transmitter.tap == face_point(drum, drum.frame, "E")[0]


def test_the_parts_stay_reachable_and_pinnable():
    """An author still has the four objects, and may still move them."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)
    loop.controller.annotate(high="LAH", low="LAL")
    loop.controller.pin(mirrored=True)
    loop.transmitter.attach(drum, face="E", offset=60)
    fs.layout()

    assert loop.controller.quadrants == {"c": ("LAH",), "d": ("LAL",)}
    assert loop.controller.frame is not None and loop.controller.frame.mirrored
    assert (loop.transmitter.face, loop.transmitter.offset) == ("E", 60)
    assert loop.transmitter.frame is not None


def test_it_takes_the_valve_rather_than_making_one():
    """Check that the loop uses the given valve and requires ``acting_on``."""
    fs, drum, lv = _feedback_sheet()
    before = list(fs.units)

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)

    assert loop.final_element is lv
    assert [u for u in fs.units if u not in before] == [loop.transmitter, loop.controller]
    with pytest.raises(TypeError):
        fs.add_control_loop("F", 102, measuring=drum)  # type: ignore[call-arg]


def test_the_output_may_name_the_nozzle_it_lands_on():
    """Check that ``acting_on`` may name the actuator nozzle."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv.actuator)

    assert loop.final_element is lv
    assert loop.output.dest is lv.actuator


def test_the_letters_follow_from_the_measured_variable():
    """Check that the transmitter and controller letters follow the measured variable."""
    fs, drum, lv = _feedback_sheet()
    fv = fs.add(U.Valve("FV-101", variant="control")).pin(x=340, port="inlet", y=340)
    run = drum.outlet.stream
    assert run is not None  # a level is read off the vessel, a flow off the line

    level = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)
    flow = fs.add_control_loop("F", 101, measuring=run, acting_on=fv)

    assert (level.transmitter.name, level.controller.name) == ("LT-101", "LIC-101")
    assert (flow.transmitter.name, flow.controller.name) == ("FT-101", "FIC-101")


def test_the_function_letters_are_the_authors_and_are_whole_codes():
    """Check that the transmitter and controller letters may be given as whole codes."""
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


def test_a_bare_measured_variable_is_not_a_functional_code():
    """Check that a bare suffix or a bare variable letter is refused by name."""
    fs, drum, lv = _feedback_sheet()

    with pytest.raises(ValueError, match=r"but 'IC' opens with 'I'"):
        fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, controller_letters="IC")

    fs, drum, lv = _feedback_sheet()
    with pytest.raises(ValueError, match=r"transmitter_letters='L' is the measured"):
        fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, transmitter_letters="L")


def test_a_declared_loop_is_taken_rather_than_declared_again():
    """Check that a declared loop is used rather than declared again."""
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
    """Check that a letter declares the loop with the sheet's next number."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", measuring=drum, acting_on=lv)

    assert loop.loop.name == "L-101"
    assert [declared.name for declared in fs.loops] == ["L-101"]
    assert fs.add_loop("F").name == "F-102"


def test_the_handle_answers_for_the_loop_it_names():
    """Check that the handle stands for its loop when adding members."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)
    alarm = fs.add_instrument("LAH", loop, near=loop.controller, face="E")

    assert (loop.loop.variable, loop.loop.number) == ("L", "101")
    assert loop.loop.tag("XV") == "XV-101"
    assert loop.loop.element("LG") == "LG-101"
    assert alarm.name == "LAH-101"
    with pytest.raises(ValueError, match="opens with 'T'"):
        fs.add_instrument("TT", loop)


def test_the_signal_kinds_are_the_authors():
    """Check that the measurement and output kinds may be given."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop(
        "L", 101, measuring=drum, acting_on=lv, measurement_kind="data", output_kind="electric"
    )

    assert (loop.measurement.kind, loop.output.kind) == ("data", "electric")


def test_the_loop_it_builds_still_reaches_no_equipment_list():
    """Check that the loop adds two balloons to the sheet and nothing to the equipment list."""
    fs, drum, lv = _feedback_sheet()

    loop = fs.add_control_loop("L", 101, measuring=drum, acting_on=lv)

    assert loop not in fs.units and loop.loop not in fs.units
    assert [tag for tag, _ in equipment_list(fs).rows] == ["V-101"]
    assert loop.transmitter in fs.units and loop.controller in fs.units


# --- a rejected call changes nothing ------------------------------------------


def _snapshot(fs: Flowsheet) -> dict[str, object]:
    """Return every part of the sheet a refused call must leave unchanged, by name."""
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
    driver = fs.add_instrument("LY", 900, near=lv, face="N")
    fs.connect(driver.sig_out, lv.actuator, kind="pneumatic")


def _nothing(fs: Flowsheet, drum: U.Vessel, lv: U.Valve) -> None:
    pass


#: ``(prepare, the call that is refused, the corrected call, the message)``.
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
            "L", measuring=drum, acting_on=lv, controller_letters=""
        ),
        lambda fs, drum, lv: fs.add_control_loop("L", measuring=drum, acting_on=lv),
        "controller_letters",
        id="empty function letters on an allocated number",
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
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, face="Q"),
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, face="N"),
        "face= is a side of V-101",
        id="the transmitter is placed nowhere",
    ),
    pytest.param(
        _nothing,
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, controller_face="Q"
        ),
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, controller_face="N"
        ),
        "face= is a side of LT-101",
        id="the controller is placed nowhere",
    ),
    pytest.param(
        _nothing,
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, at="N", face="N"
        ),
        lambda fs, drum, lv: fs.add_control_loop("L", 101, measuring=drum, acting_on=lv, face="N"),
        "V-101 is a unit, so give face= alone",
        id="the transmitter's face given twice",
    ),
    pytest.param(
        _nothing,
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, controller_at="N", controller_face="N"
        ),
        lambda fs, drum, lv: fs.add_control_loop(
            "L", 101, measuring=drum, acting_on=lv, controller_face="N"
        ),
        "give controller_face= alone",
        id="the controller's face given twice",
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
    """Check that a refused call leaves the sheet unchanged and a corrected call gets its number."""
    fs, drum, lv = _feedback_sheet()
    prepare(fs, drum, lv)
    before = _snapshot(fs)

    with pytest.raises(ValueError, match=match):
        refused(fs, drum, lv)

    assert _snapshot(fs) == before

    loop = corrected(fs, drum, lv)
    assert loop.loop.name == "L-101"
    assert [declared.name for declared in fs.loops] == ["L-101"]


@pytest.mark.parametrize(
    "refused, match",
    [
        pytest.param(
            lambda fs, drum, lv: fs.add_control_loop(
                "L", 101, measuring=drum, acting_on=lv, at="N", face="N"
            ),
            "alone",
            id="face twice",
        ),
        pytest.param(
            lambda fs, drum, lv: fs.add_control_loop(
                "L", 101, measuring=drum, acting_on=lv, controller_at="N", controller_face="N"
            ),
            "alone",
            id="controller_face twice",
        ),
        pytest.param(
            lambda fs, drum, lv: fs.add_control_loop(
                "L", 101, measuring=drum, acting_on=lv, at="S", controller_face="Q"
            ),
            "face= is a side of LT-101",
            id="an old face and a bad controller face",
        ),
    ],
)
def test_a_refused_face_warns_nothing(refused, match: str):
    fs, drum, lv = _feedback_sheet()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match=match):
            refused(fs, drum, lv)
    assert caught == []


@pytest.mark.parametrize(
    "old, member",
    [
        pytest.param(
            lambda fs, drum, lv: fs.add_control_loop(
                "L", 101, measuring=drum, acting_on=lv, at="S"
            ),
            "transmitter",
            id="at",
        ),
        pytest.param(
            lambda fs, drum, lv: fs.add_control_loop(
                "L", 101, measuring=drum, acting_on=lv, controller_at="S"
            ),
            "controller",
            id="controller_at",
        ),
    ],
)
def test_a_face_given_the_old_way_warns_at_the_authors_line(old, member: str, same_file):
    fs, drum, lv = _feedback_sheet()
    with pytest.warns(DeprecationWarning, match="face='S'") as caught:
        loop = old(fs, drum, lv)
    assert [same_file(w.filename) for w in caught] == [same_file(__file__)]
    assert getattr(loop, member).face == "S"
    found = [i.message for i in fs.validate() if i.code == "deprecated"]
    assert found == [str(caught[0].message)]


@pytest.mark.parametrize(
    "old",
    [
        pytest.param(
            lambda fs, drum, lv: fs.add_control_loop(
                "L", 101, measuring=drum, acting_on=lv, at="S"
            ),
            id="at",
        ),
        pytest.param(
            lambda fs, drum, lv: fs.add_control_loop(
                "L", 101, measuring=drum, acting_on=lv, controller_at="S"
            ),
            id="controller_at",
        ),
    ],
)
def test_a_loop_deprecation_raised_as_an_error_changes_nothing(old):
    fs, drum, lv = _feedback_sheet()
    before = (_snapshot(fs), fs.to_dict())
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with pytest.raises(DeprecationWarning):
            old(fs, drum, lv)
    assert (_snapshot(fs), fs.to_dict()) == before


def test_a_loop_refused_at_its_second_line_leaves_the_sheet_whole():
    """Check that a refusal at the second signal line leaves the sheet unchanged."""
    fs = Flowsheet("short", stream_naming_scheme=lambda n: {1: "S1"}[n])
    drum = fs.add(U.Vessel("V-101"))
    lv = fs.add(U.Valve("LV-101", variant="control"))
    before = _snapshot(fs)
    with pytest.warns(DeprecationWarning), pytest.raises(KeyError):
        fs.add_control_loop("L", measuring=drum, acting_on=lv, at="S")
    assert _snapshot(fs) == before
    assert [i for i in fs.validate() if i.code == "deprecated"] == []


def test_a_loop_declared_on_another_sheet_is_refused():
    """Check that a loop declared on another sheet is refused."""
    fs, drum, lv = _feedback_sheet()
    elsewhere, _, _ = _feedback_sheet()
    theirs = elsewhere.add_loop("L", 101)
    before = _snapshot(fs)

    with pytest.raises(ValueError, match=r"was not declared on flowsheet 'feedback'"):
        fs.add_control_loop(theirs, measuring=drum, acting_on=lv)

    assert _snapshot(fs) == before
    assert fs.add_control_loop("L", 101, measuring=drum, acting_on=lv).loop.name == "L-101"


@pytest.mark.parametrize("role", ["measuring", "acting_on"])
def test_a_member_from_another_sheet_is_refused(role):
    """Check that a measured unit or valve from another sheet is refused."""
    fs, drum, lv = _feedback_sheet()
    elsewhere, their_drum, their_valve = _feedback_sheet()
    ours: dict[str, U.Unit] = {"measuring": drum, "acting_on": lv}
    theirs = {"measuring": their_drum, "acting_on": their_valve}[role]
    before = _snapshot(fs)

    with pytest.raises(ValueError, match=rf"{role}=.*not on 'feedback'"):
        fs.add_control_loop("L", 101, **{**ours, role: theirs})

    assert _snapshot(fs) == before
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert [unit.name for unit in rebuilt.units] == [unit.name for unit in fs.units]
