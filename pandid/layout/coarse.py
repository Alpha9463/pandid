"""Place equipment with each furnished pipe contracted to its two nozzles."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from pandid.geometry import Frame
from pandid.layout import claims as claims_mod
from pandid.layout.coordinates import COL_GAP, assign_coordinates
from pandid.layout.place import assign_positions
from pandid.layout.stages import process_streams, process_units, slot
from pandid.portgeom import port_offset, resolve_size

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.stations import StationAssembly
    from pandid.streams import Stream
    from pandid.units import Unit


class Host(NamedTuple):
    """External nozzles and physical ends of a contracted material run.

    Attributes
    ----------
    source, dest : Port
        External nozzles retained in the equipment solve.
    first, last : Stream
        Physical segments carrying each endpoint's placement claims.
    recycle : bool
        Whether cycle breaking marked any segment of the run as a return.
    """

    source: Port
    dest: Port
    first: Stream
    last: Stream
    recycle: bool = False


def _position_pinned(unit: Unit) -> bool:
    """Check whether a station member has an exact placement constraint.

    Parameters
    ----------
    unit : Unit
        Station member to inspect.

    Returns
    -------
    bool
        Whether a grid or pixel position is pinned.
    """
    pin = unit.pin_
    return pin is not None and any(
        getattr(pin, axis) is not None for axis in ("col", "row", "x", "y")
    )


def _claims(fs: Flowsheet, roots: list[Host], retained: list[Unit]) -> list[claims_mod.Claim]:
    """Replace each attachment chain's internal claims with endpoint claims.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose material graph is inspected.
    roots : list[Host]
        External host runs with contracted attachments.
    retained : list[Unit]
        Process units outside the attachment chains.

    Returns
    -------
    list[Claim]
        Original external claims and projected host claims.
    """
    active = set(retained)
    streams = [stream for stream in process_streams(fs)
               if stream.source.owner in active and stream.dest.owner in active]
    out = claims_mod.read(streams)
    for root in roots:
        first, last = root.first, root.last
        source_unit, dest_unit = root.source.owner, root.dest.owner
        assert source_unit is not None and dest_unit is not None
        for stream, author, subject in ((first, source_unit, dest_unit),
                                        (last, dest_unit, source_unit)):
            out.extend(claims_mod.Claim(author, subject, claim.eastward,
                                        claim.southward, claim.confidence)
                       for claim in claims_mod.read([stream]) if claim.author is author)
        if not root.recycle:  # a return line runs against the flow, so it claims no east
            out.append(claims_mod.Claim(source_unit, dest_unit, 1, 0, claims_mod.LINE))
    return out


def _station_width(assemblies: list[StationAssembly]) -> float:
    """Measure the main legs of stations sharing one host run.

    Parameters
    ----------
    assemblies : list[StationAssembly]
        Stations ordered along one logical run.

    Returns
    -------
    float
        Required horizontal room for the station members.
    """
    width = 16.0
    for assembly in assemblies:
        station = assembly.station
        branch = {station.bypass, station.upstream_drain, station.downstream_drain}
        main = [unit for unit in station.members if unit not in branch]
        width += sum(resolve_size(unit)[0] for unit in main)
        width += assembly.gap * (len(main) - 1) + 16.0
    return width


def _end_clearance(source: Unit, source_port: str, dest: Unit,
                   dest_port: str, forward: bool) -> float:
    """Reserve equipment bodies between host nozzles and station members.

    Parameters
    ----------
    source, dest : Unit
        Equipment at the host run's ends.
    source_port, dest_port : str
        Connected nozzle names.
    forward : bool
        Whether the destination has the higher column rank.

    Returns
    -------
    float
        Additional horizontal clearance beyond the nozzle span.
    """
    source_slot, dest_slot = slot(source), slot(dest)
    source_x = port_offset(source, source_port, source_slot)[0]
    dest_x = port_offset(dest, dest_port, dest_slot)[0]
    body = ((source_slot.w - source_x) + dest_x if forward
            else source_x + (dest_slot.w - dest_x))
    return body + 41.0  # one 25px nozzle exit and 8px body clearance at each end


def _nominal_nozzle_span(host: Host, bodies: dict[int, float]) -> float:
    """Measure the minimum nozzle span supplied by occupied grid columns.

    Parameters
    ----------
    host : Host
        External ports of a contracted material run.
    bodies : dict[int, float]
        Widest retained equipment body in each occupied column.

    Returns
    -------
    float
        Horizontal nozzle separation before attachment reservations.
    """
    source, dest = host.source.owner, host.dest.owner
    assert source is not None and dest is not None
    source_col, dest_col = slot(source).col, slot(dest).col
    assert source_col is not None and dest_col is not None
    left_col, right_col = sorted((source_col, dest_col))
    left_port, right_port = ((host.source, host.dest) if source_col < dest_col
                             else (host.dest, host.source))
    left, right = left_port.owner, right_port.owner
    assert left is not None and right is not None
    columns = sum(body + COL_GAP for col, body in bodies.items()
                  if left_col <= col < right_col)
    left_x = port_offset(left, left_port.name, slot(left))[0]
    right_x = port_offset(right, right_port.name, slot(right))[0]
    return columns + right_x - left_x


def _equipment_frames(fs: Flowsheet, widths: list[tuple[Host, float]],
                      members: set[Unit], *, unaligned: frozenset[int] = frozenset()) -> None:
    """Resolve equipment positions while reserving attachment footprints.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose slots have been seeded from authored pins.
    widths : list[tuple[Host, float]]
        Host runs and their required horizontal attachment space.
    members : set[Unit]
        Attachment units excluded from the equipment solve.
    unaligned : frozenset[int], optional
        Global indices of units kept on their row axis.

    Returns
    -------
    None
        Retained units have frames; members have placeholder frames.
    """
    roots = [root for root, _ in widths]
    retained = [unit for unit in process_units(fs) if unit not in members]
    assign_positions(fs, units=retained, claims=_claims(fs, roots, retained))
    bodies: dict[int, float] = {}
    for unit in retained:
        column = slot(unit).col
        assert column is not None
        bodies[column] = max(bodies.get(column, 0.0), slot(unit).w)
    absolute_pin = any(unit.pin_ is not None
                       and (unit.pin_.x is not None or unit.pin_.y is not None)
                       for unit in retained)
    boundaries: dict[tuple[int, int], int] = {}
    for root in roots:
        source, dest = root.source.owner, root.dest.owner
        assert source is not None and dest is not None
        source_col, dest_col = slot(source).col, slot(dest).col
        assert source_col is not None and dest_col is not None
        boundary = (min(source_col, dest_col), max(source_col, dest_col))
        boundaries[boundary] = boundaries.get(boundary, 0) + 1
    gap: dict[int, float] = {}
    for root, width in widths:
        source_unit, dest_unit = root.source.owner, root.dest.owner
        assert source_unit is not None and dest_unit is not None
        source_col, dest_col = slot(source_unit).col, slot(dest_unit).col
        assert source_col is not None and dest_col is not None
        span = abs(dest_col - source_col)
        if span == 0:
            continue  # a run within one column reserves no column gap
        column = min(source_col, dest_col)
        if absolute_pin:
            clearance = _end_clearance(source_unit, root.source.name,
                                       dest_unit, root.dest.name, source_col < dest_col)
            need = max(0.0, width + clearance - span * COL_GAP)
        else:
            boundary = (min(source_col, dest_col), max(source_col, dest_col))
            shared = boundaries[boundary] - 1
            clearance = 41.0 + shared * bodies[column]
            need = max(0.0, width + clearance - _nominal_nozzle_span(root, bodies))
        gap[column] = max(gap.get(column, 0.0), need)
    links = []
    for root in roots:
        source_unit, dest_unit = root.source.owner, root.dest.owner
        assert source_unit is not None and dest_unit is not None
        links.append((source_unit, dest_unit, claims_mod.LINE))
    assign_coordinates(fs, units=retained, extra_gap=gap, links=links, hosts=roots,
                       unaligned=unaligned)
    for unit in members:
        placed = slot(unit)
        unit.frame = Frame(x=0.0, y=0.0, w=placed.w, h=placed.h,
                           orientation=placed.orientation, mirrored=placed.mirrored,
                           mirror_y=placed.mirror_y)
