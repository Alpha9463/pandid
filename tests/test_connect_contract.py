"""What ``connect()`` promises about the answer it gives back.

Two promises, both of them about the author's input rather than about the
drawing:

* **A kind the author states is the kind that is drawn** (#493). Reading the
  two nozzles is what ``connect()`` does when nobody says; it is not what it
  does when somebody does.
* **A refused call changes nothing** (#451). Not the streams, not the nozzles,
  not the numbering, not a pool member minted on the way -- and the proof is a
  comparison of the whole flowsheet, because a comparison that names what to
  look at is a comparison that goes stale.
"""

import pickle

import pytest

from pandid import Flowsheet, units as U


# --- #493: a stated kind is the kind that is drawn ---------------------------


def _duty_sheet() -> tuple[Flowsheet, U.Cooler, U.Heater]:
    """Two utility nozzles facing each other, and nothing else on the sheet."""
    fs = Flowsheet("promotion")
    cooler = fs.add(U.Cooler("C-1"))  # cooler.utility_out is an outlet energy port
    heater = fs.add(U.Heater("H-1"))  # heater.utility_in is an inlet energy port
    return fs, cooler, heater


def test_an_unstated_kind_between_two_utility_nozzles_is_still_energy():
    """The inference is wanted and is what the default is for. Guarding it
    first, because the fix for #493 is a fix to *when* it runs and it would be
    no fix at all if it stopped running."""
    fs, cooler, heater = _duty_sheet()
    assert fs.connect(cooler.utility_out, heater.utility_in).kind == "energy"


def test_a_stated_material_kind_survives_two_utility_nozzles():
    """#493 exactly as it was reported. Cooling-water piping is water in a
    pipe, the author says so, and the sheet is drawn from what they said."""
    fs, cooler, heater = _duty_sheet()
    stream = fs.connect(cooler.utility_out, heater.utility_in, kind="material")
    assert stream.kind == "material"


def test_a_stated_energy_kind_survives_two_process_nozzles():
    """The same rule from the other side, which is what makes it a rule. An
    energy kind on two process nozzles is not turned into a material one, so
    the fix cannot be read as "material always wins"."""
    fs = Flowsheet("symmetry")
    pump = fs.add(U.Pump("P-1"))
    vessel = fs.add(U.Vessel("V-1"))
    stream = fs.connect(pump.discharge, vessel.inlet, kind="energy")
    assert stream.kind == "energy"


def test_a_stated_material_duty_takes_a_process_number():
    """The stated kind reaches the drawing and not just the attribute.

    Numbering is where the kind is spent: :meth:`Flowsheet.renumber_streams`
    counts every material run first and every energy line after them. A line
    the author called material is counted with the process runs, which is the
    same statement as "the sheet is drawn from what they said".
    """
    fs = Flowsheet("numbering")
    feed = fs.add(U.Feed("F"))
    cooler = fs.add(U.Cooler("C-1"))
    heater = fs.add(U.Heater("H-1"))
    product = fs.add(U.Product("P"))
    duty = fs.connect(cooler.utility_out, heater.utility_in, kind="material")
    first = fs.connect(feed.outlet, heater.inlet)
    last = fs.connect(heater.outlet, product.inlet)
    # S1 because it was drawn first, where an energy line would have waited
    # behind both process runs for S3.
    assert (duty.name, first.name, last.name) == ("S1", "S2", "S3")


def test_a_stated_material_duty_survives_a_spec_round_trip():
    """``to_dict`` writes the kind down against what a reader would infer, not
    against the word "material", so the answer the author gave comes back."""
    fs, cooler, heater = _duty_sheet()
    fs.connect(cooler.utility_out, heater.utility_in, kind="material")
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert [s.kind for s in rebuilt.streams] == ["material"]


def test_an_inferred_duty_still_round_trips_without_saying_kind():
    """The other half of that: a line nobody named a kind for is left for the
    reader to infer, so the spec does not grow a field per stream."""
    fs, cooler, heater = _duty_sheet()
    fs.connect(cooler.utility_out, heater.utility_in)
    written = fs.to_dict()
    assert "kind" not in written["streams"][0]
    assert [s.kind for s in Flowsheet.from_dict(written).streams] == ["energy"]


def test_a_kind_that_is_not_a_kind_is_still_refused():
    fs, cooler, heater = _duty_sheet()
    with pytest.raises(ValueError, match="Stream kind must be one of"):
        fs.connect(cooler.utility_out, heater.utility_in, kind="steam")


