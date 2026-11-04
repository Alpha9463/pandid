"""Test how line numbers are formed, sequenced, drawn and written to a spec."""

import warnings
from collections.abc import Callable
from typing import Any

import pytest

from pandid import Flowsheet, units as U


def _skid(**line):
    """Build a feed -> hand valve -> control valve -> product, line-numbered at the feed."""
    fs = Flowsheet("skid")
    feed = fs.add(U.Feed("F"))
    hv = fs.add(U.Valve("HV-101"))
    fv = fs.add(U.Valve("FV-101", variant="control"))
    prod = fs.add(U.Product("P"))
    streams = [
        fs.connect(feed.outlet, hv.inlet, **line),
        fs.connect(hv.outlet, fv.inlet),
        fs.connect(fv.outlet, prod.inlet),
    ]
    return fs, fv, streams


# --- forming the number -------------------------------------------------------


def test_components_replace_the_stream_number():
    fs, _, (s1, _, _) = _skid(size='6"', service="P", spec="A1A")
    assert s1.name == '6"-P-1001-A1A'
    assert fs.streams[0].has_line_number


def test_a_stream_with_no_components_is_numbered_as_before():
    fs, _, streams = _skid()
    assert [s.name for s in streams] == ["S1", "S1", "S1"]
    assert not streams[0].has_line_number


def test_an_unset_component_drops_out_with_its_separator():
    """Check that an unset component drops out with its separator."""
    _, _, (s1, _, _) = _skid(size='6"', service="P")
    assert s1.name == '6"-P-1001'


def test_an_unset_first_component_drops_its_separator_too():
    """Check that an unset first component drops its separator too."""
    _, _, (s1, _, _) = _skid(service="AE", spec="SS")
    assert s1.name == "AE-1001-SS"


@pytest.mark.parametrize(
    "sheet, components, name",
    [
        (
            {"line_numbering_scheme": "{size}-{schedule}-{service}-{sequence}"},
            {"service": "P"},
            "P-1001",
        ),
        (
            {"line_numbering_scheme": "{size}-{service}-{sequence}-{spec}-{insulation}"},
            {"size": '2"', "service": "S", "spec": "B1A", "insulation": "H"},
            '2"-S-1001-B1A-H',
        ),
        (
            {
                "line_numbering_scheme": "{service}-{sequence}-{size}-{schedule}-{spec}",
                "line_number_start": 301,
            },
            {"service": "FB", "size": 200, "schedule": 160, "spec": "SS"},
            "FB-301-200-160-SS",
        ),
        (
            {"line_numbering_scheme": "{size}-{schedule}-{service}-{sequence}"},
            {"size": '6"', "schedule": "XS", "service": "P"},
            '6"-XS-P-1001',
        ),
        ({"line_numbering_scheme": "{schedule}-{spec}"}, {"schedule": 80}, "80"),
        (
            {"line_numbering_scheme": "{size}-{schedule}-{service}-{sequence}-{spec}"},
            {"size": '6"', "service": "P", "spec": "A1A"},
            '6"-P-1001-A1A',
        ),
        (
            {"line_numbering_scheme": lambda s: f"{s.service}{s.sequence}/{s.size}"},
            {"size": "150", "service": "P"},
            "P1001/150",
        ),
        (
            {"line_numbering_scheme": "{service}-{sequence:0>6}", "line_number_start": 1},
            {"service": "P"},
            "P-000001",
        ),
        ({}, {"size": 150, "service": "P", "spec": "A1A"}, "150-P-1001-A1A"),
        ({"line_number_start": 100}, {"size": '4"', "service": "P", "spec": "A1A"}, '4"-P-100-A1A'),
    ],
    ids=[
        "unset-leading-components",
        "insulation",
        "schedule",
        "schedule-as-a-word",
        "schedule-alone",
        "unset-schedule",
        "callable",
        "format-spec",
        "numeric-components",
        "line-number-start",
    ],
)
def test_a_scheme_writes_the_components_it_names(
    sheet: dict[str, Any], components: dict[str, Any], name: str
):
    """Check that the scheme writes the line number from the stream's components.

    Parameters
    ----------
    sheet : dict[str, Any]
        Line-numbering keywords for the flowsheet.
    components : dict[str, Any]
        Line-number components given to ``connect``.
    name : str
        Expected line number.
    """
    fs = Flowsheet("t", **sheet)
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet, **components)
    assert s.has_line_number
    assert s.name == name


def test_the_default_scheme_does_not_name_the_schedule():
    """Check that the default scheme does not name the schedule."""
    from pandid.flowsheet import DEFAULT_LINE_NUMBERING_SCHEME

    assert DEFAULT_LINE_NUMBERING_SCHEME == "{size}-{service}-{sequence}-{spec}"


