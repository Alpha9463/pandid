"""Check that stated values survive the spec writer or are refused loudly."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from pandid import Flowsheet
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