# --- #451: a refused call changes nothing ------------------------------------
#
# `connect()` checked every rule before it wrote anything and was believed to be
# all-or-nothing on those grounds. The numbering at the foot of it cannot be
# checked that way -- it runs on the sheet *with* the new run on it -- and it
# raises, so a rejected line number left the run drawn, nameless, with both
# nozzles taken and a corrected retry answering `already connected`.


def _state(fs: Flowsheet) -> bytes:
    """The whole flowsheet, deeply, as bytes that can be compared.

    ``pickle`` rather than a field-by-field walk for the same reason the
    rollback it checks is wholesale: a comparison that names what to look at is
    a comparison that goes stale. The first three rounds of this family of bugs
    were each caught by the *next* thing nobody had thought to look at -- the
    streams list, then the nozzles, then the numbering cache -- and this looks
    at all of it at once.
    """
    return pickle.dumps(fs)


def test_the_state_check_can_see_a_change():
    """The guard's own guard. A comparison that compares nothing passes
    everything, so this asserts that ``_state`` notices the smallest of the
    mutations a refused ``connect()`` used to leave behind."""
    fs = Flowsheet("meta")
    feed = fs.add(U.Feed("F"))
    product = fs.add(U.Product("P"))
    before = _state(fs)
    fs.connect(feed.outlet, product.inlet)
    assert _state(fs) != before


def test_the_state_check_can_see_a_renumbering():
    """And the mutation that is easiest to miss, because it moves no object:
    every name on the sheet changing under a sheet whose shape did not."""
    fs = Flowsheet("meta")
    feed = fs.add(U.Feed("F"))
    product = fs.add(U.Product("P"))
    fs.connect(feed.outlet, product.inlet)
    before = _state(fs)
    fs.stream_number_start = 90
    fs.renumber_streams()
    assert _state(fs) != before


