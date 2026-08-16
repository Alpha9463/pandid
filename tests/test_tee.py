"""The pipe tee: a line branching, and what a sheet draws for it.

The reference is the CV-303 station of the issued sheet the package reproduces
(``professional_examples/P&ID_301.pdf``, gitignored). Measured off its vector
geometry, that station is:

* a main run drawn as **one unbroken stroke**, ``(703.78, 233.29)`` to
  ``(471.34, 233.29)``, straight through every junction on it;
* a bypass leaving it at ``(569.14, 233.29)``, standing 15.87 pt clear over the
  top through a darkened (normally closed) valve, and rejoining at
  ``(676.85, 233.29)``;
* two drain legs dropping 9.64 pt from ``(598.90, 233.29)`` and
  ``(648.51, 233.29)`` into darkened valves, and ending there;
* every one of those strokes 0.75 pt, the same weight as the run;
* and **nothing drawn at any of the four junctions**: the sheet contains no
  filled shape smaller than 6 pt anywhere on it.

So the tests below hold three things: the run does not kink through a tee, the
tee puts no tag and no symbol on the sheet, and nothing about it reaches the
equipment list.
"""

from __future__ import annotations

import re

import pytest

from pandid import Flowsheet, units
from pandid.document import equipment_list
from pandid.portgeom import port_offset, port_point

RUN_Y = 220.0
BYPASS_Y = RUN_Y - 31.0
DRAIN_Y = 256.0


def on_run(unit, x, run_y, port="inlet", mirrored=False):
    """Pin an in-line device at ``x`` with ``port`` on its run's centreline."""
    return unit.pin(x=x, mirrored=mirrored).pin(port=port, y=run_y)


def station():
    """The CV-303 station: isolation valves, a bypass over the top, two drains.

    Laid out by hand, exactly as a valve station is drawn: every device pinned
    on the run's centreline, the tees among them. Spacings are the tightest the
    router's 25-unit escape stand-off leaves clean: a facing pair closer than
    that makes the run double back on itself, which is true of two valves with
    no tee between them and has nothing to do with the junction.
    """
    fs = Flowsheet(
        "CV-303 Station",
        line_numbering_scheme="{service}-{sequence}-{size}-{schedule}-{spec}",
        line_number_start=303,
    )
    feed = fs.add(units.Feed("From FE-303"))
    t_by_a = fs.add(units.Tee())  # bypass takeoff
    hv_a = fs.add(units.Valve("HV-303A", variant="gate"))
    t_dr_a = fs.add(units.Tee())  # upstream drain
    rd = fs.add(units.Reducer("RD-303", variant="concentric"))
    cv = fs.add(units.Valve("CV-303", variant="control"))
    t_dr_b = fs.add(units.Tee())  # downstream drain
    hv_b = fs.add(units.Valve("HV-303B", variant="gate"))
    t_by_b = fs.add(units.Tee(branch="inlet"))  # bypass return
    prod = fs.add(units.Product("To T-301"))

    hv_bp = fs.add(units.Valve("HV-303C", variant="globe", normal_position="closed"))
    dv_a = fs.add(units.Valve("HV-303D", variant="gate", normal_position="closed"))
    dv_b = fs.add(units.Valve("HV-303E", variant="gate", normal_position="closed"))

    on_run(feed, 120, RUN_Y, port="outlet")
    on_run(t_by_a, 250, RUN_Y, mirrored="y")  # branch N
    on_run(hv_a, 292, RUN_Y)
    on_run(t_dr_a, 346, RUN_Y)  # branch S
    on_run(rd, 388, RUN_Y)
    on_run(cv, 430, RUN_Y)
    on_run(t_dr_b, 484, RUN_Y)  # branch S
    on_run(hv_b, 526, RUN_Y)
    on_run(t_by_b, 580, RUN_Y, mirrored="y")  # branch N
    on_run(prod, 700, RUN_Y, port="inlet")
    on_run(hv_bp, 409, BYPASS_Y)

    # A drain valve stands in the vertical leg, so it takes the quarter turn.
    # The leg ends at the valve: a drain runs to a funnel off the sheet.
    for valve, junction_x in ((dv_a, 352.0), (dv_b, 490.0)):
        valve.pin(orientation=90)
        valve.pin(port="inlet", x=junction_x, y=DRAIN_Y)

    fs.connect(
        feed.outlet, t_by_a.inlet, service="AE", sequence=303, size=80, schedule=80, spec="SS"
    )
    fs.connect(t_by_a.outlet, hv_a.inlet)
    fs.connect(hv_a.outlet, t_dr_a.inlet)
    fs.connect(t_dr_a.outlet, rd.inlet)
    fs.connect(rd.outlet, cv.inlet)
    fs.connect(cv.outlet, t_dr_b.inlet)
    fs.connect(t_dr_b.outlet, hv_b.inlet)
    fs.connect(hv_b.outlet, t_by_b.inlet)
    fs.connect(t_by_b.outlet, prod.inlet)

    fs.connect(
        t_by_a.branch, hv_bp.inlet, service="AE", sequence=318, size=80, schedule=80, spec="SS"
    )
    fs.connect(hv_bp.outlet, t_by_b.branch)

    fs.connect(
        t_dr_a.branch, dv_a.inlet, service="AE", sequence=319, size=25, schedule=80, spec="SS"
    )
    fs.connect(
        t_dr_b.branch, dv_b.inlet, service="AE", sequence=320, size=25, schedule=80, spec="SS"
    )
    return fs


