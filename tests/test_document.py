"""Test the cross-sheet findings of ``Document.validate()``."""

from typing import Any

import pytest

from _render_cases import SCENARIOS
from pandid import (
    Document,
    Feed,
    Flowsheet,
    Product,
    Reducer,
    Stream,
    Tank,
    TitleBlock,
    Unit,
    Valve,
    Vessel,
)


def _sheet(name: str, number: str, *units: Unit) -> Flowsheet:
    """Build a sheet that joins its units in a row, under a drawing number."""
    fs = Flowsheet(name)
    if number:
        fs.title_block = TitleBlock(drawing_number=number)
    for unit in units:
        fs.add(unit)
    for up, down in zip(units, units[1:]):
        fs.connect(up.port("outlet"), down.port("inlet"))
    return fs


def _line(flag: Feed | Product, size: str, service: str, sequence: str = "") -> Stream:
    """Set the line-number fields of the line at a flag and return it."""
    stream = flag.connection.stream
    assert stream is not None
    stream.size, stream.service = size, service
    if sequence:
        stream.sequence = sequence
    return stream


def _crude_set(
    b_feed: Feed | None = None, b_vessel: Unit | None = None
) -> tuple[Flowsheet, Flowsheet, Product, Feed]:
    """Build PFD-001 sending crude to PFD-002, both drawing V-101."""
    out = Product("Crude", reference="PFD-002")
    into = b_feed or Feed("Crude", reference="PFD-001")
    a = _sheet("Crude Unit", "PFD-001", Feed("Crude Oil"), Vessel("V-101"), out)
    b = _sheet("Residue Unit", "PFD-002", into, b_vessel or Vessel("V-101"), Product("Residue"))
    return a, b, out, into


def test_a_consistent_two_sheet_set_has_no_findings():
    """Check that matched connectors on one line, and one vessel on both sheets, pass."""
    a, b, out, into = _crude_set()
    _line(out, "6", "P", "1001")
    _line(into, "6", "P", "1001")
    assert Document([a, b]).validate() == []


def test_a_connector_partners_the_flag_carrying_its_line_number():
    """Check that flags labelled differently pair when their line numbers agree."""
    out = Product("To Residue Unit", reference="PFD-002")
    into = Feed("From Crude Unit", reference="PFD-001")
    a = _sheet("Crude Unit", "PFD-001", Feed("Crude Oil"), Vessel("V-101"), out)
    b = _sheet("Residue Unit", "PFD-002", into, Vessel("V-201"), Product("Residue"))
    _line(out, "6", "P", "1001")
    _line(into, "6", "P", "1001")
    assert Document([a, b]).validate() == []


def test_a_reference_outside_the_set_is_a_warning_after_the_errors():
    """Check that a drawing not in the set warns, and errors come first."""
    a, b, out, _ = _crude_set()
    out.reference = "PFD-009"
    issues = Document([a, b]).validate()
    assert [(i.severity, i.code) for i in issues] == [
        ("error", "connector-unmatched"),
        ("warning", "reference-not-in-set"),
    ]
    warning = issues[1].message
    assert "'Crude'" in warning and "PFD-001" in warning and "PFD-009" in warning
    assert "Document([" in warning and "reference=" in warning


def test_a_connector_with_no_partner_on_the_sheet_it_names_is_an_error():
    """Check that a referenced sheet without the flag pointing back is reported."""
    a, b, _, _ = _crude_set(b_feed=Feed("Crude"))
    (issue,) = Document([a, b]).validate()
    assert (issue.severity, issue.code) == ("error", "connector-unmatched")
    assert "PFD-001" in issue.message and "PFD-002" in issue.message
    assert "Feed('Crude', reference='PFD-001')" in issue.message


def test_matched_connectors_that_disagree_on_the_line_are_an_error():
    """Check that a line numbered differently on each sheet is reported."""
    a, b, out, into = _crude_set()
    _line(out, "6", "P")
    _line(into, "4", "P")
    (issue,) = Document([a, b]).validate()
    assert (issue.severity, issue.code) == ("error", "connector-line-mismatch")
    # Each sheet numbers its own sequence: the crude line is its second run on PFD-001.
    assert "line number '6-P-1002' on PFD-001 and '4-P-1001' on PFD-002" in issue.message
    assert "size '6' on PFD-001 and '4' on PFD-002" in issue.message
    assert "service" not in issue.message
    assert "connect() the same line number (name= or sequence=) and size (size=)" in issue.message


