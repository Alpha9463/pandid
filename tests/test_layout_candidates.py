"""Legal, bounded placement proposals before final-route acceptance."""

from __future__ import annotations

import pytest

from pandid import Flowsheet, units as U
from pandid.layout.candidates import MAX_CANDIDATES, _groups, generate
from pandid.layout.faces import eligible_faces
from pandid.layout.quality import measure_final
from pandid.layout.stages import process_units
from pandid.layout.structure import infer
from pandid.layout.trials import evaluate_trial


def _off_lane() -> Flowsheet:
    """Build a straight material run with one displaced free pump.

    Returns
    -------
    Flowsheet
        Routed drawing with an avoidable dogleg.
    """
    fs = Flowsheet("Off-lane pump")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("P-1"))
    product = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    fs.layout()
    assert pump.frame is not None
    pump.frame.y += 70
    fs.route()
    return fs


def _diamond() -> Flowsheet:
    """Build two two-unit arms with shared split and merge.

    Returns
    -------
    Flowsheet
        Routed closed-branch drawing.
    """
    fs = Flowsheet("Closed arms")
    feed = fs.add(U.Feed("Feed"))
    split = fs.add(U.Splitter("Split"))
    a1 = fs.add(U.Pump("A1"))
    a2 = fs.add(U.Pump("A2"))
    b1 = fs.add(U.Pump("B1"))
    b2 = fs.add(U.Pump("B2"))
    merge = fs.add(U.Mixer("Merge", n_inlets=2))
    product = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, split.inlet)
    fs.connect(split.out_1, a1.suction)
    fs.connect(a1.discharge, a2.suction)
    fs.connect(a2.discharge, merge.in_1)
    fs.connect(split.out_2, b1.suction)
    fs.connect(b1.discharge, b2.suction)
    fs.connect(b2.discharge, merge.in_2)
    fs.connect(merge.outlet, product.inlet)
    fs.layout()
    fs.route()
    return fs


def test_off_lane_proposal_qualifies_without_changing_the_live_sheet() -> None:
    """A clear dogleg admits a deterministic, beneficial frame trial.

    Returns
    -------
    None
        The proposed group, completed-route gain, and isolation are checked.
    """
    fs = _off_lane()
    before = measure_final(fs)
    frames = tuple(unit.frame for unit in fs.units)
    routes = tuple(stream.route for stream in fs.streams)
    proposals = generate(fs)
    assert proposals == generate(fs)
    assert proposals[0].units == (1,)
    assert proposals[0].dy == -70
    trial = proposals[0].evaluate(fs)
    assert trial.qualified
    assert trial.after.length < trial.before.length
    assert measure_final(fs) == before
    assert tuple(unit.frame for unit in fs.units) == frames
    assert tuple(stream.route for stream in fs.streams) == routes


def test_closed_arms_do_not_offer_singleton_interior_or_shared_endpoint_moves() -> None:
    """Closed arms form groups and shared junctions cannot move alone.

    Returns
    -------
    None
        Every proposal respects the closed-branch grouping.
    """
    fs = _diamond()
    grouped = _groups(fs, infer(fs), process_units(fs))
    assert grouped[fs.units[2]] == (fs.units[2], fs.units[3])
    assert grouped[fs.units[4]] == (fs.units[4], fs.units[5])
    assert fs.units[1] not in grouped and fs.units[6] not in grouped
    for proposal in generate(fs):
        assert proposal.units not in ((1,), (2,), (3,), (4,), (5,), (6,))
        assert 1 not in proposal.units and 6 not in proposal.units
        assert (2 in proposal.units) == (3 in proposal.units)
        assert (4 in proposal.units) == (5 in proposal.units)


def test_pin_manual_route_and_explicit_nozzle_are_author_owned() -> None:
    """Candidate generation cannot move or re-face author geometry.

    Returns
    -------
    None
        Pinned and hand-routed endpoints are absent from proposals.
    """
    fs = _off_lane()
    pump = fs.units[1]
    pump.pin(y=pump.frame.y)
    pump.nozzle("suction", "W")
    fs.layout()
    fs.route()
    assert eligible_faces(fs, pump, "suction") == ()
    assert all(1 not in proposal.units for proposal in generate(fs))

    fs = _off_lane()
    pump = fs.units[1]
    assert fs.streams[0].route is not None
    fs.streams[0].via(list(fs.streams[0].route.waypoints))
    assert all(1 not in proposal.units for proposal in generate(fs))


