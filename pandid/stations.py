"""Valve stations: the assembly a control valve is installed in.

A control valve is never a valve on its own. It sits in a standard
arrangement that every P&ID in the industry draws the same way, and the
**CHEE4001/7103 P&ID guidelines** (p.4, corroborated by the *EXAMPLE of
a control valve system* figure on p.5) state it:

    "The basic arrangement of a control valve has two isolation
    valves and two drain valves on each side of the control valve,
    and a bypass pipe outside of the isolation valves with a
    throttling valve on it. Most control valves are smaller in
    nominal pipe size than the traveling-size pipe, in order to
    provide appropriate throttling characteristics over a given
    range, so reducers are commonly needed."

The prose is ambiguous about "two ... on each side"; the figure is not.
Read off the drawing, along the run:

    bypass takeoff, isolation valve, drain tee, reduction,
    control valve, expansion, drain tee, isolation valve,
    bypass rejoin

with the bypass carried below on one throttling valve, tapped
**outside** both isolation valves. That is two isolation valves, two
drains, one bypass valve and a size change at each end: eight devices
and four tees, wired by twelve streams, for one control valve. Spelling
it out is how mistakes get in: a station is easy to draw with no
isolation valves at all, and nothing about the drawing says so.

So the assembly is declared once, here, and
:meth:`~pandid.flowsheet.Flowsheet.add_valve_station` builds it.

**A station is not a unit.** It has no symbol, no ports of its own and
no tag; it never enters :attr:`~pandid.flowsheet.Flowsheet.units` and so
reaches no equipment list, and nothing in layout, routing, rendering or
:mod:`pandid.spec` has to know it exists. What it is is a *constructor
and a handle*: after the call the flowsheet holds twelve ordinary units
and twelve ordinary streams, and :class:`ValveStation` is the names by
which the author reaches them to pin, re-tag or instrument any one::

    station = fs.add_valve_station("CV-303", x=670, y=440,
                                   mirrored=True)
    fs.connect(fic303.sig_out, station.control.actuator,
               kind="pneumatic")
    station.bypass.pin(x=station.reduction.pin_.x)

That is also why a station needs no spec section and no round-trip of
its own: :meth:`~pandid.flowsheet.Flowsheet.to_dict` writes the members
out, and reading them back gives the same drawing. Nothing is lost
because after the call there is nothing left of the station that the
drawing depends on.

Tags
----

The guidelines are explicit that this part is local practice, *"the
symbols used to show the equipment, valves, instruments, and control
loops typically depend on the practice of the particular design
office"*, and the issued sheet in ``professional_examples/P&ID_301.pdf``
tags **none** of a station's hand valves or reducers, writing only the
control valve's own tag. So the derivation is a scheme with a common
default, exactly as
:data:`~pandid.flowsheet.DEFAULT_LINE_NUMBERING_SCHEME` is: set it once
on the :class:`~pandid.flowsheet.Flowsheet` for a site, or per station.
:data:`DEFAULT_VALVE_STATION_TAG_SCHEME` spells ``CV-303`` out as
``HV-303A`` through ``HV-303E`` and ``RD-303A``/``RD-303B``, which is
the convention most sheets use and the one the reference sheet's own
control valve numbering fits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from pandid.ports import Port
    from pandid.units import Reducer, Tee, Unit, Valve

#: How a station's members are tagged from the control valve's.
#: ``letters`` and ``suffix`` come from the member's role (the table
#: below), ``number`` from the control valve's tag, and ``control`` is
#: that whole tag. A site spelling them ``HV303A`` sets
#: ``"{letters}{number}{suffix}"``; anything a format string cannot say
#: is a callable taking ``(role, control_tag)``.
DEFAULT_VALVE_STATION_TAG_SCHEME = "{letters}-{number}{suffix}"

#: The functional letters and the suffix each role takes under a scheme.
#: The order is the one a valve list reads in (both isolations, then the
#: bypass, then both drains) rather than the order the devices sit in
#: along the run.
TAG_PARTS: dict[str, tuple[str, str]] = {
    "upstream_isolation": ("HV", "A"),
    "downstream_isolation": ("HV", "B"),
    "bypass": ("HV", "C"),
    "upstream_drain": ("HV", "D"),
    "downstream_drain": ("HV", "E"),
    "reduction": ("RD", "A"),
    "expansion": ("RD", "B"),
}

#: What each role is called in a member's description, after the
#: station's own ``description`` word: ``description="Reflux"`` gives
#: ``"Reflux Isolation Valve"``. A tee takes none, being bulk pipe with
#: nothing written against it.
ROLE_WORDS: dict[str, str] = {
    "upstream_isolation": "Isolation Valve",
    "downstream_isolation": "Isolation Valve",
    "bypass": "Bypass Valve",
    "upstream_drain": "Upstream Drain Valve",
    "downstream_drain": "Downstream Drain Valve",
    "reduction": "Inlet Reducer",
    "expansion": "Outlet Expander",
}

#: The members a bypass valve may be stood over, plus ``None`` for the
#: middle of its own leg. See
#: :meth:`~pandid.flowsheet.Flowsheet.add_valve_station`.
BYPASS_ANCHORS = ("upstream_isolation", "reduction", "control", "expansion",
                  "downstream_isolation")

#: Edge of one device to the edge of the next, along the run. The router
#: needs about 25 units to leave a nozzle before it may turn, so a
#: facing pair closer than that sends the run doubling back on itself.
DEFAULT_GAP = 30.0

#: How far the bypass leg stands off the run, and how far a drain leg
#: drops below it. Both measured from the run's centreline.
DEFAULT_BYPASS_RISE = 45.0
DEFAULT_DRAIN_DROP = 36.0


@dataclass(frozen=True)
class ValveStation:
    """The members of one control valve station, by the part each plays.

    Built by :meth:`~pandid.flowsheet.Flowsheet.add_valve_station`,
    never directly. Every field is an ordinary
    :class:`~pandid.units.Unit` already on the flowsheet and already
    connected to its neighbours, so anything that can be done to a unit
    can be done to one of these. A member the station was told to leave
    out is ``None``.

    The handle itself is frozen: which valve is the bypass is a fact
    about the assembly, and rebinding it here would rename a part
    without moving anything on the sheet.
    """

    #: The control valve the station exists for. Its ``actuator`` is
    #: where a controller's output lands.
    control: "Valve"
    upstream_isolation: "Valve | None"
    downstream_isolation: "Valve | None"
    #: The size change into the control valve, and the one back out of
    #: it.
    reduction: "Reducer | None"
    expansion: "Reducer | None"
    #: The throttling valve on the bypass leg, normally closed.
    bypass: "Valve | None"
    upstream_drain: "Valve | None"
    downstream_drain: "Valve | None"
    #: The junctions, in run order: bypass takeoff, drain tees, bypass
    #: rejoin. They carry no tag and reach no equipment list; see
    #: :class:`~pandid.units.Tee`.
    tees: tuple["Tee", ...]
    #: Every member in the order the run passes through it, tees
    #: included. What to iterate to re-pin or re-describe a whole
    #: station.
    members: tuple["Unit", ...]
    #: Where the run enters and leaves the station. Connect to these
    #: exactly as to any other port: the station is a length of line,
    #: and the piping either side of it is the author's.
    inlet: "Port"
    outlet: "Port"

    def __repr__(self) -> str:
        return f"ValveStation({self.control.name!r}, members={len(self.members)})"


def member_tag(scheme: "str | Callable[[str, str], str]", role: str,
               control_tag: str, number: str) -> str:
    """The tag one member takes under ``scheme``.

    A callable is handed the role and the control valve's whole tag and
    is trusted with the answer. A format string is filled from
    :data:`TAG_PARTS`.
    """
    if callable(scheme):
        return scheme(role, control_tag)
    letters, suffix = TAG_PARTS[role]
    try:
        return scheme.format(letters=letters, number=number, suffix=suffix,
                             role=role, control=control_tag)
    except (KeyError, IndexError) as exc:
        raise ValueError(
            f"valve_station_tag_scheme {scheme!r} asks for {exc.args[0]!r}, which is "
            f"not part of a station member's tag; the fields are 'letters', 'number', "
            f"'suffix', 'role' and 'control'"
        ) from None


def member_mirror(mirrored: bool, branch_north: bool) -> bool | str:
    """The flip one member takes, from the station and its branch.

    A station piped east to west is the same run drawn the other way
    round, so every member gains a left-right flip and takes flow on its
    east face. The two bypass tees carry a top-bottom flip on top of
    that, because a :class:`~pandid.units.Tee` branches south as drawn
    and the bypass leg is over the run, not under it.
    """
    if mirrored:
        return "xy" if branch_north else "x"
    return "y" if branch_north else False


def station_number(control_tag: str) -> str:
    """The number a station's members take, off the control valve.

    ``"CV-303"`` gives ``"303"``. A tag the split cannot find a number
    in answers with the whole tag, so the scheme still produces
    something unique rather than colliding every member on an empty
    string.
    """
    from pandid.units import split_tag

    _, number = split_tag(control_tag)
    return number or control_tag
