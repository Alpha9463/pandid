"""Place equipment before expanding stream-relative valve stations."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    from pandid.stations import StationAssembly
    from pandid.streams import Stream
    from pandid.units import Unit


def _groups(fs: Flowsheet) -> list[tuple[Stream, list[StationAssembly]]] | None:
    """Collect complete, position-free stations by logical host run.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with registered station assemblies.

    Returns
    -------
    list[tuple[Stream, list[StationAssembly]]] or None
        Eligible groups, or ``None`` when the full solver is required.
    """
    if not fs._station_assemblies:
        return None
    by_root: dict[int, tuple[Stream, list[StationAssembly]]] = {}
    for assembly in fs._station_assemblies:
        if assembly.run is None or assembly.run._logical_to is None:
            return None
        if any(unit.pin_ is not None for unit in assembly.station.members):
            return None
        key = id(assembly.run)
        if key not in by_root:
            by_root[key] = (assembly.run, [])
        by_root[key][1].append(assembly)
    members = {unit for assembly in fs._station_assemblies
               for unit in assembly.station.members}
    for root, _ in by_root.values():
        assert root._logical_to is not None
        source = root.source.owner
        dest = root._logical_to.owner
        if (source is None or dest is None or source in members or dest in members
                or source is dest or root.is_recycle):
            return None
    if any(stream.is_recycle or (stream.route is not None and stream.route.manual)
           for stream in process_streams(fs)
           if stream.source.owner in members or stream.dest.owner in members):
        return None
    return list(by_root.values())


def _claims(fs: Flowsheet, roots: list[Stream],
            retained: list[Unit]) -> list[claims_mod.Claim]:
    """Replace each attachment chain's internal claims with endpoint claims.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose material graph is inspected.
    roots : list[Stream]
        Logical host runs with contracted attachments.
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
        destination = root._logical_to
        assert destination is not None and destination.stream is not None
        first, last = root, destination.stream
        source_unit, dest_unit = root.source.owner, destination.owner
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


def _equipment_frames(fs: Flowsheet, widths: list[tuple[Stream, float]],
                      members: set[Unit]) -> bool:
    """Resolve equipment positions while reserving attachment footprints.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose slots have been seeded from authored pins.
    widths : list[tuple[Stream, float]]
        Host runs and their required horizontal attachment space.
    members : set[Unit]
        Attachment units excluded from the equipment solve.

    Returns
    -------
    bool
        Whether each host has distinct equipment grid columns.
    """
    roots = [root for root, _ in widths]
    retained = [unit for unit in process_units(fs) if unit not in members]
    assign_positions(fs, units=retained, claims=_claims(fs, roots, retained))
    gap: dict[int, float] = {}
    for root, width in widths:
        destination = root._logical_to
        assert destination is not None
        source_unit, dest_unit = root.source.owner, destination.owner
        assert source_unit is not None and dest_unit is not None
        source_col, dest_col = slot(source_unit).col, slot(dest_unit).col
        assert source_col is not None and dest_col is not None
        span = abs(dest_col - source_col)
        if span == 0:
            return False
        column = min(source_col, dest_col)
        clearance = _end_clearance(source_unit, root.source.name,
                                   dest_unit, destination.name, source_col < dest_col)
        need = max(0.0, width + clearance - span * COL_GAP)
        gap[column] = max(gap.get(column, 0.0), need)
    links = []
    for root in roots:
        destination = root._logical_to
        assert destination is not None
        source_unit, dest_unit = root.source.owner, destination.owner
        assert source_unit is not None and dest_unit is not None
        links.append((source_unit, dest_unit, claims_mod.LINE))
    assign_coordinates(fs, units=retained, extra_gap=gap, links=links)
    for unit in members:
        placed = slot(unit)
        unit.frame = Frame(x=0.0, y=0.0, w=placed.w, h=placed.h,
                           orientation=placed.orientation, mirrored=placed.mirrored,
                           mirror_y=placed.mirror_y)
    return True


def place_equipment_first(fs: Flowsheet) -> bool:
    """Place eligible station assemblies after their external equipment.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose slots have been seeded from authored pins.

    Returns
    -------
    bool
        Whether all station assemblies received complete frames.
    """
    groups = _groups(fs)
    if groups is None:
        return False
    members = {unit for assembly in fs._station_assemblies
               for unit in assembly.station.members}
    if not _equipment_frames(fs, [(root, _station_width(assemblies))
                                  for root, assemblies in groups], members):
        return False
    return place_stations(fs) == len(fs._station_assemblies)


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
    if fs._station_assemblies:
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


def place_inline_equipment_first(fs: Flowsheet) -> bool:
    """Place opted-in inline chains after their external equipment.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose slots have been seeded from authored pins.

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
    widths = [(root, sum(resolve_size(unit)[0] for unit in chain)
               + 8.0 * (len(chain) + 1)) for root, chain in groups]
    if not _equipment_frames(fs, widths, members):
        return False
    return members <= place_inline(fs)


def keep_if_better(fs: Flowsheet) -> bool:
    """Keep a routed coarse layout only if it improves the legacy result.

    Parameters
    ----------
    fs : Flowsheet
        Completed default drawing from equipment-first placement.

    Returns
    -------
    bool
        Whether the coarse drawing passed the per-sheet quality gate.
    """
    import copy

    from pandid.layout import default_layout_engine
    from pandid.layout.quality import admissible, improves, measure_final
    from pandid.layout.trials import _publish_candidate

    candidate_quality = measure_final(fs)
    baseline = copy.deepcopy(fs)
    default_layout_engine.layout(baseline, use_coarse=False)
    baseline._layout_stale = False
    baseline._route_stale = True
    baseline._refinement_attempted = False
    baseline.route()
    baseline_quality = measure_final(baseline)
    accepted = (
        admissible(baseline_quality, candidate_quality)
        and candidate_quality.bends <= baseline_quality.bends
        and candidate_quality.excess_bends <= baseline_quality.excess_bends
        and candidate_quality.length <= baseline_quality.length + 1e-6
        and candidate_quality.area <= baseline_quality.area + 1e-6
        and improves(baseline_quality, candidate_quality)
    )
    if not accepted:
        _publish_candidate(fs, baseline)
    fs._coarse_layout_candidate = False
    return accepted
