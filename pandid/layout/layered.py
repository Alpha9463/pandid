"""Place equipment by layered graph drawing, with nozzles as ports.

The graph holds equipment and boundary flags; each furnished pipe is one
link between its two end nozzles (:mod:`pandid.layout.mounted`).

1. **Layers.** Return lines are reversed (:mod:`pandid.layout.cycles`) and
   flow runs west to east, one layer per step. A pipe from a top nozzle to
   a bottom nozzle stacks its two units in one layer instead.
2. **Order.** Barycentre sweeps over nozzle positions, with a dummy in each
   layer a pipe skips, keep the order with the fewest crossings.
3. **Coordinates.** Weighted-median sweeps line up each pipe's two nozzles
   while keeping every layer's order and spacing (pool adjacent violators).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pandid.geometry import Frame
from pandid.layout.halo import Pad, balloon_pads
from pandid.layout.stages import slot
from pandid.portgeom import port_faces, resolve_port, unit_box

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.units import Unit

#: Clear width between layers; it holds a run and its line number.
COL_GAP = 120.0
#: Clear height between units in one layer.
ROW_GAP = 70.0
#: Clear height beside a pipe passing through a layer.
LANE = 25.0
#: Left and top sheet margins.
MARGIN = 50.0
#: Pipe kept at the two nozzles of a furnished link: an exit and a clearance.
END_ROOM = 41.0
#: How far a top or bottom nozzle wants its peer above or below it.
LEAD = 40.0
#: Ordering and straightening passes.
SWEEPS = 12

#: Faces each end of a stacking pipe must have: (source, dest) -> dest is above.
_STACK = {("N", "S"): True, ("S", "N"): False}


@dataclass(frozen=True)
class Link:
    """One pipe between two placed units.

    Attributes
    ----------
    source, dest : Port
        End nozzles, in flow order.
    recycle : bool
        Whether the pipe is a return line, drawn against the flow.
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
    """A stack of units, or a dummy where a pipe crosses a layer."""

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
    """A pipe's step between two adjacent layers; a port is None at a dummy."""

    left: _Node
    lport: Port | None
    right: _Node
    rport: Port | None
    link: Link
    back: bool = False


def _face(port: Port | None) -> str | None:
    """Return the face a nozzle is drawn on, or None when it has a menu."""
    if port is None:
        return None
    unit = port.owner
    assert unit is not None
    named = getattr(unit, "_port_faces", None) or {}
    if port.name in named:
        return str(named[port.name]).upper()
    menu = port_faces(unit, port.name, slot(unit))
    return menu[0] if len(menu) == 1 else None


def _shift(unit: Unit) -> float:
    """Return how far a unit's drawn box starts right of its frame; a feed flag's starts left."""
    s = slot(unit)
    return unit_box(unit, Frame(x=0.0, y=0.0, w=s.w, h=s.h, mirrored=s.mirrored))[0]


def _nozzle(port: Port, face: str | None = None) -> tuple[float, float, str]:
    """Return a nozzle's offset from its unit's drawn box, and its face; on ``face`` if given."""
    unit = port.owner
    assert unit is not None
    s = slot(unit)
    probe = Frame(x=-_shift(unit), y=0.0, w=s.w, h=s.h, orientation=s.orientation,
                  mirrored=s.mirrored, mirror_y=s.mirror_y,
                  port_faces={port.name: face} if face else {})
    (x, y), _, landed = resolve_port(unit, probe, port.name)
    return x, y, landed


def _offset(node: _Node, port: Port | None) -> tuple[float, float]:
    """Return a nozzle's offset from its stack's corner; a dummy's is 0."""
    if port is None:
        return (node.w / 2, 0.0)
    assert port.owner is not None
    px, py, _ = _nozzle(port, node.faces.get(id(port)))
    return (node.dx[port.owner] + px, node.dy[port.owner] + py)


def _around(node: _Node, port: Port | None, east: bool) -> float:
    """Return a nozzle's height down its stack, 0 to 1, for ordering against one side.

    Nozzles on a top or bottom face tie on height, so the one nearer the
    peer's side sits inside: seen from the west, the east end of the top
    face is highest.
    """
    if port is None or not node.h:
        return 0.5
    assert port.owner is not None
    _, _, face = _nozzle(port, node.faces.get(id(port)))
    x, y = _offset(node, port)
    lean = {"N": -1, "S": 1}.get(face, 0) * (-1 if east else 1) * x / (100 * max(node.w, 1))
    return y / node.h + lean


