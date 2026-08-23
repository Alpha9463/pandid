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

**A stream states one claim for each end that has something to say.**
Where both do they are independent and may flatly disagree -- a column's
``overhead -> NE`` and its condenser's own reading of its inlet face are
two different statements about the same pair -- and the solve
(:mod:`pandid.layout.solver`) arbitrates by weight rather than by
dropping one of them. That is what lets every block have a say, and it
is why nothing here has to decide which end is right.

Where **neither** end has anything to say the pipe states one claim on
its own account, and a return line is always that case (see below). The
approved design in #447 said *two* claims per stream, unconditionally.
That is amended here, deliberately: a valve has no opinion about where
its line goes, and a claim written on its behalf is not its opinion but
an invention -- and an invented claim is still a weight in the fit.
Emitting one anyway, at :data:`LINE`, costs the corpus 20 crossings and
buys a symmetry that is in the code rather than in the equipment.

What the two-claim contract was there to prevent still holds, and it is
the half that matters: **no end is ever dropped because the other end
spoke.** A stream with one stated end and one silent end states the one,
never "whichever of the two is better".

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

   A class **stops the ladder here** by mapping a nozzle to ``None``:
   that nozzle's face is artwork and nothing else, and the class has no
   view on where its peer is drawn. What that is for is the **service**
   connection -- a heater's steam supply, a filter's regenerant, a
   furnace's fuel gas. Steam enters a heater from below because that is
   where the symbol draws the nozzle, and where the steam *header*
   belongs on the sheet is not the heater's business. Read as a claim it
   was five heaters at confidence 2 each asserting their supply lay
   south of them, against a header with no opinion of its own, and the
   header sank below every consumer it fed -- 24 crossings on a sheet
   two pins draw cleanly (#459).
3. **Flow order**: the destination is one step east of the source. A
   recycle is the same statement backwards, since a return line is drawn
   right to left and its two ends are already ordered by the forward run
   it returns along.

   This one is **not** at the author's confidence. It is what the *pipe*
   says, not what the unit says: a unit whose nozzle has a menu nobody
   has picked from, or whose class declared the nozzle empty, has stated
   nothing at all, and weighing that silence as heavily as a stated
   convention makes silence argue. Concretely, a feed over a block's
   roof: the block states north, the feed's silence is read as "east of
   me", the two weigh the same, and the fit splits the difference and
   draws the feed diagonally off the corner. So flow order weighs
   :data:`LINE`, wherever it comes from.

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

What a fitting is *not* given is a claim toward the middle of its two
neighbours. That is the obvious reading of "a valve sits on the line
rather than at a place on the grid", and this grid cannot draw it: the
midpoint of two boxes one column apart is half a column, which
discretises onto one of them, and
:func:`~pandid.layout.place._separate` then hands the valve a **row** of
its own -- lifting it off the very line it was supposed to be sitting
on. Measured over the corpus that is 240 crossings against 338. Blunted,
by letting the fit read the midpoint while
:func:`~pandid.layout.place._spread` goes on giving the fitting its own
column, it still costs 74. Drawing a fitting *between* two columns
rather than in one is a question for :mod:`pandid.layout.coordinates`,
which owns where a column's paper begins and ends, and not for the
claims.
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
#: is the *pipe* that states it, not either unit, because a return's
#: nozzles are read for nothing (see :func:`read`).
#:
#: Twice :data:`LINE`, and stated once rather than once per end. Written
#: the other way -- which is what this was, both ends emitting the
#: identical pull at ``LINE`` -- it is the same arithmetic with the
#: doubling hidden inside a loop, so a return held a loop together twice
#: as stiffly as a silent forward run held its own two ends and nothing
#: said so. Undoing the doubling instead takes the corpus from 240
#: crossings to 321: a return is often the *only* run joining a loop's
#: two halves, where a silent forward run nearly always has a stated
#: claim somewhere beside it, and halved it lets the loop come apart. So
#: the doubling stays, and is written down.
RETURN = 0.5

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
            step = _flow_step(1, True)
            out.append(Claim(src, dst, step[0], step[1], RETURN))
            continue
        spoke = False
        for author, port_name, subject, forward in ends:
            direction, confidence = _placed(author, port_name)
            if confidence <= 0.0:
                continue  # an in-line fitting has nothing to say; see above
            if direction is None:
                # The unit has said nothing about this nozzle -- its
                # face is a menu no one has picked from, or its class
                # mapped the nozzle to ``None`` -- so what is left is
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


def _placed(unit: "Unit", port_name: str) -> tuple[str | None, float]:
    """Where *unit* says its peer on *port_name* is drawn, and what that is worth.

    The ladder in the module docstring, in order: the class's
    :attr:`~pandid.units.Unit.PLACES` entry, then the face the symbol
    fixed the nozzle to, then ``None`` -- which is this unit saying
    nothing, and leaves the caller to read the pipe instead.

    The confidence is the class's own unless the entry overrides it,
    which is how a column can insist on its overhead and merely prefer
    its side draws. The caller drops anything at 0; what is returned
    with it does not matter, and the check is here only so a class that
    states nothing does not pay for a face nobody will read.

    ``PLACES`` is looked up by the port's own name first and then by the
    family name, so ``{"feed": "W"}`` covers a tower with eight of them
    without listing eight keys.
    """
    confidence = float(type(unit).LAYOUT_CONFIDENCE)
    places = type(unit).PLACES
    # Asked with ``in`` rather than ``get``, because an entry **of**
    # ``None`` and no entry at all are different answers and ``get``
    # returns ``None`` to both: no entry reads the face next, an empty
    # entry is the class saying that face is artwork and stopping here.
    key = port_name if port_name in places else family(port_name)
    if key in places:
        entry = places[key]
        if entry is None:
            return None, confidence
        if isinstance(entry, tuple):
            return entry[0], float(entry[1])
        return entry, confidence
    if confidence <= 0.0:
        return None, confidence  # nothing to say; do not resolve a face for it
    return fixed_face(unit, port_name, slot(unit)), confidence


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
