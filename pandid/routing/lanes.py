"""Lay the laterals that cross one gap on lanes that do not cross.

A lateral runs from an east nozzle to a west nozzle further east, or
the mirror, at another height, and can turn on a lane between its
stand-offs clear of every obstacle. Laterals that share a gap and a
height range form a group. Where two in a group cross or share a run,
one turns more than twice, or a balloon on one taps off its line, each
is drawn as one step on its own lane, the lanes ordered so that the
fewest cross and spread evenly across the widest stretch of the gap
that all of them may use.
"""

import math
from collections import Counter
from typing import TYPE_CHECKING

from pandid.geometry import Route
from pandid.portgeom import port_anchor
from pandid.route_geometry import stream_polyline
from pandid.routing.metrics import crossing_count, real_bends
from pandid.routing.separation import SPACING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.routing.visibility import Rect, VisibilityGraph
    from pandid.streams import Stream

Point = tuple[float, float]

#: Clearance a lateral's lane keeps from every obstacle.
CLEAR = 15.0

#: Sign of a lateral by its source and destination faces.
_SIGN = {("E", "W"): 1.0, ("W", "E"): -1.0}


class _Lateral:
    """One lateral, its x measured along its flow.

    Parameters
    ----------
    stream : Stream
        Stream drawn.
    sign : float
        +1 for a lateral running east, -1 for one running west.
    anchors : tuple[Point, Point]
        Source and destination nozzles.
    escapes : tuple[Point, Point]
        Ends of the source and destination stand-offs.

    Attributes
    ----------
    stream : Stream
        Stream drawn.
    sign : float
        +1 for a lateral running east, -1 for one running west.
    anchors : tuple[Point, Point]
        Source and destination nozzles.
    escapes : tuple[Point, Point]
        Ends of the source and destination stand-offs.
    lo, hi : float
        Ends of the gap between its stand-offs, along the flow.
    sy, dy : float
        Heights of the source and destination nozzles.
    free : list[tuple[float, float]]
        Stretches of the gap its lane may take, along the flow.
    """

    def __init__(self, stream: "Stream", sign: float, anchors: tuple[Point, Point],
                 escapes: tuple[Point, Point]):  # numpydoc ignore=GL08
        self.stream, self.sign, self.anchors, self.escapes = stream, sign, anchors, escapes
        self.lo, self.hi = sign * escapes[0][0], sign * escapes[1][0]
        self.sy, self.dy = anchors[0][1], anchors[1][1]
        self.free = [(self.lo, self.hi)] if self.lo < self.hi else []

    def spans(self, y: float) -> bool:
        """Return whether the lane's run reaches a height.

        Parameters
        ----------
        y : float
            Height to test.

        Returns
        -------
        bool
            True if ``y`` is on the run, its ends included.
        """
        return min(self.sy, self.dy) <= y <= max(self.sy, self.dy)

    def meets(self, other: "_Lateral") -> bool:
        """Return whether two laterals share a gap and a height range.

        Parameters
        ----------
        other : _Lateral
            Lateral to compare.

        Returns
        -------
        bool
            True if both run the same way and their boxes overlap or
            touch.
        """
        return (self.sign == other.sign and self.lo < other.hi and other.lo < self.hi
                and min(self.sy, self.dy) <= max(other.sy, other.dy)
                and min(other.sy, other.dy) <= max(self.sy, self.dy))

    def step(self, lane: float) -> Route:
        """Return the route that turns at a lane.

        Parameters
        ----------
        lane : float
            Lane position along the flow.

        Returns
        -------
        Route
            Nozzle, stand-off, the two corners, stand-off and nozzle.
        """
        x = self.sign * lane
        start, end = self.anchors
        return Route(waypoints=[start, self.escapes[0], (x, self.sy), (x, self.dy),
                                self.escapes[1], end])