def test_a_rejected_line_number_leaves_the_sheet_alone():
    """#451 exactly as it was reported: a scheme that names ``{size}`` and a
    run that carries only ``service``. The line number would come out empty,
    the call is refused -- and the run must not be on the sheet."""
    fs = Flowsheet("a", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("Feed"))
    product = fs.add(U.Product("Product"))
    before = _state(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(feed.outlet, product.inlet, service="P")

    assert _state(fs) == before
    assert fs.streams == []
    assert feed.outlet.stream is None and product.inlet.stream is None

    # The half that says the wreckage is really gone: the corrected call runs
    # between the same two nozzles, which used to answer `already connected`.
    corrected = fs.connect(feed.outlet, product.inlet, size='6"')
    assert corrected.name == '6"'


def test_a_scheme_naming_something_that_is_not_a_component_lands_the_same_way():
    """``_format_line_number``'s other raise, which reaches the sheet by the
    same route and so has to be undone by the same guard."""
    fs = Flowsheet("b", line_numbering_scheme="{flavour}")
    feed = fs.add(U.Feed("Feed"))
    product = fs.add(U.Product("Product"))
    before = _state(fs)

    with pytest.raises(ValueError, match="not a line-number component"):
        fs.connect(feed.outlet, product.inlet, size='6"')

    assert _state(fs) == before
    assert fs.connect(feed.outlet, product.inlet).name == "S1"


def test_a_rejected_line_number_leaves_the_run_it_would_have_joined_alone():
    """The segments beside the refused one, which is where a hand-written undo
    stops looking. Numbering fills in a whole run's sequences before it works
    out what the run is called, and the raise comes from the second half."""
    fs = Flowsheet("c", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("Feed"))
    valve = fs.add(U.Valve("HV-1"))
    product = fs.add(U.Product("Product"))
    first = fs.connect(feed.outlet, valve.inlet)
    before = _state(fs)

    # The new segment is the run's only carrier of line-number components, so
    # it is the one the number is formatted from -- and it carries nothing the
    # scheme names.
    with pytest.raises(ValueError, match="never uses"):
        fs.connect(valve.outlet, product.inlet, service="P")

    assert _state(fs) == before
    assert first.name == "S1"
    assert fs.streams == [first]

    second = fs.connect(valve.outlet, product.inlet)
    assert second.name == first.name == "S1"  # one number through the valve


def test_a_rejected_line_number_mints_no_pool_member():
    """A second line off a header's flag takes a fresh member of its
    connection, and the mint happens before the numbering that refuses. A
    balloon or a flag left carrying a nozzle no line reaches is a drawing
    changed by an error, and the debug overlay draws it."""
    fs = Flowsheet("d", line_numbering_scheme="{size}")
    header = fs.add(U.Feed("CWS", header=True))
    one = fs.add(U.Product("P-1"))
    two = fs.add(U.Product("P-2"))
    fs.connect(header.outlet, one.inlet, size='6"')
    before = _state(fs)
    ports_before = sorted(header.ports)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(header.outlet, two.inlet, service="P")

    assert _state(fs) == before
    assert sorted(header.ports) == ports_before


def test_a_rejected_duty_leaves_the_lines_numbered_behind_the_runs_alone():
    """The tail -- energy and signal lines -- is numbered by a pass of its own,
    one line at a time, so a raise part-way along it used to leave the lines
    ahead of the failure renamed."""
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
    before = _state(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(second.utility_out, third.utility_in, service="P")

    assert _state(fs) == before
    assert duty.name == "S3"


def test_a_rejected_join_between_two_runs_leaves_the_whole_sheet_alone():
    """The slow path. A segment that joins two runs into one moves every name
    behind them, so ``connect()`` renumbers the sheet from the front -- and a
    raise there is a half-renumbered sheet rather than one stray stream."""
    fs = Flowsheet("f", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("F"))
    first_valve = fs.add(U.Valve("HV-1"))
    second_valve = fs.add(U.Valve("HV-2"))
    product = fs.add(U.Product("P"))
    upstream = fs.connect(feed.outlet, first_valve.inlet)
    downstream = fs.connect(second_valve.outlet, product.inlet)
    assert (upstream.name, downstream.name) == ("S1", "S2")
    before = _state(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(first_valve.outlet, second_valve.inlet, service="P")

    assert _state(fs) == before
    assert (upstream.name, downstream.name) == ("S1", "S2")

    middle = fs.connect(first_valve.outlet, second_valve.inlet)
    # The join really does renumber, which is what makes the refusal above the
    # slow path rather than the fast one.
    assert upstream.name == middle.name == downstream.name == "S1"


def test_a_refused_rule_check_still_leaves_the_sheet_alone():
    """The refusals that were already made before the first write stay made,
    and the guard does not change what they say."""
    fs = Flowsheet("g")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-1"))
    product = fs.add(U.Product("P"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    before = _state(fs)

    # A pump has one suction, and a second line on it is a tee the drawing has
    # to show -- unlike a header flag, whose connection is a pool.
    with pytest.raises(ValueError, match="already connected"):
        fs.connect(feed.outlet, pump.suction)

    assert _state(fs) == before


def test_a_scheme_changed_under_a_duty_leaves_the_lines_ahead_of_it_alone():
    """A tail the numbering gets part-way along.

    ``line_numbering_scheme`` is a property of the sheet and an author may set
    it after they have drawn on it. Do that in a way one existing duty cannot
    satisfy and the *next* ``connect()`` is what finds out -- one more process
    run means one more place used, so every line behind them is renamed, and
    the pass reaches the duty that raises only after it has renamed the one in
    front of it.
    """
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

    # A reconfiguration the sheet as it stands cannot answer: the duty that
    # carries a size carries no spec.
    fs.line_numbering_scheme = "{spec}"
    before = _state(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(heater.outlet, product.inlet)

    assert _state(fs) == before
    assert plain.name == "S2"  # renamed to S3 by the pass that never finished


def test_a_renumbering_that_cannot_finish_renumbers_nothing():
    """The same rule on the full pass, which an author can call directly.

    Numbering the fifth group is what raises, and the four groups in front of
    it have their new numbers by then. A sheet numbered from a start nobody
    ended up using is a sheet whose stream table and whose labels disagree with
    every report written off the objects.
    """
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
    before = _state(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.renumber_streams()

    assert _state(fs) == before
    assert plain.name == "S1"  # renamed to S90 by the pass that never finished


def test_a_rejected_segment_leaves_its_run_s_sequences_alone():
    """The narrowest of them, and the one no outer guard reaches.

    Naming a run writes the sequence into every segment of it *before* it works
    out what the run is called, because a ``line_numbering_scheme`` that names
    ``{sequence}`` reads one back off the carrier. Move ``line_number_start``
    between two ``connect()`` calls and the second one rewrites the first
    segment's sequence on its way to the raise -- a segment ``connect()``'s own
    guard has no reason to be holding, since it is neither of the two nozzles
    the call named.
    """
    fs = Flowsheet("j", line_numbering_scheme="{size}")
    feed = fs.add(U.Feed("F"))
    valve = fs.add(U.Valve("HV-1"))
    product = fs.add(U.Product("P"))
    first = fs.connect(feed.outlet, valve.inlet)
    assert first.sequence == "1001"

    fs.line_number_start = 2000
    before = _state(fs)

    with pytest.raises(ValueError, match="never uses"):
        fs.connect(valve.outlet, product.inlet, service="P")

    assert _state(fs) == before
    assert first.sequence == "1001"  # rewritten to 2000 by the naming that failed
