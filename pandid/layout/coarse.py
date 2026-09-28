"""Place equipment before expanding stream-relative valve stations."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Literal, NamedTuple

from pandid.geometry import Frame
from pandid.layout import claims as claims_mod
from pandid.layout.backbone import infer_backbone
from pandid.layout.coordinates import COL_GAP, assign_coordinates
from pandid.layout.place import assign_positions
from pandid.layout.stages import process_streams, process_units, slot
from pandid.layout.station import place_stations
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
    """

    source: Port
    dest: Port
    first: Stream
    last: Stream


Reservation = Literal["conservative", "compact", "shared"]


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


def has_free_station(fs: Flowsheet) -> bool:
    """Check whether any registered station still needs placement.

    Parameters
    ----------
    fs : Flowsheet
        Sheet containing station assemblies.

    Returns
    -------
    bool
        Whether at least one member of an assembly has no position pin.
    """
    return any(not all(_position_pinned(unit) for unit in assembly.station.members)
               for assembly in fs._station_assemblies)


def _groups(fs: Flowsheet) -> list[tuple[Host, list[StationAssembly]]] | None:
    """Collect complete, position-free stations by external host run.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with registered station assemblies.

    Returns
    -------
    list[tuple[Host, list[StationAssembly]]] or None
        Eligible groups, or ``None`` when the full solver is required.
    """
    if not fs._station_assemblies:
        return None
    by_root: dict[int, tuple[Host, list[StationAssembly]]] = {}
    for assembly in fs._station_assemblies:
        pinned = [_position_pinned(unit) for unit in assembly.station.members]
        if all(pinned):
            continue
        if any(pinned):
            return None
        root = assembly.run
        if root is not None:
            dest = root._logical_to
            first = root
            last = dest.stream if dest is not None else None
        else:
            first = assembly.station.inlet.stream
            last = assembly.station.outlet.stream
            dest = last.dest if last is not None else None
        if first is None or last is None or dest is None:
            return None
        host = Host(first.source, dest, first, last)
        key = id(root) if root is not None else id(assembly)
        if key not in by_root:
            by_root[key] = (host, [])
        by_root[key][1].append(assembly)
    if not by_root:
        return None
    members = {unit for _, assemblies in by_root.values()
               for assembly in assemblies for unit in assembly.station.members}
    for host, _ in by_root.values():
        source = host.source.owner
        dest = host.dest.owner
        if (source is None or dest is None or source in members or dest in members
                or source is dest or host.first.is_recycle or host.last.is_recycle):
            return None
    if any(stream.is_recycle or (stream.route is not None and stream.route.manual)
           for stream in process_streams(fs)
           if stream.source.owner in members or stream.dest.owner in members):
        return None
    return list(by_root.values())