# --- the sequence -------------------------------------------------------------


def test_auto_numbering_fills_the_sequence():
    fs, fv, (s1, s2, s3) = _skid(size='6"', service="P", spec="A1A")
    fv.new_line_number = True  # two lines now, so two sequences
    assert (s1.sequence, s2.sequence, s3.sequence) == ("1001", "1001", "1002")


def test_a_sequence_the_author_set_is_never_overwritten():
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-101"))
    prod = fs.add(U.Product("P"))
    first = fs.connect(feed.outlet, hx.tube_in, size='6"', service="P", sequence="2740", spec="A1A")
    second = fs.connect(hx.tube_out, prod.inlet, size='6"', service="P", spec="A1A")
    fs.to_svg()
    assert first.name == '6"-P-2740-A1A'
    assert second.name == '6"-P-1002-A1A'  # the automatic sequence ran on regardless


def test_a_sequence_set_after_connecting_is_kept():
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet, size='6"', service="P", spec="A1A")
    s.sequence = "2740"
    fs.renumber_streams()
    assert s.name == '6"-P-2740-A1A'


# --- inline groups and spec breaks --------------------------------------------


def test_one_line_number_runs_through_an_inline_valve():
    _, _, (s1, s2, _) = _skid(size='6"', service="P", spec="A1A")
    assert s1.name == s2.name == '6"-P-1001-A1A'


def test_a_new_line_number_valve_breaks_the_line_number():
    """Check that a ``new_line_number`` valve breaks the line number."""
    fs, fv, (s1, s2, s3) = _skid(size='6"', service="P", spec="A1A")
    fv.new_line_number = True
    s3.size, s3.service, s3.spec = '6"', "P", "D1B"
    fs.renumber_streams()
    assert s1.name == s2.name == '6"-P-1001-A1A'
    assert s3.name == '6"-P-1002-D1B'


def test_components_on_one_segment_name_the_whole_group():
    """Check that components on one segment name the whole group."""
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    hv = fs.add(U.Valve("HV-101"))
    prod = fs.add(U.Product("P"))
    s1 = fs.connect(feed.outlet, hv.inlet)
    s2 = fs.connect(hv.outlet, prod.inlet, size='6"', service="P", spec="A1A")
    assert s1.name == s2.name == '6"-P-1001-A1A'


def test_an_explicit_name_is_never_reformatted():
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet, name="100-BFW-01", size='6"', service="P", spec="A1A")
    fs.to_svg()
    assert s.name == "100-BFW-01"


def test_a_line_number_does_not_consume_a_stream_number():
    """Check that a line number does not consume a stream number."""
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-101"))
    prod = fs.add(U.Product("P"))
    first = fs.connect(feed.outlet, hx.tube_in, size='6"', service="P", spec="A1A")
    second = fs.connect(hx.tube_out, prod.inlet)
    assert (first.name, second.name) == ('6"-P-1001-A1A', "S2")


# --- rendering ----------------------------------------------------------------


def test_the_line_number_connect_returns_is_the_one_drawn():
    _, _, (s1, _, _) = _skid(size='6"', service="P", spec="A1A")
    fs = s1.source.owner.flowsheet
    held = s1.name
    svg = fs.to_svg()
    fs.to_svg()  # and again: renumbering is idempotent
    assert s1.name == held
    assert ">6&quot;-P-1001-A1A<" in svg


def test_the_stream_table_heads_its_columns_with_the_line_number():
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet, size='6"', service="P", spec="A1A")
    s.properties = {"Temperature": "25 C"}
    svg = fs.to_svg(show_stream_table=True)
    assert ">Line Number<" in svg
    assert ">Stream Number<" not in svg
    assert ">6&quot;-P-1001-A1A<" in svg


def test_a_mixed_sheet_keeps_the_stream_number_heading():
    """Check that a mixed sheet keeps the stream number heading."""
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-101"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, hx.tube_in, size='6"', service="P", spec="A1A")
    fs.connect(hx.tube_out, prod.inlet)
    for s in fs.streams:
        s.properties = {"Temperature": "25 C"}
    svg = fs.to_svg(show_stream_table=True)
    assert ">Stream Number<" in svg
    assert ">Line Number<" not in svg


# --- misuse -------------------------------------------------------------------


def test_a_scheme_naming_something_that_is_not_a_component_says_so():
    fs = Flowsheet("t", line_numbering_scheme="{size}-{fluid}")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    with pytest.raises(ValueError, match="'fluid'.*not a line-number component") as raised:
        fs.connect(feed.outlet, prod.inlet, size='6"')
    # The message lists the components that would have worked.
    assert "'schedule'" in str(raised.value)


