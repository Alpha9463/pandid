"""Score proposed geometry without changing the live drawing."""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, cast

from pandid.layout.quality import Quality, admissible, improves, measure_final
from pandid.layout.settle import settle

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Frame
    from pandid.layout.candidates import Move
    from pandid.routing import Router


MIN_ESTIMATED_GAIN_FRACTION = 0.004


@dataclass(frozen=True)
class TrialResult:
    """Completed-route measurements for a proposed geometry change.

    Attributes
    ----------
    qualified : bool
        Whether the candidate meets the measured per-sheet gate. This is
        a dry-run result; it is not published on the original drawing.
    before, after : Quality
        Original and proposed final-drawing measurements.
    """

    qualified: bool
    before: Quality
    after: Quality


def _legacy_geometry_state(fs: Flowsheet) -> tuple:
    """Capture face and label geometry for the default trial path.

    Parameters
    ----------
    fs : Flowsheet
        Settled legacy trial drawing.

    Returns
    -------
    tuple
        Frame boxes, selected faces, and label positions.
    """
    return tuple(
        None
        if unit.frame is None
        else (
            unit.frame.x,
            unit.frame.y,
            unit.frame.w,
            unit.frame.h,
            unit.frame.label_pos,
            tuple(sorted(unit.frame.port_faces.items())),
        )
        for unit in fs.units
    )


def _settle_legacy(
    fs: Flowsheet,
    router: Router | None,
    face_choices: tuple[tuple[int, str, str], ...],
) -> None:
    """Retain the existing default-refinement trial settlement.

    Parameters
    ----------
    fs : Flowsheet
        Detached drawing with proposed frames installed.
    router : Router or None
        Router used on each bounded pass.
    face_choices : tuple[tuple[int, str, str], ...]
        Trial-only automatic face preferences.

    Returns
    -------
    None
        Legacy final geometry is stored on the candidate.
    """
    from pandid.layout.attach import MAX_PLACEMENT_PASSES
    from pandid.layout.control import place_control
    from pandid.layout.coordinates import assign_labels
    from pandid.layout.faces import select_faces
    from pandid.routing import DefaultRouter

    if router is None:
        router = DefaultRouter()
    preferred = {(index, port): face for index, port, face in face_choices}
    fs.route_converged = False
    moved = False
    for _ in range(MAX_PLACEMENT_PASSES):
        select_faces(fs, preferred)
        assign_labels(fs)
        before_route = _legacy_geometry_state(fs)
        router.route(fs)
        moved = place_control(fs)
        if not moved and _legacy_geometry_state(fs) == before_route:
            fs.route_converged = True
            fs._route_stale = False
            return
    if moved:
        router.route(fs)
    fs._route_stale = False