def _lateral(stream: "Stream", escapes: tuple[Point, Point],
             obstacles: "list[Rect]", taps: list[Point]) -> "_Lateral | None":
    """Return a stream as a lateral, or None if it is not one.

    Parameters
    ----------
    stream : Stream
        Routed stream.
    escapes : tuple[Point, Point]
        Ends of its source and destination stand-offs.
    obstacles : list[Rect]
        Unit bodies and tag halos in its way.
    taps : list[Point]
        Where balloons tap the stream on its line.

    Returns
    -------
    _Lateral or None
        The lateral, or None.
    """
    src, dst = stream.source, stream.dest
    if src.owner.frame is None or dst.owner.frame is None:
        return None
    sx, sy, sface = port_anchor(src.owner, src.owner.frame, src.name)
    dx, dy, dface = port_anchor(dst.owner, dst.owner.frame, dst.name)
    sign = _SIGN.get((sface, dface))
    if sign is None or sy == dy or escapes[0][1] != sy or escapes[1][1] != dy:
        return None
    lateral = _Lateral(stream, sign, ((sx, sy), (dx, dy)), escapes)
    y0, y1 = sorted((sy, dy))
    for o in obstacles:
        a, b = sorted((sign * o.x_min, sign * o.x_max))
        a, b = a - CLEAR, b + CLEAR
        if (b <= lateral.lo or a >= lateral.hi
                or o.y_max + CLEAR <= y0 or o.y_min - CLEAR >= y1):
            continue
        # The lane keeps clear of the obstacle; a run at a nozzle's
        # height that meets it stops short of it, or starts past it.
        a = a if not o.y_min <= dy <= o.y_max else -math.inf
        b = b if not o.y_min <= sy <= o.y_max else math.inf
        lateral.free = _cut(lateral.free, a, b)
    for tx, ty in taps:
        # Keep a tap on a level run there, clear of the corner.
        x = sign * tx
        if abs(ty - sy) < 0.5:
            lateral.free = _cut(lateral.free, -math.inf, x + CLEAR)
        elif abs(ty - dy) < 0.5:
            lateral.free = _cut(lateral.free, x - CLEAR, math.inf)
    return lateral if lateral.free else None


def _cut(free: list[tuple[float, float]], a: float, b: float) -> list[tuple[float, float]]:
    """Return stretches less the open stretch between two points.

    Parameters
    ----------
    free : list[tuple[float, float]]
        Stretches as ``(lo, hi)``.
    a, b : float
        Ends of the stretch to remove.

    Returns
    -------
    list[tuple[float, float]]
        What is left, without empty stretches.
    """
    left = [(lo, min(hi, a)) for lo, hi in free if lo < min(hi, a)]
    return left + [(max(lo, b), hi) for lo, hi in free if max(lo, b) < hi]


def _lanes(group: list[_Lateral]) -> dict[int, float] | None:
    """Return each lateral's lane, ordered so the fewest cross.

    A lateral goes before one it meets when that order crosses fewer
    runs, or, on a tie, when it comes first in the group. Laterals take
    the lowest slot after every lateral they follow, and the slots are
    spread evenly across the widest stretch every lateral may use.

    Parameters
    ----------
    group : list[_Lateral]
        Laterals that meet, in sheet order.

    Returns
    -------
    dict[int, float] or None
        Lane along the flow by group index, or None if the order has a
        cycle or no stretch is wide enough for the slots.
    """
    after: dict[int, list[int]] = {i: [] for i in range(len(group))}
    waiting = Counter[int]()
    for j, b in enumerate(group):
        for i, a in enumerate(group[:j]):
            if not a.meets(b):
                continue
            # Runs crossed with a before b, then with b before a.
            ahead = b.spans(a.dy) + a.spans(b.sy)
            behind = a.spans(b.dy) + b.spans(a.sy)
            first, second = (j, i) if behind < ahead else (i, j)
            after[first].append(second)
            waiting[second] += 1
    slot = {i: 0 for i in after if not waiting[i]}
    ready = list(slot)
    for i in ready:
        for k in after[i]:
            slot[k] = max(slot.get(k, 0), slot[i] + 1)
            waiting[k] -= 1
            if not waiting[k]:
                ready.append(k)
    if len(ready) < len(group):
        return None
    shared = group[0].free
    for a in group[1:]:
        shared = [(max(lo, l2), min(hi, h2)) for lo, hi in shared for l2, h2 in a.free
                  if max(lo, l2) < min(hi, h2)]
    lo, hi = max(shared, key=lambda s: s[1] - s[0], default=(0.0, 0.0))
    pitch = (hi - lo) / (max(slot.values()) + 2)
    if pitch < SPACING:
        return None
    return {i: lo + (s + 1) * pitch for i, s in slot.items()}


