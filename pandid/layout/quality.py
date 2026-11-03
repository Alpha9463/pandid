"""Measure a routed drawing: findings, crossings, bends and area."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid.layout.conflicts import Conflict, analyze_conflicts
from pandid.portgeom import port_anchor
from pandid.route_geometry import stream_polyline
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


@dataclass(frozen=True)
class Quality:
    """Hard findings and measured costs of one settled drawing.

    Attributes
    ----------
    hard : tuple[int, ...]
        Error, fallback, finding-code and undrawn-stream counts.
    """

    hard: tuple[int, ...]
    crossings: int
    bends: int
    excess_bends: int
    length: float
    area: float
    hard_conflicts: frozenset[Conflict] = frozenset()
    crossing_pairs: frozenset[tuple[int, int]] = frozenset()


def measure_final(fs: Flowsheet) -> Quality:
    """Measure the frames and routes of a laid-out and routed sheet."""
    if fs._layout_stale or fs._route_stale:
        raise ValueError("measure_final requires completed layout and routing")
    issues = fs.validate()
    codes = [issue.code for issue in issues]
    routes = [stream.route for stream in fs.streams]
    drawn_paths = [
        stream_polyline(stream)
        if stream.route is not None and stream.source.owner.frame is not None
        and stream.dest.owner.frame is not None else None
        for stream in fs.streams
    ]
    paths = [path for path in drawn_paths if path is not None]
    conflicts = analyze_conflicts(fs)
    hard_conflicts = frozenset(conflict for conflict in conflicts if conflict.kind != "crossing")
    pairs = frozenset(
        (conflict.streams[0], conflict.streams[1])
        for conflict in conflicts
        if conflict.kind == "crossing"
    )
    frames = [unit.frame for unit in fs.units if unit.frame is not None]
    area = 0.0
    if frames:
        area = (max(frame.x_max for frame in frames) - min(frame.x for frame in frames)) * (
            max(frame.y_max for frame in frames) - min(frame.y for frame in frames)
        )

    bends = 0
    excess = 0
    for stream, path in zip(fs.streams, drawn_paths):
        route = stream.route
        if route is None or path is None:
            continue
        actual = real_bends(path)
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
        sum(route is None or (not route.manual and len(route.waypoints) < 2)
            for route in routes),
    )
    return Quality(
        hard=hard,
        crossings=crossing_count(paths),
        bends=bends,
        excess_bends=excess,
        length=sum(path_length(path) for path in paths),
        area=area,
        hard_conflicts=hard_conflicts,
        crossing_pairs=pairs,
    )
