"""Complete stream paths shared by rendering and drawing measurements."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.portgeom import port_point

if TYPE_CHECKING:
    from pandid.streams import Stream

Point = tuple[float, float]


def stream_polyline(stream: Stream) -> list[Point]:
    """Return the line drawn between a stream's two nozzles.

    Parameters
    ----------
    stream : Stream
        Connected stream with placed endpoint units.

    Returns
    -------
    list[Point]
        Nozzle points and route waypoints with collinear points removed.

    Raises
    ------
    ValueError
        If either endpoint unit has no resolved frame.
    """
    source, dest = stream.source.owner, stream.dest.owner
    if source is None or dest is None or source.frame is None or dest.frame is None:
        raise ValueError("stream_polyline requires placed endpoint units")
    start = port_point(source, source.frame, stream.source.name)
    end = port_point(dest, dest.frame, stream.dest.name)
    points = [start, *(stream.route.waypoints if stream.route is not None else []), end]

    simplified = [points[0]]
    for index in range(1, len(points) - 1):
        previous, current, following = simplified[-1], points[index], points[index + 1]
        if previous[0] == current[0] == following[0] or previous[1] == current[1] == following[1]:
            continue
        simplified.append(current)
    simplified.append(points[-1])
    return simplified
