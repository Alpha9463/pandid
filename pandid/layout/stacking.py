"""Vertical connections: a north or south face as a layout constraint.

A stream on a unit's north or south face is not a step along the flow
order. It says where its peer belongs: above the unit, or below it. The
Sugiyama phases read every edge as a rank-advancing one, so such a
stream used to put its peer a column to the left and wherever the
barycentre happened to land it -- routinely the far side of the sheet
from the nozzle it was given, reached by a climb, a run back and a line
jump. That is issue #168.

Why the peer stays ranked
-------------------------
:mod:`pandid.layout.attach` has an escape hatch shaped for this kind of
problem: an instrument balloon is kept out of the Sugiyama phases
entirely and resolves its frame from whatever host it hangs on. That is
right for a balloon, which carries no flow. Nothing is downstream of
one, so no other unit's rank depends on where it lands, and its own
position is a function of one host and a branch angle.

A process peer is none of that. It carries a stream, it may have a feed
of its own, and every unit downstream of it is ranked against it. Taken
out of the ranking it would have no column to hand its own upstream, and
the phases that place that upstream would have nothing to place it
against. So the node stays in every phase and it is the *edge* whose
meaning changes: a vertical connection is a same-column, adjacent-row
constraint rather than a flow-order step. Layering and ordering are the
phases that answer those two questions.

:mod:`pandid.layout.faces` cannot answer it. It runs after coordinate
assignment, by which point the boxes this would have moved are settled,
and it only chooses between placements a symbol offers -- whereas what
is read here is the face a port has *no* choice about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Unit

#: Which row a face puts the peer in, relative to the unit declaring it.
_SIDE = {"N": -1, "S": 1}


class Stack(NamedTuple):
    """One vertical edge, read as a placement constraint.

    ``satellite`` belongs ``delta`` rows from ``anchor`` -- one above for
    a north face, one below for a south one -- and in the same column.
    """

    satellite: "Unit"
    anchor: "Unit"
    delta: int
    stream: "Stream"


def declared_face(unit: "Unit", port_name: str) -> str | None:
    """The face an author declared for this port, as drawn.

    ``None`` for every other port, including one whose symbol offers a
    single face and that face is north or south. **A nozzle's side is
    usually a fact about the equipment, not about the peer.** A
    separator's vapour leaves the top because vapour does, a reactor's
    product leaves the bottom because it drains; what they feed is still
    the next unit along, and lifting those onto the roof would rearrange
    every sheet in the corpus around a fact about a drum.

    One face in the library is the author's word instead: a
    :class:`~pandid.units.Block`'s, because a block has no nozzles. Its
    box is a plant section, and "the only thing the drawing says about a
    connection is which side it is on". No measurement can tell that
    from a drum's top, so this asks who said it rather than where it
    points.

    Nor does :meth:`pandid.units.Unit.nozzle` count, though it is also
    the author's word. It moves a stream to another part of the same
    equipment, and where the pipe joins is still not where the peer
    goes: ``examples/08`` feeds its deaerator over the top tray with
    ``port_faces={"inlet": "N"}``, and the pump on the other end of that
    line belongs beside the drum, not over it.

    The face is read against the solver's ``_Slot``, which
    :func:`pandid.layout._seed_slots` has already filled from the
    author's :class:`~pandid.geometry.Pin`, so a block turned a quarter
    reports the face it is *drawn* on. Reading the unit's ``frame``
    instead would read back the placement the previous run emitted, and
    laying a sheet out twice would not draw it twice the same.
    """
    from pandid.portgeom import port_faces
    from pandid.units import Block

    if not isinstance(unit, Block):
        return None
    return port_faces(unit, port_name, unit._slot)[0]


def stacked_edges(fs: "Flowsheet") -> list[Stack]:
    """Every free stream that states where one of its ends sits.

    Recycles are passed over. A recycle is drawn backward from a unit
    the ranking has already put columns downstream, so reading its face
    as a same-column constraint would drag that unit back to the block
    it returns to.
    """
    from pandid.layout.attach import free_streams

    out: list[Stack] = []
    for s in free_streams(fs):
        src, dst = s.source.owner, s.dest.owner
        if s.is_recycle or src is None or dst is None or src is dst:
            continue
        by_dst = _SIDE.get(declared_face(dst, s.dest.name) or "")
        by_src = _SIDE.get(declared_face(src, s.source.name) or "")
        if by_dst is not None and by_src is not None and by_dst != -by_src:
            # Two faces each putting the other unit on its own side --
            # north into north. They state no order between the two, so
            # neither is applied and the edge ranks as any other does.
            continue
        if by_dst is not None:
            out.append(Stack(src, dst, by_dst, s))
        elif by_src is not None:
            out.append(Stack(dst, src, by_src, s))
    return out