def test_generation_is_bounded_and_repeatable_across_fresh_builds() -> None:
    """Fresh equivalent sheets yield the same ordered proposal values.

    Returns
    -------
    None
        The list is deterministic and never exceeds its fixed budget.
    """
    first = generate(_off_lane())
    second = generate(_off_lane())
    assert first == second
    assert 0 < len(first) <= MAX_CANDIDATES
    assert generate(_off_lane(), limit=1) == first[:1]


def test_preflight_rejects_port_escape_through_nearby_equipment() -> None:
    """A clear body gap is not enough room for a nozzle's outward lead.

    Returns
    -------
    None
        The pump is not proposed for an escape-blocking placement.
    """
    fs = Flowsheet("Blocked escape")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("Pump"))
    product = fs.add(U.Product("Product"))
    obstacle = fs.add(U.Pump("Obstacle"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    fs.layout()
    assert pump.frame is not None and obstacle.frame is not None
    aligned_y = pump.frame.y
    pump.frame.y += 70
    obstacle.frame.x = pump.frame.x + pump.frame.w + 10
    obstacle.frame.y = aligned_y
    fs.route()

    assert all(1 not in candidate.units for candidate in generate(fs))


def test_facing_ports_can_share_a_short_escape_gap() -> None:
    """A nearby connected endpoint can share the nozzle escape lane.

    Returns
    -------
    None
        The legal move survives preflight and qualifies after routing.
    """
    fs = Flowsheet("Shared escape")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("Pump"))
    product = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    fs.layout()
    assert pump.frame is not None and product.frame is not None
    aligned_y = pump.frame.y
    pump.frame.y += 70
    product.frame.x = pump.frame.x + pump.frame.w + 10
    product.frame.y = aligned_y
    fs.route()

    restored = next(
        candidate for candidate in generate(fs) if candidate.units == (1,) and candidate.dy == -70
    )
    assert evaluate_trial(fs, restored.apply).qualified


def test_automatic_face_proposal_qualifies_without_publishing_it() -> None:
    """A routed example can gain from a declared alternate nozzle face.

    Returns
    -------
    None
        The face choice qualifies while live geometry and routes stay fixed.
    """
    from scripts import layout_quality

    fs, _ = layout_quality.build("10_ethanol_pfd", True)
    fs.layout()
    fs.route()
    before = measure_final(fs)
    faces = tuple(dict(unit.frame.port_faces) for unit in fs.units)
    proposal = next(candidate for candidate in generate(fs) if candidate.face_choices)

    trial = proposal.evaluate(fs)
    assert trial.qualified
    assert trial.after.length < trial.before.length
    assert measure_final(fs) == before
    assert tuple(unit.frame.port_faces for unit in fs.units) == faces


def test_face_trial_rejects_an_author_fixed_nozzle() -> None:
    """An explicit nozzle face is unavailable to automatic trials.

    Returns
    -------
    None
        The trial refuses the override before creating a candidate.
    """
    fs = Flowsheet("Author nozzle")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Separator("Drum", variant="horizontal"))
    stream = fs.connect(feed.outlet, drum.feed)
    drum.nozzle("feed", "E")
    fs.layout()
    fs.route()

    with pytest.raises(ValueError, match="eligible automatic choice"):
        evaluate_trial(fs, lambda frames: None, face_choices=((1, stream.dest.name, "W"),))


def test_face_candidates_skip_a_nozzle_point_taken_by_an_earlier_port() -> None:
    """A later signal port cannot reuse its controller's occupied face.

    Returns
    -------
    None
        Feasible alternatives remain while the occupied face is absent.
    """
    fs = Flowsheet("Signal faces")
    valve = fs.add(U.Valve("FV-1", variant="control")).pin(x=300, y=180)
    feed = fs.add(U.Feed("Feed")).pin(x=100, y=175)
    product = fs.add(U.Product("Product")).pin(x=520, y=175)
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    transmitter = fs.add(U.Instrument("LT-101")).pin(x=300, y=400)
    controller = fs.add(U.Instrument("LIC-101", display="central")).pin(x=300, y=520)
    fs.connect(transmitter.sig_out, controller.sig_in, kind="electric")
    fs.connect(controller.sig_out, valve.actuator, kind="electric")
    fs.layout()
    fs.route()

    assert controller.frame.port_faces["sig_in"] == "N"
    choices = {candidate.face_choices for candidate in generate(fs) if candidate.face_choices}
    assert ((4, "sig_out", "E"),) in choices
    assert ((4, "sig_out", "N"),) not in choices
    invalid = evaluate_trial(fs, lambda frames: None, face_choices=((4, "sig_out", "N"),))
    assert not invalid.qualified
