"""Place equipment by layered graph drawing, with nozzles as ports.

Units are layered west to east along the flow, ordered in each layer to
reduce crossings, then moved up or down to line up each pipe's nozzles.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import accumulate, groupby
from typing import TYPE_CHECKING

from pandid.geometry import Frame
from pandid.layout.conflicts import boxes_overlap
from pandid.layout.halo import Pad, balloon_pads
from pandid.layout.stages import slot
from pandid.portgeom import COMPASS, port_faces, resolve_port, unit_box
from pandid.routing.visibility import MIN_ESCAPE

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.units import Unit

#: Least gap between layers, added to their balloon room.
COL_GAP = 120.0
#: Least clear height in a stack, or beside equipment in a layer.
ROW_GAP = 70.0
#: Gap between neighbours of only flags or pipes; pin clearance.
LANE = 25.0
#: Left and top margins, used when no x or y pin sets that axis.
MARGIN = 50.0
#: Pipe added to a furnished link's room for its two nozzle ends.
END_ROOM = 41.0
#: How far a top or bottom nozzle wants its peer above or below it.
LEAD = 40.0
#: Least pitch of the lanes pipes run up or down a layer gap on.
LANE_PITCH = 12.0
#: Passes for ordering, swapping and straightening.
SWEEPS = 12
#: Widest band before the drawing folds.
BAND_WIDTH = 3200.0
#: Clear height between bands.
BAND_GAP = 160.0

#: Stacking pipe end faces ``(source, dest)`` -> whether dest is above.
_STACK: dict[tuple[str | None, str | None], bool] = {("N", "S"): True, ("S", "N"): False}


@dataclass(frozen=True)
class Link:
    """One pipe between two units to place.

    Attributes
    ----------
    source : Port
        Source nozzle.
    dest : Port
        Destination nozzle.
    recycle : bool
        Whether the pipe is a return line.
    room : float
        Level pipe its furniture needs.
    rise : float
        Upright pipe its furniture needs when its ends stack.
    """

    source: Port
    dest: Port
    recycle: bool = False
    room: float = 0.0
    rise: float = 0.0


@dataclass(eq=False)
class _Node:
    """A stack of units, or a dummy where a pipe crosses a layer.

    Attributes
    ----------
    members : list[Unit]
        Units, top to bottom once shaped; empty for a dummy.
    dx : dict[Unit, float]
        Each member's x offset from the stack's left edge.
    dy : dict[Unit, float]
        Each member's y offset from the stack's top.
    w : float
        Stack width.
    h : float
        Stack height.
    pad : Pad
        Balloon room around the stack.
    layer : int
        Layer index.
    y : float
        Top of the stack.
    faces : dict[int, str]
        Face chosen for a multi-face nozzle, keyed by port id.
    """

    members: list[Unit] = field(default_factory=list)
    dx: dict[Unit, float] = field(default_factory=dict)
    dy: dict[Unit, float] = field(default_factory=dict)
    w: float = 0.0
    h: float = 0.0
    pad: Pad = Pad()
    layer: int = 0
    y: float = 0.0
    faces: dict[int, str] = field(default_factory=dict)


@dataclass(eq=False)
class _Seg:
    """A pipe's step between adjacent layers; a dummy has no port.

    Attributes
    ----------
    left : _Node
        Node in the western layer.
    lport : Port or None
        Nozzle on ``left``, or None at a dummy.
    right : _Node
        Node in the eastern layer.
    rport : Port or None
        Nozzle on ``right``, or None at a dummy.
    link : Link
        Pipe the step belongs to.
    back : bool
        Whether layering dropped the pipe for closing a cycle.
    """

    left: _Node
    lport: Port | None
    right: _Node
    rport: Port | None
    link: Link
    back: bool = False


def _face(port: Port | None) -> str | None:
    """Return a nozzle's stated or only face, else None.

    Parameters
    ----------
    port : Port or None
        Nozzle to read, or None.

    Returns
    -------
    str or None
        Face, or None for no port or a choice of faces.
    """
    if port is None:
        return None
    unit = port.owner
    named = getattr(unit, "_port_faces", None) or {}
    if port.name in named:
        return str(named[port.name]).upper()
    menu = port_faces(unit, port.name, slot(unit))
    # A family face a list or nozzle() states comes first.
    return menu[0] if len(menu) == 1 or port.name in getattr(unit, "_stated", ()) else None


def _shift(unit: Unit) -> float:
    """Return the x offset of a unit's drawn box from its frame.

    Parameters
    ----------
    unit : Unit
        Unit with a seeded slot.

    Returns
    -------
    float
        Offset of the box's left edge.
    """
    s = slot(unit)
    return unit_box(unit, Frame(x=0.0, y=0.0, w=s.w, h=s.h, mirrored=s.mirrored))[0]


def _nozzle(port: Port, face: str | None = None) -> tuple[float, float, str]:
    """Return a nozzle's offset from its drawn box, and its face.

    Parameters
    ----------
    port : Port
        Nozzle to locate.
    face : str or None, optional
        Face to read the nozzle on.

    Returns
    -------
    tuple[float, float, str]
        Offset x, offset y and face.
    """
    unit = port.owner
    s = slot(unit)
    probe = Frame(x=-_shift(unit), y=0.0, w=s.w, h=s.h, orientation=s.orientation,
                  mirrored=s.mirrored, mirror_y=s.mirror_y,
                  port_faces={port.name: face} if face else {})
    (x, y), _, landed = resolve_port(unit, probe, port.name)
    return x, y, landed


def _offset(node: _Node, port: Port | None) -> tuple[float, float]:
    """Return a nozzle's offset from its stack's corner.

    Parameters
    ----------
    node : _Node
        Stack holding the nozzle.
    port : Port or None
        Nozzle, or None for the stack's top centre.

    Returns
    -------
    tuple[float, float]
        Offset from the stack's top-left corner.
    """
    if port is None:
        return (node.w / 2, 0.0)
    px, py, _ = _nozzle(port, node.faces.get(id(port)))
    return (node.dx[port.owner] + px, node.dy[port.owner] + py)


def _around(node: _Node, port: Port | None, east: bool) -> float:
    """Return a nozzle's rank down its stack, about 0 to 1.

    A top or bottom nozzle ranks further inside the nearer it is to the
    side given by ``east``.

    Parameters
    ----------
    node : _Node
        Stack holding the nozzle.
    port : Port or None
        Nozzle, or None for a dummy.
    east : bool
        Whether the nozzle is ranked against the east side.

    Returns
    -------
    float
        Rank down the stack; 0.5 for a dummy or a flat stack.
    """
    if port is None or not node.h:
        return 0.5
    _, _, face = _nozzle(port, node.faces.get(id(port)))
    x, y = _offset(node, port)
    lean = COMPASS[face][1] * (-1 if east else 1) * x / (100 * max(node.w, 1))
    return y / node.h + lean


def _flag(port: Port | None) -> bool:
    """Return whether a nozzle belongs to a boundary flag.

    Parameters
    ----------
    port : Port or None
        Nozzle to test.

    Returns
    -------
    bool
        True for a feed or product flag.
    """
    return port is not None and port.owner.kind in ("feed", "product")


def place_equipment(fs: Flowsheet, units: list[Unit], links: list[Link]) -> None:
    """Give every unit a frame by layered drawing, keeping pins.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being laid out.
    units : list[Unit]
        Units to place.
    links : list[Link]
        Pipes between the units.
    """
    if not units:
        return
    nodes, node_of, stacked, fs._stack_spans = _stacks(units, links, fs._split_stacks)
    edges = [(node_of[link.source.owner], node_of[link.dest.owner], link) for link in links
             if node_of[link.source.owner] is not node_of[link.dest.owner]]
    kept = {id(link) for _, _, link in _layers(nodes, edges)}
    layers, segs = _chains(nodes, edges, units)
    for seg in segs:
        seg.back = id(seg.link) not in kept
        # Read a multi-face nozzle on the face toward its peer.
        for node, port, want in ((seg.left, seg.lport, "E"), (seg.right, seg.rport, "W")):
            if (port is not None and _face(port) is None
                    and want in port_faces(port.owner, port.name, slot(port.owner))):
                node.faces[id(port)] = want
    _rank(layers)
    pads = balloon_pads(fs)
    for node in nodes:
        _shape(node, stacked, pads)
    _order(layers, segs)
    _row_pins(layers)
    _rank(layers)
    _straighten(layers, segs, {})
    held = _row_order(layers)
    fs._rows_out = bool(held)
    if held and fs._order_rows:
        _straighten(layers, segs, held)
    xs = _columns(layers, segs, fs._lanes)
    plain = _columns(layers, segs, False)
    fs._widened = any(xs[n] != plain[n] for n in xs if n.members)
    if not any(u.pin_ is not None and (u.pin_.x is not None or u.pin_.y is not None)
               for u in units):
        _fold(layers, segs, xs)
    pinned_y = any(u.pin_ is not None and u.pin_.y is not None for u in units)
    lift = 0.0 if pinned_y else MARGIN - min(
        n.y - n.pad.north for layer in layers.values() for n in layer if n.members)
    # Shift free units to put the first x-pinned unit on its pin.
    slide = next((u.pin_.x - xs[node] - node.dx[u] + _shift(u)
                  for layer in layers.values() for node in layer for u in node.members
                  if u.pin_ is not None and u.pin_.x is not None), 0.0)
    for layer in layers.values():
        for node in layer:
            for unit in node.members:
                s, pin = slot(unit), unit.pin_
                s.x = (pin.x if pin is not None and pin.x is not None
                       else xs[node] + node.dx[unit] - _shift(unit) + slide)
                s.y = pin.y if pin is not None and pin.y is not None else node.y + node.dy[unit] + lift
                if pin is not None and pin.col is not None:
                    s.col = pin.col
                if pin is not None and pin.row is not None:
                    s.row = pin.row
    _clear_pins(units)
    for unit in units:
        s = slot(unit)
        unit.frame = Frame(x=s.x or 0.0, y=s.y or 0.0, w=s.w, h=s.h, col=s.col, row=s.row,
                           orientation=s.orientation, mirrored=s.mirrored, mirror_y=s.mirror_y)


def _rank(layers: dict[int, list[_Node]]) -> None:
    """Record each unit's layer and its row within the layer.

    Parameters
    ----------
    layers : dict[int, list[_Node]]
        Stacks and dummies in each layer, in order.
    """
    for layer in layers.values():
        row = 0
        for node in layer:
            for unit in node.members:
                slot(unit).col, slot(unit).row = node.layer, row
                row += 1


def _clear_pins(units: list[Unit]) -> None:
    """Step units off the fully pinned units and the units before them.

    If any unit has an x or y pin, each unit not pinned on both axes,
    in x-then-y order, steps below (right of, if its y is pinned) a
    box it comes within ``LANE`` of, up to one step more than there
    are boxes. The boxes are the fully pinned units and those before.

    Parameters
    ----------
    units : list[Unit]
        Units with set slots.
    """
    def free(u: Unit, axis: str) -> bool:
        """Return whether a unit is unpinned on one axis.

        Parameters
        ----------
        u : Unit
            Unit to test.
        axis : str
            ``"x"`` or ``"y"``.

        Returns
        -------
        bool
            True if the axis is free.
        """
        return u.pin_ is None or getattr(u.pin_, axis) is None

    def box(u: Unit) -> tuple[float, float, float, float]:
        """Return a unit's drawn box at its slot.

        Parameters
        ----------
        u : Unit
            Unit with a set slot.

        Returns
        -------
        tuple[float, float, float, float]
            Box as left, top, right, bottom.
        """
        s = slot(u)
        return unit_box(u, Frame(x=s.x or 0.0, y=s.y or 0.0, w=s.w, h=s.h, mirrored=s.mirrored))

    if all(free(u, "x") and free(u, "y") for u in units):
        return
    placed = [u for u in units if not free(u, "x") and not free(u, "y")]
    for u in sorted((u for u in units if u not in placed),
                    key=lambda u: (slot(u).x or 0.0, slot(u).y or 0.0)):
        axis = "y" if free(u, "y") else "x"
        for _ in range(len(placed) + 1):
            a = box(u)
            hit = next((b for b in map(box, placed) if boxes_overlap(a, b, LANE)), None)
            if hit is None:
                break
            s = slot(u)
            if axis == "y":
                s.y = (s.y or 0.0) + hit[3] + LANE - a[1]
            else:
                s.x = (s.x or 0.0) + hit[2] + LANE - a[0]
        placed.append(u)


def _stacks(units: list[Unit], links: list[Link], split: bool
            ) -> tuple[list[_Node], dict[Unit, _Node], list[tuple[Unit, Unit, Link]], bool]:
    """Group units joined by a top-to-bottom pipe into stacks.

    Parameters
    ----------
    units : list[Unit]
        Units to group.
    links : list[Link]
        Pipes between the units.
    split : bool
        Leave two units unstacked where another unit in their column is
        pinned to a row between theirs.

    Returns
    -------
    tuple[list[_Node], dict[Unit, _Node], list[tuple], bool]
        Stacks, each unit's stack, ``(upper, lower, link)`` pipes, and
        whether any stack would span such a row pin.
    """
    lead = {u: u for u in units}

    def find(u: Unit) -> Unit:
        """Return the root unit of a unit's stack.

        Parameters
        ----------
        u : Unit
            Unit to look up.

        Returns
        -------
        Unit
            Root of the stack.
        """
        while lead[u] is not u:
            lead[u] = lead[lead[u]]
            u = lead[u]
        return u

    col = {u: None if u.pin_ is None else u.pin_.col for u in units}
    row = {u: None if u.pin_ is None else u.pin_.row for u in units}
    # Each column-and-row pin.
    grid = {u: (c, r) for u in units if (c := col[u]) is not None and (r := row[u]) is not None}
    # Each unit's depth down its stack.
    depth = dict.fromkeys(units, 0)
    group = {u: [u] for u in units}
    stacked = []
    spans = False
    for link in links:
        a, b = link.source.owner, link.dest.owner
        up = _STACK.get((_face(link.source), _face(link.dest)))
        if up is None or link.recycle or find(a) is find(b):
            continue
        upper, lower = (b, a) if up else (a, b)
        top, bottom = find(upper), find(lower)
        drop = depth[upper] + 1 - depth[lower]
        merged = [(u, depth[u]) for u in group[top]] + [(u, depth[u] + drop) for u in group[bottom]]
        ranked = [(r, d) for u, d in merged if (r := row[u]) is not None]
        held = [grid[u] for u, _ in merged if u in grid]
        # Whether a unit pinned outside the stack falls between two of
        # its rows in its column.
        span = any(r1 < r < r2 for u, (c, r) in grid.items()
                   if find(u) is not top and find(u) is not bottom
                   for c1, r1 in held if c1 == c for c2, r2 in held if c2 == c)
        # Skip merges that break column or row pins.
        if (col[top] is not None and col[bottom] is not None and col[top] != col[bottom]) or any(
                r1 < r2 and d1 > d2 for r1, d1 in ranked for r2, d2 in ranked):
            continue
        spans = spans or span
        if split and span:
            continue
        for u in group[bottom]:
            depth[u] += drop
        col[top] = col[top] if col[top] is not None else col[bottom]
        group[top] += group.pop(bottom)
        lead[bottom] = top
        stacked.append((upper, lower, link))
    groups: dict[Unit, list[Unit]] = {}
    for u in units:
        groups.setdefault(find(u), []).append(u)
    nodes: list[_Node] = []
    node_of: dict[Unit, _Node] = {}
    for members in groups.values():
        node = _Node(members=members)
        nodes.append(node)
        node_of.update((u, node) for u in members)
    return nodes, node_of, stacked, spans


def _shape(node: _Node, stacked: list[tuple[Unit, Unit, Link]], pads: dict[Unit, Pad]) -> None:
    """Order a stack top to bottom and line up its stacking nozzles.

    Parameters
    ----------
    node : _Node
        Stack to shape.
    stacked : list[tuple[Unit, Unit, Link]]
        Stacking pipes as ``(upper, lower, link)``.
    pads : dict[Unit, Pad]
        Balloon room of each unit.
    """
    mine = set(node.members)
    inside = [(a, b, link) for a, b, link in stacked if a in mine]
    below = {u: [(b, link) for a, b, link in inside if a is u] for u in node.members}
    has_upper = {b for _, b, _ in inside}
    # Walk down from each top unit, setting each unit's x and order.
    order: list[Unit] = []
    dx: dict[Unit, float] = {}
    for top in node.members:
        if top in has_upper or top in dx:
            continue
        walk = [(top, 0.0)]
        while walk:
            u, x = walk.pop()
            if u in dx:
                continue
            dx[u] = x
            order.append(u)
            for b, link in reversed(below[u]):
                upper_port = link.source if link.source.owner is u else link.dest
                lower_port = link.dest if upper_port is link.source else link.source
                walk.append((b, x + _nozzle(upper_port)[0] - _nozzle(lower_port)[0]))
    gap = {(a, b): max(ROW_GAP, link.rise) for a, b, link in inside}
    left = min(dx.values())
    node.dx = {u: x - left for u, x in dx.items()}
    node.members, node.dy, y = order, {}, 0.0
    for k, u in enumerate(order):
        if k:
            prev = order[k - 1]
            y += gap.get((prev, u), ROW_GAP) + pads.get(prev, Pad()).south + pads.get(u, Pad()).north
        node.dy[u] = y
        y += slot(u).h
    node.w = max(node.dx[u] + slot(u).w for u in order)
    node.h = y
    ps = [pads.get(u, Pad()) for u in order]
    node.pad = Pad(ps[0].north, ps[-1].south, max(p.east for p in ps), max(p.west for p in ps))


def _east(link: Link) -> tuple[int, int]:
    """Return a pipe's certainty rank and direction.

    A lower rank is surer. A return line runs west; otherwise level
    nozzle faces vote, and a tie runs east.

    Parameters
    ----------
    link : Link
        Pipe to rank.

    Returns
    -------
    tuple[int, int]
        Rank, and +1 for east or -1 for west.
    """
    if link.recycle:
        return (3, -1)
    # Only non-flag faces vote.
    vote = ({"E": 1, "W": -1}.get(_face(link.source) or "", 0) * (not _flag(link.source))
            + {"W": 1, "E": -1}.get(_face(link.dest) or "", 0) * (not _flag(link.dest)))
    return (2 - abs(vote), -1 if vote < 0 else 1)


def _layers(nodes: list[_Node], edges: list[tuple[_Node, _Node, Link]]
            ) -> list[tuple[_Node, _Node, Link]]:
    """Assign each stack a layer and return the pipes kept west to east.

    Pipes are kept surest first unless they close a cycle. A column
    pin fixes a stack's layer; an unpinned source sits just before its
    nearest consumer.

    Parameters
    ----------
    nodes : list[_Node]
        Stacks to layer.
    edges : list[tuple[_Node, _Node, Link]]
        Pipes between different stacks.

    Returns
    -------
    list[tuple[_Node, _Node, Link]]
        Kept pipes as ``(west, east, link)``.
    """
    succ: dict[_Node, list[_Node]] = {n: [] for n in nodes}

    def reaches(a: _Node, b: _Node) -> bool:
        """Return whether kept pipes lead from one stack to another.

        Parameters
        ----------
        a : _Node
            Start stack.
        b : _Node
            Target stack.

        Returns
        -------
        bool
            True if ``b`` is reachable from ``a``.
        """
        seen, walk = {a}, [a]
        while walk:
            for m in succ[walk.pop()]:
                if m is b:
                    return True
                if m not in seen:
                    seen.add(m)
                    walk.append(m)
        return False

    kept = []
    for a, b, link in sorted(edges, key=lambda e: _east(e[2])[0]):
        west, east = (a, b) if _east(link)[1] > 0 else (b, a)
        if not reaches(east, west):
            succ[west].append(east)
            kept.append((west, east, link))
    pred: dict[_Node, list[_Node]] = {n: [] for n in nodes}
    for a, b, _ in kept:
        pred[b].append(a)
    order: list[_Node] = []
    placed: set[_Node] = set()
    # Topological order, flowsheet order among ties.
    while len(order) < len(nodes):
        n = next(n for n in nodes if n not in placed and all(p in placed for p in pred[n]))
        order.append(n)
        placed.add(n)
    fixed = {n: next(u.pin_.col for u in n.members if u.pin_ is not None and u.pin_.col is not None)
             for n in nodes if any(u.pin_ is not None and u.pin_.col is not None for u in n.members)}
    for n in order:
        n.layer = fixed.get(n, max((p.layer + 1 for p in pred[n]), default=0))
    # Put a source just before its nearest consumer.
    for n in reversed(order):
        if not pred[n] and succ[n] and n not in fixed:
            n.layer = min(m.layer for m in succ[n]) - 1
    return kept


def _chains(nodes: list[_Node], edges: list[tuple[_Node, _Node, Link]], units: list[Unit]
            ) -> tuple[dict[int, list[_Node]], list[_Seg]]:
    """Split each cross-layer pipe into steps, adding dummies.

    Parameters
    ----------
    nodes : list[_Node]
        Layered stacks.
    edges : list[tuple[_Node, _Node, Link]]
        Pipes between different stacks.
    units : list[Unit]
        Units in flowsheet order.

    Returns
    -------
    tuple[dict[int, list[_Node]], list[_Seg]]
        Stacks then dummies in each layer, and the pipe steps.
    """
    first = {n: min(units.index(u) for u in n.members) for n in nodes}
    layers: dict[int, list[_Node]] = {}
    for n in sorted(nodes, key=first.__getitem__):
        layers.setdefault(n.layer, []).append(n)
    segs = []
    for a, b, link in edges:
        if a.layer == b.layer:
            continue
        pa = link.source if link.source.owner in a.members else link.dest
        pb = link.dest if pa is link.source else link.source
        (west, wp), (east, ep) = sorted(((a, pa), (b, pb)), key=lambda e: e[0].layer)
        chain = [west]
        for layer in range(west.layer + 1, east.layer):
            dummy = _Node(layer=layer)
            layers.setdefault(layer, []).append(dummy)
            chain.append(dummy)
        chain.append(east)
        for k in range(len(chain) - 1):
            segs.append(_Seg(chain[k], wp if k == 0 else None, chain[k + 1],
                             ep if k == len(chain) - 2 else None, link))
    return dict(sorted(layers.items())), segs


def _order(layers: dict[int, list[_Node]], segs: list[_Seg]) -> None:
    """Order each layer to reduce pipe crossings.

    Barycentre sweeps keep the order with the fewest crossings, adjacent
    swaps remove more, then each flag moves beside the nozzle it serves.

    Parameters
    ----------
    layers : dict[int, list[_Node]]
        Stacks and dummies in each layer, in order.
    segs : list[_Seg]
        Pipe steps between adjacent layers.
    """
    pos: dict[_Node, float] = {}

    def index() -> None:
        """Record each node's position in its layer."""
        for layer in layers.values():
            pos.update((n, float(i)) for i, n in enumerate(layer))

    ends = [(s, _around(s.left, s.lport, True), _around(s.right, s.rport, False)) for s in segs]
    gaps: dict[int, list[tuple[_Seg, float, float]]] = {}
    for e in ends:
        gaps.setdefault(e[0].left.layer, []).append(e)

    def crossings(k: int) -> int:
        """Return the pipe crossings between layer ``k`` and the next.

        Parameters
        ----------
        k : int
            Layer index.

        Returns
        -------
        int
            Number of crossing pairs.
        """
        pairs = [(pos[s.left] + a, pos[s.right] + b) for s, a, b in gaps.get(k, [])]
        return sum(1 for i, (a, b) in enumerate(pairs) for c, d in pairs[i + 1:]
                   if (a - c) * (b - d) < 0)

    index()
    keys = list(layers)
    best, kept = sum(map(crossings, keys)), {k: list(v) for k, v in layers.items()}
    for sweep in range(SWEEPS):
        down = sweep % 2 == 0
        for k in (keys[1:] if down else keys[-2::-1]):
            near: dict[_Node, list[float]] = {}
            for s, a, b in gaps.get(k - 1 if down else k, []):
                # Order a unit by its peers, ignoring its flags.
                if down and (_flag(s.rport) or not _flag(s.lport)):
                    near.setdefault(s.right, []).append(pos[s.left] + a)
                elif not down and (_flag(s.lport) or not _flag(s.rport)):
                    near.setdefault(s.left, []).append(pos[s.right] + b)
            layers[k].sort(key=lambda n: sum(near[n]) / len(near[n]) if n in near else pos[n] + 0.5)
            pos.update((n, float(i)) for i, n in enumerate(layers[k]))
        count = sum(map(crossings, keys))
        if count < best:
            best, kept = count, {k: list(v) for k, v in layers.items()}
    layers.update(kept)
    index()
    for _ in range(SWEEPS):
        swapped = False
        for k in keys:
            layer = layers[k]
            for i in range(len(layer) - 1):
                before = crossings(k - 1) + crossings(k)
                one, two = layer[i], layer[i + 1]
                layer[i], layer[i + 1], pos[one], pos[two] = two, one, pos[two], pos[one]
                if crossings(k - 1) + crossings(k) < before:
                    swapped = True
                else:
                    layer[i], layer[i + 1], pos[one], pos[two] = one, two, pos[two], pos[one]
        if not swapped:
            break
    peer: dict[_Node, float] = {}
    for s, a, b in ends:
        if s.lport is not None and _flag(s.lport) and s.left.members == [s.lport.owner]:
            peer[s.left] = pos[s.right] + b
        if s.rport is not None and _flag(s.rport) and s.right.members == [s.rport.owner]:
            peer[s.right] = pos[s.left] + a
    for k in keys:
        layers[k].sort(key=lambda n: peer.get(n, pos[n]))