@pytest.fixture(scope="module")
def cv303():
    return station()


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def test_the_branch_takes_flow_off_the_run_by_default():
    tee = units.Tee()
    assert tee.branch.direction == "outlet"
    assert tee.branch.role == "process"
    assert tee.inlet.direction == "inlet"
    assert tee.outlet.direction == "outlet"


def test_a_returning_tee_takes_flow_back_onto_the_run():
    tee = units.Tee(branch="inlet")
    assert tee.branch.direction == "inlet"
    # The run is the run whichever way the third connection goes.
    assert tee.inlet.direction == "inlet"
    assert tee.outlet.direction == "outlet"


def test_a_branch_that_is_neither_is_refused():
    with pytest.raises(ValueError, match="branch="):
        units.Tee("T-1", branch="sideways")


def test_a_tee_carries_no_tag():
    assert units.Tee("T-1").tag == ""


def test_tees_share_one_name_and_are_told_apart_by_the_flowsheet():
    fs = Flowsheet("t")
    tees = [fs.add(units.Tee()) for _ in range(3)]
    assert [t.name for t in tees] == ["TEE", "TEE (2)", "TEE (3)"]
    # Nothing is drawn against any of them, so there is nothing to confuse.
    assert {t.tag for t in tees} == {""}


def test_a_tee_may_not_take_a_name_that_already_means_something_else():
    """The repeat is between tees, not between a tee and anything on the sheet.

    A tee has no tag, so two of them are not two things a reader could confuse.
    The name is still the handle a stream and a spec entry reach it by, and a
    tee answering to ``P-101`` would make that handle mean two things.
    """
    fs = Flowsheet("t")
    fs.add(units.Pump("P-101"))
    with pytest.raises(ValueError, match="already exists"):
        fs.add(units.Tee("P-101"))


# ---------------------------------------------------------------------------
# The drawing
# ---------------------------------------------------------------------------


def test_the_run_does_not_kink_through_a_junction(cv303):
    """Every waypoint of every run segment sits on one centreline."""
    cv303.to_svg(diagram="p&id")
    run = [s for s in cv303.streams if s.name.startswith("AE-303")]
    assert len(run) == 9
    for stream in run:
        src, dst = stream.source.owner, stream.dest.owner
        points = [port_point(src, src.frame, stream.source.name)]
        points += list(stream.route.waypoints)
        points.append(port_point(dst, dst.frame, stream.dest.name))
        assert {round(y, 6) for _, y in points} == {RUN_Y}, stream.name


def test_the_tees_nozzles_share_the_runs_centreline():
    """The reason the run stays straight: it is a property of the symbol."""
    tee = units.Tee()
    assert port_offset(tee, "inlet")[1] == port_offset(tee, "outlet")[1]
    # ...and the branch is somewhere else, or it would be the same nozzle.
    assert port_offset(tee, "branch")[1] != port_offset(tee, "inlet")[1]


