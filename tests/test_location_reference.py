"""ISO 15519-1:2010 Clause 9 location references, and the flag that carries one.

Clause 9 gives the grammar off-page connector text is composed in: the solidus
marks the sheet and the full stop the column, row or zone, and the parts are
presented in one order -- document, then sheet, then column, row or zone.

Table 2 tabulates the seven cases, which is what the first test reproduces
row for row.
"""

import json

import pytest

from pandid import Flowsheet, units as U
from pandid.document import location_reference


# --- Table 2, row for row -----------------------------------------------------


#: Every row of ISO 15519-1:2010 Table 2, *Application examples of the use of
#: document location references*, as ``(kwargs, reference, what it means)``.
TABLE_2 = [
    ({"document": "4334", "zone": "B3"}, "4334/.B3", "Zone B3 on a single-sheet diagram No. 4334"),
    (
        {"document": "7569", "sheet": "12", "zone": "B3"},
        "7569/12.B3",
        "Zone B3 on sheet 12 of multi-sheet diagram No. 7569",
    ),
    ({"sheet": "2"}, "/2", "Another sheet in the same document"),
    ({"sheet": "12", "zone": "B3"}, "/12.B3", "Zone B3 on sheet 12"),
    ({"zone": "B"}, "/.B", "Row B on the same sheet"),
    ({"zone": "3"}, "/.3", "Column 3 on the same sheet"),
    ({"zone": "B3"}, "/.B3", "Zone B3 on the same sheet"),
]


@pytest.mark.parametrize("kwargs,expected,meaning", TABLE_2, ids=[row[2] for row in TABLE_2])
def test_table_2_is_reproduced_row_for_row(kwargs, expected, meaning):
    assert location_reference(**kwargs) == expected, meaning


def test_the_solidus_survives_a_document_with_no_sheet_number():
    """Table 2's first row keeps the sign and drops only the number.

    A single-sheet diagram has no sheet to name, and 4334.B3 -- the obvious
    abbreviation -- would read as a zone on the document rather than on its one
    sheet, so Clause 9's sequence keeps the field.
    """
    assert location_reference("4334", zone="B3") == "4334/.B3"
    assert location_reference("4334", sheet="", zone="B3") == "4334/.B3"


def test_a_document_alone_is_the_document():
    """What every reference sheet in professional_examples/ actually carries.

    P&ID-301's two flags read "Fermentation Broth / P&ID-201" and "Azeotropic
    Ethanol / PFD-302"; PFD-301's four name PFD-201, PFD-302, PCD-302 and
    PFD-501. Not one of them names a sheet or a zone, so the helper has to leave
    a bare document exactly as it found it or it is no use for the common case.
    """
    for drawing in ("PFD-302", "P&ID-201", "PCD-302", "PFD-501"):
        assert location_reference(drawing) == drawing


def test_the_parts_stay_in_clause_9_order():
    assert location_reference("7569", "12") == "7569/12"
    assert location_reference("7569", "12", "B3").index("7569") == 0
    assert location_reference("7569", "12", "B3").index("/12") < location_reference(
        "7569", "12", "B3"
    ).index(".B3")


# --- what the grammar refuses -------------------------------------------------


@pytest.mark.parametrize("zone", ["3B", "B3C", "3B3", "B-3"])
def test_a_zone_spelled_back_to_front_is_refused(zone):
    """5.1.2 designates columns with numbers and rows with letters. Table 2
    writes the zone as its row then its column, so B3 is a zone and 3B is a
    reader sent to the wrong place."""
    with pytest.raises(ValueError, match="not a zone, a row or a column"):
        location_reference(zone=zone)


@pytest.mark.parametrize("part", ["document", "sheet", "zone"])
def test_a_reserved_sign_inside_a_part_is_refused(part):
    """Clause 9 spends '/' and '.' on the structure, so a part carrying one
    would be read as two parts by whoever reads the finished string."""
    for sign in ("/", "."):
        with pytest.raises(ValueError, match="reserves"):
            location_reference(**{part: f"A{sign}B"})


def test_a_reference_to_nothing_is_refused():
    with pytest.raises(ValueError, match="names none of the three"):
        location_reference()


def test_surrounding_space_is_trimmed_rather_than_drawn():
    assert location_reference("  PFD-302  ") == "PFD-302"


# --- and on a flag ------------------------------------------------------------


def _sheet(reference):
    fs = Flowsheet("offpage")
    feed = fs.add(U.Feed("Fermentation Broth", reference=reference))
    pump = fs.add(U.Pump("P-301"))
    prod = fs.add(U.Product("Azeotropic Ethanol", reference=location_reference("PFD-302")))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, prod.inlet)
    return fs, feed


def test_a_composed_reference_is_drawn_on_the_flags_second_line():
    fs, _ = _sheet(location_reference("P&ID-201", "12", "B3"))
    svg = fs.to_svg()
    # html-escaped, since the ampersand in a P&ID number is drawn as text
    assert "P&amp;ID-201/12.B3" in svg


def test_a_composed_reference_round_trips_through_the_spec():
    """It is a plain string, so ``reference:`` needs no new schema -- but the
    drawing is what proves nothing was dropped on the way through."""
    fs, _ = _sheet(location_reference("P&ID-201", "12", "B3"))
    spec = fs.to_dict()
    assert json.loads(json.dumps(spec)) == spec
    assert spec["units"][0]["reference"] == "P&ID-201/12.B3"

    rebuilt = Flowsheet.from_dict(spec)
    assert rebuilt.to_dict() == spec
    assert rebuilt.to_svg() == fs.to_svg()


def test_the_flag_grows_to_hold_a_longer_reference():
    """The flag is sized to the wider of its two lines, so a reference that
    names a sheet and a zone must not overrun the pennant it is drawn in."""
    from pandid.portgeom import resolve_size

    short = U.Feed("Feed", reference=location_reference("PFD-302"))
    long = U.Feed("Feed", reference=location_reference("PFD-302", "12", "B3"))
    assert len(short.reference) < len(long.reference)  # the label is the shorter line
    assert resolve_size(long)[0] > resolve_size(short)[0]
