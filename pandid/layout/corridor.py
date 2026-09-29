"""Choose a straight leg between the endpoint nozzles of a material run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.portgeom import resolve_port

if TYPE_CHECKING:
    from pandid.units import Unit


def horizontal_centerline(
    source: Unit,
    source_port: str,
    dest: Unit,
    dest_port: str,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    require_clear_exit: bool = False,
) -> float | None:
    """Choose a horizontal leg from the endpoint nozzle geometry.

    Parameters
    ----------
    source, dest : Unit
        Equipment at the ends of the host run.
    source_port, dest_port : str
        Connected nozzle names on that equipment.
    start, end : tuple[float, float]
        Resolved nozzle coordinates.
    require_clear_exit : bool, optional
        Require a vertical nozzle to point toward a 25 px exit leg.

    Returns
    -------
    float or None
        Axis of a horizontal leg, or ``None`` without a legal leg.
    """
    assert source.frame is not None and dest.frame is not None
    source_face = resolve_port(source, source.frame, source_port).face
    dest_face = resolve_port(dest, dest.frame, dest_port).face
    forward = 1 if end[0] > start[0] else -1
    source_forward = (source_face == "E" and forward > 0) or (source_face == "W" and forward < 0)
    dest_forward = (dest_face == "W" and forward > 0) or (dest_face == "E" and forward < 0)
    if not require_clear_exit and abs(start[1] - end[1]) <= 1:
        return start[1]
    if (
        source_forward
        and dest_face not in ("E", "W")
        and (
            not require_clear_exit
            or (dest_face == "N" and start[1] <= end[1] - 25)
            or (dest_face == "S" and start[1] >= end[1] + 25)
        )
    ):
        return start[1]
    if (
        dest_forward
        and source_face not in ("E", "W")
        and (
            not require_clear_exit
            or (source_face == "N" and end[1] <= start[1] - 25)
            or (source_face == "S" and end[1] >= start[1] + 25)
        )
    ):
        return end[1]
    if require_clear_exit and source_forward and dest_forward and abs(start[1] - end[1]) <= 1:
        return start[1]
    return None