def _flag(port: Port | None) -> bool:
    """Return whether a nozzle belongs to a boundary flag."""
    return port is not None and port.owner is not None and port.owner.kind in ("feed", "product")


def place_equipment(fs: Flowsheet, units: list[Unit], links: list[Link]) -> None:
    """Give every unit a frame by layered drawing.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with seeded slots and recycle marks.
    units : list[Unit]
        Units to place: equipment and boundary flags.
    links : list[Link]
        Pipes between them.

    Returns
    -------
    None
        Each unit gets a slot position and a frame; pins are kept.
    """
    if not units:
        return
    nodes, node_of, stacked = _stacks(units, links)
    edges = [(node_of[l.source.owner], node_of[l.dest.owner], l)
             for l in links if node_of[l.source.owner] is not node_of[l.dest.owner]]
    kept = {id(link) for _, _, link in _layers(nodes, edges)}
    layers, segs = _chains(nodes, edges, units)
    for seg in segs:
        seg.back = id(seg.link) not in kept
        # A nozzle with a menu of faces is read on the face toward its peer.
        for node, port, want in ((seg.left, seg.lport, "E"), (seg.right, seg.rport, "W")):
            if (port is not None and _face(port) is None
                    and want in port_faces(port.owner, port.name, slot(port.owner))):
                node.faces[id(port)] = want
    for layer in layers.values():
        for rank, node in enumerate(layer):
            for unit in node.members:
                slot(unit).col, slot(unit).row = node.layer, rank
    pads = balloon_pads(fs)
    for node in nodes:
        _shape(node, stacked, pads)
    _order(layers, segs)
    xs = _columns(layers, segs)
    _straighten(layers, segs)
    pinned_y = any(u.pin_ is not None and u.pin_.y is not None for u in units)
    lift = 0.0 if pinned_y else MARGIN - min(
        n.y - n.pad.north for layer in layers.values() for n in layer if n.members)
    for layer in layers.values():
        for rank, node in enumerate(layer):
            for unit in node.members:
                s, pin = slot(unit), unit.pin_
                s.x = pin.x if pin is not None and pin.x is not None else xs[node] + node.dx[unit] - _shift(unit)
                s.y = pin.y if pin is not None and pin.y is not None else node.y + node.dy[unit] + lift
                s.col = pin.col if pin is not None and pin.col is not None else node.layer
                s.row = pin.row if pin is not None and pin.row is not None else rank
                unit.frame = Frame(x=s.x, y=s.y, w=s.w, h=s.h, col=s.col, row=s.row,
                                   orientation=s.orientation, mirrored=s.mirrored,
                                   mirror_y=s.mirror_y)


def _stacks(units: list[Unit], links: list[Link]
            ) -> tuple[list[_Node], dict[Unit, _Node], list[tuple[Unit, Unit, Link]]]:
    """Group units joined by a top-to-bottom pipe into one stack per layer.

    Returns
    -------
    tuple
        Stacks in flowsheet order, each unit's stack, and the stacking pipes
        as ``(upper, lower, link)``.
    """
    lead = {u: u for u in units}

    def find(u: Unit) -> Unit:
        while lead[u] is not u:
            lead[u] = lead[lead[u]]
            u = lead[u]
        return u

    stacked = []
    for link in links:
        a, b = link.source.owner, link.dest.owner
        up = _STACK.get((_face(link.source), _face(link.dest)))
        if up is None or link.recycle or find(a) is find(b):
            continue
        lead[find(a)] = find(b)
        stacked.append((b, a, link) if up else (a, b, link))
    groups: dict[Unit, list[Unit]] = {}
    for u in units:
        groups.setdefault(find(u), []).append(u)
    nodes, node_of = [], {}
    for members in groups.values():
        node = _Node(members=members)
        nodes.append(node)
        node_of.update((u, node) for u in members)
    return nodes, node_of, stacked


