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


def test_the_number_is_allocated_once_and_never_renumbered():
    """A loop number leaves the drawing for the DCS, unlike a stream number.

    ``renumber_streams()`` re-runs on every ``connect()`` and again before every
    render, because a stream number is engine output. Nothing re-runs on a loop,
    so the tag a sheet minted before it was finished is the tag it renders with.
    """
    fs, line = _sheet()
    loop = fs.add_loop("F", 303)
    ft = fs.add_instrument("FT", loop, on=line, at=0.5, offset=60)
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


# --- the first-letter check ---------------------------------------------------


def test_a_foreign_first_letter_raises_at_the_call_site():
    fs, line = _sheet()
    loop = fs.add_loop("F", 303)
    with pytest.raises(ValueError) as excinfo:
        fs.add_instrument("TT", loop, on=line, at=0.5, offset=60)
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
    ti = fs.add_instrument("TI", 325, on=line, at=0.3, offset=50)
    square = fs.add_instrument("I", 1, on=ti, at="S", offset=44, variant="logic")
    assert (ti.name, square.name) == ("TI-325", "I-1")
    assert fs.loops == []
    fs.to_svg()  # renders, and validation raises nothing


def test_declared_and_undeclared_instruments_mix_on_one_sheet():
    fs, line = _sheet()
    loop = fs.add_loop("F", 303)
    ft = fs.add_instrument("FT", loop, on=line, at=0.5, offset=60)
    pi = fs.add_instrument("PI", 315, on=line, at=0.2, offset=50)
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
    fs.add_instrument("FT", loop, on=line, at=0.5, offset=60)

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
    fs.add_instrument("FCI", 303, on=line, at=0.5, offset=60)
    (warning,) = _letter_warnings(fs)
    assert warning.severity == "warning"
    assert "FCI-303 spells its control functions 'FCI'" in warning.message
    assert "ISO 15519-2:2015 5.2.4" in warning.message
    assert "this tag reads 'FIC'" in warning.message


def test_the_sequence_is_a_warning_and_never_stops_the_drawing():
    fs, line = _sheet()
    fs.add_instrument("FCI", 303, on=line, at=0.5, offset=60)
    assert fs.to_svg()  # no raise: the letters still read
    assert [i.severity for i in fs.validate() if i.code == "letter-sequence"] == ["warning"]


@pytest.mark.parametrize(
    "letters", ["FIC", "FT", "FE", "LAH", "LAL", "PAH", "TIC", "FY", "PI", "I", "LT", "PDI", "FICA"]
)
def test_correctly_ordered_tags_do_not_warn(letters):
    """The shipped examples spell every one of these; none may start warning."""
    fs, line = _sheet()
    fs.add_instrument(letters, 303, on=line, at=0.5, offset=60)
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
    first = fs.add_instrument("ZAC", 1, on=line, at=0.5, offset=60, variant="logic")
    host = first
    for _ in range(3):
        host = fs.add_instrument("ZAC", 1, on=host, at="N", offset=50, variant="logic")
    assert len({u.tag for u in fs.units if isinstance(u, U.Instrument)}) == 1
    assert len(_letter_warnings(fs)) == 1


# --- serialization ------------------------------------------------------------


def test_loops_round_trip_through_a_spec():
    fs, line = _sheet()
    loop = fs.add_loop("F", 303)
    fs.add_instrument("FT", loop, on=line, at=0.5, offset=60)

    spec = fs.to_dict()
    assert spec["loops"] == [{"variable": "F", "number": "303"}]

    rebuilt = Flowsheet.from_dict(spec)
    assert [(loop.variable, loop.number) for loop in rebuilt.loops] == [("F", "303")]
    assert rebuilt.to_dict() == spec


def test_a_sheet_with_no_loops_writes_no_loops_section():
    """An unconverted sheet serializes exactly as it did before loops existed."""
    fs, line = _sheet()
    fs.add_instrument("FT", 101, on=line, at=0.5, offset=60)
    assert "loops" not in fs.to_dict()


def test_a_loop_entry_needs_both_halves_of_its_identity():
    from pandid import SpecError

    with pytest.raises(SpecError, match=r"loops\[0\] needs a 'number'"):
        Flowsheet.from_dict({"name": "T", "loops": [{"variable": "F"}]})
    with pytest.raises(SpecError, match=r"loops\[0\] needs a 'variable'"):
        Flowsheet.from_dict({"name": "T", "loops": [{"number": 303}]})


def test_a_duplicate_loop_in_a_spec_names_the_entry():
    from pandid import SpecError

    with pytest.raises(SpecError, match=r"loops\[1\]: loop F-303 is already declared"):
        Flowsheet.from_dict(
            {
                "name": "T",
                "loops": [{"variable": "F", "number": 303}, {"variable": "F", "number": "303"}],
            }
        )
