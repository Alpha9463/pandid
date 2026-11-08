"""Close the empty bands across a routed drawing.

A band is a strip across the whole drawing that holds no unit, tag,
package frame, placed annotation, balloon standoff, line end, line run
along it or waypoint drawn by hand. Lines only cross it, so moving
everything on one side of it inward shortens those lines and changes
no automatic route's shape. A line whose length places something on
it, or something at its end, holds all it spans. Waypoints drawn by
hand and placed annotations stay where the author put them.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from pandid.layout.layered import COL_GAP, ROW_GAP

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: A band's start and end, the width taken out of it (added where
#: negative), and whether what lies beyond it moves rather than what
#: lies before it.
Cut = tuple[float, float, float, bool]
#: A low and a high coordinate on one axis.
Span = tuple[float, float]


def placed(fs: Flowsheet) -> list[tuple[float, float, float, float]]:
    """Return the box of each annotation placed by ``position``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.

    Returns
    -------
    list[tuple[float, float, float, float]]
        Boxes as left, top, right, bottom.
    """
    from pandid.document import TableBox
    from pandid.render import furniture

    out = []
    for a in fs.annotations:
        position = getattr(a, "position", None)
        if position is not None:
            w, h = (furniture.measure_table(a) if isinstance(a, TableBox)
                    else furniture.measure_annotation(a))
            out.append((position[0], position[1], position[0] + w, position[1] + h))
    return out


def covered(fs: Flowsheet) -> set[tuple]:
    """Return what is drawn over a placed annotation.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    set[tuple]
        The keys of :func:`covering`.
    """
    return set(covering(fs))


def covering(fs: Flowsheet) -> dict[tuple, set[int]]:
    """Return what is drawn over each placed annotation.

    Labels are placed as the SVG and draw.io backends place them, with
    and without a P&ID's joint marking and with either jump direction.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    dict[tuple, set[int]]
        A key for each unit, line (with the limits, tie-ins and spec
        breaks marked on it), tag or letter beside a unit, package label,
        letter code, line number and number leader that meets a placed
        annotation, by name, so keys from two drawings of a sheet
        compare, and the indexes in :func:`placed` of the annotations it
        meets.
    """
    from pandid.layout.attach import stream_path
    from pandid.layout.conflicts import boxes_overlap, segment_crosses_box
    from pandid.package import frame as package_frame
    from pandid.portgeom import unit_box
    from pandid.render.line_markers import line_markers
    from pandid.render.svg import (_unit_label_box, drawn_codes, package_labels,
                                   resolve_connections, stream_hops, stream_numbers,
                                   unit_tags)

    notes = placed(fs)
    if not notes:
        return {}

    def over(box: tuple | None) -> set[int]:
        """Return the placed annotations a box meets.

        Parameters
        ----------
        box : tuple or None
            Box as left, top, right, bottom, or ``None``.

        Returns
        -------
        set[int]
            Their indexes in ``notes``.
        """
        if box is None:
            return set()
        return {i for i, note in enumerate(notes) if boxes_overlap(box, note)}

    def crosses(points: list) -> set[int]:
        """Return the placed annotations a polyline enters.

        Parameters
        ----------
        points : list
            Polyline points.

        Returns
        -------
        set[int]
            Their indexes in ``notes``.
        """
        return {i for i, note in enumerate(notes)
                if any(segment_crosses_box(a, b, note) for a, b in zip(points, points[1:]))}

    out: dict[tuple, set[int]] = {}

    def add(key: tuple, hit: set[int]) -> None:
        """Record the annotations a drawn thing meets.

        Parameters
        ----------
        key : tuple
            What is drawn.
        hit : set[int]
            Indexes of the annotations it meets, possibly none.
        """
        if hit:
            out.setdefault(key, set()).update(hit)

    for u in fs.units:
        if u.frame is not None:
            add(("unit", u.name), over(unit_box(u, u.frame)))
    markers: dict[int, set[int]] = {}
    for drawn in line_markers(fs):
        markers.setdefault(id(drawn.stream), set()).update(over(drawn.box))
    for s in fs.streams:
        add(("line", s.name), crosses(stream_path(s)) | markers.get(id(s), set()))
    frames = [(pkg, package_frame(pkg)) for pkg in fs.packages]
    packages = [((pkg.name, k), item) for pkg, frame in frames if frame is not None
                for k, item in enumerate(package_labels(pkg, frame))]
    # Place labels once for each joint marking and jump direction that
    # draws the sheet differently.
    marked = any(resolve_connections(p, None) != resolve_connections(p, "none")
                 for s in fs.streams for p in (s, *s._logical_segments))
    hopped = stream_hops(fs, "vertical") != stream_hops(fs, "horizontal")
    for joints in (None, "none") if marked else (None,):
        for direction in ("vertical", "horizontal") if hopped else ("vertical",):
            items = packages + [((u.name, k), item) for u, _, drawn in unit_tags(fs, joints, direction)
                                for k, item in enumerate(drawn)]
            for key, item in items:
                add(("label", key), over(_unit_label_box(item)))
            labels = [b for b in (_unit_label_box(item) for _, item in items) if b is not None]
            numbers = stream_numbers(fs, labels, joints, direction)
            for n in numbers:
                add(("number", n.name), over(n.words) | over(n.box))
                if n.leader is not None:
                    add(("leader", n.name), crosses(list(n.leader)))
            for k, item in enumerate(drawn_codes(fs, joints, direction, labels)):
                add(("code", (k, item[5])), over(_unit_label_box(item)))
    return out


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
        units pinned on the axis or held where a ``via()`` line met them.
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
        if (pin is not None and (pin.x, pin.y)[k] is not None) or id(u) in fs._typed_at:
            fixed.append((box[k], box[k + 2]))
    held += [(h[k], h[k + 2]) for h in _halos(fs)]
    for pkg in fs.packages:
        frame = package_frame(pkg)
        if frame is None:
            continue
        held += [(frame[k], frame[k]), (frame[k + 2], frame[k + 2])]
        held += [(b[k], b[k + 2]) for b in map(_unit_label_box, package_labels(pkg, frame))
                 if b is not None]
    held += [(b[k], b[k + 2]) for b in placed(fs)]
    # A line set out by fractions of its length, or from a controller
    # that may hang off the actuator it drives, holds all it spans.
    measured = {id(u.host._logical_root or u.host) for u in fs.units
                if isinstance(getattr(u, "host", None), Stream)}
    hung = {id(u) for u in fs.units if _hangable(fs, u) is not None}
    for s in fs.streams:
        points = stream_path(s)
        if not points:
            continue
        root = s._logical_root or s
        if (id(root) in measured or root._logical_segments
                or (id(s.source.owner) in hung and s.dest.name == "actuator")):
            held.append(extent(points))
            continue
        ends = points if s.route is not None and s.route.manual else [points[0], points[-1]]
        held += [(p[k], p[k]) for p in ends]
        held += [extent([a, b]) for a, b in zip(points, points[1:]) if a[1 - k] != b[1 - k]]
    # An attached balloon holds all from its tap to its centre.
    for u in fs.units:
        tap = getattr(u, "tap", None)
        if tap is not None and u.frame is not None and is_attached(u):
            held.append(extent(tap_route(u, tap, (u.frame.cx, u.frame.cy))))
    return sorted(held), fixed


def onto_sheet(fs: Flowsheet) -> tuple[list[Cut], list[Cut]]:
    """Return the cuts that move a drawing past the sheet's top or left
    edge onto the sheet, by whole pixels.

    An axis with a unit pinned on it, any ``via()`` waypoint or any
    annotation placed by ``position`` is left as drawn.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    tuple[list[Cut], list[Cut]]
        A cut across x, then down y, that moves the whole drawing; each
        list empty where the drawing is on the sheet on that axis.
    """
    stated = bool(placed(fs)) or any(s.route is not None and s.route.manual
                                     for s in fs.streams)
    out: list[list[Cut]] = []
    for k in (0, 1):
        held, fixed = _held(fs, k)
        corners = [(u.frame.x, u.frame.y)[k] for u in fs.units if u.frame is not None]
        low = min([a for a, _ in held] + corners, default=0.0)
        # A cut of negative width ending at the drawing's edge moves all of it.
        out.append([] if low >= 0.0 or fixed or stated
                   else [(low - 1.0, low, -float(math.ceil(-low)), True)])
    return out[0], out[1]


def empty_bands(fs: Flowsheet, pinned: bool = False) -> tuple[list[Cut], list[Cut]]:
    """Return the cuts that close each empty band to the gap layout keeps.

    A band is cut to :data:`~pandid.layout.layered.COL_GAP` across the
    sheet and :data:`~pandid.layout.layered.ROW_GAP` down it, by whole
    pixels. What lies beyond it moves where nothing there is pinned on
    its axis, else what lies before it where nothing there is. A band
    with pins on both sides is kept, or, with ``pinned``, closed by
    moving what lies between it and the first pin beyond it, which
    widens the gap before that pin by as much.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    pinned : bool, default=False
        Close only the bands with pins on both sides.

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
            beyond = [a for a, _ in fixed if a >= low]
            both = bool(beyond) and any(b <= end for _, b in fixed)
            if width > 0.0 and not pinned and not both:
                cuts.append((end, low, width, not beyond))
            elif width > 0.0 and pinned and both:
                pin = min(beyond)
                reach = max((b for a, b in held if low <= a < pin), default=pin)
                if reach < pin:
                    cuts += [(end, low, width, True), (reach, pin, -width, True)]
            end = max(end, high)
        out.append(cuts)
    return out[0], out[1]


def close_bands(fs: Flowsheet, cuts: tuple[list[Cut], list[Cut]]) -> None:
    """Move everything on the free side of each cut in by its width, or out
    by a negative one.

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
