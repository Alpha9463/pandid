"""Check stream numbering: inline devices carry the number through; signals are unnumbered."""

from pandid import Flowsheet, units as U


def test_new_line_number_valve_breaks_number():
    fs = Flowsheet("v")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    v.new_line_number = True
    s1 = fs.connect(f.outlet, v.inlet)
    s2 = fs.connect(v.outlet, p.inlet)
    fs.renumber_streams()
    assert s1.name != s2.name  # important valve breaks the number


def test_reactor_breaks_number():
    fs = Flowsheet("r")
    f = fs.add(U.Feed("F"))
    r = fs.add(U.Reactor("R"))
    p = fs.add(U.Product("P"))
    s1 = fs.connect(f.outlet, r.feed)
    s2 = fs.connect(r.outlet, p.inlet)
    fs.renumber_streams()
    assert s1.name != s2.name


def test_connect_returns_the_number_that_gets_drawn():
    fs = Flowsheet("n")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    st = fs.add(U.Fitting("ST-1", variant="strainer"))
    p = fs.add(U.Product("P"))
    streams = [
        fs.connect(f.outlet, v.inlet),
        fs.connect(v.outlet, st.inlet),
        fs.connect(st.outlet, p.inlet),
    ]
    held = [s.name for s in streams]
    svg = fs.to_svg()
    fs.to_svg()  # and again: renumbering is idempotent
    assert [s.name for s in streams] == held  # rendering did not move them
    assert held == ["S1", "S1", "S1"]  # one number through both inline fittings
    assert ">S1<" in svg


def test_explicit_names_are_never_renumbered():
    fs = Flowsheet("n")
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Pump("P-1"))
    prod = fs.add(U.Product("P"))
    named = fs.connect(f.outlet, p.suction, name="100-BFW-01")
    auto = fs.connect(p.discharge, prod.inlet)
    # The named run takes the first place in the series.
    assert (named.name, auto.name) == ("100-BFW-01", "S2")
    fs.to_svg()
    assert (named.name, auto.name) == ("100-BFW-01", "S2")


def test_an_explicit_name_consumes_its_number():
    """Check that a named run takes its place in the series."""
    fs = Flowsheet("c", stream_number_start=100)
    f1, f2 = fs.add(U.Feed("F1")), fs.add(U.Feed("F2"))
    m = fs.add(U.Mixer("M-1", n_inlets=2))
    prod = fs.add(U.Product("P"))
    named = fs.connect(f1.outlet, m.inlets[0], name="S100")
    auto = fs.connect(f2.outlet, m.inlets[1])
    out = fs.connect(m.outlet, prod.inlet)
    assert (named.name, auto.name, out.name) == ("S100", "S101", "S102")
    assert len({s.name for s in fs.streams}) == 3


def test_a_named_group_consumes_one_number_not_one_per_segment():
    """The place belongs to the run, not to each segment of it."""
    fs = Flowsheet("g")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Pump("P-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(f.outlet, v.inlet, name="LINE-A")
    fs.connect(v.outlet, p.suction, name="LINE-A")  # same run, through the valve
    auto = fs.connect(p.discharge, prod.inlet)
    assert auto.name == "S2"  # not S3: the two segments are one group


def test_new_line_number_set_after_connecting_renumbers():
    fs = Flowsheet("n")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    s1 = fs.connect(f.outlet, v.inlet)
    s2 = fs.connect(v.outlet, p.inlet)
    assert s1.name == s2.name == "S1"  # inline until the valve is called important
    v.new_line_number = True
    assert (s1.name, s2.name) == ("S1", "S2")  # the break lands without a render


def test_energy_stream_does_not_take_a_process_number():
    """A duty line is drawn with a number, but not one from the process run."""
    fs = Flowsheet("e")
    f = fs.add(U.Feed("F"))
    heater = fs.add(U.Heater("E-1"))
    cooler = fs.add(U.Cooler("C-1"))
    p = fs.add(U.Product("P"))
    duty = fs.connect(cooler.utility_out, heater.utility_in)  # both energy ports
    s1 = fs.connect(f.outlet, heater.inlet)
    s2 = fs.connect(heater.outlet, p.inlet)
    assert duty.kind == "energy"
    assert (s1.name, s2.name) == ("S1", "S2")  # the duty line burned no number
    assert duty.name == "S3"  # numbered after the process streams, not before
    fs.to_svg()
    assert (s1.name, s2.name, duty.name) == ("S1", "S2", "S3")


def test_signal_line_does_not_take_a_process_number():
    fs = Flowsheet("s")
    f = fs.add(U.Feed("F"))
    fv = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    fic = fs.add_instrument("FIC", 1)
    sig = fs.connect(fic.sig_out, fv.actuator, kind="electric")
    s1 = fs.connect(f.outlet, fv.inlet)
    s2 = fs.connect(fv.outlet, p.inlet)
    assert s1.name == s2.name == "S1"
    assert sig.name == "S2"  # last in the sequence, so it shares no name


# --- stream_number_start ------------------------------------------------------


def _two_streams(**kwargs):
    """Feed -> pump -> product: a pump breaks the number, so two of them."""
    fs = Flowsheet("start", **kwargs)
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Pump("P-1"))
    prod = fs.add(U.Product("P"))
    return fs, [fs.connect(f.outlet, p.suction), fs.connect(p.discharge, prod.inlet)]