@pytest.mark.parametrize("size", ["4", "6"])
def test_a_connector_compares_the_line_through_a_valve_by_its_whole_run(size: str):
    """Check that fields stated before a valve reach the flag's line."""
    out, into = Product("Crude", reference="PFD-002"), Feed("Crude", reference="PFD-001")
    a = _sheet("Crude Unit", "PFD-001", Feed("Crude Oil"), Valve("HV-1"), out)
    b = _sheet("Residue Unit", "PFD-002", into, Product("Residue"))
    first = a.streams[0]
    first.size, first.service, first.sequence = "6", "P", "1001"
    _line(into, size, "P", "1001")

    issues = Document([a, b]).validate()

    assert [s.name for s in a.streams] == ["6-P-1001", "6-P-1001"]
    if size == "6":
        assert issues == []
    else:
        (issue,) = issues
        assert issue.code == "connector-line-mismatch"
        assert "line number '6-P-1001' on PFD-001 and '4-P-1001' on PFD-002" in issue.message
        assert "size '6' on PFD-001 and '4' on PFD-002" in issue.message


def test_a_connector_compares_the_size_stated_at_its_own_segment():
    """Check that a size changed past a reducer is the one compared at the flag."""
    a = _sheet("Crude Unit", "PFD-001")
    feed, reducer = a.add(Feed("Crude Oil")), a.add(Reducer("R-1"))
    out = a.add(Product("Crude", reference="PFD-002"))
    a.connect(feed.outlet, reducer.inlet, name="P-1001", size="6", service="P")
    a.connect(reducer.outlet, out.inlet, size="4")
    b = _sheet("Residue Unit", "PFD-002")
    into, residue = b.add(Feed("Crude", reference="PFD-001")), b.add(Product("Residue"))
    b.connect(into.outlet, residue.inlet, name="P-1001", size="6", service="P")

    (issue,) = Document([a, b]).validate()

    assert issue.code == "connector-line-mismatch"
    assert "size '4' on PFD-001 and '6' on PFD-002" in issue.message


def _run(name: str, number: str, units: list[Unit], legs: list[dict[str, Any]]) -> Flowsheet:
    """Build a sheet that joins its units in a row, one connect() per leg."""
    fs = _sheet(name, number, *units[:1])
    for unit in units[1:]:
        fs.add(unit)
    for (up, down), leg in zip(zip(units, units[1:]), legs):
        fs.connect(up.port("outlet"), down.port("inlet"), **leg)
    return fs


_P1001 = {"name": "P-1001", "service": "P"}


@pytest.mark.parametrize("far", ["4", "6"])
@pytest.mark.parametrize("leaving", [True, False], ids=["at-a-product-flag", "at-a-feed-flag"])
def test_a_connector_takes_the_size_stated_nearest_it(leaving: bool, far: str):
    """Check that a flag's unstated size is the one past its valve, short of the reducer."""
    if leaving:
        units: list[Unit] = [Feed("Crude Oil"), Reducer("R-1"), Valve("HV-1")]
        near = _run(
            "Crude Unit",
            "PFD-001",
            [*units, Product("Crude", reference="PFD-002")],
            [{**_P1001, "size": "6"}, {"size": "4"}, {}],
        )
        other = _run(
            "Residue Unit",
            "PFD-002",
            [Feed("Crude", reference="PFD-001"), Product("Residue")],
            [{**_P1001, "size": far}],
        )
        sheets = [near, other]
    else:
        units = [
            Feed("Crude", reference="PFD-001"),
            Valve("HV-1"),
            Reducer("R-1", large_end="outlet"),
        ]
        near = _run(
            "Residue Unit",
            "PFD-002",
            [*units, Product("Residue")],
            [_P1001, {"size": "4"}, {"size": "6"}],
        )
        other = _run(
            "Crude Unit",
            "PFD-001",
            [Feed("Crude Oil"), Product("Crude", reference="PFD-002")],
            [{**_P1001, "size": far}],
        )
        sheets = [other, near]

    issues = Document(sheets).validate()

    if far == "4":
        assert issues == []
    else:
        (issue,) = issues
        assert issue.code == "connector-line-mismatch"
        mine, theirs = ("4", "6") if leaving else ("6", "4")
        assert f"size {mine!r} on PFD-001 and {theirs!r} on PFD-002" in issue.message


