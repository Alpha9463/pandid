"""What each unit says about where its neighbours are drawn.

Vertical position on a P&ID is **not** elevation. A condenser is drawn
top right of its column because that reads clearly and keeps the runs
from crossing, not because it stands on a structure above it. It is a
drafting convention, and the only thing that knows it is the equipment:
a column knows its overhead goes up and to the right and its reboiler
down and to the right, and no amount of looking at the pipe will tell
you that.

So the equipment says it, in two class attributes
(:attr:`~pandid.units.Unit.PLACES` and
:attr:`~pandid.units.Unit.LAYOUT_CONFIDENCE`), and this module reads
them off the sheet as :class:`Claim` s.

One shape for everything
------------------------
``Claim(author, subject, eastward, southward, confidence)``. The
``author`` asserts; the ``subject`` is asserted upon. ``eastward`` and
``southward`` are relative **steps**, not coordinates, and are named for
their sign: ``+1 southward`` is a row further down a y-down canvas,
which ``dy`` invites a reader to get backwards.

**Every stream emits two claims, one authored by each end.** They are
independent and may flatly disagree -- a column's ``overhead -> NE`` and
its condenser's own reading of its inlet face are two different
statements about the same pair -- and the solve
(:mod:`pandid.layout.solver`) arbitrates by weight rather than by
dropping one of them. That is what lets every block have a say, and it
is why nothing here has to decide which end is right.

Where a direction comes from
----------------------------
Three levels, best first, all at the author's own confidence:

1. **:attr:`~pandid.units.Unit.PLACES`**, the drafting convention this
   kind of equipment draws to. Looked up by port name, then by the
   family name a numbered family shares, so ``feed`` covers ``feed_1``
   through ``feed_8``.
2. **The face the nozzle is fixed to**, where the symbol leaves it no
   choice (:func:`fixed_face`). A west nozzle says its peer is west.
   Note what this is *not*: it is the author's own guess about its own
   nozzle, worth exactly the author's confidence, and no longer the
   binary fact the engine before this one tried to build an order out
   of. A column overhead and a condenser inlet both facing north used to
   cancel to nothing and let the barycentre draw the tower upside down
   (#446); here they are two weak opinions that a strong ``PLACES``
   overrules.
3. **Flow order**: the destination is one step east of the source. A
   recycle is the same statement backwards, since a return line is drawn
   right to left and its two ends are already ordered by the forward run
   it returns along.

   This one is **not** at the author's confidence. It is what the *pipe*
   says, not what the unit says: a unit whose nozzle has a menu nobody
   has picked from has stated nothing at all, and weighing that silence
   as heavily as a stated convention makes silence argue. Concretely, a
   feed over a block's roof: the block states north, the feed's silence
   is read as "east of me", the two weigh the same, and the fit splits
   the difference and draws the feed diagonally off the corner. So flow
   order weighs :data:`LINE`, wherever it comes from.

Confidence 0, and why the line still speaks
-------------------------------------------
A valve, a fitting or a reducer sets
:attr:`~pandid.units.Unit.LAYOUT_CONFIDENCE` to 0: it sits *in* the line
and has no opinion about where the line goes. Its claims are dropped,
which is not the same as weighing them 1 -- a train with a dozen block
valves on it would otherwise stiffen the vessel at the end of it by 12
and drown out the column arguing with it.

Dropped claims cannot be allowed to disconnect the sheet, though: a run
of valves between two valves would leave a component with nothing
joining it to anything, and a component the solve anchors on its own is
a component drawn on top of the sheet. So a stream **both** of whose
ends declined to speak contributes one claim of its own at
:data:`LINE`, the weakest weight there is, saying only what a pipe says:
that the thing it leaves comes before the thing it reaches.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from pandid.layout.stages import slot

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Unit

#: What the run itself states, where a unit has said nothing. Below
#: every confidence a unit class declares, because it is not a unit's
#: opinion at all -- it is the pipe, and the pipe only knows which end
#: it left.
LINE = 0.25

#: What a return line is worth. It states one thing -- that the end it
#: leaves is further along the sheet than the end it reaches -- and it
#: states it weakly, because the forward run it returns along has
#: already said the same and said it better. Not dropped, because a
#: return may be the only run joining a loop's two halves and a
#: component nothing joins is a component drawn on top of the sheet.
RETURN = 0.25

#: Compass point -> ``(eastward, southward)``, in grid steps. South is
#: positive: the canvas is y-down and the table is written the way the
#: drawing reads, not the way the maths would prefer.
STEPS: dict[str, tuple[int, int]] = {
    "N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0),
    "NE": (1, -1), "NW": (-1, -1), "SE": (1, 1), "SW": (-1, 1),
}


class Claim(NamedTuple):
    """``author`` says ``subject`` is drawn this many steps away.

    ``confidence`` is stiffness, not authority: it is how hard the pair
    resists being pulled out of this arrangement, and it resists at
    **both** ends. A column insisting its condenser is north east of it
    is equally a column that will move north west to satisfy a condenser
    someone pinned.
    """

    author: "Unit"
    subject: "Unit"
    eastward: int
    southward: int
    confidence: float


def read(streams: list["Stream"]) -> list[Claim]:
    """Every claim the process runs on this sheet make, in sheet order.

    Order is part of the answer. The solve sums weights in the order it
    is handed them, and float addition is not associative, so a claim
    list assembled from a set or a dict of units would draw a sheet that
    depended on where its names happened to hash to.
    """
    out: list[Claim] = []
    for stream in streams:
        src, dst = stream.source.owner, stream.dest.owner
        assert src is not None and dst is not None
        if src is dst:
            continue  # a run from a unit back to itself places nothing
        ends = ((src, stream.source.name, dst, 1), (dst, stream.dest.name, src, -1))
        if stream.is_recycle:
            # A return line's nozzles are read for nothing. The run
            # leaves an east face and goes back **west**, so reading that
            # face forwards states the loop the wrong way round -- and
            # weakly stating something wrong is still wrong: the two
            # claims a splitter and a mixer make about each other pull
            # the whole train between them together, and every step
            # along it comes out short of a column
            # (``05_reactor_recycle``, one straight row of equipment
            # that folded into three). What is left is the only thing a
            # return says: the end it leaves is further along than the
            # end it reaches.
            for author, _port, subject, forward in ends:
                step = _flow_step(forward, True)
                out.append(Claim(author, subject, step[0], step[1], RETURN))
            continue
        spoke = False
        for author, port_name, subject, forward in ends:
            direction, confidence = _stated(author, port_name)
            if confidence <= 0.0:
                continue
            if direction is None:
                direction = fixed_face(author, port_name, slot(author))
            if direction is None:
                # The unit's nozzle has a menu and no one has picked
                # from it, so the unit has said nothing: what is left is
                # the pipe, at the pipe's weight. Weighing an invented
                # opinion at the unit's own is what puts a feed over a
                # block's roof *diagonally* -- the block states north,
                # the feed's silence is read as "east of me", the two
                # weigh the same and the fit splits the difference.
                step, weight = _flow_step(forward, False), LINE
            else:
                step, weight = STEPS[direction], confidence
            out.append(Claim(author, subject, step[0], step[1], weight))
            spoke = True
        if not spoke:
            step = _flow_step(1, False)
            out.append(Claim(src, dst, step[0], step[1], LINE))
    return out


def _flow_step(forward: int, is_recycle: bool) -> tuple[int, int]:
    """Which way the pipe alone says the peer lies.

    ``forward`` is +1 when the author is the run's source. A recycle is
    read backwards: it is drawn right to left, so its source is the unit
    further along the sheet, and reading it forwards would ask the
    solver to close the loop it is drawn around.
    """
    return (-forward if is_recycle else forward, 0)


def _stated(unit: "Unit", port_name: str) -> tuple[str | None, float]:
    """This unit's ``PLACES`` entry for a port, and what it is worth.

    The direction is ``None`` where the class states none, which sends
    the caller on to the nozzle's face; the confidence is the class's
    own unless the entry overrides it, which is how a column can insist
    on its overhead and merely prefer its side draws.

    Looked up by the port's own name first and then by the family name,
    so ``PLACES = {"feed": "W"}`` covers a tower with eight of them
    without listing eight keys.
    """
    places = type(unit).PLACES
    entry = places.get(port_name)
    if entry is None:
        entry = places.get(family(port_name))
    confidence = float(type(unit).LAYOUT_CONFIDENCE)
    if entry is None:
        return None, confidence
    if isinstance(entry, tuple):
        return entry[0], float(entry[1])
    return entry, confidence


def family(port_name: str) -> str:
    """The name a numbered family of nozzles shares: ``feed_3`` -> ``feed``.

    A trailing ``_<n>`` and nothing else, because that is the only
    generated suffix in the library (:func:`pandid.units._feed_names`
    and its peers), and a looser rule would fold ``shell_in`` onto
    ``shell``.
    """
    head, _, tail = port_name.rpartition("_")
    return head if head and tail.isdigit() else port_name


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


def stacks(fs: "Flowsheet", units: list["Unit"]) -> dict["Unit", "Unit"]:
    """Map each unit to the first unit of the stack it belongs to.

    A stack is a run of connected units the solve put in **one column**,
    and it is read off the settled grid rather than off the claims: what
    matters to the caller is which boxes are drawn one above another,
    and that is a fact about the answer and not about the argument that
    produced it. :func:`~pandid.layout.coordinates._straighten` is the
    caller, and it moves a stack as one thing -- shifting the vessel
    onto its own spine and leaving the relief valve above it on the row
    axis would say the arrangement in the row numbers and deny it in the
    ink.
    """
    from pandid.layout.stages import process_streams

    lead = {u: u for u in units}

    def find(u: "Unit") -> "Unit":
        while lead[u] is not u:
            lead[u] = lead[lead[u]]
            u = lead[u]
        return u

    placed = set(units)
    for stream in process_streams(fs):
        src, dst = stream.source.owner, stream.dest.owner
        assert src is not None and dst is not None
        if src not in placed or dst not in placed:
            continue
        if slot(src).col != slot(dst).col:
            continue
        a, b = find(src), find(dst)
        if a is not b:
            lead[a] = b
    return {u: find(u) for u in units}