def test_stream_number_start_moves_the_whole_series():
    fs, streams = _two_streams(stream_number_start=100)
    assert [s.name for s in streams] == ["S100", "S101"]
    fs.to_svg()
    assert [s.name for s in streams] == ["S100", "S101"]  # and rendering did not move them


def test_stream_number_start_defaults_to_one():
    _, streams = _two_streams()
    assert [s.name for s in streams] == ["S1", "S2"]


def test_stream_number_start_reaches_a_callable_scheme_too():
    """Check that ``stream_number_start`` offsets the number a callable scheme gets."""
    fs, streams = _two_streams(stream_naming_scheme=lambda n: f"S{n:03d}", stream_number_start=100)
    assert [s.name for s in streams] == ["S100", "S101"]


def test_stream_number_start_is_not_the_line_sequence():
    """Check that ``stream_number_start`` and ``line_number_start`` number apart."""
    fs = Flowsheet("both", stream_number_start=100, line_number_start=301)
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Pump("P-1"))
    prod = fs.add(U.Product("Prod"))
    plain = fs.connect(f.outlet, p.suction)
    numbered = fs.connect(p.discharge, prod.inlet, size='6"', service="P", spec="A1A")
    assert plain.name == "S100"  # the stream series
    assert numbered.name == '6"-P-302-A1A'  # the line series, second group


def test_stream_number_start_round_trips_through_a_spec():
    fs, _ = _two_streams(stream_number_start=100)
    spec = fs.to_dict()
    assert spec["stream_number_start"] == 100
    rebuilt = Flowsheet.from_dict(spec)
    assert rebuilt.stream_number_start == 100
    assert [s.name for s in rebuilt.streams] == ["S100", "S101"]


def test_a_default_stream_number_start_writes_no_key():
    assert "stream_number_start" not in Flowsheet("plain").to_dict()


def test_signals_unnumbered_and_no_arrow():
    fs = Flowsheet("s")
    a = fs.add(U.Instrument("FT-1"))
    b = fs.add(U.Instrument("FIC-1"))
    sig = fs.connect(a.sig_out, b.sig_in, kind="electric")
    svg = fs.to_svg()
    assert f">{sig.name}<" not in svg


# --- numbering one appended stream rather than the whole sheet -----------


def _settled(fs) -> bool:
    """True when a full pass would change nothing connect() left behind."""
    before = [(s.name, s.sequence) for s in fs.streams]
    fs.renumber_streams()
    return [(s.name, s.sequence) for s in fs.streams] == before


def test_a_join_between_two_runs_renumbers_the_sheet():
    """Check that a join between two numbered runs renumbers them as one."""
    fs = Flowsheet("merge")
    f = fs.add(U.Feed("F"))
    v1, v2 = fs.add(U.Valve("FV-1")), fs.add(U.Valve("FV-2"))
    t1 = fs.add(U.Tank("T-1"))
    tail = fs.connect(v1.outlet, t1.inlet)  # a run hanging off FV-1's outlet
    head = fs.connect(f.outlet, v2.inlet)  # another, into FV-2's inlet
    assert (tail.name, head.name) == ("S1", "S2")
    bridge = fs.connect(v2.outlet, v1.inlet)  # joins both through both valves
    assert tail.name == head.name == bridge.name == "S1"  # now one run
    assert _settled(fs)


