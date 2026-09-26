"""Acceptance and isolation of completed-route geometry trials."""

from __future__ import annotations

import copy
from dataclasses import replace

from pandid import Flowsheet, units as U
from pandid.layout.quality import admissible, measure_final
from pandid.layout.trials import evaluate_trial
from pandid.routing.metrics import crossing_count


def _branched_sheet() -> Flowsheet:
    """Build a pinned feed and two routed branches.

    Returns
    -------
    Flowsheet
        Settled drawing with one exact author pin and an automatic fork.
    """
    fs = Flowsheet("Trial isolation")
    feed = fs.add(U.Feed("Feed"))
    separator = fs.add(U.Separator("Separator"))
    vapor = fs.add(U.Product("Vapor"))
    liquid = fs.add(U.Product("Liquid"))
    feed.pin(x=50, y=50)
    fs.connect(feed.outlet, separator.feed)
    fs.connect(separator.vapor, vapor.inlet)
    fs.connect(separator.liquid, liquid.inlet)
    fs.layout()
    fs.route()
    return fs


def test_rejected_trial_preserves_live_geometry_and_identity() -> None:
    """Rejecting a longer branch leaves every original object untouched.

    Returns
    -------
    None
        The assertions establish live identity and geometry preservation.
    """
    fs = _branched_sheet()
    fs.streams[2].route.used_fallback = True
    fs.streams[2].via(list(fs.streams[2].route.waypoints))
    assert not fs.streams[2].route.used_fallback
    units = list(fs.units)
    streams = list(fs.streams)
    frames = [copy.deepcopy(unit.frame) for unit in units]
    slots = [copy.deepcopy(unit._slot) for unit in units]
    routes = [copy.deepcopy(stream.route) for stream in streams]
    pins = [unit.pin_ for unit in units]
    before = measure_final(fs)
    result = evaluate_trial(fs, lambda frames: setattr(frames[2], "x", frames[2].x + 500))
    assert not result.qualified
    assert measure_final(fs) == before
    assert all(actual is original for actual, original in zip(fs.units, units))
    assert all(actual is original for actual, original in zip(fs.streams, streams))
    assert [unit.frame for unit in units] == frames
    assert [unit._slot for unit in units] == slots
    assert [stream.route for stream in streams] == routes
    assert [unit.pin_ for unit in units] == pins
    assert fs.route_converged


def test_qualifying_trial_is_repeatable_and_does_not_publish_geometry() -> None:
    """A shorter final route qualifies without changing the live drawing.

    Returns
    -------
    None
        The assertions cover qualification, isolation, and repeatability.
    """
    fs = _branched_sheet()
    canonical_x = fs.units[2].frame.x
    fs.units[2].frame.x += 500
    fs.route()
    units = list(fs.units)
    streams = list(fs.streams)

    def restore_branch(frames: list) -> None:
        """Set the trial branch to its canonical resolved coordinate.

        Parameters
        ----------
        frames : list
            Detached candidate frames in unit order.

        Returns
        -------
        None
            The detached frame is updated in place.
        """
        frames[2].x = canonical_x

    result = evaluate_trial(fs, restore_branch)
    assert result.qualified
    assert result.after.length < result.before.length
    assert all(actual is original for actual, original in zip(fs.units, units))
    assert all(actual is original for actual, original in zip(fs.streams, streams))
    assert measure_final(fs) == result.before
    assert evaluate_trial(fs, restore_branch) == result
    assert measure_final(fs) == result.before


def test_trial_cannot_qualify_by_mirroring_an_author_transform() -> None:
    """A numeric route gain cannot alter a unit's resolved mirror state.

    Returns
    -------
    None
        The assertion protects author-owned symbol transforms.
    """
    fs = _branched_sheet()
    canonical_x = fs.units[2].frame.x
    fs.units[2].frame.x += 500
    fs.route()

    def mirror_and_restore(frames: list) -> None:
        """Shorten a branch while reversing its product symbol.

        Parameters
        ----------
        frames : list
            Detached proposed frames in unit order.

        Returns
        -------
        None
            The proposed product frame is changed.
        """
        frames[2].x = canonical_x
        frames[2].mirrored = not frames[2].mirrored

    result = evaluate_trial(fs, mirror_and_restore)
    assert result.after.length < result.before.length
    assert not result.qualified
    assert not fs.units[2].frame.mirrored


def test_nonconvergent_geometry_is_never_admissible() -> None:
    """A shorter candidate still fails when its final routes do not settle.

    Returns
    -------
    None
        The assertion protects the absolute convergence requirement.
    """
    current = measure_final(_branched_sheet())
    hard = list(current.hard)
    hard[6] = 1
    nonconvergent = replace(current, hard=tuple(hard))
    improved = replace(nonconvergent, length=nonconvergent.length * 0.5)
    assert not admissible(nonconvergent, improved)


def test_pin_violation_cannot_move_to_another_unit() -> None:
    """Keep each pinned unit fixed even when warning totals remain equal.

    Returns
    -------
    None
        The assertion rejects a swapped pin violation despite a shorter route.
    """
    fs = _branched_sheet()
    fs.units[2].pin(x=500, y=50)
    fs.layout()
    fs.route()
    fs.units[0].frame.x += 10
    fs.units[3].frame.x += 500
    fs.route()

    def swap_pin_and_shorten(frames: list) -> None:
        """Move one pin violation to another unit and shorten a branch.

        Parameters
        ----------
        frames : list
            Detached proposed frames in unit order.

        Returns
        -------
        None
            Three proposed coordinates are updated.
        """
        frames[0].x -= 10
        frames[2].x += 10
        frames[3].x -= 500

    result = evaluate_trial(fs, swap_pin_and_shorten)
    assert result.before.hard == result.after.hard
    assert result.after.length < result.before.length
    assert not result.qualified


def test_crossings_count_only_between_streams() -> None:
    """Ignore endpoint touches and a route's own crossings.

    Returns
    -------
    None
        The assertion fixes the final-path crossing convention.
    """
    paths = [
        [(0, 5), (10, 5)],
        [(5, 0), (5, 10)],
        [(0, 0), (0, 5)],
    ]
    assert crossing_count(paths) == 1
