"""Close the empty bands across a routed drawing.

A band is a strip across the whole drawing that holds no unit, tag,
package frame, balloon standoff, line end or line run along it. Lines
only cross it, so moving everything on one side of it inward shortens
those lines and changes no route's shape. A line whose length places
something on it, or something at its end, holds all it spans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.layout.layered import COL_GAP, ROW_GAP

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: A band's start and end, the width taken out of it, and whether what
#: lies beyond it moves rather than what lies before it.
Cut = tuple[float, float, float, bool]
Span = tuple[float, float]


def _held(fs: Flowsheet, k: int) -> tuple[list[Span], list[Span]]:
    """Return the spans drawn things hold on one axis, and those pinned.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    k : int
        Axis: 0 for x, 1 for y.

    Returns
    -------
    tuple[list[Span], list[Span]]
        Each held ``(low, high)`` span, sorted, and the spans of the
        units pinned on the axis, of each manual route and of the units
        it joins.
    """
    from pandid.layout.attach import is_attached, stream_path
    from pandid.layout.control import _halos, _hangable
    from pandid.package import frame as package_frame
    from pandid.portgeom import unit_box
    from pandid.render.svg import _unit_label_box, package_labels, tap_route
    from pandid.streams import Stream

    def extent(points: list[tuple[float, float]]) -> Span:
        """Return the span of points on the axis.

        Parameters
        ----------
        points : list[tuple[float, float]]
            Points to span.

        Returns
        -------
        Span
            Lowest and highest coordinate.
        """
        return min(p[k] for p in points), max(p[k] for p in points)

    held: list[Span] = []
    fixed: list[Span] = []
    for u in fs.units:
        if u.frame is None:
            continue
        box = unit_box(u, u.frame)
        held.append((box[k], box[k + 2]))
        pin = u.pin_
        if pin is not None and (pin.x, pin.y)[k] is not None:
            fixed.append((box[k], box[k + 2]))
    held += [(h[k], h[k + 2]) for h in _halos(fs)]
    for pkg in fs.packages:
        frame = package_frame(pkg)
        if frame is None:
            continue
        held += [(frame[k], frame[k]), (frame[k + 2], frame[k + 2])]
        held += [(b[k], b[k + 2]) for b in map(_unit_label_box, package_labels(pkg, frame))
                 if b is not None]
    # A line drawn by hand, set out by fractions of its length, or from
    # a controller that may hang off the actuator it drives, holds all
    # it spans.
    measured = {id(u.host._logical_root or u.host) for u in fs.units
                if isinstance(getattr(u, "host", None), Stream)}
    hung = {id(u) for u in fs.units if _hangable(fs, u) is not None}
    for s in fs.streams:
        points = stream_path(s)
        if not points:
            continue
        root = s._logical_root or s
        manual = s.route is not None and s.route.manual
        if (manual or id(root) in measured or root._logical_segments
                or (id(s.source.owner) in hung and s.dest.name == "actuator")):
            held.append(extent(points))
        else:
            held += [(points[0][k], points[0][k]), (points[-1][k], points[-1][k])]
            held += [extent([a, b]) for a, b in zip(points, points[1:]) if a[1 - k] != b[1 - k]]
        if manual:
            fixed.append(extent(points))
            fixed += [(box[k], box[k + 2]) for box in (unit_box(p.owner, p.owner.frame)
                                                      for p in (s.source, s.dest)
                                                      if p.owner.frame is not None)]
    # An attached balloon holds all from its tap to its centre.
    for u in fs.units:
        tap = getattr(u, "tap", None)
        if tap is not None and u.frame is not None and is_attached(u):
            held.append(extent(tap_route(u, tap, (u.frame.cx, u.frame.cy))))
    return sorted(held), fixed


def empty_bands(fs: Flowsheet) -> tuple[list[Cut], list[Cut]]:
    """Return the cuts that close each empty band to the gap layout keeps.

    A band is cut to :data:`~pandid.layout.layered.COL_GAP` across the
    sheet and :data:`~pandid.layout.layered.ROW_GAP` down it, by whole
    pixels. What lies beyond it moves where nothing there is pinned on
    its axis, else what lies before it where nothing there is; a band
    with pins on both sides is kept.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    tuple[list[Cut], list[Cut]]
        Cuts across x, then down y; each list empty where none.
    """
    out: list[list[Cut]] = []
    for k, gap in ((0, COL_GAP), (1, ROW_GAP)):
        held, fixed = _held(fs, k)
        cuts: list[Cut] = []
        end = held[0][1] if held else 0.0
        for low, high in held[1:]:
            width = float(int(low - end - gap))
            beyond = any(a >= low for a, _ in fixed)
            if width > 0.0 and not (beyond and any(b <= end for _, b in fixed)):
                cuts.append((end, low, width, not beyond))
            end = max(end, high)
        out.append(cuts)
    return out[0], out[1]


def close_bands(fs: Flowsheet, cuts: tuple[list[Cut], list[Cut]]) -> None:
    """Move everything on the free side of each cut inward by its width.

    A point inside a band, which only a line crossing it can hold,
    moves by the same share of the width as of the band.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet the cuts were found on.
    cuts : tuple[list[Cut], list[Cut]]
        What :func:`empty_bands` returned.
    """
    from pandid.portgeom import unit_box

    def moved(v: float, k: int) -> float:
        """Return how far the cuts move a coordinate.

        Parameters
        ----------
        v : float
            Coordinate as drawn.
        k : int
            Its axis: 0 for x, 1 for y.

        Returns
        -------
        float
            Sum over the cuts of the width, or of its share inside a
            band, signed to move the free side toward the other.
        """
        out = 0.0
        for start, stop, width, far in cuts[k]:
            share = min(1.0, max(0.0, (v - start) / (stop - start)))
            out += -width * share if far else width * (1.0 - share)
        return out

    for u in fs.units:
        if u.frame is None:
            continue
        x0, y0, _, _ = unit_box(u, u.frame)
        u.frame.x += moved(x0, 0)
        u.frame.y += moved(y0, 1)
        tap = getattr(u, "tap", None)
        if tap is not None:
            u.tap = (tap[0] + moved(tap[0], 0), tap[1] + moved(tap[1], 1))
    for s in fs.streams:
        if s.route is not None and not s.route.manual:
            s.route.waypoints = [(x + moved(x, 0), y + moved(y, 1)) for x, y in s.route.waypoints]
