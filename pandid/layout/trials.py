"""Score proposed geometry without changing the live drawing."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from pandid.layout.quality import Quality, admissible, improves, measure_final

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Frame
    from pandid.routing import Router


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
    previous = _geometry_state(fs)
    fs.route_converged = False
    moved = False
    for _ in range(MAX_PLACEMENT_PASSES):
        select_faces(fs, preferred)
        assign_labels(fs)
        router.route(fs)
        moved = place_control(fs)
        current = _geometry_state(fs)
        if not moved and current == previous:
            fs.route_converged = True
            fs._route_stale = False
            return
        previous = current
    # As in Flowsheet.route(), six control checks may need a final route
    # so a nonconvergent drawing still ends on a path for its last boxes.
    if moved:
        router.route(fs)
    fs._route_stale = False


def evaluate_trial(
    fs: Flowsheet,
    move: Callable[[list[Frame | None]], None],
    router: Router | None = None,
    *,
    face_choices: tuple[tuple[int, str, str], ...] = (),
) -> TrialResult:
    """Score a frame proposal on a deep copy of a settled drawing.

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
    TrialResult
        Before/after quality and whether the proposal qualifies for
        later, reproducible integration. No result is copied back.

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
        if port not in fs.units[index].ports or face not in eligible_faces(fs, fs.units[index], port):
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
    return TrialResult(
        qualified=faces_held and admissible(before, after) and improves(before, after),
        before=before,
        after=after,
    )