def _shape(node: _Node, stacked: list[tuple[Unit, Unit, Link]], pads: dict[Unit, Pad]) -> None:
    """Order a stack top to bottom and line up its stacking nozzles."""
    mine = set(node.members)
    inside = [(a, b, l) for a, b, l in stacked if a in mine]
    below = {u: [(b, l) for a, b, l in inside if a is u] for u in node.members}
    has_upper = {b for _, b, _ in inside}
    # A depth-first walk from each top unit gives every unit its x and its turn.
    order, dx = [], {}
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
            for b, l in reversed(below[u]):
                upper_port = l.source if l.source.owner is u else l.dest
                lower_port = l.dest if upper_port is l.source else l.source
                walk.append((b, x + _nozzle(upper_port)[0] - _nozzle(lower_port)[0]))
    gap = {(a, b): max(ROW_GAP, l.rise) for a, b, l in inside}
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
    """Return how sure a pipe is of its direction, and +1 if its dest lies east.

    A return line runs west, last. Otherwise the nozzle faces say it: a pipe
    leaving an east face or reaching a west face runs east, so a mirrored
    pump runs west. Without a level face, flow order says east.
    """
    if link.recycle:
        return (3, -1)
    vote = ({"E": 1, "W": -1}.get(_face(link.source) or "", 0)
            + {"W": 1, "E": -1}.get(_face(link.dest) or "", 0))
    return (2 - abs(vote), -1 if vote < 0 else 1)


def _layers(nodes: list[_Node], edges: list[tuple[_Node, _Node, Link]]
            ) -> list[tuple[_Node, _Node, Link]]:
    """Give each stack the longest-path layer and return the pipes kept west to east.

    Pipes are kept surest first, each unless it closes a cycle; a source
    then sits just before its nearest peer.
    """
    succ: dict[_Node, list[_Node]] = {n: [] for n in nodes}

    def reaches(a: _Node, b: _Node) -> bool:
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
    order, placed = [], set()
    while len(order) < len(nodes):  # topological order, flowsheet order among ties
        n = next(n for n in nodes if n not in placed and all(p in placed for p in pred[n]))
        order.append(n)
        placed.add(n)
    fixed = {n: next(u.pin_.col for u in n.members if u.pin_ is not None and u.pin_.col is not None)
             for n in nodes if any(u.pin_ is not None and u.pin_.col is not None for u in n.members)}
    for n in order:
        n.layer = fixed.get(n, max((p.layer + 1 for p in pred[n]), default=0))
    for n in reversed(order):  # a source follows its nearest consumer
        if not pred[n] and succ[n] and n not in fixed:
            n.layer = min(m.layer for m in succ[n]) - 1
    return kept


def _chains(nodes: list[_Node], edges: list[tuple[_Node, _Node, Link]], units: list[Unit]
            ) -> tuple[dict[int, list[_Node]], list[_Seg]]:
    """Split each pipe into one step per layer, with dummies where it skips layers."""
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
        (l, lp), (r, rp) = sorted(((a, pa), (b, pb)), key=lambda e: e[0].layer)
        chain = [l]
        for layer in range(l.layer + 1, r.layer):
            dummy = _Node(layer=layer)
            layers.setdefault(layer, []).append(dummy)
            chain.append(dummy)
        chain.append(r)
        for k in range(len(chain) - 1):
            segs.append(_Seg(chain[k], lp if k == 0 else None, chain[k + 1],
                             rp if k == len(chain) - 2 else None, link))
    return dict(sorted(layers.items())), segs


def _order(layers: dict[int, list[_Node]], segs: list[_Seg]) -> None:
    """Reorder each layer by its neighbours' nozzle positions, then swap neighbours.

    Barycentre sweeps keep the order with the fewest crossings; adjacent
    swaps that remove a crossing follow.
    """
    pos: dict[_Node, float] = {}

    def index() -> None:
        for layer in layers.values():
            pos.update((n, float(i)) for i, n in enumerate(layer))

    ends = [(s, _around(s.left, s.lport, True), _around(s.right, s.rport, False)) for s in segs]
    gaps: dict[int, list[tuple[_Seg, float, float]]] = {}
    for e in ends:
        gaps.setdefault(e[0].left.layer, []).append(e)

    def crossings(k: int) -> int:
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
            for s, a, b in ends:
                # A unit is ordered by its peers, not by its flags.
                if down and s.right.layer == k and (_flag(s.rport) or not _flag(s.lport)):
                    near.setdefault(s.right, []).append(pos[s.left] + a)
                elif not down and s.left.layer == k and (_flag(s.lport) or not _flag(s.rport)):
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
                a, b = layer[i], layer[i + 1]
                layer[i], layer[i + 1], pos[a], pos[b] = b, a, pos[b], pos[a]
                if crossings(k - 1) + crossings(k) < before:
                    swapped = True
                else:
                    layer[i], layer[i + 1], pos[a], pos[b] = a, b, pos[b], pos[a]
        if not swapped:
            break


