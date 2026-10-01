"""Separate routed streams that share a track.

Runs of different streams that lie on nearly the same track and overlap
along their length are moved onto distinct tracks at least ``spacing``
apart. Runs that end at a nozzle keep their tracks.
"""

from typing import Any, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream

def _compute_offsets(
    streams: "Sequence[Stream]", spacing: float
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]:
    """Compute the offsets :func:`separate_streams` would apply.

    :func:`preview_separated_waypoints` uses this without writing
    waypoints. Writing after every stream would re-settle earlier tracks
    and make the drawing depend on routing order, so only the final
    :func:`separate_streams` call writes.

    Parameters
    ----------
    streams : Sequence[Stream]
        Routed streams to separate.
    spacing : float
        Minimum distance between separated tracks.

    Returns
    -------
    tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]
        Vertical offsets for horizontal segments and horizontal offsets for
        vertical segments, keyed by ``(id(stream), segment index)``.
    """
    # Collect runs: maximal chains of consecutive segments on one axis.
    # Collinear segments are one drawn line and must move together. Tracks
    # keep their raw coordinate so the offset lands exactly on its slot.
    h_runs: list[dict[str, Any]] = []
    v_runs: list[dict[str, Any]] = []

    h_offsets: dict[tuple[int, int], float] = {}
    v_offsets: dict[tuple[int, int], float] = {}

    for s in streams:
        if not s.route or not s.route.waypoints:
            continue

        pts = s.route.waypoints
        n_segs = len(pts) - 1
        # The run the previous segment extended, and which axis it lies on.
        open_run: dict[str, Any] | None = None
        open_axis: str | None = None

        for i in range(n_segs):
            p1, p2 = pts[i], pts[i+1]
            is_fixed = (i == 0) or (i == n_segs - 1)
            flat_x = abs(p1[0] - p2[0]) < 0.1
            flat_y = abs(p1[1] - p2[1]) < 0.1

            if flat_x and flat_y:
                # A zero-length segment joins the run it interrupts.
                if open_run is not None:
                    open_run["is_fixed"] = open_run["is_fixed"] or is_fixed
                    open_run["seg_idxs"].append(i)
                    offsets = h_offsets if open_axis == "h" else v_offsets
                    offsets[(id(s), i)] = 0.0
                continue

            if flat_y:  # Horizontal
                axis, runs, offsets = "h", h_runs, h_offsets
                track = p1[1]
                lo, hi = min(p1[0], p2[0]), max(p1[0], p2[0])
            elif flat_x:  # Vertical
                axis, runs, offsets = "v", v_runs, v_offsets
                track = p1[0]
                lo, hi = min(p1[1], p2[1]), max(p1[1], p2[1])
            else:
                open_run, open_axis = None, None
                continue

            if open_run is not None and open_axis == axis:
                open_run["min_val"] = min(open_run["min_val"], lo)
                open_run["max_val"] = max(open_run["max_val"], hi)
                open_run["is_fixed"] = open_run["is_fixed"] or is_fixed
                open_run["seg_idxs"].append(i)
            else:
                open_run = {
                    "stream": id(s),
                    "seg_idxs": [i],
                    "track": track,
                    "min_val": lo,
                    "max_val": hi,
                    "is_fixed": is_fixed,
                }
                open_axis = axis
                runs.append(open_run)
            offsets[(id(s), i)] = 0.0

    def resolve_track(runs, offsets_dict):
        """Assign target tracks to one cluster of nearby runs.

        Runs that overlap along their length form a component. In a
        component with more than one stream, runs that end at a nozzle keep
        their track, a free run of a stream that already has a nozzle run
        joins the nearer of that stream's tracks, and every other run takes
        the nearest free slot on a ``spacing`` grid around the component's
        mean track.

        Parameters
        ----------
        runs : list[dict]
            Runs on one axis with nearby tracks.
        offsets_dict : dict[tuple[int, int], float]
            Segment offsets, updated in place.
        """
        runs.sort(key=lambda r: r["min_val"])

        components = []
        current_comp = []
        current_max = -float('inf')

        for run in runs:
            # Overlap condition
            if run["min_val"] <= current_max + 0.1:
                current_comp.append(run)
                current_max = max(current_max, run["max_val"])
            else:
                if current_comp:
                    components.append(current_comp)
                current_comp = [run]
                current_max = run["max_val"]

        if current_comp:
            components.append(current_comp)


        for comp in components:
            if len(comp) <= 1:
                continue

            if len({run["stream"] for run in comp}) <= 1:
                continue  # one stream's own runs, nothing to separate

            # Assign absolute target tracks rather than per-run deltas, so
            # runs cannot end closer than they began. Each nozzle run keeps
            # its own track, so a stream's jog between two nozzles survives.
            fixed = [run for run in comp if run["is_fixed"]]
            pool = fixed or comp
            base = sum(run["track"] for run in pool) / len(pool)

            occupied = [run["track"] for run in fixed]
            nozzles: dict[int, list[float]] = {}
            for run in fixed:
                run["target"] = run["track"]
                nozzles.setdefault(run["stream"], []).append(run["track"])

            for run in comp:
                if run["is_fixed"]:
                    continue
                own = nozzles.get(run["stream"])
                if own:
                    # Join this stream's nearer nozzle track rather than
                    # taking a slot, which would add two bends.
                    track = run["track"]
                    run["target"] = min(own, key=lambda t: (abs(t - track), t))
                    continue
                k = 0
                while "target" not in run:
                    for cand in ((base,) if k == 0 else (base + k * spacing, base - k * spacing)):
                        # The epsilon absorbs float error in ``base + k * spacing``.
                        if all(abs(cand - o) >= spacing - 1e-9 for o in occupied):
                            run["target"] = cand
                            occupied.append(cand)
                            break
                    k += 1

            for run in comp:
                offset = run["target"] - run["track"]
                for seg_idx in run["seg_idxs"]:
                    offsets_dict[(run["stream"], seg_idx)] = offset

    # Cluster tracks by single linkage within ``spacing``: runs a few pixels
    # apart read as one doubled line. resolve_track then separates only runs
    # that also overlap along their length.
    def group_by_track(runs, tolerance):
        """Cluster runs whose tracks chain within a tolerance.

        Parameters
        ----------
        runs : list[dict]
            Runs on one axis.
        tolerance : float
            Largest gap between consecutive tracks in one cluster.

        Returns
        -------
        list[list[dict]]
            Clusters in track order.
        """
        groups: list[list] = []
        current: list = []
        prev_track = None
        for run in sorted(runs, key=lambda r: r["track"]):
            if current and run["track"] - prev_track <= tolerance:
                current.append(run)
            else:
                if current:
                    groups.append(current)
                current = [run]
            prev_track = run["track"]
        if current:
            groups.append(current)
        return groups

    # A wider window would pull legible runs together onto the spacing grid.
    window = spacing
    for group in group_by_track(h_runs, window):
        resolve_track(group, h_offsets)

    for group in group_by_track(v_runs, window):
        resolve_track(group, v_offsets)

    return h_offsets, v_offsets


