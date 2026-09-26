"""Measure completed drawing geometry for isolated layout trials."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid.portgeom import pin_intent, port_anchor, port_point
from pandid.routing.metrics import crossing_count, min_bends, path_length, real_bends

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet


_HARD_CODES = (
    "unit-overlap",
    "route-crosses-unit",
    "pin-not-honored",
    "route-diagonal",
    "route-not-settled",
    "instrument-unplaced",
)
_NONCONVERGENCE_INDEX = 2 + _HARD_CODES.index("route-not-settled")


@dataclass(frozen=True)
class Quality:
    """Hard findings and measured costs of one settled drawing.

    Attributes
    ----------
    hard : tuple[int, ...]
        Error count, fallback count, named geometric findings, and undrawn
        stream count, in a stable order for pairwise comparison.
    crossings, bends, excess_bends : int
        Proper crossings and direction changes on final separated paths.
    length, area : float
        Total route length and frame bounding-box area in drawing pixels.
    author_intent : tuple
        Pins, explicit faces, and manual waypoints held by the model.
    frame_transform : tuple
        Resolved orientation and mirror choices for each unit.
    pin_geometry : tuple
        Drawn values of each pinned coordinate or rank, by unit and axis.
    """

    hard: tuple[int, ...]
    crossings: int
    bends: int
    excess_bends: int
    length: float
    area: float
    author_intent: tuple
    frame_transform: tuple
    pin_geometry: tuple


def _author_intent(fs: Flowsheet) -> tuple:
    """Capture author-owned geometry choices without object identities.

    Parameters
    ----------
    fs : Flowsheet
        Drawing model to inspect.

    Returns
    -------
    tuple
        Immutable pin, explicit-face, and manual-route values.
    """
    units = tuple(
        (unit._pin, tuple(sorted(unit._pin_ports.items())), tuple(sorted(unit._port_faces.items())))
        for unit in fs.units
    )
    manual = tuple(
        (index, tuple(stream.route.waypoints))
        for index, stream in enumerate(fs.streams)
        if stream.route is not None and stream.route.manual
    )
    return units, manual


def measure_final(fs: Flowsheet) -> Quality:
    """Measure the final frames and separated routes of a settled sheet.

    Parameters
    ----------
    fs : Flowsheet
        A sheet whose layout and route stages have completed.

    Returns
    -------
    Quality
        Drawing findings and costs for candidate acceptance.

    Raises
    ------
    ValueError
        If the sheet has stale geometry.
    """
    if fs._layout_stale or fs._route_stale:
        raise ValueError("measure_final requires completed layout and routing")
    issues = fs.validate()
    codes = [issue.code for issue in issues]
    routes = [stream.route for stream in fs.streams]
    paths = [route.waypoints for route in routes if route is not None]
    frames = [unit.frame for unit in fs.units if unit.frame is not None]
    area = 0.0
    if frames:
        area = (max(frame.x_max for frame in frames) - min(frame.x for frame in frames)) * (
            max(frame.y_max for frame in frames) - min(frame.y for frame in frames)
        )

    bends = 0
    excess = 0
    for stream in fs.streams:
        route = stream.route
        if route is None or not route.waypoints:
            continue
        actual = real_bends(route.waypoints)
        bends += actual
        if route.manual:
            continue
        source, dest = stream.source.owner, stream.dest.owner
        if source is None or dest is None or source.frame is None or dest.frame is None:
            continue
        x1, y1, face1 = port_anchor(source, source.frame, stream.source.name)
        x2, y2, face2 = port_anchor(dest, dest.frame, stream.dest.name)
        minimum = min_bends((x1, y1), face1, (x2, y2), face2)
        if minimum is not None:
            excess += max(0, actual - minimum)

    hard = (
        sum(issue.severity == "error" for issue in issues),
        sum(route is not None and not route.manual and route.used_fallback for route in routes),
        *(codes.count(code) for code in _HARD_CODES),
        sum(route is None or len(route.waypoints) < 2 for route in routes),
    )
    return Quality(
        hard=hard,
        crossings=crossing_count(paths),
        bends=bends,
        excess_bends=excess,
        length=sum(path_length(path) for path in paths),
        area=area,
        author_intent=_author_intent(fs),
        frame_transform=tuple(
            None
            if unit.frame is None
            else (unit.frame.orientation, unit.frame.mirrored, unit.frame.mirror_y)
            for unit in fs.units
        ),
        pin_geometry=tuple(
            None
            if unit.frame is None
            else (
                tuple(
                    (
                        axis,
                        port_point(unit, unit.frame, port_name)[0 if axis == "x" else 1]
                        if port_name is not None
                        else getattr(unit.frame, axis),
                    )
                    for axis, (port_name, _) in sorted(pin_intent(unit).items())
                ),
                tuple(
                    (axis, getattr(unit.frame, axis))
                    for axis, absolute in (("col", "x"), ("row", "y"))
                    if unit.pin_ is not None
                    and getattr(unit.pin_, axis) is not None
                    and getattr(unit.pin_, absolute) is None
                ),
            )
            for unit in fs.units
        ),
    )


def admissible(before: Quality, after: Quality) -> bool:
    """Check the per-sheet hard and soft regression limits.

    Parameters
    ----------
    before, after : Quality
        Measurements of the current and proposed completed drawing.

    Returns
    -------
    bool
        Whether the candidate preserves author intent and stays within
        every measured per-sheet limit. Improvement is checked separately.
    """
    return (
        before.author_intent == after.author_intent
        and before.frame_transform == after.frame_transform
        and before.pin_geometry == after.pin_geometry
        and all(new <= old for old, new in zip(before.hard, after.hard))
        and after.hard[_NONCONVERGENCE_INDEX] == 0
        and after.crossings <= before.crossings
        and after.bends <= min(before.bends + 1, before.bends * 1.03)
        and after.length <= before.length * 1.02 + 0.1
        and after.area <= before.area * 1.02 + 1.0
    )


def improves(before: Quality, after: Quality) -> bool:
    """Check for a measured gain large enough to justify a trial.

    Parameters
    ----------
    before, after : Quality
        Current and proposed final-drawing measurements.

    Returns
    -------
    bool
        True when at least one hard finding, crossing, excess bend, or
        material length or area cost decreases.
    """
    return (
        any(new < old for old, new in zip(before.hard, after.hard))
        or after.crossings < before.crossings
        or after.excess_bends < before.excess_bends
        or after.length < before.length * 0.98 - 0.1
        or after.area < before.area * 0.98 - 1.0
    )