def _columns(layers: dict[int, list[_Node]], segs: list[_Seg]) -> dict[_Node, float]:
    """Return each stack's left edge: layers side by side, a stack against its pipes."""
    lo, hi = min(layers), max(layers)
    width = {k: max((n.w for n in layers.get(k, [])), default=0.0) for k in range(lo, hi + 1)}
    east = {k: max((n.pad.east for n in layers.get(k, [])), default=0.0) for k in width}
    west = {k: max((n.pad.west for n in layers.get(k, [])), default=0.0) for k in width}
    room = dict.fromkeys(width, 0.0)
    for s in segs:
        if s.link.room:
            room[s.left.layer] = max(room[s.left.layer], s.link.room + END_ROOM)
    left, x = {}, MARGIN + west[lo]
    for k in range(lo, hi + 1):
        left[k] = x
        x += width[k] + max(COL_GAP + east[k] + west.get(k + 1, 0.0), room[k])
    sides: dict[_Node, set[int]] = {}
    for s in segs:
        sides.setdefault(s.left, set()).add(1)
        sides.setdefault(s.right, set()).add(-1)
    out = {}
    for k, layer in layers.items():
        for n in layer:
            side = sides.get(n, set())
            # A stack whose pipes all leave one way sits on that side of its layer.
            slack = width[k] - n.w
            out[n] = left[k] + (slack if side == {1} else 0.0 if side == {-1} else slack / 2)
    return out


def _straighten(layers: dict[int, list[_Node]], segs: list[_Seg]) -> None:
    """Set each stack's top so pipes run level, keeping each layer's order."""
    near: dict[_Node, list[tuple[_Node, Port | None, Port | None, float]]] = {}
    for s in segs:
        both = (s.lport, s.rport)
        level = all(_face(p) in (None, "E", "W") for p in both)
        weight = 4.0 if s.lport is None and s.rport is None else 2.0 if level else 1.0
        for own, mine, other, theirs in ((s.left, s.lport, s.right, s.rport),
                                         (s.right, s.rport, s.left, s.lport)):
            # A unit ignores its flags and its return lines; they come to the unit.
            w = 0.1 if (_flag(theirs) and not _flag(mine)) or (mine and (s.back or s.link.recycle)) else weight
            near.setdefault(own, []).append((other, mine, theirs, w))
    lead = {"N": LEAD, "S": -LEAD}
    pinned = {}
    for layer in layers.values():
        for n in layer:
            for u in n.members:
                if u.pin_ is not None and u.pin_.y is not None:
                    pinned[n] = u.pin_.y - n.dy[u]
    for layer in layers.values():  # start each layer centred on one axis
        y = 0.0
        for k, n in enumerate(layer):
            n.y = y
            y += n.h + (_gap(n, layer[k + 1]) if k + 1 < len(layer) else 0.0)
        for n in layer:
            n.y = pinned.get(n, n.y - y / 2)

    def solve(layer: list[_Node]) -> None:
        targets = []
        for n in layer:
            if n in pinned:
                targets.append([(pinned[n], 1e9)])
                continue
            t = [(other.y + _offset(other, theirs)[1] - _offset(n, mine)[1]
                  + lead.get(_face(mine) or "", 0.0) - lead.get(_face(theirs) or "", 0.0), w)
                 for other, mine, theirs, w in near.get(n, [])]
            targets.append(t or [(n.y, 1e-3)])
        tops = _isotonic(targets, [n.h + _gap(n, b) for n, b in zip(layer, layer[1:])])
        for n, y in zip(layer, tops):
            n.y = y

    keys = list(layers)
    for sweep in range(SWEEPS):
        for k in (keys if sweep % 2 == 0 else keys[::-1]):
            solve(layers[k])


def _gap(upper: _Node, lower: _Node) -> float:
    """Return the clear height kept between two neighbours in a layer."""
    gap = ROW_GAP if upper.members and lower.members else LANE
    return gap + upper.pad.south + lower.pad.north


def _isotonic(targets: list[list[tuple[float, float]]], steps: list[float]) -> list[float]:
    """Return tops nearest their weighted targets, in order, each ``step`` below the last.

    Pool adjacent violators on ``y - offset``; a pooled block sits at the
    weighted median of its targets, which lines up whole pipes rather than
    splitting the difference.
    """
    offsets = [0.0]
    for step in steps:
        offsets.append(offsets[-1] + step)
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
    """Return the weighted median of ``(value, weight)`` pairs."""
    pairs = sorted(pairs)
    half, total = sum(w for _, w in pairs) / 2, 0.0
    for v, w in pairs:
        total += w
        if total >= half:
            return v
    return pairs[-1][0]