def _evaluate_candidate(
    fs: Flowsheet,
    move: Callable[[list[Frame | None]], None],
    router: Router | None = None,
    *,
    face_choices: tuple[tuple[int, str, str], ...] = (),
    canonical: bool = False,
    before: Quality | None = None,
) -> tuple[TrialResult, Flowsheet]:
    """Settle and score a proposed drawing on an isolated copy.

    Parameters
    ----------
    fs : Flowsheet
        Current settled drawing. The function never writes to it.
    move : Callable[[list[Frame | None]], None]
        Change a detached, index-aligned list of proposed frames. The
        callback receives no model objects, pins, routes, or topology.
    router : Router or None, optional
        Router used to settle the candidate's completed geometry.
    face_choices : tuple[tuple[int, str, str], ...], optional
        Trial-only automatic face preferences. They never modify author
        nozzle choices and must survive final face selection to qualify.
    canonical : bool, optional
        Use the opt-in final-box settlement contract when true.
    before : Quality or None, optional
        Already-measured quality of ``fs`` for repeated search trials.

    Returns
    -------
    tuple[TrialResult, Flowsheet]
        Measurements and the fully settled candidate drawing.

    Raises
    ------
    ValueError
        If the original drawing has stale geometry or a requested face
        is not an available automatic choice.
    """
    from pandid.layout.faces import eligible_faces

    if before is None:
        before = measure_final(fs)
    seen: set[tuple[int, str]] = set()
    for index, port, face in face_choices:
        if not 0 <= index < len(fs.units):
            raise ValueError("trial face unit index is out of range")
        key = index, port
        if key in seen:
            raise ValueError("trial requests two faces for one port")
        seen.add(key)
        if port not in fs.units[index].ports or face not in eligible_faces(
            fs, fs.units[index], port
        ):
            raise ValueError("trial face is not an eligible automatic choice")
    candidate = copy.deepcopy(fs)
    frames = [unit.frame for unit in candidate.units]
    move(frames)
    if len(frames) != len(candidate.units):
        raise ValueError("a layout trial must preserve the number of unit frames")
    for unit, frame in zip(candidate.units, frames):
        unit.frame = frame
    candidate._route_stale = True
    if canonical:
        settle(candidate, router, face_choices=face_choices)
    else:
        _settle_legacy(candidate, router, face_choices)
    after = measure_final(candidate)
    faces_held = all(
        candidate.units[index].frame is not None
        and candidate.units[index].frame.port_faces.get(port) == face
        for index, port, face in face_choices
    )
    result = TrialResult(
        qualified=faces_held and admissible(before, after) and improves(before, after),
        before=before,
        after=after,
    )
    return result, candidate


def evaluate_trial(
    fs: Flowsheet,
    move: Callable[[list[Frame | None]], None] | Move,
    router: Router | None = None,
    *,
    face_choices: tuple[tuple[int, str, str], ...] = (),
) -> TrialResult:
    """Score a proposed drawing without changing the live drawing.

    Parameters
    ----------
    fs : Flowsheet
        Settled drawing to assess.
    move : Callable[[list[Frame or None]], None] or Move
        Change detached, index-aligned frames on a clone.
    router : Router or None, optional
        Router used to settle the candidate.
    face_choices : tuple[tuple[int, str, str], ...], optional
        Requested automatic faces for the trial.

    Returns
    -------
    TrialResult
        Final-drawing measurements and qualification.

    Raises
    ------
    ValueError
        If geometry is stale or a requested face is ineligible.
    """
    from pandid.layout.candidates import Move

    operation = move.apply if isinstance(move, Move) else move
    result, _ = _evaluate_candidate(fs, operation, router, face_choices=face_choices)
    return result


def _publish_candidate(fs: Flowsheet, candidate: Flowsheet) -> None:
    """Copy accepted derived geometry onto the original drawing.

    Parameters
    ----------
    fs : Flowsheet
        Live drawing whose model identities and author intent are retained.
    candidate : Flowsheet
        Settled and qualified clone of the same drawing.

    Returns
    -------
    None
        Frames, automatic routes, control taps, and placement status are
        updated on the live drawing.
    """
    from pandid.units import Instrument

    for live, settled in zip(fs.units, candidate.units):
        live.frame = copy.deepcopy(settled.frame)
        if isinstance(live, Instrument):
            live.tap = copy.deepcopy(settled.tap)
    for live, settled in zip(fs.streams, candidate.streams):
        if live.route is None or not live.route.manual:
            live.route = copy.deepcopy(settled.route)
    index_of = {id(unit): index for index, unit in enumerate(candidate.units)}
    fs.unplaced_instruments = [
        fs.units[index_of[id(unit)]] for unit in candidate.unplaced_instruments
    ]
    fs.route_converged = candidate.route_converged
    fs._layout_stale = False
    fs._route_stale = False


