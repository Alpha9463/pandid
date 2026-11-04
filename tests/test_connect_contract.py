"""Check that ``connect()`` draws the kind the author states and a refused call changes nothing."""

import pickle

import pytest

from pandid import Flowsheet, units as U


# --- a stated kind is the kind that is drawn ---------------------------------


def _duty_sheet() -> tuple[Flowsheet, U.Cooler, U.Heater]:
    """Two utility nozzles facing each other, and nothing else on the sheet."""
    fs = Flowsheet("promotion")
    cooler = fs.add(U.Cooler("C-1"))  # cooler.utility_out is an outlet energy port
    heater = fs.add(U.Heater("H-1"))  # heater.utility_in is an inlet energy port
    return fs, cooler, heater


def test_a_stated_energy_kind_survives_two_process_nozzles():
    """Check that a stated energy kind survives two process nozzles."""
    fs = Flowsheet("symmetry")
    pump = fs.add(U.Pump("P-1"))
    vessel = fs.add(U.Vessel("V-1"))
    stream = fs.connect(pump.discharge, vessel.inlet, kind="energy")
    assert stream.kind == "energy"


def test_a_stated_material_duty_takes_a_process_number():
    """Check that a duty stated as material is numbered with the process runs."""
    fs = Flowsheet("numbering")
    feed = fs.add(U.Feed("F"))
    cooler = fs.add(U.Cooler("C-1"))
    heater = fs.add(U.Heater("H-1"))
    product = fs.add(U.Product("P"))
    duty = fs.connect(cooler.utility_out, heater.utility_in, kind="material")
    first = fs.connect(feed.outlet, heater.inlet)
    last = fs.connect(heater.outlet, product.inlet)
    # S1 because it was drawn first; an energy line is numbered after the runs.
    assert (duty.name, first.name, last.name) == ("S1", "S2", "S3")


def test_a_stated_material_duty_survives_a_spec_round_trip():
    """Check that a duty stated as material reads back as material."""
    fs, cooler, heater = _duty_sheet()
    fs.connect(cooler.utility_out, heater.utility_in, kind="material")
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert [s.kind for s in rebuilt.streams] == ["material"]


def test_an_inferred_duty_still_round_trips_without_saying_kind():
    """Check that an inferred duty writes no kind and reads back as energy."""
    fs, cooler, heater = _duty_sheet()
    fs.connect(cooler.utility_out, heater.utility_in)
    written = fs.to_dict()
    assert "kind" not in written["streams"][0]
    assert [s.kind for s in Flowsheet.from_dict(written).streams] == ["energy"]


# --- a refused call changes nothing ------------------------------------------


def test_the_state_check_can_see_a_change():
    """Check that the pickled sheet changes when a line is added."""
    fs = Flowsheet("meta")
    feed = fs.add(U.Feed("F"))
    product = fs.add(U.Product("P"))
    before = pickle.dumps(fs)
    fs.connect(feed.outlet, product.inlet)
    assert pickle.dumps(fs) != before


def test_the_state_check_can_see_a_renumbering():
    """Check that the pickled sheet changes when the sheet is renumbered."""
    fs = Flowsheet("meta")
    feed = fs.add(U.Feed("F"))
    product = fs.add(U.Product("P"))
    fs.connect(feed.outlet, product.inlet)
    before = pickle.dumps(fs)
    fs.stream_number_start = 90
    fs.renumber_streams()
    assert pickle.dumps(fs) != before