def _row_pins(layers: dict[int, list[_Node]]) -> None:
    """Sort row-pinned stacks into pin order in the places they hold.

    Parameters
    ----------
    layers : dict[int, list[_Node]]
        Stacks and dummies in each layer, in order.
    """
    for layer in layers.values():
        rows = {n: min(u.pin_.row for u in n.members if u.pin_ is not None and u.pin_.row is not None)
                for n in layer
                if any(u.pin_ is not None and u.pin_.row is not None for u in n.members)}
        places = [i for i, n in enumerate(layer) if n in rows]
        for i, n in zip(places, sorted(rows, key=rows.__getitem__)):
            layer[i] = n


def _row_order(layers: dict[int, list[_Node]]) -> dict[_Node, float]:
    """Return stack tops that draw units pinned by row alone in row order.

    A unit other than an instrument, pinned by ``row`` with no ``col``
    or ``y``, whose centre is no lower than that of such a unit pinned to
    a lower row moves down, with the nodes below it in its layer, to
    ``ROW_GAP`` below the lowest bottom of those units.

    Parameters
    ----------
    layers : dict[int, list[_Node]]
        Stacks and dummies in each layer, in order, set in height.

    Returns
    -------
    dict[_Node, float]
        Top of each stack holding a unit pinned by row alone, or an
        empty dict if no unit moves.
    """
    rowed = sorted(((u.pin_.row, n, u) for layer in layers.values() for n in layer
                    for u in n.members
                    if u.kind != "instrument" and u.pin_ is not None and u.pin_.row is not None
                    and u.pin_.col is None and u.pin_.y is None), key=lambda e: e[0])
    y = {n: n.y for layer in layers.values() for n in layer}
    floor = ceiling = -math.inf
    moved = False
    for _, same in groupby(rowed, key=lambda e: e[0]):
        group = [(n, u) for _, n, u in same]
        for n, u in group:
            top = y[n] + n.dy[u]
            if top + slot(u).h / 2 <= ceiling:
                layer = layers[n.layer]
                for m in layer[layer.index(n):]:
                    y[m] += floor - top
                moved = True
        ceiling = max(ceiling, *(y[n] + n.dy[u] + slot(u).h / 2 for n, u in group))
        floor = max(floor, *(y[n] + n.dy[u] + slot(u).h + ROW_GAP for n, u in group))
    return {n: y[n] for _, n, _ in rowed} if moved else {}