@pytest.mark.parametrize(
    "placement,face",
    [
        ({}, "S"),
        ({"mirrored": "y"}, "N"),
        ({"orientation": 90}, "W"),
        ({"orientation": 270}, "E"),
    ],
)
def test_the_branch_leaves_whichever_side_the_placement_puts_it(placement, face):
    from pandid.portgeom import port_faces

    tee = units.Tee().pin(**placement)
    assert port_faces(tee, "branch") == [face]


def test_no_tag_is_drawn_for_a_tee(cv303):
    svg = cv303.to_svg(diagram="p&id")
    assert "TEE" not in svg
    # The valves around it are still tagged, so this is not an empty sheet.
    assert "CV-303" in svg


def test_the_junction_is_bare_pipe(cv303):
    """The tee's whole artwork: the run across, and the branch stub off it.

    The reference draws three lines meeting and nothing else -- no dot, no
    circle, no fitting outline -- so the symbol is two path segments at the
    2-unit weight the process lines are drawn in, and no fill anywhere.
    """
    from pandid.render.symbols import default_registry

    svg = default_registry.get("tee").svg
    assert svg.count("<path") == 1
    assert svg.count("<") == 3  # <g>, <path>, </g>
    assert 'fill="none"' in svg and 'stroke-width="2"' in svg
    assert cv303.to_svg(diagram="p&id").count('href="#sym_tee"') == 4


def heads_by_destination(fs, **kwargs):
    """Every stream on the sheet, keyed by where it ends, paired with whether
    it was drawn with an arrowhead.

    Read back out of the SVG rather than off the model, because the arrowhead
    is a rendering decision and the point is what a reader sees. A line's last
    ``L`` is its far end, which is the nozzle its ``dest`` port resolves to.
    """
    svg = fs.to_svg(**kwargs)
    tipped = {}
    for d, rest in re.findall(r'<path d="([^"]*)"([^>]*)/>', svg):
        tipped[d.rsplit("L ", 1)[-1].strip()] = "marker-end" in rest
    out = {}
    for stream in fs.streams:
        dest = stream.dest.owner
        x, y = port_point(dest, dest.frame, stream.dest.name)
        out[(dest.name, stream.dest.name)] = tipped[f"{x},{y}"]
    return out


def tee_on_a_pfd():
    """One run with a junction in the middle of it, and a branch off it.

    Every line but the one into the tee ends somewhere a reader can point at: a
    boundary flag, a belt, a valve. The tee is the only thing on the sheet that
    is a point on a line rather than a place.
    """
    fs = Flowsheet("Tee on a PFD")
    source = fs.add(units.Feed("Source"))
    hand_valve = fs.add(units.Valve("HV-1"))
    tee = fs.add(units.Tee())
    run = fs.add(units.Product("Run"))
    belt = fs.add(units.Conveyor("BC-1", length=90))
    cake = fs.add(units.Product("Cake"))

    fs.connect(source.outlet, hand_valve.inlet)
    fs.connect(hand_valve.outlet, tee.inlet)
    fs.connect(tee.outlet, run.inlet)
    fs.connect(tee.branch, belt.feed)
    fs.connect(belt.discharge, cake.inlet)
    return fs


def test_a_run_is_not_tipped_where_it_divides():
    """The defect: a filled arrowhead in the middle of an unbroken run.

    An arrowhead says the material arrives here. A tee is not a here -- it is a
    point on a line where the line divides, and the run carries straight on
    past it -- so the segment ending at one is drawn without a head.
    """
    fs = tee_on_a_pfd()
    heads = heads_by_destination(fs)
    assert heads[("TEE", "inlet")] is False


def test_every_line_that_arrives_somewhere_keeps_its_arrowhead():
    """Including the two the boundary flags terminate and the one the belt
    catches, which is a symbol built to its own length rather than a fixed one.
    """
    fs = tee_on_a_pfd()
    heads = heads_by_destination(fs)
    assert heads[("HV-1", "inlet")] is True
    assert heads[("Run", "inlet")] is True
    assert heads[("BC-1", "feed")] is True
    assert heads[("Cake", "inlet")] is True