def refine_default(fs: Flowsheet, *, max_trials: int = 1) -> bool:
    """Publish the first qualifying local proposal within a fixed budget.

    Parameters
    ----------
    fs : Flowsheet
        Settled drawing routed with the default router.
    max_trials : int, optional
        Maximum number of fully routed proposals to assess.

    Returns
    -------
    bool
        Whether an accepted proposal changed the drawing.
    """
    from pandid.layout.candidates import generate
    from pandid.routing.metrics import path_length

    if max_trials <= 0:
        return False
    total_length = sum(
        path_length(stream.route.waypoints) for stream in fs.streams if stream.route is not None
    )
    for proposal in generate(fs, limit=max_trials):
        # Skip an exact route when its cheap estimate is negligible beside
        # the complete drawing. This keeps large low-value trials bounded.
        if proposal.estimated_gain < total_length * MIN_ESTIMATED_GAIN_FRACTION:
            continue
        result, candidate = _evaluate_candidate(
            fs, proposal.apply, face_choices=proposal.face_choices
        )
        if result.qualified:
            from pandid.layout.stages import process_units

            fs._search_seed_frames = tuple(
                cast("Frame", copy.deepcopy(unit.frame)) for unit in process_units(fs)
            )
            _publish_candidate(fs, candidate)
            return True
    return False


def refine_rows(fs: Flowsheet) -> bool:
    """Try independent column-row spacing against completed routes.

    Parameters
    ----------
    fs : Flowsheet
        Completed default drawing to improve without changing its model.

    Returns
    -------
    bool
        Whether a routed compact-row trial replaced the current drawing.
    """
    from pandid.layout import default_layout_engine
    from pandid.layout.coarse import has_free_station
    from pandid.layout.stages import process_units, slot

    if has_free_station(fs) or any(stream._logical_to is not None for stream in fs.streams):
        return False

    before = measure_final(fs)
    warnings = Counter(issue.code for issue in fs.validate() if issue.severity == "warning")
    seed_y = tuple(slot(unit).y for unit in process_units(fs))
    winner: Flowsheet | None = None
    best = (before.hard, before.crossings, before.bends, before.length, before.area)
    for fraction in (0.25, 0.5, 0.75, 1.0):
        trial = copy.deepcopy(fs)
        default_layout_engine.layout(trial, row_compaction=fraction)
        if tuple(slot(unit).y for unit in process_units(trial)) == seed_y:
            continue
        trial._layout_stale = False
        trial._route_stale = True
        settle(trial)
        after = measure_final(trial)
        trial_warnings = Counter(
            issue.code for issue in trial.validate() if issue.severity == "warning"
        )
        if not _row_quality_better(before, after, warnings, trial_warnings):
            continue
        rank = (after.hard, after.crossings, after.bends, after.length, after.area)
        if rank < best:
            best = rank
            winner = trial
    if winner is None:
        return False
    _publish_candidate(fs, winner)
    fs._search_seed_frames = None
    return True


def _row_quality_better(before: Quality, after: Quality,
                        old_warnings: Counter[str], new_warnings: Counter[str]) -> bool:
    """Apply the completed-drawing gate to a row-spacing candidate.

    Parameters
    ----------
    before, after : Quality
        Baseline and proposed final geometry measurements.
    old_warnings, new_warnings : Counter[str]
        Validation warning counts by code for each drawing.

    Returns
    -------
    bool
        Whether every measured rule is preserved and one improves.
    """
    return (
        admissible(before, after)
        and after.bends <= before.bends
        and after.excess_bends <= before.excess_bends
        and after.length <= before.length + 1e-6
        and after.area <= before.area + 1e-6
        and all(count <= old_warnings[code] for code, count in new_warnings.items())
        and improves(before, after)
    )


def row_final_better(reference: Flowsheet, candidate: Flowsheet) -> bool:
    """Compare a compact-row drawing with the fully searched baseline.

    Parameters
    ----------
    reference, candidate : Flowsheet
        Completed baseline and compact-row drawings of the same model.

    Returns
    -------
    bool
        Whether the candidate improves without any measured regression.
    """
    before, after = measure_final(reference), measure_final(candidate)
    old_warnings = Counter(
        issue.code for issue in reference.validate() if issue.severity == "warning"
    )
    new_warnings = Counter(
        issue.code for issue in candidate.validate() if issue.severity == "warning"
    )
    return _row_quality_better(before, after, old_warnings, new_warnings)
