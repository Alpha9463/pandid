"""Check that stated values survive the spec round trip or are refused loudly."""

from __future__ import annotations

import numbers
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from pandid import Flowsheet, spec, units as U
from pandid.document import Annotation, TableBox
from pandid.spec import SpecError

NUMBER_STARTS = ("stream_number_start", "line_number_start", "loop_number_start")


@pytest.mark.parametrize("name", NUMBER_STARTS)
@pytest.mark.parametrize(
    "value",
    [1.0, 1500.5, Decimal(1), True, "1"],
    ids=["whole float", "fraction", "Decimal", "bool", "text"],
)
def test_a_number_start_refuses_a_non_integer(name, value):
    """Check that construction and assignment both refuse a non-integer start."""
    with pytest.raises(TypeError, match=name):
        Flowsheet("refused", **{name: value})
    fs = Flowsheet("refused")
    with pytest.raises(TypeError, match=name):
        setattr(fs, name, value)


@pytest.mark.parametrize("name", NUMBER_STARTS)
def test_a_number_start_stores_any_integer_as_an_int(name):
    """Check that an integer subclass is accepted and stored as a plain int."""

    class Count(int):
        """An integer type that is not ``int`` itself."""

    kwargs: dict[str, Any] = {name: Count(301)}
    fs = Flowsheet("integral", **kwargs)
    assert getattr(fs, name) == 301
    assert type(getattr(fs, name)) is int


def test_a_numpy_integer_number_start_is_accepted():
    """Check that a numpy integer, common in data-driven sheets, is accepted."""
    numpy = pytest.importorskip("numpy")
    fs = Flowsheet("numpy", stream_number_start=numpy.int64(90))
    assert fs.stream_number_start == 90
    assert type(fs.stream_number_start) is int


@pytest.mark.parametrize("box", [Annotation, TableBox])
@pytest.mark.parametrize("title", [0, False, None])
def test_a_falsy_annotation_title_is_written_and_refused_on_reading(box, title):
    """Check that a stated falsy title is kept, so reading it back fails loudly."""
    fs = Flowsheet("titled")
    fs.annotations.append(box(title=title, rows=[["a"]]))
    spec = fs.to_dict()
    assert spec["annotations"][0]["title"] is title
    with pytest.raises(SpecError, match=r"annotations\[0\]\.title"):
        Flowsheet.from_dict(spec)


@pytest.mark.parametrize("box", [Annotation, TableBox])
def test_a_default_annotation_title_writes_no_key(box):
    """Check that an untitled box round-trips without a title key."""
    fs = Flowsheet("untitled")
    fs.annotations.append(box(rows=[["a"]]))
    spec = fs.to_dict()
    assert "title" not in spec["annotations"][0]
    assert Flowsheet.from_dict(spec).annotations[0].title == ""


def _sheet(real: Any, whole: Any) -> Flowsheet:
    """Return a sheet whose numeric fields are all built from two values.

    Parameters
    ----------
    real : Any
        Real number used for sizes, positions and displayed values.
    whole : Any
        Integer used for counts, ranks and stages.

    Returns
    -------
    Flowsheet
        Sheet with sizes, a pin, a column, a line number, a property and
        an annotation.
    """
    fs = Flowsheet("numbers")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-1", width=real * 70, height=real * 45))
    column = fs.add(U.Column("T-1", internals="tray", trays=whole * 8, feed_stages=[whole * 3]))
    product = fs.add(U.Product("PR"))
    fs.connect(feed.outlet, pump.suction)
    run = fs.connect(pump.discharge, column.feed)
    fs.connect(column.bottoms, product.inlet)
    pump.pin(x=real * 300, y=real * 200)
    run.properties = {"Flow (kg/h)": real * 5000}
    run.size, run.service, run.spec = whole * 150, "P", "A"
    fs.annotations.append(Annotation(title="N", rows=["a"], margin=real * 5, font_size=real * 11))
    return fs


def test_a_real_number_that_is_not_a_float_round_trips():
    """Check that a Fraction, a numbers.Real but not a float, reads back and draws the same."""
    fs = _sheet(Fraction(1), 1)
    assert Flowsheet.from_dict(fs.to_dict()).to_svg() == fs.to_svg()


def test_numpy_numbers_round_trip():
    """Check that numpy scalars, as read from pandas, read back and draw the same."""
    numpy = pytest.importorskip("numpy")
    fs = _sheet(numpy.float64(1), numpy.int64(1))
    assert Flowsheet.from_dict(fs.to_dict()).to_svg() == fs.to_svg()