def _apply_offsets(
    streams: "Sequence[Stream]",
    h_offsets: dict[tuple[int, int], float],
    v_offsets: dict[tuple[int, int], float],
) -> dict[int, list[tuple[float, float]]]:
    """Return every stream's waypoints with the offsets applied.

    Parameters
    ----------
    streams : Sequence[Stream]
        Routed streams.
    h_offsets, v_offsets : dict[tuple[int, int], float]
        Offsets from :func:`_compute_offsets`.

    Returns
    -------
    dict[int, list[tuple[float, float]]]
        New waypoints keyed by ``id(stream)``. A waypoint takes its own
        segment's offset in preference to the previous segment's.
    """
    result: dict[int, list[tuple[float, float]]] = {}
    for s in streams:
        if not s.route or not s.route.waypoints:
            continue

        pts = s.route.waypoints
        n_segs = len(pts) - 1
        new_pts = []

        for i, pt in enumerate(pts):
            dx = 0.0
            dy = 0.0

            if i > 0:
                seg_idx = i - 1
                if (id(s), seg_idx) in h_offsets:
                    dy = h_offsets[(id(s), seg_idx)]
                if (id(s), seg_idx) in v_offsets:
                    dx = v_offsets[(id(s), seg_idx)]

            # A waypoint's own segment wins over the one before it.
            if i < n_segs:
                seg_idx = i
                if (id(s), seg_idx) in h_offsets:
                    dy = h_offsets[(id(s), seg_idx)]
                if (id(s), seg_idx) in v_offsets:
                    dx = v_offsets[(id(s), seg_idx)]

            new_pts.append((pt[0] + dx, pt[1] + dy))

        result[id(s)] = new_pts
    return result


def separate_streams(fs: "Flowsheet", spacing: float = 6.0) -> None:
    """Separate overlapping parallel runs and write the new waypoints.

    Called once per routing pass, on the complete set of streams.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet; route waypoints are updated in place.
    spacing : float, default=6.0
        Minimum distance between separated tracks.
    """
    h_offsets, v_offsets = _compute_offsets(fs.streams, spacing)
    new_waypoints = _apply_offsets(fs.streams, h_offsets, v_offsets)
    for s in fs.streams:
        if id(s) in new_waypoints:
            s.route.waypoints = new_waypoints[id(s)]  # type: ignore[union-attr]


def preview_separated_waypoints(
    streams: "Sequence[Stream]", spacing: float = 6.0
) -> dict[int, list[tuple[float, float]]]:
    """Return where :func:`separate_streams` would put each stream's waypoints.

    ``DefaultRouter.route()`` prices crossings against this preview of the
    streams routed so far, without writing waypoints. A later stream can
    still move an earlier stream's track, so a search can underprice a
    crossing in the finished drawing (#509).

    Parameters
    ----------
    streams : Sequence[Stream]
        Streams routed so far.
    spacing : float, default=6.0
        Minimum distance between separated tracks.

    Returns
    -------
    dict[int, list[tuple[float, float]]]
        Separated waypoints keyed by ``id(stream)``.
    """
    h_offsets, v_offsets = _compute_offsets(streams, spacing)
    return _apply_offsets(streams, h_offsets, v_offsets)
