"""Line numbers: the identifier that ties a line on the sheet to the line list.

A line number is a stream number with the rest of the identity filled in, so it
is assigned by the same machinery and obeys the same rules — one number through
an inline fitting, a break where a significant unit marks the spec break, and
never a word about a stream the caller named itself. A stream with no components
set is numbered exactly as it always was, which is what protects every sheet
drawn before line numbers existed.
"""

import pytest

from pandid import Flowsheet, units as U


def _skid(**line):
    """Feed -> hand valve -> control valve -> product, line-numbered at the feed."""
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
    """A line drawn before its spec is issued reads 6"-P-1001, not 6"-P-1001-."""
    _, _, (s1, _, _) = _skid(size='6"', service="P")
    assert s1.name == '6"-P-1001'


def test_a_scheme_can_name_the_insulation():
    fs = Flowsheet("t", line_numbering_scheme="{size}-{service}-{sequence}-{spec}-{insulation}")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet, size='2"', service="S", spec="B1A", insulation="H")
    assert s.name == '2"-S-1001-B1A-H'


def test_a_callable_scheme_takes_the_stream():
    fs = Flowsheet("t", line_numbering_scheme=lambda s: f"{s.service}{s.sequence}/{s.size}")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet, size="150", service="P")
    assert s.name == "P1001/150"


def test_a_format_spec_pads_the_sequence():
    fs = Flowsheet("t", line_numbering_scheme="{service}-{sequence:0>6}", line_number_start=1)
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet, service="P")
    assert s.name == "P-000001"


def test_components_may_be_numbers():
    """A metric size read out of a spreadsheet arrives as an int, not as text."""
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet, size=150, service="P", spec="A1A")
    assert s.name == "150-P-1001-A1A"


# --- the sequence -------------------------------------------------------------


def test_auto_numbering_fills_the_sequence():
    fs, fv, (s1, s2, s3) = _skid(size='6"', service="P", spec="A1A")
    fv.significant = True  # two lines now, so two sequences
    assert (s1.sequence, s2.sequence, s3.sequence) == ("1001", "1001", "1002")


def test_line_number_start_moves_the_sequence():
    fs = Flowsheet("t", line_number_start=100)
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet, size='4"', service="P", spec="A1A")
    assert s.name == '4"-P-100-A1A'


def test_a_sequence_the_author_set_is_never_overwritten():
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-101"))
    prod = fs.add(U.Product("P"))
    first = fs.connect(feed.outlet, hx.cold_in, size='6"', service="P", sequence="2740", spec="A1A")
    second = fs.connect(hx.cold_out, prod.inlet, size='6"', service="P", spec="A1A")
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


def test_a_significant_valve_breaks_the_line_number():
    """A spec break is exactly what `significant` marks, so it breaks the number."""
    fs, fv, (s1, s2, s3) = _skid(size='6"', service="P", spec="A1A")
    fv.significant = True
    s3.size, s3.service, s3.spec = '6"', "P", "D1B"
    fs.renumber_streams()
    assert s1.name == s2.name == '6"-P-1001-A1A'
    assert s3.name == '6"-P-1002-D1B'


def test_components_on_one_segment_name_the_whole_group():
    """Same rule as an explicit name: the group takes it from whichever segment
    carries it, so a downstream segment need not repeat the identity."""
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
    """One sequence covers both, so a line number and a stream number on the
    same sheet can never collide."""
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-101"))
    prod = fs.add(U.Product("P"))
    first = fs.connect(feed.outlet, hx.cold_in, size='6"', service="P", spec="A1A")
    second = fs.connect(hx.cold_out, prod.inlet)
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
    """The corner cell has to be true of every column under it."""
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-101"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, hx.cold_in, size='6"', service="P", spec="A1A")
    fs.connect(hx.cold_out, prod.inlet)
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
    with pytest.raises(ValueError, match="'fluid'.*not a line-number component"):
        fs.connect(feed.outlet, prod.inlet, size='6"')


def test_components_the_scheme_never_uses_are_not_silently_dropped():
    fs = Flowsheet("t", line_numbering_scheme="{size}-{service}")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    with pytest.raises(ValueError, match="line number would be empty"):
        fs.connect(feed.outlet, prod.inlet, spec="A1A")


# --- the spec format ----------------------------------------------------------


def test_line_numbers_round_trip_through_a_spec():
    spec = {
        "name": "t",
        "line_number_start": 2000,
        "units": [
            {"kind": "Feed", "name": "F"},
            {"kind": "Valve", "name": "FV-101", "significant": True},
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


def test_a_spec_omits_the_sequence_auto_numbering_assigned():
    """A computed number is a result, not intent: writing it would pin a number
    the engine re-derives from the topology."""
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
