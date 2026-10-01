"""Define control valve stations: the assembly a control valve sits in.

A standard station, following the CHEE4001/7103 P&ID guidelines (pp. 4-5),
runs along the line as::

    bypass takeoff, isolation valve, drain tee, reduction,
    control valve, expansion, drain tee, isolation valve,
    bypass rejoin

with a bypass leg carrying one throttling valve, tapped outside both
isolation valves. That is eight devices and four tees joined by twelve
streams. :meth:`~pandid.flowsheet.Flowsheet.add_valve_station` builds it.

A station is not a unit: it has no symbol, ports or equipment-list entry.
Its members are ordinary units and streams, reached through
:class:`ValveStation`::

    station = fs.add_valve_station("CV-303", x=670, y=440,
                                   mirrored=True)
    fs.connect(fic303.sig_out, station.control.actuator,
               kind="pneumatic")
    station.bypass.pin(x=station.reduction.pin_.x)

Pinned stations round-trip through their members' pins; unpinned stations
also save their assembly record so their relative geometry survives.

Member tags follow a scheme set on the flowsheet or per station.
:data:`DEFAULT_VALVE_STATION_TAG_SCHEME` tags the members of ``CV-303`` as
``HV-303A`` to ``HV-303E`` and ``RD-303A``/``RD-303B``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from pandid.ports import Port
    from pandid.streams import Stream
    from pandid.units import Reducer, Tee, Unit, Valve

#: Default member tag scheme. ``letters`` and ``suffix`` come from the
#: member's role (:data:`TAG_PARTS`), ``number`` from the control valve's
#: tag, and ``control`` is the whole control tag. A callable taking
#: ``(role, control_tag)`` may be used instead of a format string.
DEFAULT_VALVE_STATION_TAG_SCHEME = "{letters}-{number}{suffix}"

#: Functional letters and suffix per member role, in valve-list order.
TAG_PARTS: dict[str, tuple[str, str]] = {
    "upstream_isolation": ("HV", "A"),
    "downstream_isolation": ("HV", "B"),
    "bypass": ("HV", "C"),
    "upstream_drain": ("HV", "D"),
    "downstream_drain": ("HV", "E"),
    "reduction": ("RD", "A"),
    "expansion": ("RD", "B"),
}

#: Words appended to the station's ``description`` for each member, so
#: ``description="Reflux"`` gives ``"Reflux Isolation Valve"``. Tees take
#: none.
ROLE_WORDS: dict[str, str] = {
    "upstream_isolation": "Isolation Valve",
    "downstream_isolation": "Isolation Valve",
    "bypass": "Bypass Valve",
    "upstream_drain": "Upstream Drain Valve",
    "downstream_drain": "Downstream Drain Valve",
    "reduction": "Inlet Reducer",
    "expansion": "Outlet Expander",
}

#: Members a bypass valve may be centred over. ``None`` centres it on its
#: own leg; see :meth:`~pandid.flowsheet.Flowsheet.add_valve_station`.
BYPASS_ANCHORS = ("upstream_isolation", "reduction", "control", "expansion",
                  "downstream_isolation")

#: Gap between adjacent devices along the run. It exceeds the router's
#: 25-unit nozzle stand-off, so a run cannot double back between them.
DEFAULT_GAP = 30.0

#: Offsets of the bypass leg above the run and of a drain leg below it,
#: from the run's centreline.
DEFAULT_BYPASS_RISE = 45.0
DEFAULT_DRAIN_DROP = 36.0


@dataclass(frozen=True)
class ValveStation:
    """The members of one control valve station, by role.

    Built by :meth:`~pandid.flowsheet.Flowsheet.add_valve_station`. Every
    member is an ordinary connected unit on the flowsheet; an omitted
    member is ``None``. The handle is frozen so roles cannot be rebound.

    Attributes
    ----------
    control : Valve
        The control valve; a controller output connects to its
        ``actuator``.
    upstream_isolation, downstream_isolation : Valve or None
        Isolation valves either side of the control valve.
    reduction, expansion : Reducer or None
        Size change into and out of the control valve.
    bypass : Valve or None
        Normally closed throttling valve on the bypass leg.
    upstream_drain, downstream_drain : Valve or None
        Drain valves.
    tees : tuple[Tee, ...]
        Junctions in run order: bypass takeoff, drain tees, bypass rejoin.
    members : tuple[Unit, ...]
        Every member in run order, tees included.
    inlet, outlet : Port
        Where the run enters and leaves the station.
    """

    control: "Valve"
    upstream_isolation: "Valve | None"
    downstream_isolation: "Valve | None"
    reduction: "Reducer | None"
    expansion: "Reducer | None"
    bypass: "Valve | None"
    upstream_drain: "Valve | None"
    downstream_drain: "Valve | None"
    tees: tuple["Tee", ...]
    members: tuple["Unit", ...]
    inlet: "Port"
    outlet: "Port"

    def __repr__(self) -> str:
        """Return a short representation naming the control valve."""
        return f"ValveStation({self.control.name!r}, members={len(self.members)})"


@dataclass(frozen=True)
class StationAssembly:
    """Retain the members and relative placement of one station.

    Attributes
    ----------
    station : ValveStation
        Wired station whose members move together.
    mirrored : bool
        Whether material flows from right to left through the station.
    gap, bypass_rise, drain_drop : float
        Local spacing between main members and branch members.
    bypass_over : str or None
        Optional main member beneath the bypass valve.
    run : Stream or None
        Original material run handle when inserted with the station API.
    at : float or None
        Preferred fraction of that complete run.
    """

    station: ValveStation
    mirrored: bool
    gap: float
    bypass_rise: float
    drain_drop: float
    bypass_over: str | None
    run: Stream | None = None
    at: float | None = None


def member_tag(scheme: "str | Callable[[str, str], str]", role: str,
               control_tag: str, number: str) -> str:
    """Return a member's tag under a tag scheme.

    Parameters
    ----------
    scheme : str or Callable[[str, str], str]
        Format string filled from :data:`TAG_PARTS`, or a callable taking
        ``(role, control_tag)``.
    role : str
        Member role, a key of :data:`TAG_PARTS`.
    control_tag : str
        Control valve's tag.
    number : str
        Number taken from the control tag (:func:`station_number`).

    Returns
    -------
    str
        Member tag.

    Raises
    ------
    ValueError
        If the format string names an unknown field.
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
    """Return the flip a station member takes.

    A station piped east to west flips every member left to right. Bypass
    tees also flip top to bottom, because a :class:`~pandid.units.Tee`
    branches south as drawn and the bypass leg runs above the line.

    Parameters
    ----------
    mirrored : bool
        Whether the station is piped east to west.
    branch_north : bool
        Whether the member is a bypass tee.

    Returns
    -------
    bool or str
        Mirror setting for :meth:`pandid.units.Unit.pin`.
    """
    if mirrored:
        return "xy" if branch_north else "x"
    return "y" if branch_north else False


def station_number(control_tag: str) -> str:
    """Return the number a station's members take from the control tag.

    Parameters
    ----------
    control_tag : str
        Control valve's tag, such as ``"CV-303"``.

    Returns
    -------
    str
        Its number (``"303"``), or the whole tag when it has no number, so
        member tags stay unique.
    """
    from pandid.units import split_tag

    _, number = split_tag(control_tag)
    return number or control_tag
