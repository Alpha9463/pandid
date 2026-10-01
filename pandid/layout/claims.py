"""Read the placement claims that process streams make about their two ends.

A claim says that one unit (the author) expects another (the subject) a
number of grid steps away. The placement solve
(:mod:`pandid.layout.solver`) fits every claim by weighted least squares,
so two ends of one stream may disagree; the solve weighs them rather than
dropping either.

Each end of a stream speaks for itself. Its direction comes from, in
order:

1. the class's :attr:`~pandid.units.Unit.PLACES` entry for the port, or
   for the port's numbered family (``feed`` covers ``feed_1``);
2. the face the symbol fixes the nozzle to (:func:`fixed_face`).

Both are read as drawn, so a turned or mirrored unit states turned
directions. Either claim weighs the class's
:attr:`~pandid.units.Unit.LAYOUT_CONFIDENCE` unless the ``PLACES`` entry
gives its own weight.

An end whose port has a face menu, or whose ``PLACES`` entry is ``None``
(a service connection such as a heater's steam), states only flow order:
the destination lies one column east, at weight :data:`LINE`. A unit with
confidence 0 (a valve, fitting or reducer) states nothing. If neither end
speaks, the stream states flow order once at :data:`LINE`, so inline
devices never leave the sheet disconnected. A return line states only
that its source lies east of its destination, at :data:`RETURN`.

Vertical position is a drafting convention, not elevation: a condenser is
drawn above and to the right of its column because the column's
``PLACES`` says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from pandid.layout.stages import slot
from pandid.portgeom import COMPASS, drawn_direction

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Unit

#: Weight of a claim the stream makes without a stated direction. It is
#: below every unit confidence, so flow order never outweighs a unit.
LINE = 0.25

#: Weight of a return line's single claim. Twice :data:`LINE`, because a
#: return is often the only run holding a loop's two halves together.
RETURN = 0.5

#: Compass point to ``(eastward, southward)`` grid steps, with south
#: positive on the y-down canvas. Shared with
#: :func:`~pandid.portgeom.drawn_direction` so a claim and its transform
#: use one table.
STEPS = COMPASS


class Claim(NamedTuple):
    """State that ``subject`` is drawn a number of grid steps from ``author``.

    Attributes
    ----------
    author : Unit
        Unit making the claim.
    subject : Unit
        Unit the claim places.
    eastward, southward : int
        Grid steps from ``author`` to ``subject``; positive is east and
        south.
    confidence : float
        Weight in the least-squares fit. It resists movement at both ends,
        so a pinned subject moves an unpinned author.
    """

    author: "Unit"
    subject: "Unit"
    eastward: int
    southward: int
    confidence: float


def read(streams: list["Stream"]) -> list[Claim]:
    """Read every claim the given streams make, in stream order.

    The order is deterministic because the solve sums weights in the
    order given, and floating-point addition is not associative.

    Parameters
    ----------
    streams : list[Stream]
        Process streams whose ends both have an owner.

    Returns
    -------
    list[Claim]
        Zero to two claims per stream, in stream order.
    """
    out: list[Claim] = []
    for stream in streams:
        src, dst = stream.source.owner, stream.dest.owner
        assert src is not None and dst is not None
        if src is dst:
            continue  # a run from a unit back to itself places nothing
        ends = ((src, stream.source.name, dst, 1), (dst, stream.dest.name, src, -1))
        if stream.is_recycle:
            # A return leaves an east face and runs back west, so its
            # nozzle faces would state the loop backwards. Read only that
            # its source lies further along than its destination.
            step = _flow_step(1, True)
            out.append(Claim(src, dst, step[0], step[1], RETURN))
            continue
        spoke = False
        for author, port_name, subject, forward in ends:
            direction, confidence = _placed(author, port_name)
            if confidence <= 0.0:
                continue  # an inline device states nothing
            if direction is None:
                # No stated direction: only flow order, at the pipe's
                # weight, so it cannot pull a stated claim off its line.
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
    """Return the step flow order alone gives from an author to its peer.

    Parameters
    ----------
    forward : int
        ``1`` when the author is the stream's source, ``-1`` when it is the
        destination.
    is_recycle : bool
        Whether the stream is a return line, which is drawn right to left.

    Returns
    -------
    tuple[int, int]
        ``(eastward, southward)`` grid step.
    """
    return (-forward if is_recycle else forward, 0)


def _placed(unit: "Unit", port_name: str) -> tuple[str | None, float]:
    """Return the direction a unit states for a port's peer, and its weight.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port connected to the peer.

    Returns
    -------
    tuple[str | None, float]
        Compass direction as drawn, or ``None`` when the unit states no
        direction, and the claim weight. A weight of 0 means the unit
        states nothing at all.
    """
    confidence = float(type(unit).LAYOUT_CONFIDENCE)
    places = type(unit).PLACES
    # Test membership: an entry of ``None`` (face is artwork only) differs
    # from no entry (read the fixed face next).
    key = port_name if port_name in places else family(port_name)
    if key in places:
        entry = places[key]
        if entry is None:
            return None, confidence
        direction, weight = entry if isinstance(entry, tuple) else (entry, confidence)
        return drawn_direction(direction, slot(unit)), float(weight)
    if confidence <= 0.0:
        return None, confidence  # nothing to say; do not resolve a face for it
    return fixed_face(unit, port_name, slot(unit)), confidence


def family(port_name: str) -> str:
    """Return the family name of a numbered port.

    Only a trailing ``_<digits>`` is removed, so ``feed_3`` becomes
    ``feed`` and ``shell_in`` is unchanged.

    Parameters
    ----------
    port_name : str
        Port name.

    Returns
    -------
    str
        Name without its numeric suffix.
    """
    head, _, tail = port_name.rpartition("_")
    return head if head and tail.isdigit() else port_name


def fixed_face(unit: "Unit", port_name: str, placed: object) -> str | None:
    """Return the face a port is drawn on when it has only one.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port to resolve.
    placed : object
        Placement to answer for, normally the solver's ``_Slot`` seeded from
        the author's pin. The previous frame is not used, so laying out
        twice gives the same answer.

    Returns
    -------
    str or None
        Face stated with ``nozzle()``, the symbol's only face, or ``None``
        when the port has a menu that :mod:`pandid.layout.faces` chooses
        from later.
    """
    from pandid.portgeom import port_faces

    named = getattr(unit, "_port_faces", None) or {}
    if port_name in named:
        return str(named[port_name]).upper()
    menu = port_faces(unit, port_name, placed)
    return menu[0] if len(menu) == 1 else None


def stacks(fs: "Flowsheet", units: list["Unit"]) -> dict["Unit", "Unit"]:
    """Map each unit to the representative of its stack.

    A stack is a set of units joined by process streams and placed in one
    grid column. :func:`~pandid.layout.coordinates._straighten` moves a
    stack as one group.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose process streams join the units.
    units : list[Unit]
        Units with settled grid columns.

    Returns
    -------
    dict[Unit, Unit]
        Representative unit for each unit; units in one stack share it.
    """
    from pandid.layout.stages import process_streams

    lead = {u: u for u in units}

    def find(u: "Unit") -> "Unit":
        """Return the representative of a unit's stack.

        Parameters
        ----------
        u : Unit
            Unit to look up.

        Returns
        -------
        Unit
            Stack representative, with the path compressed.
        """
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
