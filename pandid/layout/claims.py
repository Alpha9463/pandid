"""What each end of a stream says about where its own unit belongs.

The symbol has already fixed most of the geometry before anything is
placed. A column's overhead leaves the top, a relief valve sits on a
crown, a reboiler return comes in at the bottom, a pump takes suction
from the side -- and :func:`~pandid.portgeom.port_faces` knows which,
because a port with **one** declared placement is a port with no choice
about its face. That is not new information dug up for this module; it
is the same test :mod:`pandid.layout.faces` already uses to decide which
ports it is allowed to move.

The reading is per **endpoint**, not per edge:

- a unit whose **west** port carries a stream is east of that stream's
  far end, and one whose **east** port carries it is west of that end;
- the far end is read the same way, on its own.

An edge with one fixed nozzle and one free port still yields a
constraint, which is what a per-edge rule cannot do. Only an edge free
at *both* ends falls back to the flow-order default -- source before
destination -- so a sheet of plain blocks lays out exactly as it always
did, and the old engine's "every edge runs east to west" turns out to be
the special case where every face is east or west.

Why a vertical nozzle is read second
------------------------------------
North and south are read the same way -- south of that end, north of it
-- but **only where the edge has said nothing about along**. A single
vertical nozzle is usually a fact about the *equipment* and not about
the peer: a separator's vapour leaves the top because vapour does, a
reactor's product leaves the bottom because it drains, and what they
feed is still the next unit along the sheet, reached by a pipe that
turns. Read as a storey instead, every such nozzle costs a row and every
sideways nozzle on the same run costs a column, so a plant walks
diagonally off the page: ``21_alumina_refinery`` came out a staircase
27 columns wide and 11 rows deep with the corners of the sheet empty.

Where **neither** end says anything about along, the two nozzles are all
there is, and then a vertical face is a statement about the drawing: a
relief valve on a crown, a condenser over a column, a reboiler under
one. Those edges are read as *above* and *below*, and their two ends
share a column.

One face outranks the far end's, and it is the one an author *wrote*:
a :class:`~pandid.units.Block`'s, because a block has no nozzles to be a
fact about. See :func:`_stated_side`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.layout.solver import Order, Same
from pandid.layout.stages import slot

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Unit

#: A constraint the sheet may not break: two units in one column may not
#: be in one row. Ranked above every claim a nozzle makes, because a
#: nozzle pointing the wrong way is a drawing to argue with and two
#: boxes in one place is not a drawing at all.
SEPARATION = 4

#: A face the symbol fixed, or the author named, on a forward run.
FIXED = 3

#: The flow-order default, for an edge whose two ends can both move.
FLOW = 2

#: The same claim, made by a stream the cycle breaker tore. It is read
#: rather than dropped -- a relief line back to the vessel it protects
#: is the clearest statement on the sheet of where that valve goes --
#: but it gives way to every forward run it contradicts.
RETURN = 1


class Claims:
    """The constraints one sheet makes, gathered per axis."""

    def __init__(self) -> None:
        self.along: list[Order] = []   # the column axis: west to east
        self.across: list[Order] = []  # the row axis: north to south
        self.columns: list[Same] = []  # ends a vertical run lines up


def fixed_face(unit: "Unit", port_name: str, placed: object) -> str | None:
    """The face this port is drawn on, when it has no choice.

    ``None`` where the port has a menu and no one has picked from it:
    :mod:`pandid.layout.faces` will choose once the boxes are settled,
    and a placement pass that guessed the answer now would be placing
    the boxes to suit a face it had itself invented.

    ``placed`` is the placement to answer for and is the solver's
    ``_Slot``, seeded from the author's :class:`~pandid.geometry.Pin`.
    Reading the unit's ``frame`` instead would read back the placement
    the *previous* run emitted, and laying a sheet out twice would not
    draw it twice the same.
    """
    from pandid.portgeom import port_faces

    named = getattr(unit, "_port_faces", None) or {}
    if port_name in named:
        return str(named[port_name]).upper()
    menu = port_faces(unit, port_name, placed)
    return menu[0] if len(menu) == 1 else None


def stacks(units: list["Unit"], claims: "Claims") -> dict["Unit", "Unit"]:
    """Map each unit to the first unit of the stack it belongs to.

    A stack is a run of units the nozzles fix one above another, and it
    is **rigid**: what the faces fix is the arrangement inside it, and
    where the whole thing goes is one question rather than one per unit.
    Both the row solver and the straightener ask it, which is why it is
    answered here rather than in either of them.
    """
    lead = {u: u for u in units}

    def find(u: "Unit") -> "Unit":
        while lead[u] is not u:
            lead[u] = lead[lead[u]]
            u = lead[u]
        return u

    for edge in claims.across:
        a, b = find(edge.before), find(edge.after)
        if a is not b:
            lead[a] = b
    return {u: find(u) for u in units}


def read(fs: "Flowsheet", streams: list["Stream"]) -> Claims:
    """Every constraint the process runs on this sheet make."""
    claims = Claims()
    for stream in streams:
        src, dst = stream.source.owner, stream.dest.owner
        assert src is not None and dst is not None
        if src is dst:
            continue  # a run from a unit back to itself places nothing
        rank = RETURN if stream.is_recycle else FIXED
        ends = ((src, fixed_face(src, stream.source.name, slot(src)), dst),
                (dst, fixed_face(dst, stream.dest.name, slot(dst)), src))
        along: list[Order] = []
        across: list[Order] = []
        for mine, face, peer in ends:
            if face == "W":
                along.append(Order(peer, mine, rank))
            elif face == "E":
                along.append(Order(mine, peer, rank))
            elif face == "N":
                across.append(Order(peer, mine, rank))
            elif face == "S":
                across.append(Order(mine, peer, rank))
        along, across = _agreed(along), _agreed(across)
        stated = not stream.is_recycle and any(
            _stated_side(mine, face) for mine, face, _ in ends)
        if across and stated:
            _stack(claims, src, dst, across, rank)
        elif along:
            claims.along.extend(along)
        elif across:
            _stack(claims, src, dst, across, rank)
        else:
            claims.along.append(Order(src, dst, FLOW))
    return claims


def _stack(claims: Claims, src: "Unit", dst: "Unit", across: list[Order],
           rank: int) -> None:
    """Read an edge as *above* and *below*, and as one column.

    Above and below are statements about the row, so the column has to
    come out the same for both ends or the row cannot be honoured. That
    is the rule the old engine applied to :class:`~pandid.units.Block`
    alone; here it is what any vertical connection means.
    """
    claims.across.extend(across)
    claims.columns.append(Same(src, dst, rank))


def _stated_side(unit: "Unit", face: str | None) -> bool:
    """Is this face the *author* saying which side the peer is on?

    Only a :class:`~pandid.units.Block`'s is, because a block has no
    nozzles: its box is a plant section and the only thing the drawing
    says about a connection is which side it is on. **Every other
    vertical face is a fact about the equipment, not about the peer.** A
    separator's vapour leaves the top because vapour does, a reactor's
    product leaves the bottom because it drains; what they feed is still
    the next unit along, and lifting those onto the roof would rearrange
    every sheet in the corpus around a fact about a drum.

    Nor does :meth:`pandid.units.Unit.nozzle` count, though it is also
    the author's word. It moves a stream to another part of the same
    equipment, and where the pipe joins is still not where the peer
    goes: ``examples/08`` feeds its deaerator over the top tray with
    ``port_faces={"inlet": "N"}``, and the pump on the other end of that
    line belongs beside the drum, not over it.
    """
    from pandid.units import Block

    return face in ("N", "S") and isinstance(unit, Block)


def _agreed(axis: list[Order]) -> list[Order]:
    """One axis's claims, unless the two ends contradict each other.

    North into north: each end's nozzle puts the other unit on its own
    side, which between them states no order at all. Neither is applied
    and the edge falls through to whatever the other axis, or the flow,
    has to say -- rather than one being demoted at random by the cycle
    breaker, which would answer a question the drawing never asked.
    """
    if len(axis) == 2 and axis[0].before is axis[1].after \
            and axis[0].after is axis[1].before:
        return []
    return axis