def _columns(layers: dict[int, list[_Node]], segs: list[_Seg],
             widen: bool) -> dict[_Node, float]:
    """Return each node's left edge.

    Parameters
    ----------
    layers : dict[int, list[_Node]]
        Stacks and dummies in each layer, in order.
    segs : list[_Seg]
        Pipe steps between adjacent layers.
    widen : bool
        Widen each gap for the lanes its laterals need.

    Returns
    -------
    dict[_Node, float]
        Left edge of each node.
    """
    lo, hi = min(layers), max(layers)
    width = {k: max((n.w for n in layers.get(k, [])), default=0.0) for k in range(lo, hi + 1)}
    east = {k: max((n.pad.east for n in layers.get(k, [])), default=0.0) for k in width}
    west = {k: max((n.pad.west for n in layers.get(k, [])), default=0.0) for k in width}
    room = dict.fromkeys(width, 0.0)
    # Furniture room goes in the gap after the pipe's west end.
    for s in segs:
        if s.link.room and s.lport is not None:
            room[s.left.layer] = max(room[s.left.layer], s.link.room + END_ROOM)
    for k, lanes in (_lanes(segs) if widen else {}).items():
        room[k] = max(room[k], 2 * MIN_ESCAPE + (lanes + 1) * LANE_PITCH)
    left, x = {}, MARGIN + west[lo]
    for k in range(lo, hi + 1):
        left[k] = x
        # A layer of only pipes takes no room.
        if any(n.members for n in layers.get(k, [])):
            x += width[k] + max(COL_GAP + east[k] + west.get(k + 1, 0.0), room[k])
    sides: dict[_Node, set[int]] = {}
    for s in segs:
        sides.setdefault(s.left, set()).add(1)
        sides.setdefault(s.right, set()).add(-1)
    out = {}
    for k, layer in layers.items():
        for n in layer:
            side = sides.get(n, set())
            # Push a stack toward the side all its pipes leave by.
            slack = width[k] - n.w
            out[n] = left[k] + (slack if side == {1} else 0.0 if side == {-1} else slack / 2)
    return out