def test_the_sheet_loses_one_arrowhead_per_junction_and_no_others():
    fs = tee_on_a_pfd()
    into_a_junction = sum(1 for s in fs.streams if isinstance(s.dest.owner, units.Tee))
    assert into_a_junction == 1
    assert fs.to_svg().count("marker-end=") == len(fs.streams) - into_a_junction


def test_a_leg_rejoining_the_run_is_not_tipped_either(cv303):
    """A bypass coming back is still arriving at a point on a line.

    The station has five lines ending at a junction: four on the run, plus the
    bypass returning onto the fifth through a tee whose branch is an inlet.
    Drawn as a PFD, which is the sheet that carries arrowheads at all.
    """
    heads = heads_by_destination(cv303, diagram="pfd")
    junctions = {end: head for end, head in heads.items() if end[0].startswith("TEE")}
    assert len(junctions) == 5
    assert ("TEE (4)", "branch") in junctions  # the bypass return
    assert not any(junctions.values())
    assert all(head for end, head in heads.items() if not end[0].startswith("TEE"))


def test_the_junction_is_the_only_symbol_drawn_as_bare_pipe():
    """The rule is keyed on what the symbol draws, not on the ``Tee`` class, so
    this is what says how far it reaches. Every other in-line device -- a valve,
    a reducer, a fitting -- draws a body the arrowhead lands against."""
    from pandid.render.symbols import default_registry

    bare = sorted(key for key, symbol in default_registry._symbols.items() if symbol.bare_run)
    assert bare == [("tee", "default")]


def test_the_station_validates_clean(cv303):
    assert cv303.validate() == []


def test_the_bypass_and_the_drains_are_drawn(cv303):
    """The three branch legs reach the devices on them, off the run."""
    cv303.to_svg(diagram="p&id")
    by_name = {u.name: u for u in cv303.units}
    for tag, expect_y in (("HV-303C", BYPASS_Y), ("HV-303D", DRAIN_Y)):
        valve = by_name[tag]
        assert valve.frame is not None
        point = port_point(valve, valve.frame, "inlet")
        assert round(point[1] if tag == "HV-303C" else point[1]) == round(expect_y)
        assert point[1] != RUN_Y


# ---------------------------------------------------------------------------
# The equipment list
# ---------------------------------------------------------------------------


def test_a_tee_is_not_equipment(cv303):
    assert equipment_list(cv303).rows == []


def test_a_tee_still_has_a_name_for_an_explicit_schedule(cv303):
    """``include=`` takes whatever it names, which is how a piping schedule is
    built from the same flowsheet."""
    rows = equipment_list(cv303, include=["TEE", "TEE (2)"]).rows
    assert rows == [("TEE", "Pipe Tee"), ("TEE (2)", "Pipe Tee")]


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------


def test_the_run_keeps_one_number_through_its_tees_and_each_branch_takes_its_own(
    cv303,
):
    numbers = {}
    for stream in cv303.streams:
        numbers.setdefault(stream.name, 0)
        numbers[stream.name] += 1
    assert numbers == {
        "AE-303-80-80-SS": 9,  # the whole run, four tees and three devices
        "AE-318-80-80-SS": 2,  # the bypass leg, across its own valve
        "AE-319-25-80-SS": 1,
        "AE-320-25-80-SS": 1,
    }


def test_a_new_line_number_tee_breaks_the_run_number():
    fs = Flowsheet("t")
    feed = fs.add(units.Feed("F"))
    tee = fs.add(units.Tee())
    drain = fs.add(units.Valve("HV-1"))
    prod = fs.add(units.Product("P"))
    upstream = fs.connect(feed.outlet, tee.inlet)
    downstream = fs.connect(tee.outlet, prod.inlet)
    fs.connect(tee.branch, drain.inlet)
    assert upstream.name == downstream.name
    tee.new_line_number = True
    assert upstream.name != downstream.name


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------


def test_a_station_round_trips_through_the_spec(cv303):
    data = cv303.to_dict()
    rebuilt = Flowsheet.from_dict(data)
    assert rebuilt.to_dict() == data
    assert rebuilt.to_svg(diagram="p&id") == cv303.to_svg(diagram="p&id")