def test_a_rejected_line_number_leaves_the_sheet_alone():
    """Check that a refused line number leaves the sheet unchanged and the corrected call works."""
    fs = Flowsheet("a", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("Feed"))
    product = fs.add(U.Product("Product"))
    before = pickle.dumps(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(feed.outlet, product.inlet, service="P")

    assert pickle.dumps(fs) == before
    assert fs.streams == []
    assert feed.outlet.stream is None and product.inlet.stream is None

    # The corrected call runs between the same two nozzles.
    corrected = fs.connect(feed.outlet, product.inlet, size='6"')
    assert corrected.name == '6"'


def test_a_scheme_naming_something_that_is_not_a_component_lands_the_same_way():
    """Check that a scheme naming an unknown component leaves the sheet unchanged."""
    fs = Flowsheet("b", line_numbering_scheme="{flavour}")
    feed = fs.add(U.Feed("Feed"))
    product = fs.add(U.Product("Product"))
    before = pickle.dumps(fs)

    with pytest.raises(ValueError, match="not a line-number component"):
        fs.connect(feed.outlet, product.inlet, size='6"')

    assert pickle.dumps(fs) == before
    assert fs.connect(feed.outlet, product.inlet).name == "S1"


def test_a_rejected_line_number_leaves_the_run_it_would_have_joined_alone():
    """Check that a refused segment leaves the run it would have joined unchanged."""
    fs = Flowsheet("c", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("Feed"))
    valve = fs.add(U.Valve("HV-1"))
    product = fs.add(U.Product("Product"))
    first = fs.connect(feed.outlet, valve.inlet)
    before = pickle.dumps(fs)

    # The new segment is the run's only carrier of line-number components.
    with pytest.raises(ValueError, match="never uses"):
        fs.connect(valve.outlet, product.inlet, service="P")

    assert pickle.dumps(fs) == before
    assert first.name == "S1"
    assert fs.streams == [first]

    second = fs.connect(valve.outlet, product.inlet)
    assert second.name == first.name == "S1"  # one number through the valve


def test_a_rejected_line_number_mints_no_pool_member():
    """Check that a refused line off a header flag mints no nozzle."""
    fs = Flowsheet("d", line_numbering_scheme="{size}")
    header = fs.add(U.Feed("CWS", header=True))
    one = fs.add(U.Product("P-1"))
    two = fs.add(U.Product("P-2"))
    fs.connect(header.outlet, one.inlet, size='6"')
    before = pickle.dumps(fs)
    ports_before = sorted(header.ports)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(header.outlet, two.inlet, service="P")

    assert pickle.dumps(fs) == before
    assert sorted(header.ports) == ports_before


def test_a_rejected_duty_leaves_the_lines_numbered_behind_the_runs_alone():
    """Check that a refused duty leaves the lines numbered after the runs unchanged."""
    fs = Flowsheet("e", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("F"))
    heater = fs.add(U.Heater("H-1"))
    cooler = fs.add(U.Cooler("C-1"))
    product = fs.add(U.Product("P"))
    fs.connect(feed.outlet, heater.inlet)
    fs.connect(heater.outlet, product.inlet)
    duty = fs.connect(cooler.utility_out, heater.utility_in)
    assert (duty.kind, duty.name) == ("energy", "S3")
    second = fs.add(U.Cooler("C-2"))
    third = fs.add(U.Heater("H-2"))
    before = pickle.dumps(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(second.utility_out, third.utility_in, service="P")

    assert pickle.dumps(fs) == before
    assert duty.name == "S3"


def test_a_rejected_join_between_two_runs_leaves_the_whole_sheet_alone():
    """Check that a refused join between two runs leaves the sheet unchanged."""
    fs = Flowsheet("f", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("F"))
    first_valve = fs.add(U.Valve("HV-1"))
    second_valve = fs.add(U.Valve("HV-2"))
    product = fs.add(U.Product("P"))
    upstream = fs.connect(feed.outlet, first_valve.inlet)
    downstream = fs.connect(second_valve.outlet, product.inlet)
    assert (upstream.name, downstream.name) == ("S1", "S2")
    before = pickle.dumps(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(first_valve.outlet, second_valve.inlet, service="P")

    assert pickle.dumps(fs) == before
    assert (upstream.name, downstream.name) == ("S1", "S2")

    middle = fs.connect(first_valve.outlet, second_valve.inlet)
    assert upstream.name == middle.name == downstream.name == "S1"


def test_a_refused_rule_check_still_leaves_the_sheet_alone():
    """Check that a second line on a pump suction is refused with the sheet unchanged."""
    fs = Flowsheet("g")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-1"))
    product = fs.add(U.Product("P"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    before = pickle.dumps(fs)

    # A pump has one suction, unlike a header flag's pooled connection.
    with pytest.raises(ValueError, match="already connected"):
        fs.connect(feed.outlet, pump.suction)

    assert pickle.dumps(fs) == before


def test_a_scheme_changed_under_a_duty_leaves_the_lines_ahead_of_it_alone():
    """Check that a scheme a duty cannot meet leaves the lines ahead of it unchanged."""
    fs = Flowsheet("h", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("F"))
    heater = fs.add(U.Heater("H-1"))
    product = fs.add(U.Product("P"))
    first_cooler = fs.add(U.Cooler("C-1"))
    second_cooler = fs.add(U.Cooler("C-2"))
    second_heater = fs.add(U.Heater("H-2"))
    fs.connect(feed.outlet, heater.inlet)
    plain = fs.connect(first_cooler.utility_out, heater.utility_in)
    numbered = fs.connect(second_cooler.utility_out, second_heater.utility_in, size='2"')
    assert (plain.name, numbered.name) == ("S2", '2"')

    # The duty that carries a size carries no spec.
    fs.line_numbering_scheme = "{spec}"
    before = pickle.dumps(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(heater.outlet, product.inlet)

    assert pickle.dumps(fs) == before
    assert plain.name == "S2"  # renamed to S3 by the pass that never finished


def test_a_renumbering_that_cannot_finish_renumbers_nothing():
    """Check that a ``renumber_streams()`` that raises renumbers nothing."""
    fs = Flowsheet("i", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("F"))
    product = fs.add(U.Product("P"))
    cooler = fs.add(U.Cooler("C-1"))
    heater = fs.add(U.Heater("H-1"))
    plain = fs.connect(feed.outlet, product.inlet)
    numbered = fs.connect(cooler.utility_out, heater.utility_in, kind="material", size='2"')
    assert (plain.name, numbered.name) == ("S1", '2"')

    fs.line_numbering_scheme = "{spec}"
    fs.stream_number_start = 90
    before = pickle.dumps(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.renumber_streams()

    assert pickle.dumps(fs) == before
    assert plain.name == "S1"  # renamed to S90 by the pass that never finished


def test_a_rejected_segment_leaves_its_run_s_sequences_alone():
    """Check that a refused segment leaves its run's sequence numbers unchanged."""
    fs = Flowsheet("j", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("F"))
    valve = fs.add(U.Valve("HV-1"))
    product = fs.add(U.Product("P"))
    first = fs.connect(feed.outlet, valve.inlet)
    assert first.sequence == "1001"

    fs.line_number_start = 2000
    before = pickle.dumps(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(valve.outlet, product.inlet, service="P")

    assert pickle.dumps(fs) == before
    assert first.sequence == "1001"  # rewritten to 2000 by the naming that failed