def _lanes(segs: list[_Seg]) -> dict[int, int]:
    """Return how many lanes each layer gap needs.

    A pipe step between east and west nozzles at different heights runs
    up or down its gap on a lane of its own, so a gap needs as many
    lanes as such steps overlap at any one height.

    Parameters
    ----------
    segs : list[_Seg]
        Pipe steps between adjacent layers, with stacks set in height.

    Returns
    -------
    dict[int, int]
        Lanes needed, by the layer before the gap.
    """
    events: dict[int, list[tuple[float, int]]] = {}
    for s in segs:
        ends = []
        for node, port in ((s.left, s.lport), (s.right, s.rport)):
            if port is not None and _nozzle(port, node.faces.get(id(port)))[2] not in ("E", "W"):
                break
            ends.append(node.y + _offset(node, port)[1])
        else:
            if abs(ends[0] - ends[1]) > 1e-6:
                # An end sorts before a start at the same height.
                events.setdefault(s.left.layer, []).extend(
                    ((min(ends), 1), (max(ends), -1)))
    return {k: max(accumulate(step for _, step in sorted(e))) for k, e in events.items()}


def _straighten(layers: dict[int, list[_Node]], segs: list[_Seg],
                held: dict[_Node, float]) -> None:
    """Set each stack's top to level its pipes, keeping layer order.

    Parameters
    ----------
    layers : dict[int, list[_Node]]
        Stacks and dummies in each layer, in order.
    segs : list[_Seg]
        Pipe steps between adjacent layers.
    held : dict[_Node, float]
        Top to keep each of these stacks at, unless a ``y`` pin sets it.
    """
    lead = {"N": LEAD, "S": -LEAD}
    near: dict[_Node, list[tuple[_Node, float, float, float, float, float]]] = {}
    for s in segs:
        both = (s.lport, s.rport)
        level = all(_face(p) in (None, "E", "W") for p in both)
        # Dummy runs pull hardest, then level pipes; furniture adds one.
        weight = (4.0 if s.lport is None and s.rport is None else 2.0 if level else 1.0) + bool(s.link.room)
        for own, mine, other, theirs in ((s.left, s.lport, s.right, s.rport),
                                         (s.right, s.rport, s.left, s.lport)):
            # A unit barely pulls toward its flags and return lines.
            w = 0.1 if (_flag(theirs) and not _flag(mine)) or (mine and (s.back or s.link.recycle)) else weight
            near.setdefault(own, []).append((other, _offset(other, theirs)[1], _offset(own, mine)[1],
                                             lead.get(_face(mine) or "", 0.0),
                                             lead.get(_face(theirs) or "", 0.0), w))
    pinned = dict(held)
    for layer in layers.values():
        for n in layer:
            for u in n.members:
                if u.pin_ is not None and u.pin_.y is not None:
                    pinned[n] = u.pin_.y - n.dy[u]
    # Each stack pulls harder toward a neighbour nearer a pin.
    hops = dict.fromkeys(pinned, 0)
    walk = list(pinned)
    while walk:
        n = walk.pop(0)
        for other, *_ in near.get(n, []):
            if other not in hops:
                hops[other] = hops[n] + 1
                walk.append(other)
    far = len(hops) + 1
    for n, entries in near.items():
        entries[:] = [(o, a, b, c, d, w * (1.5 if hops.get(o, far) < hops.get(n, far) else 1))
                      for o, a, b, c, d, w in entries]
    # Start each layer centred on one axis.
    for layer in layers.values():
        y = 0.0
        for k, n in enumerate(layer):
            n.y = y
            y += n.h + (_gap(n, layer[k + 1]) if k + 1 < len(layer) else 0.0)
        for n in layer:
            n.y = pinned.get(n, n.y - y / 2)

    def solve(layer: list[_Node]) -> None:
        """Set the tops of one layer's stacks nearest their targets.

        Parameters
        ----------
        layer : list[_Node]
            Stacks of one layer, in order.
        """
        targets = []
        for n in layer:
            if n in pinned:
                targets.append([(pinned[n], 1e9)])
                continue
            t = [(other.y + theirs - mine + up - down, w)
                 for other, theirs, mine, up, down, w in near.get(n, [])]
            targets.append(t or [(n.y, 1e-3)])
        tops = _isotonic(targets, [n.h + _gap(n, b) for n, b in zip(layer, layer[1:])])
        for n, y in zip(layer, tops):
            n.y = y

    keys = list(layers)
    for sweep in range(SWEEPS):
        for k in (keys if sweep % 2 == 0 else keys[::-1]):
            solve(layers[k])