def test_the_spec_writes_a_tees_name_because_it_has_no_tag(cv303):
    tees = [u for u in cv303.to_dict()["units"] if u["kind"] == "Tee"]
    assert [t["name"] for t in tees] == ["TEE", "TEE (2)", "TEE (3)", "TEE (4)"]


def test_the_spec_writes_the_branch_direction_only_when_it_is_a_return(cv303):
    tees = [u for u in cv303.to_dict()["units"] if u["kind"] == "Tee"]
    assert [t.get("branch") for t in tees] == [None, None, None, "inlet"]


# ---------------------------------------------------------------------------
# branch_direction is the port's own (#292)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("branch", ["outlet", "inlet"])
def test_the_branch_direction_is_read_off_the_nozzle(branch):
    tee = units.Tee("T-1", branch=branch)
    assert tee.branch_direction == tee.ports["branch"].direction == branch


def test_the_branch_direction_cannot_be_assigned():
    """It was a plain attribute until #292, and assigning it moved the word.

    The nozzle stayed where it was, so the tee reported a return while its
    branch went on taking flow off the run -- and :mod:`pandid.spec` wrote the
    word rather than the nozzle, so the file said the same wrong thing.
    """
    tee = units.Tee("T-1")
    with pytest.raises(AttributeError, match="read-only"):
        tee.branch_direction = "inlet"
    assert tee.branch_direction == tee.ports["branch"].direction == "outlet"


def test_the_branch_direction_is_derived_and_so_cannot_shadow_the_nozzle():
    """One fact, read in both places.

    Reaching into ``ports`` is not an API this class offers -- it is how the
    test says there is nothing kept beside the nozzle to fall out of step with
    it. The serialiser is asked in the same breath, because #292 was as much
    about what went into the file as about what the object reported.
    """
    fs = Flowsheet("s")
    tee = fs.add(units.Tee("T-1"))
    tee.ports["branch"].direction = "inlet"
    assert tee.branch_direction == "inlet"
    (entry,) = fs.to_dict()["units"]
    assert entry["branch"] == "inlet"


@pytest.mark.parametrize("branch", ["outlet", "inlet"])
def test_a_tee_comes_back_from_the_spec_branching_the_way_it_went_in(branch):
    """Asserted on the rebuilt tee, not on its dict.

    A dict comparison is satisfied by a value the writer drops and the reader
    never sees, which is exactly the shape of #276 and #316. The question here
    is what the *object* on the far side does, so that is what is asked.
    """
    fs = Flowsheet("s")
    fs.add(units.Tee("T-1", branch=branch))
    (rebuilt,) = Flowsheet.from_dict(fs.to_dict()).units
    assert rebuilt.branch_direction == branch
    assert rebuilt.ports["branch"].direction == branch


def test_only_a_tee_takes_a_branch_direction():
    from pandid.spec import SpecError

    with pytest.raises(SpecError, match="only a Tee takes 'branch'"):
        Flowsheet.from_dict(
            {"name": "s", "units": [{"kind": "Valve", "name": "V", "branch": "inlet"}]}
        )


def test_a_spec_can_name_a_tee_by_its_kind():
    fs = Flowsheet.from_dict(
        {"name": "s", "units": [{"kind": "tee", "name": "T-1", "branch": "inlet"}]}
    )
    (tee,) = fs.units
    assert isinstance(tee, units.Tee)
    assert tee.branch.direction == "inlet"


# ---------------------------------------------------------------------------
# What the reference measures out at
# ---------------------------------------------------------------------------


def test_the_branch_is_drawn_at_the_weight_of_the_run(cv303):
    """0.75 pt on the reference for both; 2 units here for both."""
    from pandid.render.symbols import default_registry

    svg = cv303.to_svg(diagram="p&id")
    branch = [s for s in cv303.streams if s.name.startswith("AE-319")]
    assert branch, "the drain leg is a stream like any other"
    assert 'stroke-width="2"' in default_registry.get("tee").svg
    assert re.search(r'stroke="black" stroke-width="2"', svg)