@pytest.mark.parametrize("leaving", [True, False], ids=["at-a-product-flag", "at-a-feed-flag"])
def test_a_connector_takes_no_size_from_across_a_reducer(leaving: bool):
    """Check that a size stated only past a reducer is not compared at the flag."""
    if leaving:
        near = _run(
            "Crude Unit",
            "PFD-001",
            [Feed("Crude Oil"), Reducer("R-1"), Product("Crude", reference="PFD-002")],
            [{**_P1001, "size": "6"}, {}],
        )
        other = _run(
            "Residue Unit",
            "PFD-002",
            [Feed("Crude", reference="PFD-001"), Product("Residue")],
            [{**_P1001, "size": "4"}],
        )
    else:
        near = _run(
            "Residue Unit",
            "PFD-002",
            [
                Feed("Crude", reference="PFD-001"),
                Reducer("R-1", large_end="outlet"),
                Product("Residue"),
            ],
            [_P1001, {"size": "6"}],
        )
        other = _run(
            "Crude Unit",
            "PFD-001",
            [Feed("Crude Oil"), Product("Crude", reference="PFD-002")],
            [{**_P1001, "size": "4"}],
        )
    assert Document([near, other]).validate() == []


def test_one_tag_on_two_kinds_of_equipment_is_an_error():
    """Check that a tag naming a vessel on one sheet and a tank on another is reported."""
    a, b, _, _ = _crude_set(b_vessel=Tank("V-101"))
    (issue,) = Document([a, b]).validate()
    assert (issue.severity, issue.code) == ("error", "tag-reused")
    assert "Vessel('V-101') on PFD-001 and Tank('V-101') on PFD-002" in issue.message
    assert 'Tank("<new tag>")' in issue.message


def test_two_sheets_with_one_drawing_number_are_an_error():
    """Check that a drawing number filed twice is reported with the call that fixes it."""
    a = _sheet("Crude Unit", "PFD-001", Feed("Crude Oil"), Product("Crude"))
    b = _sheet("Residue Unit", "pfd-001", Feed("Crude"), Product("Residue"))
    (issue,) = Document([a, b]).validate()
    assert (issue.severity, issue.code) == ("error", "drawing-number-duplicate")
    assert "'Crude Unit'" in issue.message and "'Residue Unit'" in issue.message
    assert "fs.title_block.drawing_number = " in issue.message


@pytest.mark.parametrize(
    ("block", "call"),
    [
        (None, "fs.title_block = TitleBlock(drawing_number="),
        (TitleBlock(title="Crude Unit"), "fs.title_block.drawing_number = "),
    ],
    ids=["no-title-block", "blank-number"],
)
def test_an_unnumbered_sheet_in_a_crossing_is_an_error(block: TitleBlock | None, call: str):
    """Check that a sheet the far sheet cannot point back at is reported."""
    a = _sheet("Crude Unit", "", Feed("Crude Oil"), Product("Crude", reference="PFD-002"))
    a.title_block = block
    b = _sheet("Residue Unit", "PFD-002", Feed("Crude"), Product("Residue"))
    (issue,) = Document([a, b]).validate()
    assert (issue.severity, issue.code) == ("error", "drawing-number-missing")
    assert "'Crude Unit'" in issue.message and "PFD-002" in issue.message
    assert call in issue.message


def test_the_alumina_refinery_set_has_no_cross_sheet_error():
    """Check that the three alumina refinery sheets only warn about drawings outside the set."""
    sheets = [SCENARIOS[f"20_alumina_refinery_{n}"][0]() for n in (1, 2, 3)]
    issues = Document(sheets).validate()
    assert issues
    assert {(i.severity, i.code) for i in issues} == {("warning", "reference-not-in-set")}


def test_a_refused_validate_leaves_every_sheet_as_it_was():
    """Check that a sheet whose lines cannot be numbered leaves the earlier sheets unchanged."""
    a = _sheet("Crude Unit", "PFD-001", Feed("In"), Product("Out"))
    b = _sheet("Residue Unit", "PFD-002", Feed("In"), Product("Out"))
    (line_a,), (line_b,) = a.streams, b.streams
    for fs, line in ((a, line_a), (b, line_b)):
        line.size, line.service = "6", "P"
        fs.renumber_streams()
    line_a.sequence = "4711"
    b.line_numbering_scheme = "{spec}"
    with pytest.raises(ValueError, match="line_numbering_scheme"):
        Document([a, b]).validate()
    assert (line_a.name, line_b.name) == ("6-P-1001", "6-P-1001")


def test_a_document_holds_only_flowsheets():
    """Check that a sheet that is not a Flowsheet is refused."""
    sheets: list[Any] = ["PFD-001"]
    with pytest.raises(TypeError, match="Flowsheet"):
        Document(sheets)
