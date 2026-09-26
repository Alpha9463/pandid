"""Score proposed geometry without changing the live drawing."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from pandid.layout.quality import Quality, admissible, improves, measure_final

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


def _geometry_state(fs: Flowsheet) -> tuple:
    """Capture the geometry that can alter face and label selection.

    Parameters
    ----------
    fs : Flowsheet
        Candidate drawing after a settling pass.

    Returns
    -------
    tuple
        Frame positions, dimensions, automatic faces, and label sides.
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


def _settle_candidate(
    fs: Flowsheet,
    router: Router | None,
    face_choices: tuple[tuple[int, str, str], ...] = (),
) -> None:
    """Settle automatic faces, labels, controls, and routes on a clone.

    Parameters
    ----------
    fs : Flowsheet
        Candidate with proposed frames already installed.
    router : Router or None
        Router used for each bounded settling pass.
    face_choices : tuple[tuple[int, str, str], ...], optional
        Trial-only unit, port, and drawn-face preferences.

    Returns
    -------
    None
        Final derived geometry is stored on the candidate.
    """
    from pandid.layout.attach import MAX_PLACEMENT_PASSES
    from pandid.layout.coordinates import assign_labels
    from pandid.layout.control import place_control
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
        before_route = _geometry_state(fs)
        router.route(fs)
        moved = place_control(fs)
        if not moved and _geometry_state(fs) == before_route:
            fs.route_converged = True
            fs._route_stale = False
            return
    # As in Flowsheet.route(), six control checks may need a final route
    # so a nonconvergent drawing still ends on a path for its last boxes.
    if moved:
        router.route(fs)
    fs._route_stale = False


def _evaluate_candidate(
    fs: Flowsheet,
    move: Callable[[list[Frame | None]], None],
    router: Router | None = None,
    *,
    face_choices: tuple[tuple[int, str, str], ...] = (),
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
    frames = [copy.deepcopy(unit.frame) for unit in candidate.units]
    move(frames)
    if len(frames) != len(candidate.units):
        raise ValueError("a layout trial must preserve the number of unit frames")
    for unit, frame in zip(candidate.units, frames):
        unit.frame = frame
    candidate._route_stale = True
    _settle_candidate(candidate, router, face_choices)
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
            _publish_candidate(fs, candidate)
            return True
    return False