def _fold(layers: dict[int, list[_Node]], segs: list[_Seg], xs: dict[_Node, float]) -> None:
    """Fold a drawing wider than :data:`BAND_WIDTH` into bands.

    A band ends at the layer in its second half that the fewest pipe
    steps leave, the latest on a tie.

    Parameters
    ----------
    layers : dict[int, list[_Node]]
        Stacks and dummies in each layer, in order.
    segs : list[_Seg]
        Pipe steps between adjacent layers.
    xs : dict[_Node, float]
        Left edge of each node, updated in place.
    """
    keys = sorted(layers)
    left = {k: min(xs[n] - n.pad.west for n in layers[k]) for k in keys}
    right = {k: max(xs[n] + n.w + n.pad.east for n in layers[k]) for k in keys}
    leaving = Counter(s.left.layer for s in segs)
    bands, start = [], 0
    while True:
        last = max([i for i in range(start, len(keys))
                    if right[keys[i]] - left[keys[start]] <= BAND_WIDTH], default=start)
        if last == len(keys) - 1:
            bands.append(keys[start:])
            break
        cut = min(range(start + (last - start) // 2, last + 1),
                  key=lambda i: (leaving[keys[i]], -i))
        bands.append(keys[start:cut + 1])
        start = cut + 1
    bottom = None
    for band in bands:
        nodes = [n for k in band for n in layers[k]]
        top = min(n.y - n.pad.north for n in nodes)
        dx = left[band[0]] - left[keys[0]]
        dy = 0.0 if bottom is None else bottom + BAND_GAP - top
        for n in nodes:
            xs[n] -= dx
            n.y += dy
        bottom = max(n.y + n.h + n.pad.south for n in nodes)


def _gap(upper: _Node, lower: _Node) -> float:
    """Return the clear height between two neighbours in a layer.

    Parameters
    ----------
    upper : _Node
        Upper neighbour.
    lower : _Node
        Lower neighbour.

    Returns
    -------
    float
        ``LANE`` or ``ROW_GAP``, plus the balloon room between them.
    """
    flags = all(u.kind in ("feed", "product") for u in (*upper.members, *lower.members))
    gap = LANE if flags else ROW_GAP  # dummies and flags only
    return gap + upper.pad.south + lower.pad.north


def _isotonic(targets: list[list[tuple[float, float]]], steps: list[float]) -> list[float]:
    """Return the tops nearest their weighted targets, in order.

    Each top is at least its step below the last; adjacent violators
    share the weighted median of their targets less each top's offset.

    Parameters
    ----------
    targets : list[list[tuple[float, float]]]
        ``(value, weight)`` targets for each top.
    steps : list[float]
        Least distance from each top to the next.

    Returns
    -------
    list[float]
        The tops.
    """
    offsets = [0.0, *accumulate(steps)]
    blocks: list[tuple[list[tuple[float, float]], int, float]] = []
    for i, t in enumerate(targets):
        pool, count = [(v - offsets[i], w) for v, w in t], 1
        while True:
            value = _median(pool)
            if not blocks or blocks[-1][2] <= value:
                break
            prev, n, _ = blocks.pop()
            pool, count = prev + pool, n + count
        blocks.append((pool, count, _median(pool)))
    out = []
    for _, count, value in blocks:
        out.extend([value] * count)
    return [v + o for v, o in zip(out, offsets)]


def _median(pairs: list[tuple[float, float]]) -> float:
    """Return the lower weighted median of ``(value, weight)`` pairs.

    Parameters
    ----------
    pairs : list[tuple[float, float]]
        Values and weights.

    Returns
    -------
    float
        Least value whose cumulative weight reaches half the total.

    Raises
    ------
    IndexError
        If ``pairs`` is empty.
    """
    pairs = sorted(pairs)
    half, total = sum(w for _, w in pairs) / 2, 0.0
    for v, w in pairs:
        total += w
        if total >= half:
            return v
    return pairs[-1][0]
