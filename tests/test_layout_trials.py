"""Acceptance and isolation of completed-route geometry trials."""

from __future__ import annotations

import copy
import inspect
import sys
from collections import Counter
from dataclasses import replace

from pandid import Flowsheet, units as U
from pandid.layout import trials
from pandid.layout.quality import Quality, accepts, admissible, measure_final
from pandid.layout.settle import settle
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
    assert not admissible(nonconvergent, improved, preserve_crossing_pairs=True)


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


def test_every_trial_settles_with_the_one_settle_loop(monkeypatch) -> None:
    """Settle a refinement trial with ``settle``, as the search does (#574).

    The default trial ran a second loop of its own, which ended the pass cap
    differently and ignored a moved tap.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces ``settle`` with a recording wrapper.

    Returns
    -------
    None
        The trial settles once, through ``settle``.
    """
    fs = _branched_sheet()
    calls: list[tuple] = []

    def recording(candidate: Flowsheet, router=None, *, face_choices=()) -> None:
        """Record a settlement and run it.

        Parameters
        ----------
        candidate : Flowsheet
            Detached drawing being settled.
        router : Router or None, optional
            Router passed on.
        face_choices : tuple, optional
            Trial face preferences passed on.
        """
        calls.append(face_choices)
        settle(candidate, router, face_choices=face_choices)

    monkeypatch.setattr(trials, "settle", recording)
    evaluate_trial(fs, lambda frames: None)
    assert calls == [()]


def test_the_acceptance_gate_applies_the_mode_each_caller_states() -> None:
    """One gate, whose modes are stated by every caller (#574).

    It was written three times, and two defaulted to keeping crossing pairs
    where the third did not.

    Returns
    -------
    None
        Each mode refuses exactly what it names.
    """
    current = measure_final(_branched_sheet())
    smaller = replace(current, area=current.area * 0.9)
    assert accepts(current, smaller, preserve_crossing_pairs=True, strict=False)

    crossed = replace(smaller, crossing_pairs=current.crossing_pairs | {(98, 99)})
    assert not accepts(current, crossed, preserve_crossing_pairs=True, strict=False)
    assert accepts(current, crossed, preserve_crossing_pairs=False, strict=False)

    # Within the per-sheet 2 % allowance, which strict mode does not grant.
    longer = replace(smaller, length=current.length * 1.01)
    assert accepts(current, longer, preserve_crossing_pairs=True, strict=False)
    assert not accepts(current, longer, preserve_crossing_pairs=True, strict=True)

    same, more = Counter({"route-detour": 1}), Counter({"route-detour": 2})
    for warnings, expected in (((same, same), True), ((same, more), False)):
        verdict = accepts(
            current, smaller, preserve_crossing_pairs=True, strict=True, warnings=warnings
        )
        assert verdict == expected


def test_every_layout_caller_judges_through_the_one_gate_in_its_own_mode(monkeypatch) -> None:
    """Drive each acceptance caller and record how it asks the gate (#574).

    The gate was written three times, with ``preserve_crossing_pairs``
    defaulting to True in two copies and False in the third. A caller that
    judged a proposal inline again would not reach ``accepts`` and fails
    here, as would one that changed the mode it has always used; and no
    gate may default the mode.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces ``accepts`` with a recording wrapper, and the layout
        engine with one that moves a row so ``refine_rows`` reaches its gate.

    Returns
    -------
    None
        Each caller asks once per proposal, in the mode it has always used.
    """
    from pandid.layout import default_layout_engine, quality
    from pandid.layout.stages import process_units, slot

    for gate in (quality.accepts, quality.admissible):
        for mode in ("preserve_crossing_pairs", "strict", "preserve_size"):
            parameter = inspect.signature(gate).parameters.get(mode)
            assert parameter is None or parameter.default is inspect.Parameter.empty, (
                f"{gate.__name__} defaults {mode}"
            )

    asked: set[tuple[str, bool, bool, bool]] = set()
    real = quality.accepts

    def recording(
        before: Quality,
        after: Quality,
        *,
        preserve_crossing_pairs: bool,
        strict: bool,
        warnings: tuple[Counter[str], Counter[str]] | None = None,
    ) -> bool:
        """Record who asked the gate and in which mode, then ask it.

        Parameters
        ----------
        before, after : Quality
            Measurements passed on.
        preserve_crossing_pairs, strict : bool
            Mode passed on.
        warnings : tuple or None, optional
            Further check passed on.

        Returns
        -------
        bool
            The gate's verdict.
        """
        caller = sys._getframe(1).f_code.co_name
        asked.add(
            (caller, preserve_crossing_pairs, strict, warnings is not None)
        )
        return real(
            before,
            after,
            preserve_crossing_pairs=preserve_crossing_pairs,
            strict=strict,
            warnings=warnings,
        )

    fs = _branched_sheet()
    monkeypatch.setattr(quality, "accepts", recording)
    monkeypatch.setattr(trials, "accepts", recording)
    real_layout = default_layout_engine.layout

    def lowered(fs: Flowsheet, *, row_compaction: float) -> None:
        """Lay out as the engine does, then move the first row down 1 px.

        Parameters
        ----------
        fs : Flowsheet
            Trial drawing.
        row_compaction : float
            Row spacing ``refine_rows`` is trying, passed on.
        """
        real_layout(fs, row_compaction=row_compaction)
        first = slot(process_units(fs)[0])
        first.y = (first.y or 0.0) + 1.0

    monkeypatch.setattr(default_layout_engine, "layout", lowered)

    evaluate_trial(fs, lambda frames: None)
    trials.row_final_better(fs, fs)
    trials.refine_rows(copy.deepcopy(fs))
    # (caller, preserve_crossing_pairs, strict, warnings compared)
    assert asked == {
        ("_evaluate_candidate", True, False, False),
        ("row_final_better", True, True, True),
        ("refine_rows", True, True, True),
    }