def test_components_the_scheme_never_uses_are_not_silently_dropped():
    fs = Flowsheet("t", line_numbering_scheme="{size}-{service}")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    with pytest.raises(ValueError, match="line number would be empty"):
        fs.connect(feed.outlet, prod.inlet, spec="A1A")


def test_line_components_is_deprecated(same_file: Callable[[str], str]) -> None:
    """Check that ``line_components()`` warns at the caller, is reported, and still answers."""
    fs = Flowsheet(
        "t", line_numbering_scheme=lambda s: "-".join(filter(None, s.line_components().values()))
    )
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    with pytest.warns(DeprecationWarning, match=r"line_components\(\)") as caught:
        s = fs.connect(feed.outlet, prod.inlet, size='6"', service="P")
    assert s.name == '6"-P-1001'
    assert [same_file(w.filename) for w in caught] == [same_file(__file__)]
    found = [i.message for i in fs.validate() if i.code == "deprecated"]
    assert found == [str(caught[0].message)]


def test_a_format_string_scheme_raises_no_deprecation() -> None:
    """Check that numbering a line by a format string does not call ``line_components()``."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        _, _, (s1, _, _) = _skid(size='6"', service="P")
    assert s1.name == '6"-P-1001'


# --- the spec format ----------------------------------------------------------


def test_line_numbers_round_trip_through_a_spec():
    spec = {
        "name": "t",
        "line_number_start": 2000,
        "units": [
            {"kind": "Feed", "name": "F"},
            {"kind": "Valve", "name": "FV-101", "new_line_number": True},
            {"kind": "Product", "name": "P"},
        ],
        "streams": [
            {
                "from": ["F", "outlet"],
                "to": ["FV-101", "inlet"],
                "size": '6"',
                "service": "P",
                "spec": "A1A",
                "insulation": "H",
            },
            {
                "from": ["FV-101", "outlet"],
                "to": ["P", "inlet"],
                "size": '6"',
                "service": "P",
                "sequence": "2740",
                "spec": "D1B",
            },
        ],
    }
    fs = Flowsheet.from_dict(spec)
    assert [s.name for s in fs.streams] == ['6"-P-2000-A1A', '6"-P-2740-D1B']
    assert fs.to_dict() == spec


def test_a_schedule_round_trips_through_a_spec():
    """Check that a schedule round trips through a spec."""
    spec = {
        "name": "t",
        "line_numbering_scheme": "{service}-{sequence}-{size}-{schedule}-{spec}",
        "line_number_start": 301,
        "units": [
            {"kind": "Feed", "name": "Fermentation Broth"},
            {"kind": "Product", "name": "To T-301"},
        ],
        "streams": [
            {
                "from": ["Fermentation Broth", "outlet"],
                "to": ["To T-301", "inlet"],
                "size": 200,
                "schedule": 160,
                "service": "FB",
                "spec": "SS",
            },
        ],
    }
    fs = Flowsheet.from_dict(spec)
    assert [s.name for s in fs.streams] == ["FB-301-200-160-SS"]
    assert fs.streams[0].schedule == 160
    assert fs.to_dict() == spec


def test_a_spec_omits_the_sequence_auto_numbering_assigned():
    """Check that a spec omits the sequence auto-numbering assigned."""
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, prod.inlet, size='6"', service="P", spec="A1A")
    assert "sequence" not in fs.to_dict()["streams"][0]


def test_a_custom_scheme_round_trips():
    fs = Flowsheet("t", line_numbering_scheme="{service}/{sequence}")
    fs.add(U.Feed("F"))
    assert fs.to_dict()["line_numbering_scheme"] == "{service}/{sequence}"
    assert Flowsheet.from_dict(fs.to_dict()).line_numbering_scheme == "{service}/{sequence}"


def test_the_defaults_stay_out_of_the_spec():
    fs = Flowsheet("t")
    fs.add(U.Feed("F"))
    spec = fs.to_dict()
    assert "line_numbering_scheme" not in spec
    assert "line_number_start" not in spec


def test_a_callable_scheme_cannot_be_written_to_a_spec():
    from pandid.spec import SpecError

    fs = Flowsheet("t", line_numbering_scheme=lambda s: str(s.sequence))
    fs.add(U.Feed("F"))
    with pytest.raises(SpecError, match="callable line_numbering_scheme"):
        fs.to_dict()


def test_a_component_that_is_neither_text_nor_a_number_is_rejected():
    from pandid.spec import SpecError

    spec = {
        "name": "t",
        "units": [{"kind": "Feed", "name": "F"}, {"kind": "Product", "name": "P"}],
        "streams": [{"from": ["F", "outlet"], "to": ["P", "inlet"], "size": ["6", "in"]}],
    }
    with pytest.raises(SpecError, match=r"streams\[0\].size must be text or a number"):
        Flowsheet.from_dict(spec)