def _claims(fs: Flowsheet, roots: list[Host],
            retained: list[Unit]) -> list[claims_mod.Claim]:
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
                      members: set[Unit], reservation: Reservation = "shared") -> bool:
    """Resolve equipment positions while reserving attachment footprints.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose slots have been seeded from authored pins.
    widths : list[tuple[Host, float]]
        Host runs and their required horizontal attachment space.
    members : set[Unit]
        Attachment units excluded from the equipment solve.
    reservation : {"conservative", "compact", "shared"}, optional
        Attachment-corridor estimate to use for this isolated layout.

    Returns
    -------
    bool
        Whether each host has distinct equipment grid columns.
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
            return False
        column = min(source_col, dest_col)
        if absolute_pin or reservation == "conservative":
            clearance = _end_clearance(source_unit, root.source.name,
                                       dest_unit, root.dest.name, source_col < dest_col)
            need = max(0.0, width + clearance - span * COL_GAP)
        else:
            boundary = (min(source_col, dest_col), max(source_col, dest_col))
            shared = boundaries[boundary] - 1 if reservation == "shared" else 0
            clearance = 41.0 + shared * bodies[column]
            need = max(0.0, width + clearance - _nominal_nozzle_span(root, bodies))
        gap[column] = max(gap.get(column, 0.0), need)
    links = []
    for root in roots:
        source_unit, dest_unit = root.source.owner, root.dest.owner
        assert source_unit is not None and dest_unit is not None
        links.append((source_unit, dest_unit, claims_mod.LINE))
    assign_coordinates(fs, units=retained, extra_gap=gap, links=links, hosts=roots)
    for unit in members:
        placed = slot(unit)
        unit.frame = Frame(x=0.0, y=0.0, w=placed.w, h=placed.h,
                           orientation=placed.orientation, mirrored=placed.mirrored,
                           mirror_y=placed.mirror_y)
    return True


def place_equipment_first(fs: Flowsheet, *,
                          reservation: Reservation = "shared") -> bool:
    """Place eligible station assemblies after their external equipment.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose slots have been seeded from authored pins.
    reservation : {"conservative", "compact", "shared"}, optional
        Attachment-corridor estimate for this placement trial.

    Returns
    -------
    bool
        Whether all station assemblies received complete frames.
    """
    groups = _groups(fs)
    if groups is None:
        return False
    members = {unit for _, assemblies in groups
               for assembly in assemblies for unit in assembly.station.members}
    if not _equipment_frames(fs, [(root, _station_width(assemblies))
                                  for root, assemblies in groups], members, reservation):
        return False
    return place_stations(fs) == sum(len(assemblies) for _, assemblies in groups)


def _inline_groups(fs: Flowsheet) -> list[tuple[Stream, list[Unit]]] | None:
    """Collect complete unpinned logical runs of simple inline devices.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with possible stream-relative inline devices.

    Returns
    -------
    list[tuple[Stream, list[Unit]]] or None
        Eligible logical runs, or ``None`` when the full solver is required.
    """
    if has_free_station(fs):
        return None
    roots = [stream for stream in fs.streams if stream._logical_to is not None]
    if not roots:
        return None
    units = process_units(fs)
    backbone = infer_backbone(fs)
    inline = {units[index] for run in backbone.runs for index in run.inline_units}
    streams = process_streams(fs)
    logical_segments = {id(segment) for root in roots for segment in root._logical_segments}
    for run in backbone.runs:
        path = [streams[index] for index in run.streams]
        if any(id(stream) in logical_segments for stream in path) and any(
            stream._inline_at is not None and id(stream) not in logical_segments
            for stream in path
        ):
            return None
    groups: list[tuple[Stream, list[Unit]]] = []
    for root in roots:
        segments = root._logical_segments
        members = [segment.dest.owner for segment in segments[:-1]]
        if not members or any(unit is None or unit not in inline for unit in members):
            return None
        if any(segment._inline_at is None for segment in segments[:-1]) or any(
            segment.is_recycle or (segment.route is not None and segment.route.manual)
            for segment in segments
        ):
            return None
        destination = root._logical_to
        assert destination is not None
        source, dest = root.source.owner, destination.owner
        if source is None or dest is None or source is dest:
            return None
        groups.append((root, [unit for unit in members if unit is not None]))
    return groups


def place_inline_equipment_first(fs: Flowsheet, *,
                                 reservation: Reservation = "shared") -> bool:
    """Place opted-in inline chains after their external equipment.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose slots have been seeded from authored pins.
    reservation : {"conservative", "compact", "shared"}, optional
        Attachment-corridor estimate for this placement trial.

    Returns
    -------
    bool
        Whether every contracted inline device received a host placement.
    """
    from pandid.layout.inline import place_inline

    groups = _inline_groups(fs)
    if groups is None:
        return False
    members = {unit for _, chain in groups for unit in chain}
    widths = []
    for root, chain in groups:
        dest = root._logical_to
        assert dest is not None and dest.stream is not None
        host = Host(root.source, dest, root, dest.stream)
        widths.append((host, sum(resolve_size(unit)[0] for unit in chain)
                       + 8.0 * (len(chain) + 1)))
    if not _equipment_frames(fs, widths, members, reservation):
        return False
    return members <= place_inline(fs, allow_elbows=True)


def _routed_reservation(fs: Flowsheet, reservation: Reservation) -> Flowsheet | None:
    """Settle one detached equipment-first spacing proposal.

    Parameters
    ----------
    fs : Flowsheet
        Completed drawing whose model is reused for the trial.
    reservation : {"conservative", "compact", "shared"}
        Attachment-corridor estimate to evaluate.

    Returns
    -------
    Flowsheet or None
        Completed candidate, or ``None`` if contraction failed.
    """
    import copy

    from pandid.layout import default_layout_engine

    trial = copy.deepcopy(fs)
    default_layout_engine.layout(trial, reservation=reservation)
    if not trial._coarse_layout_candidate:
        return None
    trial._coarse_layout_candidate = False
    trial._layout_stale = False
    trial._route_stale = True
    trial._refinement_attempted = False
    trial.route()
    return trial


def _frame_size(fs: Flowsheet) -> tuple[float, float]:
    """Measure the horizontal and vertical span of resolved units.

    Parameters
    ----------
    fs : Flowsheet
        Completed drawing to measure.

    Returns
    -------
    tuple[float, float]
        Width and height in drawing pixels.
    """
    frames = [unit.frame for unit in fs.units if unit.frame is not None]
    if not frames:
        return 0.0, 0.0
    return (max(frame.x_max for frame in frames) - min(frame.x for frame in frames),
            max(frame.y_max for frame in frames) - min(frame.y for frame in frames))


def _warning_counts(fs: Flowsheet) -> Counter[str]:
    """Count completed-drawing warnings by code.

    Parameters
    ----------
    fs : Flowsheet
        Routed drawing to inspect.

    Returns
    -------
    Counter[str]
        Number of each warning reported by validation.
    """
    return Counter(issue.code for issue in fs.validate() if issue.severity == "warning")


def _acceptable(reference: Flowsheet, candidate: Flowsheet, *,
                preserve_size: bool = False) -> bool:
    """Require a routed proposal to improve without a measured regression.

    Parameters
    ----------
    reference, candidate : Flowsheet
        Completed drawings with the same authored model.
    preserve_size : bool, optional
        Keep both dimensions within the established drawing's extent.

    Returns
    -------
    bool
        Whether the proposal is safe and materially better.
    """
    from pandid.layout.quality import admissible, improves, measure_final

    before, after = measure_final(reference), measure_final(candidate)
    old_warnings, new_warnings = _warning_counts(reference), _warning_counts(candidate)
    old_size, new_size = _frame_size(reference), _frame_size(candidate)
    return (
        admissible(before, after, preserve_crossing_pairs=False)
        and after.bends <= before.bends
        and after.excess_bends <= before.excess_bends
        and after.length <= before.length + 1e-6
        and after.area <= before.area + 1e-6
        and all(count <= old_warnings[code] for code, count in new_warnings.items())
        and (not preserve_size or all(new <= old + 1e-6
                                      for old, new in zip(old_size, new_size)))
        and improves(before, after)
    )


def _rank(fs: Flowsheet) -> tuple:
    """Order admissible routed layouts by visible drawing costs.

    Parameters
    ----------
    fs : Flowsheet
        Completed drawing to rank.

    Returns
    -------
    tuple
        Lexicographic defect, warning, crossing, bend, length, and size costs.
    """
    from pandid.layout.quality import measure_final

    quality = measure_final(fs)
    return (quality.hard, len(quality.hard_conflicts),
            sum(_warning_counts(fs).values()), quality.crossings, quality.bends,
            quality.excess_bends, quality.length, quality.area, *_frame_size(fs))


def keep_if_better(fs: Flowsheet) -> bool:
    """Keep the best routed corridor trial that improves the old layout.

    Parameters
    ----------
    fs : Flowsheet
        Completed default drawing from equipment-first placement.

    Returns
    -------
    bool
        Whether an equipment-first drawing passed the per-sheet quality gate.
    """
    import copy

    from pandid.layout import default_layout_engine
    from pandid.layout.trials import _publish_candidate

    baseline = copy.deepcopy(fs)
    default_layout_engine.layout(baseline, use_coarse=False)
    baseline._layout_stale = False
    baseline._route_stale = True
    baseline._refinement_attempted = False
    baseline.route()
    absolute_pin = any(unit.pin_ is not None
                       and (unit.pin_.x is not None or unit.pin_.y is not None)
                       for unit in process_units(fs))
    if absolute_pin:
        accepted = _acceptable(baseline, fs)
        if not accepted:
            _publish_candidate(fs, baseline)
        fs._coarse_layout_candidate = False
        return accepted
    conservative = _routed_reservation(fs, "conservative")
    old = (conservative if conservative is not None
           and _acceptable(baseline, conservative) else baseline)
    compact = _routed_reservation(fs, "compact")
    winner = old
    for trial in (compact, fs):
        if (trial is not None and _acceptable(old, trial, preserve_size=True)
                and _rank(trial) < _rank(winner)):
            winner = trial
    if winner is not fs:
        _publish_candidate(fs, winner)
    fs._coarse_layout_candidate = False
    return winner is not baseline