def _score(fs: "Flowsheet") -> tuple[Counter[str], set[int]]:
    """Return what the sheet is judged by after routing.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    tuple[Counter[str], set[int]]
        Crossings and bends of the drawn lines with the findings and
        clashes balloon placement is judged by, and the balloons whose
        tap is off their line.
    """
    from pandid.layout.control import _flaws, _taps_off

    paths = [stream_polyline(s) for s in fs.streams if s.route is not None
             and s.source.owner.frame is not None and s.dest.owner.frame is not None]
    return (_flaws(fs) + Counter(crossings=crossing_count(paths),
                                 bends=sum(map(real_bends, paths))), _taps_off(fs))


def _tangled(lines: list[list[Point]]) -> bool:
    """Return whether lines cross, share a run, or one turns over twice.

    Parameters
    ----------
    lines : list[list[Point]]
        Drawn lines.

    Returns
    -------
    bool
        True if the lines could be drawn more simply.
    """
    from pandid.layout.control import _shared

    runs = [(k, a, b) for k, line in enumerate(lines) for a, b in zip(line, line[1:])]
    return (crossing_count(lines) > 0 or max(map(real_bends, lines)) > 2
            or any(_shared(a, b, c, d) for i, (k, a, b) in enumerate(runs)
                   for m, c, d in runs[i + 1:] if m != k))


def relane(fs: "Flowsheet", escapes: dict[int, tuple[Point, Point]],
           graph: "VisibilityGraph") -> None:
    """Re-lay each group of laterals that cross, touch or wind.

    A group is also re-laid where a balloon it carries taps off its
    line. A group's new routes are kept only if no crossing, bend,
    finding or clash grows in number, no tap leaves its line, and one of
    them falls.

    Parameters
    ----------
    fs : Flowsheet
        Routed and separated sheet.
    escapes : dict[int, tuple[Point, Point]]
        Ends of each routed stream's stand-offs, by ``id(stream)``.
    graph : VisibilityGraph
        Graph the sheet was routed on, for its obstacles.
    """
    from pandid.layout.attach import is_attached
    from pandid.layout.control import _taps_off
    from pandid.streams import Stream

    # Balloons on lines follow their lines, so are in no lateral's way.
    carried = [u for u in fs.units if is_attached(u) and isinstance(u.host, Stream)
               and getattr(u, "tap", None) is not None]
    off = _taps_off(fs)
    taps: dict[int, list[Point]] = {}
    for u in carried:
        if id(u) not in off:
            taps.setdefault(id(u.host), []).append(u.tap)
    adrift = {id(u.host) for u in carried if id(u) in off}
    followers = {id(body) for u, body in graph.body_obstacles
                 if any(u is c for c in carried)}
    obstacles = [o for o in graph.obstacles if id(o) not in followers]
    laterals = [lateral for s in fs.streams if id(s) in escapes
                and (lateral := _lateral(s, escapes[id(s)], obstacles,
                                         taps.get(id(s), []))) is not None]
    groups: list[list[_Lateral]] = []
    for lateral in laterals:
        joined = [g for g in groups if any(lateral.meets(other) for other in g)]
        merged = [other for g in joined for other in g] + [lateral]
        groups = [g for g in groups if all(g is not j for j in joined)] + [merged]
    before = None
    for group in groups:
        if (not any(id(a.stream) in adrift for a in group)
                and not _tangled([stream_polyline(a.stream) for a in group])):
            continue
        group.sort(key=lambda a: fs.streams.index(a.stream))
        lanes = _lanes(group)
        if lanes is None:
            continue
        before = before or _score(fs)
        old = [a.stream.route for a in group]
        for i, a in enumerate(group):
            a.stream.route = a.step(lanes[i])
        after = _score(fs)
        if after != before and not after[0] - before[0] and after[1] <= before[1]:
            before = after
            continue
        for a, route in zip(group, old):
            a.stream.route = route