def test_a_later_segment_can_rename_the_run_it_joins():
    """Check that a later segment with a line number renames its run."""
    fs = Flowsheet("rename")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    first = fs.connect(f.outlet, v.inlet)
    assert first.name == "S1"
    fs.connect(v.outlet, p.inlet, size='6"', service="P", spec="A1A")
    assert first.name == '6"-P-1001-A1A'  # renamed by the segment behind it
    assert _settled(fs)


def test_an_explicit_name_on_a_later_segment_names_the_run():
    fs = Flowsheet("rename-explicit")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    first = fs.connect(f.outlet, v.inlet)
    fs.connect(v.outlet, p.inlet, name="LINE-A")
    assert first.name == "LINE-A"
    assert _settled(fs)


def test_a_tees_branch_starts_a_line_of_its_own():
    fs = Flowsheet("branch")
    f = fs.add(U.Feed("F"))
    tee = fs.add(U.Tee("T-1"))
    p, d = fs.add(U.Product("P")), fs.add(U.Product("D"))
    run_in = fs.connect(f.outlet, tee.inlet)
    run_out = fs.connect(tee.outlet, p.inlet)
    branch = fs.connect(tee.branch, d.inlet)
    assert run_in.name == run_out.name == "S1"
    assert branch.name == "S2"
    assert _settled(fs)


def test_a_duty_line_added_after_the_process_runs_settles():
    fs = Flowsheet("tail")
    f = fs.add(U.Feed("F"))
    heater = fs.add(U.Heater("E-1"))
    cooler = fs.add(U.Cooler("C-1"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, heater.inlet)
    duty = fs.connect(cooler.utility_out, heater.utility_in)
    assert duty.kind == "energy"
    last = fs.connect(heater.outlet, p.inlet)  # a process run behind the duty
    assert (last.name, duty.name) == ("S2", "S3")  # the duty shifted up
    assert _settled(fs)


def _fuzz_sheet(check: bool):
    """Return a 120-step sheet built by appending random devices, names and lines.

    With *check*, run a full renumbering after every append and require it to move nothing.
    """
    import random

    rng = random.Random(20260816)
    fs = Flowsheet("fuzz", stream_number_start=100)
    free = [fs.add(U.Feed("F")).outlet]  # outlets with no line on them yet
    made = []
    for i in range(120):
        kind = rng.choice(["valve", "fitting", "tee", "tank", "heater"])
        if kind == "valve":
            u = fs.add(U.Valve(f"FV-{i}"))
        elif kind == "fitting":
            u = fs.add(U.Fitting(f"ST-{i}", variant="strainer"))
        elif kind == "tee":
            u = fs.add(U.Tee(f"TE-{i}"))
        elif kind == "heater":
            u = fs.add(U.Heater(f"E-{i}"))
        else:
            u = fs.add(U.Tank(f"T-{i}"))
        opts: dict = {}
        roll = rng.random()
        if roll < 0.15:
            opts["name"] = f"HAND-{i}"
        elif roll < 0.3:
            opts.update(size='6"', service="P", spec="A1A")
        # A port carries one line, so each outlet is spent as it is used.
        src = free.pop(rng.randrange(len(free)))
        fs.connect(src, u.inlet, **opts)
        made.append(u)
        assert not check or _settled(fs), f"append {i} ({kind}) moved"
        free.append(u.outlet)
        if "branch" in u.ports:
            free.append(u.branch)
        if kind == "heater":  # a duty line, numbered in the tail
            cooler = fs.add(U.Cooler(f"C-{i}"))
            fs.connect(cooler.utility_out, u.utility_in)
            assert not check or _settled(fs), f"duty {i} moved"
        if rng.random() < 0.1:  # a break set after the run was numbered
            rng.choice(made).new_line_number = True
            assert not check or _settled(fs), f"break {i} moved"
    assert len(fs.streams) > 120
    return fs


def test_every_shape_of_append_agrees_with_a_full_pass():
    """Check that a full pass after each append changes nothing."""
    _fuzz_sheet(check=True)


def test_a_sheet_built_by_appending_alone_agrees_with_a_full_pass():
    """Check that a sheet built by appends alone agrees with a full pass."""
    fs = _fuzz_sheet(check=False)
    assert _settled(fs)
