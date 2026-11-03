"""Control valve stations: the assembly a control valve sits in.

A full station runs along the line as bypass takeoff, isolation
valve, drain tee, reducer, control valve, expander, drain tee,
isolation valve and bypass rejoin, with a throttling valve on the
bypass leg.
:meth:`~pandid.flowsheet.Flowsheet.add_valve_station` builds one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from pandid.ports import Port
    from pandid.streams import Stream
    from pandid.units import Reducer, Tee, Unit, Valve

#: Default member tag scheme. Its fields are ``letters``, ``number``,
#: ``suffix``, ``role`` and ``control`` (the control valve's tag).
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

#: Words appended to the station's ``description`` for each member.
ROLE_WORDS: dict[str, str] = {
    "upstream_isolation": "Isolation Valve",
    "downstream_isolation": "Isolation Valve",
    "bypass": "Bypass Valve",
    "upstream_drain": "Upstream Drain Valve",
    "downstream_drain": "Downstream Drain Valve",
    "reduction": "Inlet Reducer",
    "expansion": "Outlet Expander",
}

#: Members a bypass valve may be centred over.
BYPASS_ANCHORS = ("upstream_isolation", "reduction", "control", "expansion",
                  "downstream_isolation")

#: Gap between adjacent devices along the run.
DEFAULT_GAP = 30.0

#: Offsets of the bypass leg above the run and a drain leg below it.
DEFAULT_BYPASS_RISE = 45.0
DEFAULT_DRAIN_DROP = 36.0


@dataclass(frozen=True)
class ValveStation:
    """The members of one control valve station, by role.

    An omitted member is ``None``.

    Attributes
    ----------
    control : Valve
        The control valve.
    upstream_isolation, downstream_isolation : Valve or None
        Isolation valves either side of the control valve.
    reduction, expansion : Reducer or None
        Size change into and out of the control valve.
    bypass : Valve or None
        Normally closed throttling valve on the bypass leg.
    upstream_drain, downstream_drain : Valve or None
        Drain valves.
    tees : tuple[Tee, ...]
        Junctions in run order.
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
        """Return a short representation naming the control valve.

        Returns
        -------
        str
            ``ValveStation(<control tag>, members=<count>)``.
        """
        return f"ValveStation({self.control.name!r}, members={len(self.members)})"


@dataclass(frozen=True)
class StationAssembly:
    """Members and relative placement of one station.

    Attributes
    ----------
    station : ValveStation
        Station whose members move together.
    mirrored : bool
        Whether flow runs right to left.
    gap, bypass_rise, drain_drop : float
        Spacing along the run, up to the bypass and down to a drain.
    bypass_over : str or None
        Member the bypass valve is centred over.
    run : Stream or None
        Run the station was inserted into, if any.
    at : float or None
        Fraction along that run.
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
        Format string, or a callable taking ``(role, control_tag)``.
    role : str
        Member role, a key of :data:`TAG_PARTS`.
    control_tag : str
        Control valve's tag.
    number : str
        Number taken from the control tag.

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
    """Return the mirror setting a station member is pinned with.

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
    """Return the control tag's number, or the whole tag if none.

    Parameters
    ----------
    control_tag : str
        Control valve's tag, such as ``"CV-303"``.

    Returns
    -------
    str
        Its number, such as ``"303"``, or the whole tag.
    """
    from pandid.units import split_tag

    _, number = split_tag(control_tag)
    return number or control_tag