def test_any_integer_type_is_a_whole_number():
    """Check that the reader takes any numbers.Integral and returns it unchanged."""

    class Tally:
        """A stand-in integer type that is not ``int``."""

    numbers.Integral.register(Tally)
    tally = Tally()
    assert spec._integer(tally, "x") is tally
    for refused in (True, 1.0, Fraction(1), Decimal(1), "1"):
        with pytest.raises(SpecError, match="whole number"):
            spec._integer(refused, "x")


def test_a_decimal_reads_back_where_it_is_only_displayed():
    """Check that a Decimal line-number component and property round-trip."""
    fs = _sheet(1, 1)
    run = fs.streams[1]
    # Typed Any: the annotations say str | float, but a Decimal draws.
    size: Any = Decimal("150")
    flow: Any = Decimal("5000.5")
    run.size = size
    run.properties = {"Flow (kg/h)": flow}
    back = Flowsheet.from_dict(fs.to_dict())
    assert back.streams[1].size == Decimal("150")
    assert back.streams[1].properties["Flow (kg/h)"] == Decimal("5000.5")
    assert back.to_svg() == fs.to_svg()


def test_a_decimal_geometry_value_is_refused_on_reading():
    """Check that a Decimal size is refused by name, since layout cannot use one."""
    data = _sheet(1, 1).to_dict()
    data["units"][1]["width"] = Decimal(70)
    with pytest.raises(SpecError, match="width must be a number"):
        Flowsheet.from_dict(data)


def _flagged() -> tuple[Flowsheet, Any, Any]:
    """Return a two-flag sheet with a tabulated stream.

    Returns
    -------
    tuple
        The sheet, its feed and its stream.
    """
    fs = Flowsheet("flags")
    feed = fs.add(U.Feed("F"))
    run = fs.connect(feed.outlet, fs.add(U.Product("PR")).inlet)
    run.properties = {"Flow (kg/h)": 1}
    return fs, feed, run


@pytest.mark.parametrize("name, value", [("color", True), ("dasharray", 4)])
def test_a_stream_style_must_be_text(name, value):
    """Check that a non-text colour or dash pattern is refused, not drawn wrongly."""
    _fs, _feed, run = _flagged()
    with pytest.raises(TypeError, match=f"{name}=.* must be text"):
        setattr(run, name, value)


def test_a_numeric_flag_reference_is_drawn_as_text():
    """Check that reference=100 draws "100" in both backends instead of crashing."""
    fs, feed, _run = _flagged()
    feed.reference = 100
    assert ">100<" in fs.to_svg()
    assert "100" in fs.to_drawio()


@pytest.mark.parametrize("name", ["sheet_drawing_number", "sheet_subtitle"])
def test_a_numeric_table_sheet_field_is_drawn_as_text(name):
    """Check that a numeric table-sheet number or subtitle draws as text."""
    fs, _feed, _run = _flagged()
    setattr(fs.stream_table, name, 100)
    assert "100" in fs.to_svg(show_stream_table="sheet")
    assert "100" in fs.to_drawio(show_stream_table="sheet")


DOORS = {
    "Unit(width=)": lambda v: U.Pump("P-1", width=v),
    "unit.height =": lambda v: setattr(U.Pump("P-1"), "height", v),
    "block.width =": lambda v: setattr(U.Block("B", inputs=1), "width", v),
    "pin(x=)": lambda v: U.Pump("P-1").pin(x=v),
    "via()": lambda v: _flagged()[2].via([(v, 0)]),
    "Annotation(margin=)": lambda v: Annotation(rows=["a"], margin=v),
    "annotation.position =": lambda v: setattr(Annotation(rows=["a"]), "position", (v, 0)),
    "TableBox(font_size=)": lambda v: TableBox(rows=[["a"]], font_size=v),
}


@pytest.mark.parametrize("door", DOORS, ids=list(DOORS))
def test_a_decimal_is_refused_where_layout_computes_with_it(door):
    """Check that a Decimal geometry value is refused at once, naming the fix."""
    with pytest.raises(TypeError, match=r"must be a number.*float\(value\)"):
        DOORS[door](Decimal(10))


@pytest.mark.parametrize("door", DOORS, ids=list(DOORS))
def test_a_real_number_is_still_accepted_where_layout_computes_with_it(door):
    """Check that the same doors still take an int, a float and a Fraction."""
    for value in (10, 10.5, Fraction(10)):
        DOORS[door](value)


def test_a_grid_rank_must_be_a_whole_number():
    """Check that pin col and row refuse a float or bool and take any integer."""
    pump = U.Pump("P-1")
    refused: tuple[Any, ...] = (1.0, True)
    for value in refused:
        with pytest.raises(TypeError, match="whole number"):
            pump.pin(col=value)
    pump.pin(col=2, row=3)
    pin = pump.pin_
    assert pin is not None and (pin.col, pin.row) == (2, 3)
